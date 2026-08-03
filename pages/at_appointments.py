"""
GBO — Athletic Trainer Appointments.

Real appointment scheduling: specific date, time, player, and which
Athletic Trainer. Creating/editing restricted to Athletic Trainer and
Administrator; everyone else with Player Development access can view
which players have upcoming appointments (not clinical details beyond
the reason field).
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date, timedelta
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, Role, ATAppointment

page_header("Athletic Trainer Appointments")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)

CAN_EDIT_APPOINTMENTS = ("Administrator", "Athletic Trainer")
can_edit_appointments = role_name in CAN_EDIT_APPOINTMENTS

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    player_query = session.query(Player).filter(Player.active.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    players = player_query.order_by(Player.last_name, Player.first_name).all()

    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
        page_footer()
        st.stop()

    player_ids = [p.player_id for p in players]
    players_by_id = {p.player_id: p for p in players}

    st.divider()
    st.subheader("Upcoming appointments")
    upcoming = (
        session.query(ATAppointment)
        .options(joinedload(ATAppointment.player), joinedload(ATAppointment.athletic_trainer))
        .filter(ATAppointment.player_id.in_(player_ids), ATAppointment.appointment_date >= date.today())
        .order_by(ATAppointment.appointment_date, ATAppointment.appointment_time)
        .all()
    )
    if not upcoming:
        empty_state("No upcoming appointments scheduled.")
    else:
        st.dataframe(
            [
                {
                    "Date": a.appointment_date.strftime("%Y-%m-%d (%a)"),
                    "Time": a.appointment_time or "—",
                    "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                    "Athletic Trainer": f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "—",
                    "Reason": a.reason or "",
                }
                for a in upcoming
            ],
            use_container_width=True,
            hide_index=True,
        )

    if not can_edit_appointments:
        st.info("Your role has read-only access to appointment scheduling.")
    else:
        st.divider()
        st.subheader("Schedule an appointment")

        athletic_trainers = (
            session.query(User)
            .join(Role)
            .filter(Role.role_name == "Athletic Trainer", User.active.is_(True))
            .all()
        )
        if not athletic_trainers:
            st.warning("No Athletic Trainer accounts exist yet.")
        else:
            at_by_id = {u.user_id: u for u in athletic_trainers}

            with st.form("at_appointment_form"):
                appt_player_id = st.selectbox(
                    "Player",
                    options=list(players_by_id.keys()),
                    format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                )
                at_choice = st.selectbox(
                    "Athletic Trainer",
                    options=list(at_by_id.keys()),
                    format_func=lambda uid: f"{at_by_id[uid].first_name} {at_by_id[uid].last_name}",
                )
                appt_date = st.date_input("Date", value=date.today() + timedelta(days=1))
                appt_time = st.time_input("Time")
                reason = st.text_input("Reason (optional)", placeholder="e.g. shoulder follow-up")
                notes = st.text_area("Notes (optional)")
                submitted = st.form_submit_button("Schedule appointment", type="primary")

            if submitted:
                session.add(ATAppointment(
                    player_id=appt_player_id,
                    athletic_trainer_user_id=at_choice,
                    appointment_date=appt_date,
                    appointment_time=appt_time.strftime("%H:%M"),
                    reason=reason.strip() or None,
                    notes=notes.strip() or None,
                    created_by_user_id=current_user_id,
                ))
                session.commit()
                st.success(f"Scheduled appointment for {players_by_id[appt_player_id].first_name} {players_by_id[appt_player_id].last_name}.")
                st.rerun()

finally:
    session.close()

page_footer()