"""
GBO -- role-based navigation shell for the Shiny app.

Direct port of the `pages` dict construction in the original Streamlit
app.py (the role_name in (...) blocks after the sidebar, lines ~192-325)
-- same role -> section -> page rules, same page ordering, same
specialty-based inclusion/exclusion logic (Hitting/Pitching coach
specialty, Sports Scientist/Data Analyst read-only visibility, the
pitcher-vs-hitter split for Player nav, etc.). Ported here as *data*
(build_nav_sections() below) instead of imperative st.Page() calls, so
the role-gating logic is reviewable on its own, independent of which
individual pages have a working Shiny module behind them yet.

`key` on each NavPage matches a page module's name once it's migrated
(see modules/ and MODULE_UI in shiny_app/app.py). Until a page is
migrated, app.py renders a "not yet migrated" placeholder for it instead
of failing -- that's what lets the full nav shape be wired up and
reviewed now, with real modules swapped in one at a time.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class NavPage:
    key: str
    title: str
    icon: Optional[str] = None  # bootstrap-icons name, optional


@dataclass
class NavSection:
    title: str
    pages: list


def build_nav_sections(role_name: str, coach_specialty: Optional[str], is_pitcher_player: bool) -> list:
    """Same role -> nav mapping as the original app.py. role_name is
    required (callers should only reach this once AppState.is_authenticated()
    is True); coach_specialty/is_pitcher_player mirror the same two
    fields the original read off current_user."""
    sections = [NavSection("Dashboard", [NavPage("dashboard", "Dashboard", "house")])]

    if role_name in ("Administrator", "Head Coach", "Coach", "Strength Coach", "Athletic Trainer", "Sports Scientist", "Data Analyst"):
        pd_pages = [
            NavPage("players", "Players", "person"),
            NavPage("assessments", "Assessments", "clipboard-check"),
            NavPage("pitch_video", "Video Review", "camera-video"),
            NavPage("idp", "IDP", "bullseye"),
            NavPage("team_schedule", "Team Schedule", "calendar3"),
            NavPage("player_assignments", "Player Assignments", "check2-square"),
            NavPage("training_routines", "Training Routines", "activity"),
        ]

        # AT Appointments isn't sports-science-relevant -- everyone else
        # with Player Development access still sees it (same rule as
        # the original: privacy-scoped inside the page itself, not here).
        if role_name != "Sports Scientist":
            pd_pages.append(NavPage("at_appointments", "Athletic Trainer Appointments", "hospital"))

        # Import Rapsodo Data / Bullpen Tracking / Bullpen Scripts /
        # Bullpen Dashboard are pitching-side tools -- hidden from
        # Strength Coach, Athletic Trainer, and a Coach specifically
        # tagged Hitting (a Coach tagged Pitching/Both/unset still sees
        # them, same as Administrator/Head Coach). Sports Scientist and
        # Data Analyst get read-only visibility -- their
        # can_edit_sessions permission is already False at the role
        # level, so the migrated pages themselves render read-only.
        show_bullpen_pages = role_name in ("Administrator", "Head Coach") or (
            role_name == "Coach" and coach_specialty != "Hitting"
        )
        if show_bullpen_pages:
            pd_pages.insert(2, NavPage("rapsodo_import", "Import Rapsodo Data", "upload"))
        if show_bullpen_pages or role_name in ("Sports Scientist", "Data Analyst"):
            pd_pages.extend([
                NavPage("bullpen_tracking", "Bullpen Tracking", "trophy"),
                NavPage("bullpen_scripts", "Bullpen Scripts", "calendar-event"),
                NavPage("bullpen_dashboard", "Bullpen Dashboard", "bar-chart"),
            ])

        # Hitter Tracking is hitting-side -- mirror-opposite exclusion
        # from Bullpen Tracking: hidden from a Coach tagged Pitching.
        # Same read-only visibility for Sports Scientist/Data Analyst.
        show_hitter_tracking = role_name in ("Administrator", "Head Coach") or (
            role_name == "Coach" and coach_specialty != "Pitching"
        )
        if show_hitter_tracking or role_name in ("Sports Scientist", "Data Analyst"):
            pd_pages.append(NavPage("hitter_tracking", "Hitter Tracking", "trophy"))

        sections.append(NavSection("Player Development", pd_pages))

    # Game Operations, Scouting, Analytics -- not specialty-restricted
    # (a game always involves both pitching and hitting). Data Analyst
    # gets real edit rights on Game Tracking/Opponent Teams specifically
    # (a page-level override inside those two pages once migrated, not
    # a nav-level concern). Sports Scientist stays read-only.
    if role_name in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
        sections.append(NavSection("Game Operations", [NavPage("game_tracking", "Game Tracking", "clipboard-data")]))
        sections.append(NavSection("Scouting", [NavPage("opponent_teams", "Opponent Teams", "people")]))
        sections.append(NavSection("Analytics", [
            NavPage("analytics", "Player Stats", "graph-up"),
            NavPage("pitcher_game_report", "Pitcher Game Report", "file-text"),
            NavPage("hitter_game_report", "Hitter Game Report", "trophy"),
        ]))

    if role_name == "Administrator":
        sections.append(NavSection("Administration", [
            NavPage("user_management", "User Management", "gear"),
            NavPage("staff_assignments", "Staff Assignments", "link-45deg"),
        ]))
    elif role_name == "Head Coach":
        sections.append(NavSection("Administration", [NavPage("staff_assignments", "Staff Assignments", "link-45deg")]))

    if role_name == "Player":
        my_dev_pages = [
            NavPage("player_schedule", "My Schedule", "calendar3"),
            NavPage("player_development", "My Development", "bullseye"),
            NavPage("player_stats", "My Assessments", "graph-up"),
            NavPage("player_game_stats", "My Stats", "bar-chart"),
            NavPage("player_video", "My Video", "camera-video"),
            # Same page coaches use to build/edit routines -- already
            # correctly read-only for non-edit-capable roles once
            # migrated, so this stays a single shared page, not a
            # separate player-facing copy.
            NavPage("training_routines", "Training Routines", "activity"),
        ]
        # My Bullpens is pitcher-specific; My Hitting is the mirror-
        # opposite for position players -- only one shows, based on the
        # player's own is_pitcher flag (same as the original).
        if is_pitcher_player:
            my_dev_pages.append(NavPage("player_bullpens", "My Bullpens", "trophy"))
        else:
            my_dev_pages.append(NavPage("player_hitting", "My Hitting", "trophy"))
        sections.append(NavSection("My Development", my_dev_pages))

    return sections
