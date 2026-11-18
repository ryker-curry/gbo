"""
Load the pitchers' fall testing workbook (STUDY_BBF26 DATA.xlsx) into GBO --
Nov 2026, Ryker: "get rid of everything that has been input and start from
scratch", one fall test date for every tab, and a newer copy of the
workbook must be able to replace it later.

    python3 -m scripts.import_pitcher_workbook "<workbook.xlsx>"                      # dry run
    python3 -m scripts.import_pitcher_workbook "<workbook.xlsx>" --replace --apply    # write

Options:
  --date YYYY-MM-DD   test date for every value (default 2026-09-15)
  --replace           first remove this fall's testing already on file for the
                      pitchers in the workbook (Aug 1 - Dec 31 of the test date's
                      year), so the workbook is the only fall copy. Run the same
                      command on a newer workbook to override everything again.
                      Left alone: Rapsodo pitch imports, VALD Hub exports and the
                      position-players sheet (Fern's hitter testing).
                      Every removed value is saved first to
                      data/backups/pitcher_fall_testing_removed_<time>.csv.
  --apply             write; without it nothing is changed.

The FB VELO&SPIN tab (fastball velo / spin) is not imported (Ryker, Nov 2026).

Uses the same reader / name matching / unit conversions / side resolution as
the Import Assessments page (services/study_workbook_import.py). Close name
matches are accepted and listed; names with no match are skipped and listed.
All-or-nothing: if anything fails, nothing (including the removal) is saved.
"""

import csv
import os
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import SessionLocal  # noqa: E402
from models import (Assessment, AssessmentCategory, AssessmentResult, AssessmentTestType, BullpenPitch,  # noqa: E402
                    IDPGoal, Player, Role, User, Video)
from services import study_workbook_import as swi  # noqa: E402

DEFAULT_DATE = date(2026, 9, 15)
MARKER = "Pitcher testing workbook (fall)"
KEEP_NOTES = ("Imported from Rapsodo", "VALD Hub export", "Position players testing sheet")


def fall_window(day):
    return date(day.year, 8, 1), date(day.year + 1, 1, 1)   # end exclusive


def removal_set(db, pids, day):
    """Assessments --replace would remove: this fall, these players, not a kept source."""
    start, end = fall_window(day)
    rows = (db.query(Assessment).filter(Assessment.player_id.in_(pids), Assessment.assessment_date >= start,
                                        Assessment.assessment_date < end).all()) if pids else []
    return [a for a in rows if not any(k in (a.notes or "") for k in KEEP_NOTES)]


