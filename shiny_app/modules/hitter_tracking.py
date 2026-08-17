"""
GBO -- Hitter Tracking module.

Direct port of pages/hitter_tracking.py -- live swing-by-swing tracking
sheet, same spirit as Bullpen Tracking but for hitters: pitch type,
location (same 3x3 zone grid + Bury), pitcher hand (always capturable,
even for a BP arm/machine/opponent not on our roster), an optional link
to a specific roster pitcher, a contact-quality grade (Barrel/Solid/
Weak/Miss), where the ball was hit, and a per-hitter zone heatmap
(contact quality by zone, filterable by pitcher hand).

Restricted the mirror-opposite way from Bullpen Tracking: hidden from
Pitching-specialty coaches, visible to Hitting-specialty coaches (plus
Administrator/Head Coach/Sports Scientist/Data Analyst).

The most structurally complex module in this migration batch -- lots of
small render.ui blocks, each existing only to satisfy the "never read an
input from the block that defines it" ordering hazard:
  - hitter_picker -> session_picker (reads selected_hitter_id) -> a
    _sync_active_session_id effect that mirrors session_select's value
    into a LOCAL reactive.Value (_active_session_id) -- the in-page
    replacement for the original's st.query_params["hitter_session_id"]
    round-trip (per the migration plan's translation table: an internal
    reactive.Value stands in for query-param-as-navigation-state here,
    same technique bullpen_dashboard.py uses locally, just without the
    cross-page app_state.deep_link_bullpen_id wrinkle since this never
    needs to be reached from another page).
  - session_lifecycle (new-session form / delete accordion / header)
    reads only the LOCAL _active_session_id, so it doesn't need its own
    split -- the hazard is specifically about `input` (client) values.
  - The swing-logging form has the deepest chain: pitch/hand/roster-
    pitcher picker -> intended-zone grid (reads roster-pitcher choice)
    -> actual-zone grid (no upstream read, its own block only for
    consistency) -> contact-quality picker -> hit-location/notes/submit
    (reads contact-quality choice, since "Miss" hides the hit-location
    field exactly like the original's `if contact_quality_choice !=
    "Miss"`).
  - The two 3x3 zone grids are NOT shinywidgets/plotly click capture --
    they're the original's own plain st.button-per-cell grid, ported
    1:1 as ui.input_action_button-per-cell. Both grids' 20 buttons
    (10 actual + 10 intended, ids ht_zone_btn_0..9 /
    ht_intended_zone_btn_0..9) are a FIXED, known-in-advance set, so
    each gets its own statically-registered @reactive.effect at
    module-server-setup time -- no lazy per-item registration needed
    (that pattern is reserved for a data-dependent, unbounded count of
    buttons, e.g. training_routines.py's per-exercise video-save buttons).
  - "Reset after submit": the original's ht_reset_pending session-state
    flag becomes _bump_refresh() (rebuilds every form-field block fresh
    off the bumped _refresh_tick, wiping transient selections back to
    default) plus explicit _target_zone.set(5)/_intended_zone.set(5)
    for the two custom grids, which _refresh_tick alone can't reset
    since they're plain reactive.Value, not input widgets.
"""

import plotly.graph_objects as go

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, PitchType, HitterTrackingSession, HitterSwing, HitterSessionType
from r2_client import upload_video_to_r2

import ui_helpers
import chart_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")
PITCH_VIDEO_SUBFOLDER = "pitch-videos/"

ZONE_LABELS = {
    0: "Bury (in the dirt)",
    1: "Up-Left", 2: "Up-Middle", 3: "Up-Right",
    4: "Middle-Left", 5: "Middle-Middle", 6: "Middle-Right",
    7: "Down-Left", 8: "Down-Middle", 9: "Down-Right",
}
CONTACT_QUALITY_OPTIONS = ["Barrel", "Solid", "Weak", "Miss"]
CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}
HIT_LOCATION_OPTIONS = ["Left Field", "Left-Center", "Center Field", "Right-Center", "Right Field", "Infield"]
ZONE_GRID_LAYOUT = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]


