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
import error_log  # noqa: E402

# Oct 2026: record every error a user hits (app_errors) and email Ryker on
# bursts + a daily summary -- see error_log.py.
error_log.install()
from types import SimpleNamespace  # noqa: E402
from auth import do_login, do_logout, _load_gbo_role  # noqa: E402
import database  # noqa: E402
import demo_db  # noqa: E402
import nav  # noqa: E402
import ui_helpers  # noqa: E402
import theme  # noqa: E402
import click_widgets  # noqa: E402
from modules import (  # noqa: E402
    dashboard, player_schedule, player_stats, players, assessments, video_import,
    team_schedule, player_assignments, at_appointments, rapsodo_import, assessment_import,
    player_development, player_game_stats, player_hitting, player_video, player_bullpens,
    analytics, pitcher_game_report, hitter_game_report, bullpen_dashboard,
    pitcher_profile, hitter_profile, pitching_leaderboard, hitting_leaderboard,
    user_management, staff_assignments, hitter_tracking,
    opponent_teams, bullpen_scripts, training_routines, idp, bullpen_tracking,
    game_tracking, command_tracker, roster, player_profile,
    pitcher_meeting_report, weekly_report, advance_scouting, hitter_meeting_report, team_game_report,
    data_health, arm_care, how_to_read, research_project, charter_training,
)

# Registry of page keys (see nav.NavPage.key) that have a real Shiny
# module behind them so far. Everything else in the nav falls back to
# the "not yet migrated" placeholder panel below -- add an entry here
# in the same commit that adds a page's module.
MODULE_UI = {
    "dashboard": lambda: dashboard.dashboard_ui("dashboard"),
    "how_to_read": lambda: how_to_read.how_to_read_ui("how_to_read"),
    "research_project": lambda: research_project.research_project_ui("research_project"),
    "player_schedule": lambda: player_schedule.player_schedule_ui("player_schedule"),
    "player_stats": lambda: player_stats.player_stats_ui("player_stats"),
    "players": lambda: players.players_ui("players"),
    "assessments": lambda: assessments.assessments_ui("assessments"),
    "assessment_import": lambda: assessment_import.assessment_import_ui("assessment_import"),
    "video_import": lambda: video_import.video_import_ui("video_import"),
    "team_schedule": lambda: team_schedule.team_schedule_ui("team_schedule"),
    "player_assignments": lambda: player_assignments.player_assignments_ui("player_assignments"),
    "at_appointments": lambda: at_appointments.at_appointments_ui("at_appointments"),
    "rapsodo_import": lambda: rapsodo_import.rapsodo_import_ui("rapsodo_import"),
    "player_development": lambda: player_development.player_development_ui("player_development"),
    "player_game_stats": lambda: player_game_stats.player_game_stats_ui("player_game_stats"),
    "player_hitting": lambda: player_hitting.player_hitting_ui("player_hitting"),
    "player_video": lambda: player_video.player_video_ui("player_video"),
    "player_bullpens": lambda: player_bullpens.player_bullpens_ui("player_bullpens"),
    "analytics": lambda: analytics.analytics_ui("analytics"),
    "pitcher_game_report": lambda: pitcher_game_report.pitcher_game_report_ui("pitcher_game_report"),
    "pitcher_meeting_report": lambda: pitcher_meeting_report.pitcher_meeting_report_ui("pitcher_meeting_report"),
    "hitter_meeting_report": lambda: hitter_meeting_report.hitter_meeting_report_ui("hitter_meeting_report"),
    "team_game_report": lambda: team_game_report.team_game_report_ui("team_game_report"),
    "data_health": lambda: data_health.data_health_ui("data_health"),
    "charter_training": lambda: charter_training.charter_training_ui("charter_training"),
    "arm_care": lambda: arm_care.arm_care_ui("arm_care"),
    "weekly_report": lambda: weekly_report.weekly_report_ui("weekly_report"),
    "advance_scouting": lambda: advance_scouting.advance_scouting_ui("advance_scouting"),
    "hitter_game_report": lambda: hitter_game_report.hitter_game_report_ui("hitter_game_report"),
    "pitcher_profile": lambda: pitcher_profile.pitcher_profile_ui("pitcher_profile"),
    "hitter_profile": lambda: hitter_profile.hitter_profile_ui("hitter_profile"),
    "pitching_leaderboard": lambda: pitching_leaderboard.pitching_leaderboard_ui("pitching_leaderboard"),
    "hitting_leaderboard": lambda: hitting_leaderboard.hitting_leaderboard_ui("hitting_leaderboard"),
    "bullpen_dashboard": lambda: bullpen_dashboard.bullpen_dashboard_ui("bullpen_dashboard"),
    "user_management": lambda: user_management.user_management_ui("user_management"),
    "staff_assignments": lambda: staff_assignments.staff_assignments_ui("staff_assignments"),
    "hitter_tracking": lambda: hitter_tracking.hitter_tracking_ui("hitter_tracking"),
    "opponent_teams": lambda: opponent_teams.opponent_teams_ui("opponent_teams"),
    "bullpen_scripts": lambda: bullpen_scripts.bullpen_scripts_ui("bullpen_scripts"),
    "training_routines": lambda: training_routines.training_routines_ui("training_routines"),
    "idp": lambda: idp.idp_ui("idp"),
    "bullpen_tracking": lambda: bullpen_tracking.bullpen_tracking_ui("bullpen_tracking"),
    "game_tracking": lambda: game_tracking.game_tracking_ui("game_tracking"),
    "command_tracker": lambda: command_tracker.command_tracker_ui("command_tracker"),
    "roster": lambda: roster.roster_ui("roster"),
    "player_profile": lambda: player_profile.player_profile_ui("player_profile"),
}

