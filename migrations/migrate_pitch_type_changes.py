"""
GBO -- Migration: add pitch_type_changes table (Fastball Shape Check).

Run once, after pulling this update:
    python -m migrations.migrate_pitch_type_changes

Additive only -- creates the audit/undo log behind the Fastball Shape
Check's "switch" action (see models.PitchTypeChange). No existing table
or row is touched. Foreign keys to rapsodo_pitches/game_pitches are
ON DELETE SET NULL so this log never blocks deleting a game, a pitch, or
a Rapsodo import.
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating pitch_type_changes...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS pitch_type_changes (
                pitch_type_change_id SERIAL PRIMARY KEY,
                rapsodo_pitch_id INTEGER REFERENCES rapsodo_pitches(rapsodo_pitch_id) ON DELETE SET NULL,
                game_pitch_id INTEGER REFERENCES game_pitches(game_pitch_id) ON DELETE SET NULL,
                player_id INTEGER REFERENCES players(player_id),
                from_rapsodo_pitch_type_id INTEGER REFERENCES pitch_types(pitch_type_id),
                from_game_pitch_type_id INTEGER REFERENCES pitch_types(pitch_type_id),
                to_pitch_type_id INTEGER NOT NULL REFERENCES pitch_types(pitch_type_id),
                source VARCHAR(30) NOT NULL DEFAULT 'shape_check',
                reason TEXT,
                changed_by_user_id INTEGER REFERENCES users(user_id),
                changed_at TIMESTAMP NOT NULL DEFAULT NOW(),
                undone_at TIMESTAMP
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_pitch_type_changes_player ON pitch_type_changes(player_id)"))
    print("Done. The Fastball Shape Check's Switch/Undo buttons on Pitcher Profile now work.")


if __name__ == "__main__":
    main()
