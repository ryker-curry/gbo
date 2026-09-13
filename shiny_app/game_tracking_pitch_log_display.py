"""
GBO -- Game Tracking's "Pitch Log" section, extracted out of
game_tracking.py's single ~4300-line game_tracking_server (Tier 2 split,
2026-09 -- see game_tracking_manage_display.py's module docstring for the
overall rationale and the registration pattern this follows).

Unlike Video Review's split (game_tracking_video_display.py),
_registered_pitch_row_ids / _gt_editing_pitch_id / _gt_pending_delete_pitch_id /
_pitch_log_limit / _gt_pl_pending_preview are NOT self-contained --
_sync_active_game_id (Seasons + game picker section, still in
game_tracking.py) resets all five reactive.Values back to their defaults
whenever the active game changes. So they stay defined in
game_tracking_server and are threaded in here as parameters, same as
_refresh_tick/_active_game_id/_access_ok/_can_edit already are for the
Manage Game split. PITCH_OUTCOMES/CONTACT_QUALITY_OPTIONS/AB_OUTCOMES and
build_re_lookup/replay_game are also passed in rather than imported,
since importing them from game_tracking.py here would be a circular
import (game_tracking.py imports this module).

-----------------------------------------------------------------------
Edit scope and the preview-then-confirm save flow (Sept 2026)
-----------------------------------------------------------------------
Ryker: "can we adjust game tracking to be able and go back and edit
anything that has happened but not having to undo pitches" -- this used
to be impossible for anything beyond a handful of "leaf" fields
(pitch_type, pitch_outcome, intended/actual location, contact_quality,
is_sword, batted_ball_type/x/y, notes), because every OTHER field on a
GamePitch either feeds or IS the forward-computed count/inning/score
chain: balls_before/strikes_before/outs_before/bases_before/inning/
pa_pitch_number are all derived from whatever came before them at the
moment they were recorded (see compute_current_state in
game_tracking.py), and re_before/re_after/run_value are a one-time
lookup baked in alongside them. Editing an EARLIER pitch's
pitch_outcome/ab_outcome/ends_plate_appearance/outs_after/bases_after/
runs_scored_on_play used to silently desync every later pitch's stored
chain fields, with nothing detecting or fixing it.

Now EVERY field is editable, including those. The trick is
game_tracking.py's replay_game() -- given the whole game's pitches (with
the pending, not-yet-committed edit applied in memory) and runner
events, it walks the game from the very start and recomputes what every
pitch's chain fields and the game's score totals SHOULD be, the exact
same transition rules compute_current_state applies one step at a time.

Saving is split into two paths, gated on whether the edit touches any of
STATE_AFFECTING_FIELDS below:
  - A pure leaf edit (pitch_type/location/contact_quality/batted_ball_*/
    notes/is_sword) saves INSTANTLY, exactly like before this feature --
    no preview, no behavior change, since a leaf value is never read by
    anything else.
  - An edit touching pitch_outcome/ab_outcome/ends_plate_appearance/
    outs_after/bases_after/runs_scored_on_play/unearned_runs_on_play
    does NOT write anything immediately. Instead it builds the in-memory
    "what would replay_game say now" preview and shows it (see
    _render_preview_block) -- same dry-run-then-apply posture
    scripts/backfill_opponent_hand.py already uses for DB backfills.
    Only an explicit "Confirm & Save" click (_confirm_pitch_log_preview)
    actually re-derives the replay fresh from the DB (guarding against
    anything having changed since the preview was built -- e.g. a live
    pitch recorded in the meantime) and commits the edit, every affected
    pitch's corrected chain fields, and the game's corrected score
    totals as one transaction. "Cancel" (_cancel_pitch_log_preview)
    discards the pending preview and writes nothing.

replay_game deliberately does NOT reassign a pitch's already-recorded
our_player_id/opponent_* identity fields even when its recomputed
inning/is_our_team_batting differs from what's stored (its
side_changed_pitch_ids) -- knowing WHO was actually up when a half-
inning boundary shifts is a human judgment call this replay has no way
to make. _render_preview_block surfaces that list as an explicit
warning so the coach can go fix identity by hand; see replay_game's own
docstring in game_tracking.py for the full reasoning.

DELETE keeps its original restriction-free behavior -- removing a row
still can't corrupt any OTHER row's already-stored data on its own (it
only leaves a gap in pitch_sequence, already harmless -- see
_do_record_pitch's max(pitch_sequence)+1), so it stays a simple
confirm/cancel with no replay involved. (A deleted pitch CAN desync the
chain the same way an edit can, in principle -- this pass didn't extend
delete to run replay_game too, since Ryker's ask was specifically about
editing without needing to undo; deleting a past pitch outright is
already a rarer, more destructive action than editing one, and is left
as a possible future follow-up.)
"""

import re

from shiny import ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd, GameLineupSlot, LineupSubstitution, PitchType
import strike_zone
import ui_helpers

# Touching ANY of these routes a Pitch Log save through the preview-then-
# confirm flow instead of saving instantly -- see module docstring.
# Order doesn't matter; only used for the "did anything state-affecting
# change" check in _save_pitch_log_edit.
STATE_AFFECTING_FIELDS = (
    "pitch_outcome", "ab_outcome", "ends_plate_appearance",
    "outs_after", "bases_after", "runs_scored_on_play", "unearned_runs_on_play",
)

# Exactly the fields replay_game (game_tracking.py) recomputes and owns.
# Keys match replay_game's by_pitch dict AND GamePitch's own column
# names 1:1, so writing a confirmed preview is a plain setattr loop --
# see _confirm_pitch_log_preview.
REPLAY_OWNED_FIELDS = (
    "balls_before", "strikes_before", "outs_before", "bases_before",
    "inning", "is_our_team_batting", "pa_pitch_number",
    "re_before", "re_after", "run_value",
)


# "Runner on"/"Advances to" labels for the retroactive "Log runner
# event" form below -- same small dicts
# game_tracking_runner_events_display.py keeps its own copy of, rather
# than a cross-import (these two files are deliberately independent
# leaf modules under game_tracking.py -- see this module's own
# docstring, and that module's, for why neither imports the other).
BASE_LABEL = {1: "1st", 2: "2nd", 3: "3rd"}
TO_BASE_LABEL = {2: "2nd", 3: "3rd", 4: "Home"}


def _players_from_slots(slots):
    """Every Player who ever occupied one of `slots` this game -- the
    slot's original starter plus everyone who substituted in, deduped
    by player_id, sorted by name. Same helper
    game_tracking_runner_events_display.py uses for the same reason:
    we're picking a runner for something that already happened (a
    retroactive add anchored to a past pitch), not the live "who's up
    right now" picker (get_current_slot_occupant_id, game_tracking.py)."""
    players = {}
    for slot in slots:
        if slot.player_id and slot.player is not None:
            players[slot.player_id] = slot.player
        for sub in slot.substitutions:
            if sub.player_id and sub.player is not None:
                players[sub.player_id] = sub.player
    return sorted(players.values(), key=lambda p: (p.last_name, p.first_name))


