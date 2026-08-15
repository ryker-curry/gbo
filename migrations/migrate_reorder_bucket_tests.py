"""
GBO — Migration: reorder Assessment test types within each bucket-
relevant category to exactly match the bucket-system spreadsheet's own
left-to-right column order, per Ryker's request -- makes data entry
match the order he'd naturally scan a spreadsheet (or type results in
as they're collected during testing), with all variables of the same
test type kept together (e.g. all 4 IMTP fields together, all 4 CMJ
fields together).

Safe to re-run -- just sets display_order on existing rows, no data
change. Only reorders the 6 bucket-relevant categories; everything
else (Arm Health, Mobility, Anthropometrics, Pitcher-Specific, etc.)
is untouched.

Run once, after pulling this update.

Run:
    python migrate_reorder_bucket_tests.py
"""

from database import get_session
from models import AssessmentCategory, AssessmentTestType

# (category_name, [test_name in the exact order they should appear])
NEW_ORDER = {
    "Body Composition": [
        "Body Weight", "Body Fat Mass", "Skeletal Muscle Mass", "Percent Body Fat",
        # everything else in this category keeps its existing relative order, appended after these 4
    ],
    "Rotational Power": [
        "Medicine Ball Shot Put Distance",
    ],
    "Explosive Power": [
        "Vertical Jump (Jump Mat)",
        "Broad Jump Distance",
        "Lateral Jump Distance (Drive Leg)", "Lateral Jump Distance (Plant Leg)",
        "Countermovement Jump Height",
        "Countermovement Jump RSI-Modified",
        "Countermovement Jump Concentric Duration",
        "Countermovement Jump Concentric Mean Force",
        "Hop Test RSI (10/5)",
        "Hop Test Average Force",
        "Hop Test Mean Contact Time",
        "Single-Leg Jump Height (Drive Leg)", "Single-Leg Jump Concentric Impulse (Drive Leg)",
        "Single-Leg Jump Height (Plant Leg)", "Single-Leg Jump Concentric Impulse (Plant Leg)",
    ],
    "Lower Body Strength": [
        "Hex Bar Deadlift Max", "Front Squat Max",
        "Hip Abduction Force (Drive Leg)", "Hip Abduction Force (Plant Leg)",
        "Hip Adduction Force (Drive Leg)", "Hip Adduction Force (Plant Leg)",
        "Isometric Mid-Thigh Pull Average Force",
        "Isometric Mid-Thigh Pull Peak Vertical Force",
        "Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)",
        "Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)",
    ],
    "Upper Body Strength": [
        "Neutral Grip Chin Up Max External Load",
        "Neutral Grip/DB Bench Press Max Load",
        "Grip Strength (Seated, Throwing Hand)",
    ],
    "Speed": [
        "Top Speed: Flying 10 Sprint Time",
        "Acceleration: 10-Yard Sprint Time",
    ],
}


def main():
    session = get_session()
    try:
        categories = {c.category_name: c for c in session.query(AssessmentCategory).all()}
        total_updated = 0

        for cat_name, ordered_names in NEW_ORDER.items():
            cat = categories.get(cat_name)
            if cat is None:
                print(f"SKIP -- category '{cat_name}' not found.")
                continue

            all_tests = session.query(AssessmentTestType).filter(AssessmentTestType.category_id == cat.category_id).all()
            tests_by_name = {t.test_name: t for t in all_tests}

            updated = 0
            order = 1
            # First, the explicitly-ordered ones (spreadsheet order)
            for name in ordered_names:
                t = tests_by_name.get(name)
                if t is None:
                    print(f"  WARNING -- '{name}' not found under {cat_name}, skipping.")
                    continue
                if t.display_order != order:
                    t.display_order = order
                    updated += 1
                order += 1
            # Then everything else in that category (not in the explicit
            # list -- e.g. Body Composition's other 15 InBody fields),
            # keeping their existing relative order, appended after.
            remaining = sorted([t for t in all_tests if t.test_name not in ordered_names], key=lambda t: t.display_order)
            for t in remaining:
                if t.display_order != order:
                    t.display_order = order
                    updated += 1
                order += 1

            session.commit()
            total_updated += updated
            print(f"{cat_name}: reordered {updated} test type(s).")

        print(f"\nDone. {total_updated} test type(s) updated total.")
    finally:
        session.close()


if __name__ == "__main__":
    main()