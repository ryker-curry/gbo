"""
GBO — Migration: add game_pitches.is_sword.

Run once, after pulling this update.

Adds one nullable-in-practice-but-defaulted boolean column so a coach
can flag a pitch as a "sword" (an ugly, off-balance checked swing) live
during Game Tracking. Additive only -- every existing GamePitch row
gets is_sword=False by default, nothing else changes.

Run:
    python migrate_sword_flag.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding game_pitches.is_sword...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS is_sword BOOLEAN NOT NULL DEFAULT FALSE"
        ))
    print("Done. No existing game_pitches rows were changed (all default to False).")


if __name__ == "__main__":
    main()
