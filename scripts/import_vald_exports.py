"""
Load VALD Hub CSV exports (ForceDecks + ForceFrame) into assessments --
Nov 2026, Ryker: fall 2026 hitters' force plate / ForceFrame testing, straight
from VALD Hub instead of a hand-built workbook.

    python3 -m scripts.import_vald_exports data/vald_import/2026_fall_hitters            # dry run
    python3 -m scripts.import_vald_exports data/vald_import/2026_fall_hitters --apply    # write

Point it at a folder of VALD Hub exports (forcedecks-test-export-*.csv,
forceframe-test-export-*.csv). Every test date becomes its own assessment
(Ryker: keep every session); a value already stored for that player, test
and date is left alone, so re-running is safe.

Choices agreed with Ryker (AskUserQuestion, Nov 2026):
  - VALD is the source, with bad trials removed and listed:
      CMJ: eccentric peak velocity of exactly 0.00 (no real countermovement).
      Hop (HJ): contact time over 500 ms (not a reactive hop).
  - Same test names and unit conversions as the testing workbook
    (study_workbook_spec.py): cm -> in, ForceFrame shoulder N -> lb.
  - ForceFrame Shoulder IR/ER (supine 90/90): Pull = ER, Squeeze = IR.
    Hip AD/AB (supine, ankle): Pull = abduction, Squeeze = adduction. Other
    positions (e.g. Hip AD/AB - 45) are skipped. 0 means "side not tested".
  - L/R -> throwing / glove arm from Player.throws. Legs: for pitchers the
    drive leg is the throwing side (same as the workbook); for hitters
    (is_pitcher False) "Drive Leg" is the BACK leg, from Player.bats -- a
    left-handed hitter's back leg is his left whatever arm he throws with.
    Switch hitters have no single back leg, so they fall back to their
    throwing side. A player without a hand on file gets his two-leg tests only.
  - Shoulder ER:IR ratios are filled from the imported peak forces.
  - IBSQT (isometric belt squat) gets its own test types in Force Plate
    Detail, created on --apply if missing.
  - Same player, test and date twice: the later valid row counts.
"""

import csv
import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import SessionLocal  # noqa: E402
from models import (Player, User, Role, Assessment, AssessmentResult, AssessmentTestType,  # noqa: E402
                    AssessmentCategory)
import study_workbook_spec as spec  # noqa: E402

# VALD name -> GBO "first last" (spelling differences seen in exports)
ALIASES = {
    "conor mcelligot": "conor mcelligott",
    "jaydn mcnealy": "jadyn mcnealy",
    "miles burhrle": "miles burhle",
    "cj freelund": "carter freeland",
    "landon midgett": "landin midgett",
}
HOP_MAX_CONTACT_MS = 500
IBSQT_TESTS = [  # (VALD header, GBO test name, unit)
    ("BW [KG]", "Isometric Belt Squat Bodyweight", "kg"),
    ("Peak Vertical Force [N]", "Isometric Belt Squat Peak Vertical Force", "N"),
    ("Peak Vertical Force / BM [N/kg]", "Isometric Belt Squat Peak Vertical Force / BM", "N/kg"),
    ("RFD - 100ms [N/s]", "Isometric Belt Squat RFD 0-100 ms", "N/s"),
    ("Force at 100ms [N]", "Isometric Belt Squat Force at 100 ms", "N"),
    ("Start Time to 80% Net Peak Force [s]", "Isometric Belt Squat Time to 80% Net Peak Force", "s"),
]
_SL_NAMES = {h: (name, unit, conv) for h, name, unit, conv in spec._SL}


def _key(name):
    k = re.sub(r"\s+", " ", str(name).replace("\xa0", " ")).strip().lower()
    return ALIASES.get(k, k)


def _num(v):
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x


def _date(v):
    return datetime.strptime(v.strip(), "%m/%d/%Y").date()


def _time(v):
    try:
        return datetime.strptime(v.strip(), "%I:%M %p").time()
    except (TypeError, ValueError):
        return None


def _read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return [{spec.norm(k): v for k, v in r.items() if k is not None} for r in rows]


def _sides(throws):
    """(throw/drive side letter, glove/plant side letter)."""
    return ("R", "L") if throws == "R" else ("L", "R")


def leg_side(player):
    """'R' / 'L' side of the drive leg: a hitter's back leg (from bats), a
    pitcher's throwing side. Switch hitters / no bats -> throwing side."""
    if not player.is_pitcher and player.bats in ("R", "L"):
        return player.bats
    return player.throws


