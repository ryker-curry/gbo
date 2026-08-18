"""
GBO — Migration: add lineup_substitutions table + game_pitches.batting_slot_id.

Batting substitutions were never possible: once a squad's starting
lineup was saved, Game Tracking's Lineup & Setup UI hid itself entirely
and the live "who's up" picker only ever offered whoever was in that
original saved GameLineupSlot set -- for either squad, in intrasquad
scrimmages OR real external games. This blocked pinch hitters,
defensive substitutes who needed a bat, and "extra hitters" cycling
through a scrimmage to get everyone reps. Pitching substitutions never
had this problem (any active pitcher, any time, via pitching_changes).

This migration adds:
  1. lineup_substitutions -- mirrors pitching_changes' "a start + an
     ordered list of changes, most-recent-wins" shape, but scoped to a
     single game_lineup_slots row rather than the whole team, since
     batting has many simultaneous "current occupants" (one per
     batting-order slot) instead of a single pitcher role. See
     models.py's LineupSubstitution docstring for the full design
     rationale.
  2. game_pitches.batting_slot_id -- which lineup slot the batter
     occupied at the moment a pitch was recorded, so "who's up next"
     can look up the next slot directly instead of re-matching by
     player identity (which breaks once a player can be subbed out and
     later re-enter the same slot).

Adding a brand-new slot that wasn't part of the original lineup (an
"extra hitter") doesn't need a schema change at all -- it's just
another game_lineup_slots row, inserted at any batting_order position
(existing slots renumbered +1 from that point on -- safe, since every
reference to a slot points at lineup_slot_id, never at the mutable
batting_order value).

Run once, after pulling this update. Depends on Game Tracking and
intrasquad games (migrate_intrasquad_games.py) already being migrated.

Run from the repo root:
    python -m migrations.migrate_lineup_substitutions
"""

from sqlalchemy import text
from database import engine


def main():
    print("Step 1: creating lineup_substitutions...")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS lineup_substitutions (
                lineup_substitution_id SERIAL PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(game_id) ON DELETE CASCADE,
                lineup_slot_id INTEGER NOT NULL REFERENCES game_lineup_slots(lineup_slot_id) ON DELETE CASCADE,
                player_id INTEGER NOT NULL REFERENCES players(player_id),
                inning INTEGER NOT NULL,
                outs_at_entry INTEGER NOT NULL,
                pitch_sequence_at_entry INTEGER NOT NULL,
                new_position_id INTEGER REFERENCES positions(position_id),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """))
    print("Done.")

    print("\nStep 2: adding batting_slot_id to game_pitches...")
    with engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS batting_slot_id "
            "INTEGER REFERENCES game_lineup_slots(lineup_slot_id)"
        ))
    print("Done.")

    print("\nMigration complete. Existing games are unaffected -- no lineup_substitutions rows yet,")
    print("and every existing game_pitches row defaults batting_slot_id=NULL (game_tracking.py's")
    print("suggest_next_our_batter/suggest_next_squad_b_batter fall back to identity-matching for")
    print("those older pitches). Substitutions and mid-order slot additions become available on")
    print("Game Tracking's Live Tracking tab for any game going forward.")


if __name__ == "__main__":
    main()
