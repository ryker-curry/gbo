"""
GBO -- Migration: error alerts (error_log.py).

Run once, after pulling this update:
    python3 -m migrations.migrate_app_errors

Additive only -- creates app_errors (see models.AppError). No existing
table is touched.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating app_errors...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS app_errors (
                error_id SERIAL PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                fingerprint VARCHAR(64) NOT NULL,
                error_type VARCHAR(120),
                message TEXT,
                location VARCHAR(255),
                output_name VARCHAR(255),
                page VARCHAR(120),
                user_id INTEGER,
                role_name VARCHAR(60),
                traceback_text TEXT,
                alert_sent BOOLEAN NOT NULL DEFAULT FALSE
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_errors_created ON app_errors (created_at)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_app_errors_fp ON app_errors (fingerprint, created_at)"))
    print("Done. App errors will be logged and emailed (GBO_ALERT_EMAIL).")


if __name__ == "__main__":
    main()
