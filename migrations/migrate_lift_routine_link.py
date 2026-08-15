"""
GBO — Migration: link Team Schedule events to Training Routines.

Run once, after pulling this update. Lets a scheduled Lift day (or any
team event) point at the actual workout content -- so a player sees the
real exercises/video, not just a title like "Squat Day".

Run:
    python migrate_lift_routine_link.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS routine_id INTEGER REFERENCES training_routines(routine_id)"
        ))
    print("Added routine_id column to team_schedule_events.")


if __name__ == "__main__":
    main()