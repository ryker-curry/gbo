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
from models import Player, Game, GamePitch, User, OpponentPlayer
from game_stats import (
    get_batting_pitches, compute_batting_line, compute_batted_ball_profile,
    _group_into_plate_appearances, ops_plus, get_batter_hands,
)
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline
from analytics import profile_queries
from visualizations.hitter_pitch_chart import at_bat_pitch_locations_chart
# Reusing Hitter Tracking's own zone-score math/heatmap builder and its
# CONTACT_QUALITY_SCORE/ZONE_LABELS constants -- rather than a second,
# parallel implementation -- so a batter's "how well do I make contact
# by zone" reads the same whether it comes from a simulated Hitter
# Tracking session or, as of this section, real in-game at-bats.
# _compute_zone_scores/_build_zone_heatmap_figure are generic over any
# object exposing .pitch_zone/.contact_quality, which GamePitch does too.
from modules.hitter_tracking import _compute_zone_scores, _build_zone_heatmap_figure, CONTACT_QUALITY_SCORE

import strike_zone
import ui_helpers
from analytics import league_baselines
import format_helpers
import chart_helpers
import glossary_content
from format_helpers import (
    format_pct as _fmt_pct,
    opponent_display_name as _opponent_display_name,
    game_label as _game_label,
)


VIEWS = {"overview": "Overview", "approach": "Approach", "batted": "Batted Balls", "at_bats": "At-Bat by At-Bat"}


def _fmt(value, decimals=3):
    return format_helpers.format_num(value, decimals)


def location_words(x, z, batter_hand=None):
    """Plain description of where a pitch crossed, from the hitter's point
    of view: "In zone -- up and in", "Ball -- down and away". Catcher's
    view: a right-handed batter stands on the 3B (negative x) side, so
    inside = negative x for him and positive x for a lefty. Unknown hand
    (switch-hitter not resolved) says 3B side / 1B side instead."""
    if x is None or z is None:
        return "Not located"
    x, z = float(x), float(z)
    third = (strike_zone.ZONE_TOP - strike_zone.ZONE_BOTTOM) / 3
    if z > strike_zone.ZONE_TOP - third:
        height = "up"
    elif z < strike_zone.ZONE_BOTTOM + third:
        height = "down"
    else:
        height = "middle"
    edge = strike_zone.ZONE_HALF_WIDTH / 3
    if abs(x) <= edge:
        side = None
    elif batter_hand in ("R", "L"):
        inside = (x < 0) if batter_hand == "R" else (x > 0)
        side = "in" if inside else "away"
    else:
        side = "3B side" if x < 0 else "1B side"
    if side is None:
        where = "middle-middle" if height == "middle" else height
    elif height == "middle":
        where = side
    else:
        where = f"{height} and {side}"
    return f"{'In zone' if strike_zone.is_in_zone(x, z) else 'Ball'} -- {where}"


def _pitcher_of(db, p):
    """(name, hand) of whoever threw this pitch to our batter."""
    if p.opponent_our_player_id is not None:
        pl = db.query(Player).filter(Player.player_id == p.opponent_our_player_id).first()
        if pl is not None:
            return f"{pl.first_name} {pl.last_name}", pl.throws
    if p.opponent_player_id is not None:
        op = db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id == p.opponent_player_id).first()
        if op is not None:
            return op.player_name, (op.throws if op.throws in ("R", "L") else p.opponent_hand)
    return None, p.opponent_hand


def _vs(name, hand):
    hp = f"{hand}HP" if hand in ("R", "L") else None
    if name and hp:
        return f"vs {name} ({hp})"
    return f"vs {name}" if name else (f"vs {hp}" if hp else "")


