"""
Endo an incorrectly-created GameForcedHalfInningEnd and re-sync the game.

Built for a specific incident (Ryker, Sept 2026, game #14 -- the Kurt
Kassner/Shane Holman game): "End half-inning after this pitch" was
clicked on pitch #55 (Holman's last pitch), intending to formally close
out Holman's stint since the team was rotating to a new lineup on a
pitch count, not a real 3rd out. That feature forces outs to 3, resets
bases, increments inning, and FLIPS is_our_team_batting -- unconditionally,
per its own design (see GameForcedHalfInningEnd's docstring in models.py
and replay_game's outs>=3 branch in game_tracking.py, which does the
exact same flip for a natural 3-out half-inning). In a two-squad game
that flip is always correct. In a THREE-squad intrasquad game (this one
-- Team 1/2/3), is_our_team_batting doesn't track "which of the three
squads is up" (that's the separate batting_squad column) -- it's a
strictly-alternating bookkeeping flag that decides which of our_player_id/
opponent_our_player_id holds the batter for a given pitch. Flipping it
here, without the pitches after it having been entered expecting a flip
(they were entered as a same-side pitching change, no side change),
silently swapped which column reads as "batter" vs. "pitcher" for every
pitch from #56 onward, and cascaded the same parity shift into every
LATER half-inning transition in the game too -- which is why Bradley
Neill's later stint went missing from pitching stats as well, even
though nothing about his own pitches was touched.

The fix: delete the offending GameForcedHalfInningEnd row (undoing
exactly the one write that caused this) and then re-run replay_game --
the same function every save in this app already uses -- across the
game's full, current pitch/event/forced-end history, and write its
output back. This restores the game to exactly the state it was in
right before that click, nothing more.

This does NOT fix the original bug you asked about (Kassner's
undercounted innings pitched from the missing half-inning boundary
between Holman and him) -- that's still there after this runs, same as
before the click. This script only undoes the NEW, worse problem the
forced-end click introduced. We'll fix the original bug properly
afterward (likely a code change so this feature is 3-squad-rotation-
aware, rather than a manual retroactive click).

Usage:
    # Step 1 -- list every forced-half-inning-end row for the game, so
    # you can see exactly which one to remove (this makes NO changes):
    python3 scripts/undo_forced_half_inning_end.py 14

    # Step 2 -- once you've confirmed the forced_end_id from step 1,
    # delete it and re-sync the whole game:
    python3 scripts/undo_forced_half_inning_end.py 14 --delete 7
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shiny_app"))

from database import get_session
from models import Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd, Player
from modules.game_tracking import build_re_lookup, replay_game

REPLAY_OWNED_FIELDS = (
    "balls_before", "strikes_before", "outs_before", "bases_before",
    "inning", "is_our_team_batting", "pa_pitch_number",
    "re_before", "re_after", "run_value",
)


def list_forced_ends(db, game_id):
    rows = (
        db.query(GameForcedHalfInningEnd)
        .filter(GameForcedHalfInningEnd.game_id == game_id)
        .order_by(GameForcedHalfInningEnd.pitch_sequence_after, GameForcedHalfInningEnd.forced_end_id)
        .all()
    )
    if not rows:
        print(f"No GameForcedHalfInningEnd rows exist for game {game_id}.")
        return
    players = {p.player_id: p for p in db.query(Player).all()}
    print(f"GameForcedHalfInningEnd rows for game {game_id}:")
    for fe in rows:
        credited = players.get(fe.credited_player_id)
        credited_name = f"{credited.first_name} {credited.last_name}" if credited else fe.credited_player_id
        print(
            f"  forced_end_id={fe.forced_end_id}  after pitch_seq={fe.pitch_sequence_after}  "
            f"inning={fe.inning}  is_our_team_batting={fe.is_our_team_batting}  "
            f"batting_squad={fe.batting_squad}  runs_scored={fe.runs_scored}  "
            f"credited_player={credited_name}  created_at={fe.created_at}"
        )
    print(
        "\nRe-run with --delete <forced_end_id> once you've confirmed which row is the "
        "one to undo (nothing has been changed yet)."
    )


def delete_and_resync(db, game_id, forced_end_id):
    target = (
        db.query(GameForcedHalfInningEnd)
        .filter(
            GameForcedHalfInningEnd.forced_end_id == forced_end_id,
            GameForcedHalfInningEnd.game_id == game_id,
        )
        .first()
    )
    if target is None:
        print(f"No GameForcedHalfInningEnd with forced_end_id={forced_end_id} in game {game_id} -- nothing to do.")
        return

    print(
        f"Deleting forced_end_id={forced_end_id} "
        f"(after pitch_seq={target.pitch_sequence_after}, inning={target.inning}, "
        f"is_our_team_batting={target.is_our_team_batting})..."
    )
    db.delete(target)
    db.flush()

    game = db.query(Game).filter(Game.game_id == game_id).first()
    all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
    all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
    all_forced_ends = (
        db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()
    )

    re_lookup = build_re_lookup(db)
    result = replay_game(all_pitches, all_events, re_lookup, all_forced_ends)

    changed = 0
    for p in all_pitches:
        r = result["by_pitch"].get(p.game_pitch_id)
        if r is None:
            continue
        for field in REPLAY_OWNED_FIELDS:
            if getattr(p, field) != r[field]:
                changed += 1
            setattr(p, field, r[field])

    if game is not None:
        game.our_score = result["our_score"]
        game.opponent_score = result["opponent_score"]
        game.squad_c_score = result["squad_c_score"]

    db.commit()
    print(f"Done -- re-synced {len(all_pitches)} pitch(es), {changed} field(s) changed across all pitches.")
    print(f"Scores now: our_score={result['our_score']}  opponent_score={result['opponent_score']}  squad_c_score={result['squad_c_score']}")
    if result["side_changed_pitch_ids"]:
        print(
            f"NOTE: replay_game flagged {len(result['side_changed_pitch_ids'])} pitch(es) whose "
            f"is_our_team_batting changed relative to what was stored before this script ran -- "
            f"that's expected here since undoing the bad flip IS the fix, but if that number looks "
            f"unexpectedly large, stop and let me know before doing anything else."
        )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 4) or (len(sys.argv) == 4 and sys.argv[2] != "--delete"):
        print("Usage:")
        print("  python3 scripts/undo_forced_half_inning_end.py <game_id>                  # list only")
        print("  python3 scripts/undo_forced_half_inning_end.py <game_id> --delete <forced_end_id>")
        sys.exit(1)

    game_id = int(sys.argv[1])
    db = get_session()
    try:
        if len(sys.argv) == 2:
            list_forced_ends(db, game_id)
        else:
            delete_and_resync(db, game_id, int(sys.argv[3]))
    finally:
        db.close()
