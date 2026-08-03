"""
GBO — Migration: Pitcher-Specific tests + Pitch Type dropdown.

Run once, after pulling this update.

What this does:
  1. Creates the new pitch_types table.
  2. Adds the pitch_type_id column to assessments.
  3. Seeds Pitcher-Specific test types (Velocity, Spin Rate, Spin Axis in
     degrees, etc.) and the 7 pitch types (4-Seam Fastball, Slider, ...).

Run:
    python migrate_pitcher_specific.py
"""

from sqlalchemy import text

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from seed_lookups import seed_assessment_categories_and_tests, seed_pitch_types


def main():
    print("Step 1: creating pitch_types table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding pitch_type_id column to assessments...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE assessments ADD COLUMN IF NOT EXISTS pitch_type_id INTEGER REFERENCES pitch_types(pitch_type_id)"
        ))
    print("Done.")

    print("Step 3: seeding Pitcher-Specific test types and pitch types...")
    session = get_session()
    try:
        seed_assessment_categories_and_tests(session)
        seed_pitch_types(session)
    finally:
        session.close()
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()