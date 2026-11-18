"""
Diagnostic: scan EVERY game-linked Rapsodo import currently in the
database and flag any whose Rapsodo pitch count doesn't match the
charted pitch count for that pitcher's outing -- the exact fingerprint
of the no-read-drop bug fixed in import_rapsodo_file (Ryker, Sept 2026:
a no-read row used to be silently rejected instead of kept as a
placeholder, shifting every later pitch's Rapsodo numbering down by one
relative to the charted stint -- see Gavin Derr's game 14 outing).

That fix only changes what happens on a NEW import -- it does nothing
to imports already sitting in the database. This script finds any
OTHER outing that might be quietly carrying the same kind of mismatch,
so you don't have to go hunting pitcher by pitcher.

Flags an import as NEEDS REVIEW when either:
  - its RapsodoPitch count doesn't match this pitcher's charted pitch
    count for that game (the no-read-drop symptom, though a handful of
    other things can also cause a count mismatch -- a warm-up throw
    that leaked into the export, a foul tip double-read, etc.), or
  - the counts DO match but some of its RapsodoPitch rows still have no
    game_pitch_id (never got matched to a charted pitch at all -- an
    import that was uploaded but never reconciled).

Everything else is reported OK and needs no action.

This does not tell you whether a flagged import's CURRENT matches are
right or wrong -- only that something about it is worth a second look.
Read-only -- makes no changes.

Usage:
    python3 scripts/diagnose_all_rapsodo_game_imports.py
"""
import sys

sys.path.insert(0, ".")

from database import get_session
from game_stats import get_pitching_pitches
from models import RapsodoImport, RapsodoPitch


def main():
    db = get_session()
    try:
        imports = (
            db.query(RapsodoImport)
            .filter(RapsodoImport.game_id.isnot(None))
            .order_by(RapsodoImport.game_id, RapsodoImport.player_id)
            .all()
        )
        if not imports:
            print("No game-linked Rapsodo imports found.")
            return

        print(f"{len(imports)} game-linked Rapsodo import(s) found.\n")
        print(f"{'Import#':>8} {'Pitcher':<22} {'Game':<12} {'File':<28} {'Rapsodo#':>9} {'Charted#':>9} {'Matched#':>9}  Status")

        needs_review = []
        for imp in imports:
            pitcher = imp.player
            game = imp.game
            pitcher_name = f"{pitcher.first_name} {pitcher.last_name}" if pitcher else f"player_id={imp.player_id}"
            game_label = str(game.game_date) if game and game.game_date else f"game_id={imp.game_id}"

            rapsodo_pitches = db.query(RapsodoPitch).filter(RapsodoPitch.import_id == imp.import_id).all()
            rapsodo_count = len(rapsodo_pitches)
            matched_count = sum(1 for p in rapsodo_pitches if p.game_pitch_id is not None)

            charted_count = None
            if game is not None:
                charted_pitches = get_pitching_pitches(db, imp.player_id, game_id=imp.game_id)
                charted_count = len(charted_pitches)

            count_mismatch = charted_count is not None and rapsodo_count != charted_count
            some_unmatched = matched_count < rapsodo_count

            if count_mismatch or some_unmatched:
                if count_mismatch:
                    reason = f"NEEDS REVIEW -- {rapsodo_count} Rapsodo pitch(es) vs {charted_count} charted"
                else:
                    reason = f"NEEDS REVIEW -- {rapsodo_count - matched_count} pitch(es) never matched to a charted pitch"
                needs_review.append((imp, pitcher_name, game_label, reason))
            else:
                reason = "OK"

            charted_str = "—" if charted_count is None else str(charted_count)
            print(
                f"{imp.import_id:>8} {pitcher_name:<22} {game_label:<12} {imp.original_filename[:28]:<28} "
                f"{rapsodo_count:>9} {charted_str:>9} {matched_count:>9}  {reason}"
            )

        print()
        if not needs_review:
            print("Nothing flagged -- every game-linked import's Rapsodo pitch count matches its charted stint, fully matched.")
        else:
            print(f"{len(needs_review)} import(s) flagged for review:")
            for imp, pitcher_name, game_label, reason in needs_review:
                print(f"  import_id={imp.import_id}  {pitcher_name}  {game_label}  -- {reason}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
