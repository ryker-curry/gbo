"""
GBO -- Hitter Game Report module.

Direct port of pages/hitter_game_report.py -- batting-side counterpart to
pitcher_game_report.py: single-game slash line + situational splits,
zone plate discipline, zone-tier discipline, and batted-ball profile,
all from the exact same game_stats.py/plate_discipline.py functions
Analytics/My Stats use, just scoped to one game_id instead of
season/all-time aggregate.

Same three-block ordering-hazard-safe chain as pitcher_game_report.py:
Game picker -> Batter picker (req("game_select" in input)) -> report
body (req on both).

Known gaps/assumptions carried over unchanged from the original (not
silently dropped, still worth surfacing to the user in the UI):
  - Pull/Center/Oppo uses the standard 30/30/30-degree spray-angle
    split -- documented convention, not Ryker-confirmed to the inch.
  - Switch-hitters (bats == 'S') and batters with no bats on file get
    side-neutral Left/Center/Right Field labels instead of Pull/Oppo.
  - Barrel %/Hard-Contact % use the coach's own live contact_quality
    call, not a measured Statcast Barrel (GBO has no exit-velo radar).
"""

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch
from game_stats import get_batting_pitches, compute_batting_line, compute_batted_ball_profile
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline

import ui_helpers


def _fmt_pct(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt(value, decimals=3):
    return f"{value:.{decimals}f}" if value is not None else "—"


def _opponent_display_name(g):
    if g.opponent_team:
        return g.opponent_team.team_name
    return g.opponent_name or "Unknown opponent"


def _game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
    return f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status})"


@module.ui
def hitter_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Hitter Game Report"),
        ui.output_ui("game_picker"),
        ui.output_ui("batter_picker"),
        ui.output_ui("report_body"),
        ui_helpers.page_footer(),
    )


@module.server
def hitter_game_report_server(input, output, session, app_state):
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
    def batter_picker():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        selected_game_id = int(input.game_select())

        db = get_session()
        try:
            batter_ids = [
                pid for (pid,) in db.query(GamePitch.our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(True))
                .distinct().all()
                if pid is not None
            ]
            if not batter_ids:
                return ui_helpers.empty_state("No pitches recorded for any of our batters in this game yet.")
            batters = db.query(Player).filter(Player.player_id.in_(batter_ids)).order_by(Player.last_name, Player.first_name).all()
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in batters}
            return ui.input_select("batter_select", "Batter", choices=choices)
        finally:
            db.close()

    @render.ui
    def report_body():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("batter_select" in input)
        selected_game_id = int(input.game_select())
        selected_batter_id = int(input.batter_select())

        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == selected_game_id).first()
            batter = db.query(Player).filter(Player.player_id == selected_batter_id).first()
            if game is None or batter is None:
                return None

            pitches = get_batting_pitches(db, selected_batter_id, game_id=selected_game_id)
            if not pitches:
                return ui_helpers.empty_state("No pitches for this batter in this game.")

            line = compute_batting_line(pitches)
            sections = [ui.h5(f"{batter.first_name} {batter.last_name} — {_game_label(game)}", class_="gbo-section-title")]

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
                {"label": "ISO", "value": _fmt(line["ISO"])},
                {"label": "wOBA*", "value": _fmt(line["wOBA"])},
            ]))
            sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.", class_="text-muted small"))

            sections.append(ui.p(ui.strong("Plate Discipline")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "BB %", "value": _fmt_pct(line["BB %"])},
                {"label": "K %", "value": _fmt_pct(line["K %"])},
                {"label": "BB/K", "value": _fmt(line["BB/K"], 2)},
            ]))

            sections.append(ui.p(ui.strong("Situational")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "RISP AVG", "value": _fmt(line["RISP AVG"])},
                {"label": "2-Strike AVG", "value": _fmt(line["2-Strike AVG"])},
                {"label": "Leadoff AVG", "value": _fmt(line["Leadoff AVG"])},
            ]))
            sections.append(ui.p(
                f"RISP: {line['RISP PA']} PA ({line['RISP AB']} AB) · 2-Strike: {line['2-Strike PA']} PA "
                f"({_fmt_pct(line['2-Strike K %'])} ended in a K) · Leadoff: {line['Leadoff PA']} PA",
                class_="text-muted small",
            ))

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
            tier_rows = compute_zone_tier_discipline(pitches)
            sections.append(ui_helpers.render_dict_table(tier_rows))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Batted-Ball Profile")))
            profile = compute_batted_ball_profile(pitches, bats=batter.bats)
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
