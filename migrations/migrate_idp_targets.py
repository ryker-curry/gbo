"""
GBO — Migration: add structured target fields to IDP goals.

Run once, after pulling this update. Adds optional target_test_type_id,
baseline_value, target_value, and target_date to idp_goals -- turns a
goal from pure free text into something measurable ("85° -> 95° by
Sept 1") when a coach chooses to fill them in. Existing goals are
unaffected (all new columns are nullable).

Run:
    python migrate_idp_targets.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS target_test_type_id INTEGER REFERENCES assessment_test_types(test_type_id)"
        ))
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS baseline_value NUMERIC(10, 3)"
        ))
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS target_value NUMERIC(10, 3)"
        ))
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS target_date DATE"
        ))
    print("Added target_test_type_id, baseline_value, target_value, and target_date to idp_goals.")


if __name__ == "__main__":
    main()