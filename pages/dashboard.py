"""
GBO — Dashboard (Milestone: Aug 14-15).

Role-adaptive:
  - Athletic Trainer: injury / return-to-play focus (player status
    breakdown, recent Arm Health pain scores, recent Arm Care sessions)
  - Strength Coach: S&C focus (recent Upper/Lower Body Strength,
    Explosive Power, Rotational Power assessments; recent Conditioning
    sessions)
  - Sports Scientist: data/analytics focus (assessment volume, IDP
    goals needing attention -- overdue ones specifically, team-wide
    recent assessments across all categories, tracked-session activity
    combining Bullpen + Hitter Tracking) -- deliberately NOT scheduling/
    coaching-operations content (AT Appointments has no relevance here
    at all, so it's excluded from their nav entirely, not just this page)
  - Everyone else (Administrator, Head Coach, Coach, Data Analyst):
    general overview -- roster size, open IDP goals, recent
    assessments/sessions across all categories

Every view is scoped to whichever players the logged-in role can see
(same can_view_all_players filtering used everywhere else) -- this is
also what makes a Coach assigned only to pitchers naturally see a
pitcher-focused dashboard, without needing separate "Pitching Coach" /
"Hitting Coach" roles.

Player role gets a simple placeholder for now -- the full player-facing
view is a separate future build (My Development).
"""

import streamlit as st
import base64
import os
from datetime import date, timedelta, datetime
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, Assessment, AssessmentResult,
    AssessmentTestType, AssessmentCategory, IDPGoal, IDPActionStep, IDPStatus,
    TrainingSession, PlayerStatus, TeamScheduleEvent, TeamEventType,
    User, PlayerAssignment, ATAppointment, TrainingRoutine, BullpenSession,
    HitterTrackingSession,
)
from ui_components import render_kpi_cards, page_header, page_footer, empty_state, render_player_profile_header, render_staff_profile_header
from bucket_system import compute_bucket_system
from bucket_system_display import render_score_rings

page_header("Dashboard")

_logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "GBO_logo-06.png")
try:
    with open(_logo_path, "rb") as _f:
        GBO_LOGO_BASE64 = base64.b64encode(_f.read()).decode("utf-8")
