"""
GBO -- Hitter Profile (Aug 2026, Phase 0 of STUFF-LOCATION-PITCHING-
PLUS-PLAN.md). Batting-side counterpart to pitcher_profile.py: a
filterable, per-hitter deep dive across counting stats/slash line,
plate discipline (overall and by zone tier), batted-ball profile, and
contact quality by zone/pitch type -- all from the exact same
game_stats.py/plate_discipline.py functions Analytics/My Stats and
Hitter Game Report already use, just scoped to this page's own date-
range/pitch-type/game-scope filters instead of one game_id. No
Stuff+/Location+/Pitching+ here -- those are pitcher-only grades (see
pitcher_profile.py); a hitter's "how am I doing against stuff" read is
the existing Contact Quality by Zone/Pitch Type section below.

Self-scoping, same pattern as pitcher_profile.py/player_profile.py: a
staff role sees a player picker (scoped to assigned players unless
can_view_all_players); a "Player" role always sees their own linked
player, no picker, and gets nothing if that player IS a pitcher (pure
pitchers don't get a Hitter Profile -- mirrors My Bullpens/My Hitting's
existing is_pitcher split). A two-way player who bats and pitches only
ever gets routed to one of the two via nav.py's is_pitcher flag, same
simplification the rest of the app already makes.
"""

from datetime import date, timedelta

from shiny import module, ui, render, req
from shinywidgets import output_widget, render_plotly

from database import get_session
from models import Player, User, PitchType, StaffPlayerAssignment
from game_stats import compute_batting_line, compute_batted_ball_profile
from plate_discipline import compute_hitter_discipline, compute_zone_tier_discipline
from analytics import profile_queries
from modules.hitter_tracking import _compute_zone_scores, _build_zone_heatmap_figure, CONTACT_QUALITY_SCORE

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")


def _fmt_pct(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt(value, decimals=3):
    return f"{value:.{decimals}f}" if value is not None else "—"


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
        ui.output_ui("hp_body"),
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
    def hp_body():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
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

            line = compute_batting_line(pitches)
            sections = [ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title")]

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
            sections.append(ui.p("*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact.", class_="text-muted small"))

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
            sections.append(ui_helpers.render_dict_table(compute_zone_tier_discipline(pitches)))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Batted-Ball Profile")))
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
    # Contact Quality by Zone / Pitch Type -- same reused Hitter Tracking
    # zone-score math/heatmap builder Hitter Game Report already uses,
    # just scoped by this page's own filters instead of one game_id. Own
    # top-level output (own render.ui/render_plotly split), same reason
    # as hitter_game_report.py: a render_plotly output needs its own
    # registered function.
    # -------------------------------------------------------------------

    @render.ui
    def hp_contact_section():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
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
                ui.hr(),
                ui.p(ui.strong("Contact Quality by Zone / Pitch Type")),
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
