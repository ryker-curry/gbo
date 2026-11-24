"""
GBO -- Scoring Chances page (Nov 2026, Ryker, from PEAR Ratings' "Runs
per Scoring Chance" chart). Staff-only. Team offense vs pitching staff,
then a PEAR-style scatter + leaderboard for pitchers and for hitters.
Math: analytics/scoring_chances.py. Display: scoring_chances_display.py
(shared with the Pitcher / Hitter Profiles).
"""

from datetime import date

from shiny import module, ui, render, req

from database import get_session
from models import Player
from analytics import scoring_chances as sc
from analytics.weekly_report import season_start
import scoring_chances_display as scd
import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")


@module.ui
def scoring_chances_ui():
    return ui.div(
        ui_helpers.page_header("Scoring Chances", "Runs per half-inning with a runner on 2nd or 3rd"),
        ui.output_ui("sc_filters"),
        ui.output_ui("sc_body"),
        ui_helpers.page_footer(),
    )


@module.server
def scoring_chances_server(input, output, session, app_state):
    def _allowed():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    @render.ui
    def sc_filters():
        if not app_state.is_authenticated():
            return None
        if not _allowed():
            return ui.p("You don't have access to this page.", class_="text-danger")
        return ui.layout_columns(
            ui.input_date("sc_from", "From", value=season_start()),
            ui.input_date("sc_to", "To", value=date.today()),
            ui.input_select("sc_scope", "Games",
                            choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[4, 4, 4],
        )

    @render.ui
    def sc_body():
        if not _allowed():
            return None
        req("sc_scope" in input)
        db = get_session()
        try:
            data = sc.scoring_chances(db, input.sc_from(), input.sc_to(), input.sc_scope())
            ids = set(data["pitchers"]) | set(data["hitters"])
            names = {p.player_id: f"{p.first_name} {p.last_name}"
                     for p in db.query(Player).filter(Player.player_id.in_(ids)).all()} if ids else {}
        finally:
            db.close()

        team = data["team"]
        if not team["offense"]["half_innings"] and not team["staff"]["half_innings"]:
            return ui_helpers.empty_state("No charted games in this range yet.")

        star = ui.p("* small sample (under %d chances for a pitcher, %d RISP PA for a hitter) -- left off the chart."
                    % (sc.MIN_PITCHER_CHANCES, sc.MIN_HITTER_RISP_PA), class_="text-muted small")
        p_rows = scd.pitcher_table(data["pitchers"], names)
        h_rows = scd.hitter_table(data["hitters"], names)
        return ui.div(
            ui.div(ui.h5("Team", class_="gbo-section-title", style="margin-bottom:0;"),
                   ui_helpers.how_to_link("scoring_chances"),
                   style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;"),
            *scd.team_section(team),
            ui.hr(),
            ui.h5("Pitchers", class_="gbo-section-title"),
            ui.p("Up and right is better. Dashed lines = staff average. Runs are charged to the pitcher who put "
                 "the runner on, so a reliever who strands his inherited runners isn't hurt by them.",
                 class_="text-muted small"),
            ui.HTML(scd.pitcher_scatter(data["pitchers"], names, team["staff"])),
            ui_helpers.render_dict_table(p_rows) if p_rows else ui.p("No pitcher chances yet.", class_="text-muted small"),
            star,
            ui.hr(),
            ui.h5("Hitters", class_="gbo-section-title"),
            ui.p("Up and right is better. Dashed lines = team average. Sorted by RISP RE24 (runs added with a "
                 "runner on 2nd or 3rd).", class_="text-muted small"),
            ui.HTML(scd.hitter_scatter(data["hitters"], names)),
            ui_helpers.render_dict_table(h_rows) if h_rows else ui.p("No RISP plate appearances yet.", class_="text-muted small"),
            star,
        )
