"""
GBO — Migration: link Player Assignments to a specific Bullpen Script.

Run once, after pulling this update (depends on bullpen_scripts already
existing -- run migrate_bullpen_scripts.py first if you haven't).

Run:
    python migrate_assignment_script_link.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS bullpen_script_id INTEGER REFERENCES bullpen_scripts(script_id)"
        ))
    print("Added bullpen_script_id column to player_assignments.")


if __name__ == "__main__":
    main()