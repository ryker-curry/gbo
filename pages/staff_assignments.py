"""
GBO — Staff-to-Player Assignments.

Lets Administrators and Head Coaches control which players a Coach (or
other staff role) can see and work with -- this is what the Coach role's
"assigned players only" restriction actually reads from.

Restricted to Administrator and Head Coach: a general Coach assigning
themselves players would bypass the whole point of the restriction.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state

from database import get_session
from models import User, Player, StaffPlayerAssignment, Role

page_header("Staff Assignments")

role_name = st.session_state.get("gbo_role_name")

if role_name not in ("Administrator", "Head Coach"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

session = get_session()
try:
    staff_users = (
        session.query(User)
        .join(Role)
        .filter(Role.role_name != "Player", User.active.is_(True))
        .order_by(Role.role_name, User.last_name, User.first_name)
        .all()
    )
    players = (
        session.query(Player)
        .filter(Player.active.is_(True))
        .order_by(Player.last_name, Player.first_name)
        .all()
    )

    if not staff_users:
        empty_state("No staff accounts exist yet.")
        page_footer()
        st.stop()
    if not players:
        empty_state("No players exist yet -- add players first from the Players page.")
        page_footer()
        st.stop()

    staff_by_id = {u.user_id: u for u in staff_users}
    players_by_id = {p.player_id: p for p in players}

    selected_staff_id = st.selectbox(
        "Select a staff member:",
        options=list(staff_by_id.keys()),
        format_func=lambda uid: f"{staff_by_id[uid].first_name} {staff_by_id[uid].last_name} ({staff_by_id[uid].role.role_name})",
    )

    current_assignment_ids = {
        a.player_id for a in
        session.query(StaffPlayerAssignment)
        .filter(StaffPlayerAssignment.staff_user_id == selected_staff_id)
        .all()
    }

    st.caption(
        f"{staff_by_id[selected_staff_id].first_name} {staff_by_id[selected_staff_id].last_name} "
        f"currently has {len(current_assignment_ids)} player(s) assigned."
    )

    with st.form("assignment_form"):
        selected_player_ids = st.multiselect(
            "Assigned players:",
            options=list(players_by_id.keys()),
            default=list(current_assignment_ids),
            format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
        )
        submitted = st.form_submit_button("Save assignments", type="primary")

    if submitted:
        new_ids = set(selected_player_ids)
        to_remove = current_assignment_ids - new_ids
        to_add = new_ids - current_assignment_ids

        if to_remove:
            session.query(StaffPlayerAssignment).filter(
                StaffPlayerAssignment.staff_user_id == selected_staff_id,
                StaffPlayerAssignment.player_id.in_(to_remove),
            ).delete(synchronize_session=False)

        for pid in to_add:
            session.add(StaffPlayerAssignment(staff_user_id=selected_staff_id, player_id=pid))

        session.commit()
        st.success(
            f"Updated assignments for {staff_by_id[selected_staff_id].first_name} "
            f"{staff_by_id[selected_staff_id].last_name}: "
            f"{len(to_add)} added, {len(to_remove)} removed."
        )
        st.rerun()

finally:
    session.close()

page_footer()