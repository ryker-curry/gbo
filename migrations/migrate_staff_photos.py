"""
GBO — Migration: add photo_url to users (staff/coach profile photos).

Was flagged as "in progress, not confirmed finished" -- this is the
actual finish: adds the column, matching the same pattern Player.photo_url
already uses.

Run once, after pulling this update.

Run:
    python migrate_staff_photos.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding photo_url to users...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500)"))
    print("Done.")


if __name__ == "__main__":
    main()