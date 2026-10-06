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
from game_stats import compute_pitching_line, compute_pitch_type_breakdown, get_batter_hands, compute_pitch_mix_by_count, pitching_line_for
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
# Sept 2026, Ryker: "an opposing hitters heat map for each of my
# pitchers ... this would go in pitcher profile ... under the
# results section" -- run-value-by-zone, reusing this page's own
# existing Pitch Type filter (no separate dropdown needed, see
# pp_zone_damage_chart's own comment).
from analytics.pitcher_zone_damage import compute_zone_damage
from visualizations.zone_damage_chart import zone_damage_heatmap_by_hand
import plotly.graph_objects as go
from visualizations.chart_theme import apply_gbo_theme
import glossary_content
from pitch_type_config import get_pitch_color, FASTBALL_TYPES
from analytics import fastball_shape, pitch_class
import velo_fade_display
from analytics import velo_fade
from services.pitch_type_switch import apply_switches, undo_switches
from models import PitchTypeChange, ArsenalTarget
from analytics import approach_angles, best_zone, arsenal_plan, stuff_breakdown, trends, ivb_expected, slider_fit, sequencing
from visualizations import trend_charts
from visualizations.stuff_breakdown_chart import trait_impact_figure, strip_figure, outcome_figure, ordinal, fmt_value

# Stuff+ Breakdown styling (hide the plotly toolbar -- it sat on the titles).
_SB_CSS = """
.gbo-sb .modebar-container{display:none!important}
.gbo-sb .gbo-sb-why{font-weight:600;font-size:15px;margin:12px 0 4px}
.gbo-sb .gbo-sb-tips{margin:4px 0 6px;font-size:13.5px}
.gbo-sb .gbo-sb-val{font-size:20px;font-weight:700}
.gbo-sb .gbo-sb-pct{font-weight:700;font-size:13px;padding:2px 8px;border-radius:10px}
.gbo-sb .gbo-sb-pct.up{color:#3FB27F;background:rgba(63,178,127,.12)}
.gbo-sb .gbo-sb-pct.down{color:#D64545;background:rgba(214,69,69,.12)}
.gbo-sb .gbo-section-title-row .form-group{margin-bottom:0}
"""
from analytics.bullpen_metrics import average_estimated_arm_angle
from visualizations.arsenal_plan_chart import plan_movement_figure, progress_figure
from visualizations.best_zone_chart import best_zone_figure

import ui_helpers
from analytics import league_baselines
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


def _zone_hand_filtered(db, pitches, hand_choice):
    """Sept 2026, Ryker: "for the zone tab in pitcher profile be able
    to select vs right and left handed hitters" -- shared by pp_zone_
    section (Attack Zone Distribution bar + per-type breakdown table)
    and pp_location_heatmap (the density heatmap widget) so both
    pieces of the Zone tab reflect the same selection. Resolved via
    get_batter_hands (roster Player.bats/OpponentPlayer.bats, with the
    switch-hitter fix), same as every other hand-split view on this
    page (pp_arsenal_section, pp_zone_damage_chart) -- never the raw
    GamePitch.opponent_hand column, which silently holds the pitcher's
    own throwing hand instead of the batter's on a three-squad
    intrasquad pitch (get_batter_hands' own docstring)."""
    if hand_choice in (None, "All Batters"):
        return pitches
    hands = get_batter_hands(db, pitches)
    target = "R" if hand_choice == "vs RHH" else "L"
    return [p for p in pitches if hands.get(p.game_pitch_id) == target]


