"""
GBO -- Dashboard module (Shiny).

Full port of pages/dashboard.py -- role-adaptive:
  - Player: profile header, physical-testing score rings (compact --
    full breakdown lives on My Assessments), and a "Today" list pulling
    together anything due today (team events, assignments, AT
    appointments) ahead of the weekly views on My Schedule.
  - Athletic Trainer: injury / return-to-play focus (player status
    breakdown, recent Arm Health pain scores, recent Arm Care sessions)
  - Strength Coach: S&C focus (recent Upper/Lower Body Strength,
    Explosive Power, Rotational Power assessments; recent Conditioning
    sessions)
  - Sports Scientist: data/analytics focus (assessment volume, IDP
    goals needing attention -- overdue ones specifically, team-wide
    recent assessments across all categories, tracked-session activity
    combining Bullpen + Hitter Tracking) -- deliberately NOT scheduling/
    coaching-operations content, same as the original
  - Everyone else (Administrator, Head Coach, Coach, Data Analyst):
    general overview -- roster size, open IDP goals, recent
    assessments/sessions across all categories

Every staff view is scoped to whichever players the logged-in role can
see (app_state.can_view_all_players(), same rule used everywhere else)
-- this is also what makes a Coach assigned only to pitchers naturally
see a pitcher-focused dashboard, without separate "Pitching Coach" /
"Hitting Coach" roles.

Same st.dataframe(list_of_dicts) -> table conversion every other
migrated module uses, but via the new shared ui_helpers.render_dict_table()
helper (this file has ~10 of these tables -- the first module to
actually need that dedup, see that function's docstring).

One wording change from the original: its "See My Schedule and My
Development in the sidebar..." caption assumed Streamlit's sidebar nav.
This app uses a top navset_bar instead (see shiny_app/app.py), so that
line just says "in the navigation" here.
"""

from datetime import date, timedelta

from shiny import module, ui, render
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, Assessment, AssessmentResult,
    AssessmentTestType, AssessmentCategory, IDPGoal, IDPStatus,
    TrainingSession, TeamScheduleEvent, TeamEventType, User,
    PlayerAssignment, ATAppointment, TrainingRoutine, BullpenSession,
    HitterTrackingSession,
)
from bucket_system import compute_bucket_system

import ui_helpers
import bucket_display


