"""
GBO -- Migration: body_comp_targets (Oct 2026, Body Comp ring scores to
a target instead of value / team max).

Run once, after pulling this update:
    python3 -m migrations.migrate_body_comp_targets

Additive only -- one new table (models.BodyCompTarget). Until it exists
(or while it's empty) the ring uses the active roster's median as the
target, so the app runs fine before this is run.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating body_comp_targets...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS body_comp_targets (
                target_id SERIAL PRIMARY KEY,
                test_name VARCHAR(100) NOT NULL UNIQUE,
                target_value NUMERIC(7, 2) NOT NULL,
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
    print("Done. Set targets on Assessments -> Body comp ring targets.")


if __name__ == "__main__":
    main()
