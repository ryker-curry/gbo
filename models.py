"""
GBO — Data models (Milestone 1).

Sections:
  1. Lookup tables
  2. Organization / Team / User / Player core
  3. Assessments (normalized: assessment session -> individual test results)
  4. Individual Development Plan (IDP)
  5. Individual Sessions
  6. Future-module stubs (Training, Recovery, Video, Reports, Research, Scouting)
     -- these exist only so the schema never needs a breaking migration later.
     They are NOT wired into the app for the Aug 17 MVP.

Design standards followed throughout:
  - snake_case naming
  - every table has a primary key
  - foreign keys define every relationship (no free-text links)
  - lookup tables over free text for any fixed-value field
  - created_at / updated_at on every substantive record
"""

from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Date, DateTime,
    ForeignKey, Numeric, UniqueConstraint
)
from sqlalchemy.orm import relationship

from database import Base


# ---------------------------------------------------------------------------
# 1. LOOKUP TABLES
# ---------------------------------------------------------------------------

class Role(Base):
    """The 8 finalized MVP roles and what each is allowed to touch.

    permission_scope is a short machine-readable tag the app layer uses to
    decide read/edit access per module. It is enforced in application code
    (every query filters by it) -- this table is the single source of truth
    for what each role's tag means, not a substitute for query-level checks.
    """
    __tablename__ = "roles"

    role_id = Column(Integer, primary_key=True)
    role_name = Column(String(50), unique=True, nullable=False)
    description = Column(Text, nullable=False)
    can_edit_assessments = Column(Boolean, default=False, nullable=False)
    can_edit_idp = Column(Boolean, default=False, nullable=False)
    can_edit_sessions = Column(Boolean, default=False, nullable=False)
    can_view_all_players = Column(Boolean, default=False, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)

    users = relationship("User", back_populates="role")


class AssessmentCategory(Base):
    """The 11 real assessment buckets, per Ryker's Master Player Profile
    Data Dictionary: Anthropometrics, Body Composition, Mobility & ROM,
    Arm Health, Upper Body Strength, Lower Body Strength, Explosive
    Power, Rotational Power, Speed, Baseball Performance (all universal),
    plus Pitcher-Specific (position-specific).

    Individual test names within each bucket are populated as Ryker's
    protocol document fills in -- AssessmentTestType is where those go
    without touching this table.
    """
    __tablename__ = "assessment_categories"

    category_id = Column(Integer, primary_key=True)
    category_name = Column(String(100), unique=True, nullable=False)
    is_universal = Column(Boolean, default=True, nullable=False)  # False = position-specific (e.g. Pitcher-Specific)
    display_order = Column(Integer, default=0, nullable=False)

    test_types = relationship("AssessmentTestType", back_populates="category")
    assessments = relationship("Assessment", back_populates="category")


class AssessmentTestType(Base):
    """An individual test/metric within a category (e.g. 'Shoulder IR ROM').

    STUB: rows here are placeholders until Ryker's protocol document is
    reviewed. The table structure (test belongs to a category, has a unit)
    is final; the actual test rows are not populated yet.
    """
    __tablename__ = "assessment_test_types"

    test_type_id = Column(Integer, primary_key=True)
    category_id = Column(Integer, ForeignKey("assessment_categories.category_id"), nullable=False)
    test_name = Column(String(150), nullable=False)
    unit = Column(String(30), nullable=True)  # e.g. 'degrees', 'kg', 'seconds', 'mph'
    display_order = Column(Integer, default=0, nullable=False)

    category = relationship("AssessmentCategory", back_populates="test_types")
    results = relationship("AssessmentResult", back_populates="test_type")


class IDPStatus(Base):
    """Lookup for IDP goal / action step status.

    PLACEHOLDER DEFAULTS (Not Started / In Progress / Completed / On Hold) --
    not yet confirmed with Ryker. Flag this for review before Aug 7-10 build.
    """
    __tablename__ = "idp_statuses"

    status_id = Column(Integer, primary_key=True)
    status_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class SessionType(Base):
    """Lookup for Individual Session type -- mirrors the future Training
    module's categories (Arm Care, Conditioning, Hitting Drills,
    Throwing, Plyos, General) so nothing gets rebuilt when Training ships.
    """
    __tablename__ = "session_types"

    session_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(100), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)

    sessions = relationship("TrainingSession", back_populates="session_type")


