"""
GBO -- Migration: pitch_cards (Oct 2026, pre-game Pitch Calling Cards).

Run once, after pulling this update:
    python3 -m migrations.migrate_pitch_cards

Additive only -- one new table (models.PitchCard). Until it exists the
Pitch Calling Cards page still builds and prints cards; it just can't
save edits, and Card vs Calls compares against a freshly built card.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating pitch_cards...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pitch_cards (
                card_id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                pitcher_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
                data JSON NOT NULL,
                updated_by_user_id INTEGER REFERENCES users(user_id),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                CONSTRAINT uq_pitch_card_game_pitcher UNIQUE (game_id, pitcher_id)
            )
        """))
    print("Done. Pitch Calling Cards can now be saved.")


if __name__ == "__main__":
    main()
