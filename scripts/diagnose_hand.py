"""
Diagnostic: why does a pitcher's game report still show no pitches vs
a given hand, when Ryker knows a specific batter of that hand faced
them?

Prints, for a given pitcher name and batter name:
  1. The batter's roster record(s) (Player and/or OpponentPlayer) and
     their bats value -- confirms whether the roster data is actually
     set the way Ryker expects.
  2. Every GamePitch where that pitcher was pitching (is_our_team_batting
     == False) and that batter is linked via opponent_our_player_id or
     opponent_player_id -- shows the CURRENT opponent_hand stored on
     each pitch, and whether it's linked to the batter by ID at all
     (a pitch tracked without picking a specific batter from a
     dropdown would have neither ID set, and the backfill script can't
     touch it no matter what the roster says).

Usage:
    python3 scripts/diagnose_hand.py "Shane Holman" "Luke Clayton"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session
from models import GamePitch, Player, OpponentPlayer, Game


def find_players(db, name):
    parts = name.strip().split()
    first, last = parts[0], parts[-1]
    our = (
        db.query(Player)
        .filter(Player.first_name.ilike(f"%{first}%"), Player.last_name.ilike(f"%{last}%"))
        .all()
    )
    opp = db.query(OpponentPlayer).filter(OpponentPlayer.player_name.ilike(f"%{name}%")).all()
    return our, opp


def main(pitcher_name, batter_name):
    db = get_session()
    try:
        p_our, p_opp = find_players(db, pitcher_name)
        b_our, b_opp = find_players(db, batter_name)

        print(f"=== Pitcher match(es) for '{pitcher_name}' ===")
        for p in p_our:
            print(f"  Player #{p.player_id}: {p.first_name} {p.last_name}  throws={p.throws!r}")
        for p in p_opp:
            print(f"  OpponentPlayer #{p.opponent_player_id}: {p.player_name}  throws={p.throws!r}")
        if not p_our and not p_opp:
            print("  NO MATCH FOUND -- check spelling/roster.")

        print(f"\n=== Batter match(es) for '{batter_name}' ===")
        for p in b_our:
            print(f"  Player #{p.player_id}: {p.first_name} {p.last_name}  bats={p.bats!r}")
        for p in b_opp:
            print(f"  OpponentPlayer #{p.opponent_player_id}: {p.player_name}  bats={p.bats!r}")
        if not b_our and not b_opp:
            print("  NO MATCH FOUND -- check spelling/roster.")

        pitcher_ids = [p.player_id for p in p_our]
        batter_our_ids = [p.player_id for p in b_our]
        batter_opp_ids = [p.opponent_player_id for p in b_opp]

        if not pitcher_ids:
            print("\nCan't look up pitches -- pitcher not found in our roster (Player table).")
            return

        pitches = (
            db.query(GamePitch)
            .filter(GamePitch.our_player_id.in_(pitcher_ids))
            .filter(GamePitch.is_our_team_batting.is_(False))
            .all()
        )
        games = {g.game_id: g for g in db.query(Game).all()}

        print(f"\n=== All pitches thrown by {pitcher_name} ({len(pitches)} total) ===")
        matched = 0
        for p in sorted(pitches, key=lambda x: (x.game_id, x.pitch_sequence)):
            is_this_batter = (
                (p.opponent_our_player_id in batter_our_ids and batter_our_ids)
                or (p.opponent_player_id in batter_opp_ids and batter_opp_ids)
            )
            if is_this_batter:
                matched += 1
                game = games.get(p.game_id)
                print(
                    f"  MATCH  game={p.game_id} ({game.game_date if game else '?'}) "
                    f"pitch_seq={p.pitch_sequence}  opponent_hand={p.opponent_hand!r}  "
                    f"opponent_our_player_id={p.opponent_our_player_id}  opponent_player_id={p.opponent_player_id}"
                )
        if matched == 0:
            print(
                f"  NO pitches link to {batter_name} by ID at all. Either they never faced each "
                f"other, or those pitches were tracked without selecting {batter_name} from the "
                f"batter dropdown (opponent_our_player_id/opponent_player_id both blank) -- in "
                f"which case the backfill script has nothing to attach the roster's bats value to, "
                f"no matter what bats says."
            )

        # Also show a distinct-hand breakdown across ALL this pitcher's pitches, for context.
        hands = {}
        for p in pitches:
            hands[p.opponent_hand] = hands.get(p.opponent_hand, 0) + 1
        print(f"\n=== opponent_hand distribution across all of {pitcher_name}'s pitches ===")
        for hand, count in sorted(hands.items(), key=lambda kv: (kv[0] is None, kv[0])):
            print(f"  {hand!r}: {count}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print('Usage: python3 scripts/diagnose_hand.py "Pitcher Name" "Batter Name"')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
