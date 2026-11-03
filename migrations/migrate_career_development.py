"""
GBO -- Migration: Career Development (Nov 2026, Ryker). See models.py's
RapsodoHistory, SeasonPitchSplit and SeasonPitchingLine, and
career_development.py for how the Player Profile tab reads them.

Creates (nothing existing changes):
  - rapsodo_history: Rapsodo pitches from before GBO's own imports (Ryker's
    Rapsodo account back to Oct 2022, the fall 2025 intrasquad export in the
    team Drive). Kept OUT of rapsodo_pitches on purpose: ~50 analytics read
    rapsodo_pitches, several over every pitch a player has (ratings, pitch
    class, fastball shape, release comps), and old seasons would quietly
    change those numbers. Only Career Development reads this table.
  - season_pitch_splits: per-pitch-type game numbers for a term (spring 2026
    from the staff game-tracking workbooks).
  - season_pitching_lines: one leaderboard line per pitcher per term.
  - Row Level Security ON, anon/authenticated revoked (Oct 31 2026 lockdown).

Run (module form), then load the data:
    python3 -m migrations.migrate_career_development
    python3 -m scripts.import_career_history            # dry run
    python3 -m scripts.import_career_history --apply

Safe to re-run.
"""

from sqlalchemy import text
from database import engine

SQL = [
    """
    CREATE TABLE IF NOT EXISTS rapsodo_history (
        rapsodo_history_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        source VARCHAR(40) NOT NULL,
        source_uid VARCHAR(100) NOT NULL,
        pitch_date TIMESTAMP NOT NULL,
        session_key VARCHAR(100),
        session_type VARCHAR(40),
        raw_pitch_type VARCHAR(50),
        pitch_type_id INTEGER REFERENCES pitch_types(pitch_type_id),
        velocity NUMERIC(6, 2),
        total_spin NUMERIC(7, 2),
        true_spin NUMERIC(7, 2),
        spin_efficiency NUMERIC(6, 2),
        spin_confidence NUMERIC(5, 3),
        gyro_degree NUMERIC(6, 2),
        spin_axis_degrees NUMERIC(5, 1),
        vb_spin NUMERIC(6, 2),
        hb_trajectory NUMERIC(6, 2),
        release_height NUMERIC(6, 3),
        release_side NUMERIC(6, 3),
        release_extension NUMERIC(6, 3),
        is_strike BOOLEAN,
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_rapsodo_history_source UNIQUE (player_id, source, source_uid)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_rapsodo_history_player_date ON rapsodo_history(player_id, pitch_date)",
    """
    CREATE TABLE IF NOT EXISTS season_pitch_splits (
        season_pitch_split_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        term VARCHAR(20) NOT NULL,
        pitch_label VARCHAR(30) NOT NULL,
        pitches INTEGER NOT NULL,
        strike_pct NUMERIC(5, 1),
        called_pct NUMERIC(5, 1),
        swing_pct NUMERIC(5, 1),
        whiff_pct NUMERIC(5, 1),
        csw_pct NUMERIC(5, 1),
        putaway_pct NUMERIC(5, 1),
        gb_pct NUMERIC(5, 1),
        runs_saved_per_100 NUMERIC(7, 2),
        oba NUMERIC(5, 3),
        woba NUMERIC(5, 3),
        hits INTEGER,
        hr INTEGER,
        source VARCHAR(150),
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_season_pitch_split UNIQUE (player_id, term, pitch_label)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS season_pitching_lines (
        season_pitching_line_id SERIAL PRIMARY KEY,
        player_id INTEGER NOT NULL REFERENCES players(player_id) ON DELETE CASCADE,
        term VARCHAR(20) NOT NULL,
        ip NUMERIC(6, 2),
        pitches INTEGER,
        strike_pct NUMERIC(5, 1),
        fps_pct NUMERIC(5, 1),
        ea_pct NUMERIC(5, 1),
        k_pct NUMERIC(5, 1),
        whiff_pct NUMERIC(5, 1),
        csw_pct NUMERIC(5, 1),
        dominance_pct NUMERIC(5, 1),
        putaway_pct NUMERIC(5, 1),
        gb_pct NUMERIC(5, 1),
        ld_pct NUMERIC(5, 1),
        fb_pct NUMERIC(5, 1),
        oba NUMERIC(5, 3),
        woba NUMERIC(5, 3),
        runs_saved_per_100 NUMERIC(7, 2),
        era NUMERIC(6, 2),
        fip NUMERIC(6, 2),
        whip NUMERIC(5, 2),
        siera NUMERIC(6, 2),
        source VARCHAR(150),
        created_at TIMESTAMP NOT NULL DEFAULT now(),
        CONSTRAINT uq_season_pitching_line UNIQUE (player_id, term)
    )
    """,
]
for _t in ("rapsodo_history", "season_pitch_splits", "season_pitching_lines"):
    SQL += [f"ALTER TABLE {_t} ENABLE ROW LEVEL SECURITY",
            f"REVOKE ALL ON TABLE {_t} FROM anon, authenticated"]


def main():
    print("Creating rapsodo_history, season_pitch_splits, season_pitching_lines...")
    with engine.begin() as conn:
        for sql in SQL:
            conn.execute(text(sql))
    print("Done. Next: python3 -m scripts.import_career_history --apply")


if __name__ == "__main__":
    main()
