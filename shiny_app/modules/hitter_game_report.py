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
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch, User
from game_stats import get_batting_pitches, compute_batting_line, compute_batted_ball_profile
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline
# Reusing Hitter Tracking's own zone-score math/heatmap builder and its
# CONTACT_QUALITY_SCORE/ZONE_LABELS constants -- rather than a second,
# parallel implementation -- so a batter's "how well do I make contact
# by zone" reads the same whether it comes from a simulated Hitter
# Tracking session or, as of this section, real in-game at-bats.
# _compute_zone_scores/_build_zone_heatmap_figure are generic over any
# object exposing .pitch_zone/.contact_quality, which GamePitch does too.
from modules.hitter_tracking import _compute_zone_scores, _build_zone_heatmap_figure, CONTACT_QUALITY_SCORE

import ui_helpers
import format_helpers
from format_helpers import (
    format_pct as _fmt_pct,
    opponent_display_name as _opponent_display_name,
    game_label as _game_label,
)


def _fmt(value, decimals=3):
    return format_helpers.format_num(value, decimals)


@module.ui
def hitter_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Hitter Game Report"),
        ui.output_ui("game_picker"),
        ui.output_ui("batter_picker"),
        ui.output_ui("report_body"),
        ui.output_ui("contact_by_zone_section"),
        ui_helpers.page_footer(),
    )


@module.server
def hitter_game_report_server(input, output, session, app_state):
    # "Player" added Sept 2026 (Ryker: players should be able to see game
    # reports for themselves) -- same self-scoping pattern as
    # pitcher_game_report.py/hitter_profile.py: a Player sees no game/
    # batter pickers pointed at the whole roster, just their own outings;
    # every other gated section below is unchanged, since they all just
    # read game_select/batter_select, already restricted below to this
    # player's own data. Nav only links this page for a non-pitcher-
    # flagged Player (see nav.py's is_pitcher_player) -- the is_pitcher
    # check here is defense-in-depth, not the only gate.
    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator", "Player")

    def _my_hitter(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        player = db.query(Player).filter(Player.player_id == me.player_id).first()
        return player if (player is not None and not player.is_pitcher) else None

    @render.ui
    def game_picker():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role not in ALLOWED_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            if role == "Player":
                me = _my_hitter(db)
                if me is None:
                    return ui.p("You don't have access to this page.", class_="text-danger")
                # Union our_player_id (normal games, batting for our
                # own team) with opponent_our_player_id (intrasquad games
                # only -- this player batted while lined up as the "other
                # squad," still one of our own roster) so intrasquad games
                # aren't dropped from a player's own game list. Mirrors
                # pitcher_game_report.py's pitcher_picker() union.
                own_game_ids_batting = {
                    gid for (gid,) in db.query(GamePitch.game_id)
                    .filter(GamePitch.our_player_id == me.player_id, GamePitch.is_our_team_batting.is_(True))
                    .distinct().all()
                }
                own_game_ids_intrasquad = {
                    gid for (gid,) in db.query(GamePitch.game_id)
                    .filter(GamePitch.opponent_our_player_id == me.player_id, GamePitch.is_our_team_batting.is_(False))
                    .distinct().all()
                }
                own_game_ids = own_game_ids_batting | own_game_ids_intrasquad
                if not own_game_ids:
                    return ui_helpers.empty_state("No games recorded for you as a batter yet.")
                games = (
                    db.query(Game).options(joinedload(Game.opponent_team))
                    .filter(Game.game_id.in_(own_game_ids))
                    .order_by(Game.game_date.desc()).all()
                )
            else:
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
            if app_state.role_name() == "Player":
                me = _my_hitter(db)
                if me is None:
                    return ui.p("You don't have access to this page.", class_="text-danger")
                # No picker needed -- game_picker above already restricted
                # game_select to games this player batted in, so there's
                # exactly one batter to show: themselves. Still a real
                # input_select so downstream sections keep reading
                # input.batter_select() unchanged.
                return ui.input_select("batter_select", "Batter", choices={str(me.player_id): f"{me.first_name} {me.last_name}"})

            # Union our_player_id (our team's own batters) with
            # opponent_our_player_id (intrasquad games only -- the "other
            # squad" batters, who are also our own roster) so intrasquad
            # games show batters from both squads, not just one. Mirrors
            # pitcher_game_report.py's pitcher_picker() union.
            our_batter_ids = {
                pid for (pid,) in db.query(GamePitch.our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(True))
                .distinct().all() if pid is not None
            }
            other_squad_batter_ids = {
                pid for (pid,) in db.query(GamePitch.opponent_our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(False))
                .distinct().all() if pid is not None
            }
            batter_ids = list(our_batter_ids | other_squad_batter_ids)
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

    # -------------------------------------------------------------------
    # Contact Quality by Zone / Pitch Type -- simple first version (see
    # task discussion): sourced from real game at-bats only via the same
    # get_batting_pitches() call as report_body above, not from Hitter
    # Tracking's simulated sessions. A separate top-level section (its
    # own output_ui) rather than folded into report_body, since a
    # render_plotly output needs its own registered function -- the
    # nested-output_ui-inside-a-render.ui technique this whole migration
    # already relies on elsewhere (see game_tracking.py's module
    # docstring).
    # -------------------------------------------------------------------

    def _selected_batter_pitches(db):
        if "game_select" not in input or "batter_select" not in input:
            return None
        game_id_raw, batter_id_raw = input.game_select(), input.batter_select()
        if not game_id_raw or not batter_id_raw:
            return None
        return get_batting_pitches(db, int(batter_id_raw), game_id=int(game_id_raw))

    @render.ui
    def contact_by_zone_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("batter_select" in input)
        db = get_session()
        try:
            pitches = _selected_batter_pitches(db)
            if not pitches:
                return None
            located = [p for p in pitches if p.pitch_zone is not None and p.contact_quality in CONTACT_QUALITY_SCORE]
            if not located:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Contact Quality by Zone / Pitch Type")),
                ui.p(
                    "From this batter's actual game at-bats (located pitches only -- needs both a recorded zone and "
                    "a contact-quality call). Same 0-3 Barrel/Solid/Weak/Miss scale Hitter Tracking uses.",
                    class_="text-muted small",
                ),
                output_widget("contact_by_zone_chart"),
                ui.output_ui("contact_by_pitch_type_table"),
            )
        finally:
            db.close()

    @render_plotly
    def contact_by_zone_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_batter_pitches(db)
            if not pitches:
                return None
            scores, counts = _compute_zone_scores(pitches)
            if not scores:
                return None
            return _build_zone_heatmap_figure("Contact Quality by Zone (this game)", scores, counts)
        finally:
            db.close()

    @render.ui
    def contact_by_pitch_type_table():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_batter_pitches(db)
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
