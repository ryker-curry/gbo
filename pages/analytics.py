"""
GBO — Analytics (coach/staff-facing).

Pick a player, see their batting and pitching lines computed from
Game Tracking data, filterable by season (so fall/practice stats stay
separate from real spring regular-season stats). Shares its
computation logic with My Stats (the player-facing equivalent) via
game_stats.py, so the two never drift apart.

Plate Discipline (Zone%/Swing%/Chase%/Whiff%/etc.) and Pitch Command/
Usage are computed from the coordinate data captured in Phase 2 (see
plate_discipline.py). Pitch Type Breakdown (Strike%/Whiff%/CSW%/Chase%/
Putaway%/GB-FB-LD%, split overall and by opponent batter handedness) is
the per-pitch-type rate-stat rollup from game_stats.py's
compute_pitch_type_breakdown() -- still not a full spray-chart/heat-map
page, but the CSW%/Putaway%/handedness-split gap flagged here before is
closed.

Pitching's "Line" section is the season/all-time-aggregate counterpart
to pages/pitcher_game_report.py's single-game box score -- same
compute_pitching_line() call (just without a game_id filter, so it
aggregates across whatever the Season picker above selects, or all-time
if "All seasons"), same IP/WHIP/K-BB/FIP/wOBA/situational-count fields,
so a coach can view either one game or a whole season through the same
lens without the two ever computing something differently. Same for
Command Precision and Attack Zones (pitch_location_stats.py) -- season-
aggregate here, single-game there, identical computation either way.
"""

import streamlit as st

from database import get_session
from models import Player, Season
from ui_components import page_header, page_footer, empty_state
from game_stats import (
    get_batting_pitches, get_pitching_pitches, compute_batting_line, compute_pitching_line,
    compute_pitch_type_breakdown,
)
from plate_discipline import compute_hitter_discipline, compute_pitcher_command, compute_zone_performance, render_zone_performance_heatmap
from pitch_location_stats import compute_command_precision, compute_attack_zones
from bucket_system_display import render_percentage_rings

page_header("Player Stats")


def _fmt_pct(value):
    return f"{value:.0f}%" if value is not None else "—"


