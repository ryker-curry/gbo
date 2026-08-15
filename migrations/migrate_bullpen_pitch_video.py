"""
GBO — Migration: add video_url to bullpen_pitches.

Run once, after pulling this update. Lets a specific pitch within a
bullpen session have a video clip attached (release point/mechanics
review), separate from the Rapsodo data link. One video per pitch, no
multi-angle support.

Run:
    python migrate_bullpen_pitch_video.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE bullpen_pitches ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)"
        ))
    print("Added video_url column to bullpen_pitches.")
    print(
        "\nThis reuses the same 'pitch-videos' Storage bucket you already "
        "created for Pitch Video Review -- no new bucket needed."
    )


if __name__ == "__main__":
    main()