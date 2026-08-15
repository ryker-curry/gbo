"""
GBO — Rename positions to abbreviations (RHP, LHP, C, 1B, ... UTL).

Safe to run whether or not migrate_positions.py has already run:
  - If the positions table is empty, seeds it directly with abbreviations.
  - If it already has the old full names (Pitcher, Catcher, ...), renames
    them in place -- any player already assigned to "Pitcher" keeps that
    same row (now called "RHP"), so no data is lost. A new "LHP" row is
    added since the old list didn't distinguish pitcher handedness.
  - If it's already abbreviated, does nothing.

Run:
    python rename_positions_to_abbreviations.py
"""

from database import get_session
from models import Position

# old full name -> (new abbreviation, new display_order)
RENAME_MAP = {
    "Pitcher": ("RHP", 1),
    "Catcher": ("C", 3),
    "First Base": ("1B", 4),
    "Second Base": ("2B", 5),
    "Third Base": ("3B", 6),
    "Shortstop": ("SS", 7),
    "Left Field": ("LF", 8),
    "Center Field": ("CF", 9),
    "Right Field": ("RF", 10),
    "Designated Hitter": ("DH", 11),
    "Utility": ("UTL", 12),
}


def main():
    session = get_session()
    try:
        existing = {p.position_name: p for p in session.query(Position).all()}

        if not existing:
            print("positions table is empty -- seeding abbreviations directly.")
            from seed_lookups import seed_positions
            seed_positions(session)
            return

        renamed = 0
        for old_name, (new_name, new_order) in RENAME_MAP.items():
            if old_name in existing:
                row = existing[old_name]
                row.position_name = new_name
                row.display_order = new_order
                renamed += 1
        session.commit()

        if renamed:
            print(f"Renamed {renamed} positions to abbreviations.")
        else:
            print("No old full-name positions found -- already abbreviated or using a different naming.")

        # Add LHP if it doesn't exist yet (old list had no handedness split)
        if session.query(Position).filter(Position.position_name == "LHP").first() is None:
            session.add(Position(position_name="LHP", display_order=2))
            session.commit()
            print("Added LHP as a new position option.")

    finally:
        session.close()


if __name__ == "__main__":
    main()