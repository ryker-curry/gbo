"""
GBO — My Stats (Player role only).

The player's own batting and pitching lines from Game Tracking data,
filterable by season. Distinct from My Assessments (the 11 testing
categories) -- this is game statistics specifically. Shares its
computation logic with Analytics (the coach-facing equivalent) via
game_stats.py, so the two never drift apart. Read-only.

Plate Discipline (Zone%/Swing%/Chase%/Whiff%/etc.) and Pitch Command/
Usage are computed from the coordinate data captured in Phase 2 (see
plate_discipline.py). Pitch Type Breakdown (Strike%/Whiff%/CSW%/Chase%/
Putaway%/GB-FB-LD%) is game_stats.py's compute_pitch_type_breakdown() --
still not a full spray-chart/heat-map page, but the CSW%/Putaway% gap
flagged here before is closed. No handedness-split tabs here (kept
simpler than the coach-facing Analytics page) -- ask if that's wanted.

Pitching line/situational stats and Command Precision/Attack Zones
(pitch_location_stats.py) match pages/analytics.py's Pitching section
exactly -- same compute_pitching_line()/compute_command_precision()/
compute_attack_zones() calls, just scoped to the logged-in player's own
data instead of a coach's player picker, so a player's own "My Stats"
never shows a different number than what their coach sees for them.
Same for Hitting's Slash Line/Situational/Zone-Tier Discipline/Batted-
Ball Profile sections -- match pages/analytics.py's Hitting section
exactly.
"""

import streamlit as st

from database import get_session
from models import Player, User, Season
from ui_components import page_header, page_footer, empty_state
from game_stats import (
    get_batting_pitches, get_pitching_pitches, compute_batting_line, compute_pitching_line,
    compute_pitch_type_breakdown, compute_batted_ball_profile,
)
from plate_discipline import compute_hitter_discipline, compute_pitcher_command, compute_zone_tier_discipline
from pitch_location_stats import compute_command_precision, compute_attack_zones

