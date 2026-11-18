"""
GBO -- Migration: game_pitches.is_pitch (Oct 2026, pitch clock violations
and intentional walks).

Run once, after pulling this update:
    python3 -m migrations.migrate_non_pitch_events

Additive only -- one boolean column, TRUE for every existing row (they're
all real pitches). Game Tracking saves a pitch clock violation (+ball or
+strike) or an intentional walk as a row with is_pitch = FALSE, so the
count and the at-bat result work like any pitch but it never adds to a
pitch count, strike % or pitch chart.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding game_pitches.is_pitch...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS is_pitch BOOLEAN NOT NULL DEFAULT TRUE"))
    print("Done. Every existing row is a real pitch (is_pitch = TRUE).")


if __name__ == "__main__":
    main()
