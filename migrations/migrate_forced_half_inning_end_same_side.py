"""
GBO -- Migration: add game_forced_half_inning_ends.same_side_continues.

Run once, after pulling this update.

"End half-inning early" originally always flipped is_our_team_batting
when folded into replay_game/compute_current_state (game_tracking.py),
on the assumption that ending a half-inning always means the OTHER
side comes up next -- true for a normal 2-squad game. But the
feature's own original motivating example (Kurt Kassner: a pitcher
hits his pitch count and the team rotates to the next pitcher AND next
lineup) turns out to be a case where the SAME side/squad keeps
pitching, just against a fresh batting order -- flipping in that case
corrupts every pitch after it (is_our_team_batting no longer matches
which id column -- our_player_id vs. opponent_our_player_id -- holds
the batter, so pitchers show up as hitters and vice versa in every
pitching/hitting stat view; this is exactly what happened on game 14,
Sept 2026, after using the existing feature for this scenario).

This adds same_side_continues (NOT NULL, default FALSE, so every
existing row keeps flipping exactly as before) so a coach can mark a
specific forced end as "same team continues" instead, for three-squad
pitch-count rotations. See replay_game/compute_current_state in
game_tracking.py for how it's folded in, and
GameForcedHalfInningEnd's docstring in models.py.

Run from the repo root:
    python -m migrations.migrate_forced_half_inning_end_same_side
"""

from sqlalchemy import text
from database import engine


def main():
    print("Adding game_forced_half_inning_ends.same_side_continues...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_forced_half_inning_ends "
            "ADD COLUMN IF NOT EXISTS same_side_continues BOOLEAN NOT NULL DEFAULT FALSE"
        ))
    print("Done. Every existing forced-half-inning-end row keeps flipping sides exactly as")
    print("before (same_side_continues=False) -- nothing about past games changes until a")
    print("coach explicitly picks the new 'same team continues' option going forward.")


if __name__ == "__main__":
    main()
