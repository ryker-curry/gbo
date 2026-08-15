"""
GBO — Migration: link Training Sessions to IDP goals.

Run once, after pulling this update. Adds a nullable goal_id column to
training_sessions so a session can (optionally) be tagged as work
prescribed toward a specific IDP goal.

Run:
    python migrate_session_goal_link.py
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE training_sessions ADD COLUMN IF NOT EXISTS goal_id INTEGER REFERENCES idp_goals(goal_id)"
        ))
    print("Added goal_id column to training_sessions.")


if __name__ == "__main__":
    main()