"""
One-time backfill: correct GamePitch.opponent_hand on already-tracked
games, now that roster Bats/Throws data has been filled in.

Ryker, Sept 2026: "why is it not recognizing hitters based on their
hitting hand. it shows every hitter as right handed" -- traced to
game_tracking.py's live-tracking hand radio defaulting to "R" whenever
Player.bats/OpponentPlayer.bats (or, for the pitcher side below,
.throws) was blank at the time a pitch was recorded (see
who_is_up_hand_and_order()'s default_hand logic). That default gets
saved permanently onto GamePitch.opponent_hand and is never recomputed
later -- this script is the one-time catch-up now that the roster is
filled in.

opponent_hand does double duty (see models.py's GamePitch docstring):
  - is_our_team_batting == False: we're pitching, opponent_hand = the
    BATTER's hand -- the one Ryker originally flagged (Pitcher Game
    Report showing every hitter as right-handed). Sourced from
    Player.bats (intrasquad batter) / OpponentPlayer.bats (real
    opponent batter). Switch hitters (bats == "S") are skipped --
    there's no way to know from roster data alone which side a switch
    hitter actually batted from in a specific plate appearance, so
    guessing would be worse than leaving whatever was tracked live.
  - is_our_team_batting == True: we're batting, opponent_hand = the
    opposing PITCHER's throwing hand -- the parallel issue this
    script's batter mode originally just flagged the count of.
    Sourced from Player.throws (intrasquad pitcher) /
    OpponentPlayer.throws (real opponent pitcher). No switch-pitcher
    concept, so nothing to skip there beyond a blank value.

Common to both modes:
  - Only R/L values are ever written. A blank/None value on file
    leaves the existing opponent_hand untouched (no better information
    to fall back on).
  - Rows already matching the roster's value are left alone (no no-op
    write).

Safety: dry run by default -- prints every change it WOULD make,
grouped by game, without writing anything. Re-run with --apply once
the printed report looks right.

Usage:
    python3 scripts/backfill_opponent_hand.py                        # dry run, batter hand
    python3 scripts/backfill_opponent_hand.py --apply                # writes batter-hand changes
    python3 scripts/backfill_opponent_hand.py --side pitcher          # dry run, pitcher hand
    python3 scripts/backfill_opponent_hand.py --side pitcher --apply  # writes pitcher-hand changes
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

SIDE_CONFIG = {
    "batter": {
        "is_our_team_batting": False,
        "field": "bats",
        "skip_switch": True,
        "role_label": "batter",
        "scope_label": "we're pitching, batter identified",
    },
    "pitcher": {
        "is_our_team_batting": True,
        "field": "throws",
        "skip_switch": False,
        "role_label": "pitcher",
        "scope_label": "we're batting, opposing pitcher identified",
    },
}


def main(side: str, apply: bool):
    cfg = SIDE_CONFIG[side]
    db = get_session()
    try:
        pitches = (
            db.query(GamePitch)
            .filter(GamePitch.is_our_team_batting.is_(cfg["is_our_team_batting"]))
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

        # For the "the other side has this too" cross-reference callout.
        other_side = "pitcher" if side == "batter" else "batter"
        other_cfg = SIDE_CONFIG[other_side]
        other_count = (
            db.query(GamePitch)
            .filter(GamePitch.is_our_team_batting.is_(other_cfg["is_our_team_batting"]))
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
            hand = None
            source = None
            if p.opponent_our_player_id is not None:
                player = our_players.get(p.opponent_our_player_id)
                if player is not None:
                    hand = getattr(player, cfg["field"])
                    source = f"{player.first_name} {player.last_name} (our roster)"
            elif p.opponent_player_id is not None:
                opp = opp_players.get(p.opponent_player_id)
                if opp is not None:
                    hand = getattr(opp, cfg["field"])
                    source = f"{opp.player_name} (opponent roster)"

            if cfg["skip_switch"] and hand == "S":
                skipped_switch += 1
                continue
            if hand not in ("R", "L"):
                skipped_no_data += 1
                continue
            if hand == p.opponent_hand:
                continue  # already correct, nothing to do

            changes.append((p, hand, source))

        by_game = defaultdict(list)
        for p, new_hand, source in changes:
            by_game[p.game_id].append((p, new_hand, source))

        print(f"Mode: {side} hand ({cfg['field']})")
        print(f"{len(pitches)} pitches in scope ({cfg['scope_label']})")
        if cfg["skip_switch"]:
            print(f"{skipped_switch} skipped (switch hitter -- can't infer which side without game context)")
        print(f"{skipped_no_data} skipped (no {cfg['field']} on file for that {cfg['role_label']})")
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

        if other_count:
            print(
                f"\nNote: {other_count} pitch(es) on the {other_side} side ({other_cfg['scope_label']}) "
                f"also have an opponent_hand that could have the same stale-default problem -- run with "
                f"--side {other_side} to backfill those."
            )
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", choices=["batter", "pitcher"], default="batter", help="Which hand to backfill (default: batter)")
    parser.add_argument("--apply", action="store_true", help="Actually write the changes (default: dry run only)")
    args = parser.parse_args()
    main(side=args.side, apply=args.apply)