@module.ui
def dashboard_ui():
    return ui.div(
        ui_helpers.page_header("Dashboard"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def dashboard_server(input, output, session, app_state):
    @render.ui
    def body():
        if not app_state.is_authenticated():
            return None

        role_name = app_state.role_name()
        current_user_id = app_state.user_id()
        can_view_all = app_state.can_view_all_players()
        mode = app_state.dark_mode() or "dark"

        db = get_session()
        try:
            if role_name == "Player":
                return _player_dashboard_ui(db, current_user_id, mode)

            sections = [
                _staff_header_ui(
                    db, current_user_id,
                    app_state.first_name() or "", app_state.last_name() or "",
                    role_name,
                )
            ]

            player_query = db.query(Player).options(joinedload(Player.status)).filter(Player.active.is_(True))
            if not can_view_all:
                assigned_ids = [
                    a.player_id for a in
                    db.query(StaffPlayerAssignment)
                    .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
                    .all()
                ]
                player_query = player_query.filter(Player.player_id.in_(assigned_ids))
            players = player_query.order_by(Player.last_name, Player.first_name).all()
            player_ids = [p.player_id for p in players]

            if not players:
                sections.append(ui_helpers.empty_state(
                    "No players to show yet." if can_view_all else "No players are currently assigned to you."
                ))
                return ui.div(*sections)

            week_ago = date.today() - timedelta(days=7)

            if role_name == "Athletic Trainer":
                sections.append(_athletic_trainer_section(db, players, player_ids))
            elif role_name == "Strength Coach":
                sections.append(_strength_coach_section(db, players, player_ids, week_ago))
            elif role_name == "Sports Scientist":
                sections.append(_sports_scientist_section(db, players, player_ids, week_ago))
            else:
                sections.append(_general_section(db, players, player_ids, week_ago))

            return ui.div(*sections)
        finally:
            db.close()


def _staff_header_ui(db, current_user_id, first_name, last_name, role_name):
    current_user_row = db.query(User).filter(User.user_id == current_user_id).first()
    photo_url = current_user_row.photo_url if current_user_row else None
    return ui_helpers.render_staff_profile_header(first_name, last_name, role_name, photo_url=photo_url)


# =============================================================================
# PLAYER -- profile header, score rings, "Today"
# =============================================================================

def _player_dashboard_ui(db, current_user_id, mode):
    me = db.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        return ui.p(
            "Your player profile isn't linked yet. Check with an administrator.",
            class_="text-muted",
        )

    my_player = (
        db.query(Player)
        .options(joinedload(Player.team), joinedload(Player.player_position), joinedload(Player.player_class))
        .filter(Player.player_id == me.player_id)
        .first()
    )
    sections = [ui_helpers.render_player_profile_header(my_player)]

    # --- Physical testing: the big overall scores, shown right up top
    # like the reference dashboard layout. Full breakdown by metric
    # lives on My Assessments, not here -- this is just
    # Overall/Strength/Power at a glance. ---
    bucket_data = compute_bucket_system(db, my_player.player_id)
    rings = bucket_display.build_score_rings(bucket_data, "dash", mode=mode)
    if rings is not None:
        sections.append(rings)
        sections.append(ui.p("Full breakdown by metric is on My Assessments.", class_="text-muted small"))

    today = date.today()

    # --- Today: everything due today in one place, ahead of the weekly views ---
    sections.append(ui.hr())
    sections.append(ui.h5("Today", class_="gbo-section-title"))

    todays_events = (
        db.query(TeamScheduleEvent)
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
        db.query(PlayerAssignment)
        .options(
            joinedload(PlayerAssignment.session_type),
            joinedload(PlayerAssignment.routine),
            joinedload(PlayerAssignment.bullpen_type),
            joinedload(PlayerAssignment.bullpen_script),
        )
        .filter(PlayerAssignment.player_id == my_player.player_id, PlayerAssignment.scheduled_date == today)
        .all()
    )
    todays_appointments = (
        db.query(ATAppointment)
        .options(joinedload(ATAppointment.athletic_trainer))
        .filter(ATAppointment.player_id == my_player.player_id, ATAppointment.appointment_date == today)
        .order_by(ATAppointment.appointment_time)
        .all()
    )

    if not todays_events and not todays_assignments and not todays_appointments:
        sections.append(ui.p("Nothing scheduled for today.", class_="text-muted small"))
    else:
        today_items = []
        for e in todays_events:
            event_label = f"{e.event_type.type_name if e.event_type else 'Team'}: {e.title}"
            if e.routine:
                panel_content = []
                if e.routine.description:
                    panel_content.append(ui.p(e.routine.description))
                for ex in e.routine.exercises:
                    ex_label = ex.exercise_name
                    if ex.sets or ex.reps:
                        ex_label += f" — {ex.sets or '—'} sets x {ex.reps or '—'}"
                    panel_content.append(ui.p(ui.strong(ex_label), class_="mb-1"))
                    if ex.video_url:
                        panel_content.append(
                            ui.tags.video(
                                ui.tags.source(src=ex.video_url),
                                controls=True,
                                style="max-width:100%; margin-bottom: 8px;",
                            )
                        )
                    if ex.notes:
                        panel_content.append(ui.p(ex.notes, class_="text-muted small"))
                today_items.append(
                    ui.accordion(
                        ui.accordion_panel(f"{event_label} — {e.routine.routine_name}", *panel_content),
                        open=False, id=None,
                    )
                )
            else:
                today_items.append(ui.p(ui.strong(event_label), class_="mb-1"))
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
            today_items.append(ui.p(ui.strong(label), class_="mb-1"))
        for a in todays_appointments:
            at_name = f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "Athletic Trainer"
            time_label = f" at {a.appointment_time}" if a.appointment_time else ""
            today_items.append(ui.p(ui.strong("Appointment"), f" with {at_name}{time_label}", class_="mb-1"))
        sections.append(ui.div(*today_items))

    sections.append(ui.p(
        "See ", ui.strong("My Schedule"), " and ", ui.strong("My Development"),
        " in the navigation for the full week ahead and your development plan.",
        class_="text-muted small",
    ))

    return ui.div(*sections)


# =============================================================================
# ATHLETIC TRAINER -- injury / return-to-play focus
# =============================================================================

def _athletic_trainer_section(db, players, player_ids):
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
    for name, count in status_counts.items():
        if name not in ("Injured", "Medical Hold"):
            kpi_cards.append({"label": name, "value": str(count)})

    sections = [ui_helpers.render_kpi_cards(kpi_cards), ui.hr()]

    flagged_statuses = ("Injured", "Medical Hold")
    flagged_players = [p for p in players if p.status and p.status.status_name in flagged_statuses]

    sections.append(ui.h5("Players currently Injured or on Medical Hold", class_="gbo-section-title"))
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Name": f"{p.first_name} {p.last_name}",
                "Status": p.status.status_name if p.status else "—",
                "Position": p.player_position.position_name if p.player_position else "—",
            }
            for p in flagged_players
        ],
        empty_message="No players currently flagged.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent Arm Health pain / readiness scores", class_="gbo-section-title"))
    pain_tests = (
        db.query(AssessmentResult)
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
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": r.assessment.assessment_date.strftime("%Y-%m-%d (%a)"),
                "Player": f"{r.assessment.player.first_name} {r.assessment.player.last_name}" if r.assessment.player else "—",
                "Metric": r.test_type.test_name.replace("Pain & Readiness: ", ""),
                "Score": round(float(r.value), 2),
            }
            for r in pain_tests
        ],
        empty_message="No Arm Health pain/readiness entries recorded yet.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent Arm Care sessions", class_="gbo-section-title"))
    arm_care_sessions = (
        db.query(TrainingSession)
        .join(TrainingSession.session_type)
        .options(joinedload(TrainingSession.player))
        .filter(TrainingSession.player_id.in_(player_ids))
        .filter(TrainingSession.session_type.has(type_name="Arm Care"))
        .order_by(TrainingSession.session_date.desc())
        .limit(10)
        .all()
    )
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": s.session_date.strftime("%Y-%m-%d (%a)"),
                "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                "Notes": s.notes or "",
            }
            for s in arm_care_sessions
        ],
        empty_message="No Arm Care sessions logged yet.",
    ))

    return ui.div(*sections)


