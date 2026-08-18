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
  - Coach tagged Pitching specialty: pitching-staff KPIs -- a team-wide
    pitching line (ERA/WHIP/K%/K-BB) aggregated from every charted
    pitch thrown by anyone on this coach's roster, plus a per-pitcher
    leaderboard, over a coach-selectable window (current season vs.
    last 30 days -- see controls()/_pitching_staff_section()).
  - Coach tagged Hitting specialty: the mirror-opposite -- team-wide
    hitting line (AVG/OBP/SLG/OPS) plus a per-hitter leaderboard, same
    selectable window (see _hitter_staff_section()).
  - Head Coach, and a Coach with no specialty tag (Both/unset): team-
    ops focus (team record, next game, this week's team schedule, full
    player-availability detail, recent game results) -- NOT assessment/
    assignment completion counts, which coaches don't manage day-to-day
    the way Sports Scientist/Strength Coach do, and NOT the pitching-
    or hitting-specific KPI split above, since a Head Coach oversees
    both sides of the ball rather than one specialty.
  - Administrator, Data Analyst: general overview -- roster size, open
    IDP goals, recent assessments/sessions across all categories (the
    original shared "everyone else" dashboard). Revisit Administrator's
    own dashboard as a separate pass later.

Every staff view is scoped to whichever players the logged-in role can
see (app_state.can_view_all_players(), same rule used everywhere else)
-- this is also what makes a Coach assigned only to pitchers naturally
see a pitcher-heavy roster feed into their dashboard, on top of the
specialty-based KPI split above.

Same st.dataframe(list_of_dicts) -> table conversion every other
migrated module uses, but via the new shared ui_helpers.render_dict_table()
helper (this file has ~10+ of these tables -- the first module to
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
    HitterTrackingSession, Game, Season,
)
from game_stats import get_pitching_pitches, get_batting_pitches, compute_pitching_line, compute_batting_line
from bucket_system import compute_bucket_system

import ui_helpers
import bucket_display

# How many of the team's most recent completed games count as "recent
# form" for the pitching-staff / hitter KPI window toggle -- a game-
# count window rather than a calendar-day one, since a coach thinks in
# terms of "the last few outings" and this rides out bye weeks/gaps in
# the schedule cleanly (a fixed day count can land on zero games one
# week and two full series the next). 5 games is roughly a weekend
# series plus a midweek game -- enough of a sample to mean something
# without going stale. Change this one constant to retune it.
RECENT_GAMES_COUNT = 5


