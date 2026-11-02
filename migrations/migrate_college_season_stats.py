"""
GBO -- Migration: college_season_stats (Nov 2026, College Career on Player
Profile). See models.py's CollegeSeasonStat. Load the researched seasons
afterwards with scripts/import_college_season_stats.py.

Run (module form):
    python3 -m migrations.migrate_college_season_stats
"""

from sqlalchemy import text
from database import engine

STAT_COLS = ("g gs ab r h doubles triples hr rbi bb hbp so gdp sf sh sb cs ibb "
             "w l cg sho sv ip_outs er wp bk bf").split()

SQL = [
    """
    CREATE TABLE IF NOT EXISTS college_season_stats (
        college_season_stat_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        side VARCHAR(10) NOT NULL,
        season_year INTEGER NOT NULL,
        school VARCHAR(120) NOT NULL,
        level VARCHAR(20),
        """ + ",\n        ".join(f"{c} INTEGER" for c in STAT_COLS) + """,
        source_url TEXT,
        notes TEXT,
        created_by_user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        updated_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_college_season_stat UNIQUE (player_id, side, season_year, school)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_college_season_stats_player_id ON college_season_stats(player_id)",
    # Oct 31 2026 lockdown: RLS on, no anon/authenticated Data API access.
    "ALTER TABLE college_season_stats ENABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON TABLE college_season_stats FROM anon, authenticated",
]


def main():
    print("Creating college_season_stats...")
    with engine.begin() as conn:
        for sql in SQL:
            conn.execute(text(sql))
    print("Done. Next: python3 -m scripts.import_college_season_stats --apply")


if __name__ == "__main__":
    main()
