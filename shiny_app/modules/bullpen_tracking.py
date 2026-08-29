"""
GBO -- Bullpen Tracking module (manual zone-tap workflow).

Direct port of pages/bullpen_tracking.py -- a real bullpen tracking
sheet: pick a pitcher, start a session (typed by bullpen type), log each
pitch live with a tap-friendly 3x3 target-zone grid (catcher's-eye
view). Per the Rapsodo Bullpen Analytics architecture review, this
manual-tap workflow is planned for retirement once Rapsodo import is the
standard path for every tracked bullpen -- kept running as-is here, not
a target for further feature investment beyond this straight port.

Once a bullpen's Rapsodo CSV is imported separately (Import Rapsodo
Data), a pitch here can optionally be linked to its matching
Rapsodo-imported record -- the ACTUAL zone and hit/miss are then
computed from the real Plate Height/Plate Side coordinates, compared
against the intended zone called in real time. Logging a pitch only
records intent; Rapsodo determines what actually happened once linked.

Restricted to Administrator/Head Coach/Coach/Sports Scientist/Data
Analyst, and hidden from Hitting-specialty coaches (mirror image of
Hitter Tracking's restriction).

Query-params-as-navigation, replaced per the migration plan's
translation table: the original's `st.query_params["bullpen_id"]`
round-trip (used specifically because Streamlit kept resetting the
Session dropdown otherwise) becomes a local `_active_bullpen_id`
reactive.Value, synced from the session picker via a plain (non-evented)
effect -- same technique hitter_tracking.py's `_active_session_id` and
bullpen_dashboard.py's `_target_bullpen_id` already establish. "Open
Rapsodo Bullpen Dashboard for this session" is a real cross-page jump
though, so THAT one button still uses the shared
app_state.deep_link_bullpen_id + ui.update_navs("main_nav", ...,
session=session.root_scope()) pattern rapsodo_import.py established.

Reactive block chain, each block existing only to satisfy the "never
read an input from the block that defines it" ordering hazard used
throughout this migration:
  pitcher_picker -> session_picker (+ a plain _sync_active_bullpen_id
  effect mirroring session_select into the local reactive.Value) ->
  pending_assignments_section / new_bullpen_type_picker ->
  new_bullpen_form (reads the type picker) -> active_session_header ->
  zone_view_toggle -> record_pitch_section (reads the toggle + the
  local _target_zone reactive.Value) -> pitch_log_section ->
  session_summary_section -> charts_section.

The 3x3 + Bury zone grid is a FIXED, known-in-advance set of 10 buttons
(ids bp_zone_btn_0..9), statically registered at server-setup time --
same pattern hitter_tracking.py's two grids use. Unlike that page, this
grid's on-screen LAYOUT (not the underlying zone numbers, which are
fixed physical locations) flips between Pitcher's view and Catcher's
view -- `_zone_grid_buttons` takes a `catcher_view` flag and reverses
each row's left-right order for display only; button ids stay tied to
the physical zone number either way, so static registration still
works regardless of which view is selected. "Reset after submit" (pitch
type back to 4-Seam Fastball, zone back to 5) uses the same
_bump_refresh() + explicit `_target_zone.set(5)` technique
hitter_tracking.py's docstring documents, plus `ui.update_select` to
reset the pitch-type dropdown specifically (a real input widget, not a
bare reactive.Value, so it needs an explicit client-side update rather
than just being rebuilt fresh).

Two genuinely unbounded, data-dependent button sets get LAZY
registration (training_routines.py's per-exercise video-save buttons
are the canonical example this migration follows):
  - "Start this bullpen" per pending PlayerAssignment
    (_registered_assignment_ids / _register_assignment_handler)
  - "Link" per not-yet-linked BullpenPitch, in the "Link pitches to
    Rapsodo data" section (_registered_link_ids / _register_link_handler)
The pitch-video section, by contrast, follows assessments.py's simpler
"one fixed Save button, read whichever record is currently selected in
a dropdown" pattern (video_pitch_choice + a single upload/save button
pair) rather than lazy-per-row, since only one pitch's video is being
edited at a time here.

Charts (movement plot, release point, strike zone plot, velocity bar)
are decorative/hover-only in the original (no on_select/click capture),
so they render as static PNGs via chart_helpers.fig_to_img, same
technique player_bullpens.py/bullpen_dashboard_display.py already use.
"""

from datetime import date, datetime

import plotly.graph_objects as go
from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from r2_client import upload_video_to_r2
from models import (
    Player, StaffPlayerAssignment, BullpenType, BullpenSession, BullpenPitch,
    PitchType, Assessment, AssessmentCategory, AssessmentResult, PlayerAssignment,
    BullpenScript, RapsodoPitch, RapsodoImport,
)
from services.rapsodo_import import delete_rapsodo_import, RapsodoImportError
from video_helpers import drive_file_id, render_video_clip

import ui_helpers
import chart_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")
PITCH_VIDEO_SUBFOLDER = "pitch-videos/"

PITCH_TYPE_COLORS = [
    "#3A8FE0", "#B08618", "#2A9E7A", "#B85FC4", "#E0713F", "#7F7EDB", "#D94F3D", "#7A8594",
]

# Fixed generic strike-zone boundaries in feet (not per-batter calibrated).
ZONE_SIDE_BOUNDS = (-0.283, 0.283)
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)
BURY_HEIGHT_THRESHOLD = 1.5

_SIDE_THIRD = ZONE_SIDE_BOUNDS[1] - ZONE_SIDE_BOUNDS[0]
FULL_ZONE_SIDE = (ZONE_SIDE_BOUNDS[0] - _SIDE_THIRD, ZONE_SIDE_BOUNDS[1] + _SIDE_THIRD)
_HEIGHT_THIRD = ZONE_HEIGHT_BOUNDS[1] - ZONE_HEIGHT_BOUNDS[0]
FULL_ZONE_HEIGHT = (ZONE_HEIGHT_BOUNDS[0] - _HEIGHT_THIRD, ZONE_HEIGHT_BOUNDS[1] + _HEIGHT_THIRD)

ZONE_GRID_LAYOUT = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


def get_zone_labels(throws):
    if throws == "R":
        arm_col, glove_col = "Arm Side", "Glove Side"
    elif throws == "L":
        arm_col, glove_col = "Glove Side", "Arm Side"
    else:
        arm_col, glove_col = "Left", "Right"
    col0_label, col2_label = arm_col, glove_col
    return {
        0: "Bury (in the dirt)",
        1: f"Up-{col0_label}", 2: "Up-Middle", 3: f"Up-{col2_label}",
        4: f"Middle-{col0_label}", 5: "Middle-Middle", 6: f"Middle-{col2_label}",
        7: f"Down-{col0_label}", 8: "Down-Middle", 9: f"Down-{col2_label}",
    }


