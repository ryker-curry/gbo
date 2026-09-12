"""
GBO -- Game Tracking's "Runner Events" log, a new tab mirroring
game_tracking_pitch_log_display.py's Tier 2 split pattern (Sept 2026,
Ryker: "also need to be able to edit runner events such as wild pitch,
stolen base etc.").

Until now GameRunnerEvent only supported two operations: add one (the
collapsed form in runner_events_panel, game_tracking.py) and undo the
single most recent one (_undo_last_runner_event) -- there was no way to
see the full history for a game, or to fix/remove an event recorded
several pitches ago. This file adds that: a full listing (works both
mid-game and after completion, same as Pitch Log), with per-row
Edit/Delete.

Editing or deleting an event that supplied an out or a base advance can
change everything computed from it forward -- exactly the problem
Pitch Log's own edit already solved via game_tracking.py's replay_game(),
which already accepts a runner_events list (that's the whole reason this
feature was straightforward to add: no changes to the replay engine
itself were needed, only this UI). So both Edit and Delete here route
through the SAME preview-then-confirm flow Pitch Log uses: build the
change in memory, run replay_game, show what would change, require an
explicit confirm before writing anything.

Unlike Pitch Log's delete (deliberately left replay-free, since removing
a GamePitch only ever leaves a harmless gap in pitch_sequence -- see that
module's docstring), deleting a GameRunnerEvent is NOT safe to leave
un-replayed: it can be the event that supplied a 3rd out or put a runner
in scoring position, so every later pitch's count/inning/score would
silently desync exactly like an un-replayed pitch edit would. So delete
gets a preview here too -- clicking "Delete" immediately builds it (no
separate form to fill out first, unlike edit), and "Confirm delete" is
the second, explicit step that actually writes anything.

Editing event_type/from_base/to_base/is_out is state-affecting (it can
change bases/outs and everything downstream) and goes through preview.
Editing only the runner's identity or notes is a pure leaf change and
saves instantly, same "instant vs. preview" split Pitch Log uses.

Runner-picker choices are built from this game's own saved lineup
(GameLineupSlot + LineupSubstitution) for the relevant squad -- every
player who ever occupied a slot for that squad this game, not just
whoever currently occupies it, since we're editing something that
already happened, not recording a new live event. Still not a perfect
historical reconstruction (it knows who was in the lineup, not exactly
who occupied which base) -- same "always overridable, don't force a
pick you don't have" philosophy GameRunnerEvent's own docstring already
states for the live add-form.
"""

from shiny import ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Game, GamePitch, GameRunnerEvent, GameLineupSlot, LineupSubstitution
from game_tracking_pitch_log_display import REPLAY_OWNED_FIELDS
import ui_helpers

# Touching either of these routes a Runner Event save through the
# preview-then-confirm flow instead of saving instantly -- same idea as
# Pitch Log's STATE_AFFECTING_FIELDS. Order doesn't matter.
STATE_AFFECTING_FIELDS_RE = ("event_type", "from_base", "to_base", "is_out")

BASE_LABEL = {1: "1st", 2: "2nd", 3: "3rd"}
TO_BASE_LABEL = {2: "2nd", 3: "3rd", 4: "Home"}


