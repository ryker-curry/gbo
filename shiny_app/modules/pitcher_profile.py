"""
GBO -- Pitcher Profile (Aug 2026, Phase 0 of STUFF-LOCATION-PITCHING-
PLUS-PLAN.md). A filterable, per-pitcher deep dive: counting stats,
pitch-type breakdown, Stuff+/Location+/Pitching+ grades, pitch usage,
attack-zone distribution, a grade trend over time, physical-profile
Movement/Release Point/Spin Axis charts, Command Target Zones, and a
full Individual Pitches table. Sits alongside the existing Analytics
page as a coach-facing (and player-facing, self-scoped) advanced
view -- not a replacement for it.

Sept 2026 (Ryker, looking at this page on his own Player login, and at
mlbpitchprofiler.com's own pitcher page as a reference): everything used
to render at once in one long scroll (pp_body). Restructured behind a
"View" dropdown instead -- Overview / Metrics / Results / Zone /
Arsenal, same convention pitcher_game_report.py's own "View" dropdown
already established, so only the selected view's section actually
queries the DB (see pp_view_picker's docstring). Results is genuinely
new: quality-of-contact-allowed per pitch type (GBO's own
contact_quality vocabulary, six buckets summing to 100% of that type's
balls in play) plus Hard Hit %/Whiff %/Chase % alongside, styled after
mlbpitchprofiler.com's own Results tab (visualizations/
pitch_results_chart.py). Metrics is the Physical Profile section,
Zone is Attack Zone Distribution + per-pitch-type location density
heatmaps (Sept 2026, visualizations/pitch_location_heatmap.py) +
Command Target Zones, Arsenal is the
Arsenal table + Pitch Type Breakdown + Individual Pitches. Overview
keeps the Line/Grades/Performance/Pitch Usage/Trend content pp_body
used to open with -- still the default first thing a viewer sees.

Sept 2026 (Ryker: "need to make the pitcher profile metrics (physical
profile) better. right now have to click show charts, don't
neccesarily want to have to do that") -- Metrics used to embed the
reused Bullpen Dashboard fragment (bullpen_dashboard_display.
register_bullpen_dashboard), which gates its charts behind a "Show
Charts" button because those charts render server-side through
kaleido (slow -- ~30s -- and prone to websocket timeouts on an
ungated page). Rebuilt to call the underlying PURE chart-builder
functions directly instead -- analytics/bullpen_metrics.py's
pitch_type_summary/average_estimated_arm_angle and visualizations/
bullpen_charts.py's movement_chart/release_point_chart, visualizations/
spin_axis_chart.py's average_spin_axis_chart/individual_spin_axis_chart
-- as plain @render_plotly/output_widget outputs, the same fast,
client-side, click-free pattern this page already uses for
pp_trend_chart/pp_results_chart/pp_location_heatmap. No gate needed
because there's no kaleido step. Also drops the old bullpen-only
Location heatmap from this tab -- redundant now that the Zone tab
has its own real-game pitch-location heatmaps, and dropping it keeps
this tab focused on release/movement/spin mechanics rather than
location (which already has its own tab).

Self-scoping, same pattern as player_profile.py: a staff role sees a
player picker (scoped to assigned players unless can_view_all_players);
a "Player" role always sees their own linked player, no picker, and
gets nothing at all if that player isn't a pitcher (see hitter_profile.py
for that mirror case). Both cases render the exact same page body
otherwise -- no simplified/stripped-down player version, per the design
brief.

Reuses, doesn't reinvent: game_stats.py (line/pitch-type breakdown),
plate_discipline.py, analytics/command_metrics.py + visualizations/
command_charts.py (Command Target Zones, same code pitcher_game_report.py
already uses, just scoped by this page's own filters instead of one
game_id), analytics/bullpen_metrics.py + visualizations/bullpen_charts.py
+ visualizations/spin_axis_chart.py (Physical Profile -- the same
Movement/Release Point/Spin Axis figure builders the Bullpen Dashboard
uses, called directly here against this pitcher's WHOLE Rapsodo history
in the selected date range -- bullpen sessions and intrasquad games
alike, via profile_queries.get_pitcher_rapsodo_pitches, the same
unified query this page's Zone tab already uses), and
analytics/pitch_grading.py (Stuff+/Location+/Pitching+/Arsenal).
analytics/profile_queries.py is the one new piece: the date-range/
pitch-type/game-scope filtered queries this page needs that
game_stats.py's season/single-game queries don't cover.
"""

from datetime import date, timedelta
from statistics import mean

from shiny import module, ui, render, req, reactive
from shinywidgets import output_widget, render_plotly
from database import get_session
from models import Player, User, PitchType, PlayerPitchArsenal, StaffPlayerAssignment
from game_stats import compute_pitching_line, compute_pitch_type_breakdown, get_batter_hands, compute_pitch_mix_by_count
from strike_zone import classify_attack_zone
import command_config
from analytics import command_metrics, performance_score, profile_queries
from analytics.pitch_grading import (
    stuff_plus, location_plus, pitching_plus, arsenal_summary, MIN_BASELINE_PITCHES,
)
from visualizations import command_charts, profile_charts
from visualizations.pitch_results_chart import pitch_results_chart
from visualizations.count_leverage_chart import count_leverage_chart
from visualizations.pitch_location_heatmap import pitch_location_heatmaps, MIN_FOR_CONTOUR
import glossary_content
from pitch_type_config import get_pitch_color

import ui_helpers
import format_helpers
from analytics.bullpen_metrics import pitch_type_summary, average_estimated_arm_angle, pitch_type_label
from visualizations.bullpen_charts import movement_chart, release_point_chart, color_for_pitch_label
from visualizations.pitcher_graphic import pitcher_release_svg
from visualizations.spin_axis_chart import average_spin_axis_chart, individual_spin_axis_chart
from format_helpers import (
    format_pct as _fmt_pct,
    format_num as _fmt,
)

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

# V1 fixed palette for the Attack Zone bar (Heart -> Waste), innermost
# to outermost -- no existing app-wide convention to reuse (Heart/
# Shadow/Chase/Waste only ever appear as text/percentages elsewhere,
# see plate_discipline.py/pitch_location_stats.py), so this picks a
# brand-consistent crimson-to-gray fade rather than inventing an
# unrelated scheme. Flag for Ryker/the designer to revise if a
# different treatment is wanted.
ATTACK_ZONE_COLORS = {"Heart": "#BF1E2D", "Shadow": "#F2B529", "Chase": "#7A8594", "Waste": "#3A3F47"}


def _fmt_grade(value):
    return f"{value:.1f}" if value is not None else "—"


