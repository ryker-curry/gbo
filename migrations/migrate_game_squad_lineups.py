"""
GBO — Migration: add game_lineup_slots.squad.

Lets the same GameLineupSlot table hold both Squad A and Squad B
batting orders for intrasquad games (squad = 'A' or 'B'), instead of
only Squad A having a real saved lineup. Every existing row -- which
was always Squad A, since Squad B never had a lineup concept before
this -- backfills to 'A', so nothing about existing games changes.

Run once, after pulling this update.

Run:
    python migrate_game_squad_lineups.py
"""

from sqlalchemy import text
from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    print("Step 1: adding game_lineup_slots.squad (defaulting existing rows to 'A')...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_lineup_slots ADD COLUMN IF NOT EXISTS squad VARCHAR(1) NOT NULL DEFAULT 'A'"
        ))
    print("Done.")

    print("\nMigration complete. Existing lineups are unaffected -- they're all")
    print("Squad A now. Squad B lineup setup is optional, same as everything else")
    print("in Game Tracking; without it, Squad B's batter is still picked ad hoc")
    print("each at-bat, exactly like before this migration.")


if __name__ == "__main__":
    main()
