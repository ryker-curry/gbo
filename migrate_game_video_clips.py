"""
GBO — Migration: add game_video_clips table.

Lets you bulk-upload pitch clips (e.g. downloaded from your camera,
one clip per pitch) for a game, then match each one to the actual
GamePitch it belongs to. Same "upload now, match later" pattern
already used on Video Review's pitcher bulk-upload. Reuses the
existing "pitch-videos" Supabase Storage bucket -- no new bucket
needs to be created for this.

Run once, after pulling this update.

Run:
    python migrate_game_video_clips.py
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    print("Creating game_video_clips table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("\nMigration complete. This reuses the existing 'pitch-videos' Storage")
    print("bucket (already created for Video Review) -- no new bucket needed.")


if __name__ == "__main__":
    main()
