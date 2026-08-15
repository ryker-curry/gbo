"""
GBO — Migration: add video_url to hitter_swings.

Run once, after pulling this update. Lets a specific swing within a
Hitter Tracking session have a video clip attached, same pattern as
BullpenPitch.video_url. One clip per swing, no multi-angle.

Run:
    python migrate_hitter_swing_video.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE hitter_swings ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)"
        ))
    print("Added video_url column to hitter_swings.")
    print("\nThis reuses the same 'pitch-videos' Storage bucket already in use -- no new bucket needed.")


if __name__ == "__main__":
    main()