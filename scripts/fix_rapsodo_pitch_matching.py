"""
Directly fix Rapsodo-to-GamePitch matching for one pitcher's one game,
for the specific "exactly one charted pitch has no Rapsodo reading"
shape of problem (Kurt Kassner and Gavin Derr's game 14 outings, Sept
2026) -- bypasses the manual-match table's one-dropdown-at-a-time UI
and writes the correct mapping straight to the database in one pass.

What "correct" means here: every Rapsodo reading, in its own
chronological order (RapsodoPitch.pitch_number), maps 1:1 to this
pitcher's charted pitches (GamePitch.pitch_sequence) UP TO the missing
one, then shifts by one target for every reading after it -- the gap
itself gets no Rapsodo match at all. See Gavin Derr's case this
session for the full reasoning.

Two ways to tell it where the gap is:
  --gap-position N   You already know it (Nth pitch of the CHARTED
                      stint, 1-based) -- required when nothing is
                      currently matched yet (a fresh, unreconciled
                      import), since there's nothing to detect from.
  (omitted)          Auto-detect: if exactly one charted pitch has no
                      RapsodoPitch currently pointing at it, that's the
                      gap. Works when most of the import is already
                      matched (Kassner's case) and lets this script
                      also just VERIFY an existing reconciliation is
                      internally consistent, with nothing to change.

Only handles a single missing pitch (rapsodo_count == charted_count - 1
exactly). Refuses to guess for any other shape of mismatch.

Before repointing a RapsodoPitch that's already linked elsewhere, clears
the OLD GamePitch's actual_plate_x/z + pitch_zone -- but only when they
still exactly equal that RapsodoPitch's own plate_x_ft/plate_z_ft (i.e.
this import is still what set them, nothing else has since). Copies
location onto the new target only when it doesn't already have one.

Dry-run by default -- prints every pitch's current vs. correct target
and does not touch the database. Pass --apply to write the changes.

Usage:
    python3 scripts/fix_rapsodo_pitch_matching.py "<pitcher name>" <game_date YYYY-MM-DD> [--gap-position N] [--apply]

    e.g. python3 scripts/fix_rapsodo_pitch_matching.py "Kurt Kassner" 2026-09-08
         python3 scripts/fix_rapsodo_pitch_matching.py "Gavin Derr" 2026-09-08 --gap-position 6
         python3 scripts/fix_rapsodo_pitch_matching.py "Gavin Derr" 2026-09-08 --gap-position 6 --apply
"""
import sys
from datetime import datetime

sys.path.insert(0, ".")

from database import get_session
from game_stats import get_pitching_pitches
from models import Player, Game, RapsodoPitch, RapsodoImport, GamePitch
from strike_zone import derive_old_zone