class _ShinyFileAdapter:
    """Adapts one ui.input_file() entry to the .name/.getvalue()/.type
    shape upload_video_to_r2() expects -- same adapter as
    training_routines.py's, duplicated here per that file's own
    convention (each video-handling module carries its own small
    copy). video_import.py used to carry one too, but that page was
    redesigned to store pasted Google Drive links instead of uploading
    files, so it no longer needs R2 or this adapter."""
    def __init__(self, file_info: dict):
        self.name = file_info["name"]
        self.type = file_info.get("type")
        self._datapath = file_info["datapath"]

    def getvalue(self) -> bytes:
        with open(self._datapath, "rb") as f:
            return f.read()


def _upload_swing_video(file_info: dict, identifier: str):
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


def _compute_zone_scores(swings):
    """Average contact-quality score and count per zone, from a list of
    HitterSwing objects. Miss counts toward the average (score 0) but
    has no hit_location."""
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def _build_zone_heatmap_figure(title, zone_scores, zone_counts, invert_colors=False):
    """3x3 heatmap of average contact-quality score per zone. Green =
    good, red = poor -- inverted for a pitcher-facing view (not used on
    this page, kept for parity with the original's shared helper
    signature in case bullpen_tracking.py's own port wants the mirror
    view later)."""
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_scores.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_scores[zid]:.1f}<br>({zone_counts[zid]})" if zid in zone_scores else "—" for zid in row] for row in zone_grid]

    colorscale = "RdYlGn_r" if invert_colors else "RdYlGn"
    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale=colorscale, zmin=0, zmax=3, showscale=True,
        colorbar=dict(title="Avg score", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380, width=700,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    return fig


def _zone_grid_buttons(prefix, current_zone):
    """The 3x3 + Bury button grid shared by both the actual-location and
    intended-location pickers -- id prefix distinguishes the two sets
    (ht_zone_btn_* / ht_intended_zone_btn_*)."""
    rows = []
    for row in ZONE_GRID_LAYOUT:
        cells = []
        for zone in row:
            is_selected = current_zone == zone
            label = f"● {zone}" if is_selected else str(zone)
            cells.append(ui.input_action_button(f"{prefix}_{zone}", label, class_="w-100"))
        rows.append(ui.layout_columns(*cells))
    bury_selected = current_zone == 0
    bury_label = "● Bury (in the dirt)" if bury_selected else "Bury (in the dirt)"
    rows.append(ui.input_action_button(f"{prefix}_0", bury_label, class_="w-100 mt-1"))
    rows.append(ui.p(f"Selected: {current_zone} ({ZONE_LABELS[current_zone]})", class_="text-muted small"))
    return ui.div(*rows)


@module.ui
def hitter_tracking_ui():
    return ui.div(
        ui_helpers.page_header("Hitter Tracking"),
        ui.output_ui("hitter_picker"),
        ui.output_ui("session_picker"),
        ui.output_ui("session_lifecycle"),
        ui.output_ui("swing_pitch_picker"),
        ui.output_ui("swing_intended_zone_grid"),
        ui.output_ui("swing_actual_zone_grid"),
        ui.output_ui("swing_contact_quality_picker"),
        ui.output_ui("swing_hit_location_and_submit"),
        ui.output_ui("swing_log"),
        ui.output_ui("swing_video_picker"),
        ui.output_ui("swing_video_body"),
        ui.output_ui("heatmap_hand_filter"),
        ui.output_ui("heatmap_body"),
        ui_helpers.page_footer(),
    )


@module.server
def hitter_tracking_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _active_session_id = reactive.Value(None)
    _target_zone = reactive.Value(5)
    _intended_zone = reactive.Value(5)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _access_ok():
        if not app_state.is_authenticated():
            return False
        if app_state.role_name() not in ALLOWED_ROLES:
            return False
        if app_state.role_name() == "Coach" and app_state.coach_specialty() == "Pitching":
            return False
        return True

    def _visible_players(db):
        q = db.query(Player).filter(Player.active.is_(True))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()
            ]
            q = q.filter(Player.player_id.in_(assigned_ids))
        return q.order_by(Player.last_name, Player.first_name).all()

    # --- Statically register all 20 zone-grid button handlers once, at
    # server-setup time -- a fixed, known-in-advance set (unlike
    # training_routines.py's per-exercise video-save buttons), so no
    # lazy registration needed. Default-arg closures capture each loop
    # iteration's zone value correctly. -----------------------------
    def _register_zone_button(button_id, target_value):
        @reactive.effect
        @reactive.event(input[button_id])
        def _handler():
            target_value.set(int(button_id.rsplit("_", 1)[-1]))
        return _handler

    for _zone in range(10):
        _register_zone_button(f"ht_zone_btn_{_zone}", _target_zone)
        _register_zone_button(f"ht_intended_zone_btn_{_zone}", _intended_zone)

    # -------------------------------------------------------------------
    # Hitter + session pickers
    # -------------------------------------------------------------------

    @render.ui
    def hitter_picker():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if not _access_ok():
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            players = _visible_players(db)
            if not players:
                return ui_helpers.empty_state("No players to show yet." if app_state.can_view_all_players() else "No players are currently assigned to you.")
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}
            return ui.input_select("selected_hitter_id", "Hitter", choices=choices)
        finally:
            db.close()

    @render.ui
    def session_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        req("selected_hitter_id" in input)
        selected_hitter_id = int(input.selected_hitter_id())

        db = get_session()
        try:
            hitter = db.query(Player).filter(Player.player_id == selected_hitter_id).first()
            existing_sessions = (
                db.query(HitterTrackingSession)
                .options(joinedload(HitterTrackingSession.session_type))
                .filter(HitterTrackingSession.player_id == selected_hitter_id)
                .order_by(HitterTrackingSession.session_date.desc())
                .all()
            )
            choices = {"": "-- Start a new session --"}
            for s in existing_sessions:
                label = f"{s.session_date.strftime('%Y-%m-%d (%a)')} — {s.session_type.type_name if s.session_type else '—'}"
                if s.label:
                    label += f": {s.label}"
                label += f" ({len(s.swings)} swings)"
                choices[str(s.session_id)] = label

            sessions_by_id = {s.session_id: s for s in existing_sessions}
            current = _active_session_id()
            default_key = str(current) if current in sessions_by_id else ""
            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Sessions — {hitter.first_name} {hitter.last_name}" if hitter else "Sessions")),
                ui.input_select("session_select", "Session", choices=choices, selected=default_key),
            )
        finally:
            db.close()

    @reactive.effect
    def _sync_active_session_id():
        req("session_select" in input)
        raw = input.session_select()
        _active_session_id.set(int(raw) if raw else None)

    # -------------------------------------------------------------------
    # Session lifecycle: start / header / delete
    # -------------------------------------------------------------------

    @render.ui
    def session_lifecycle():
        _refresh_tick()
        if not _access_ok():
            return None
        req("selected_hitter_id" in input)
        selected_hitter_id = int(input.selected_hitter_id())
        active_session_id = _active_session_id()

        db = get_session()
        try:
            if active_session_id is None:
                if not app_state.can_edit_sessions():
                    return ui.p("Your role has read-only access to hitter tracking.", class_="text-muted small")
                session_types = db.query(HitterSessionType).order_by(HitterSessionType.display_order).all()
                if not session_types:
                    return ui.p("No hitter session types set up yet -- run the migration/seed script first.", class_="text-warning")
                return ui.div(
                    ui.input_date("new_session_date", "Date"),
                    ui.input_select("new_session_type", "Type", choices=[t.type_name for t in session_types]),
                    ui.input_text("new_session_label", "Additional detail (optional)", placeholder="e.g. Round 2"),
                    ui.input_text_area("new_session_notes", "Session notes (optional)"),
                    ui.input_action_button("start_session_btn", "Start session", class_="btn-primary mt-2"),
                )

            active_session = db.query(HitterTrackingSession).options(joinedload(HitterTrackingSession.session_type)).filter(HitterTrackingSession.session_id == active_session_id).first()
            if active_session is None or active_session.player_id != selected_hitter_id:
                return None

            title = f"{active_session.session_date.strftime('%Y-%m-%d (%a)')} — {active_session.session_type.type_name if active_session.session_type else '—'}"
            if active_session.label:
                title += f": {active_session.label}"

            sections = [ui.h5(title, class_="gbo-section-title")]
            if active_session.overall_notes:
                sections.append(ui.p(active_session.overall_notes, class_="text-muted small"))

            if app_state.can_edit_sessions():
                sections.append(ui.accordion(
                    ui.accordion_panel(
                        "Delete this session",
                        ui.p(f"This permanently deletes this session and all {len(active_session.swings)} swing(s) logged in it. This can't be undone.", class_="text-warning"),
                        ui.input_checkbox("confirm_delete_ht_session", "Yes, I want to permanently delete this session", value=False),
                        ui.input_action_button("delete_ht_session_btn", "Delete session", class_="btn-danger"),
                    ),
                    open=False, id=None,
                ))
            return ui.div(*sections)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.start_session_btn)
    def _start_session():
        req("selected_hitter_id" in input)
        selected_hitter_id = int(input.selected_hitter_id())
        new_type_choice = input.new_session_type()
        new_date = input.new_session_date()
        new_label = (input.new_session_label() or "").strip()
        overall_notes = (input.new_session_notes() or "").strip()

        db = get_session()
        try:
            session_types = db.query(HitterSessionType).order_by(HitterSessionType.display_order).all()
            new_type_id = next(t.session_type_id for t in session_types if t.type_name == new_type_choice)
            new_ht_session = HitterTrackingSession(
                player_id=selected_hitter_id,
                session_type_id=new_type_id,
                session_date=new_date,
                label=new_label or None,
                overall_notes=overall_notes or None,
                created_by_user_id=app_state.user_id(),
            )
            db.add(new_ht_session)
            db.commit()
            _active_session_id.set(new_ht_session.session_id)
            ui.notification_show(f"Started {new_type_choice} session on {new_date.strftime('%Y-%m-%d (%a)')}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_ht_session_btn)
    def _delete_session():
        if not input.confirm_delete_ht_session():
            return
        active_session_id = _active_session_id()
        if active_session_id is None:
            return
        db = get_session()
        try:
            active_session = db.query(HitterTrackingSession).filter(HitterTrackingSession.session_id == active_session_id).first()
            if active_session is None:
                return
            db.delete(active_session)
            db.commit()
            _active_session_id.set(None)
            ui.notification_show(f"Deleted session #{active_session_id}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Swing logging
    # -------------------------------------------------------------------

    def _can_log_swing():
        return _access_ok() and app_state.can_edit_sessions() and _active_session_id() is not None

    @render.ui
    def swing_pitch_picker():
        _refresh_tick()
        if not _can_log_swing():
            return None
        db = get_session()
        try:
            active_session = db.query(HitterTrackingSession).filter(HitterTrackingSession.session_id == _active_session_id()).first()
            if active_session is None:
                return None
            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            roster_pitchers = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).order_by(Player.last_name, Player.first_name).all()
            roster_pitcher_choices = {"": "-- Not a roster pitcher (BP/machine/opponent) --"}
            for p in roster_pitchers:
                roster_pitcher_choices[str(p.player_id)] = f"{p.first_name} {p.last_name}"

            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Swing #{len(active_session.swings) + 1}")),
                ui.input_select("ht_pitch_type", "Pitch type", choices=[pt.type_name for pt in pitch_types]),
                ui.input_radio_buttons("ht_pitcher_hand", "Pitcher hand", choices=["R", "L"], inline=True),
                ui.input_select("ht_roster_pitcher", "Link to a roster pitcher? (optional)", choices=roster_pitcher_choices),
            )
        finally:
            db.close()

    @render.ui
    def swing_intended_zone_grid():
        _refresh_tick()
        if not _can_log_swing():
            return None
        req("ht_roster_pitcher" in input)
        if not input.ht_roster_pitcher():
            return None
        return ui.div(
            ui.p("Intended zone (what he was aiming for)", class_="text-muted small"),
            _zone_grid_buttons("ht_intended_zone_btn", _intended_zone()),
        )

    @render.ui
    def swing_actual_zone_grid():
        _refresh_tick()
        if not _can_log_swing():
            return None
        return ui.div(
            ui.p("Actual location (where it ended up)", class_="text-muted small"),
            _zone_grid_buttons("ht_zone_btn", _target_zone()),
        )

    @render.ui
    def swing_contact_quality_picker():
        _refresh_tick()
        if not _can_log_swing():
            return None
        return ui.input_select("ht_contact_quality", "Contact quality", choices=["-- Select --"] + CONTACT_QUALITY_OPTIONS)

    @render.ui
    def swing_hit_location_and_submit():
        _refresh_tick()
        if not _can_log_swing():
            return None
        req("ht_contact_quality" in input)
        contact_quality_choice = input.ht_contact_quality()

        children = []
        if contact_quality_choice not in ("-- Select --", "Miss"):
            children.append(ui.input_select("ht_hit_location", "Where was it hit? (optional)", choices=["-- Not specified --"] + HIT_LOCATION_OPTIONS))
        children.append(ui.input_text("ht_swing_notes", "Notes (optional)"))
        children.append(ui.input_action_button("record_swing_btn", "Record swing", class_="btn-primary mt-2"))
        return ui.div(*children)

    @reactive.effect
    @reactive.event(input.record_swing_btn)
    def _record_swing():
        active_session_id = _active_session_id()
        if active_session_id is None:
            return
        contact_quality_choice = input.ht_contact_quality() if "ht_contact_quality" in input else "-- Select --"
        if contact_quality_choice == "-- Select --":
            ui.notification_show("Select a contact quality before recording the swing.", type="error", duration=8)
            return

        pitch_type_choice = input.ht_pitch_type()
        pitcher_hand_choice = input.ht_pitcher_hand()
        roster_pitcher_raw = input.ht_roster_pitcher() if "ht_roster_pitcher" in input else ""
        roster_pitcher_choice = int(roster_pitcher_raw) if roster_pitcher_raw else None
        intended_zone_choice = _intended_zone() if roster_pitcher_choice is not None else None
        hit_location_choice = input.ht_hit_location() if "ht_hit_location" in input else None
        swing_notes = (input.ht_swing_notes() or "").strip() if "ht_swing_notes" in input else ""

        db = get_session()
        try:
            active_session = db.query(HitterTrackingSession).filter(HitterTrackingSession.session_id == active_session_id).first()
            if active_session is None:
                return
            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            pitch_type_id = next(pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_choice)
            swing_number = len(active_session.swings) + 1
            db.add(HitterSwing(
                session_id=active_session_id,
                swing_number=swing_number,
                pitch_type_id=pitch_type_id,
                intended_zone=intended_zone_choice,
                pitch_zone=_target_zone(),
                pitcher_hand=pitcher_hand_choice,
                pitcher_player_id=roster_pitcher_choice,
                contact_quality=contact_quality_choice,
                hit_location=hit_location_choice if hit_location_choice and hit_location_choice != "-- Not specified --" else None,
                notes=swing_notes or None,
            ))
            db.commit()
            ui.notification_show(f"Recorded swing #{swing_number}.", type="message", duration=6)
            _target_zone.set(5)
            _intended_zone.set(5)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Swing log + video
    # -------------------------------------------------------------------

    @render.ui
    def swing_log():
        _refresh_tick()
        if not _access_ok():
            return None
        active_session_id = _active_session_id()
        if active_session_id is None:
            return None
        db = get_session()
        try:
            active_session = db.query(HitterTrackingSession).filter(HitterTrackingSession.session_id == active_session_id).first()
            if active_session is None:
                return None
            if not active_session.swings:
                return ui.div(ui.hr(), ui.p(ui.strong("Swing log")), ui_helpers.empty_state("No swings logged yet for this session."))

            rows = [
                {
                    "#": s.swing_number,
                    "Pitch Type": s.pitch_type.type_name if s.pitch_type else "—",
                    "Intended": f"{s.intended_zone} ({ZONE_LABELS.get(s.intended_zone, '—')})" if s.intended_zone is not None else "—",
                    "Actual": f"{s.pitch_zone} ({ZONE_LABELS.get(s.pitch_zone, '—')})" if s.pitch_zone is not None else "—",
                    "Located": "Yes" if (s.intended_zone is not None and s.pitch_zone is not None and s.intended_zone == s.pitch_zone) else ("No" if s.intended_zone is not None and s.pitch_zone is not None else "—"),
                    "Pitcher Hand": s.pitcher_hand or "—",
                    "Roster Pitcher": f"{s.pitcher_player.first_name} {s.pitcher_player.last_name}" if s.pitcher_player else "—",
                    "Contact": s.contact_quality or "—",
                    "Hit Location": s.hit_location or "—",
                    "Notes": s.notes or "",
                }
                for s in active_session.swings
            ]
            return ui.div(ui.hr(), ui.p(ui.strong("Swing log")), ui_helpers.render_dict_table(rows))
        finally:
            db.close()

    @render.ui
    def swing_video_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        active_session_id = _active_session_id()
        if active_session_id is None:
            return None
        db = get_session()
        try:
            active_session = db.query(HitterTrackingSession).filter(HitterTrackingSession.session_id == active_session_id).first()
            if active_session is None or not active_session.swings:
                return None
            video_count = sum(1 for s in active_session.swings if s.video_url)
            choices = {}
            for s in active_session.swings:
                label = f"Swing #{s.swing_number}"
                if s.pitch_type:
                    label += f" ({s.pitch_type.type_name})"
                if s.contact_quality:
                    label += f" — {s.contact_quality}"
                if s.video_url:
                    label += " (video)"
                choices[str(s.swing_id)] = label
            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Swing video ({video_count} of {len(active_session.swings)} swings have video)")),
                ui.input_select("ht_video_swing_select", "Swing", choices=choices),
            )
        finally:
            db.close()

    @render.ui
    def swing_video_body():
        _refresh_tick()
        if not _access_ok():
            return None
        req("ht_video_swing_select" in input)
        db = get_session()
        try:
            selected_swing = db.query(HitterSwing).filter(HitterSwing.swing_id == int(input.ht_video_swing_select())).first()
            if selected_swing is None:
                return None
            children = []
            if selected_swing.video_url:
                children.append(ui.tags.video(ui.tags.source(src=selected_swing.video_url), controls=True, style="max-width:100%;"))
            if app_state.can_edit_sessions():
                upload_label = "Replace video" if selected_swing.video_url else "Upload video"
                children.append(ui.input_file("ht_video_file", upload_label, accept=[".mp4", ".mov", ".m4v"]))
                children.append(ui.input_action_button("ht_video_save_btn", "Save video", class_="btn-primary mt-2"))
            return ui.div(*children)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.ht_video_save_btn)
    def _save_swing_video():
        req("ht_video_swing_select" in input)
        files = input.ht_video_file() if "ht_video_file" in input else None
        if not files:
            return
        db = get_session()
        try:
            selected_swing = db.query(HitterSwing).filter(HitterSwing.swing_id == int(input.ht_video_swing_select())).first()
            if selected_swing is None:
                return
            identifier = f"hitter-swing-{selected_swing.session_id}-{selected_swing.swing_number}"
            url = _upload_swing_video(files[0], identifier)
            if url:
                selected_swing.video_url = url
                db.commit()
                ui.notification_show(f"Saved video for swing #{selected_swing.swing_number}.", type="message", duration=8)
                _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Zone heatmap (this hitter, all sessions)
    # -------------------------------------------------------------------

    @render.ui
    def heatmap_hand_filter():
        _refresh_tick()
        if not _access_ok():
            return None
        req("selected_hitter_id" in input)
        return ui.div(
            ui.hr(),
            ui.p(ui.strong("Zone heatmap")),
            ui.input_radio_buttons("ht_heatmap_hand_filter", "Filter by pitcher hand", choices=["All", "vs RHP", "vs LHP"], inline=True),
        )

    @render.ui
    def heatmap_body():
        if not _access_ok():
            return None
        req("selected_hitter_id" in input)
        req("ht_heatmap_hand_filter" in input)
        selected_hitter_id = int(input.selected_hitter_id())
        hand_filter = input.ht_heatmap_hand_filter()

        db = get_session()
        try:
            all_swings = (
                db.query(HitterSwing)
                .join(HitterTrackingSession)
                .filter(HitterTrackingSession.player_id == selected_hitter_id)
                .all()
            )
            filtered_swings = all_swings
            if hand_filter == "vs RHP":
                filtered_swings = [s for s in all_swings if s.pitcher_hand == "R"]
            elif hand_filter == "vs LHP":
                filtered_swings = [s for s in all_swings if s.pitcher_hand == "L"]

            if not filtered_swings:
                return ui_helpers.empty_state("No swings logged yet to build a heatmap from.")

            zone_scores, zone_counts = _compute_zone_scores(filtered_swings)
            if not zone_scores:
                return ui_helpers.empty_state("No swings with both a zone and contact quality recorded yet.")

            fig = _build_zone_heatmap_figure(f"Contact quality by zone ({hand_filter})", zone_scores, zone_counts)
            return ui.div(
                chart_helpers.fig_to_img(fig),
                ui.p("Green = best contact (Barrel/Solid), red = weakest (Weak/Miss). Number in parentheses is swing count.", class_="text-muted small"),
            )
        finally:
            db.close()
