"""
GBO — Migration: add Med Ball session type.

Run once, after pulling this update.

Run:
    python migrate_med_ball_type.py
"""

from database import get_session
from models import SessionType


def main():
    session = get_session()
    try:
        if session.query(SessionType).filter(SessionType.type_name == "Med Ball").first() is None:
            session.add(SessionType(type_name="Med Ball", display_order=9))
            session.commit()
            print("Added 'Med Ball' session type.")
        else:
            print("'Med Ball' already exists -- nothing to do.")

        general = session.query(SessionType).filter(SessionType.type_name == "General").first()
        if general:
            general.display_order = 10
            session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()