@module.ui
def dashboard_ui():
    return ui.div(
        ui_helpers.page_header("Dashboard"),
        ui.output_ui("controls"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def dashboard_server(input, output, session, app_state):
    # Static-ish control strip: only rendered (non-empty) for the two
    # specialty-KPI roles, so it doesn't clutter every other role's
    # dashboard. Lives in its own output (rather than being built
    # inline inside body() below) so the radio buttons aren't
    # destroyed and recreated -- and their selected value reset -- on
    # every re-render of body() itself.
    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        role_name = app_state.role_name()
        specialty = app_state.coach_specialty()
        if role_name == "Coach" and specialty in ("Pitching", "Hitting"):
            return ui.div(
                ui.input_radio_buttons(
                    "kpi_window",
                    None,
                    {"season": "Current Season", "recent": f"Last {RECENT_GAMES_COUNT} Games"},
                    selected="season",
                    inline=True,
                ),
                class_="mb-3",
            )
        return None

    @render.ui
    def body():
        if not app_state.is_authenticated():
            return None

        role_name = app_state.role_name()
        current_user_id = app_state.user_id()
        can_view_all = app_state.can_view_all_players()
        specialty = app_state.coach_specialty()
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
            elif role_name == "Coach" and specialty == "Pitching":
                # Reads the radio button rendered by controls() above --
                # accessing it before the client has echoed its default
                # value back is expected to briefly hold this output
                # empty (Shiny's normal "silent" retry behavior for a
                # not-yet-available input), then it renders once the
                # value arrives -- no error, no explicit fallback needed.
                sections.append(_pitching_staff_section(db, players, input.kpi_window()))
            elif role_name == "Coach" and specialty == "Hitting":
                sections.append(_hitter_staff_section(db, players, input.kpi_window()))
            elif role_name in ("Head Coach", "Coach"):
                sections.append(_head_coach_section(db, players, player_ids, week_ago))
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
# SHARED HELPERS -- "current season" resolution and window-scoped pitch
# lookups, used by both specialty-KPI sections below.
# =============================================================================

def _current_season(db):
    """Best-guess 'current season' for the season-window KPI toggle: the
    Season row whose start/end date range contains today, or (if none is
    dated that way -- e.g. no end_date set yet for an ongoing season) the
    most recently started one. Returns None if no seasons exist yet at
    all, in which case callers fall back to all-time charted data rather
    than showing an empty page."""
    today = date.today()
    seasons = db.query(Season).all()
    for s in seasons:
        if s.start_date and s.end_date and s.start_date <= today <= s.end_date:
            return s
    dated = [s for s in seasons if s.start_date]
    if dated:
        return max(dated, key=lambda s: s.start_date)
    return None


def _recent_game_ids(db, n):
    """The game_ids of the N most recently completed (Final) games, by
    date -- both external and intrasquad, since intrasquad reps are
    still real charted innings/at-bats worth including in a "recent
    form" read. This is the game-count version of the KPI window
    toggle: naturally rides out bye weeks/schedule gaps, unlike a fixed
    calendar-day cutoff."""
    games = (
        db.query(Game.game_id)
        .filter(Game.status == "Final")
        .order_by(Game.game_date.desc())
        .limit(n)
        .all()
    )
    return {row[0] for row in games}


def _pitching_pitches_for_window(db, player_id, window, season, recent_game_ids):
    if window == "recent":
        return [p for p in get_pitching_pitches(db, player_id) if p.game_id in recent_game_ids]
    # "season" -- or any unrecognized value defaults here too
    return get_pitching_pitches(db, player_id, season_id=season.season_id if season else None)


def _batting_pitches_for_window(db, player_id, window, season, recent_game_ids):
    if window == "recent":
        return [p for p in get_batting_pitches(db, player_id) if p.game_id in recent_game_ids]
    return get_batting_pitches(db, player_id, season_id=season.season_id if season else None)


def _window_controls_caption(window, season):
    if window == "recent":
        return f"Showing: Last {RECENT_GAMES_COUNT} Games"
    if season is not None:
        return f"Showing: Current Season ({season.season_name})"
    return "Showing: All-time (no season set up yet)"


# =============================================================================
# COACH -- Pitching specialty: pitching-staff KPIs
# =============================================================================

def _pitching_staff_section(db, players, window):
    """Team-wide pitching KPIs for a Pitching-specialty Coach: an
    aggregate staff pitching line built from every charted pitch thrown
    by anyone on this coach's roster (combined into one box score via
    game_stats.compute_pitching_line -- correctly weighted, not an
    average of individual rates), then a per-pitcher leaderboard below
    ranked by workload (innings pitched) so the staff's most-used arms
    surface first. window is "season" (current Season by date range) or
    "recent" (last RECENT_GAMES_COUNT completed games), driven by the
    radio toggle in controls() above."""
    season = _current_season(db)
    recent_game_ids = _recent_game_ids(db, RECENT_GAMES_COUNT) if window == "recent" else set()

    per_pitcher = []
    all_pitches = []
    for p in players:
        pitches = _pitching_pitches_for_window(db, p.player_id, window, season, recent_game_ids)
        if not pitches:
            continue
        line = compute_pitching_line(pitches)
        per_pitcher.append((p, line))
        all_pitches.extend(pitches)

    per_pitcher.sort(key=lambda row: row[1]["IP (decimal)"] or 0, reverse=True)

    sections = [ui.p(_window_controls_caption(window, season), class_="text-muted small")]

    if not all_pitches:
        sections.append(ui_helpers.empty_state(
            "No charted pitches yet for this window -- log some innings in Game Tracking."
        ))
        return ui.div(*sections)

    team_line = compute_pitching_line(all_pitches)
    era_key = "ERA (runs-allowed avg -- ER not tracked)"

    sections.append(ui_helpers.render_kpi_cards([
        {"label": "Team ERA*", "value": str(team_line[era_key]) if team_line[era_key] is not None else "—"},
        {"label": "WHIP", "value": str(team_line["WHIP"]) if team_line["WHIP"] is not None else "—"},
        {"label": "K %", "value": f'{team_line["K %"]}%' if team_line["K %"] is not None else "—"},
        {"label": "K/BB", "value": str(team_line["K/BB"]) if team_line["K/BB"] is not None else "—"},
        {"label": "First Pitch Strike %", "value": f'{team_line["First Pitch Strike %"]}%' if team_line["First Pitch Strike %"] is not None else "—"},
    ]))
    sections.append(ui.p(
        "*Runs-allowed average -- GBO doesn't track earned vs. unearned runs.",
        class_="text-muted small",
    ))

    sections.append(ui.hr())
    sections.append(ui.h5("Pitching Staff Leaderboard", class_="gbo-section-title"))
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Pitcher": f"{p.first_name} {p.last_name}",
                "IP": line["IP"],
                "ERA*": line[era_key] if line[era_key] is not None else "—",
                "WHIP": line["WHIP"] if line["WHIP"] is not None else "—",
                "K": line["K"], "BB": line["BB"],
                "K %": line["K %"] if line["K %"] is not None else "—",
                "FPS %": line["First Pitch Strike %"] if line["First Pitch Strike %"] is not None else "—",
                "BF": line["Batters Faced"],
            }
            for p, line in per_pitcher
        ],
        empty_message="No pitchers with charted innings yet.",
    ))
    sections.append(ui.p(
        "See Bullpen Dashboard / Pitcher Game Report in the navigation for full pitch-by-pitch detail.",
        class_="text-muted small",
    ))

    return ui.div(*sections)


