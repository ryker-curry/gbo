"""
GBO -- Migration: team game report email log.

Run once, after pulling this update:
    python3 -m migrations.migrate_team_report_sends

Additive only -- team_report_sends (see models.TeamReportSend), one row per
(game, coach) so scripts/send_team_game_reports.py never double-sends.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating team_report_sends...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS team_report_sends (
                send_id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                email VARCHAR(150),
                status VARCHAR(20) NOT NULL,
                detail TEXT,
                sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_team_report_send_game_user UNIQUE (game_id, user_id)
            )
        """))
    print("Done. Team game report emails are logged.")


if __name__ == "__main__":
    main()