def _runner_choices_for_event(db, game, is_our_team_batting, batting_squad):
    """Returns (our_choices_dict, opp_roster_list) -- exactly one is
    populated (the other is None). Same split
    game_tracking_runner_events_display.py's own copy uses, built from
    this GAME's saved lineup history rather than "who's up live right
    now" -- see _players_from_slots above."""
    if game.uses_three_squad_intrasquad or game.is_intrasquad:
        squad = batting_squad or ("A" if is_our_team_batting else "B")
        slots = (
            db.query(GameLineupSlot)
            .options(
                joinedload(GameLineupSlot.player),
                joinedload(GameLineupSlot.substitutions).joinedload(LineupSubstitution.player),
            )
            .filter(GameLineupSlot.game_id == game.game_id, GameLineupSlot.squad == squad)
            .all()
        )
        players = _players_from_slots(slots)
        return {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}, None
    if is_our_team_batting:
        slots = (
            db.query(GameLineupSlot)
            .options(
                joinedload(GameLineupSlot.player),
                joinedload(GameLineupSlot.substitutions).joinedload(LineupSubstitution.player),
            )
            .filter(GameLineupSlot.game_id == game.game_id, GameLineupSlot.squad == "A")
            .all()
        )
        players = _players_from_slots(slots)
        return {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}, None
    opp_roster = game.opponent_team.roster if game.opponent_team else []
    return None, opp_roster


def _apply_field_values(pitch, values):
    """setattr loop shared by the instant-save path, the in-memory
    preview build, and the confirmed save -- `values` is always a plain
    dict of column_name -> new_value, built once by _save_pitch_log_edit
    from the edit form's inputs."""
    for key, val in values.items():
        setattr(pitch, key, val)


def _build_preview_rows(all_pitches, result, game):
    """Diffs replay_game's recomputed `result` against what's currently
    stored on each of `all_pitches` (the pending edit already applied in
    memory to whichever one is being edited -- see _save_pitch_log_edit),
    returning (rows, side_changed_seqs, score_changes):
      - rows: one dict per CHANGED pitch for ui_helpers.render_dict_table
        -- a single "Changes" column summarizing every field that
        differs, rather than one row per field, since several fields
        commonly change together on the same pitch.
      - side_changed_seqs: "#N"-formatted pitch_sequence strings for
        every pitch in replay_game's side_changed_pitch_ids, in game
        order -- see module docstring.
      - score_changes: human-readable "X: old -> new" strings, one per
        score total that would actually change.
    """
    by_pitch = result["by_pitch"]

    def _fmt(v):
        return f"{float(v):.3f}" if v is not None else "—"

    def _rounded(v):
        return round(float(v), 3) if v is not None else None

    ordered = sorted(all_pitches, key=lambda x: x.pitch_sequence)

    rows = []
    for p in ordered:
        r = by_pitch.get(p.game_pitch_id)
        if r is None:
            continue
        diffs = []
        old_count = f"{p.balls_before or 0}-{p.strikes_before or 0}"
        new_count = f"{r['balls_before']}-{r['strikes_before']}"
        if old_count != new_count:
            diffs.append(f"Count {old_count}→{new_count}")
        if (p.outs_before or 0) != r["outs_before"]:
            diffs.append(f"Outs before {p.outs_before}→{r['outs_before']}")
        if (p.bases_before or "000") != r["bases_before"]:
            diffs.append(f"Bases before {p.bases_before or '000'}→{r['bases_before']}")
        if p.inning != r["inning"]:
            diffs.append(f"Inning {p.inning}→{r['inning']}")
        if p.is_our_team_batting != r["is_our_team_batting"]:
            diffs.append(
                f"Side {'Us' if p.is_our_team_batting else 'Opp'}"
                f"→{'Us' if r['is_our_team_batting'] else 'Opp'}"
            )
        if (p.pa_pitch_number or 1) != r["pa_pitch_number"]:
            diffs.append(f"PA pitch # {p.pa_pitch_number}→{r['pa_pitch_number']}")
        if _rounded(p.re_before) != _rounded(r["re_before"]):
            diffs.append(f"RE before {_fmt(p.re_before)}→{_fmt(r['re_before'])}")
        if _rounded(p.re_after) != _rounded(r["re_after"]):
            diffs.append(f"RE after {_fmt(p.re_after)}→{_fmt(r['re_after'])}")
        if _rounded(p.run_value) != _rounded(r["run_value"]):
            diffs.append(f"RV {_fmt(p.run_value)}→{_fmt(r['run_value'])}")
        if diffs:
            rows.append({"Pitch #": f"#{p.pitch_sequence}", "Changes": "; ".join(diffs)})

    side_changed_seqs = [
        f"#{p.pitch_sequence}" for p in ordered
        if p.game_pitch_id in result["side_changed_pitch_ids"]
    ]

    score_changes = []
    if game is not None:
        if result["our_score"] != game.our_score:
            score_changes.append(f"Our score: {game.our_score} → {result['our_score']}")
        if result["opponent_score"] != game.opponent_score:
            score_changes.append(f"Opponent score: {game.opponent_score} → {result['opponent_score']}")
        # "Team 3" mirrors game_tracking.py's TEAM_LABEL['C'] -- not
        # imported here (one more cross-module constant isn't worth it
        # for a single display string) since it can never change
        # independently of that dict without this line needing a look
        # anyway.
        if game.uses_three_squad_intrasquad and result["squad_c_score"] != game.squad_c_score:
            score_changes.append(f"Team 3 score: {game.squad_c_score} → {result['squad_c_score']}")

    return rows, side_changed_seqs, score_changes


def _render_preview_block(preview):
    """The "review before you commit" step -- same border+Confirm/Cancel
    convention _confirm_pitch_log_delete already uses below for delete,
    just non-destructive-styled (border-warning, not border-danger)
    since nothing has been removed, only recomputed. Rendered in place
    of the edit form for the pitch being edited once
    _save_pitch_log_edit has determined the edit is state-affecting."""
    children = [
        ui.h6(f"Preview: saving pitch #{preview['target_seq']}", class_="mt-2"),
        ui.p(
            "This edit changes state later pitches were computed from. "
            "Nothing has been saved yet -- review what would change "
            "below, then Confirm & Save or Cancel.",
            class_="text-muted small",
        ),
    ]
    if preview["side_changed_seqs"]:
        children.append(ui.p(
            "Side/inning changed for pitch(es) " + ", ".join(preview["side_changed_seqs"]) +
            " -- this pitch's recorded batter/pitcher may no longer match who was "
            "actually up; review it manually. The count/RE numbers will still be "
            "corrected, but who's listed as playing won't be reassigned automatically.",
            class_="text-warning small fw-bold mb-1",
        ))
    if preview["rows"]:
        children.append(ui.p("Pitches that would change:", class_="small fw-bold mb-1"))
        children.append(ui_helpers.render_dict_table(preview["rows"]))
    else:
        children.append(ui.p("No other pitch's stored count/inning/RE would change.", class_="text-muted small"))
    if preview["score_changes"]:
        children.append(ui.p("Score change: " + "; ".join(preview["score_changes"]), class_="small fw-bold mt-1"))
    children.append(ui.layout_columns(
        ui.input_action_button("gt_pl_confirm_preview_btn", "Confirm & Save", class_="btn-danger btn-sm mt-2"),
        ui.input_action_button("gt_pl_cancel_preview_btn", "Cancel", class_="btn-outline-secondary btn-sm mt-2"),
        col_widths=[6, 6],
    ))
    return ui.div(*children, class_="border border-warning rounded p-2 mb-2")


