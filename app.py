"""
GBO — Streamlit entry point.

Auth: Supabase email/password (switched from Microsoft Entra because
Ryker does not have Pitt State Azure/IT admin access to register an
Entra app -- the Aug 17 deadline can't depend on an external IT approval
process). Each GBO user gets a dedicated Supabase account (email +
password), separate from their Pitt State Microsoft login.

st.navigation() is called on every run (login screen included) so
Streamlit never falls back to its own automatic pages/-folder sidebar --
that auto-sidebar bypasses our role-based menu and login gate entirely,
so we keep st.navigation() in control from the very first screen.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import User
from supabase_client import get_supabase_client, get_supabase_admin_client

st.set_page_config(page_title="Gorilla Baseball Operations", page_icon="assets/GBO_logo-06.png", layout="wide")

if "gbo_auth_user" not in st.session_state:
    st.session_state.gbo_auth_user = None
if "gbo_auth_error" not in st.session_state:
    st.session_state.gbo_auth_error = None
if "gbo_is_guest" not in st.session_state:
    st.session_state.gbo_is_guest = False


def do_login(email: str, password: str):
    supabase = get_supabase_client()
    try:
        result = supabase.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        st.session_state.gbo_auth_user = result.user
        st.session_state.gbo_auth_error = None
    except Exception:
        st.session_state.gbo_auth_user = None
        st.session_state.gbo_auth_error = "Login failed. Check your email and password and try again."


def do_logout():
    supabase = get_supabase_client()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    st.session_state.gbo_auth_user = None
    st.session_state.gbo_auth_error = None


def login_page():
    st.markdown(
        '<style>'
        '.gbo-login-title { text-align: center; font-size: 2rem; font-weight: 800; '
        'color: #FFFDE5; margin-top: 8px; margin-bottom: 4px; }'
        '.gbo-login-tagline { text-align: center; color: #B8B8B8; margin-bottom: 28px; }'
        '</style>',
        unsafe_allow_html=True,
    )

    _, center_col, _ = st.columns([1, 1.2, 1])
    with center_col:
        _, logo_col, _ = st.columns([1, 1, 1])
        with logo_col:
            st.image("assets/GBO_logo-06.png", width=180)

        st.markdown('<div class="gbo-login-title">Gorilla Baseball Operations</div>', unsafe_allow_html=True)
        st.markdown('<div class="gbo-login-tagline">Log in with your GBO account</div>', unsafe_allow_html=True)

        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in", use_container_width=True)

        if submitted:
            do_login(email, password)
            st.rerun()

        if st.session_state.gbo_auth_error:
            st.error(st.session_state.gbo_auth_error)

        st.caption("Don't have an account yet? Contact an administrator to be added.")

        st.divider()
        st.caption("Just want to see what GBO looks like?")
        if st.button("Continue as Guest", use_container_width=True):
            st.session_state.gbo_is_guest = True
            st.rerun()


def account_not_set_up_page():
    st.error(
        "Your account is not yet set up in GBO. "
        "Contact an administrator to be added before you can continue."
    )
    st.button("Log out", on_click=do_logout)


# --- Guest mode: curated overview, no real auth, no real data -----------
if st.session_state.gbo_is_guest:
    pg = st.navigation([st.Page("pages/guest_overview.py", title="Guest Overview")], position="hidden")
    pg.run()
    st.stop()

# --- Not logged in: show only the login screen, sidebar hidden -----------
if st.session_state.gbo_auth_user is None:
    pg = st.navigation([st.Page(login_page, title="Login")], position="hidden")
    pg.run()
    st.stop()

# --- Look up the logged-in user's GBO role -----------------------------
auth_email = st.session_state.gbo_auth_user.email

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

# --- Logged in via Supabase, but no matching GBO users row --------------
if current_user is None:
    pg = st.navigation([st.Page(account_not_set_up_page, title="Account Pending")], position="hidden")
    pg.run()
    st.stop()

role_name = current_user.role.role_name

# Make identity/permission info available to sub-pages (they run in a
# separate module scope, so local variables here aren't visible to them).
st.session_state.gbo_user_id = current_user.user_id
st.session_state.gbo_user_first_name = current_user.first_name
st.session_state.gbo_user_last_name = current_user.last_name
st.session_state.gbo_role_name = role_name
st.session_state.gbo_can_view_all_players = current_user.role.can_view_all_players
st.session_state.gbo_can_edit_assessments = current_user.role.can_edit_assessments
st.session_state.gbo_can_edit_sessions = current_user.role.can_edit_sessions
st.session_state.gbo_coach_specialty = current_user.coach_specialty

# --- Sidebar: identity + logout -----------------------------------------
with st.sidebar:
    st.markdown(
        '<style>'
        'section[data-testid="stSidebar"] .stSelectbox, '
        'section[data-testid="stSidebar"] h3 { margin-top: 4px; }'
        'section[data-testid="stSidebar"] [data-testid="stPageLink"] { margin-bottom: 2px; }'
        '.gbo-role-badge { display: inline-block; background: #BF1E2D; color: #FFFDE5; '
        'font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.03em; '
        'padding: 3px 10px; border-radius: 12px; margin: 4px 0 10px 0; }'
        '</style>',
        unsafe_allow_html=True,
    )
    st.image("assets/GBO_logo-06.png", width=100)
    st.write(f"**{current_user.first_name} {current_user.last_name}**")
    st.markdown(f'<div class="gbo-role-badge">{role_name}</div>', unsafe_allow_html=True)
    st.button("Log out", on_click=do_logout)

    with st.expander("Change my password"):
        with st.form("change_password_form"):
            new_password = st.text_input("New password (min 6 characters)", type="password", key="my_new_pw")
            confirm_password = st.text_input("Confirm new password", type="password", key="my_confirm_pw")
            change_submitted = st.form_submit_button("Change password")

        if change_submitted:
            if len(new_password) < 6:
                st.error("Password must be at least 6 characters.")
            elif new_password != confirm_password:
                st.error("Passwords do not match.")
            elif not current_user.auth_subject_id:
                st.error("Unable to update password -- account isn't fully set up. Contact an administrator.")
            else:
                try:
                    admin_client = get_supabase_admin_client()
                    admin_client.auth.admin.update_user_by_id(
                        current_user.auth_subject_id, {"password": new_password}
                    )
                    st.success("Password updated.")
                except Exception as e:
                    st.error(f"Failed to update password: {e}")

    st.divider()

# --- Role-based navigation shell -----------------------------------------
pages = {"Dashboard": [st.Page("pages/dashboard.py", title="Dashboard", url_path="dashboard", icon=":material/home:")]}

if role_name in ("Administrator", "Head Coach", "Coach", "Strength Coach", "Athletic Trainer", "Sports Scientist", "Data Analyst"):
    pages["Player Development"] = [
        st.Page("pages/players.py", title="Players", url_path="players", icon=":material/person:"),
        st.Page("pages/assessments.py", title="Assessments", url_path="assessments", icon=":material/assignment:"),
        st.Page("pages/pitch_video.py", title="Video Review", url_path="pitch-video", icon=":material/videocam:"),
        st.Page("pages/idp.py", title="IDP", url_path="idp", icon=":material/track_changes:"),
        st.Page("pages/team_schedule.py", title="Team Schedule", url_path="team-schedule", icon=":material/calendar_month:"),
        st.Page("pages/player_assignments.py", title="Player Assignments", url_path="player-assignments", icon=":material/task_alt:"),
        st.Page("pages/training_routines.py", title="Training Routines", url_path="training-routines", icon=":material/fitness_center:"),
    ]

    # AT Appointments isn't sports-science-relevant -- everyone else with
    # Player Development access still sees it (privacy-scoped separately
    # inside the page itself).
    if role_name != "Sports Scientist":
        pages["Player Development"].append(
            st.Page("pages/at_appointments.py", title="Athletic Trainer Appointments", url_path="at-appointments", icon=":material/medical_services:"),
        )

    # Import Rapsodo Data is Rapsodo/pitching-side data -- same
    # Hitting-specialty exclusion as Bullpen Tracking/Scripts below.
    if show_bullpen_pages := (role_name in ("Administrator", "Head Coach") or (
        role_name == "Coach" and current_user.coach_specialty != "Hitting"
    )):
        pages["Player Development"].insert(2, st.Page("pages/import_rapsodo.py", title="Import Rapsodo Data", url_path="import-rapsodo", icon=":material/upload_file:"))

    # Bullpen Tracking/Scripts are pitching-side tools -- not relevant to
    # Strength Coach, Athletic Trainer, or a Coach specifically tagged
    # Hitting (a Coach tagged Pitching/Both/unset still sees them, same
    # as Administrator/Head Coach). Sports Scientist and Data Analyst
    # get read-only visibility -- their can_edit_sessions permission is
    # already False at the role level, so the pages themselves render
    # read-only automatically with no further changes needed.
    if show_bullpen_pages or role_name in ("Sports Scientist", "Data Analyst"):
        pages["Player Development"].extend([
            st.Page("pages/bullpen_tracking.py", title="Bullpen Tracking", url_path="bullpen-tracking", icon=":material/sports_baseball:"),
            st.Page("pages/bullpen_scripts.py", title="Bullpen Scripts", url_path="bullpen-scripts", icon=":material/edit_calendar:"),
        ])

    # Hitter Tracking is hitting-side -- mirror-opposite exclusion from
    # Bullpen Tracking: hidden from a Coach tagged Pitching (Pitching/
    # Both/unset for Bullpen, Hitting/Both/unset here). Same read-only
    # visibility for Sports Scientist/Data Analyst as above.
    show_hitter_tracking = role_name in ("Administrator", "Head Coach") or (
        role_name == "Coach" and current_user.coach_specialty != "Pitching"
    )
    if show_hitter_tracking or role_name in ("Sports Scientist", "Data Analyst"):
        pages["Player Development"].append(
            st.Page("pages/hitter_tracking.py", title="Hitter Tracking", url_path="hitter-tracking", icon=":material/sports_baseball:"),
        )

    # Game Tracking covers BOTH sides of the ball (our hitting AND our
    # pitching in the same game) -- not specialty-restricted like
    # Bullpen/Hitter Tracking, since a game always involves both. Same
    # read-only visibility for Sports Scientist/Data Analyst.
    if role_name in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
        pages["Player Development"].append(
            st.Page("pages/game_tracking.py", title="Game Tracking", url_path="game-tracking", icon=":material/scoreboard:"),
        )

if role_name == "Administrator":
    pages["Administration"] = [
        st.Page("pages/user_management.py", title="User Management", url_path="user-management", icon=":material/settings:"),
        st.Page("pages/staff_assignments.py", title="Staff Assignments", url_path="staff-assignments", icon=":material/link:"),
    ]
elif role_name == "Head Coach":
    pages["Administration"] = [
        st.Page("pages/staff_assignments.py", title="Staff Assignments", url_path="staff-assignments", icon=":material/link:"),
    ]

if role_name == "Player":
    pages["My Development"] = [
        st.Page("pages/player_schedule.py", title="My Schedule", url_path="my-schedule", icon=":material/calendar_month:"),
        st.Page("pages/player_development.py", title="My Development", url_path="my-development", icon=":material/track_changes:"),
        st.Page("pages/player_stats.py", title="My Assessments", url_path="my-stats", icon=":material/query_stats:"),
        st.Page("pages/player_video.py", title="My Video", url_path="my-video", icon=":material/videocam:"),
    ]
    # My Bullpens is pitcher-specific (Bullpen Tracking's own player-facing
    # view); My Hitting is the mirror-opposite for position players. Only
    # one should show for a given player, based on their own is_pitcher flag.
    is_pitcher_player = current_user.player.is_pitcher if current_user.player else False
    if is_pitcher_player:
        pages["My Development"].append(
            st.Page("pages/player_bullpens.py", title="My Bullpens", url_path="my-bullpens", icon=":material/sports_baseball:"),
        )
    else:
        pages["My Development"].append(
            st.Page("pages/player_hitting.py", title="My Hitting", url_path="my-hitting", icon=":material/sports_baseball:"),
        )

navigation = st.navigation(pages)
navigation.run()