def _avg_or_none(values):
    """Plain mean of the non-None values, rounded to 1 decimal, or
    None if every value is missing -- used for the Metrics tab's
    Spin Efficiency/Gyro Degree columns, which analytics/bullpen_
    metrics.pitch_type_summary() doesn't already compute (kept local
    to this page rather than added to that shared function, since
    pitch_type_summary's column set matches a documented spec table
    reused by several other pages -- My Bullpens, the standalone
    Bullpen Dashboard, Player Profile -- that this change shouldn't
    silently widen)."""
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _aggregate_trend_by_game(pitch_points):
    """pitch_points: list of (game_id, game_date, value) for individual
    graded pitches (value already non-None) -- one entry per pitch, as
    _compute_grading_bundle/pp_trend_chart build them. Groups by
    game_id, not date alone, so two games on the same date (a
    doubleheader) stay separate points instead of silently averaging
    together. Returns one point per OUTING -- (date, mean, lo, hi) --
    sorted by date: mean is that outing's average pitch-level grade,
    lo/hi its min/max, so profile_charts.trend_chart can show each
    outing's spread (an error bar) around its average instead of one
    dot per pitch.

    Sept 2026, Ryker: raw pitch-by-pitch dots were too noisy to read as
    an actual trend across outings ("how is this useful?" -- fair
    question, given it took a whole page of pitches per outing to find
    the shape). An outing-level average is what "trend over time"
    actually means to a coach looking for whether a guy's pitching
    better or worse lately, not a per-pitch scatter."""
    groups = {}
    for game_id, game_date, value in pitch_points:
        groups.setdefault(game_id, {"date": game_date, "values": []})["values"].append(value)
    rows = [
        (g["date"], round(mean(g["values"]), 1), round(min(g["values"]), 1), round(max(g["values"]), 1))
        for g in groups.values()
    ]
    rows.sort(key=lambda r: r[0])
    return rows


def _my_player(db, app_state):
    me = db.query(User).filter(User.user_id == app_state.user_id()).first()
    if me is None or me.player_id is None:
        return None
    return db.query(Player).filter(Player.player_id == me.player_id).first()


# NOTE (Aug 31 2026): _grade_ring_status/_grade_rings used to live here
# -- moved to shiny_app/ui_helpers.py as render_percentile_bars
# (Savant/mlbpitchprofiler.com-style percentile bars, per Ryker's own
# reference site, replacing the ring treatment for this grade family)
# so hitter_profile.py's new Performance section can reuse the same
# component. Sept 2026: recolored to that site's own continuous
# blue-to-red percentile scale (ui_helpers.percentile_color) -- see
# pp_overview_section()'s Grades section below and
# ui_helpers.render_percentile_bars' docstring.


def _stacked_bar(segments):
    """segments: list of (label, pct, color), pct 0-100 (need not sum
    to exactly 100 after rounding). Plain CSS flex bar -- same
    zero-image-render approach as bucket_display.py's rings/metric bars,
    no Plotly/kaleido needed for a simple stacked-percentage bar."""
    segments = [(label, pct, color) for label, pct, color in segments if pct]
    if not segments:
        return None
    bar = ui.div(
        *[ui.div(style=f"width:{pct}%; background:{color};", title=f"{label}: {pct:.0f}%") for label, pct, color in segments],
        style="display:flex; height:22px; border-radius:6px; overflow:hidden; width:100%;",
    )
    legend = ui.div(
        *[
            ui.div(
                ui.span(style=f"display:inline-block; width:10px; height:10px; border-radius:5px; background:{color}; margin-right:5px;"),
                f"{label} {pct:.0f}%",
                style="display:inline-flex; align-items:center; font-size:0.8rem; margin:2px 10px 2px 0;",
            )
            for label, pct, color in segments
        ],
        style="display:flex; flex-wrap:wrap; margin-top:6px;",
    )
    return ui.div(bar, legend)


@module.ui
def pitcher_profile_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Profile"),
        ui.output_ui("pp_player_picker"),
        ui.output_ui("pp_filters"),
        # Sept 2026, Ryker: a "View" dropdown instead of every section
        # rendering at once and scrolling forever -- same convention
        # pitcher_game_report.py's own "View" dropdown already
        # established. Each of these five stays statically listed here
        # (Shiny needs a placeholder in the DOM for each output id) --
        # the gate inside each render.ui function is what actually
        # controls which one does anything.
        ui.output_ui("pp_view_picker"),
        ui.output_ui("pp_overview_section"),
        ui.output_ui("pp_metrics_section"),
        ui.output_ui("pp_results_section"),
        ui.output_ui("pp_zone_section"),
        ui.output_ui("pp_command_section"),
        ui.output_ui("pp_arsenal_section"),
        ui.output_ui("pp_count_leverage_section"),
        ui_helpers.page_footer(),
    )