def forcedecks_values(r, legs):
    """{test name: value} for one ForceDecks row, plus a reason if the row
    is a bad trial."""
    t = r.get("test type", "").strip().upper()
    out = {}

    def take(cols):
        for c in cols:
            if c.kind != "value":
                continue
            v = _num(r.get(spec.norm(c.header)))
            name = spec.resolve_test(c.test, legs) if c.test else None
            if v is None or name is None:
                continue
            out[name] = spec.CONV[c.conv](v) if c.conv else v

    if t == "CMJ":
        if _num(r.get(spec.norm("Eccentric Peak Velocity [m/s]"))) == 0:
            return {}, "CMJ eccentric velocity 0.00"
        take(spec.CMJ)
    elif t == "HJ":
        ct = _num(r.get(spec.norm("Contact Time [ms]")))
        if ct is not None and ct > HOP_MAX_CONTACT_MS:
            return {}, f"hop contact time {ct:.0f} ms"
        take(spec.HOP)
    elif t == "IMTP":
        take(spec.IMTP)
    elif t == "SLJ":
        v = _num(r.get(spec.norm("BW [KG]")))
        if v is not None:
            out["Single-Leg Jump Bodyweight"] = v
        if legs in ("R", "L"):
            d, p = _sides(legs)
            for h, (name, unit, conv) in _SL_NAMES.items():
                for side, word in ((d, "Drive Leg"), (p, "Plant Leg")):
                    v = _num(r.get(spec.norm(f"{h} ({side})")))
                    if v is not None:
                        out[f"Single-Leg Jump {name} ({word})"] = spec.CONV[conv](v) if conv else v
    elif t == "IBSQT":
        for h, name, _u in IBSQT_TESTS:
            v = _num(r.get(spec.norm(h)))
            if v is not None:
                out[name] = v
    else:
        return {}, f"unknown test type {t!r}"
    return out, None


def forceframe_values(rows, throws, legs):
    """One player's ForceFrame rows for one date -> {test name: value}.
    Arms follow the throwing hand, legs the drive-leg side (leg_side)."""
    best = defaultdict(lambda: None)
    for r in rows:
        test, direction, pos = r.get("test", ""), r.get("direction", ""), r.get("position", "")
        if test == "Shoulder IR/ER" and "Supine (90 Degrees AB)" in pos:
            motion = "ER" if direction == "Pull" else "IR" if direction == "Squeeze" else None
            if throws not in ("R", "L"):
                continue
            d, p = _sides(throws)
            words = {d: "Throwing Arm", p: "Non-Throwing Arm"}
            names = lambda side: {  # noqa: E731
                "max": f"Shoulder Strength: {words[side]} {motion} Peak Force",
                "avg": f"Shoulder {motion} Avg Force ({words[side]})",
                "imp": f"Shoulder {motion} Impulse ({words[side]})"}
            conv = spec.CONV["n_lb"]
        elif test == "Hip AD/AB" and "Supine (Ankle)" in pos:
            motion = "Abduction" if direction == "Pull" else "Adduction" if direction == "Squeeze" else None
            if legs not in ("R", "L"):
                continue
            d, p = _sides(legs)
            words = {d: "Drive Leg", p: "Plant Leg"}
            names = lambda side: {  # noqa: E731
                "max": f"Hip {motion} Force ({words[side]})",
                "avg": f"Hip {motion} Avg Force ({words[side]})",
                "imp": f"Hip {motion} Impulse ({words[side]})"}
            conv = None
        else:
            continue
        if motion is None:
            continue
        for side in ("L", "R"):
            n = names(side)
            for key, col, cv in (("max", f"{side} Max Force (N)", conv), ("avg", f"{side} Avg Force (N)", conv),
                                 ("imp", f"{side} Max Impulse (Ns)", None)):
                v = _num(r.get(spec.norm(col)))
                if not v:  # 0 / blank = that side wasn't tested in this row
                    continue
                v = cv(v) if cv else v
                if best[n[key]] is None or v > best[n[key]]:
                    best[n[key]] = v
    out = {k: v for k, v in best.items() if v is not None}
    for arm in ("Throwing Arm", "Non-Throwing Arm"):
        er, ir = out.get(f"Shoulder Strength: {arm} ER Peak Force"), out.get(f"Shoulder Strength: {arm} IR Peak Force")
        if er and ir:
            out[f"Shoulder Strength: {arm} ER:IR Ratio"] = er / ir
    return out


