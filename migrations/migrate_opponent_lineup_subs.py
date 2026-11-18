"""
GBO -- Migration: opponent lineup substitutions + lineup restarts (Oct 31 2026).

Run once (already applied to the live DB on Oct 31 2026 via Supabase MCP):
    python3 -m migrations.migrate_opponent_lineup_subs

Creates (nothing existing changes):
  - opponent_lineup_substitutions -- a player entering one of the
    opponent's batting-order spots mid-game.
  - opponent_lineup_restarts -- the opponent went back to the top of
    their order; the next batter after this point is their #1 spot.
Both get Row Level Security ON with no policies (same as every other
GBO table -- the app's own database login is unaffected).

Safe to re-run.
"""

from sqlalchemy import text
from database import engine

SQL = """
CREATE TABLE IF NOT EXISTS opponent_lineup_substitutions (
    opponent_sub_id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    opponent_lineup_slot_id INTEGER NOT NULL REFERENCES opponent_lineup_slots(opponent_lineup_slot_id) ON DELETE CASCADE,
    opponent_player_id INTEGER NOT NULL REFERENCES opponent_players(opponent_player_id),
    inning INTEGER NOT NULL,
    outs_at_entry INTEGER NOT NULL,
    pitch_sequence_at_entry INTEGER NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id),
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_opponent_lineup_substitutions_game_id ON opponent_lineup_substitutions (game_id);
CREATE TABLE IF NOT EXISTS opponent_lineup_restarts (
    restart_id SERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
    pitch_sequence_at_entry INTEGER NOT NULL,
    inning INTEGER NOT NULL,
    created_by_user_id INTEGER REFERENCES users(user_id),
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_opponent_lineup_restarts_game_id ON opponent_lineup_restarts (game_id);
ALTER TABLE opponent_lineup_substitutions ENABLE ROW LEVEL SECURITY;
ALTER TABLE opponent_lineup_restarts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON opponent_lineup_substitutions, opponent_lineup_restarts FROM anon, authenticated;
"""


def main():
    with engine.begin() as conn:
        conn.execute(text(SQL))
    print("opponent_lineup_substitutions + opponent_lineup_restarts ready.")


if __name__ == "__main__":
    main()
