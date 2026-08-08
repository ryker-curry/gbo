"""
GBO — Bullpen Tracking.

A real bullpen tracking sheet: pick a pitcher, start a session (typed by
bullpen type -- High Intent Velo, Pitch Design, Execution Focused, Touch
and Feel, Short Box), then log each pitch live with a tap-friendly 3x3
target-zone grid (catcher's-eye view) -- fast enough to use mound-side,
no device needed in the moment.

Once the bullpen's Rapsodo CSV is imported separately (Import Rapsodo
Data page), a pitch here can optionally be linked to its matching
Rapsodo-imported record -- the ACTUAL zone and hit/miss are then computed
from the real Plate Height/Plate Side coordinates, compared against the
intended zone the coach called in real time, rather than a second manual
entry. Logging a pitch only records intent -- Rapsodo determines what
actually happened once linked.

The summary at the bottom adapts to the bullpen type, since different
bullpens are about different things: Execution Focused/Short Box show
zone hit-rate %, High Intent Velo shows a velocity summary, Pitch Design
shows movement/spin metrics, Touch and Feel just shows a simple pitch
count (no grading -- it's lower-intent, feel-focused work).

Zone numbering (catcher's/TV view): 1-2-3 top row, 4-5-6 middle row,
7-8-9 bottom row, left-to-right. Zone boundaries are fixed generic
approximations of the strike zone (not per-batter calibrated) -- good
enough for bullpen command work, not umpire-grade.
"""

import streamlit as st
import uuid
import plotly.graph_objects as go
from datetime import date, datetime
from sqlalchemy.orm import joinedload

from database import get_session
from supabase_client import get_supabase_admin_client
from models import (
    Player, StaffPlayerAssignment, BullpenType, BullpenSession, BullpenPitch,
    PitchType, Assessment, AssessmentCategory, AssessmentResult, PlayerAssignment,
    BullpenScript, HitterSwing,
)
from ui_components import page_header, page_footer, empty_state

page_header("Bullpen Tracking")

PITCH_VIDEO_BUCKET = "pitch-videos"  # reuses the same bucket Pitch Video Review already uses


PITCH_TYPE_COLORS = [
    "#BF1E2D", "#D4AF37", "#4C6EF5", "#37B24D", "#F76707", "#AE3EC9", "#0CA678", "#E64980",
]


def render_scatter_with_averages(title, x_label, y_label, data_by_type, x_key, y_key):
    """A scatter plot showing individual pitches (small, faded) plus a
    bold, labeled average marker per pitch type -- the 'movement plot
    averages' pattern: see the overall shape/cluster per pitch type at a
    glance, with individual points still visible for spread/consistency."""
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
            marker=dict(color=color, size=18, line=dict(color="#FFFDE5", width=2)),
            text=[pitch_type], textposition="top center",
            textfont=dict(color="#FFFDE5", size=12),
            hovertemplate=f"{pitch_type} average<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(
        title=title,
        xaxis_title=x_label, yaxis_title=y_label,
        showlegend=False, height=420,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        margin=dict(t=40, b=40, l=40, r=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_strike_zone_plot(title, data_by_type):
    """Actual pitch locations (real Plate Side/Plate Height from linked
    Rapsodo data) plotted against a drawn strike zone -- Rapsodo's own
    signature visualization. Individual pitches only (no averaging --
    the whole point is seeing the actual spread of locations), colored
    by pitch type, with the 3x3 grid drawn in for reference."""
    fig = go.Figure()

    # Outer zone boundary
    fig.add_shape(type="rect", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1],
                  line=dict(color="#FFFDE5", width=2), fillcolor="rgba(0,0,0,0)")
    # Internal 3x3 grid lines
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
            marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#1E1E1E", width=1)),
            hovertemplate=f"{pitch_type}<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Plate Side (ft)", yaxis_title="Plate Height (ft)",
        showlegend=True, height=480,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[FULL_ZONE_SIDE[0] - 1, FULL_ZONE_SIDE[1] + 1], scaleanchor="y", scaleratio=1),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[0, FULL_ZONE_HEIGHT[1] + 1.5]),
        margin=dict(t=40, b=40, l=40, r=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, use_container_width=True)


CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}


def compute_zone_scores(swings):
    """Average contact-quality score and count per zone, from a list of
    HitterSwing objects."""
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def render_zone_heatmap(title, zone_scores, zone_counts, invert_colors=False, subtitle=None):
    """3x3 heatmap of average contact-quality score per zone. Green =
    good, red = poor -- inverted for the pitcher view, where a LOW
    opponent contact-quality score is what's good for the pitcher."""
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
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)
    if subtitle:
        st.caption(subtitle)


def compute_execution_accuracy(swings):
    """Hit-rate (0-100%) and attempt count per INTENDED zone, from a
    list of HitterSwing objects -- how often, when this pitcher aimed
    for a given zone, did he actually land it (with a hitter in the
    box, live). Different from Bullpen Tracking's own execution % --
    that's bullpen-only, no hitter present; this is specifically the
    live-AB version, from Hitter Tracking swing data."""
    by_zone = {}
    for s in swings:
        if s.intended_zone is None or s.pitch_zone is None:
            continue
        by_zone.setdefault(s.intended_zone, []).append(1 if s.intended_zone == s.pitch_zone else 0)
    rates = {z: 100 * sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return rates, counts


def render_execution_heatmap(title, zone_rates, zone_counts, subtitle=None):
    """3x3 heatmap of hit-rate % per intended zone. Green = high
    accuracy, red = low -- always this direction (unlike the contact-
    quality heatmap, there's no "inverted" case here)."""
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_rates.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_rates[zid]:.0f}%<br>({zone_counts[zid]})" if zid in zone_rates else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn", zmin=0, zmax=100, showscale=True,
        colorbar=dict(title="Hit rate %", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)
    if subtitle:
        st.caption(subtitle)


