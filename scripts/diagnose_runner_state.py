"""
Diagnostic: reconstruct a pitcher's outing pitch-by-pitch, interleaved
with any GameRunnerEvent rows recorded during it, so a base-state
discrepancy (e.g., "only one runner shows on base when there should be
two") can be tracked back to the exact pitch/event where it goes wrong.

Uses game_stats.get_pitching_pitches for pitcher attribution -- the
same helper every other pitcher-outing script this session has used --
rather than re-deriving is_our_team_batting/opponent_our_player_id
matching by hand, since that attribution has had real bugs before.

Read-only -- makes no changes.

Usage:
    python3 scripts/diagnose_runner_state.py "<pitcher name>" <game_date YYYY-MM-DD>

    e.g. python3 scripts/diagnose_runner_state.py "Porter Starnes" 2026-09-08
"""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from database import get_session
from game_stats import get_pitching_pitches
from models import Player, Game, GameRunnerEvent


def base_str(bases):
    """'101' -> '1st, 3rd' style label; '000'/None -> 'empty'."""
    labels = []
    for i, c in enumerate(bases or "000"):
        if c == "1":
            labels.append(["1st", "2nd", "3rd"][i])
    return ", ".join(labels) if labels else "empty"


def event_label(ev, base_label):
    who = None
    if ev.our_player_id and ev.our_player:
        who = f"{ev.our_player.first_name} {ev.our_player.last_name}"
    elif ev.opponent_player_id and ev.opponent_player:
        who = ev.opponent_player.player_name
    outcome = "out" if ev.is_out else {2: "2nd", 3: "3rd", 4: "home"}.get(ev.to_base, "?")
    return f"{ev.event_type} -- {who or '(unspecified)'} {base_label.get(ev.from_base, '?')} -> {outcome}"


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" <game_date YYYY-MM-DD>')
        sys.exit(1)
    name_query = args[0].strip().lower()
    try:
        game_date = datetime.strptime(args[1].strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Couldn't parse date '{args[1]}' -- use YYYY-MM-DD.")
        sys.exit(1)

    db = get_session()
    try:
        players = [p for p in db.query(Player).all() if name_query in f"{p.first_name} {p.last_name}".lower()]
        if not players:
            print(f"No roster player matching '{args[0]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{args[0]}': " + ", ".join(f"#{p.player_id} {p.first_name} {p.last_name}" for p in players))
            return
        pitcher = players[0]

        games = db.query(Game).filter(Game.game_date == game_date).all()
        if not games:
            print(f"No game found on {game_date}.")
            return
        if len(games) > 1:
            print(f"Multiple games found on {game_date}: " + ", ".join(f"game_id={g.game_id}" for g in games))
            return
        game = games[0]

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date}")
        print(f"three_squad_intrasquad={game.uses_three_squad_intrasquad}  is_intrasquad={game.is_intrasquad}\n")

        pitcher_pitches = sorted(get_pitching_pitches(db, pitcher.player_id, game_id=game.game_id), key=lambda p: p.pitch_sequence)
        if not pitcher_pitches:
            print("No charted pitches found for this pitcher in this game.")
            return

        seqs = [p.pitch_sequence for p in pitcher_pitches]
        lo, hi = min(seqs), max(seqs)

        events = (
            db.query(GameRunnerEvent)
            .filter(GameRunnerEvent.game_id == game.game_id)
            .order_by(GameRunnerEvent.pitch_sequence_after, GameRunnerEvent.created_at)
            .all()
        )
        events_by_seq = {}
        for ev in events:
            events_by_seq.setdefault(ev.pitch_sequence_after, []).append(ev)

        base_label = {1: "1st", 2: "2nd", 3: "3rd"}
        print(f"{'Seq':>5} {'Batter':<22} {'Squad':>5} {'Outs bef':>8} {'Bases bef':>18} {'Outcome':<14} {'Bases after':>18}")
        for p in pitcher_pitches:
            for ev in events_by_seq.get(p.pitch_sequence - 1, []):
                print(f"      >>> RUNNER EVENT (after seq {p.pitch_sequence - 1}): {event_label(ev, base_label)}")

            batter = "—"
            if p.our_player_id and p.our_player and p.is_our_team_batting:
                batter = f"{p.our_player.first_name} {p.our_player.last_name}"
            elif p.opponent_player_id and p.opponent_player:
                batter = p.opponent_player.player_name
            elif p.opponent_our_player_id:
                batter = f"(our player #{p.opponent_our_player_id} batting)"
            outcome = p.ab_outcome or ""
            bases_after = base_str(p.bases_after) if p.bases_after else ""
            print(f"{p.pitch_sequence:>5} {batter:<22} {p.batting_squad or '-':>5} {p.outs_before if p.outs_before is not None else '-':>8} {base_str(p.bases_before):>18} {outcome:<14} {bases_after:>18}")

        for ev in events_by_seq.get(hi, []):
            print(f"      >>> RUNNER EVENT (after seq {hi}): {event_label(ev, base_label)}")

        print(f"\n{len(pitcher_pitches)} pitch(es) shown, pitch_sequence {lo}-{hi}.")
        print(f"{len(events)} total GameRunnerEvent row(s) in the whole game.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
