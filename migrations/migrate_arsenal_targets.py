"""
GBO -- Migration: add arsenal_targets table (Arsenal Plan coach overrides).

Run once, after pulling this update:
    python3 -m migrations.migrate_arsenal_targets

Additive only -- stores a coach's own target shape for a pitch on the
Arsenal Plan (see models.ArsenalTarget). No existing table or row is
touched. The Arsenal Plan works without it (rule-based targets only);
this just lets coaches save their own.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating arsenal_targets...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS arsenal_targets (
                target_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                family VARCHAR(20) NOT NULL,
                velo NUMERIC(5,1),
                ivb NUMERIC(5,1) NOT NULL,
                run NUMERIC(5,1) NOT NULL,
                note TEXT,
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_arsenal_target_player_family UNIQUE (player_id, family)
            )
        """))
    print("Done. Coaches can now save their own target shapes on Pitcher Profile -> Arsenal Plan.")


if __name__ == "__main__":
    main()
