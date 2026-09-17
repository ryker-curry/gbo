"""
GBO -- Pitcher Profile (Aug 2026, Phase 0 of STUFF-LOCATION-PITCHING-
PLUS-PLAN.md). A filterable, per-pitcher deep dive: counting stats,
pitch-type breakdown, Stuff+/Location+/Pitching+ grades, pitch usage,
attack-zone distribution, a grade trend over time, the reused Bullpen
Dashboard physical charts, Command Target Zones, and a full Individual
Pitches table. Sits alongside the existing Analytics page as a coach-
facing (and player-facing, self-scoped) advanced view -- not a
replacement for it.

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
pitch_results_chart.py). Metrics is the old Physical Profile section,
Zone is Attack Zone Distribution + Command Target Zones, Arsenal is the
Arsenal table + Pitch Type Breakdown + Individual Pitches. Overview
keeps the Line/Grades/Performance/Pitch Usage/Trend content pp_body
used to open with -- still the default first thing a viewer sees.

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
game_id), bullpen_dashboard_display.register_bullpen_dashboard
(Physical Profile -- the exact same Bullpen Dashboard charts, pointed at
this pitcher's WHOLE Rapsodo history in the selected date range --
bullpen sessions and intrasquad games alike as of Sept 2026, via the
"player_pitches" target kind added to bullpen_dashboard_display.py
specifically for this page, rather than the bullpen-only "combined"
kind My Bullpens/the standalone Bullpen Dashboard use), and
analytics/pitch_grading.py (Stuff+/Location+/Pitching+/Arsenal).
analytics/profile_queries.py is the one new piece: the date-range/
pitch-type/game-scope filtered queries this page needs that
game_stats.py's season/single-game queries don't cover.
"""

from datetime import date, timedelta

from shiny import module, ui, render, req, reactive
from shinywidgets import output_widget, render_plotly
from database import get_session
from models import Player, User, PitchType, PlayerPitchArsenal, StaffPlayerAssignment
from game_stats import compute_pitching_line, compute_pitch_type_breakdown
from strike_zone import classify_attack_zone
import command_config
from analytics import command_metrics, performance_score, profile_queries
from analytics.pitch_grading import (
    stuff_plus, location_plus, pitching_plus, arsenal_summary, MIN_BASELINE_PITCHES,
)
from visualizations import command_charts, profile_charts
from visualizations.pitch_results_chart import pitch_results_chart
from pitch_type_config import get_pitch_color

import ui_helpers
import bullpen_dashboard_display
import format_helpers
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


def _my_player(db, app_state):
    me = db.query(User).filter(User.user_id == app_state.user_id()).first()
    if me is None or me.player_id is None:
        return None
    return db.query(Player).filter(Player.player_id == me.player_id).first()