class PlayerStatus(Base):
    """Lookup for player status (Active, Injured, Redshirt, etc.) per
    Ryker's Player Information sheet.

    PLACEHOLDER DEFAULTS -- confirm the exact status list with Ryker.
    """
    __tablename__ = "player_statuses"

    status_id = Column(Integer, primary_key=True)
    status_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class PlayerClass(Base):
    """Lookup for academic class (Freshman, Sophomore, Junior, Senior,
    Graduate) per Ryker's Player Information sheet."""
    __tablename__ = "player_classes"

    class_id = Column(Integer, primary_key=True)
    class_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class Position(Base):
    """Lookup for defensive position (Pitcher, Catcher, First Base, etc.)
    -- dropdown instead of free text, per Ryker's preference to minimize
    typing."""
    __tablename__ = "positions"

    position_id = Column(Integer, primary_key=True)
    position_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class PitchType(Base):
    """Lookup for pitch type (4-Seam Fastball, Slider, etc.) -- a dropdown
    field on a Pitcher-Specific assessment record, not a numeric test
    value, since it's categorical rather than measured."""
    __tablename__ = "pitch_types"

    pitch_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


# ---------------------------------------------------------------------------
# 2. ORGANIZATION / TEAM / USER / PLAYER CORE
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    organization_id = Column(Integer, primary_key=True)
    organization_name = Column(String(150), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    teams = relationship("Team", back_populates="organization")
    users = relationship("User", back_populates="organization")


class Team(Base):
    """Game/roster team -- distinct from player identity, per earlier
    architecture decision (Teams module is for game tracking)."""
    __tablename__ = "teams"

    team_id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.organization_id"), nullable=False)
    team_name = Column(String(100), nullable=False)
    season_year = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="teams")
    players = relationship("Player", back_populates="team")


class Player(Base):
    __tablename__ = "players"

    player_id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    position_id = Column(Integer, ForeignKey("positions.position_id"), nullable=True)
    secondary_position_id = Column(Integer, ForeignKey("positions.position_id"), nullable=True)
    is_pitcher = Column(Boolean, default=False, nullable=False)  # drives which assessment tier applies
    jersey_number = Column(Integer, nullable=True)
    throws = Column(String(1), nullable=True)  # 'R' or 'L'
    bats = Column(String(1), nullable=True)  # 'R', 'L', or 'S' (switch)
    class_id = Column(Integer, ForeignKey("player_classes.class_id"), nullable=True)
    graduation_year = Column(Integer, nullable=True)
    dominant_hand = Column(String(1), nullable=True)  # 'R' or 'L'
    dominant_leg = Column(String(1), nullable=True)  # 'R' or 'L'
    hometown = Column(String(150), nullable=True)
    previous_school = Column(String(150), nullable=True)  # high school, or JUCO/transfer school for players who transferred in
    height_in = Column(Numeric(5, 2), nullable=True)  # current height, inches
    weight_lb = Column(Numeric(5, 1), nullable=True)  # current weight, lb
    status_id = Column(Integer, ForeignKey("player_statuses.status_id"), nullable=True)
    photo_url = Column(String(500), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    email = Column(String(150), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    team = relationship("Team", back_populates="players")
    player_position = relationship("Position", foreign_keys=[position_id])
    player_secondary_position = relationship("Position", foreign_keys=[secondary_position_id])
    player_class = relationship("PlayerClass")
    status = relationship("PlayerStatus")
    user_account = relationship("User", back_populates="player", uselist=False)
    assessments = relationship("Assessment", back_populates="player")
    idp_goals = relationship("IDPGoal", back_populates="player")
    sessions = relationship("TrainingSession", back_populates="player")
    staff_assignments = relationship("StaffPlayerAssignment", back_populates="player")


class User(Base):
    """One row per login-capable person (staff or player).

    auth_subject_id stores the Supabase Auth user ID (a UUID) for the
    matching account -- this is what ties a GBO login to a role and
    (for players) a player record. GBO accounts are separate from Pitt
    State Microsoft accounts (switched from planned Microsoft Entra login
    because Entra requires Pitt State Azure/IT admin access to set up).
    """
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("organizations.organization_id"), nullable=False)
    auth_subject_id = Column(String(255), unique=True, nullable=True)  # populated on first login
    email = Column(String(150), unique=True, nullable=False)
    first_name = Column(String(80), nullable=False)
    last_name = Column(String(80), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.role_id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)  # set only for Player role
    coach_specialty = Column(String(20), nullable=True)  # "Pitching" / "Hitting" / "Both" -- only meaningful for role=Coach, filters which Training Routines they see
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    organization = relationship("Organization", back_populates="users")
    role = relationship("Role", back_populates="users")
    player = relationship("Player", back_populates="user_account")
    staff_assignments = relationship("StaffPlayerAssignment", back_populates="staff_user")


class StaffPlayerAssignment(Base):
    """Which staff user is assigned to which player -- drives the Coach
    role's 'assigned players only' access filter."""
    __tablename__ = "staff_player_assignments"

    assignment_id = Column(Integer, primary_key=True)
    staff_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("staff_user_id", "player_id", name="uq_staff_player"),)

    staff_user = relationship("User", back_populates="staff_assignments")
    player = relationship("Player", back_populates="staff_assignments")


