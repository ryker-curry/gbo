"""
GBO -- Migration: Throwing Workload (Nov 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_throwing_workload

Additive only -- throw_logs (logged / sensor throws) and throwing_assumptions
(the assumed warm-up and catch-play throws). No existing table is touched.
Safe to re-run.
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS throw_logs (
                throw_log_id SERIAL PRIMARY KEY,
                player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                log_date DATE NOT NULL,
                throw_type VARCHAR(20) NOT NULL,
                throws INTEGER NOT NULL DEFAULT 0,
                high_intent INTEGER,
                source VARCHAR(12) NOT NULL DEFAULT 'manual',
                workload NUMERIC(10, 2),
                peak_torque NUMERIC(6, 1),
                notes TEXT,
                created_by_user_id INTEGER REFERENCES users(user_id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_throw_logs_player_date ON throw_logs (player_id, log_date)"))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS throwing_assumptions (
                setting_id INTEGER PRIMARY KEY,
                pen_warmup INTEGER NOT NULL DEFAULT 25,
                game_warmup INTEGER NOT NULL DEFAULT 35,
                catch_play INTEGER NOT NULL DEFAULT 40,
                catch_play_days VARCHAR(12) NOT NULL DEFAULT 'practice',
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
        conn.execute(text("INSERT INTO throwing_assumptions (setting_id) VALUES (1) ON CONFLICT (setting_id) DO NOTHING"))
        for t in ("throw_logs", "throwing_assumptions"):
            conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
    print("Done. Throwing Workload can save logs, sensor imports and assumptions.")


if __name__ == "__main__":
    main()
