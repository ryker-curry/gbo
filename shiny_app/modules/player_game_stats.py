"""
GBO -- My Stats module (Player role only).

Direct port of pages/player_game_stats.py -- the player's own batting/
pitching lines from Game Tracking data, filterable by season. Shares
its computation logic unchanged with game_stats.py/plate_discipline.py/
pitch_location_stats.py, same as the original (Analytics' coach-facing
equivalent uses the same functions, so a player's own numbers never
drift from what their coach sees for them).

st.columns(...) + .metric(...) rows become ui_helpers.render_kpi_cards
calls throughout -- same visual job (a row of labeled stat cards), one
consistent helper instead of Shiny's per-widget st.metric equivalent
(which doesn't exist as a single widget the way Streamlit's does).
"""

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, User, Season
from game_stats import (
    get_batting_pitches, get_pitching_pitches, compute_batting_line, compute_pitching_line,
    compute_pitch_type_breakdown, compute_batted_ball_profile,
)
from plate_discipline import compute_hitter_discipline, compute_pitcher_command, compute_zone_tier_discipline
from pitch_location_stats import compute_command_precision, compute_attack_zones

import ui_helpers


def _fmt_pct(value):
    return f"{value:.0f}%" if value is not None else "—"


def _fmt_pct1(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_num(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


@module.ui
def player_game_stats_ui():
    return ui.div(
        ui_helpers.page_header("My Stats"),
        ui.output_ui("season_picker"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_game_stats_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _my_player(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        return db.query(Player).filter(Player.player_id == me.player_id).first()

    @render.ui
    def season_picker():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        db = get_session()
        try:
            if _my_player(db) is None:
                return None
            seasons = db.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
            choices = {"": "-- All seasons --"}
            choices.update({
                str(s.season_id): s.season_name + ("" if s.is_official else " (practice/fall, not official)")
                for s in seasons
            })
            return ui.input_select("season_choice", "Season", choices=choices)
        finally:
            db.close()

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player":
            return ui.p("This page is only available to Player accounts.", class_="text-danger")
        req("season_choice" in input)

        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None:
                return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-muted")

            raw_season = input.season_choice()
            season_choice = int(raw_season) if raw_season else None
            season_label = None
            if season_choice is not None:
                season = db.query(Season).filter(Season.season_id == season_choice).first()
                season_label = season.season_name if season else None

            batting_pitches = get_batting_pitches(db, my_player.player_id, season_choice)
            pitching_pitches = get_pitching_pitches(db, my_player.player_id, season_choice)

            sections = []

            if not my_player.is_pitcher:
                sections.append(ui.h5("Hitting", class_="gbo-section-title"))
                if not batting_pitches:
                    sections.append(ui_helpers.empty_state("No hitting data recorded yet for you in Game Tracking."))
                else:
                    bl = compute_batting_line(batting_pitches)
                    sections.append(ui.p(ui.strong("Line" + (f" — {season_label}" if season_label else " — All seasons"))))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "PA", "value": str(bl["PA"])},
                        {"label": "AB", "value": str(bl["AB"])},
                        {"label": "H", "value": str(bl["H"])},
                        {"label": "BB", "value": str(bl["BB"])},
                        {"label": "K", "value": str(bl["K"])},
                        {"label": "AVG", "value": f"{bl['AVG']:.3f}" if bl["AVG"] is not None else "—"},
                    ]))
                    sections.append(ui.p(
                        f"1B: {bl['1B']} · 2B: {bl['2B']} · 3B: {bl['3B']} · HR: {bl['HR']} · "
                        f"HBP: {bl['HBP']} · Total RV: {bl['Total RV']} · Avg RV/PA: {bl['Avg RV/PA']}",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Slash Line")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "OBP", "value": _fmt_num(bl["OBP"], 3)},
                        {"label": "SLG", "value": _fmt_num(bl["SLG"], 3)},
                        {"label": "OPS", "value": _fmt_num(bl["OPS"], 3)},
                        {"label": "ISO", "value": _fmt_num(bl["ISO"], 3)},
                        {"label": "wOBA*", "value": _fmt_num(bl["wOBA"], 3)},
                    ]))
                    sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set.", class_="text-muted small"))

                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "BB %", "value": _fmt_pct1(bl["BB %"])},
                        {"label": "K %", "value": _fmt_pct1(bl["K %"])},
                        {"label": "BB/K", "value": _fmt_num(bl["BB/K"], 2)},
                    ]))

                    sections.append(ui.p(ui.strong("Situational")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "RISP AVG", "value": _fmt_num(bl["RISP AVG"], 3)},
                        {"label": "2-Strike AVG", "value": _fmt_num(bl["2-Strike AVG"], 3)},
                        {"label": "Leadoff AVG", "value": _fmt_num(bl["Leadoff AVG"], 3)},
                    ]))
                    sections.append(ui.p(
                        f"RISP: {bl['RISP PA']} PA ({bl['RISP AB']} AB) · 2-Strike: {bl['2-Strike PA']} PA "
                        f"({_fmt_pct1(bl['2-Strike K %'])} ended in a K) · Leadoff: {bl['Leadoff PA']} PA",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Plate Discipline")))
                    discipline = compute_hitter_discipline(batting_pitches)
                    if discipline["Pitches Seen"] == 0:
                        sections.append(ui.p("No pitches seen yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Zone %", "value": _fmt_pct(discipline["Zone %"])},
                            {"label": "Swing %", "value": _fmt_pct(discipline["Swing %"])},
                            {"label": "Chase %", "value": _fmt_pct(discipline["Chase %"])},
                            {"label": "Whiff %", "value": _fmt_pct(discipline["Whiff %"])},
                            {"label": "1st-Pitch Swing %", "value": _fmt_pct(discipline["First-Pitch Swing %"])},
                        ]))
                        sections.append(ui.p(
                            f"Zone Swing %: {_fmt_pct(discipline['Zone Swing %'])} · Zone Contact %: {_fmt_pct(discipline['Zone Contact %'])} · "
                            f"Chase Contact %: {_fmt_pct(discipline['Chase Contact %'])} · Pitches Seen: {discipline['Pitches Seen']} "
                            f"({discipline['Located Pitches']} with a recorded location)",
                            class_="text-muted small",
                        ))

                    sections.append(ui.p(ui.strong("Zone-Tier Discipline")))
                    sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                    sections.append(ui_helpers.render_dict_table(compute_zone_tier_discipline(batting_pitches)))

                    sections.append(ui.p(ui.strong("Batted-Ball Profile")))
                    profile = compute_batted_ball_profile(batting_pitches, bats=my_player.bats)
                    if profile["Balls in Play"] == 0:
                        sections.append(ui.p("No balls in play yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Ground Ball %", "value": _fmt_pct1(profile["Ground Ball %"])},
                            {"label": "Fly Ball %", "value": _fmt_pct1(profile["Fly Ball %"])},
                            {"label": "Line Drive %", "value": _fmt_pct1(profile["Line Drive %"])},
                            {"label": "Pop Up %", "value": _fmt_pct1(profile["Pop Up %"])},
                        ]))
                        if profile["Spray Mode"] == "Pull/Center/Oppo":
                            sections.append(ui_helpers.render_kpi_cards([
                                {"label": "Pull %", "value": _fmt_pct1(profile["Pull %"])},
                                {"label": "Center %", "value": _fmt_pct1(profile["Center %"])},
                                {"label": "Oppo %", "value": _fmt_pct1(profile["Oppo %"])},
                            ]))
                        else:
                            sections.append(ui_helpers.render_kpi_cards([
                                {"label": "Left Field %", "value": _fmt_pct1(profile["Left Field %"])},
                                {"label": "Center %", "value": _fmt_pct1(profile["Center %"])},
                                {"label": "Right Field %", "value": _fmt_pct1(profile["Right Field %"])},
                            ]))
                            sections.append(ui.p("Your bats hand isn't on file (or switch-hitter), so this shows raw field side instead of Pull/Oppo.", class_="text-muted small"))
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Barrel %", "value": _fmt_pct1(profile["Barrel %"])},
                            {"label": "Hard Contact %", "value": _fmt_pct1(profile["Hard Contact %"])},
                        ]))
                        sections.append(ui.p(f"Balls in Play: {profile['Balls in Play']} ({profile['Located']} with a recorded field location).", class_="text-muted small"))
                sections.append(ui.hr())

            if my_player.is_pitcher:
                sections.append(ui.h5("Pitching", class_="gbo-section-title"))
                if not pitching_pitches:
                    sections.append(ui_helpers.empty_state("No pitching data recorded yet for you in Game Tracking."))
                else:
                    pl = compute_pitching_line(pitching_pitches)

                    sections.append(ui.p(ui.strong("Line" + (f" — {season_label}" if season_label else " — All seasons"))))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "IP", "value": str(pl["IP"])},
                        {"label": "Pitches", "value": str(pl["Pitches"])},
                        {"label": "K", "value": str(pl["K"])},
                        {"label": "BB", "value": str(pl["BB"])},
                        {"label": "H", "value": str(pl["H Allowed"])},
                        {"label": "R", "value": str(pl["Runs Allowed"])},
                    ]))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "WHIP", "value": _fmt_num(pl["WHIP"])},
                        {"label": "K/BB", "value": _fmt_num(pl["K/BB"])},
                        {"label": "K %", "value": _fmt_pct1(pl["K %"])},
                        {"label": "ERA*", "value": _fmt_num(pl["ERA (runs-allowed avg -- ER not tracked)"])},
                        {"label": "FIP", "value": _fmt_num(pl["FIP"])},
                        {"label": "Execution %", "value": _fmt_pct1(pl["Execution %"])},
                    ]))
                    sections.append(ui.p(
                        f"*ERA here is runs-allowed average, not true ERA -- GBO doesn't distinguish earned from unearned runs yet. "
                        f"Total RV Allowed: {pl['Total RV Allowed']} · Avg RV Allowed/Pitch: {pl['Avg RV Allowed/Pitch']}",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Count Control")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Strike %", "value": _fmt_pct1(pl["Strike %"])},
                        {"label": "Early", "value": str(pl["Early"])},
                        {"label": "Ahead", "value": str(pl["Ahead (PA)"])},
                        {"label": "E+A %", "value": _fmt_pct1(pl["E+A %"])},
                    ]))
                    sections.append(ui.p(
                        f"Pitches/Inning: {_fmt_num(pl['Pitches/Inning'], 1)} · Balls: {pl['Balls']} ({_fmt_pct1(pl['Ball %'])})",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Situational")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Leadoff Out %", "value": _fmt_pct1(pl["Leadoff Out %"])},
                        {"label": "Leadoff BB", "value": str(pl["Leadoff BB"])},
                        {"label": "2 Out BB", "value": str(pl["2 Out BB"])},
                        {"label": "XBH Allowed", "value": str(pl["XBH"])},
                    ]))
                    sections.append(ui.p(
                        f"0-2 Hits: {pl['0-2 Hits']} · 0-2 Barrel: {pl['0-2 Barrel']} · 1-2 Barrel: {pl['1-2 Barrel']}",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Against")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "OBA", "value": _fmt_num(pl["OBA (opponent AVG)"], 3)},
                        {"label": "wOBA*", "value": _fmt_num(pl["wOBA"], 3)},
                        {"label": "AB", "value": str(pl["AB"])},
                    ]))
                    sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set.", class_="text-muted small"))

                    sections.append(ui.p(ui.strong("Pitch Command / Usage")))
                    command = compute_pitcher_command(pitching_pitches)
                    if command["Pitches Thrown"] == 0:
                        sections.append(ui.p("No pitches thrown yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Zone %", "value": _fmt_pct(command["Zone %"])},
                            {"label": "Whiff % Induced", "value": _fmt_pct(command["Whiff % Induced"])},
                            {"label": "Chase % Induced", "value": _fmt_pct(command["Chase % Induced"])},
                        ]))
                        sections.append(ui.p(f"Pitches Thrown: {command['Pitches Thrown']} ({command['Located Pitches']} with a recorded location)", class_="text-muted small"))
                        if command["Usage %"]:
                            usage_str = " · ".join(f"{name}: {_fmt_pct(pct)}" for name, pct in sorted(command["Usage %"].items(), key=lambda kv: -(kv[1] or 0)))
                            sections.append(ui.p(f"Usage — {usage_str}", class_="text-muted small"))

                    sections.append(ui.p(ui.strong("Pitch Type Breakdown")))
                    sections.append(ui_helpers.render_dict_table(compute_pitch_type_breakdown(pitching_pitches)))

                    sections.append(ui.p(ui.strong("Command Precision")))
                    sections.append(ui.p(
                        "Real distance between where you aimed and where it actually crossed the plate -- only counts "
                        "pitches reviewed in Video Review (both an intended and an actual location on file).",
                        class_="text-muted small",
                    ))
                    cp_overall, cp_by_type = compute_command_precision(pitching_pitches, throws=my_player.throws)
                    if cp_overall["Reviewed"] == 0:
                        sections.append(ui.p("No reviewed pitches yet (needs Video Review).", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Avg Miss", "value": f"{cp_overall['Avg Miss (in)']}\""},
                            {"label": "Reviewed", "value": str(cp_overall["Reviewed"])},
                            {"label": "Horizontal Bias", "value": f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}"},
                            {"label": "Vertical Bias", "value": f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}"},
                        ]))
                        sections.append(ui_helpers.render_dict_table(cp_by_type))

                    sections.append(ui.p(ui.strong("Attack Zones")))
                    sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                    az_overall, az_by_type = compute_attack_zones(pitching_pitches)
                    if az_overall["Located"] == 0:
                        sections.append(ui.p("No located pitches yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Heart %", "value": _fmt_pct(az_overall["Heart %"])},
                            {"label": "Shadow %", "value": _fmt_pct(az_overall["Shadow %"])},
                            {"label": "Chase Zone %", "value": _fmt_pct(az_overall["Chase Zone %"])},
                            {"label": "Waste %", "value": _fmt_pct(az_overall["Waste %"])},
                        ]))
                        sections.append(ui_helpers.render_dict_table(az_by_type))

            return ui.div(*sections)
        finally:
            db.close()
