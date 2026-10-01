"""
Diagnostic: list every one of a pitcher's pitches in one game that
currently has an "actual location" on file (GamePitch.actual_plate_x/z
not null), so you can tell which ones are leftover from a deleted
Rapsodo import (Ryker, Sept 2026, re: Gavin Derr -- deleted a bad
Rapsodo import but Command Target Zones / Miss direction by pitch kept
showing data, because delete_rapsodo_import used to leave the location
it had copied onto GamePitch untouched -- see the same-day fix in
services/rapsodo_import.py).

That fix only prevents this going forward. For an import ALREADY
deleted, the RapsodoPitch rows it would have been compared against are
gone, so there's no automatic way left to tell "this location came from
the deleted import" apart from "this location came from video review."
This script doesn't guess -- it just lists every located pitch for this
pitcher/game with the "Editing pitch #<N>" number the Pitch Log uses,
so you can go through them against what you actually know happened
(which pitches you've video-reviewed, which came from the file you
deleted) and clear the wrong ones by hand: open that pitch on the Pitch
Log, uncheck "Actual location recorded", save.

Usage:
    python3 scripts/list_pitches_with_actual_location.py "<pitcher name>" <game_date YYYY-MM-DD>

    e.g. python3 scripts/list_pitches_with_actual_location.py "Gavin Derr" 2026-09-08

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
            print("Adjust this script to take a game_id directly if you need to disambiguate.")
            return
        game = games[0]

        pitches = sorted(get_pitching_pitches(db, pitcher.player_id, game_id=game.game_id), key=lambda p: p.pitch_sequence)
        if not pitches:
            print(f"No pitches found for {pitcher.first_name} {pitcher.last_name} in game {game.game_id} ({game_date}).")
            return

        located = [(stint_position, p) for stint_position, p in enumerate(pitches, start=1) if p.actual_plate_x is not None]

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date}")
        print(f"{len(pitches)} total pitch(es); {len(located)} currently have an actual location on file.\n")

        if not located:
            print("None of this pitcher's pitches in this game currently have an actual location -- nothing to clear.")
            return

        print("Pull each of these up on the Pitch Log by its \"Editing pitch #<Seq>\" number and check whether you")
        print("expect it to have a real location (video-reviewed) or not (leftover from the deleted import):\n")
        print(f"{'Stint#':>7} {'Pitch Log Seq#':>15} {'Actual X':>9} {'Actual Z':>9} {'Zone':>5} {'Outcome':<16} {'Pitch Type':<14}")
        for stint_position, p in located:
            pitch_type_name = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
            print(
                f"{stint_position:>7} {p.pitch_sequence:>15} {float(p.actual_plate_x):>9.3f} {float(p.actual_plate_z):>9.3f} "
                f"{('—' if p.pitch_zone is None else p.pitch_zone):>5} {(p.pitch_outcome or '—'):<16} {pitch_type_name:<14}"
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
