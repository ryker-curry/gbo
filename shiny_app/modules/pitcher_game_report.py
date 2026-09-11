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
import plotly.graph_objects as go

from database import get_session
from models import Player, Game, GamePitch, RapsodoPitch
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
from analytics import command_metrics, profile_queries
from analytics.pitch_grading import stuff_plus, arsenal_summary, MIN_BASELINE_PITCHES
from analytics.bullpen_metrics import (
    average_estimated_arm_angle, pitch_type_label,
    _pitch_level_vaa, _pitch_level_haa, _avg_pitch_level,
)
from visualizations import command_charts
from visualizations.bullpen_charts import movement_chart, color_for_pitch_label
from visualizations.pitcher_graphic import pitcher_release_svg
from visualizations.chart_theme import apply_gbo_theme, MUTED_GRAY, TEXT_CREAM

import strike_zone
import chart_helpers
import ui_helpers
import format_helpers
from format_helpers import (
    format_pct as _fmt_pct,
    format_num as _fmt,
    opponent_display_name as _opponent_display_name,
    game_label as _game_label,
)


def _fmt_grade(value):
    return f"{value:.1f}" if value is not None else "—"


def _pitch_type_breakdown_with_stuff(pitches_subset, rap_by_gp, stuff_baselines):
    """compute_pitch_type_breakdown()'s rows, with a "Stuff+"/"Stuff+
    Reliable" column merged on by matching "Pitch Type" -- the Pitch
    Frequency by handedness panel from STUFF-LOCATION-PITCHING-PLUS-
    PLAN.md section 10, minus the Location+/Pitching+ half (Attack
    Zones below already covers location; Stuff+ is what's genuinely
    new here). rap_by_gp/stuff_baselines are precomputed once by the
    caller (analytics/profile_queries.py, same team-wide baseline
    Pitcher Profile's Arsenal table uses) and reused across all three
    tabs rather than requeried per tab.

    Reuses pitch_grading.arsenal_summary() for the per-type average +
    MIN_BASELINE_PITCHES reliability flag instead of a second rollup
    implementation -- same "n pitches of that type in THIS window"
    floor as the Arsenal table, which for a single outing will read
    "No" for most types (a start rarely throws 20+ of a given
    secondary pitch) -- shown anyway, not hidden, same small-sample
    philosophy as everywhere else this scale is used."""
    base_rows = compute_pitch_type_breakdown(pitches_subset)

    pitch_type_grades = {}
    for p in pitches_subset:
        if p.pitch_type is None:
            continue
        rap = rap_by_gp.get(p.game_pitch_id)
        if rap is None:
            continue
        label = p.pitch_type.type_name
        s_val = stuff_plus(rap, stuff_baselines.get(label))
        if s_val is None:
            continue
        pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
        pitch_type_grades[label]["n"] += 1
        pitch_type_grades[label]["stuff_plus"].append(s_val)

    stuff_by_label = {row["Pitch Type"]: (row["Stuff+"], row["Reliable"]) for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}
    all_stuff_vals = [v for g in pitch_type_grades.values() for v in g["stuff_plus"]]
    total_stuff = round(sum(all_stuff_vals) / len(all_stuff_vals), 1) if all_stuff_vals else None
    total_reliable = len(all_stuff_vals) >= MIN_BASELINE_PITCHES

    out_rows = []
    for row in base_rows:
        row = dict(row)
        if row["Pitch Type"] == "Total":
            s_val, reliable = total_stuff, total_reliable
        else:
            s_val, reliable = stuff_by_label.get(row["Pitch Type"], (None, False))
        row["Stuff+"] = _fmt_grade(s_val)
        row["Stuff+ Reliable"] = "Yes" if (s_val is not None and reliable) else "No"
        out_rows.append(row)
    return out_rows


