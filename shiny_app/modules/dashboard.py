"""
GBO -- Dashboard module (Shiny).

PHASE 3 SCOPE NOTE: this is deliberately a minimal placeholder, not a
full port of the original pages/dashboard.py (755 lines, five different
role-specific layouts -- Player/Athletic Trainer/Strength Coach/Sports
Scientist/general staff). Its job right now is to prove the wiring end
to end: AppState -> module -> a real database.py/models.py query ->
ui_helpers rendering -- the same pattern every other page module will
follow. The full role-specific dashboard layouts are Phase 5 work (see
the migration plan), migrated in the same batch as the other
first-priority pages (player_stats, player_schedule).

Module mounting: dashboard_server() is called exactly once, at app
startup, from shiny_app/app.py's server() -- unconditionally, before
any user has logged in. That's intentional (see app.py's module
docstring): it's cheap (just registers a reactive.Calc/render.ui, does
no DB work by itself), and it sidesteps the risk of double-registering
observers that comes with conditionally (re-)invoking a module server
function after login. The @render.ui below checks app_state itself
before doing anything.
"""

from shiny import module, ui, render

from database import get_session
from models import Player

import ui_helpers


@module.ui
def dashboard_ui():
    return ui.div(
        ui.output_ui("header"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def dashboard_server(input, output, session, app_state):
    @render.ui
    def header():
        if not app_state.is_authenticated():
            return None
        return ui_helpers.page_header(f"Welcome, {app_state.first_name()}")

    @render.ui
    def body():
        if not app_state.is_authenticated():
            return None

        # Same "team_id scoping via the logged-in user's team" pattern
        # every real query in the app follows -- kept trivial here
        # (just an active-player count) since the point of this module
        # right now is to prove a DB round trip works through the full
        # AppState -> module -> database.py stack, not to reproduce the
        # original dashboard's actual KPIs yet (Phase 5).
        db_session = get_session()
        try:
            active_player_count = db_session.query(Player).filter(Player.active.is_(True)).count()
        finally:
            db_session.close()

        return ui.div(
            ui.p(
                f"Role: {app_state.role_name()}",
                ui.tags.br(),
                "This is a placeholder dashboard proving the Shiny migration's "
                "auth + navigation + database wiring end to end. The full "
                "dashboard (role-specific layouts, KPI rows, bucket-system score "
                "rings) is ported in a later phase.",
            ),
            ui_helpers.render_kpi_cards([
                {"label": "Active Players", "value": str(active_player_count)},
            ]),
        )
