"""
GBO — Migration: rename individual_sessions to training_sessions.

Run once, after pulling this update. The table was empty (no page
existed to add rows to it yet), so this is a simple, safe rename --
Postgres updates foreign key references automatically.

Run:
    python migrate_training_sessions.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'individual_sessions'"
        )).first()
        if exists:
            conn.execute(text("ALTER TABLE individual_sessions RENAME TO training_sessions"))
            print("Renamed individual_sessions -> training_sessions.")
        else:
            print("individual_sessions table not found -- nothing to rename (already renamed, or fresh install).")


if __name__ == "__main__":
    main()