def _players_from_slots(slots):
    """Every Player who ever occupied one of `slots` this game -- the
    slot's original starter plus everyone who substituted in, deduped
    by player_id, sorted by name. Used instead of "who occupies the
    slot right now" (get_current_slot_occupant_id in game_tracking.py)
    because we're picking a runner for something that already happened,
    not the live "who's up now" picker."""
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
    populated (the other is None), mirroring runner_events_panel's own
    our_player_select/opponent_player_select split in game_tracking.py
    for the live add-form."""
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


def _build_re_preview_rows(all_pitches, result, game):
    """Same diff-building idea as game_tracking_pitch_log_display._build_
    preview_rows -- kept as its own (near-identical) copy rather than a
    cross-import, since the two files are deliberately independent leaf
    modules under game_tracking.py (neither imports the other, or
    game_tracking.py itself, to avoid circular imports -- see either
    module's own docstring)."""
    by_pitch = result["by_pitch"]

    def _fmt(v):
        return f"{float(v):.3f}" if v is not None else "-"

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
            diffs.append(f"Count {old_count}->{new_count}")
        if (p.outs_before or 0) != r["outs_before"]:
            diffs.append(f"Outs before {p.outs_before}->{r['outs_before']}")
        if (p.bases_before or "000") != r["bases_before"]:
            diffs.append(f"Bases before {p.bases_before or '000'}->{r['bases_before']}")
        if p.inning != r["inning"]:
            diffs.append(f"Inning {p.inning}->{r['inning']}")
        if p.is_our_team_batting != r["is_our_team_batting"]:
            diffs.append(
                f"Side {'Us' if p.is_our_team_batting else 'Opp'}"
                f"->{'Us' if r['is_our_team_batting'] else 'Opp'}"
            )
        if (p.pa_pitch_number or 1) != r["pa_pitch_number"]:
            diffs.append(f"PA pitch # {p.pa_pitch_number}->{r['pa_pitch_number']}")
        if _rounded(p.re_before) != _rounded(r["re_before"]):
            diffs.append(f"RE before {_fmt(p.re_before)}->{_fmt(r['re_before'])}")
        if _rounded(p.re_after) != _rounded(r["re_after"]):
            diffs.append(f"RE after {_fmt(p.re_after)}->{_fmt(r['re_after'])}")
        if _rounded(p.run_value) != _rounded(r["run_value"]):
            diffs.append(f"RV {_fmt(p.run_value)}->{_fmt(r['run_value'])}")
        if diffs:
            rows.append({"Pitch #": f"#{p.pitch_sequence}", "Changes": "; ".join(diffs)})

    side_changed_seqs = [
        f"#{p.pitch_sequence}" for p in ordered
        if p.game_pitch_id in result["side_changed_pitch_ids"]
    ]

    score_changes = []
    if game is not None:
        if result["our_score"] != game.our_score:
            score_changes.append(f"Our score: {game.our_score} -> {result['our_score']}")
        if result["opponent_score"] != game.opponent_score:
            score_changes.append(f"Opponent score: {game.opponent_score} -> {result['opponent_score']}")
        if game.uses_three_squad_intrasquad and result["squad_c_score"] != game.squad_c_score:
            score_changes.append(f"Team 3 score: {game.squad_c_score} -> {result['squad_c_score']}")

    return rows, side_changed_seqs, score_changes


def _render_re_preview(preview):
    """Same border+Confirm/Cancel convention Pitch Log's own
    _render_preview_block uses -- non-destructive styling (border-
    warning) for an edit, border-danger for a delete, since a delete
    preview is confirming something IS about to be removed."""
    is_delete = preview.get("kind") == "delete"
    header = f"Preview: delete {preview['event_type']} (after pitch #{preview['pitch_sequence_after']})" if is_delete \
        else f"Preview: saving {preview['event_type']} (after pitch #{preview['pitch_sequence_after']})"
    children = [
        ui.h6(header, class_="mt-2"),
        ui.p(
            "Nothing has been saved yet -- review what would change below, then Confirm or Cancel.",
            class_="text-muted small",
        ),
    ]
    if preview["side_changed_seqs"]:
        children.append(ui.p(
            "Side/inning changed for pitch(es) " + ", ".join(preview["side_changed_seqs"]) +
            " -- those pitches' recorded batter/pitcher may no longer match who was "
            "actually up; review them manually. The count/RE numbers will still be "
            "corrected, but who's listed as playing won't be reassigned automatically.",
            class_="text-warning small fw-bold mb-1",
        ))
    if preview["rows"]:
        children.append(ui.p("Pitches that would change:", class_="small fw-bold mb-1"))
        children.append(ui_helpers.render_dict_table(preview["rows"]))
    else:
        children.append(ui.p("No pitch's stored count/inning/RE would change.", class_="text-muted small"))
    if preview["score_changes"]:
        children.append(ui.p("Score change: " + "; ".join(preview["score_changes"]), class_="small fw-bold mt-1"))
    confirm_id = "gt_re_confirm_delete_btn" if is_delete else "gt_re_confirm_preview_btn"
    confirm_label = "Confirm delete" if is_delete else "Confirm & Save"
    cancel_id = "gt_re_cancel_delete_btn" if is_delete else "gt_re_cancel_preview_btn"
    children.append(ui.layout_columns(
        ui.input_action_button(confirm_id, confirm_label, class_="btn-danger btn-sm mt-2"),
        ui.input_action_button(cancel_id, "Cancel", class_="btn-outline-secondary btn-sm mt-2"),
        col_widths=[6, 6],
    ))
    return ui.div(*children, class_="border border-danger rounded p-2 mb-2" if is_delete else "border border-warning rounded p-2 mb-2")


def register_game_tracking_runner_events(
    input, output, session,
    _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_pa, _bump_refresh,
    _registered_runner_event_row_ids, _gt_re_editing_event_id, _gt_re_pending_preview,
    build_re_lookup, replay_game,
    RUNNER_EVENT_TYPES, RUNNER_EVENT_OUT_TYPES,
):

    @render.ui
    def runner_events_log_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            events = (
                db.query(GameRunnerEvent)
                .options(joinedload(GameRunnerEvent.our_player), joinedload(GameRunnerEvent.opponent_player))
                .filter(GameRunnerEvent.game_id == game_id)
                .order_by(GameRunnerEvent.pitch_sequence_after, GameRunnerEvent.created_at)
                .all()
            )
            if not events:
                return ui.div(
                    ui.h5("Runner events", class_="gbo-section-title"),
                    ui_helpers.empty_state("No runner events logged yet for this game -- steals, caught stealing, pickoffs, wild pitches, passed balls, and balks all show up here once logged from Live Tracking."),
                )

            can_edit = _can_edit()
            editing_id = _gt_re_editing_event_id() if can_edit else None
            pending_preview = _gt_re_pending_preview() if can_edit else None

            rows = [ui.h5(f"Runner events ({len(events)})", class_="gbo-section-title")]
            for ev in events:
                if can_edit and pending_preview is not None and pending_preview.get("event_id") == ev.runner_event_id:
                    rows.append(_render_re_preview(pending_preview))
                    continue

                if can_edit and ev.runner_event_id == editing_id:
                    our_choices, opp_roster = _runner_choices_for_event(db, game, ev.is_our_team_batting, ev.batting_squad)
                    runner_choices = {"": "-- Unspecified --"}
                    if our_choices:
                        runner_choices.update(our_choices)
                    elif opp_roster:
                        runner_choices.update({str(p.opponent_player_id): p.player_name for p in opp_roster})
                    selected_runner = (
                        str(ev.our_player_id) if ev.our_player_id
                        else (str(ev.opponent_player_id) if ev.opponent_player_id else "")
                    )
                    edit_children = [
                        ui.h6(f"Editing runner event (after pitch #{ev.pitch_sequence_after})", class_="mt-2"),
                        ui.layout_columns(
                            ui.input_select("gt_re_edit_event_type", "Event", choices=RUNNER_EVENT_TYPES, selected=ev.event_type),
                            ui.input_select("gt_re_edit_from_base", "Runner on", choices=BASE_LABEL, selected=str(ev.from_base)),
                            col_widths=[7, 5],
                        ),
                        ui.input_select(
                            "gt_re_edit_to_base", "Advances to (ignored for an out)",
                            choices={str(k): v for k, v in TO_BASE_LABEL.items()},
                            selected=str(ev.to_base) if ev.to_base else "2",
                        ),
                        ui.input_select("gt_re_edit_runner", "Runner (optional)", choices=runner_choices, selected=selected_runner),
                        ui.input_text("gt_re_edit_notes", "Notes (optional)", value=ev.notes or ""),
                        ui.layout_columns(
                            ui.input_action_button("gt_re_save_edit_btn", "Save", class_="btn-primary btn-sm"),
                            ui.input_action_button("gt_re_cancel_edit_btn", "Cancel", class_="btn-outline-secondary btn-sm"),
                            col_widths=[6, 6],
                        ),
                    ]
                    rows.append(ui.div(*edit_children, class_="border rounded p-2 mb-2"))
                    continue

                who = None
                if ev.our_player_id and ev.our_player:
                    who = f"{ev.our_player.first_name} {ev.our_player.last_name} -- "
                elif ev.opponent_player_id and ev.opponent_player:
                    who = f"{ev.opponent_player.player_name} -- "
                outcome = "out" if ev.is_out else TO_BASE_LABEL.get(ev.to_base, "?")
                side = "Us batting" if ev.is_our_team_batting else "Opponent batting"
                line1 = f"After #{ev.pitch_sequence_after} -- Inn {ev.inning}, {side} -- {ev.event_type}: {who or ''}{BASE_LABEL.get(ev.from_base, '?')} -> {outcome}"
                summary_children = [ui.p(line1, class_="mb-0 small")]
                if ev.notes:
                    summary_children.append(ui.p(ev.notes, class_="text-muted small mb-0 fst-italic"))

                if can_edit:
                    edit_btn_id = f"gt_re_edit_btn_{ev.runner_event_id}"
                    delete_btn_id = f"gt_re_delete_btn_{ev.runner_event_id}"
                    rows.append(ui.layout_columns(
                        ui.div(*summary_children),
                        ui.input_action_button(edit_btn_id, "Edit", class_="btn-outline-primary btn-sm"),
                        ui.input_action_button(delete_btn_id, "Delete", class_="btn-outline-danger btn-sm"),
                        col_widths=[8, 2, 2],
                    ))
                    if edit_btn_id not in _registered_runner_event_row_ids:
                        _registered_runner_event_row_ids.add(edit_btn_id)
                        _register_runner_event_row_handlers(ev.runner_event_id)
                else:
                    rows.append(ui.div(*summary_children))

            return ui.div(*rows)
        finally:
            db.close()

    def _register_runner_event_row_handlers(event_id):
        edit_btn_id = f"gt_re_edit_btn_{event_id}"
        delete_btn_id = f"gt_re_delete_btn_{event_id}"

        @reactive.effect
        @reactive.event(input[edit_btn_id])
        def _on_re_edit_trigger():
            _gt_re_pending_preview.set(None)
            _gt_re_editing_event_id.set(event_id)
            _bump_refresh()

        @reactive.effect
        @reactive.event(input[delete_btn_id])
        def _on_re_delete_trigger():
            """Delete has no form of its own -- it goes straight to
            building the preview (see module docstring for why delete
            needs one at all, unlike Pitch Log's replay-free delete)."""
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
                ev = db.query(GameRunnerEvent).filter(GameRunnerEvent.runner_event_id == event_id).first()
                if game is None or ev is None:
                    return
                all_pitches = sorted(game.pitches, key=lambda x: x.pitch_sequence)
                remaining_events = [e for e in game.runner_events if e.runner_event_id != event_id]
                forced_ends = sorted(game.forced_half_inning_ends, key=lambda e: e.pitch_sequence_after)

                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, remaining_events, re_lookup, forced_ends)
                rows, side_changed_seqs, score_changes = _build_re_preview_rows(all_pitches, result, game)

                _gt_re_pending_preview.set({
                    "kind": "delete",
                    "event_id": event_id,
                    "event_type": ev.event_type,
                    "pitch_sequence_after": ev.pitch_sequence_after,
                    "rows": rows,
                    "side_changed_seqs": side_changed_seqs,
                    "score_changes": score_changes,
                })
                _gt_re_editing_event_id.set(None)
                _bump_refresh()
            finally:
                db.close()

    @reactive.effect
    @reactive.event(input.gt_re_cancel_edit_btn)
    def _cancel_re_edit():
        _gt_re_editing_event_id.set(None)
        _gt_re_pending_preview.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_re_save_edit_btn)
    def _save_re_edit():
        event_id = _gt_re_editing_event_id()
        if event_id is None:
            return
        req("gt_re_edit_event_type" in input)
        req("gt_re_edit_from_base" in input)

        event_type = input.gt_re_edit_event_type()
        from_base = int(input.gt_re_edit_from_base())
        is_out = event_type in RUNNER_EVENT_OUT_TYPES
        to_base = None if is_out else int(input.gt_re_edit_to_base())
        if not is_out and to_base <= from_base:
            ui.notification_show("Advances-to base must be further than the runner's current base -- not saved.", type="error", duration=8)
            return

        runner_raw = input.gt_re_edit_runner() if "gt_re_edit_runner" in input else ""
        notes = (input.gt_re_edit_notes() or "").strip() or None

        db = get_session()
        save_result = None
        try:
            ev = db.query(GameRunnerEvent).filter(GameRunnerEvent.runner_event_id == event_id).first()
            if ev is None:
                _gt_re_editing_event_id.set(None)
                _gt_re_pending_preview.set(None)
                _bump_refresh()
                return

            our_choices, opp_roster = _runner_choices_for_event(db, ev.game, ev.is_our_team_batting, ev.batting_squad)
            our_player_id = None
            opponent_player_id = None
            if runner_raw:
                if our_choices is not None:
                    our_player_id = int(runner_raw)
                else:
                    opponent_player_id = int(runner_raw)

            values = {
                "event_type": event_type, "from_base": from_base, "to_base": to_base, "is_out": is_out,
                "our_player_id": our_player_id, "opponent_player_id": opponent_player_id, "notes": notes,
            }
            state_changed = any(getattr(ev, f) != values[f] for f in STATE_AFFECTING_FIELDS_RE)

            if not state_changed:
                for field, value in values.items():
                    setattr(ev, field, value)
                db.commit()
                ui.notification_show("Updated runner event.", type="message", duration=6)
                save_result = "instant"
            else:
                game_id = ev.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = sorted(db.query(GamePitch).filter(GamePitch.game_id == game_id).all(), key=lambda x: x.pitch_sequence)
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                forced_ends = game.forced_half_inning_ends if game is not None else []
                for field, value in values.items():
                    setattr(ev, field, value)  # in-memory only, on the ORM object already inside all_events
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, forced_ends)
                rows, side_changed_seqs, score_changes = _build_re_preview_rows(all_pitches, result, game)
                _gt_re_pending_preview.set({
                    "kind": "edit",
                    "event_id": event_id,
                    "event_type": event_type,
                    "pitch_sequence_after": ev.pitch_sequence_after,
                    "edits": values,
                    "rows": rows,
                    "side_changed_seqs": side_changed_seqs,
                    "score_changes": score_changes,
                })
                save_result = "preview"
                # Deliberately no db.commit() -- closing this session
                # below with nothing committed rolls back the in-memory
                # edit above, same dry-run posture Pitch Log's own
                # state-affecting save uses.
        finally:
            db.close()

        if save_result == "instant":
            _gt_re_editing_event_id.set(None)
            _gt_re_pending_preview.set(None)
            _bump_pa()
            _bump_refresh()
        elif save_result == "preview":
            _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_re_cancel_preview_btn)
    def _cancel_re_preview():
        _gt_re_pending_preview.set(None)
        _gt_re_editing_event_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_re_confirm_preview_btn)
    def _confirm_re_preview():
        """Re-derives everything fresh from the DB rather than trusting
        the preview's cached rows -- same staleness guard Pitch Log's
        _confirm_pitch_log_preview uses."""
        preview = _gt_re_pending_preview()
        if preview is None:
            return
        event_id = preview["event_id"]
        db = get_session()
        try:
            ev = db.query(GameRunnerEvent).filter(GameRunnerEvent.runner_event_id == event_id).first()
            if ev is None:
                ui.notification_show("That runner event no longer exists -- nothing saved.", type="warning", duration=8)
            else:
                game_id = ev.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                all_pitches = sorted(db.query(GamePitch).filter(GamePitch.game_id == game_id).all(), key=lambda x: x.pitch_sequence)
                all_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                forced_ends = game.forced_half_inning_ends if game is not None else []
                for field, value in preview["edits"].items():
                    setattr(ev, field, value)
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, all_events, re_lookup, forced_ends)
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
                ui.notification_show(f"Updated runner event and re-synced {len(all_pitches)} pitch(es) in this game.", type="message", duration=8)
        finally:
            db.close()
        _gt_re_pending_preview.set(None)
        _gt_re_editing_event_id.set(None)
        _bump_pa()
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_re_cancel_delete_btn)
    def _cancel_re_delete():
        _gt_re_pending_preview.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.gt_re_confirm_delete_btn)
    def _confirm_re_delete():
        preview = _gt_re_pending_preview()
        if preview is None or preview.get("kind") != "delete":
            return
        event_id = preview["event_id"]
        db = get_session()
        try:
            ev = db.query(GameRunnerEvent).filter(GameRunnerEvent.runner_event_id == event_id).first()
            if ev is None:
                ui.notification_show("That runner event no longer exists.", type="warning", duration=8)
            else:
                game_id = ev.game_id
                game = db.query(Game).filter(Game.game_id == game_id).first()
                deleted_seq = ev.pitch_sequence_after
                db.delete(ev)
                db.flush()  # so the query below no longer sees it
                all_pitches = sorted(db.query(GamePitch).filter(GamePitch.game_id == game_id).all(), key=lambda x: x.pitch_sequence)
                remaining_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game_id).all()
                forced_ends = game.forced_half_inning_ends if game is not None else []
                re_lookup = build_re_lookup(db)
                result = replay_game(all_pitches, remaining_events, re_lookup, forced_ends)
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
                ui.notification_show(f"Deleted runner event (after pitch #{deleted_seq}) and re-synced {len(all_pitches)} pitch(es).", type="message", duration=8)
        finally:
            db.close()
        _gt_re_pending_preview.set(None)
        _bump_pa()
        _bump_refresh()
