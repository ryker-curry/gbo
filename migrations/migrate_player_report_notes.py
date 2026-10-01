"""
GBO -- Migration: add player_report_notes table (Pitcher Meeting Report).

Run once, after pulling this update:
    python3 -m migrations.migrate_player_report_notes

Additive only -- stores the coach's typed focus points that print on a
Pitcher Meeting Report sheet (see models.PlayerReportNote). No existing
table or row is touched. FKs to players/games/seasons are ON DELETE
CASCADE so a note never blocks deleting a game or season.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating player_report_notes...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS player_report_notes (
                note_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                report_kind VARCHAR(10) NOT NULL,
                game_id INTEGER REFERENCES games(game_id) ON DELETE CASCADE,
                season_id INTEGER REFERENCES seasons(season_id) ON DELETE CASCADE,
                notes TEXT,
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_player_report_notes_lookup "
            "ON player_report_notes(player_id, report_kind, game_id, season_id)"
        ))
    print("Done. Coach notes on the Pitcher Meeting Report now save.")


if __name__ == "__main__":
    main()
