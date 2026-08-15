"""
GBO — Migration: add Mobility session type, split Throwing/Plyos.

Run once, after pulling this update.

What this does:
  1. Renames the existing "Throwing / Plyos" row to "Throwing" (same
     row/id, so anything already logged or assigned against it keeps
     working -- it just reads as "Throwing" now).
  2. Adds a new "Plyos" row.
  3. Adds a new "Mobility" row.
  4. Updates display_order on everything to a sensible new sequence.

Run:
    python migrate_session_types_split.py
"""

from database import get_session
from models import SessionType

NEW_ORDER = {
    "Arm Care": 1,
    "Mobility": 2,
    "Conditioning": 3,
    "Lifting": 4,
    "Hitting Drills": 5,
    "Throwing": 6,
    "Plyos": 7,
    "General": 8,
}


def main():
    session = get_session()
    try:
        existing = {t.type_name: t for t in session.query(SessionType).all()}

        # Step 1: rename "Throwing / Plyos" -> "Throwing" (same row)
        old_combined = existing.get("Throwing / Plyos")
        if old_combined:
            old_combined.type_name = "Throwing"
            existing["Throwing"] = old_combined
            print("Renamed 'Throwing / Plyos' -> 'Throwing' (existing references preserved).")
        elif "Throwing" not in existing:
            session.add(SessionType(type_name="Throwing", display_order=NEW_ORDER["Throwing"]))
            print("Added 'Throwing' (no old combined row found).")

        # Step 2: add "Plyos" if missing
        if "Plyos" not in existing:
            session.add(SessionType(type_name="Plyos", display_order=NEW_ORDER["Plyos"]))
            print("Added 'Plyos'.")

        # Step 3: add "Mobility" if missing
        if "Mobility" not in existing:
            session.add(SessionType(type_name="Mobility", display_order=NEW_ORDER["Mobility"]))
            print("Added 'Mobility'.")

        session.commit()

        # Step 4: fix display_order on everything
        for t in session.query(SessionType).all():
            if t.type_name in NEW_ORDER:
                t.display_order = NEW_ORDER[t.type_name]
        session.commit()
        print("Updated display order for all session types.")

        print("\nMigration complete.")
    finally:
        session.close()


if __name__ == "__main__":
    main()