except FileNotFoundError:
    GBO_LOGO_BASE64 = None

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name == "Player":
    session = get_session()
    try:
        me = session.query(User).filter(User.user_id == current_user_id).first()
        if me is None or me.player_id is None:
            st.info("Your player profile isn't linked yet. Check with an administrator.")
            page_footer()
            st.stop()

        my_player = (
            session.query(Player)
            .options(joinedload(Player.team), joinedload(Player.player_position), joinedload(Player.player_class))
            .filter(Player.player_id == me.player_id)
            .first()
        )
        render_player_profile_header(my_player, logo_base64=GBO_LOGO_BASE64)

        # --- Physical testing: the big overall scores, shown right up
        # top like the reference dashboard layout. Full breakdown by
        # metric lives on My Assessments, not here -- this is just
        # Overall/Strength/Power at a glance. ---
        bucket_data = compute_bucket_system(session, my_player.player_id)
        if render_score_rings(bucket_data, key_prefix="dash"):
            st.caption("Full breakdown by metric is on My Assessments.")

        today = date.today()
        week_ahead = today + timedelta(days=7)

        # --- Today: everything due today in one place, ahead of the weekly views ---
        st.divider()
        st.markdown("### Today")

        todays_events = (
            session.query(TeamScheduleEvent)
            .options(
                joinedload(TeamScheduleEvent.event_type),
                joinedload(TeamScheduleEvent.routine).joinedload(TrainingRoutine.exercises),
            )
            .filter(
                TeamScheduleEvent.team_id == my_player.team_id,
                TeamScheduleEvent.scheduled_date == today,
                or_(TeamScheduleEvent.pitchers_only.is_(None), TeamScheduleEvent.pitchers_only == my_player.is_pitcher),
            )
            .order_by(TeamScheduleEvent.event_type_id)
            .all()
        )
        todays_assignments = (
            session.query(PlayerAssignment)
            .options(joinedload(PlayerAssignment.session_type), joinedload(PlayerAssignment.routine), joinedload(PlayerAssignment.bullpen_type), joinedload(PlayerAssignment.bullpen_script))
            .filter(PlayerAssignment.player_id == my_player.player_id, PlayerAssignment.scheduled_date == today)
            .all()
        )
        todays_appointments = (
            session.query(ATAppointment)
            .options(joinedload(ATAppointment.athletic_trainer))
            .filter(ATAppointment.player_id == my_player.player_id, ATAppointment.appointment_date == today)
            .order_by(ATAppointment.appointment_time)
            .all()
        )

        if not todays_events and not todays_assignments and not todays_appointments:
            st.caption("Nothing scheduled for today.")
        else:
            for e in todays_events:
                event_label = f"{e.event_type.type_name if e.event_type else 'Team'}: {e.title}"
                if e.routine:
                    with st.expander(f"**{event_label}** — {e.routine.routine_name}"):
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
                else:
                    st.markdown(f"- **{event_label}**")
            for a in todays_assignments:
                label = a.session_type.type_name if a.session_type else "Assignment"
                if a.routine:
                    label += f": {a.routine.routine_name}"
                elif a.bullpen_type:
                    label += f": {a.bullpen_type.type_name}"
                    if a.bullpen_script:
                        label += f" ({a.bullpen_script.script_name})"
                elif a.notes:
                    label += f": {a.notes}"
                st.markdown(f"- **{label}**")
            for a in todays_appointments:
                at_name = f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "Athletic Trainer"
                time_label = f" at {a.appointment_time}" if a.appointment_time else ""
                st.markdown(f"- **Appointment** with {at_name}{time_label}")

        st.caption("See **My Schedule** and **My Development** in the sidebar for the full week ahead and your development plan.")

    finally:
        session.close()
    page_footer()
    st.stop()

first_name = st.session_state.get("gbo_user_first_name", "")
last_name = st.session_state.get("gbo_user_last_name", "")
_header_session = get_session()
try:
    _current_user_row = _header_session.query(User).filter(User.user_id == current_user_id).first()
    _staff_photo_url = _current_user_row.photo_url if _current_user_row else None
finally:
    _header_session.close()
render_staff_profile_header(first_name, last_name, role_name, logo_base64=GBO_LOGO_BASE64, photo_url=_staff_photo_url)