def compute_actual_zone(plate_side_ft, plate_height_ft):
    if plate_height_ft < BURY_HEIGHT_THRESHOLD:
        return 0
    if plate_side_ft < ZONE_SIDE_BOUNDS[0]:
        col = 0
    elif plate_side_ft > ZONE_SIDE_BOUNDS[1]:
        col = 2
    else:
        col = 1
    if plate_height_ft > ZONE_HEIGHT_BOUNDS[1]:
        row = 0
    elif plate_height_ft < ZONE_HEIGHT_BOUNDS[0]:
        row = 2
    else:
        row = 1
    return row * 3 + col + 1


def _zone_grid_buttons(current_zone, catcher_view):
    rows = []
    for row in ZONE_GRID_LAYOUT:
        display_row = row if catcher_view else list(reversed(row))
        cells = []
        for zone in display_row:
            is_selected = current_zone == zone
            label = f"● {zone}" if is_selected else str(zone)
            cells.append(ui.input_action_button(f"bp_zone_btn_{zone}", label, class_="w-100"))
        rows.append(ui.layout_columns(*cells))
    bury_selected = current_zone == 0
    bury_label = "● Bury (in the dirt)" if bury_selected else "Bury (in the dirt)"
    rows.append(ui.input_action_button("bp_zone_btn_0", bury_label, class_="w-100 mt-1"))
    return ui.div(*rows)