def upload_pitch_video(uploaded_file, identifier: str):
    try:
        admin_client = get_supabase_admin_client()
        ext = uploaded_file.name.split(".")[-1].lower()
        path = f"{identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        file_bytes = uploaded_file.getvalue()
        admin_client.storage.from_(PITCH_VIDEO_BUCKET).upload(
            path, file_bytes, {"content-type": uploaded_file.type}
        )
        return admin_client.storage.from_(PITCH_VIDEO_BUCKET).get_public_url(path)
    except Exception as e:
        st.error(
            f"Video upload failed: {e}. "
            f"Make sure a public Storage bucket named '{PITCH_VIDEO_BUCKET}' exists in your Supabase project."
        )
        return None

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

if role_name == "Coach" and st.session_state.get("gbo_coach_specialty") == "Hitting":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

# Fixed generic strike-zone boundaries in feet (not per-batter calibrated).
# Plate Side sign convention follows whatever Rapsodo exports -- verify
# left/right reads correctly against real data and adjust if flipped.
ZONE_SIDE_BOUNDS = (-0.283, 0.283)  # left | middle | right column cutoffs
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)  # bottom | middle | top row cutoffs (generic 1.5-3.5 ft zone)
BURY_HEIGHT_THRESHOLD = 1.5  # ft -- below this counts as "buried" (intentionally in the dirt), not just the Down row

# Full strike zone rectangle bounds (feet), derived from the same fixed
# generic per-third boundaries above -- the left/right third width and
# top/bottom third height mirrored out to the zone's outer edges. Used
# by render_strike_zone_plot for the drawn zone boundary.
_SIDE_THIRD = ZONE_SIDE_BOUNDS[1] - ZONE_SIDE_BOUNDS[0]
FULL_ZONE_SIDE = (ZONE_SIDE_BOUNDS[0] - _SIDE_THIRD, ZONE_SIDE_BOUNDS[1] + _SIDE_THIRD)
_HEIGHT_THIRD = ZONE_HEIGHT_BOUNDS[1] - ZONE_HEIGHT_BOUNDS[0]
FULL_ZONE_HEIGHT = (ZONE_HEIGHT_BOUNDS[0] - _HEIGHT_THIRD, ZONE_HEIGHT_BOUNDS[1] + _HEIGHT_THIRD)

# Zone numbers (1-9) are physical field locations and never change.
# Arm-side/glove-side is a pitcher-relative concept (tied to their
# throwing hand), not a viewer-relative one like left/right -- so unlike
# the Pitcher's/Catcher's view toggle (which only affects the on-screen
# button LAYOUT), these labels stay the same regardless of that toggle.
# Zone 0 = Bury, a distinct below-the-zone target (intentionally in the
# dirt) -- not part of the 3x3 in-zone grid, since horizontal placement
# isn't the point of a bury call.
ARM_SIDE_ZONES = {1, 4, 7}  # physical zones on the arm side for a RHP (flipped for a LHP)


def get_zone_labels(throws):
    """Zone labels using arm-side/glove-side terminology. Falls back to
    plain Left/Right if the pitcher's throwing hand isn't on file yet."""
    if throws == "R":
        arm_col, glove_col = "Arm Side", "Glove Side"
    elif throws == "L":
        arm_col, glove_col = "Glove Side", "Arm Side"
    else:
        arm_col, glove_col = "Left", "Right"
    col0_label, col2_label = arm_col, glove_col  # zones {1,4,7}=col0, {3,6,9}=col2 -- see ARM_SIDE_ZONES
    return {
        0: "Bury (in the dirt)",
        1: f"Up-{col0_label}", 2: "Up-Middle", 3: f"Up-{col2_label}",
        4: f"Middle-{col0_label}", 5: "Middle-Middle", 6: f"Middle-{col2_label}",
        7: f"Down-{col0_label}", 8: "Down-Middle", 9: f"Down-{col2_label}",
    }


def compute_actual_zone(plate_side_ft, plate_height_ft):
    """Map real Rapsodo plate coordinates (feet) to a 1-9 zone using the
    fixed generic boundaries above (or 0 if the pitch actually ended up
    buried, regardless of what was called). Values well outside the zone
    still get clamped to the nearest edge zone -- this is about comparing
    intent to result, not flagging balls vs strikes."""
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


