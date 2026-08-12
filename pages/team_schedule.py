"""
GBO — Team Schedule.

Team-wide calendar (lift days, practice, games, other), with completion
tracking (was it actually done, and how did it go) -- this replaced the
separate Training Sessions log for team-wide work. Renamed/generalized
from Lift Schedule once Ryker asked for practice schedule too. A "Lift"
event can optionally have an actual Training Routine attached (real
exercises/video), not just a title -- so a player sees the real workout,
not just "Squat Day" with no content.

Creating/editing is restricted to Administrator, Head Coach, and
Strength Coach; everyone else with Player Development access can view it.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date, timedelta, datetime
from sqlalchemy.orm import joinedload

from database import get_session
from models import Team, TeamScheduleEvent, TeamEventType, TrainingRoutine, SessionType

# Maps a Team Schedule event type to the matching Training Routine session
# type, so a "Lift" day can offer routines built under "Lifting". Only
# types with an established content library are listed -- Practice/Game/
# Other don't have a routine picker since there's no matching library yet.
EVENT_TYPE_TO_SESSION_TYPE = {"Lift": "Lifting"}

page_header("Team Schedule")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

CAN_EDIT_SCHEDULE = ("Administrator", "Head Coach", "Strength Coach")
can_edit_schedule = role_name in CAN_EDIT_SCHEDULE

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    teams = session.query(Team).all()
    if not teams:
        st.warning("No teams exist yet.")
        page_footer()
        st.stop()
    team = teams[0]  # single-team MVP

    event_types = session.query(TeamEventType).order_by(TeamEventType.display_order).all()
    type_filter = st.selectbox("Filter by type", ["All"] + [t.type_name for t in event_types])

    st.divider()
    st.subheader("Upcoming events")
    upcoming_query = (
        session.query(TeamScheduleEvent)
        .options(joinedload(TeamScheduleEvent.event_type), joinedload(TeamScheduleEvent.routine))
        .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date >= date.today())
    )
    if type_filter != "All":
        upcoming_query = upcoming_query.join(TeamEventType).filter(TeamEventType.type_name == type_filter)
    upcoming = upcoming_query.order_by(TeamScheduleEvent.scheduled_date).all()

    if not upcoming:
        empty_state("No upcoming events scheduled.")
    else:
        st.dataframe(
            [
                {
                    "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                    "Type": s.event_type.type_name if s.event_type else "—",
                    "Title": s.title,
                    "Audience": "Pitchers Only" if s.pitchers_only is True else ("Position Players Only" if s.pitchers_only is False else "Whole Team"),
                    "Routine": s.routine.routine_name if s.routine else "—",
                    "Completed": "Yes" if s.completed else "No",
                    "Notes": s.notes or "",
                }
                for s in upcoming
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.subheader("Mark events as completed")
    pending_events = (
        session.query(TeamScheduleEvent)
        .options(joinedload(TeamScheduleEvent.event_type))
        .filter(
            TeamScheduleEvent.team_id == team.team_id,
            TeamScheduleEvent.scheduled_date <= date.today(),
            TeamScheduleEvent.completed.is_(False),
        )
        .order_by(TeamScheduleEvent.scheduled_date.desc())
        .all()
    )
    if not pending_events:
        st.caption("No pending events (today or earlier) to mark complete.")
    elif not can_edit_schedule:
        st.info("Your role has read-only access to the team schedule.")
    else:
        for s in pending_events:
            date_label = s.scheduled_date.strftime("%Y-%m-%d (%a)")
            type_label = s.event_type.type_name if s.event_type else "—"
            with st.expander(f"{date_label} — {type_label}: {s.title}"):
                with st.form(f"complete_event_{s.schedule_id}"):
                    completed_notes = st.text_area("What actually happened (optional)", key=f"cen_{s.schedule_id}")
                    mark_submitted = st.form_submit_button("Mark as completed", type="primary")
                if mark_submitted:
                    s.completed = True
                    s.completed_notes = completed_notes.strip() or None
                    s.completed_at = datetime.utcnow()
                    session.commit()
                    st.success(f"Marked {s.title} on {date_label} as completed.")
                    st.rerun()

    st.divider()
    with st.expander("Past events"):
        past_query = (
            session.query(TeamScheduleEvent)
            .options(joinedload(TeamScheduleEvent.event_type), joinedload(TeamScheduleEvent.routine))
            .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date < date.today())
        )
        if type_filter != "All":
            past_query = past_query.join(TeamEventType).filter(TeamEventType.type_name == type_filter)
        past = past_query.order_by(TeamScheduleEvent.scheduled_date.desc()).limit(50).all()

        if not past:
            st.caption("No past entries.")
        else:
            st.dataframe(
                [
                    {
                        "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                        "Type": s.event_type.type_name if s.event_type else "—",
                        "Title": s.title,
                        "Audience": "Pitchers Only" if s.pitchers_only is True else ("Position Players Only" if s.pitchers_only is False else "Whole Team"),
                        "Routine": s.routine.routine_name if s.routine else "—",
                        "Completed": "Yes" if s.completed else "No",
                        "What happened": s.completed_notes or "",
                        "Notes": s.notes or "",
                    }
                    for s in past
                ],
                use_container_width=True,
                hide_index=True,
            )

    if not can_edit_schedule:
        st.info("Your role has read-only access to the team schedule.")
    else:
        st.divider()
        st.subheader("Add a scheduled event")

        # Type selection lives outside the form so the routine dropdown
        # below can filter by it -- widgets inside st.form don't rerun
        # the app until submit, so this couldn't update reactively there.
        event_type_choice = st.selectbox("Type", [t.type_name for t in event_types], key="new_event_type")
        event_type_id = next(t.event_type_id for t in event_types if t.type_name == event_type_choice)

        matching_routines = []
        mapped_session_type = EVENT_TYPE_TO_SESSION_TYPE.get(event_type_choice)
        if mapped_session_type:
            matching_routines = (
                session.query(TrainingRoutine)
                .join(SessionType)
                .filter(SessionType.type_name == mapped_session_type)
                .order_by(TrainingRoutine.routine_name)
                .all()
            )

        with st.form("team_schedule_form"):
            scheduled_date = st.date_input("Date", value=date.today() + timedelta(days=1))
            title = st.text_input("Title", placeholder="e.g. Squat Day, Team Practice")
            audience_choice = st.selectbox("Who is this for?", ["Whole Team", "Pitchers Only", "Position Players Only"])
            routine_choice = None
            if matching_routines:
                routines_by_id = {r.routine_id: r for r in matching_routines}
                routine_choice = st.selectbox(
                    "Attach a routine (optional)",
                    options=[None] + list(routines_by_id.keys()),
                    format_func=lambda rid: "-- No routine, just a title --" if rid is None else routines_by_id[rid].routine_name,
                )
            elif mapped_session_type:
                st.caption(f"No {mapped_session_type} routines saved yet -- build one on Training Routines first if you want to attach real workout content.")
            notes = st.text_area("Notes (optional)")
            submitted = st.form_submit_button("Add to schedule", type="primary")

        if submitted:
            if not title.strip():
                st.error("Title is required.")
            else:
                pitchers_only = {"Whole Team": None, "Pitchers Only": True, "Position Players Only": False}[audience_choice]
                session.add(TeamScheduleEvent(
                    team_id=team.team_id,
                    event_type_id=event_type_id,
                    routine_id=routine_choice,
                    pitchers_only=pitchers_only,
                    scheduled_date=scheduled_date,
                    title=title.strip(),
                    notes=notes.strip() or None,
                    created_by_user_id=current_user_id,
                ))
                session.commit()
                st.success(f"Added {title.strip()} on {scheduled_date.strftime('%Y-%m-%d (%a)')}.")
                st.rerun()

finally:
    session.close()

page_footer()