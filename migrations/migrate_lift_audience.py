"""
GBO — Migration: add audience targeting to Team Schedule events.

Run once, after pulling this update. Lets a scheduled event (like a
Lift day) target the whole team, pitchers only, or position players
only -- so pitchers and position players can have separate lifts on the
same day. Existing events default to "whole team" (NULL), so nothing
already scheduled changes visibility.

Run:
    python migrate_lift_audience.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS pitchers_only BOOLEAN"
        ))
    print("Added pitchers_only column to team_schedule_events (NULL = whole team, existing events unaffected).")


if __name__ == "__main__":
    main()