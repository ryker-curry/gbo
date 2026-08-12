"""
GBO — Player Assignments.

Prescribed, forward-looking tasks for a specific player (e.g. "today:
throwing program", "today: arm care") -- assigned ahead of time by a
coach, Strength Coach, or Athletic Trainer. Also tracks completion (was
it actually done, and how did it go) -- this replaced the separate
Training Sessions log, which duplicated planning already captured here.
Reuses the SessionType lookup so assignment types match logged session
types exactly. Can optionally be prescribed toward a specific IDP goal.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date, datetime

from database import get_session
from models import Player, StaffPlayerAssignment, SessionType, PlayerAssignment, TrainingRoutine, IDPGoal, BullpenType, BullpenScript, BullpenSession

page_header("Player Assignments")

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
    session_types = session.query(SessionType).order_by(SessionType.display_order).all()

    if not can_edit_sessions:
        st.info("Your role has read-only access to player assignments.")
    else:
        st.subheader("Bulk assign to multiple players")
        st.caption("Assign the same thing (e.g. conditioning, arm care) to several players at once, instead of one at a time.")

        # Type selection lives outside the form so the routine dropdown
        # below can filter by it -- widgets inside st.form don't rerun
        # the app until submit, so this couldn't update reactively there.
        bulk_type_choice = st.selectbox("Type", [t.type_name for t in session_types], key="bulk_type_choice")
        bulk_type_id = next(t.session_type_id for t in session_types if t.type_name == bulk_type_choice)
        bulk_matching_routines = (
            session.query(TrainingRoutine)
            .filter(TrainingRoutine.session_type_id == bulk_type_id)
            .order_by(TrainingRoutine.routine_name)
            .all()
        )
        bulk_is_bullpen = bulk_type_choice == "Bullpen"
        bulk_bullpen_types = session.query(BullpenType).order_by(BullpenType.display_order).all() if bulk_is_bullpen else []

        bulk_bullpen_type_choice = None
        bulk_matching_scripts = []
        if bulk_is_bullpen and bulk_bullpen_types:
            bulk_bp_types_by_id = {bt.bullpen_type_id: bt for bt in bulk_bullpen_types}
            bulk_bullpen_type_choice = st.selectbox(
                "Bullpen type",
                options=list(bulk_bp_types_by_id.keys()),
                format_func=lambda btid: bulk_bp_types_by_id[btid].type_name,
                key="bulk_bullpen_type_choice",
            )
            bulk_matching_scripts = (
                session.query(BullpenScript)
                .filter(BullpenScript.bullpen_type_id == bulk_bullpen_type_choice)
                .order_by(BullpenScript.script_name)
                .all()
            )

        bulk_selected_player_ids = st.multiselect(
            "Players",
            options=list(players_by_id.keys()),
            format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
            key="bulk_players",
        )

        with st.form("bulk_assignment_form"):
            bulk_date = st.date_input("Date", value=date.today(), key="bulk_date")
            bulk_routine_choice = None
            bulk_script_choice = None
            if bulk_is_bullpen:
                if bulk_matching_scripts:
                    bulk_scripts_by_id = {s.script_id: s for s in bulk_matching_scripts}
                    bulk_script_choice = st.selectbox(
                        "Attach a script (optional)",
                        options=[None] + list(bulk_scripts_by_id.keys()),
                        format_func=lambda sid: "-- No script, just notes --" if sid is None else bulk_scripts_by_id[sid].script_name,
                        key="bulk_script_choice",
                    )
                elif bulk_bullpen_type_choice:
                    st.caption("No scripts saved yet for this bullpen type -- build one on Bullpen Scripts first if you want to attach a planned sequence.")
            elif bulk_matching_routines:
                bulk_routines_by_id = {r.routine_id: r for r in bulk_matching_routines}
                bulk_routine_choice = st.selectbox(
                    "Use a saved routine (optional)",
                    options=[None] + list(bulk_routines_by_id.keys()),
                    format_func=lambda rid: "-- No routine, just notes --" if rid is None else bulk_routines_by_id[rid].routine_name,
                    key="bulk_routine_choice",
                )
            bulk_notes = st.text_area("Notes (optional, applies to everyone selected)", key="bulk_notes")
            bulk_submitted = st.form_submit_button("Assign to selected players", type="primary")

        if bulk_submitted:
            if not bulk_selected_player_ids:
                st.error("Select at least one player.")
            else:
                for pid in bulk_selected_player_ids:
                    session.add(PlayerAssignment(
                        player_id=pid,
                        session_type_id=bulk_type_id,
                        routine_id=bulk_routine_choice,
                        bullpen_type_id=bulk_bullpen_type_choice,
                        bullpen_script_id=bulk_script_choice,
                        scheduled_date=bulk_date,
                        notes=bulk_notes.strip() or None,
                        assigned_by_user_id=current_user_id,
                    ))
                session.commit()
                names = ", ".join(f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in bulk_selected_player_ids)
                st.success(f"Assigned {bulk_type_choice} to {len(bulk_selected_player_ids)} player(s): {names}.")
                st.rerun()

    st.divider()
    st.subheader("Manage a single player's assignments")

    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
        key="single_player_choice",
    )
    selected_player = players_by_id[selected_player_id]

    st.divider()
    st.subheader(f"Upcoming assignments — {selected_player.first_name} {selected_player.last_name}")

    upcoming = (
        session.query(PlayerAssignment)
        .filter(PlayerAssignment.player_id == selected_player_id, PlayerAssignment.scheduled_date >= date.today())
        .order_by(PlayerAssignment.scheduled_date)
        .all()
    )
    if not upcoming:
        empty_state("No upcoming assignments for this player.")
    else:
        st.dataframe(
            [
                {
                    "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                    "Type": a.session_type.type_name if a.session_type else "—",
                    "Routine": a.routine.routine_name if a.routine else (
                        a.bullpen_script.script_name if a.bullpen_script else (a.bullpen_type.type_name if a.bullpen_type else "—")
                    ),
                    "Notes": a.notes or "",
                }
                for a in upcoming
            ],
            use_container_width=True,
            hide_index=True,
        )

    if can_edit_sessions:
        all_assignments = (
            session.query(PlayerAssignment)
            .filter(PlayerAssignment.player_id == selected_player_id)
            .order_by(PlayerAssignment.scheduled_date.desc())
            .limit(200)
            .all()
        )
        if all_assignments:
            with st.expander("Delete an assignment (past or upcoming)"):
                assignments_by_id = {a.assignment_id: a for a in all_assignments}

                def _assignment_label(aid):
                    a = assignments_by_id[aid]
                    label = f"{a.scheduled_date.strftime('%Y-%m-%d (%a)')} — {a.session_type.type_name if a.session_type else '—'}"
                    if a.bullpen_script:
                        label += f": {a.bullpen_script.script_name}"
                    elif a.routine:
                        label += f": {a.routine.routine_name}"
                    if a.completed:
                        label += " (completed)"
                    return label

                delete_target_id = st.selectbox(
                    "Which assignment?",
                    options=list(assignments_by_id.keys()),
                    format_func=_assignment_label,
                    key="delete_assignment_choice",
                )
                confirm_delete_assignment = st.checkbox("Yes, permanently delete this assignment", key=f"confirm_delete_assignment_{delete_target_id}")
                if st.button("Delete assignment", key=f"delete_assignment_{delete_target_id}", disabled=not confirm_delete_assignment, type="primary"):
                    # A BullpenSession can point back at this assignment
                    # (source_assignment_id) -- unlink rather than block or
                    # cascade-delete, since the session's actual pitch
                    # data is worth keeping even if its source prescription
                    # goes away.
                    linked_sessions = (
                        session.query(BullpenSession)
                        .filter(BullpenSession.source_assignment_id == delete_target_id)
                        .all()
                    )
                    for bs in linked_sessions:
                        bs.source_assignment_id = None
                    session.delete(assignments_by_id[delete_target_id])
                    session.commit()
                    msg = "Deleted the assignment."
                    if linked_sessions:
                        msg += f" Unlinked it from {len(linked_sessions)} bullpen session(s) that were tracking it (those sessions and their pitches are kept)."
                    st.success(msg)
                    st.rerun()

    st.divider()
    st.subheader("Mark assignments as completed")

    pending = (
        session.query(PlayerAssignment)
        .filter(
            PlayerAssignment.player_id == selected_player_id,
            PlayerAssignment.scheduled_date <= date.today(),
            PlayerAssignment.completed.is_(False),
        )
        .order_by(PlayerAssignment.scheduled_date.desc())
        .all()
    )
    if not pending:
        st.caption("No pending assignments (today or earlier) to mark complete.")
    elif not can_edit_sessions:
        st.info("Your role has read-only access to player assignments.")
    else:
        for a in pending:
            type_label = a.session_type.type_name if a.session_type else "—"
            date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
            title = f"{date_label} — {type_label}"
            if a.routine:
                title += f": {a.routine.routine_name}"
            elif a.bullpen_type:
                title += f": {a.bullpen_type.type_name}"
            with st.expander(title):
                with st.form(f"complete_assignment_{a.assignment_id}"):
                    completed_notes = st.text_area("What actually happened (optional)", key=f"cn_{a.assignment_id}")
                    player_feedback = st.text_area("Player feedback (optional)", key=f"pf_{a.assignment_id}")
                    mark_submitted = st.form_submit_button("Mark as completed", type="primary")
                if mark_submitted:
                    a.completed = True
                    a.completed_notes = completed_notes.strip() or None
                    a.player_feedback = player_feedback.strip() or None
                    a.completed_at = datetime.utcnow()
                    session.commit()
                    st.success(f"Marked {type_label} on {date_label} as completed.")
                    st.rerun()

    with st.expander("Recently completed"):
        completed = (
            session.query(PlayerAssignment)
            .filter(PlayerAssignment.player_id == selected_player_id, PlayerAssignment.completed.is_(True))
            .order_by(PlayerAssignment.scheduled_date.desc())
            .limit(20)
            .all()
        )
        if not completed:
            st.caption("No completed assignments yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                        "Type": a.session_type.type_name if a.session_type else "—",
                        "What happened": a.completed_notes or "",
                        "Player feedback": a.player_feedback or "",
                    }
                    for a in completed
                ],
                use_container_width=True,
                hide_index=True,
            )

    if not can_edit_sessions:
        st.info("Your role has read-only access to player assignments.")
    else:
        st.divider()
        st.subheader("Add an assignment")

        # Type selection lives outside the form so the routine dropdown
        # below can filter by it -- widgets inside st.form don't rerun
        # the app until submit, so this couldn't update reactively there.
        type_choice = st.selectbox("Type", [t.type_name for t in session_types], key="assignment_type_choice")
        type_id_for_filter = next(t.session_type_id for t in session_types if t.type_name == type_choice)
        matching_routines = (
            session.query(TrainingRoutine)
            .filter(TrainingRoutine.session_type_id == type_id_for_filter)
            .order_by(TrainingRoutine.routine_name)
            .all()
        )
        is_bullpen = type_choice == "Bullpen"
        bullpen_types = session.query(BullpenType).order_by(BullpenType.display_order).all() if is_bullpen else []

        bullpen_type_choice = None
        matching_scripts = []
        if is_bullpen and bullpen_types:
            bp_types_by_id = {bt.bullpen_type_id: bt for bt in bullpen_types}
            bullpen_type_choice = st.selectbox(
                "Bullpen type",
                options=list(bp_types_by_id.keys()),
                format_func=lambda btid: bp_types_by_id[btid].type_name,
                key="single_bullpen_type_choice",
            )
            matching_scripts = (
                session.query(BullpenScript)
                .filter(BullpenScript.bullpen_type_id == bullpen_type_choice)
                .order_by(BullpenScript.script_name)
                .all()
            )

        player_goals = (
            session.query(IDPGoal)
            .filter(IDPGoal.player_id == selected_player_id)
            .order_by(IDPGoal.created_at.desc())
            .all()
        )

        with st.form("player_assignment_form"):
            scheduled_date = st.date_input("Date", value=date.today())
            routine_choice = None
            script_choice = None
            if is_bullpen:
                if matching_scripts:
                    scripts_by_id = {s.script_id: s for s in matching_scripts}
                    script_choice = st.selectbox(
                        "Attach a script (optional)",
                        options=[None] + list(scripts_by_id.keys()),
                        format_func=lambda sid: "-- No script, just notes --" if sid is None else scripts_by_id[sid].script_name,
                    )
                elif bullpen_type_choice:
                    st.caption("No scripts saved yet for this bullpen type -- build one on Bullpen Scripts first if you want to attach a planned sequence.")
            elif matching_routines:
                routines_by_id = {r.routine_id: r for r in matching_routines}
                routine_choice = st.selectbox(
                    "Use a saved routine (optional)",
                    options=[None] + list(routines_by_id.keys()),
                    format_func=lambda rid: "-- No routine, just notes --" if rid is None else routines_by_id[rid].routine_name,
                )
            goal_choice = None
            if player_goals:
                goals_by_id = {g.goal_id: g for g in player_goals}
                goal_choice = st.selectbox(
                    "Prescribed toward IDP goal (optional)",
                    options=[None] + list(goals_by_id.keys()),
                    format_func=lambda gid: "-- Not linked to a goal --" if gid is None else f"{goals_by_id[gid].description[:50]}",
                )
            notes = st.text_area("Notes (optional)", placeholder="e.g. specific throwing program details")
            submitted = st.form_submit_button("Add assignment", type="primary")

        if submitted:
            session.add(PlayerAssignment(
                player_id=selected_player_id,
                session_type_id=type_id_for_filter,
                routine_id=routine_choice,
                bullpen_type_id=bullpen_type_choice,
                bullpen_script_id=script_choice,
                goal_id=goal_choice,
                scheduled_date=scheduled_date,
                notes=notes.strip() or None,
                assigned_by_user_id=current_user_id,
            ))
            session.commit()
            st.success(f"Added {type_choice} assignment for {selected_player.first_name} {selected_player.last_name} on {scheduled_date.strftime('%Y-%m-%d (%a)')}.")
            st.rerun()

finally:
    session.close()

page_footer()