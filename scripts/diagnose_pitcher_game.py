"""
Diagnostic: a pitcher's Game Report undercounts innings pitched, or is
missing whole at-bats vs a given hand, even though the coach knows the
real outs/at-bats happened (Ryker, Sept 2026, re: Kurt Kassner -- "got
two outs, a popout and a strikeout but when i look at his game report
it says he only threw 0.1 inning" / "it is only showing 3 pitches vs
right handed hitters... he faced 2 right handed hitters, the first
hitter saw 3 pitches, why is the other at bat not showing up").

get_pitching_pitches() (game_stats.py) -- the function every pitching
stat view in this app (game report, analytics, dashboard) is built on
-- decides "was this player pitching on this pitch" purely from two
fields: is_our_team_batting and our_player_id/opponent_our_player_id.
replay_game() (game_tracking.py) recomputes is_our_team_batting for
every pitch after any edit, forced-half-inning-end, or runner event,
but deliberately does NOT reassign our_player_id/opponent_our_player_id
to match (that's flagged as a "review manually" warning in the preview
UI instead, per its own docstring). So if a GameForcedHalfInningEnd or
a Pitch Log edit ended up anchored earlier in the half-inning than it
should have been, every pitch after that anchor -- including pitches
this pitcher genuinely threw -- can have is_our_team_batting flipped
out from under it, while our_player_id still points at him. The pitch
doesn't disappear from the database; it just silently stops looking,
to get_pitching_pitches, like a pitch this player pitched.

This script does not guess at a fix -- it just dumps the raw rows,
clearly labeled, so you can match them against what you know actually
happened in the game and tell me exactly which pitch(es) are wrong.

Usage:
    python3 scripts/diagnose_pitcher_game.py "Kurt Kassner"
    python3 scripts/diagnose_pitcher_game.py "Kurt Kassner" 42   # just game 42
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session
from models import GamePitch, GameForcedHalfInningEnd, Player, Game
from game_stats import get_pitching_pitches


def find_player(db, name):
    parts = name.strip().split()
    first, last = parts[0], parts[-1]
    return (
        db.query(Player)
        .filter(Player.first_name.ilike(f"%{first}%"), Player.last_name.ilike(f"%{last}%"))
        .all()
    )


def main(name, game_id=None):
    db = get_session()
    try:
        matches = find_player(db, name)
        if not matches:
            print(f"NO MATCH for '{name}' in Player table -- check spelling/roster.")
            return
        if len(matches) > 1:
            print(
                "Multiple Player matches for '%s': %s"
                % (name, ", ".join(f"#{p.player_id} {p.first_name} {p.last_name}" for p in matches))
            )
            print("Using the first one below; pass a game_id as a 2nd argument to narrow if needed.")
        player = matches[0]
        pid = player.player_id
        print(f"=== Using Player #{pid}: {player.first_name} {player.last_name} ===")

        # Every game where this player shows up as our_player_id on ANY
        # pitch -- pitching or (if something's already gone wrong)
        # miscategorized as batting.
        q = db.query(GamePitch.game_id).filter(GamePitch.our_player_id == pid).distinct()
        if game_id is not None:
            q = q.filter(GamePitch.game_id == int(game_id))
        game_ids = sorted(row[0] for row in q.all())
        if not game_ids:
            print(f"No GamePitch rows at all have our_player_id={pid}.")
            return

        games = {g.game_id: g for g in db.query(Game).filter(Game.game_id.in_(game_ids)).all()}
        pitching_pitch_ids_all = {p.game_pitch_id for p in get_pitching_pitches(db, pid)}

        for gid in game_ids:
            game = games.get(gid)
            label = f"Game #{gid}"
            if game is not None:
                kind = "intrasquad" if game.is_intrasquad else (game.opponent_name or "opponent")
                label += f" ({game.game_date}, {kind})"
            print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")

            all_pitches = (
                db.query(GamePitch)
                .filter(GamePitch.game_id == gid)
                .order_by(GamePitch.pitch_sequence)
                .all()
            )
            forced_ends = (
                db.query(GameForcedHalfInningEnd)
                .filter(GameForcedHalfInningEnd.game_id == gid)
                .order_by(GameForcedHalfInningEnd.pitch_sequence_after)
                .all()
            )
            forced_end_anchors = {fe.pitch_sequence_after for fe in forced_ends}

            print(f"\n-- All {len(all_pitches)} pitches in this game --")
            header = (
                f"{'seq':>4} {'inn':>3} {'ourBat':>6} {'our_pid':>7} {'opp_our':>7} {'opp_pid':>7} "
                f"{'hand':>4} {'outsB':>5} {'outsA':>5} {'endsPA':>6} {'ab_outcome':>14}   note"
            )
            print(header)
            for p in all_pitches:
                is_this_player_row = p.our_player_id == pid
                note = ""
                if is_this_player_row:
                    if p.is_our_team_batting is False:
                        pitching_flag = (
                            "counted as pitching"
                            if p.game_pitch_id in pitching_pitch_ids_all
                            else "*** our_player_id=this player, is_our_team_batting=False, but NOT in get_pitching_pitches -- shouldn't be possible, investigate ***"
                        )
                        note = pitching_flag
                    else:
                        note = (
                            "*** our_player_id=this player but is_our_team_batting=TRUE -- "
                            "this pitch will show up in his BATTING stats, not pitching, and "
                            "will NOT count toward his innings pitched ***"
                        )
                if p.pitch_sequence in forced_end_anchors:
                    note = (note + "  " if note else "") + "<-- a GameForcedHalfInningEnd is anchored right after this pitch"
                print(
                    f"{p.pitch_sequence:>4} {p.inning:>3} {str(p.is_our_team_batting):>6} {p.our_player_id:>7} "
                    f"{str(p.opponent_our_player_id):>7} {str(p.opponent_player_id):>7} {str(p.opponent_hand):>4} "
                    f"{str(p.outs_before):>5} {str(p.outs_after):>5} {str(p.ends_plate_appearance):>6} "
                    f"{str(p.ab_outcome):>14}   {note}"
                )

            if forced_ends:
                print(f"\n-- {len(forced_ends)} GameForcedHalfInningEnd row(s) for this game --")
                for fe in forced_ends:
                    print(
                        f"  after pitch_seq={fe.pitch_sequence_after}  inning={fe.inning}  "
                        f"is_our_team_batting={fe.is_our_team_batting}  batting_squad={fe.batting_squad}  "
                        f"runs_scored={fe.runs_scored}  credited_player_id={fe.credited_player_id}"
                    )
            else:
                print("\n-- No GameForcedHalfInningEnd rows for this game --")

        pitching_pitches_this_player = [p for p in get_pitching_pitches(db, pid) if game_id is None or p.game_id == int(game_id)]
        outs_recorded = sum(
            (p.outs_after - p.outs_before)
            for p in pitching_pitches_this_player
            if p.ends_plate_appearance and p.outs_before is not None and p.outs_after is not None
        )
        print(f"\n{'=' * 78}")
        print(
            f"get_pitching_pitches() currently counts {len(pitching_pitches_this_player)} pitch(es) "
            f"for {player.first_name} {player.last_name}"
            + (f" in game {game_id}" if game_id is not None else " across all games")
            + f", totaling {outs_recorded} out(s) recorded on plate-appearance-ending pitches "
            f"(this is exactly the number the Game Report's innings-pitched figure is built from)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print('Usage: python3 scripts/diagnose_pitcher_game.py "Player Name" [game_id]')
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None)
