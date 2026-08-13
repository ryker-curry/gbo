"""
GBO — Hitter Game Report (single-game slash line + batted-ball profile
+ zone-tier discipline).

Batting-side counterpart to pages/pitcher_game_report.py -- pick one
game and one batter, see the full box-score-style line (AVG/OBP/SLG/
OPS/ISO/wOBA, BB%/K%/BB-K, RISP/2-Strike/Leadoff situational splits)
plus the batted-ball profile (GB/FB/LD/Pop-Up%, Pull/Center/Oppo%,
Barrel%/Hard-Contact%) and zone-tier plate discipline (Heart/Shadow/
Chase/Waste swing%/whiff%/contact%).

Shares every computation with Analytics/My Stats via game_stats.py
(get_batting_pitches(..., game_id=...), compute_batting_line(),
compute_batted_ball_profile()) and plate_discipline.py
(compute_zone_tier_discipline()) -- nothing here is computed a second,
possibly-drifting way, same principle as the pitching side.

Known gaps/assumptions, not silently guessed:
  - Pull/Center/Oppo uses the standard 30/30/30-degree spray-angle
    split (see field_location.classify_spray_direction) -- a
    documented convention, not Ryker-confirmed to the inch, easy to
    adjust if he wants different boundaries.
  - Switch-hitters (bats == 'S') and batters with no bats on file get
    side-neutral Left/Right Field labels instead of Pull/Oppo, since
    GBO doesn't track which side a switch-hitter actually batted from
    on a given PA.
  - Barrel %/Hard-Contact % use the coach's own live "Barrel/Solid/
    Weak/Miss" call (contact_quality) -- GBO has no exit-velocity
    radar, so this is not a measured Statcast Barrel.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch
from ui_components import page_header, page_footer, empty_state
from game_stats import get_batting_pitches, compute_batting_line, compute_batted_ball_profile
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline

page_header("Hitter Game Report")

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


def _fmt(value, decimals=3):
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

    # Every one of OUR players who batted at least once in this game --
    # same pattern as pitcher_game_report.py's pitcher picker (queries
    # our_player_id directly rather than the lineup, since substitutions
    # mean more than one player can occupy a batting slot in a game).
    batter_ids = [
        pid for (pid,) in session.query(GamePitch.our_player_id)
        .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(True))
        .distinct()
        .all()
        if pid is not None
    ]
    if not batter_ids:
        empty_state("No pitches recorded for any of our batters in this game yet.")
        page_footer()
        st.stop()

    batters = session.query(Player).filter(Player.player_id.in_(batter_ids)).order_by(Player.last_name, Player.first_name).all()
    batters_by_id = {p.player_id: p for p in batters}
    selected_batter_id = st.selectbox(
        "Batter", options=list(batters_by_id.keys()),
        format_func=lambda pid: f"{batters_by_id[pid].first_name} {batters_by_id[pid].last_name}",
    )
    selected_batter = batters_by_id[selected_batter_id]

    st.divider()
    st.subheader(f"{selected_batter.first_name} {selected_batter.last_name} — {_game_label(selected_game_id)}")

    pitches = get_batting_pitches(session, selected_batter_id, game_id=selected_game_id)
    if not pitches:
        empty_state("No pitches for this batter in this game.")
        page_footer()
        st.stop()

    line = compute_batting_line(pitches)

    st.markdown("**Line**")
    cols = st.columns(6)
    cols[0].metric("PA", line["PA"])
    cols[1].metric("AB", line["AB"])
    cols[2].metric("H", line["H"])
    cols[3].metric("BB", line["BB"])
    cols[4].metric("K", line["K"])
    cols[5].metric("AVG", _fmt(line["AVG"]))
    st.caption(
        f"1B: {line['1B']} · 2B: {line['2B']} · 3B: {line['3B']} · HR: {line['HR']} · HBP: {line['HBP']} · "
        f"Total RV: {line['Total RV']} · Avg RV/PA: {line['Avg RV/PA']}"
    )

    st.markdown("**Slash Line**")
    scols = st.columns(5)
    scols[0].metric("OBP", _fmt(line["OBP"]))
    scols[1].metric("SLG", _fmt(line["SLG"]))
    scols[2].metric("OPS", _fmt(line["OPS"]))
    scols[3].metric("ISO", _fmt(line["ISO"]))
    scols[4].metric("wOBA*", _fmt(line["wOBA"]))
    st.caption("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.")

    st.markdown("**Plate Discipline**")
    dcols = st.columns(3)
    dcols[0].metric("BB %", _fmt_pct(line["BB %"]))
    dcols[1].metric("K %", _fmt_pct(line["K %"]))
    dcols[2].metric("BB/K", _fmt(line["BB/K"], 2))

    st.markdown("**Situational**")
    sitcols = st.columns(3)
    sitcols[0].metric("RISP AVG", _fmt(line["RISP AVG"]))
    sitcols[1].metric("2-Strike AVG", _fmt(line["2-Strike AVG"]))
    sitcols[2].metric("Leadoff AVG", _fmt(line["Leadoff AVG"]))
    st.caption(
        f"RISP: {line['RISP PA']} PA ({line['RISP AB']} AB) · 2-Strike: {line['2-Strike PA']} PA "
        f"({_fmt_pct(line['2-Strike K %'])} ended in a K) · Leadoff: {line['Leadoff PA']} PA"
    )

    st.divider()
    st.markdown("**Plate Discipline (Zone)**")
    discipline = compute_hitter_discipline(pitches)
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
    tier_rows = compute_zone_tier_discipline(pitches)
    st.dataframe(tier_rows, use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**Batted-Ball Profile**")
    profile = compute_batted_ball_profile(pitches, bats=selected_batter.bats)
    if profile["Balls in Play"] == 0:
        st.caption("No balls in play yet.")
    else:
        bcols = st.columns(4)
        bcols[0].metric("Ground Ball %", _fmt_pct(profile["Ground Ball %"]))
        bcols[1].metric("Fly Ball %", _fmt_pct(profile["Fly Ball %"]))
        bcols[2].metric("Line Drive %", _fmt_pct(profile["Line Drive %"]))
        bcols[3].metric("Pop Up %", _fmt_pct(profile["Pop Up %"]))

        bcols2 = st.columns(3)
        if profile["Spray Mode"] == "Pull/Center/Oppo":
            bcols2[0].metric("Pull %", _fmt_pct(profile["Pull %"]))
            bcols2[1].metric("Center %", _fmt_pct(profile["Center %"]))
            bcols2[2].metric("Oppo %", _fmt_pct(profile["Oppo %"]))
        else:
            bcols2[0].metric("Left Field %", _fmt_pct(profile["Left Field %"]))
            bcols2[1].metric("Center %", _fmt_pct(profile["Center %"]))
            bcols2[2].metric("Right Field %", _fmt_pct(profile["Right Field %"]))
            st.caption("Batter's hand isn't on file (or switch-hitter), so this shows raw field side instead of Pull/Oppo.")

        bcols3 = st.columns(2)
        bcols3[0].metric("Barrel %", _fmt_pct(profile["Barrel %"]))
        bcols3[1].metric("Hard Contact %", _fmt_pct(profile["Hard Contact %"]))
        st.caption(f"Balls in Play: {profile['Balls in Play']} ({profile['Located']} with a recorded field location).")

finally:
    session.close()

page_footer()