# ---------------------------------------------------------------------------
# 3. ASSESSMENTS (normalized: session -> individual results)
# ---------------------------------------------------------------------------

class Assessment(Base):
    """One assessment 'session' for a player in a given category on a given
    date (e.g. Player X's Strength assessment on 2026-08-05).

    Individual test values for that session live in AssessmentResult, not
    as columns here -- this is what lets new tests get added later without
    a schema migration.
    """
    __tablename__ = "assessments"

    assessment_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("assessment_categories.category_id"), nullable=False)
    assessment_date = Column(Date, default=date.today, nullable=False)
    entered_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)  # only used for Pitcher-Specific category
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    player = relationship("Player", back_populates="assessments")
    category = relationship("AssessmentCategory", back_populates="assessments")
    entered_by = relationship("User")
    pitch_type = relationship("PitchType")
    results = relationship("AssessmentResult", back_populates="assessment", cascade="all, delete-orphan")
    idp_goals = relationship("IDPGoal", back_populates="source_assessment")
    videos = relationship("Video", back_populates="assessment")


class AssessmentResult(Base):
    """One individual test value within an assessment session."""
    __tablename__ = "assessment_results"

    result_id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=False)
    test_type_id = Column(Integer, ForeignKey("assessment_test_types.test_type_id"), nullable=False)
    value = Column(Numeric(10, 3), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    assessment = relationship("Assessment", back_populates="results")
    test_type = relationship("AssessmentTestType", back_populates="results")


# ---------------------------------------------------------------------------
# 4. INDIVIDUAL DEVELOPMENT PLAN (IDP)
# ---------------------------------------------------------------------------

class IDPGoal(Base):
    """A development goal, typed by assessment category and linked back to
    the specific assessment record that motivated it (per Ryker's decision:
    goals are tied to assessment buckets and link to assessment records,
    not freeform).

    Optional structured target (added when Ryker felt goals were too
    vague as pure free text): a specific test within the category,
    baseline value, target value, and target date -- turns "improve
    shoulder mobility" into a measurable "85° -> 95° by Sept 1"."""
    __tablename__ = "idp_goals"

    goal_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("assessment_categories.category_id"), nullable=False)
    source_assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=True)
    target_test_type_id = Column(Integer, ForeignKey("assessment_test_types.test_type_id"), nullable=True)
    baseline_value = Column(Numeric(10, 3), nullable=True)
    target_value = Column(Numeric(10, 3), nullable=True)
    target_date = Column(Date, nullable=True)
    description = Column(Text, nullable=False)
    status_id = Column(Integer, ForeignKey("idp_statuses.status_id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    player = relationship("Player", back_populates="idp_goals")
    category = relationship("AssessmentCategory")
    source_assessment = relationship("Assessment", back_populates="idp_goals")
    target_test_type = relationship("AssessmentTestType")
    status = relationship("IDPStatus")
    created_by = relationship("User")
    action_steps = relationship("IDPActionStep", back_populates="goal", cascade="all, delete-orphan")
    progress_notes = relationship("IDPProgressNote", back_populates="goal", cascade="all, delete-orphan")
    linked_sessions = relationship("TrainingSession", back_populates="goal")
    linked_assignments = relationship("PlayerAssignment", back_populates="goal")


class IDPActionStep(Base):
    __tablename__ = "idp_action_steps"

    step_id = Column(Integer, primary_key=True)
    goal_id = Column(Integer, ForeignKey("idp_goals.goal_id"), nullable=False)
    description = Column(Text, nullable=False)
    status_id = Column(Integer, ForeignKey("idp_statuses.status_id"), nullable=False)
    due_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    goal = relationship("IDPGoal", back_populates="action_steps")
    status = relationship("IDPStatus")


class IDPProgressNote(Base):
    __tablename__ = "idp_progress_notes"

    note_id = Column(Integer, primary_key=True)
    goal_id = Column(Integer, ForeignKey("idp_goals.goal_id"), nullable=False)
    note_text = Column(Text, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    goal = relationship("IDPGoal", back_populates="progress_notes")
    created_by = relationship("User")


# ---------------------------------------------------------------------------
# 5. INDIVIDUAL SESSIONS
# ---------------------------------------------------------------------------

class TrainingSession(Base):
    """Renamed from IndividualSession -- 'Individual' wrongly implied
    1-on-1 only, but these logs cover group work too (arm care,
    conditioning, drills done with multiple players)."""
    __tablename__ = "training_sessions"

    session_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    coach_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    session_type_id = Column(Integer, ForeignKey("session_types.session_type_id"), nullable=False)
    goal_id = Column(Integer, ForeignKey("idp_goals.goal_id"), nullable=True)  # optional: this session prescribed toward a specific IDP goal
    session_date = Column(Date, default=date.today, nullable=False)
    notes = Column(Text, nullable=True)
    player_feedback = Column(Text, nullable=True)
    next_steps = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player", back_populates="sessions")
    coach = relationship("User")
    session_type = relationship("SessionType", back_populates="sessions")
    goal = relationship("IDPGoal", back_populates="linked_sessions")


class TeamEventType(Base):
    """Lookup for team-wide schedule event type (Lift, Practice, Game,
    Other)."""
    __tablename__ = "team_event_types"

    event_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class TeamScheduleEvent(Base):
    """A planned team-wide event (lift day, practice, game, etc.).
    Team-wide rather than per-player, since these are set for the whole
    team (e.g. 'Monday: Squat Day') rather than individualized. Tracks
    completion (was it actually done) -- this replaced the separate
    Training Sessions log for team-wide work.

    Renamed/generalized from ScheduledLift once Ryker asked for practice
    schedule alongside the lift schedule -- same underlying concept, just
    typed by event_type instead of being lift-specific."""
    __tablename__ = "team_schedule_events"

    schedule_id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.team_id"), nullable=False)
    event_type_id = Column(Integer, ForeignKey("team_event_types.event_type_id"), nullable=False)
    routine_id = Column(Integer, ForeignKey("training_routines.routine_id"), nullable=True)  # optional: the actual workout content for this scheduled event (e.g. a Lift day)
    pitchers_only = Column(Boolean, nullable=True)  # None = whole team, True = pitchers only, False = position players only -- lets pitchers and position players have separate lifts on the same day
    scheduled_date = Column(Date, nullable=False)
    title = Column(String(150), nullable=False)  # e.g. "Squat Day", "Upper Body"
    notes = Column(Text, nullable=True)
    completed = Column(Boolean, default=False, nullable=False)
    completed_notes = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    team = relationship("Team")
    routine = relationship("TrainingRoutine")
    event_type = relationship("TeamEventType")
    created_by = relationship("User")


class PlayerAssignment(Base):
    """A prescribed, forward-looking task for a specific player (e.g.
    'today: throwing program', 'today: arm care') -- assigned ahead of
    time by a coach or Athletic Trainer. Also tracks completion (was it
    actually done, and how did it go) -- this replaced the separate
    Training Sessions log, which duplicated planning already captured
    here. Reuses the SessionType lookup (Arm Care, Mobility, Conditioning,
    Lifting, Hitting Drills, Throwing, Plyos, General) so assignment
    types match logged session types exactly."""
    __tablename__ = "player_assignments"

    assignment_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    session_type_id = Column(Integer, ForeignKey("session_types.session_type_id"), nullable=False)
    routine_id = Column(Integer, ForeignKey("training_routines.routine_id"), nullable=True)  # optional: a specific saved routine from the library
    bullpen_type_id = Column(Integer, ForeignKey("bullpen_types.bullpen_type_id"), nullable=True)  # optional: for Type=Bullpen assignments, which kind of bullpen
    bullpen_script_id = Column(Integer, ForeignKey("bullpen_scripts.script_id"), nullable=True)  # optional: a specific pre-planned script for this bullpen assignment
    goal_id = Column(Integer, ForeignKey("idp_goals.goal_id"), nullable=True)  # optional: this assignment is prescribed toward a specific IDP goal
    scheduled_date = Column(Date, nullable=False)
    notes = Column(Text, nullable=True)
    assigned_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    completed_notes = Column(Text, nullable=True)  # what actually happened, coach's note
    player_feedback = Column(Text, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player")
    session_type = relationship("SessionType")
    routine = relationship("TrainingRoutine")
    bullpen_type = relationship("BullpenType")
    bullpen_script = relationship("BullpenScript")
    goal = relationship("IDPGoal", back_populates="linked_assignments")
    assigned_by = relationship("User")


class ATAppointment(Base):
    """A scheduled appointment between a player and a specific Athletic
    Trainer -- real date + time, not just a note."""
    __tablename__ = "at_appointments"

    appointment_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    athletic_trainer_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    appointment_date = Column(Date, nullable=False)
    appointment_time = Column(String(10), nullable=True)  # simple "HH:MM" string, e.g. "14:30" -- avoids timezone complexity for MVP
    reason = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player")
    athletic_trainer = relationship("User", foreign_keys=[athletic_trainer_user_id])
    created_by = relationship("User", foreign_keys=[created_by_user_id])


# ---------------------------------------------------------------------------
# 6. FUTURE-MODULE STUBS
#    Table shells only -- no app logic wired to these for the Aug 17 MVP.
#    Purpose: reserve the schema so later builds don't require migrations
#    that touch MVP tables.
# ---------------------------------------------------------------------------

class TrainingRoutine(Base):
    """A named, reusable routine (e.g. 'Standard Post-Throw Recovery') a
    coach builds once and assigns to players repeatedly via
    PlayerAssignment, instead of retyping the same notes every time.
    Promoted out of stub status when Ryker asked for structured arm care
    routines with sets/reps."""
    __tablename__ = "training_routines"

    routine_id = Column(Integer, primary_key=True)
    session_type_id = Column(Integer, ForeignKey("session_types.session_type_id"), nullable=False)
    routine_name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    session_type = relationship("SessionType")
    created_by = relationship("User")
    exercises = relationship("RoutineExercise", back_populates="routine", cascade="all, delete-orphan", order_by="RoutineExercise.display_order")


class RoutineExercise(Base):
    """One structured step within a TrainingRoutine (exercise name, sets,
    reps, optional notes)."""
    __tablename__ = "routine_exercises"

    exercise_id = Column(Integer, primary_key=True)
    routine_id = Column(Integer, ForeignKey("training_routines.routine_id"), nullable=False)
    exercise_name = Column(String(150), nullable=False)
    sets = Column(Integer, nullable=True)
    reps = Column(String(30), nullable=True)  # string, not int -- allows "10", "AMRAP", "30 sec", etc.
    notes = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)  # optional demo clip for this specific exercise
    display_order = Column(Integer, default=0, nullable=False)

    routine = relationship("TrainingRoutine", back_populates="exercises")


class RecoveryTest(Base):
    """STUB -- future in-season Recovery module (repeated force-plate
    testing). Structure intentionally mirrors Assessment/AssessmentResult
    since the scope decision (full VALD panel vs. quick daily subset) is
    still open."""
    __tablename__ = "recovery_tests"

    recovery_test_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    test_date = Column(Date, default=date.today, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Video(Base):
    """Video clips, optionally linked to a specific Assessment record --
    e.g. the exact pitch a Rapsodo entry came from, so the numbers and
    footage can be viewed side by side. Promoted out of stub status when
    Ryker asked for Rapsodo-data-to-video matching."""
    __tablename__ = "videos"

    video_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=True)
    video_url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    recorded_date = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player")
    assessment = relationship("Assessment", back_populates="videos")


class Report(Base):
    """STUB -- future Reports module."""
    __tablename__ = "reports"

    report_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)
    report_title = Column(String(200), nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ResearchProject(Base):
    """STUB -- future Research module (Master's research tracking)."""
    __tablename__ = "research_projects"

    research_project_id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ScoutingReport(Base):
    """STUB -- future Scouting / Game Operations module."""
    __tablename__ = "scouting_reports"

    scouting_report_id = Column(Integer, primary_key=True)
    opponent_name = Column(String(150), nullable=True)
    game_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BullpenType(Base):
    """Lookup for bullpen session type (High Intent Velo, Pitch Design,
    Execution Focused, Touch and Feel, Short Box)."""
    __tablename__ = "bullpen_types"

    bullpen_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class BullpenSession(Base):
    """One bullpen outing for a pitcher on a given date -- the tracking
    sheet header. Individual pitches live in BullpenPitch.

    source_assignment_id optionally links back to the PlayerAssignment
    that prescribed this bullpen (Type=Bullpen), so starting a session
    from that assignment carries over its date/type automatically, and
    the assignment can be marked completed once the bullpen is tracked."""
    __tablename__ = "bullpen_sessions"

    bullpen_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    bullpen_type_id = Column(Integer, ForeignKey("bullpen_types.bullpen_type_id"), nullable=False)
    source_assignment_id = Column(Integer, ForeignKey("player_assignments.assignment_id"), nullable=True)
    session_date = Column(Date, default=date.today, nullable=False)
    overall_notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player")
    bullpen_type = relationship("BullpenType")
    source_assignment = relationship("PlayerAssignment")
    created_by = relationship("User")
    pitches = relationship("BullpenPitch", back_populates="bullpen", cascade="all, delete-orphan", order_by="BullpenPitch.pitch_number")


class BullpenPitch(Base):
    """One pitch within a bullpen session. target_zone is entered live by
    the coach during the bullpen (manual 3x3 grid tap -- fast, no device
    needed in the moment). linked_assessment_id optionally points at the
    matching Rapsodo-imported pitch (once that CSV is imported after the
    session), from which the actual zone and hit/miss are computed from
    real Plate Height/Plate Side coordinates rather than a second manual
    entry."""
    __tablename__ = "bullpen_pitches"

    bullpen_pitch_id = Column(Integer, primary_key=True)
    bullpen_id = Column(Integer, ForeignKey("bullpen_sessions.bullpen_id"), nullable=False)
    pitch_number = Column(Integer, nullable=False)
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    target_zone = Column(Integer, nullable=True)  # 1-9, catcher's-eye view: 1-2-3 top row, 4-5-6 middle, 7-8-9 bottom, left-to-right
    linked_assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=True)
    notes = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)  # optional clip for this specific pitch (release/mechanics review) -- one per pitch, no multi-angle

    bullpen = relationship("BullpenSession", back_populates="pitches")
    pitch_type = relationship("PitchType")
    linked_assessment = relationship("Assessment")


class BullpenScript(Base):
    """A reusable, pre-planned bullpen sequence -- build once (e.g. "25-pitch
    Execution Ladder"), then load it when starting a real BullpenSession to
    pre-create the whole planned pitch sequence at once (Ryker's chosen
    workflow: script the whole thing upfront, link each pitch to Rapsodo
    after it's thrown, rather than picking each pitch live one at a time)."""
    __tablename__ = "bullpen_scripts"

    script_id = Column(Integer, primary_key=True)
    script_name = Column(String(150), nullable=False)
    bullpen_type_id = Column(Integer, ForeignKey("bullpen_types.bullpen_type_id"), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    bullpen_type = relationship("BullpenType")
    created_by = relationship("User")
    pitches = relationship("BullpenScriptPitch", back_populates="script", cascade="all, delete-orphan", order_by="BullpenScriptPitch.pitch_number")


class BullpenScriptPitch(Base):
    """One planned pitch within a BullpenScript -- pitch type + intended
    zone, in order. Copied into real BullpenPitch rows when the script is
    loaded to start an actual session."""
    __tablename__ = "bullpen_script_pitches"

    script_pitch_id = Column(Integer, primary_key=True)
    script_id = Column(Integer, ForeignKey("bullpen_scripts.script_id"), nullable=False)
    pitch_number = Column(Integer, nullable=False)
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    target_zone = Column(Integer, nullable=True)  # 0 = Bury, 1-9 = in-zone grid, same convention as BullpenPitch
    notes = Column(Text, nullable=True)

    script = relationship("BullpenScript", back_populates="pitches")
    pitch_type = relationship("PitchType")


class HitterSessionType(Base):
    """Lookup for hitter-tracking session type (Live ABs, Batting
    Practice, Intersquad, Scrimmage, Game)."""
    __tablename__ = "hitter_session_types"

    session_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class HitterTrackingSession(Base):
    """A hitter-tracking session (BP round, live AB work, scrimmage
    at-bats) -- a grouping container. Unlike bullpens, the pitcher can
    vary swing to swing within one session (facing multiple live arms,
    or a BP arm plus some live look reps), so pitcher info lives on
    each individual HitterSwing, not on the session itself."""
    __tablename__ = "hitter_tracking_sessions"

    session_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)  # the hitter
    session_type_id = Column(Integer, ForeignKey("hitter_session_types.session_type_id"), nullable=False)
    session_date = Column(Date, default=date.today, nullable=False)
    label = Column(String(150), nullable=True)  # optional further detail, e.g. "Round 2" on top of the type
    overall_notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player", foreign_keys=[player_id])
    session_type = relationship("HitterSessionType")
    created_by = relationship("User")
    swings = relationship("HitterSwing", back_populates="session", cascade="all, delete-orphan", order_by="HitterSwing.swing_number")


class HitterSwing(Base):
    """One swing within a HitterTrackingSession -- pitch type, intended
    location (what the pitcher was aiming for) vs. pitch_zone (the
    ACTUAL location it ended up at -- both same 1-9 + 0=Bury convention
    as pitcher zone tracking, only set when linked to a roster pitcher,
    since intent only makes sense for our own guys), pitcher hand,
    optional link to a specific roster pitcher (so a pitcher's own
    execution-accuracy and "where hitters struggle against me" heatmaps
    can both be built from the same data), contact quality, and where
    the ball was hit."""
    __tablename__ = "hitter_swings"

    swing_id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("hitter_tracking_sessions.session_id"), nullable=False)
    swing_number = Column(Integer, nullable=False)
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    intended_zone = Column(Integer, nullable=True)  # what the pitcher was aiming for -- only meaningful when pitcher_player_id is set (our own guy)
    pitch_zone = Column(Integer, nullable=True)  # 0 = Bury, 1-9 = in-zone grid -- where it ACTUALLY ended up, same convention as BullpenPitch
    pitcher_hand = Column(String(1), nullable=True)  # 'R' or 'L' -- always capturable even if the pitcher isn't a roster player (BP arm, machine, opponent)
    pitcher_player_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)  # optional: only set if it's one of our own roster pitchers
    contact_quality = Column(String(20), nullable=True)  # "Barrel" / "Solid" / "Weak" / "Miss"
    hit_location = Column(String(20), nullable=True)  # field spray direction -- not applicable for Miss
    notes = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)  # optional clip for this specific swing -- one per swing, no multi-angle, same as BullpenPitch

    session = relationship("HitterTrackingSession", back_populates="swings")
    pitch_type = relationship("PitchType")
    pitcher_player = relationship("Player", foreign_keys=[pitcher_player_id])