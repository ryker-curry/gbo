"""
GBO — Migration: add Bullpen Tracking (bullpen_types, bullpen_sessions,
bullpen_pitches).

Run once, after pulling this update.

Run:
    python migrate_bullpen_tracking.py
"""

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from seed_lookups import seed_bullpen_types


def main():
    print("Step 1: creating bullpen tables...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: seeding bullpen types...")
    session = get_session()
    try:
        seed_bullpen_types(session)
    finally:
        session.close()
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()