def main():
    raw_args = sys.argv[1:]
    apply = "--apply" in raw_args
    raw_args = [a for a in raw_args if a != "--apply"]

    gap_position = None
    if "--gap-position" in raw_args:
        idx = raw_args.index("--gap-position")
        try:
            gap_position = int(raw_args[idx + 1])
        except (IndexError, ValueError):
            print("--gap-position needs an integer argument.")
            sys.exit(1)
        del raw_args[idx:idx + 2]

    if len(raw_args) != 2:
        print(f'Usage: python3 {sys.argv[0]} "<pitcher name>" <game_date YYYY-MM-DD> [--gap-position N] [--apply]')
        sys.exit(1)
    name_query = raw_args[0].strip().lower()
    try:
        game_date = datetime.strptime(raw_args[1].strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Couldn't parse date '{raw_args[1]}' -- use YYYY-MM-DD.")
        sys.exit(1)

    db = get_session()
    try:
        players = [p for p in db.query(Player).all() if name_query in f"{p.first_name} {p.last_name}".lower()]
        if not players:
            print(f"No roster player matching '{raw_args[0]}'.")
            return
        if len(players) > 1:
            print(f"Multiple roster players match '{raw_args[0]}': " + ", ".join(f"#{p.player_id} {p.first_name} {p.last_name}" for p in players))
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

        game_pitches = sorted(get_pitching_pitches(db, pitcher.player_id, game_id=game.game_id), key=lambda p: p.pitch_sequence)
        rapsodo_pitches = sorted(
            db.query(RapsodoPitch)
            .join(RapsodoImport, RapsodoPitch.import_id == RapsodoImport.import_id)
            .filter(RapsodoImport.game_id == game.game_id, RapsodoImport.player_id == pitcher.player_id)
            .all(),
            key=lambda p: p.pitch_number,
        )

        print(f"{pitcher.first_name} {pitcher.last_name}, game_id={game.game_id}, {game_date}")
        print(f"{len(game_pitches)} charted pitch(es), {len(rapsodo_pitches)} Rapsodo reading(s).\n")

        if len(rapsodo_pitches) == len(game_pitches):
            currently_matched = {rp.game_pitch_id for rp in rapsodo_pitches if rp.game_pitch_id is not None}
            unmatched_rp = [rp for rp in rapsodo_pitches if rp.game_pitch_id is None]
            unmatched_gp = [gp for gp in game_pitches if gp.game_pitch_id not in currently_matched]
            if not unmatched_rp and not unmatched_gp:
                print("Counts already match and every reading is linked -- nothing to do.")
            else:
                print(f"Counts match, but {len(unmatched_rp)} reading(s) aren't linked and {len(unmatched_gp)} charted pitch(es) have no reading.")
                print("This isn't the single-gap shape this script handles -- needs manual review via the Rapsodo import page.")
            return

        if len(rapsodo_pitches) != len(game_pitches) - 1:
            print(
                f"Counts differ by {len(game_pitches) - len(rapsodo_pitches)}, not exactly 1 -- this script only "
                f"handles a single missing pitch. Needs manual review."
            )
            return

        if gap_position is None:
            currently_matched = {rp.game_pitch_id for rp in rapsodo_pitches if rp.game_pitch_id is not None}
            unmatched_gp = [(i, gp) for i, gp in enumerate(game_pitches, start=1) if gp.game_pitch_id not in currently_matched]
            if len(unmatched_gp) != 1:
                print(
                    f"Couldn't auto-detect the gap -- {len(unmatched_gp)} charted pitch(es) currently have no "
                    f"Rapsodo reading pointing at them (expected exactly 1). Pass --gap-position N explicitly "
                    f"(the Nth pitch of the charted stint that has no Rapsodo reading)."
                )
                return
            gap_position, gap_gp = unmatched_gp[0]
            print(f"Auto-detected gap at stint position {gap_position} (charted pitch #{gap_gp.pitch_sequence}, currently unmatched).\n")
        else:
            if not (1 <= gap_position <= len(game_pitches)):
                print(f"--gap-position {gap_position} is out of range (1-{len(game_pitches)}).")
                return
            print(f"Using given gap position {gap_position} (charted pitch #{game_pitches[gap_position - 1].pitch_sequence}).\n")

        gap_index = gap_position - 1  # 0-based

        changes = []
        for j, rp in enumerate(rapsodo_pitches):
            target_index = j if j < gap_index else j + 1
            target_gp = game_pitches[target_index]
            current_seq = None
            if rp.game_pitch_id is not None:
                current_gp = next((gp for gp in game_pitches if gp.game_pitch_id == rp.game_pitch_id), None)
                current_seq = current_gp.pitch_sequence if current_gp is not None else f"game_pitch_id={rp.game_pitch_id} (not this pitcher's -- odd)"
            changes.append((rp, target_gp, current_seq))

        print(f"{'Rapsodo#':>9} {'Current target seq':>20} {'Correct target seq':>20}  Status")
        any_change = False
        for rp, target_gp, current_seq in changes:
            is_change = current_seq != target_gp.pitch_sequence
            any_change = any_change or is_change
            status = "CHANGE" if is_change else "same"
            print(f"{rp.pitch_number:>9} {str(current_seq):>20} {target_gp.pitch_sequence:>20}  {status}")
        print(f"\nCharted pitch #{game_pitches[gap_index].pitch_sequence} (stint position {gap_position}) will have NO Rapsodo match -- correct, since that's the gap.")

        if not any_change:
            print("\nEverything is already correctly matched -- nothing to apply.")
            return

        if not apply:
            print("\nDRY RUN -- no changes made. Re-run with --apply to write these changes.")
            return

        cleared_count = 0
        copied_count = 0
        for rp, target_gp, _ in changes:
            old_gp = None
            if rp.game_pitch_id is not None and rp.game_pitch_id != target_gp.game_pitch_id:
                old_gp = db.query(GamePitch).filter(GamePitch.game_pitch_id == rp.game_pitch_id).first()
            if (
                old_gp is not None
                and rp.plate_x_ft is not None
                and rp.plate_z_ft is not None
                and old_gp.actual_plate_x == rp.plate_x_ft
                and old_gp.actual_plate_z == rp.plate_z_ft
            ):
                old_gp.actual_plate_x = None
                old_gp.actual_plate_z = None
                old_gp.pitch_zone = None
                cleared_count += 1

            rp.game_pitch_id = target_gp.game_pitch_id
            if (
                target_gp.actual_plate_x is None
                and target_gp.actual_plate_z is None
                and rp.plate_x_ft is not None
                and rp.plate_z_ft is not None
            ):
                target_gp.actual_plate_x = rp.plate_x_ft
                target_gp.actual_plate_z = rp.plate_z_ft
                target_gp.pitch_zone = derive_old_zone(float(rp.plate_x_ft), float(rp.plate_z_ft))
                copied_count += 1

        db.commit()
        repointed_count = len([c for c in changes if c[2] != c[1].pitch_sequence])
        print(f"\nDone -- repointed {repointed_count} reading(s), "
              f"cleared stale location on {cleared_count} old pitch(es), copied fresh location onto {copied_count} pitch(es).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