# =============================================================================
# STRENGTH COACH -- S&C focus
# =============================================================================

def _strength_coach_section(db, players, player_ids, week_ago):
    sc_categories = ["Upper Body Strength", "Lower Body Strength", "Explosive Power", "Rotational Power"]

    assessments_this_week = (
        db.query(Assessment)
        .join(Assessment.category)
        .filter(
            Assessment.player_id.in_(player_ids),
            Assessment.assessment_date >= week_ago,
            AssessmentCategory.category_name.in_(sc_categories),
        )
        .count()
    )
    lifting_this_week = (
        db.query(PlayerAssignment)
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
        db.query(Assessment)
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
        db.query(PlayerAssignment)
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

    sections = [ui_helpers.render_kpi_cards([
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
    ])]

    sections.append(ui.hr())
    sections.append(ui.h5("Upcoming scheduled lifts", class_="gbo-section-title"))
    team = players[0].team if players else None
    upcoming_lifts = (
        db.query(TeamScheduleEvent)
        .join(TeamScheduleEvent.event_type)
        .options(joinedload(TeamScheduleEvent.routine))
        .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date >= date.today())
        .filter(TeamEventType.type_name == "Lift")
        .order_by(TeamScheduleEvent.scheduled_date)
        .limit(10)
        .all()
    ) if team else []
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                "Title": s.title,
                "Routine": s.routine.routine_name if s.routine else "—",
                "Notes": s.notes or "",
            }
            for s in upcoming_lifts
        ],
        empty_message="No upcoming lifts scheduled -- add some from the Team Schedule page.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent S&C assessments", class_="gbo-section-title"))
    recent_sc = (
        db.query(Assessment)
        .join(Assessment.category)
        .options(joinedload(Assessment.player), joinedload(Assessment.category))
        .filter(Assessment.player_id.in_(player_ids))
        .filter(AssessmentCategory.category_name.in_(sc_categories))
        .order_by(Assessment.assessment_date.desc())
        .limit(15)
        .all()
    )
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                "Category": a.category.category_name if a.category else "—",
            }
            for a in recent_sc
        ],
        empty_message="No Strength/Power assessments recorded yet.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent Lifting workload (completed)", class_="gbo-section-title"))
    recent_lifting = (
        db.query(PlayerAssignment)
        .join(PlayerAssignment.session_type)
        .options(joinedload(PlayerAssignment.player))
        .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed.is_(True))
        .filter(PlayerAssignment.session_type.has(type_name="Lifting"))
        .order_by(PlayerAssignment.completed_at.desc())
        .limit(10)
        .all()
    )
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                "What happened": s.completed_notes or "",
            }
            for s in recent_lifting
        ],
        empty_message="No completed Lifting assignments yet.",
    ))

    return ui.div(*sections)


# =============================================================================
# SPORTS SCIENTIST -- data/analytics focus
# =============================================================================