# NOTE (Aug 31 2026): _grade_ring_status/_grade_rings used to live here
# -- moved to shiny_app/ui_helpers.py as mean100_ring_status/
# render_percentile_bars (Savant/mlbpitchprofiler.com-style percentile
# bars, per Ryker's own reference site, replacing the ring treatment
# for this grade family) so hitter_profile.py's new Performance section
# can reuse the same component. See pp_overview_section()'s Grades
# section below and ui_helpers.render_percentile_bars' docstring.


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
    # Physical Profile -- reused Bullpen Dashboard (register once here,
    # per bullpen_dashboard_display's own "mount once" convention; its
    # returned fragment is embedded inside pp_metrics_section below).
    # -------------------------------------------------------------------

    def _get_physical_target(input):
        """Sept 2026: was bullpen-only (bullpen_ids_for_player, ignoring
        the Pitch Type/Games filters entirely) -- now pulls this
        player's RapsodoPitch history bullpen AND game alike
        (profile_queries.get_pitcher_rapsodo_pitches, the same unified
        query already backing this page's "no pitches in this range"
        gate above), respecting all three filters (date range, pitch
        type, game scope) the way every other section on this page
        already does. Ryker's call: the Physical Profile dashboard
        (Movement/Release/Location/Spin, arm angle) is the coach-and-
        player "dig deeper" place for a pitcher's whole Rapsodo history,
        not just bullpen reps -- an intrasquad outing's ball flight data
        matters just as much here. Feeds bullpen_dashboard_display's new
        "player_pitches" target kind (a plain id list, not bullpen_ids)
        added specifically for this -- "session"/"combined" (My
        Bullpens, this page's own earlier version) are untouched."""
        req("pp_date_from" in input)
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None
            f = _current_filters()
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            if not rapsodo_pitches:
                return None
            return {"kind": "player_pitches", "player": player, "rapsodo_pitch_ids": [p.rapsodo_pitch_id for p in rapsodo_pitches]}
        finally:
            db.close()

    _physical_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "pp_phys", _get_physical_target,
    )

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
                        "arsenal": "Arsenal",
                    },
                ),
            )
        finally:
            db.close()

    def _compute_grading_bundle(db, game_pitches, rapsodo_pitches):
        """Shared derived-data pass over one filtered pitch window --
        Stuff+/Location+/Pitching+ per pitch, pitch usage counts,
        attack-zone counts, the Pitching+ trend series, the Arsenal
        rollup, and the Individual Pitches rows. Factored out of what
        used to be one single pp_body loop so pp_overview_section/
        pp_zone_section/pp_arsenal_section can each call it fresh (same
        "only the selected view queries anything" principle
        pitcher_game_report.py's own gated sections already establish)
        without tripling this ~60-line loop three ways."""
        stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
        location_baseline = profile_queries.team_location_plus_baseline(db)

        game_pitch_ids = [p.game_pitch_id for p in game_pitches]
        rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, game_pitch_ids)

        def _type_label(pitch_type_obj):
            return pitch_type_obj.type_name if pitch_type_obj is not None else "Unspecified"

        pitch_type_grades = {}
        individual_rows = []
        trend_points = []
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
                trend_points.append((p.game.game_date, pi_val))

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
            "trend_points": trend_points,
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

            sections = [ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title")]

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
                sections.append(output_widget("pp_trend_chart"))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def pp_metrics_section():
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
            pid = _current_player_id(db)
            if pid is None:
                return None
            return ui.div(
                ui.p(ui.strong("Physical Profile")),
                ui.p(
                    "Same Movement/Release Point/Location/Spin Axis charts as the Bullpen Dashboard, built from every "
                    "Rapsodo-linked pitch this pitcher has -- bullpen sessions AND intrasquad games alike -- matching "
                    "the Pitch Type/Games filters above.",
                    class_="text-muted small",
                ),
                _physical_fragment,
            )
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
        Flare-Burner labels, same six-bucket idea."""
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
            type_rows = [r for r in rows if r["Pitch Type"] != "Total" and (r["Balls in Play"] or 0) > 0]
            if not type_rows:
                return ui.p(
                    "No balls in play in this range yet -- Results needs at least one ball in play per pitch type.",
                    class_="text-muted small",
                )
            return ui.div(
                ui.p(ui.strong("Results")),
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
            sections = [ui.p(ui.strong("Attack Zone Distribution"))]
            total_located = sum(bundle["zone_counts"].values())
            if not total_located:
                sections.append(ui.p("No located pitches yet.", class_="text-muted small"))
            else:
                sections.append(ui.p("Heart = down the middle, Shadow = zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                sections.append(_stacked_bar([
                    (zone, round(100 * bundle["zone_counts"][zone] / total_located, 1), ATTACK_ZONE_COLORS[zone])
                    for zone in ("Heart", "Shadow", "Chase", "Waste")
                ]))
            return ui.div(*sections)
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
            sections = []

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
                vs_rhh = [p for p in game_pitches if p.opponent_hand == "R"]
                vs_lhh = [p for p in game_pitches if p.opponent_hand == "L"]
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
            points = []
            for p in game_pitches:
                label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
                rap = rap_by_gp.get(p.game_pitch_id)
                s_val = stuff_plus(rap, stuff_baselines.get(label)) if rap is not None else None
                l_val = location_plus(p, location_baseline)
                pi_val = pitching_plus(s_val, l_val)
                if pi_val is not None and p.game is not None:
                    points.append((p.game.game_date, pi_val))
            points.sort(key=lambda t: t[0])
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
        if input.pp_view() != "zone":
            return None
        _current_filters()
        view_pitches, _throws = _view_pitches()
        if not view_pitches:
            return None
        return ui.div(
            ui.hr(),
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
        if input.pp_view() != "zone":
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
        if input.pp_view() != "zone":
            return None
        view_pitches, _throws = _view_pitches()
        if not view_pitches:
            return None
        located = [p for p in view_pitches if p.horizontal_miss is not None]
        if not located:
            return None
        return command_charts.command_chart(view_pitches)