page_header("My Stats")


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
            st.markdown("**Line**" + (f" — {seasons_by_id[season_choice].season_name}" if season_choice is not None else " — All seasons"))
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

            st.markdown("**Slash Line**")
            scols = st.columns(5)
            scols[0].metric("OBP", _fmt_num(batting_line["OBP"], 3))
            scols[1].metric("SLG", _fmt_num(batting_line["SLG"], 3))
            scols[2].metric("OPS", _fmt_num(batting_line["OPS"], 3))
            scols[3].metric("ISO", _fmt_num(batting_line["ISO"], 3))
            scols[4].metric("wOBA*", _fmt_num(batting_line["wOBA"], 3))
            st.caption("*wOBA uses generic linear weights, not a season/league-specific set.")

            dcols = st.columns(3)
            dcols[0].metric("BB %", _fmt_pct1(batting_line["BB %"]))
            dcols[1].metric("K %", _fmt_pct1(batting_line["K %"]))
            dcols[2].metric("BB/K", _fmt_num(batting_line["BB/K"], 2))

            st.markdown("**Situational**")
            sitcols = st.columns(3)
            sitcols[0].metric("RISP AVG", _fmt_num(batting_line["RISP AVG"], 3))
            sitcols[1].metric("2-Strike AVG", _fmt_num(batting_line["2-Strike AVG"], 3))
            sitcols[2].metric("Leadoff AVG", _fmt_num(batting_line["Leadoff AVG"], 3))
            st.caption(
                f"RISP: {batting_line['RISP PA']} PA ({batting_line['RISP AB']} AB) · 2-Strike: {batting_line['2-Strike PA']} PA "
                f"({_fmt_pct1(batting_line['2-Strike K %'])} ended in a K) · Leadoff: {batting_line['Leadoff PA']} PA"
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

            st.markdown("**Zone-Tier Discipline**")
            st.caption("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.")
            st.dataframe(compute_zone_tier_discipline(batting_pitches), use_container_width=True, hide_index=True)

            st.markdown("**Batted-Ball Profile**")
            profile = compute_batted_ball_profile(batting_pitches, bats=my_player.bats)
            if profile["Balls in Play"] == 0:
                st.caption("No balls in play yet.")
            else:
                bcols = st.columns(4)
                bcols[0].metric("Ground Ball %", _fmt_pct1(profile["Ground Ball %"]))
                bcols[1].metric("Fly Ball %", _fmt_pct1(profile["Fly Ball %"]))
                bcols[2].metric("Line Drive %", _fmt_pct1(profile["Line Drive %"]))
                bcols[3].metric("Pop Up %", _fmt_pct1(profile["Pop Up %"]))

                bcols2 = st.columns(3)
                if profile["Spray Mode"] == "Pull/Center/Oppo":
                    bcols2[0].metric("Pull %", _fmt_pct1(profile["Pull %"]))
                    bcols2[1].metric("Center %", _fmt_pct1(profile["Center %"]))
                    bcols2[2].metric("Oppo %", _fmt_pct1(profile["Oppo %"]))
                else:
                    bcols2[0].metric("Left Field %", _fmt_pct1(profile["Left Field %"]))
                    bcols2[1].metric("Center %", _fmt_pct1(profile["Center %"]))
                    bcols2[2].metric("Right Field %", _fmt_pct1(profile["Right Field %"]))
                    st.caption("Your bats hand isn't on file (or switch-hitter), so this shows raw field side instead of Pull/Oppo.")

                bcols3 = st.columns(2)
                bcols3[0].metric("Barrel %", _fmt_pct1(profile["Barrel %"]))
                bcols3[1].metric("Hard Contact %", _fmt_pct1(profile["Hard Contact %"]))
                st.caption(f"Balls in Play: {profile['Balls in Play']} ({profile['Located']} with a recorded field location).")
        st.divider()
    if my_player.is_pitcher:
        st.markdown("### Pitching")
        if not pitching_pitches:
            empty_state("No pitching data recorded yet for you in Game Tracking.")
        else:
            pitching_line = compute_pitching_line(pitching_pitches)

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
                f"1-2 Barrel: {pitching_line['1-2 Barrel']}"
            )

            st.markdown("**Against**")
            acols = st.columns(3)
            acols[0].metric("OBA", _fmt_num(pitching_line["OBA (opponent AVG)"], 3))
            acols[1].metric("wOBA*", _fmt_num(pitching_line["wOBA"], 3))
            acols[2].metric("AB", pitching_line["AB"])
            st.caption("*wOBA uses generic linear weights, not a season/league-specific set.")

            st.markdown("**Pitch Command / Usage**")
            command = compute_pitcher_command(pitching_pitches)
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
            st.dataframe(compute_pitch_type_breakdown(pitching_pitches), use_container_width=True, hide_index=True)

            st.markdown("**Command Precision**")
            st.caption(
                "Real distance between where you aimed and where it actually crossed the plate -- only counts "
                "pitches reviewed in Video Review (both an intended and an actual location on file)."
            )
            cp_overall, cp_by_type = compute_command_precision(pitching_pitches, throws=my_player.throws)
            if cp_overall["Reviewed"] == 0:
                st.caption("No reviewed pitches yet (needs Video Review).")
            else:
                cp1, cp2, cp3, cp4 = st.columns(4)
                cp1.metric("Avg Miss", f"{cp_overall['Avg Miss (in)']}\"")
                cp2.metric("Reviewed", cp_overall["Reviewed"])
                cp3.metric("Horizontal Bias", f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}")
                cp4.metric("Vertical Bias", f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}")
                st.dataframe(cp_by_type, use_container_width=True, hide_index=True)

            st.markdown("**Attack Zones**")
            st.caption("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.")
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

finally:
    session.close()

page_footer()