def _render_forced_end_preview(preview):
    """Same border+Confirm/Cancel convention _render_preview_block uses
    above for editing a pitch, but for INSERTING a brand-new
    GameForcedHalfInningEnd anchored right after this pitch -- the
    retroactive fix for a pitcher's outing that ended on a pitch count
    with runners left on base (Ryker, Sept 2026 -- the Kurt Kassner
    example; see forced_half_inning_end_panel in game_tracking.py for
    the live version of this same action, and models.
    GameForcedHalfInningEnd for the full design)."""
    if preview["runs_scored"]:
        charge = (
            f"charged to {preview['credited_player_label']}'s ERA" if preview["credited_player_label"]
            else "not charged to anyone's ERA (no pitcher on file for this pitch)"
        )
        runs_line = f"{preview['runs_scored']} runner(s) on base at this point will score and {charge}."
    else:
        runs_line = "No runners on base at this point -- the half-inning just ends here, no runs charged."
    children = [
        ui.h6(f"Preview: end half-inning after pitch #{preview['target_seq']}", class_="mt-2"),
        ui.p(
            "Nothing has been saved yet -- review what would change below, then Confirm or Cancel.",
            class_="text-muted small",
        ),
        ui.p(runs_line, class_="small fw-bold mb-1"),
    ]
    if preview.get("same_side_continues"):
        children.append(ui.p(
            "Mode: same team continues pitching to a fresh lineup -- who's pitching/batting "
            "will NOT flip after this point; only the count/bases reset and the inning advances.",
            class_="small fw-bold text-info mb-1",
        ))
    if preview["side_changed_seqs"]:
        children.append(ui.p(
            "Side/inning changed for pitch(es) " + ", ".join(preview["side_changed_seqs"]) +
            " -- this pitch's recorded batter/pitcher may no longer match who was "
            "actually up; review it manually. The count/RE numbers will still be "
            "corrected, but who's listed as playing won't be reassigned automatically.",
            class_="text-warning small fw-bold mb-1",
        ))
    if preview["rows"]:
        children.append(ui.p("Pitches that would change:", class_="small fw-bold mb-1"))
        children.append(ui_helpers.render_dict_table(preview["rows"]))
    else:
        children.append(ui.p("No other pitch's stored count/inning/RE would change.", class_="text-muted small"))
    if preview["score_changes"]:
        children.append(ui.p("Score change: " + "; ".join(preview["score_changes"]), class_="small fw-bold mt-1"))
    children.append(ui.layout_columns(
        ui.input_action_button("gt_pl_confirm_forced_end_btn", "Confirm -- end half-inning", class_="btn-warning btn-sm mt-2"),
        ui.input_action_button("gt_pl_cancel_forced_end_btn", "Cancel", class_="btn-outline-secondary btn-sm mt-2"),
        col_widths=[6, 6],
    ))
    return ui.div(*children, class_="border border-warning rounded p-2 mb-2")


def _render_runner_add_preview(preview):
    """Same border+Confirm/Cancel convention the other two preview
    blocks in this file use, for INSERTING a brand-new GameRunnerEvent
    anchored right after a past pitch -- the retroactive counterpart to
    the live "+ Log a runner event" form (game_tracking.py's
    runner_events_panel, which can only ever anchor to the pitch just
    thrown). Built so a steal/wild pitch/etc. missed in the moment can
    still be logged after the fact, on any already-tracked game, live
    or completed (Ryker, Sept 2026: "if i need to add a runner event to
    something that i logged before how do i do that")."""
    who = f" ({preview['runner_label']})" if preview.get("runner_label") else ""
    outcome = "out" if preview["is_out"] else TO_BASE_LABEL.get(preview["to_base"], "?")
    summary = f"{preview['event_type']}{who}: {BASE_LABEL.get(preview['from_base'], '?')} \u2192 {outcome}"
    children = [
        ui.h6(f"Preview: log runner event after pitch #{preview['target_seq']}", class_="mt-2"),
        ui.p(
            "Nothing has been saved yet -- review what would change below, then Confirm or Cancel.",
            class_="text-muted small",
        ),
        ui.p(summary, class_="small fw-bold mb-1"),
    ]
    if preview["side_changed_seqs"]:
        children.append(ui.p(
            "Side/inning changed for pitch(es) " + ", ".join(preview["side_changed_seqs"]) +
            " -- this pitch's recorded batter/pitcher may no longer match who was "
            "actually up; review it manually. The count/RE numbers will still be "
            "corrected, but who's listed as playing won't be reassigned automatically.",
            class_="text-warning small fw-bold mb-1",
        ))
    if preview["rows"]:
        children.append(ui.p("Pitches that would change:", class_="small fw-bold mb-1"))
        children.append(ui_helpers.render_dict_table(preview["rows"]))
    else:
        children.append(ui.p("No other pitch's stored count/inning/RE would change.", class_="text-muted small"))
    if preview["score_changes"]:
        children.append(ui.p("Score change: " + "; ".join(preview["score_changes"]), class_="small fw-bold mt-1"))
    children.append(ui.layout_columns(
        ui.input_action_button("gt_pl_confirm_runner_add_btn", "Confirm & Save", class_="btn-warning btn-sm mt-2"),
        ui.input_action_button("gt_pl_cancel_runner_add_btn", "Cancel", class_="btn-outline-secondary btn-sm mt-2"),
        col_widths=[6, 6],
    ))
    return ui.div(*children, class_="border border-warning rounded p-2 mb-2")


