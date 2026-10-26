"""
GBO -- Testing-workbook importer (Oct 2026, Ryker: rebuild the assessment
importer around the study workbook -- STUDY_BBF26 DATA.xlsx, one tab per
test, one row per player). Column map: study_workbook_spec.py.

Two steps, same as the other importers:
  build_plan(db, file_bytes, test_date, overrides)  -- reads every tab,
      matches names to the roster, converts units, resolves throw / glove /
      drive / plant sides from the player's throwing hand, and lists
      exactly what would be written. Writes NOTHING.
  commit_plan(db, plan, user_id)                     -- writes it.

Rules (Ryker's calls, Oct 2026):
  - Every column is imported; asymmetry %, ratio and best-of-both-legs
    columns are skipped (GBO calculates them). The two ER:IR ratio tests
    the app already uses are filled from the imported peak forces.
  - Units are converted to GBO's (study_workbook_spec.CONV).
  - A cell the sheet flags is skipped and its note kept: the IMTP notes
    column ("ISOT (WRONG)", "DID BELT SQUAT", ...) skips that player's
    IMTP values; a text cell where a number belongs ("355 BELTSQUAT",
    "22 R") skips that one value. Notes go on that player's Assessment
    for the date (Assessment.notes) so the Research Project checklist can
    show why a value is missing.
  - FB VELO&SPIN -> models.ResearchFBOutcome (one row per player and
    season; re-importing updates it).
  - Names are matched to the roster with a forgiving match (case, extra
    spaces, small spelling differences like Kappelmann / Kappellmann);
    anything that isn't an exact match is shown for the coach to confirm
    or change before importing (overrides).
  - Never overwrites: a test already recorded for that player on that
    date is skipped and reported, same as the single-category importer.
"""

import difflib
import io
from collections import defaultdict
from datetime import datetime

import openpyxl

import study_workbook_spec as spec
from models import (Assessment, AssessmentResult, AssessmentTestType, Player, ResearchFBOutcome)

ER_IR_RATIO_TESTS = {
    "Shoulder Strength: Throwing Arm ER:IR Ratio": ("Shoulder Strength: Throwing Arm ER Peak Force",
                                                    "Shoulder Strength: Throwing Arm IR Peak Force"),
    "Shoulder Strength: Non-Throwing Arm ER:IR Ratio": ("Shoulder Strength: Non-Throwing Arm ER Peak Force",
                                                        "Shoulder Strength: Non-Throwing Arm IR Peak Force"),
}
CLOSE_FULL = 0.85     # whole-name similarity that counts as the same person
CLOSE_FIRST = 0.6     # first-name similarity when the last name matches exactly


class WorkbookError(Exception):
    pass


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _num(v):
    """(number or None, leftover text or None)."""
    if v is None:
        return None, None
    if isinstance(v, bool):
        return None, str(v)
    if isinstance(v, (int, float)):
        return float(v), None
    s = str(v).replace("\xa0", " ").strip()
    if s in ("", "-", "—"):
        return None, None
    try:
        return float(s), None
    except ValueError:
        return None, s


def _hand(v):
    s = spec.norm(v).upper()
    if s.startswith("R"):
        return "R"
    if s.startswith("L"):
        return "L"
    return None


