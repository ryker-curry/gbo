"""
GBO -- Migration: game_play_run_scorers (Nov 2026, runs scored tracking).

Who scored on a PA-ending play, when the coach confirms or fixes it in Game
Tracking. Optional data -- every past game already gets runs scored from
run_scorers.py's inference, so nothing needs backfilling. See models.py's
GamePlayRunScorer.

Run (module form):
    python3 -m migrations.migrate_run_scorers
"""

from sqlalchemy import text
from database import engine

SQL = [
    """
    CREATE TABLE IF NOT EXISTS game_play_run_scorers (
        run_scorer_id SERIAL PRIMARY KEY,
        game_pitch_id INTEGER NOT NULL REFERENCES game_pitches(game_pitch_id) ON DELETE CASCADE,
        slot INTEGER NOT NULL,
        our_player_id INTEGER REFERENCES players(player_id) ON DELETE SET NULL,
        opponent_player_id INTEGER REFERENCES opponent_players(opponent_player_id) ON DELETE SET NULL,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_game_play_run_scorers_game_pitch_id ON game_play_run_scorers(game_pitch_id)",
    # Oct 31 2026 lockdown: RLS on, no anon/authenticated Data API access.
    "ALTER TABLE game_play_run_scorers ENABLE ROW LEVEL SECURITY",
    "REVOKE ALL ON TABLE game_play_run_scorers FROM anon, authenticated",
]


def main():
    print("Creating game_play_run_scorers...")
    with engine.begin() as conn:
        for sql in SQL:
            conn.execute(text(sql))
    print("Done.")


if __name__ == "__main__":
    main()
