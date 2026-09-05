"""
GBO -- Intended Location & Command Tracker module (Phase 1).

Coach-facing workflow for GBO's own command-tracking system: pick a
pitcher, start or resume a session, then (Step 4 onward) click an
intended target and an actual location for each pitch, save it, and see
command develop live across the bullpen. See the architecture doc
agreed with Ryker (Aug 2026) for the full spec.

This step builds the session layer only -- pitcher/session pickers,
starting a new session, and the arsenal-filtered pitch-type selector.
Click-to-place location entry, saving a CommandPitch, the pitch log,
charts, and the scorecard are built in the steps that follow; this
file grows in place rather than being replaced.

Command Tracker sessions ARE BullpenSession rows (deliberately reused,
not a second competing session table -- see the architecture doc).
BullpenType already has a "Command" value; new_session_type_picker below
defaults to it but still allows any type, since tracking command during
a Pitch Design or Velocity bullpen is equally valid. Individual pitches
live in the new CommandPitch table (models.py), separate from the older
BullpenPitch (categorical 1-9 zone, being phased out) and RapsodoPitch
(actual Rapsodo-imported data) -- a single BullpenSession can have any
combination of the three depending on which tracking workflows were
used on it.

Deliberately has NO "delete this session" control (unlike Bullpen
Tracking's equivalent) -- a BullpenSession can carry BullpenPitch/
RapsodoPitch data from OTHER features alongside its command_pitches, so
deleting the whole session from this page could silently destroy
unrelated tracked data. Command Tracker's own Undo/Edit/Delete (Section
30, Step 6) operates on individual CommandPitch rows only.

Same pitcher-visibility, role-gating, and arsenal-filtering patterns as
bullpen_tracking.py / game_tracking.py -- duplicated here rather than
imported cross-module, matching this migration's existing convention of
each page module keeping its own small copies of shared logic (e.g.
_render_strike_zone_plot appears independently in both
bullpen_tracking.py and player_bullpens.py).
"""

from datetime import date

from shiny import module, ui, render, reactive, req
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, BullpenType, BullpenSession, PitchType, PlayerPitchArsenal, CommandPitch
from analytics import command_metrics

import ui_helpers
import strike_zone
import click_widgets
import command_config
from visualizations import command_charts

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")
DEFAULT_NEW_SESSION_TYPE = "Command"


def get_arsenal_pitch_type_names(db, pitcher_id, all_pitch_types):
    """Section 7: only the pitcher's configured arsenal, or every type if
    none is configured yet. Same query/fallback as
    shiny_app/modules/game_tracking.py's get_arsenal_pitch_type_names."""
    arsenal = (
        db.query(PlayerPitchArsenal)
        .filter(PlayerPitchArsenal.player_id == pitcher_id, PlayerPitchArsenal.active.is_(True))
        .all()
    )
    if not arsenal:
        return [pt.type_name for pt in all_pitch_types]
    arsenal_type_ids = {a.pitch_type_id for a in arsenal}
    return [pt.type_name for pt in all_pitch_types if pt.pitch_type_id in arsenal_type_ids]


@module.ui
def command_tracker_ui():
    return ui.div(
        ui_helpers.page_header("Command Tracker"),
        ui.output_ui("cmd_pitcher_picker"),
        ui.output_ui("cmd_session_picker"),
        ui.output_ui("cmd_new_session_type_picker"),
        ui.output_ui("cmd_new_session_form"),
        ui.output_ui("cmd_active_session_header"),
        ui.output_ui("cmd_pitch_type_picker"),
        ui.output_ui("cmd_intended_location_section"),
        click_widgets.click_target(output_widget("cmd_intended_location_widget"), "cmd_intended_x_input", "cmd_intended_z_input"),
        ui.output_ui("cmd_intended_location_caption"),
        ui.output_ui("cmd_actual_location_section"),
        click_widgets.click_target(output_widget("cmd_actual_location_widget"), "cmd_actual_x_input", "cmd_actual_z_input"),
        ui.output_ui("cmd_actual_location_caption"),
        ui.output_ui("cmd_save_pitch_section"),
        ui.output_ui("cmd_pitch_log_section"),
        ui.output_ui("cmd_scorecard_section"),
        ui.output_ui("cmd_chart_section"),
        ui_helpers.page_footer(),
    )


