"""
GBO -- Migration: widen game_pitches.pitch_outcome to VARCHAR(30) (Oct 31 2026).

Run once (already applied to the live DB on Oct 31 2026 via Supabase MCP):
    python3 -m migrations.migrate_pitch_outcome_length

Why: the pitch clock buttons save "Clock Violation - Pitcher" (25 chars) /
"Clock Violation - Batter" (24 chars), which didn't fit in VARCHAR(20) --
Postgres rejected the row and Game Tracking showed "Couldn't record that --
nothing was saved." Widening a VARCHAR is instant and keeps every row.

Safe to re-run.
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE game_pitches ALTER COLUMN pitch_outcome TYPE VARCHAR(30)"))
    print("game_pitches.pitch_outcome is now VARCHAR(30).")


if __name__ == "__main__":
    main()
