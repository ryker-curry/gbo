"""
GBO — Migration: add games.squad_b_starting_pitcher_id.

Squad A's starting pitcher has always been a real saved field
(games.starting_pitcher_id) -- Squad B never had an equivalent, since
its pitcher was always picked live, every single plate appearance, with
nothing saved. This adds just the STARTING pick for Squad B, mirroring
starting_pitcher_id -- NOT a parallel PitchingChange-style table, so
Squad B still doesn't get formal "pitching change" history the way
Squad A does. Game Tracking's Live Tracking tab uses this as a smarter
default for the per-plate-appearance opposing-pitcher picker in
intrasquad games (falling back further to whichever Squad B pitcher
most recently appeared in the game's pitches, once any exist) --
always overridable, same as every other auto-suggested default on that
page.

Run once, after pulling this update. Depends on Game Tracking and
intrasquad games (migrate_intrasquad_games.py) already being migrated.

Run from the repo root:
    python -m migrations.migrate_squad_b_starting_pitcher
"""

from sqlalchemy import text
from database import engine


def main():
    print("Step 1: adding squad_b_starting_pitcher_id to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS squad_b_starting_pitcher_id INTEGER REFERENCES players(player_id)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games default to squad_b_starting_pitcher_id=NULL -- unaffected.")
    print("Squad B's opposing-pitcher picker keeps working exactly as before until you set one on the")
    print("Lineup & Setup tab for a given game.")


if __name__ == "__main__":
    main()
