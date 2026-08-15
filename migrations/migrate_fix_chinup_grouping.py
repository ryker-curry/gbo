"""
GBO — Migration: fix Chin Up External Load grouping.

"Push Strength: Chin Up External Load" should be "Pull Strength: Chin
Up External Load" -- a chin-up is a pull movement, not a push one.
Renames the test type in place (same test_type_id), so any assessment
values already recorded against it stay correctly attached.

Run once, after pulling this update.

Run:
    python migrate_fix_chinup_grouping.py
"""

from database import get_session
from models import AssessmentTestType


def main():
    session = get_session()
    try:
        test_type = (
            session.query(AssessmentTestType)
            .filter(AssessmentTestType.test_name == "Push Strength: Chin Up External Load")
            .first()
        )
        if test_type:
            test_type.test_name = "Pull Strength: Chin Up External Load"
            session.commit()
            print("Renamed 'Push Strength: Chin Up External Load' -> 'Pull Strength: Chin Up External Load'.")
        else:
            already_fixed = (
                session.query(AssessmentTestType)
                .filter(AssessmentTestType.test_name == "Pull Strength: Chin Up External Load")
                .first()
            )
            if already_fixed:
                print("Already correctly named -- nothing to do.")
            else:
                print("Test type not found under either name -- check your Upper Body Strength category.")
    finally:
        session.close()


if __name__ == "__main__":
    main()