# Fix for "scrolling through a page feels like it keeps refreshing/
# dimming" (Ryker's report -- reproduces on Assessments' New/Edit entry
# forms, which are a wall of ui.input_numeric fields, and on Bullpen
# Dashboard's Pitch Number Range / Minimum-pitches-to-shade sliders
# sitting right above the charts). Root cause: Chrome (and some other
# browsers) treats a mouse-wheel tick over a focused <input type="number">
# as an increment/decrement, not a page-scroll -- so scrolling the page
# with the cursor happening to pass over a numeric field bumps its
# value instead. Every one of those fields is wired to a live Shiny
# input, so each accidental bump sends a value to the server and
# triggers a real (if small) reactive recompute -- which shows up as
# the page visually flashing/dimming (Shiny's default "recalculating"
# state on the affected output) once per wheel tick while scrolling.
# Fix: blur any number input the instant a wheel event reaches it, so
# the browser has nothing focused to apply its
# scroll-changes-the-value behavior to, and the wheel event falls
# through to its normal job -- scrolling the page. Global listener
# (not a per-input JS binding) so it covers every ui.input_numeric on
# every page, including any added later, with no per-field wiring.
_NO_WHEEL_SCROLL_JS = """
document.addEventListener('wheel', function (e) {
  var el = e.target && e.target.closest ? e.target.closest('input[type="number"]') : null;
  if (el) { el.blur(); }
}, { passive: true, capture: true });
"""

app_ui = ui.page_fluid(
    # chart_helpers.plotly_js_dep() used to be included here for the
    # brief window where fig_to_img() rendered live plotly.js in the
    # browser -- that was reverted back to kaleido/static-PNG rendering
    # ("Quiet Bullpen Dashboard chart warnings, fix pitch-color
    # collisions"), which deleted plotly_js_dep() from chart_helpers.py
    # but missed this call site, breaking app startup (AttributeError)
    # the next time the server actually restarted. fig_to_img() no
    # longer needs plotly.js in the page at all, so this is just
    # removed rather than re-added.
    ui.tags.head(theme.fonts_link(), ui.tags.style(theme.GLOBAL_CSS)),
    ui.tags.script(_NO_WHEEL_SCROLL_JS),
    ui.tags.script(theme.MOTION_JS),
    ui.tags.script(theme.PHONE_JS),
    # Shared click-to-place capture for every click_widgets.click_target()
    # widget app-wide (Command Tracker's intended/actual location, Game
    # Tracking's pitch/batted-ball/video-review location) -- see
    # click_widgets.py's module docstring. This was previously never
    # actually wired in here despite that module's docstring claiming it
    # was (Aug 29 2026 finding, live-confirmed: the script was completely
    # absent from the rendered page, so no click-to-place widget anywhere
    # in the app could ever have worked, regardless of the clickmode fix
    # in strike_zone.py/field_location.py made the same day).
    ui.tags.script(click_widgets.CLICK_CAPTURE_JS),
    ui.output_ui("shell"),
    title="Gorilla Baseball Operations",
    style="padding:0;",
    # No theme= here on purpose -- see theme.py's GBO_THEME comment.
)


