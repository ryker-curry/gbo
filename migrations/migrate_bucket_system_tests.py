"""
GBO — Migration: align Assessment test types with the bucket-system
spreadsheet exactly, per Ryker's explicit instruction: only include raw
data points that are in the spreadsheet, use its DRIVE/PLANT leg framing
and units, and replace GBO's existing versions of overlapping tests.

Two safe operations, in order:
  1. RENAME_MAP -- existing test types renamed/re-unitted IN PLACE (an
     UPDATE, not delete+recreate) so test_type_id stays the same and any
     already-entered AssessmentResult history for that test survives
     intact, just relabeled to match the spreadsheet.
  2. NEW_TESTS -- test types the spreadsheet includes that GBO didn't
     have at all yet (e.g. CMJ Concentric Duration/Force, IMTP Average
     Force, Hop Test Average Force/Contact Time).

Test types NOT in the spreadsheet are deliberately left untouched --
Ryker wants to keep them around in case they get added to the bucket
system later. They just don't feed into the bucket calculation.

Run once, after pulling this update.

Run:
    python migrate_bucket_system_tests.py
"""

from database import get_session
from models import AssessmentCategory, AssessmentTestType

# (category_name, old_test_name, new_test_name, new_unit)
RENAME_MAP = [
    ("Upper Body Strength", "Push Strength: NG/DB Bench Press Load", "Neutral Grip/DB Bench Press Max Load", "lbs"),
    ("Upper Body Strength", "Pull Strength: Chin Up External Load", "Neutral Grip Chin Up Max External Load", "lbs"),
    ("Upper Body Strength", "Grip Strength: Right Grip Strength", "Grip Strength (Seated, Throwing Hand)", "lbs"),

    ("Lower Body Strength", "Bilateral Strength: Trap Bar Deadlift", "Hex Bar Deadlift Max", "lbs"),
    ("Lower Body Strength", "Bilateral Strength: Front Squat", "Front Squat Max", "lbs"),
    ("Lower Body Strength", "Bilateral Strength: Isometric Mid-Thigh Pull (IMTP) Peak Force", "Isometric Mid-Thigh Pull Peak Vertical Force", "N"),
    ("Lower Body Strength", "Hip Strength: Right Hip Abduction Force", "Hip Abduction Force (Drive Leg)", "N"),
    ("Lower Body Strength", "Hip Strength: Left Hip Abduction Force", "Hip Abduction Force (Plant Leg)", "N"),
    ("Lower Body Strength", "Hip Strength: Right Hip Adduction Force", "Hip Adduction Force (Drive Leg)", "N"),
    ("Lower Body Strength", "Hip Strength: Left Hip Adduction Force", "Hip Adduction Force (Plant Leg)", "N"),

    ("Explosive Power", "Jump Performance: Countermovement Jump Height", "Countermovement Jump Height", "in"),
    ("Explosive Power", "Jump Performance: Countermovement Jump RSI-Modified", "Countermovement Jump RSI-Modified", "ratio"),
    ("Explosive Power", "Horizontal Power: Broad Jump Distance", "Broad Jump Distance", "ft"),
    ("Explosive Power", "Lateral Power: Lateral Jump Distance (Right)", "Lateral Jump Distance (Drive Leg)", "ft"),
    ("Explosive Power", "Lateral Power: Lateral Jump Distance (Left)", "Lateral Jump Distance (Plant Leg)", "ft"),
    ("Explosive Power", "Reactive Power: Hop Test RSI (Right)", "Hop Test RSI (10/5)", "ratio"),
    ("Explosive Power", "Jump Performance: Single-Leg Jump Height (Right)", "Single-Leg Jump Height (Drive Leg)", "in"),
    ("Explosive Power", "Jump Performance: Single-Leg Jump Height (Left)", "Single-Leg Jump Height (Plant Leg)", "in"),

    ("Rotational Power", "Rotational Medicine Ball Throw Distance (Right)", "Medicine Ball Shot Put Distance", "ft"),
]

# (category_name, test_name, unit)
NEW_TESTS = [
    ("Explosive Power", "Vertical Jump (Jump Mat)", "in"),
    ("Explosive Power", "Countermovement Jump Concentric Duration", "ms"),
    ("Explosive Power", "Countermovement Jump Concentric Mean Force", "N"),
    ("Explosive Power", "Hop Test Average Force", "N"),
    ("Explosive Power", "Hop Test Mean Contact Time", "ms"),
    ("Explosive Power", "Single-Leg Jump Concentric Impulse (Drive Leg)", "Ns"),
    ("Explosive Power", "Single-Leg Jump Concentric Impulse (Plant Leg)", "Ns"),
    ("Lower Body Strength", "Isometric Mid-Thigh Pull Average Force", "N"),
    ("Lower Body Strength", "Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "N"),
    ("Lower Body Strength", "Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", "N"),
]

# NOTE: test types not in the bucket spreadsheet (Plyometric Push-Up,
# Squat Jump Height, Split Squat, Knee Strength tests, 20-yard sprint,
# etc.) are deliberately NOT removed -- Ryker wants to keep them in GBO
# in case some get added to the bucket system later. They just aren't
# part of the bucket calculation for now.


def main():
    session = get_session()
    try:
        categories = {c.category_name: c for c in session.query(AssessmentCategory).all()}

        print("Step 1: renaming existing test types to match the spreadsheet...")
        renamed = 0
        for cat_name, old_name, new_name, new_unit in RENAME_MAP:
            cat = categories.get(cat_name)
            if cat is None:
                print(f"  SKIP -- category '{cat_name}' not found.")
                continue
            existing = session.query(AssessmentTestType).filter(
                AssessmentTestType.category_id == cat.category_id,
                AssessmentTestType.test_name == old_name,
            ).first()
            if existing is None:
                # Already renamed (e.g. migration re-run), or never existed under that name.
                already_new = session.query(AssessmentTestType).filter(
                    AssessmentTestType.category_id == cat.category_id,
                    AssessmentTestType.test_name == new_name,
                ).first()
                if already_new:
                    print(f"  Already done: '{old_name}' -> '{new_name}'.")
                else:
                    print(f"  SKIP -- '{old_name}' not found under '{cat_name}' (nothing to rename).")
                continue
            existing.test_name = new_name
            existing.unit = new_unit
            renamed += 1
            print(f"  Renamed: '{old_name}' -> '{new_name}' ({new_unit})")
        session.commit()
        print(f"Done. {renamed} test type(s) renamed.\n")

        print("Step 2: adding new test types from the spreadsheet...")
        added = 0
        for cat_name, test_name, unit in NEW_TESTS:
            cat = categories.get(cat_name)
            if cat is None:
                print(f"  SKIP -- category '{cat_name}' not found.")
                continue
            existing = session.query(AssessmentTestType).filter(
                AssessmentTestType.category_id == cat.category_id,
                AssessmentTestType.test_name == test_name,
            ).first()
            if existing:
                continue
            max_order = session.query(AssessmentTestType).filter(AssessmentTestType.category_id == cat.category_id).count()
            session.add(AssessmentTestType(category_id=cat.category_id, test_name=test_name, unit=unit, display_order=max_order + 1))
            added += 1
            print(f"  Added: '{test_name}' ({unit}) under {cat_name}")
        session.commit()
        print(f"Done. {added} new test type(s) added.\n")

        print("Test types not in the bucket spreadsheet were left in place (kept in case they're added to the bucket system later) -- they just aren't part of the bucket calculation.")

    finally:
        session.close()

    print("\nMigration complete.")


if __name__ == "__main__":
    main()