def _pitch_shape_rows(pitches, rap_by_gp, stuff_baselines, pitcher):
    """Physical pitch-shape table for the Pitch Shape (Rapsodo) section
    (Ryker's Pitch Profiler-style reference, Sept 2026): Velocity/Spin
    Rate/IVB/HB/VAA/HAA/vRel/hRel/Ext/Arm deg, plus Stuff+ and Whiff %,
    one row per pitch type actually thrown -- grouped by the coach's own
    charted GamePitch.pitch_type (not Rapsodo's independent auto-
    classification), same convention as _pitch_type_breakdown_with_stuff
    above, since Usage %/Whiff % are GamePitch-outcome facts that need
    to agree with the rest of the page. Physical columns only average
    the subset of that type's pitches with a Rapsodo reading linked
    (rap_by_gp) -- a charted type with no Rapsodo match yet shows
    Usage %/Whiff % from the charted count and "--" for every physical
    column, same "shown anyway" philosophy as elsewhere, rather than
    being dropped from the table.

    No separate Barrel % column -- GBO doesn't track batted-ball
    exit velocity/launch angle, so there's no GBO equivalent to
    substitute (Ryker's own call: substitute a real GBO equivalent
    where one exists, skip what doesn't rather than fabricating it).

    Stuff+ reuses pitch_grading.stuff_plus/arsenal_summary against the
    same team-wide baseline as the Arsenal table and Pitch Type
    Breakdown above -- not a second Stuff+ computation. Small-sample
    reality: MIN_BASELINE_PITCHES is 20, and a single outing rarely
    throws 20+ of a secondary pitch, so most Stuff+ values here will be
    on a thin sample -- shown anyway rather than hidden, with a caption
    below the table flagging the floor, same convention as
    _pitch_type_breakdown_with_stuff's own "Reliable" column."""
    base_rows = {row["Pitch Type"]: row for row in compute_pitch_type_breakdown(pitches) if row["Pitch Type"] != "Total"}

    type_order = []
    rapsodo_groups = {}
    for p in pitches:
        if p.pitch_type is None:
            continue
        label = p.pitch_type.type_name
        if label not in rapsodo_groups:
            rapsodo_groups[label] = []
            type_order.append(label)
        rap = rap_by_gp.get(p.game_pitch_id)
        if rap is not None:
            rapsodo_groups[label].append(rap)

    pitch_type_grades = {}
    for label, raps in rapsodo_groups.items():
        for rap in raps:
            s_val = stuff_plus(rap, stuff_baselines.get(label))
            if s_val is None:
                continue
            grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
            grp["n"] += 1
            grp["stuff_plus"].append(s_val)
    stuff_by_label = {row["Pitch Type"]: row["Stuff+"] for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}

    def _avg_field(raps, field, decimals=1):
        vals = [float(getattr(r, field)) for r in raps if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), decimals) if vals else None

    def _d(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "—"

    rows = []
    for label in type_order:
        raps = rapsodo_groups[label]
        base = base_rows.get(label, {})
        arm_angle, _n = average_estimated_arm_angle(raps, pitcher)
        rows.append({
            "Pitch Type": label,
            "% Thrown": _d(base.get("Pitch Usage %"), "%"),
            "Velocity": _d(_avg_field(raps, "velocity"), " mph"),
            "Spin Rate": _d(_avg_field(raps, "total_spin", 0), " rpm"),
            "IVB": _d(_avg_field(raps, "vb_spin"), '"'),
            "HB": _d(_avg_field(raps, "hb_spin"), '"'),
            "VAA": _d(_avg_pitch_level([_pitch_level_vaa(r)["value_degrees"] for r in raps])[0], "° (est.)"),
            "HAA": _d(_avg_pitch_level([_pitch_level_haa(r)["value_degrees"] for r in raps])[0], "° (est.)"),
            "vRel": _d(_avg_field(raps, "release_height"), "'"),
            "hRel": _d(_avg_field(raps, "release_side"), "'"),
            "Ext": _d(_avg_field(raps, "release_extension"), "'"),
            "Arm°": _d(round(arm_angle) if arm_angle is not None else None, "°"),
            "Stuff+": _d(stuff_by_label.get(label)),
            "Whiff %": _d(base.get("Whiff %"), "%"),
        })
    return rows


def _pitch_location_figure(intended_x, intended_z, actual_x, actual_z, color):
    """Compact single-pitch intended-vs-actual location figure for the
    Pitch-by-Pitch detail card (Ryker, Sept 2026: "add like how we
    have in [Command Tracking] where we can see intended location and
    then actual location and it shows the distance between with a
    line"). Mirrors visualizations/command_charts.pitch_locations_chart's
    established styling -- dotted gray connecting line drawn first
    (layer="below"), hollow-ring marker for intended, filled marker
    for actual, both colored by pitch type -- but scaled down to a
    single pitch and a small fixed-size image (this renders via
    chart_helpers.fig_to_img, same static-PNG pattern as the rest of
    this per-selection card) rather than the full multi-pitch chart
    with its batter silhouettes and legend, which wouldn't read at
    280x280.

    intended_x/z and actual_x/z are floats already, in the same
    plate-coordinate feet used by strike_zone.py's zone constants;
    actual_x/z may be None if the pitch has no recorded location yet,
    in which case only the intended point is drawn."""
    fig = go.Figure()

    if actual_x is not None and actual_z is not None:
        fig.add_shape(
            type="line", xref="x", yref="y",
            x0=intended_x, y0=intended_z, x1=actual_x, y1=actual_z,
            line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below",
        )

    fig.add_trace(go.Scatter(
        x=[intended_x], y=[intended_z], mode="markers",
        marker=dict(symbol="circle-open", color=color, size=22, line=dict(color=color, width=3)),
        name="Intended", showlegend=True, hoverinfo="skip",
    ))
    if actual_x is not None and actual_z is not None:
        fig.add_trace(go.Scatter(
            x=[actual_x], y=[actual_z], mode="markers",
            marker=dict(symbol="circle", color=color, size=22, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            name="Actual", showlegend=True, hoverinfo="skip",
        ))

    fig.add_shape(
        type="rect", x0=-strike_zone.ZONE_HALF_WIDTH, x1=strike_zone.ZONE_HALF_WIDTH,
        y0=strike_zone.ZONE_BOTTOM, y1=strike_zone.ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )

    apply_gbo_theme(
        fig, height=280, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(range=[-2.0, 2.0], visible=False, fixedrange=True),
        yaxis=dict(range=[0.5, 4.5], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", y=-0.05, font=dict(size=10)),
    )
    return fig


@module.ui
def pitcher_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Game Report"),
        ui.output_ui("game_picker"),
        ui.output_ui("pitcher_picker"),
        ui.output_ui("report_body"),
        # Everything below is one of the "View" dropdown's sections --
        # each of these render.ui functions gates itself on
        # input.report_section() and returns None when not selected, so
        # only the chosen section actually queries the DB/builds charts
        # (see report_section_picker below). All five stay statically
        # listed here (Shiny needs a placeholder in the DOM for each
        # output id), same as report_body/command_target_section/
        # rapsodo_shape_section always were -- the change is what each
        # function does internally, not whether it's wired up.
        ui.output_ui("report_section_picker"),
        ui.output_ui("pitch_type_breakdown_section"),
        ui.output_ui("command_execution_section"),
        ui.output_ui("command_target_section"),
        ui.output_ui("rapsodo_shape_section"),
        ui.output_ui("pitch_by_pitch_section"),
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

            # Pitch Type Breakdown / Command Precision / Attack Zones /
            # Command Target Zones / Pitch Shape (Rapsodo) used to all be
            # appended here too, making this one continuously-scrolling
            # page. They're now each their own gated section, chosen via
            # the "View" dropdown (report_section_picker) below, so only
            # one renders (and queries the DB) at a time -- Ryker's Sept
            # 2026 report request. See pitch_type_breakdown_section/
            # command_execution_section/command_target_section/
            # rapsodo_shape_section/pitch_by_pitch_section.
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def report_section_picker():
        """The "View" dropdown driving which of the five sections below
        actually renders. Default (first dict entry, Python preserves
        insertion order) is Pitch Type Breakdown -- each gated section
        function checks input.report_section() itself and returns None
        immediately when not selected, before doing any query, so
        switching this dropdown is what stops the DB work for the other
        four, not CSS visibility."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.input_select(
                    "report_section", "View",
                    choices={
                        "pitch_type_breakdown": "Pitch Type Breakdown",
                        "command_execution": "Command & Execution",
                        "pitch_shape": "Pitch Shape / Rapsodo",
                        "pitch_by_pitch": "Pitch-by-Pitch",
                    },
                ),
            )
        finally:
            db.close()

    @render.ui
    def pitch_type_breakdown_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_type_breakdown":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return None
            vs_rhh = [p for p in pitches if p.opponent_hand == "R"]
            vs_lhh = [p for p in pitches if p.opponent_hand == "L"]
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            return ui.div(
                ui.p(ui.strong("Pitch Type Breakdown")),
                ui.p(
                    f"Stuff+ is team-relative (100 = your staff's average, 10 points = 1 SD) and only populates for "
                    f"pitches with a Rapsodo reading linked to this outing. 'Reliable' needs at least "
                    f"{MIN_BASELINE_PITCHES} pitches of that type in this game -- shown either way, just flagged below "
                    f"that floor.",
                    class_="text-muted small",
                ),
                ui.navset_tab(
                    ui.nav_panel("All Batters", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(pitches, rap_by_gp, stuff_baselines))),
                    ui.nav_panel("vs RHH", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(vs_rhh, rap_by_gp, stuff_baselines)) if vs_rhh else ui.p("No pitches recorded against a right-handed batter yet.", class_="text-muted small")),
                    ui.nav_panel("vs LHH", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(vs_lhh, rap_by_gp, stuff_baselines)) if vs_lhh else ui.p("No pitches recorded against a left-handed batter yet.", class_="text-muted small")),
                ),
            )
        finally:
            db.close()

    @render.ui
    def command_execution_section():
        """Command Precision + Attack Zones -- unchanged computation,
        just moved out of report_body into their own gated section
        (paired under the same "Command & Execution" dropdown value as
        command_target_section below, which stays a separate function
        since it also owns a render_plotly chart -- see that function's
        own comment for why that split has to stay a separate output)."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "command_execution":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitcher = db.query(Player).filter(Player.player_id == selected_pitcher_id).first()
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches or pitcher is None:
                return None

            sections = [ui.p(ui.strong("Command Precision"))]
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
        req("report_section" in input)
        if input.report_section() != "command_execution":
            return None
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
                {"label": "Execution %", "value": _cmd_fmt(scorecard["execution_pct"], "%")},
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
                    "Execution %": row["Execution %"] if row["Execution %"] is not None else "—",
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



    # -------------------------------------------------------------------
    # Pitch Shape (Rapsodo) -- Sept 2026, restyled after Ryker's Pitch
    # Profiler reference image: Release Point (silhouette), Movement
    # Profile (with per-pitch-type Estimated Arm Angle rays), and Pitch
    # Frequency by batter handedness side by side, then a full physical
    # breakdown table below. Reuses the same pure chart/analytics
    # functions the Bullpen Dashboard and the Pitch Type Breakdown tabs
    # above already use (visualizations/bullpen_charts.py,
    # visualizations/pitcher_graphic.py, analytics/bullpen_metrics.py,
    # analytics/pitch_grading.py) -- no second implementation of any of
    # this math, just fed this game's own Rapsodo-linked pitches.
    #
    # Deliberately still lean on controls, per Ryker's own call: no
    # pitch-type/date filters, no individual-vs-average toggle -- fixed
    # defaults only. The Bullpen Dashboard's full interactive version
    # (arm-angle filters, mode toggles, etc.) stays the place a coach
    # digs deeper for bullpen sessions; the equivalent for intrasquad
    # games (season-wide, not just one outing) is planned for Pitcher
    # Profile, not built yet as of this section.
    #
    # No Barrel % column anywhere here -- GBO doesn't track batted-ball
    # exit velocity/launch angle, so there's no real GBO equivalent to
    # substitute (Ryker's own call on the metric gap: substitute a real
    # equivalent where one exists, skip what doesn't).
    # -------------------------------------------------------------------

    def _selected_pitcher_rapsodo_game_pitches(db):
        if "game_select" not in input or "pitcher_select" not in input:
            return None
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        pitches = (
            db.query(RapsodoPitch)
            .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
            .options(joinedload(RapsodoPitch.pitch_type), joinedload(RapsodoPitch.player))
            .filter(GamePitch.game_id == int(game_id_raw), RapsodoPitch.player_id == int(pitcher_id_raw))
            .order_by(RapsodoPitch.pitch_number)
            .all()
        )
        return pitches or None

    def _rapsodo_arm_angles_by_type(pitches, player):
        """[(label, color, angle_degrees), ...] for every pitch type with
        a computable Estimated Arm Angle -- same grouping/coloring
        bullpen_dashboard_display.py's own movement-chart panel uses, so
        the ray colors always agree with the dots they're drawn against."""
        type_groups = {}
        type_order = []
        for p in pitches:
            label = pitch_type_label(p)
            if label not in type_groups:
                type_groups[label] = []
                type_order.append(label)
            type_groups[label].append(p)
        out = []
        for label in type_order:
            angle, _n = average_estimated_arm_angle(type_groups[label], player)
            if angle is not None:
                out.append((label, color_for_pitch_label(label), angle))
        return out

    @render.ui
    def rapsodo_shape_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_shape":
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Pitch Shape (Rapsodo)")),
                ui.p(
                    "Release point, movement, and pitch mix by batter handedness for this outing, from this "
                    "game's Rapsodo-linked pitches.",
                    class_="text-muted small",
                ),
                ui.layout_columns(
                    ui.div(
                        ui.p("Release Point", style="font-weight:700; text-align:center;"),
                        ui.output_ui("rapsodo_release_point"),
                    ),
                    output_widget("rapsodo_movement_chart"),
                    col_widths=[5, 7],
                ),
                # Its own full-width row rather than a third equal column --
                # it's a horizontal bar chart with a label past the tip of
                # every bar, so a ~1/3-width column left it visibly cramped
                # (labels overlapping/squeezed even after fixing the hard
                # clipping). Full width gives every bar's label room.
                output_widget("rapsodo_pitch_frequency_chart"),
                ui.output_ui("rapsodo_pitch_shape_table"),
            )
        finally:
            db.close()

    @render.ui
    def rapsodo_release_point():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            type_groups = {}
            type_order = []
            for p in pitches:
                label = pitch_type_label(p)
                if label not in type_groups:
                    type_groups[label] = []
                    type_order.append(label)
                type_groups[label].append(p)

            releases = []
            for label in type_order:
                group = type_groups[label]
                heights = [float(p.release_height) for p in group if p.release_height is not None]
                sides = [float(p.release_side) for p in group if p.release_side is not None]
                if not heights or not sides:
                    continue
                releases.append({
                    "label": label,
                    "color": color_for_pitch_label(label),
                    "side_ft": sum(sides) / len(sides),
                    "height_ft": sum(heights) / len(heights),
                    "count": len(group),
                })

            player = pitches[0].player
            player_height_in = float(player.height_in) if player is not None and player.height_in is not None else None
            throws = player.throws if player is not None else None
            children = [ui.HTML(pitcher_release_svg(releases, throws=throws or "R", height_in=player_height_in or 73))]
            if player is not None and player.height_in is None:
                children.append(ui.p(
                    "Using an average height -- add this pitcher's real height on the Players page for a more accurate figure.",
                    class_="text-muted small", style="text-align:center;",
                ))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def rapsodo_movement_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            player = pitches[0].player
            throws = player.throws if player is not None else None
            arm_angles_by_type = _rapsodo_arm_angles_by_type(pitches, player)
            return movement_chart(pitches, arm_angles_by_type=arm_angles_by_type, throws=throws)
        finally:
            db.close()

    @render_plotly
    def rapsodo_pitch_frequency_chart():
        """Pitch mix vs RHH/vs LHH, tornado-style -- same vs_rhh/vs_lhh
        split and Stuff+ baseline the Pitch Type Breakdown tabs above
        already compute (GamePitch.opponent_hand, profile_queries'
        team-wide Stuff+ baseline), just as one combined chart instead
        of separate tabs. Stuff+ shown per pitch type overall (not
        re-split by handedness) -- splitting the baseline further would
        shrink an already-thin single-outing sample per type into
        something too small to mean anything."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches:
                return None
            vs_rhh = [p for p in pitches if p.opponent_hand == "R"]
            vs_lhh = [p for p in pitches if p.opponent_hand == "L"]
            if not vs_rhh and not vs_lhh:
                return None

            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            pitch_type_grades = {}
            for p in pitches:
                if p.pitch_type is None:
                    continue
                rap = rap_by_gp.get(p.game_pitch_id)
                if rap is None:
                    continue
                label = p.pitch_type.type_name
                s_val = stuff_plus(rap, stuff_baselines.get(label))
                if s_val is None:
                    continue
                grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
                grp["n"] += 1
                grp["stuff_plus"].append(s_val)
            stuff_by_label = {row["Pitch Type"]: row["Stuff+"] for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}

            def _counts_by_type(subset):
                counts, order = {}, []
                for p in subset:
                    if p.pitch_type is None:
                        continue
                    label = p.pitch_type.type_name
                    if label not in counts:
                        counts[label] = 0
                        order.append(label)
                    counts[label] += 1
                return counts, order

            rhh_counts, rhh_order = _counts_by_type(vs_rhh)
            lhh_counts, lhh_order = _counts_by_type(vs_lhh)
            labels = list(dict.fromkeys(rhh_order + lhh_order))
            if not labels:
                return None
            rhh_vals = [rhh_counts.get(l, 0) for l in labels]
            lhh_vals = [lhh_counts.get(l, 0) for l in labels]
            colors = [color_for_pitch_label(l) for l in labels]

            def _bar_text(label, count):
                # A 0-length bar (this pitch type never thrown to that
                # handedness) still sits at x=0 -- giving it a label too
                # would overlap the other side's label right at the
                # zero line, especially for low counts. Skip it.
                if not count:
                    return ""
                stuff = stuff_by_label.get(label)
                return f"Count: {count}" + (f"  ({round(stuff)} Stuff+)" if stuff is not None else "")

            fig = go.Figure()
            # cliponaxis=False: "outside" bar text is positioned in data
            # units, not pixels, so with three narrow side-by-side charts
            # the longer "Count: N  (NNN Stuff+)" labels were getting hard
            # -clipped at the axis range boundary before this. Letting the
            # text draw past the axis (into the figure's own margin) fixes
            # the truncation regardless of window width.
            fig.add_trace(go.Bar(
                y=labels, x=[-v for v in lhh_vals], orientation="h", name="LHH",
                marker_color=colors, text=[_bar_text(l, v) for l, v in zip(labels, lhh_vals)],
                textposition="outside", hoverinfo="text", cliponaxis=False,
            ))
            fig.add_trace(go.Bar(
                y=labels, x=rhh_vals, orientation="h", name="RHH",
                marker_color=colors, text=[_bar_text(l, v) for l, v in zip(labels, rhh_vals)],
                textposition="outside", hoverinfo="text", cliponaxis=False,
            ))
            max_val = max(rhh_vals + lhh_vals + [1])
            fig.update_xaxes(range=[-max_val * 1.8, max_val * 1.8], zeroline=True, zerolinewidth=2, showticklabels=False)
            fig.add_annotation(text="← LHH", x=0, xref="paper", xanchor="left", y=1.08, yref="paper", showarrow=False)
            fig.add_annotation(text="RHH →", x=1, xref="paper", xanchor="right", y=1.08, yref="paper", showarrow=False)
            return apply_gbo_theme(fig, title="Pitch Frequency", height=420, showlegend=False, barmode="overlay")
        finally:
            db.close()

    @render.ui
    def rapsodo_pitch_shape_table():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitcher = db.query(Player).filter(Player.player_id == int(pitcher_id_raw)).first()
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches or pitcher is None:
                return None
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            rows = _pitch_shape_rows(pitches, rap_by_gp, stuff_baselines, pitcher)
            if not rows:
                return None
            return ui.div(
                ui_helpers.render_dict_table(rows),
                ui.p(
                    "VAA/HAA are estimated from release point, release angle, extension, and actual plate-crossing "
                    "location (not a direct Rapsodo measurement -- Rapsodo's own exported VAA/HAA columns are blank "
                    "in these files), same approach as the Bullpen Dashboard's arm-angle/VAA/HAA estimates.",
                    class_="text-muted small",
                ),
                ui.p(
                    f"Stuff+ needs at least {MIN_BASELINE_PITCHES} pitches of that type (team-wide) to be a stable "
                    "read -- a single outing rarely reaches that for a secondary pitch, shown anyway rather than hidden.",
                    class_="text-muted small",
                ),
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch-by-Pitch -- Ryker's Sept 2026 report request: a per-pitch
    # list for this outing (not a per-type average like the sections
    # above), with a picker to drill into one pitch's Rapsodo numbers,
    # its actual location on the zone, its estimated arm angle (reusing
    # average_estimated_arm_angle on a one-pitch list rather than a new
    # single-pitch helper), and its charted result. The zone plot is
    # rendered as a static PNG via chart_helpers.fig_to_img (same
    # pattern Bullpen Dashboard uses) rather than a registered
    # render_plotly/output_widget, since it's a small, non-interactive,
    # per-selection image -- simpler than managing another widget id.
    # -------------------------------------------------------------------

    @render.ui
    def pitch_by_pitch_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_by_pitch":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return None
            pitches = sorted(pitches, key=lambda p: p.pitch_sequence)
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])

            rows = []
            choices = {}
            for p in pitches:
                label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
                rap = rap_by_gp.get(p.game_pitch_id)
                rows.append({
                    "#": p.pitch_sequence,
                    "Pitch Type": label,
                    "Velo": f"{float(rap.velocity):.1f} mph" if rap is not None and rap.velocity is not None else "—",
                    "Result": p.pitch_outcome or "—",
                    "AB Outcome": p.ab_outcome if (p.ends_plate_appearance and p.ab_outcome) else "—",
                })
                choices[str(p.game_pitch_id)] = f"Pitch {p.pitch_sequence} — {label} — {p.pitch_outcome or 'unknown result'}"

            return ui.div(
                ui.p(ui.strong("Pitch-by-Pitch")),
                ui.p(
                    "Every pitch in this outing, in order. Pick one below to see its Rapsodo numbers, actual "
                    "location, and estimated arm angle.",
                    class_="text-muted small",
                ),
                ui_helpers.render_dict_table(rows),
                ui.input_select("selected_pitch_id", "Pitch detail", choices=choices),
                ui.output_ui("pitch_detail_card"),
            )
        finally:
            db.close()

    @render.ui
    def pitch_detail_card():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_by_pitch":
            return None
        req("selected_pitch_id" in input)
        selected_raw = input.selected_pitch_id()
        if not selected_raw:
            return None
        db = get_session()
        try:
            p = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type))
                .filter(GamePitch.game_pitch_id == int(selected_raw))
                .first()
            )
            if p is None:
                return None
            pitcher = db.query(Player).filter(Player.player_id == int(input.pitcher_select())).first()
            rap = db.query(RapsodoPitch).filter(RapsodoPitch.game_pitch_id == p.game_pitch_id).first()
            label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"

            has_intended = p.intended_plate_x is not None and p.intended_plate_z is not None
            has_actual = p.actual_plate_x is not None and p.actual_plate_z is not None
            if has_intended:
                location_fig = _pitch_location_figure(
                    intended_x=float(p.intended_plate_x), intended_z=float(p.intended_plate_z),
                    actual_x=float(p.actual_plate_x) if has_actual else None,
                    actual_z=float(p.actual_plate_z) if has_actual else None,
                    color=color_for_pitch_label(label),
                )
                location_block = ui.div(
                    ui.p("Location", style="font-weight:700; text-align:center;"),
                    chart_helpers.fig_to_img(location_fig, width=280, height=280),
                )
            else:
                location_block = ui.div(
                    ui.p("Location", style="font-weight:700; text-align:center;"),
                    ui.p("Not located yet.", class_="text-muted small", style="text-align:center;"),
                )

            if rap is not None:
                vaa = _pitch_level_vaa(rap)["value_degrees"]
                haa = _pitch_level_haa(rap)["value_degrees"]
                arm_angle, _n = average_estimated_arm_angle([rap], pitcher)
                rapsodo_block = ui.div(
                    ui.p("Rapsodo", style="font-weight:700;"),
                    ui_helpers.render_kpi_cards([
                        {"label": "Velocity", "value": f"{float(rap.velocity):.1f} mph" if rap.velocity is not None else "—"},
                        {"label": "Spin Rate", "value": f"{float(rap.total_spin):.0f} rpm" if rap.total_spin is not None else "—"},
                        {"label": "IVB", "value": f'{float(rap.vb_spin):.1f}"' if rap.vb_spin is not None else "—"},
                        {"label": "HB", "value": f'{float(rap.hb_spin):.1f}"' if rap.hb_spin is not None else "—"},
                        {"label": "VAA (est.)", "value": f"{vaa}°" if vaa is not None else "—"},
                        {"label": "HAA (est.)", "value": f"{haa}°" if haa is not None else "—"},
                        {"label": "Arm Angle (est.)", "value": f"{round(arm_angle)}°" if arm_angle is not None else "—"},
                    ]),
                )
            else:
                rapsodo_block = ui.div(
                    ui.p("Rapsodo", style="font-weight:700;"),
                    ui.p("No Rapsodo reading linked to this pitch.", class_="text-muted small"),
                )

            result_bits = [f"Result: {p.pitch_outcome or '—'}"]
            if p.contact_quality:
                result_bits.append(f"Contact Quality: {p.contact_quality}")
            if p.batted_ball_type:
                result_bits.append(f"Batted Ball: {p.batted_ball_type}")
            if p.ends_plate_appearance and p.ab_outcome:
                result_bits.append(f"AB Outcome: {p.ab_outcome}")

            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Pitch {p.pitch_sequence} — {label}")),
                ui.layout_columns(
                    location_block,
                    ui.div(
                        rapsodo_block,
                        ui.p(" · ".join(result_bits), class_="text-muted small", style="margin-top:12px;"),
                    ),
                    col_widths=[4, 8],
                ),
            )
        finally:
            db.close()
