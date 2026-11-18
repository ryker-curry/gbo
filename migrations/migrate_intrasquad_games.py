"""
GBO — Migration: add intrasquad game support.

games.is_intrasquad (default False) marks a game as Squad A vs Squad B
using our own roster, not an external opponent. game_pitches gets
opponent_our_player_id -- for intrasquad games, the "opposing" side of
a pitch can point at a real roster player instead of just a hand/order
entry or a disconnected OpponentPlayer, so both squads' stats stay
attributed to real player profiles.

Run once, after pulling this update. Depends on Game Tracking and
Opponent Teams already being migrated.

Run:
    python migrate_intrasquad_games.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Step 1: adding is_intrasquad to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS is_intrasquad BOOLEAN NOT NULL DEFAULT FALSE"
        ))
    print("Done.")

    print("Step 2: adding opponent_our_player_id to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS opponent_our_player_id INTEGER REFERENCES players(player_id)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games default to is_intrasquad=False -- unaffected.")


if __name__ == "__main__":
    main()