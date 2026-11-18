"""
GBO — Migration: promote Training Routines out of stub status + add
structured exercise steps + link routines to Player Assignments.

Run once, after pulling this update.

What this does:
  1. Creates the routine_exercises table.
  2. Adds created_by_user_id to training_routines (the table itself
     already existed as an empty stub, so no data is at risk).
  3. Adds routine_id to player_assignments so an assignment can
     optionally point at a specific saved routine.

Run:
    python migrate_training_routines.py
"""

from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    print("Step 1: creating routine_exercises table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding created_by_user_id to training_routines...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE training_routines ADD COLUMN IF NOT EXISTS created_by_user_id INTEGER REFERENCES users(user_id)"
        ))
    print("Done.")

    print("Step 3: adding routine_id to player_assignments...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS routine_id INTEGER REFERENCES training_routines(routine_id)"
        ))
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()