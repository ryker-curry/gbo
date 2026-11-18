"""
GBO -- Migration: weekly progress report tables.

Run once, after pulling this update:
    python3 -m migrations.migrate_weekly_reports

Additive only -- weekly_report_notes (coach notes, see
models.WeeklyReportNote) and weekly_report_sends (email log, see
models.WeeklyReportSend). No existing table or row is touched.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating weekly_report_notes and weekly_report_sends...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS weekly_report_notes (
                note_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                week_start DATE NOT NULL,
                note TEXT,
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_weekly_note_player_week UNIQUE (player_id, week_start)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS weekly_report_sends (
                send_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                week_start DATE NOT NULL,
                email VARCHAR(150),
                status VARCHAR(20) NOT NULL,
                detail TEXT,
                sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_weekly_send_player_week UNIQUE (player_id, week_start)
            )
        """))
    print("Done. Weekly report notes save and Monday emails are logged.")


if __name__ == "__main__":
    main()