def _render_scatter_with_averages(title, x_label, y_label, data_by_type, x_key, y_key):
    fig = go.Figure()
    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e[x_key] for e in entries if x_key in e and y_key in e]
        ys = [e[y_key] for e in entries if x_key in e and y_key in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=8, opacity=0.35),
            showlegend=False,
            hovertemplate=f"{pitch_type}<br>{x_label}: %{{x}}<br>{y_label}: %{{y}}<extra></extra>",
        ))
        avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
        fig.add_trace(go.Scatter(
            x=[avg_x], y=[avg_y], mode="markers+text", name=pitch_type,
            marker=dict(color=color, size=18, line=dict(color="#AEB6C2", width=2)),
            text=[pitch_type], textposition="top center",
            textfont=dict(color="#AEB6C2", size=12),
            hovertemplate=f"{pitch_type} average<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(
        title=title, xaxis_title=x_label, yaxis_title=y_label,
        showlegend=False, height=420,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB6C2"),
        xaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039"),
        yaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039"),
        margin=dict(t=40, b=40, l=40, r=40),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=420)


def _render_strike_zone_plot(title, data_by_type):
    fig = go.Figure()
    fig.add_shape(type="rect", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1],
                  line=dict(color="#AEB6C2", width=2), fillcolor="rgba(0,0,0,0)")
    for x in ZONE_SIDE_BOUNDS:
        fig.add_shape(type="line", x0=x, x1=x, y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1], line=dict(color="#5A5A5A", width=1, dash="dot"))
    for y in ZONE_HEIGHT_BOUNDS:
        fig.add_shape(type="line", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=y, y1=y, line=dict(color="#5A5A5A", width=1, dash="dot"))

    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e["Plate Side"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        ys = [e["Plate Height"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#171B21", width=1)),
            hovertemplate=f"{pitch_type}<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
        ))

    fig.update_layout(
        title=title, xaxis_title="Plate Side (ft)", yaxis_title="Plate Height (ft)",
        showlegend=True, height=480,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB6C2"),
        xaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039", range=[FULL_ZONE_SIDE[0] - 1, FULL_ZONE_SIDE[1] + 1], scaleanchor="y", scaleratio=1),
        yaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039", range=[0, FULL_ZONE_HEIGHT[1] + 1.5]),
        margin=dict(t=40, b=40, l=40, r=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=480)


class _ShinyFileAdapter:
    """Adapts one ui.input_file() entry to the .name/.getvalue()/.type
    shape upload_video_to_r2() expects -- same adapter as
    training_routines.py's/hitter_tracking.py's, duplicated here per
    that convention."""
    def __init__(self, file_info: dict):
        self.name = file_info["name"]
        self.type = file_info.get("type")
        self._datapath = file_info["datapath"]

    def getvalue(self) -> bytes:
        with open(self._datapath, "rb") as f:
            return f.read()


def _upload_pitch_video(file_info: dict, identifier: str):
    try:
        return upload_video_to_r2(_ShinyFileAdapter(file_info), identifier, bucket_subfolder=PITCH_VIDEO_SUBFOLDER)
    except Exception as e:
        ui.notification_show(
            f"Video upload failed: {e}. Make sure Cloudflare R2 is configured "
            f"(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- "
            f"see r2_client.py's docstring for setup steps).",
            type="error", duration=12,
        )
        return None


@module.ui
def bullpen_tracking_ui():
    return ui.div(
        ui_helpers.page_header("Bullpen Tracking"),
        ui.output_ui("pitcher_picker"),
        ui.output_ui("session_picker"),
        ui.output_ui("pending_assignments_section"),
        ui.output_ui("new_bullpen_type_picker"),
        ui.output_ui("new_bullpen_form"),
        ui.output_ui("active_session_header"),
        ui.output_ui("zone_view_toggle"),
        ui.output_ui("record_pitch_section"),
        ui.output_ui("pitch_log_section"),
        ui.output_ui("pitch_video_section"),
        ui.output_ui("link_to_rapsodo_section"),
        ui.output_ui("session_summary_section"),
        ui.output_ui("charts_section"),
        ui_helpers.page_footer(),
    )


@module.server
def bullpen_tracking_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _active_bullpen_id = reactive.Value(None)
    _target_zone = reactive.Value(None)  # None = no location picked -- Command Tracker already owns precise intended-location entry, so this defaults to "not tracked" instead of a misleading zone 5 (Aug 2026, per Ryker)
    _registered_assignment_ids = set()
    _registered_link_ids = set()

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

    # --- Statically register the 10 zone-grid button handlers once, at
    # server-setup time -- a fixed, known-in-advance set (unlike the
    # lazily-registered per-assignment/per-link buttons below). ------
    def _register_zone_button(zone):
        @reactive.effect
        @reactive.event(input[f"bp_zone_btn_{zone}"])
        def _handler():
            _target_zone.set(zone)
        return _handler

    for _zone in range(10):
        _register_zone_button(_zone)

    # -------------------------------------------------------------------
    # Pitcher + session pickers
    # -------------------------------------------------------------------

    @render.ui
    def pitcher_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        db = get_session()
        try:
            pitchers = _visible_pitchers(db)
            if not pitchers:
                return ui_helpers.empty_state("No pitchers to show yet." if app_state.can_view_all_players() else "No pitchers are currently assigned to you.")
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitchers}
            # Preserve the current pitcher across _refresh_tick-triggered rebuilds
            # (e.g. every time a pitch is recorded) -- without this, the widget was
            # rebuilt with no `selected=`, so it silently snapped back to the first
            # pitcher in the list on every save. That cascaded into session_picker
            # re-rendering with the WRONG pitcher's session list, which is what made
            # it look like recording a pitch "kicked you out" of the active session.
            current = input.pitcher_select() if "pitcher_select" in input else None
            selected = current if current in choices else None
            return ui.input_select("pitcher_select", "Pitcher", choices=choices, selected=selected)
        finally:
            db.close()

    @render.ui
    def session_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        req("pitcher_select" in input)
        selected_pitcher_id = int(input.pitcher_select())

        db = get_session()
        try:
            existing_sessions = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.player_id == selected_pitcher_id)
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            choices = {"": "-- Start a new bullpen session --"}
            choices.update({
                str(b.bullpen_id): f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {b.bullpen_type.type_name if b.bullpen_type else '—'} ({len(b.pitches)} pitches)"
                for b in existing_sessions
            })
            active_id = _active_bullpen_id()
            return ui.div(ui.hr(), ui.input_select("session_select", "Session", choices=choices, selected=str(active_id) if active_id is not None else ""))
        finally:
            db.close()

    @reactive.effect
    def _sync_active_bullpen_id():
        req("session_select" in input)
        raw = input.session_select()
        _active_bullpen_id.set(int(raw) if raw else None)

    # -------------------------------------------------------------------
    # Pending prescribed-but-not-yet-tracked bullpen assignments
    # -------------------------------------------------------------------

    @render.ui
    def pending_assignments_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("pitcher_select" in input)
        if _active_bullpen_id() is not None:
            return None
        selected_pitcher_id = int(input.pitcher_select())

        db = get_session()
        try:
            already_linked_ids = {
                b.source_assignment_id for b in
                db.query(BullpenSession).filter(BullpenSession.player_id == selected_pitcher_id).all()
                if b.source_assignment_id
            }
            pending = (
                db.query(PlayerAssignment)
                .options(joinedload(PlayerAssignment.bullpen_script).joinedload(BullpenScript.pitches), joinedload(PlayerAssignment.bullpen_type))
                .filter(
                    PlayerAssignment.player_id == selected_pitcher_id,
                    PlayerAssignment.bullpen_type_id.isnot(None),
                    PlayerAssignment.completed.is_(False),
                )
                .order_by(PlayerAssignment.scheduled_date.desc())
                .all()
            )
            pending = [a for a in pending if a.assignment_id not in already_linked_ids]
            if not pending:
                return None

            rows = [ui.p(f"{len(pending)} prescribed bullpen assignment(s) not yet tracked:")]
            for a in pending:
                bp_type_name = a.bullpen_type.type_name if a.bullpen_type else "—"
                date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
                label = f"**{bp_type_name}**"
                if a.bullpen_script:
                    label += f" — script: {a.bullpen_script.script_name}"
                label += f" — {date_label}" + (f" — _{a.notes}_" if a.notes else "")
                rows.append(ui.layout_columns(
                    ui.markdown(label),
                    ui.input_action_button(f"start_from_assignment_{a.assignment_id}", "Start this bullpen", class_="btn-primary btn-sm"),
                    col_widths=[9, 3],
                ))
                if a.assignment_id not in _registered_assignment_ids:
                    _registered_assignment_ids.add(a.assignment_id)
                    _register_assignment_handler(a.assignment_id, selected_pitcher_id)

            rows.append(ui.hr())
            rows.append(ui.p("Or start a bullpen that wasn't pre-assigned:", class_="text-muted small"))
            return ui.div(*rows)
        finally:
            db.close()

    def _register_assignment_handler(assignment_id, pitcher_id):
        @reactive.effect
        @reactive.event(input[f"start_from_assignment_{assignment_id}"])
        def _handler():
            db = get_session()
            try:
                a = db.query(PlayerAssignment).options(joinedload(PlayerAssignment.bullpen_script).joinedload(BullpenScript.pitches), joinedload(PlayerAssignment.bullpen_type)).filter(PlayerAssignment.assignment_id == assignment_id).first()
                if a is None:
                    return
                new_bullpen = BullpenSession(
                    player_id=pitcher_id, bullpen_type_id=a.bullpen_type_id, source_assignment_id=a.assignment_id,
                    session_date=a.scheduled_date, created_by_user_id=app_state.user_id(),
                )
                db.add(new_bullpen)
                db.flush()
                pitches_loaded = 0
                if a.bullpen_script:
                    for sp in a.bullpen_script.pitches:
                        db.add(BullpenPitch(bullpen_id=new_bullpen.bullpen_id, pitch_number=sp.pitch_number, pitch_type_id=sp.pitch_type_id, target_zone=sp.target_zone, notes=sp.notes))
                        pitches_loaded += 1
                db.commit()
                _active_bullpen_id.set(new_bullpen.bullpen_id)
                bp_type_name = a.bullpen_type.type_name if a.bullpen_type else "—"
                msg = f"Started {bp_type_name} bullpen."
                if pitches_loaded:
                    msg += f" Loaded {pitches_loaded} planned pitch(es) from {a.bullpen_script.script_name}."
                ui.notification_show(msg, type="message", duration=8)
                _bump_refresh()
            finally:
                db.close()

    # -------------------------------------------------------------------
    # New bullpen session (not pre-assigned)
    # -------------------------------------------------------------------

    @render.ui
    def new_bullpen_type_picker():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("pitcher_select" in input)
        if _active_bullpen_id() is not None:
            return None
        db = get_session()
        try:
            bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all()
            choices = {t.type_name: t.type_name for t in bullpen_types}
            return ui.input_select("new_bullpen_type_choice", "Bullpen type", choices=choices)
        finally:
            db.close()

    @render.ui
    def new_bullpen_form():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("pitcher_select" in input)
        if _active_bullpen_id() is not None:
            return None
        req("new_bullpen_type_choice" in input)
        type_choice = input.new_bullpen_type_choice()

        db = get_session()
        try:
            bullpen_type = db.query(BullpenType).filter(BullpenType.type_name == type_choice).first()
            if bullpen_type is None:
                return None
            matching_scripts = (
                db.query(BullpenScript)
                .options(joinedload(BullpenScript.pitches))
                .filter(BullpenScript.bullpen_type_id == bullpen_type.bullpen_type_id)
                .order_by(BullpenScript.script_name)
                .all()
            )
            script_block = []
            if matching_scripts:
                script_choices = {"": "-- No script, start blank --"}
                script_choices.update({str(s.script_id): f"{s.script_name} ({len(s.pitches)} pitches)" for s in matching_scripts})
                script_block = [ui.input_select("new_bullpen_script_choice", "Load a script (optional)", choices=script_choices)]
            else:
                script_block = [ui.p(f"No {type_choice} scripts saved yet -- build one on Bullpen Scripts first if you want to pre-load a planned sequence.", class_="text-muted small")]

            return ui.div(
                ui.input_date("new_bullpen_date", "Date", value=date.today()),
                *script_block,
                ui.input_text_area("new_bullpen_notes", "Session notes (optional)"),
                ui.input_action_button("start_bullpen_btn", "Start bullpen session", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.start_bullpen_btn)
    def _start_bullpen():
        selected_pitcher_id = int(input.pitcher_select())
        type_choice = input.new_bullpen_type_choice()
        db = get_session()
        try:
            bullpen_type = db.query(BullpenType).filter(BullpenType.type_name == type_choice).first()
            if bullpen_type is None:
                return
            new_bullpen = BullpenSession(
                player_id=selected_pitcher_id, bullpen_type_id=bullpen_type.bullpen_type_id,
                session_date=input.new_bullpen_date(), overall_notes=(input.new_bullpen_notes() or "").strip() or None,
                created_by_user_id=app_state.user_id(),
            )
            db.add(new_bullpen)
            db.flush()

            pitches_loaded = 0
            script_raw = input.new_bullpen_script_choice() if "new_bullpen_script_choice" in input else ""
            if script_raw:
                script = db.query(BullpenScript).options(joinedload(BullpenScript.pitches)).filter(BullpenScript.script_id == int(script_raw)).first()
                if script:
                    for sp in script.pitches:
                        db.add(BullpenPitch(bullpen_id=new_bullpen.bullpen_id, pitch_number=sp.pitch_number, pitch_type_id=sp.pitch_type_id, target_zone=sp.target_zone, notes=sp.notes))
                        pitches_loaded += 1

            db.commit()
            _active_bullpen_id.set(new_bullpen.bullpen_id)
            msg = f"Started {type_choice} bullpen for {input.new_bullpen_date().strftime('%Y-%m-%d (%a)')}."
            if pitches_loaded:
                msg += f" Loaded {pitches_loaded} planned pitch(es) from the script -- link them to Rapsodo data once that day's CSV is imported."
            ui.notification_show(msg, type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Active session header
    # -------------------------------------------------------------------

    @render.ui
    def active_session_header():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            if not app_state.can_edit_sessions():
                return ui.p("Your role has read-only access to bullpen tracking.", class_="text-muted")
            return None

        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.source_assignment)).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_bullpen is None:
                return None
            type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"

            children = [
                ui.hr(),
                ui.h4(f"{type_label} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')}", class_="gbo-section-title"),
            ]
            if active_bullpen.overall_notes:
                children.append(ui.p(active_bullpen.overall_notes, class_="text-muted small"))

            has_rapsodo_data = db.query(RapsodoPitch).filter(RapsodoPitch.bullpen_id == bullpen_id).first() is not None
            if has_rapsodo_data:
                children.append(ui.input_action_button("open_bullpen_dashboard_btn", "Open Rapsodo Bullpen Dashboard for this session", class_="btn-outline-primary btn-sm mb-2"))

            # Aug 2026 addition: session-level video via a pasted Google
            # Drive link (Ryker: coaches currently film the whole bullpen
            # as one continuous video, not per-pitch clips -- clipping
            # individual pitches out of it is extra work nobody's doing
            # today). This is deliberately Drive-paste ONLY, no file-
            # upload alternative: a full bullpen video is a much bigger
            # file than a single pitch clip (see BullpenPitch.video_url's
            # file-upload path just below), and Drive-paste is exactly
            # how video_import.py/hitter_tracking.py already avoid that
            # problem elsewhere in this app. render_video_clip() (shared
            # with those pages) renders whatever's already stored in
            # active_bullpen.video_url correctly either way -- it was
            # already being read on the Bullpen Dashboard, just via a
            # raw <video> tag that could never actually play a Drive
            # link; that display bug is fixed as part of this change too
            # (see bullpen_dashboard_display.py).
            video_section = [ui.h6("Session video", class_="mt-2 mb-1")]
            if active_bullpen.video_url:
                video_section.append(render_video_clip(active_bullpen.video_url, height="320"))
            if app_state.can_edit_sessions():
                video_section.append(ui.p(
                    "Paste a Google Drive share link for this session's full bullpen video. "
                    "Make sure sharing is set to \"Anyone with the link can view\" so it plays inline.",
                    class_="text-muted small mt-1",
                ))
                video_section.append(ui.input_text(
                    "bp_session_video_link", None,
                    value=active_bullpen.video_url or "",
                    placeholder="https://drive.google.com/file/d/.../view?usp=sharing",
                ))
                video_section.append(ui.input_action_button(
                    "bp_session_video_save_btn",
                    "Replace video" if active_bullpen.video_url else "Save video",
                    class_="btn-primary btn-sm mt-1",
                ))
            children.append(ui.div(*video_section, class_="mb-2"))

            if app_state.can_edit_sessions():
                pitch_count = len(active_bullpen.pitches)
                children.append(ui.accordion(
                    ui.accordion_panel(
                        "Delete this session",
                        ui.p(f"This permanently deletes this bullpen session and all {pitch_count} pitch(es) logged in it. This can't be undone.", class_="text-warning small"),
                        ui.input_checkbox("confirm_delete_bullpen", "Yes, I want to permanently delete this session", value=False),
                        ui.input_action_button("delete_bullpen_btn", "Delete session", class_="btn-danger btn-sm"),
                    ),
                    open=False, id=None,
                ))

                if active_bullpen.source_assignment:
                    if active_bullpen.source_assignment.completed:
                        children.append(ui.p("Source assignment already marked completed.", class_="text-muted small"))
                    elif active_bullpen.pitches:
                        children.append(ui.input_action_button("complete_source_assignment_btn", "Mark source assignment as completed", class_="btn-primary btn-sm"))
                    else:
                        children.append(ui.p("This bullpen came from a prescribed assignment — log at least one pitch to mark it completed.", class_="text-muted small"))

            return ui.div(*children)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.open_bullpen_dashboard_btn)
    def _open_bullpen_dashboard():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        app_state.deep_link_bullpen_id.set(bullpen_id)
        ui.update_navs("main_nav", selected="Bullpen Dashboard", session=session.root_scope())

    @reactive.effect
    @reactive.event(input.delete_bullpen_btn)
    def _delete_bullpen():
        if not (input.confirm_delete_bullpen() if "confirm_delete_bullpen" in input else False):
            return
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_bullpen is None:
                return
            # Capture any Rapsodo import audit records tied to this session
            # BEFORE deleting it. BullpenSession's cascade only covers the
            # RapsodoPitch rows themselves (rapsodo_pitches relationship,
            # cascade="all, delete-orphan") -- the RapsodoImport audit
            # record each upload created has no such cascade, and its
            # bullpen_id column is nullable, so deleting the session just
            # leaves that record behind with bullpen_id nulled out rather
            # than blocking the delete. Left alone, that orphaned record's
            # file_hash keeps tripping the "this file was already
            # imported" duplicate guard forever, even after the session
            # and its pitches are long gone -- found via a real case (Aug
            # 2026): deleting a bullpen to fix a wrong-pitcher Rapsodo
            # upload permanently blocked that file from ever being
            # re-uploaded, anywhere, since the duplicate check is keyed on
            # (player_id, file_hash), not on a still-existing session.
            stale_import_ids = [
                i.import_id for i in
                db.query(RapsodoImport).filter(RapsodoImport.bullpen_id == bullpen_id).all()
            ]
            db.delete(active_bullpen)
            db.commit()
            # Only after the session (and its cascaded RapsodoPitch rows)
            # are actually gone -- delete_rapsodo_import would otherwise
            # hit RapsodoPitch.import_id's NOT NULL FK trying to delete an
            # import that still has live pitches attached.
            for import_id in stale_import_ids:
                try:
                    delete_rapsodo_import(db, import_id)
                except RapsodoImportError:
                    pass  # already cleaned up, or a real problem -- either way, the session delete above already succeeded, so don't block on this
            _active_bullpen_id.set(None)
            ui.notification_show(f"Deleted bullpen session #{bullpen_id}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.complete_source_assignment_btn)
    def _complete_source_assignment():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).options(joinedload(BullpenSession.source_assignment)).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_bullpen is None or active_bullpen.source_assignment is None:
                return
            active_bullpen.source_assignment.completed = True
            active_bullpen.source_assignment.completed_notes = f"Tracked in Bullpen Tracking — {len(active_bullpen.pitches)} pitches logged."
            active_bullpen.source_assignment.completed_at = datetime.utcnow()
            db.commit()
            ui.notification_show("Marked the source assignment as completed.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Zone-view toggle + record-pitch section
    # -------------------------------------------------------------------

    @render.ui
    def zone_view_toggle():
        _refresh_tick()
        if not _access_ok() or _active_bullpen_id() is None:
            return None
        return ui.input_radio_buttons("bp_zone_view", "Grid perspective", choices=["Pitcher's view", "Catcher's view"], selected="Pitcher's view", inline=True)

    @render.ui
    def record_pitch_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        req("bp_zone_view" in input)
        catcher_view = input.bp_zone_view() == "Catcher's view"

        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            selected_pitcher = db.query(Player).filter(Player.player_id == active_bullpen.player_id).first()
            if active_bullpen is None or selected_pitcher is None:
                return None
            zone_labels = get_zone_labels(selected_pitcher.throws)
            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()

            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
            same_day_pitches = []
            if category:
                same_day_pitches = (
                    db.query(Assessment)
                    .options(joinedload(Assessment.pitch_type), joinedload(Assessment.results).joinedload(AssessmentResult.test_type))
                    .filter(Assessment.player_id == active_bullpen.player_id, Assessment.category_id == category.category_id, Assessment.assessment_date == active_bullpen.session_date)
                    .order_by(Assessment.assessment_id)
                    .all()
                )

            link_block = []
            if same_day_pitches:
                link_choices = {"": "-- Not linked --"}
                for a in same_day_pitches:
                    velo = next((r.value for r in a.results if r.test_type.test_name == "Velocity"), None)
                    label = f"Pitch #{a.assessment_id}" + (f" — {float(velo):.1f} mph" if velo is not None else "")
                    link_choices[str(a.assessment_id)] = label
                link_block = [ui.input_select("bp_pitch_link_choice", "Link to Rapsodo pitch (optional, once imported)", choices=link_choices)]
            else:
                link_block = [ui.p("No Rapsodo pitches imported yet for this pitcher on this date -- you can link one later once imported.", class_="text-muted small")]

            return ui.div(
                ui.h5(f"Pitch #{len(active_bullpen.pitches) + 1}", class_="gbo-section-title"),
                ui.input_select("bp_pitch_type", "Pitch type", choices=[pt.type_name for pt in pitch_types]),
                ui.p(f"Intended zone ({input.bp_zone_view().lower()}) -- optional, skip this if you're already calling location in Command Tracker", class_="text-muted small"),
                _zone_grid_buttons(_target_zone(), catcher_view),
                ui.p(
                    f"Selected intended zone: {_target_zone()} ({zone_labels.get(_target_zone(), '—')})"
                    if _target_zone() is not None else "No location selected -- this pitch will log as a count only.",
                    class_="text-muted small",
                ),
                *link_block,
                ui.input_text("bp_pitch_notes", "Notes (optional)"),
                ui.input_action_button("record_pitch_btn", "Record pitch", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.record_pitch_btn)
    def _record_pitch():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_bullpen is None:
                return
            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == input.bp_pitch_type()), None)
            link_raw = input.bp_pitch_link_choice() if "bp_pitch_link_choice" in input else ""

            db.add(BullpenPitch(
                bullpen_id=bullpen_id,
                pitch_number=len(active_bullpen.pitches) + 1,
                pitch_type_id=pitch_type_id,
                target_zone=_target_zone(),  # None unless a zone was actually clicked -- see reactive.Value(None) above
                linked_assessment_id=int(link_raw) if link_raw else None,
                notes=(input.bp_pitch_notes() or "").strip() or None,
            ))
            had_zone = _target_zone() is not None
            db.commit()
            _target_zone.set(None)
            ui.update_select("bp_pitch_type", selected="4-Seam Fastball")
            msg = "Recorded intent" if had_zone else "Recorded pitch"
            ui.notification_show(f"{msg} for pitch #{len(active_bullpen.pitches) + 1}.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch log, video, link-to-rapsodo
    # -------------------------------------------------------------------

    def _load_active_bullpen(db, bullpen_id):
        return (
            db.query(BullpenSession)
            .options(
                joinedload(BullpenSession.bullpen_type),
                joinedload(BullpenSession.pitches).joinedload(BullpenPitch.pitch_type),
                joinedload(BullpenSession.pitches).joinedload(BullpenPitch.linked_assessment).joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
            )
            .filter(BullpenSession.bullpen_id == bullpen_id)
            .first()
        )

    @render.ui
    def pitch_log_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_bullpen = _load_active_bullpen(db, bullpen_id)
            if active_bullpen is None:
                return None
            selected_pitcher = db.query(Player).filter(Player.player_id == active_bullpen.player_id).first()
            zone_labels = get_zone_labels(selected_pitcher.throws if selected_pitcher else None)

            children = [ui.hr(), ui.h5("Pitch log", class_="gbo-section-title")]
            if not active_bullpen.pitches:
                children.append(ui_helpers.empty_state("No pitches logged yet for this session."))
                return ui.div(*children)

            rows = []
            for p in active_bullpen.pitches:
                pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                actual_zone = None
                hit_target = None
                if p.linked_assessment:
                    plate_side = next((r.value for r in p.linked_assessment.results if r.test_type.test_name == "Plate Side"), None)
                    plate_height = next((r.value for r in p.linked_assessment.results if r.test_type.test_name == "Plate Height"), None)
                    if plate_side is not None and plate_height is not None:
                        actual_zone = compute_actual_zone(float(plate_side), float(plate_height))
                        hit_target = actual_zone == p.target_zone
                rows.append({
                    "#": p.pitch_number,
                    "Pitch Type": pt_name,
                    "Intended Zone": f"{p.target_zone} ({zone_labels.get(p.target_zone, '—')})" if p.target_zone is not None else "—",
                    "Actual": f"{actual_zone} ({zone_labels.get(actual_zone, '—')})" if actual_zone is not None else "Not linked yet",
                    "Hit Target": "Yes" if hit_target is True else ("No" if hit_target is False else "—"),
                    "Notes": p.notes or "",
                })
            children.append(ui_helpers.render_dict_table(rows))

            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def pitch_video_section():
        """Defines video_pitch_choice only -- the body that reads it
        (video player + upload/save controls) lives in the SEPARATE
        pitch_video_body block below, per this migration's "never read
        an input from the block that defines it" rule."""
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_bullpen = _load_active_bullpen(db, bullpen_id)
            if active_bullpen is None or not active_bullpen.pitches:
                return None
            with_video = sum(1 for p in active_bullpen.pitches if p.video_url)
            video_choices = {}
            for p in active_bullpen.pitches:
                label = f"Pitch #{p.pitch_number}" + (f" ({p.pitch_type.type_name})" if p.pitch_type else "") + (" (video)" if p.video_url else "")
                video_choices[str(p.bullpen_pitch_id)] = label
            return ui.accordion(
                ui.accordion_panel(
                    f"Pitch video ({with_video} of {len(active_bullpen.pitches)} pitches have video)",
                    ui.input_select("video_pitch_choice", "Pitch", choices=video_choices),
                    ui.output_ui("pitch_video_body"),
                ),
                open=False, id=None,
            )
        finally:
            db.close()

    @render.ui
    def pitch_video_body():
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None
        req("video_pitch_choice" in input)
        selected_video_pitch_id = int(input.video_pitch_choice())

        db = get_session()
        try:
            selected_video_pitch = db.query(BullpenPitch).filter(BullpenPitch.bullpen_pitch_id == selected_video_pitch_id).first()
            if selected_video_pitch is None:
                return None
            children = []
            if selected_video_pitch.video_url:
                children.append(ui.tags.video(ui.tags.source(src=selected_video_pitch.video_url), controls=True, style="max-width:100%;"))
            if app_state.can_edit_sessions():
                upload_label = "Replace video" if selected_video_pitch.video_url else "Upload video"
                children.append(ui.input_file("bp_video_upload", upload_label, accept=[".mp4", ".mov", ".m4v"]))
                children.append(ui.input_action_button("bp_video_save_btn", "Save video", class_="btn-primary btn-sm mt-1"))
            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def link_to_rapsodo_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_bullpen = _load_active_bullpen(db, bullpen_id)
            if active_bullpen is None:
                return None
            children = []
            # --- Link already-logged pitches to Rapsodo data ---
            unlinked_pitches = [p for p in active_bullpen.pitches if p.linked_assessment_id is None]
            if unlinked_pitches and app_state.can_edit_sessions():
                category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
                same_day_pitches_post = []
                if category:
                    same_day_pitches_post = (
                        db.query(Assessment)
                        .options(joinedload(Assessment.pitch_type), joinedload(Assessment.results).joinedload(AssessmentResult.test_type))
                        .filter(Assessment.player_id == active_bullpen.player_id, Assessment.category_id == category.category_id, Assessment.assessment_date == active_bullpen.session_date)
                        .order_by(Assessment.assessment_id)
                        .all()
                    )

                link_children = []
                if not same_day_pitches_post:
                    link_children.append(ui.p("No Rapsodo pitches imported yet for this pitcher on this date. Import the CSV on the Import Rapsodo Data page, then come back here to link them.", class_="text-muted small"))
                else:
                    already_linked_ids = {p.linked_assessment_id for p in active_bullpen.pitches if p.linked_assessment_id}
                    available_rapsodo = [a for a in same_day_pitches_post if a.assessment_id not in already_linked_ids]
                    total_bullpen, total_rapsodo = len(active_bullpen.pitches), len(same_day_pitches_post)
                    if total_bullpen != total_rapsodo:
                        link_children.append(ui.p(f"{total_bullpen} bullpen pitches logged vs. {total_rapsodo} Rapsodo pitches imported for this date -- counts don't match. Check for extra warm-up throws or a missed rep before linking.", class_="text-warning small"))
                    else:
                        link_children.append(ui.p(f"{total_bullpen} bullpen pitches logged, {total_rapsodo} Rapsodo pitches imported -- counts match.", class_="text-muted small"))

                    post_choices = {"": "-- Not linked --"}
                    for a in same_day_pitches_post:
                        velo = next((r.value for r in a.results if r.test_type.test_name == "Velocity"), None)
                        post_choices[str(a.assessment_id)] = f"Pitch #{a.assessment_id}" + (f" — {float(velo):.1f} mph" if velo is not None else "")

                    unlinked_sorted = sorted(unlinked_pitches, key=lambda p: p.pitch_number)
                    for idx, p in enumerate(unlinked_sorted):
                        pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                        suggested_aid = available_rapsodo[idx].assessment_id if idx < len(available_rapsodo) else None
                        select_id = f"link_choice_{p.bullpen_pitch_id}"
                        btn_id = f"link_btn_{p.bullpen_pitch_id}"
                        link_children.append(ui.layout_columns(
                            ui.p(f"Pitch #{p.pitch_number} ({pt_name})", class_="mb-0"),
                            ui.input_select(select_id, None, choices=post_choices, selected=str(suggested_aid) if suggested_aid else ""),
                            ui.input_action_button(btn_id, "Link", class_="btn-sm btn-outline-primary"),
                            col_widths=[4, 5, 3],
                        ))
                        if btn_id not in _registered_link_ids:
                            _registered_link_ids.add(btn_id)
                            _register_link_handler(btn_id, select_id, p.bullpen_pitch_id, p.pitch_number)

                children.append(ui.accordion(ui.accordion_panel(f"Link pitches to Rapsodo data ({len(unlinked_pitches)} not yet linked)", *link_children), open=False, id=None))

            return ui.div(*children)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.bp_session_video_save_btn)
    def _save_session_video():
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return
        link = (input.bp_session_video_link() or "").strip()
        if not link:
            ui.notification_show("Paste a Google Drive link first.", type="error", duration=8)
            return
        if drive_file_id(link) is None:
            ui.notification_show(
                "That doesn't look like a standard Google Drive file link -- it'll still be saved, but it may not "
                "play inline (an \"Open in a new tab\" link will show alongside it either way).",
                type="warning", duration=10,
            )
        db = get_session()
        try:
            active_bullpen = db.query(BullpenSession).filter(BullpenSession.bullpen_id == bullpen_id).first()
            if active_bullpen is None:
                return
            active_bullpen.video_url = link
            db.commit()
            ui.notification_show("Saved session video.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.bp_video_save_btn)
    def _save_pitch_video():
        req("video_pitch_choice" in input)
        pitch_id = int(input.video_pitch_choice())
        files = input.bp_video_upload() if "bp_video_upload" in input else None
        if not files:
            ui.notification_show("Choose a video file first.", type="error", duration=8)
            return
        db = get_session()
        try:
            p = db.query(BullpenPitch).filter(BullpenPitch.bullpen_pitch_id == pitch_id).first()
            if p is None:
                return
            identifier = f"bullpen-{p.bullpen_id}-pitch-{p.pitch_number}"
            url = _upload_pitch_video(files[0], identifier)
            if url:
                p.video_url = url
                db.commit()
                ui.notification_show(f"Saved video for pitch #{p.pitch_number}.", type="message", duration=8)
                _bump_refresh()
        finally:
            db.close()

    def _register_link_handler(btn_id, select_id, bullpen_pitch_id, pitch_number):
        @reactive.effect
        @reactive.event(input[btn_id])
        def _handler():
            chosen_raw = input[select_id]()
            if not chosen_raw:
                return
            db = get_session()
            try:
                p = db.query(BullpenPitch).filter(BullpenPitch.bullpen_pitch_id == bullpen_pitch_id).first()
                if p is None:
                    return
                p.linked_assessment_id = int(chosen_raw)
                db.commit()
                ui.notification_show(f"Linked pitch #{pitch_number}.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

    # -------------------------------------------------------------------
    # Session summary (adapts to bullpen type) + charts
    # -------------------------------------------------------------------

    def _summarize_session(b):
        s_linked = s_hits = 0
        s_hits_by_type, s_counts_by_type, s_velos_by_type, s_movement_by_type = {}, {}, {}, {}
        for pitch in b.pitches:
            pt_name = pitch.pitch_type.type_name if pitch.pitch_type else "—"
            s_counts_by_type[pt_name] = s_counts_by_type.get(pt_name, 0) + 1
            if pitch.linked_assessment:
                s_linked += 1
                results = {r.test_type.test_name: float(r.value) for r in pitch.linked_assessment.results}
                plate_side, plate_height = results.get("Plate Side"), results.get("Plate Height")
                if plate_side is not None and plate_height is not None:
                    a_zone = compute_actual_zone(plate_side, plate_height)
                    if a_zone == pitch.target_zone:
                        s_hits += 1
                        s_hits_by_type[pt_name] = s_hits_by_type.get(pt_name, 0) + 1
                v = results.get("Velocity")
                if v is not None:
                    s_velos_by_type.setdefault(pt_name, []).append(v)
                s_movement_by_type.setdefault(pt_name, []).append(results)
        return {
            "linked": s_linked, "hits": s_hits, "hits_by_type": s_hits_by_type,
            "counts_by_type": s_counts_by_type, "velos_by_type": s_velos_by_type,
            "movement_by_type": s_movement_by_type, "total_pitches": len(b.pitches),
        }

    @render.ui
    def session_summary_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_bullpen = _load_active_bullpen(db, bullpen_id)
            if active_bullpen is None or not active_bullpen.pitches:
                return None

            current_summary = _summarize_session(active_bullpen)
            hits, linked_count = current_summary["hits"], current_summary["linked"]
            hits_by_type, counts_by_type = current_summary["hits_by_type"], current_summary["counts_by_type"]
            bp_type_name = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else ""

            previous_session = (
                db.query(BullpenSession)
                .options(
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.pitch_type),
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.linked_assessment).joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                )
                .filter(
                    BullpenSession.player_id == active_bullpen.player_id,
                    BullpenSession.bullpen_type_id == active_bullpen.bullpen_type_id,
                    BullpenSession.bullpen_id != active_bullpen.bullpen_id,
                    BullpenSession.session_date <= active_bullpen.session_date,
                )
                .order_by(BullpenSession.session_date.desc(), BullpenSession.bullpen_id.desc())
                .first()
            )
            prev_summary = _summarize_session(previous_session) if previous_session else None
            prev_date_label = previous_session.session_date.strftime("%Y-%m-%d (%a)") if previous_session else None

            children = [ui.hr()]

            if bp_type_name == "Command":
                children.append(ui.h5("Execution summary", class_="gbo-section-title"))
                if linked_count == 0:
                    children.append(ui.p("Link pitches to their Rapsodo data (once imported) to see execution %.", class_="text-muted small"))
                else:
                    pct = round(100 * hits / linked_count)
                    cards = [{"label": "Overall execution", "value": f"{hits}/{linked_count}", "delta": f"{pct}%", "delta_positive": True}]
                    if prev_summary and prev_summary["linked"] > 0:
                        prev_pct = round(100 * prev_summary["hits"] / prev_summary["linked"])
                        diff = pct - prev_pct
                        cards[0]["delta"] = f"{pct}% ({diff:+d} pts vs {prev_date_label})"
                        cards[0]["delta_positive"] = diff >= 0
                    children.append(ui_helpers.render_kpi_cards(cards))
                    by_type_lines = "\n\n".join(f"{pt}: {hits_by_type.get(pt, 0)}/{count}" for pt, count in counts_by_type.items())
                    children.append(ui.markdown(f"**By pitch type**\n\n{by_type_lines}"))

            elif bp_type_name == "Velocity":
                children.append(ui.h5("Velocity summary", class_="gbo-section-title"))
                if linked_count == 0:
                    children.append(ui.p("Link pitches to their Rapsodo data (once imported) to see velocity.", class_="text-muted small"))
                else:
                    velos_by_type = {}
                    for p in active_bullpen.pitches:
                        if not p.linked_assessment:
                            continue
                        pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                        v = next((r.value for r in p.linked_assessment.results if r.test_type.test_name == "Velocity"), None)
                        if v is not None:
                            velos_by_type.setdefault(pt_name, []).append(float(v))
                    if not velos_by_type:
                        children.append(ui.p("No velocity data found on the linked pitches yet.", class_="text-muted small"))
                    else:
                        all_velos = [v for vs in velos_by_type.values() for v in vs]
                        avg_velo, max_velo = sum(all_velos) / len(all_velos), max(all_velos)
                        prev_avg_delta = prev_max_delta = None
                        if prev_summary and prev_summary["velos_by_type"]:
                            prev_all = [v for vs in prev_summary["velos_by_type"].values() for v in vs]
                            if prev_all:
                                prev_avg_delta = avg_velo - (sum(prev_all) / len(prev_all))
                                prev_max_delta = max_velo - max(prev_all)
                        cards = [
                            {"label": "Max velocity", "value": f"{max_velo:.1f} mph", "delta": f"{prev_max_delta:+.1f} vs {prev_date_label}" if prev_max_delta is not None else None, "delta_positive": (prev_max_delta or 0) >= 0},
                            {"label": "Average velocity", "value": f"{avg_velo:.1f} mph", "delta": f"{prev_avg_delta:+.1f} vs {prev_date_label}" if prev_avg_delta is not None else None, "delta_positive": (prev_avg_delta or 0) >= 0},
                        ]
                        children.append(ui_helpers.render_kpi_cards(cards))
                        by_type_lines = "\n\n".join(f"{pt}: avg {sum(vs)/len(vs):.1f} mph, max {max(vs):.1f} mph" for pt, vs in velos_by_type.items())
                        children.append(ui.markdown(f"**By pitch type**\n\n{by_type_lines}"))
                        if previous_session and prev_avg_delta is None:
                            children.append(ui.p(f"Previous session ({prev_date_label}) had no velocity data to compare against.", class_="text-muted small"))

            elif bp_type_name == "Pitch Design":
                children.append(ui.h5("Movement summary", class_="gbo-section-title"))
                if linked_count == 0:
                    children.append(ui.p("Link pitches to their Rapsodo data (once imported) to see movement metrics.", class_="text-muted small"))
                else:
                    movement_by_type = current_summary["movement_by_type"]
                    if not movement_by_type:
                        children.append(ui.p("No movement data found on the linked pitches yet.", class_="text-muted small"))
                    else:
                        def _avg_of(entries, key):
                            vals = [e[key] for e in entries if key in e]
                            return round(sum(vals) / len(vals), 1) if vals else None
                        summary_rows = []
                        for pt, entries in movement_by_type.items():
                            row = {"Pitch Type": pt, "Count": len(entries)}
                            prev_entries = prev_summary["movement_by_type"].get(pt) if prev_summary else None
                            for label, key in [
                                ("Avg Spin Rate (rpm)", "Spin Rate"), ("Avg Horizontal Break (in)", "Horizontal Break"),
                                ("Avg Induced Vert. Break (in)", "Induced Vertical Break"), ("Avg Spin Efficiency (%)", "Spin Efficiency"),
                            ]:
                                cur_avg = _avg_of(entries, key)
                                row[label] = cur_avg if cur_avg is not None else "—"
                                if cur_avg is not None and prev_entries:
                                    prev_avg = _avg_of(prev_entries, key)
                                    if prev_avg is not None:
                                        row[f"{label} vs last"] = f"{round(cur_avg - prev_avg, 1):+.1f}"
                            summary_rows.append(row)
                        children.append(ui_helpers.render_dict_table(summary_rows))
                        if previous_session:
                            children.append(ui.p(f'"vs last" compares to the previous {bp_type_name} session on {prev_date_label}.', class_="text-muted small"))

            elif bp_type_name == "Recovery":
                children.append(ui.h5("Session summary", class_="gbo-section-title"))
                children.append(ui.p("Recovery bullpens are lower-intent, feel-focused work -- no grading here, just a pitch count.", class_="text-muted small"))
                delta = len(active_bullpen.pitches) - prev_summary["total_pitches"] if prev_summary else None
                children.append(ui_helpers.render_kpi_cards([{"label": "Total pitches", "value": str(len(active_bullpen.pitches)), "delta": f"{delta:+d} vs {prev_date_label}" if delta is not None else None, "delta_positive": (delta or 0) >= 0}]))
                by_type_lines = "\n\n".join(f"{pt}: {count}" for pt, count in counts_by_type.items())
                children.append(ui.markdown(f"**By pitch type**\n\n{by_type_lines}"))

            else:
                children.append(ui.h5("Session summary", class_="gbo-section-title"))
                delta = len(active_bullpen.pitches) - prev_summary["total_pitches"] if prev_summary else None
                children.append(ui_helpers.render_kpi_cards([{"label": "Total pitches", "value": str(len(active_bullpen.pitches)), "delta": f"{delta:+d} vs {prev_date_label}" if delta is not None else None, "delta_positive": (delta or 0) >= 0}]))
                by_type_lines = "\n\n".join(f"{pt}: {count}" for pt, count in counts_by_type.items())
                children.append(ui.markdown(f"**By pitch type**\n\n{by_type_lines}"))

            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def charts_section():
        _refresh_tick()
        if not _access_ok():
            return None
        bullpen_id = _active_bullpen_id()
        if bullpen_id is None:
            return None

        db = get_session()
        try:
            active_bullpen = _load_active_bullpen(db, bullpen_id)
            if active_bullpen is None or not active_bullpen.pitches:
                return None
            current_summary = _summarize_session(active_bullpen)
            movement_data = current_summary["movement_by_type"]
            has_movement = any("Horizontal Break" in e and "Induced Vertical Break" in e for entries in movement_data.values() for e in entries)
            has_release = any("Release Side" in e and "Release Height" in e for entries in movement_data.values() for e in entries)
            has_location = any("Plate Side" in e and "Plate Height" in e for entries in movement_data.values() for e in entries)
            has_velocity = any(vs for vs in current_summary["velos_by_type"].values())
            if not (has_movement or has_release or has_location or has_velocity):
                return None

            children = [ui.hr(), ui.h5("Charts", class_="gbo-section-title")]
            if has_location:
                children.append(_render_strike_zone_plot("Actual Pitch Locations", movement_data))
                children.append(ui.p("Where pitches actually crossed the plate -- from real Rapsodo Plate Side/Height, not the called intended zone.", class_="text-muted small"))
            children.append(ui.p("Bold labeled markers are the average per pitch type; smaller dots are individual pitches.", class_="text-muted small"))
            if has_movement:
                children.append(_render_scatter_with_averages("Movement Plot", "Horizontal Break (in)", "Induced Vertical Break (in)", movement_data, "Horizontal Break", "Induced Vertical Break"))
            if has_release:
                children.append(_render_scatter_with_averages("Release Point (tunneling)", "Release Side (ft)", "Release Height (ft)", movement_data, "Release Side", "Release Height"))
                children.append(ui.p("Tighter clustering across pitch types here means better tunneling -- harder for a hitter to read pitch type out of the hand.", class_="text-muted small"))
            if has_velocity:
                velo_fig = go.Figure()
                for i, (pt_name, vs) in enumerate(current_summary["velos_by_type"].items()):
                    if not vs:
                        continue
                    color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
                    velo_fig.add_trace(go.Bar(x=[pt_name], y=[sum(vs) / len(vs)], marker_color=color, showlegend=False, name=pt_name, hovertemplate=f"{pt_name}<br>Avg: %{{y:.1f}} mph<extra></extra>"))
                velo_fig.update_layout(
                    title="Average Velocity by Pitch Type", yaxis_title="mph",
                    plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB6C2"),
                    yaxis=dict(gridcolor="#2A3039"), height=380, margin=dict(t=40, b=40, l=40, r=40),
                )
                children.append(chart_helpers.fig_to_img(velo_fig, width=700, height=380))

            return ui.div(*children)
        finally:
            db.close()