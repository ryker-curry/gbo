"""
GBO -- Migration: VALD testing tables (Nov 2026). See models.py's
ValdImport / ValdTest / ValdNameLink and services/vald_import.py.
Display only -- these never feed Assessments or the Bucket System.

Run (module form):
    python3 -m migrations.migrate_vald
"""

from sqlalchemy import text
from database import engine

SQL = [
    """
    CREATE TABLE IF NOT EXISTS vald_imports (
        vald_import_id SERIAL PRIMARY KEY,
        system VARCHAR(20) NOT NULL,
        file_name VARCHAR(200),
        first_test_date DATE,
        last_test_date DATE,
        test_count INTEGER NOT NULL DEFAULT 0,
        imported_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS vald_tests (
        vald_test_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        vald_import_id INTEGER REFERENCES vald_imports(vald_import_id) ON DELETE SET NULL,
        system VARCHAR(20) NOT NULL,
        test_type VARCHAR(100) NOT NULL,
        position VARCHAR(150),
        test_key VARCHAR(250) NOT NULL,
        test_date DATE NOT NULL,
        tested_at TIMESTAMP NOT NULL,
        body_weight_kg NUMERIC(6, 2),
        reps INTEGER,
        metrics JSON NOT NULL DEFAULT '{}'::json,
        vald_name VARCHAR(150),
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_vald_test UNIQUE (player_id, system, test_key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_vald_tests_player_id ON vald_tests(player_id)",
    "CREATE INDEX IF NOT EXISTS ix_vald_tests_test_date ON vald_tests(test_date)",
    """
    CREATE TABLE IF NOT EXISTS vald_name_links (
        vald_name_link_id SERIAL PRIMARY KEY,
        vald_name_key VARCHAR(150) NOT NULL,
        vald_name VARCHAR(150),
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_vald_name_link_key UNIQUE (vald_name_key)
    )
    """,
    # Oct 31 2026 lockdown: RLS on, no anon/authenticated Data API access.
    "ALTER TABLE vald_imports ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE vald_tests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE vald_name_links ENABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON TABLE vald_imports FROM anon, authenticated",
    "REVOKE ALL ON TABLE vald_tests FROM anon, authenticated",
    "REVOKE ALL ON TABLE vald_name_links FROM anon, authenticated",
]


def main():
    print("Creating VALD tables (vald_imports, vald_tests, vald_name_links)...")
    with engine.begin() as conn:
        for sql in SQL:
            conn.execute(text(sql))
    print("Done. Upload VALD exports on the Import VALD page.")


if __name__ == "__main__":
    main()
