"""
GBO — Migration: add Opponent Teams and rosters (opponent_teams,
opponent_players), and link Game/GamePitch to them.

Existing games keep working unchanged -- opponent_name stays as a
fallback; opponent_team_id and opponent_player_id are both optional
additions, not replacements.

Run once, after pulling this update. Depends on Game Tracking already
being migrated (migrate_game_tracking.py).

Run:
    python migrate_opponent_teams.py
"""

from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    print("Step 1: creating opponent_teams and opponent_players tables...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding opponent_team_id to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS opponent_team_id INTEGER REFERENCES opponent_teams(team_id)"
        ))
        conn.execute(text(
            "ALTER TABLE games ALTER COLUMN opponent_name DROP NOT NULL"
        ))
    print("Done.")

    print("Step 3: adding opponent_player_id to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS opponent_player_id INTEGER REFERENCES opponent_players(opponent_player_id)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games/pitches are unaffected -- "
          "opponent_name and free-typed hand/batting-order still work "
          "exactly as before; the team/roster links are optional additions.")


if __name__ == "__main__":
    main()