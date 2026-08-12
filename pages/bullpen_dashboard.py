"""
GBO — Bullpen Dashboard (Rapsodo Bullpen Analytics, Phase 2 + Phase 3).

Two layers: an Overall Pitch Tracking table (section 1) combining every
one of the selected pitcher's Rapsodo sessions, sitting above a single
session's full drill-down -- session header/KPI cards, filters (pitch
type, pitch number range), the pitch-type summary table with an
expandable individual-pitch view (spec Sections 5-6), and the core
visualizations -- movement, release point, velocity/spin trend,
location, and spin axis (spec Sections 7-11, Phase 3). Regenerates
entirely from stored RapsodoPitch rows -- never needs the original
file re-uploaded, per spec Section 3 Step 7.

Chart layout follows spec Section 25's grouping: Movement | Release
Point, then Velocity + Spin, then Location | Spin Axis. All charts
respect the same pitch-type/pitch-number filters as the summary table
above them, except the individual-pitch spin-axis view (busy at "All
Pitches" scale by design, per its own docstring) which gets its own
type selector.

Reached two ways:
  - With ?bullpen_id=<id> in the URL (e.g. linked from Bullpen Tracking's
    session list, or the "view full dashboard" link after a fresh
    import) -- the pitcher is implied by that session, so both picker
    steps below are skipped and the page opens straight into the
    Overall table (for that pitcher) plus that specific session's
    drill-down.
  - With no bullpen_id -- a two-step picker, per Ryker's request:
    first pick a pitcher (scoped to whatever the logged-in user is
    allowed to see, same permission pattern as Bullpen Tracking/My
    Bullpens), which immediately reveals that pitcher's Overall Pitch
    Tracking table, then pick one of that specific pitcher's sessions
    to open its full drill-down below.

Permissions mirror pages/bullpen_tracking.py and pages/player_bullpens.py
exactly -- no new authorization logic invented here. Players see only
their own sessions; coaches see assigned players unless
can_view_all_players; the page itself has no edit actions (Phase 2 is
read-only review), so no can_edit_sessions gate is needed.

Page chrome (near-black background, bordered card panels, numbered
section labels) is styled after Paradigm Player Development's report
layout -- see bullpen_dashboard_style.py for why that's its own module
instead of a change to ui_components.py's shared styling.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, BullpenSession, RapsodoPitch
from ui_components import page_header, page_footer, empty_state, render_kpi_cards
from bullpen_dashboard_style import inject_dashboard_theme, section_label, pitch_type_legend
from bullpen_dashboard_render import render_bullpen_session
from analytics.bullpen_metrics import session_summary, pitch_type_summary
from visualizations.bullpen_charts import (
    movement_chart, release_point_chart, velocity_spin_trend_chart, location_chart, color_for_pitch_label,
)
from visualizations.spin_axis_chart import individual_spin_axis_chart, average_spin_axis_chart

page_header("Bullpen Dashboard")
inject_dashboard_theme()

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

    # --- Resolve the target bullpen session: from URL, or from a
    # pitcher-then-session picker ---
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

    if not sessions_with_rapsodo_data:
        empty_state(
            "No bullpen sessions with imported Rapsodo data yet. Upload one from the "
            "\"Import Rapsodo Data\" page first."
        )
        page_footer()
        st.stop()

    sessions_by_id = {b.bullpen_id: b for b in sessions_with_rapsodo_data}
    if target_bullpen_id is not None and target_bullpen_id not in sessions_by_id:
        st.warning("That session either doesn't exist, has no Rapsodo data yet, or you don't have access to it.")
        target_bullpen_id = None

    # Pitchers who actually have Rapsodo session data, scoped to what this
    # user is allowed to see -- the picker's first step. Ordered by name,
    # not session-recency, since this is "pick a person" not "pick a date."
    pitchers_by_id = {}
    for b in sessions_with_rapsodo_data:
        if b.player and b.player_id not in pitchers_by_id:
            pitchers_by_id[b.player_id] = b.player
    sorted_pitcher_ids = sorted(
        pitchers_by_id, key=lambda pid: (pitchers_by_id[pid].last_name, pitchers_by_id[pid].first_name)
    )

    if target_bullpen_id is not None:
        # Direct-link entry point (e.g. from Bullpen Tracking's session
        # list) -- the pitcher is already implied by the session, no
        # picker needed.
        target_player_id = sessions_by_id[target_bullpen_id].player_id
    else:
        # --- Step 1: pick a pitcher ---
        st.subheader("Select a pitcher")
        target_player_id = st.selectbox(
            "Pitcher", options=sorted_pitcher_ids,
            format_func=lambda pid: f"{pitchers_by_id[pid].first_name} {pitchers_by_id[pid].last_name}",
        )

    target_player = pitchers_by_id.get(target_player_id) or sessions_by_id[target_bullpen_id].player
    player_session_ids = [b.bullpen_id for b in sessions_with_rapsodo_data if b.player_id == target_player_id]

    # --- Overall Pitch Tracking: every one of this pitcher's Rapsodo
    # sessions combined, ahead of the single-session drill-down below --
    # per Ryker's request for a career/overall total table before the
    # existing per-session view. Reuses the exact same pitch_type_summary()
    # table shape as the per-session Pitch Summary further down, just fed
    # every pitch across every session instead of one. ---
    overall_pitches = (
        session.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.bullpen_id.in_(player_session_ids))
        .order_by(RapsodoPitch.pitch_date)
        .all()
    )
    with st.container(border=True):
        section_label(1, f"Overall Pitch Tracking — {target_player.first_name} {target_player.last_name}")
        overall_summary = session_summary(overall_pitches)
        render_kpi_cards([
            {"label": "Sessions", "value": str(len(player_session_ids))},
            {"label": "Total Pitches", "value": str(overall_summary["total_pitches"])},
            {"label": "Pitch Types", "value": str(len(overall_summary["pitch_type_names"]))},
            {"label": "Avg Velocity", "value": f"{overall_summary['avg_velocity']:.1f} mph" if overall_summary["avg_velocity"] is not None else "—"},
            {"label": "Avg Spin Rate", "value": f"{overall_summary['avg_spin_rate']:.0f} rpm" if overall_summary["avg_spin_rate"] is not None else "—"},
        ])
        overall_rows = pitch_type_summary(overall_pitches)
        st.dataframe(overall_rows, use_container_width=True, hide_index=True)

        if overall_pitches:
            st.write("")
            st.markdown("**Charts — every imported pitch for this pitcher, all sessions combined**")

            # Same five charts as the single-session view below, fed
            # every pitch across every one of this pitcher's sessions
            # instead of just one -- per Ryker's request that the overall
            # section show charts too, not just the totals table. Widget
            # keys are prefixed "overall_" since these are a second,
            # independent instance of the same controls used lower down
            # for the single-session Charts section.
            overall_min_shading = st.slider(
                "Minimum pitches to shade a pitch type's cluster", min_value=1, max_value=10, value=2,
                key="overall_min_shading_pitches",
                help="A pitch type with fewer pitches than this still shows its dots, just no shaded cluster region.",
            )
            st.plotly_chart(
                movement_chart(overall_pitches, min_pitches_for_shading=overall_min_shading), use_container_width=True
            )
            pitch_type_legend(overall_rows, overall_summary["total_pitches"], color_for_pitch_label)
            st.caption("Centered on release point; color-coded by pitch type. Hover a pitch for details.")

            st.plotly_chart(release_point_chart(overall_pitches), use_container_width=True)
            st.caption("Tighter clustering across pitch types suggests better tunneling out of the hand.")

            st.plotly_chart(velocity_spin_trend_chart(overall_pitches), use_container_width=True)
            st.caption(
                "Showing every pitch across every session in throwing order -- a jump between sessions "
                "will show up as a break in the trend here, not a single continuous outing."
            )

            overall_location_mode = st.radio(
                "Location view", ["Heat Map", "Individual Pitches"], horizontal=True, key="overall_location_mode",
            )
            st.plotly_chart(
                location_chart(overall_pitches, mode="heatmap" if overall_location_mode == "Heat Map" else "individual"),
                use_container_width=True,
            )

            overall_spin_axis_mode = st.radio(
                "Spin axis view", ["Average by Pitch Type", "Individual Pitches"], horizontal=True,
                key="overall_spin_axis_mode",
            )
            if overall_spin_axis_mode == "Average by Pitch Type":
                st.plotly_chart(average_spin_axis_chart(overall_pitches), use_container_width=True)
            else:
                st.caption("Showing every pitch type at once gets busy across a full multi-session history.")
                st.plotly_chart(
                    individual_spin_axis_chart(overall_pitches, pitch_type_filter=None), use_container_width=True
                )

    st.write("")

    if target_bullpen_id is None:
        # --- Step 2: pick one of that pitcher's sessions ---
        st.subheader("Select a session")
        pitcher_sessions_by_id = {bid: sessions_by_id[bid] for bid in player_session_ids}

        def _label(bid):
            b = pitcher_sessions_by_id[bid]
            type_label = b.bullpen_type.type_name if b.bullpen_type else "—"
            return f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}"

        chosen = st.selectbox("Bullpen session", options=list(pitcher_sessions_by_id.keys()), format_func=_label)
        if st.button("Open dashboard", type="primary"):
            st.query_params["bullpen_id"] = str(chosen)
            st.rerun()
        page_footer()
        st.stop()

    # --- Single-session drill-down (sections 2-4: Filters, Pitch
    # Summary, Charts) -- shared with pages/player_bullpens.py's inline
    # expander version, see bullpen_dashboard_render.py. ---
    render_bullpen_session(session, target_bullpen_id, section_start=2)

finally:
    session.close()

page_footer()
