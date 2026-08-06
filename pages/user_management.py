"""
GBO — User Management (Milestone: Aug 14-15).

Administrator-only. Replaces the terminal scripts (create_admin_user.py,
create_staff_user.py, set_password.py) with a real in-app screen:
  - View all users and their roles/status
  - Create a new user (any role, including Player -- linked to an
    existing roster player)
  - Edit an existing user's role or active status
  - Reset a user's password

Creating an account and resetting a password both call the Supabase
Admin API (service role key) -- same mechanism the terminal scripts used.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from sqlalchemy.orm import joinedload

from database import get_session
from models import User, Role, Organization, Player
from supabase_client import get_supabase_admin_client

page_header("User Management")

role_name = st.session_state.get("gbo_role_name")

if role_name != "Administrator":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

session = get_session()
try:
    users = (
        session.query(User)
        .options(joinedload(User.role), joinedload(User.player))
        .order_by(User.active.desc(), User.last_name, User.first_name)
        .all()
    )
    roles = session.query(Role).order_by(Role.role_id).all()
    org = session.query(Organization).first()

    st.subheader("All users")
    st.dataframe(
        [
            {
                "Name": f"{u.first_name} {u.last_name}",
                "Email": u.email,
                "Role": u.role.role_name if u.role else "—",
                "Specialty": u.coach_specialty or "—",
                "Linked Player": f"{u.player.first_name} {u.player.last_name}" if u.player else "—",
                "Active": "Yes" if u.active else "No",
            }
            for u in users
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.subheader("Create a new user")

    # Role lives outside the form so the player-picker below can react
    # immediately when "Player" is chosen -- widgets inside st.form don't
    # rerun the app until submit, so the picker would only appear at the
    # same instant you click Create, defaulting to the first player with
    # no chance to actually pick someone else.
    role_choice = st.selectbox("Role", [r.role_name for r in roles], key="create_user_role")

    linked_player_id = None
    coach_specialty_choice = None
    if role_choice == "Player":
        eligible_players = session.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
        if eligible_players:
            players_by_id = {p.player_id: p for p in eligible_players}
            linked_player_id = st.selectbox(
                "Which player is this account for?",
                options=list(players_by_id.keys()),
                format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                key="create_user_linked_player",
            )
        else:
            st.warning("No players exist on the roster yet -- add one first from the Players page.")
    elif role_choice == "Coach":
        coach_specialty_choice = st.selectbox(
            "Specialty",
            ["Both", "Pitching", "Hitting"],
            key="create_user_specialty",
            help="Filters which Training Routines this coach sees -- Pitching coaches won't see hitting-only routines and vice versa. Shared categories (Lifting, Conditioning, Mobility, Med Ball, General) are visible either way.",
        )

    with st.form("create_user_form"):
        c1, c2 = st.columns(2)
        first_name = c1.text_input("First name")
        last_name = c2.text_input("Last name")
        email = st.text_input("Email (their GBO login)")
        password = st.text_input("Initial password (min 6 characters)", type="password")
        submitted = st.form_submit_button("Create user", type="primary")

    if submitted:
        if not (first_name.strip() and last_name.strip() and email.strip() and len(password) >= 6):
            st.error("First name, last name, email, and a password of at least 6 characters are required.")
        elif org is None:
            st.error("No organization exists yet.")
        elif role_choice == "Player" and linked_player_id is None:
            st.error("Select which player this account is for.")
        elif session.query(User).filter(User.email == email.strip()).first():
            st.error(f"A user with email {email.strip()} already exists.")
        else:
            try:
                admin_client = get_supabase_admin_client()
                auth_result = admin_client.auth.admin.create_user(
                    {"email": email.strip(), "password": password, "email_confirm": True}
                )
                role = next(r for r in roles if r.role_name == role_choice)
                new_user = User(
                    organization_id=org.organization_id,
                    auth_subject_id=auth_result.user.id,
                    email=email.strip(),
                    first_name=first_name.strip(),
                    last_name=last_name.strip(),
                    role_id=role.role_id,
                    player_id=linked_player_id,
                    coach_specialty=coach_specialty_choice,
                    active=True,
                )
                session.add(new_user)
                session.commit()
                st.success(f"Created {role_choice} account for {first_name.strip()} {last_name.strip()}.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to create account: {e}")

    st.divider()
    st.subheader("Edit an existing user")

    if not users:
        empty_state("No users to edit yet.")
    else:
        users_by_id = {u.user_id: u for u in users}
        selected_user_id = st.selectbox(
            "Select a user",
            options=list(users_by_id.keys()),
            format_func=lambda uid: f"{users_by_id[uid].first_name} {users_by_id[uid].last_name} ({users_by_id[uid].email})",
        )
        editing_user = users_by_id[selected_user_id]

        # Role selection lives outside the form so the player-link picker
        # below can react to it -- widgets inside st.form don't rerun the
        # app until submit, so this couldn't update reactively there.
        role_names = [r.role_name for r in roles]
        new_role_choice = st.selectbox(
            "Role", role_names,
            index=role_names.index(editing_user.role.role_name) if editing_user.role else 0,
            key="edit_role_choice",
        )

        new_player_id = None
        new_coach_specialty = None
        if new_role_choice == "Player":
            all_players = session.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
            if not all_players:
                st.warning("No players exist on the roster yet -- add one first from the Players page.")
            else:
                players_by_id = {p.player_id: p for p in all_players}
                default_idx = list(players_by_id.keys()).index(editing_user.player_id) if editing_user.player_id in players_by_id else 0
                new_player_id = st.selectbox(
                    "Which player is this account for?",
                    options=list(players_by_id.keys()),
                    index=default_idx,
                    format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                    key="edit_player_choice",
                )
        elif new_role_choice == "Coach":
            specialty_options = ["Both", "Pitching", "Hitting"]
            current_specialty_idx = specialty_options.index(editing_user.coach_specialty) if editing_user.coach_specialty in specialty_options else 0
            new_coach_specialty = st.selectbox(
                "Specialty",
                specialty_options,
                index=current_specialty_idx,
                key="edit_coach_specialty",
                help="Filters which Training Routines this coach sees -- Pitching coaches won't see hitting-only routines and vice versa. Shared categories (Lifting, Conditioning, Mobility, Med Ball, General) are visible either way.",
            )

        with st.form("edit_user_form"):
            c1, c2 = st.columns(2)
            new_first_name = c1.text_input("First name", value=editing_user.first_name)
            new_last_name = c2.text_input("Last name", value=editing_user.last_name)
            new_email = st.text_input("Email", value=editing_user.email)
            active_choice = st.checkbox("Active", value=editing_user.active)
            edit_submitted = st.form_submit_button("Save changes", type="primary")

        if edit_submitted:
            if not (new_first_name.strip() and new_last_name.strip() and new_email.strip()):
                st.error("First name, last name, and email are required.")
            else:
                email_changed = new_email.strip() != editing_user.email
                if email_changed and session.query(User).filter(User.email == new_email.strip(), User.user_id != editing_user.user_id).first():
                    st.error(f"Another user already has the email {new_email.strip()}.")
                else:
                    if email_changed and editing_user.auth_subject_id:
                        try:
                            admin_client = get_supabase_admin_client()
                            admin_client.auth.admin.update_user_by_id(
                                editing_user.auth_subject_id, {"email": new_email.strip()}
                            )
                        except Exception as e:
                            st.error(f"Failed to update login email in Supabase: {e}")
                            page_footer()
                            st.stop()

                    new_role = next(r for r in roles if r.role_name == new_role_choice)
                    editing_user.first_name = new_first_name.strip()
                    editing_user.last_name = new_last_name.strip()
                    editing_user.email = new_email.strip()
                    editing_user.role_id = new_role.role_id
                    # Clear the player link if the role isn't Player anymore;
                    # otherwise save whichever player was selected above.
                    editing_user.player_id = new_player_id if new_role_choice == "Player" else None
                    # Same for specialty -- only meaningful for Coach.
                    editing_user.coach_specialty = new_coach_specialty if new_role_choice == "Coach" else None
                    editing_user.active = active_choice
                    session.commit()
                    st.success(f"Updated {editing_user.first_name} {editing_user.last_name}.")
                    st.rerun()

        st.markdown("**Reset password**")
        with st.form("reset_password_form"):
            new_password = st.text_input("New password (min 6 characters)", type="password", key="reset_pw")
            confirm_password = st.text_input("Confirm new password", type="password", key="reset_pw_confirm")
            reset_submitted = st.form_submit_button("Reset password", type="primary")

        if reset_submitted:
            if len(new_password) < 6:
                st.error("Password must be at least 6 characters.")
            elif new_password != confirm_password:
                st.error("Passwords do not match.")
            else:
                try:
                    admin_client = get_supabase_admin_client()
                    auth_users = admin_client.auth.admin.list_users()
                    match = next((u for u in auth_users if u.email == editing_user.email), None)
                    if match is None:
                        st.error(f"No Supabase Auth account found for {editing_user.email}.")
                    else:
                        admin_client.auth.admin.update_user_by_id(match.id, {"password": new_password})
                        st.success(f"Password updated for {editing_user.first_name} {editing_user.last_name}.")
                except Exception as e:
                    st.error(f"Failed to reset password: {e}")

finally:
    session.close()

page_footer()