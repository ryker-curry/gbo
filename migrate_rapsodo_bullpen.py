"""
GBO — Migration: Rapsodo Bullpen Analytics, Phase 1.

Run once, after pulling this update.

What this does:
  1. Creates the new tables: rapsodo_imports, rapsodo_pitches,
     bullpen_pitch_videos.
  2. Adds bullpen_sessions.video_url (session-level video).
  3. Replaces the BullpenType lookup's 5 original values with the
     Rapsodo Bullpen Analytics spec's 8-value list, remapping any
     existing BullpenSession rows onto the closest new name (see the
     OLD_TO_NEW_BULLPEN_TYPE mapping below -- this is a judgment call on
     naming, not a settled 1:1 equivalence; review it and rename again
     later if a mapping doesn't fit).
  4. Seeds the new "Fastball" PitchType (generic/undifferentiated --
     distinct from "4-Seam Fastball", see pitch_type_config.py for why).

Run:
    python migrate_rapsodo_bullpen.py
"""

from sqlalchemy import text

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from models import BullpenType, BullpenSession, PitchType

# Old BullpenType.type_name -> new spec name. Chosen by closest semantic
# match to the existing coach-facing summary behavior each type already
# drives in pages/bullpen_tracking.py (execution %, velocity, movement,
# or plain count) -- not a certainty, flagged for review:
#   High Intent Velo    -> Velocity        (both are max-effort velocity work)
#   Execution Focused   -> Command         (both are location/execution grading)
#   Short Box           -> Standard Bullpen (proximity/generic work, no single new name fits exactly)
#   Touch and Feel       -> Recovery        (both are low-intent, ungraded, feel-focused)
#   Pitch Design         -> Pitch Design    (unchanged)
OLD_TO_NEW_BULLPEN_TYPE = {
    "High Intent Velo": "Velocity",
    "Execution Focused": "Command",
    "Short Box": "Standard Bullpen",
    "Touch and Feel": "Recovery",
    "Pitch Design": "Pitch Design",
}

# Final 8-value list with display order, per the spec (Section 3).
NEW_BULLPEN_TYPES = [
    ("Standard Bullpen", 1),
    ("Pitch Design", 2),
    ("Command", 3),
    ("Velocity", 4),
    ("Recovery", 5),
    ("Live BP", 6),
    ("Assessment", 7),
    ("Other", 8),
]


def migrate_bullpen_types(session):
    existing = {t.type_name: t for t in session.query(BullpenType).all()}

    renamed = 0
    for old_name, new_name in OLD_TO_NEW_BULLPEN_TYPE.items():
        if old_name in existing and old_name != new_name:
            row = existing.pop(old_name)
            if new_name in existing:
                # New name already exists as a separate row (e.g. "Pitch
                # Design" both before and after) -- repoint any sessions
                # using the old row onto the existing new row, then
                # remove the now-duplicate old row.
                session.query(BullpenSession).filter(
                    BullpenSession.bullpen_type_id == row.bullpen_type_id
                ).update({"bullpen_type_id": existing[new_name].bullpen_type_id})
                session.delete(row)
            else:
                row.type_name = new_name
                existing[new_name] = row
            renamed += 1
    session.commit()
    print(f"Renamed/remapped {renamed} existing bullpen type row(s).")

    added = 0
    for name, order in NEW_BULLPEN_TYPES:
        if name in existing:
            existing[name].display_order = order
        else:
            session.add(BullpenType(type_name=name, display_order=order))
            added += 1
    session.commit()
    print(f"Added {added} new bullpen type row(s). Final list: {[t for t, _ in NEW_BULLPEN_TYPES]}")


def seed_fastball_pitch_type(session):
    if session.query(PitchType).filter(PitchType.type_name == "Fastball").first():
        return
    session.add(PitchType(type_name="Fastball", display_order=0))
    session.commit()
    print("Seeded generic 'Fastball' pitch type (distinct from '4-Seam Fastball').")


def main():
    print("Step 1: creating rapsodo_imports, rapsodo_pitches, bullpen_pitch_videos tables...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 2: adding video_url column to bullpen_sessions...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE bullpen_sessions ADD COLUMN IF NOT EXISTS video_url VARCHAR(500)"
        ))
    print("Done.")

    print("Step 3: migrating bullpen types to the new 8-value list...")
    session = get_session()
    try:
        migrate_bullpen_types(session)
        print("Step 4: seeding 'Fastball' pitch type...")
        seed_fastball_pitch_type(session)
    finally:
        session.close()

    print(
        "\nMigration complete. NOTE: pages/bullpen_tracking.py and "
        "pages/player_bullpens.py compare bullpen type NAMES as strings "
        "to decide which summary to show -- those string literals have "
        "been updated in this same change to match the new names. If "
        "you're applying this migration without the matching code "
        "change, those two pages' type-specific summaries will silently "
        "stop matching until that code is also updated."
    )


if __name__ == "__main__":
    main()