def _fmt_pct1(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_num(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"

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

session = get_session()
try:
    players = session.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
    players_by_id = {p.player_id: p for p in players}

    if not players:
        empty_state("No players to show yet.")
        page_footer()
        st.stop()

    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )
    selected_player = players_by_id[selected_player_id]

    seasons = session.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
    seasons_by_id = {s.season_id: s for s in seasons}
    season_choice = st.selectbox(
        "Season",
        options=[None] + list(seasons_by_id.keys()),
        format_func=lambda sid: "-- All seasons --" if sid is None else f"{seasons_by_id[sid].season_name}" + ("" if seasons_by_id[sid].is_official else " (practice/fall, not official)"),
    )

    st.divider()
    st.subheader(f"{selected_player.first_name} {selected_player.last_name}")

    batting_pitches = get_batting_pitches(session, selected_player_id, season_choice)
    pitching_pitches = get_pitching_pitches(session, selected_player_id, season_choice)

    if not selected_player.is_pitcher:
        st.markdown("### Hitting")
        if not batting_pitches:
            empty_state("No hitting data recorded yet for this player in Game Tracking.")
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

            st.markdown("**Plate Discipline**")
            discipline = compute_hitter_discipline(batting_pitches)
            if discipline["Pitches Seen"] == 0:
                st.caption("No pitches seen yet.")
            else:
                d1, d2, d3, d4, d5 = st.columns(5)
                d1.metric("Zone %", _fmt_pct(discipline["Zone %"]))
                d2.metric("Swing %", _fmt_pct(discipline["Swing %"]))
                d3.metric("Chase %", _fmt_pct(discipline["Chase %"]))
                d4.metric("Whiff %", _fmt_pct(discipline["Whiff %"]))
                d5.metric("1st-Pitch Swing %", _fmt_pct(discipline["First-Pitch Swing %"]))
                st.caption(
                    f"Zone Swing %: {_fmt_pct(discipline['Zone Swing %'])} · Zone Contact %: {_fmt_pct(discipline['Zone Contact %'])} · "
                    f"Chase Contact %: {_fmt_pct(discipline['Chase Contact %'])} · Pitches Seen: {discipline['Pitches Seen']} "
                    f"({discipline['Located Pitches']} with a recorded location)"
                )
        st.divider()
    if selected_player.is_pitcher:
        st.markdown("### Pitching")
        if not pitching_pitches:
            empty_state("No pitching data recorded yet for this player in Game Tracking.")
        else:
            pitching_line = compute_pitching_line(pitching_pitches)
            command = compute_pitcher_command(pitching_pitches)

            st.markdown("**Pitching KPIs**")
            render_percentage_rings(
                [
                    ("Zone %", command["Zone %"]),
                    ("Whiff % Induced", command["Whiff % Induced"]),
                    ("Chase % Induced", command["Chase % Induced"]),
                    ("Execution %", pitching_line["Execution %"]),
                ],
                key_prefix=f"pitch_kpi_{selected_player_id}",
            )

            st.markdown("**Line**" + (f" — {seasons_by_id[season_choice].season_name}" if season_choice is not None else " — All seasons"))
            cols = st.columns(6)
            cols[0].metric("IP", pitching_line["IP"])
            cols[1].metric("Pitches", pitching_line["Pitches"])
            cols[2].metric("K", pitching_line["K"])
            cols[3].metric("BB", pitching_line["BB"])
            cols[4].metric("H", pitching_line["H Allowed"])
            cols[5].metric("R", pitching_line["Runs Allowed"])

            cols2 = st.columns(6)
            cols2[0].metric("WHIP", _fmt_num(pitching_line["WHIP"]))
            cols2[1].metric("K/BB", _fmt_num(pitching_line["K/BB"]))
            cols2[2].metric("K %", _fmt_pct1(pitching_line["K %"]))
            cols2[3].metric("ERA*", _fmt_num(pitching_line["ERA (runs-allowed avg -- ER not tracked)"]))
            cols2[4].metric("FIP", _fmt_num(pitching_line["FIP"]))
            cols2[5].metric("Execution %", _fmt_pct1(pitching_line["Execution %"]))
            st.caption(
                f"*ERA here is runs-allowed average, not true ERA -- GBO doesn't distinguish earned from unearned runs yet. "
                f"Total RV Allowed: {pitching_line['Total RV Allowed']} · Avg RV Allowed/Pitch: {pitching_line['Avg RV Allowed/Pitch']}"
            )

            st.markdown("**Count Control**")
            ccols = st.columns(4)
            ccols[0].metric("Strike %", _fmt_pct1(pitching_line["Strike %"]))
            ccols[1].metric("Early", pitching_line["Early"])
            ccols[2].metric("Ahead", pitching_line["Ahead (PA)"])
            ccols[3].metric("E+A %", _fmt_pct1(pitching_line["E+A %"]))
            st.caption(
                f"Pitches/Inning: {_fmt_num(pitching_line['Pitches/Inning'], 1)} · "
                f"Balls: {pitching_line['Balls']} ({_fmt_pct1(pitching_line['Ball %'])})"
            )

            st.markdown("**Situational**")
            scols = st.columns(4)
            scols[0].metric("Leadoff Out %", _fmt_pct1(pitching_line["Leadoff Out %"]))
            scols[1].metric("Leadoff BB", pitching_line["Leadoff BB"])
            scols[2].metric("2 Out BB", pitching_line["2 Out BB"])
            scols[3].metric("XBH Allowed", pitching_line["XBH"])
            st.caption(
                f"0-2 Hits: {pitching_line['0-2 Hits']} · 0-2 Barrel: {pitching_line['0-2 Barrel']} · "
                f"1-2 Barrel: {pitching_line['1-2 Barrel']} · "
                "\"Score\" versions (did that specific walked runner score) aren't computable yet -- "
                "GBO tracks base occupancy, not individual runner identity."
            )

            st.markdown("**Against**")
            acols = st.columns(3)
            acols[0].metric("OBA", _fmt_num(pitching_line["OBA (opponent AVG)"], 3))
            acols[1].metric("wOBA*", _fmt_num(pitching_line["wOBA"], 3))
            acols[2].metric("AB", pitching_line["AB"])
            st.caption("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.")

            st.markdown("**Pitch Command / Usage**")
            if command["Pitches Thrown"] == 0:
                st.caption("No pitches thrown yet.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Zone %", _fmt_pct(command["Zone %"]))
                c2.metric("Whiff % Induced", _fmt_pct(command["Whiff % Induced"]))
                c3.metric("Chase % Induced", _fmt_pct(command["Chase % Induced"]))
                st.caption(f"Pitches Thrown: {command['Pitches Thrown']} ({command['Located Pitches']} with a recorded location)")
                if command["Usage %"]:
                    usage_str = " · ".join(f"{name}: {_fmt_pct(pct)}" for name, pct in sorted(command["Usage %"].items(), key=lambda kv: -(kv[1] or 0)))
                    st.caption(f"Usage — {usage_str}")

            st.markdown("**Pitch Type Breakdown**")
            st.caption(
                "Rate stats per pitch type -- the same breakdown a game-tracking spreadsheet computes with "
                "formulas, generated here from the same pitches already logged in Game Tracking."
            )
            breakdown_tab_all, breakdown_tab_rhh, breakdown_tab_lhh = st.tabs(["All Batters", "vs RHH", "vs LHH"])
            with breakdown_tab_all:
                st.dataframe(compute_pitch_type_breakdown(pitching_pitches), use_container_width=True, hide_index=True)
            with breakdown_tab_rhh:
                vs_rhh = [p for p in pitching_pitches if p.opponent_hand == "R"]
                if not vs_rhh:
                    st.caption("No pitches recorded against a right-handed batter yet.")
                else:
                    st.dataframe(compute_pitch_type_breakdown(vs_rhh), use_container_width=True, hide_index=True)
            with breakdown_tab_lhh:
                vs_lhh = [p for p in pitching_pitches if p.opponent_hand == "L"]
                if not vs_lhh:
                    st.caption("No pitches recorded against a left-handed batter yet.")
                else:
                    st.dataframe(compute_pitch_type_breakdown(vs_lhh), use_container_width=True, hide_index=True)

            st.markdown("**Command Precision**")
            st.caption(
                "Real distance between where he aimed and where it actually crossed the plate -- only counts "
                "pitches reviewed in Video Review (both an intended and an actual location on file)."
            )
            cp_overall, cp_by_type = compute_command_precision(pitching_pitches, throws=selected_player.throws)
            if cp_overall["Reviewed"] == 0:
                st.caption("No reviewed pitches yet (needs Video Review).")
            else:
                cp1, cp2, cp3, cp4 = st.columns(4)
                cp1.metric("Avg Miss", f"{cp_overall['Avg Miss (in)']}\"")
                cp2.metric("Reviewed", cp_overall["Reviewed"])
                cp3.metric("Horizontal Bias", f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}")
                cp4.metric("Vertical Bias", f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}")
                if selected_player.throws not in ("R", "L"):
                    st.caption("Pitcher's throwing hand isn't on file, so horizontal bias shows raw 3B-side/1B-side instead of Arm-side/Glove-side.")
                st.dataframe(cp_by_type, use_container_width=True, hide_index=True)

            st.markdown("**Attack Zones**")
            st.caption("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near. GBO approximation of Statcast's own tiers -- see pitch_location_stats.py for exact boundaries.")
            az_overall, az_by_type = compute_attack_zones(pitching_pitches)
            if az_overall["Located"] == 0:
                st.caption("No located pitches yet.")
            else:
                az1, az2, az3, az4 = st.columns(4)
                az1.metric("Heart %", _fmt_pct(az_overall["Heart %"]))
                az2.metric("Shadow %", _fmt_pct(az_overall["Shadow %"]))
                az3.metric("Chase Zone %", _fmt_pct(az_overall["Chase Zone %"]))
                az4.metric("Waste %", _fmt_pct(az_overall["Waste %"]))
                st.dataframe(az_by_type, use_container_width=True, hide_index=True)

            st.markdown("**Zone Performance**")
            st.caption("How well his pitches perform in each part of the zone, from his own Game Tracking pitches (Run Value by location).")
            avg_rv, zone_counts = compute_zone_performance(pitching_pitches)
            if not avg_rv:
                empty_state("No pitches yet with both a recorded location and a computed Run Value.")
            else:
                render_zone_performance_heatmap(avg_rv, zone_counts)


finally:
    session.close()

page_footer()