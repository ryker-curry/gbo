"""
GBO — Migration: Integrated Insights (spec Section 27), IDPGoal <-> Rapsodo link.

Run once, after pulling this update.

What this does:
  Adds two nullable columns to idp_goals:
    - target_pitch_type_id (FK -> pitch_types.pitch_type_id): optionally
      scopes a Pitcher-Specific goal's Rapsodo baseline/current value to
      one pitch type (e.g. Fastball velocity vs. Slider velocity).
    - source_bullpen_id (FK -> bullpen_sessions.bullpen_id): optionally
      links a goal back to the specific bullpen session that motivated
      it, the Rapsodo-data equivalent of the existing
      source_assessment_id column.

Both are additive and nullable -- every existing IDPGoal row is
unaffected; nothing is renamed, dropped, or backfilled.

Run:
    python migrate_idp_rapsodo_link.py
"""

from sqlalchemy import text

from database import engine


def main():
    print("Adding idp_goals.target_pitch_type_id and idp_goals.source_bullpen_id...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS target_pitch_type_id "
            "INTEGER REFERENCES pitch_types(pitch_type_id)"
        ))
        conn.execute(text(
            "ALTER TABLE idp_goals ADD COLUMN IF NOT EXISTS source_bullpen_id "
            "INTEGER REFERENCES bullpen_sessions(bullpen_id)"
        ))
    print("Done. No existing idp_goals rows were changed.")


if __name__ == "__main__":
    main()
