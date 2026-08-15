"""
GBO — Migration: correct assessment categories + expand Player fields.

Run once, after pulling this update, to bring an already-initialized
database up to date without losing existing data (like Ryker's first
test player).

What this does:
  1. Creates the new player_statuses and player_classes tables (and any
     other new tables in models.py that don't exist yet).
  2. Adds new columns to the existing players table via ALTER TABLE
     (SQLAlchemy's create_all only creates missing tables -- it does not
     add columns to tables that already exist).
  3. Deletes the old, incorrect assessment_categories rows (safe: no
     assessments have been created yet, so nothing references them) and
     reseeds with the corrected 11-category list + real test types for
     Anthropometrics and Body Composition.
  4. Seeds the new player_statuses and player_classes lookup tables.

Run:
    python migrate_milestone2.py
"""

from sqlalchemy import text

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base
from models import AssessmentCategory, AssessmentTestType
from database import get_session
from seed_lookups import (
    seed_assessment_categories_and_tests, seed_player_statuses, seed_player_classes,
)

NEW_PLAYER_COLUMNS = [
    "ADD COLUMN IF NOT EXISTS secondary_position VARCHAR(50)",
    "ADD COLUMN IF NOT EXISTS jersey_number INTEGER",
    "ADD COLUMN IF NOT EXISTS throws VARCHAR(1)",
    "ADD COLUMN IF NOT EXISTS bats VARCHAR(1)",
    "ADD COLUMN IF NOT EXISTS class_id INTEGER REFERENCES player_classes(class_id)",
    "ADD COLUMN IF NOT EXISTS graduation_year INTEGER",
    "ADD COLUMN IF NOT EXISTS dominant_hand VARCHAR(1)",
    "ADD COLUMN IF NOT EXISTS dominant_leg VARCHAR(1)",
    "ADD COLUMN IF NOT EXISTS hometown VARCHAR(150)",
    "ADD COLUMN IF NOT EXISTS high_school VARCHAR(150)",
    "ADD COLUMN IF NOT EXISTS height_in NUMERIC(5, 2)",
    "ADD COLUMN IF NOT EXISTS weight_lb NUMERIC(5, 1)",
    "ADD COLUMN IF NOT EXISTS status_id INTEGER REFERENCES player_statuses(status_id)",
]


def main():
    print("Step 1: creating any new tables (player_statuses, player_classes)...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding new columns to the players table...")
    with engine.begin() as conn:
        for clause in NEW_PLAYER_COLUMNS:
            conn.execute(text(f"ALTER TABLE players {clause}"))
    print("Done.")

    print("Step 3: correcting assessment categories...")
    session = get_session()
    try:
        # Safe to clear: no assessments/results reference these yet.
        session.query(AssessmentTestType).delete()
        session.query(AssessmentCategory).delete()
        session.commit()
    finally:
        session.close()

    session = get_session()
    try:
        seed_assessment_categories_and_tests(session)
    finally:
        session.close()
    print("Done.")

    print("Step 4: seeding player statuses and classes...")
    session = get_session()
    try:
        seed_player_statuses(session)
        seed_player_classes(session)
    finally:
        session.close()
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()