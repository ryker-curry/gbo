"""
GBO -- Shiny auth: Supabase email/password login + GBO role lookup.

Direct port of the auth section of the original Streamlit app.py
(do_login/do_logout + the role lookup that followed a successful
login) -- same Supabase call, same database.py/models.py query, same
role/permission fields read off the User/Role/Player models. Only the
"how do I show a message" / "how do I trigger a re-render" mechanics
change: Shiny reactivity instead of st.session_state + st.rerun().

Uses database.py/models.py/supabase_client.py completely unchanged --
those are part of the analytics-engine boundary this migration
preserves, not something auth-specific to rewrite.

DIAGNOSED (Sept 2026): the "login succeeds but lands on account-not-
set-up" reports traced to email casing -- Supabase Auth normalizes
emails to lowercase, but GBO's own user_management.py account-creation
flow only .strip()'d the typed email, so any account created with a
capital letter never matched here. _load_gbo_role below now normalizes
auth_email before the lookup, user_management.py normalizes on create/
edit, and scripts/backfill_lowercase_user_emails.py fixes rows created
before this fix. The temporary [GBO LOGIN DEBUG]/[GBO LOGIN ERROR]
print() block that was here while this was being chased has been
removed now that it's diagnosed and fixed.
"""

from sqlalchemy.orm import joinedload

from database import get_session
from models import User
from supabase_client import get_supabase_client


def do_login(app_state, email: str, password: str):
    """Same Supabase sign_in_with_password call as the original
    do_login(). On success, looks up the matching GBO user row in the
    same step (the original app.py did this on the *next* Streamlit
    script rerun; here it happens inline since Shiny has no "next
    rerun" to lean on -- reactive.Value.set() below is what actually
    triggers the UI to update)."""
    try:
        supabase = get_supabase_client()
        result = supabase.auth.sign_in_with_password({"email": email, "password": password})
    except Exception:
        app_state.auth_user.set(None)
        app_state.auth_error.set("Login failed. Check your email and password and try again.")
        return

    app_state.auth_user.set(result.user)
    app_state.auth_error.set(None)
    _load_gbo_role(app_state, result.user.email)


def do_logout(app_state):
    supabase = get_supabase_client()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    app_state.reset()


def _load_gbo_role(app_state, auth_email: str):
    """Same query as the original app.py: look up the active GBO user
    row matching the Supabase auth email, with role + player eager-
    loaded. Sets app_state fields on success; leaves role_name unset
    (None) if there's no matching row -- AppState.is_pending_setup()
    treats that as "account not set up yet", same as the original
    account_not_set_up_page().

    auth_email is lowercased before the lookup -- Supabase Auth
    normalizes emails to lowercase, and User.email is now written
    lowercase too (see user_management.py), but this normalizes the
    read side independently rather than assuming both sides agree."""
    auth_email = (auth_email or "").strip().lower()
    session = get_session()
    try:
        current_user = (
            session.query(User)
            .options(joinedload(User.role), joinedload(User.player))
            .filter(User.email == auth_email, User.active.is_(True))
            .first()
        )
    finally:
        session.close()

    if current_user is None:
        return  # role_name stays None -> "account not set up" state

    app_state.user_id.set(current_user.user_id)
    app_state.first_name.set(current_user.first_name)
    app_state.last_name.set(current_user.last_name)
    app_state.role_name.set(current_user.role.role_name)
    app_state.can_view_all_players.set(current_user.role.can_view_all_players)
    app_state.can_edit_assessments.set(current_user.role.can_edit_assessments)
    app_state.can_edit_sessions.set(current_user.role.can_edit_sessions)
    app_state.coach_specialty.set(current_user.coach_specialty)
    app_state.is_pitcher.set(current_user.player.is_pitcher if current_user.player else False)
