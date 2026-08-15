"""
GBO — Migration: link videos to specific pitches/assessments.

Run once, after pulling this update. The videos table already existed
as a stub with no rows -- this just adds the assessment_id column so a
video can be tied to the exact pitch it came from.

Run:
    python migrate_video_pitch_link.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE videos ADD COLUMN IF NOT EXISTS assessment_id INTEGER REFERENCES assessments(assessment_id)"
        ))
    print("Added assessment_id column to videos.")
    print(
        "\nOne more manual step: create a public Storage bucket named "
        "'pitch-videos' in your Supabase dashboard (Storage -> New bucket -> "
        "make it Public), same as you did for 'player-photos'."
    )


if __name__ == "__main__":
    main()