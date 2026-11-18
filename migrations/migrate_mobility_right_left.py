"""
Migration: Right/Left mobility field restructuring.

Per Ryker's explicit call: Mobility & ROM data entry moves from
role-based Shoulder wording (Throwing Arm / Non-Throwing Arm) to plain
anatomical Right/Left, so a coach testing a player doesn't have to
know that player's handedness to enter the numbers. The bucket-scoring
layer (bucket_system.py) now resolves Right/Left back to Throwing Arm/
Non-Throwing Arm per player from Player.throws at scoring time -- see
resolve_side_by_throws in bucket_system.py.

What this script does:

  1. Renames the 4 Hip "Stride Leg" AssessmentTestType rows to "Plant
     Leg" IN PLACE (clean 1:1 name mapping -- "Plant Leg" is just a
     clearer name for the same glove-side-leg concept, per Ryker's
     correction; nothing about what's measured changes).

  2. Deletes the old role-labeled Shoulder ER/IR/Flexion/Extension
     AssessmentTestType rows (6 rows: Throwing Arm / Non-Throwing Arm
     ER + IR, plus the old single non-sided Flexion/Extension) and
     reseeds the new anatomical Right/Left set (8 rows) from
     seed_lookups.MOBILITY_ROM_TESTS. This ISN'T a clean 1:1 rename --
     Flexion/Extension go from 1 field each to a Right/Left pair each
     -- so a straight UPDATE isn't possible here the way it is for Hip.

     Safety check: before deleting any of the 6 old Shoulder rows, this
     script counts real AssessmentResult rows attached to it. If ANY
     old Shoulder field has real data on it, that field is left alone
     and flagged for manual review instead of being deleted -- deleting
     a test_type row with real results would silently destroy that
     data. Ryker confirmed (Aug 2026) that no real Mobility data has
     been entered yet, so this is expected to delete cleanly, but the
     script checks for real data itself rather than trusting that
     confirmation blindly.

  3. Re-runs seed_assessment_categories_and_tests() to add the new
     Right/Left Shoulder rows (and anything else newly added to the
     seed lists) -- this function is already idempotent/additive-only,
     so it's safe to call again on an existing database.

Run once against your real database:
    python3 migrate_mobility_right_left.py
"""
import sys

from database import get_session
from models import AssessmentTestType, AssessmentResult
from seed_lookups import seed_assessment_categories_and_tests

HIP_RENAMES = {
    "Hip: Stride Leg Internal Rotation": "Hip: Plant Leg Internal Rotation",
    "Hip: Stride Leg External Rotation": "Hip: Plant Leg External Rotation",
    "Hip: Stride Leg Abduction": "Hip: Plant Leg Abduction",
    "Hip: Stride Leg Adduction": "Hip: Plant Leg Adduction",
}

OLD_SHOULDER_FIELDS = [
    "Shoulder: Throwing Arm External Rotation",
    "Shoulder: Non-Throwing Arm External Rotation",
    "Shoulder: Throwing Arm Internal Rotation",
    "Shoulder: Non-Throwing Arm Internal Rotation",
    "Shoulder: Flexion",
    "Shoulder: Extension",
]


def run():
    session = get_session()
    try:
        # --- 1. Hip: Stride Leg -> Plant Leg, clean rename ---
        renamed = 0
        for old_name, new_name in HIP_RENAMES.items():
            tt = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == old_name).first()
            if tt is None:
                print(f"  (already absent, nothing to rename: '{old_name}')")
                continue
            clash = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == new_name).first()
            if clash is not None:
                print(f"  SKIPPING '{old_name}' -> '{new_name}': target name already exists.")
                continue
            tt.test_name = new_name
            renamed += 1
            print(f"  renamed: '{old_name}' -> '{new_name}'")
        session.commit()

        # --- 2. Old role-labeled Shoulder fields -> delete (if no real data), reseed as Right/Left ---
        deleted = 0
        skipped_with_data = []
        for old_name in OLD_SHOULDER_FIELDS:
            tt = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == old_name).first()
            if tt is None:
                print(f"  (already absent, nothing to delete: '{old_name}')")
                continue
            result_count = (
                session.query(AssessmentResult)
                .filter(AssessmentResult.test_type_id == tt.test_type_id)
                .count()
            )
            if result_count > 0:
                skipped_with_data.append((old_name, result_count))
                print(f"  SKIPPING delete of '{old_name}' -- has {result_count} real result(s) on file. "
                      f"Not touched; resolve manually.")
                continue
            session.delete(tt)
            deleted += 1
            print(f"  deleted (no data attached): '{old_name}'")
        session.commit()

        print(f"\n{renamed} Hip field(s) renamed, {deleted} old Shoulder field(s) removed.")
        if skipped_with_data:
            print("\nWARNING -- the following old Shoulder fields have REAL DATA and were left in place:")
            for name, count in skipped_with_data:
                print(f"  - '{name}' ({count} result(s))")
            print("These won't show up under the new Right/Left labels until handled manually.")

        # --- 3. Reseed: adds the new Right/Left Shoulder rows (idempotent, additive-only) ---
        print("\nSeeding new Right/Left Shoulder fields (and anything else new)...")
        seed_assessment_categories_and_tests(session)
        print("\nDone.")
    finally:
        session.close()


if __name__ == "__main__":
    run()
    sys.exit(0)