@module.ui
def hitter_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Hitter Game Report", actions=ui_helpers.glossary_link("hgr_glossary", "Stats Glossary")),
        ui.output_ui("game_picker"),
        ui.output_ui("batter_picker"),
        ui.input_select("hgr_view", "View", choices=VIEWS),
        ui.output_ui("report_body"),
        # Oct 2026, Ryker: "go look at each individual at bat and pitch with
        # pitch type, location, as well as pitch result" -- replaces the old
        # all-at-bats chart grid.
        ui.output_ui("at_bat_section"),
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

    def _view():
        return input.hgr_view() if "hgr_view" in input else "overview"

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
            # Oct 2026: OPS+ (and the other "+" stats below) vs the 2026 D2 average.
            player_ops_plus = ops_plus(line["OBP"], line["SLG"])
            plus = league_baselines.hitting_plus(line)
            header = ui.h5(f"{batter.first_name} {batter.last_name} — {_game_label(game)}", class_="gbo-section-title")
            # Oct 2026, Ryker: View dropdown like Pitcher Game Report --
            # each block below lands in its view's list; only the picked
            # view is shown.
            groups = {"overview": [], "approach": [], "batted": []}
            sections = groups["overview"]

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

            sections = groups["approach"]
            sections.append(ui.p(ui.strong("Plate Discipline")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "BB %", "value": _fmt_pct(line["BB %"])},
                {"label": "K %", "value": _fmt_pct(line["K %"])},
                {"label": "BB/K", "value": _fmt(line["BB/K"], 2)},
            ]))

            sections = groups["overview"]
            sections.append(ui.p(ui.strong("Situational")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "RISP AVG", "value": _fmt(line["RISP AVG"])},
                {"label": "2-Strike AVG", "value": _fmt(line["2-Strike AVG"])},
                {"label": "Leadoff AVG", "value": _fmt(line["Leadoff AVG"])},
                {"label": "QAB %", "value": _fmt_pct(line["QAB %"])},
            ]))
            sections.append(ui.p(
                f"RISP: {line['RISP PA']} PA ({line['RISP AB']} AB) · 2-Strike: {line['2-Strike PA']} PA "
                f"({_fmt_pct(line['2-Strike K %'])} ended in a K) · Leadoff: {line['Leadoff PA']} PA · "
                f"QAB: {line['QAB']} of {line['PA']} PA",
                class_="text-muted small",
            ))

            sections = groups["approach"]
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

            sections.append(ui.p(ui.strong("Zone-Tier Discipline")))
            sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
            tier_rows = compute_zone_tier_discipline(pitches)
            sections.append(ui_helpers.render_dict_table(tier_rows))

            sections = groups["batted"]
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

            return ui.div(header, *groups.get(_view(), []))
        finally:
            db.close()

    # -------------------------------------------------------------------
    # At-Bat by At-Bat (Oct 2026, Ryker) -- the hitting twin of Pitcher
    # Game Report's Pitch-by-Pitch: pick an at-bat -> its zone chart and
    # every pitch (count, type, velo when Rapsodo has it, location,
    # result) -> pick a pitch for its own picture and details.
    # -------------------------------------------------------------------

    def _plate_appearances(db):
        pitches = _selected_batter_pitches(db)
        if not pitches:
            return []
        return _group_into_plate_appearances(sorted(pitches, key=lambda p: p.pitch_sequence))

    @render.ui
    def at_bat_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        if _view() != "at_bats":
            return None
        req("game_select" in input)
        req("batter_select" in input)
        db = get_session()
        try:
            pas = _plate_appearances(db)
            if not pas:
                return None
            choices = {}
            for i, pa in enumerate(pas, start=1):
                name, hand = _pitcher_of(db, pa[0])
                result = pa[-1].ab_outcome if pa[-1].ends_plate_appearance and pa[-1].ab_outcome else "In progress"
                choices[str(i)] = f"At-bat {i} -- Inning {pa[0].inning} {_vs(name, hand)} -- {result}"
            return ui.div(
                ui.p(ui.strong("At-Bat by At-Bat")),
                ui.p("Pick an at-bat to see every pitch: count, pitch type, location and result. Pick a pitch "
                     "below the table for its own picture.", class_="text-muted small"),
                ui.input_select("ab_select", "At-bat", choices=choices),
                ui.output_ui("at_bat_detail"),
            )
        finally:
            db.close()

    @render.ui
    def at_bat_detail():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("ab_select" in input)
        db = get_session()
        try:
            pas = _plate_appearances(db)
            k = int(input.ab_select())
            if not (1 <= k <= len(pas)):
                return None
            pa = pas[k - 1]
            hands = get_batter_hands(db, pa)
            rap = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pa])
            rows, pitch_choices = [], {}
            for p in pa:
                label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
                r = rap.get(p.game_pitch_id)
                outcome = p.pitch_outcome or "--"
                if p.ends_plate_appearance and p.ab_outcome:
                    outcome += f" ({p.ab_outcome})"
                rows.append({
                    "#": p.pa_pitch_number,
                    "Count": f"{p.balls_before}-{p.strikes_before}" if p.balls_before is not None else "--",
                    "Pitch": label,
                    "Velo": f"{float(r.velocity):.1f}" if r is not None and r.velocity is not None else "--",
                    "Location": location_words(p.actual_plate_x, p.actual_plate_z, hands.get(p.game_pitch_id)),
                    "Result": outcome,
                })
                pitch_choices[str(p.game_pitch_id)] = f"Pitch {p.pa_pitch_number} -- {label} -- {p.pitch_outcome or 'no result'}"
            if not rap:                       # no Rapsodo on any pitch (external opponent): drop the column
                for row in rows:
                    row.pop("Velo")
            hand = hands.get(pa[0].game_pitch_id)
            located = [p for p in pa if p.actual_plate_x is not None and p.actual_plate_z is not None]
            result = pa[-1].ab_outcome if pa[-1].ends_plate_appearance else "In progress"
            chart = (chart_helpers.fig_to_img(at_bat_pitch_locations_chart(pa, batter_hand=hand, title=f"At-bat {k} -- {result or '--'}", zoom=True),
                                              width=460, height=460)
                     if located else ui.p("No pitch locations charted for this at-bat.", class_="text-muted small"))
            # Oct 2026, Ryker: "also add the pitcher they faced, the name of the pitcher"
            faced = []
            for p in pa:
                who = _pitcher_of(db, p)
                if who not in faced:
                    faced.append(who)
            if len(faced) > 1:                # pitching change mid at-bat: say who threw each pitch
                for row, p in zip(rows, pa):
                    n, h = _pitcher_of(db, p)
                    row["Pitcher"] = n or (f"{h}HP" if h else "--")
            facing = ", ".join(f"{n or 'Unknown pitcher'}" + (f" ({h}HP)" if h in ("R", "L") else "") for n, h in faced)
            return ui.div(
                ui.div(ui.span("Pitcher faced", class_="gbo-kpi-label"), ui.div(facing, style="font-size:1.15rem;font-weight:700;"),
                       style="margin:6px 0 10px;"),
                ui.layout_columns(
                    ui.div(chart, style="text-align:center;"),
                    ui.div(ui_helpers.render_dict_table(rows),
                           ui.p("Velo shows when the pitcher threw with Rapsodo running (our own pitchers in "
                                "intrasquads). Location is from your side: in = toward you.", class_="text-muted small")),
                    col_widths=[5, 7],
                ),
                ui.input_select("ab_pitch_select", "Pitch detail", choices=pitch_choices),
                ui.output_ui("ab_pitch_card"),
            )
        finally:
            db.close()

    @render.ui
    def ab_pitch_card():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("ab_pitch_select" in input)
        raw = input.ab_pitch_select()
        if not raw:
            return None
        db = get_session()
        try:
            p = (db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
                 .filter(GamePitch.game_pitch_id == int(raw)).first())
            if p is None or "batter_select" not in input or p.our_player_id != int(input.batter_select()):
                return None
            label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
            hand = get_batter_hands(db, [p]).get(p.game_pitch_id)
            r = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id]).get(p.game_pitch_id)
            name, phand = _pitcher_of(db, p)
            located = p.actual_plate_x is not None and p.actual_plate_z is not None
            pic = (chart_helpers.fig_to_img(at_bat_pitch_locations_chart([p], batter_hand=hand, title=f"Pitch {p.pa_pitch_number} -- {label}", zoom=True),
                                            width=460, height=460)
                   if located else ui.p("Not located.", class_="text-muted small"))
            extra = []
            if p.contact_quality:
                extra.append(f"Contact: {p.contact_quality}")
            if p.batted_ball_type:
                extra.append(f"Batted ball: {p.batted_ball_type}")
            if p.ends_plate_appearance and p.ab_outcome:
                extra.append(f"At-bat result: {p.ab_outcome}")
            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Pitch {p.pa_pitch_number} -- {label}"), f"  {_vs(name, phand)}", class_="small"),
                ui.layout_columns(
                    ui.div(pic, style="text-align:center;"),
                    ui.div(
                        ui_helpers.render_kpi_cards([
                            {"label": "Pitcher", "value": (name or "Unknown") + (f" ({phand}HP)" if phand in ("R", "L") else "")},
                            {"label": "Pitch", "value": label},
                            {"label": "Velocity", "value": f"{float(r.velocity):.1f} mph" if r is not None and r.velocity is not None else "--"},
                            {"label": "Count", "value": f"{p.balls_before}-{p.strikes_before}" if p.balls_before is not None else "--"},
                            {"label": "Result", "value": p.pitch_outcome or "--"},
                        ]),
                        ui.p(ui.strong("Location: "), location_words(p.actual_plate_x, p.actual_plate_z, hand), style="margin-top:10px;"),
                        ui.p(" · ".join(extra), class_="text-muted small") if extra else None,
                    ),
                    col_widths=[5, 7],
                ),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.hgr_glossary)
    def _hgr_show_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Hitting Stats Glossary", glossary_content.HITTING))

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
        if _view() != "batted":
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
