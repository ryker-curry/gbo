"""
GBO -- Migration: SmartPark (WIN Reality / Yakkertech) game import (Oct 2026).

Run once, after pulling this update:
    python3 -m migrations.migrate_smartpark

Creates (nothing existing changes):
  - smartpark_imports        one row per uploaded game file
  - smartpark_pitches        every pitch's raw tracking readings
  - smartpark_player_links   remembered name -> roster player matches
Row Level Security is turned ON with no policies (same as the WHOOP tables),
so the public API key can't read them; GBO's own database login is unaffected.

Safe to re-run.
"""

from sqlalchemy import text
from database import engine

_FLOAT_COLS = [
    "rel_speed", "spin_rate", "spin_axis", "spin_efficiency", "rel_height", "rel_side", "extension",
    "vert_rel_angle", "horz_rel_angle", "induced_vert_break", "horz_break", "vert_break",
    "plate_loc_height", "plate_loc_side", "zone_speed", "vert_appr_angle", "horz_appr_angle",
    "exit_speed", "launch_angle", "direction", "distance", "hit_spin_rate", "hang_time", "bat_speed",
    "plate_x_ft", "plate_z_ft",
]

TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS smartpark_imports (
        import_id SERIAL PRIMARY KEY,
        game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
        original_filename VARCHAR(255) NOT NULL,
        file_hash VARCHAR(64) NOT NULL,
        source_game_uid VARCHAR(100),
        uploaded_by_user_id INTEGER NOT NULL REFERENCES users(user_id),
        uploaded_at TIMESTAMP NOT NULL DEFAULT now(),
        row_count INTEGER NOT NULL,
        pitch_count INTEGER NOT NULL DEFAULT 0,
        status VARCHAR(20) NOT NULL,
        warnings TEXT,
        CONSTRAINT uq_smartpark_import_hash UNIQUE (file_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS smartpark_pitches (
        smartpark_pitch_id SERIAL PRIMARY KEY,
        import_id INTEGER NOT NULL REFERENCES smartpark_imports(import_id) ON DELETE CASCADE,
        game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
        game_pitch_id INTEGER REFERENCES game_pitches(game_pitch_id) ON DELETE SET NULL,
        pitcher_player_id INTEGER REFERENCES players(player_id),
        batter_player_id INTEGER REFERENCES players(player_id),
        pitch_type_id INTEGER REFERENCES pitch_types(pitch_type_id),
        pitch_no INTEGER,
        source_pitch_uid VARCHAR(100),
        pitch_time TIMESTAMP,
        inning INTEGER,
        top_bottom VARCHAR(10),
        pa_of_inning INTEGER,
        pitch_of_pa INTEGER,
        outs INTEGER,
        balls INTEGER,
        strikes INTEGER,
        pitcher_name VARCHAR(150),
        pitcher_source_id VARCHAR(50),
        pitcher_throws VARCHAR(10),
        pitcher_team VARCHAR(100),
        batter_name VARCHAR(150),
        batter_source_id VARCHAR(50),
        batter_side VARCHAR(10),
        batter_team VARCHAR(100),
        tagged_pitch_type VARCHAR(50),
        auto_pitch_type VARCHAR(50),
        pitch_call VARCHAR(40),
        kor_bb VARCHAR(20),
        tagged_hit_type VARCHAR(30),
        play_result VARCHAR(30),
        outs_on_play INTEGER,
        runs_scored INTEGER,
        tilt VARCHAR(10),
        """ + ",\n        ".join(f"{c} DOUBLE PRECISION" for c in _FLOAT_COLS) + """,
        raw_extra JSON,
        created_at TIMESTAMP NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_smartpark_pitches_import_id ON smartpark_pitches(import_id)",
    "CREATE INDEX IF NOT EXISTS ix_smartpark_pitches_game_id ON smartpark_pitches(game_id)",
    "CREATE INDEX IF NOT EXISTS ix_smartpark_pitches_game_pitch_id ON smartpark_pitches(game_pitch_id)",
    "CREATE INDEX IF NOT EXISTS ix_smartpark_pitches_pitcher_player_id ON smartpark_pitches(pitcher_player_id)",
    "CREATE INDEX IF NOT EXISTS ix_smartpark_pitches_batter_player_id ON smartpark_pitches(batter_player_id)",
    """
    CREATE TABLE IF NOT EXISTS smartpark_player_links (
        link_id SERIAL PRIMARY KEY,
        source_key VARCHAR(200) NOT NULL,
        source_name VARCHAR(150),
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_smartpark_player_link_key UNIQUE (source_key)
    )
    """,
]

RLS_TABLES = ["smartpark_imports", "smartpark_pitches", "smartpark_player_links"]


def main():
    print("Creating SmartPark tables...")
    with engine.begin() as conn:
        for sql in TABLES_SQL:
            conn.execute(text(sql))
        for t in RLS_TABLES:
            conn.execute(text(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY"))
    print("Done.")


if __name__ == "__main__":
    main()
