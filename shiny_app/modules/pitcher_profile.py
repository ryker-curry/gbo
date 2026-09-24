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
in the selected date range -- games only, not bullpen sessions (Sept
2026, Ryker: "i want pitcher profile to only pull pitches from games"
-- see profile_queries.get_pitcher_rapsodo_pitches' game_linked_only
param), via profile_queries.get_pitcher_rapsodo_pitches, the same
unified query this page's Zone tab already uses), and
analytics/pitch_grading.py (Stuff+/Location+/Pitching+/Arsenal).
analytics/profile_queries.py is the one new piece: the date-range/
pitch-type/game-scope filtered queries this page needs that
game_stats.py's season/single-game queries don't cover.
"""

from datetime import date, timedelta

from shiny import module, ui, render, req, reactive
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload
from database import get_session
from models import Player, User, PitchType, PlayerPitchArsenal, StaffPlayerAssignment, Game, GamePitch, RapsodoPitch
from game_stats import compute_pitching_line, compute_pitch_type_breakdown, get_batter_hands, compute_pitch_mix_by_count
from strike_zone import classify_attack_zone
import command_config
from analytics import command_metrics, performance_score, profile_queries
from analytics.pitch_grading import (
    stuff_plus, location_plus, pitching_plus, MIN_BASELINE_PITCHES,
    tunnel_type_pair_summary, team_tunneling_baseline, tunneling_plus, MIN_TUNNELING_PAIRS,
)
# Pitch Type Breakdown's cards-plus-grouped-tabs display (Sept 2026,
# Ryker: "want it to be similar in pitcher profile") -- reused from
# pitcher_game_report.py, where that redesign happened first, rather
# than a second implementation. Same cross-module private-helper reuse
# convention modules/hitter_tracking.py already establishes for
# hitter_game_report.py/hitter_profile.py.
from modules.pitcher_game_report import _pitch_type_breakdown_with_stuff, _pitch_type_breakdown_view
from visualizations import command_charts, profile_charts
from visualizations.pitch_results_chart import pitch_results_chart
from visualizations.count_leverage_chart import count_leverage_chart
from visualizations.pitch_location_heatmap import pitch_location_heatmaps, MIN_FOR_CONTOUR
import glossary_content
from pitch_type_config import get_pitch_color, FASTBALL_TYPES

import ui_helpers
import format_helpers
from analytics.bullpen_metrics import (
    pitch_type_summary, average_estimated_arm_angle, pitch_type_label,
    fastball_trajectory_diagnostic, vaa_trajectory_triples, team_havaa_baseline,
)
from visualizations.bullpen_charts import movement_chart, release_point_chart, color_for_pitch_label
from visualizations.pitcher_graphic import pitcher_release_svg
from visualizations.attack_zones_chart import attack_zones_figure
from pitch_location_stats import compute_attack_zones
from visualizations.spin_axis_chart import average_spin_axis_chart, individual_spin_axis_chart
from format_helpers import (
    format_pct as _fmt_pct,
    format_num as _fmt,
    game_label as _game_label,
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
        ui.output_ui("pp_tunneling_section"),
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

            # Game selector (Sept 2026, Ryker: "for everything in
            # pitcher profile be able to select a specific game as
            # well as the entire season view") -- same own_player_id/
            # opponent_our_player_id dual lookup pitcher_game_report.py's
            # own game_picker uses (an intrasquad game records "the
            # other squad's" pitcher under opponent_our_player_id, not
            # our_player_id), scoped to this one pitcher. "Season" is
            # the default and behaves exactly as before this feature --
            # From/To/Games below still apply. Picking one game
            # overrides From/To/Games entirely (see _current_filters).
            own_game_ids = {
                gid for (gid,) in db.query(GamePitch.game_id)
                .filter(GamePitch.our_player_id == pid, GamePitch.is_our_team_batting.is_(False))
                .distinct().all()
            } | {
                gid for (gid,) in db.query(GamePitch.game_id)
                .filter(GamePitch.opponent_our_player_id == pid, GamePitch.is_our_team_batting.is_(True))
                .distinct().all()
            }
            games = (
                db.query(Game).filter(Game.game_id.in_(own_game_ids)).order_by(Game.game_date.desc()).all()
                if own_game_ids else []
            )
            game_choices = {"__season__": "Season (All Games)"}
            for g in games:
                game_choices[str(g.game_id)] = _game_label(g)
        finally:
            db.close()

        return ui.layout_columns(
            ui.input_select("pp_game_select", "Game", choices=game_choices),
            ui.input_date("pp_date_from", "From", value=date.today() - timedelta(days=365)),
            ui.input_date("pp_date_to", "To", value=date.today()),
            ui.input_select("pp_pitch_type", "Pitch Type", choices=type_choices),
            ui.input_select("pp_game_scope", "Games", choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[2, 3, 3, 2, 2],
        )

    def _current_filters():
        req("pp_date_from" in input)
        req("pp_date_to" in input)
        req("pp_pitch_type" in input)
        req("pp_game_scope" in input)
        pitch_type = input.pp_pitch_type()
        game_id = None
        if "pp_game_select" in input and input.pp_game_select() and input.pp_game_select() != "__season__":
            game_id = int(input.pp_game_select())
        return {
            # A specific game overrides the date range entirely rather
            # than narrowing within it -- picking a game and having
            # From/To silently also exclude it (e.g. From/To left at
            # last season while switching games) would be a confusing
            # way to fail. game_scope is moot too once one exact game
            # is picked, so it's left as-is and simply unused downstream
            # (see analytics.profile_queries._apply_filters).
            "date_from": None if game_id is not None else input.pp_date_from(),
            "date_to": None if game_id is not None else input.pp_date_to(),
            "pitch_type": None if pitch_type == "__all__" else pitch_type,
            "game_scope": input.pp_game_scope(),
            "game_id": game_id,
        }

    # -------------------------------------------------------------------
    # Physical Profile -- pure chart builders called directly (Sept
    # 2026 rebuild, see module docstring). _physical_target(db) is the
    # one shared query pp_metrics_section and the three chart outputs
    # below all call -- same "player_pitches" scope (this pitcher's
    # WHOLE Rapsodo history, GAMES ONLY -- see module docstring's
    # "games only, not bullpen sessions" note -- filtered by date
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
            game_id=f["game_id"], game_linked_only=True,
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
                game_id=f["game_id"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_id=f["game_id"], game_linked_only=True,
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
                        "tunneling": "Tunneling+",
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
    @reactive.event(input.pp_glossary_tunneling)
    def _pp_show_tunneling_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Tunneling+ Glossary", glossary_content.TUNNELING))

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
                game_id=f["game_id"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_id=f["game_id"], game_linked_only=True,
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
                "\"Overall\" below is blended across every pitch type thrown in this window (each pitch type "
                "counted once, not weighted by how often it's thrown), not a single pitch's grade -- the "
                "per-pitch-type breakdown underneath it grades each pitch against the team's own population of "
                "that SAME pitch type (a 4-Seam Fastball's Stuff+ never blends with sliders or changeups). The "
                "Arsenal tab has the same per-pitch-type numbers as a compact table, with Usage % and pitch "
                "counts alongside them.",
                class_="text-muted small fst-italic",
            ))

            bundle = profile_queries.compute_grading_bundle(db, game_pitches, rapsodo_pitches)
            stuff_plus_value = bundle["stuff_plus_value"]
            location_plus_value = bundle["location_plus_value"]
            pitching_plus_value = bundle["pitching_plus_value"]
            arsenal_rows = bundle["arsenal_rows"]

            grade_bars = ui_helpers.render_percentile_bars([
                ("Stuff+ (Overall)", stuff_plus_value),
                ("Location+ (Overall)", location_plus_value),
                ("Pitching+ (Overall)", pitching_plus_value),
            ])
            if grade_bars is not None:
                sections.append(grade_bars)
            else:
                sections.append(ui.p("No graded pitches yet in this range -- needs Rapsodo-linked pitches (Stuff+) or located game pitches (Location+).", class_="text-muted small"))

            # Per-pitch-type grades (Sept 2026, Ryker: "for pitcher
            # profile overview i want stuff+, location+, pitching+ for
            # each pitch as well as overall pitches not just for all
            # pitches... a 4sfb would have a stuff+ score and a
            # percentile that is specific to that pitch type") --
            # arsenal_rows (from compute_grading_bundle -> arsenal_
            # summary) already grades every pitch type against ITS OWN
            # team-wide population (stuff_baselines/location_baseline
            # are both keyed by pitch type label -- see
            # profile_queries.compute_grading_bundle), so this is
            # display-only: the same per-type numbers the Overall bars
            # above are themselves averaged FROM, just shown
            # individually instead of blended. Reuses the exact same
            # mlbpitchprofiler.com-style percentile-bar component as
            # Overall, one group per pitch type, sorted by usage
            # (arsenal_summary's own sort order).
            if arsenal_rows:
                sections.append(ui.p(ui.strong("By Pitch Type"), class_="mt-3"))
                for row in arsenal_rows:
                    reliability_note = "" if row["Reliable"] else " -- small sample, grade may swing"
                    sections.append(ui.p(
                        ui.strong(row["Pitch Type"]),
                        f" — {row['Usage %']}% usage, {row['Pitches']} pitches{reliability_note}",
                        class_="mt-2 mb-1",
                    ))
                    type_bars = ui_helpers.render_percentile_bars([
                        ("Stuff+", row["Stuff+"]),
                        ("Location+", row["Location+"]),
                        ("Pitching+", row["Pitching+"]),
                    ])
                    sections.append(
                        type_bars if type_bars is not None
                        else ui.p("No graded pitches of this type yet.", class_="text-muted small")
                    )

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
                    ui.p("No Rapsodo-linked GAME pitches in this range yet.", class_="text-muted small"),
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
                    "Est. VAA": row.get("Est. VAA", "N/A"),
                })

            # Fastball Trajectory / HAVAA (Sept 2026, Ryker: "add height
            # adjusted vertical approach angle (HAVAA) to pitcher
            # profile") -- same fastball_trajectory_diagnostic() card
            # Bullpen Dashboard already shows (analytics/bullpen_metrics.py,
            # ported here rather than reinventing it), one per fastball-
            # family pitch type this pitcher actually threw in this
            # window. Rendered with this page's own KPI-card look
            # (ui_helpers.render_kpi_cards) instead of Bullpen Dashboard's
            # dark-themed _card() styling, for visual consistency with the
            # rest of Pitcher Profile.
            havaa_baseline = _team_havaa_baseline(db)
            trajectory_children = []
            present_fastball_types = [t for t in FASTBALL_TYPES if t in groups_by_label]
            for canonical_type in present_fastball_types:
                diag = fastball_trajectory_diagnostic(
                    rapsodo_pitches, player, canonical_pitch_type=canonical_type, havaa_baseline=havaa_baseline,
                )
                if diag is None:
                    continue
                trajectory_children.append(ui.p(
                    ui.strong(f"Fastball Trajectory — {canonical_type}"), f" (n={diag['n']})",
                    class_="mt-3 mb-1",
                ))
                trajectory_children.append(ui_helpers.render_kpi_cards([
                    {"label": "Velocity", "value": f"{diag['Velocity']:.1f} mph" if diag["Velocity"] is not None else "—"},
                    {"label": "VB", "value": f'{diag["VB"]:.1f}"' if diag["VB"] is not None else "—"},
                    {"label": "VAA", "value": diag["VAA"]},
                    {"label": "HAVAA", "value": diag["HAVAA"]},
                    {"label": "Release Height", "value": f'{diag["Release Height"]:.2f} ft' if diag["Release Height"] is not None else "—"},
                    {"label": "Extension", "value": f'{diag["Extension"]:.2f} ft' if diag["Extension"] is not None else "—"},
                    {"label": "Arm Angle", "value": diag["Arm Angle"]},
                    {"label": "Trajectory", "value": diag["Trajectory"]},
                ]))
            if trajectory_children:
                trajectory_children.append(ui.p(
                    "HAVAA (Height-Adjusted VAA): how many standard deviations flatter (+) or steeper (-) than a "
                    "typical pitch of the SAME type crossing the plate at the SAME height, against a team-wide "
                    "baseline -- isolates true ride/carry from the geometric fact that raw VAA is naturally "
                    "flatter high in the zone and steeper low. Estimated VAA/Arm Angle are geometric estimates "
                    "from release point and plate-crossing data, not direct biomechanical measurements.",
                    class_="text-muted small",
                ))

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
                    "Every Rapsodo-linked pitch this pitcher has thrown in real games (intrasquad or external) "
                    "in this window, broken out by pitch type -- bullpen sessions aren't counted here.",
                    class_="text-muted small",
                ),
                ui_helpers.render_dict_table(table_rows),
                *trajectory_children,
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

    # -------------------------------------------------------------------
    # Tunneling+ (Sept 2026, Ryker: "keep working on the trajectory
    # model for the tunneling+ model", then "need to look at release
    # point as well. would like to combine all of these things to
    # create our own", then "give tunneling its own tab in dropdown") --
    # split out of Metrics into its own View entry. Two reasons: it's
    # conceptually its own analysis (pitch-pair sequencing, not a
    # single pitch's physical profile), and practically, this section
    # has NO input controls of its own, so its .shiny-html-output
    # wrapper never matches theme.py's ".gbo-content .shiny-html-
    # output:has(.shiny-input-container)" rule -- the one that boxes
    # Metrics (which DOES have input_slider/input_radio_buttons for its
    # charts) into a single max-width:900px card. Outside that box,
    # .gbo-kpi-row's own grid (repeat(auto-fit, minmax(160px,1fr)))
    # can actually spread its cards across the full page width instead
    # of every row falling back to one card per line (Ryker: "don't
    # want all the kpi cards to be one vertical line up and down.
    # spread them across in a way that makes sense").
    # -------------------------------------------------------------------

    @render.ui
    def pp_tunneling_section():
        """Grades how well each secondary pitch this pitcher threw
        tunnels off his primary fastball, using real back-to-back pitch
        sequences (bullpen reps and real game plate appearances alike --
        see _tunneling_pairs_for_player) and the cached flight-path
        physics (pitch_trajectory.py) rather than a chart. Tunnel/Plate/
        Late Break/Ratio follow Baseball Prospectus's published
        methodology (now measured at a fixed TIME before the plate
        rather than a fixed distance -- see analytics/pitch_grading.py's
        DECISION_TIME_BEFORE_PLATE_S comment for why); Tunneling+ itself
        is a GBO-specific blend of Ratio and Release Consistency (see
        that module's tunneling_plus docstring for the full citations
        and math). Velo Diff/Break Diff are shown as separate context,
        NOT part of the grade (Ryker's call, after reviewing
        seemagnus.com's finding that they predict whiffs independently
        -- see tunnel_pair_metrics' docstring for why they're kept out
        of the score itself).

        Cards are grouped into rows that mean something (Ryker: "spread
        them across in a way that makes sense") rather than one long
        strip: tunnel geometry (Tunnel/Plate/Late Break/Ratio), then
        release consistency and the grade itself (Release/Release
        Height Diff/Release Side Diff/Tunneling+ -- Ryker: "i want to
        see release height and release side differences in tunneling
        section"; the height/side split is display-only context, same
        as Velo/Break Diff below -- tunneling_plus still grades on the
        one combined Release number, see pitch_grading.tunnel_pair_
        metrics' docstring), then context. Both graded rows pass
        accent=True (Ryker: "incorporate more red in these") for the
        crimson-tinted .gbo-kpi-card-accent look (theme.py); the plain
        context row keeps the default card style so the "not part of
        the grade" cards don't read as equally important."""
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "tunneling":
            return None
        db = get_session()
        try:
            header = ui.div(
                ui.p(ui.strong("Tunneling+"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("pp_glossary_tunneling", "Tunneling+ Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )
            player, rapsodo_pitches = _physical_target(db)
            if player is None or not rapsodo_pitches:
                return ui.div(
                    header,
                    ui.p("No Rapsodo-linked GAME pitches in this range yet.", class_="text-muted small"),
                )

            primary_fb = _primary_fastball_type(rapsodo_pitches)
            if primary_fb is None:
                return ui.div(
                    header,
                    ui.p(
                        "This pitcher has no fastball-family pitch in this range to tunnel other pitches off of.",
                        class_="text-muted small",
                    ),
                )

            tunneling_pairs = _tunneling_pairs_for_player(rapsodo_pitches)
            secondary_types = sorted({pitch_type_label(p) for p in rapsodo_pitches} - FASTBALL_TYPES)
            tunneling_baseline = None
            children = []
            for secondary in secondary_types:
                summary = tunnel_type_pair_summary(tunneling_pairs, primary_fb, secondary)
                if summary is None:
                    continue
                if tunneling_baseline is None:
                    tunneling_baseline = _team_tunneling_baseline(db)
                grade = tunneling_plus(summary, secondary, tunneling_baseline)
                children.append(ui.p(
                    ui.strong(f"{secondary} off {primary_fb}"), f" (n={summary['n']} sequences)",
                    class_="mt-4 mb-2",
                    style="border-left:3px solid var(--gbo-crimson); padding-left:10px;",
                ))
                children.append(ui_helpers.render_kpi_cards([
                    {"label": "Tunnel", "value": f"{summary['tunnel_in']}\""},
                    {"label": "Plate", "value": f"{summary['plate_in']}\""},
                    {"label": "Late Break", "value": f"{summary['late_break_in']}\""},
                    {"label": "Ratio", "value": f"{summary['ratio']}"},
                    {"label": "Break:Tunnel % (BP)", "value": f"{summary['break_tunnel_pct']}%"},
                ], accent=True))
                children.append(ui_helpers.render_kpi_cards([
                    {"label": "Release (Combined)", "value": f"{summary['release_in']}\"" if summary["release_in"] is not None else "—"},
                    {"label": "Release Height Diff", "value": f"{summary['release_height_diff_in']}\"" if summary["release_height_diff_in"] is not None else "—"},
                    {"label": "Release Side Diff", "value": f"{summary['release_side_diff_in']}\"" if summary["release_side_diff_in"] is not None else "—"},
                    {"label": "Tunneling+", "value": grade if grade is not None else "—"},
                ], accent=True))
                context_cards = []
                if summary["velo_diff_mph"] is not None:
                    context_cards.append({"label": "Velo Diff", "value": f"{summary['velo_diff_mph']} mph"})
                if summary["break_diff_in"] is not None:
                    context_cards.append({"label": "Vert Break Diff", "value": f"{summary['break_diff_in']}\""})
                if context_cards:
                    children.append(ui.p("For context (not part of the grade):", class_="text-muted small mb-1 mt-1"))
                    children.append(ui_helpers.render_kpi_cards(context_cards))
            if children:
                children.append(ui.p(
                    f"Tunnel: how far apart (in inches) this pitch and the {primary_fb} still are ~167ms "
                    "before THIS pitch would cross the plate -- roughly when a hitter must commit to swing. "
                    "Plate: how far apart they end up at the plate. Late Break: the difference (separation "
                    "added after the decision point). Ratio: Plate/Tunnel -- GBO's own metric, higher means "
                    "the pitches looked more alike early and diverged more late. Break:Tunnel % (BP): Late "
                    "Break / Tunnel as a percentage -- this is the actual formula Baseball Prospectus "
                    "published as their \"Break:Tunnel Ratio\" (GBO's own Ratio field above shares a similar "
                    "name but isn't the same formula). Release (Combined): separation between the two "
                    "pitches' real release points -- a pitcher who releases two pitch types from visibly "
                    "different slots is telegraphing before the ball even leaves his hand, regardless of how "
                    "well the flight paths converge afterward. Release Height Diff/Release Side Diff break that "
                    "same separation into its two axes (how high vs. how far to the side) -- context for "
                    "coaching the fix, not separately graded. Tunneling+ blends Ratio (higher is better) and "
                    "the combined Release number (lower is better) against the rest of the team, equally "
                    "weighted (100 = team average, 10 points = 1 SD) -- a placeholder weighting, not a "
                    "validated one. Velo Diff/Vert Break Diff are shown for context only, not folded into the "
                    f"grade. Built only from real back-to-back pitch sequences (at least {MIN_TUNNELING_PAIRS} "
                    "needed per pitch pair) -- bullpen reps and real game plate appearances, not random "
                    "pitches paired across different outings.",
                    class_="text-muted small",
                ))
                children.append(ui.p(
                    "For reference: Baseball Prospectus's original 2017 MLB-wide study (Pavlidis/Long/Judge, "
                    "\"Introducing Pitch Tunnels\") found league averages of about 10.0\" Tunnel, 18.7\" Plate, "
                    "2.6\" Late Break, 27.6% Break:Tunnel %, and 2.4\" Release separation (their most consistent "
                    "pitcher in that sample, Jon Lester, sat at 1.2\" Release). These aren't a direct "
                    "apples-to-apples comparison to the numbers above -- that study measured at a fixed "
                    "23.8-foot point rather than GBO's fixed 167ms-before-plate point, and its sample was MLB "
                    "pitchers, not Division II college -- but they're a reasonable sense of scale. Tunneling+ "
                    "itself, and Velo Diff/Vert Break Diff, have no outside published benchmark to compare "
                    "against -- Tunneling+ is a GBO-specific blend that doesn't exist elsewhere, so \"good\" "
                    "only means relative to the rest of this team (100 = team average, 110 = one standard "
                    "deviation better).",
                    class_="text-muted small",
                ))
            elif secondary_types:
                children.append(ui.p(
                    "Not enough back-to-back pitch sequences yet to grade tunneling for this pitcher's "
                    "secondary pitches against his fastball.",
                    class_="text-muted small",
                ))
            else:
                children.append(ui.p(
                    "This pitcher has no secondary pitch types in this range to tunnel off his fastball.",
                    class_="text-muted small",
                ))
            return ui.div(header, *children)
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_id=f["game_id"], game_linked_only=True,
            )
            if not game_pitches and not rapsodo_pitches:
                return None
            bundle = profile_queries.compute_grading_bundle(db, game_pitches, rapsodo_pitches)
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_id=f["game_id"], game_linked_only=True,
            )
            if not game_pitches and not rapsodo_pitches:
                return None
            bundle = profile_queries.compute_grading_bundle(db, game_pitches, rapsodo_pitches)
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
                # Cards (headline stats, incl. Stuff+ -- this cut is by
                # opponent hand, which the Arsenal table above doesn't
                # split by, so it's not pure duplication) + grouped
                # detail tabs, same _pitch_type_breakdown_with_stuff/
                # _pitch_type_breakdown_view pitcher_game_report.py uses.
                rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in game_pitches])
                stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
                sections.append(ui.navset_tab(
                    ui.nav_panel("All Batters", _pitch_type_breakdown_view(_pitch_type_breakdown_with_stuff(game_pitches, rap_by_gp, stuff_baselines))),
                    ui.nav_panel("vs RHH", _pitch_type_breakdown_view(_pitch_type_breakdown_with_stuff(vs_rhh, rap_by_gp, stuff_baselines)) if vs_rhh else ui.p("No pitches vs a right-handed batter in this range.", class_="text-muted small")),
                    ui.nav_panel("vs LHH", _pitch_type_breakdown_view(_pitch_type_breakdown_with_stuff(vs_lhh, rap_by_gp, stuff_baselines)) if vs_lhh else ui.p("No pitches vs a left-handed batter in this range.", class_="text-muted small")),
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
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
                game_id=f["game_id"],
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
            # profile_queries.aggregate_trend_by_game's docstring.
            points = profile_queries.aggregate_trend_by_game(pitch_points)
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
                game_id=f["game_id"],
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

    def _team_havaa_baseline(db):
        """Team-wide Height-Adjusted VAA baseline (Sept 2026, Ryker:
        "add height adjusted vertical approach angle (HAVAA) to pitcher
        profile") -- ported from bullpen_dashboard_display.py's own
        _team_havaa_baseline_query/_havaa_baseline rather than
        reinventing it. HAVAA compares a pitch's VAA against every
        OTHER pitch in a real game (any pitcher) that crossed the plate
        at roughly the same height, so this is deliberately NOT scoped
        to this page's own player/date filters -- same
        team-wide-population idea as _team_command_plus_baselines
        above. Only pulls the 4 columns calculate_estimated_vaa needs,
        filtered not-null here so a missing value can't silently
        produce a bad baseline entry.

        Games-only (Sept 2026, Ryker: "i want pitcher profile to only
        pull pitches from games") -- excludes bullpen-sourced readings
        via RapsodoPitch.bullpen_id.is_(None), same filter every
        rapsodo_pitches query on this page now applies (see
        profile_queries.get_pitcher_rapsodo_pitches' game_linked_only
        param), so the population a pitcher's OWN games-only HAVAA gets
        compared against matches what's actually being measured."""
        rows = (
            db.query(RapsodoPitch)
            .options(joinedload(RapsodoPitch.pitch_type))
            .filter(
                RapsodoPitch.bullpen_id.is_(None),
                RapsodoPitch.release_height.isnot(None),
                RapsodoPitch.release_angle.isnot(None),
                RapsodoPitch.release_extension.isnot(None),
                RapsodoPitch.plate_z_ft.isnot(None),
            )
            .all()
        )
        return team_havaa_baseline(vaa_trajectory_triples(rows))

    def _primary_fastball_type(pitches):
        """Whichever FASTBALL_TYPES member this pitcher threw the most
        of, among the given pitches -- same "primary is picked per
        pitcher, not assumed team-wide" reasoning as
        profile_queries.team_pitcher_primary_fastball_velocity, just
        scoped to whatever pool of pitches Tunneling+ is being computed
        from here (bullpen + game combined, not real-game-only). None
        if this pitcher has no fastball-family pitch in the pool."""
        counts = {}
        for p in pitches:
            label = pitch_type_label(p)
            if label in FASTBALL_TYPES:
                counts[label] = counts.get(label, 0) + 1
        return max(counts, key=counts.get) if counts else None

    def _tunneling_pairs_for_player(rapsodo_pitches):
        """Groups one player's RapsodoPitch rows (each already carrying
        a cached trajectory_json -- see pitch_grading.py's Tunneling+
        section) into real outings and returns every real back-to-back
        pair within them, for pitch_grading.tunnel_type_pair_summary to
        consume (Sept 2026, Ryker: "keep working on the trajectory
        model for the tunneling+ model").

        Bullpen-sourced pitches: grouped by bullpen_id, ordered by
        pitch_number (chronological within that session).

        Game-sourced pitches: ordered by game_pitch.pitch_sequence
        (global chronological order across the whole game), paired only
        when BOTH pitch_sequence AND game_pitch.pa_pitch_number advance
        by exactly 1 from one pitch to the next -- i.e. genuinely the
        very next pitch to the SAME batter in the SAME plate
        appearance, not the first pitch of a new at-bat (a new batter
        hasn't seen anything from this pitcher yet in that PA, so
        there's nothing to tunnel off of)."""
        pairs = []

        bullpen_groups = {}
        for p in rapsodo_pitches:
            if p.bullpen_id is not None:
                bullpen_groups.setdefault(p.bullpen_id, []).append(p)
        for group in bullpen_groups.values():
            group.sort(key=lambda p: p.pitch_number)
            pairs.extend(zip(group, group[1:]))

        game_pitches = [p for p in rapsodo_pitches if p.game_pitch is not None]
        game_pitches.sort(key=lambda p: p.game_pitch.pitch_sequence)
        for prev, cur in zip(game_pitches, game_pitches[1:]):
            gp_prev, gp_cur = prev.game_pitch, cur.game_pitch
            if gp_prev.pa_pitch_number is None or gp_cur.pa_pitch_number is None:
                continue
            if gp_cur.pitch_sequence == gp_prev.pitch_sequence + 1 and gp_cur.pa_pitch_number == gp_prev.pa_pitch_number + 1:
                pairs.append((prev, cur))

        return pairs

    def _team_tunneling_baseline(db):
        """Team-wide Ratio/Release baseline per secondary pitch type
        (Sept 2026, Ryker: "keep working on the trajectory model for
        the tunneling+ model") -- every pitcher's own (primary fastball,
        secondary type) numbers (see pitch_grading.
        tunnel_type_pair_summary) feed pitch_grading.
        team_tunneling_baseline, same team-wide-population idea as
        _team_command_plus_baselines/_team_havaa_baseline above. Only
        reads RapsodoPitch.trajectory_json (already computed -- see
        pitch_trajectory.py) rather than recomputing anything, and
        deliberately NOT scoped to this page's own date/pitch-type
        filters -- a stable roster-wide reference, same as the other
        two team baselines.

        Games-only (Sept 2026, Ryker: "i want pitcher profile to only
        pull pitches from games") -- excludes bullpen-sourced readings,
        same as _team_havaa_baseline above. This also naturally means
        _tunneling_pairs_for_player's bullpen-session pairing branch
        never finds anything to pair here (every row it sees is already
        game-linked) -- real in-game plate-appearance sequences are the
        only source of tunneling pairs now, for every pitcher on the
        team, not just this page's own player."""
        rows = (
            db.query(RapsodoPitch)
            .options(joinedload(RapsodoPitch.pitch_type), joinedload(RapsodoPitch.game_pitch))
            .filter(RapsodoPitch.bullpen_id.is_(None), RapsodoPitch.trajectory_json.isnot(None))
            .all()
        )
        by_player = {}
        for p in rows:
            by_player.setdefault(p.player_id, []).append(p)

        pitcher_type_pair_summaries = []
        for player_pitches in by_player.values():
            primary = _primary_fastball_type(player_pitches)
            if primary is None:
                continue
            pairs = _tunneling_pairs_for_player(player_pitches)
            secondary_types = {pitch_type_label(p) for p in player_pitches} - FASTBALL_TYPES
            for secondary in secondary_types:
                summary = tunnel_type_pair_summary(pairs, primary, secondary)
                if summary is not None:
                    pitcher_type_pair_summaries.append((secondary, summary))

        return team_tunneling_baseline(pitcher_type_pair_summaries)

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

            ui.hr(),
            ui.p(ui.strong("Attack Zones")),
            ui.p(
                "Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste "
                "= nowhere near. GBO approximation of Statcast's own tiers.",
                class_="text-muted small",
            ),
            ui.output_ui("pp_attack_zones_table"),
            output_widget("pp_attack_zones_chart"),

            ui.hr(),
            ui.p(ui.strong("Miss by Call")),
            ui.p(
                "For pitches called to each location, by pitch type, how they actually missed on average -- scan "
                "for a pitch/call combo that consistently misses the same way.",
                class_="text-muted small",
            ),
            ui.output_ui("pp_miss_by_call_table"),

            ui.hr(),
            ui.p(ui.strong("Pitch Targeting Plan")),
            ui.p(
                "Recommended aim point per pitch type -- shifted opposite this pitcher's own average miss bias "
                "for that pitch, so if he tends to miss glove side on his slider, the recommendation aims a bit "
                "arm side of the true target instead.",
                class_="text-muted small",
            ),
            ui.output_ui("pp_targeting_plan_table"),
            output_widget("pp_targeting_plan_chart"),
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

            # Command+ by pitch type (Ryker, Sept 2026: "i want command+
            # by pitch type to show up in pitcher profile command and
            # execution" -- same table/column Pitcher Game Report already
            # has, added here too since Pitcher Profile's own window can
            # span multiple games/a date range, which is exactly the
            # larger sample this needs to be a trustworthy read (a
            # single game's count of one pitch type is noisy -- see the
            # caption below).
            plus_by_type = (
                command_metrics.command_plus_by_pitch_type(view_pitches, baselines)
                if baselines["pooled"][2] >= command_metrics.MIN_BASELINE_PITCHES else {}
            )
            by_type = command_metrics.command_by_pitch_type(view_pitches, throws)
            if len(by_type) > 1:
                # Ryker, Sept 2026: "the command+ should be the big card
                # style look ... by pitch type and then put command+ and
                # big cards have each pitch and its respective command+.
                # so we know what pitch each pitcher commands best, if
                # there is one he struggles with, etc" -- one KPI-style
                # card per pitch type instead of a column buried in the
                # detail table below, so the best/worst pitch reads at a
                # glance rather than requiring a scan across columns.
                if plus_by_type:
                    children.append(ui.h6("Command+ by pitch type", class_="mt-3"))
                    children.append(ui_helpers.render_kpi_cards([
                        {"label": row["Pitch Type"], "value": _fmt_grade(plus_by_type.get(row["Pitch Type"]))}
                        for row in by_type
                    ]))
                    children.append(ui.p(
                        "Which pitch this pitcher commands best -- and which he struggles with -- at a glance. "
                        "Same Command+ scale as the KPI above (100 = team average for that pitch type), just "
                        "broken out per pitch instead of blended into one number. A small pitch count for one "
                        "type is a noisy read -- widen the date range above for a steadier number.",
                        class_="text-muted small",
                    ))
                by_type_rows = []
                for row in by_type:
                    tier_cols = {
                        f'{label} % (\u2264{radius:.0f}")': (row["Tier Pcts"].get(label) if row["Tier Pcts"].get(label) is not None else "—")
                        for radius, label in command_config.TARGET_RADII_IN
                    }
                    by_type_rows.append({
                        "Pitch Type": row["Pitch Type"],
                        "Pitches": row["Pitches"],
                        "Avg Miss (in)": row["Avg Miss"] if row["Avg Miss"] is not None else "—",
                        "Danger-Adj. Miss (in)": row["Danger-Adj. Miss"] if row["Danger-Adj. Miss"] is not None else "—",
                        "Command Execution %": row["Command Execution %"] if row["Command Execution %"] is not None else "—",
                        **tier_cols,
                        "Major Miss %": row["Major Miss %"] if row["Major Miss %"] is not None else "—",
                        "Miss Bias": _cmd_bias_label(row["Miss Bias"]),
                    })
                children.append(ui.h6("By pitch type", class_="mt-3"))
                children.append(ui_helpers.render_dict_table(by_type_rows))

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

    # -------------------------------------------------------------------
    # Attack Zones / Miss by Call / Pitch Targeting Plan -- Sept 2026,
    # Ryker: "for pitcher profile command and execution tab add: attack
    # zones with attack zone chart ... miss by call, pitch targeting
    # plan, and command+." Command+ is the pre-existing Command Target
    # Zones block above. Attack Zones needs RAW GamePitch rows (all
    # located pitches, intended location irrelevant) so it queries
    # profile_queries directly rather than reusing _view_pitches()'s
    # command-view wrapper, which excludes any pitch with no intended
    # location on file -- same reasoning pitcher_game_report.py's
    # command_execution_section/attack_zones_chart already established;
    # chart itself now lives in visualizations/attack_zones_chart.py so
    # both pages share one implementation. Miss by Call and Pitch
    # Targeting Plan are both intent-vs-actual comparisons, so they
    # reuse _view_pitches() like Command Target Zones does, and mirror
    # pitcher_game_report.py's command_target_section/
    # pitch_targeting_plan_section table layouts exactly.
    # -------------------------------------------------------------------

    @render.ui
    def pp_attack_zones_table():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
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
                game_id=f["game_id"],
            )
            if not game_pitches:
                return None
            az_overall, az_by_type = compute_attack_zones(game_pitches)
            if az_overall["Located"] == 0:
                return ui.p("No located pitches yet.", class_="text-muted small")
            return ui.div(
                ui_helpers.render_kpi_cards([
                    {"label": "Heart %", "value": _fmt_pct(az_overall["Heart %"])},
                    {"label": "Shadow %", "value": _fmt_pct(az_overall["Shadow %"])},
                    {"label": "Chase Zone %", "value": _fmt_pct(az_overall["Chase Zone %"])},
                    {"label": "Waste %", "value": _fmt_pct(az_overall["Waste %"])},
                ]),
                ui_helpers.render_dict_table(az_by_type),
            )
        finally:
            db.close()

    @render_plotly
    def pp_attack_zones_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
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
                game_id=f["game_id"],
            )
            located = [p for p in game_pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
            if not located:
                return None
            return attack_zones_figure(located)
        finally:
            db.close()

    @render.ui
    def pp_miss_by_call_table():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, throws = _view_pitches()
        if not view_pitches:
            return None
        call_rows = command_metrics.miss_by_call(view_pitches, throws)
        if not call_rows:
            return ui.p("No called pitches with a logged location yet.", class_="text-muted small")
        return ui_helpers.render_dict_table([
            {
                "Pitch Type": row["Pitch Type"],
                "Called": row["Called"],
                "Pitches": row["Pitches"],
                "Typical Miss": _cmd_bias_label(row["Miss Bias"]),
            }
            for row in call_rows
        ])

    @render.ui
    def pp_targeting_plan_table():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, throws = _view_pitches()
        if not view_pitches:
            return None
        plan = command_metrics.pitch_targeting_plan(view_pitches, throws)
        if not plan:
            return ui.p(
                f"Pitch Targeting Plan needs at least {command_metrics.MIN_TARGETING_PITCHES} located pitches "
                "of a given pitch type in this window to recommend an aim point -- none qualify yet.",
                class_="text-muted small",
            )
        return ui_helpers.render_dict_table([
            {
                "Pitch Type": row["Pitch Type"],
                "Located": row["Located"],
                "Bias": row["Bias"],
                "Recommended Aim Shift": f'{row["recommended_aim_horizontal_in"]:+.1f}" horiz / {row["recommended_aim_vertical_in"]:+.1f}" vert',
            }
            for row in plan
        ])

    @render_plotly
    def pp_targeting_plan_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, throws = _view_pitches()
        if not view_pitches:
            return None
        plan = command_metrics.pitch_targeting_plan(view_pitches, throws)
        if not plan:
            return None
        return command_charts.pitch_targeting_chart(plan)