def _sports_scientist_section(db, players, player_ids, week_ago):
    assessments_this_week = (
        db.query(Assessment)
        .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= week_ago)
        .count()
    )

    completed_status = db.query(IDPStatus).filter(IDPStatus.status_name == "Completed").first()
    open_goals_query = db.query(IDPGoal).options(joinedload(IDPGoal.player), joinedload(IDPGoal.target_test_type)).filter(IDPGoal.player_id.in_(player_ids))
    if completed_status:
        open_goals_query = open_goals_query.filter(IDPGoal.status_id != completed_status.status_id)
    open_goals = open_goals_query.all()

    overdue_goals = [g for g in open_goals if g.target_date and g.target_date < date.today()]

    bullpen_sessions_this_week = (
        db.query(BullpenSession)
        .filter(BullpenSession.player_id.in_(player_ids), BullpenSession.session_date >= week_ago)
        .count()
    )
    hitter_sessions_this_week = (
        db.query(HitterTrackingSession)
        .filter(HitterTrackingSession.player_id.in_(player_ids), HitterTrackingSession.session_date >= week_ago)
        .count()
    )

    sections = [ui_helpers.render_kpi_cards([
        {"label": "Assessments This Week", "value": str(assessments_this_week)},
        {"label": "Open IDP Goals", "value": str(len(open_goals))},
        {"label": "Goals Overdue", "value": str(len(overdue_goals))},
        {"label": "Tracked Sessions This Week", "value": str(bullpen_sessions_this_week + hitter_sessions_this_week)},
    ])]

    sections.append(ui.hr())
    sections.append(ui.h5("Player status", class_="gbo-section-title"))
    status_counts = {}
    for p in players:
        name = p.status.status_name if p.status else "Unknown"
        status_counts[name] = status_counts.get(name, 0) + 1
    sections.append(ui.p(" · ".join(f"{name}: {count}" for name, count in status_counts.items()) or "—"))

    sections.append(ui.hr())
    sections.append(ui.h5("Goals needing attention", class_="gbo-section-title"))
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Player": f"{g.player.first_name} {g.player.last_name}" if g.player else "—",
                "Metric": g.target_test_type.test_name if g.target_test_type else "—",
                "Target date": g.target_date.strftime("%Y-%m-%d (%a)") if g.target_date else "—",
            }
            for g in overdue_goals
        ],
        empty_message="No open goals are past their target date.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent assessments (all categories)", class_="gbo-section-title"))
    recent_assessments = (
        db.query(Assessment)
        .options(joinedload(Assessment.player), joinedload(Assessment.category))
        .filter(Assessment.player_id.in_(player_ids))
        .order_by(Assessment.assessment_date.desc())
        .limit(15)
        .all()
    )
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                "Category": a.category.category_name if a.category else "—",
            }
            for a in recent_assessments
        ],
        empty_message="No assessments recorded yet.",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent tracked sessions (Bullpen + Hitter Tracking)", class_="gbo-section-title"))
    recent_bullpens = (
        db.query(BullpenSession)
        .options(joinedload(BullpenSession.player), joinedload(BullpenSession.bullpen_type))
        .filter(BullpenSession.player_id.in_(player_ids))
        .order_by(BullpenSession.session_date.desc())
        .limit(8)
        .all()
    )
    recent_hitter_sessions = (
        db.query(HitterTrackingSession)
        .options(joinedload(HitterTrackingSession.player), joinedload(HitterTrackingSession.session_type))
        .filter(HitterTrackingSession.player_id.in_(player_ids))
        .order_by(HitterTrackingSession.session_date.desc())
        .limit(8)
        .all()
    )
    combined_sessions = sorted(
        [
            {
                "Date": b.session_date,
                "Player": f"{b.player.first_name} {b.player.last_name}" if b.player else "—",
                "Type": f"Bullpen: {b.bullpen_type.type_name}" if b.bullpen_type else "Bullpen",
            }
            for b in recent_bullpens
        ] + [
            {
                "Date": h.session_date,
                "Player": f"{h.player.first_name} {h.player.last_name}" if h.player else "—",
                "Type": h.session_type.type_name if h.session_type else "Hitter Tracking",
            }
            for h in recent_hitter_sessions
        ],
        key=lambda r: r["Date"], reverse=True,
    )[:10]
    sections.append(ui_helpers.render_dict_table(
        [{"Date": r["Date"].strftime("%Y-%m-%d (%a)"), "Player": r["Player"], "Type": r["Type"]} for r in combined_sessions],
        empty_message="No tracked sessions logged yet.",
    ))

    return ui.div(*sections)


# =============================================================================
# EVERYONE ELSE -- general overview (Administrator, Head Coach, Coach, Data Analyst)
# =============================================================================