@module.ui
def pitcher_profile_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Profile", actions=ui_helpers.how_to_link("pitcher_profile")),
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
        ui.output_ui("pp_zone_hand_filter"),
        ui.output_ui("pp_zone_section"),
        ui.output_ui("pp_command_section"),
        ui.output_ui("pp_arsenal_section"),
        ui.output_ui("pp_trends_section"),
        ui.output_ui("pp_count_leverage_section"),
        ui.output_ui("pp_sequencing_section"),
        ui.output_ui("pp_fastball_shape_section"),
        ui.output_ui("pp_pitch_type_check_section"),
        ui.output_ui("pp_arsenal_plan_section"),
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
            view_choices = {
                "overview": "Overview",
                "metrics": "Metrics (Physical Profile)",
                "tunneling": "Tunneling+",
                "results": "Results",
                "zone": "Zone",
                "command": "Command & Execution",
                "arsenal": "Arsenal",
                "count_leverage": "Count Leverage",
                "sequencing": "Sequencing",
                "arsenal_plan": "Arsenal Plan",
                "trends": "Trends",
            }
            # Oct 2026, Ryker: "i don't want guys to see it" -- the
            # Fastball Shape Check is a staff-only data-cleanup tool.
            if app_state.role_name() in STAFF_ROLES:
                view_choices["fastball_shape"] = "Fastball Shape Check"
                view_choices["pitch_type_check"] = "Pitch Type Check"
            return ui.div(
                ui.hr(),
                ui.input_select("pp_view", "View", choices=view_choices),
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
        # Oct 2026, Ryker: deeper dive -- how every grade is built and how
        # much each ingredient counts (visualizations/grade_explainer.py),
        # then the original term-by-term glossary underneath.
        from visualizations.grade_explainer import render_html
        ui.modal_show(ui.modal(
            ui.HTML(render_html()),
            ui.hr(),
            ui.h5("Every term on this page", style="margin-bottom:10px;"),
            *[ui.div(ui.p(t, style="font-weight:700;margin-bottom:2px;"), ui.p(d, class_="text-muted small"))
              for t, d in glossary_content.OVERVIEW],
            title="How your grades are built", easy_close=True, size="xl",
            footer=ui.modal_button("Got it"),
        ))

    @reactive.effect
    @reactive.event(input.pp_glossary_command)
    def _pp_show_command_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Command Glossary", glossary_content.COMMAND))

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
                ui_helpers.glossary_link("pp_glossary_overview", "How your grades are built + Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]

            if game_pitches:
                # Runner-event outs / forced-end runs belong to the whole
                # outing, not any one pitch type -- only fold them in for
                # the unfiltered line (see get_pitching_extras_for_pitches).
                if f["pitch_type"]:
                    line = compute_pitching_line(game_pitches)
                else:
                    line = pitching_line_for(db, pid, game_pitches)
                sections.append(ui.p(ui.strong("Line")))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "IP", "value": str(line["IP"])},
                    {"label": "Pitches", "value": str(line["Pitches"])},
                    {"label": "K", "value": str(line["K"])},
                    {"label": "BB", "value": str(line["BB"])},
                    {"label": "WHIP", "value": _fmt(line["WHIP"])},
                    {"label": "TBIP", "value": _fmt(line["TBIP"])},
                    {"label": "FIP", "value": _fmt(line["FIP"])},
                ]))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Strike %", "value": _fmt_pct(line["Strike %"])},
                    {"label": "Zone Execution %", "value": _fmt_pct(line["Zone Execution %"])},
                    {"label": "OBA", "value": _fmt(line["OBA (opponent AVG)"], 3)},
                    {"label": "wOBA*", "value": _fmt(line["wOBA"], 3)},
                ]))
                sections.append(ui.p("*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact.", class_="text-muted small"))

                sections.append(ui.p(ui.strong("Plus stats vs D2 (2026)")))
                sections.append(ui_helpers.plus_stat_cards(league_baselines.pitching_plus(line), league_baselines.PITCHING_PLUS_ORDER, league_baselines.pitching_actuals(line)))
                sections.append(ui.p(league_baselines.PLUS_HELP, class_="text-muted small"))

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

    # -------------------------------------------------------------------
    # VAAA / HAAAA (Oct 2026, Ryker sent Paradigm's HAAAA thread: "build
    # both"). Approach angles minus what the pitch's context predicts --
    # see analytics/approach_angles.py for the model and sign conventions.
    # -------------------------------------------------------------------
    def _fmt_deg(v, signed=True):
        if v is None:
            return "—"
        return f"{v:+.1f}°" if signed else f"{v:.1f}°"

    def _approach_children(db, player, rapsodo_pitches):
        try:
            model = approach_angles.get_model(db)
            scored = approach_angles.score_pitches(rapsodo_pitches, player.throws, model)
        except Exception:
            return []
        rows = approach_angles.summary_by_type(scored, player.throws, FASTBALL_TYPES)
        if not rows or all(r["n_vaaa"] == 0 and r["n_haaaa"] == 0 for r in rows):
            return [ui.hr(), ui.p(ui.strong("Approach Angles Above Expected (VAAA / HAAAA)")),
                    ui.p("Not enough Rapsodo readings with plate location yet to build the expected-angle model.",
                         class_="text-muted small")]
        table = [{
            "Pitch Type": r["label"] + (" *" if r["rough"] else ""), "#": r["n"],
            "VAA": _fmt_deg(r["vaa"], signed=False), "VAAA": _fmt_deg(r["vaaa"]), "Vertical read": r["vaaa_text"],
            "HAA": _fmt_deg(r["haa"]), "HAAAA": _fmt_deg(r["haaaa"]), "Horizontal read": r["haaaa_text"],
        } for r in rows]
        # Fit quality of the per-pitch-type lines actually used here
        # (the pooled fallback line is always weaker -- it ignores type).
        labels = {r["label"] for r in rows}
        v_r2 = [model["vaa"][l]["r2"] for l in labels if l in model["vaa"]]
        h_r2 = [model["haa"][l]["r2"] for l in labels if l in model["haa"]]
        fit_note = []
        if v_r2:
            fit_note.append(f"VAA lines R² {min(v_r2):.2f}–{max(v_r2):.2f}" if len(v_r2) > 1 else f"VAA line R² {v_r2[0]:.2f}")
        if h_r2:
            fit_note.append(f"HAA lines R² {min(h_r2):.2f}–{max(h_r2):.2f}" if len(h_r2) > 1 else f"HAA line R² {h_r2[0]:.2f}")
        return [
            ui.hr(),
            ui.p(ui.strong("Approach Angles Above Expected (VAAA / HAAAA)")),
            ui.p(
                "Raw approach angles mostly reflect where a pitch crossed the plate and where it was released. These "
                "subtract what that context predicts, leaving what's unusual about the pitch itself. "
                "VAAA: + = flatter than expected for its height (fastballs up), − = steeper (breaking balls). "
                "HAAAA (Paradigm's convention): + = sharper toward a right-handed hitter than expected, − = toward a "
                "lefty. Expected angles come from lines fit on all of our Rapsodo readings"
                + (f" ({', '.join(fit_note)})" if fit_note else "") + ". * = rougher estimate (too few team readings of "
                "that pitch type yet, so a pooled line was used). Built on estimated VAA/HAA.",
                class_="text-muted small",
            ),
            ui_helpers.render_dict_table(table),
            ui_helpers.card(
                *[ui.div(
                    ui.strong(r["label"]),
                    ui.tags.ul(*[ui.tags.li(t) for t in approach_angles.usage_tips(r, player.throws)],
                               style="margin:2px 0 8px; padding-left:18px;"),
                ) for r in rows],
                ui.p("Starting points, not proven on our own games yet: side-to-side lines follow Paradigm's 2026 D1 "
                     "swing/whiff findings, up-and-down lines follow the standard VAA patterns.",
                     class_="text-muted small", style="margin:0;"),
                title="How to use it",
            ),
            ui.input_switch("pp_aa_show_chart", "Show advanced chart (every pitch's VAAA vs. HAAAA)", value=False),
            output_widget("pp_approach_chart"),
        ]

    # -------------------------------------------------------------------
    # IVB over expected (Oct 2026, from Ryker's article batch: Paradigm's
    # VAA piece, O'Brien's FB deception index, SABRLions' sliders). Ride
    # minus what his arm slot predicts -- analytics/ivb_expected.py.
    # -------------------------------------------------------------------
    def _ivb_over_children(db, player, rapsodo_pitches):
        try:
            model = ivb_expected.get_model(db)
            scored = ivb_expected.score_pitches(rapsodo_pitches, player, model)
        except Exception:
            return []
        rows = ivb_expected.summary_by_type(scored, FASTBALL_TYPES)
        title = ui.p(ui.strong("IVB Over Expected (ride vs. his arm slot)"))
        if not rows:
            reason = ("Set his height on the Players page -- the arm angle needs it."
                      if player.height_in is None else "Not enough Rapsodo readings yet.")
            return [ui.hr(), title, ui.p(reason, class_="text-muted small")]
        fb = model.get("4-Seam Fastball")
        slope = (f" On our staff a 4-seam gains about {fb['slope']:.2f}\" of ride per degree of arm slot."
                 if fb and fb["slope"] > 0 else "")
        table = [{
            "Pitch Type": r["label"] + (" *" if r["rough"] else ""), "#": r["n"],
            "Arm angle": f"{r['arm']:.0f}°", "IVB": f"{r['ivb']:.1f}\"", "Expected IVB": f"{r['exp']:.1f}\"",
            "Over expected": f"{r['over']:+.1f}\"", "Read": r["read"],
        } for r in rows]
        return [
            ui.hr(), title,
            ui.p("Ride (IVB) mostly follows arm slot: higher slots get more ride, lower slots more run. This "
                 "takes out what his slot predicts, so what's left is what's unusual about the pitch -- the part "
                 "hitters don't expect from that arm. Fastballs: + = carries more than his slot (plays up in the "
                 "zone), − = sinks/runs more. Breaking balls: + = more carry, − = more depth." + slope +
                 " Expected values come from lines fit on all of our Rapsodo readings, so this is vs. our staff, "
                 "not a league. * = rough (too few team readings of that type, pooled line used). "
                 f"Within ±{ivb_expected.TYPICAL_IN:.1f}\" reads as typical.",
                 class_="text-muted small"),
            ui_helpers.render_dict_table(table),
        ]

    @render_plotly
    def pp_approach_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "metrics":
            return None
        if "pp_aa_show_chart" not in input or not input.pp_aa_show_chart():
            return None
        db = get_session()
        try:
            player, rapsodo_pitches = _physical_target(db)
            if player is None or not rapsodo_pitches:
                return None
            model = approach_angles.get_model(db)
            scored = [r for r in approach_angles.score_pitches(rapsodo_pitches, player.throws, model)
                      if r["vaaa"] is not None and r["haaaa"] is not None]
            if not scored:
                return None
            fig = go.Figure()
            by_type = {}
            for r in scored:
                by_type.setdefault(r["label"], []).append(r)
            for label, rs in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
                fig.add_trace(go.Scatter(
                    x=[r["haaaa"] for r in rs], y=[r["vaaa"] for r in rs], mode="markers", name=label,
                    marker=dict(color=get_pitch_color(label), size=8, opacity=0.75, line=dict(width=0.5, color="#1E1E1E")),
                    hovertemplate=f"{label}<br>HAAAA %{{x:+.1f}}°<br>VAAA %{{y:+.1f}}°<extra></extra>",
                ))
                mx = sum(r["haaaa"] for r in rs) / len(rs)
                my = sum(r["vaaa"] for r in rs) / len(rs)
                fig.add_trace(go.Scatter(
                    x=[mx], y=[my], mode="markers", showlegend=False,
                    marker=dict(color=get_pitch_color(label), size=16, symbol="diamond", line=dict(width=2, color="#FFFDE5")),
                    hovertemplate=f"{label} average<br>HAAAA {mx:+.1f}°<br>VAAA {my:+.1f}°<extra></extra>",
                ))
            fig.add_hline(y=0, line=dict(color="#6b7280", width=1))
            fig.add_vline(x=0, line=dict(color="#6b7280", width=1))
            return apply_gbo_theme(
                fig, title="Approach angles vs. expected (diamond = pitch average)", height=430,
                x_title="HAAAA (°)  ← toward LHH · toward RHH →", y_title="VAAA (°)  ↓ steeper · flatter ↑",
            )
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
                *_approach_children(db, player, rapsodo_pitches),
                *_ivb_over_children(db, player, rapsodo_pitches),
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
        Late Break follow Baseball Prospectus's published methodology
        (now measured at a fixed TIME before the plate rather than a
        fixed distance -- see analytics/pitch_grading.py's
        DECISION_TIME_BEFORE_PLATE_S comment for why); Ratio is GBO's
        own Plate/Tunnel metric, NOT literally BP's own "Break:Tunnel
        Ratio" formula despite the similar name -- see Break:Tunnel %
        (BP) below for the field that actually matches BP's formula
        (Sept 2026 correction, checked directly against BP's source
        articles). Tunneling+ itself is a GBO-specific blend of Ratio
        and Release Consistency (see that module's tunneling_plus
        docstring for the full citations and math). Velo Diff/Break
        Diff are shown as separate context,
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
        metrics' docstring), then context. (Ryker: "incorporate more
        red in these" -> "make all of the kpi cards the red style" ->
        "i want all kpi cards in the website to be this way" -- the
        crimson-tinted look this tab started with is now every
        .gbo-kpi-card's own default styling app-wide, see
        ui_helpers.render_kpi_cards/theme.py, so nothing here needs to
        opt in anymore.) The Velo/Break Diff context row is still
        marked "For context (not part of the grade)" in its own
        caption above it, so it stays distinguishable from the graded
        rows by label even though every row's card styling now
        matches."""
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
                    children.append(ui_helpers.render_kpi_cards(context_cards, accent=True))
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
                # Oct 2026, Ryker: see Pitch Results vs both hands, RHH, or
                # LHH -- same "Batters" dropdown pattern as Damage by Zone.
                # Chart + table are their own renders so switching hands
                # doesn't rebuild this section (or reset the dropdown).
                ui.input_select(
                    "pp_results_hand", "Batters",
                    choices={"all": "Both (All Batters)", "R": "vs RHH", "L": "vs LHH"},
                    selected=_current_results_hand(),
                    width="220px",
                ),
                output_widget("pp_results_chart"),
                ui.output_ui("pp_results_table"),
                ui.hr(),
                ui.p(ui.strong("Damage by Zone"), style="margin-bottom:0;"),
                ui.p(
                    "Where opposing hitters do the most damage against this pitch selection (Pitch Type filter "
                    "above -- pick one pitch type or leave it on All Pitches), every charted pitch re-sliced "
                    "spatially into the same 1-9 zone grid used everywhere else in GBO. Use the Batters "
                    "dropdown to see both hands together, or just vs RHH / vs LHH. Colored by average run value per zone (red = favors the hitter, blue = favors "
                    "the pitcher), centered on break-even -- the same RV number behind this page's own RV/100 "
                    "column, not a separate wOBA or contact-quality-only score. Contact quality and hits "
                    "allowed show on hover. Needs Video Review, same as the Zone tab's location heatmaps -- "
                    "zones with fewer than a handful of pitches are grayed out rather than colored, and a hand "
                    "this pitcher hasn't faced yet in this window shows a short note instead of a chart.",
                    class_="text-muted small",
                ),
                # Oct 2026, Ryker: "select both, rhh, or lhh in a
                # dropdown so you would only see one at a time." Lives
                # here (static content), read by pp_zone_damage_chart --
                # a separate render, so no same-render input issue.
                # isolate() keeps the current pick when this section
                # re-renders after a filter change.
                ui.input_select(
                    "pp_damage_hand", "Batters",
                    choices={"all": "Both (All Batters)", "R": "vs RHH", "L": "vs LHH"},
                    selected=_current_damage_hand(),
                    width="220px",
                ),
                output_widget("pp_zone_damage_chart"),
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
            game_pitches = _results_hand_pitches(db, game_pitches)
            req(game_pitches)
            rows = compute_pitch_type_breakdown(game_pitches)
            return pitch_results_chart(rows)
        finally:
            db.close()

    def _current_results_hand():
        with reactive.isolate():
            try:
                choice = input.pp_results_hand() if "pp_results_hand" in input else "all"
            except Exception:
                choice = "all"
        return choice if choice in ("all", "R", "L") else "all"

    def _results_hand_pitches(db, game_pitches):
        """Filter to the batter hand picked in Results' "Batters" dropdown
        (get_batter_hands -- switch-hitter aware, never raw opponent_hand)."""
        choice = input.pp_results_hand() if "pp_results_hand" in input else "all"
        if choice not in ("R", "L"):
            return game_pitches
        hands = get_batter_hands(db, game_pitches)
        return [p for p in game_pitches if hands.get(p.game_pitch_id) == choice]

    @render.ui
    def pp_results_table():
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
            game_pitches = _results_hand_pitches(db, game_pitches)
            hand = input.pp_results_hand() if "pp_results_hand" in input else "all"
            who = {"R": "right-handed", "L": "left-handed"}.get(hand)
            if not game_pitches:
                return ui.p(f"No pitches vs {who} hitters in this range yet." if who else "No game pitches in this range yet.",
                            class_="text-muted small")
            rows = compute_pitch_type_breakdown(game_pitches)
            type_rows = [
                r for r in rows
                if r["Pitch Type"] != "Total" and ((r["Balls in Play"] or 0) > 0 or (r["Total Swings"] or 0) > 0)
            ]
            if not type_rows:
                return ui.p(f"No swings vs {who} hitters in this range yet." if who else "No swings in this range yet.",
                            class_="text-muted small")
            note = ui.p(f"Only pitches to {who} hitters ({len(game_pitches)} pitches). % Thrown is out of those pitches.",
                        class_="text-muted small") if who else None
            return ui.div(note, ui_helpers.render_dict_table([
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
            ]))
        finally:
            db.close()

    def _current_damage_hand():
        with reactive.isolate():
            try:
                choice = input.pp_damage_hand() if "pp_damage_hand" in input else "all"
            except Exception:
                choice = "all"
        return choice if choice in ("all", "R", "L") else "all"

    @render_plotly
    def pp_zone_damage_chart():
        """Sept 2026, Ryker: "an opposing hitters heat map for each of
        my pitchers ... select a pitch type from a drop down then see
        a strikezone that has red zones ... under pitcher profile it
        would go under the results section." Deliberately reuses this
        page's own existing "Pitch Type" filter (input.pp_pitch_type,
        via f["pitch_type"]/_current_filters) rather than adding a
        second, competing pitch-type dropdown just for this chart --
        it's the exact same filter pp_results_chart above and every
        other section on this page already honors, so "All Pitches"
        shows every pitch type blended into one zone map and picking
        one type from that same dropdown narrows this chart (and only
        this chart re-slices spatially instead of by pitch type -- see
        analytics/pitcher_zone_damage.py's own docstring for the RV
        vs. wOBA vs. contact-quality-alone reasoning). Sept 2026,
        Ryker: "add damage by zone for left and right hitters as
        well" -- draws All Batters/vs RHH/vs LHH side by side
        (zone_damage_heatmap_by_hand), with the batter's hand resolved
        via game_stats.get_batter_hands (roster Player.bats, with the
        switch-hitter and three-squad fixes already established for
        every other hand split in this app) rather than trusted from
        GamePitch.opponent_hand directly."""
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
            label = f["pitch_type"] or "All Pitch Types"
            # One panel at a time, picked from the Batters dropdown
            # (Oct 2026) -- "all" = both hands combined, no silhouette.
            hand_choice = input.pp_damage_hand() if "pp_damage_hand" in input else "all"
            if hand_choice in ("R", "L"):
                hands = get_batter_hands(db, game_pitches)
                subset = [p for p in game_pitches if hands.get(p.game_pitch_id) == hand_choice]
                panel_label, hand = ("vs RHH", "R") if hand_choice == "R" else ("vs LHH", "L")
            else:
                subset, panel_label, hand = game_pitches, "All Batters", None
            fig = zone_damage_heatmap_by_hand([(panel_label, compute_zone_damage(subset), hand)], label)
            if fig is None:
                # No located pitches against that hand in this window.
                fig = go.Figure()
                fig.add_annotation(
                    text=f"No located pitches {panel_label.lower()} in this selection yet.",
                    x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False,
                )
                fig.update_xaxes(visible=False)
                fig.update_yaxes(visible=False)
                fig = apply_gbo_theme(fig, title=f"{label} — Damage by Zone", height=200)
            return fig
        finally:
            db.close()

    @render.ui
    def pp_zone_hand_filter():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "zone":
            return None
        # Sept 2026, Ryker: "for the zone tab in pitcher profile be
        # able to select vs right and left handed hitters" -- a plain
        # radio-button filter (not a small-multiples split like the
        # Results tab's Damage by Zone) so the density heatmap below
        # stays ONE interactive Plotly widget rather than three, same
        # single-selector-drives-one-widget shape hitter_tracking.py's
        # own "Filter by pitcher hand" heatmap control already uses.
        # Split into its own function/placeholder (rather than folding
        # into pp_zone_section itself) for the same reason hitter_
        # tracking.py splits heatmap_hand_filter from heatmap_body --
        # a render.ui can't reliably read an input it defines in that
        # same call, since the client hasn't registered the widget's
        # default value back into `input` until after this render
        # finishes.
        return ui.input_radio_buttons(
            "pp_zone_hand", "Filter by batter hand",
            choices=["All Batters", "vs RHH", "vs LHH"], selected="All Batters", inline=True,
        )

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
        req("pp_zone_hand" in input)
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

            hand_choice = input.pp_zone_hand()
            game_pitches = _zone_hand_filtered(db, game_pitches, hand_choice)
            if hand_choice != "All Batters" and not game_pitches:
                return ui.div(
                    ui.p(ui.strong("Attack Zone Distribution"), style="margin-bottom:0;"),
                    ui.p(
                        f"No pitches {'vs a right-handed' if hand_choice == 'vs RHH' else 'vs a left-handed'} batter in this range.",
                        class_="text-muted small",
                    ),
                )

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

            sections += _best_zone_children(db, pid, game_pitches)
            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Best Zone (Oct 2026, Ryker sent Paradigm's "Miss Distance" thread:
    # "build it") -- how far each pitch landed from the area where that
    # pitch plays best, by batter hand. See analytics/best_zone.py.
    # -------------------------------------------------------------------
    def _bz_pct(v):
        return "—" if v is None else f"{v:.0f}%"

    def _best_zone_children(db, pid, game_pitches):
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None or player.throws not in ("R", "L"):
            return []
        scored, maps = best_zone.score_for_pitcher(db, game_pitches, player.throws)
        head = [ui.hr(), ui.p(ui.strong("Best Zone (distance from where each pitch plays best)"))]
        if not scored:
            return head + [ui.p("No located pitches with a known batter hand yet (locations come from video review).",
                                class_="text-muted small")]
        any_team = any(r["source"] == "team" for r in scored)
        type_rows = best_zone.summary_by_type(scored)
        table = [{
            "Pitch Type": r["label"], "#": r["n"],
            "In best zone": _bz_pct(r["inside_pct"]), "Within 3\"": _bz_pct(r["near_pct"]),
            "6\"+ away": _bz_pct(r["far_pct"]), "Avg distance": f'{r["avg_dist"]:.1f}"',
            "Best zone": r["where"],
        } for r in type_rows]
        band_rows = [{
            "Distance": b["band"], "Pitches": b["n"], "Strike %": _bz_pct(b["strike_pct"]),
            "Swing %": _bz_pct(b["swing_pct"]), "Whiff / swing": _bz_pct(b["whiff_pct"]),
            "Hits / ball in play": _bz_pct(b["hit_pct_bip"]),
            "Run value / 100": "—" if b["rv100"] is None else f'{b["rv100"]:+.1f}',
        } for b in best_zone.results_by_band(scored) if b["n"]]
        return head + [
            ui.p(
                "Each pitch has an area where it plays best (four-seams up, breaking balls down and glove side, "
                "changeups down and arm side, adjusted by batter hand). This measures how far every pitch landed "
                "from that whole area -- not from the called spot -- in Paradigm's bands. "
                + ("Some areas are drawn from our own run values (enough games logged); the rest are starting maps. "
                   if any_team else
                   "Areas are educated starting maps for now; they switch to our own run-value data as games add up. ")
                + "Results by distance are small-sample and use run value and hits on balls in play (no exit velo, "
                "so no xwOBA).",
                class_="text-muted small",
            ),
            ui_helpers.render_dict_table(table),
            ui.p(ui.strong("Results by distance"), class_="mt-2 mb-1"),
            ui_helpers.render_dict_table(band_rows),
            ui.p("Run value / 100 is from the hitter's side: lower (more negative) is better for the pitcher.",
                 class_="text-muted small"),
            output_widget("pp_best_zone_chart"),
        ]

    @render_plotly
    def pp_best_zone_chart():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "zone":
            return None
        req("pp_zone_hand" in input)
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            player = db.query(Player).filter(Player.player_id == pid).first() if pid else None
            if player is None or player.throws not in ("R", "L"):
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"], game_id=f["game_id"],
            )
            game_pitches = _zone_hand_filtered(db, game_pitches, input.pp_zone_hand())
            scored, maps = best_zone.score_for_pitcher(db, game_pitches, player.throws)
            if not scored:
                return None
            choice = input.pp_zone_hand()
            if choice == "vs RHH":
                hand = "R"
            elif choice == "vs LHH":
                hand = "L"
            else:
                same = sum(1 for r in scored if r["matchup"] == "same")
                hand = player.throws if same >= len(scored) - same else ("L" if player.throws == "R" else "R")
            return best_zone_figure(scored, maps, player.throws, hand)
        finally:
            db.close()

    @render_plotly
    def pp_location_heatmap():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "zone":
            return None
        req("pp_zone_hand" in input)
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
            # Same pp_zone_hand selection pp_zone_section's Attack Zone
            # Distribution bar and per-type table already apply, so the
            # heatmap below them stays in sync with the rest of the tab.
            game_pitches = _zone_hand_filtered(db, game_pitches, input.pp_zone_hand())
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

            sb = _sb_data()
            if sb and any(e["features"] for e in sb["breakdown"]):
                sb_types = {e["label"]: f"{e['label']}  ·  {e['stuff_plus']:.0f}" for e in sb["breakdown"] if e["features"]}
                sections.append(ui.hr())
                sections.append(ui.div(
                    ui.tags.style(_SB_CSS),
                    ui_helpers.section_title("Stuff+ Breakdown",
                                             ui.input_select("pp_sb_type", None, choices=sb_types, width="260px")),
                    ui.div(ui_helpers.how_to_link("stuff_breakdown", "How to read the breakdown"), "  ·  ",
                           ui_helpers.how_to_link("grades", "How Stuff+ is built"), style="margin:-4px 0 6px;"),
                    ui.output_ui("pp_sb_header"),
                    ui.layout_columns(
                        ui_helpers.card(output_widget("pp_sb_traits"),
                                        ui.output_ui("pp_sb_traits_note"),
                                        title="What's driving the grade"),
                        ui_helpers.card(output_widget("pp_sb_outcomes"),
                                        ui.output_ui("pp_sb_outcome_note"),
                                        title="Do game results match?"),
                        col_widths=[6, 6],
                    ),
                    ui.output_ui("pp_sb_strip_titles"),
                    class_="gbo-sb",
                ))

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
    # Trends (Oct 2026, Ryker approved). One point per game (or week), a
    # rolling line, and his / team / D2 reference lines. Math:
    # analytics/trends.py, charts: visualizations/trend_charts.py.
    # -------------------------------------------------------------------
    def _trend_gate():
        if not app_state.is_authenticated():
            return False
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return False
        req("pp_view" in input)
        return input.pp_view() == "trends"

    @render.ui
    def pp_trends_section():
        if not _trend_gate():
            return None
        return ui.div(
            ui.p(ui.strong("Trends"), "  ", ui_helpers.how_to_link("trends"), style="margin-bottom:0;"),
            ui.p("Is he getting better? Dots = each game (or week), red line = rolling average (pools the pitches, "
                 "so one short outing doesn't swing it). Dotted = his average over this range, gray dashed = team, "
                 "gold dashed = D2. Uses the date range above.", class_="text-muted small"),
            ui.layout_columns(
                    ui.input_radio_buttons("pp_trend_by", "Each point is", {"game": "A game", "week": "A week"},
                                           selected="game", inline=True),
                    ui.input_radio_buttons("pp_trend_roll", "Rolling line over", {"3": "3", "5": "5", "10": "10"},
                                           selected="5", inline=True),
                    col_widths=[6, 6],
                ),
            output_widget("pp_trend_metrics"),
            ui.p(ui.strong("Velo and Stuff+ by pitch (Rapsodo: bullpens + games)"), style="margin:14px 0 0;"),
            output_widget("pp_trend_velo"),
            ui.hr(),
            ui.output_ui("pp_trend_fade"),
        )

    @render_plotly
    def pp_trend_metrics():
        req(_trend_gate())
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            req(pid)
            ps = profile_queries.get_pitcher_profile_pitches(db, pid, date_from=f["date_from"], date_to=f["date_to"],
                                                             pitch_type=f["pitch_type"], game_scope=f["game_scope"])
            req(ps)
            team = trends.team_pitches_in_range(db, f["date_from"], f["date_to"], pitching=True)
            by = input.pp_trend_by() if "pp_trend_by" in input else "game"
            roll = int(input.pp_trend_roll()) if "pp_trend_roll" in input else 5
            return trend_charts.metrics_figure(trends.build(db, ps, team, True, by, roll))
        finally:
            db.close()

    @render_plotly
    def pp_trend_velo():
        req(_trend_gate())
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            req(pid)
            by = input.pp_trend_by() if "pp_trend_by" in input else "game"
            vs = trends.velo_stuff(db, pid, f["date_from"], f["date_to"], by)
            req(vs)
            return trend_charts.velo_stuff_figure(vs)
        finally:
            db.close()

    @render.ui
    def pp_trend_fade():
        """Velo fade by outing (Oct 2026, analytics/velo_fade.py)."""
        req(_trend_gate())
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            req(pid)
            raps = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=None,
                game_scope=f["game_scope"], game_id=f["game_id"],
            )
            return velo_fade_display.season_block(velo_fade.by_outing(raps or [], pitch_type_label))
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Stuff+ Breakdown (Oct 2026, Ryker, after Kyle Bland's "Why doesn't
    # he get whiffs if he has good Stuff?" thread). Lives in the Arsenal
    # view; staff + player. Math in analytics/stuff_breakdown.py.
    # -------------------------------------------------------------------

    @reactive.calc
    def _sb_data():
        if not app_state.is_authenticated():
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
                pitch_type=f["pitch_type"], game_scope=f["game_scope"], game_id=f["game_id"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_scope=f["game_scope"], game_id=f["game_id"], game_linked_only=True,
            )
            if not rapsodo_pitches:
                return None
            breakdown, outcomes = stuff_breakdown.get_for_pitcher(db, rapsodo_pitches, game_pitches)
            return {"breakdown": breakdown, "outcomes": outcomes}
        finally:
            db.close()

    def _sb_entry():
        data = _sb_data()
        if not data:
            return None, None
        req("pp_sb_type" in input)
        label = input.pp_sb_type()
        entry = next((e for e in data["breakdown"] if e["label"] == label), None)
        return entry, data["outcomes"].get(label)

    def _sb_top_features(entry, k=3):
        return [f for f in entry["features"] if entry["team_values"].get(f["name"])][:k]

    @render.ui
    def pp_sb_header():
        entry, o = _sb_entry()
        if entry is None:
            return None
        sp = entry["stuff_plus"]
        cards = [
            {"label": f"{entry['label']} Stuff+", "value": f"{sp:.0f}",
             "delta": f"{sp - 100:+.0f} vs team avg", "delta_positive": sp >= 100},
            {"label": "Rapsodo readings", "value": str(entry["n"])},
            {"label": f"Team {entry['label']}s compared ({entry.get('team_pitchers', '—')} pitchers)",
             "value": str(entry.get("team_n", "—"))},
        ]
        if o is not None:
            cards.append({"label": "Game results vs team", "value": f"{o['gap']:+.2f}",
                          "delta": "runs saved / 100 pitches" + ("" if o["enough"] else " · small sample"),
                          "delta_positive": o["gap"] >= 0})
        line = stuff_breakdown.why_line(entry, {entry["label"]: o} if o else None)
        tips = []
        for f in entry["features"]:
            if f["contrib"] <= -2.0 and f["name"] in stuff_breakdown.FEATURE_TIPS:
                want = stuff_breakdown.FEATURE_TIPS[f["name"]] if f["weight"] > 0 else "less " + f["label"].lower()
                tips.append(ui.tags.li(ui.strong(f["label"]), f" is costing {abs(f['contrib']):.0f} points -- the model rewards {want}."))
        kids = [ui_helpers.render_kpi_cards(cards)]
        if line:
            kids.append(ui.p(line, class_="gbo-sb-why"))
        if tips:
            kids.append(ui.tags.ul(*tips[:3], class_="gbo-sb-tips"))
        kids.append(ui.p(
            f"Compared only against team {entry['label']}s -- never other pitch types. 100 = the team's average "
            f"{entry['label']}; each trait's bar is how many points it adds or costs.",
            class_="text-muted small",
        ))
        if not entry.get("enough"):
            kids.append(ui.p(f"Only {entry['n']} readings on this pitch -- read the bars loosely.", class_="text-muted small"))
        return ui.div(*kids)

    @render_plotly
    def pp_sb_traits():
        entry, _o = _sb_entry()
        req(entry is not None and entry["features"])
        return trait_impact_figure(entry)

    @render.ui
    def pp_sb_traits_note():
        entry, _o = _sb_entry()
        if entry is None:
            return None
        return ui.p("Hover a bar for his average, the team average and his percentile.", class_="text-muted small")

    @render.ui
    def pp_sb_strip_titles():
        entry, _o = _sb_entry()
        if entry is None:
            return None
        feats = _sb_top_features(entry)
        if not feats:
            return None
        cards = []
        for i, f in enumerate(feats):
            tone = "up" if f["contrib"] >= 0 else "down"
            right = ui.span(f"{ordinal(f['pct'])} pct", class_=f"gbo-sb-pct {tone}")
            cards.append(ui_helpers.card(
                ui.div(ui.span(fmt_value(f), class_="gbo-sb-val"),
                       ui.span(f"  team {fmt_value(f, f['team_avg'])}  ·  {f['contrib']:+.1f} Stuff+", class_="text-muted small")),
                output_widget(f"pp_sb_strip_{i}"),
                title=f["label"], right=right, small=True,
            ))
        return ui.div(
            ui.p(ui.strong("Where he ranks on the traits that matter most"),
                 ui.span(f"  ·  grey = every team {entry['label']}, color = his", class_="text-muted small"),
                 style="margin:14px 0 6px;"),
            ui.layout_columns(*cards, col_widths=[12 // len(cards)] * len(cards)),
        )

    def _sb_strip(i):
        entry, _o = _sb_entry()
        req(entry is not None)
        feats = _sb_top_features(entry)
        req(len(feats) > i)
        return strip_figure(entry, feats[i]["name"])

    @render_plotly
    def pp_sb_strip_0():
        return _sb_strip(0)

    @render_plotly
    def pp_sb_strip_1():
        return _sb_strip(1)

    @render_plotly
    def pp_sb_strip_2():
        return _sb_strip(2)

    @render_plotly
    def pp_sb_outcomes():
        entry, o = _sb_entry()
        req(entry is not None and o is not None)
        return outcome_figure(entry["label"], o)

    @render.ui
    def pp_sb_outcome_note():
        entry, o = _sb_entry()
        if entry is None:
            return None
        if o is None:
            return ui.p("No game pitches with run value for this pitch yet.", class_="text-muted small")
        sign = "better" if o["gap"] >= 0 else "worse"
        msg = (f"{abs(o['gap']):.2f} runs per 100 pitches {sign} than team {entry['label']}s (n={o['n']}). "
               "A red Balls bar = more costly balls than teammates; red Balls in play = more damage on contact.")
        if not o["enough"]:
            msg += f" Greyed until {stuff_breakdown.MIN_PITCHES_FOR_OUTCOMES} game pitches -- noisy at this size."
        return ui.p(msg, class_="text-muted small")

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

    # -------------------------------------------------------------------
    # Sequencing (Oct 2026, from Paradigm's "Sequencing vs Tunneling" --
    # Ryker picked "Pitch-pair sequencing"). What follows what, and how
    # the second pitch did. Math in analytics/sequencing.py.
    # -------------------------------------------------------------------
    def _seq_gate():
        if not app_state.is_authenticated():
            return False
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return False
        return "pp_view" in input and input.pp_view() == "sequencing"

    @render.ui
    def pp_sequencing_section():
        if not _seq_gate():
            return None
        return ui.div(
            ui.p(ui.strong("Sequencing: what follows what"), style="margin-bottom:0;"),
            ui.p("Each row is two back-to-back pitches to the same hitter (first → second), graded on what the SECOND "
                 "pitch did. Share = of everything he threw right after the first pitch, how often it was this one. "
                 "CSW % = called strikes + whiffs; Whiff % = of swings; Chase % = swings at located pitches outside "
                 f"the zone. Team = the same pair across our whole staff. Gray rows have fewer than {sequencing.MIN_N} "
                 "-- too few to trust yet. Charted games only; uses the date range above (the pitch-type filter is "
                 "ignored here so pairs stay whole).", class_="text-muted small"),
            ui.layout_columns(
                ui.input_radio_buttons("pp_seq_side", "Hitters", {"all": "All", "R": "vs RHH", "L": "vs LHH"},
                                       selected="all", inline=True),
                ui.input_radio_buttons("pp_seq_count", "Count before the 2nd pitch", sequencing.COUNT_FILTERS,
                                       selected="all", inline=True),
                col_widths=[4, 8],
            ),
            ui.output_ui("pp_seq_table"),
        )

    @render.ui
    def pp_seq_table():
        if not _seq_gate():
            return None
        req("pp_seq_side" in input and "pp_seq_count" in input)
        side, count = input.pp_seq_side(), input.pp_seq_count()
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            mine = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=None,
                game_scope=f["game_scope"], game_id=f["game_id"],
            ) or []
            team = trends.team_pitches_in_range(db, f["date_from"], f["date_to"], pitching=True)
            hands = get_batter_hands(db, list(mine) + list(team))
        finally:
            db.close()
        res = sequencing.table(mine, hands, side, count)
        if not res["rows"]:
            return ui_helpers.empty_state("No back-to-back pitches in this range and filter yet.")
        team_rows = sequencing.team_lookup(team, hands, side, count)

        def pct(v):
            return f"{v}%" if v is not None else "—"
        rows = []
        for r in res["rows"]:
            t = team_rows.get((r["first"], r["second"]))
            rows.append({
                "Pair": r["label"], "Times": r["n"], "Share": pct(r["share"]),
                "Strike %": pct(r["strike"]), "CSW %": pct(r["csw"]), "Whiff %": pct(r["whiff"]),
                "Chase %": pct(r["chase"]), "In play (hits)": f"{r['in_play']} ({r['hits']})",
                "Team CSW %": pct(t["csw"]) if t else "—",
            })
        table_html = ui_helpers.render_dict_table(rows)
        # gray out thin rows (render_dict_table has no per-row class hook)
        thin = [i for i, r in enumerate(res["rows"]) if not r["reliable"]]
        style = "".join(f"#{session.ns('pp_seq_table')} tbody tr:nth-child({i + 1}){{opacity:.5}}" for i in thin)
        notes = sequencing.takeaways(res["rows"])
        return ui.div(
            ui.tags.style(style) if style else None,
            ui.p(f"{res['total']} pairs. " + " · ".join(sorted({f"{sequencing.short(x)} = {x}" for r in res["rows"] for x in (r["first"], r["second"])})),
                 class_="text-muted small", style="margin:0 0 4px;"),
            *[ui.p(ui.strong(n), class_="small", style="margin:0 0 4px;") for n in notes],
            table_html,
        )

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
        # Oct 2026 bug fix: sort within each game -- pitch_sequence
        # restarts every game, so a pitch_sequence-only sort interleaved
        # outings (dropping real back-to-back pairs and allowing
        # cross-game ones). Pairs must also come from the same game.
        game_pitches.sort(key=lambda p: (p.game_pitch.game_id or 0, p.game_pitch.pitch_sequence))
        for prev, cur in zip(game_pitches, game_pitches[1:]):
            gp_prev, gp_cur = prev.game_pitch, cur.game_pitch
            if gp_prev.pa_pitch_number is None or gp_cur.pa_pitch_number is None:
                continue
            if gp_prev.game_id != gp_cur.game_id:
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
            # Oct 2026 (Ryker): Zone Execution % -- called cell + 6 in cushion.
            ui.div(
                ui.p(ui.strong("Zone Execution"), "  ", ui_helpers.how_to_link("zone_execution"), style="margin:0;"),
                ui_helpers.glossary_link("pp_glossary_command", "Command Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            ),
            ui.p(
                "A pitch hits its spot if it lands in the box the catcher called, or within 6 inches (half a foot) of it. Calls "
                "off the plate (the outside boxes) count anywhere off the plate on that side.",
                class_="text-muted small",
            ),
            ui.output_ui("pp_zone_exec"),
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

            ui.hr(),
            ui.p(ui.strong("Miss Map")),
            ui.p(
                "Every pitch placed by how it missed its called spot, one panel per pitch. Arm side is always to "
                "the right (lefties flipped to match). The gold star is his average miss -- the way he leans. A "
                "pitch that landed inside the called spot sits on the center x.",
                class_="text-muted small",
            ),
            output_widget("pp_miss_map"),

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
    def pp_zone_exec():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        from analytics import zone_execution as ze
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            f = _current_filters()
            pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
                game_scope=f["game_scope"], game_id=f["game_id"])
            rep = ze.breakdown(pitches, player.throws if player else None)
        finally:
            db.close()
        if rep is None:
            return ui.p("No pitches with both a called spot and a charted location in this window.",
                        class_="text-muted small")
        o, m = rep["overall"], rep["miss"]
        cards = [
            {"label": "Zone Execution %", "value": f"{o['pct']:.0f}%" if o["pct"] is not None else "—",
             "delta": f"{o['hits']} of {o['n']} hit their spot"},
            {"label": "Missed over the middle", "value": f"{m['over_middle']:.0f}%" if m["over_middle"] is not None else "—",
             "delta": "of his misses -- the ones that get hit", "delta_positive": (m["over_middle"] or 0) < 20},
            {"label": "Miss lean", "value": (m["lean"] or "No clear lean").capitalize(),
             "delta": f"from {m['n']} misses"},
        ]

        def _rows(items):
            return [{"": r["label"], "Zone Exec %": f"{r['pct']:.0f}%" if r["pct"] is not None else "—",
                     "Hit": r["hits"], "Pitches": r["n"]} for r in items]
        miss_rows = [{"Missed": k, "% of misses": f"{m[key]:.0f}%" if m[key] is not None else "—"}
                     for k, key in (("Up", "up"), ("Down", "down"), ("Arm side", "arm"), ("Glove side", "glove"),
                                    ("Over the middle", "over_middle"))]
        return ui.div(
            ui_helpers.render_kpi_cards(cards),
            ui.layout_columns(
                ui_helpers.card(ui_helpers.render_dict_table(_rows(rep["by_type"])), title="By pitch"),
                ui_helpers.card(ui_helpers.render_dict_table(_rows(rep["by_count"])), title="By count"),
                ui_helpers.card(ui_helpers.render_dict_table(miss_rows),
                                ui.p("A miss can be both up and arm side, so these don't add to 100%.",
                                     class_="text-muted small"), title="When he misses"),
                col_widths=[4, 4, 4],
            ),
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

    @render_plotly
    def pp_miss_map():
        """Oct 2026, Ryker: "build miss map" -- see command_charts.miss_map."""
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "command":
            return None
        view_pitches, throws = _view_pitches()
        if not view_pitches:
            return None
        return command_charts.miss_map(view_pitches, throws)

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

    # -------------------------------------------------------------------
    # Arsenal Plan (Oct 2026, Ryker sent Paradigm's REAPER thread: "build
    # it"). Keep / tune / add, built off his own fastball and arm slot --
    # see analytics/arsenal_plan.py for the rules and their limits.
    # Players see it; FS_SWITCH_ROLES can save their own target shapes.
    # -------------------------------------------------------------------
    _ap_tick = reactive.Value(0)

    def _ap_overrides(db, pid):
        try:
            rows = db.query(ArsenalTarget).filter(ArsenalTarget.player_id == pid).all()
        except Exception:
            db.rollback()
            return {}
        return {r.family: {"velo": float(r.velo) if r.velo is not None else None, "ivb": float(r.ivb),
                           "run": float(r.run), "note": r.note} for r in rows}

    def _ap_data(db):
        pid = _current_player_id(db)
        if pid is None:
            return None, None, None
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None:
            return None, None, None
        f = _current_filters()
        games_only = ("pp_ap_source" in input) and input.pp_ap_source() == "games"
        raps = profile_queries.get_pitcher_rapsodo_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=None,
            game_scope=f["game_scope"], game_id=f["game_id"], game_linked_only=games_only,
        )
        fb_like = [p for p in raps if pitch_type_label(p) in arsenal_plan.FASTBALLS]
        arm, _n = average_estimated_arm_angle(fb_like or raps, player)
        heights = [float(p.release_height) for p in (fb_like or raps) if p.release_height is not None]
        rel_h = sum(heights) / len(heights) if heights else None
        overrides = _ap_overrides(db, pid)
        plan = arsenal_plan.build_plan(raps, player.throws or "R", arm, rel_h, overrides=overrides, label_of=pitch_type_label)
        return player, plan, raps

    def _slider_fit_card(db, player, plan, raps):
        """Slider type + fit (Oct 2026, analytics/slider_fit.py)."""
        try:
            model = ivb_expected.get_model(db)
            scored = ivb_expected.score_pitches(raps, player, model)
            overs = {lab: ivb_expected.over_for_type(scored, lab) for lab in {r["label"] for r in scored}}
            fit = slider_fit.build(plan, raps, pitch_type_label, player.throws or "R", overs)
        except Exception:
            return None
        if fit is None:
            return None
        names = {"gyro": "a hard gyro slider", "sweeper": "a sweeper", "either": "either a gyro slider or a sweeper"}
        if fit["se"] is None:
            hint = ui.p(f"Not enough fastball spin-efficiency readings yet ({fit['n_se']} of 5) for the fit hint.",
                        class_="text-muted small")
        else:
            lean_txt = {"pronator": "leans pronator", "supinator": "leans supinator",
                        "neutral": "sits in between"}[fit["lean"]]
            line = (f"Fastball spin efficiency {fit['se']:.0f}% -- {lean_txt}, which usually suits "
                    f"{names[fit['suggested']]}. His arm slot / fastball shape points to {names[fit['slot_suggested']]}.")
            if fit["agree"] is True:
                line += " Both agree."
            elif fit["agree"] is False:
                line += " These disagree -- worth trying both grips in a bullpen and letting the Rapsodo shape decide."
            hint = ui.p(line, class_="small")
        items = []
        for r in fit["rows"]:
            c = r["cur"]
            over = f" · {r['ivb_over']:+.1f}\" ride vs. his slot" if r["ivb_over"] is not None else ""
            v = f"{c['velo']:.1f} mph · " if c.get("velo") is not None else ""
            items.append(ui.div(
                ui.strong(f"{r['label']}: ", style=f"color:{get_pitch_color(r['label'])};"),
                ui.strong(r["type_name"]),
                ui.div(f"{v}{c['ivb']:.1f}\" ride · {-c['run']:.1f}\" glove-side{over}", class_="small"),
                *[ui.div(n, class_="small text-muted") for n in r["notes"]],
                style="margin-bottom:8px;",
            ))
        if not items:
            items = [ui.p("No slider, sweeper or curveball with 5+ readings in this range.", class_="text-muted small")]
        return ui_helpers.card(
            hint, *items,
            ui.p(f"Types by shape: gyro = within {slider_fit.GYRO_RUN:.0f}\" side to side and "
                 f"{slider_fit.CURVE_IVB:.0f} to +{slider_fit.GYRO_IVB[1]:.0f}\" ride; traditional slider = 5-10\" "
                 "glove-side; sweeper = "
                 f"{slider_fit.SWEEP_IN:.0f}\"+ glove-side; carry sweeper = a sweeper with {slider_fit.CARRY_IN:.0f}\"+ "
                 f"ride over expected; curveball = {slider_fit.CURVE_IVB:.0f}\" ride or less (slurve if it also sweeps 10\"+). Fit hint: fastball spin "
                 f"efficiency {slider_fit.PRONATOR_SE:.0f}%+ leans pronator (gyro), {slider_fit.SUPINATOR_SE:.0f}% or "
                 "less leans supinator (sweeper) -- a rule of thumb from public pitch-design work, not a measurement "
                 "of his forearm.", class_="text-muted small", style="margin:4px 0 0;"),
            title="Slider type & fit",
        )

    @render.ui
    def pp_arsenal_plan_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "arsenal_plan":
            return None
        _ap_tick()
        db = get_session()
        try:
            player, plan, raps = _ap_data(db)
            source = input.pp_ap_source() if "pp_ap_source" in input else "all"
            controls = ui.input_radio_buttons(
                "pp_ap_source", "Rapsodo readings",
                {"all": "Games + bullpens", "games": "Games only"}, selected=source, inline=True,
            )
            head = [
                ui.hr(),
                ui.h5("Arsenal Plan", class_="gbo-section-title"),
                ui.p("What to keep, what to tune, and what to add -- built off his own fastball shape and arm slot, "
                     "using established pitch-design rules (not a trained model like Paradigm's REAPER). Treat targets "
                     "as starting points; coaches can save their own. Uses this page's date range.",
                     class_="text-muted small"),
                controls,
            ]
            if player is None or plan is None:
                return ui.div(*head, ui.p("Needs at least 5 Rapsodo fastball readings in this range.",
                                          class_="text-muted small"))
            fb = plan["fb"]
            slot_txt = {"high": "high slot", "low": "low slot", "mid": "three-quarter slot"}[plan["slot"]]
            arm_txt = f" (est. arm angle {plan['arm_angle']:.0f}°)" if plan.get("arm_angle") is not None else ""
            kind_txt = {"ride": "a riding fastball profile -- builds around vertical separation",
                        "run": "a running/sinking profile -- builds around horizontal separation",
                        "mid": "an in-between profile"}[plan["kind"]]
            summary = ui.p(
                ui.strong(f"{plan['primary']}: "),
                f"{fb['velo']:.1f} mph, {fb['ivb']:.1f}\" ride, {fb['run']:.1f}\" arm-side run · {slot_txt}{arm_txt} · "
                f"{kind_txt}.", class_="small",
            )

            def fmt_shape(sh):
                v = f"{sh['velo']:.1f} mph · " if sh.get("velo") is not None else ""
                return f"{v}{sh['ivb']:.1f}\" ride · {sh['run']:+.1f}\" run"

            keeps = [r for r in plan["rows"] if r["status"] in ("keep", "anchor")]
            tunes = [r for r in plan["rows"] if r["status"] == "tune"]

            def item(title, lines, color):
                return ui.div(ui.strong(title, style=f"color:{color};"),
                              *[ui.div(l, class_="small") for l in lines],
                              style="margin-bottom:10px;")

            keep_card = ui_helpers.card(*[
                item(r["label"], [f"Now: {fmt_shape(r['cur'])}", r["text"]], get_pitch_color(r["label"])) for r in keeps
            ] or [ui.p("Nothing at its target yet.", class_="text-muted small")], title="Keep")
            tune_card = ui_helpers.card(*[
                item(r["label"] + (f" → {arsenal_plan.NAMES[r['family']]} target" if arsenal_plan.NAMES.get(r["family"]) != r["label"] else ""),
                     [f"Now: {fmt_shape(r['cur'])}",
                      f"Target{' (coach)' if r.get('source') == 'coach' else ''}: {fmt_shape(r['target'])} · {r['dist']:.1f}\" away",
                      r["text"]], get_pitch_color(r["label"])) for r in tunes
            ] or [ui.p("Nothing to tune.", class_="text-muted small")], title="Tune")
            add_card = ui_helpers.card(*[
                item(f"+ {a['label']}" + ("" if a["core"] else " (option)"),
                     [f"Target{' (coach)' if a.get('source') == 'coach' else ''}: {fmt_shape(a['target'])}", a["why"]],
                     get_pitch_color(a["label"])) for a in plan["adds"]
            ] or [ui.p("Nothing missing for his profile.", class_="text-muted small")], title="Add")

            children = head + [summary,
                ui.layout_columns(keep_card, tune_card, add_card, col_widths=[4, 4, 4]),
                _slider_fit_card(db, player, plan, raps),
                output_widget("pp_ap_movement"),
                ui.p("Progress: how far each pitch's shape was from its target in each session (all readings that day).",
                     class_="text-muted small mt-2"),
                output_widget("pp_ap_progress"),
            ]
            if app_state.role_name() in FS_SWITCH_ROLES:
                fam_choices = {k: v for k, v in arsenal_plan.NAMES.items()}
                children.append(ui_helpers.card(
                    ui.layout_columns(
                        ui.input_select("pp_ap_family", "Pitch", choices=fam_choices,
                                        selected=input.pp_ap_family() if "pp_ap_family" in input else "changeup"),
                        ui.output_ui("pp_ap_fields"),
                        col_widths=[3, 9],
                    ),
                    ui.div(
                        ui.input_action_button("pp_ap_save", "Save target", class_="btn-sm btn-primary"),
                        ui.input_action_button("pp_ap_reset", "Reset to rule", class_="btn-sm btn-outline-light",
                                               style="margin-left:8px;"),
                    ),
                    ui.p("Ride = induced vertical break; run is + toward his arm side, - toward his glove side (inches).",
                         class_="text-muted small", style="margin-top:6px;"),
                    title="Set a target (coaches)",
                ))
            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def pp_ap_fields():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return None
        req("pp_ap_family" in input)
        fam = input.pp_ap_family()
        _ap_tick()
        db = get_session()
        try:
            _player, plan, _raps = _ap_data(db)
            t = (plan or {}).get("targets", {}).get(fam) or {"velo": None, "ivb": 0.0, "run": 0.0}
            return ui.layout_columns(
                ui.input_numeric("pp_ap_velo", "Velo (mph)", value=t.get("velo"), step=0.5),
                ui.input_numeric("pp_ap_ivb", "Ride (in)", value=t["ivb"], step=0.5),
                ui.input_numeric("pp_ap_run", "Run (in)", value=t["run"], step=0.5),
                ui.input_text("pp_ap_note", "Note", value=""),
                col_widths=[2, 2, 2, 6],
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.pp_ap_save)
    def _pp_ap_save():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        ivb, run = input.pp_ap_ivb(), input.pp_ap_run()
        if ivb is None or run is None:
            ui.notification_show("Enter ride and run.", type="warning", duration=5)
            return
        db = get_session()
        try:
            pid = _current_player_id(db)
            fam = input.pp_ap_family()
            row = db.query(ArsenalTarget).filter(ArsenalTarget.player_id == pid, ArsenalTarget.family == fam).first()
            if row is None:
                row = ArsenalTarget(player_id=pid, family=fam)
                db.add(row)
            row.velo = input.pp_ap_velo()
            row.ivb, row.run = ivb, run
            row.note = (input.pp_ap_note() or "").strip() or None
            row.updated_by_user_id = app_state.user_id()
            db.commit()
            ui.notification_show(f"Saved {arsenal_plan.NAMES.get(fam, fam)} target.", type="message", duration=5)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_arsenal_targets been run? ({e})", type="error", duration=10)
        finally:
            db.close()
        _ap_tick.set(_ap_tick() + 1)

    @reactive.effect
    @reactive.event(input.pp_ap_reset)
    def _pp_ap_reset():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        db = get_session()
        try:
            pid = _current_player_id(db)
            db.query(ArsenalTarget).filter(ArsenalTarget.player_id == pid,
                                           ArsenalTarget.family == input.pp_ap_family()).delete()
            db.commit()
            ui.notification_show("Back to the rule-based target.", type="message", duration=5)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't reset ({e})", type="error", duration=10)
        finally:
            db.close()
        _ap_tick.set(_ap_tick() + 1)

    @render_plotly
    def pp_ap_movement():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "arsenal_plan":
            return None
        _ap_tick()
        db = get_session()
        try:
            _player, plan, _raps = _ap_data(db)
            return plan_movement_figure(plan) if plan else None
        finally:
            db.close()

    @render_plotly
    def pp_ap_progress():
        if not app_state.is_authenticated():
            return None
        req("pp_view" in input)
        if input.pp_view() != "arsenal_plan":
            return None
        _ap_tick()
        db = get_session()
        try:
            player, plan, raps = _ap_data(db)
            if not plan:
                return None
            return progress_figure(arsenal_plan.progress(raps, player.throws or "R", plan, label_of=pitch_type_label))
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Fastball Shape Check (Oct 2026, Ryker: "build this into the
    # website. fastball shape check. if it fits the other type then we
    # can switch it"). Pitches are logged by GRIP; this compares each
    # Rapsodo-tracked fastball's movement against the pitcher's own
    # 4-seam/2-seam groups (analytics/fastball_shape.py) and lists the
    # ones that move like the other type. A coach checks the ones to
    # switch and confirms -- the Rapsodo reading and its matched game
    # pitch are relabeled together and logged (PitchTypeChange) so every
    # switch can be undone. Ignores the page's Pitch Type filter (it's
    # always about fastballs); honors the date range / game picker.
    # Bullpen readings are included (their labels feed Stuff+ too).
    # -------------------------------------------------------------------
    FS_SWITCH_ROLES = ("Administrator", "Head Coach", "Coach", "Data Analyst")
    _fs_tick = reactive.Value(0)

    def _fs_data(db):
        pid = _current_player_id(db)
        if pid is None:
            return None, None
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None:
            return None, None
        f = _current_filters()
        raps = profile_queries.get_pitcher_rapsodo_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=None,
            game_scope=f["game_scope"], game_id=f["game_id"], game_linked_only=False,
        )
        arsenal = [
            pt.type_name for pt in db.query(PitchType)
            .join(PlayerPitchArsenal, PlayerPitchArsenal.pitch_type_id == PitchType.pitch_type_id)
            .filter(PlayerPitchArsenal.player_id == pid, PlayerPitchArsenal.active.is_(True)).all()
        ]
        return player, fastball_shape.check_pitcher(raps, player.throws or "R", arsenal=arsenal or None)

    def _fs_pitch_label(fl):
        p = fl["pitch"]
        when = p.pitch_date.strftime("%b %d") if p.pitch_date else "—"
        src = "Game" if p.bullpen_id is None else "Bullpen"
        velo = f"{fl['velo']:.1f} mph · " if fl.get("velo") is not None else ""
        return (f"{when} {src} #{p.pitch_number}: {fl['labeled']} → {fl['suggested']} "
                f"({velo}{fl['ivb']:.1f}\" ride, {fl['run']:.1f}\" run)")

    @render.ui
    def pp_fastball_shape_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "fastball_shape":
            return None
        _fs_tick()
        db = get_session()
        try:
            player, res = _fs_data(db)
            if player is None:
                return None
            if res["mode"] == "none":
                return ui.p("No Rapsodo-tracked fastballs (4-seam / 2-seam / Fastball) with movement data in this range yet.", class_="text-muted small")
            can_switch = role in FS_SWITCH_ROLES
            counts = " · ".join(f"{t}: {n}" for t, n in sorted(res["counts"].items()))
            if res["mode"] == "per_pitcher":
                c4, c2 = res["centers"][fastball_shape.FOUR_SEAM], res["centers"][fastball_shape.TWO_SEAM]
                mode_text = (f"Compared to his own fastballs -- 4-seam avg {c4[0]:.1f}\" ride / {c4[1]:.1f}\" arm-side run, "
                             f"2-seam avg {c2[0]:.1f}\" ride / {c2[1]:.1f}\" run (group medians).")
            else:
                mode_text = ("He doesn't throw enough of both fastballs (or they move too much alike) to compare him to himself, "
                             "so this uses general guidelines: a 4-seam rides well over its run, a 2-seam runs more than it rides.")
            fb_ref = res.get("fb_ref")
            if fb_ref is not None:
                src = res.get("offspeed_sources") or {}
                src_txt = ", ".join(f"{t} ({'his own' if v == 'his' else 'guideline'})" for t, v in src.items())
                mode_text += (f" Off-speed check: his fastball sits {fb_ref[2]:.1f} mph, {fb_ref[0]:.1f}\" ride / "
                              f"{fb_ref[1]:.1f}\" run. A pitch logged as a fastball that's {fastball_shape.OFFSPEED_VELO_GAP:.0f}+ mph "
                              f"slower, or breaks well glove-side with much less ride, is flagged with the off-speed pitch it "
                              f"moves most like" + (f" -- checking {src_txt}." if src_txt else "."))
            else:
                mode_text += (f" Off-speed check needs at least {fastball_shape.MIN_FB_REFERENCE} fastball readings "
                              f"with velo to know his fastball, so it's skipped here.")
            flags = res["flags"]
            children = [
                ui.hr(),
                ui.h5("Fastball Shape Check", class_="gbo-section-title"),
                ui.p("Pitches are logged by grip. This flags Rapsodo-tracked pitches logged as fastballs that are really "
                     "off-speed (too slow or breaking the wrong way), and fastballs that move like his other fastball, "
                     "so you can confirm and switch the label. " + mode_text, class_="text-muted small"),
                ui.p(f"Checked: {counts}", class_="text-muted small"),
                output_widget("pp_fastball_shape_chart"),
            ]
            if not flags:
                children.append(ui_helpers.card(ui_helpers.empty_state("Every fastball matches its label. Nothing to switch.")))
            else:
                osn = sum(1 for f in flags if f["kind"] == "offspeed")
                mism = sum(1 for f in flags if f["kind"] == "mismatch")
                unl = sum(1 for f in flags if f["kind"] == "unlabeled")
                parts = []
                if osn:
                    parts.append(f"{osn} logged as a fastball but look off-speed")
                if mism:
                    parts.append(f"{mism} move like the other fastball")
                if unl:
                    parts.append(f"{unl} unlabeled \"Fastball\" reading(s) with a suggested type")
                summary = "; ".join(parts) + "."
                table = ui_helpers.render_dict_table([{
                    "Date": f["pitch"].pitch_date.strftime("%Y-%m-%d") if f["pitch"].pitch_date else "—",
                    "Source": "Game" if f["pitch"].bullpen_id is None else "Bullpen",
                    "#": f["pitch"].pitch_number,
                    "Logged as": f["labeled"], "Moves like": f["suggested"],
                    "Velo": f"{f['velo']:.1f}" if f["velo"] is not None else "—",
                    "Ride (IVB)": f"{f['ivb']:.1f}", "Arm-side run": f"{f['run']:.1f}",
                    "Why": f["reason"],
                } for f in flags])
                body = [ui.p(summary, class_="small"), table]
                if can_switch:
                    body += [
                        ui.input_checkbox_group(
                            "pp_fs_select", "Switch these pitches to the type they move like:",
                            choices={str(f["pitch"].rapsodo_pitch_id): _fs_pitch_label(f) for f in flags},
                        ),
                        ui.input_action_button("pp_fs_switch", "Switch selected", class_="btn-sm btn-primary"),
                        ui.p("Updates the Rapsodo reading and its matched game pitch. Every switch is logged and can be undone below.",
                             class_="text-muted small", style="margin-top:6px;"),
                    ]
                children.append(ui_helpers.card(*body, title="Flagged pitches"))

            if can_switch:
                recent = (
                    db.query(PitchTypeChange)
                    .filter(PitchTypeChange.player_id == player.player_id, PitchTypeChange.undone_at.is_(None))
                    .order_by(PitchTypeChange.changed_at.desc()).limit(50).all()
                )
                if recent:
                    type_names = {t.pitch_type_id: t.type_name for t in db.query(PitchType).all()}
                    choices = {
                        str(ch.pitch_type_change_id):
                            f"{ch.changed_at.strftime('%b %d %H:%M')} -- Rapsodo #{ch.rapsodo_pitch_id or '?'}: "
                            f"{type_names.get(ch.from_rapsodo_pitch_type_id, '?')} → {type_names.get(ch.to_pitch_type_id, '?')}"
                        for ch in recent
                    }
                    children.append(ui_helpers.card(
                        ui.input_checkbox_group("pp_fs_undo_select", None, choices=choices),
                        ui.input_action_button("pp_fs_undo", "Undo selected", class_="btn-sm btn-outline-light"),
                        title="Recent switches", right="undo puts both labels back",
                    ))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def pp_fastball_shape_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "fastball_shape":
            return None
        _fs_tick()
        db = get_session()
        try:
            player, res = _fs_data(db)
            if player is None or not res or not res["points"]:
                return None
            fig = go.Figure()
            for label in (fastball_shape.FOUR_SEAM, fastball_shape.TWO_SEAM, fastball_shape.GENERIC):
                pts = [pt for pt in res["points"] if pt["labeled"] == label and not pt.get("offspeed")]
                if not pts:
                    continue
                fig.add_trace(go.Scatter(
                    x=[pt["run"] for pt in pts], y=[pt["ivb"] for pt in pts], mode="markers", name=f"Logged {label}",
                    marker=dict(size=[12 if pt["flagged"] else 8 for pt in pts], color=get_pitch_color(label),
                                line=dict(width=[2.5 if pt["flagged"] else 0 for pt in pts], color="#FFFDE5"), opacity=0.85),
                    text=[f"{'FLAGGED -- ' if pt['flagged'] else ''}{label}<br>{pt['ivb']:.1f}\" ride, {pt['run']:.1f}\" run"
                          + (f"<br>{pt['velo']:.1f} mph" if pt['velo'] is not None else "") for pt in pts],
                    hovertemplate="%{text}<extra></extra>",
                ))
            for os_type in sorted({pt["offspeed"] for pt in res["points"] if pt.get("offspeed")}):
                pts = [pt for pt in res["points"] if pt.get("offspeed") == os_type]
                fig.add_trace(go.Scatter(
                    x=[pt["run"] for pt in pts], y=[pt["ivb"] for pt in pts], mode="markers",
                    name=f"Logged fastball → looks like {os_type}",
                    marker=dict(size=12, symbol="diamond", color=get_pitch_color(os_type),
                                line=dict(width=2.5, color="#FFFDE5"), opacity=0.9),
                    text=[f"FLAGGED -- logged {pt['labeled']}, looks like {os_type}<br>{pt['ivb']:.1f}\" ride, {pt['run']:.1f}\" run"
                          + (f"<br>{pt['velo']:.1f} mph" if pt['velo'] is not None else "") for pt in pts],
                    hovertemplate="%{text}<extra></extra>",
                ))
            fb_ref = res.get("fb_ref")
            if fb_ref is not None:
                fig.add_trace(go.Scatter(
                    x=[fb_ref[1]], y=[fb_ref[0]], mode="markers", name="His fastball (reference)",
                    marker=dict(symbol="star", size=16, color="#FFFDE5", line=dict(width=1, color="#000")),
                    hovertemplate=f"His fastball reference<br>{fb_ref[2]:.1f} mph, {fb_ref[0]:.1f}\" ride, {fb_ref[1]:.1f}\" run<extra></extra>",
                ))
            for label, c in res["centers"].items():
                fig.add_trace(go.Scatter(
                    x=[c[1]], y=[c[0]], mode="markers", name=f"His {label} center",
                    marker=dict(symbol="x", size=14, color=get_pitch_color(label), line=dict(width=2)),
                    hovertemplate=f"{label} group center<br>{c[0]:.1f}\" ride, {c[1]:.1f}\" run<extra></extra>",
                ))
            fig = apply_gbo_theme(fig, title="Pitches logged as fastballs (outlined = flagged)", height=420,
                                  x_title="Arm-side run (in)", y_title="Induced vertical break (in)")
            return fig
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch Type Check (Oct 2026, Ryker: "build it") -- every pitch type,
    # not just fastballs: fastball / breaking ball / changeup by speed off
    # his fastball + arm-side run + IVB (analytics/pitch_class.py, after
    # SABR Tooth Tigers' TopoTagger, centered on OUR Rapsodo data). Same
    # review-then-switch flow as Fastball Shape Check, same logged/undoable
    # switching (services/pitch_type_switch.py, source "pitch_type_check").
    # -------------------------------------------------------------------
    _ptc_tick = reactive.Value(0)

    def _ptc_centers(db):
        return pitch_class.team_centers(db)

    def _ptc_data(db):
        pid = _current_player_id(db)
        if pid is None:
            return None, None
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None:
            return None, None
        f = _current_filters()
        raps = profile_queries.get_pitcher_rapsodo_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=None,
            game_scope=f["game_scope"], game_id=f["game_id"], game_linked_only=False,
        )
        return player, pitch_class.check_pitcher(raps, player.throws or "R", _ptc_centers(db)["centers"])

    def _ptc_staff_rows(db):
        """Flag counts for every pitcher in the same date range."""
        f = _current_filters()
        q = db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
        if f["date_from"] is not None:
            q = q.filter(RapsodoPitch.pitch_date >= f["date_from"])
        if f["date_to"] is not None:
            q = q.filter(RapsodoPitch.pitch_date < f["date_to"] + timedelta(days=1))
        by_p = {}
        for r in q.all():
            by_p.setdefault(r.player_id, []).append(r)
        if not by_p:
            return []
        players = {pl.player_id: pl for pl in db.query(Player).filter(Player.player_id.in_(list(by_p))).all()}
        centers = _ptc_centers(db)["centers"]
        rows = []
        for pid, raps in by_p.items():
            pl = players.get(pid)
            if pl is None:
                continue
            res = pitch_class.check_pitcher(raps, pl.throws or "R", centers)
            if not res["points"]:
                continue
            rows.append({"Pitcher": f"{pl.last_name}, {pl.first_name}", "Pitches": len(res["points"]),
                         "Flagged": len(res["flags"]), "Agree %": res["agree_pct"] if res["agree_pct"] is not None else "--"})
        return sorted(rows, key=lambda r: (-r["Flagged"], r["Pitcher"]))

    @render.ui
    def pp_pitch_type_check_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "pitch_type_check":
            return None
        _ptc_tick()
        db = get_session()
        try:
            player, res = _ptc_data(db)
            if player is None:
                return None
            cal = _ptc_centers(db)
            cen = cal["centers"]
            def _c(g):
                c = cen[g]
                return f"{g.lower()} {c[2]:+.1f} mph / {c[0]:.1f}\" run / {c[1]:.1f}\" IVB"
            src = "our own Rapsodo pitches" if all(v == "ours" for v in cal["source"].values()) else "our pitches where we have enough, the article's D1 numbers otherwise"
            children = [
                ui.hr(),
                ui.h5("Pitch Type Check", class_="gbo-section-title"),
                ui.p("Every Rapsodo-tracked pitch sorted into what a hitter sees -- fastball, breaking ball or changeup -- "
                     "by its speed off his own fastball, arm-side run and ride (IVB). A pitch is flagged when it clearly "
                     "behaves like a different group than its label. Cutters can sit with fastballs or breaking balls and "
                     "splitters with changeups or breaking balls, so those aren't flagged for either. Pitches are logged by "
                     f"grip -- nothing changes until you switch it. Group centers come from {src}: " + "; ".join(_c(g) for g in cen) + ".",
                     class_="text-muted small"),
            ]
            staff = _ptc_staff_rows(db)
            if staff:
                children.append(ui_helpers.card(ui_helpers.render_dict_table(staff), title="Whole staff (same dates)",
                                                right="pick a pitcher above to review"))
            if not res or not res["points"]:
                children.append(ui.p("No Rapsodo pitches with movement and velocity for him in this range.", class_="text-muted small"))
                return ui.div(*children)
            children.append(ui.p(f"{player.first_name} {player.last_name}: {len(res['points'])} pitches checked, "
                                 f"{res['agree_pct']}% match their label." if res["agree_pct"] is not None else "", class_="small"))
            children.append(output_widget("pp_ptc_chart"))
            can_switch = role in FS_SWITCH_ROLES
            flags = res["flags"]
            if not flags:
                children.append(ui_helpers.card(ui_helpers.empty_state("Every pitch behaves like its label. Nothing to switch.")))
            else:
                table = ui_helpers.render_dict_table([{
                    "Date": fl["pitch"].pitch_date.strftime("%Y-%m-%d") if fl["pitch"].pitch_date else "--",
                    "Source": "Game" if fl["pitch"].bullpen_id is None else "Bullpen",
                    "#": fl["pitch"].pitch_number,
                    "Logged as": fl["labeled"], "Behaves like": fl["looks_like"], "Suggested": fl["suggested"],
                    "Velo": f"{fl['velo']:.1f}", "vs FB": f"{fl['dv']:+.1f}",
                    "Arm-side run": f"{fl['run']:.1f}", "IVB": f"{fl['ivb']:.1f}",
                } for fl in flags])
                body = [ui.p(f"{len(flags)} pitch(es) behave like a different group than their label.", class_="small"), table]
                if can_switch:
                    body += [
                        ui.input_checkbox_group(
                            "pp_ptc_select", "Switch these pitches to the suggested type:",
                            choices={str(fl["pitch"].rapsodo_pitch_id):
                                     (f"{fl['pitch'].pitch_date.strftime('%b %d') if fl['pitch'].pitch_date else '--'} "
                                      f"{'Game' if fl['pitch'].bullpen_id is None else 'Bullpen'} #{fl['pitch'].pitch_number}: "
                                      f"{fl['labeled']} → {fl['suggested']} ({fl['velo']:.1f} mph, {fl['run']:.1f}\" run, {fl['ivb']:.1f}\" IVB)")
                                     for fl in flags},
                        ),
                        ui.input_action_button("pp_ptc_switch", "Switch selected", class_="btn-sm btn-primary"),
                        ui.p("Updates the Rapsodo reading and its matched game pitch. Every switch is logged and can be undone "
                             "(Fastball Shape Check's Recent switches list shows them too).", class_="text-muted small", style="margin-top:6px;"),
                    ]
                children.append(ui_helpers.card(*body, title="Flagged pitches"))
            if can_switch:
                recent = (db.query(PitchTypeChange)
                          .filter(PitchTypeChange.player_id == player.player_id, PitchTypeChange.undone_at.is_(None))
                          .order_by(PitchTypeChange.changed_at.desc()).limit(50).all())
                if recent:
                    names = {t.pitch_type_id: t.type_name for t in db.query(PitchType).all()}
                    children.append(ui_helpers.card(
                        ui.input_checkbox_group("pp_ptc_undo_select", None, choices={
                            str(ch.pitch_type_change_id):
                                f"{ch.changed_at.strftime('%b %d %H:%M')} -- Rapsodo #{ch.rapsodo_pitch_id or '?'}: "
                                f"{names.get(ch.from_rapsodo_pitch_type_id, '?')} → {names.get(ch.to_pitch_type_id, '?')}"
                            for ch in recent}),
                        ui.input_action_button("pp_ptc_undo", "Undo selected", class_="btn-sm btn-outline-light"),
                        title="Recent switches", right="undo puts both labels back",
                    ))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def pp_ptc_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in STAFF_ROLES:
            return None
        req("pp_view" in input)
        if input.pp_view() != "pitch_type_check":
            return None
        _ptc_tick()
        db = get_session()
        try:
            player, res = _ptc_data(db)
            if player is None or not res or not res["points"]:
                return None
            cen = _ptc_centers(db)["centers"]
            fig = go.Figure()
            for label in sorted({pt["labeled"] or "Unlabeled" for pt in res["points"]}):
                pts = [pt for pt in res["points"] if (pt["labeled"] or "Unlabeled") == label]
                fig.add_trace(go.Scatter(
                    x=[pt["run"] for pt in pts], y=[pt["ivb"] for pt in pts], mode="markers", name=f"Logged {label}",
                    marker=dict(size=[13 if pt["flagged"] else 8 for pt in pts],
                                symbol=["diamond" if pt["flagged"] else "circle" for pt in pts],
                                color=get_pitch_color(label),
                                line=dict(width=[2.5 if pt["flagged"] else 0 for pt in pts], color="#FFFDE5"), opacity=0.85),
                    text=[f"{'FLAGGED -- behaves like a ' + pt['pred'].lower() + '<br>' if pt['flagged'] else ''}{label}<br>"
                          f"{pt['velo']:.1f} mph ({pt['dv']:+.1f} vs FB)<br>{pt['run']:.1f}\" run, {pt['ivb']:.1f}\" IVB" for pt in pts],
                    hovertemplate="%{text}<extra></extra>",
                ))
            for g, c in cen.items():
                fig.add_trace(go.Scatter(
                    x=[c[0]], y=[c[1]], mode="markers+text", name=f"{g} center", text=[g], textposition="top center",
                    marker=dict(symbol="x", size=14, color="#FFFDE5", line=dict(width=2)),
                    hovertemplate=f"{g} group center (staff)<br>{c[2]:+.1f} mph vs FB, {c[0]:.1f}\" run, {c[1]:.1f}\" IVB<extra></extra>",
                ))
            return apply_gbo_theme(fig, title="Every pitch by movement (diamonds = flagged)", height=440,
                                   x_title="Arm-side run (in)", y_title="Induced vertical break (in)")
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.pp_ptc_switch)
    def _pp_ptc_switch():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        selected = set(input.pp_ptc_select() or []) if "pp_ptc_select" in input else set()
        if not selected:
            ui.notification_show("Check at least one pitch to switch.", type="warning", duration=6)
            return
        db = get_session()
        try:
            _player, res = _ptc_data(db)
            switches = [(fl["pitch"].rapsodo_pitch_id, fl["suggested"], fl["reason"])
                        for fl in (res or {}).get("flags", []) if str(fl["pitch"].rapsodo_pitch_id) in selected]
            n = apply_switches(db, switches, user_id=app_state.user_id(), source="pitch_type_check")
            ui.notification_show(f"Switched {n} pitch(es).", type="message", duration=6)
        except Exception as e:
            ui.notification_show(f"Couldn't switch those pitches -- nothing was changed. ({e})", type="error", duration=10)
        finally:
            db.close()
        _ptc_tick.set(_ptc_tick() + 1)
        _fs_tick.set(_fs_tick() + 1)

    @reactive.effect
    @reactive.event(input.pp_ptc_undo)
    def _pp_ptc_undo():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        selected = [int(x) for x in (input.pp_ptc_undo_select() or [])] if "pp_ptc_undo_select" in input else []
        if not selected:
            ui.notification_show("Check at least one switch to undo.", type="warning", duration=6)
            return
        db = get_session()
        try:
            n = undo_switches(db, selected)
            ui.notification_show(f"Undid {n} switch(es).", type="message", duration=6)
        except Exception as e:
            ui.notification_show(f"Couldn't undo -- nothing was changed. ({e})", type="error", duration=10)
        finally:
            db.close()
        _ptc_tick.set(_ptc_tick() + 1)
        _fs_tick.set(_fs_tick() + 1)

    @reactive.effect
    @reactive.event(input.pp_fs_switch)
    def _pp_fs_switch():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        selected = set(input.pp_fs_select() or []) if "pp_fs_select" in input else set()
        if not selected:
            ui.notification_show("Check at least one pitch to switch.", type="warning", duration=6)
            return
        db = get_session()
        try:
            _player, res = _fs_data(db)
            switches = [
                (f["pitch"].rapsodo_pitch_id, f["suggested"], f["reason"])
                for f in (res or {}).get("flags", []) if str(f["pitch"].rapsodo_pitch_id) in selected
            ]
            n = apply_switches(db, switches, user_id=app_state.user_id())
            ui.notification_show(f"Switched {n} pitch(es).", type="message", duration=6)
        except Exception as e:
            ui.notification_show(f"Couldn't switch those pitches -- nothing was changed. ({e})", type="error", duration=10)
        finally:
            db.close()
        _fs_tick.set(_fs_tick() + 1)

    @reactive.effect
    @reactive.event(input.pp_fs_undo)
    def _pp_fs_undo():
        if app_state.role_name() not in FS_SWITCH_ROLES:
            return
        selected = [int(x) for x in (input.pp_fs_undo_select() or [])] if "pp_fs_undo_select" in input else []
        if not selected:
            ui.notification_show("Check at least one switch to undo.", type="warning", duration=6)
            return
        db = get_session()
        try:
            n = undo_switches(db, selected)
            ui.notification_show(f"Undid {n} switch(es).", type="message", duration=6)
        except Exception as e:
            ui.notification_show(f"Couldn't undo -- nothing was changed. ({e})", type="error", duration=10)
        finally:
            db.close()
        _fs_tick.set(_fs_tick() + 1)
