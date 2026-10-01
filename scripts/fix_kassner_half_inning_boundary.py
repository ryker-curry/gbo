"""
Fix Kurt Kassner's innings-pitched boundary in game #14 -- correctly this
time, using the same_side_continues option added for exactly this case.

What happened: forced_end_id=3 (created 2026-09-12 by clicking the old
"End half-inning after this pitch" button on pitch #55) unconditionally
flipped is_our_team_batting for every pitch after it, corrupting Kassner's
whole outing. That was undone with undo_forced_half_inning_end.py. Then,
before the same_side_continues fix was deployed, the same old button was
clicked again on the same pitch, creating forced_end_id=4 -- the identical
corruption, back again.

This script does the real fix in one run:
  1. Deletes forced_end_id=4 (the re-introduced bad flip).
  2. Inserts a new GameForcedHalfInningEnd anchored at the same pitch
     (#55) with same_side_continues=True -- same squad (Kassner) keeps
     pitching to a fresh lineup, so outs/bases reset to 0 and the inning
     advances, but who's-batting/who's-pitching does NOT flip. This is
     the actual fix for the original bug: Kassner's frame now starts at
     0 outs instead of inheriting Holman's, so his 2 recorded outs will
     correctly show as 0.2 IP instead of 0.1.
  3. Re-runs replay_game (the same function every save in this app uses)
     across the game's full current history and writes the result back,
     exactly like undo_forced_half_inning_end.py does.

The two OTHER existing forced-half-inning-end rows (id=1, id=2, both
anchored at pitch #81 -- Kassner's outing genuinely ending and a real
side/lineup change happening) are untouched.

Usage:
    python3 scripts/fix_kassner_half_inning_boundary.py 14
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "shiny_app"))

from database import get_session
from models import Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd
from modules.game_tracking import build_re_lookup, replay_game

REPLAY_OWNED_FIELDS = (
    "balls_before", "strikes_before", "outs_before", "bases_before",
    "inning", "is_our_team_batting", "pa_pitch_number",
    "re_before", "re_after", "run_value",
)

BAD_FORCED_END_ID = 4
ANCHOR_PITCH_SEQ = 55
ANCHOR_INNING = 4
ANCHOR_IS_OUR_TEAM_BATTING = False
ANCHOR_BATTING_SQUAD = "C"
ANCHOR_RUNS_SCORED = 0
ANCHOR_CREDITED_PLAYER_ID = 54  # Shane Holman -- same as what the app itself computed for forced_end_id=4


def main(game_id):
    db = get_session()
    try:
        bad = (
            db.query(GameForcedHalfInningEnd)
            .filter(
                GameForcedHalfInningEnd.forced_end_id == BAD_FORCED_END_ID,
                GameForcedHalfInningEnd.game_id == game_id,
            )
            .first()
        )
        if bad is None:
            print(f"No forced_end_id={BAD_FORCED_END_ID} found in game {game_id} -- already fixed? Stopping, no changes made.")
            return
        if bad.pitch_sequence_after != ANCHOR_PITCH_SEQ:
            print(
                f"forced_end_id={BAD_FORCED_END_ID} is anchored at pitch_seq="
                f"{bad.pitch_sequence_after}, not the expected {ANCHOR_PITCH_SEQ} -- "
                f"stopping without changes so this can be checked by hand first."
            )
            return

        print(f"Deleting forced_end_id={BAD_FORCED_END_ID} (the re-introduced bad flip)...")
        db.delete(bad)
        db.flush()

        print(f"Inserting corrected forced-half-inning-end at pitch_seq={ANCHOR_PITCH_SEQ}, same_side_continues=True...")
        db.add(GameForcedHalfInningEnd(
            game_id=game_id,
            pitch_sequence_after=ANCHOR_PITCH_SEQ,
            inning=ANCHOR_INNING,
            is_our_team_batting=ANCHOR_IS_OUR_TEAM_BATTING,
            batting_squad=ANCHOR_BATTING_SQUAD,
            runs_scored=ANCHOR_RUNS_SCORED,
            credited_player_id=ANCHOR_CREDITED_PLAYER_ID,
            same_side_continues=True,
        ))
        db.flush()

        game = db.query(Game).filter(Game.game_id == game_id).first()
        all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
        all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
        all_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()

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
        print(f"Done -- re-synced {len(all_pitches)} pitch(es), {changed} field(s) changed.")
        print(f"Scores now: our_score={result['our_score']}  opponent_score={result['opponent_score']}  squad_c_score={result['squad_c_score']}")
        print(
            f"replay_game flagged {len(result['side_changed_pitch_ids'])} pitch(es) whose stored "
            f"inning/is_our_team_batting changed -- expect roughly pitches #56-81 (Kassner's outing, "
            f"now correctly un-flipped back to how it was entered). If that number looks way off from "
            f"~26, stop and let me know before doing anything else."
        )
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 scripts/fix_kassner_half_inning_boundary.py <game_id>")
        sys.exit(1)
    main(int(sys.argv[1]))
