"""
GBO -- Hitter Profile (Aug 2026, Phase 0 of STUFF-LOCATION-PITCHING-
PLUS-PLAN.md; retiled into tabs Sept 2026). Batting-side counterpart to
pitcher_profile.py: a filterable, per-hitter deep dive across counting
stats/slash line, plate discipline (overall and by zone tier), batted-
ball profile, situational splits, and contact quality by zone/pitch
type -- all from the exact same game_stats.py/plate_discipline.py
functions Analytics/My Stats and Hitter Game Report already use, just
scoped to this page's own date-range/pitch-type/game-scope filters
instead of one game_id. No Stuff+/Location+/Pitching+ here -- those
are pitcher-only grades (see pitcher_profile.py); a hitter's "how am I
doing against stuff" read is the Contact Quality by Zone/Pitch Type
view below.

Self-scoping, same pattern as pitcher_profile.py/player_profile.py: a
staff role sees a player picker (scoped to assigned players unless
can_view_all_players); a "Player" role always sees their own linked
player, no picker, and gets nothing if that player IS a pitcher (pure
pitchers don't get a Hitter Profile -- mirrors My Bullpens/My Hitting's
existing is_pitcher split). A two-way player who bats and pitches only
ever gets routed to one of the two via nav.py's is_pitcher flag, same
simplification the rest of the app already makes.

View tabs (Sept 2026, Ryker: "make hitter profile similar to pitcher
to where it has tabs and you can choose what you want to see" -- same
"View" dropdown convention pitcher_profile.py/pitcher_game_report.py
already established, gating which of the render.ui sections below
actually queries/renders, rather than one long page everyone has to
scroll through): Overview (Line/Slash Line/OPS+/Performance), Plate
Discipline (BB%/K%, Zone discipline, Zone-Tier table, and -- Ryker's
own reference here was Baseball Savant's percentile-rank rows -- one
percentile bar each for wOBA/Chase %/Whiff %/Zone Swing %, reusing
performance_score's own single-metric z-score math one metric at a
time instead of blended), Batted Ball (GB/FB/LD/PopUp, Pull/Center/
Oppo or LF/CF/RF, Barrel %/Hard Contact %), Situational & Count
Leverage (RISP/2-Strike/Leadoff AVG, QAB %, Ahead/Even/Behind table),
Contact Quality by Zone (the existing Hitter Tracking zone-score
heat map), and Spray Chart (Sept 2026 addition, Ryker: "i want a hit
spray chart as well as an infield slice chart" -- Baseball Savant's
own two-panel Spray Chart/Infield Slice Chart, side by side, built
from visualizations/spray_chart.py; hits-only on the spray chart,
matching Savant's own default view -- see that module's docstring for
the full definitions). Each gated section function checks input.hp_view() itself
and returns None immediately when not selected -- switching the
dropdown is what stops the DB work for the other views, not CSS
visibility -- same discipline pitcher_profile.py's pp_view_picker
docstring spells out. GBO has no real Statcast data (no exit-velo
radar, no xwOBA) -- the percentile-bar treatment here is GBO's own
team-relative "+" grade system re-used per-metric, not a real Statcast
percentile rank against the league.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req
from shinywidgets import output_widget, render_plotly

from database import get_session
from models import Player, User, PitchType, StaffPlayerAssignment
from game_stats import get_pitcher_hands, compute_batting_line, compute_batted_ball_profile, ops_plus
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline
from analytics import performance_score, profile_queries
from analytics import hitter_hot_zones, hitter_insights, league_baselines, trends
from visualizations import trend_charts
from visualizations import hitter_insight_charts as hic
from visualizations.hitter_hot_zone_chart import hot_zone_figure
from modules.hitter_tracking import _compute_zone_scores, _build_zone_heatmap_figure, CONTACT_QUALITY_SCORE
from visualizations.spray_chart import hit_spray_chart, infield_slice_chart

import ui_helpers
import format_helpers
import glossary_content
from format_helpers import format_pct as _fmt_pct

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

# One percentile bar per metric, in display order -- (HITTER_RESULTS_METRICS
# key, display label). wOBA's own bar is still labeled "wOBA*" (same
# generic-linear-weights caveat asterisk every other wOBA display in
# the app carries), even though the underlying baseline/line dict key
# is the plain "wOBA" performance_score.HITTER_RESULTS_METRICS uses.
DISCIPLINE_PERCENTILE_METRICS = [
    ("wOBA", "wOBA*"),
    ("Chase %", "Chase %"),
    ("Whiff %", "Whiff %"),
    ("Zone Swing %", "Zone Swing %"),
]


def _fmt(value, decimals=3):
    return format_helpers.format_num(value, decimals)


def _my_player(db, app_state):
    me = db.query(User).filter(User.user_id == app_state.user_id()).first()
    if me is None or me.player_id is None:
        return None
    return db.query(Player).filter(Player.player_id == me.player_id).first()


@module.ui
def hitter_profile_ui():
    return ui.div(
        ui_helpers.page_header("Hitter Profile", actions=ui_helpers.how_to_link("hitter_profile")),
        ui.output_ui("hp_player_picker"),
        ui.output_ui("hp_filters"),
        # Sept 2026, Ryker: a "View" dropdown instead of every section
        # rendering at once and scrolling forever -- same convention
        # pitcher_profile.py already established. Each of these six
        # stays statically listed here (Shiny needs a placeholder in
        # the DOM for each output id) -- the gate inside each render.ui
        # function is what actually controls which one does anything.
        ui.output_ui("hp_view_picker"),
        ui.output_ui("hp_overview_section"),
        ui.output_ui("hp_discipline_section"),
        ui.output_ui("hp_batted_ball_section"),
        ui.output_ui("hp_situational_section"),
        ui.output_ui("hp_hot_zones_section"),
        ui.output_ui("hp_insights_section"),
        ui.output_ui("hp_contact_section"),
        ui.output_ui("hp_spray_chart_section"),
        ui_helpers.page_footer(),
    )


@module.server
def hitter_profile_server(input, output, session, app_state):

    def _visible_hitters(db):
        q = db.query(Player).filter(Player.is_pitcher.is_(False))
        if not app_state.can_view_all_players():
            ids = [a.player_id for a in db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()]
            q = q.filter(Player.player_id.in_(ids))
        return q.filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()

    def _current_player_id(db):
        if app_state.role_name() == "Player":
            me = _my_player(db, app_state)
            return me.player_id if (me is not None and not me.is_pitcher) else None
        if "hp_player_select" not in input or not input.hp_player_select():
            return None
        return int(input.hp_player_select())

    @render.ui
    def hp_player_picker():
        if not app_state.is_authenticated() or app_state.role_name() == "Player":
            return None
        if app_state.role_name() not in STAFF_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")
        db = get_session()
        try:
            hitters = _visible_hitters(db)
        finally:
            db.close()
        if not hitters:
            return ui_helpers.empty_state("No hitters to show yet.")
        choices = {str(p.player_id): f"{p.last_name}, {p.first_name}" + (f"  #{p.jersey_number}" if p.jersey_number else "") for p in hitters}
        return ui.div(ui.input_select("hp_player_select", "Hitter", choices=choices, width="320px"), style="margin-bottom:8px;")

    @render.ui
    def hp_filters():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        if role in STAFF_ROLES:
            req("hp_player_select" in input)

        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()
            type_choices = {"__all__": "All Pitches"}
            for t in pitch_types:
                type_choices[t.type_name] = t.type_name
        finally:
            db.close()

        return ui.layout_columns(
            ui.input_date("hp_date_from", "From", value=date.today() - timedelta(days=365)),
            ui.input_date("hp_date_to", "To", value=date.today()),
            ui.input_select("hp_pitch_type", "Pitch Type Seen", choices=type_choices),
            ui.input_select("hp_game_scope", "Games", choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[3, 3, 3, 3],
        )

    def _current_filters():
        req("hp_date_from" in input)
        req("hp_date_to" in input)
        req("hp_pitch_type" in input)
        req("hp_game_scope" in input)
        pitch_type = input.hp_pitch_type()
        return {
            "date_from": input.hp_date_from(),
            "date_to": input.hp_date_to(),
            "pitch_type": None if pitch_type == "__all__" else pitch_type,
            "game_scope": input.hp_game_scope(),
        }

    def _current_pitches(db):
        pid = _current_player_id(db)
        if pid is None:
            return None, None
        f = _current_filters()
        pitches = profile_queries.get_hitter_profile_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"],
            pitch_type=f["pitch_type"], game_scope=f["game_scope"], pitcher_hand=None,
        )
        return pid, pitches

    @render.ui
    def hp_view_picker():
        """The "View" dropdown driving which of the sections below
        actually renders -- same convention pitcher_profile.py's own
        pp_view_picker already established (Sept 2026, Ryker: "make
        hitter profile similar to pitcher to where it has tabs and you
        can choose what you want to see"). Each gated section function
        below checks input.hp_view() itself and returns None
        immediately when not selected, before doing any query --
        switching this dropdown is what stops the DB work for the
        other views, not CSS visibility."""
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        if role in STAFF_ROLES:
            req("hp_player_select" in input)
        db = get_session()
        try:
            pid, pitches = _current_pitches(db)
            if pid is None or not pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.input_select(
                    "hp_view", "View",
                    choices={
                        "overview": "Overview",
                        "discipline": "Plate Discipline",
                        "batted_ball": "Batted Ball",
                        "situational": "Situational & Count Leverage",
                        "hot_zones": "Hot Zones",
                        "swing_decisions": "Swing Decisions",
                        "attack": "How Pitchers Attack Me",
                        "pitch_type": "Results by Pitch Type",
                        "fp_two": "First Pitch & Two Strikes",
                        "ranks": "Team Percentile Ranks",
                        "trends": "Trends",
                        "contact_zone": "Contact Quality by Zone",
                        "spray_chart": "Spray Chart",
                    },
                ),
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Overview: Line / Slash Line (incl. OPS+) / Performance -- the "at
    # a glance" numbers, same role pitcher_profile.py's Overview view
    # plays, and (Ryker's own reference) the top-of-page summary a
    # Baseball Savant player page opens with.
    # -------------------------------------------------------------------
    @render.ui
    def hp_overview_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "overview":
            return None

        db = get_session()
        try:
            pid, pitches = _current_pitches(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None
            if not pitches:
                return ui_helpers.card(ui_helpers.empty_state(
                    "No pitches seen in this date range yet. Widen the filters, or check back once games are tracked."
                ))
            f = _current_filters()

            line = compute_batting_line(pitches)
            # Oct 2026: OPS+ (and the other "+" stats below) vs the 2026 D2 average.
            player_ops_plus = ops_plus(line["OBP"], line["SLG"])
            plus = league_baselines.hitting_plus(line)
            sections = [ui.div(
                ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title", style="margin-bottom:0;"),
                ui_helpers.glossary_link("hp_glossary_overview", "Overview Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]

            sections.append(ui.p(ui.strong("Line")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "PA", "value": str(line["PA"])},
                {"label": "AB", "value": str(line["AB"])},
                {"label": "H", "value": str(line["H"])},
                {"label": "BB", "value": str(line["BB"])},
                {"label": "K", "value": str(line["K"])},
                {"label": "AVG", "value": _fmt(line["AVG"])},
            ]))
            sections.append(ui.p(
                f"1B: {line['1B']} · 2B: {line['2B']} · 3B: {line['3B']} · HR: {line['HR']} · HBP: {line['HBP']} · "
                f"Total RV: {line['Total RV']} · Avg RV/PA: {line['Avg RV/PA']}",
                class_="text-muted small",
            ))

            sections.append(ui.p(ui.strong("Slash Line")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "OBP", "value": _fmt(line["OBP"])},
                {"label": "SLG", "value": _fmt(line["SLG"])},
                {"label": "OPS", "value": _fmt(line["OPS"])},
                {"label": "OPS+", "value": str(player_ops_plus) if player_ops_plus is not None else "—"},
                {"label": "ISO", "value": _fmt(line["ISO"])},
                {"label": "wOBA*", "value": _fmt(line["wOBA"])},
            ]))
            sections.append(ui.p(
                "*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact. "
                "OPS+ is vs the 2026 D2 average (100 = D2 average).",
                class_="text-muted small",
            ))
            sections.append(ui.p(ui.strong("Plus stats vs D2 (2026)")))
            sections.append(ui_helpers.plus_stat_cards(plus, league_baselines.HITTING_PLUS_ORDER, league_baselines.hitting_actuals(line)))
            sections.append(ui.p(league_baselines.PLUS_HELP, class_="text-muted small"))

            # Performance: results-based composite (Aug 31 2026 design
            # call with Ryker -- see analytics/performance_score.py's
            # module docstring). Hitters don't get a Stuff+/Location+/
            # Command+/Arsenal equivalent (pitcher-only, pitch-quality
            # concepts) -- this IS the whole Hitter Performance score,
            # not a blend of several pieces the way pitcher Performance
            # is. Needs compute_hitter_discipline for its Chase %/
            # Whiff %/Zone Swing % inputs -- the Plate Discipline view
            # computes the same thing again for its own KPI cards, same
            # "each gated section computes what it needs" convention
            # pitcher_profile.py's own views already follow.
            discipline = compute_hitter_discipline(pitches)
            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Performance")))
            sections.append(ui.p(
                "Results-based composite -- wOBA, AVG, Chase % (lower better), Whiff % (lower better), Zone "
                "Swing % (higher better), all team-relative -- game production, separate from the Bucket "
                "System's physical/athletic score. Hitters don't have a pitch-quality grade to blend in the way "
                "pitcher Performance does, so this is the Results score in full.",
                class_="text-muted small",
            ))
            if discipline["Pitches Seen"] == 0:
                sections.append(ui.p("Not enough pitches with plate-discipline data yet for a Performance score.", class_="text-muted small"))
            else:
                hitter_results_line = dict(line, **{
                    "Chase %": discipline["Chase %"],
                    "Whiff %": discipline["Whiff %"],
                    "Zone Swing %": discipline["Zone Swing %"],
                })
                team_hitting_lines = profile_queries.team_hitting_lines(db, date_from=f["date_from"], date_to=f["date_to"])
                performance_value = None
                if len(team_hitting_lines) >= performance_score.MIN_BASELINE_PLAYERS:
                    results_baseline = performance_score.team_hitter_results_baseline(team_hitting_lines)
                    performance_value = performance_score.hitter_results_score(hitter_results_line, results_baseline)
                performance_bars = ui_helpers.render_percentile_bars([("Performance", performance_value)])
                if performance_bars is not None:
                    sections.append(performance_bars)
                else:
                    sections.append(ui.p("Not enough team baseline yet for a Performance score.", class_="text-muted small"))

            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Plate Discipline: BB %/K % + Zone discipline (Zone %/Swing %/
    # Chase %/Whiff %/SwStr %/1st-Pitch Swing %) + per-metric team-
    # percentile bars (Sept 2026, Ryker's reference: Baseball Savant's
    # percentile-rank rows) + Zone-Tier Discipline table.
    # -------------------------------------------------------------------
    @render.ui
    def hp_discipline_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "discipline":
            return None

        db = get_session()
        try:
            pid, pitches = _current_pitches(db)
            if pid is None or not pitches:
                return None
            f = _current_filters()
            line = compute_batting_line(pitches)

            sections = [ui.div(
                ui.p(ui.strong("Plate Discipline"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("hp_glossary_discipline", "Plate Discipline Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "BB %", "value": _fmt_pct(line["BB %"])},
                {"label": "K %", "value": _fmt_pct(line["K %"])},
                {"label": "BB/K", "value": _fmt(line["BB/K"], 2)},
            ]))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Plate Discipline (Zone)")))
            discipline = compute_hitter_discipline(pitches)
            if discipline["Pitches Seen"] == 0:
                sections.append(ui.p("No pitches seen yet.", class_="text-muted small"))
            else:
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Zone %", "value": _fmt_pct(discipline["Zone %"])},
                    {"label": "Swing %", "value": _fmt_pct(discipline["Swing %"])},
                    {"label": "Chase %", "value": _fmt_pct(discipline["Chase %"])},
                    {"label": "Whiff %", "value": _fmt_pct(discipline["Whiff %"])},
                    {"label": "SwStr %", "value": _fmt_pct(discipline["SwStr %"])},
                    {"label": "1st-Pitch Swing %", "value": _fmt_pct(discipline["First-Pitch Swing %"])},
                ]))
                sections.append(ui.p(
                    f"Zone Swing %: {_fmt_pct(discipline['Zone Swing %'])} · Zone Contact %: {_fmt_pct(discipline['Zone Contact %'])} · "
                    f"Chase Contact %: {_fmt_pct(discipline['Chase Contact %'])} · Pitches Seen: {discipline['Pitches Seen']} "
                    f"({discipline['Located Pitches']} with a recorded location)",
                    class_="text-muted small",
                ))

                # Per-metric team-percentile bars (Sept 2026, Ryker's
                # own reference: Baseball Savant's percentile-rank
                # rows). Reuses performance_score's own single-metric
                # z-score math -- performance_score._results_score
                # already blends N metrics into one grade by averaging
                # their z-scores; calling it with a ONE-metric baseline
                # dict is the exact same formula with N=1, so this is
                # not new math, just the existing Performance
                # composite's own per-metric building blocks shown one
                # at a time instead of averaged together.
                hitter_results_line = dict(line, **{
                    "Chase %": discipline["Chase %"],
                    "Whiff %": discipline["Whiff %"],
                    "Zone Swing %": discipline["Zone Swing %"],
                })
                team_hitting_lines = profile_queries.team_hitting_lines(db, date_from=f["date_from"], date_to=f["date_to"])
                metric_bars = []
                if len(team_hitting_lines) >= performance_score.MIN_BASELINE_PLAYERS:
                    results_baseline = performance_score.team_hitter_results_baseline(team_hitting_lines)
                    for metric_key, bar_label in DISCIPLINE_PERCENTILE_METRICS:
                        grade = performance_score._results_score(hitter_results_line, {metric_key: results_baseline[metric_key]})
                        metric_bars.append((bar_label, grade))

                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Team Percentile (this window)")))
                sections.append(ui.p(
                    "Each stat's own percentile against the rest of the team over this same date range -- same "
                    "grade/percentile scale as the Performance bar on Overview, one metric at a time instead of "
                    "blended together.",
                    class_="text-muted small",
                ))
                metric_percentile_bars = ui_helpers.render_percentile_bars(metric_bars) if metric_bars else None
                if metric_percentile_bars is not None:
                    sections.append(metric_percentile_bars)
                else:
                    sections.append(ui.p("Not enough team baseline yet for individual percentiles.", class_="text-muted small"))

            sections.append(ui.p(ui.strong("Zone-Tier Discipline")))
            sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
            sections.append(ui_helpers.render_dict_table(compute_zone_tier_discipline(pitches)))

            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Batted Ball: GB %/FB %/LD %/Pop Up %, Pull/Center/Oppo (or LF/CF/
    # RF for switch-hitters/unknown bats), Barrel %/Hard Contact %.
    # -------------------------------------------------------------------
    @render.ui
    def hp_batted_ball_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "batted_ball":
            return None

        db = get_session()
        try:
            pid, pitches = _current_pitches(db)
            if pid is None or not pitches:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None

            sections = [ui.div(
                ui.p(ui.strong("Batted-Ball Profile"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("hp_glossary_batted_ball", "Batted Ball Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]
            profile = compute_batted_ball_profile(pitches, bats=player.bats)
            if profile["Balls in Play"] == 0:
                sections.append(ui.p("No balls in play yet.", class_="text-muted small"))
            else:
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Ground Ball %", "value": _fmt_pct(profile["Ground Ball %"])},
                    {"label": "Fly Ball %", "value": _fmt_pct(profile["Fly Ball %"])},
                    {"label": "Line Drive %", "value": _fmt_pct(profile["Line Drive %"])},
                    {"label": "Pop Up %", "value": _fmt_pct(profile["Pop Up %"])},
                ]))
                if profile["Spray Mode"] == "Pull/Center/Oppo":
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Pull %", "value": _fmt_pct(profile["Pull %"])},
                        {"label": "Center %", "value": _fmt_pct(profile["Center %"])},
                        {"label": "Oppo %", "value": _fmt_pct(profile["Oppo %"])},
                    ]))
                else:
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Left Field %", "value": _fmt_pct(profile["Left Field %"])},
                        {"label": "Center %", "value": _fmt_pct(profile["Center %"])},
                        {"label": "Right Field %", "value": _fmt_pct(profile["Right Field %"])},
                    ]))
                    sections.append(ui.p("Batter's hand isn't on file (or switch-hitter), so this shows raw field side instead of Pull/Oppo.", class_="text-muted small"))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Barrel %", "value": _fmt_pct(profile["Barrel %"])},
                    {"label": "Hard Contact %", "value": _fmt_pct(profile["Hard Contact %"])},
                ]))
                sections.append(ui.p(f"Balls in Play: {profile['Balls in Play']} ({profile['Located']} with a recorded field location).", class_="text-muted small"))

            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Situational & Count Leverage: RISP/2-Strike/Leadoff AVG + QAB %,
    # and the Ahead/Even/Behind count-leverage split table.
    # -------------------------------------------------------------------
    @render.ui
    def hp_situational_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "situational":
            return None

        db = get_session()
        try:
            pid, pitches = _current_pitches(db)
            if pid is None or not pitches:
                return None
            line = compute_batting_line(pitches)

            sections = [ui.div(
                ui.p(ui.strong("Situational"), style="margin-bottom:0;"),
                ui_helpers.glossary_link("hp_glossary_situational", "Situational Glossary"),
                style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
            )]
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "RISP AVG", "value": _fmt(line["RISP AVG"])},
                {"label": "2-Strike AVG", "value": _fmt(line["2-Strike AVG"])},
                {"label": "Leadoff AVG", "value": _fmt(line["Leadoff AVG"])},
                {"label": "QAB %", "value": _fmt_pct(line["QAB %"])},
            ]))
            sections.append(ui.p(f"QAB: {line['QAB']} of {line['PA']} PA", class_="text-muted small"))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Count Leverage (Ahead / Even / Behind)")))
            sections.append(ui_helpers.render_dict_table([
                {"Count State": "Ahead", "PA": line["Ahead PA"], "AVG": _fmt(line["Ahead AVG"]), "OBP": _fmt(line["Ahead OBP"]), "SLG": _fmt(line["Ahead SLG"]), "wOBA*": _fmt(line["Ahead wOBA"])},
                {"Count State": "Even", "PA": line["Even PA"], "AVG": _fmt(line["Even AVG"]), "OBP": _fmt(line["Even OBP"]), "SLG": _fmt(line["Even SLG"]), "wOBA*": _fmt(line["Even wOBA"])},
                {"Count State": "Behind", "PA": line["Behind PA"], "AVG": _fmt(line["Behind AVG"]), "OBP": _fmt(line["Behind OBP"]), "SLG": _fmt(line["Behind SLG"]), "wOBA*": _fmt(line["Behind wOBA"])},
            ]))
            sections.append(ui.p(
                "Split by the count when the at-bat ended -- Ahead = more balls than strikes, Behind = more strikes than balls, Even = equal.",
                class_="text-muted small",
            ))

            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Contact Quality by Zone / Pitch Type -- same reused Hitter Tracking
    # zone-score math/heatmap builder Hitter Game Report already uses,
    # just scoped by this page's own filters instead of one game_id. Own
    # top-level output (own render.ui/render_plotly split), same reason
    # as hitter_game_report.py: a render_plotly output needs its own
    # registered function -- and, same as pitcher_profile.py's own
    # nested per-view outputs, each of the three functions below
    # independently re-checks input.hp_view() itself rather than
    # relying only on DOM nesting/visibility.
    # -------------------------------------------------------------------

    @reactive.effect
    @reactive.event(input.hp_glossary_overview)
    def _hp_show_glossary_overview():
        ui.modal_show(ui_helpers.glossary_modal("Overview Glossary", glossary_content.HITTING_OVERVIEW))

    @reactive.effect
    @reactive.event(input.hp_glossary_discipline)
    def _hp_show_glossary_discipline():
        ui.modal_show(ui_helpers.glossary_modal("Plate Discipline Glossary", glossary_content.HITTING_DISCIPLINE))

    @reactive.effect
    @reactive.event(input.hp_glossary_batted_ball)
    def _hp_show_glossary_batted_ball():
        ui.modal_show(ui_helpers.glossary_modal("Batted Ball Glossary", glossary_content.HITTING_BATTED_BALL))

    @reactive.effect
    @reactive.event(input.hp_glossary_situational)
    def _hp_show_glossary_situational():
        ui.modal_show(ui_helpers.glossary_modal("Situational Glossary", glossary_content.HITTING_SITUATIONAL))

    @reactive.effect
    @reactive.event(input.hp_glossary_contact_zone)
    def _hp_show_glossary_contact_zone():
        ui.modal_show(ui_helpers.glossary_modal("Contact Quality by Zone Glossary", glossary_content.HITTING_CONTACT_ZONE))

    @reactive.effect
    @reactive.event(input.hp_glossary_spray)
    def _hp_show_glossary_spray():
        ui.modal_show(ui_helpers.glossary_modal("Spray Chart Glossary", glossary_content.HITTING_SPRAY))

    # -------------------------------------------------------------------
    # Hot Zones (Oct 2026, Ryker: "add heat maps for hitters based on vs
    # rhp, lhp and just one altogether. want hitters to know where their
    # hot zone is"). AVG/SLG on balls in play, 13 zones, three panels
    # side by side. Math in analytics/hitter_hot_zones.py.
    # -------------------------------------------------------------------
    _ZONE_WORDS = {1: "up and to the left", 2: "up the middle", 3: "up and to the right",
                   4: "middle-left", 5: "middle-middle", 6: "middle-right",
                   7: "down and to the left", 8: "down the middle", 9: "down and to the right",
                   "OUL": "up and off the plate to the left", "OUR": "up and off the plate to the right",
                   "ODL": "down and off the plate to the left", "ODR": "down and off the plate to the right"}

    @render.ui
    def hp_hot_zones_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "hot_zones":
            return None
        return ui.div(
            ui.p(ui.strong("Hot Zones"), "  ", ui_helpers.how_to_link("hot_zones"), style="margin-bottom:0;"),
            ui.p(
                "Where you do damage when you put the ball in play -- every ball in play from your game at-bats "
                f"in this range, by where the pitch was (catcher's view). Red = hot, blue = cold. Zones with fewer "
                f"than {hitter_hot_zones.MIN_BIP} balls in play are gray. The 4 outer boxes are pitches off the plate.",
                class_="text-muted small",
            ),
            ui.input_radio_buttons("hp_hot_metric", None, choices={"avg": "AVG", "slg": "SLG"},
                                   selected="avg", inline=True),
            output_widget("hp_hot_zones_chart"),
            ui.output_ui("hp_hot_zones_notes"),
        )

    def _hot_panels(db):
        _pid, pitches = _current_pitches(db)
        if not pitches:
            return None
        return hitter_hot_zones.panels(db, pitches)

    @render_plotly
    def hp_hot_zones_chart():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "hot_zones":
            return None
        metric = input.hp_hot_metric() if "hp_hot_metric" in input else "avg"
        db = get_session()
        try:
            panels = _hot_panels(db)
            req(panels and panels[0][2]["bip"])
            return hot_zone_figure(panels, metric, stacked=app_state.is_phone())
        finally:
            db.close()

    @render.ui
    def hp_hot_zones_notes():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "hot_zones":
            return None
        metric = input.hp_hot_metric() if "hp_hot_metric" in input else "avg"
        db = get_session()
        try:
            panels = _hot_panels(db)
            if not panels or not panels[0][2]["bip"]:
                return ui.p("No located balls in play in this range yet (pitch locations come from Video Review).",
                            class_="text-muted small")
            lines = []
            for label, cells, t in panels:
                best = hitter_hot_zones.hottest(cells, metric)
                if best is None:
                    lines.append(ui.tags.li(f"{label}: not enough balls in play yet ({t['bip']})."))
                    continue
                z, c = best
                val = f"{c[metric]:.3f}".lstrip("0")
                lines.append(ui.tags.li(ui.strong(f"{label}: "),
                                        f"hottest {self_word(z)} -- {metric.upper()} {val} on {c['bip']} balls in play."))
            return ui.div(ui.tags.ul(*lines, style="margin-top:6px;"),
                          ui.p("Catcher's view: left on the chart = third-base side, right = first-base side.", class_="text-muted small"))
        finally:
            db.close()

    def self_word(z):
        return _ZONE_WORDS.get(z, str(z))

    # -------------------------------------------------------------------
    # Hitter insight views (Oct 2026, Ryker: "build 1-3. once those are
    # complete build 4-7"): Swing Decisions, How Pitchers Attack Me,
    # Results by Pitch Type, First Pitch & Two Strikes, Team Percentile
    # Ranks. One section output switches on the view; each chart is its
    # own render_plotly. Math in analytics/hitter_insights.py.
    # -------------------------------------------------------------------
    _INSIGHT_VIEWS = ("swing_decisions", "attack", "pitch_type", "fp_two", "ranks", "trends")
    _HAND_CHOICES = {"all": "All pitchers", "R": "vs RHP", "L": "vs LHP"}

    def _insight_gate(view):
        if not app_state.is_authenticated():
            return False
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return False
        req("hp_view" in input)
        return input.hp_view() == view

    def _hand_pitches(db, pitches, input_id):
        choice = input[input_id]() if input_id in input else "all"
        if choice not in ("R", "L"):
            return pitches
        hands = get_pitcher_hands(db, pitches)
        return [p for p in pitches if hands.get(p.game_pitch_id) == choice]

    def _fmt3(v):
        return f"{v:.3f}".replace("0.", ".", 1) if v is not None else "—"

    def _fmtp(v):
        return f"{v:.0f}%" if v is not None else "—"

    def hitter_insights_league(key):
        """'D2 avg .296 · MIAA .292' for stats with a league number (Oct 2026)."""
        from analytics import league_baselines as lb
        return lb.short(key, "hitting")

    def _rank_bars(ranks):
        rows = [ui.div(
            ui.div("", class_="gbo-pctbar-label"),
            ui.div("Rank on the team", class_="gbo-pctbar-header-pct"),
            ui.div("You", class_="gbo-pctbar-header-raw"),
            class_="gbo-pctbar-row gbo-pctbar-header",
        )]
        for key, label, _hib, desc in hitter_insights.PERCENTILE_METRICS:
            r = ranks.get(key)
            if r is None:
                continue
            v = r["value"]
            raw = "—" if v is None else (_fmt3(v) if key in ("AVG", "OBP", "SLG") else
                                         (f"{v:.1f}" if key == "Pitches/PA" else f"{v:.0f}%"))
            lg = hitter_insights_league(key)
            lab = ui.div(ui.div(label), ui.div(desc + (f" · {lg}" if lg else ""), class_="text-muted",
                                               style="font-size:.7rem;font-weight:400;"),
                         class_="gbo-pctbar-label")
            if r["pct"] is None:
                rows.append(ui.div(lab, ui.div("Not enough data yet", class_="gbo-pctbar-empty"),
                                   ui.div(raw, class_="gbo-pctbar-raw"), class_="gbo-pctbar-row"))
                continue
            pct = r["pct"]
            fill_hex, text_hex = ui_helpers.percentile_color(pct)
            rows.append(ui.div(
                lab,
                ui.div(
                    ui.div(class_="gbo-pctbar-fill", style=f"width:{max(pct, 3)}%; background:{fill_hex};"),
                    ui.div(str(pct), class_="gbo-pctbar-badge", style=f"left:{pct}%; background:{fill_hex}; color:{text_hex};"),
                    class_="gbo-pctbar-track",
                ),
                ui.div(raw, class_="gbo-pctbar-raw"),
                class_="gbo-pctbar-row",
            ))
        return ui.div(*rows, class_="gbo-pctbar-group")

    @render.ui
    def hp_insights_section():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        view = input.hp_view()
        if view not in _INSIGHT_VIEWS:
            return None
        if not _insight_gate(view):
            return None
        hand_select = lambda iid: ui.input_radio_buttons(iid, None, choices=_HAND_CHOICES, selected="all", inline=True)
        if view == "swing_decisions":
            return ui.div(
                ui.p(ui.strong("Swing Decisions"), "  ", ui_helpers.how_to_link("swing_decisions"), style="margin-bottom:0;"),
                ui.p("Every located pitch graded on the decision, not the result. Heart of the plate: swing. Way off the "
                     "plate: take. The edges are your call -- except with two strikes, when you protect. "
                     "Catcher's view (left = third-base side).", class_="text-muted small"),
                hand_select("hp_sd_hand"),
                ui.output_ui("hp_sd_summary"),
                ui.layout_columns(output_widget("hp_sd_chart"), ui.output_ui("hp_sd_table"), col_widths=[7, 5]),
            )
        if view == "attack":
            return ui.div(
                ui.p(ui.strong("How Pitchers Attack Me"), "  ", ui_helpers.how_to_link("attack"), style="margin-bottom:0;"),
                ui.p("What pitchers throw you in each count and where they put it -- so you can walk up with a plan. "
                     "Inside/away is from your side of the plate.", class_="text-muted small"),
                hand_select("hp_atk_hand"),
                ui.output_ui("hp_atk_notes"),
                # Oct 2026, Ryker: every count state, the share of pitches
                # thrown in each, and location habits by count.
                ui.p(ui.strong("Every count: how often you see it and what's thrown"), style="margin:14px 0 2px;"),
                ui.p("% of pitches = how much of what you see comes in that count. The pitch columns are the mix "
                     "within that count.", class_="text-muted small"),
                ui.output_ui("hp_atk_count_table"),
                ui.p(ui.strong("Pitch mix by count"), style="margin:14px 0 0;"),
                output_widget("hp_atk_mix"),
                ui.p(ui.strong("Where they throw it, by count"), style="margin:14px 0 2px;"),
                ui.p("From your side of the plate (in = inner third or inside, away = outer third or off the plate). "
                     "Pick a count and a pitch.", class_="text-muted small"),
                ui.layout_columns(
                    ui.input_select("hp_atk_count", "Count", choices={
                        "all": "All counts",
                        **{f"c:{c}": c for c in hitter_insights.COUNTS},
                        **{f"g:{k}": f"{', '.join(v)} ({k.lower()})" for k, v in hitter_insights.COUNT_GROUPS.items()},
                    }),
                    ui.input_select("hp_atk_fam", "Pitch", choices={"all": "All pitches", "Fastball": "Fastballs",
                                                                     "Breaking": "Breaking balls", "Offspeed": "Offspeed"}),
                    col_widths=[3, 3],
                ),
                ui.layout_columns(output_widget("hp_atk_grid"), ui.output_ui("hp_atk_tendencies"), col_widths=[5, 7]),
                ui.p(ui.strong("Where they throw it (all counts, by pitch)"), style="margin:14px 0 0;"),
                output_widget("hp_atk_loc"),
            )
        if view == "pitch_type":
            return ui.div(
                ui.p(ui.strong("Results by Pitch Type"), style="margin-bottom:0;"),
                ui.p("Fastballs (4-seam, 2-seam, sinker, cutter), breaking balls (slider, curveball) and offspeed "
                     "(changeup, splitter), split by pitcher hand. AVG/SLG count the at-bats that ended on that pitch.",
                     class_="text-muted small"),
                ui.output_ui("hp_pt_body"),
            )
        if view == "fp_two":
            return ui.div(
                ui.p(ui.strong("First Pitch & Two Strikes"), style="margin-bottom:0;"),
                ui.p("How you handle the first pitch, and how you battle once you have two strikes.", class_="text-muted small"),
                hand_select("hp_fp_hand"),
                ui.output_ui("hp_fp_body"),
            )
        if view == "trends":
            return ui.div(
                ui.p(ui.strong("Trends"), "  ", ui_helpers.how_to_link("trends"), style="margin-bottom:0;"),
                ui.p("Is he getting better? Dots = each game (or week), red line = rolling average (pools the "
                     "pitches, so one 1-PA game doesn't swing it). Dotted = his average over this range, gray dashed = "
                     "team, gold dashed = D2. Uses the date range above.", class_="text-muted small"),
                ui.layout_columns(
                    ui.input_radio_buttons("hp_trend_by", "Each point is", {"game": "A game", "week": "A week"},
                                           selected="game", inline=True),
                    ui.input_radio_buttons("hp_trend_roll", "Rolling line over", {"3": "3", "5": "5", "10": "10"},
                                           selected="5", inline=True),
                    col_widths=[6, 6],
                ),
                output_widget("hp_trend_metrics"),
            )
        return ui.div(
            ui.p(ui.strong("Team Percentile Ranks"), style="margin-bottom:0;"),
            ui.p(f"Where you rank among active hitters with {hitter_insights.MIN_PA_FOR_RANK}+ plate appearances in the "
                 "same date range and filters. 100 = best on the team, 0 = last. Red = better, blue = worse "
                 "(for stats where lower is better, like Chase % and K %, the rank is already flipped).",
                 class_="text-muted small"),
            ui.output_ui("hp_ranks_body"),
        )

    # ---- 1. Swing decisions ----
    def _sd_data(db):
        _pid, pitches = _current_pitches(db)
        if not pitches:
            return None
        return hitter_insights.swing_decisions(_hand_pitches(db, pitches, "hp_sd_hand"))

    @render.ui
    def hp_sd_summary():
        if not _insight_gate("swing_decisions"):
            return None
        db = get_session()
        try:
            sd = _sd_data(db)
            if not sd or not sd["graded"]:
                return ui.p("No located pitches yet (locations come from Video Review).", class_="text-muted small")
            c = sd["counts"]
            return ui_helpers.render_kpi_cards([
                {"label": "Swing decision %", "value": _fmtp(sd["score"]),
                 "delta": f"{c['Good swing'] + c['Good take']} good of {sd['scored']} graded"},
                {"label": "Chased clear balls", "value": _fmtp(sd["chase_pct"]), "delta": f"{c['Chase']} chases (way off the plate)",
                 "delta_positive": (sd["chase_pct"] or 0) < 25},
                {"label": "Took a hittable strike", "value": _fmtp(sd["heart_take_pct"]),
                 "delta": f"{c['Taken strike']} taken", "delta_positive": (sd["heart_take_pct"] or 0) < 20},
                {"label": "Borderline pitches", "value": str(c["Borderline"]), "delta": "your call -- not graded"},
            ])
        finally:
            db.close()

    @render_plotly
    def hp_sd_chart():
        req(_insight_gate("swing_decisions"))
        db = get_session()
        try:
            sd = _sd_data(db)
            req(sd and sd["graded"])
            return hic.swing_decision_chart(sd["graded"])
        finally:
            db.close()

    @render.ui
    def hp_sd_table():
        if not _insight_gate("swing_decisions"):
            return None
        db = get_session()
        try:
            sd = _sd_data(db)
            if not sd or not sd["graded"]:
                return None
            rows = [{"Zone": t["Zone"], "Pitches": t["Pitches"], "Swing %": _fmtp(t["Swing %"]),
                     "Whiff %": _fmtp(t["Whiff %"]), "Ideal": t["Ideal"]} for t in sd["tiers"]]
            return ui.div(
                ui_helpers.render_dict_table(rows),
                ui.p("Heart = middle of the zone. Shadow = the edges (just in or just off). Chase = a ball off the "
                     "plate. Waste = nowhere close. The dotted boxes on the chart are Heart and Shadow.",
                     class_="text-muted small", style="margin-top:6px;"),
            )
        finally:
            db.close()

    # ---- 2. How pitchers attack me ----
    def _atk_data(db):
        _pid, pitches = _current_pitches(db)
        if not pitches:
            return None
        choice = input.hp_atk_hand() if "hp_atk_hand" in input else "all"
        return hitter_insights.attack_profile(db, pitches, None if choice not in ("R", "L") else choice)

    @render.ui
    def hp_atk_notes():
        if not _insight_gate("attack"):
            return None
        db = get_session()
        try:
            prof = _atk_data(db)
            if not prof or not prof["n"]:
                return ui.p("No pitches seen in this range.", class_="text-muted small")
            s, h = prof["sides"], prof["heights"]
            cards = [
                {"label": "Pitches seen", "value": str(prof["n"]), "delta": f"{prof['located']} located"},
                {"label": "Inside / Middle / Away", "value": f"{_fmtp(s['In'])} / {_fmtp(s['Middle'])} / {_fmtp(s['Away'])}"},
                {"label": "Up / Middle / Down", "value": f"{_fmtp(h['Up'])} / {_fmtp(h['Middle'])} / {_fmtp(h['Down'])}"},
            ]
            lines = hitter_insights.attack_takeaways(prof)
            return ui.div(ui_helpers.render_kpi_cards(cards),
                          ui.tags.ul(*[ui.tags.li(l) for l in lines], style="margin-top:8px;") if lines else None)
        finally:
            db.close()

    def _atk_hand():
        choice = input.hp_atk_hand() if "hp_atk_hand" in input else "all"
        return None if choice not in ("R", "L") else choice

    @render.ui
    def hp_atk_count_table():
        if not _insight_gate("attack"):
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            ct = hitter_insights.count_table(db, pitches, _atk_hand())
            if not ct["rows"]:
                return ui.p("No pitches with a recorded count.", class_="text-muted small")
            types = ct["types"][:6]
            rows = []
            by_count = {r["Count"]: r for r in ct["rows"]}
            # Oct 2026, Ryker: every count always listed (3-2 "missing" was a
            # count this hitter hasn't been in yet) -- 0 seen shows as "—".
            for c in hitter_insights.COUNTS:
                r = by_count.get(c)
                if r is None:
                    rows.append({"Count": c, "Seen": 0, "% of pitches": "—", **{t: "—" for t in types}, "In zone": "—"})
                    continue
                row = {"Count": r["Count"], "Seen": r["Seen"], "% of pitches": _fmtp(r["% of pitches"])}
                for t in types:
                    row[t] = _fmtp(r["types"].get(t)) if r["types"].get(t) else "—"
                row["In zone"] = _fmtp(r["In zone %"])
                rows.append(row)
            return ui_helpers.render_dict_table(rows)
        finally:
            db.close()

    @render_plotly
    def hp_atk_mix():
        req(_insight_gate("attack"))
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            req(pitches)
            ct = hitter_insights.count_table(db, pitches, _atk_hand())
            by_count = {r["Count"]: r for r in ct["rows"]}
            req(by_count)
            mix = [{"Count": c, "Pitches": by_count[c]["Seen"], **by_count[c]["families"]} if c in by_count
                   else {"Count": c, "Pitches": 0} for c in hitter_insights.COUNTS]
            return hic.count_mix_chart(mix)
        finally:
            db.close()

    def _atk_grid_args():
        c = input.hp_atk_count() if "hp_atk_count" in input else "all"
        f = input.hp_atk_fam() if "hp_atk_fam" in input else "all"
        counts = None
        label = "All counts"
        if c.startswith("g:"):
            label = c[2:]
            counts = hitter_insights.COUNT_GROUPS[label]
        elif c.startswith("c:"):
            label = c[2:]
            counts = (label,)
        fam = None if f == "all" else f
        return counts, fam, label

    @render_plotly
    def hp_atk_grid():
        req(_insight_gate("attack"))
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            req(pitches)
            counts, fam, label = _atk_grid_args()
            g = hitter_insights.location_grid(db, pitches, counts, fam, _atk_hand())
            req(g["n"])
            fam_word = {"Fastball": "fastballs", "Breaking": "breaking balls", "Offspeed": "offspeed"}.get(fam, "all pitches")
            return hic.location_grid_figure(g, f"{label} · {fam_word} · {g['n']} located")
        finally:
            db.close()

    @render.ui
    def hp_atk_tendencies():
        if not _insight_gate("attack"):
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            counts, fam, label = _atk_grid_args()
            g = hitter_insights.location_grid(db, pitches, counts, fam, _atk_hand())
            lines = hitter_insights.count_tendencies(db, pitches, _atk_hand())
            groups = [l for l in lines if l["group"]]
            singles = [l for l in lines if not l["group"]]
            kids = []
            if g["n"] and g["n"] < hitter_insights.MIN_TENDENCY:
                kids.append(ui.p(f"Only {g['n']} located pitches for this pick -- read it loosely.", class_="text-muted small"))
            if groups:
                kids.append(ui.p(ui.strong("Clear habits by count type"), style="margin:0 0 2px;"))
                kids.append(ui.tags.ul(*[ui.tags.li(l["text"]) for l in groups]))
            if singles:
                kids.append(ui.p(ui.strong("Clear habits in specific counts"), style="margin:6px 0 2px;"))
                kids.append(ui.tags.ul(*[ui.tags.li(l["text"]) for l in singles]))
            if not groups and not singles:
                kids.append(ui.p(f"No clear location habit yet -- a pitch needs {hitter_insights.MIN_TENDENCY}+ located "
                                 f"pitches in a count and {hitter_insights.TENDENCY_PCT:.0f}%+ in one spot to show here.",
                                 class_="text-muted small"))
            return ui.div(*kids, style="font-size:.9rem;")
        finally:
            db.close()

    @render_plotly
    def hp_atk_loc():
        req(_insight_gate("attack"))
        db = get_session()
        try:
            prof = _atk_data(db)
            req(prof and prof["located"])
            return hic.attack_location_chart(prof["by_family_loc"])
        finally:
            db.close()

    # ---- 3. Results by pitch type ----
    @render.ui
    def hp_pt_body():
        if not _insight_gate("pitch_type"):
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return ui.p("No pitches seen in this range.", class_="text-muted small")
            res = hitter_insights.pitch_type_results(db, pitches)
            lines = hitter_insights.pitch_type_takeaways(res)
            tabs = []
            for split in ("All", "vs RHP", "vs LHP"):
                rows = [{"Pitch": r["Pitch"], "Seen": r["Seen"], "Swing %": _fmtp(r["Swing %"]),
                         "Whiff %": _fmtp(r["Whiff %"]), "Chase %": _fmtp(r["Chase %"]), "AB": r["AB"],
                         "AVG": _fmt3(r["AVG"]), "SLG": _fmt3(r["SLG"]), "Hard contact %": _fmtp(r["Hard contact %"]),
                         "K": r["K"]} for r in res[split]]
                tabs.append(ui.nav_panel(split, ui_helpers.render_dict_table(rows)))
            return ui.div(
                ui.tags.ul(*[ui.tags.li(l) for l in lines]) if lines else
                ui.p("Not enough pitches yet to call out a strength or weakness (15+ of a type per hand).",
                     class_="text-muted small"),
                ui.navset_tab(*tabs),
                ui.p("Hard contact % = barreled or solid contact per ball in play. Chase % = swings at pitches out of "
                     "the zone.", class_="text-muted small", style="margin-top:6px;"),
            )
        finally:
            db.close()

    # ---- 4. First pitch & two strikes ----
    @render.ui
    def hp_fp_body():
        if not _insight_gate("fp_two"):
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return ui.p("No pitches seen in this range.", class_="text-muted small")
            d = hitter_insights.first_pitch_two_strike(_hand_pitches(db, pitches, "hp_fp_hand"))
            f, t = d["first"], d["two"]
            a1, a0 = f["After 0-1"], f["After 1-0"]
            first_cards = ui_helpers.render_kpi_cards([
                {"label": "First-pitch swing %", "value": _fmtp(f["Swing %"]), "delta": f"{f['PAs']} PAs"},
                {"label": "First pitch was a strike", "value": _fmtp(f["Strike seen %"])},
                {"label": "Took strike one", "value": _fmtp(f["Took a strike %"])},
                {"label": "First pitch put in play", "value": f"{_fmt3(f['AVG in play'])} AVG",
                 "delta": f"{f['In play']} times · {_fmt3(f['SLG in play'])} SLG"},
            ])
            split_rows = [
                {"After": "Strike one (0-1)", "PA": a1["PA"], "AVG": _fmt3(a1["AVG"]), "OBP": _fmt3(a1["OBP"]),
                 "SLG": _fmt3(a1["SLG"]), "K %": _fmtp(a1["K%"])},
                {"After": "Ball one (1-0)", "PA": a0["PA"], "AVG": _fmt3(a0["AVG"]), "OBP": _fmt3(a0["OBP"]),
                 "SLG": _fmt3(a0["SLG"]), "K %": _fmtp(a0["K%"])},
            ]
            two_cards = ui_helpers.render_kpi_cards([
                {"label": "2-strike PAs", "value": str(t["PAs"]), "delta": f"{_fmt3(t['AVG'])} AVG · {_fmt3(t['SLG'])} SLG"},
                {"label": "Strikeout %", "value": _fmtp(t["K %"]), "delta": f"{t['Looking Ks']} looking",
                 "delta_positive": (t["K %"] or 0) < 40},
                {"label": "2-strike chase %", "value": _fmtp(t["Chase %"]), "delta_positive": (t["Chase %"] or 0) < 30,
                 "delta": "swings off the plate"},
                {"label": "Foul-offs per PA", "value": f"{t['Foul-offs per PA']}" if t["Foul-offs per PA"] is not None else "—",
                 "delta": f"{t['Pitches per PA']} pitches per PA" if t["Pitches per PA"] is not None else None},
            ])
            return ui.div(
                ui.p(ui.strong("First pitch"), style="margin:8px 0 4px;"), first_cards,
                ui.p(ui.strong("How the at-bat goes after pitch one"), style="margin:12px 0 4px;"),
                ui_helpers.render_dict_table(split_rows),
                ui.p(ui.strong("Two strikes"), style="margin:16px 0 4px;"), two_cards,
                ui.p(f"With two strikes: {_fmtp(t['Contact %'])} contact on swings, {_fmtp(t['Whiff %'])} whiffs.",
                     class_="text-muted small", style="margin-top:6px;"),
            )
        finally:
            db.close()

    # ---- Trends (Oct 2026) ----
    @render_plotly
    def hp_trend_metrics():
        req(_insight_gate("trends"))
        f = _current_filters()
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            req(pitches)
            team = trends.team_pitches_in_range(db, f["date_from"], f["date_to"], pitching=False)
            by = input.hp_trend_by() if "hp_trend_by" in input else "game"
            roll = int(input.hp_trend_roll()) if "hp_trend_roll" in input else 5
            return trend_charts.metrics_figure(trends.build(db, pitches, team, False, by, roll))
        finally:
            db.close()

    # ---- 7. Team percentile ranks ----
    @render.ui
    def hp_ranks_body():
        if not _insight_gate("ranks"):
            return None
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            f = _current_filters()
            team = profile_queries.get_team_hitting_pitches(db, f["date_from"], f["date_to"], f["pitch_type"], f["game_scope"])
            _pid, mine = _current_pitches(db)
            team[pid] = mine or []
            ranks = hitter_insights.team_percentiles(team, pid)
            if not ranks:
                return ui.p("No at-bats in this range yet.", class_="text-muted small")
            n = max((r["n_players"] for r in ranks.values()), default=0)
            return ui.div(ui.p(f"Compared against {n} hitters.", class_="text-muted small"), _rank_bars(ranks))
        finally:
            db.close()

    @render.ui
    def hp_contact_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "contact_zone":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            located = [p for p in pitches if p.pitch_zone is not None and p.contact_quality in CONTACT_QUALITY_SCORE]
            if not located:
                return None
            return ui.div(
                ui.div(
                    ui.p(ui.strong("Contact Quality by Zone / Pitch Type"), style="margin-bottom:0;"),
                    ui_helpers.glossary_link("hp_glossary_contact_zone", "Contact Zone Glossary"),
                    style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
                ),
                ui.p(
                    "From this hitter's actual game at-bats in the selected range (located pitches only -- needs both "
                    "a recorded zone and a contact-quality call). Same 0-3 Barrel/Solid/Weak/Miss scale Hitter "
                    "Tracking uses.",
                    class_="text-muted small",
                ),
                output_widget("hp_contact_chart"),
                ui.output_ui("hp_contact_by_type_table"),
            )
        finally:
            db.close()

    @render_plotly
    def hp_contact_chart():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "contact_zone":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            scores, counts = _compute_zone_scores(pitches)
            if not scores:
                return None
            return _build_zone_heatmap_figure("Contact Quality by Zone", scores, counts)
        finally:
            db.close()

    @render.ui
    def hp_contact_by_type_table():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "contact_zone":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            by_type = {}
            for p in pitches:
                if p.contact_quality not in CONTACT_QUALITY_SCORE:
                    continue
                label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
                by_type.setdefault(label, []).append(CONTACT_QUALITY_SCORE[p.contact_quality])
            if not by_type:
                return None
            rows = [
                {"Pitch Type": label, "Avg Score": f"{sum(vals) / len(vals):.2f}", "Swings": len(vals)}
                for label, vals in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
            ]
            return ui_helpers.render_dict_table(rows)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Spray Chart / Infield Slice Chart -- Sept 2026, Ryker: "i want a
    # hit spray chart as well as an infield slice chart", referencing
    # Baseball Savant's own player-page Visuals for the concrete look
    # (both AskUserQuestion rounds answered with the recommended
    # defaults: a new "Spray Chart" tab here rather than folding it
    # into an existing view, and hits-only on the spray chart, matching
    # Savant's own default BASE HITS view over also plotting outs).
    # Two side-by-side charts from visualizations/spray_chart.py, same
    # Savant two-panel layout. Own top-level output/render_plotly split
    # for the same reason as Contact Quality by Zone above -- each of
    # the three functions below independently re-checks input.hp_view()
    # itself rather than relying only on DOM nesting/visibility.
    # -------------------------------------------------------------------
    @render.ui
    def hp_spray_chart_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("hp_view" in input)
        if input.hp_view() != "spray_chart":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            # Gate on "any located ball in play at all" -- same
            # discipline hp_contact_section's own `located` check
            # follows: if there's nothing either chart could possibly
            # show, don't render an empty two-panel shell.
            located_in_play = [
                p for p in pitches
                if p.pitch_outcome == "In Play" and p.batted_ball_x is not None and p.batted_ball_y is not None
            ]
            if not located_in_play:
                return None
            return ui.div(
                ui.div(
                    ui.p(ui.strong("Spray Chart / Infield Slice Chart"), style="margin-bottom:0;"),
                    ui_helpers.glossary_link("hp_glossary_spray", "Spray Chart Glossary"),
                    style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
                ),
                ui.p(
                    "Spray Chart: every base hit (1B/2B/3B/HR) at its recorded field location, colored by hit "
                    "type -- base hits only, same as Baseball Savant's own default view. Infield Slice Chart: the "
                    "share of all batted balls within 200 ft of home plate landing in each of five field wedges "
                    "-- Savant's own weak/short-contact definition.",
                    class_="text-muted small",
                ),
                ui.layout_columns(
                    output_widget("hp_spray_chart_widget"),
                    output_widget("hp_infield_slice_widget"),
                    col_widths=[6, 6],
                ),
            )
        finally:
            db.close()

    @render_plotly
    def hp_spray_chart_widget():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "spray_chart":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            return hit_spray_chart(pitches, title="Spray Chart (Base Hits)")
        finally:
            db.close()

    @render_plotly
    def hp_infield_slice_widget():
        if not app_state.is_authenticated():
            return None
        req("hp_view" in input)
        if input.hp_view() != "spray_chart":
            return None
        db = get_session()
        try:
            _pid, pitches = _current_pitches(db)
            if not pitches:
                return None
            return infield_slice_chart(pitches, title="Infield Slice Chart")
        finally:
            db.close()