def server(input, output, session):
    app_state = new_app_state()
    error_log.register_session(session, lambda: (
        app_state.user_id(), app_state.role_name(), input.main_nav() if "main_nav" in input else None))

    # --- Dark/light mode: sync the client-side toggle into AppState so
    # server-rendered plotly charts (bucket_display.py -- CSS can't
    # reach those, they're static PNGs) know which palette to draw
    # with. Every other component reacts to the toggle purely via CSS
    # (see theme.py's [data-bs-theme] custom properties) -- no
    # server-side re-render needed for those. -----------------------
    # Oct 2026 (Part 2): "How to read this" links (ui_helpers.how_to_link)
    # open the matching guide section as a pop-up from any page.
    @reactive.effect
    @reactive.event(input.gbo_howto)
    def _show_how_to():
        allowed = {p.title for s in nav.build_nav_sections(app_state.role_name(), app_state.coach_specialty(),
                                                           app_state.is_pitcher()) for p in s.pages} \
            if app_state.is_authenticated() else set()
        m = how_to_read.modal(input.gbo_howto(), allowed)
        if m is not None:
            ui.modal_show(m)

    # Oct 2026 (Part 2): phone-width flag from the browser (theme.PHONE_JS)
    # so a few charts can stack instead of sitting side by side.
    @reactive.effect
    @reactive.event(input.gbo_phone)
    def _sync_phone():
        app_state.is_phone.set(bool(input.gbo_phone()))

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

    # --- Continue as Guest (Oct 2026, Ryker: midterm progress report) --
    # A guest gets the REAL app shell, logged in as a demo user, on a
    # private copy of a made-up team (demo_db.py). database.get_session()
    # hands this session that copy from here on; nothing a guest does can
    # reach Supabase, uploads or email (see database.in_guest_demo).
    guest_engine = {"eng": None}

    def _guest_login(email):
        app_state.auth_user.set(SimpleNamespace(email=email))
        app_state.auth_error.set(None)
        _load_gbo_role(app_state, email)

    @reactive.effect
    @reactive.event(input.guest_continue)
    def _on_guest_continue():
        maker, eng = demo_db.new_guest_db()
        database.use_guest_db(session, maker)
        guest_engine["eng"] = eng
        app_state.is_guest.set(True)
        _guest_login(demo_db.DEMO_COACH_EMAIL)

    @reactive.effect
    @reactive.event(input.guest_view)
    def _on_guest_view():
        if not app_state.is_guest():
            return
        email = {"coach": demo_db.DEMO_COACH_EMAIL, "pitcher": demo_db.DEMO_PLAYER_EMAIL,
                 "hitter": demo_db.DEMO_HITTER_EMAIL}.get(input.guest_view())
        if email:
            _guest_login(email)

    def _end_guest():
        database.use_guest_db(session, None)
        if guest_engine["eng"] is not None:
            guest_engine["eng"].dispose()
            guest_engine["eng"] = None

    session.on_ended(_end_guest)

    @reactive.effect
    @reactive.event(input.logout_button)
    def _on_logout():
        if app_state.is_guest():          # no Supabase login to sign out of
            app_state.reset()
            _end_guest()
            return
        do_logout(app_state)

    @reactive.effect
    @reactive.event(input.sidebar_go)
    def _on_sidebar_go():
        ui.update_navs("main_nav", selected=input.sidebar_go())

    @reactive.effect
    async def _mirror_nav_to_sidebar():
        title = input.main_nav()
        if title:
            await session.send_custom_message("gbo-nav-active", {"title": title})

    # --- Mount every page module's server ONCE, unconditionally --------
    # (see module docstring above for why always-mount is the safe
    # pattern here, and modules/dashboard.py for what an individual
    # module does with app_state before/after login.)
    dashboard.dashboard_server("dashboard", app_state)
    player_schedule.player_schedule_server("player_schedule", app_state)
    player_stats.player_stats_server("player_stats", app_state)
    players.players_server("players", app_state)
    assessments.assessments_server("assessments", app_state)
    assessment_import.assessment_import_server("assessment_import", app_state)
    video_import.video_import_server("video_import", app_state)
    team_schedule.team_schedule_server("team_schedule", app_state)
    player_assignments.player_assignments_server("player_assignments", app_state)
    at_appointments.at_appointments_server("at_appointments", app_state)
    rapsodo_import.rapsodo_import_server("rapsodo_import", app_state)
    player_development.player_development_server("player_development", app_state)
    player_game_stats.player_game_stats_server("player_game_stats", app_state)
    player_hitting.player_hitting_server("player_hitting", app_state)
    player_video.player_video_server("player_video", app_state)
    player_bullpens.player_bullpens_server("player_bullpens", app_state)
    analytics.analytics_server("analytics", app_state)
    pitcher_game_report.pitcher_game_report_server("pitcher_game_report", app_state)
    pitcher_meeting_report.pitcher_meeting_report_server("pitcher_meeting_report", app_state)
    hitter_meeting_report.hitter_meeting_report_server("hitter_meeting_report", app_state)
    team_game_report.team_game_report_server("team_game_report", app_state)
    data_health.data_health_server("data_health", app_state)
    charter_training.charter_training_server("charter_training", app_state)
    arm_care.arm_care_server("arm_care", app_state)
    weekly_report.weekly_report_server("weekly_report", app_state)
    how_to_read.how_to_read_server("how_to_read", app_state)
    research_project.research_project_server("research_project", app_state)
    advance_scouting.advance_scouting_server("advance_scouting", app_state)
    hitter_game_report.hitter_game_report_server("hitter_game_report", app_state)
    pitcher_profile.pitcher_profile_server("pitcher_profile", app_state)
    hitter_profile.hitter_profile_server("hitter_profile", app_state)
    pitching_leaderboard.pitching_leaderboard_server("pitching_leaderboard", app_state)
    hitting_leaderboard.hitting_leaderboard_server("hitting_leaderboard", app_state)
    bullpen_dashboard.bullpen_dashboard_server("bullpen_dashboard", app_state)
    user_management.user_management_server("user_management", app_state)
    staff_assignments.staff_assignments_server("staff_assignments", app_state)
    hitter_tracking.hitter_tracking_server("hitter_tracking", app_state)
    opponent_teams.opponent_teams_server("opponent_teams", app_state)
    bullpen_scripts.bullpen_scripts_server("bullpen_scripts", app_state)
    training_routines.training_routines_server("training_routines", app_state)
    idp.idp_server("idp", app_state)
    bullpen_tracking.bullpen_tracking_server("bullpen_tracking", app_state)
    game_tracking.game_tracking_server("game_tracking", app_state)
    command_tracker.command_tracker_server("command_tracker", app_state)
    roster.roster_server("roster", app_state)
    player_profile.player_profile_server("player_profile", app_state)

    # --- Top-level shell: decide what to show, just like the original --
    @render.ui
    def shell():
        if app_state.auth_user() is None:
            return _login_ui(app_state)
        if app_state.is_pending_setup():
            return _account_not_set_up_ui()
        return _app_shell_ui(app_state)


