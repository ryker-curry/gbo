"""
One-time backfill: correct GamePitch.opponent_hand (BATTER hand only --
is_our_team_batting == False rows) on already-tracked games, now that
roster Bats data has been filled in.

Ryker, Sept 2026: "why is it not recognizing hitters based on their
hitting hand. it shows every hitter as right handed" -- traced to
game_tracking.py's live-tracking hand radio defaulting to "R" whenever
Player.bats/OpponentPlayer.bats was blank at the time a pitch was
recorded (see who_is_up_hand_and_order()'s default_hand logic). That
default gets saved permanently onto GamePitch.opponent_hand and is
never recomputed later -- this script is the one-time catch-up now
that the roster is filled in.

Scope: ONLY is_our_team_batting == False rows (we're pitching,
opponent_hand = the BATTER's hand) -- matches what Ryker actually
flagged (hitters showing wrong in Pitcher Game Report). Rows where
is_our_team_batting == True (opponent_hand = the opposing PITCHER's
hand, relevant to Hitter Game Report) are a separate, parallel issue
NOT touched here -- this script's summary calls out how many such rows
exist in case that's wanted too.

For each in-scope pitch:
  - intrasquad batter (opponent_our_player_id set): look up
    Player.bats.
  - external opponent batter (opponent_player_id set): look up
    OpponentPlayer.bats.
  - Switch hitters (bats == "S") are skipped -- there's no way to know
    from roster data alone which side a switch hitter actually batted
    from in a specific plate appearance, so guessing would be worse
    than leaving whatever was tracked live.
  - Only R/L values are ever written. A blank/None bats on file leaves
    the existing opponent_hand untouched (no better information to
    fall back on).
  - Rows already matching the roster's bats value are left alone (no
    no-op write).

Safety: dry run by default -- prints every change it WOULD make,
grouped by game, without writing anything. Re-run with --apply once
the printed report looks right.

Usage:
    python3 scripts/backfill_opponent_hand.py            # dry run
    python3 scripts/backfill_opponent_hand.py --apply    # writes changes
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Repo root is this script's parent directory -- add it to sys.path so
# `python3 scripts/backfill_opponent_hand.py` finds database.py/models.py
# at the repo root regardless of the caller's own working directory or
# PYTHONPATH (Ryker hit ModuleNotFoundError: No module named 'database'
# running it straight from the repo root without this).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session
from models import GamePitch, Player, OpponentPlayer, Game


def main(apply: bool):
    db = get_session()
    try:
        pitches = (
            db.query(GamePitch)
            .filter(GamePitch.is_our_team_batting.is_(False))
            .filter(
                (GamePitch.opponent_our_player_id.isnot(None))
                | (GamePitch.opponent_player_id.isnot(None))
            )
            .all()
        )

        # Preload rosters/games up front to avoid N+1 queries.
        our_players = {p.player_id: p for p in db.query(Player).all()}
        opp_players = {p.opponent_player_id: p for p in db.query(OpponentPlayer).all()}
        games = {g.game_id: g for g in db.query(Game).all()}

        # For the "how many pitcher-hand rows exist too" callout.
        pitcher_hand_count = (
            db.query(GamePitch)
            .filter(GamePitch.is_our_team_batting.is_(True))
            .filter(
                (GamePitch.opponent_our_player_id.isnot(None))
                | (GamePitch.opponent_player_id.isnot(None))
            )
            .count()
        )

        changes = []  # (pitch, new_hand, source_label)
        skipped_switch = 0
        skipped_no_data = 0

        for p in pitches:
            bats = None
            source = None
            if p.opponent_our_player_id is not None:
                player = our_players.get(p.opponent_our_player_id)
                if player is not None:
                    bats = player.bats
                    source = f"{player.first_name} {player.last_name} (our roster)"
            elif p.opponent_player_id is not None:
                opp = opp_players.get(p.opponent_player_id)
                if opp is not None:
                    bats = opp.bats
                    source = f"{opp.player_name} (opponent roster)"

            if bats == "S":
                skipped_switch += 1
                continue
            if bats not in ("R", "L"):
                skipped_no_data += 1
                continue
            if bats == p.opponent_hand:
                continue  # already correct, nothing to do

            changes.append((p, bats, source))

        by_game = defaultdict(list)
        for p, new_hand, source in changes:
            by_game[p.game_id].append((p, new_hand, source))

        print(f"{len(pitches)} pitches in scope (we're pitching, batter identified)")
        print(f"{skipped_switch} skipped (switch hitter -- can't infer which side without game context)")
        print(f"{skipped_no_data} skipped (no bats on file for that batter)")
        print(f"{len(changes)} pitch(es) to correct, across {len(by_game)} game(s)\n")

        for game_id, rows in sorted(by_game.items()):
            game = games.get(game_id)
            label = f"Game {game_id}" if game is None else f"Game {game_id} ({game.game_date}, {'intrasquad' if game.is_intrasquad else game.opponent_name or 'opponent'})"
            print(label)
            for p, new_hand, source in rows:
                old = p.opponent_hand or "(blank)"
                print(f"  pitch_sequence={p.pitch_sequence}: {old} -> {new_hand}  [{source}]")
                if apply:
                    p.opponent_hand = new_hand
            print()

        if apply:
            db.commit()
            print(f"Applied. {len(changes)} row(s) updated.")
        else:
            print("DRY RUN -- nothing written. Re-run with --apply to save these changes.")

        if pitcher_hand_count:
            print(
                f"\nNote: {pitcher_hand_count} pitch(es) where we're BATTING also have an "
                "opponent_hand (the opposing pitcher's throwing hand) that could have the same "
                "stale-default problem -- not touched by this script since Ryker only flagged "
                "hitters. Let me know if that should be backfilled too."
            )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually write the changes (default: dry run only)")
    args = parser.parse_args()
    main(apply=args.apply)