session = get_session()
try:
    # --- Visible players (same role-based filtering as everywhere else) ---
    player_query = session.query(Player).options(joinedload(Player.status)).filter(Player.active.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    players = player_query.order_by(Player.last_name, Player.first_name).all()
    player_ids = [p.player_id for p in players]

    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
        page_footer()
        st.stop()

    week_ago = date.today() - timedelta(days=7)

    # =====================================================================
    # ATHLETIC TRAINER — injury / return-to-play focus
    # =====================================================================
    if role_name == "Athletic Trainer":
        status_counts = {}
        for p in players:
            name = p.status.status_name if p.status else "Unknown"
            status_counts[name] = status_counts.get(name, 0) + 1

        injured_count = status_counts.get("Injured", 0)
        medical_hold_count = status_counts.get("Medical Hold", 0)

        kpi_cards = [
            {"label": "Injured Players", "value": str(injured_count)},
            {"label": "Medical Hold", "value": str(medical_hold_count)},
        ]
        # Remaining statuses (Active, Redshirt, Inactive, etc.), skipping the two already shown above
        for name, count in status_counts.items():
            if name not in ("Injured", "Medical Hold"):
                kpi_cards.append({"label": name, "value": str(count)})

        render_kpi_cards(kpi_cards)

        st.divider()

        flagged_statuses = ("Injured", "Medical Hold")
        flagged_players = [p for p in players if p.status and p.status.status_name in flagged_statuses]

        st.subheader("Players currently Injured or on Medical Hold")
        if not flagged_players:
            st.caption("No players currently flagged.")
        else:
            st.dataframe(
                [
                    {
                        "Name": f"{p.first_name} {p.last_name}",
                        "Status": p.status.status_name if p.status else "—",
                        "Position": p.player_position.position_name if p.player_position else "—",
                    }
                    for p in flagged_players
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent Arm Health pain / readiness scores")
        pain_tests = (
            session.query(AssessmentResult)
            .join(AssessmentTestType)
            .join(Assessment)
            .options(joinedload(AssessmentResult.test_type), joinedload(AssessmentResult.assessment).joinedload(Assessment.player))
            .filter(
                Assessment.player_id.in_(player_ids),
                AssessmentTestType.test_name.like("Pain & Readiness:%"),
            )
            .order_by(Assessment.assessment_date.desc())
            .limit(15)
            .all()
        )
        if not pain_tests:
            st.caption("No Arm Health pain/readiness entries recorded yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": r.assessment.assessment_date.strftime("%Y-%m-%d (%a)"),
                        "Player": f"{r.assessment.player.first_name} {r.assessment.player.last_name}" if r.assessment.player else "—",
                        "Metric": r.test_type.test_name.replace("Pain & Readiness: ", ""),
                        "Score": round(float(r.value), 2),
                    }
                    for r in pain_tests
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent Arm Care sessions")
        arm_care_sessions = (
            session.query(TrainingSession)
            .join(TrainingSession.session_type)
            .options(joinedload(TrainingSession.player))
            .filter(TrainingSession.player_id.in_(player_ids))
            .filter(TrainingSession.session_type.has(type_name="Arm Care"))
            .order_by(TrainingSession.session_date.desc())
            .limit(10)
            .all()
        )
        if not arm_care_sessions:
            st.caption("No Arm Care sessions logged yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": s.session_date.strftime("%Y-%m-%d (%a)"),
                        "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                        "Notes": s.notes or "",
                    }
                    for s in arm_care_sessions
                ],
                use_container_width=True,
                hide_index=True,
            )

    # =====================================================================
    # STRENGTH COACH — S&C focus
    # =====================================================================
    elif role_name == "Strength Coach":
        sc_categories = ["Upper Body Strength", "Lower Body Strength", "Explosive Power", "Rotational Power"]

        assessments_this_week = (
            session.query(Assessment)
            .join(Assessment.category)
            .filter(
                Assessment.player_id.in_(player_ids),
                Assessment.assessment_date >= week_ago,
                AssessmentCategory.category_name.in_(sc_categories),
            )
            .count()
        )
        lifting_this_week = (
            session.query(PlayerAssignment)
            .join(PlayerAssignment.session_type)
            .filter(
                PlayerAssignment.player_id.in_(player_ids),
                PlayerAssignment.scheduled_date >= week_ago,
                PlayerAssignment.completed.is_(True),
            )
            .filter(PlayerAssignment.session_type.has(type_name="Lifting"))
            .count()
        )

        two_weeks_ago = week_ago - timedelta(days=7)
        assessments_prev_week = (
            session.query(Assessment)
            .join(Assessment.category)
            .filter(
                Assessment.player_id.in_(player_ids),
                Assessment.assessment_date >= two_weeks_ago,
                Assessment.assessment_date < week_ago,
                AssessmentCategory.category_name.in_(sc_categories),
            )
            .count()
        )
        lifting_prev_week = (
            session.query(PlayerAssignment)
            .join(PlayerAssignment.session_type)
            .filter(
                PlayerAssignment.player_id.in_(player_ids),
                PlayerAssignment.scheduled_date >= two_weeks_ago,
                PlayerAssignment.scheduled_date < week_ago,
                PlayerAssignment.completed.is_(True),
            )
            .filter(PlayerAssignment.session_type.has(type_name="Lifting"))
            .count()
        )

        render_kpi_cards([
            {"label": "Players", "value": str(len(players))},
            {
                "label": "S&C Assessments (7 days)",
                "value": str(assessments_this_week),
                "delta": f"{abs(assessments_this_week - assessments_prev_week)} vs last week",
                "delta_positive": assessments_this_week >= assessments_prev_week,
            },
            {
                "label": "Lifting Sessions (7 days)",
                "value": str(lifting_this_week),
                "delta": f"{abs(lifting_this_week - lifting_prev_week)} vs last week",
                "delta_positive": lifting_this_week >= lifting_prev_week,
            },
        ])

        st.divider()
        st.subheader("Upcoming scheduled lifts")
        team = players[0].team if players else None
        upcoming_lifts = (
            session.query(TeamScheduleEvent)
            .join(TeamScheduleEvent.event_type)
            .options(joinedload(TeamScheduleEvent.routine))
            .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date >= date.today())
            .filter(TeamEventType.type_name == "Lift")
            .order_by(TeamScheduleEvent.scheduled_date)
            .limit(10)
            .all()
        ) if team else []
        if not upcoming_lifts:
            st.caption("No upcoming lifts scheduled -- add some from the Team Schedule page.")
        else:
            st.dataframe(
                [
                    {
                        "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                        "Title": s.title,
                        "Routine": s.routine.routine_name if s.routine else "—",
                        "Notes": s.notes or "",
                    }
                    for s in upcoming_lifts
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent S&C assessments")
        recent_sc = (
            session.query(Assessment)
            .join(Assessment.category)
            .options(joinedload(Assessment.player), joinedload(Assessment.category))
            .filter(Assessment.player_id.in_(player_ids))
            .filter(AssessmentCategory.category_name.in_(sc_categories))
            .order_by(Assessment.assessment_date.desc())
            .limit(15)
            .all()
        )
        if not recent_sc:
            st.caption("No Strength/Power assessments recorded yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                        "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                        "Category": a.category.category_name if a.category else "—",
                    }
                    for a in recent_sc
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent Lifting workload (completed)")
        recent_lifting = (
            session.query(PlayerAssignment)
            .join(PlayerAssignment.session_type)
            .options(joinedload(PlayerAssignment.player))
            .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed.is_(True))
            .filter(PlayerAssignment.session_type.has(type_name="Lifting"))
            .order_by(PlayerAssignment.completed_at.desc())
            .limit(10)
            .all()
        )
        if not recent_lifting:
            st.caption("No completed Lifting assignments yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                        "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                        "What happened": s.completed_notes or "",
                    }
                    for s in recent_lifting
                ],
                use_container_width=True,
                hide_index=True,
            )

    # =====================================================================
    # SPORTS SCIENTIST — data/analytics focus
    # =====================================================================
    elif role_name == "Sports Scientist":
        assessments_this_week = (
            session.query(Assessment)
            .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= week_ago)
            .count()
        )

        completed_status = session.query(IDPStatus).filter(IDPStatus.status_name == "Completed").first()
        open_goals_query = session.query(IDPGoal).options(joinedload(IDPGoal.player), joinedload(IDPGoal.target_test_type)).filter(IDPGoal.player_id.in_(player_ids))
        if completed_status:
            open_goals_query = open_goals_query.filter(IDPGoal.status_id != completed_status.status_id)
        open_goals = open_goals_query.all()

        overdue_goals = [g for g in open_goals if g.target_date and g.target_date < date.today()]

        bullpen_sessions_this_week = (
            session.query(BullpenSession)
            .filter(BullpenSession.player_id.in_(player_ids), BullpenSession.session_date >= week_ago)
            .count()
        )
        hitter_sessions_this_week = (
            session.query(HitterTrackingSession)
            .filter(HitterTrackingSession.player_id.in_(player_ids), HitterTrackingSession.session_date >= week_ago)
            .count()
        )

        render_kpi_cards([
            {"label": "Assessments This Week", "value": str(assessments_this_week)},
            {"label": "Open IDP Goals", "value": str(len(open_goals))},
            {"label": "Goals Overdue", "value": str(len(overdue_goals))},
            {"label": "Tracked Sessions This Week", "value": str(bullpen_sessions_this_week + hitter_sessions_this_week)},
        ])

        st.divider()
        st.subheader("Player status")
        status_counts = {}
        for p in players:
            name = p.status.status_name if p.status else "Unknown"
            status_counts[name] = status_counts.get(name, 0) + 1
        st.write(" · ".join(f"{name}: {count}" for name, count in status_counts.items()) or "—")

        st.divider()
        st.subheader("Goals needing attention")
        if not overdue_goals:
            st.caption("No open goals are past their target date.")
        else:
            st.dataframe(
                [
                    {
                        "Player": f"{g.player.first_name} {g.player.last_name}" if g.player else "—",
                        "Metric": g.target_test_type.test_name if g.target_test_type else "—",
                        "Target date": g.target_date.strftime("%Y-%m-%d (%a)") if g.target_date else "—",
                    }
                    for g in overdue_goals
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent assessments (all categories)")
        recent_assessments = (
            session.query(Assessment)
            .options(joinedload(Assessment.player), joinedload(Assessment.category))
            .filter(Assessment.player_id.in_(player_ids))
            .order_by(Assessment.assessment_date.desc())
            .limit(15)
            .all()
        )
        if not recent_assessments:
            st.caption("No assessments recorded yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                        "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                        "Category": a.category.category_name if a.category else "—",
                    }
                    for a in recent_assessments
                ],
                use_container_width=True,
                hide_index=True,
            )

        st.divider()
        st.subheader("Recent tracked sessions (Bullpen + Hitter Tracking)")
        recent_bullpens = (
            session.query(BullpenSession)
            .options(joinedload(BullpenSession.player), joinedload(BullpenSession.bullpen_type))
            .filter(BullpenSession.player_id.in_(player_ids))
            .order_by(BullpenSession.session_date.desc())
            .limit(8)
            .all()
        )
        recent_hitter_sessions = (
            session.query(HitterTrackingSession)
            .options(joinedload(HitterTrackingSession.player), joinedload(HitterTrackingSession.session_type))
            .filter(HitterTrackingSession.player_id.in_(player_ids))
            .order_by(HitterTrackingSession.session_date.desc())
            .limit(8)
            .all()
        )
        combined_sessions = sorted(
            [
                {"Date": b.session_date, "Player": f"{b.player.first_name} {b.player.last_name}" if b.player else "—", "Type": f"Bullpen: {b.bullpen_type.type_name}" if b.bullpen_type else "Bullpen"}
                for b in recent_bullpens
            ] + [
                {"Date": h.session_date, "Player": f"{h.player.first_name} {h.player.last_name}" if h.player else "—", "Type": h.session_type.type_name if h.session_type else "Hitter Tracking"}
                for h in recent_hitter_sessions
            ],
            key=lambda r: r["Date"], reverse=True,
        )[:10]
        if not combined_sessions:
            st.caption("No tracked sessions logged yet.")
        else:
            st.dataframe(
                [{"Date": r["Date"].strftime("%Y-%m-%d (%a)"), "Player": r["Player"], "Type": r["Type"]} for r in combined_sessions],
                use_container_width=True,
                hide_index=True,
            )

    # =====================================================================
    # EVERYONE ELSE — general overview
    # =====================================================================
    else:
        open_goal_count = 0
        completed_status = session.query(IDPStatus).filter(IDPStatus.status_name == "Completed").first()
        open_goals_query = session.query(IDPGoal).filter(IDPGoal.player_id.in_(player_ids))
        if completed_status:
            open_goals_query = open_goals_query.filter(IDPGoal.status_id != completed_status.status_id)
        open_goal_count = open_goals_query.count()

        assessments_this_week = (
            session.query(Assessment)
            .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= week_ago)
            .count()
        )
        sessions_this_week = (
            session.query(PlayerAssignment)
            .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed_at >= week_ago, PlayerAssignment.completed.is_(True))
            .count()
        )

        two_weeks_ago = week_ago - timedelta(days=7)
        assessments_prev_week = (
            session.query(Assessment)
            .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= two_weeks_ago, Assessment.assessment_date < week_ago)
            .count()
        )
        sessions_prev_week = (
            session.query(PlayerAssignment)
            .filter(
                PlayerAssignment.player_id.in_(player_ids),
                PlayerAssignment.completed_at >= two_weeks_ago,
                PlayerAssignment.completed_at < week_ago,
                PlayerAssignment.completed.is_(True),
            )
            .count()
        )

        render_kpi_cards([
            {"label": "Players", "value": str(len(players))},
            {"label": "Open IDP Goals", "value": str(open_goal_count)},
            {
                "label": "Assessments (7 days)",
                "value": str(assessments_this_week),
                "delta": f"{abs(assessments_this_week - assessments_prev_week)} vs last week",
                "delta_positive": assessments_this_week >= assessments_prev_week,
            },
            {
                "label": "Completed Assignments (7 days)",
                "value": str(sessions_this_week),
                "delta": f"{abs(sessions_this_week - sessions_prev_week)} vs last week",
                "delta_positive": sessions_this_week >= sessions_prev_week,
            },
        ])

        st.divider()

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Recent assessments")
            recent_assessments = (
                session.query(Assessment)
                .options(joinedload(Assessment.player), joinedload(Assessment.category))
                .filter(Assessment.player_id.in_(player_ids))
                .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
                .limit(10)
                .all()
            )
            if not recent_assessments:
                st.caption("No assessments recorded yet.")
            else:
                st.dataframe(
                    [
                        {
                            "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                            "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                            "Category": a.category.category_name if a.category else "—",
                        }
                        for a in recent_assessments
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

        with col2:
            st.subheader("Recently completed assignments")
            recent_sessions = (
                session.query(PlayerAssignment)
                .options(joinedload(PlayerAssignment.player), joinedload(PlayerAssignment.session_type))
                .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed.is_(True))
                .order_by(PlayerAssignment.completed_at.desc())
                .limit(10)
                .all()
            )
            if not recent_sessions:
                st.caption("No completed assignments yet.")
            else:
                st.dataframe(
                    [
                        {
                            "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                            "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                            "Type": s.session_type.type_name if s.session_type else "—",
                        }
                        for s in recent_sessions
                    ],
                    use_container_width=True,
                    hide_index=True,
                )

        st.divider()
        st.subheader("Recent bullpens")
        recent_bullpens = (
            session.query(BullpenSession)
            .options(joinedload(BullpenSession.player), joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.pitches))
            .filter(BullpenSession.player_id.in_(player_ids))
            .order_by(BullpenSession.session_date.desc())
            .limit(8)
            .all()
        )
        if not recent_bullpens:
            st.caption("No bullpen sessions logged yet.")
        else:
            st.dataframe(
                [
                    {
                        "Date": b.session_date.strftime("%Y-%m-%d (%a)"),
                        "Pitcher": f"{b.player.first_name} {b.player.last_name}" if b.player else "—",
                        "Type": b.bullpen_type.type_name if b.bullpen_type else "—",
                        "Pitches": len(b.pitches),
                    }
                    for b in recent_bullpens
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption("Open Bullpen Tracking for full pitch-by-pitch detail and execution summaries.")

        st.divider()
        st.subheader("Open IDP goals")
        open_goals = (
            open_goals_query
            .options(joinedload(IDPGoal.player), joinedload(IDPGoal.category), joinedload(IDPGoal.status))
            .order_by(IDPGoal.created_at.desc())
            .limit(15)
            .all()
        )
        if not open_goals:
            st.caption("No open goals right now.")
        else:
            st.dataframe(
                [
                    {
                        "Player": f"{g.player.first_name} {g.player.last_name}" if g.player else "—",
                        "Category": g.category.category_name if g.category else "—",
                        "Goal": g.description[:60] + ("..." if len(g.description) > 60 else ""),
                        "Status": g.status.status_name if g.status else "—",
                    }
                    for g in open_goals
                ],
                use_container_width=True,
                hide_index=True,
            )

finally:
    session.close()

page_footer()