def remove(db, assessments, backup_path):
    """Back up then delete (not committed here -- the import's commit saves both)."""
    ids = [a.assessment_id for a in assessments]
    if not ids:
        return 0
    rows = (db.query(Player.first_name, Player.last_name, Assessment.assessment_date, AssessmentCategory.category_name,
                     AssessmentTestType.test_name, AssessmentResult.value, Assessment.notes)
            .join(Assessment, Assessment.player_id == Player.player_id)
            .join(AssessmentCategory, AssessmentCategory.category_id == Assessment.category_id)
            .outerjoin(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
            .outerjoin(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
            .filter(Assessment.assessment_id.in_(ids)).all())
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    with open(backup_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["first", "last", "date", "category", "test", "value", "notes"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], r[3], r[4], float(r[5]) if r[5] is not None else "", r[6] or ""])
    for a in assessments:          # forget the loaded objects so new rows can't collide with them
        db.expunge(a)
    # unhook anything pointing at these assessments, then delete
    db.query(Video).filter(Video.assessment_id.in_(ids)).update({Video.assessment_id: None}, synchronize_session=False)
    db.query(IDPGoal).filter(IDPGoal.source_assessment_id.in_(ids)).update({IDPGoal.source_assessment_id: None},
                                                                          synchronize_session=False)
    db.query(BullpenPitch).filter(BullpenPitch.linked_assessment_id.in_(ids)).update(
        {BullpenPitch.linked_assessment_id: None}, synchronize_session=False)
    n = db.query(AssessmentResult).filter(AssessmentResult.assessment_id.in_(ids)).delete(synchronize_session=False)
    db.query(Assessment).filter(Assessment.assessment_id.in_(ids)).delete(synchronize_session=False)
    return n


def admin_id(db):
    u = (db.query(User).join(Role, Role.role_id == User.role_id)
         .filter(Role.role_name == "Administrator", User.active.is_(True)).order_by(User.user_id).first())
    if u is None:
        sys.exit("No active Administrator user to record as 'entered by'.")
    return u.user_id


def report(plan):
    t = plan["totals"]
    print(f"Test date: {plan['test_date']}   players: {t['players']}   values: {t['new_values']} new, "
          f"{t['already_recorded']} already on file for that date")
    close = [n for n in plan["names"] if n["player_id"] and n.get("how") not in ("exact", "chosen")]
    if close:
        print("Close name matches (accepted -- check these):")
        for n in close:
            print(f"  {n['first']} {n['last']}  ->  {n['player_name']}  ({n.get('how')})")
    miss = [n for n in plan["names"] if not n["player_id"]]
    if miss:
        print("No GBO player (skipped): " + ", ".join(f"{n['first']} {n['last']}" for n in miss))
    for tab, info in plan["tabs"].items():
        line = f"  {tab:14s} rows {info['rows']:3d}  values {info['values']:4d}"
        if info["unmatched"]:
            line += f"  unmatched {info['unmatched']}"
        print(line)
        for who, flag in info["flags"]:
            print(f"      flagged, skipped: {who}: {flag}")
        for who, col, text in info["text"]:
            print(f"      text in a number cell, skipped: {who} / {col.strip()}: {text}")
        if info["unknown"]:
            print(f"      columns not recognized: {', '.join(map(str, info['unknown']))}")
    if plan["missing_tabs"]:
        print("Tabs not in this workbook: " + ", ".join(plan["missing_tabs"]))
    skipped = sorted({s for p in plan["players"].values() for s in p["skipped"]})
    if skipped:
        print("Not imported (fix and re-run): " + "; ".join(skipped[:12]) + (" ..." if len(skipped) > 12 else ""))


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    path = args[0]
    day = DEFAULT_DATE
    for a in argv:
        if a.startswith("--date="):
            day = datetime.strptime(a.split("=", 1)[1], "%Y-%m-%d").date()
    if "--date" in argv:
        day = datetime.strptime(argv[argv.index("--date") + 1], "%Y-%m-%d").date()
    replace, apply = "--replace" in argv, "--apply" in argv
    with open(path, "rb") as f:
        data = f.read()
    db = SessionLocal()
    try:
        plan = swi.build_plan(db, data, day)
        # Ryker: "don't worry about the pitch data in that spreadsheet" -- the
        # FB VELO&SPIN tab is not imported.
        for pp in plan["players"].values():
            pp["fb"] = None
        plan["totals"]["fb_rows"] = 0
        plan["tabs"].pop("FB VELO&SPIN", None)
        pids = list(plan["players"])
        gone = removal_set(db, pids, day) if replace else []
        if replace:
            n_vals = (db.query(AssessmentResult).filter(AssessmentResult.assessment_id.in_(
                [a.assessment_id for a in gone])).count() if gone else 0)
            start, end = fall_window(day)
            print(f"--replace: {'removing' if apply else 'would remove'} {len(gone)} assessments ({n_vals} values) "
                  f"from {start} to {end} for these {len(pids)} players.")
            # the import must not treat values about to be removed as "already on file"
            for pp in plan["players"].values():
                pp["duplicates"] = []
            plan["totals"]["new_values"] += plan["totals"]["already_recorded"]
            plan["totals"]["already_recorded"] = 0
        report(plan)
        if not apply:
            print("Dry run -- nothing written. Add --apply (with --replace to start from scratch).")
            return
        if gone:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = os.path.join(ROOT, "data", "backups", f"pitcher_fall_testing_removed_{stamp}.csv")
            n = remove(db, gone, backup)
            db.flush()
            print(f"Backed up {n} removed values to {backup}")
        counts = swi.commit_plan(db, plan, admin_id(db))     # commits the removal + import together
        for a in db.query(Assessment).filter(Assessment.player_id.in_(pids), Assessment.assessment_date == day).all():
            if MARKER not in (a.notes or ""):
                a.notes = MARKER + (("\n" + a.notes) if a.notes else "")
        db.commit()
        print(f"Wrote {counts['values']} values in {counts['assessments_created']} assessments; "
              f"{counts['players_updated']} players' height / hand updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main(sys.argv[1:])
