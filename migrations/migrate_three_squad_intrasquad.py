"""
GBO — Migration: add three-team intrasquad support.

Some intrasquad scrimmages use THREE squads (7-8 players each) rotating
through -- one squad bats while the other two share the field, then it
rotates -- rather than the existing two-squad Team A vs Team B format.
This migration is deliberately ADDITIVE: it does not touch the existing
two-squad intrasquad flow (is_our_team_batting's plain True/False
alternation, our_score/opponent_score) at all. It just unlocks a THIRD
roster and score bucket, gated behind a new opt-in flag per game.

Adds:
  - games.uses_three_squad_intrasquad (Boolean, default False) -- opt-in
    flag set at game creation. False for every existing game, including
    ordinary two-squad intrasquad games, which are entirely unaffected.
  - games.squad_c_score (Integer, default 0) -- Squad C's running total,
    mirroring our_score/opponent_score (which continue to hold Squad
    A's and Squad B's totals respectively).
  - games.squad_c_starting_pitcher_id (FK -> players.player_id) --
    mirrors squad_b_starting_pitcher_id.
  - game_pitches.batting_squad (String(1), nullable) -- 'A'/'B'/'C',
    which squad was actually batting on this pitch, in three-squad
    games only.
  - game_runner_events.batting_squad (String(1), nullable) -- same,
    for mid-PA runner events (steals, etc.) so a scored run credits the
    right one of three totals.

Squad C's roster itself needs NO schema change -- GameLineupSlot.squad
is already an unconstrained single-character column (today only 'A'/'B'
are used by convention, nothing in the schema enforces that), so Squad
C's lineup slots reuse the exact same table/mechanism Squad A and
Squad B already use.

Run once, after pulling this update. Depends on intrasquad games
(migrate_intrasquad_games.py) and Squad B's starting pitcher
(migrate_squad_b_starting_pitcher.py) already being migrated.

Run from the repo root:
    python -m migrations.migrate_three_squad_intrasquad
"""

from sqlalchemy import text
from database import engine


def main():
    print("Step 1: adding uses_three_squad_intrasquad to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS uses_three_squad_intrasquad BOOLEAN NOT NULL DEFAULT FALSE"
        ))

    print("Step 2: adding squad_c_score to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS squad_c_score INTEGER NOT NULL DEFAULT 0"
        ))

    print("Step 3: adding squad_c_starting_pitcher_id to games...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE games ADD COLUMN IF NOT EXISTS squad_c_starting_pitcher_id INTEGER REFERENCES players(player_id)"
        ))

    print("Step 4: adding batting_squad to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS batting_squad VARCHAR(1)"
        ))

    print("Step 5: adding batting_squad to game_runner_events...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_runner_events ADD COLUMN IF NOT EXISTS batting_squad VARCHAR(1)"
        ))

    print("Done.")
    print("\nMigration complete. Existing games default to uses_three_squad_intrasquad=False,")
    print("squad_c_score=0 -- entirely unaffected. Two-squad games (including existing")
    print("intrasquad games) keep working exactly as before.")


if __name__ == "__main__":
    main()
