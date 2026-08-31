"""
GBO — Migration: link Rapsodo pitches to intrasquad-game pitches.

Adds the columns needed to import a Rapsodo export against a pitcher's
outing in an intrasquad game, instead of only against a bullpen session,
and to record which specific live-charted GamePitch each Rapsodo reading
has been matched to (see services/rapsodo_import.py).

Three changes:
  1. rapsodo_pitches.bullpen_id -- relaxed to nullable. A game-linked
     import has no bullpen session at all; RapsodoImport.game_id (below)
     is set instead of RapsodoImport.bullpen_id for those imports, and
     every RapsodoPitch row belonging to that import has bullpen_id NULL.
  2. rapsodo_pitches.game_pitch_id -- new nullable FK to game_pitches.
     Set once a Rapsodo reading has been matched (automatically, when
     pitch counts line up, or manually via the reconciliation UI) to the
     specific pitch it came from.
  3. rapsodo_imports.game_id -- new nullable FK to games, parallel to the
     existing bullpen_id column. Mutually exclusive with bullpen_id on a
     given import row.

Existing rows are untouched: bullpen_id stays populated on every
pre-existing RapsodoPitch/RapsodoImport row exactly as it was, and the
two new columns are simply NULL on all of them.

Run once, after pulling this update, as a module from the repo root:
    python -m migrations.migrate_rapsodo_game_linking
"""

from sqlalchemy import text
from database import engine


def main():
    print("Updating rapsodo_pitches / rapsodo_imports for game-linked Rapsodo imports...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE rapsodo_pitches ALTER COLUMN bullpen_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE rapsodo_pitches ADD COLUMN IF NOT EXISTS game_pitch_id INTEGER REFERENCES game_pitches(game_pitch_id)"))
        conn.execute(text("ALTER TABLE rapsodo_imports ADD COLUMN IF NOT EXISTS game_id INTEGER REFERENCES games(game_id)"))
    print("Done.")

    print("\nMigration complete. Existing bullpen-linked imports/pitches are")
    print("unchanged. New intrasquad-game imports can now set")
    print("RapsodoImport.game_id instead of bullpen_id, and matched pitches")
    print("can record their game_pitch_id link.")


if __name__ == "__main__":
    main()
