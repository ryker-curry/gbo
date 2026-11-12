"""
GBO -- VALD import (Nov 2026, Ryker: "put any testing we have done on the
website").

Reads a VALD Hub CSV export -- ForceDecks (force plate) or ForceFrame
(shoulder / hip strength) -- and stores each test in vald_tests. Display
only: nothing here feeds Assessments, percentiles or the Bucket System.

File shapes (from the real 11/11/2026 exports):
  ForceDecks -- one row per test: Name, ExternalId, Test Type, Date, Time,
      BW [KG], Reps, Tags, then that test type's metrics ("Peak Vertical
      Force [N] ", "RFD - 100ms [N/s] ", asymmetry like "20 R", ...).
  ForceFrame -- one row per direction: Name, Date, Time, Device, Mode, Test,
      Direction (Pull / Squeeze), Position, then L/R columns (L Max Force (N),
      R Max Force (N), ...). An athlete tested one arm at a time shows up as
      two rows per direction with the other side's reps = 0.

ForceFrame directions (Ryker, Nov 11 2026): shoulder IR/ER -- Squeeze = IR,
Pull = ER. Hip -- Squeeze = adduction, Pull = abduction (VALD's standard
meaning of the two directions).

One vald_tests row per player per test:
  ForceDecks -- per (test type, date, time).
  ForceFrame -- per (test, position, date): Pull and Squeeze rows and both
      arms are merged, a side with 0 reps is treated as not tested, and if
      a side was tested twice the higher max force wins.
Re-importing the same file updates those rows instead of duplicating them.

Name matching: VALD names are often misspelled. Exact roster match or a
saved link (vald_name_links) -> matched. Otherwise GBO suggests the
closest roster name and staff confirm or pick; the confirmed pick is saved
so that spelling matches on its own next time.
"""

import csv
import difflib
import io
import re
from datetime import datetime

from models import Player, ValdImport, ValdTest, ValdNameLink


class ValdImportError(Exception):
    pass


FORCEDECKS = "ForceDecks"
FORCEFRAME = "ForceFrame"

_DIRECTION_LABELS = {
    # test name (lowercased, startswith) -> {direction: label}
    "shoulder": {"squeeze": "IR", "pull": "ER"},
    "hip": {"squeeze": "AD", "pull": "AB"},
}

# ForceFrame per-side metrics kept for each direction (VALD column -> key).
_FF_SIDE_METRICS = {
    "Max Force (N)": "max_force",
    "Avg Force (N)": "avg_force",
    "Max Impulse (Ns)": "max_impulse",
    "Max RFD (N/s)": "max_rfd",
    "Min Time To Peak Force (s)": "time_to_peak",
    "Max Force Per kg (N/kg)": "max_force_per_kg",
    "Reps": "reps",
}


# ---------------------------------------------------------------- helpers

def normalize_name(name):
    s = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    return re.sub(r"\s+", " ", s).strip()


def clean_header(h):
    return re.sub(r"\s+", " ", (h or "").replace("﻿", "")).strip()


def _num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_asym(v):
    """'20 R' -> (20.0, 'R'); '7.2 L' -> (7.2, 'L'); '' -> (None, None)."""
    m = re.match(r"^\s*(-?[\d.]+)\s*([LR])?\s*$", str(v or ""))
    if not m:
        return None, None
    return float(m.group(1)), m.group(2)


def _parse_dt(d, t):
    d = (d or "").strip()
    t = (t or "").strip()
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %I:%M %p"):
        try:
            return datetime.strptime(f"{d} {t}".strip(), fmt)
        except ValueError:
            continue
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(d, fmt)
        except ValueError:
            continue
    return None


