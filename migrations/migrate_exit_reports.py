"""
GBO -- Migration: Fall Exit Report plans (Oct 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_exit_reports

Creates exit_reports (see models.ExitReport). Nothing existing changes.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating exit_reports...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS exit_reports (
                exit_report_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                season_id INTEGER NOT NULL REFERENCES seasons(season_id) ON DELETE CASCADE,
                status VARCHAR(12) NOT NULL DEFAULT 'draft',
                priorities JSON,
                coach_notes TEXT,
                met_on DATE,
                saved_by_user_id INTEGER REFERENCES users(user_id),
                saved_at TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                updated_at TIMESTAMP NOT NULL DEFAULT now(),
                CONSTRAINT uq_exit_reports_player_season UNIQUE (player_id, season_id)
            )
        """))
    print("Done. Exit reports can be saved.")


if __name__ == "__main__":
    main()