# =============================================================================
# COACH -- Hitting specialty: hitter KPIs
# =============================================================================

def _hitter_staff_section(db, players, window):
    """Mirror-opposite of _pitching_staff_section() above, for a
    Hitting-specialty Coach: team-wide hitting line (AVG/OBP/SLG/OPS)
    aggregated from every charted plate appearance for anyone on this
    coach's roster, plus a per-hitter leaderboard ranked by plate
    appearances (most active hitters first). Same window toggle as the
    pitching side."""
    season = _current_season(db)
    recent_game_ids = _recent_game_ids(db, RECENT_GAMES_COUNT) if window == "recent" else set()

    per_hitter = []
    all_pitches = []
    for p in players:
        pitches = _batting_pitches_for_window(db, p.player_id, window, season, recent_game_ids)
        if not pitches:
            continue
        line = compute_batting_line(pitches)
        per_hitter.append((p, line))
        all_pitches.extend(pitches)

    per_hitter.sort(key=lambda row: row[1]["PA"] or 0, reverse=True)

    sections = [ui.p(_window_controls_caption(window, season), class_="text-muted small")]

    if not all_pitches:
        sections.append(ui_helpers.empty_state(
            "No charted plate appearances yet for this window -- log some at-bats in Game Tracking."
        ))
        return ui.div(*sections)

    team_line = compute_batting_line(all_pitches)

    sections.append(ui_helpers.render_kpi_cards([
        {"label": "Team AVG", "value": str(team_line["AVG"]) if team_line["AVG"] is not None else "—"},
        {"label": "Team OBP", "value": str(team_line["OBP"]) if team_line["OBP"] is not None else "—"},
        {"label": "Team SLG", "value": str(team_line["SLG"]) if team_line["SLG"] is not None else "—"},
        {"label": "Team OPS", "value": str(team_line["OPS"]) if team_line["OPS"] is not None else "—"},
    ]))

    sections.append(ui.hr())
    sections.append(ui.h5("Hitters Leaderboard", class_="gbo-section-title"))
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Hitter": f"{p.first_name} {p.last_name}",
                "PA": line["PA"], "AB": line["AB"],
                "AVG": line["AVG"] if line["AVG"] is not None else "—",
                "OBP": line["OBP"] if line["OBP"] is not None else "—",
                "SLG": line["SLG"] if line["SLG"] is not None else "—",
                "OPS": line["OPS"] if line["OPS"] is not None else "—",
                "BB %": line["BB %"] if line["BB %"] is not None else "—",
                "K %": line["K %"] if line["K %"] is not None else "—",
            }
            for p, line in per_hitter
        ],
        empty_message="No hitters with charted plate appearances yet.",
    ))
    sections.append(ui.p(
        "See Hitter Tracking / Hitter Game Report in the navigation for full at-bat detail.",
        class_="text-muted small",
    ))

    return ui.div(*sections)


