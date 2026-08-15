"""
GBO — Migration: add intended_zone to hitter_swings.

Run once, after pulling this update. Lets a live-AB swing capture BOTH
what the pitcher was aiming for (intended_zone) and where it actually
ended up (the existing pitch_zone column) -- enables a pitcher's own
"live execution accuracy" heatmap (intended vs. actual, with a hitter
in the box) without a second, duplicate tracking system.

Run:
    python migrate_hitter_swing_intended_zone.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE hitter_swings ADD COLUMN IF NOT EXISTS intended_zone INTEGER"
        ))
    print("Added intended_zone column to hitter_swings.")


if __name__ == "__main__":
    main()