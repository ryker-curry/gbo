"""
GBO -- Migration: add advance_reports table (Advance Scouting Report).

Run once, after pulling this update:
    python3 -m migrations.migrate_advance_reports

Additive only -- see models.AdvanceReport. No existing table or row is
touched. (Game Tracking's new "Their pitcher" picker needs no schema
change: it stores into the existing GamePitch.opponent_player_id.)
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating advance_reports...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS advance_reports (
                report_id SERIAL PRIMARY KEY,
                opponent_team_id INTEGER NOT NULL REFERENCES opponent_teams(team_id) ON DELETE CASCADE,
                title VARCHAR(200) NOT NULL,
                series_date DATE,
                roles JSON,
                plan_text TEXT,
                published BOOLEAN NOT NULL DEFAULT FALSE,
                created_by_user_id INTEGER REFERENCES users(user_id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_advance_reports_team ON advance_reports(opponent_team_id)"))
    print("Done. Advance Scouting reports can now be saved and published.")


if __name__ == "__main__":
    main()