def _login_ui(app_state):
    error = app_state.auth_error()
    error_html = ui.div(ui.tags.span(error, class_="text-danger small"), class_="mt-2 text-center") if error else ui.div()

    return ui.div(
        ui.div(ui.input_dark_mode(id="dark_mode", mode="dark"), class_="gbo-mode-toggle", style="position:fixed;top:12px;right:16px;"),
        ui.div(
            theme.logo_img(css_class="gbo-auth-logo"),
            ui.div("Gorilla Baseball Operations", class_="gbo-page-header", style="text-align:center;"),
            ui.div(class_="gbo-auth-underline"),
            ui.p("Log in with your GBO account", class_="text-muted small", style="text-align:center; margin-bottom:20px;"),
            ui.input_text("login_email", "Email"),
            ui.input_password("login_password", "Password"),
            ui.input_action_button("login_submit", "Log in", class_="btn-primary w-100 mt-3"),
            error_html,
            ui.hr(),
            ui.p("Just want to see what GBO looks like?", class_="text-muted small", style="text-align:center;"),
            ui.input_action_button("guest_continue", "Continue as Guest", class_="btn-outline-light w-100"),
            class_="gbo-auth-card",
        ),
        class_="gbo-auth-wrap",
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


# --- v2 shell: left sidebar + top bar + hidden navset ------------------
# Page modules still switch pages with ui.update_navs("main_nav",
# selected=<page title>) -- the navset is now ui.navset_hidden with the
# same id and the same nav_panel titles, so those calls keep working.
# The sidebar is plain HTML; clicking a link sets the Shiny input
# `sidebar_go` (page title) and the server calls update_navs. The
# server also mirrors input.main_nav back to the sidebar so
# programmatic jumps highlight the right link.

# Regroup nav.py's role-gated pages into the design-system groups
# (GBO-DESIGN-SYSTEM.md section 5). Unknown keys fall into "Other".
_NAV_GROUPS = [
    ("About", ["research_project"]),   # guest demo only (Oct 2026)
    ("Overview", ["dashboard", "how_to_read"]),
    ("Roster", ["roster", "player_profile", "players"]),
    ("Development", ["assessments", "assessment_import", "idp", "training_routines", "player_assignments", "team_schedule"]),
    # at_appointments/bullpen_scripts intentionally omitted from every group
    # below (Aug 31 2026 -- Ryker's call, kept in the codebase/MODULE_UI,
    # just out of the visible sidebar) -- see nav.py's matching comments.
    ("Pitching", ["arm_care", "bullpen_dashboard", "bullpen_tracking", "rapsodo_import"]),
    # ("Hitting", ["hitter_tracking"]) -- removed from the sidebar Oct 2026 (Ryker)
    ("Games", ["game_tracking", "data_health", "charter_training", "team_game_report", "pitcher_game_report", "pitcher_meeting_report", "hitter_game_report", "hitter_meeting_report"]),
    # Sept 2026, Ryker: "pitcher profile, hitter profile, player stats
    # should be under analytics rather than games" -- moved out of
    # "Games" above into their own group; Pitcher/Hitter Game Report
    # stay under Games (single-outing box scores, not asked to move).
    ("Analytics", ["analytics", "pitcher_profile", "weekly_report", "hitter_profile", "pitching_leaderboard", "hitting_leaderboard"]),
    ("Scouting", ["advance_scouting", "opponent_teams"]),
    ("Admin", ["user_management", "staff_assignments", "video_import"]),
    ("Me", ["player_profile", "player_schedule", "player_development", "player_stats", "player_game_stats", "player_hitting", "player_video", "player_bullpens", "pitcher_profile", "pitcher_meeting_report", "weekly_report", "advance_scouting", "hitter_profile", "hitter_meeting_report", "pitching_leaderboard", "hitting_leaderboard"]),
]
_NAV_LABELS = {
    "players": "Player setup", "roster": "Players", "idp": "Development plans", "rapsodo_import": "Import Rapsodo",
    "assessment_import": "Import Assessments",
    "analytics": "Player stats", "at_appointments": "AT appointments", "player_assignments": "Assignments",
    "team_schedule": "Team schedule", "user_management": "Users", "staff_assignments": "Staff assignments",
}
_ICONS = {
    "research_project": '<path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3"/><path d="M7.5 15h9"/>',
    "roster": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M16 4a3.5 3.5 0 010 7M21.5 20a6.5 6.5 0 00-5-6.3"/>',
    "player_profile": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
    "dashboard": '<path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"/>',
    "how_to_read": '<path d="M4 5a2 2 0 012-2h13v16H6a2 2 0 00-2 2V5z"/><path d="M4 19a2 2 0 002 2h13"/><path d="M9 8h6M9 12h4"/>',
    "players": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "assessments": '<path d="M9 4h6v3H9zM7 6H5v15h14V6h-2M8 13l2 2 5-5"/>',
    "assessment_import": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "idp": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    "training_routines": '<path d="M4 12h3l2-6 4 12 2-6h5"/>',
    "player_assignments": '<path d="M5 5h14v14H5zM8 12l3 3 5-6"/>',
    "team_schedule": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "at_appointments": '<path d="M12 4v16M4 12h16"/><rect x="3" y="3" width="18" height="18" rx="3"/>',
    "data_health": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "charter_training": '<path d="M2 9l10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>',
    "arm_care": '<path d="M12 21s-7-4.5-9-9.5C1.5 7 4.5 4 8 4c2 0 3.2 1 4 2.2C12.8 5 14 4 16 4c3.5 0 6.5 3 5 7.5-2 5-9 9.5-9 9.5z"/>',
    "bullpen_dashboard": '<path d="M4 20V9M10 20V4M16 20v-8M22 20H2"/>',
    "bullpen_tracking": '<circle cx="12" cy="12" r="8"/><path d="M8 8c2 2 2 6 0 8M16 8c-2 2-2 6 0 8"/>',
    "bullpen_scripts": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6"/>',
    "rapsodo_import": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "hitter_tracking": '<path d="M4 20L18 6l2 2L6 22zM15 3l6 6"/>',
    "game_tracking": '<path d="M12 3l8 8-8 10-8-10z"/><path d="M12 3v18M4 11h16"/>',
    "pitcher_game_report": '<path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/>',
    "hitter_game_report": '<path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/>',
    "advance_scouting": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4M8 11h6M11 8v6"/>',
    "weekly_report": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4M7 17l3-3 3 2 4-4"/>',
    "pitcher_meeting_report": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/><path d="M3 9h3M3 13h3"/>',
    "hitter_meeting_report": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/><path d="M3 9h3M3 13h3"/>',
    "team_game_report": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M8 15h2M14 15h2M8 4v16M16 4v16"/>',
    "analytics": '<path d="M3 17l6-6 4 4 8-8M14 7h7v7"/>',
    "pitcher_profile": '<path d="M3 17l6-6 4 4 8-8M14 7h7v7"/><circle cx="12" cy="12" r="9"/>',
    "hitter_profile": '<path d="M3 17l6-6 4 4 8-8M14 7h7v7"/><circle cx="12" cy="12" r="9"/>',
    "pitching_leaderboard": '<path d="M8 21h8M12 17v4M17 3H7v5a5 5 0 0010 0V3z"/><path d="M5 5H3v2a3 3 0 003 3M19 5h2v2a3 3 0 01-3 3"/>',
    "hitting_leaderboard": '<path d="M8 21h8M12 17v4M17 3H7v5a5 5 0 0010 0V3z"/><path d="M5 5H3v2a3 3 0 003 3M19 5h2v2a3 3 0 01-3 3"/>',
    "opponent_teams": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
    "user_management": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    "staff_assignments": '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
    "video_import": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "player_schedule": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "player_development": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
    "player_stats": '<path d="M9 4h6v3H9zM7 6H5v15h14V6h-2M8 13l2 2 5-5"/>',
    "player_game_stats": '<path d="M4 20V9M10 20V4M16 20v-8M22 20H2"/>',
    "player_hitting": '<path d="M4 20L18 6l2 2L6 22zM15 3l6 6"/>',
    "player_video": '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3z"/>',
    "player_bullpens": '<circle cx="12" cy="12" r="8"/><path d="M8 8c2 2 2 6 0 8M16 8c-2 2-2 6 0 8"/>',
}

_SIDEBAR_JS = """
(function(){
  function setActive(title){
    document.querySelectorAll('.gbo-side-link[data-title]').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-title') === title);
    });
    var c = document.getElementById('gbo-crumb');
    if (c) { c.innerHTML = '<b>' + title.replace(/</g,'&lt;') + '</b>'; }
  }
  document.addEventListener('click', function(e){
    var b = e.target && e.target.closest ? e.target.closest('.gbo-side-link[data-title]') : null;
    if (!b) return;
    var t = b.getAttribute('data-title');
    setActive(t);
    if (window.Shiny) { Shiny.setInputValue('sidebar_go', t, {priority: 'event'}); }
    var side = document.querySelector('.gbo-side'); if (side) side.classList.remove('open');
  });
  document.addEventListener('click', function(e){
    var m = e.target && e.target.closest ? e.target.closest('.gbo-menu-btn') : null;
    if (!m) return; var side = document.querySelector('.gbo-side'); if (side) side.classList.toggle('open');
  });
  if (window.Shiny) {
    Shiny.addCustomMessageHandler('gbo-nav-active', function(msg){ setActive(msg.title); });
  }
})();
"""


def _icon(key):
    path = _ICONS.get(key, '<circle cx="12" cy="12" r="3"/>')
    return ui.HTML(f'<svg viewBox="0 0 24 24" aria-hidden="true">{path}</svg>')


def _sidebar(app_state, sections):
    pages_by_key = {}
    for section in sections:
        for page in section.pages:
            pages_by_key.setdefault(page.key, page)
    placed = set()
    groups = []
    for gtitle, keys in _NAV_GROUPS:
        items = [pages_by_key[k] for k in keys if k in pages_by_key and k not in placed]
        if items:
            groups.append((gtitle, items)); placed.update(p.key for p in items)
    leftovers = [p for k, p in pages_by_key.items() if k not in placed]
    if leftovers:
        groups.append(("Other", leftovers))

    links = []
    first_title = None
    for gtitle, items in groups:
        links.append(ui.div(gtitle, class_="gbo-side-group"))
        for page in items:
            if first_title is None:
                first_title = page.title
            label = _NAV_LABELS.get(page.key, page.title)
            links.append(ui.tags.button(_icon(page.key), ui.span(label), class_="gbo-side-link" + (" active" if page.title == first_title else ""), type="button", **{"data-title": page.title}))

    initials = (app_state.first_name() or "?")[:1] + (app_state.last_name() or "")[:1]
    me = ui.div(
        ui.div(initials.upper(), class_="gbo-avatar"),
        ui.div(ui.div(f"{app_state.first_name()} {app_state.last_name()}", class_="gbo-side-me-name"), ui.span(app_state.role_name(), class_="gbo-role-badge")),
        class_="gbo-side-me",
    )
    brand = ui.div(theme.logo_img(css_class=""), ui.div(ui.div("GBO", class_="gbo-brand-title"), ui.div("Gorilla Baseball Ops", class_="gbo-brand-sub")), class_="gbo-brand")
    return ui.tags.aside(brand, *links, me, class_="gbo-side"), first_title


GUEST_VIEWS = [("coach", "Staff"), ("pitcher", "Pitcher"), ("hitter", "Hitter")]


def _guest_banner(app_state):
    """Oct 2026: strip across the top of the guest demo -- what this is, and
    buttons to see it as a coach, a pitcher or a hitter."""
    current = "coach" if app_state.role_name() != "Player" else ("pitcher" if app_state.is_pitcher() else "hitter")
    buttons = [
        ui.tags.button(label, type="button", class_="btn btn-sm " + ("btn-primary" if key == current else "btn-outline-secondary"),
                       onclick=f"Shiny.setInputValue('guest_view', '{key}', {{priority: 'event'}})")
        for key, label in GUEST_VIEWS
    ]
    return ui.div(
        ui.div(ui.strong("Guest demo"), " · a made-up team, nothing here is real player data (except the counts on "
               "Research Project) · changes stay in your copy only", class_="gbo-guest-text"),
        ui.div(ui.span("View as", class_="gbo-guest-lbl"), *buttons, class_="gbo-guest-btns"),
        class_="gbo-guest-banner",
    )


def _app_shell_ui(app_state):
    sections = nav.build_nav_sections(
        app_state.role_name(), app_state.coach_specialty(), app_state.is_pitcher()
    )
    guest = app_state.is_guest()
    if guest:
        sections = [nav.NavSection("About", [nav.NavPage("research_project", "Research Project", "flask")])] + sections
    sidebar, first_title = _sidebar(app_state, sections)

    panels = []
    for section in sections:
        for page in section.pages:
            panels.append(ui.nav_panel(page.title, _page_body(page)))

    topbar = ui.div(
        ui.tags.button(ui.HTML('<svg viewBox="0 0 24 24" style="width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:2"><path d="M4 7h16M4 12h16M4 17h16"/></svg>'), class_="btn btn-outline-light gbo-menu-btn", type="button"),
        ui.div(ui.HTML(f"<b>{first_title}</b>"), class_="gbo-crumb", id="gbo-crumb"),
        ui.div(
            ui.div(ui.input_dark_mode(id="dark_mode", mode="dark"), class_="gbo-mode-toggle"),
            ui.input_action_button("logout_button", "Exit demo" if guest else "Log out", class_="btn-sm btn-outline-light"),
            class_="gbo-top-right",
        ),
        class_="gbo-top",
    )

    return ui.div(
        sidebar,
        ui.div(
            topbar,
            _guest_banner(app_state) if guest else None,
            ui.div(ui.navset_hidden(*panels, id="main_nav", selected=first_title), class_="gbo-content"),
            class_="gbo-main",
        ),
        ui.tags.script(_SIDEBAR_JS),
        class_="gbo-app",
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