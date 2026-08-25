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
import chart_helpers  # noqa: E402
from modules import (  # noqa: E402
    dashboard, player_schedule, player_stats, players, assessments, video_import,
    team_schedule, player_assignments, at_appointments, rapsodo_import,
    player_development, player_game_stats, player_hitting, player_video, player_bullpens,
    analytics, pitcher_game_report, hitter_game_report, bullpen_dashboard,
    user_management, staff_assignments, hitter_tracking,
    opponent_teams, bullpen_scripts, training_routines, idp, bullpen_tracking,
    game_tracking, command_tracker, roster, player_profile,
)

# Registry of page keys (see nav.NavPage.key) that have a real Shiny
# module behind them so far. Everything else in the nav falls back to
# the "not yet migrated" placeholder panel below -- add an entry here
# in the same commit that adds a page's module.
MODULE_UI = {
    "dashboard": lambda: dashboard.dashboard_ui("dashboard"),
    "player_schedule": lambda: player_schedule.player_schedule_ui("player_schedule"),
    "player_stats": lambda: player_stats.player_stats_ui("player_stats"),
    "players": lambda: players.players_ui("players"),
    "assessments": lambda: assessments.assessments_ui("assessments"),
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
    "hitter_game_report": lambda: hitter_game_report.hitter_game_report_ui("hitter_game_report"),
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
    ui.tags.head(theme.fonts_link(), ui.tags.style(theme.GLOBAL_CSS), chart_helpers.plotly_js_dep()),
    ui.tags.script(_NO_WHEEL_SCROLL_JS),
    ui.tags.script(theme.MOTION_JS),
    ui.output_ui("shell"),
    title="Gorilla Baseball Operations",
    style="padding:0;",
    # No theme= here on purpose -- see theme.py's GBO_THEME comment.
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
    @reactive.event(input.guest_back_to_login)
    def _on_guest_back_to_login():
        app_state.is_guest.set(False)

    @reactive.effect
    @reactive.event(input.logout_button)
    def _on_logout():
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
    hitter_game_report.hitter_game_report_server("hitter_game_report", app_state)
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
        if app_state.is_guest():
            return _guest_ui()
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


_GUEST_ASSESSMENT_CATEGORIES = [
    ("Body Composition", "19 metrics via InBody770",
     "Skeletal muscle mass, body fat percentage, and lean/fat mass broken out by limb (including "
     "throwing arm vs. non-throwing arm). This tracks a player's power-to-weight ratio and conditioning "
     "level over an offseason or season, and asymmetries between limbs can flag developing imbalances "
     "before they become injuries."),
    ("Mobility & ROM", "24 range-of-motion measurements",
     "How far the shoulder, elbow, and hip move, tested bilaterally (or by drive leg/plant leg for "
     "the hip) -- plus Total Arc of Motion and GIRD (Glenohumeral Internal Rotation Deficit), both "
     "calculated automatically from the shoulder readings rather than tested separately. Restricted "
     "mobility anywhere in the chain limits how efficiently force transfers through the body, and it's "
     "one of the most "
     "common root causes of both reduced performance and overuse injury."),
    ("Arm Health", "26 metrics — ROM, strength, pain, and workload",
     "A dedicated deep-dive on the throwing arm: shoulder rotation range, shoulder and grip strength, "
     "elbow mobility, and daily self-reported pain/readiness scores, plus throwing workload counts "
     "(bullpen and game pitch counts). This is the platform's core injury-prevention tool for pitchers "
     "and any position player who throws often -- catching a strength or ROM deficit early can prevent "
     "a shoulder or elbow injury before it happens."),
    ("Upper Body Strength", "6 metrics — push, pull, grip",
     "Bench press load and reps, chin-up load and reps, grip strength. Upper body strength underlies "
     "bat speed and throwing velocity -- a stronger, more stable upper body can produce and control "
     "more force through the swing or throw."),
    ("Lower Body Strength", "15 metrics — bilateral, unilateral, hip, knee",
     "Squat and deadlift loads, isometric mid-thigh pull force, single-leg strength, and hip/knee "
     "force output on each side. Baseball power starts from the ground up -- sprint speed, jump "
     "height, and rotational power at the plate or on the mound all trace back to lower body strength "
     "and how symmetric it is left to right."),
    ("Explosive Power", "13 metrics — jump and reactive power",
     "Countermovement jump height, squat jump, single-leg jumps, broad jump, lateral jumps, and a "
     "plyometric push-up test. This measures how quickly a player can produce force (not just how "
     "much), which is what actually translates strength into bat speed, throwing velocity, and first-step "
     "quickness -- strength alone doesn't win at the plate or on the bases without speed of application."),
    ("Rotational Power", "4 metrics — medicine ball throws",
     "Distance and velocity of a rotational medicine ball throw, both directions. Baseball's core "
     "movements -- the swing and the throw -- are both rotational, so this is one of the most direct "
     "physical proxies for hitting and throwing power the platform tracks."),
    ("Speed", "4 metrics — acceleration and top speed",
     "10-yard and 20-yard sprint times, a flying 10-yard split, and estimated max velocity. Directly "
     "relevant to baserunning and defensive range, and a useful cross-check against lower body "
     "strength and power numbers -- strength gains that don't show up in speed testing may not be "
     "transferring to the field yet."),
    ("Pitcher-Specific (Pitch Characteristics)", "13 metrics via Rapsodo, per pitch",
     "Velocity, spin rate, spin efficiency, spin axis, horizontal/vertical break, release point, "
     "extension, approach angle, and plate location -- captured pitch by pitch. This is what "
     "separates raw arm strength from actual pitch effectiveness: two pitchers can throw the same "
     "velocity, but movement, spin, and location are what determine how hittable each pitch actually is."),
    ("Baseball Performance", "reserved for future use",
     "A placeholder category for future performance metrics not yet defined -- kept open rather than "
     "removed so it's ready whenever the program decides what belongs here."),
]

_GUEST_DASHBOARDS = [
    ("Head Coach / Coach / Administrator", "A general overview: roster size, open IDP goals, "
     "recent assessments and training sessions, and week-over-week trend deltas."),
    ("Strength Coach", "S&C-specific: recent Upper/Lower Body Strength, Explosive Power, and "
     "Rotational Power assessments, lifting session workload, and upcoming scheduled lifts."),
    ("Athletic Trainer", "Injury and return-to-play focus: a live count of injured/medical-hold "
     "players, recent Arm Health pain and readiness scores, and recent Arm Care sessions."),
    ("Player", "Their own upcoming week: team schedule, their prescribed assignments, and their "
     "Athletic Trainer appointments."),
]


def _guest_ui():
    # Mirrors the original app.py's guest mode (pages/guest_overview.py)
    # -- a curated, illustrative walkthrough of the platform's vision,
    # NOT a real login and NOT connected to the actual database. Guests
    # see example numbers and module descriptions only, never real
    # player data -- privacy first, even for a low-stakes "show the
    # vision" mode. Plain function (not a module) since it has no state
    # of its own beyond the one "Go to login" button, whose click
    # handler lives in server() below (app_state isn't in scope here).
    return ui.div(
        ui_helpers.page_header("Gorilla Baseball Operations"),
        ui.p(
            "A comprehensive player development platform for Pittsburg State Gorilla Baseball -- "
            "combining physical testing, individual development plans, training logs, scheduling, "
            "and role-based dashboards in one place. Below is a detailed look at everything the "
            "platform does."
        ),
        ui.p("You're viewing example data as a guest -- this is not connected to real player records.", class_="text-muted small"),

        ui.hr(),
        ui.h5("Example: what a coach sees at a glance", class_="gbo-section-title"),
        ui_helpers.render_kpi_cards([
            {"label": "Players", "value": "24"},
            {"label": "Open IDP Goals", "value": "12", "delta": "3 vs last week", "delta_positive": False},
            {"label": "Assessments (7 days)", "value": "18", "delta": "5 vs last week", "delta_positive": True},
            {"label": "Training Sessions (7 days)", "value": "31", "delta": "8 vs last week", "delta_positive": True},
        ]),

        ui.hr(),
        ui.h4("Player Management"),
        ui.p(
            "The full team roster: name, photo, jersey number, position, class, graduation year, "
            "throws/bats, height, weight, hometown, high school, and status (Active, Injured, Redshirt, "
            "Medical Hold, Inactive). Searchable, filterable, sortable, and exportable to CSV. This is the "
            "single source of truth every other module builds on -- assessments, goals, and sessions are "
            "all tied back to a specific player record here."
        ),

        ui.hr(),
        ui.h4("Assessments — 10 categories of physical testing"),
        ui.p(
            "Every category below supports full history (not just a snapshot) -- a player can be tested "
            "the same way repeatedly over months or years, and the platform tracks trends (Count, Average, "
            "Max, Min) automatically. Here's what each one measures and why it matters:"
        ),
        ui.accordion(*[
            ui.accordion_panel(f"{name} — {count_label}", ui.p(explanation))
            for name, count_label, explanation in _GUEST_ASSESSMENT_CATEGORIES
        ], open=False, id=None),

        ui.hr(),
        ui.h4("Individual Development Plans (IDP)"),
        ui.p(
            "A development goal isn't just a note -- it's tied to a specific assessment category, and can "
            "link directly to the exact assessment record that motivated it (e.g. a shoulder mobility deficit "
            "found on a specific date). Each goal can carry action steps (specific tasks with due dates and "
            "status) and progress notes (dated commentary from staff). Training Sessions can be tagged as "
            "'prescribed toward' a specific goal, so a coach can open any goal and see the actual work that's "
            "been logged against it -- not just a plan, but a running record of follow-through."
        ),

        ui.hr(),
        ui.h4("Training Sessions"),
        ui.p(
            "A day-to-day log of what actually happened: arm care, lifting, conditioning, hitting drills, or "
            "throwing/plyometric work, each with notes, optional player feedback, and next steps. This is "
            "distinct from a formal Assessment (which is periodic testing) -- it's the daily diary that shows "
            "consistency and follow-through over time, and each entry can optionally be linked back to a "
            "specific IDP goal."
        ),

        ui.hr(),
        ui.h4("Team Schedule, Player Assignments & AT Appointments"),
        ui.p(
            ui.strong("Team Schedule"), " is a shared calendar for team-wide events -- lift days, practices, games. ",
            ui.strong("Player Assignments"), " are forward-looking, prescribed tasks for a specific player (e.g. \"today: "
            "throwing program\"), assigned ahead of time by a coach or Athletic Trainer -- separate from the "
            "Training Sessions log of completed work. ", ui.strong("Athletic Trainer Appointments"), " are real, timed "
            "appointments between a specific player and a specific Athletic Trainer. Together, these give "
            "every player a clear picture of what's coming up -- team commitments, individual prescribed work, "
            "and medical appointments -- all in one place on their own dashboard."
        ),

        ui.hr(),
        ui.h4("Rapsodo & Video Integration"),
        ui.p(
            "Bulk-import an entire Rapsodo pitching session in one upload instead of typing in every pitch "
            "by hand -- the platform maps columns automatically (with sensible pre-filled guesses), converts "
            "units where needed (like spin axis from clock format to degrees), and creates one record per "
            "pitch. Any individual pitch can then have video uploaded and linked directly to it, so a coach "
            "can pull up the exact numbers for a pitch side-by-side with the actual footage -- comparing what "
            "the data says against what the eye sees."
        ),

        ui.hr(),
        ui.h4("Role-Based Dashboards"),
        ui.p("Every role sees a dashboard built around what actually matters for their job, all pulling from the same underlying data:"),
        *[
            ui.div(ui.p(ui.strong(role)), ui.p(desc), ui.br())
            for role, desc in _GUEST_DASHBOARDS
        ],

        ui.hr(),
        ui.p("Ready to see the real thing? Log in with a GBO account using the button below.", class_="text-muted"),
        ui.input_action_button("guest_back_to_login", "Go to login", class_="btn-primary"),

        ui_helpers.page_footer(),
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
    ("Overview", ["dashboard"]),
    ("Roster", ["roster", "player_profile", "players"]),
    ("Development", ["assessments", "idp", "training_routines", "player_assignments", "team_schedule", "at_appointments"]),
    ("Pitching", ["bullpen_dashboard", "bullpen_tracking", "bullpen_scripts", "rapsodo_import"]),
    ("Hitting", ["hitter_tracking"]),
    ("Games", ["game_tracking", "pitcher_game_report", "hitter_game_report", "analytics"]),
    ("Scouting", ["opponent_teams"]),
    ("Admin", ["user_management", "staff_assignments", "video_import"]),
    ("Me", ["player_profile", "player_schedule", "player_development", "player_stats", "player_game_stats", "player_hitting", "player_video", "player_bullpens"]),
]
_NAV_LABELS = {
    "players": "Player setup", "roster": "Players", "idp": "Development plans", "rapsodo_import": "Import Rapsodo",
    "analytics": "Player stats", "at_appointments": "AT appointments", "player_assignments": "Assignments",
    "team_schedule": "Team schedule", "user_management": "Users", "staff_assignments": "Staff assignments",
}
_ICONS = {
    "roster": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0113 0M16 4a3.5 3.5 0 010 7M21.5 20a6.5 6.5 0 00-5-6.3"/>',
    "player_profile": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0"/>',
    "dashboard": '<path d="M3 11l9-7 9 7v9a1 1 0 01-1 1h-5v-6H9v6H4a1 1 0 01-1-1z"/>',
    "players": '<path d="M12 20h9M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4z"/>',
    "assessments": '<path d="M9 4h6v3H9zM7 6H5v15h14V6h-2M8 13l2 2 5-5"/>',
    "idp": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
    "training_routines": '<path d="M4 12h3l2-6 4 12 2-6h5"/>',
    "player_assignments": '<path d="M5 5h14v14H5zM8 12l3 3 5-6"/>',
    "team_schedule": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "at_appointments": '<path d="M12 4v16M4 12h16"/><rect x="3" y="3" width="18" height="18" rx="3"/>',
    "bullpen_dashboard": '<path d="M4 20V9M10 20V4M16 20v-8M22 20H2"/>',
    "bullpen_tracking": '<circle cx="12" cy="12" r="8"/><path d="M8 8c2 2 2 6 0 8M16 8c-2 2-2 6 0 8"/>',
    "bullpen_scripts": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6"/>',
    "rapsodo_import": '<path d="M12 3v12M7 10l5 5 5-5M4 21h16"/>',
    "hitter_tracking": '<path d="M4 20L18 6l2 2L6 22zM15 3l6 6"/>',
    "game_tracking": '<path d="M12 3l8 8-8 10-8-10z"/><path d="M12 3v18M4 11h16"/>',
    "pitcher_game_report": '<path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/>',
    "hitter_game_report": '<path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/>',
    "analytics": '<path d="M3 17l6-6 4 4 8-8M14 7h7v7"/>',
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


def _app_shell_ui(app_state):
    sections = nav.build_nav_sections(
        app_state.role_name(), app_state.coach_specialty(), app_state.is_pitcher()
    )
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
            ui.input_action_button("logout_button", "Log out", class_="btn-sm btn-outline-light"),
            class_="gbo-top-right",
        ),
        class_="gbo-top",
    )

    return ui.div(
        sidebar,
        ui.div(
            topbar,
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