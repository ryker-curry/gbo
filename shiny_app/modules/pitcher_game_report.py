"""
GBO -- Pitcher Game Report module.

Direct port of pages/pitcher_game_report.py -- single-game box score +
pitch-type breakdown (Usage/Strike/CSW/Whiff/Chase/Putaway/GB-FB-LD%,
overall and by opponent batter handedness) plus Command Precision and
Attack Zones, all from the exact same game_stats.py/pitch_location_stats.py
functions Analytics/My Stats use, just scoped to one game_id instead of
season/all-time aggregate.

Two-step picker (Game, then Pitcher) -- Game lives in its own render.ui
block; Pitcher (which needs to know who actually threw in that game)
lives in a second block reading it via req("game_select" in input); the
report body lives in a third block reading both. Same
ordering-hazard-safe chain as assessments.py's player/category/
pitch-type-filter sequence.

st.tabs(["All Batters", "vs RHH", "vs LHH"]) -> ui.navset_tab -- the one
new translation-table entry this batch introduces that hasn't come up
in an earlier module yet.
"""

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch
from game_stats import get_pitching_pitches, compute_pitching_line, compute_pitch_type_breakdown
from pitch_location_stats import compute_command_precision, compute_attack_zones

import ui_helpers


def _fmt_pct(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


def _opponent_display_name(g):
    if g.opponent_team:
        return g.opponent_team.team_name
    return g.opponent_name or "Unknown opponent"


def _game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
    return f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status})"


@module.ui
def pitcher_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Game Report"),
        ui.output_ui("game_picker"),
        ui.output_ui("pitcher_picker"),
        ui.output_ui("report_body"),
        ui_helpers.page_footer(),
    )


