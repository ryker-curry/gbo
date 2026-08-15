"""
GBO — Migration: add precise pitch-location coordinates to game_pitches.

Phase 2 of Ryker's architecture doc: replaces manual 1-9 zone-button
entry with click-the-exact-spot location. intended_zone/pitch_zone
(the old 1-9+Bury integers) are kept and still populated -- now
auto-derived from the new coordinates rather than entered separately,
so existing execution-accuracy calculations elsewhere in the app keep
working unchanged.

Run once, after pulling this update. Existing GamePitch rows are NOT
backfilled with coordinates (there's no way to reconstruct precise
location from an old 1-9 zone number) -- their actual_plate_x/z and
intended_plate_x/z stay NULL; intended_zone/pitch_zone on those old
rows are untouched.

Run:
    python migrate_pitch_coordinates.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding pitch coordinate columns to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS actual_plate_x NUMERIC(5, 3)"))
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS actual_plate_z NUMERIC(5, 3)"))
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS intended_plate_x NUMERIC(5, 3)"))
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS intended_plate_z NUMERIC(5, 3)"))
    print("Done.")

    print("\nMigration complete. Existing pitches keep their old 1-9 zone")
    print("values as-is (not backfilled with coordinates) -- only pitches")
    print("logged after this point will have precise location.")


if __name__ == "__main__":
    main()