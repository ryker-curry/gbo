"""
GBO -- Migration: official box scores for the Data Health box score check.

Run once, after pulling this update:
    python3 -m migrations.migrate_game_box_scores

Additive only -- creates game_box_scores (see models.GameBoxScore). No
existing table is touched.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating game_box_scores...")
    cols = ",\n".join(f"                {s}_{k} INTEGER" for s in ("our", "opp") for k in ("r", "h", "e", "bb", "k"))
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS game_box_scores (
                game_id INTEGER PRIMARY KEY REFERENCES games(game_id) ON DELETE CASCADE,
{cols},
                entered_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
    print("Done. Official box scores can be entered on the Data Health page.")


if __name__ == "__main__":
    main()
