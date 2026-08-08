"""
GBO — My Stats (Player role only).

The player's own batting and pitching lines from Game Tracking data,
filterable by season. Distinct from My Assessments (the 11 testing
categories) -- this is game statistics specifically. Shares its
computation logic with Analytics (the coach-facing equivalent) via
game_stats.py, so the two never drift apart. Read-only.

First, honest pass at counting stats + Run Value -- NOT the full
Baseball-Savant-style page yet (Whiff%/CSW%/Chase%/Putaway%/splits
etc. are a deferred follow-up).
"""

import streamlit as st

from database import get_session
from models import Player, User, Season
from ui_components import page_header, page_footer, empty_state
from game_stats import get_batting_pitches, get_pitching_pitches, compute_batting_line, compute_pitching_line

page_header("My Stats")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name != "Player":
    st.error("This page is only available to Player accounts.")
    page_footer()
    st.stop()

session = get_session()
try:
    me = session.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        st.info("Your player profile isn't linked yet. Check with an administrator.")
        page_footer()
        st.stop()

    my_player = session.query(Player).filter(Player.player_id == me.player_id).first()

    seasons = session.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
    seasons_by_id = {s.season_id: s for s in seasons}
    season_choice = st.selectbox(
        "Season",
        options=[None] + list(seasons_by_id.keys()),
        format_func=lambda sid: "-- All seasons --" if sid is None else f"{seasons_by_id[sid].season_name}" + ("" if seasons_by_id[sid].is_official else " (practice/fall, not official)"),
    )

    st.divider()

    batting_pitches = get_batting_pitches(session, my_player.player_id, season_choice)
    pitching_pitches = get_pitching_pitches(session, my_player.player_id, season_choice)

    if not my_player.is_pitcher:
        st.markdown("### Hitting")
        if not batting_pitches:
            empty_state("No hitting data recorded yet for you in Game Tracking.")
        else:
            batting_line = compute_batting_line(batting_pitches)
            cols = st.columns(6)
            cols[0].metric("PA", batting_line["PA"])
            cols[1].metric("AB", batting_line["AB"])
            cols[2].metric("H", batting_line["H"])
            cols[3].metric("BB", batting_line["BB"])
            cols[4].metric("K", batting_line["K"])
            cols[5].metric("AVG", f"{batting_line['AVG']:.3f}" if batting_line["AVG"] is not None else "—")
            st.caption(
                f"1B: {batting_line['1B']} · 2B: {batting_line['2B']} · 3B: {batting_line['3B']} · HR: {batting_line['HR']} · "
                f"HBP: {batting_line['HBP']} · Total RV: {batting_line['Total RV']} · Avg RV/PA: {batting_line['Avg RV/PA']}"
            )
        st.divider()
    st.markdown("### Pitching")
    if not pitching_pitches:
        empty_state("No pitching data recorded yet for you in Game Tracking.")
    else:
        pitching_line = compute_pitching_line(pitching_pitches)
        cols = st.columns(6)
        cols[0].metric("Batters Faced", pitching_line["Batters Faced"])
        cols[1].metric("Pitches", pitching_line["Pitches"])
        cols[2].metric("K", pitching_line["K"])
        cols[3].metric("BB", pitching_line["BB"])
        cols[4].metric("H Allowed", pitching_line["H Allowed"])
        cols[5].metric("Execution %", f"{pitching_line['Execution %']:.1f}%" if pitching_line["Execution %"] is not None else "—")
        st.caption(
            f"HR Allowed: {pitching_line['HR Allowed']} · Runs Allowed: {pitching_line['Runs Allowed']} · "
            f"Total RV Allowed: {pitching_line['Total RV Allowed']} · Avg RV Allowed/Pitch: {pitching_line['Avg RV Allowed/Pitch']}"
        )

finally:
    session.close()

page_footer()