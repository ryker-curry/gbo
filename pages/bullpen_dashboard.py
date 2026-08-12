"""
GBO — Bullpen Dashboard (Rapsodo Bullpen Analytics, Phase 2 + Phase 3).

Two layers: an Overall Pitch Tracking table (section 1) combining every
one of the selected pitcher's Rapsodo sessions, sitting above a single
session's full drill-down -- session header/KPI cards, filters (pitch
type, pitch number range), the pitch-type summary table with an
expandable individual-pitch view (spec Sections 5-6), and the core
visualizations -- movement, release point (individual pitches and
average-by-type, side by side), location, and spin axis (spec Sections
7, 8, 11, Phase 3). Regenerates entirely from stored RapsodoPitch
rows -- never needs the original file re-uploaded, per spec Section 3
Step 7.

Chart layout: Movement, then Release Point (two panels), then
Location | Spin Axis -- adapted from spec Section 25's original
Movement | Release Point, then Velocity + Spin, then Location | Spin
Axis grouping, since the Velocity and Spin Rate Trend chart (Section
9) was removed per Ryker's call. (A Phase 4 flight-path Trajectory
pair of panels was tried here too and then removed again after Ryker
reviewed it live -- see bullpen_dashboard_render.py's docstring.) All
charts respect the same pitch-type/pitch-number filters as the
summary table above them, except the individual-pitch spin-axis view
(busy at "All Pitches" scale by design, per its own docstring) which
gets its own type
selector.

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
from ui_components import page_header, page_footer, empty_state
from bullpen_dashboard_style import inject_dashboard_theme
from bullpen_dashboard_render import render_bullpen_session, render_overall_pitch_tracking

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
    # existing per-session view. Shared with pages/player_bullpens.py's
    # "All Sessions (Combined)" picker option, see
    # bullpen_dashboard_render.py. ---
    render_overall_pitch_tracking(session, target_player, player_session_ids, section_start=1)

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