@module.server
def command_tracker_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _active_bullpen_id = reactive.Value(None)
    # Persists the coach's pitch-type choice across pitches (Section 30:
    # "Keep the selected pitch type active until the coach changes it").
    # Read/written for real once pitch entry exists (Step 5) -- this step
    # only keeps it in sync with the picker below.
    _active_pitch_type = reactive.Value(None)
    # Bug fix (Aug 2026): cmd_pitcher_picker() used to rebuild its
    # ui.input_select with no `selected=`, so every _refresh_tick bump
    # (e.g. right after saving a pitch) silently reset the dropdown to
    # whichever pitcher sorts first alphabetically. Tracked here and fed
    # back in as `selected=`, same pattern as _active_bullpen_id/
    # _active_pitch_type above.
    _active_pitcher_id = reactive.Value(None)
    # Bug fix (Aug 2026): cmd_intended_location_section()/
    # cmd_actual_location_section() used to hardcode value=0.0/2.5 on
    # every rebuild -- including rebuilds triggered by just changing
    # pitch type (cmd_intended_location_section reactively reads
    # input.cmd_pitch_type_select() for its header) -- silently wiping
    # out a location the coach had already clicked or typed. Tracked
    # here instead and only actually reset to neutral (0.0, 2.5) on a
    # genuine new pitch: session switch (_sync_active_bullpen_id below)
    # or after a successful save (_save_pitch below).
    _active_intended_x = reactive.Value(0.0)
    _active_intended_z = reactive.Value(2.5)
    _active_actual_x = reactive.Value(0.0)
    _active_actual_z = reactive.Value(2.5)

    # Step 6 -- pitch log (Section 30): Undo Last Pitch, and per-row Edit/
    # Delete on individual CommandPitch rows. Only one row can be mid-edit
    # or mid-delete-confirm at a time, so those two use fixed input ids
    # (cmd_pl_edit_*, cmd_pl_confirm_delete_btn, etc.) rather than one set
    # per pitch. The Edit/Delete *trigger* buttons on each log row are a
    # genuinely unbounded, data-dependent set though, so those use the
    # lazy-registration pattern already established for per-row buttons
    # elsewhere in this migration (see game_tracking.py's
    # _registered_clip_match_ids / _register_clip_match_handler).
    _editing_pitch_id = reactive.Value(None)
    _pending_delete_pitch_id = reactive.Value(None)
    _registered_pitch_row_ids = set()

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _access_ok():
        if not app_state.is_authenticated():
            return False
        if app_state.role_name() not in ALLOWED_ROLES:
            return False
        if app_state.role_name() == "Coach" and app_state.coach_specialty() == "Hitting":
            return False
        return True

    def _visible_pitchers(db):
        q = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()
            ]
            q = q.filter(Player.player_id.in_(assigned_ids))
        return q.order_by(Player.last_name, Player.first_name).all()

    # -------------------------------------------------------------------
    # Pitcher + session pickers
    # -------------------------------------------------------------------

    @render.ui
    def cmd_pitcher_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        db = get_session()
        try:
            pitchers = _visible_pitchers(db)
            if not pitchers:
                return ui_helpers.empty_state("No pitchers to show yet." if app_state.can_view_all_players() else "No pitchers are currently assigned to you.")
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitchers}
            current_id = _active_pitcher_id()
            current = str(current_id) if current_id is not None and str(current_id) in choices else next(iter(choices))
            return ui.input_select("cmd_pitcher_select", "Pitcher", choices=choices, selected=current)
        finally:
            db.close()

    @reactive.effect
    def _sync_active_pitcher_id():
        req("cmd_pitcher_select" in input)
        raw = input.cmd_pitcher_select()
        _active_pitcher_id.set(int(raw) if raw else None)

    @render.ui
    def cmd_session_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        req("cmd_pitcher_select" in input)
        selected_pitcher_id = int(input.cmd_pitcher_select())

        db = get_session()
        try:
            # Every one of this pitcher's bullpen sessions, any type --
            # not just "Command" -- a coach might track intended-vs-
            # actual location during any bullpen type.
            existing_sessions = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.player_id == selected_pitcher_id)
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            choices = {"": "-- Start a new session --"}
            choices.update({
                str(b.bullpen_id): f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {b.bullpen_type.type_name if b.bullpen_type else '—'} ({len(b.command_pitches)} command pitch(es))"
                for b in existing_sessions
            })
            active_id = _active_bullpen_id()
            return ui.div(ui.hr(), ui.input_select("cmd_session_select", "Session", choices=choices, selected=str(active_id) if active_id is not None else ""))
        finally:
            db.close()

    @reactive.effect
    def _sync_active_bullpen_id():
        req("cmd_session_select" in input)
        raw = input.cmd_session_select()
        new_bullpen_id = int(raw) if raw else None
        if new_bullpen_id != _active_bullpen_id():
            # Switching to a different (or brand-new) session means a
            # fresh pitch #1 -- don't carry over intended/actual location
            # values left over from whatever session was active before.
            _active_intended_x.set(0.0)
            _active_intended_z.set(2.5)
            _active_actual_x.set(0.0)
            _active_actual_z.set(2.5)
        _active_bullpen_id.set(new_bullpen_id)

    # -------------------------------------------------------------------
    # New session -- defaults the type picker to "Command" but allows any
    # BullpenType.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_new_session_type_picker():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("cmd_pitcher_select" in input)
        if _active_bullpen_id() is not None:
            return None
        db = get_session()
        try:
            bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all()
            choices = {t.type_name: t.type_name for t in bullpen_types}
            default = DEFAULT_NEW_SESSION_TYPE if DEFAULT_NEW_SESSION_TYPE in choices else next(iter(choices), None)
            return ui.input_select("cmd_new_session_type_choice", "Session type", choices=choices, selected=default)
        finally:
            db.close()

    @render.ui
    def cmd_new_session_form():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("cmd_pitcher_select" in input)
        if _active_bullpen_id() is not None:
            return None
        req("cmd_new_session_type_choice" in input)
        return ui.div(
            ui.input_date("cmd_new_session_date", "Date", value=date.today()),
            ui.input_text_area("cmd_new_session_notes", "Session notes (optional)"),
            ui.input_action_button("cmd_start_session_btn", "Start session", class_="btn-primary mt-2"),
        )

    @reactive.effect
    @reactive.event(input.cmd_start_session_btn)
    def _start_session():
        selected_pitcher_id = int(input.cmd_pitcher_select())
        type_choice = input.cmd_new_session_type_choice()
        db = get_session()
        try:
            bullpen_type = db.query(BullpenType).filter(BullpenType.type_name == type_choice).first()
            if bullpen_type is None:
                return
            new_session = BullpenSession(
                player_id=selected_pitcher_id, bullpen_type_id=bullpen_type.bullpen_type_id,
                session_date=input.cmd_new_session_date(),
                overall_notes=(input.cmd_new_session_notes() or "").strip() or None,
                created_by_user_id=app_state.user_id(),
            )
            db.add(new_session)
            db.commit()
            _active_bullpen_id.set(new_session.bullpen_id)
            ui.notification_show(f"Started {type_choice} session for {input.cmd_new_session_date().strftime('%Y-%m-%d (%a)')}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Active session header -- see module docstring for why there's
    # deliberately no delete-session control here.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_active_session_header():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            if not app_state.can_edit_sessions():
                return ui.p("Your role has read-only access to Command Tracker.", class_="text-muted")
            return None

        db = get_session()
        try:
            active_session = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.bullpen_id == bullpen_id)
                .first()
            )
            if active_session is None:
                return None
            type_label = active_session.bullpen_type.type_name if active_session.bullpen_type else "—"
            children = [
                ui.hr(),
                ui.h4(f"{type_label} — {active_session.session_date.strftime('%Y-%m-%d (%a)')}", class_="gbo-section-title"),
                ui.p(f"{len(active_session.command_pitches)} command pitch(es) tracked in this session.", class_="text-muted small"),
            ]
            if active_session.overall_notes:
                children.append(ui.p(active_session.overall_notes, class_="text-muted small"))
            return ui.div(*children)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Arsenal-filtered pitch-type selector (Sections 7 & 30).
    # -------------------------------------------------------------------

    @render.ui
    def cmd_pitch_type_picker():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        req("cmd_pitcher_select" in input)
        selected_pitcher_id = int(input.cmd_pitcher_select())

        db = get_session()
        try:
            all_pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            arsenal_names = get_arsenal_pitch_type_names(db, selected_pitcher_id, all_pitch_types)
            if not arsenal_names:
                return ui_helpers.empty_state("This pitcher has no pitch types available -- configure their arsenal on the Players page.")
            current = _active_pitch_type() if _active_pitch_type() in arsenal_names else arsenal_names[0]
            return ui.div(ui.hr(), ui.input_select("cmd_pitch_type_select", "Pitch type", choices=arsenal_names, selected=current))
        finally:
            db.close()

    @reactive.effect
    def _sync_active_pitch_type():
        req("cmd_pitch_type_select" in input)
        _active_pitch_type.set(input.cmd_pitch_type_select())

    # -------------------------------------------------------------------
    # Intended-location click widget (Step 4). Same click-to-place
    # technique proven in game_tracking.py's intended_location_widget --
    # see click_widgets.py's docstring. The two numeric inputs
    # (cmd_intended_x_input/cmd_intended_z_input) are the actual source
    # of truth (still directly typeable for fine correction); clicking
    # the zone below is just a faster way to fill them in. Save-pitch
    # wiring and the reset-after-save behavior are Step 5.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_intended_location_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        req("cmd_pitch_type_select" in input)

        db = get_session()
        try:
            active_session = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_session is None:
                return None
            next_pitch_number = len(active_session.command_pitches) + 1
        finally:
            db.close()

        return ui.div(
            ui.hr(),
            ui.h5(f"Pitch #{next_pitch_number} — {input.cmd_pitch_type_select()} — intended location", class_="gbo-section-title"),
            ui.layout_columns(
                # value= comes from the tracked _active_intended_x/z, not a
                # hardcoded 0.0/2.5 -- see the reactive.Value declarations
                # above for why (this section rebuilds on every pitch-type
                # change, which used to silently wipe an already-placed
                # location).
                ui.input_numeric("cmd_intended_x_input", "Intended plate side (ft, 0 = center, negative = 3B side)", value=_active_intended_x(), min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                ui.input_numeric("cmd_intended_z_input", "Intended plate height (ft off the ground)", value=_active_intended_z(), min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
            ),
        )

    @reactive.effect
    def _sync_active_intended_location():
        req("cmd_intended_x_input" in input)
        _active_intended_x.set(input.cmd_intended_x_input())
        _active_intended_z.set(input.cmd_intended_z_input())

    @render_plotly
    def cmd_intended_location_widget():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        if _active_bullpen_id() is None:
            return None
        req("cmd_intended_x_input" in input)
        x, z = input.cmd_intended_x_input(), input.cmd_intended_z_input()
        return click_widgets.build_clickable_widget(strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z))

    @render.ui
    def cmd_intended_location_caption():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        if _active_bullpen_id() is None:
            return None
        req("cmd_intended_x_input" in input)
        x, z = input.cmd_intended_x_input(), input.cmd_intended_z_input()
        return ui.p(
            f"Intended: {x:+.2f} ft, {z:.2f} ft high — click the zone above, or type coordinates directly.",
            class_="text-muted small text-center",
        )

    # -------------------------------------------------------------------
    # Actual-location click widget (Step 5) -- same technique as the
    # intended-location widget above, a separate pair of numeric inputs/
    # click target. Defaults to the same (0.0, 2.5) neutral coordinate as
    # intended -- KNOWN LIMITATION, matching the existing Video Review
    # page's actual-location entry (game_tracking.py's vr_actual_x_input):
    # nothing currently stops a coach from hitting Save without ever
    # touching this widget, which would silently record a suspiciously
    # perfect 0.00" miss rather than blocking the save. Flagged to Ryker;
    # can add a confirmation guard later if it turns out to matter in
    # practice.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_actual_location_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        if _active_bullpen_id() is None:
            return None
        req("cmd_intended_x_input" in input)
        return ui.div(
            ui.h6("Actual location", class_="gbo-section-title mt-2"),
            ui.layout_columns(
                # value= comes from the tracked _active_actual_x/z -- same
                # reasoning as cmd_intended_location_section above.
                ui.input_numeric("cmd_actual_x_input", "Actual plate side (ft, 0 = center, negative = 3B side)", value=_active_actual_x(), min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                ui.input_numeric("cmd_actual_z_input", "Actual plate height (ft off the ground)", value=_active_actual_z(), min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
            ),
        )

    @reactive.effect
    def _sync_active_actual_location():
        req("cmd_actual_x_input" in input)
        _active_actual_x.set(input.cmd_actual_x_input())
        _active_actual_z.set(input.cmd_actual_z_input())

    @render_plotly
    def cmd_actual_location_widget():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        if _active_bullpen_id() is None:
            return None
        req("cmd_actual_x_input" in input)
        x, z = input.cmd_actual_x_input(), input.cmd_actual_z_input()
        return click_widgets.build_clickable_widget(strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z))

    @render.ui
    def cmd_actual_location_caption():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        if _active_bullpen_id() is None:
            return None
        req("cmd_actual_x_input" in input)
        x, z = input.cmd_actual_x_input(), input.cmd_actual_z_input()
        return ui.p(
            f"Actual: {x:+.2f} ft, {z:.2f} ft high — click the zone above, or type coordinates directly.",
            class_="text-muted small text-center",
        )

    # -------------------------------------------------------------------
    # Save Pitch (Step 5) -- computes miss distance/direction/target
    # classification via analytics/command_metrics.py (never re-derived
    # anywhere else), inserts the CommandPitch row, then resets intended/
    # actual back to their neutral defaults and bumps pitch_number for
    # the next pitch (Section 30: "Immediately ready for next pitch").
    # Pitch type stays selected -- _active_pitch_type isn't touched here.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_save_pitch_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        req("cmd_actual_x_input" in input)
        db = get_session()
        try:
            has_pitches = db.query(CommandPitch).filter(CommandPitch.bullpen_id == bullpen_id).first() is not None
        finally:
            db.close()
        return ui.div(
            ui.hr(),
            ui.layout_columns(
                ui.input_text("cmd_velocity_input", "Velocity (mph, optional)", value=""),
                ui.input_text("cmd_pitch_notes_input", "Notes (optional)", value=""),
            ),
            ui.layout_columns(
                ui.input_action_button("cmd_save_pitch_btn", "Save pitch", class_="btn-primary mt-2"),
                # Step 6 -- same "delete the most-recent row" pattern as
                # game_tracking.py's Undo Last Pitch (see _undo_last_pitch
                # below); per-pitch Edit/Delete on ANY row lives in the
                # pitch log section further down.
                ui.input_action_button("cmd_undo_last_pitch_btn", "Undo Last Pitch", class_="btn-outline-danger mt-2", disabled=not has_pitches),
                col_widths=[8, 4],
            ),
        )

    @reactive.effect
    @reactive.event(input.cmd_undo_last_pitch_btn)
    def _undo_last_pitch():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        db = get_session()
        try:
            last_pitch = (
                db.query(CommandPitch)
                .filter(CommandPitch.bullpen_id == bullpen_id)
                .order_by(CommandPitch.pitch_number.desc())
                .first()
            )
            if last_pitch is None:
                ui.notification_show("No pitches recorded yet in this session.", type="warning", duration=6)
                return
            undone_number = last_pitch.pitch_number
            db.delete(last_pitch)
            db.commit()
            ui.notification_show(f"Undid pitch #{undone_number}.", type="message", duration=8)
        finally:
            db.close()
        _editing_pitch_id.set(None)
        _pending_delete_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.cmd_save_pitch_btn)
    def _save_pitch():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        req("cmd_pitcher_select" in input)
        req("cmd_pitch_type_select" in input)
        req("cmd_intended_x_input" in input)
        req("cmd_actual_x_input" in input)

        pitcher_id = int(input.cmd_pitcher_select())
        pitch_type_name = input.cmd_pitch_type_select()
        intended_x, intended_z = input.cmd_intended_x_input(), input.cmd_intended_z_input()
        actual_x, actual_z = input.cmd_actual_x_input(), input.cmd_actual_z_input()

        velocity_raw = (input.cmd_velocity_input() or "").strip() if "cmd_velocity_input" in input else ""
        velocity = None
        if velocity_raw:
            try:
                velocity = float(velocity_raw)
            except ValueError:
                ui.notification_show("Velocity must be a number (or left blank) -- pitch not saved.", type="error", duration=8)
                return
        notes = ((input.cmd_pitch_notes_input() or "").strip() or None) if "cmd_pitch_notes_input" in input else None

        db = get_session()
        try:
            pitcher = db.query(Player).filter(Player.player_id == pitcher_id).first()
            active_session = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            pitch_type = db.query(PitchType).filter(PitchType.type_name == pitch_type_name).first()
            if pitcher is None or active_session is None:
                return

            next_pitch_number = len(active_session.command_pitches) + 1
            derived = command_metrics.compute_command_pitch_fields(intended_x, intended_z, actual_x, actual_z, pitcher.throws)

            new_pitch = CommandPitch(
                bullpen_id=bullpen_id,
                pitch_number=next_pitch_number,
                pitch_type_id=pitch_type.pitch_type_id if pitch_type else None,
                intended_x=intended_x, intended_z=intended_z,
                actual_x=actual_x, actual_z=actual_z,
                velocity=velocity,
                notes=notes,
                source="manual",
                **derived,
            )
            db.add(new_pitch)
            db.commit()

            miss_label = f"{derived['miss_distance']:.1f} in ({derived['miss_direction']})" if derived["miss_distance"] is not None else "—"
            ui.notification_show(f"Saved pitch #{next_pitch_number} ({pitch_type_name}) — Miss: {miss_label}", type="message", duration=8)

            ui.update_numeric("cmd_intended_x_input", value=0.0)
            ui.update_numeric("cmd_intended_z_input", value=2.5)
            ui.update_numeric("cmd_actual_x_input", value=0.0)
            ui.update_numeric("cmd_actual_z_input", value=2.5)
            # Reset the tracked values directly rather than relying on the
            # client round-trip from the update_numeric() calls above to
            # eventually reach _sync_active_intended_location/
            # _sync_active_actual_location -- otherwise a pitch-type change
            # in the gap before that round-trip completes would rebuild
            # the section with the *old* (not-yet-reset) tracked value.
            _active_intended_x.set(0.0)
            _active_intended_z.set(2.5)
            _active_actual_x.set(0.0)
            _active_actual_z.set(2.5)
            if "cmd_velocity_input" in input:
                ui.update_text("cmd_velocity_input", value="")
            if "cmd_pitch_notes_input" in input:
                ui.update_text("cmd_pitch_notes_input", value="")
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch log (Step 6, Section 30) -- every CommandPitch in the active
    # session, most recent last (CommandPitch.pitch_number order, same as
    # BullpenSession.command_pitches' own order_by). Edit/Delete operate
    # on individual rows, independent of Undo Last Pitch above (which
    # only ever touches the single most-recent row). Only one row can be
    # mid-edit or mid-delete-confirm at once -- see the reactive.Value
    # declarations near the top of this function for why those two use
    # fixed input ids while the per-row Edit/Delete trigger buttons use
    # the lazy-registration pattern.
    # -------------------------------------------------------------------

    @render.ui
    def cmd_pitch_log_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_session = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.player), joinedload(BullpenSession.command_pitches).joinedload(CommandPitch.pitch_type))
                .filter(BullpenSession.bullpen_id == bullpen_id)
                .first()
            )
            if active_session is None:
                return None
            pitches = active_session.command_pitches
            children = [ui.hr(), ui.h5("Pitch log", class_="gbo-section-title")]
            if not pitches:
                children.append(ui_helpers.empty_state("No pitches logged yet for this session."))
                return ui.div(*children)

            can_edit = app_state.can_edit_sessions()
            editing_id = _editing_pitch_id() if can_edit else None
            pending_delete_id = _pending_delete_pitch_id() if can_edit else None
            all_pitch_type_names = [pt.type_name for pt in db.query(PitchType).order_by(PitchType.pitch_type_id).all()] if editing_id is not None else []

            rows = []
            for p in pitches:
                pt_name = p.pitch_type.type_name if p.pitch_type else "—"

                if can_edit and p.command_pitch_id == editing_id:
                    rows.append(ui.div(
                        ui.h6(f"Editing pitch #{p.pitch_number}", class_="mt-2"),
                        ui.input_select("cmd_pl_edit_pitch_type", "Pitch type", choices=all_pitch_type_names, selected=pt_name if pt_name in all_pitch_type_names else None),
                        ui.layout_columns(
                            ui.input_numeric("cmd_pl_edit_ix", "Intended plate side", value=float(p.intended_x), min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                            ui.input_numeric("cmd_pl_edit_iz", "Intended plate height", value=float(p.intended_z), min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
                        ),
                        ui.layout_columns(
                            ui.input_numeric("cmd_pl_edit_ax", "Actual plate side", value=float(p.actual_x) if p.actual_x is not None else 0.0, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                            ui.input_numeric("cmd_pl_edit_az", "Actual plate height", value=float(p.actual_z) if p.actual_z is not None else 2.5, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
                        ),
                        ui.layout_columns(
                            ui.input_text("cmd_pl_edit_velocity", "Velocity (mph, optional)", value="" if p.velocity is None else str(p.velocity)),
                            ui.input_text("cmd_pl_edit_notes", "Notes (optional)", value=p.notes or ""),
                        ),
                        ui.layout_columns(
                            ui.input_action_button("cmd_pl_save_edit_btn", "Save", class_="btn-primary btn-sm"),
                            ui.input_action_button("cmd_pl_cancel_edit_btn", "Cancel", class_="btn-outline-secondary btn-sm"),
                            col_widths=[6, 6],
                        ),
                        class_="border rounded p-2 mb-2",
                    ))
                    continue

                if can_edit and p.command_pitch_id == pending_delete_id:
                    rows.append(ui.div(
                        ui.p(f"Delete pitch #{p.pitch_number} ({pt_name})? This can't be undone.", class_="text-danger mb-1"),
                        ui.layout_columns(
                            ui.input_action_button("cmd_pl_confirm_delete_btn", "Confirm delete", class_="btn-danger btn-sm"),
                            ui.input_action_button("cmd_pl_cancel_delete_btn", "Cancel", class_="btn-outline-secondary btn-sm"),
                            col_widths=[6, 6],
                        ),
                        class_="border border-danger rounded p-2 mb-2",
                    ))
                    continue

                summary = f"#{p.pitch_number} — {pt_name} — Intended {float(p.intended_x):+.2f}/{float(p.intended_z):.2f}"
                if p.actual_x is not None and p.actual_z is not None:
                    miss_label = f"{float(p.miss_distance):.1f} in ({p.miss_direction})" if p.miss_distance is not None else "—"
                    summary += f" — Actual {float(p.actual_x):+.2f}/{float(p.actual_z):.2f} — Miss {miss_label}"
                    score = command_metrics.pitch_execution_score(p)
                    if score is not None:
                        summary += f" — Execution {score} ({command_config.execution_score_label(score)})"
                else:
                    summary += " — Actual not recorded"
                if p.velocity is not None:
                    summary += f" — {float(p.velocity):.0f} mph"
                row_children = [ui.p(summary, class_="mb-0 small")]
                if p.notes:
                    row_children.append(ui.p(p.notes, class_="text-muted small mb-0"))

                if can_edit:
                    edit_btn_id = f"cmd_pl_edit_btn_{p.command_pitch_id}"
                    delete_btn_id = f"cmd_pl_delete_btn_{p.command_pitch_id}"
                    rows.append(ui.layout_columns(
                        ui.div(*row_children),
                        ui.input_action_button(edit_btn_id, "Edit", class_="btn-outline-primary btn-sm"),
                        ui.input_action_button(delete_btn_id, "Delete", class_="btn-outline-danger btn-sm"),
                        col_widths=[8, 2, 2],
                    ))
                    if edit_btn_id not in _registered_pitch_row_ids:
                        _registered_pitch_row_ids.add(edit_btn_id)
                        _registered_pitch_row_ids.add(delete_btn_id)
                        _register_pitch_row_handlers(p.command_pitch_id)
                else:
                    rows.append(ui.div(*row_children))

            children.extend(rows)
            return ui.div(*children)
        finally:
            db.close()

    def _register_pitch_row_handlers(pitch_id):
        edit_btn_id = f"cmd_pl_edit_btn_{pitch_id}"
        delete_btn_id = f"cmd_pl_delete_btn_{pitch_id}"

        @reactive.effect
        @reactive.event(input[edit_btn_id])
        def _on_edit_trigger():
            _pending_delete_pitch_id.set(None)
            _editing_pitch_id.set(pitch_id)
            _bump_refresh()

        @reactive.effect
        @reactive.event(input[delete_btn_id])
        def _on_delete_trigger():
            _editing_pitch_id.set(None)
            _pending_delete_pitch_id.set(pitch_id)
            _bump_refresh()

    @reactive.effect
    @reactive.event(input.cmd_pl_cancel_edit_btn)
    def _cancel_pitch_edit():
        _editing_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.cmd_pl_save_edit_btn)
    def _save_pitch_edit():
        pitch_id = _editing_pitch_id()
        if pitch_id is None:
            return
        req("cmd_pl_edit_pitch_type" in input)
        req("cmd_pl_edit_ix" in input)
        req("cmd_pl_edit_ax" in input)

        pitch_type_name = input.cmd_pl_edit_pitch_type()
        intended_x, intended_z = input.cmd_pl_edit_ix(), input.cmd_pl_edit_iz()
        actual_x, actual_z = input.cmd_pl_edit_ax(), input.cmd_pl_edit_az()
        velocity_raw = (input.cmd_pl_edit_velocity() or "").strip()
        velocity = None
        if velocity_raw:
            try:
                velocity = float(velocity_raw)
            except ValueError:
                ui.notification_show("Velocity must be a number (or left blank) -- edit not saved.", type="error", duration=8)
                return
        notes = (input.cmd_pl_edit_notes() or "").strip() or None

        db = get_session()
        try:
            pitch = (
                db.query(CommandPitch)
                .options(joinedload(CommandPitch.bullpen).joinedload(BullpenSession.player))
                .filter(CommandPitch.command_pitch_id == pitch_id)
                .first()
            )
            if pitch is None:
                _editing_pitch_id.set(None)
                _bump_refresh()
                return
            pitch_type = db.query(PitchType).filter(PitchType.type_name == pitch_type_name).first()
            throws = pitch.bullpen.player.throws if pitch.bullpen and pitch.bullpen.player else None
            derived = command_metrics.compute_command_pitch_fields(intended_x, intended_z, actual_x, actual_z, throws)

            pitch.pitch_type_id = pitch_type.pitch_type_id if pitch_type else None
            pitch.intended_x = intended_x
            pitch.intended_z = intended_z
            pitch.actual_x = actual_x
            pitch.actual_z = actual_z
            pitch.velocity = velocity
            pitch.notes = notes
            for field_name, field_value in derived.items():
                setattr(pitch, field_name, field_value)
            db.commit()
            ui.notification_show(f"Updated pitch #{pitch.pitch_number}.", type="message", duration=6)
        finally:
            db.close()
        _editing_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.cmd_pl_cancel_delete_btn)
    def _cancel_pitch_delete():
        _pending_delete_pitch_id.set(None)
        _bump_refresh()

    @reactive.effect
    @reactive.event(input.cmd_pl_confirm_delete_btn)
    def _confirm_pitch_delete():
        pitch_id = _pending_delete_pitch_id()
        if pitch_id is None:
            return
        db = get_session()
        try:
            pitch = db.query(CommandPitch).filter(CommandPitch.command_pitch_id == pitch_id).first()
            if pitch is None:
                _pending_delete_pitch_id.set(None)
                _bump_refresh()
                return
            deleted_number = pitch.pitch_number
            db.delete(pitch)
            db.commit()
            ui.notification_show(f"Deleted pitch #{deleted_number}.", type="message", duration=6)
        finally:
            db.close()
        _pending_delete_pitch_id.set(None)
        _bump_refresh()

    # -------------------------------------------------------------------
    # Session command scorecard + command chart (Step 7, Sections 18/21).
    # Pure display over analytics/command_metrics.py's already-built
    # aggregate functions -- no new math here, this module just formats
    # session_command_scorecard/miss_bias/command_by_pitch_type into KPI
    # cards and a table, and hands the same pitch list to
    # visualizations/command_charts.command_chart() for the plot. All
    # three read the derived fields already stored on CommandPitch at
    # save/edit time (see command_metrics.py's module docstring on why
    # aggregates never recompute miss_distance/direction themselves).
    # -------------------------------------------------------------------

    def _fmt(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "—"

    def _bias_label(bias):
        parts = []
        if bias["horizontal_bias_in"] is not None:
            parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
        if bias["vertical_bias_in"] is not None:
            parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
        return " / ".join(parts) if parts else "—"

    @render.ui
    def cmd_scorecard_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_session = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.player), joinedload(BullpenSession.command_pitches).joinedload(CommandPitch.pitch_type))
                .filter(BullpenSession.bullpen_id == bullpen_id)
                .first()
            )
            if active_session is None:
                return None
            pitches = active_session.command_pitches
            if not pitches:
                # Pitch log's own empty state already covers "no pitches
                # yet" -- nothing useful to summarize here on top of it.
                return None

            throws = active_session.player.throws if active_session.player else None
            scorecard = command_metrics.session_command_scorecard(pitches)
            children = [ui.hr(), ui.h5("Session command scorecard", class_="gbo-section-title")]

            if scorecard["located_pitches"] == 0:
                children.append(ui_helpers.empty_state("No pitches have an actual location recorded yet -- the scorecard fills in once at least one does."))
                return ui.div(*children)

            children.append(ui_helpers.render_kpi_cards([
                {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
                {"label": "Avg Miss", "value": _fmt(scorecard["avg_miss_distance"], " in")},
                {"label": "Danger-Adj. Miss", "value": _fmt(scorecard["avg_danger_adjusted_miss"], " in")},
                {"label": "Median Miss", "value": _fmt(scorecard["median_miss_distance"], " in")},
                {"label": "Execution %", "value": _fmt(scorecard["execution_pct"], "%")},
                {"label": "Precision %", "value": _fmt(scorecard["precision_pct"], "%")},
                {"label": "Command Target %", "value": _fmt(scorecard["command_target_pct"], "%")},
                {"label": "Competitive %", "value": _fmt(scorecard["competitive_pct"], "%")},
                {"label": "Major Miss %", "value": _fmt(scorecard["major_miss_pct"], "%")},
            ]))

            bias = command_metrics.miss_bias(pitches, throws)
            children.append(ui.p(f"Average miss bias: {_bias_label(bias)}", class_="text-muted small mt-2"))

            by_type = command_metrics.command_by_pitch_type(pitches, throws)
            if len(by_type) > 1:
                rows = [{
                    "Pitch Type": row["Pitch Type"],
                    "Pitches": row["Pitches"],
                    "Avg Miss (in)": row["Avg Miss"] if row["Avg Miss"] is not None else "—",
                    "Danger-Adj. Miss (in)": row["Danger-Adj. Miss"] if row["Danger-Adj. Miss"] is not None else "—",
                    "Execution %": row["Execution %"] if row["Execution %"] is not None else "—",
                    "Precision %": row["Precision %"] if row["Precision %"] is not None else "—",
                    "Command %": row["Command Target %"] if row["Command Target %"] is not None else "—",
                    "Major Miss %": row["Major Miss %"] if row["Major Miss %"] is not None else "—",
                    "Miss Bias": _bias_label(row["Miss Bias"]),
                } for row in by_type]
                children.append(ui.h6("By pitch type", class_="mt-3"))
                children.append(ui_helpers.render_dict_table(rows))

            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def cmd_chart_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            has_located = (
                db.query(CommandPitch)
                .filter(CommandPitch.bullpen_id == bullpen_id, CommandPitch.horizontal_miss.isnot(None))
                .first()
                is not None
            )
        finally:
            db.close()

        children = [ui.hr(), ui.h5("Command chart", class_="gbo-section-title")]
        if not has_located:
            children.append(ui_helpers.empty_state("No pitches have an actual location recorded yet -- the chart fills in once at least one does."))
            return ui.div(*children)
        children.append(output_widget("cmd_command_chart"))
        return ui.div(*children)

    @render_plotly
    def cmd_command_chart():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        db = get_session()
        try:
            pitches = (
                db.query(CommandPitch)
                .options(joinedload(CommandPitch.pitch_type))
                .filter(CommandPitch.bullpen_id == bullpen_id)
                .order_by(CommandPitch.pitch_number)
                .all()
            )
            if not pitches:
                return None
            return command_charts.command_chart(pitches)
        finally:
            db.close()
