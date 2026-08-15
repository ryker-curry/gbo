"""
GBO -- Shiny for Python entry point (migration target for the original
Streamlit app.py + pages/ directory).

Run with (from the repo root):
    pip install -r requirements.txt
    shiny run shiny_app/app.py --reload

Coexists with the original Streamlit app during the migration -- run
`streamlit run app.py` at the repo root for the still-complete original,
or `shiny run shiny_app/app.py` for this in-progress port. Both read the
same database.py/models.py/supabase_client.py against the same Supabase
project, so either can run at once without conflict; nothing here
touches the Streamlit app.py or pages/ directory.

Architecture (full rationale in the migration plan doc):
  - Outer UI is a single static shell with one ui.output_ui("shell").
  - AppState (state.py) is created once per session inside server() --
    never at module scope -- so identity/role state never leaks across
    different users connected to the same running app process.
  - The "shell" render.ui reactively swaps between the login form, the
    "account not set up" message, and the full role-based navset_bar --
    mirroring the original app.py's "decide what to show, every run"
    model without a full page reload.
  - Every page module's *_server() is mounted unconditionally at
    startup (cheap -- it just registers reactive closures, no DB work
    happens until a value is actually read) and each module internally
    no-ops (via app_state.is_authenticated()) until the session is
    authenticated. This avoids the alternative -- conditionally calling
    a module's _server() only after login -- which risks re-registering
    duplicate observers if it ever fires more than once per session.

Import path note: `shiny run ... --reload` loads this file through a
file-watcher subprocess that does NOT reliably put the repo root (one
level up, where database.py/models.py/supabase_client.py live) on
sys.path the way a plain `shiny run` does -- confirmed to fail with
`ModuleNotFoundError: No module named 'database'` under --reload on at
least one real setup. The explicit sys.path fix below removes the
dependency on however that CLI happens to resolve paths, so this
package works the same whether run as `shiny run shiny_app/app.py`,
`shiny run shiny_app/app.py --reload`, or `python3 -m shiny run ...`,
and regardless of which directory it's launched from.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
for _p in (_REPO_ROOT, _THIS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from shiny import App, ui, render, reactive  # noqa: E402

from state import new_app_state  # noqa: E402
from auth import do_login, do_logout  # noqa: E402
import nav  # noqa: E402
import ui_helpers  # noqa: E402
import theme  # noqa: E402
from modules import dashboard, player_schedule, player_stats  # noqa: E402

# Registry of page keys (see nav.NavPage.key) that have a real Shiny
# module behind them so far. Everything else in the nav falls back to
# the "not yet migrated" placeholder panel below -- add an entry here
# in the same commit that adds a page's module.
MODULE_UI = {
    "dashboard": lambda: dashboard.dashboard_ui("dashboard"),
    "player_schedule": lambda: player_schedule.player_schedule_ui("player_schedule"),
    "player_stats": lambda: player_stats.player_stats_ui("player_stats"),
}

app_ui = ui.page_fillable(
    ui.tags.style(theme.GLOBAL_CSS),
    ui.div(
        ui.input_dark_mode(id="dark_mode", mode="dark"),
        class_="gbo-mode-toggle",
    ),
    ui.output_ui("shell"),
    title="Gorilla Baseball Operations",
    fillable_mobile=True,
    # No theme= here on purpose -- see theme.py's GBO_THEME comment.
    # Styling comes entirely from the plain-CSS GLOBAL_CSS injected
    # above, so there's no Sass compile step (and no libsass native
    # dependency) at app startup.
)


def server(input, output, session):
    app_state = new_app_state()

    # --- Dark/light mode: sync the client-side toggle into AppState so
    # server-rendered plotly charts (bucket_display.py -- CSS can't
    # reach those, they're static PNGs) know which palette to draw
    # with. Every other component reacts to the toggle purely via CSS
    # (see theme.py's [data-bs-theme] custom properties) -- no
    # server-side re-render needed for those. -----------------------
    @reactive.effect
    def _sync_dark_mode():
        mode = input.dark_mode()
        if mode:
            app_state.dark_mode.set(mode)

    # --- Login form + logout handlers ----------------------------------
    @reactive.effect
    @reactive.event(input.login_submit)
    def _on_login_submit():
        do_login(app_state, input.login_email(), input.login_password())

    @reactive.effect
    @reactive.event(input.guest_continue)
    def _on_guest_continue():
        app_state.is_guest.set(True)

    @reactive.effect
    @reactive.event(input.logout_button)
    def _on_logout():
        do_logout(app_state)

    # --- Mount every page module's server ONCE, unconditionally --------
    # (see module docstring above for why always-mount is the safe
    # pattern here, and modules/dashboard.py for what an individual
    # module does with app_state before/after login.)
    dashboard.dashboard_server("dashboard", app_state)
    player_schedule.player_schedule_server("player_schedule", app_state)
    player_stats.player_stats_server("player_stats", app_state)

    # --- Top-level shell: decide what to show, just like the original --
    @render.ui
    def shell():
        if app_state.is_guest():
            return _guest_ui()
        if app_state.auth_user() is None:
            return _login_ui(app_state)
        if app_state.is_pending_setup():
            return _account_not_set_up_ui()
        return _app_shell_ui(app_state)


def _login_ui(app_state):
    error = app_state.auth_error()
    error_html = ui.div(ui.tags.span(error, class_="text-danger")) if error else ui.div()

    return ui.div(
        ui.h2("Gorilla Baseball Operations", class_="text-center mt-4"),
        ui.p("Log in with your GBO account", class_="text-center text-muted mb-4"),
        ui.row(
            ui.column(
                4,
                ui.input_text("login_email", "Email"),
                ui.input_password("login_password", "Password"),
                ui.input_action_button("login_submit", "Log in", class_="btn-primary w-100 mt-2"),
                error_html,
                ui.hr(),
                ui.p("Just want to see what GBO looks like?", class_="text-muted small"),
                ui.input_action_button("guest_continue", "Continue as Guest", class_="w-100"),
                offset=4,
            ),
        ),
    )


def _guest_ui():
    # Mirrors the original app.py's guest mode (pages/guest_overview.py)
    # -- curated overview, no real auth, no real data. Not migrated yet
    # (Phase 5); placeholder for now.
    return ui.div(
        ui.h3("Guest Overview"),
        ui.p("Guest overview page not yet migrated to Shiny."),
        class_="p-4",
    )


def _account_not_set_up_ui():
    return ui.div(
        ui.tags.span(
            "Your account is not yet set up in GBO. Contact an administrator to be added before you can continue.",
            class_="text-danger",
        ),
        ui.br(),
        ui.input_action_button("logout_button", "Log out", class_="mt-2"),
        class_="p-4",
    )


def _app_shell_ui(app_state):
    sections = nav.build_nav_sections(
        app_state.role_name(), app_state.coach_specialty(), app_state.is_pitcher()
    )

    nav_items = []
    for section in sections:
        panels = [ui.nav_panel(page.title, _page_body(page)) for page in section.pages]
        if len(panels) == 1 and len(section.pages) == 1 and section.title == "Dashboard":
            nav_items.append(panels[0])
        else:
            nav_items.append(ui.nav_menu(section.title, *panels))

    return ui.navset_bar(
        *nav_items,
        ui.nav_spacer(),
        ui.nav_control(
            ui.tags.span(
                f"{app_state.first_name()} {app_state.last_name()} ",
                ui.tags.span(app_state.role_name(), class_="gbo-role-badge ms-1"),
                class_="navbar-text me-2",
            )
        ),
        ui.nav_control(ui.input_action_button("logout_button", "Log out", class_="btn-sm btn-outline-light")),
        title=ui.div(theme.logo_img(), "GBO", class_="gbo-navbar-brand"),
        id="main_nav",
    )


def _page_body(page):
    """Real module UI if migrated, otherwise a placeholder -- see
    MODULE_UI at the top of this file."""
    build = MODULE_UI.get(page.key)
    if build is not None:
        return build()
    return ui.div(
        ui_helpers.page_header(page.title),
        ui.p(f'"{page.title}" has not been migrated to Shiny yet.', class_="text-muted"),
        class_="p-3",
    )


app = App(app_ui, server, static_assets={"/assets": theme.ASSETS_DIR})
