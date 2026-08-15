"""
GBO -- per-session app state for the Shiny UI.

This is the Shiny analogue of the st.session_state.gbo_* keys the
original Streamlit app.py set after login/role lookup. Every field is a
reactive.Value so page modules can react to login/logout/role changes
without polling for them.

IMPORTANT: an AppState instance must be created INSIDE the top-level
server() function (once per browser session, via new_app_state()),
never at module import time. A reactive.Value created at import time is
shared by every user connected to the running app process; one created
inside server() is private to that one session. Getting this wrong is
the single easiest way to leak one coach's screen into another's.
"""

from dataclasses import dataclass

from shiny import reactive


@dataclass
class AppState:
    auth_user: reactive.Value       # Supabase auth user object, or None
    auth_error: reactive.Value      # str | None -- login failure message
    is_guest: reactive.Value        # bool

    user_id: reactive.Value         # int | None -- GBO users.user_id
    first_name: reactive.Value      # str | None
    last_name: reactive.Value       # str | None
    role_name: reactive.Value       # str | None, e.g. "Head Coach"
    can_view_all_players: reactive.Value
    can_edit_assessments: reactive.Value
    can_edit_sessions: reactive.Value
    coach_specialty: reactive.Value  # str | None
    is_pitcher: reactive.Value       # bool -- only meaningful for role "Player"

    # "dark" | "light" -- synced from ui.input_dark_mode() in app.py.
    # Deliberately NOT touched by reset() -- a user's light/dark
    # preference should survive login/logout, unlike every other field
    # here which is identity/role state tied to the authenticated user.
    dark_mode: reactive.Value

    def is_authenticated(self) -> bool:
        """True once Supabase login succeeded AND a matching, active GBO
        users row was found (role_name gets set only then)."""
        return self.auth_user() is not None and self.role_name() is not None

    def is_pending_setup(self) -> bool:
        """Logged in via Supabase, but no matching GBO users row --
        mirrors the original app.py's account_not_set_up_page state."""
        return self.auth_user() is not None and self.role_name() is None

    def reset(self):
        """Clear everything back to logged-out state (used on logout)."""
        self.auth_user.set(None)
        self.auth_error.set(None)
        self.is_guest.set(False)
        self.user_id.set(None)
        self.first_name.set(None)
        self.last_name.set(None)
        self.role_name.set(None)
        self.can_view_all_players.set(False)
        self.can_edit_assessments.set(False)
        self.can_edit_sessions.set(False)
        self.coach_specialty.set(None)
        self.is_pitcher.set(False)


def new_app_state() -> AppState:
    """Factory -- call this ONCE inside server(), never at module scope."""
    return AppState(
        auth_user=reactive.Value(None),
        auth_error=reactive.Value(None),
        is_guest=reactive.Value(False),
        user_id=reactive.Value(None),
        first_name=reactive.Value(None),
        last_name=reactive.Value(None),
        role_name=reactive.Value(None),
        can_view_all_players=reactive.Value(False),
        can_edit_assessments=reactive.Value(False),
        can_edit_sessions=reactive.Value(False),
        coach_specialty=reactive.Value(None),
        is_pitcher=reactive.Value(False),
        dark_mode=reactive.Value("dark"),
    )
