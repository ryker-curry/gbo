"""
GBO — Migration: add game_pitches.unearned_runs_on_play.

Run once, after pulling this update.

Adds one integer column so a coach can tag, per play, how many of that
play's runs_scored_on_play were UNEARNED (an error caused them) --
manual entry, defaulting to 0 (i.e. "all earned"), the same "human
judgment, not an automated rules engine" philosophy GamePitch already
uses for base/out state. See models.py's GamePitch.unearned_runs_on_play
and .earned_runs_on_play for the full reasoning.

Additive only -- every existing game_pitches row gets
unearned_runs_on_play=0 by default (i.e. every historical run stays
counted as earned, same as GBO's runs-allowed-average "ERA" always
treated it), nothing else changes.

Run:
    python migrate_unearned_runs.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding game_pitches.unearned_runs_on_play...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS unearned_runs_on_play INTEGER NOT NULL DEFAULT 0"
        ))
    print("Done. No existing game_pitches rows changed in effect (all default to 0 unearned, i.e. all-earned).")


if __name__ == "__main__":
    main()
