"""
GBO — Migration: add Lifting session type + scheduled_lifts table.

Run once, after pulling this update.

Run:
    python migrate_lifting_and_schedule.py
"""

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from models import SessionType


def main():
    print("Step 1: creating the scheduled_lifts table...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding the Lifting session type...")
    session = get_session()
    try:
        if session.query(SessionType).filter(SessionType.type_name == "Lifting").first() is None:
            session.add(SessionType(type_name="Lifting", display_order=3))
            session.commit()
            print("Added 'Lifting' session type.")
        else:
            print("'Lifting' session type already exists -- nothing to do.")
    finally:
        session.close()

    print("\nMigration complete.")


if __name__ == "__main__":
    main()