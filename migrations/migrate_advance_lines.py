"""
GBO -- Migration: one-line plans on advance reports (Oct 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_advance_lines

Additive only: advance_reports.lines (JSON) holds the coach-edited
one-line plan for each of their pitchers and hitters.
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE advance_reports ADD COLUMN IF NOT EXISTS lines JSON"))
    print("Done. Advance reports can now save one-line plans.")


if __name__ == "__main__":
    main()