def _general_section(db, players, player_ids, week_ago):
    completed_status = db.query(IDPStatus).filter(IDPStatus.status_name == "Completed").first()
    open_goals_query = db.query(IDPGoal).filter(IDPGoal.player_id.in_(player_ids))
    if completed_status:
        open_goals_query = open_goals_query.filter(IDPGoal.status_id != completed_status.status_id)
    open_goal_count = open_goals_query.count()

    assessments_this_week = (
        db.query(Assessment)
        .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= week_ago)
        .count()
    )
    sessions_this_week = (
        db.query(PlayerAssignment)
        .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed_at >= week_ago, PlayerAssignment.completed.is_(True))
        .count()
    )

    two_weeks_ago = week_ago - timedelta(days=7)
    assessments_prev_week = (
        db.query(Assessment)
        .filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= two_weeks_ago, Assessment.assessment_date < week_ago)
        .count()
    )
    sessions_prev_week = (
        db.query(PlayerAssignment)
        .filter(
            PlayerAssignment.player_id.in_(player_ids),
            PlayerAssignment.completed_at >= two_weeks_ago,
            PlayerAssignment.completed_at < week_ago,
            PlayerAssignment.completed.is_(True),
        )
        .count()
    )

    sections = [ui_helpers.render_kpi_cards([
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
    ])]

    sections.append(ui.hr())

    recent_assessments = (
        db.query(Assessment)
        .options(joinedload(Assessment.player), joinedload(Assessment.category))
        .filter(Assessment.player_id.in_(player_ids))
        .order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc())
        .limit(10)
        .all()
    )
    col1 = ui.div(
        ui.h5("Recent assessments", class_="gbo-section-title"),
        ui_helpers.render_dict_table(
            [
                {
                    "Date": a.assessment_date.strftime("%Y-%m-%d (%a)"),
                    "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                    "Category": a.category.category_name if a.category else "—",
                }
                for a in recent_assessments
            ],
            empty_message="No assessments recorded yet.",
        ),
    )

    recent_sessions = (
        db.query(PlayerAssignment)
        .options(joinedload(PlayerAssignment.player), joinedload(PlayerAssignment.session_type))
        .filter(PlayerAssignment.player_id.in_(player_ids), PlayerAssignment.completed.is_(True))
        .order_by(PlayerAssignment.completed_at.desc())
        .limit(10)
        .all()
    )
    col2 = ui.div(
        ui.h5("Recently completed assignments", class_="gbo-section-title"),
        ui_helpers.render_dict_table(
            [
                {
                    "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
                    "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—",
                    "Type": s.session_type.type_name if s.session_type else "—",
                }
                for s in recent_sessions
            ],
            empty_message="No completed assignments yet.",
        ),
    )

    sections.append(ui.layout_columns(col1, col2))

    sections.append(ui.hr())
    sections.append(ui.h5("Recent bullpens", class_="gbo-section-title"))
    recent_bullpens = (
        db.query(BullpenSession)
        .options(joinedload(BullpenSession.player), joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.pitches))
        .filter(BullpenSession.player_id.in_(player_ids))
        .order_by(BullpenSession.session_date.desc())
        .limit(8)
        .all()
    )
    if not recent_bullpens:
        sections.append(ui_helpers.empty_state("No bullpen sessions logged yet."))
    else:
        sections.append(ui_helpers.render_dict_table([
            {
                "Date": b.session_date.strftime("%Y-%m-%d (%a)"),
                "Pitcher": f"{b.player.first_name} {b.player.last_name}" if b.player else "—",
                "Type": b.bullpen_type.type_name if b.bullpen_type else "—",
                "Pitches": len(b.pitches),
            }
            for b in recent_bullpens
        ]))
        sections.append(ui.p("Open Bullpen Tracking for full pitch-by-pitch detail and execution summaries.", class_="text-muted small"))

    sections.append(ui.hr())
    sections.append(ui.h5("Open IDP goals", class_="gbo-section-title"))
    open_goals = (
        open_goals_query
        .options(joinedload(IDPGoal.player), joinedload(IDPGoal.category), joinedload(IDPGoal.status))
        .order_by(IDPGoal.created_at.desc())
        .limit(15)
        .all()
    )
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Player": f"{g.player.first_name} {g.player.last_name}" if g.player else "—",
                "Category": g.category.category_name if g.category else "—",
                "Goal": g.description[:60] + ("..." if len(g.description) > 60 else ""),
                "Status": g.status.status_name if g.status else "—",
            }
            for g in open_goals
        ],
        empty_message="No open goals right now.",
    ))

    return ui.div(*sections)
