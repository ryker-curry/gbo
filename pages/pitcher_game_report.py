"""
GBO — Pitcher Game Report (single-game box score + pitch-type breakdown).

Built to replace Ryker's Google Sheets "Game Stat Sheet" -- pick one
game and one pitcher, see the full box-score-style line (IP, WHIP,
K/BB, K%, ERA/FIP/wOBA/OBA, Leadoff/2-Out/0-2 situational stats, E+A%)
plus the pitch-type breakdown (Usage%, Strike%, Dominance%/CSW%,
Whiff%, Chase%, Putaway%, GB/FB/LD%, Execution%, RV), split overall and
by opponent batter handedness.

Deliberately its own page rather than a tab bolted onto the existing
Analytics page -- Analytics is season/all-time aggregate by design
(see its own docstring); this page needs a single-game scope instead,
matching how Ryker actually fills out one Game Stat Sheet per outing.
Shares every computation with Analytics/My Stats via game_stats.py
(get_pitching_pitches(..., game_id=...), compute_pitching_line(),
compute_pitch_type_breakdown()) -- nothing here is computed a second,
possibly-drifting way.

Known gaps, not silently guessed (see game_stats.py's docstrings for
the full explanation): ER isn't distinguished from total runs allowed
(no earned/unearned model), SBA isn't tracked, and "2 Out BB Score"/
"Leadoff BB Score" (did that specific walked runner score) can't be
computed without tracking individual baserunner identity, which GBO's
bases_before/bases_after occupancy model doesn't do. Only the raw
Leadoff BB / 2 Out BB counts are shown.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch
from ui_components import page_header, page_footer, empty_state
from game_stats import get_pitching_pitches, compute_pitching_line, compute_pitch_type_breakdown

page_header("Pitcher Game Report")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()


def _fmt_pct(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


session = get_session()
try:
    games = session.query(Game).options(joinedload(Game.opponent_team)).order_by(Game.game_date.desc()).all()
    games_by_id = {g.game_id: g for g in games}

    if not games:
        empty_state("No games tracked yet. Start one on Game Tracking first.")
        page_footer()
        st.stop()

    def _opponent_display_name(g):
        if g.opponent_team:
            return g.opponent_team.team_name
        return g.opponent_name or "Unknown opponent"

    def _game_label(gid):
        g = games_by_id[gid]
        loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
        return f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status})"

    selected_game_id = st.selectbox("Game", options=list(games_by_id.keys()), format_func=_game_label)
    selected_game = games_by_id[selected_game_id]

    # Every one of OUR players who threw at least one pitch in this
    # game -- the picker's second step. Query directly rather than
    # relying on the lineup/starting-pitcher fields, since a game with
    # multiple pitching changes has more than one pitcher who actually
    # threw (see GamePitch.our_player_id -- the actual pitcher on every
    # single pitch, not just the starter).
    pitcher_ids = [
        pid for (pid,) in session.query(GamePitch.our_player_id)
        .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(False))
        .distinct()
        .all()
        if pid is not None
    ]
    if not pitcher_ids:
        empty_state("No pitches recorded for any of our pitchers in this game yet.")
        page_footer()
        st.stop()

    pitchers = session.query(Player).filter(Player.player_id.in_(pitcher_ids)).order_by(Player.last_name, Player.first_name).all()
    pitchers_by_id = {p.player_id: p for p in pitchers}
    selected_pitcher_id = st.selectbox(
        "Pitcher", options=list(pitchers_by_id.keys()),
        format_func=lambda pid: f"{pitchers_by_id[pid].first_name} {pitchers_by_id[pid].last_name}",
    )
    selected_pitcher = pitchers_by_id[selected_pitcher_id]

    st.divider()
    st.subheader(f"{selected_pitcher.first_name} {selected_pitcher.last_name} — {_game_label(selected_game_id)}")

    pitches = get_pitching_pitches(session, selected_pitcher_id, game_id=selected_game_id)
    if not pitches:
        empty_state("No pitches for this pitcher in this game.")
        page_footer()
        st.stop()

    line = compute_pitching_line(pitches)

    st.markdown("**Line**")
    cols = st.columns(6)
    cols[0].metric("IP", line["IP"])
    cols[1].metric("Pitches", line["Pitches"])
    cols[2].metric("K", line["K"])
    cols[3].metric("BB", line["BB"])
    cols[4].metric("H", line["H Allowed"])
    cols[5].metric("R", line["Runs Allowed"])

    cols2 = st.columns(6)
    cols2[0].metric("WHIP", _fmt(line["WHIP"]))
    cols2[1].metric("K/BB", _fmt(line["K/BB"]))
    cols2[2].metric("K %", _fmt_pct(line["K %"]))
    cols2[3].metric("ERA*", _fmt(line["ERA (runs-allowed avg -- ER not tracked)"]))
    cols2[4].metric("FIP", _fmt(line["FIP"]))
    cols2[5].metric("Execution %", _fmt_pct(line["Execution %"]))
    st.caption("*ERA here is runs-allowed average, not true ERA -- GBO doesn't distinguish earned from unearned runs yet.")

    st.markdown("**Count Control**")
    ccols = st.columns(4)
    ccols[0].metric("Strike %", _fmt_pct(line["Strike %"]))
    ccols[1].metric("Early", line["Early"])
    ccols[2].metric("Ahead", line["Ahead (PA)"])
    ccols[3].metric("E+A %", _fmt_pct(line["E+A %"]))
    st.caption(
        f"Pitches/Inning: {_fmt(line['Pitches/Inning'], 1)} · "
        f"Balls: {line['Balls']} ({_fmt_pct(line['Ball %'])})"
    )

    st.markdown("**Situational**")
    scols = st.columns(4)
    scols[0].metric("Leadoff Out %", _fmt_pct(line["Leadoff Out %"]))
    scols[1].metric("Leadoff BB", line["Leadoff BB"])
    scols[2].metric("2 Out BB", line["2 Out BB"])
    scols[3].metric("XBH Allowed", line["XBH"])
    st.caption(
        f"0-2 Hits: {line['0-2 Hits']} · 0-2 Barrel: {line['0-2 Barrel']} · 1-2 Barrel: {line['1-2 Barrel']} · "
        "\"Score\" versions (did that specific walked runner score) aren't computable yet -- "
        "GBO tracks base occupancy, not individual runner identity."
    )

    st.markdown("**Against**")
    acols = st.columns(3)
    acols[0].metric("OBA", _fmt(line["OBA (opponent AVG)"], 3))
    acols[1].metric("wOBA*", _fmt(line["wOBA"], 3))
    acols[2].metric("AB", line["AB"])
    st.caption("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.")

    st.divider()
    st.markdown("**Pitch Type Breakdown**")
    breakdown_tab_all, breakdown_tab_rhh, breakdown_tab_lhh = st.tabs(["All Batters", "vs RHH", "vs LHH"])
    with breakdown_tab_all:
        st.dataframe(compute_pitch_type_breakdown(pitches), use_container_width=True, hide_index=True)
    with breakdown_tab_rhh:
        vs_rhh = [p for p in pitches if p.opponent_hand == "R"]
        if not vs_rhh:
            st.caption("No pitches recorded against a right-handed batter yet.")
        else:
            st.dataframe(compute_pitch_type_breakdown(vs_rhh), use_container_width=True, hide_index=True)
    with breakdown_tab_lhh:
        vs_lhh = [p for p in pitches if p.opponent_hand == "L"]
        if not vs_lhh:
            st.caption("No pitches recorded against a left-handed batter yet.")
        else:
            st.dataframe(compute_pitch_type_breakdown(vs_lhh), use_container_width=True, hide_index=True)

finally:
    session.close()

page_footer()
