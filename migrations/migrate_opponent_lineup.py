"""
GBO — Migration: add opponent_lineup_slots table and
games.opponent_starting_pitcher_id.

Phase 2 of Ryker's architecture doc: a real per-game opponent lineup
(batting order mapped to actual named players from their OpponentTeam
roster), instead of just picking a roster player ad hoc each at-bat.
Only meaningful for external games with a real OpponentTeam linked and
a built-out roster -- optional, same as everything else in the
Opponent Teams system.

Run once, after pulling this update. Depends on Opponent Teams already
being migrated (migrate_opponent_teams.py).

Run:
    python migrate_opponent_lineup.py
"""

from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    print("Step 1: creating opponent_lineup_slots table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding opponent_starting_pitcher_id to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS opponent_starting_pitcher_id INTEGER REFERENCES opponent_players(opponent_player_id)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games are unaffected -- opponent")
    print("lineup setup is optional, same as picking a roster player ad hoc")
    print("each at-bat still works fine without it.")


if __name__ == "__main__":
    main()