"""
GBO — Individual Development Plan (IDP) (Milestone: Aug 11-13).

Goals are typed by assessment category and can link back to the specific
assessment record that motivated them (per Ryker's decision) -- action
steps and progress notes hang off each goal.

Edit permissions are more granular than the single can_edit_idp flag:
  - Administrator, Head Coach, Coach, Strength Coach: full edit
    (create goals, add action steps, add progress notes)
  - Athletic Trainer: progress notes only, per Ryker's decision
  - Sports Scientist, Data Analyst: read-only
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date, timedelta
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, AssessmentCategory, Assessment, AssessmentResult, AssessmentTestType,
    IDPGoal, IDPActionStep, IDPProgressNote, IDPStatus, TrainingSession, PlayerAssignment,
)

page_header("Individual Development Plan")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)

FULL_EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Strength Coach")
can_create_goals = role_name in FULL_EDIT_ROLES
can_add_progress_notes = role_name in FULL_EDIT_ROLES + ("Athletic Trainer",)

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

    categories = session.query(AssessmentCategory).order_by(AssessmentCategory.display_order).all()
    statuses = session.query(IDPStatus).order_by(IDPStatus.display_order).all()
    categories_by_id = {c.category_id: c for c in categories}
    statuses_by_id = {s.status_id: s for s in statuses}

    st.divider()
    st.subheader(f"Goals — {selected_player.first_name} {selected_player.last_name}")

    goals = (
        session.query(IDPGoal)
        .options(
            joinedload(IDPGoal.category),
            joinedload(IDPGoal.status),
            joinedload(IDPGoal.source_assessment),
            joinedload(IDPGoal.target_test_type),
            joinedload(IDPGoal.action_steps).joinedload(IDPActionStep.status),
            joinedload(IDPGoal.progress_notes),
            joinedload(IDPGoal.linked_sessions).joinedload(TrainingSession.session_type),
            joinedload(IDPGoal.linked_assignments).joinedload(PlayerAssignment.session_type),
        )
        .filter(IDPGoal.player_id == selected_player_id)
        .order_by(IDPGoal.created_at.desc())
        .all()
    )

    if not goals:
        st.info("No development goals yet for this player.")
    else:
        for goal in goals:
            status_label = goal.status.status_name if goal.status else "—"
            with st.expander(f"**{goal.category.category_name}** — {goal.description[:60]}{'...' if len(goal.description) > 60 else ''}  ·  {status_label}"):
                st.write(goal.description)
                if goal.target_test_type:
                    unit = f" {goal.target_test_type.unit}" if goal.target_test_type.unit else ""
                    target_line = f"**Target: {goal.target_test_type.test_name}** — "
                    if goal.baseline_value is not None:
                        target_line += f"{float(goal.baseline_value):.2f}{unit} → "
                    if goal.target_value is not None:
                        target_line += f"{float(goal.target_value):.2f}{unit}"
                    if goal.target_date:
                        target_line += f" by {goal.target_date.strftime('%Y-%m-%d (%a)')}"
                    st.markdown(target_line)
                if goal.source_assessment:
                    st.caption(f"Linked to assessment dated {goal.source_assessment.assessment_date.strftime('%Y-%m-%d (%a)')}")

                # --- Update status ---
                if can_create_goals:
                    status_names = [s.status_name for s in statuses]
                    current_idx = status_names.index(goal.status.status_name) if goal.status else 0
                    new_status = st.selectbox("Status", status_names, index=current_idx, key=f"goal_status_{goal.goal_id}")
                    if new_status != status_label:
                        if st.button("Update status", key=f"update_status_{goal.goal_id}"):
                            goal.status_id = next(s.status_id for s in statuses if s.status_name == new_status)
                            session.commit()
                            st.rerun()

                # --- Action steps ---
                st.markdown("**Action steps**")
                if not goal.action_steps:
                    st.caption("No action steps yet.")
                else:
                    st.dataframe(
                        [
                            {
                                "Description": a.description,
                                "Status": a.status.status_name if a.status else "—",
                                "Due date": a.due_date.strftime("%Y-%m-%d (%a)") if a.due_date else "—",
                            }
                            for a in goal.action_steps
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                if can_create_goals:
                    with st.form(f"action_step_form_{goal.goal_id}"):
                        step_desc = st.text_input("New action step", key=f"step_desc_{goal.goal_id}")
                        step_due = st.date_input("Due date", value=date.today(), key=f"step_due_{goal.goal_id}")
                        step_status_choice = st.selectbox("Status", [s.status_name for s in statuses], key=f"step_status_{goal.goal_id}")
                        step_submitted = st.form_submit_button("Add action step", type="primary")
                    if step_submitted and step_desc.strip():
                        session.add(IDPActionStep(
                            goal_id=goal.goal_id,
                            description=step_desc.strip(),
                            status_id=next(s.status_id for s in statuses if s.status_name == step_status_choice),
                            due_date=step_due,
                        ))
                        session.commit()
                        st.rerun()

                # --- Work completed toward this goal (Assignments replaced Training Sessions for this) ---
                st.markdown("**Work completed toward this goal**")
                completed_assignments = [a for a in goal.linked_assignments if a.completed]
                if not completed_assignments and not goal.linked_sessions:
                    st.caption("No completed work logged toward this goal yet -- assign one from Player Assignments and mark it completed once it's done.")
                else:
                    rows = [
                        {
                            "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                            "Type": a.session_type.type_name if a.session_type else "—",
                            "What happened": a.completed_notes or "",
                        }
                        for a in sorted(completed_assignments, key=lambda a: a.scheduled_date, reverse=True)
                    ]
                    # Older, already-logged Training Sessions still show for continuity
                    rows += [
                        {
                            "Date": s.session_date.strftime("%Y-%m-%d (%a)"),
                            "Type": s.session_type.type_name if s.session_type else "—",
                            "What happened": s.notes or "",
                        }
                        for s in sorted(goal.linked_sessions, key=lambda s: s.session_date, reverse=True)
                    ]
                    st.dataframe(rows, use_container_width=True, hide_index=True)

                # --- Progress notes ---
                st.markdown("**Progress notes**")
                if not goal.progress_notes:
                    st.caption("No progress notes yet.")
                else:
                    for note in sorted(goal.progress_notes, key=lambda n: n.created_at, reverse=True):
                        st.caption(f"{note.created_at.strftime('%Y-%m-%d (%a)')}")
                        st.write(note.note_text)

                if can_add_progress_notes:
                    with st.form(f"progress_note_form_{goal.goal_id}"):
                        note_text = st.text_area("New progress note", key=f"note_text_{goal.goal_id}")
                        note_submitted = st.form_submit_button("Add progress note", type="primary")
                    if note_submitted and note_text.strip():
                        session.add(IDPProgressNote(
                            goal_id=goal.goal_id,
                            note_text=note_text.strip(),
                            created_by_user_id=current_user_id,
                        ))
                        session.commit()
                        st.rerun()

    st.divider()

    # --- New goal ---
    if not can_create_goals:
        st.info("Your role can add progress notes to existing goals, but not create new goals." if can_add_progress_notes else "Your role has read-only access to IDP.")
    else:
        st.subheader("New development goal")

        # Category, assessment link, and target metric live outside the
        # form so each selection can react live and auto-fill the
        # baseline value -- widgets inside st.form don't rerun until
        # submit, so this couldn't work reactively in there.
        goal_categories = [c for c in categories if c.category_name != "Anthropometrics"]
        category_names = [c.category_name for c in goal_categories]
        category_choice = st.selectbox("Category", category_names, key="new_goal_category")
        linked_category_id = next(c.category_id for c in goal_categories if c.category_name == category_choice)

        player_assessments = (
            session.query(Assessment)
            .filter(Assessment.player_id == selected_player_id, Assessment.category_id == linked_category_id)
            .order_by(Assessment.assessment_date.desc())
            .limit(50)
            .all()
        )
        assessments_by_key = {f"{a.assessment_date.strftime('%Y-%m-%d (%a)')} (#{a.assessment_id})": a for a in player_assessments}
        assessment_options = ["-- Not linked to a specific assessment --"] + list(assessments_by_key.keys())
        assessment_choice = st.selectbox("Link to assessment (optional)", assessment_options, key="new_goal_assessment")
        selected_assessment = assessments_by_key.get(assessment_choice)

        category_test_types = (
            session.query(AssessmentTestType)
            .filter(AssessmentTestType.category_id == linked_category_id)
            .order_by(AssessmentTestType.display_order)
            .all()
        )
        target_test_type_id = None
        baseline_value = None
        if category_test_types:
            test_types_by_name = {t.test_name: t for t in category_test_types}
            target_metric_choice = st.selectbox(
                "Target metric (optional)",
                ["-- No specific metric --"] + list(test_types_by_name.keys()),
                key="new_goal_target_metric",
            )
            if target_metric_choice != "-- No specific metric --":
                target_test_type = test_types_by_name[target_metric_choice]
                target_test_type_id = target_test_type.test_type_id
                if selected_assessment:
                    matching_result = (
                        session.query(AssessmentResult)
                        .filter(AssessmentResult.assessment_id == selected_assessment.assessment_id, AssessmentResult.test_type_id == target_test_type_id)
                        .first()
                    )
                    if matching_result:
                        baseline_value = float(matching_result.value)
                        st.caption(f"Baseline auto-filled from the linked assessment: {baseline_value} {target_test_type.unit or ''}")
        else:
            st.caption("No specific tests defined yet for this category -- target metric isn't available until they are.")

        with st.form("new_goal_form"):
            if target_test_type_id:
                baseline_value = st.number_input(
                    "Baseline value", value=baseline_value if baseline_value is not None else 0.0, step=0.1, format="%.2f"
                )
                target_value = st.number_input("Target value", value=0.0, step=0.1, format="%.2f")
                target_date = st.date_input("Target date", value=date.today() + timedelta(days=60))
            description = st.text_area("Goal description")
            status_choice = st.selectbox("Initial status", [s.status_name for s in statuses])
            submitted = st.form_submit_button("Create goal", type="primary")

        if submitted:
            if not description.strip():
                st.error("Goal description is required.")
            else:
                source_assessment_id = selected_assessment.assessment_id if selected_assessment else None

                new_goal = IDPGoal(
                    player_id=selected_player_id,
                    category_id=linked_category_id,
                    source_assessment_id=source_assessment_id,
                    target_test_type_id=target_test_type_id,
                    baseline_value=baseline_value if target_test_type_id else None,
                    target_value=target_value if target_test_type_id else None,
                    target_date=target_date if target_test_type_id else None,
                    description=description.strip(),
                    status_id=next(s.status_id for s in statuses if s.status_name == status_choice),
                    created_by_user_id=current_user_id,
                )
                session.add(new_goal)
                session.commit()
                st.success(f"Created goal for {selected_player.first_name} {selected_player.last_name}.")
                st.rerun()

finally:
    session.close()

page_footer()