session = get_session()
try:
    player_query = session.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    pitchers = player_query.order_by(Player.last_name, Player.first_name).all()

    if not pitchers:
        empty_state("No pitchers to show yet." if can_view_all else "No pitchers are currently assigned to you.")
        page_footer()
        st.stop()

    pitchers_by_id = {p.player_id: p for p in pitchers}
    pitcher_ids_list = list(pitchers_by_id.keys())
    # Explicitly compute the index ourselves (rather than relying only on
    # Streamlit's automatic key-based persistence) as a defensive fallback
    # against this resetting to the first pitcher on rerun.
    default_pitcher_id = st.session_state.get("bp_selected_pitcher_id")
    pitcher_index = pitcher_ids_list.index(default_pitcher_id) if default_pitcher_id in pitcher_ids_list else 0
    selected_pitcher_id = st.selectbox(
        "Pitcher",
        options=pitcher_ids_list,
        index=pitcher_index,
        format_func=lambda pid: f"{pitchers_by_id[pid].first_name} {pitchers_by_id[pid].last_name}",
        key="bp_selected_pitcher_id",
    )
    selected_pitcher = pitchers_by_id[selected_pitcher_id]

    bullpen_types = session.query(BullpenType).order_by(BullpenType.display_order).all()

    st.divider()
    st.subheader(f"Bullpen sessions — {selected_pitcher.first_name} {selected_pitcher.last_name}")

    existing_sessions = (
        session.query(BullpenSession)
        .filter(BullpenSession.player_id == selected_pitcher_id)
        .order_by(BullpenSession.session_date.desc())
        .all()
    )
    sessions_by_id = {b.bullpen_id: b for b in existing_sessions}

    def _session_label(bullpen_id):
        if bullpen_id is None:
            return "-- Start a new bullpen session --"
        b = sessions_by_id[bullpen_id]
        return f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {b.bullpen_type.type_name if b.bullpen_type else '—'} ({len(b.pitches)} pitches)"

    def _set_active_bullpen(bullpen_id):
        """Persist the active session in the URL itself (not just Python
        session_state) -- query params survive reruns unconditionally,
        so this is immune to whatever was causing the Session dropdown
        to keep resetting."""
        if bullpen_id is None:
            st.query_params.pop("bullpen_id", None)
        else:
            st.query_params["bullpen_id"] = str(bullpen_id)
        st.session_state.active_bullpen_id = bullpen_id

    # Source of truth is the URL query param, not session_state alone.
    query_bullpen_id_raw = st.query_params.get("bullpen_id")
    try:
        default_bullpen_id = int(query_bullpen_id_raw) if query_bullpen_id_raw is not None else None
    except ValueError:
        default_bullpen_id = None
    if default_bullpen_id not in sessions_by_id:
        default_bullpen_id = None

    session_option_ids = [None] + list(sessions_by_id.keys())
    session_index = session_option_ids.index(default_bullpen_id) if default_bullpen_id in session_option_ids else 0
    active_bullpen_id = st.selectbox(
        "Session",
        options=session_option_ids,
        index=session_index,
        format_func=_session_label,
        key="bp_session_selectbox",
    )
    if active_bullpen_id != default_bullpen_id:
        _set_active_bullpen(active_bullpen_id)

    active_bullpen = sessions_by_id[active_bullpen_id] if active_bullpen_id is not None else None

    if active_bullpen_id is None and can_edit_sessions:
        # Any prescribed-but-not-yet-tracked Bullpen assignment for this
        # pitcher (from Player Assignments) that isn't already linked to
        # a session -- surfaced here so starting from it carries the
        # date/type over automatically, closing the loop back to
        # "mark as completed" once pitches are logged.
        already_linked_ids = {b.source_assignment_id for b in existing_sessions if b.source_assignment_id}
        pending_bullpen_assignments = (
            session.query(PlayerAssignment)
            .options(joinedload(PlayerAssignment.bullpen_script).joinedload(BullpenScript.pitches))
            .filter(
                PlayerAssignment.player_id == selected_pitcher_id,
                PlayerAssignment.bullpen_type_id.isnot(None),
                PlayerAssignment.completed.is_(False),
            )
            .order_by(PlayerAssignment.scheduled_date.desc())
            .all()
        )
        pending_bullpen_assignments = [a for a in pending_bullpen_assignments if a.assignment_id not in already_linked_ids]

        if pending_bullpen_assignments:
            st.info(f"{selected_pitcher.first_name} has {len(pending_bullpen_assignments)} prescribed bullpen assignment(s) not yet tracked:")
            for a in pending_bullpen_assignments:
                bp_type_name = a.bullpen_type.type_name if a.bullpen_type else "—"
                date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
                label = f"**{bp_type_name}**"
                if a.bullpen_script:
                    label += f" — script: {a.bullpen_script.script_name}"
                label += f" — {date_label}" + (f" — _{a.notes}_" if a.notes else "")
                col1, col2 = st.columns([3, 1])
                col1.markdown(label)
                if col2.button("Start this bullpen", key=f"start_from_assignment_{a.assignment_id}"):
                    new_bullpen = BullpenSession(
                        player_id=selected_pitcher_id,
                        bullpen_type_id=a.bullpen_type_id,
                        source_assignment_id=a.assignment_id,
                        session_date=a.scheduled_date,
                        created_by_user_id=current_user_id,
                    )
                    session.add(new_bullpen)
                    session.flush()  # assigns new_bullpen.bullpen_id without a full commit yet

                    pitches_loaded = 0
                    if a.bullpen_script:
                        for sp in a.bullpen_script.pitches:
                            session.add(BullpenPitch(
                                bullpen_id=new_bullpen.bullpen_id,
                                pitch_number=sp.pitch_number,
                                pitch_type_id=sp.pitch_type_id,
                                target_zone=sp.target_zone,
                                notes=sp.notes,
                            ))
                            pitches_loaded += 1

                    session.commit()
                    _set_active_bullpen(new_bullpen.bullpen_id)
                    msg = f"Started {bp_type_name} bullpen for {selected_pitcher.first_name}."
                    if pitches_loaded:
                        msg += f" Loaded {pitches_loaded} planned pitch(es) from {a.bullpen_script.script_name}."
                    st.success(msg)
                    st.rerun()
            st.divider()

        st.caption("Or start a bullpen that wasn't pre-assigned:")

        # Type selection lives outside the form so the script picker
        # below can filter by it -- widgets inside st.form don't rerun
        # the app until submit, so this couldn't update reactively there.
        new_type_choice = st.selectbox("Bullpen type", [t.type_name for t in bullpen_types], key="new_bullpen_type_choice")
        new_type_id = next(t.bullpen_type_id for t in bullpen_types if t.type_name == new_type_choice)
        matching_scripts = (
            session.query(BullpenScript)
            .options(joinedload(BullpenScript.pitches))
            .filter(BullpenScript.bullpen_type_id == new_type_id)
            .order_by(BullpenScript.script_name)
            .all()
        )

        with st.form("new_bullpen_form"):
            new_date = st.date_input("Date", value=date.today())
            script_choice = None
            if matching_scripts:
                scripts_by_id = {s.script_id: s for s in matching_scripts}
                script_choice = st.selectbox(
                    "Load a script (optional)",
                    options=[None] + list(scripts_by_id.keys()),
                    format_func=lambda sid: "-- No script, start blank --" if sid is None else f"{scripts_by_id[sid].script_name} ({len(scripts_by_id[sid].pitches)} pitches)",
                )
            elif can_edit_sessions:
                st.caption(f"No {new_type_choice} scripts saved yet -- build one on Bullpen Scripts first if you want to pre-load a planned sequence.")
            overall_notes = st.text_area("Session notes (optional)")
            new_bullpen_submitted = st.form_submit_button("Start bullpen session", type="primary")

        if new_bullpen_submitted:
            new_bullpen = BullpenSession(
                player_id=selected_pitcher_id,
                bullpen_type_id=new_type_id,
                session_date=new_date,
                overall_notes=overall_notes.strip() or None,
                created_by_user_id=current_user_id,
            )
            session.add(new_bullpen)
            session.flush()  # assigns new_bullpen.bullpen_id without a full commit yet

            pitches_loaded = 0
            if script_choice is not None:
                script = scripts_by_id[script_choice]
                for sp in script.pitches:
                    session.add(BullpenPitch(
                        bullpen_id=new_bullpen.bullpen_id,
                        pitch_number=sp.pitch_number,
                        pitch_type_id=sp.pitch_type_id,
                        target_zone=sp.target_zone,
                        notes=sp.notes,
                    ))
                    pitches_loaded += 1

            session.commit()
            _set_active_bullpen(new_bullpen.bullpen_id)
            msg = f"Started {new_type_choice} bullpen for {selected_pitcher.first_name} on {new_date.strftime('%Y-%m-%d (%a)')}."
            if pitches_loaded:
                msg += f" Loaded {pitches_loaded} planned pitch(es) from the script -- link them to Rapsodo data once that day's CSV is imported."
            st.success(msg)
            st.rerun()
    elif active_bullpen_id is None:
        st.info("Your role has read-only access to bullpen tracking.")

    if active_bullpen:
        st.divider()
        type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"
        st.markdown(f"### {type_label} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')}")
        if active_bullpen.overall_notes:
            st.caption(active_bullpen.overall_notes)

        if can_edit_sessions:
            with st.expander("Delete this session"):
                st.warning(f"This permanently deletes this bullpen session and all {len(active_bullpen.pitches)} pitch(es) logged in it. This can't be undone.")
                confirm_delete = st.checkbox("Yes, I want to permanently delete this session", key=f"confirm_delete_{active_bullpen.bullpen_id}")
                if st.button("Delete session", key=f"delete_bullpen_{active_bullpen.bullpen_id}", disabled=not confirm_delete, type="primary"):
                    deleted_id = active_bullpen.bullpen_id
                    session.delete(active_bullpen)
                    session.commit()
                    st.query_params.pop("bullpen_id", None)
                    st.session_state.active_bullpen_id = None
                    st.success(f"Deleted bullpen session #{deleted_id}.")
                    st.rerun()

        if active_bullpen.source_assignment and can_edit_sessions:
            if active_bullpen.source_assignment.completed:
                st.caption("Source assignment already marked completed.")
            elif active_bullpen.pitches:
                if st.button("Mark source assignment as completed", key="complete_source_assignment", type="primary"):
                    active_bullpen.source_assignment.completed = True
                    active_bullpen.source_assignment.completed_notes = f"Tracked in Bullpen Tracking — {len(active_bullpen.pitches)} pitches logged."
                    active_bullpen.source_assignment.completed_at = datetime.utcnow()
                    session.commit()
                    st.success("Marked the source assignment as completed.")
                    st.rerun()
            else:
                st.caption("This bullpen came from a prescribed assignment — log at least one pitch to mark it completed.")

        pitch_types = session.query(PitchType).order_by(PitchType.pitch_type_id).all()

        if "bp_zone_view" not in st.session_state:
            st.session_state.bp_zone_view = "Pitcher's view"
        zone_view = st.radio("Grid perspective", ["Pitcher's view", "Catcher's view"], key="bp_zone_view", horizontal=True)
        zone_labels = get_zone_labels(selected_pitcher.throws)

        # --- Record the next pitch's intent (not a result -- Rapsodo determines what actually happened) ---
        if can_edit_sessions:
            st.subheader(f"Pitch #{len(active_bullpen.pitches) + 1} — call the intent")

            # Apply any pending reset to defaults (set by the previous
            # pitch's save, below) here -- BEFORE these widgets are
            # created this run. Streamlit disallows writing to a widget's
            # session_state key after that widget already exists for the
            # run, so the actual write has to happen on the run before
            # the widget is (re)instantiated, not right after saving.
            if st.session_state.get("bp_reset_pending"):
                st.session_state.bp_pitch_type = "4-Seam Fastball"
                st.session_state.bp_target_zone = 5
                st.session_state.bp_reset_pending = False

            pitch_type_choice = st.selectbox("Pitch type", [pt.type_name for pt in pitch_types], key="bp_pitch_type")

            st.caption(f"Intended zone ({zone_view.lower()})")
            if "bp_target_zone" not in st.session_state:
                st.session_state.bp_target_zone = 5
            # Zone numbers are physical field locations and stay fixed;
            # only the on-screen row order mirrors for pitcher's view,
            # since left/right flip depending on which way you're facing.
            catcher_zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
            zone_layout = catcher_zone_layout if zone_view == "Catcher's view" else [list(reversed(row)) for row in catcher_zone_layout]
            for row in zone_layout:
                cols = st.columns(3)
                for i, zone in enumerate(row):
                    is_selected = st.session_state.bp_target_zone == zone
                    label = f"● {zone}" if is_selected else str(zone)
                    if cols[i].button(label, key=f"zone_btn_{zone}", use_container_width=True):
                        st.session_state.bp_target_zone = zone
                        st.rerun()
            bury_selected = st.session_state.bp_target_zone == 0
            bury_label = "● Bury (in the dirt)" if bury_selected else "Bury (in the dirt)"
            if st.button(bury_label, key="zone_btn_bury", use_container_width=True):
                st.session_state.bp_target_zone = 0
                st.rerun()
            st.caption(f"Selected intended zone: {st.session_state.bp_target_zone} ({zone_labels[st.session_state.bp_target_zone]})")

            # Rapsodo pitches from the same pitcher/date, for optional linking
            category = session.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
            same_day_pitches = []
            if category:
                same_day_pitches = (
                    session.query(Assessment)
                    .options(joinedload(Assessment.pitch_type))
                    .filter(
                        Assessment.player_id == selected_pitcher_id,
                        Assessment.category_id == category.category_id,
                        Assessment.assessment_date == active_bullpen.session_date,
                    )
                    .order_by(Assessment.assessment_id)
                    .all()
                )

            with st.form("bullpen_pitch_form"):
                linked_choice = None
                if same_day_pitches:
                    pitches_by_id = {a.assessment_id: a for a in same_day_pitches}

                    def _pitch_label(aid):
                        a = pitches_by_id[aid]
                        velo = next((r.value for r in a.results if r.test_type.test_name == "Velocity"), None)
                        label = f"Pitch #{aid}" + (f" — {float(velo):.1f} mph" if velo is not None else "")
                        rapsodo_pt_name = a.pitch_type.type_name if a.pitch_type else None
                        if rapsodo_pt_name and rapsodo_pt_name != pitch_type_choice:
                            label += f" [mismatch: {rapsodo_pt_name}, not {pitch_type_choice}]"
                        return label

                    linked_choice = st.selectbox(
                        "Link to Rapsodo pitch (optional, once imported)",
                        options=[None] + list(pitches_by_id.keys()),
                        format_func=lambda aid: "-- Not linked --" if aid is None else _pitch_label(aid),
                    )
                else:
                    st.caption("No Rapsodo pitches imported yet for this pitcher on this date -- you can link one later once imported.")
                pitch_notes = st.text_input("Notes (optional)")
                log_submitted = st.form_submit_button("Record intended pitch", type="primary")

            if log_submitted:
                pitch_type_id = next(pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_choice)
                session.add(BullpenPitch(
                    bullpen_id=active_bullpen.bullpen_id,
                    pitch_number=len(active_bullpen.pitches) + 1,
                    pitch_type_id=pitch_type_id,
                    target_zone=st.session_state.bp_target_zone,
                    linked_assessment_id=linked_choice,
                    notes=pitch_notes.strip() or None,
                ))
                session.commit()
                # Flag the reset for next run -- can't write directly to
                # these widgets' session_state keys here since they've
                # already been instantiated this run (see the check
                # right before the Pitch type widget above).
                st.session_state.bp_reset_pending = True
                st.success(f"Recorded intent for pitch #{len(active_bullpen.pitches) + 1}.")
                st.rerun()

        # --- Pitch log + execution summary ---
        st.divider()
        st.subheader("Pitch log")
        if not active_bullpen.pitches:
            empty_state("No pitches logged yet for this session.")
        else:
            rows = []
            hits = 0
            hits_by_type = {}
            counts_by_type = {}
            for p in active_bullpen.pitches:
                pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                actual_zone = None
                hit_target = None
                if p.linked_assessment:
                    plate_side = next((r.value for r in p.linked_assessment.results if r.test_type.test_name == "Plate Side"), None)
                    plate_height = next((r.value for r in p.linked_assessment.results if r.test_type.test_name == "Plate Height"), None)
                    if plate_side is not None and plate_height is not None:
                        actual_zone = compute_actual_zone(float(plate_side), float(plate_height))
                        hit_target = (actual_zone == p.target_zone)

                counts_by_type[pt_name] = counts_by_type.get(pt_name, 0) + 1
                if hit_target is True:
                    hits += 1
                    hits_by_type[pt_name] = hits_by_type.get(pt_name, 0) + 1

                rows.append({
                    "#": p.pitch_number,
                    "Pitch Type": pt_name,
                    "Intended Zone": f"{p.target_zone} ({zone_labels.get(p.target_zone, '—')})" if p.target_zone is not None else "—",
                    "Actual": f"{actual_zone} ({zone_labels.get(actual_zone, '—')})" if actual_zone is not None else "Not linked yet",
                    "Hit Target": "Yes" if hit_target is True else ("No" if hit_target is False else "—"),
                    "Notes": p.notes or "",
                })

            st.dataframe(rows, use_container_width=True, hide_index=True)

            # --- Pitch video (release/mechanics review) ---
            with st.expander(f"Pitch video ({sum(1 for p in active_bullpen.pitches if p.video_url)} of {len(active_bullpen.pitches)} pitches have video)"):
                video_pitches_by_id = {p.bullpen_pitch_id: p for p in active_bullpen.pitches}
                video_pitch_id = st.selectbox(
                    "Pitch",
                    options=list(video_pitches_by_id.keys()),
                    format_func=lambda pid: f"Pitch #{video_pitches_by_id[pid].pitch_number}"
                    + (f" ({video_pitches_by_id[pid].pitch_type.type_name})" if video_pitches_by_id[pid].pitch_type else "")
                    + (" (video)" if video_pitches_by_id[pid].video_url else ""),
                    key="video_pitch_choice",
                )
                selected_video_pitch = video_pitches_by_id[video_pitch_id]

                if selected_video_pitch.video_url:
                    st.video(selected_video_pitch.video_url)

                if can_edit_sessions:
                    upload_label = "Replace video" if selected_video_pitch.video_url else "Upload video"
                    video_file = st.file_uploader(upload_label, type=["mp4", "mov", "m4v"], key=f"bp_video_upload_{selected_video_pitch.bullpen_pitch_id}")
                    if video_file is not None and st.button("Save video", key=f"bp_video_save_{selected_video_pitch.bullpen_pitch_id}", type="primary"):
                        identifier = f"bullpen-{active_bullpen.bullpen_id}-pitch-{selected_video_pitch.pitch_number}"
                        url = upload_pitch_video(video_file, identifier)
                        if url:
                            selected_video_pitch.video_url = url
                            session.commit()
                            st.success(f"Saved video for pitch #{selected_video_pitch.pitch_number}.")
                            st.rerun()

            # --- Link already-logged pitches to Rapsodo data, once imported ---
            unlinked_pitches = [p for p in active_bullpen.pitches if p.linked_assessment_id is None]
            if unlinked_pitches and can_edit_sessions:
                category = session.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
                same_day_pitches_post = []
                if category:
                    same_day_pitches_post = (
                        session.query(Assessment)
                        .options(joinedload(Assessment.pitch_type))
                        .filter(
                            Assessment.player_id == selected_pitcher_id,
                            Assessment.category_id == category.category_id,
                            Assessment.assessment_date == active_bullpen.session_date,
                        )
                        .order_by(Assessment.assessment_id)
                        .all()
                    )

                with st.expander(f"Link pitches to Rapsodo data ({len(unlinked_pitches)} not yet linked)"):
                    if not same_day_pitches_post:
                        st.caption("No Rapsodo pitches imported yet for this pitcher on this date. Import the CSV on the Import Rapsodo Data page, then come back here to link them.")
                    else:
                        # Safeguard 1: count comparison, so a mismatch is
                        # obvious before any linking happens.
                        already_linked_ids = {p.linked_assessment_id for p in active_bullpen.pitches if p.linked_assessment_id}
                        available_rapsodo = [a for a in same_day_pitches_post if a.assessment_id not in already_linked_ids]
                        total_bullpen = len(active_bullpen.pitches)
                        total_rapsodo = len(same_day_pitches_post)
                        if total_bullpen != total_rapsodo:
                            st.warning(f"{total_bullpen} bullpen pitches logged vs. {total_rapsodo} Rapsodo pitches imported for this date -- counts don't match. Check for extra warm-up throws or a missed rep before linking.")
                        else:
                            st.caption(f"{total_bullpen} bullpen pitches logged, {total_rapsodo} Rapsodo pitches imported -- counts match.")

                        post_pitches_by_id = {a.assessment_id: a for a in same_day_pitches_post}

                        def _post_pitch_label(aid, bullpen_pitch_type_name):
                            a = post_pitches_by_id[aid]
                            velo = next((r.value for r in a.results if r.test_type.test_name == "Velocity"), None)
                            label = f"Pitch #{aid}" + (f" — {float(velo):.1f} mph" if velo is not None else "")
                            rapsodo_pt_name = a.pitch_type.type_name if a.pitch_type else None
                            if rapsodo_pt_name and rapsodo_pt_name != bullpen_pitch_type_name:
                                label += f" [mismatch: {rapsodo_pt_name}, not {bullpen_pitch_type_name}]"
                            return label

                        # Safeguard 3: default each unlinked bullpen pitch to
                        # the same-position available Rapsodo pitch, assuming
                        # matching chronological order -- coach can override.
                        unlinked_sorted = sorted(unlinked_pitches, key=lambda p: p.pitch_number)
                        for idx, p in enumerate(unlinked_sorted):
                            pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                            suggested_aid = available_rapsodo[idx].assessment_id if idx < len(available_rapsodo) else None
                            options = list(post_pitches_by_id.keys())
                            default_index = options.index(suggested_aid) if suggested_aid in options else 0

                            col1, col2, col3 = st.columns([2, 3, 1])
                            col1.markdown(f"Pitch #{p.pitch_number} ({pt_name})")
                            link_choice = col2.selectbox(
                                " ",
                                options=options,
                                index=default_index,
                                format_func=lambda aid, pt=pt_name: _post_pitch_label(aid, pt),
                                key=f"link_choice_{p.bullpen_pitch_id}",
                                label_visibility="collapsed",
                            )
                            # Safeguard 2: explicit warning if the selected
                            # Rapsodo pitch's own type doesn't match what was
                            # called for this bullpen pitch.
                            chosen = post_pitches_by_id[link_choice]
                            chosen_pt_name = chosen.pitch_type.type_name if chosen.pitch_type else None
                            if chosen_pt_name and chosen_pt_name != pt_name:
                                st.warning(f"Selected Rapsodo pitch is a {chosen_pt_name}, but this bullpen pitch was called as {pt_name}. Double-check before linking.")
                            if col3.button("Link", key=f"link_btn_{p.bullpen_pitch_id}"):
                                p.linked_assessment_id = link_choice
                                session.commit()
                                st.success(f"Linked pitch #{p.pitch_number}.")
                                st.rerun()

            def _summarize_session(b):
                """Compute the same aggregate metrics for any bullpen
                session -- reused for both the current session and the
                previous one, so comparisons are apples-to-apples."""
                s_linked = 0
                s_hits = 0
                s_hits_by_type = {}
                s_counts_by_type = {}
                s_velos_by_type = {}
                s_movement_by_type = {}
                for pitch in b.pitches:
                    pt_name = pitch.pitch_type.type_name if pitch.pitch_type else "—"
                    s_counts_by_type[pt_name] = s_counts_by_type.get(pt_name, 0) + 1
                    if pitch.linked_assessment:
                        s_linked += 1
                        results = {r.test_type.test_name: float(r.value) for r in pitch.linked_assessment.results}
                        plate_side = results.get("Plate Side")
                        plate_height = results.get("Plate Height")
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

            linked_count = sum(1 for p in active_bullpen.pitches if p.linked_assessment)
            st.divider()

            bp_type_name = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else ""

            # Most recent PRIOR session of the same type for this pitcher,
            # for a same-type-to-same-type comparison (an Execution Focused
            # session isn't a fair comparison against a Touch and Feel one).
            previous_session = (
                session.query(BullpenSession)
                .options(
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.pitch_type),
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.linked_assessment).joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                )
                .filter(
                    BullpenSession.player_id == selected_pitcher_id,
                    BullpenSession.bullpen_type_id == active_bullpen.bullpen_type_id,
                    BullpenSession.bullpen_id != active_bullpen.bullpen_id,
                    BullpenSession.session_date <= active_bullpen.session_date,
                )
                .order_by(BullpenSession.session_date.desc(), BullpenSession.bullpen_id.desc())
                .first()
            )
            prev_summary = _summarize_session(previous_session) if previous_session else None
            prev_date_label = previous_session.session_date.strftime("%Y-%m-%d (%a)") if previous_session else None
            current_summary = _summarize_session(active_bullpen)

            if bp_type_name in ("Execution Focused", "Short Box"):
                st.subheader("Execution summary")
                if linked_count == 0:
                    st.caption("Link pitches to their Rapsodo data (once imported) to see execution %.")
                else:
                    pct = round(100 * hits / linked_count)
                    delta = None
                    if prev_summary and prev_summary["linked"] > 0:
                        prev_pct = round(100 * prev_summary["hits"] / prev_summary["linked"])
                        delta = f"{pct - prev_pct:+d} pts vs {prev_date_label}"
                    c1, c2 = st.columns(2)
                    c1.metric("Overall execution", f"{hits}/{linked_count}", f"{pct}%")
                    if delta:
                        c1.caption(f"{'▲' if pct - prev_pct >= 0 else '▼'} {delta}")
                    elif previous_session:
                        c1.caption(f"Previous session ({prev_date_label}) had no linked pitches to compare against.")
                    by_type_lines = [f"{pt}: {hits_by_type.get(pt, 0)}/{count}" for pt, count in counts_by_type.items()]
                    c2.markdown("**By pitch type**\n\n" + "\n\n".join(by_type_lines))

            elif bp_type_name == "High Intent Velo":
                st.subheader("Velocity summary")
                if linked_count == 0:
                    st.caption("Link pitches to their Rapsodo data (once imported) to see velocity.")
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
                        st.caption("No velocity data found on the linked pitches yet.")
                    else:
                        all_velos = [v for vs in velos_by_type.values() for v in vs]
                        avg_velo = sum(all_velos) / len(all_velos)
                        max_velo = max(all_velos)

                        prev_avg_delta = prev_max_delta = None
                        if prev_summary and prev_summary["velos_by_type"]:
                            prev_all = [v for vs in prev_summary["velos_by_type"].values() for v in vs]
                            if prev_all:
                                prev_avg_delta = avg_velo - (sum(prev_all) / len(prev_all))
                                prev_max_delta = max_velo - max(prev_all)

                        c1, c2 = st.columns(2)
                        c1.metric("Max velocity", f"{max_velo:.1f} mph", f"{prev_max_delta:+.1f} vs {prev_date_label}" if prev_max_delta is not None else None)
                        c1.metric("Average velocity", f"{avg_velo:.1f} mph", f"{prev_avg_delta:+.1f} vs {prev_date_label}" if prev_avg_delta is not None else None)
                        by_type_lines = [f"{pt}: avg {sum(vs)/len(vs):.1f} mph, max {max(vs):.1f} mph" for pt, vs in velos_by_type.items()]
                        c2.markdown("**By pitch type**\n\n" + "\n\n".join(by_type_lines))
                        if previous_session and prev_avg_delta is None:
                            st.caption(f"Previous session ({prev_date_label}) had no velocity data to compare against.")

            elif bp_type_name == "Pitch Design":
                st.subheader("Movement summary")
                if linked_count == 0:
                    st.caption("Link pitches to their Rapsodo data (once imported) to see movement metrics.")
                else:
                    movement_by_type = {}
                    for p in active_bullpen.pitches:
                        if not p.linked_assessment:
                            continue
                        pt_name = p.pitch_type.type_name if p.pitch_type else "—"
                        results = {r.test_type.test_name: float(r.value) for r in p.linked_assessment.results}
                        movement_by_type.setdefault(pt_name, []).append(results)
                    if not movement_by_type:
                        st.caption("No movement data found on the linked pitches yet.")
                    else:
                        def _avg_of(entries, key):
                            vals = [e[key] for e in entries if key in e]
                            return round(sum(vals) / len(vals), 1) if vals else None

                        summary_rows = []
                        for pt, entries in movement_by_type.items():
                            row = {"Pitch Type": pt, "Count": len(entries)}
                            prev_entries = prev_summary["movement_by_type"].get(pt) if prev_summary else None
                            for label, key in [
                                ("Avg Spin Rate (rpm)", "Spin Rate"),
                                ("Avg Horizontal Break (in)", "Horizontal Break"),
                                ("Avg Induced Vert. Break (in)", "Induced Vertical Break"),
                                ("Avg Spin Efficiency (%)", "Spin Efficiency"),
                            ]:
                                cur_avg = _avg_of(entries, key)
                                row[label] = cur_avg if cur_avg is not None else "—"
                                if cur_avg is not None and prev_entries:
                                    prev_avg = _avg_of(prev_entries, key)
                                    if prev_avg is not None:
                                        diff = round(cur_avg - prev_avg, 1)
                                        row[f"{label} vs last"] = f"{diff:+.1f}"
                            summary_rows.append(row)
                        st.dataframe(summary_rows, use_container_width=True, hide_index=True)
                        if previous_session:
                            st.caption(f"\"vs last\" compares to the previous {bp_type_name} session on {prev_date_label}.")

            elif bp_type_name == "Touch and Feel":
                st.subheader("Session summary")
                st.caption("Touch and Feel bullpens are lower-intent, feel-focused work -- no grading here, just a pitch count.")
                c1, c2 = st.columns(2)
                delta = len(active_bullpen.pitches) - prev_summary["total_pitches"] if prev_summary else None
                c1.metric("Total pitches", len(active_bullpen.pitches), f"{delta:+d} vs {prev_date_label}" if delta is not None else None)
                by_type_lines = [f"{pt}: {count}" for pt, count in counts_by_type.items()]
                c2.markdown("**By pitch type**\n\n" + "\n\n".join(by_type_lines))

            else:
                st.subheader("Session summary")
                c1, c2 = st.columns(2)
                delta = len(active_bullpen.pitches) - prev_summary["total_pitches"] if prev_summary else None
                c1.metric("Total pitches", len(active_bullpen.pitches), f"{delta:+d} vs {prev_date_label}" if delta is not None else None)
                by_type_lines = [f"{pt}: {count}" for pt, count in counts_by_type.items()]
                c2.markdown("**By pitch type**\n\n" + "\n\n".join(by_type_lines))

            # --- Charts (shared across all bullpen types -- shown whenever
            # linked Rapsodo data has the relevant metrics, regardless of
            # which type this session is, since movement/release
            # consistency and velocity are useful context either way) ---
            movement_data = current_summary["movement_by_type"]
            has_movement = any("Horizontal Break" in e and "Induced Vertical Break" in e for entries in movement_data.values() for e in entries)
            has_release = any("Release Side" in e and "Release Height" in e for entries in movement_data.values() for e in entries)
            has_location = any("Plate Side" in e and "Plate Height" in e for entries in movement_data.values() for e in entries)
            has_velocity = any(vs for vs in current_summary["velos_by_type"].values())

            if has_movement or has_release or has_location or has_velocity:
                st.divider()
                st.subheader("Charts")

                if has_location:
                    render_strike_zone_plot("Actual Pitch Locations", movement_data)
                    st.caption("Where pitches actually crossed the plate -- from real Rapsodo Plate Side/Height, not the called intended zone.")

                st.caption("Bold labeled markers are the average per pitch type; smaller dots are individual pitches.")
                if has_movement:
                    render_scatter_with_averages(
                        "Movement Plot", "Horizontal Break (in)", "Induced Vertical Break (in)",
                        movement_data, "Horizontal Break", "Induced Vertical Break",
                    )
                if has_release:
                    render_scatter_with_averages(
                        "Release Point (tunneling)", "Release Side (ft)", "Release Height (ft)",
                        movement_data, "Release Side", "Release Height",
                    )
                    st.caption("Tighter clustering across pitch types here means better tunneling -- harder for a hitter to read pitch type out of the hand.")
                if has_velocity:
                    velo_fig = go.Figure()
                    for i, (pt_name, vs) in enumerate(current_summary["velos_by_type"].items()):
                        if not vs:
                            continue
                        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
                        velo_fig.add_trace(go.Bar(x=[pt_name], y=[sum(vs) / len(vs)], marker_color=color, showlegend=False, name=pt_name,
                                                   hovertemplate=f"{pt_name}<br>Avg: %{{y:.1f}} mph<extra></extra>"))
                    velo_fig.update_layout(
                        title="Average Velocity by Pitch Type", yaxis_title="mph",
                        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E", font=dict(color="#FFFDE5"),
                        yaxis=dict(gridcolor="#3A3A3A"), height=380, margin=dict(t=40, b=40, l=40, r=40),
                    )
                    st.plotly_chart(velo_fig, use_container_width=True)

    # --- This pitcher's zone heatmap: where opponents do damage,
    # from every logged Hitter Tracking swing against him, any hitter.
    # Shown here on his own page (Bullpen Tracking) since that's where
    # a coach reviewing this specific pitcher already is -- the source
    # data necessarily comes from hitter outcomes (there's no other way
    # to know where he gets hit hard), but this isn't a hitter-tracking
    # feature, it's his own page. Not tied to a specific bullpen
    # session -- always shown for whichever pitcher is selected above. ---
    st.divider()
    st.subheader(f"{selected_pitcher.first_name} {selected_pitcher.last_name}'s zone heatmap")
    st.caption("Where opponents do damage against him -- contact quality by zone, from every logged Hitter Tracking swing against him, any hitter.")
    pitcher_swings = (
        session.query(HitterSwing)
        .filter(HitterSwing.pitcher_player_id == selected_pitcher_id)
        .all()
    )
    if not pitcher_swings:
        empty_state("No swings logged against this pitcher yet on Hitter Tracking.")
    else:
        pitcher_zone_scores, pitcher_zone_counts = compute_zone_scores(pitcher_swings)
        if not pitcher_zone_scores:
            empty_state("No swings with both a zone and contact quality recorded against this pitcher yet.")
        else:
            render_zone_heatmap(
                "Opponent contact quality by zone", pitcher_zone_scores, pitcher_zone_counts, invert_colors=True,
                subtitle="Green = pitches hardest to hit here (good for him), red = hit hardest here. Number in parentheses is swing count.",
            )

        # --- Live execution accuracy: intended zone vs. actual zone,
        # with a hitter in the box -- distinct from the bullpen's own
        # execution % (which has no hitter present at all). ---
        st.divider()
        st.caption(f"How well {selected_pitcher.first_name} executes to his intended locations with a hitter in the box (from Hitter Tracking).")
        exec_rates, exec_counts = compute_execution_accuracy(pitcher_swings)
        if not exec_rates:
            empty_state("No swings with both an intended and actual zone recorded for this pitcher yet.")
        else:
            render_execution_heatmap(
                "Live execution accuracy by intended zone", exec_rates, exec_counts,
                subtitle="Green = hits his spot most often when he aims here, red = misses most often. Number in parentheses is attempt count.",
            )

finally:
    session.close()

page_footer()