@module.server
def pitcher_game_report_server(input, output, session, app_state):
    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")

    @render.ui
    def game_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() not in ALLOWED_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            games = db.query(Game).options(joinedload(Game.opponent_team)).order_by(Game.game_date.desc()).all()
            if not games:
                return ui_helpers.empty_state("No games tracked yet. Start one on Game Tracking first.")
            choices = {str(g.game_id): _game_label(g) for g in games}
            return ui.input_select("game_select", "Game", choices=choices)
        finally:
            db.close()

    @render.ui
    def pitcher_picker():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        selected_game_id = int(input.game_select())

        db = get_session()
        try:
            pitcher_ids = [
                pid for (pid,) in db.query(GamePitch.our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(False))
                .distinct().all()
                if pid is not None
            ]
            if not pitcher_ids:
                return ui_helpers.empty_state("No pitches recorded for any of our pitchers in this game yet.")
            pitchers = db.query(Player).filter(Player.player_id.in_(pitcher_ids)).order_by(Player.last_name, Player.first_name).all()
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitchers}
            return ui.input_select("pitcher_select", "Pitcher", choices=choices)
        finally:
            db.close()

    @render.ui
    def report_body():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())

        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == selected_game_id).first()
            pitcher = db.query(Player).filter(Player.player_id == selected_pitcher_id).first()
            if game is None or pitcher is None:
                return None

            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return ui_helpers.empty_state("No pitches for this pitcher in this game.")

            line = compute_pitching_line(pitches)
            sections = [ui.h5(f"{pitcher.first_name} {pitcher.last_name} — {_game_label(game)}", class_="gbo-section-title")]

            sections.append(ui.p(ui.strong("Line")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "IP", "value": str(line["IP"])},
                {"label": "Pitches", "value": str(line["Pitches"])},
                {"label": "K", "value": str(line["K"])},
                {"label": "BB", "value": str(line["BB"])},
                {"label": "H", "value": str(line["H Allowed"])},
                {"label": "R", "value": str(line["Runs Allowed"])},
            ]))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "WHIP", "value": _fmt(line["WHIP"])},
                {"label": "K/BB", "value": _fmt(line["K/BB"])},
                {"label": "K %", "value": _fmt_pct(line["K %"])},
                {"label": "ERA*", "value": _fmt(line["ERA (runs-allowed avg -- ER not tracked)"])},
                {"label": "FIP", "value": _fmt(line["FIP"])},
                {"label": "Execution %", "value": _fmt_pct(line["Execution %"])},
            ]))
            sections.append(ui.p("*ERA here is runs-allowed average, not true ERA -- GBO doesn't distinguish earned from unearned runs yet.", class_="text-muted small"))

            sections.append(ui.p(ui.strong("Count Control")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "Strike %", "value": _fmt_pct(line["Strike %"])},
                {"label": "Early", "value": str(line["Early"])},
                {"label": "Ahead", "value": str(line["Ahead (PA)"])},
                {"label": "E+A %", "value": _fmt_pct(line["E+A %"])},
            ]))
            sections.append(ui.p(f"Pitches/Inning: {_fmt(line['Pitches/Inning'], 1)} · Balls: {line['Balls']} ({_fmt_pct(line['Ball %'])})", class_="text-muted small"))

            sections.append(ui.p(ui.strong("Situational")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "Leadoff Out %", "value": _fmt_pct(line["Leadoff Out %"])},
                {"label": "Leadoff BB", "value": str(line["Leadoff BB"])},
                {"label": "2 Out BB", "value": str(line["2 Out BB"])},
                {"label": "XBH Allowed", "value": str(line["XBH"])},
            ]))
            sections.append(ui.p(
                f"0-2 Hits: {line['0-2 Hits']} · 0-2 Barrel: {line['0-2 Barrel']} · 1-2 Barrel: {line['1-2 Barrel']} · "
                "\"Score\" versions (did that specific walked runner score) aren't computable yet -- "
                "GBO tracks base occupancy, not individual runner identity.",
                class_="text-muted small",
            ))

            sections.append(ui.p(ui.strong("Against")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "OBA", "value": _fmt(line["OBA (opponent AVG)"], 3)},
                {"label": "wOBA*", "value": _fmt(line["wOBA"], 3)},
                {"label": "AB", "value": str(line["AB"])},
            ]))
            sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.", class_="text-muted small"))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Pitch Type Breakdown")))
            vs_rhh = [p for p in pitches if p.opponent_hand == "R"]
            vs_lhh = [p for p in pitches if p.opponent_hand == "L"]
            sections.append(ui.navset_tab(
                ui.nav_panel("All Batters", ui_helpers.render_dict_table(compute_pitch_type_breakdown(pitches))),
                ui.nav_panel("vs RHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_rhh)) if vs_rhh else ui.p("No pitches recorded against a right-handed batter yet.", class_="text-muted small")),
                ui.nav_panel("vs LHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_lhh)) if vs_lhh else ui.p("No pitches recorded against a left-handed batter yet.", class_="text-muted small")),
            ))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Command Precision")))
            sections.append(ui.p(
                "Real distance between where he aimed and where it actually crossed the plate -- only counts "
                "pitches reviewed in Video Review (both an intended and an actual location on file).",
                class_="text-muted small",
            ))
            cp_overall, cp_by_type = compute_command_precision(pitches, throws=pitcher.throws)
            if cp_overall["Reviewed"] == 0:
                sections.append(ui.p("No reviewed pitches yet (needs Video Review).", class_="text-muted small"))
            else:
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Avg Miss", "value": f"{cp_overall['Avg Miss (in)']}\""},
                    {"label": "Reviewed", "value": str(cp_overall["Reviewed"])},
                    {"label": "Horizontal Bias", "value": f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}"},
                    {"label": "Vertical Bias", "value": f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}"},
                ]))
                if pitcher.throws not in ("R", "L"):
                    sections.append(ui.p("Pitcher's throwing hand isn't on file, so horizontal bias shows raw 3B-side/1B-side instead of Arm-side/Glove-side.", class_="text-muted small"))
                sections.append(ui_helpers.render_dict_table(cp_by_type))

            sections.append(ui.p(ui.strong("Attack Zones")))
            sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near. GBO approximation of Statcast's own tiers.", class_="text-muted small"))
            az_overall, az_by_type = compute_attack_zones(pitches)
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
