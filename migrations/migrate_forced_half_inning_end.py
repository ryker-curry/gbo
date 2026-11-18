"""
GBO -- Migration: add game_forced_half_inning_ends table.

Run once, after pulling this update.

Adds the table backing the "End half-inning early" control (Ryker,
Sept 2026: "i also need the ability to end the inning during
intrasquads even if 3 outs haven't been achieved because some innings
may be ended due to pitch counts... i need to be able to click
something that ends that inning where it was and moves on to the
next" -- with a real example: Kurt Kassner's outing ended on a pitch
count with runners left on base, and the team just moved on to the
next pitcher/lineup without recording the outs that would have been
needed to end the half-inning normally). And, from the same
conversation: "also, if there are runners on base when the half
innings ends those runs score and count towards era" -- so this table
also records who gets charged and how many runs.

See models.py's GameForcedHalfInningEnd docstring for the full design
(same pitch_sequence_after-anchored pattern PitchingChange/
LineupSubstitution/GameRunnerEvent already use), and game_tracking.py's
compute_current_state()/replay_game() for how it's folded into live
tracking and historical recompute.

Additive only -- no existing table or row is touched. Existing games
get zero rows here (no forced-inning-ends recorded retroactively until
a coach adds one through the app), so nothing about how they display
or score changes until that happens.

Run from the repo root:
    python -m migrations.migrate_forced_half_inning_end
"""

from sqlalchemy import text
from database import engine


def main():
    print("Creating game_forced_half_inning_ends...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS game_forced_half_inning_ends (
                forced_end_id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                pitch_sequence_after INTEGER NOT NULL,
                inning INTEGER NOT NULL,
                is_our_team_batting BOOLEAN NOT NULL,
                batting_squad VARCHAR(1),
                runs_scored INTEGER NOT NULL DEFAULT 0,
                credited_player_id INTEGER REFERENCES players(player_id),
                notes TEXT,
                created_by_user_id INTEGER REFERENCES users(user_id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
    print("Done.")

    print("\nMigration complete. No existing games are affected -- the 'End half-inning early'")
    print("control (live, and retroactively via Pitch Log) becomes available for intrasquad")
    print("games going forward, and for fixing already-tracked intrasquad games like the one")
    print("Ryker described (a pitcher's outing ending on a pitch count with runners left on base).")


if __name__ == "__main__":
    main()
