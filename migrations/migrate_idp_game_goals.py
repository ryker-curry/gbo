"""
GBO -- Migration: development goals on game stats.

Run once, after pulling this update:
    python3 -m migrations.migrate_idp_game_goals

Adds two nullable columns to idp_goals (game_metric, metric_window -- see
models.IDPGoal / analytics/game_goals.py). Existing goals are untouched.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding game_metric / metric_window to idp_goals...")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS game_metric VARCHAR(40)"))
        conn.execute(text("ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS metric_window VARCHAR(12)"))
    print("Done. Game-stat development goals can be saved.")


if __name__ == "__main__":
    main()
