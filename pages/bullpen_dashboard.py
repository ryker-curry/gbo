"""
GBO — Bullpen Dashboard (Rapsodo Bullpen Analytics, Phase 2 + Phase 3).

Opens a single bullpen session's Rapsodo-imported data: session header/
KPI cards, filters (pitch type, pitch number range), the pitch-type
summary table with an expandable individual-pitch view (spec Sections
5-6), and the core visualizations -- movement, release point, velocity/
spin trend, location, and spin axis (spec Sections 7-11, Phase 3).
Regenerates entirely from stored RapsodoPitch rows -- never needs the
original file re-uploaded, per spec Section 3 Step 7.

Chart layout follows spec Section 25's grouping: Movement | Release
Point, then Velocity + Spin, then Location | Spin Axis. All charts
respect the same pitch-type/pitch-number filters as the summary table
above them, except the individual-pitch spin-axis view (busy at "All
Pitches" scale by design, per its own docstring) which gets its own
type selector.

Reached two ways:
  - With ?bullpen_id=<id> in the URL (e.g. linked from Bullpen Tracking's
    session list, or the "view full dashboard" link after a fresh
    import) -- opens that session directly.
  - With no bullpen_id -- shows a player + session picker scoped to
    whatever the logged-in user is allowed to see (same permission
    pattern as Bullpen Tracking/My Bullpens).

Permissions mirror pages/bullpen_tracking.py and pages/player_bullpens.py
exactly -- no new authorization logic invented here. Players see only
their own sessions; coaches see assigned players unless
can_view_all_players; the page itself has no edit actions (Phase 2 is
read-only review), so no can_edit_sessions gate is needed.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, BullpenSession, RapsodoPitch
from ui_components import page_header, page_footer, empty_state, render_kpi_cards
from analytics.bullpen_metrics import (
    session_summary, pitch_type_summary, individual_pitch_rows, filter_pitches, pitch_type_label,
)
from visualizations.bullpen_charts import (
    movement_chart, release_point_chart, velocity_spin_trend_chart, location_chart,
)
from visualizations.spin_axis_chart import individual_spin_axis_chart, average_spin_axis_chart

page_header("Bullpen Dashboard")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    # --- Figure out which players this user is allowed to see ---
    if role_name == "Player":
        me = session.query(User).filter(User.user_id == current_user_id).first()
        if me is None or me.player_id is None:
            st.info("Your player profile isn't linked yet. Check with an administrator.")
            page_footer()
            st.stop()
        allowed_player_ids = [me.player_id]
    else:
        if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
            st.error("You don't have access to this page.")
            page_footer()
            st.stop()
        player_query = session.query(Player).filter(Player.is_pitcher.is_(True))
        if not can_view_all:
            assigned_ids = [
                a.player_id for a in
                session.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == current_user_id).all()
            ]
            player_query = player_query.filter(Player.player_id.in_(assigned_ids))
        allowed_player_ids = [p.player_id for p in player_query.all()]

    if not allowed_player_ids:
        empty_state("No pitchers to show yet." if can_view_all else "No pitchers are currently assigned to you.")
        page_footer()
        st.stop()

    # --- Resolve the target bullpen session: from URL, or from a picker ---
    query_bullpen_id_raw = st.query_params.get("bullpen_id")
    try:
        target_bullpen_id = int(query_bullpen_id_raw) if query_bullpen_id_raw is not None else None
    except ValueError:
        target_bullpen_id = None

    # Sessions with at least one RapsodoPitch row, scoped to allowed players --
    # this dashboard is specifically for Rapsodo-native data (Phase 2 scope).
    sessions_with_rapsodo_data = (
        session.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .join(RapsodoPitch, RapsodoPitch.bullpen_id == BullpenSession.bullpen_id)
        .filter(BullpenSession.player_id.in_(allowed_player_ids))
        .distinct()
        .order_by(BullpenSession.session_date.desc())
        .all()
    )

    if target_bullpen_id is not None and target_bullpen_id not in {b.bullpen_id for b in sessions_with_rapsodo_data}:
        st.warning("That session either doesn't exist, has no Rapsodo data yet, or you don't have access to it.")
        target_bullpen_id = None

    if target_bullpen_id is None:
        if not sessions_with_rapsodo_data:
            empty_state(
                "No bullpen sessions with imported Rapsodo data yet. Upload one from the "
                "\"Import Rapsodo Data\" page first."
            )
            page_footer()
            st.stop()

        st.subheader("Select a session")
        sessions_by_id = {b.bullpen_id: b for b in sessions_with_rapsodo_data}

        def _label(bid):
            b = sessions_by_id[bid]
            name = f"{b.player.first_name} {b.player.last_name}" if b.player else "—"
            type_label = b.bullpen_type.type_name if b.bullpen_type else "—"
            return f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {name} — {type_label}"

        chosen = st.selectbox("Bullpen session", options=list(sessions_by_id.keys()), format_func=_label)
        if st.button("Open dashboard", type="primary"):
            st.query_params["bullpen_id"] = str(chosen)
            st.rerun()
        page_footer()
        st.stop()

    active_bullpen = (
        session.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .filter(BullpenSession.bullpen_id == target_bullpen_id)
        .first()
    )

    all_pitches = (
        session.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.bullpen_id == target_bullpen_id)
        .order_by(RapsodoPitch.pitch_number)
        .all()
    )

    # --- Session header ---
    player_name = f"{active_bullpen.player.first_name} {active_bullpen.player.last_name}" if active_bullpen.player else "—"
    type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"
    st.subheader(f"{player_name} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}")
    if active_bullpen.overall_notes:
        st.caption(active_bullpen.overall_notes)

    summary = session_summary(all_pitches)
    render_kpi_cards([
        {"label": "Total Pitches", "value": str(summary["total_pitches"])},
        {"label": "Pitch Types", "value": str(len(summary["pitch_type_names"]))},
        {"label": "Avg Velocity", "value": f"{summary['avg_velocity']:.1f} mph" if summary["avg_velocity"] is not None else "—"},
        {"label": "Max Velocity", "value": f"{summary['max_velocity']:.1f} mph" if summary["max_velocity"] is not None else "—"},
        {"label": "Avg Spin Rate", "value": f"{summary['avg_spin_rate']:.0f} rpm" if summary["avg_spin_rate"] is not None else "—"},
    ])

    if active_bullpen.video_url:
        with st.expander("Session video"):
            st.video(active_bullpen.video_url)

    st.divider()

    # --- Filters (spec Section 5): All Pitches / Pitch Type / Pitch Number Range ---
    st.subheader("Filters")
    col1, col2 = st.columns([1, 2])
    with col1:
        type_options = ["All Pitches"] + summary["pitch_type_names"]
        selected_type = st.selectbox("Pitch Type", options=type_options)
    with col2:
        max_pitch_number = max((p.pitch_number for p in all_pitches), default=1)
        pitch_range = st.slider(
            "Pitch Number Range", min_value=1, max_value=max_pitch_number,
            value=(1, max_pitch_number), disabled=(max_pitch_number <= 1),
        )

    filtered_pitches = filter_pitches(
        all_pitches,
        pitch_type_name=None if selected_type == "All Pitches" else selected_type,
        pitch_number_range=pitch_range,
    )

    if not filtered_pitches:
        empty_state("No pitches match the selected filters.")
        page_footer()
        st.stop()

    st.divider()

    # --- Pitch-type summary table (spec Section 6) ---
    st.subheader("Pitch Summary")
    summary_rows = pitch_type_summary(filtered_pitches)
    st.dataframe(summary_rows, use_container_width=True, hide_index=True)

    st.caption("Expand a pitch type below to see every individual pitch.")
    pitches_by_type = {}
    for p in filtered_pitches:
        pitches_by_type.setdefault(pitch_type_label(p), []).append(p)

    for row in summary_rows:
        label = row["Pitch Type"]
        with st.expander(f"{label} ({row['#']} pitches)"):
            st.dataframe(individual_pitch_rows(pitches_by_type[label]), use_container_width=True, hide_index=True)

    st.divider()

    # --- Charts (spec Sections 7-11, Phase 3) -- respect the same
    # filters as the summary table above (pitch type, pitch number
    # range), per spec Section 5's "charts should respond to the
    # filters whenever appropriate." ---
    st.subheader("Charts")

    col1, col2 = st.columns(2)
    with col1:
        st.plotly_chart(movement_chart(filtered_pitches), use_container_width=True)
        st.caption("Centered on release point; color-coded by pitch type. Hover a pitch for details.")
    with col2:
        st.plotly_chart(release_point_chart(filtered_pitches), use_container_width=True)
        st.caption("Tighter clustering across pitch types suggests better tunneling out of the hand.")

    st.plotly_chart(velocity_spin_trend_chart(filtered_pitches), use_container_width=True)
    if selected_type == "All Pitches":
        st.caption(
            "Showing every pitch in throwing order -- a fastball/offspeed mix will naturally zigzag here. "
            "Filter to a single pitch type above for that type's own trend."
        )

    col3, col4 = st.columns(2)
    with col3:
        location_mode = st.radio("Location view", ["Heat Map", "Individual Pitches"], horizontal=True, key="dash_location_mode")
        st.plotly_chart(
            location_chart(filtered_pitches, mode="heatmap" if location_mode == "Heat Map" else "individual"),
            use_container_width=True,
        )
    with col4:
        spin_axis_mode = st.radio("Spin axis view", ["Average by Pitch Type", "Individual Pitches"], horizontal=True, key="dash_spin_axis_mode")
        if spin_axis_mode == "Average by Pitch Type":
            st.plotly_chart(average_spin_axis_chart(filtered_pitches), use_container_width=True)
        else:
            individual_type_filter = None if selected_type == "All Pitches" else selected_type
            if selected_type == "All Pitches":
                st.caption("Showing every pitch type at once gets busy -- filter to one type above for a cleaner view.")
            st.plotly_chart(individual_spin_axis_chart(filtered_pitches, pitch_type_filter=individual_type_filter), use_container_width=True)

finally:
    session.close()

page_footer()
