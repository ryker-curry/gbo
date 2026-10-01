"""
Diagnostic: "Miss direction by pitch" (Pitcher Game Report -> Command
Execution) skips a pitch number that doesn't match what the coach knows
is actually missing an actual location (Ryker, Sept 2026, re: Gavin
Derr's game 14 outing -- "pitch 6 doesn't have an actual location...
that is why i am confused" after the app's own "Miss direction by
pitch" table instead skipped #9).

Two different places in the app number a pitcher's own pitches within
one game, built from two different pitch lists:

  - The Rapsodo manual-match table (shiny_app/modules/rapsodo_import.py)
    numbers ALL of get_pitching_pitches(pitcher, game) in pitch_sequence
    order -- every pitch this pitcher threw in the game, no filtering.

  - "Miss direction by pitch" (analytics/command_metrics.py's
    game_pitches_command_view) numbers only the pitches with an
    intended_plate_x on file (command is an intent-vs-actual
    comparison, so an "opponent" pitcher's intent is never captured --
    see game_tracking.py's show_intended), in pitch_sequence order
    among JUST that subset.

Normally these agree, because show_intended is True for every pitch in
an intrasquad game regardless of which side is "batting" -- so every
real live-tracked pitch should have an intended location on file. If
even ONE of this pitcher's earlier pitches in the game is missing
intended_plate_x for some other reason (a retroactively-added Pitch Log
entry, an edit path that only exposes intended-location fields for
"not is_our_team_batting" pitches even in an intrasquad game -- see
game_tracking_pitch_log_display.py's pitch-log edit form -- or anything
else), every pitch AFTER that gap gets a HIGHER number in "Miss
direction by pitch" than it has everywhere else in the app, because the
missing one still occupies a slot in the "stint position" numbering but
not in the "has intended location" numbering.

This script does not guess at a fix -- it just prints both numbering
schemes side by side for one pitcher's one game, and flags any pitch
missing intended_plate_x and/or actual_plate_x, so you can see exactly
which pitch(es) caused the drift and match it against what you know
actually happened.

Usage:
    python3 scripts/diagnose_miss_direction_numbering.py "<pitcher name>" <game_date YYYY-MM-DD>

    e.g. python3 scripts/diagnose_miss_direction_numbering.py "Gavin Derr" 2026-09-08

Read-only -- makes no changes.
"""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from database import get_session
from game_stats import get_pitching_pitches
from models import Player, Game


def main():
    if len(sys.argv) != 3:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" <game_date YYYY-MM-DD>')
        sys.exit(1)
    name_query = sys.argv[1].strip().lower()
    try:
        game_date = datetime.strptime(sys.argv[2].strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Couldn't parse date '{sys.argv[2]}' -- use YYYY-MM-DD.")
        sys.exit(1)

    db = get_session()
    try:
        players = [
            p for p in db.query(Player).all()
            if name_query in f"{p.first_name} {p.last_name}".lower()
        ]
        if not players:
            print(f"No roster player matching '{sys.argv[1]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{sys.argv[1]}':")
            for p in players:
                print(f"  player_id={p.player_id}: {p.first_name} {p.last_name}")
            print("Re-run with a more specific name.")
            return
        pitcher = players[0]

        games = db.query(Game).filter(Game.game_date == game_date).all()
        if not games:
            print(f"No game found on {game_date}.")
            return
        if len(games) > 1:
            print(f"Multiple games found on {game_date}:")
            for g in games:
                print(f"  game_id={g.game_id}")
            print("Re-run pointing at scripts/diagnose_pitcher_game.py or adjust this script to take a game_id directly.")
            return
        game = games[0]

        pitches = sorted(get_pitching_pitches(db, pitcher.player_id, game_id=game.game_id), key=lambda p: p.pitch_sequence)
        if not pitches:
            print(f"No pitches found for {pitcher.first_name} {pitcher.last_name} in game {game.game_id} ({game_date}).")
            return

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date}")
        print(f"{len(pitches)} total pitch(es) for this pitcher in this game (stint-position order, matches the Rapsodo manual-match table's numbering):\n")
        print(f"{'Stint#':>7} {'Eligible#':>10} {'Seq':>6} {'is_our_batting':>15} {'Intended?':>10} {'Actual?':>8} {'Outcome':<16}")

        eligible_number = 0
        for stint_position, p in enumerate(pitches, start=1):
            has_intended = p.intended_plate_x is not None
            has_actual = p.actual_plate_x is not None
            eligible_label = ""
            if has_intended:
                eligible_number += 1
                eligible_label = str(eligible_number)
            flag = ""
            if not has_intended:
                flag = "  <-- MISSING INTENDED (excluded from 'Miss direction by pitch' numbering entirely -- shifts every later pitch's number there)"
            elif not has_actual:
                flag = "  <-- missing actual location (correctly skipped as a ROW in 'Miss direction by pitch', but still occupies a number there)"
            print(
                f"{stint_position:>7} {eligible_label:>10} {p.pitch_sequence:>6} {str(p.is_our_team_batting):>15} "
                f"{'yes' if has_intended else 'NO':>10} {'yes' if has_actual else 'NO':>8} {(p.pitch_outcome or '—'):<16}{flag}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
