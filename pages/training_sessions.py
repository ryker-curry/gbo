"""
GBO — Training Sessions (Milestone: Aug 11-13).

A lightweight day-to-day training log -- separate from Assessments
(formal periodic testing) and IDP (long-term goals + progress notes tied
to a goal). This is the "what actually happened today" diary: arm care,
conditioning, hitting drills, throwing/plyos, or general work.

Renamed from "Individual Sessions" -- that name wrongly implied 1-on-1
only; these logs cover group work too.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, SessionType, TrainingSession, IDPGoal

page_header("Training Sessions")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    # --- Visible players (same role-based filtering as Player Management) ---
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

    players_by_id = {p.player_id: p for p in players}
    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )
    selected_player = players_by_id[selected_player_id]

    session_types = session.query(SessionType).order_by(SessionType.display_order).all()

    st.divider()

    # --- Filter by session type ---
    type_filter = st.selectbox("Filter by type", ["All"] + [t.type_name for t in session_types])

    st.subheader(f"Session log — {selected_player.first_name} {selected_player.last_name}")

    history_query = (
        session.query(TrainingSession)
        .options(
            joinedload(TrainingSession.session_type),
            joinedload(TrainingSession.coach),
            joinedload(TrainingSession.goal),
        )
        .filter(TrainingSession.player_id == selected_player_id)
    )
    if type_filter != "All":
        history_query = history_query.join(SessionType).filter(SessionType.type_name == type_filter)
    past_sessions = history_query.order_by(TrainingSession.session_date.desc()).limit(200).all()

    if not past_sessions:
        st.info("No training sessions logged yet for this player.")
    else:
        st.dataframe(
            [
                {
                    "Date": s.session_date.strftime("%Y-%m-%d (%a)"),
                    "Type": s.session_type.type_name if s.session_type else "—",
                    "Coach": f"{s.coach.first_name} {s.coach.last_name}" if s.coach else "—",
                    "IDP Goal": (s.goal.description[:40] + "...") if s.goal and len(s.goal.description) > 40 else (s.goal.description if s.goal else ""),
                    "Notes": s.notes or "",
                    "Player Feedback": s.player_feedback or "",
                    "Next Steps": s.next_steps or "",
                }
                for s in past_sessions
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # --- Log a new session (edit-capable roles only) ---
    if not can_edit_sessions:
        st.info("Your role has read-only access to training sessions.")
    else:
        st.subheader("Log a new training session")

        open_goals = (
            session.query(IDPGoal)
            .options(joinedload(IDPGoal.category))
            .filter(IDPGoal.player_id == selected_player_id)
            .order_by(IDPGoal.created_at.desc())
            .all()
        )
        goals_by_id = {g.goal_id: g for g in open_goals}

        with st.form("training_session_form"):
            session_date = st.date_input("Date", value=date.today())
            session_type_choice = st.selectbox("Type", [t.type_name for t in session_types])
            goal_choice = None
            if open_goals:
                goal_choice = st.selectbox(
                    "Prescribed toward IDP goal (optional)",
                    options=[None] + list(goals_by_id.keys()),
                    format_func=lambda gid: "-- Not linked to a goal --" if gid is None else f"{goals_by_id[gid].category.category_name}: {goals_by_id[gid].description[:50]}",
                )
            notes = st.text_area("Notes")
            player_feedback = st.text_area("Player feedback (optional)")
            next_steps = st.text_area("Next steps (optional)")
            submitted = st.form_submit_button("Log session", type="primary")

        if submitted:
            if not notes.strip():
                st.error("Notes are required.")
            else:
                session_type_id = next(t.session_type_id for t in session_types if t.type_name == session_type_choice)
                new_session = TrainingSession(
                    player_id=selected_player_id,
                    goal_id=goal_choice,
                    coach_user_id=current_user_id,
                    session_type_id=session_type_id,
                    session_date=session_date,
                    notes=notes.strip(),
                    player_feedback=player_feedback.strip() or None,
                    next_steps=next_steps.strip() or None,
                )
                session.add(new_session)
                session.commit()
                st.success(f"Logged {session_type_choice} session for {selected_player.first_name} {selected_player.last_name}.")
                st.rerun()

finally:
    session.close()

page_footer()