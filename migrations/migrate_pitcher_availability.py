"""
GBO -- Migration: Arm Care & Availability board.

Run once, after pulling this update:
    python3 -m migrations.migrate_pitcher_availability

Additive only -- pitcher_availability (coach holds / limits and planned
outings, see models.PitcherAvailability). No existing table is touched.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating pitcher_availability...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pitcher_availability (
                availability_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                kind VARCHAR(10) NOT NULL,
                status VARCHAR(12),
                plan_type VARCHAR(12),
                start_date DATE,
                end_date DATE,
                planned_date DATE,
                note TEXT,
                cleared BOOLEAN NOT NULL DEFAULT FALSE,
                created_by_user_id INTEGER REFERENCES users(user_id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pitcher_availability_player ON pitcher_availability (player_id)"))
    print("Done. Arm Care holds and planned outings can be saved.")


if __name__ == "__main__":
    main()
