"""
GBO — Migration: add batted-ball type + field location to game_pitches.

Phase 2 of Ryker's architecture doc: batted_ball_type (Ground Ball /
Line Drive / Fly Ball / Pop Up) and raw field coordinates
(batted_ball_x/y, see field_location.py) for balls in play. Swing/take
itself isn't a new column -- already fully derivable from the existing
pitch_outcome field. Pull/Straight/Oppo is deliberately NOT computed
here either -- that depends on batter handedness and belongs in
analysis code, not entry.

Run once, after pulling this update. Existing GamePitch rows are NOT
backfilled (no way to reconstruct this after the fact) -- only pitches
logged after this point will have batted-ball data.

Run:
    python migrate_batted_ball.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding batted-ball columns to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS batted_ball_type VARCHAR(20)"))
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS batted_ball_x NUMERIC(6, 1)"))
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS batted_ball_y NUMERIC(6, 1)"))
    print("Done.")

    print("\nMigration complete. Existing pitches are unaffected -- only")
    print("balls in play logged after this point will have this data.")


if __name__ == "__main__":
    main()