def build(db, folder):
    players = {_key(f"{p.first_name} {p.last_name}"): p for p in db.query(Player).all()}
    plan = defaultdict(dict)       # (pid, date) -> {test: value}
    stamp = {}                     # (pid, date, test) -> time of the row that set it
    dropped, unmatched, no_hand = [], set(), set()
    ff = defaultdict(list)
    files = sorted(glob.glob(os.path.join(folder, "*.csv")))
    for path in files:
        rows = _read(path)
        if not rows:
            continue
        is_ff = "device" in rows[0]
        for r in rows:
            p = players.get(_key(r.get("name", "")))
            if p is None:
                unmatched.add(r.get("name", "").strip())
                continue
            day = _date(r["date"])
            if is_ff:
                ff[(p.player_id, day)].append(r)
                continue
            vals, why = forcedecks_values(r, leg_side(p))
            if why:
                dropped.append(f"{p.first_name} {p.last_name} {day} {r.get('test type')}: {why}")
                continue
            if r.get("test type", "").upper() in ("SLJ", "IMTP") and leg_side(p) not in ("R", "L"):
                no_hand.add(f"{p.first_name} {p.last_name}")
            t = _time(r.get("time"))
            for name, v in vals.items():
                k = (p.player_id, day, name)
                if k not in stamp or (t and stamp[k] and t > stamp[k]):
                    plan[(p.player_id, day)][name] = v
                    stamp[k] = t
    by_id = {p.player_id: p for p in players.values()}
    for (pid, day), rows in ff.items():
        if by_id[pid].throws not in ("R", "L") or leg_side(by_id[pid]) not in ("R", "L"):
            no_hand.add(f"{by_id[pid].first_name} {by_id[pid].last_name}")
        plan[(pid, day)].update(forceframe_values(rows, by_id[pid].throws, leg_side(by_id[pid])))
    return plan, by_id, dropped, unmatched, no_hand, files


def run(db, folder, apply=False, user_id=None):
    plan, by_id, dropped, unmatched, no_hand, files = build(db, folder)
    print(f"Files: {len(files)}")
    # Some ForceFrame names exist twice (an older "Dynamometry" copy and the
    # workbook's "ForceFrame" one) -- the workbook categories win.
    cat_names = {c.category_id: c.category_name for c in db.query(AssessmentCategory).all()}
    prefer = {"ForceFrame": 2, "Force Plate Detail": 2, "Dynamometry": 0}
    tests = {}
    for t in sorted(db.query(AssessmentTestType).all(),
                    key=lambda t: (prefer.get(cat_names.get(t.category_id), 1), t.test_type_id)):
        tests[t.test_name] = t
    fpd =db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Force Plate Detail").first()
    for _h, name, unit in IBSQT_TESTS:
        if name not in tests and fpd is not None:
            t = AssessmentTestType(category_id=fpd.category_id, test_name=name, unit=unit, display_order=900)
            db.add(t)
            db.flush()
            tests[name] = t
            print(f"  + new test type: {name} ({unit})")
    if user_id is None:
        u = (db.query(User).join(Role, Role.role_id == User.role_id)
             .filter(Role.role_name == "Administrator", User.active.is_(True)).order_by(User.user_id).first())
        if u is None:
            sys.exit("No active Administrator user to record as 'entered by'.")
        user_id = u.user_id
    missing_tests = set()
    n_new_a = n_vals = n_have = 0
    for (pid, day), vals in sorted(plan.items(), key=lambda kv: (by_id[kv[0][0]].last_name, kv[0][1])):
        by_cat = defaultdict(dict)
        for name, v in vals.items():
            t = tests.get(name)
            if t is None:
                missing_tests.add(name)
                continue
            by_cat[t.category_id][t.test_type_id] = round(v, 3)
        for cat_id, tv in by_cat.items():
            a = (db.query(Assessment).filter(Assessment.player_id == pid, Assessment.category_id == cat_id,
                                             Assessment.assessment_date == day).first())
            have = set()
            if a is None:
                a = Assessment(player_id=pid, category_id=cat_id, assessment_date=day, entered_by_user_id=user_id,
                               notes="VALD Hub export")
                db.add(a)
                db.flush()
                n_new_a += 1
            else:
                have = {r[0] for r in db.query(AssessmentResult.test_type_id)
                        .filter(AssessmentResult.assessment_id == a.assessment_id)}
            for ttid, v in tv.items():
                if ttid in have:
                    n_have += 1
                    continue
                db.add(AssessmentResult(assessment_id=a.assessment_id, test_type_id=ttid, value=v))
                n_vals += 1
        p = by_id[pid]
        print(f"  {p.first_name} {p.last_name} {day}: {len(vals)} values")
    print(f"{'Wrote' if apply else 'Would write'}: {n_new_a} new assessments, {n_vals} values "
          f"({n_have} already stored, left alone).")
    if dropped:
        print("Bad trials left out:\n  " + "\n  ".join(dropped))
    if unmatched:
        print("No GBO player (skipped): " + ", ".join(sorted(unmatched)))
    if no_hand:
        print("No throwing hand in GBO -- sided tests skipped: " + ", ".join(sorted(no_hand)))
    if missing_tests:
        print("No GBO test type (skipped): " + ", ".join(sorted(missing_tests)))
    if apply:
        db.commit()
    else:
        db.rollback()
        print("Dry run -- nothing written. Re-run with --apply.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit("Usage: python3 -m scripts.import_vald_exports <folder of VALD csvs> [--apply]")
    db = SessionLocal()
    try:
        run(db, args[0], apply="--apply" in sys.argv)
    finally:
        db.close()
