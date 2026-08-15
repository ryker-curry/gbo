"""
GBO — Migration: add coach_specialty to users.

Run once, after pulling this update. Lets a Coach be tagged Pitching /
Hitting / Both, used to filter which Training Routines they see (a
Hitting Coach doesn't need to see pitcher-specific routines and vice
versa). Only meaningful for role=Coach -- everyone else's dashboards
and pages are unaffected.

Run:
    python migrate_coach_specialty.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS coach_specialty VARCHAR(20)"
        ))
    print("Added coach_specialty column to users.")


if __name__ == "__main__":
    main()