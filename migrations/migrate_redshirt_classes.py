"""
GBO — Migration: add Redshirt class options.

Run once, after pulling this update.

Run:
    python migrate_redshirt_classes.py
"""

from database import get_session
from models import PlayerClass

NEW_CLASSES = [
    ("Redshirt Freshman", 2),
    ("Redshirt Sophomore", 4),
    ("Redshirt Junior", 6),
    ("Redshirt Senior", 8),
]

# Re-order the originals to leave room for the redshirt tiers between them
REORDER = {
    "Freshman": 1,
    "Sophomore": 3,
    "Junior": 5,
    "Senior": 7,
    "Graduate": 9,
}


def main():
    session = get_session()
    try:
        existing_names = {c.class_name for c in session.query(PlayerClass).all()}

        added = 0
        for name, order in NEW_CLASSES:
            if name not in existing_names:
                session.add(PlayerClass(class_name=name, display_order=order))
                added += 1
        session.commit()
        print(f"Added {added} redshirt class option(s).")

        for c in session.query(PlayerClass).all():
            if c.class_name in REORDER:
                c.display_order = REORDER[c.class_name]
        session.commit()
        print("Updated display order for all classes.")
    finally:
        session.close()


if __name__ == "__main__":
    main()