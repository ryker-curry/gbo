"""
GBO — Migration: add hitter_session_types (Live ABs, Batting Practice,
Intersquad, Scrimmage, Game) and link it to hitter_tracking_sessions.

Run once, after pulling this update.

Run:
    python migrate_hitter_session_types.py
"""

from sqlalchemy import text
from database import engine, get_session, Base
import models  # noqa: F401 -- registers all model classes with Base
from seed_lookups import seed_hitter_session_types
from models import HitterSessionType


def main():
    print("Step 1: creating hitter_session_types table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: seeding hitter session types...")
    session = get_session()
    try:
        seed_hitter_session_types(session)
    finally:
        session.close()
    print("Done.")

    print("Step 3: adding session_type_id to hitter_tracking_sessions...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE hitter_tracking_sessions ADD COLUMN IF NOT EXISTS session_type_id INTEGER REFERENCES hitter_session_types(session_type_id)"
        ))
    print("Done.")

    print("Step 4: backfilling any existing sessions to 'Live ABs' (default)...")
    session = get_session()
    try:
        default_type = session.query(HitterSessionType).filter(HitterSessionType.type_name == "Live ABs").first()
        if default_type:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE hitter_tracking_sessions SET session_type_id = :tid WHERE session_type_id IS NULL"
                ), {"tid": default_type.session_type_id})
    finally:
        session.close()
    print("Done.")

    print("Step 5: making session_type_id required going forward...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE hitter_tracking_sessions ALTER COLUMN session_type_id SET NOT NULL"
        ))
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()