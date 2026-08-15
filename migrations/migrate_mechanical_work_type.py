"""
GBO — Migration: add Mechanical Work session type.

Run once, after pulling this update.

Run:
    python migrate_mechanical_work_type.py
"""

from database import get_session
from models import SessionType


def main():
    session = get_session()
    try:
        if session.query(SessionType).filter(SessionType.type_name == "Mechanical Work").first() is None:
            session.add(SessionType(type_name="Mechanical Work", display_order=8))
            session.commit()
            print("Added 'Mechanical Work' session type.")
        else:
            print("'Mechanical Work' already exists -- nothing to do.")

        # Push "General" to the end if it exists, so Mechanical Work lands before it
        general = session.query(SessionType).filter(SessionType.type_name == "General").first()
        if general:
            general.display_order = 9
            session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()