def read_tabs(file_bytes):
    """{tab: {"cols": {col_index: Col}, "unknown": [header], "missing": [header],
    "rows": [{"first", "last", "cells": {col_index: raw}, "flag": text or None}]}}
    plus "_unknown_tabs"."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        raise WorkbookError(f"This file couldn't be read as an Excel workbook ({e}).")
    by_norm = {spec.norm(t): t for t in spec.TABS}
    out = {"_unknown_tabs": []}
    for ws in wb.worksheets:
        tab = by_norm.get(spec.norm(ws.title))
        if tab is None:
            out["_unknown_tabs"].append(ws.title)
            continue
        t = spec.TABS[tab]
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) <= t["header_rows"]:
            continue
        head = rows[t["header_rows"] - 1]
        groups = [None] * len(head)
        if t["header_rows"] == 2:
            g = None
            for i, v in enumerate(rows[0][:len(head)] if rows[0] else []):
                if v not in (None, ""):
                    g = spec.norm(v)
                groups[i] = g
        want = {}
        for c in t["cols"]:
            want.setdefault((spec.norm(c.group) if c.group else None, spec.norm(c.header)), c)
        cols, unknown, seen = {}, [], set()
        first_data = t["name_col"] + 2
        for i, h in enumerate(head):
            if i < first_data:
                continue
            key = (groups[i] if t["header_rows"] == 2 else None, spec.norm(h))
            c = want.get(key) or want.get((None, spec.norm(h)))
            if c is None and spec.norm(h) == "":
                c = want.get((None, ""))   # unnamed note column
            if c is None:
                if spec.norm(h):
                    unknown.append(f"{groups[i].upper() + ' ' if groups[i] else ''}{str(h).strip()}")
                continue
            cols[i] = c
            seen.add((spec.norm(c.group) if c.group else None, spec.norm(c.header)))
        missing = [c.header for c in t["cols"] if c.header and c.kind not in ("note",)
                   and (spec.norm(c.group) if c.group else None, spec.norm(c.header)) not in seen]
        data = []
        for r in rows[t["header_rows"]:]:
            if not r:
                continue
            nc = t["name_col"]
            first = r[nc] if len(r) > nc else None
            last = r[nc + 1] if len(r) > nc + 1 else None
            if spec.norm(first) == "" and spec.norm(last) == "":
                continue
            flag = None
            if "flag_col" in t and len(r) > t["flag_col"] and spec.norm(r[t["flag_col"]]):
                flag = str(r[t["flag_col"]]).strip()
            data.append({"first": str(first or "").strip(), "last": str(last or "").strip(),
                         "cells": {i: r[i] for i in cols if i < len(r)}, "flag": flag})
        out[tab] = {"cols": cols, "unknown": unknown, "missing": missing, "rows": data}
    return out


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------

def name_key(first, last):
    return f"{spec.norm(first)}|{spec.norm(last)}"


def match_names(players, keys):
    """{key: {"player_id", "how": "exact"/"close"/"none", "score"}} for
    every sheet name key, against the roster."""
    roster = [(p.player_id, spec.norm(p.first_name), spec.norm(p.last_name)) for p in players]
    exact = {f"{f}|{l}": pid for pid, f, l in roster}
    out = {}
    for k in keys:
        if k in exact:
            out[k] = {"player_id": exact[k], "how": "exact", "score": 1.0}
            continue
        f, l = k.split("|", 1)
        best, best_s = None, 0.0
        for pid, rf, rl in roster:
            full = difflib.SequenceMatcher(None, f"{f} {l}", f"{rf} {rl}").ratio()
            first = difflib.SequenceMatcher(None, f, rf).ratio() if l == rl else 0.0
            s = max(full, first if first >= CLOSE_FIRST else 0.0)
            ok = full >= CLOSE_FULL or (l == rl and first >= CLOSE_FIRST)
            if ok and s > best_s:
                best, best_s = pid, s
        out[k] = ({"player_id": best, "how": "close", "score": round(best_s, 2)} if best is not None
                  else {"player_id": None, "how": "none", "score": 0.0})
    return out


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def build_plan(db, file_bytes, test_date, overrides=None):
    """Everything the import would do, written nowhere.
    overrides: {name_key: player_id, or 0 to skip that name}.
    -> {"names": [...], "tabs": {...}, "players": {pid: {...}}, "unknown_tabs", "missing_tabs",
        "test_date", "totals"}"""
    overrides = overrides or {}
    sheets = read_tabs(file_bytes)
    players = db.query(Player).all()
    by_id = {p.player_id: p for p in players}
    keys, display = [], {}
    for tab in spec.TABS:
        for r in sheets.get(tab, {}).get("rows", []):
            k = name_key(r["first"], r["last"])
            if k not in display:
                keys.append(k)
                display[k] = {"first": r["first"], "last": r["last"], "tabs": []}
            display[k]["tabs"].append(tab)
    matches = match_names(players, keys)
    for k, v in overrides.items():
        if k in matches:
            matches[k] = ({"player_id": None, "how": "skipped", "score": 0.0} if not v else
                          {"player_id": int(v), "how": "chosen", "score": 1.0})

    tests = {t.test_name: t for t in db.query(AssessmentTestType).all()}

    # sheet hand per player (HAND / Handedness columns), used when the roster has none
    sheet_hand = {}
    for tab in spec.TABS:
        s = sheets.get(tab)
        if not s:
            continue
        for r in s["rows"]:
            pid = matches[name_key(r["first"], r["last"])]["player_id"]
            for i, c in s["cols"].items():
                if c.kind == "throws" and pid and _hand(r["cells"].get(i)):
                    sheet_hand.setdefault(pid, _hand(r["cells"].get(i)))

    plan_players = {}

    def P(pid):
        if pid not in plan_players:
            p = by_id[pid]
            plan_players[pid] = {"player_id": pid, "name": f"{p.first_name} {p.last_name}",
                                 "throws": p.throws or sheet_hand.get(pid), "set_throws": None if p.throws else sheet_hand.get(pid),
                                 "height_in": None, "values": {}, "notes": [], "fb": None, "skipped": []}
        return plan_players[pid]

    tab_info = {}
    for tab, t in spec.TABS.items():
        s = sheets.get(tab)
        if s is None:
            continue
        info = {"rows": len(s["rows"]), "values": 0, "unknown": s["unknown"], "missing": s["missing"],
                "derived": sorted({c.header for c in s["cols"].values() if c.kind == "derived"}),
                "flags": [], "text": [], "unmatched": 0}
        for r in s["rows"]:
            pid = matches[name_key(r["first"], r["last"])]["player_id"]
            if not pid:
                info["unmatched"] += 1
                continue
            pp = P(pid)
            if r["flag"]:
                info["flags"].append((pp["name"], r["flag"]))
                pp["notes"].append(f"{tab}: '{r['flag']}' -- {tab} values not imported")
                continue
            fb = {}
            for i, c in s["cols"].items():
                raw = r["cells"].get(i)
                if c.kind in ("derived", "throws"):
                    continue
                if c.kind == "note":
                    if spec.norm(raw):
                        if t.get("fb"):
                            fb["note"] = str(raw).strip()
                        else:
                            pp["notes"].append(f"{tab}: {str(raw).strip()}")
                    continue
                val, text = _num(raw)
                if text is not None:
                    info["text"].append((pp["name"], c.header, text))
                    pp["notes"].append(f"{tab} {c.header.strip()}: '{text}' -- not imported")
                    continue
                if val is None:
                    continue
                if c.kind == "height_cm":
                    pp["height_in"] = round(val / 2.54, 2)
                    continue
                if c.kind.startswith("fb:"):
                    fb[c.kind[3:]] = val
                    continue
                name = spec.resolve_test(c.test, pp["throws"])
                if name is None:
                    pp["skipped"].append(f"{c.header.strip()} (throwing hand unknown)")
                    continue
                if name not in tests:
                    pp["skipped"].append(f"{name} (test type not set up -- run migrate_study_workbook)")
                    continue
                v = spec.CONV[c.conv](val) if c.conv else val
                pp["values"][name] = round(v, 3)
                info["values"] += 1
            if fb:
                pp["fb"] = fb
                info["values"] += len([k for k in fb if k != "note"])
        tab_info[tab] = info

    # GBO-calculated ER:IR ratios from the imported peak forces
    for pp in plan_players.values():
        for ratio, (er, ir) in ER_IR_RATIO_TESTS.items():
            if er in pp["values"] and ir in pp["values"] and pp["values"][ir] and ratio in tests:
                pp["values"][ratio] = round(pp["values"][er] / pp["values"][ir], 3)

    # what's already recorded on this date (never overwritten)
    pids = list(plan_players)
    existing = defaultdict(set)
    if pids and test_date is not None:
        for pid, tname in (db.query(Assessment.player_id, AssessmentTestType.test_name)
                           .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
                           .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
                           .filter(Assessment.player_id.in_(pids), Assessment.assessment_date == test_date).all()):
            existing[pid].add(tname)
    n_new = n_dup = 0
    for pid, pp in plan_players.items():
        pp["duplicates"] = sorted(n for n in pp["values"] if n in existing[pid])
        n_dup += len(pp["duplicates"])
        n_new += len(pp["values"]) - len(pp["duplicates"])

    names = [{"key": k, **display[k], **matches[k],
              "player_name": (f"{by_id[matches[k]['player_id']].first_name} {by_id[matches[k]['player_id']].last_name}"
                              if matches[k]["player_id"] else None)} for k in keys]
    return {
        "test_date": test_date, "names": names, "tabs": tab_info, "players": plan_players,
        "unknown_tabs": sheets["_unknown_tabs"], "missing_tabs": [t for t in spec.TABS if t not in sheets],
        "totals": {"new_values": n_new, "already_recorded": n_dup, "players": len(plan_players),
                   "unmatched_names": sum(1 for n in names if not n["player_id"]),
                   "fb_rows": sum(1 for p in plan_players.values() if p["fb"])},
    }


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------

def _season_label(day):
    import bucket_system as bs
    for label, start, end in bs.list_seasons():
        if start is not None and day >= start and (end is None or day < end):
            return label
    return bs.current_season_label()


def commit_plan(db, plan, user_id):
    """Write a build_plan() result. One Assessment per (player, category,
    date) -- reused if it already exists -- one AssessmentResult per new
    value, notes appended, player height / missing throwing hand set,
    fastball outcomes upserted. All or nothing."""
    day = plan["test_date"]
    if day is None:
        raise WorkbookError("Pick the test date first.")
    tests = {t.test_name: t for t in db.query(AssessmentTestType).all()}
    counts = {"assessments_created": 0, "values": 0, "players_updated": 0, "fb_outcomes": 0, "notes": 0}
    season = _season_label(day)
    try:
        for pid, pp in plan["players"].items():
            by_cat = defaultdict(dict)
            for name, v in pp["values"].items():
                if name in pp.get("duplicates", []) or name not in tests:
                    continue
                by_cat[tests[name].category_id][tests[name].test_type_id] = v
            if pp["notes"] and not by_cat:
                # notes only (e.g. a whole IMTP row flagged): keep them on a Force Plate Detail entry
                cat = next((t.category_id for t in tests.values() if t.category.category_name == "Force Plate Detail"),
                           None) if tests else None
                if cat is not None:
                    by_cat[cat] = {}
            first_assessment = None
            for cat_id, vals in by_cat.items():
                a = (db.query(Assessment).filter(Assessment.player_id == pid, Assessment.category_id == cat_id,
                                                 Assessment.assessment_date == day).first())
                if a is None:
                    a = Assessment(player_id=pid, category_id=cat_id, assessment_date=day, entered_by_user_id=user_id)
                    db.add(a)
                    db.flush()
                    counts["assessments_created"] += 1
                have = {r.test_type_id for r in db.query(AssessmentResult.test_type_id)
                        .filter(AssessmentResult.assessment_id == a.assessment_id).all()}
                for ttid, v in vals.items():
                    if ttid in have:
                        continue
                    db.add(AssessmentResult(assessment_id=a.assessment_id, test_type_id=ttid, value=v))
                    counts["values"] += 1
                first_assessment = first_assessment or a
            if pp["notes"] and first_assessment is not None:
                new = [n for n in pp["notes"] if n not in (first_assessment.notes or "")]
                if new:
                    first_assessment.notes = "\n".join(x for x in [first_assessment.notes, *new] if x)
                    counts["notes"] += len(new)
            p = db.query(Player).filter(Player.player_id == pid).first()
            changed = False
            if pp.get("height_in") and p is not None:
                p.height_in = pp["height_in"]
                changed = True
            if pp.get("set_throws") and p is not None and not p.throws:
                p.throws = pp["set_throws"]
                changed = True
            counts["players_updated"] += changed
            if pp.get("fb"):
                fb = pp["fb"]
                row = (db.query(ResearchFBOutcome).filter(ResearchFBOutcome.player_id == pid,
                                                          ResearchFBOutcome.season_label == season).first())
                if row is None:
                    row = ResearchFBOutcome(player_id=pid, season_label=season)
                    db.add(row)
                row.test_date = day
                for k in ("avg_velo", "peak_velo", "avg_spin", "peak_spin"):
                    setattr(row, k, fb.get(k))
                row.n_pitches = int(fb["n_pitches"]) if fb.get("n_pitches") is not None else None
                row.note = fb.get("note")
                row.updated_at = datetime.utcnow()
                counts["fb_outcomes"] += 1
        db.commit()
    except Exception as e:
        db.rollback()
        raise WorkbookError(f"Import failed partway -- nothing was saved ({e}).")
    return counts
