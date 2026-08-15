"""
GBO — Migration: add video_url to routine_exercises.

Run once, after pulling this update.

Run:
    python migrate_routine_exercise_video.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE routine_exercises ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)"
        ))
    print("Added video_url column to routine_exercises.")
    print(
        "\nOne more manual step: create a public Storage bucket named "
        "'routine-videos' in your Supabase project (Supabase dashboard -> "
        "Storage -> New bucket -> name it 'routine-videos' -> make it Public), "
        "same as you did for 'player-photos' and 'pitch-videos'."
    )


if __name__ == "__main__":
    main()