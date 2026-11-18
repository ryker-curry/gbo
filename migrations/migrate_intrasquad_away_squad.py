"""
GBO — Migration: add games.intrasquad_away_squad.

Two-squad intrasquad games now get a real, pickable Home/Away
designation instead of a fixed "squad A is always first to bat"
default. This column records which squad ('A' or 'B') is Away for a
given game -- Away bats first (top of the inning), matching real
baseball, with the other squad as Home. NULL for every other game
(external games, three-squad intrasquad games, and any two-squad
intrasquad game created before this column existed) -- game_tracking.py's
_squad_display()/compute_current_state() both treat NULL the same as
'A', so every existing game keeps behaving exactly as it did before
this migration.

Run once, after pulling this update. Depends on Game Tracking and
intrasquad games (migrate_intrasquad_games.py) already being migrated.

Run from the repo root:
    python -m migrations.migrate_intrasquad_away_squad
"""

from sqlalchemy import text
from database import engine


def main():
    print("Step 1: adding intrasquad_away_squad to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS intrasquad_away_squad VARCHAR(1)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games default to intrasquad_away_squad=NULL, which")
    print("_squad_display()/compute_current_state() treat the same as 'A' -- no behavior change")
    print("until you pick a Home/Away team for a game (at creation, or on Manage Game while")
    print("the game is still Scheduled).")


if __name__ == "__main__":
    main()
