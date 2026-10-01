"""
Bulk-clear GamePitch.actual_plate_x/z + pitch_zone for every pitch one
pitcher threw in one game -- a clean-slate reset before re-importing
Rapsodo data (Ryker, Sept 2026, re: Gavin Derr's game 14 outing: a
deleted Rapsodo import left stale actual locations on every one of his
22 pitches -- see delete_rapsodo_import's same-day fix in
services/rapsodo_import.py, which only prevents this going forward --
and there's no way left to tell which of those 22 are still correct
now that the old RapsodoPitch rows are gone. Clearing all of them and
re-importing from scratch is simpler and safer than auditing each one).

Does NOT touch intended_plate_x/z (the coach's own live-entered pitch
target) -- only the ACTUAL location and the pitch_zone derived from it,
exactly like unchecking "Actual location recorded" on the Pitch Log
editor would, just for every pitch this pitcher threw in this game at
once instead of one at a time.

Dry-run by default -- lists every pitch that WOULD be cleared and
does not touch the database. Pass --apply to actually clear them.

Usage:
    python3 scripts/clear_actual_locations_for_pitcher_game.py "<pitcher name>" <game_date YYYY-MM-DD> [--apply]

    e.g. python3 scripts/clear_actual_locations_for_pitcher_game.py "Gavin Derr" 2026-09-08
         python3 scripts/clear_actual_locations_for_pitcher_game.py "Gavin Derr" 2026-09-08 --apply
"""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from database import get_session
from game_stats import get_pitching_pitches
from models import Player, Game


def main():
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv
    if len(args) != 2:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" <game_date YYYY-MM-DD> [--apply]')
        sys.exit(1)
    name_query = args[0].strip().lower()
    try:
        game_date = datetime.strptime(args[1].strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Couldn't parse date '{args[1]}' -- use YYYY-MM-DD.")
        sys.exit(1)

    db = get_session()
    try:
        players = [
            p for p in db.query(Player).all()
            if name_query in f"{p.first_name} {p.last_name}".lower()
        ]
        if not players:
            print(f"No roster player matching '{args[0]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{args[0]}':")
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
        located = [(i, p) for i, p in enumerate(pitches, start=1) if p.actual_plate_x is not None]

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date}")
        print(f"{len(pitches)} total pitch(es); {len(located)} currently have an actual location on file.\n")

        if not located:
            print("Nothing to clear.")
            return

        print(f"{'Stint#':>7} {'Pitch Log Seq#':>15} {'Actual X':>9} {'Actual Z':>9}")
        for stint_position, p in located:
            print(f"{stint_position:>7} {p.pitch_sequence:>15} {float(p.actual_plate_x):>9.3f} {float(p.actual_plate_z):>9.3f}")

        if not apply:
            print(f"\nDRY RUN -- {len(located)} pitch(es) would have actual_plate_x/z and pitch_zone cleared.")
            print("Intended location (the coach's own live-entered target) is left untouched either way.")
            print("Re-run with --apply to actually clear them.")
            return

        for _, p in located:
            p.actual_plate_x = None
            p.actual_plate_z = None
            p.pitch_zone = None
        db.commit()
        print(f"\nDone -- cleared actual location on {len(located)} pitch(es). Ready for a fresh Rapsodo import.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
