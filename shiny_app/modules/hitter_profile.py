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
and Contact Quality by Zone (the existing Hitter Tracking zone-score
heat map). Each gated section function checks input.hp_view() itself
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
from game_stats import compute_batting_line, compute_batted_ball_profile, ops_plus
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline
from analytics import performance_score, profile_queries
from modules.hitter_tracking import _compute_zone_scores, _build_zone_heatmap_figure, CONTACT_QUALITY_SCORE

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
        ui_helpers.page_header("Hitter Profile"),
        ui.output_ui("hp_player_picker"),
        ui.output_ui("hp_filters"),
        # Sept 2026, Ryker: a "View" dropdown instead of every section
        # rendering at once and scrolling forever -- same convention
        # pitcher_profile.py already established. Each of these five
        # stays statically listed here (Shiny needs a placeholder in
        # the DOM for each output id) -- the gate inside each render.ui
        # function is what actually controls which one does anything.
        ui.output_ui("hp_view_picker"),
        ui.output_ui("hp_overview_section"),
        ui.output_ui("hp_discipline_section"),
        ui.output_ui("hp_batted_ball_section"),
        ui.output_ui("hp_situational_section"),
        ui.output_ui("hp_contact_section"),
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
                        "contact_zone": "Contact Quality by Zone",
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
            season_ids = {p.game.season_id for p in pitches if p.game is not None and p.game.season_id is not None}
            season_baseline = profile_queries.team_batting_line_for_seasons(db, season_ids)
            player_ops_plus = ops_plus(
                line["OBP"], line["SLG"],
                season_baseline["OBP"] if season_baseline else None,
                season_baseline["SLG"] if season_baseline else None,
            )
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
                "OPS+ is against this team's own season average (100 = team average) -- see the glossary." if season_baseline else
                "*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact. "
                "OPS+ isn't shown -- no team baseline yet for this window's season(s).",
                class_="text-muted small",
            ))

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
