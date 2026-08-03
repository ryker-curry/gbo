"""
GBO — My Schedule (Player role only).

Split out of the Dashboard so a player's sidebar has focused pages
instead of one long scrolling dashboard: Dashboard (Today), My Schedule
(this page -- team schedule, assignments, AT appointments for the next
7 days), and My Development (IDP goals).
"""

import streamlit as st
from datetime import date, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, TeamScheduleEvent, PlayerAssignment, ATAppointment, TrainingRoutine
from ui_components import page_header, page_footer, empty_state

page_header("My Schedule")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name != "Player":
    st.error("This page is only available to Player accounts.")
    page_footer()
    st.stop()

session = get_session()
try:
    me = session.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        st.info("Your player profile isn't linked yet. Check with an administrator.")
        page_footer()
        st.stop()

    my_player = session.query(Player).filter(Player.player_id == me.player_id).first()

    today = date.today()
    week_ahead = today + timedelta(days=7)

    # --- Team-wide schedule (practice, lifts, games) for the next 7 days ---
    st.markdown("**Team schedule (next 7 days)**")
    team_events = (
        session.query(TeamScheduleEvent)
        .options(
            joinedload(TeamScheduleEvent.event_type),
            joinedload(TeamScheduleEvent.routine).joinedload(TrainingRoutine.exercises),
        )
        .filter(
            TeamScheduleEvent.team_id == my_player.team_id,
            TeamScheduleEvent.scheduled_date >= today,
            TeamScheduleEvent.scheduled_date <= week_ahead,
            or_(TeamScheduleEvent.pitchers_only.is_(None), TeamScheduleEvent.pitchers_only == my_player.is_pitcher),
        )
        .order_by(TeamScheduleEvent.scheduled_date)
        .all()
    )
    if not team_events:
        empty_state("No team events scheduled this week.")
    else:
        for e in team_events:
            date_label = e.scheduled_date.strftime("%Y-%m-%d (%a)")
            type_label = e.event_type.type_name if e.event_type else "Team"
            title = f"{date_label} — {type_label}: {e.title}"
            if e.routine:
                title += f" ({e.routine.routine_name})"
            with st.expander(title):
                if e.routine:
                    if e.routine.description:
                        st.write(e.routine.description)
                    for ex in e.routine.exercises:
                        ex_label = f"**{ex.exercise_name}**"
                        if ex.sets or ex.reps:
                            ex_label += f" — {ex.sets or '—'} sets x {ex.reps or '—'}"
                        st.markdown(ex_label)
                        if ex.video_url:
                            st.video(ex.video_url)
                        if ex.notes:
                            st.caption(ex.notes)
                if e.notes:
                    st.caption(e.notes)
                if not e.routine and not e.notes:
                    st.caption("No additional details provided.")

    st.divider()

    # --- My prescribed assignments (throwing, arm care, etc.) ---
    st.markdown("**My assignments (next 7 days)**")
    my_assignments = (
        session.query(PlayerAssignment)
        .options(
            joinedload(PlayerAssignment.session_type),
            joinedload(PlayerAssignment.routine).joinedload(TrainingRoutine.exercises),
            joinedload(PlayerAssignment.bullpen_type),
            joinedload(PlayerAssignment.bullpen_script),
        )
        .filter(
            PlayerAssignment.player_id == my_player.player_id,
            PlayerAssignment.scheduled_date >= today,
            PlayerAssignment.scheduled_date <= week_ahead,
        )
        .order_by(PlayerAssignment.scheduled_date)
        .all()
    )
    if not my_assignments:
        empty_state("No assignments scheduled this week.")
    else:
        for a in my_assignments:
            type_label = a.session_type.type_name if a.session_type else "—"
            date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
            title = f"{date_label} — {type_label}"
            if a.routine:
                title += f": {a.routine.routine_name}"
            elif a.bullpen_type:
                title += f": {a.bullpen_type.type_name}"
                if a.bullpen_script:
                    title += f" ({a.bullpen_script.script_name})"
            with st.expander(title):
                if a.routine:
                    if a.routine.description:
                        st.write(a.routine.description)
                    if a.routine.exercises:
                        for e in a.routine.exercises:
                            ex_label = f"**{e.exercise_name}**"
                            if e.sets or e.reps:
                                ex_label += f" — {e.sets or '—'} sets x {e.reps or '—'}"
                            st.markdown(ex_label)
                            if e.video_url:
                                st.video(e.video_url)
                            if e.notes:
                                st.caption(e.notes)
                elif a.bullpen_type:
                    caption = f"{a.bullpen_type.type_name} bullpen"
                    if a.bullpen_script:
                        caption += f": {a.bullpen_script.script_name}"
                    st.caption(f"{caption} — logged in Bullpen Tracking once thrown.")
                if a.notes:
                    st.caption(a.notes)
                if not a.routine and not a.bullpen_type and not a.notes:
                    st.caption("No additional details provided.")

    st.divider()

    # --- My Athletic Trainer appointments ---
    st.markdown("**My Athletic Trainer appointments**")
    my_appointments = (
        session.query(ATAppointment)
        .options(joinedload(ATAppointment.athletic_trainer))
        .filter(ATAppointment.player_id == my_player.player_id, ATAppointment.appointment_date >= today)
        .order_by(ATAppointment.appointment_date, ATAppointment.appointment_time)
        .all()
    )
    if not my_appointments:
        empty_state("No upcoming Athletic Trainer appointments.")
    else:
        st.dataframe(
            [
                {
                    "Date": a.appointment_date.strftime("%Y-%m-%d (%a)"),
                    "Time": a.appointment_time or "—",
                    "Athletic Trainer": f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "—",
                    "Reason": a.reason or "",
                }
                for a in my_appointments
            ],
            use_container_width=True,
            hide_index=True,
        )

finally:
    session.close()

page_footer()