def register_game_tracking_pitch_log(
    input, output, session, app_state,
    _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_pa, _bump_refresh,
    _registered_pitch_row_ids, _gt_editing_pitch_id, _gt_pending_delete_pitch_id, _pitch_log_limit,
    _gt_pl_pending_preview, _gt_pl_pending_forced_end,
    _gt_pl_adding_runner_event_pitch_id, _gt_pl_pending_runner_add,
    PITCH_OUTCOMES, CONTACT_QUALITY_OPTIONS, AB_OUTCOMES,
    RUNNER_EVENT_TYPES, RUNNER_EVENT_OUT_TYPES,
    build_re_lookup, replay_game,
):

    @render.ui
    def pitch_log_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            limit = _pitch_log_limit()
            game = db.query(Game).filter(Game.game_id == game_id).first()
            total_count = db.query(GamePitch).filter(GamePitch.game_id == game_id).count()
            pitches = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.our_player), joinedload(GamePitch.opponent_our_player), joinedload(GamePitch.opponent_player))
                .filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence.desc())
                .limit(limit).all()
            )
            if not pitches:
                return ui.div(ui.h5("Pitch log", class_="gbo-section-title"), ui_helpers.empty_state("No pitches logged yet for this game."))

            can_edit = _can_edit()
            editing_id = _gt_editing_pitch_id() if can_edit else None
            pending_delete_id = _gt_pending_delete_pitch_id() if can_edit else None
            pending_preview = _gt_pl_pending_preview() if can_edit else None
            pending_forced_end = _gt_pl_pending_forced_end() if can_edit else None
            pending_runner_add = _gt_pl_pending_runner_add() if can_edit else None
            adding_runner_event_id = _gt_pl_adding_runner_event_pitch_id() if can_edit else None
            pitch_type_choices = {}
            ab_outcome_choices = {}
            if editing_id is not None:
                pitch_type_choices = {pt.type_name: pt.type_name for pt in db.query(PitchType).order_by(PitchType.pitch_type_id).all()}
                ab_outcome_choices = {name: name for name in AB_OUTCOMES}

            rows = [ui.h5(f"Pitch log ({min(len(pitches), total_count)} of {total_count})", class_="gbo-section-title")]
            for p in pitches:
                pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                opponent_label = (
                    (f"{p.opponent_our_player.first_name} {p.opponent_our_player.last_name}" if p.opponent_our_player else None)
                    or (p.opponent_player.player_name if p.opponent_player else None)
                    or (f"#{p.opponent_batting_order} ({p.opponent_hand})" if p.opponent_batting_order else "—")
                )
                player_label = f"{p.our_player.first_name} {p.our_player.last_name}" if p.our_player else "—"

                if can_edit and p.game_pitch_id == editing_id:
                    if pending_preview is not None and pending_preview.get("pitch_id") == p.game_pitch_id:
                        rows.append(_render_preview_block(pending_preview))
                        continue

                    edit_children = [
                        ui.h6(f"Editing pitch #{p.pitch_sequence}", class_="mt-2"),
                        ui.input_select("gt_pl_edit_pitch_type", "Pitch type", choices=pitch_type_choices, selected=pt_name if pt_name in pitch_type_choices else None),
                        ui.input_select("gt_pl_edit_outcome", "Pitch outcome", choices=PITCH_OUTCOMES, selected=p.pitch_outcome if p.pitch_outcome in PITCH_OUTCOMES else None),
                    ]
                    if not p.is_our_team_batting:
                        edit_children.append(ui.layout_columns(
                            ui.input_numeric("gt_pl_edit_ix", "Intended plate side (ft, 0 = center)", value=float(p.intended_plate_x) if p.intended_plate_x is not None else 0.0, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                            ui.input_numeric("gt_pl_edit_iz", "Intended plate height (ft)", value=float(p.intended_plate_z) if p.intended_plate_z is not None else 2.5, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
                        ))
                        edit_children.append(ui.input_checkbox("gt_pl_edit_has_actual", "Actual location recorded", value=p.actual_plate_x is not None))
                        edit_children.append(ui.layout_columns(
                            ui.input_numeric("gt_pl_edit_ax", "Actual plate side (ft)", value=float(p.actual_plate_x) if p.actual_plate_x is not None else 0.0, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                            ui.input_numeric("gt_pl_edit_az", "Actual plate height (ft)", value=float(p.actual_plate_z) if p.actual_plate_z is not None else 2.5, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
                        ))
                    # These three fields aren't conditionally shown/hidden based
                    # on the outcome dropdown the way live entry's
                    # pitch_outcome_dependent_fields does -- this render block
                    # doesn't re-run when gt_pl_edit_outcome changes (it's only
                    # read at save time), so always showing them and saving only
                    # what's relevant (see _save_pitch_log_edit) is the simpler,
                    # safer choice here rather than a second nested render block.
                    edit_children.append(ui.input_select("gt_pl_edit_cq", "Contact quality (optional -- only meaningful if swung at)", choices=["-- N/A --"] + CONTACT_QUALITY_OPTIONS, selected=p.contact_quality or "-- N/A --"))
                    edit_children.append(ui.input_checkbox("gt_pl_edit_sword", "Sword (ugly, off-balance swing)", value=p.is_sword))
                    edit_children.append(ui.input_select("gt_pl_edit_bbt", "Batted ball type (optional -- only meaningful if In Play)", choices=["-- N/A --", "Ground Ball", "Line Drive", "Fly Ball", "Pop Up"], selected=p.batted_ball_type or "-- N/A --"))
                    edit_children.append(ui.layout_columns(
                        ui.input_numeric("gt_pl_edit_bbx", "Feet right of CF line", value=float(p.batted_ball_x) if p.batted_ball_x is not None else 0.0, step=5.0),
                        ui.input_numeric("gt_pl_edit_bby", "Feet from home toward OF", value=float(p.batted_ball_y) if p.batted_ball_y is not None else 150.0, step=5.0),
                    ))
                    edit_children.append(ui.input_text("gt_pl_edit_notes", "Notes (optional)", value=p.notes or ""))

                    # -- Plate-appearance / count-affecting fields (Sept
                    # 2026 -- see module docstring). Always shown while
                    # editing, same "always show, save only what's
                    # relevant" convention as the fields above -- saving
                    # any of these routes through the preview flow
                    # instead of an instant save, see
                    # _save_pitch_log_edit/STATE_AFFECTING_FIELDS.
                    edit_children.append(ui.hr())
                    edit_children.append(ui.p(
                        "Plate appearance / count state (advanced) -- changing "
                        "any of these can shift every later pitch's stored count, "
                        "inning, and score; you'll see a preview of exactly what "
                        "would change before anything is saved.",
                        class_="text-muted small mb-1",
                    ))
                    edit_children.append(ui.input_checkbox("gt_pl_edit_ends_pa", "This pitch ends the plate appearance", value=bool(p.ends_plate_appearance)))
                    edit_children.append(ui.input_select("gt_pl_edit_ab_outcome", "AB outcome", choices=ab_outcome_choices, selected=p.ab_outcome if p.ab_outcome in ab_outcome_choices else None))
                    edit_children.append(ui.layout_columns(
                        ui.input_numeric("gt_pl_edit_outs_after", "Outs after", value=p.outs_after if p.outs_after is not None else 0, min=0, max=3, step=1),
                        ui.input_text("gt_pl_edit_bases_after", "Bases after (1st,2nd,3rd = 1/0)", value=p.bases_after or "000"),
                        ui.input_numeric("gt_pl_edit_runs", "Runs scored on play", value=p.runs_scored_on_play or 0, min=0, max=4, step=1),
                    ))
                    edit_children.append(ui.input_numeric("gt_pl_edit_unearned", "Of those, unearned (error-caused)", value=p.unearned_runs_on_play or 0, min=0, max=4, step=1))

                    edit_children.append(ui.layout_columns(
                        ui.input_action_button("gt_pl_save_edit_btn", "Save", class_="btn-primary btn-sm"),
                        ui.input_action_button("gt_pl_cancel_edit_btn", "Cancel", class_="btn-outline-secondary btn-sm"),
                        col_widths=[6, 6],
                    ))
                    rows.append(ui.div(*edit_children, class_="border rounded p-2 mb-2"))
                    continue

                if can_edit and p.game_pitch_id == pending_delete_id:
                    warn = f"Delete pitch #{p.pitch_sequence} ({pt_name})? This can't be undone."
                    if p.ends_plate_appearance and p.runs_scored_on_play:
                        warn += f" This will also reverse {p.runs_scored_on_play} run(s) credited on this play."
                    rows.append(ui.div(
                        ui.p(warn, class_="text-danger mb-1"),
                        ui.layout_columns(
                            ui.input_action_button("gt_pl_confirm_delete_btn", "Confirm delete", class_="btn-danger btn-sm"),
                            ui.input_action_button("gt_pl_cancel_delete_btn", "Cancel", class_="btn-outline-secondary btn-sm"),
                            col_widths=[6, 6],
                        ),
                        class_="border border-danger rounded p-2 mb-2",
                    ))
                    continue

                if can_edit and pending_forced_end is not None and pending_forced_end.get("pitch_id") == p.game_pitch_id:
                    rows.append(_render_forced_end_preview(pending_forced_end))
                    continue

                if can_edit and pending_runner_add is not None and pending_runner_add.get("pitch_id") == p.game_pitch_id:
                    rows.append(_render_runner_add_preview(pending_runner_add))
                    continue

                if can_edit and p.game_pitch_id == adding_runner_event_id:
                    bases_here = (p.bases_after if p.ends_plate_appearance else p.bases_before) or "000"
                    occupied_here = [i + 1 for i, c in enumerate(bases_here) if c == "1"]
                    add_children = [ui.h6(f"Log runner event after pitch #{p.pitch_sequence}", class_="mt-2")]
                    if not occupied_here:
                        add_children.append(ui.p("No runners on base at this point -- nothing to log here.", class_="text-muted small"))
                        add_children.append(ui.input_action_button("gt_pl_cancel_runner_add_form_btn", "Cancel", class_="btn-outline-secondary btn-sm"))
                    else:
                        from_choices_here = {str(b): BASE_LABEL[b] for b in occupied_here}
                        add_children.append(ui.layout_columns(
                            ui.input_select("gt_pl_add_event_type", "Event", choices=RUNNER_EVENT_TYPES),
                            ui.input_select("gt_pl_add_from_base", "Runner on", choices=from_choices_here),
                            col_widths=[7, 5],
                        ))
                        add_children.append(ui.output_ui("pitch_log_runner_add_fields"))
                        add_children.append(ui.layout_columns(
                            ui.input_action_button("gt_pl_save_runner_add_btn", "Log runner event", class_="btn-primary btn-sm mt-2"),
                            ui.input_action_button("gt_pl_cancel_runner_add_form_btn", "Cancel", class_="btn-outline-secondary btn-sm mt-2"),
                            col_widths=[6, 6],
                        ))
                    rows.append(ui.div(*add_children, class_="border rounded p-2 mb-2"))
                    continue

                side = "Us batting" if p.is_our_team_batting else "Us pitching"
                # Distinguish the three states a coach can hit here, rather
                # than a bare "—" that reads the same whether location never
                # applies (we were batting), or it applies but Video Review
                # hasn't happened yet (intended IS already known -- only
                # actual is pending, see _vr_save/video_review_body), or it's
                # genuinely both missing. A plain dash for the "pending"
                # case looked identical to "no data" and was confusing.
                if p.is_our_team_batting:
                    loc = "—"
                else:
                    intended_str = f"{float(p.intended_plate_x):+.2f}, {float(p.intended_plate_z):.2f}" if p.intended_plate_x is not None else "—"
                    if p.actual_plate_x is not None:
                        loc = f"Intended {intended_str} / Actual {float(p.actual_plate_x):+.2f}, {float(p.actual_plate_z):.2f}"
                    else:
                        loc = f"Intended {intended_str} / Actual: awaiting video review"
                bb = ((p.batted_ball_type or "") + (f" ({float(p.batted_ball_x):+.0f}, {float(p.batted_ball_y):.0f})" if p.batted_ball_x is not None else "")) if (p.batted_ball_type or p.batted_ball_x is not None) else "—"
                line1 = f"#{p.pitch_sequence} — Inn {p.inning}, {side} — {player_label} vs {opponent_label} — {pt_name}"
                line2 = f"{(p.pitch_outcome or '—')}{' (Sword)' if p.is_sword else ''} — {loc} — Batted ball {bb}" + (" — 🎥" if p.video_url else "")
                summary_children = [ui.p(line1, class_="mb-0 small"), ui.p(line2, class_="text-muted small mb-0")]
                if p.ends_plate_appearance:
                    re_before_str = f"{float(p.re_before):.2f}" if p.re_before is not None else "—"
                    re_after_str = f"{float(p.re_after):.2f}" if p.re_after is not None else "—"
                    rv_str = f"{float(p.run_value):+.3f}" if p.run_value is not None else "—"
                    runs_str = f"{p.runs_scored_on_play}" + (f" ({p.unearned_runs_on_play} unearned)" if p.unearned_runs_on_play else "")
                    summary_children.append(ui.p(
                        f"AB: {p.ab_outcome or '—'} — Runs {runs_str} — RE {re_before_str}→{re_after_str} (RV {rv_str})",
                        class_="text-muted small mb-0",
                    ))
                if p.notes:
                    summary_children.append(ui.p(p.notes, class_="text-muted small mb-0 fst-italic"))

                if can_edit:
                    edit_btn_id = f"gt_pl_edit_btn_{p.game_pitch_id}"
                    delete_btn_id = f"gt_pl_delete_btn_{p.game_pitch_id}"
                    # "End half-inning after this" -- intrasquad only, and
                    # only offered on a pitch where we were PITCHING (the
                    # side a pitch-count limit actually applies to). See
                    # forced_half_inning_end_panel (game_tracking.py) for
                    # the live version; this is the retroactive fix for an
                    # outing that already ended this way without a formal
                    # 3rd out being recorded (Ryker's Kurt Kassner example).
                    can_end_here = bool(game is not None and game.is_intrasquad and not p.is_our_team_batting)
                    # "Log runner event" -- offered on ANY pitch that left
                    # at least one runner on base (steals/caught stealing/
                    # pickoffs/wild pitches/passed balls/balks can happen
                    # regardless of which side is batting or whether this
                    # is an intrasquad game), so a coach can go back and
                    # log something missed in the moment on an
                    # already-tracked game (Ryker, Sept 2026 -- see
                    # _render_runner_add_preview above for the full story).
                    bases_now = (p.bases_after if p.ends_plate_appearance else p.bases_before) or "000"
                    can_add_runner_event_here = "1" in bases_now
                    buttons = [
                        ui.input_action_button(edit_btn_id, "Edit", class_="btn-outline-primary btn-sm"),
                        ui.input_action_button(delete_btn_id, "Delete", class_="btn-outline-danger btn-sm"),
                    ]
                    if can_end_here:
                        forced_end_btn_id = f"gt_pl_forced_end_btn_{p.game_pitch_id}"
                        forced_end_same_side_btn_id = f"gt_pl_forced_end_same_side_btn_{p.game_pitch_id}"
                        if game is not None and game.uses_three_squad_intrasquad:
                            buttons.append(ui.input_action_button(forced_end_btn_id, "End half-inning (new team up)", class_="btn-outline-warning btn-sm"))
                            buttons.append(ui.input_action_button(forced_end_same_side_btn_id, "End half-inning (same team continues)", class_="btn-outline-warning btn-sm"))
                        else:
                            buttons.append(ui.input_action_button(forced_end_btn_id, "End half-inning after this", class_="btn-outline-warning btn-sm"))
                    if can_add_runner_event_here:
                        add_runner_btn_id = f"gt_pl_add_runner_btn_{p.game_pitch_id}"
                        buttons.append(ui.input_action_button(add_runner_btn_id, "Log runner event", class_="btn-outline-info btn-sm"))
                    summary_width = 12 - 2 * len(buttons)
                    rows.append(ui.layout_columns(
                        ui.div(*summary_children),
                        *buttons,
                        col_widths=[summary_width] + [2] * len(buttons),
                    ))
                    if edit_btn_id not in _registered_pitch_row_ids:
                        _registered_pitch_row_ids.add(edit_btn_id)
                        _registered_pitch_row_ids.add(delete_btn_id)
                        _register_pitch_row_handlers(p.game_pitch_id, can_end_here, can_add_runner_event_here)
                else:
                    rows.append(ui.div(*summary_children))

            if total_count > len(pitches):
                rows.append(ui.input_action_button("gt_pl_load_more_btn", f"Load 50 more ({total_count - len(pitches)} older pitch(es) not shown)", class_="btn-outline-secondary btn-sm mt-2"))

            return ui.div(*rows)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.gt_pl_load_more_btn)
    def _load_more_pitch_log():
        _pitch_log_limit.set(_pitch_log_limit() + 50)

    def _register_pitch_row_handlers(pitch_id, can_end_here=False, can_add_runner_event_here=False):
        edit_btn_id = f"gt_pl_edit_btn_{pitch_id}"
        delete_btn_id = f"gt_pl_delete_btn_{pitch_id}"

        @reactive.effect
        @reactive.event(input[edit_btn_id])
        def _on_pitch_log_edit_trigger():
            _gt_pending_delete_pitch_id.set(None)
            _gt_pl_pending_preview.set(None)
            _gt_pl_pending_forced_end.set(None)
            _gt_pl_adding_runner_event_pitch_id.set(None)
            _gt_pl_pending_runner_add.set(None)
            _gt_editing_pitch_id.set(pitch_id)
            _bump_refresh()

        @reactive.effect
        @reactive.event(input[delete_btn_id])
        def _on_pitch_log_delete_trigger():
            _gt_editing_pitch_id.set(None)
            _gt_pl_pending_preview.set(None)
            _gt_pl_pending_forced_end.set(None)
            _gt_pl_adding_runner_event_pitch_id.set(None)
            _gt_pl_pending_runner_add.set(None)
            _gt_pending_delete_pitch_id.set(pitch_id)
            _bump_refresh()

        if can_add_runner_event_here:
            add_runner_btn_id = f"gt_pl_add_runner_btn_{pitch_id}"

            @reactive.effect
            @reactive.event(input[add_runner_btn_id])
            def _on_pitch_log_add_runner_trigger():
                _gt_editing_pitch_id.set(None)
                _gt_pending_delete_pitch_id.set(None)
                _gt_pl_pending_preview.set(None)
                _gt_pl_pending_forced_end.set(None)
                _gt_pl_pending_runner_add.set(None)
                _gt_pl_adding_runner_event_pitch_id.set(pitch_id)
                _bump_refresh()

        if not can_end_here:
            return

        forced_end_btn_id = f"gt_pl_forced_end_btn_{pitch_id}"
        forced_end_same_side_btn_id = f"gt_pl_forced_end_same_side_btn_{pitch_id}"

        def _build_forced_end_preview(same_side_continues):
            game_id = _active_game_id()
            if game_id is None:
                return
            db = get_session()
            try:
                game = (
                    db.query(Game)
                    .options(joinedload(Game.runner_events), joinedload(Game.forced_half_inning_ends))
                    .filter(Game.game_id == game_id)
                    .first()
                )
                p = (
                    db.query(GamePitch).options(joinedload(GamePitch.our_player))
                    .filter(GamePitch.game_pitch_id == pitch_id).first()
                )
                if game is None or p is None or p.is_our_team_batting:
                    return

                all_pitches = sorted(game.pitches, key=lambda x: x.pitch_sequence)
                all_events = sorted(game.runner_events, key=lambda e: (e.pitch_sequence_after, e.created_at))
                existing_forced_ends = sorted(game.forced_half_inning_ends, key=lambda e: e.pitch_sequence_after)

                # Runners on base right after this specific pitch -- the
                # same state compute_current_state would land on if this
                # were the last pitch recorded (bases_after when this
                # pitch ended the PA, otherwise bases_before carries
                # straight through since a non-ending pitch never changes
                # bases). See models.GameForcedHalfInningEnd's docstring.
                bases = (p.bases_after if p.ends_plate_appearance else p.bases_before) or "000"
                runs_scored = bases.count("1")
                pending_event = GameForcedHalfInningEnd(
                    game_id=game_id, pitch_sequence_after=p.pitch_sequence,
                    inning=p.inning, is_our_team_batting=p.is_our_team_batting,
                    batting_squad=p.batting_squad, runs_scored=runs_scored,
                    credited_player_id=p.our_player_id,
                    same_side_continues=same_side_continues,
                )
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, existing_forced_ends + [pending_event])
                rows, side_changed_seqs, score_changes = _build_preview_rows(all_pitches, result, game)

                _gt_pl_pending_forced_end.set({
                    "pitch_id": pitch_id,
                    "target_seq": p.pitch_sequence,
                    "runs_scored": runs_scored,
                    "credited_player_label": f"{p.our_player.first_name} {p.our_player.last_name}" if p.our_player else None,
                    "rows": rows,
                    "side_changed_seqs": side_changed_seqs,
                    "score_changes": score_changes,
                    "same_side_continues": same_side_continues,
                })
                _gt_editing_pitch_id.set(None)
                _gt_pending_delete_pitch_id.set(None)
                _gt_pl_pending_preview.set(None)
                _gt_pl_adding_runner_event_pitch_id.set(None)
                _gt_pl_pending_runner_add.set(None)
                _bump_refresh()
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[forced_end_btn_id])
        def _on_pitch_log_forced_end_trigger():
            _build_forced_end_preview(False)

        @reactive.effect
        @reactive.event(input[forced_end_same_side_btn_id])
        def _on_pitch_log_forced_end_same_side_trigger():
            _build_forced_end_preview(True)

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_edit_btn)
    def _cancel_pitch_log_edit():
        _gt_editing_pitch_id.set(None)
        _gt_pl_pending_preview.set(None)
        _gt_pl_pending_forced_end.set(None)
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _gt_pl_pending_runner_add.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_save_edit_btn)
    def _save_pitch_log_edit():
        pitch_id = _gt_editing_pitch_id()
        if pitch_id is None:
            return
        req("gt_pl_edit_pitch_type" in input)
        req("gt_pl_edit_outcome" in input)

        pitch_type_name = input.gt_pl_edit_pitch_type()
        outcome = input.gt_pl_edit_outcome()
        notes = (input.gt_pl_edit_notes() or "").strip() or None

        db = get_session()
        # save_result distinguishes "wrote something, close out the edit
        # UI and bump the live-tracking state" (instant leaf save, or a
        # confirmed preview -- the latter happens in
        # _confirm_pitch_log_preview, not here) from "showed a preview /
        # a validation error, leave everything as-is" -- see the bottom
        # of this function.
        save_result = None
        try:
            pitch = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if pitch is None:
                _gt_editing_pitch_id.set(None)
                _gt_pl_pending_preview.set(None)
                _bump_refresh()
                return

            values = {}
            pitch_type = db.query(PitchType).filter(PitchType.type_name == pitch_type_name).first()
            values["pitch_type_id"] = pitch_type.pitch_type_id if pitch_type else None
            values["pitch_outcome"] = outcome
            values["notes"] = notes

            if not pitch.is_our_team_batting and "gt_pl_edit_ix" in input:
                intended_x, intended_z = input.gt_pl_edit_ix(), input.gt_pl_edit_iz()
                has_actual = bool(input.gt_pl_edit_has_actual()) if "gt_pl_edit_has_actual" in input else pitch.actual_plate_x is not None
                actual_x = input.gt_pl_edit_ax() if has_actual else None
                actual_z = input.gt_pl_edit_az() if has_actual else None
                values["intended_plate_x"] = intended_x
                values["intended_plate_z"] = intended_z
                values["actual_plate_x"] = actual_x
                values["actual_plate_z"] = actual_z
                values["intended_zone"] = strike_zone.derive_old_zone(intended_x, intended_z)
                values["pitch_zone"] = strike_zone.derive_old_zone(actual_x, actual_z)

            if outcome in ("In Play", "Foul", "Swing and Miss") and "gt_pl_edit_cq" in input:
                raw_cq = input.gt_pl_edit_cq()
                values["contact_quality"] = raw_cq if raw_cq and raw_cq != "-- N/A --" else None
                values["is_sword"] = bool(input.gt_pl_edit_sword()) if "gt_pl_edit_sword" in input else False
            else:
                values["contact_quality"] = None
                values["is_sword"] = False

            if outcome == "In Play" and "gt_pl_edit_bbt" in input:
                raw_bbt = input.gt_pl_edit_bbt()
                values["batted_ball_type"] = raw_bbt if raw_bbt and raw_bbt != "-- N/A --" else None
                values["batted_ball_x"] = input.gt_pl_edit_bbx() if "gt_pl_edit_bbx" in input else None
                values["batted_ball_y"] = input.gt_pl_edit_bby() if "gt_pl_edit_bby" in input else None
            else:
                values["batted_ball_type"] = None
                values["batted_ball_x"] = None
                values["batted_ball_y"] = None

            # -- Plate-appearance / count-affecting fields (see module
            # docstring). Gated by the ends-plate-appearance checkbox,
            # mirroring how live entry gates the same fields by the
            # automatic count math (_ends_plate_appearance) -- here it's
            # the coach's explicit call instead of the count, since
            # they're editing a pitch after the fact and may know better
            # than what the count alone would suggest.
            ends_pa_checked = bool(input.gt_pl_edit_ends_pa()) if "gt_pl_edit_ends_pa" in input else bool(pitch.ends_plate_appearance)
            if ends_pa_checked:
                if "gt_pl_edit_ab_outcome" not in input:
                    ui.notification_show("Confirm the AB outcome before saving -- not saved.", type="error", duration=8)
                    return
                ab_outcome_val = input.gt_pl_edit_ab_outcome()
                outs_after_val = int(input.gt_pl_edit_outs_after())
                bases_after_val = (input.gt_pl_edit_bases_after() or "").strip()
                if not re.fullmatch(r"[01]{3}", bases_after_val):
                    ui.notification_show(
                        'Bases after must be exactly 3 characters of 0/1 (e.g. "010" = runner on 2nd only) -- not saved.',
                        type="error", duration=10,
                    )
                    return
                runs_val = int(input.gt_pl_edit_runs())
                unearned_val = int(input.gt_pl_edit_unearned()) if "gt_pl_edit_unearned" in input else 0
                if unearned_val > runs_val:
                    ui.notification_show("Unearned runs can't exceed runs scored on the play -- not saved.", type="error", duration=8)
                    return
            else:
                ab_outcome_val = None
                outs_after_val = None
                bases_after_val = None
                runs_val = 0
                unearned_val = 0

            values["ends_plate_appearance"] = ends_pa_checked
            values["ab_outcome"] = ab_outcome_val
            values["outs_after"] = outs_after_val
            values["bases_after"] = bases_after_val
            values["runs_scored_on_play"] = runs_val
            values["unearned_runs_on_play"] = unearned_val

            state_changed = any(getattr(pitch, f) != values[f] for f in STATE_AFFECTING_FIELDS)

            if not state_changed:
                # Pure leaf edit (or a no-op re-save of the same
                # state-affecting values) -- instant save, exactly like
                # this form has always worked.
                _apply_field_values(pitch, values)
                db.commit()
                ui.notification_show(f"Updated pitch #{pitch.pitch_sequence}.", type="message", duration=6)
                save_result = "instant"
            else:
                # State-affecting change -- build the preview instead of
                # writing anything. Query the rest of the game BEFORE
                # mutating `pitch` in memory below, so this read can't
                # trigger an autoflush of the not-yet-confirmed edit.
                game_id = pitch.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                all_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()
                _apply_field_values(pitch, values)  # in-memory only, on the ORM object already inside all_pitches
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, all_forced_ends)
                preview_rows, side_changed_seqs, score_changes = _build_preview_rows(all_pitches, result, game)
                _gt_pl_pending_preview.set({
                    "pitch_id": pitch_id,
                    "target_seq": pitch.pitch_sequence,
                    "edits": values,
                    "rows": preview_rows,
                    "side_changed_seqs": side_changed_seqs,
                    "score_changes": score_changes,
                })
                save_result = "preview"
                # Deliberately no db.commit() here -- closing this
                # session below with nothing committed rolls back the
                # in-memory edit above (and any autoflush of it), same
                # dry-run posture scripts/backfill_opponent_hand.py uses
                # for DB backfills without --apply.
        finally:
            db.close()

        if save_result == "instant":
            _gt_editing_pitch_id.set(None)
            _gt_pl_pending_preview.set(None)
            _bump_pa()
            _bump_refresh()
        elif save_result == "preview":
            _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_preview_btn)
    def _cancel_pitch_log_preview():
        _gt_pl_pending_preview.set(None)
        _gt_editing_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_confirm_preview_btn)
    def _confirm_pitch_log_preview():
        """The only place a state-affecting Pitch Log edit actually gets
        written. Re-derives everything fresh from the DB rather than
        trusting the preview's own cached rows -- if a live pitch got
        recorded (or anything else about the game changed) in the time
        between the preview being built and this click, the WRITE is
        still correct (just re-run replay_game against current data);
        only the on-screen preview the coach reviewed could have been
        stale, never what actually gets saved."""
        preview = _gt_pl_pending_preview()
        if preview is None:
            return
        pitch_id = preview["pitch_id"]
        db = get_session()
        try:
            pitch = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if pitch is None:
                ui.notification_show("That pitch no longer exists -- nothing saved.", type="warning", duration=8)
            else:
                game_id = pitch.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                all_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()
                _apply_field_values(pitch, preview["edits"])
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, all_forced_ends)
                for p2 in all_pitches:
                    r = result["by_pitch"].get(p2.game_pitch_id)
                    if r is None:
                        continue
                    for field in REPLAY_OWNED_FIELDS:
                        setattr(p2, field, r[field])
                if game is not None:
                    game.our_score = result["our_score"]
                    game.opponent_score = result["opponent_score"]
                    game.squad_c_score = result["squad_c_score"]
                db.commit()
                ui.notification_show(
                    f"Updated pitch #{pitch.pitch_sequence} and re-synced {len(all_pitches)} pitch(es) in this game.",
                    type="message", duration=8,
                )
        finally:
            db.close()
        _gt_pl_pending_preview.set(None)
        _gt_editing_pitch_id.set(None)
        _bump_pa()
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_forced_end_btn)
    def _cancel_pitch_log_forced_end():
        _gt_pl_pending_forced_end.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_confirm_forced_end_btn)
    def _confirm_pitch_log_forced_end():
        """Writes the new GameForcedHalfInningEnd, then re-syncs the
        whole game exactly like _confirm_pitch_log_preview does for an
        edited pitch -- re-derived fresh from the DB rather than trusting
        the preview's cached numbers, same staleness guard."""
        preview = _gt_pl_pending_forced_end()
        if preview is None:
            return
        pitch_id = preview["pitch_id"]
        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                ui.notification_show("That pitch no longer exists -- nothing saved.", type="warning", duration=8)
            else:
                game_id = p.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                existing_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()

                bases = (p.bases_after if p.ends_plate_appearance else p.bases_before) or "000"
                runs_scored = bases.count("1")
                new_event = GameForcedHalfInningEnd(
                    game_id=game_id, pitch_sequence_after=p.pitch_sequence,
                    inning=p.inning, is_our_team_batting=p.is_our_team_batting,
                    batting_squad=p.batting_squad, runs_scored=runs_scored,
                    credited_player_id=p.our_player_id,
                    same_side_continues=bool(preview.get("same_side_continues")),
                    created_by_user_id=app_state.user_id(),
                )
                db.add(new_event)

                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, existing_forced_ends + [new_event])
                for p2 in all_pitches:
                    r = result["by_pitch"].get(p2.game_pitch_id)
                    if r is None:
                        continue
                    for field in REPLAY_OWNED_FIELDS:
                        setattr(p2, field, r[field])
                if game is not None:
                    game.our_score = result["our_score"]
                    game.opponent_score = result["opponent_score"]
                    game.squad_c_score = result["squad_c_score"]
                db.commit()
                ui.notification_show(
                    f"Half-inning ended after pitch #{p.pitch_sequence} -- {len(all_pitches)} pitch(es) re-synced.",
                    type="message", duration=8,
                )
        finally:
            db.close()
        _gt_pl_pending_forced_end.set(None)
        _bump_pa()
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_delete_btn)
    def _cancel_pitch_log_delete():
        _gt_pending_delete_pitch_id.set(None)
        _gt_pl_pending_forced_end.set(None)
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _gt_pl_pending_runner_add.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_confirm_delete_btn)
    def _confirm_pitch_log_delete():
        pitch_id = _gt_pending_delete_pitch_id()
        if pitch_id is None:
            return
        db = get_session()
        try:
            pitch = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if pitch is None:
                _gt_pending_delete_pitch_id.set(None)
                _bump_refresh()
                return
            game = db.query(Game).filter(Game.game_id == pitch.game_id).first()
            if game is not None and pitch.ends_plate_appearance and pitch.runs_scored_on_play:
                if pitch.batting_squad == "A":
                    game.our_score = max(0, game.our_score - pitch.runs_scored_on_play)
                elif pitch.batting_squad == "B":
                    game.opponent_score = max(0, game.opponent_score - pitch.runs_scored_on_play)
                elif pitch.batting_squad == "C":
                    game.squad_c_score = max(0, game.squad_c_score - pitch.runs_scored_on_play)
                elif pitch.is_our_team_batting:
                    game.our_score = max(0, game.our_score - pitch.runs_scored_on_play)
                else:
                    game.opponent_score = max(0, game.opponent_score - pitch.runs_scored_on_play)
            deleted_seq = pitch.pitch_sequence
            db.delete(pitch)
            db.commit()
            ui.notification_show(f"Deleted pitch #{deleted_seq}.", type="message", duration=6)
        finally:
            db.close()
        _gt_pending_delete_pitch_id.set(None)
        _bump_pa()
        _bump_refresh()

    @render.ui
    def pitch_log_runner_add_fields():
        """Dynamic to_base/runner-identity sub-fields for the
        retroactive "Log runner event" form -- same split
        runner_event_fields() (the live version, game_tracking.py)
        uses, just anchored to a past pitch instead of "right now"."""
        if not _can_edit():
            return None
        pitch_id = _gt_pl_adding_runner_event_pitch_id()
        if pitch_id is None:
            return None
        req("gt_pl_add_event_type" in input)
        req("gt_pl_add_from_base" in input)
        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                return None
            game = db.query(Game).filter(Game.game_id == p.game_id).first()
            if game is None:
                return None

            event_type = input.gt_pl_add_event_type()
            from_base_val = int(input.gt_pl_add_from_base())
            is_out_type = event_type in RUNNER_EVENT_OUT_TYPES

            fields = []
            if is_out_type:
                fields.append(ui.p(f"Recorded as an out at {BASE_LABEL.get(from_base_val, '?')}.", class_="text-muted small"))
            else:
                to_choices = {str(b): TO_BASE_LABEL[b] for b in (2, 3, 4) if b > from_base_val}
                fields.append(ui.input_select("gt_pl_add_to_base", "Advances to", choices=to_choices))

            our_choices, opp_roster = _runner_choices_for_event(db, game, p.is_our_team_batting, p.batting_squad)
            runner_choices = {"": "-- Unspecified --"}
            if our_choices:
                runner_choices.update(our_choices)
            elif opp_roster:
                runner_choices.update({str(op.opponent_player_id): op.player_name for op in opp_roster})
            fields.append(ui.input_select("gt_pl_add_runner", "Runner (optional)", choices=runner_choices))
            fields.append(ui.input_text("gt_pl_add_notes", "Notes (optional)", value=""))
            return ui.div(*fields)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_runner_add_form_btn)
    def _cancel_runner_add_form():
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _gt_pl_pending_runner_add.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_save_runner_add_btn)
    def _save_runner_add():
        pitch_id = _gt_pl_adding_runner_event_pitch_id()
        if pitch_id is None:
            return
        req("gt_pl_add_event_type" in input)
        req("gt_pl_add_from_base" in input)

        event_type = input.gt_pl_add_event_type()
        from_base = int(input.gt_pl_add_from_base())
        is_out = event_type in RUNNER_EVENT_OUT_TYPES
        to_base = None
        if not is_out:
            if "gt_pl_add_to_base" not in input or not input.gt_pl_add_to_base():
                ui.notification_show("Pick where the runner advances to.", type="error", duration=8)
                return
            to_base = int(input.gt_pl_add_to_base())

        runner_raw = input.gt_pl_add_runner() if "gt_pl_add_runner" in input else ""
        notes = (input.gt_pl_add_notes() or "").strip() if "gt_pl_add_notes" in input else ""
        notes = notes or None

        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                ui.notification_show("That pitch no longer exists -- not saved.", type="warning", duration=8)
                _gt_pl_adding_runner_event_pitch_id.set(None)
                _bump_refresh()
                return
            game_id = p.game_id
            game = db.query(Game).filter(Game.game_id == game_id).first()

            our_choices, opp_roster = _runner_choices_for_event(db, game, p.is_our_team_batting, p.batting_squad)
            our_player_id = None
            opponent_player_id = None
            runner_label = None
            if runner_raw:
                if our_choices is not None:
                    our_player_id = int(runner_raw)
                    runner_label = our_choices.get(runner_raw)
                else:
                    opponent_player_id = int(runner_raw)
                    runner_label = next((op.player_name for op in (opp_roster or []) if str(op.opponent_player_id) == runner_raw), None)

            pending_event = GameRunnerEvent(
                game_id=game_id, pitch_sequence_after=p.pitch_sequence,
                is_our_team_batting=p.is_our_team_batting, batting_squad=p.batting_squad,
                event_type=event_type, from_base=from_base, to_base=to_base, is_out=is_out,
                our_player_id=our_player_id, opponent_player_id=opponent_player_id, notes=notes,
            )

            all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
            all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
            all_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()
            re_lookup = build_re_lookup(db)
            result = replay_game(all_pitches, all_events + [pending_event], re_lookup, all_forced_ends)
            rows, side_changed_seqs, score_changes = _build_preview_rows(all_pitches, result, game)

            _gt_pl_pending_runner_add.set({
                "pitch_id": pitch_id,
                "target_seq": p.pitch_sequence,
                "event_type": event_type, "from_base": from_base, "to_base": to_base, "is_out": is_out,
                "our_player_id": our_player_id, "opponent_player_id": opponent_player_id, "notes": notes,
                "runner_label": runner_label,
                "rows": rows,
                "side_changed_seqs": side_changed_seqs,
                "score_changes": score_changes,
            })
            # Deliberately no db.commit() -- pending_event was never
            # added to `db` (db.add was never called), so closing this
            # session below discards it for free, same dry-run posture
            # every other preview in this file uses.
        finally:
            db.close()
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_runner_add_btn)
    def _cancel_runner_add_preview():
        _gt_pl_pending_runner_add.set(None)
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_confirm_runner_add_btn)
    def _confirm_runner_add():
        """Writes the new GameRunnerEvent, then re-syncs the whole game
        exactly like the other two preview-then-confirm flows in this
        file -- re-derived fresh from the DB rather than trusting the
        preview's cached numbers, same staleness guard
        _confirm_pitch_log_preview/_confirm_pitch_log_forced_end use."""
        preview = _gt_pl_pending_runner_add()
        if preview is None:
            return
        pitch_id = preview["pitch_id"]
        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                ui.notification_show("That pitch no longer exists -- nothing saved.", type="warning", duration=8)
            else:
                game_id = p.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = db.query(GamePitch).filter(GamePitch.game_id == game_id).all()
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                all_forced_ends = db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == game_id).all()

                new_event = GameRunnerEvent(
                    game_id=game_id, pitch_sequence_after=p.pitch_sequence,
                    is_our_team_batting=p.is_our_team_batting, batting_squad=p.batting_squad,
                    event_type=preview["event_type"], from_base=preview["from_base"],
                    to_base=preview["to_base"], is_out=preview["is_out"],
                    our_player_id=preview["our_player_id"], opponent_player_id=preview["opponent_player_id"],
                    notes=preview["notes"], created_by_user_id=app_state.user_id(),
                )
                db.add(new_event)

                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events + [new_event], re_lookup, all_forced_ends)
                for p2 in all_pitches:
                    r = result["by_pitch"].get(p2.game_pitch_id)
                    if r is None:
                        continue
                    for field in REPLAY_OWNED_FIELDS:
                        setattr(p2, field, r[field])
                if game is not None:
                    game.our_score = result["our_score"]
                    game.opponent_score = result["opponent_score"]
                    game.squad_c_score = result["squad_c_score"]
                db.commit()
                ui.notification_show(
                    f"Logged {preview['event_type']} after pitch #{p.pitch_sequence} -- {len(all_pitches)} pitch(es) re-synced.",
                    type="message", duration=8,
                )
        finally:
            db.close()
        _gt_pl_pending_runner_add.set(None)
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _bump_pa()
        _bump_refresh()