def _read_rows(data):
    if isinstance(data, bytes):
        text = data.decode("utf-8-sig", errors="replace")
    else:
        text = data.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(c.strip() for c in r)]
    if not rows:
        raise ValdImportError("This file is empty.")
    headers = [clean_header(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        out.append({headers[i]: (r[i] if i < len(r) else "") for i in range(len(headers))})
    return headers, out


def detect_system(headers):
    hs = set(headers)
    if {"Name", "Direction", "L Max Force (N)", "R Max Force (N)"} <= hs:
        return FORCEFRAME
    if {"Name", "Test Type", "Date"} <= hs:
        return FORCEDECKS
    raise ValdImportError(
        "This doesn't look like a VALD ForceDecks or ForceFrame export (missing the Name / Test Type / "
        "Direction columns). Export the results CSV from VALD Hub and upload that file.")


def direction_label(test, direction):
    t = (test or "").lower()
    d = (direction or "").strip().lower()
    for prefix, labels in _DIRECTION_LABELS.items():
        if t.startswith(prefix) and d in labels:
            return labels[d]
    return (direction or "").strip() or "Force"


# ---------------------------------------------------------------- parsing

def _parse_forcedecks(rows):
    tests = []
    skip = {"Name", "ExternalId", "Test Type", "Date", "Time", "BW [KG]", "Reps", "Tags"}
    for r in rows:
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        tested_at = _parse_dt(r.get("Date"), r.get("Time"))
        if tested_at is None:
            continue
        test_type = (r.get("Test Type") or "").strip() or "Test"
        metrics, asym = {}, {}
        for k, v in r.items():
            if k in skip or not k:
                continue
            if "(Asym)" in k or "Asym" in k.split("[")[0]:
                val, side = parse_asym(v)
                if val is not None:
                    asym[k] = {"value": val, "side": side}
                continue
            n = _num(v)
            if n is not None:
                metrics[k] = n
        tests.append({
            "vald_name": name,
            "system": FORCEDECKS,
            "test_type": test_type,
            "position": None,
            "tested_at": tested_at,
            "test_key": f"{test_type}|{tested_at:%Y-%m-%d %H:%M}",
            "body_weight_kg": _num(r.get("BW [KG]")),
            "reps": int(_num(r.get("Reps")) or 0) or None,
            "metrics": {"values": metrics, "asym": asym, "tags": (r.get("Tags") or "").strip() or None},
        })
    return tests


def _parse_forceframe(rows):
    grouped = {}
    for r in rows:
        name = (r.get("Name") or "").strip()
        if not name:
            continue
        tested_at = _parse_dt(r.get("Date"), r.get("Time"))
        if tested_at is None:
            continue
        test = (r.get("Test") or "").strip() or "ForceFrame"
        position = (r.get("Position") or "").strip() or None
        key = (normalize_name(name), test, position or "", tested_at.date())
        g = grouped.setdefault(key, {
            "vald_name": name, "system": FORCEFRAME, "test_type": test, "position": position,
            "tested_at": tested_at, "body_weight_kg": None, "reps": None,
            "test_key": f"{test}|{position or ''}|{tested_at:%Y-%m-%d}",
            "metrics": {"directions": {}, "device": (r.get("Device") or "").strip() or None,
                        "mode": (r.get("Mode") or "").strip() or None},
        })
        g["tested_at"] = min(g["tested_at"], tested_at)
        label = direction_label(test, r.get("Direction"))
        d = g["metrics"]["directions"].setdefault(label, {"L": None, "R": None, "raw_direction": (r.get("Direction") or "").strip()})
        for side in ("L", "R"):
            reps = _num(r.get(f"{side} Reps"))
            force = _num(r.get(f"{side} Max Force (N)"))
            if not reps or not force:
                continue  # this side wasn't tested in this row
            vals = {k: _num(r.get(f"{side} {col}")) for col, k in _FF_SIDE_METRICS.items()}
            prev = d[side]
            if prev is None or (vals.get("max_force") or 0) > (prev.get("max_force") or 0):
                d[side] = vals
    tests = list(grouped.values())
    # drop a direction with neither side tested
    for t in tests:
        t["metrics"]["directions"] = {k: v for k, v in t["metrics"]["directions"].items() if v["L"] or v["R"]}
    return [t for t in tests if t["metrics"]["directions"]]


def parse_file(data):
    """-> (system, tests). tests are plain dicts, not yet tied to a player."""
    headers, rows = _read_rows(data)
    system = detect_system(headers)
    tests = _parse_forcedecks(rows) if system == FORCEDECKS else _parse_forceframe(rows)
    if not tests:
        raise ValdImportError("No tests with a name and date were found in this file.")
    return system, tests


# ---------------------------------------------------------------- matching

def _suggest(norm, roster):
    """Closest roster player for a VALD name that didn't match exactly."""
    best, best_ratio = None, 0.0
    for p in roster:
        full = normalize_name(f"{p.first_name} {p.last_name}")
        ratio = difflib.SequenceMatcher(None, norm, full).ratio()
        if ratio > best_ratio:
            best, best_ratio = p, ratio
    if best is not None and best_ratio >= 0.85:
        return best
    # Same last name, same first initial, only one such player (e.g. "CJ Freeland").
    parts = norm.split(" ")
    if len(parts) >= 2:
        last, initial = parts[-1], parts[0][:1]
        same = [p for p in roster if normalize_name(p.last_name) == last
                and normalize_name(p.first_name)[:1] == initial]
        if len(same) == 1:
            return same[0]
    return None


def match_names(db, names):
    """names: iterable of VALD names. -> {vald_name: {"player_id", "how", "suggested_id"}}.
    how: "exact" | "saved" | "suggested" | "none"."""
    roster = db.query(Player).all()
    active = [p for p in roster if p.active]
    by_full = {}
    for p in roster:
        by_full.setdefault(normalize_name(f"{p.first_name} {p.last_name}"), []).append(p)
    links = {l.vald_name_key: l.player_id for l in db.query(ValdNameLink).all()}
    out = {}
    for name in names:
        norm = normalize_name(name)
        if norm in links:
            out[name] = {"player_id": links[norm], "how": "saved", "suggested_id": None}
            continue
        exact = by_full.get(norm) or []
        exact_active = [p for p in exact if p.active] or exact
        if len(exact_active) == 1:
            out[name] = {"player_id": exact_active[0].player_id, "how": "exact", "suggested_id": None}
            continue
        s = _suggest(norm, active) or _suggest(norm, roster)
        out[name] = {"player_id": None, "how": "suggested" if s else "none",
                     "suggested_id": s.player_id if s else None}
    return out


def preview(db, data):
    system, tests = parse_file(data)
    names = sorted({t["vald_name"] for t in tests}, key=lambda n: normalize_name(n))
    matches = match_names(db, names)
    dates = sorted({t["tested_at"].date() for t in tests})
    types = sorted({t["test_type"] for t in tests})
    return {"system": system, "tests": tests, "names": names, "matches": matches,
            "dates": dates, "test_types": types}


# ---------------------------------------------------------------- writing

def commit(db, data, file_name, picks, user_id=None):
    """picks: {vald_name: player_id or None (skip)} -- the final choice for
    every name in the file. Saves a link for any name that wasn't an exact
    roster match. -> {"created", "updated", "skipped_names", "import_id"}."""
    plan = preview(db, data)
    imp = ValdImport(system=plan["system"], file_name=(file_name or "")[:200],
                     first_test_date=plan["dates"][0], last_test_date=plan["dates"][-1],
                     imported_by_user_id=user_id)
    db.add(imp)
    db.flush()

    links = {l.vald_name_key: l for l in db.query(ValdNameLink).all()}
    for name in plan["names"]:
        pid = picks.get(name)
        if pid is None or plan["matches"][name]["how"] == "exact":
            continue
        key = normalize_name(name)
        if key in links:
            links[key].player_id = pid
            links[key].vald_name = name
        else:
            l = ValdNameLink(vald_name_key=key, vald_name=name, player_id=pid, created_by_user_id=user_id)
            db.add(l)
            links[key] = l

    created = updated = 0
    skipped = sorted({n for n in plan["names"] if picks.get(n) is None})
    for t in plan["tests"]:
        pid = picks.get(t["vald_name"])
        if pid is None:
            continue
        row = db.query(ValdTest).filter(ValdTest.player_id == pid, ValdTest.system == t["system"],
                                        ValdTest.test_key == t["test_key"]).first()
        if row is None:
            row = ValdTest(player_id=pid, system=t["system"], test_key=t["test_key"])
            db.add(row)
            created += 1
        else:
            updated += 1
        row.vald_import_id = imp.vald_import_id
        row.test_type = t["test_type"]
        row.position = t["position"]
        row.tested_at = t["tested_at"]
        row.test_date = t["tested_at"].date()
        row.body_weight_kg = t["body_weight_kg"]
        row.reps = t["reps"]
        row.metrics = t["metrics"]
        row.vald_name = t["vald_name"]
    imp.test_count = created + updated
    db.commit()
    return {"created": created, "updated": updated, "skipped_names": skipped, "import_id": imp.vald_import_id}
