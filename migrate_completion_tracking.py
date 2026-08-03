"""
GBO — Migration: completion tracking on Player Assignments + Team
Schedule Events (replaces the separate Training Sessions log).

Run once, after pulling this update.

What this does:
  1. Adds goal_id, completed, completed_notes, player_feedback,
     completed_at to player_assignments.
  2. Adds completed, completed_notes, completed_at to
     team_schedule_events.

Run:
    python migrate_completion_tracking.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS goal_id INTEGER REFERENCES idp_goals(goal_id)"))
        conn.execute(text("ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS completed BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS completed_notes TEXT"))
        conn.execute(text("ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS player_feedback TEXT"))
        conn.execute(text("ALTER TABLE player_assignments ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
    print("Updated player_assignments.")

    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS completed BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS completed_notes TEXT"))
        conn.execute(text("ALTER TABLE team_schedule_events ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP"))
    print("Updated team_schedule_events.")

    print("\nMigration complete.")


if __name__ == "__main__":
    main()