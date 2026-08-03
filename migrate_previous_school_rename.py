"""
GBO — Migration: rename players.high_school to players.previous_school.

Run once, after pulling this update. Safe rename -- existing data
(anyone's high school already entered) is preserved, just under the new
column name, which now also covers JUCO/transfer schools for players
who transferred in.

Run:
    python migrate_previous_school_rename.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        has_old = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'players' AND column_name = 'high_school'"
        )).first()
        has_new = conn.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'players' AND column_name = 'previous_school'"
        )).first()

        if has_old and not has_new:
            conn.execute(text("ALTER TABLE players RENAME COLUMN high_school TO previous_school"))
            print("Renamed players.high_school -> players.previous_school (existing data preserved).")
        elif has_new:
            print("players.previous_school already exists -- nothing to do.")
        else:
            conn.execute(text("ALTER TABLE players ADD COLUMN IF NOT EXISTS previous_school VARCHAR(150)"))
            print("Added players.previous_school (no old column found to rename).")


if __name__ == "__main__":
    main()