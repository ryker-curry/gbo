"""
GBO — Migration: link Bullpen Sessions back to the Player Assignment
that prescribed them.

Run once, after pulling this update (depends on bullpen_sessions and
player_assignments already existing).

Run:
    python migrate_bullpen_assignment_link.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE bullpen_sessions ADD COLUMN IF NOT EXISTS source_assignment_id INTEGER REFERENCES player_assignments(assignment_id)"
        ))
    print("Added source_assignment_id column to bullpen_sessions.")


if __name__ == "__main__":
    main()