# =============================================================================
# HEAD COACH, and COACH with no Pitching/Hitting specialty -- team-ops
# focus: record, next game, this week's schedule, full player
# availability, recent results. Replaces the assessment/assignment-
# completion-count view these roles used to share with Administrator/
# Data Analyst below -- that's not what a coach actually manages day to
# day.
# =============================================================================

def _head_coach_section(db, players, player_ids, week_ago):
    today = date.today()
    week_ahead = today + timedelta(days=6)

    # --- Record: external (non-intrasquad) Final games only -- a
    # scrimmage against your own Squad B shouldn't count toward the
    # season record. ---
    final_games = (
        db.query(Game)
        .options(joinedload(Game.opponent_team))
        .filter(Game.status == "Final")
        .order_by(Game.game_date.desc())
        .all()
    )
    external_finals = [g for g in final_games if not g.is_intrasquad]
    wins = sum(1 for g in external_finals if g.our_score > g.opponent_score)
    losses = sum(1 for g in external_finals if g.our_score < g.opponent_score)
    ties = sum(1 for g in external_finals if g.our_score == g.opponent_score)
    record_label = f"{wins}-{losses}" + (f"-{ties}" if ties else "")

    # --- Next game ---
    next_game = (
        db.query(Game)
        .options(
            joinedload(Game.opponent_team),
            joinedload(Game.starting_pitcher),
            joinedload(Game.opponent_starting_pitcher),
        )
        .filter(Game.game_date >= today, Game.status.in_(["Scheduled", "In Progress", "Paused"]))
        .order_by(Game.game_date)
        .first()
    )

    def _opp_label(g):
        if g.opponent_team:
            return g.opponent_team.team_name
        if g.is_intrasquad:
            return "Intrasquad"
        return g.opponent_name or "TBD"

    if next_game:
        next_game_value = f"{next_game.game_date.strftime('%-m/%-d')} vs {_opp_label(next_game)}"
    else:
        next_game_value = "None scheduled"

    # --- Player availability ---
    status_counts = {}
    for p in players:
        name = p.status.status_name if p.status else "Unknown"
        status_counts[name] = status_counts.get(name, 0) + 1
    injured_count = status_counts.get("Injured", 0)
    medical_hold_count = status_counts.get("Medical Hold", 0)

    # --- This week's team schedule ---
    team = players[0].team if players else None
    week_events = (
        db.query(TeamScheduleEvent)
        .options(joinedload(TeamScheduleEvent.event_type))
        .filter(
            TeamScheduleEvent.team_id == team.team_id,
            TeamScheduleEvent.scheduled_date >= today,
            TeamScheduleEvent.scheduled_date <= week_ahead,
        )
        .order_by(TeamScheduleEvent.scheduled_date)
        .all()
    ) if team else []

    sections = [ui_helpers.render_kpi_cards([
        {"label": "Record", "value": record_label},
        {"label": "Next Game", "value": next_game_value},
        {"label": "Injured", "value": str(injured_count)},
        {"label": "Medical Hold", "value": str(medical_hold_count)},
    ])]

    # --- This week ---
    sections.append(ui.hr())
    sections.append(ui.h5("This Week", class_="gbo-section-title"))
    if not week_events:
        sections.append(ui_helpers.empty_state("Nothing on the team schedule this week."))
    else:
        sections.append(ui_helpers.render_dict_table([
            {
                "Date": e.scheduled_date.strftime("%Y-%m-%d (%a)"),
                "Type": e.event_type.type_name if e.event_type else "Event",
                "Title": e.title,
                "Pitchers only": "Yes" if e.pitchers_only else "",
            }
            for e in week_events
        ]))

    # --- Next game detail ---
    sections.append(ui.hr())
    sections.append(ui.h5("Next Game", class_="gbo-section-title"))
    if next_game is None:
        sections.append(ui_helpers.empty_state("No upcoming game scheduled -- add one from Game Tracking."))
    else:
        location = "Home" if next_game.is_home else ("Away" if next_game.is_home is False else "—")
        our_sp = f"{next_game.starting_pitcher.first_name} {next_game.starting_pitcher.last_name}" if next_game.starting_pitcher else "Not set"
        sections.append(ui.p(
            ui.strong(f"{_opp_label(next_game)} — {next_game.game_date.strftime('%Y-%m-%d (%a)')}"),
            f" ({location})",
        ))
        sections.append(ui.p(f"Our starting pitcher: {our_sp}", class_="text-muted small"))
        if not next_game.is_intrasquad:
            their_sp = next_game.opponent_starting_pitcher.player_name if next_game.opponent_starting_pitcher else "Unknown"
            sections.append(ui.p(f"Their starting pitcher: {their_sp}", class_="text-muted small"))

    # --- Player availability detail ---
    sections.append(ui.hr())
    sections.append(ui.h5("Player Availability", class_="gbo-section-title"))
    flagged_statuses = ("Injured", "Medical Hold")
    flagged_players = [p for p in players if p.status and p.status.status_name in flagged_statuses]
    sections.append(ui_helpers.render_dict_table(
        [
            {
                "Name": f"{p.first_name} {p.last_name}",
                "Status": p.status.status_name if p.status else "—",
                "Position": p.player_position.position_name if p.player_position else "—",
            }
            for p in flagged_players
        ],
        empty_message="Everyone is available -- no players currently injured or on medical hold.",
    ))

    # --- Recent results ---
    sections.append(ui.hr())
    sections.append(ui.h5("Recent Results", class_="gbo-section-title"))
    recent_finals = final_games[:5]
    if not recent_finals:
        sections.append(ui_helpers.empty_state("No completed games logged yet."))
    else:
        sections.append(ui_helpers.render_dict_table([
            {
                "Date": g.game_date.strftime("%Y-%m-%d (%a)"),
                "Opponent": _opp_label(g),
                "Score": f"{g.our_score}-{g.opponent_score}",
                "Result": "W" if g.our_score > g.opponent_score else ("L" if g.our_score < g.opponent_score else "T"),
            }
            for g in recent_finals
        ]))
        sections.append(ui.p("See Player Stats / Game Reports in the navigation for full box scores and trends.", class_="text-muted small"))

    return ui.div(*sections)


# =============================================================================
# ADMINISTRATOR / DATA ANALYST -- general overview (unchanged for now --
# revisit Administrator's own dashboard as a separate pass later)
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