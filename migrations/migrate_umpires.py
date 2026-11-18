"""
Migration: umpires lookup table + home plate umpire on each game.

Run (module form):  python3 -m migrations.migrate_umpires

Why: SmartPark (like Trackman) does not record who the plate umpire is,
so umpire scorecards and umpire-adjusted framing need it entered per game.

BEFORE RUNNING: check GAMES_TABLE matches models.py's Game.__tablename__.
Batter heights: the framing/umpire code needs a height (inches) for every
batter, PSU and opponent. Check models.py for an existing height column on
players and on opponent players before adding a new one; this script does
not add height columns for that reason.

Also update models.py to match:
  class Umpire(Base):  __tablename__ = "umpires"  (umpire_id, full_name,
                       active, created_at, updated_at)
  Game.home_plate_umpire_id = Column(Integer, ForeignKey("umpires.umpire_id"),
                                     nullable=True)
"""
from sqlalchemy import text

from database import engine  # GBO's shared engine (root-level database.py)

GAMES_TABLE = "games"

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS umpires (
        umpire_id   SERIAL PRIMARY KEY,
        full_name   VARCHAR(120) NOT NULL,
        active      BOOLEAN NOT NULL DEFAULT TRUE,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_umpires_full_name UNIQUE (full_name)
    )
    """,
    f"""
    ALTER TABLE {GAMES_TABLE}
        ADD COLUMN IF NOT EXISTS home_plate_umpire_id INTEGER
        REFERENCES umpires (umpire_id)
    """,
    f"""
    CREATE INDEX IF NOT EXISTS ix_{GAMES_TABLE}_home_plate_umpire_id
        ON {GAMES_TABLE} (home_plate_umpire_id)
    """,
    # Match the Oct 31 2026 lockdown: RLS on, no public Data API access.
    "ALTER TABLE umpires ENABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON umpires FROM anon, authenticated",
    "REVOKE ALL ON SEQUENCE umpires_umpire_id_seq FROM anon, authenticated",
]


def main():
    with engine.begin() as conn:
        for sql in STATEMENTS:
            conn.execute(text(sql))
    print("migrate_umpires: done")


if __name__ == "__main__":
    main()
