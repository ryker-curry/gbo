"""
GBO — Migration: generalize Lift Schedule into Team Schedule + add
Player Assignments and Athletic Trainer appointments.

Run once, after pulling this update.

What this does:
  1. Renames scheduled_lifts -> team_schedule_events and adds the new
     event_type_id column (existing rows are backfilled as "Lift" type,
     so nothing already scheduled is lost).
  2. Creates the team_event_types, player_assignments, and
     at_appointments tables.
  3. Seeds the 4 team event types (Lift, Practice, Game, Other).

Run:
    python migrate_scheduling_system.py
"""

from sqlalchemy import text

from database import engine, Base, get_session
import models  # noqa: F401 -- registers all model classes with Base
from models import TeamEventType
from seed_lookups import seed_team_event_types


def main():
    with engine.begin() as conn:
        old_table_exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'scheduled_lifts'"
        )).first()
        new_table_exists = conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'team_schedule_events'"
        )).first()

        if old_table_exists and not new_table_exists:
            print("Step 1: renaming scheduled_lifts -> team_schedule_events...")
            conn.execute(text("ALTER TABLE scheduled_lifts RENAME TO team_schedule_events"))
            print("Done.")
        else:
            print("Step 1: nothing to rename (already renamed, or fresh install).")

    print("Step 2: creating new tables (team_event_types, player_assignments, at_appointments) "
          "and any missing columns...")
    Base.metadata.create_all(bind=engine)
    print("Done.")

    print("Step 3: seeding team event types...")
    session = get_session()
    try:
        seed_team_event_types(session)
        lift_type = session.query(TeamEventType).filter(TeamEventType.type_name == "Lift").first()
    finally:
        session.close()
    print("Done.")

    print("Step 4: adding event_type_id column to team_schedule_events and backfilling existing rows as 'Lift'...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS event_type_id INTEGER REFERENCES team_event_types(event_type_id)"
        ))
        if lift_type:
            conn.execute(
                text("UPDATE team_schedule_events SET event_type_id = :lift_id WHERE event_type_id IS NULL"),
                {"lift_id": lift_type.event_type_id},
            )
    print("Done.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()