@module.server
def pitcher_profile_server(input, output, session, app_state):

    def _visible_pitchers(db):
        q = db.query(Player).filter(Player.is_pitcher.is_(True))
        if not app_state.can_view_all_players():
            ids = [a.player_id for a in db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()]
            q = q.filter(Player.player_id.in_(ids))
        return q.filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()

    def _current_player_id(db):
        if app_state.role_name() == "Player":
            me = _my_player(db, app_state)
            return me.player_id if (me is not None and me.is_pitcher) else None
        if "pp_player_select" not in input or not input.pp_player_select():
            return None
        return int(input.pp_player_select())

    @render.ui
    def pp_player_picker():
        if not app_state.is_authenticated() or app_state.role_name() == "Player":
            return None
        if app_state.role_name() not in STAFF_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")
        db = get_session()
        try:
            pitchers = _visible_pitchers(db)
        finally:
            db.close()
        if not pitchers:
            return ui_helpers.empty_state("No pitchers to show yet.")
        choices = {str(p.player_id): f"{p.last_name}, {p.first_name}" + (f"  #{p.jersey_number}" if p.jersey_number else "") for p in pitchers}
        return ui.div(ui.input_select("pp_player_select", "Pitcher", choices=choices, width="320px"), style="margin-bottom:8px;")

    @render.ui
    def pp_filters():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        if role in STAFF_ROLES:
            req("pp_player_select" in input)

        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            arsenal = (
                db.query(PitchType)
                .join(PlayerPitchArsenal, PlayerPitchArsenal.pitch_type_id == PitchType.pitch_type_id)
                .filter(PlayerPitchArsenal.player_id == pid, PlayerPitchArsenal.active.is_(True))
                .order_by(PitchType.display_order)
                .all()
            )
            type_choices = {"__all__": "All Pitches"}
            for t in arsenal:
                type_choices[t.type_name] = t.type_name
        finally:
            db.close()

        return ui.layout_columns(
            ui.input_date("pp_date_from", "From", value=date.today() - timedelta(days=365)),
            ui.input_date("pp_date_to", "To", value=date.today()),
            ui.input_select("pp_pitch_type", "Pitch Type", choices=type_choices),
            ui.input_select("pp_game_scope", "Games", choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[3, 3, 3, 3],
        )

    def _current_filters():
        req("pp_date_from" in input)
        req("pp_date_to" in input)
        req("pp_pitch_type" in input)
        req("pp_game_scope" in input)
        pitch_type = input.pp_pitch_type()
        return {
            "date_from": input.pp_date_from(),
            "date_to": input.pp_date_to(),
            "pitch_type": None if pitch_type == "__all__" else pitch_type,
            "game_scope": input.pp_game_scope(),
        }

    # -------------------------------------------------------------------
    # Physical Profile -- pure chart builders called directly (Sept
    # 2026 rebuild, see module docstring). _physical_target(db) is the
    # one shared query pp_metrics_section and the three chart outputs
    # below all call -- same "player_pitches" scope (this pitcher's
    # WHOLE Rapsodo history, bullpen AND game alike, filtered by date
    # range/pitch type/game scope) the old bullpen-dashboard fragment
    # used, just without that fragment's kaleido/click-gate machinery.
    # -------------------------------------------------------------------

    def _physical_target(db):
        pid = _current_player_id(db)
        if pid is None:
            return None, []
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None:
            return None, []
        f = _current_filters()
        rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"],
            pitch_type=f["pitch_type"], game_scope=f["game_scope"],
        )
        return player, rapsodo_pitches

    @render.ui
    def pp_view_picker():
        """The "View" dropdown driving which of the sections below
        actually renders -- same convention pitcher_game_report.py's
        report_section_picker already established (Sept 2026, Ryker:
        "have the drop down menu to where we can select what to view
        rather than all of it showing up and having to scroll down
        forever"). Each gated section function below checks
        input.pp_view() itself and returns None immediately when not
        selected, before doing any query -- switching this dropdown is
        what stops the DB work for the other views, not CSS visibility."""
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        if role in STAFF_ROLES:
            req("pp_player_select" in input)
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            f = _current_filters()
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
            )
            if not game_pitches and not rapsodo_pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.input_select(
                    "pp_view", "View",
                    choices={
                        "overview": "Overview",
                        "metrics": "Metrics (Physical Profile)",
                        "results": "Results",
                        "zone": "Zone",
                        "command": "Command & Execution",
                        "arsenal": "Arsenal",
                        "count_leverage": "Count Leverage",
                    },
                ),
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Per-tab "Glossary" links (Sept 2026, Ryker: reference is
    # mlbpitchprofiler.com's own per-page "Zone Glossary"/"Results
    # Glossary" links) -- one input_action_link wired up in each view
    # section above (ui_helpers.glossary_link), one reactive.effect
    # here per link that pops the matching glossary_content.py list as
    # a modal. Content lives in glossary_content.py, not inline here,
    # so it can be reused if another page ever wants the same terms.
    # -------------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.pp_glossary_overview)
    def _pp_show_overview_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Overview Glossary", glossary_content.OVERVIEW))

    @reactive.effect
    @reactive.event(input.pp_glossary_metrics)
    def _pp_show_metrics_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Metrics Glossary", glossary_content.METRICS))

    @reactive.effect
    @reactive.event(input.pp_glossary_results)
    def _pp_show_results_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Results Glossary", glossary_content.RESULTS))

    @reactive.effect
    @reactive.event(input.pp_glossary_zone)
    def _pp_show_zone_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Zone Glossary", glossary_content.ZONE))

    @reactive.effect
    @reactive.event(input.pp_glossary_arsenal)
    def _pp_show_arsenal_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Arsenal Glossary", glossary_content.ARSENAL))

    def _compute_grading_bundle(db, game_pitches, rapsodo_pitches):
        """Shared derived-data pass over one filtered pitch window --
        Stuff+/Location+/Pitching+ per pitch, pitch usage counts,
        attack-zone counts, the Pitching+ trend series (one point per
        OUTING, not per pitch -- see _aggregate_trend_by_game), the
        Arsenal rollup, and the Individual Pitches rows. Factored out
        of what used to be one single pp_body loop so pp_overview_
        section/pp_zone_section/pp_arsenal_section can each call it
        fresh (same "only the selected view queries anything"
        principle pitcher_game_report.py's own gated sections already
        establish) without tripling this ~60-line loop three ways."""
        stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
        location_baseline = profile_queries.team_location_plus_baseline(db)

        game_pitch_ids = [p.game_pitch_id for p in game_pitches]
        rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, game_pitch_ids)

        def _type_label(pitch_type_obj):
            return pitch_type_obj.type_name if pitch_type_obj is not None else "Unspecified"

        pitch_type_grades = {}
        individual_rows = []
        trend_pitch_points = []
        zone_counts = {"Heart": 0, "Shadow": 0, "Chase": 0, "Waste": 0}
        usage_counts = {}

        for p in game_pitches:
            label = _type_label(p.pitch_type)
            usage_counts[label] = usage_counts.get(label, 0) + 1

            rap = rap_by_gp.get(p.game_pitch_id)
            s_val = stuff_plus(rap, stuff_baselines.get(label)) if rap is not None else None
            l_val = location_plus(p, location_baseline)
            pi_val = pitching_plus(s_val, l_val)

            grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
            grp["n"] += 1
            if s_val is not None:
                grp["stuff_plus"].append(s_val)
            if l_val is not None:
                grp["location_plus"].append(l_val)
            if pi_val is not None:
                grp["pitching_plus"].append(pi_val)

            if p.actual_plate_x is not None and p.actual_plate_z is not None:
                zone = classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z))
                if zone:
                    zone_counts[zone] += 1

            if pi_val is not None and p.game is not None:
                trend_pitch_points.append((p.game.game_id, p.game.game_date, pi_val))

            individual_rows.append({
                "Date": p.game.game_date.strftime("%Y-%m-%d") if p.game else "—",
                "#": p.pitch_sequence,
                "Pitch Type": label,
                "Velo": f"{float(rap.velocity):.1f}" if rap is not None and rap.velocity is not None else "—",
                "Result": p.pitch_outcome or "—",
                "Stuff+": _fmt_grade(s_val),
                "Location+": _fmt_grade(l_val),
                "Pitching+": _fmt_grade(pi_val),
            })

        # Any Rapsodo pitches with no game link at all (pure bullpen
        # reps) still count toward Arsenal's Stuff+ rollup -- see this
        # function's callers' original docstring note (kept from
        # pp_body's own comment, unchanged reasoning): stuff_baselines
        # holds fitted MODELS, trained only on real-game pitches, but a
        # fitted model scores any pitch from just its physical readings.
        linked_rapsodo_ids = {r.rapsodo_pitch_id for r in rap_by_gp.values()}
        for r in rapsodo_pitches:
            if r.rapsodo_pitch_id in linked_rapsodo_ids:
                continue
            label = _type_label(r.pitch_type)
            s_val = stuff_plus(r, stuff_baselines.get(label))
            if s_val is None:
                continue
            grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
            grp["n"] += 1
            grp["stuff_plus"].append(s_val)

        arsenal_rows = arsenal_summary(pitch_type_grades) if pitch_type_grades else []
        overview_stuff = [v for row in arsenal_rows for v in [row["Stuff+"]] if v is not None]
        overview_loc = [v for row in arsenal_rows for v in [row["Location+"]] if v is not None]
        overview_pitching = [v for row in arsenal_rows for v in [row["Pitching+"]] if v is not None]

        return {
            "stuff_plus_value": round(sum(overview_stuff) / len(overview_stuff), 1) if overview_stuff else None,
            "location_plus_value": round(sum(overview_loc) / len(overview_loc), 1) if overview_loc else None,
            "pitching_plus_value": round(sum(overview_pitching) / len(overview_pitching), 1) if overview_pitching else None,
            "usage_counts": usage_counts,
            "zone_counts": zone_counts,
            "trend_points": _aggregate_trend_by_game(trend_pitch_points),
            "arsenal_rows": arsenal_rows,
            "individual_rows": individual_rows,
        }

    @render.ui
    def pp_overview_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "overview":
            return None
        f = _current_filters()

        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None

            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
            )
            if not game_pitches and not rapsodo_pitches:
                return ui_helpers.card(ui_helpers.empty_state(
                    "No pitches in this date range yet. Widen the filters, or check back once games/bullpens are tracked."
                ))

            sections = [ui.div(
                ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title", style="margin-bottom:0;"),
                ui_helpers.glossary_link("pp_glossary_overview", "Overview Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]

            if game_pitches:
                line = compute_pitching_line(game_pitches)
                sections.append(ui.p(ui.strong("Line")))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "IP", "value": str(line["IP"])},
                    {"label": "Pitches", "value": str(line["Pitches"])},
                    {"label": "K", "value": str(line["K"])},
                    {"label": "BB", "value": str(line["BB"])},
                    {"label": "WHIP", "value": _fmt(line["WHIP"])},
                    {"label": "FIP", "value": _fmt(line["FIP"])},
                ]))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Strike %", "value": _fmt_pct(line["Strike %"])},
                    {"label": "Zone Execution %", "value": _fmt_pct(line["Zone Execution %"])},
                    {"label": "OBA", "value": _fmt(line["OBA (opponent AVG)"], 3)},
                    {"label": "wOBA*", "value": _fmt(line["wOBA"], 3)},
                ]))
                sections.append(ui.p("*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact.", class_="text-muted small"))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Overview")))
            sections.append(ui.p(
                "Stuff+/Location+/Pitching+: 100 = your own team's average across every graded pitch, 10 points = 1 "
                "standard deviation. Team-relative only -- GBO has no access to league-wide pitch data to compare "
                "against a real MLB Stuff+ number.",
                class_="text-muted small",
            ))
            sections.append(ui.p(
                "Blended across every pitch type thrown in this window (each pitch type counted once, not weighted "
                "by how often it's thrown) -- not a single pitch's grade. See the Arsenal tab for the breakdown by "
                "pitch type.",
                class_="text-muted small fst-italic",
            ))

            bundle = _compute_grading_bundle(db, game_pitches, rapsodo_pitches)
            stuff_plus_value = bundle["stuff_plus_value"]
            location_plus_value = bundle["location_plus_value"]
            pitching_plus_value = bundle["pitching_plus_value"]
            arsenal_rows = bundle["arsenal_rows"]

            grade_bars = ui_helpers.render_percentile_bars([
                ("Stuff+", stuff_plus_value),
                ("Location+", location_plus_value),
                ("Pitching+", pitching_plus_value),
            ])
            if grade_bars is not None:
                sections.append(grade_bars)
            else:
                sections.append(ui.p("No graded pitches yet in this range -- needs Rapsodo-linked pitches (Stuff+) or located game pitches (Location+).", class_="text-muted small"))

            if game_pitches:
                baselines = _team_command_plus_baselines(db)
                cmd_view_pitches = command_metrics.game_pitches_command_view(game_pitches, player.throws)
                cmd_scorecard = command_metrics.session_command_scorecard(cmd_view_pitches)
                command_plus_value = None
                if baselines["pooled"][2] >= command_metrics.MIN_BASELINE_PITCHES:
                    command_plus_value = command_metrics.session_command_plus(cmd_view_pitches, baselines)

                arsenal_pitching_value = performance_score.usage_weighted_average(arsenal_rows, "Pitching+")

                pitcher_results_line = dict(line, **{"CSW %": performance_score.csw_pct(game_pitches)})
                team_pitching_lines = profile_queries.team_pitching_lines(db, date_from=f["date_from"], date_to=f["date_to"])
                results_score = None
                if len(team_pitching_lines) >= performance_score.MIN_BASELINE_PLAYERS:
                    results_baseline = performance_score.team_pitcher_results_baseline(team_pitching_lines)
                    results_score = performance_score.pitcher_results_score(pitcher_results_line, results_baseline)

                performance_value = performance_score.combine_pitcher_performance(
                    stuff_plus_value, location_plus_value, command_plus_value, arsenal_pitching_value, results_score,
                )

                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Performance")))
                sections.append(ui.p(
                    "Equal-weighted blend of Stuff+, Location+, Command+, Arsenal (usage-weighted Pitching+ across "
                    "the mix), and Results (FIP/WHIP/K-BB/CSW%/Execution%, team-relative) -- game production, kept "
                    "separate from the Bucket System's physical/athletic score. Not adjusted for the overlap this "
                    "creates between Arsenal and Stuff+/Location+ (Arsenal is itself built from them) -- a V1 "
                    "formula, same treatment as every other composite in this build.",
                    class_="text-muted small",
                ))
                sections.append(ui.p(
                    "Stuff+/Location+ here are the same blended-across-pitch-types numbers as the Grades section "
                    "above (Arsenal below them IS usage-weighted, per pitch type -- see the Arsenal tab).",
                    class_="text-muted small fst-italic",
                ))
                performance_bars = ui_helpers.render_percentile_bars([
                    ("Stuff+", stuff_plus_value),
                    ("Location+", location_plus_value),
                    ("Command+", command_plus_value),
                    ("Arsenal", arsenal_pitching_value),
                    ("Results", results_score),
                    ("Performance", performance_value),
                ])
                if performance_bars is not None:
                    sections.append(performance_bars)
                else:
                    sections.append(ui.p("Not enough graded pitches or team baseline yet for a Performance score.", class_="text-muted small"))

            total_pitches = sum(bundle["usage_counts"].values())
            if total_pitches:
                sections.append(ui.p(ui.strong("Pitch Usage"), class_="mt-3"))
                sections.append(_stacked_bar([
                    (label, round(100 * n / total_pitches, 1), get_pitch_color(label))
                    for label, n in sorted(bundle["usage_counts"].items(), key=lambda kv: -kv[1])
                ]))

            if len(bundle["trend_points"]) >= 2:
                sections.append(ui.p(ui.strong("Pitching+ Trend"), class_="mt-3"))
                sections.append(ui.p(
                    "One point per outing (that appearance's average Pitching+), with an error bar showing the "
                    "spread from its lowest- to highest-graded pitch.",
                    class_="text-muted small",
                ))
                sections.append(output_widget("pp_trend_chart"))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def pp_metrics_section():
        """Sept 2026 rebuild -- see module docstring. Header + per-
        pitch-type physical table render immediately (a plain DB query,
        same cost as any other tab's table); the three charts below are
        output_widget placeholders filled in by the @render_plotly
        functions right after this one, same split pp_zone_section uses
        for its own pp_location_heatmap widget."""
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "metrics":
            return None
        db = get_session()
        try:
            header = ui.div(
                ui.p(ui.strong("Physical Profile"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("pp_glossary_metrics", "Metrics Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )
            player, rapsodo_pitches = _physical_target(db)
            if player is None or not rapsodo_pitches:
                return ui.div(
                    header,
                    ui.p("No Rapsodo-linked pitches (bullpen or game) in this range yet.", class_="text-muted small"),
                )

            # pitch_type_summary already covers Velo/Max Velo/Spin/IVB/
            # HB/Release Height/Release Side/Est. Arm Angle (passing
            # player=player); Spin Efficiency and Gyro Degree are added
            # locally below rather than widening that shared function
            # (see _avg_or_none's docstring).
            summary_rows = pitch_type_summary(rapsodo_pitches, player=player)
            groups_by_label = {}
            for p in rapsodo_pitches:
                groups_by_label.setdefault(pitch_type_label(p), []).append(p)
            table_rows = []
            for row in summary_rows:
                group = groups_by_label.get(row["Pitch Type"], [])
                table_rows.append({
                    "Pitch Type": row["Pitch Type"], "#": row["#"],
                    "Velo": row["Avg Velo"], "Max Velo": row["Max Velo"],
                    "Spin Rate": row["Avg Spin"],
                    "Spin Eff %": _avg_or_none([p.spin_efficiency for p in group]),
                    "Gyro °": _avg_or_none([p.gyro_degree for p in group]),
                    "IVB": row["IVB"], "HB": row["HB"],
                    "Release Ht": row["Release Height"], "Release Side": row["Release Side"],
                    "Arm Angle": row.get("Est. Arm Angle", "N/A"),
                })

            # Release-point pitcher graphic (Sept 2026, Ryker: "want to
            # be able to see the graphic of pitcher outline with the
            # estimated arm angle") -- same visualizations.pitcher_
            # graphic.pitcher_release_svg already live on Pitcher Game
            # Report and Bullpen Dashboard (the web-designer graphic
            # that replaced the older release_silhouette.py illustration),
            # reused here rather than a second, differently-styled
            # graphic, so this pitcher looks the same across every page
            # that shows their release point. One averaged release
            # point per pitch type -- same groups_by_label already
            # built above for the table.
            releases = []
            for label, group in groups_by_label.items():
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
            player_height_in = float(player.height_in) if player.height_in is not None else None
            graphic_children = [ui.p(ui.strong("Release Point & Arm Angle"), class_="mt-3")]
            if releases:
                graphic_children.append(ui.div(
                    ui.HTML(pitcher_release_svg(releases, throws=player.throws or "R", height_in=player_height_in or 73)),
                ))
                if player_height_in is None:
                    graphic_children.append(ui.p(
                        "Using an average height -- add this pitcher's real height on the Players page for a "
                        "more accurate figure.",
                        class_="text-muted small", style="text-align:center;",
                    ))
            else:
                graphic_children.append(ui.p("No release point data yet.", class_="text-muted small"))

            return ui.div(
                header,
                ui.p(
                    "Every Rapsodo-linked pitch this pitcher has thrown in this window -- bullpen sessions and "
                    "intrasquad games alike -- broken out by pitch type.",
                    class_="text-muted small",
                ),
                ui_helpers.render_dict_table(table_rows),
                ui.hr(),
                *graphic_children,
                ui.hr(),
                ui.input_slider(
                    "pp_phys_shading", "Minimum pitches to shade a pitch type's cluster",
                    min=1, max=10, value=2,
                ),
                output_widget("pp_movement_chart"),
                ui.p(
                    "IVB vs. HB, one point per pitch -- shaded regions show each pitch type's own cluster; dashed "
                    "rays show that type's estimated arm angle.",
                    class_="text-muted small",
                ),
                ui.input_radio_buttons(
                    "pp_phys_release_mode", "Release point view",
                    ["Individual Pitches", "Average by Pitch Type"], inline=True,
                ),
                output_widget("pp_release_chart"),
                ui.input_radio_buttons(
                    "pp_phys_spin_mode", "Spin axis view",
                    ["Average by Pitch Type", "Individual Pitches"], inline=True,
                ),
                output_widget("pp_spin_axis_chart"),
            )
        finally:
            db.close()

    @render_plotly
    def pp_movement_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "metrics":
            return None
        db = get_session()
        try:
            player, pitches = _physical_target(db)
            if not pitches:
                return None
            min_shading = input.pp_phys_shading() if "pp_phys_shading" in input else 2
            throws = player.throws if player is not None else None
            order, groups = [], {}
            for p in pitches:
                label = pitch_type_label(p)
                if label not in groups:
                    groups[label] = []
                    order.append(label)
                groups[label].append(p)
            arm_angles_by_type = []
            for label in order:
                angle, n = average_estimated_arm_angle(groups[label], player)
                if angle is not None:
                    arm_angles_by_type.append((label, color_for_pitch_label(label), angle))
            return movement_chart(
                pitches, min_pitches_for_shading=min_shading,
                arm_angles_by_type=arm_angles_by_type, throws=throws,
            )
        finally:
            db.close()

    @render_plotly
    def pp_release_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "metrics":
            return None
        db = get_session()
        try:
            _, pitches = _physical_target(db)
            if not pitches:
                return None
            mode_label = input.pp_phys_release_mode() if "pp_phys_release_mode" in input else "Individual Pitches"
            mode = "average" if mode_label == "Average by Pitch Type" else "individual"
            return release_point_chart(pitches, mode=mode)
        finally:
            db.close()

    @render_plotly
    def pp_spin_axis_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "metrics":
            return None
        db = get_session()
        try:
            _, pitches = _physical_target(db)
            if not pitches:
                return None
            mode_label = input.pp_phys_spin_mode() if "pp_phys_spin_mode" in input else "Average by Pitch Type"
            if mode_label == "Individual Pitches":
                return individual_spin_axis_chart(pitches)
            return average_spin_axis_chart(pitches)
        finally:
            db.close()

    @render.ui
    def pp_results_section():
        """Sept 2026, Ryker (reference: mlbpitchprofiler.com's own
        Results tab) -- quality of contact ALLOWED per pitch type, plus
        Hard Hit %/Whiff %/Chase % alongside. Built entirely from
        game_stats.compute_pitch_type_breakdown()'s rows, which grew the
        contact-quality columns (Weak/Jammed/Off the End/Clipped/Solid/
        Barreled %, Hard Hit %) specifically for this section -- GBO's
        own contact_quality vocabulary, not Statcast's Topped/Under/
        Flare-Burner labels, same six-bucket idea.

        A pitch type qualifies for a row here with EITHER a ball in play
        OR a swing (so whiffs/fouls-only pitch types still show up, not
        just BIP > 0) -- Whiff %/SwStr % are computed straight off
        pitch_outcome == "Swing and Miss" (game_stats.WHIFF_OUTCOMES),
        never off contact_quality, and a whiff by definition has no
        contact_quality to record (Ryker, Sept 2026: "it should show
        whiffs based on swing and miss. Don't need to click swing and
        miss for contact quality because there was no contact"). The
        contact-quality stack columns (Weak/Jammed/etc.) still correctly
        show "--" for a 0-BIP pitch type -- format_pct(None) -- so a
        whiff-only row never claims a contact-quality rate it has no
        balls in play to support."""
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "results":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return ui.p("No game pitches in this range yet.", class_="text-muted small")
            rows = compute_pitch_type_breakdown(game_pitches)
            type_rows = [
                r for r in rows
                if r["Pitch Type"] != "Total" and ((r["Balls in Play"] or 0) > 0 or (r["Total Swings"] or 0) > 0)
            ]
            if not type_rows:
                return ui.p(
                    "No swings recorded in this range yet -- Results needs at least one swing (in play, foul, or a "
                    "miss) per pitch type.",
                    class_="text-muted small",
                )
            return ui.div(
                ui.div(
                    ui.p(ui.strong("Results"), style="margin-bottom:0;"),
                    ui_helpers.glossary_link("pp_glossary_results", "Results Glossary"),
                    style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
                ),
                ui.p(
                    "Quality of contact allowed (Weak/Jammed/Off the End/Clipped/Solid/Barreled, stacked to 100% of "
                    "that pitch type's own balls in play), plus Hard Hit %/Whiff %/Chase % shown alongside as their "
                    "own rates -- not part of the stack, each against its own denominator (Hard Hit % of balls in "
                    "play, Whiff % of swings, Chase % of pitches out of the zone).",
                    class_="text-muted small",
                ),
                output_widget("pp_results_chart"),
                ui_helpers.render_dict_table([
                    {
                        "Pitch Type": r["Pitch Type"], "% Thrown": _fmt_pct(r["Pitch Usage %"]), "BIP": r["Balls in Play"],
                        "Weak %": _fmt_pct(r["Weak %"]), "Jammed %": _fmt_pct(r["Jammed %"]),
                        "Off the End %": _fmt_pct(r["Off the End %"]), "Clipped %": _fmt_pct(r["Clipped %"]),
                        "Solid %": _fmt_pct(r["Solid Contact %"]), "Barreled %": _fmt_pct(r["Barreled %"]),
                        "Hard Hit %": _fmt_pct(r["Hard Hit %"]), "Whiff %": _fmt_pct(r["Whiff %"]),
                        "SwStr %": _fmt_pct(r["SwStr %"]), "Chase %": _fmt_pct(r["Chase %"]),
                        "RV/100": r["RV/100"] if r["RV/100"] is not None else "—",
                    }
                    for r in type_rows
                ]),
            )
        finally:
            db.close()

    @render_plotly
    def pp_results_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "results":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None
            rows = compute_pitch_type_breakdown(game_pitches)
            return pitch_results_chart(rows)
        finally:
            db.close()

    @render.ui
    def pp_zone_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "zone":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
            )
            if not game_pitches and not rapsodo_pitches:
                return None
            bundle = _compute_grading_bundle(db, game_pitches, rapsodo_pitches)
            sections = [ui.div(
                ui.p(ui.strong("Attack Zone Distribution"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("pp_glossary_zone", "Zone Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]
            total_located = sum(bundle["zone_counts"].values())
            if not total_located:
                sections.append(ui.p("No located pitches yet.", class_="text-muted small"))
            else:
                sections.append(ui.p("Heart = down the middle, Shadow = zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                sections.append(_stacked_bar([
                    (zone, round(100 * bundle["zone_counts"][zone] / total_located, 1), ATTACK_ZONE_COLORS[zone])
                    for zone in ("Heart", "Shadow", "Chase", "Waste")
                ]))

            # Sept 2026, Ryker (reference: mlbpitchprofiler.com's own
            # "2026 PITCH LOCATIONS" section) -- per-pitch-type density
            # heatmaps below the aggregate Attack Zone bar above, plus
            # the matching per-type Heart/Shadow/Chase/Waste/Zone %
            # mix table (game_stats.compute_pitch_type_breakdown's new
            # "Zone %"/"Heart Zone %"/etc. columns -- see that
            # function's docstring for how these differ from the
            # existing swing-rate "Chase %").
            if game_pitches:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Pitch Locations")))
                sections.append(ui.p(
                    "Density of where each pitch type actually landed, real-game charted locations only "
                    f"(n={len(game_pitches)} charted pitches in this window; bullpen-only reps aren't located "
                    "so they can't appear here). Fewer than "
                    f"{MIN_FOR_CONTOUR} located pitches of a type shows plain dots instead of a density "
                    "surface -- not enough to smooth reliably.",
                    class_="text-muted small",
                ))
                sections.append(output_widget("pp_location_heatmap"))
                type_rows = [
                    r for r in compute_pitch_type_breakdown(game_pitches)
                    if r["Pitch Type"] != "Total" and r.get("Zone %") is not None
                ]
                if type_rows:
                    sections.append(ui_helpers.render_dict_table([
                        {
                            "Pitch Type": r["Pitch Type"], "% Thrown": _fmt_pct(r["Pitch Usage %"]),
                            "Zone %": _fmt_pct(r["Zone %"]), "Heart %": _fmt_pct(r["Heart Zone %"]),
                            "Shadow %": _fmt_pct(r["Shadow Zone %"]), "Chase %": _fmt_pct(r["Chase Zone %"]),
                            "Waste %": _fmt_pct(r["Waste Zone %"]),
                        }
                        for r in type_rows
                    ]))

            return ui.div(*sections)
        finally:
            db.close()

    @render_plotly
    def pp_location_heatmap():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "zone":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None
            return pitch_location_heatmaps(game_pitches)
        finally:
            db.close()

    @render.ui
    def pp_arsenal_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "arsenal":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
            )
            if not game_pitches and not rapsodo_pitches:
                return None
            bundle = _compute_grading_bundle(db, game_pitches, rapsodo_pitches)
            sections = [ui.div(
                ui_helpers.glossary_link("pp_glossary_arsenal", "Arsenal Glossary"),
                style="text-align:right;",
            )]

            if bundle["arsenal_rows"]:
                sections.append(ui.p(ui.strong("Arsenal")))
                sections.append(ui.p(
                    f"'Reliable' needs at least {MIN_BASELINE_PITCHES} pitches of that type in this window -- "
                    "fewer than that and the grade swings wildly with every new pitch.",
                    class_="text-muted small",
                ))
                sections.append(ui_helpers.render_dict_table([
                    {
                        "Pitch Type": row["Pitch Type"], "Usage %": _fmt_pct(row["Usage %"]), "Pitches": row["Pitches"],
                        "Stuff+": _fmt_grade(row["Stuff+"]), "Location+": _fmt_grade(row["Location+"]),
                        "Pitching+": _fmt_grade(row["Pitching+"]), "Reliable": "Yes" if row["Reliable"] else "No",
                    }
                    for row in bundle["arsenal_rows"]
                ]))

            if game_pitches:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Pitch Type Breakdown")))
                # Derived via get_batter_hands (Sept 2026), not the raw
                # opponent_hand column -- that column can hold 'S' for a
                # switch hitter and is the PITCHER's hand, not the
                # batter's, on our-team-batting rows (see that column's
                # comment on models.GamePitch), so comparing it directly
                # here silently dropped/miscounted switch hitters from
                # both buckets.
                _hands = get_batter_hands(db, game_pitches)
                vs_rhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "R"]
                vs_lhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "L"]
                sections.append(ui.navset_tab(
                    ui.nav_panel("All Batters", ui_helpers.render_dict_table(compute_pitch_type_breakdown(game_pitches))),
                    ui.nav_panel("vs RHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_rhh)) if vs_rhh else ui.p("No pitches vs a right-handed batter in this range.", class_="text-muted small")),
                    ui.nav_panel("vs LHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_lhh)) if vs_lhh else ui.p("No pitches vs a left-handed batter in this range.", class_="text-muted small")),
                ))

            if bundle["individual_rows"]:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Individual Pitches")))
                sections.append(ui_helpers.render_dict_table(list(reversed(bundle["individual_rows"]))))

            if not sections:
                return ui.p("Nothing to show for the Arsenal view yet in this range.", class_="text-muted small")
            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Count Leverage (Sept 2026, Ryker: "create a count leverage chart in
    # pitcher stats looking at what pitches thrown in certain counts
    # using pie charts" -- reference is Lance Brozdowski's "count
    # leverage" framing and the Marlins' own pitch-calling system, both
    # of which treat pitch selection as something that should shift with
    # the count rather than stay fixed across an at-bat). Same
    # render.ui-wrapper / render_plotly split every other chart-bearing
    # view on this page uses (a render_plotly output needs its own
    # registered function, not one nested inside a render.ui's return).
    #
    # vs RHH/vs LHH tabs added Sept 2026 (Ryker: "tabs like pitch type
    # breakdown with one tree visible at a time") -- same get_batter_hands
    # split as the Pitch Type Breakdown tabs above, in pp_arsenal_section.
    # Each tab needs its own registered render_plotly function for the
    # same nesting reason noted above, so there are three chart functions
    # below (_all / _rhh / _lhh) instead of one.
    # -------------------------------------------------------------------

    @render.ui
    def pp_count_leverage_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "count_leverage":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return ui.p("No game pitches in this range yet.", class_="text-muted small")
            counts = compute_pitch_mix_by_count(game_pitches)
            if not any(counts[c]["Total"] for c in counts):
                return ui.p(
                    "No pitches with a recorded count in this range yet.",
                    class_="text-muted small",
                )

            _hands = get_batter_hands(db, game_pitches)
            vs_rhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "R"]
            vs_lhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "L"]
            rhh_counts = compute_pitch_mix_by_count(vs_rhh)
            lhh_counts = compute_pitch_mix_by_count(vs_lhh)
            rhh_has_counts = any(rhh_counts[c]["Total"] for c in rhh_counts)
            lhh_has_counts = any(lhh_counts[c]["Total"] for c in lhh_counts)

            return ui.div(
                ui.p(ui.strong("Count Leverage")),
                ui.p(
                    "Pitch mix by ball-strike count, laid out as a count tree -- 0-0 at the top, then every count "
                    "reachable by that many total pitches into the at-bat below it, pitcher-favorable (more "
                    "strikes) toward the left, hitter-favorable (more balls) toward the right, narrowing back "
                    "down to 3-2 alone at the bottom. Pitch selection isn't supposed to stay fixed across an "
                    "at-bat: the idea (Lance Brozdowski's framing, and the same split behind the Marlins' own "
                    "dugout pitch-calling system) is best stuff middle-middle in non-two-strike counts, leaning "
                    "on breaking stuff once there are two strikes to chase the whiff. Each pie's own count total "
                    "is in its title; percentages are of THAT count, not his overall mix. Hover a slice for that "
                    "pitch/count combo's own RV/100 (run value -- same currency Location+/Pitching+/Command+ use "
                    "elsewhere on this page) to see whether what he leans on there is actually working, not just "
                    "how often he throws it.",
                    class_="text-muted small",
                ),
                ui.navset_tab(
                    ui.nav_panel("All Batters", output_widget("pp_count_leverage_chart_all")),
                    ui.nav_panel(
                        "vs RHH",
                        output_widget("pp_count_leverage_chart_rhh") if rhh_has_counts
                        else ui.p("No pitches with a recorded count vs a right-handed batter in this range.", class_="text-muted small"),
                    ),
                    ui.nav_panel(
                        "vs LHH",
                        output_widget("pp_count_leverage_chart_lhh") if lhh_has_counts
                        else ui.p("No pitches with a recorded count vs a left-handed batter in this range.", class_="text-muted small"),
                    ),
                ),
            )
        finally:
            db.close()

    @render_plotly
    def pp_count_leverage_chart_all():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "count_leverage":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None
            counts = compute_pitch_mix_by_count(game_pitches)
            return count_leverage_chart(counts)
        finally:
            db.close()

    @render_plotly
    def pp_count_leverage_chart_rhh():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "count_leverage":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None
            _hands = get_batter_hands(db, game_pitches)
            vs_rhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "R"]
            if not vs_rhh:
                return None
            counts = compute_pitch_mix_by_count(vs_rhh)
            return count_leverage_chart(counts)
        finally:
            db.close()

    @render_plotly
    def pp_count_leverage_chart_lhh():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "count_leverage":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None
            _hands = get_batter_hands(db, game_pitches)
            vs_lhh = [p for p in game_pitches if _hands.get(p.game_pitch_id) == "L"]
            if not vs_lhh:
                return None
            counts = compute_pitch_mix_by_count(vs_lhh)
            return count_leverage_chart(counts)
        finally:
            db.close()

    @render_plotly
    def pp_trend_chart():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "overview":
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            game_pitch_ids = [p.game_pitch_id for p in game_pitches]
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, game_pitch_ids)
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            location_baseline = profile_queries.team_location_plus_baseline(db)
            pitch_points = []
            for p in game_pitches:
                label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
                rap = rap_by_gp.get(p.game_pitch_id)
                s_val = stuff_plus(rap, stuff_baselines.get(label)) if rap is not None else None
                l_val = location_plus(p, location_baseline)
                pi_val = pitching_plus(s_val, l_val)
                if pi_val is not None and p.game is not None:
                    pitch_points.append((p.game.game_id, p.game.game_date, pi_val))
            # One point per OUTING (mean/lo/hi), not per pitch -- see
            # _aggregate_trend_by_game's docstring.
            points = _aggregate_trend_by_game(pitch_points)
            return profile_charts.trend_chart(points, y_label="Pitching+")
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Command Target Zones -- same code pitcher_game_report.py uses
    # (Command Tracker's own scorecard/table/chart via
    # command_metrics.game_pitches_command_view), scoped by this page's
    # filters instead of a single game_id. Own render.ui/render_plotly
    # split, same reason as pitcher_game_report.py: a render_plotly
    # output needs its own registered function.
    # -------------------------------------------------------------------

    @reactive.calc
    def _view_pitches():
        """Command Target Zones' filtered view-pitch list, shared by
        pp_command_section/pp_command_table/pp_command_chart below.
        Was a plain function taking a caller-supplied `db`, called
        fresh (a full query) from each of those three render
        functions independently on every reactive tick -- now computed
        once and reused, same @reactive.calc memoization pattern
        bullpen_dashboard.py's _resolved() already uses for the
        identical reason. Opens and fully closes its own db session
        (rather than reusing a caller's) so the cached result is safe
        to read after this function returns, no matter which caller
        reads it or when -- game_pitches_command_view()'s objects only
        carry plain scalars plus the already-joinedload'd .pitch_type
        (see profile_queries._base_pitching_query), so nothing on them
        needs a live session once this returns."""
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None, None
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None, None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None, None
            f = _current_filters()
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not game_pitches:
                return None, None
            return command_metrics.game_pitches_command_view(game_pitches, player.throws), player.throws
        finally:
            db.close()

    def _team_command_plus_baselines(db):
        """Same all-time, all-games team population Pitcher Game Report's
        Command+ uses (see that module's docstring) -- not scoped to
        this page's own filters, a stable roster-wide reference. Returns
        command_metrics.team_command_plus_baselines()'s {"pooled": (mean,
        stdev, n), "by_type": {...}} -- Sept 2026, widened so
        session_command_plus() can grade each pitch against its own
        pitch type (see that function's module comment in
        analytics/command_metrics.py for why)."""
        from models import GamePitch
        all_pitches = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
        view_pitches = command_metrics.game_pitches_command_view(all_pitches, None)
        return command_metrics.team_command_plus_baselines(view_pitches)

    def _cmd_bias_label(bias):
        parts = []
        if bias["horizontal_bias_in"] is not None:
            parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
        if bias["vertical_bias_in"] is not None:
            parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
        return " / ".join(parts) if parts else "—"

    @render.ui
    def pp_command_section():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        _current_filters()
        view_pitches, _throws = _view_pitches()
        if not view_pitches:
            return None
        return ui.div(
            ui.p(ui.strong("Command Target Zones")),
            ui.p(
                "Same Precision/Command/Competitive target-radius bands and concentric-ring chart Command "
                "Tracker uses -- built from this window's intended-vs-actual pitch locations. Only pitches with "
                "a logged intended location count (a real opponent's pitcher never has one on file).",
                class_="text-muted small",
            ),
            ui.output_ui("pp_command_table"),
            output_widget("pp_command_chart"),
        )

    @render.ui
    def pp_command_table():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, throws = _view_pitches()
        if not view_pitches:
            return None
        scorecard = command_metrics.session_command_scorecard(view_pitches)
        db = get_session()
        try:
            if scorecard["located_pitches"] == 0:
                return ui.p("No pitches have an actual location recorded yet -- needs Video Review or a Rapsodo link.", class_="text-muted small")

            baselines = _team_command_plus_baselines(db)
            command_plus_value = None
            if baselines["pooled"][2] >= command_metrics.MIN_BASELINE_PITCHES:
                command_plus_value = command_metrics.session_command_plus(view_pitches, baselines)

            tier_cards = [
                {"label": f'{label} Hit% (\u2264{radius:.0f}")', "value": _fmt_pct(scorecard["tier_pcts"].get(label))}
                for radius, label in command_config.TARGET_RADII_IN
            ]
            children = [ui_helpers.render_kpi_cards([
                {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
                {"label": "Command+", "value": _fmt_grade(command_plus_value)},
                {"label": "Avg Miss", "value": f'{scorecard["avg_miss_distance"]}"' if scorecard["avg_miss_distance"] is not None else "—"},
                *tier_cards,
                {"label": "Major Miss %", "value": _fmt_pct(scorecard["major_miss_pct"])},
            ])]
            bias = command_metrics.miss_bias(view_pitches, throws)
            children.append(ui.p(f"Average miss bias: {_cmd_bias_label(bias)}", class_="text-muted small mt-2"))

            # Per-pitch miss direction (Ryker, Sept 2026: "would like to
            # be able to see a miss bias for each individual pitch ...
            # figure out why they miss where they miss ... if i am
            # trying to go down and away do i always miss arm side") --
            # no inches, just which way each pitch missed and what it
            # was called, so a pattern by call is scannable at a glance.
            children.append(ui.h6("Miss direction by pitch", class_="mt-3"))
            children.append(ui.p(
                "Called is the pitcher's own Level+Zone code (e.g. \"25\") for that pitch's target -- scan for a "
                "repeated code to see whether that call tends to miss the same way.",
                class_="text-muted small",
            ))
            children.append(ui_helpers.render_dict_table(command_metrics.miss_direction_rows(view_pitches, throws)))

            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def pp_command_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, _throws = _view_pitches()
        if not view_pitches:
            return None
        located = [p for p in view_pitches if p.horizontal_miss is not None]
        if not located:
            return None
        return command_charts.command_chart(view_pitches)
