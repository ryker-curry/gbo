"""
GBO — Migration: turn Position into a dropdown lookup.

Run once, after pulling this update. Converts players.position and
players.secondary_position from free text to foreign keys into a new
positions lookup table, carrying over any text you already typed (e.g.
"Pitcher" matches the new Position row named "Pitcher").

Anything that doesn't match an exact position name (typos, abbreviations
like "SS", blank values) is left unset -- go back into Players and
re-select it from the dropdown after this runs.

Run:
    python migrate_positions.py
"""

from sqlalchemy import text

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from models import Position
from seed_lookups import seed_positions


def main():
    print("Step 1: creating the positions table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: seeding standard positions...")
    session = get_session()
    try:
        seed_positions(session)
        positions_by_name = {p.position_name: p.position_id for p in session.query(Position).all()}
    finally:
        session.close()
    print("Done.")

    print("Step 3: adding position_id / secondary_position_id columns to players...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS position_id INTEGER REFERENCES positions(position_id)"
        ))
        conn.execute(text(
            "ALTER TABLE players ADD COLUMN IF NOT EXISTS secondary_position_id INTEGER REFERENCES positions(position_id)"
        ))
    print("Done.")

    print("Step 4: migrating existing free-text position values where they match exactly...")
    with engine.begin() as conn:
        has_old_columns = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'players' AND column_name = 'position'"
        )).first()
        if has_old_columns:
            for name, pos_id in positions_by_name.items():
                conn.execute(
                    text("UPDATE players SET position_id = :pid WHERE position = :name AND position_id IS NULL"),
                    {"pid": pos_id, "name": name},
                )
                conn.execute(
                    text("UPDATE players SET secondary_position_id = :pid WHERE secondary_position = :name AND secondary_position_id IS NULL"),
                    {"pid": pos_id, "name": name},
                )
            print("Migrated any exact-matching text values. Anything that didn't match "
                  "an exact position name (typos, abbreviations, blanks) was left unset "
                  "-- re-select it from the dropdown in Players.")
        else:
            print("No old free-text position column found -- nothing to migrate.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()