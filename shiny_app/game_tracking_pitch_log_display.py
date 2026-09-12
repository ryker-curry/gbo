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
from models import Game, GamePitch, GameRunnerEvent, PitchType
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


def register_game_tracking_pitch_log(
    input, output, session,
    _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_pa, _bump_refresh,
    _registered_pitch_row_ids, _gt_editing_pitch_id, _gt_pending_delete_pitch_id, _pitch_log_limit,
    _gt_pl_pending_preview,
    PITCH_OUTCOMES, CONTACT_QUALITY_OPTIONS, AB_OUTCOMES,
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
                    rows.append(ui.layout_columns(
                        ui.div(*summary_children),
                        ui.input_action_button(edit_btn_id, "Edit", class_="btn-outline-primary btn-sm"),
                        ui.input_action_button(delete_btn_id, "Delete", class_="btn-outline-danger btn-sm"),
                        col_widths=[8, 2, 2],
                    ))
                    if edit_btn_id not in _registered_pitch_row_ids:
                        _registered_pitch_row_ids.add(edit_btn_id)
                        _registered_pitch_row_ids.add(delete_btn_id)
                        _register_pitch_row_handlers(p.game_pitch_id)
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

    def _register_pitch_row_handlers(pitch_id):
        edit_btn_id = f"gt_pl_edit_btn_{pitch_id}"
        delete_btn_id = f"gt_pl_delete_btn_{pitch_id}"

        @reactive.effect
        @reactive.event(input[edit_btn_id])
        def _on_pitch_log_edit_trigger():
            _gt_pending_delete_pitch_id.set(None)
            _gt_pl_pending_preview.set(None)
            _gt_editing_pitch_id.set(pitch_id)
            _bump_refresh()

        @reactive.effect
        @reactive.event(input[delete_btn_id])
        def _on_pitch_log_delete_trigger():
            _gt_editing_pitch_id.set(None)
            _gt_pl_pending_preview.set(None)
            _gt_pending_delete_pitch_id.set(pitch_id)
            _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_pl_cancel_edit_btn)
    def _cancel_pitch_log_edit():
        _gt_editing_pitch_id.set(None)
        _gt_pl_pending_preview.set(None)
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
                _apply_field_values(pitch, values)  # in-memory only, on the ORM object already inside all_pitches
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup)
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
                _apply_field_values(pitch, preview["edits"])
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup)
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
    @reactive.event(input.gt_pl_cancel_delete_btn)
    def _cancel_pitch_log_delete():
        _gt_pending_delete_pitch_id.set(None)
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
