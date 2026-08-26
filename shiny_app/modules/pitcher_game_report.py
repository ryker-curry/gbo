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
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch
from game_stats import get_pitching_pitches, compute_pitching_line, compute_pitch_type_breakdown
from pitch_location_stats import compute_command_precision, compute_attack_zones
# Target-radius bands (Precision/Command/Competitive/Major Miss) and the
# concentric-ring chart, reused as-is from Command Tracker rather than a
# second implementation -- game_pitches_command_view() adapts a game
# pitcher's own GamePitch rows (intended_plate_x/z/actual_plate_x/z) into
# the same duck-typed shape session_command_scorecard/command_by_pitch_type
# and command_chart() already expect, with NO CommandPitch schema change
# or mirrored rows (see that function's own docstring for why). Existing
# Command Precision/Attack Zones above are untouched, computed the way
# they always have been -- this is a new, additional section, not a
# replacement.
from analytics import command_metrics
from visualizations import command_charts

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
        ui.output_ui("command_target_section"),
        ui_helpers.page_footer(),
    )


@module.server
def pitcher_game_report_server(input, output, session, app_state):
    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

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
            our_pitcher_ids = {
                pid for (pid,) in db.query(GamePitch.our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(False))
                .distinct().all()
                if pid is not None
            }
            # Intrasquad games: the "other side" is also our own roster (Squad B),
            # recorded as opponent_our_player_id while we're batting -- include
            # those pitchers too so BOTH squads' pitchers show up here, since in
            # an intrasquad game every pitcher belongs to our own team either way.
            other_squad_pitcher_ids = {
                pid for (pid,) in db.query(GamePitch.opponent_our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(True))
                .distinct().all()
                if pid is not None
            }
            pitcher_ids = our_pitcher_ids | other_squad_pitcher_ids
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

    # -------------------------------------------------------------------
    # Command Target Zones -- Command Tracker's own scorecard/table/chart
    # (analytics/command_metrics.py's session_command_scorecard/
    # command_by_pitch_type/miss_bias + visualizations/command_charts.
    # command_chart()), fed this game's own GamePitch rows adapted through
    # command_metrics.game_pitches_command_view() instead of a second,
    # parallel bullpen-only implementation. A new, additional section
    # placed AFTER Attack Zones -- Command Precision/Attack Zones above
    # (pitch_location_stats.py) are completely untouched. Only pitches
    # with an intended location count here (game_pitches_command_view()
    # excludes any without one -- i.e. a real external opponent's
    # pitches, whose intent GBO never captures; see game_tracking.py's
    # show_intended), so for a real-opponent game this section stays
    # empty even though Command Precision above (which only needs
    # intended+actual together anyway) would too. Same three-block
    # render.ui-wrapper / render_plotly / render.ui-table split as
    # hitter_game_report.py's Contact Quality by Zone / Pitch Type
    # section, for the same reason: a render_plotly output needs its own
    # registered function, not one nested inside report_body's render.ui.
    # -------------------------------------------------------------------

    def _selected_pitcher_view_pitches(db):
        if "game_select" not in input or "pitcher_select" not in input:
            return None, None
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None, None
        pitcher = db.query(Player).filter(Player.player_id == int(pitcher_id_raw)).first()
        if pitcher is None:
            return None, None
        pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
        if not pitches:
            return None, None
        return command_metrics.game_pitches_command_view(pitches, pitcher.throws), pitcher.throws

    def _team_command_plus_baseline(db):
        """Every located pitch, across every game (intrasquad and real
        opponents alike -- fall scrimmages and the spring season both),
        from our own pitchers -- Ryker's 2026-08-23 call on what counts
        as "the team" for Command+: games only, not bullpen sessions,
        and not scoped to just intrasquad. A real-opponent game's DOES
        count for our own pitcher's outings in it -- only the opposing
        pitcher's pitches are excluded, and that's already handled
        automatically by the DB filter below: intended_plate_x is only
        ever set for our own pitcher in the first place (see
        game_tracking.py's show_intended), never for an opponent's.
        Not scoped to a season/date range yet -- all-time across every
        game currently in the system; worth revisiting once "all-time"
        and "this season" start to meaningfully diverge.

        throws=None is safe here even though these pitches span many
        different pitchers' hands -- danger_adjusted_miss doesn't depend
        on throws at all (only the miss_direction/within_*_target labels
        do, neither of which this baseline needs).

        Returns (mean, stdev, n) from
        command_metrics.team_command_plus_baseline."""
        all_pitches = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
        view_pitches = command_metrics.game_pitches_command_view(all_pitches, None)
        return command_metrics.team_command_plus_baseline(view_pitches)

    def _cmd_fmt(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "—"

    def _cmd_bias_label(bias):
        parts = []
        if bias["horizontal_bias_in"] is not None:
            parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
        if bias["vertical_bias_in"] is not None:
            parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
        return " / ".join(parts) if parts else "—"

    @render.ui
    def command_target_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        db = get_session()
        try:
            view_pitches, _throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Command Target Zones")),
                ui.p(
                    "Same Precision/Command/Competitive target-radius bands and concentric-ring chart Command "
                    "Tracker uses -- built from this game's own intended-vs-actual pitch locations, no separate "
                    "math. Only pitches with a logged intended location count (a real opponent's pitcher never has "
                    "one on file).",
                    class_="text-muted small",
                ),
                ui.output_ui("command_target_table"),
                output_widget("command_target_chart"),
            )
        finally:
            db.close()

    @render.ui
    def command_target_table():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None

            scorecard = command_metrics.session_command_scorecard(view_pitches)
            if scorecard["located_pitches"] == 0:
                return ui.p("No pitches have an actual location recorded yet -- needs Video Review.", class_="text-muted small")

            baseline_mean, baseline_stdev, baseline_n = _team_command_plus_baseline(db)
            command_plus_value = None
            if baseline_n >= command_metrics.MIN_BASELINE_PITCHES:
                command_plus_value = command_metrics.command_plus(scorecard["avg_danger_adjusted_miss"], baseline_mean, baseline_stdev)

            children = [ui_helpers.render_kpi_cards([
                {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
                {"label": "Command+", "value": _cmd_fmt(command_plus_value)},
                {"label": "Avg Miss", "value": _cmd_fmt(scorecard["avg_miss_distance"], " in")},
                {"label": "Danger-Adj. Miss", "value": _cmd_fmt(scorecard["avg_danger_adjusted_miss"], " in")},
                {"label": "Median Miss", "value": _cmd_fmt(scorecard["median_miss_distance"], " in")},
                {"label": "Precision %", "value": _cmd_fmt(scorecard["precision_pct"], "%")},
                {"label": "Command Target %", "value": _cmd_fmt(scorecard["command_target_pct"], "%")},
                {"label": "Competitive %", "value": _cmd_fmt(scorecard["competitive_pct"], "%")},
                {"label": "Major Miss %", "value": _cmd_fmt(scorecard["major_miss_pct"], "%")},
            ])]
            if command_plus_value is not None:
                children.append(ui.p(
                    "Command+: 100 = your own team's average across every located pitch in every game so far -- "
                    "not an MLB comparison, GBO doesn't have access to league-wide pitch data. Above 100 is better "
                    "than your team's own average, below is worse.",
                    class_="text-muted small",
                ))
            else:
                children.append(ui.p(
                    f"Command+ needs at least {command_metrics.MIN_BASELINE_PITCHES} located pitches across all your "
                    f"team's games (any pitcher, any game) to form a stable baseline -- {baseline_n} so far. 100 will "
                    "mean your own team's average, not an MLB comparison -- GBO doesn't have access to league-wide "
                    "pitch data.",
                    class_="text-muted small",
                ))

            bias = command_metrics.miss_bias(view_pitches, throws)
            children.append(ui.p(f"Average miss bias: {_cmd_bias_label(bias)}", class_="text-muted small mt-2"))

            by_type = command_metrics.command_by_pitch_type(view_pitches, throws)
            if len(by_type) > 1:
                rows = [{
                    "Pitch Type": row["Pitch Type"],
                    "Pitches": row["Pitches"],
                    "Avg Miss (in)": row["Avg Miss"] if row["Avg Miss"] is not None else "—",
                    "Danger-Adj. Miss (in)": row["Danger-Adj. Miss"] if row["Danger-Adj. Miss"] is not None else "—",
                    "Precision %": row["Precision %"] if row["Precision %"] is not None else "—",
                    "Command %": row["Command Target %"] if row["Command Target %"] is not None else "—",
                    "Major Miss %": row["Major Miss %"] if row["Major Miss %"] is not None else "—",
                    "Miss Bias": _cmd_bias_label(row["Miss Bias"]),
                } for row in by_type]
                children.append(ui.h6("By pitch type", class_="mt-3"))
                children.append(ui_helpers.render_dict_table(rows))

            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def command_target_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, _throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            located = [p for p in view_pitches if p.horizontal_miss is not None]
            if not located:
                return None
            return command_charts.command_chart(view_pitches)
        finally:
            db.close()
