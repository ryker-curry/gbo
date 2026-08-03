"""
GBO — Migration: add photo_url column to players.

Run once, after pulling this update.

Run:
    python add_player_photo_column.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding photo_url column to players...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE players ADD COLUMN IF NOT EXISTS photo_url VARCHAR(500)"))
    print("Done.")


if __name__ == "__main__":
    main()