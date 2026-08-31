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
    ForeignKey, Numeric, UniqueConstraint, JSON
)
from sqlalchemy.orm import relationship

from database import Base


# ---------------------------------------------------------------------------
# 1. LOOKUP TABLES
# ---------------------------------------------------------------------------

class Role(Base):
    """The finalized MVP roles and what each is allowed to touch (8
    originally; "Video Coordinator" added 2026-08-26 -- see game_tracking.py,
    analytics.py, pitcher_game_report.py, hitter_game_report.py,
    opponent_teams.py, video_import.py, and nav.py for where it's
    special-cased).

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
    # Movement Flag inputs (bucket_system.compute_movement_flag) -- staff-set
    # on the player profile, not derived from any test data. poor_mover is
    # just the label used to number an already-Red flag (6+ ROM deficits);
    # current_injury is a hard override that forces Red regardless of
    # deficit count, since an active injury/surgical recovery matters more
    # than any ROM number. See compute_movement_flag's docstring.
    poor_mover = Column(Boolean, default=False, nullable=False)
    current_injury = Column(Boolean, default=False, nullable=False)
    injury_note = Column(Text, nullable=True)
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
    photo_url = Column(String(500), nullable=True)  # staff profile photo, same pattern as Player.photo_url
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
    shoulder mobility" into a measurable "85° -> 95° by Sept 1".

    Integrated Insights (spec Section 27) extension: for Pitcher-Specific
    goals whose target_test_type has a Rapsodo Bullpen Analytics
    equivalent (see analytics/rapsodo_goal_metrics.py -- most of them do,
    since PITCHER_SPECIFIC_TESTS in seed_lookups.py was originally written
    against Rapsodo's own vocabulary), baseline/current values are
    computed live from RapsodoPitch instead of AssessmentResult, since
    that's where pitch data actually lands now that the legacy
    Assessment-based Rapsodo import has been retired. Two new optional
    fields support this without disturbing the existing
    source_assessment_id/target_test_type_id pair used by every other
    category:
      - target_pitch_type_id: Rapsodo metrics vary a lot by pitch type
        (a fastball-velocity goal and a changeup-velocity goal are not
        the same number), so a Rapsodo-linked goal can optionally scope
        itself to one pitch type. Left null, it averages across every
        pitch type thrown.
      - source_bullpen_id: the bullpen session that motivated the goal,
        the Rapsodo-data equivalent of source_assessment_id. Optional,
        same "not freeform" spirit -- a real session, not typed-in text.
    """
    __tablename__ = "idp_goals"

    goal_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    category_id = Column(Integer, ForeignKey("assessment_categories.category_id"), nullable=False)
    source_assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=True)
    target_test_type_id = Column(Integer, ForeignKey("assessment_test_types.test_type_id"), nullable=True)
    target_pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    source_bullpen_id = Column(Integer, ForeignKey("bullpen_sessions.bullpen_id"), nullable=True)
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
    target_pitch_type = relationship("PitchType")
    source_bullpen = relationship("BullpenSession", back_populates="idp_goals")
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
    """Lookup for bullpen session type. Replaced (migrate_rapsodo_bullpen.py)
    from the original 5 values (High Intent Velo, Pitch Design, Execution
    Focused, Touch and Feel, Short Box) with the Rapsodo Bullpen Analytics
    spec's 8-value list: Standard Bullpen, Pitch Design, Command, Velocity,
    Recovery, Live BP, Assessment, Other. Existing BullpenSession rows are
    remapped onto the closest new name by the same migration -- see that
    file for the exact old->new mapping and rationale."""
    __tablename__ = "bullpen_types"

    bullpen_type_id = Column(Integer, primary_key=True)
    type_name = Column(String(50), unique=True, nullable=False)
    display_order = Column(Integer, default=0, nullable=False)


class BullpenSession(Base):
    """One bullpen outing for a pitcher on a given date -- the tracking
    sheet header. Individual pitches live in BullpenPitch (manual zone-tap
    tracking, being phased out) or RapsodoPitch (Rapsodo-imported data,
    the primary path going forward) -- a session can have either or both,
    since a bullpen might be tracked live with no device, imported from
    Rapsodo with no live tap tracking, or (during the transition) both.

    source_assignment_id optionally links back to the PlayerAssignment
    that prescribed this bullpen (Type=Bullpen), so starting a session
    from that assignment carries over its date/type automatically, and
    the assignment can be marked completed once the bullpen is tracked.

    video_url is session-level video (Rapsodo Bullpen Analytics spec
    Section 16) -- the whole bullpen's footage, distinct from any
    pitch-level clips on BullpenPitch.video_url or the future
    pitch-level sync in BullpenPitchVideo."""
    __tablename__ = "bullpen_sessions"

    bullpen_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    bullpen_type_id = Column(Integer, ForeignKey("bullpen_types.bullpen_type_id"), nullable=False)
    source_assignment_id = Column(Integer, ForeignKey("player_assignments.assignment_id"), nullable=True)
    session_date = Column(Date, default=date.today, nullable=False)
    overall_notes = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    player = relationship("Player")
    bullpen_type = relationship("BullpenType")
    source_assignment = relationship("PlayerAssignment")
    created_by = relationship("User")
    pitches = relationship("BullpenPitch", back_populates="bullpen", cascade="all, delete-orphan", order_by="BullpenPitch.pitch_number")
    rapsodo_imports = relationship("RapsodoImport", back_populates="bullpen")
    rapsodo_pitches = relationship("RapsodoPitch", back_populates="bullpen", cascade="all, delete-orphan", order_by="RapsodoPitch.pitch_number")
    idp_goals = relationship("IDPGoal", back_populates="source_bullpen")
    command_pitches = relationship("CommandPitch", back_populates="bullpen", cascade="all, delete-orphan", order_by="CommandPitch.pitch_number")


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


# ---------------------------------------------------------------------------
# RAPSODO BULLPEN ANALYTICS
#
# Rapsodo-native pitch storage, replacing the old pattern of importing
# pitches as Assessment/AssessmentResult rows (see pages/import_rapsodo.py --
# kept working for now, but no longer the destination for new imports).
# Three layers per the architecture review (GBO_Rapsodo_Module_Architecture_
# Review.md): raw (exactly as exported), derived (GBO-calculated, kept in
# separate columns so it's always clear what came from the device), and a
# raw_extra JSON catch-all for fields with no dedicated column yet.
#
# Column comments reference the actual CSV header text seen in the real
# export reviewed (a Rapsodo "Pitching" report) -- nothing here is a
# guessed/invented field name.
# ---------------------------------------------------------------------------

class RapsodoImport(Base):
    """One uploaded Rapsodo export file -- the audit/dedup log Section 21
    of the spec calls for. file_hash (sha256 of the raw file bytes) is the
    actual duplicate-import guard -- re-uploading the same file for the
    same player is rejected before anything is inserted, closing the known
    limitation flagged in the old import_rapsodo.py docstring ("re-
    importing the same file twice will create duplicates").

    Scoped to one player per import, matching the real export format
    reviewed (a single "Player ID:"/"Player Name:" header, no per-row
    player column) -- this is a per-pitcher, per-outing device export, not
    a multi-player team file."""
    __tablename__ = "rapsodo_imports"
    __table_args__ = (UniqueConstraint("player_id", "file_hash", name="uq_rapsodo_import_player_hash"),)

    import_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    bullpen_id = Column(Integer, ForeignKey("bullpen_sessions.bullpen_id"), nullable=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=True)  # set instead of bullpen_id when this file was imported against an intrasquad game outing rather than a bullpen session -- mutually exclusive with bullpen_id, never both set
    original_filename = Column(String(255), nullable=False)
    file_hash = Column(String(64), nullable=False)  # sha256 hex digest of the raw uploaded bytes
    uploaded_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    row_count = Column(Integer, nullable=False)  # total data rows found in the file
    imported_row_count = Column(Integer, default=0, nullable=False)
    rejected_row_count = Column(Integer, default=0, nullable=False)
    status = Column(String(20), nullable=False)  # "success" / "partial" / "failed"
    error_summary = Column(Text, nullable=True)  # human-readable reasons for any rejected rows / failure

    player = relationship("Player")
    bullpen = relationship("BullpenSession", back_populates="rapsodo_imports")
    game = relationship("Game")
    uploaded_by = relationship("User")
    pitches = relationship("RapsodoPitch", back_populates="import_record")


class RapsodoPitch(Base):
    """One pitch from a Rapsodo bullpen export.

    pitch_number is chronological within the session, assigned by GBO from
    the parsed pitch Date/timestamp -- NOT copied from the file's own "No"
    column. The real export reviewed lists pitches most-recent-first (No=1
    had the latest timestamp, No=13 the earliest) -- using "No" directly
    would silently invert true throwing order everywhere it matters: the
    Pitch Number Range filter, the individual-pitch table, and (for a
    combined multi-session view) the chronological ordering by pitch_date.

    rapsodo_unique_id (CSV "Unique ID", e.g. "1502926@1786212209") plus the
    player_id unique constraint below is a second, DB-level dedup guard on
    top of RapsodoImport.file_hash.
    """
    __tablename__ = "rapsodo_pitches"
    __table_args__ = (UniqueConstraint("player_id", "rapsodo_unique_id", name="uq_rapsodo_pitch_player_unique_id"),)

    rapsodo_pitch_id = Column(Integer, primary_key=True)
    bullpen_id = Column(Integer, ForeignKey("bullpen_sessions.bullpen_id"), nullable=True)  # nullable Aug 2026: an intrasquad-game import (see RapsodoImport.game_id) has no bullpen session at all -- one or the other is set, matching the import it came from
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    import_id = Column(Integer, ForeignKey("rapsodo_imports.import_id"), nullable=False)
    pitch_number = Column(Integer, nullable=False)  # chronological within the session -- see docstring above
    game_pitch_id = Column(Integer, ForeignKey("game_pitches.game_pitch_id"), nullable=True)  # set once this reading has been matched to the specific live-charted pitch it came from (intrasquad-game imports only) -- see services/rapsodo_import.py's matching logic

    # --- Raw layer: exactly as imported, never overwritten by recalculation ---
    rapsodo_pitch_id_raw = Column(String(50), nullable=True)  # CSV "Pitch ID"
    rapsodo_unique_id = Column(String(100), nullable=True)  # CSV "Unique ID"
    pitch_date = Column(DateTime, nullable=True)  # parsed CSV "Date"
    raw_pitch_type = Column(String(50), nullable=True)  # CSV "Pitch Type", pre-normalization ("-" if Rapsodo couldn't classify it)
    is_strike = Column(Boolean, nullable=True)  # CSV "Is Strike" (Y/N)
    strike_zone_side = Column(Numeric(7, 3), nullable=True)  # CSV "Strike Zone Side", inches, zone-relative
    strike_zone_height = Column(Numeric(7, 3), nullable=True)  # CSV "Strike Zone Height", inches
    velocity = Column(Numeric(6, 2), nullable=True)  # CSV "Velocity", mph
    total_spin = Column(Numeric(7, 2), nullable=True)  # CSV "Total Spin", rpm
    true_spin = Column(Numeric(7, 2), nullable=True)  # CSV "True Spin (release)", rpm
    spin_efficiency = Column(Numeric(6, 2), nullable=True)  # CSV "Spin Efficiency (release)", %
    spin_direction_clock = Column(String(10), nullable=True)  # CSV "Spin Direction", clock format e.g. "12:18"
    spin_confidence = Column(Numeric(5, 3), nullable=True)  # CSV "Spin Confidence"
    vb_trajectory = Column(Numeric(6, 2), nullable=True)  # CSV "VB (trajectory)", in
    hb_trajectory = Column(Numeric(6, 2), nullable=True)  # CSV "HB (trajectory)", in
    ssw_vb = Column(Numeric(6, 2), nullable=True)  # CSV "SSW VB" -- seam-shifted-wake component, often blank
    ssw_hb = Column(Numeric(6, 2), nullable=True)  # CSV "SSW HB"
    vb_spin = Column(Numeric(6, 2), nullable=True)  # CSV "VB (spin)" -- spin-induced vertical break, in (this is what Section 7's Movement Chart / IVB uses)
    hb_spin = Column(Numeric(6, 2), nullable=True)  # CSV "HB (spin)" -- spin-induced horizontal break, in
    horizontal_angle = Column(Numeric(6, 2), nullable=True)  # CSV "Horizontal Angle" -- appears to be release-point launch angle, pending confirmation before trajectory-engine use (see architecture review)
    release_angle = Column(Numeric(6, 2), nullable=True)  # CSV "Release Angle" -- same caveat as above
    release_height = Column(Numeric(6, 3), nullable=True)  # CSV "Release Height", ft
    release_side = Column(Numeric(6, 3), nullable=True)  # CSV "Release Side", ft
    gyro_degree = Column(Numeric(6, 2), nullable=True)  # CSV "Gyro Degree (deg)"
    device_serial_number = Column(String(50), nullable=True)  # CSV "Device Serial Number"
    horizontal_approach_angle = Column(Numeric(6, 2), nullable=True)  # CSV "Horizontal Approach Angle" -- at plate crossing
    vertical_approach_angle = Column(Numeric(6, 2), nullable=True)  # CSV "Vertical Approach Angle"
    rapsodo_session_name = Column(String(150), nullable=True)  # CSV "Session Name" -- the device's own session label, NOT GBO's BullpenSession
    intent_type = Column(String(50), nullable=True)  # CSV "Intent Type" -- blank/"-" in every real export seen so far
    release_extension = Column(Numeric(6, 3), nullable=True)  # CSV "Release Extension (ft)"
    raw_extra = Column(JSON, nullable=True)  # catch-all: "No" (file row order), "SO - *" sensor-orientation fields, and any future unmapped column

    # --- Derived layer: GBO-calculated, kept separate from raw values ---
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)  # normalized via pitch_type_config.py
    spin_axis_degrees = Column(Numeric(5, 1), nullable=True)  # converted from spin_direction_clock, see rapsodo_conventions.py
    plate_x_ft = Column(Numeric(6, 3), nullable=True)  # converted from strike_zone_side (GBO plate-center-at-0 convention, matches strike_zone.py)
    plate_z_ft = Column(Numeric(6, 3), nullable=True)  # converted from strike_zone_height (0 = ground)
    perceived_velocity = Column(Numeric(6, 2), nullable=True)  # extension-adjusted formula -- deferred indefinitely per Ryker's Phase 4 call (no agreed-on reference baseline), still NULL
    trajectory_json = Column(JSON, nullable=True)  # a Phase 4 flight-path model (pitch_trajectory.py) briefly computed and stored this at import time, then was removed per Ryker's call after reviewing the chart live -- nothing computes or reads this anymore. Left in place rather than dropped, since some rows still hold values from that brief window and dropping the column would just discard them for no benefit; safe to ignore, and safe to drop later in a real migration if this is ever cleaned up

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    bullpen = relationship("BullpenSession", back_populates="rapsodo_pitches")
    player = relationship("Player")
    import_record = relationship("RapsodoImport", back_populates="pitches")
    pitch_type = relationship("PitchType")
    pitch_videos = relationship("BullpenPitchVideo", back_populates="pitch", cascade="all, delete-orphan")
    game_pitch = relationship("GamePitch")


class BullpenPitchVideo(Base):
    """Pitch-level video timestamp -- maps one RapsodoPitch to an offset
    into a bullpen video, so a player/coach can jump straight to that
    pitch's delivery (Rapsodo Bullpen Analytics spec Section 16's
    long-term architecture). Table created now (Phase 1) since it's purely
    additive with no dependency on anything undecided, but not wired into
    any UI until Phase 5 -- pitch-level sync needs its own scrubbing/
    tagging UI, not something to half-build alongside the importer."""
    __tablename__ = "bullpen_pitch_videos"

    bullpen_pitch_video_id = Column(Integer, primary_key=True)
    rapsodo_pitch_id = Column(Integer, ForeignKey("rapsodo_pitches.rapsodo_pitch_id"), nullable=False)
    video_url = Column(String(500), nullable=False)
    timestamp_seconds = Column(Numeric(8, 2), nullable=True)  # offset into the video where this pitch's delivery starts
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    pitch = relationship("RapsodoPitch", back_populates="pitch_videos")


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


class OpponentTeam(Base):
    """A reusable opponent team -- create once, select from a list for
    every future game against them instead of re-typing the name (and,
    once a roster is built out, picking real opposing players by name
    instead of just entering hand + batting order each time)."""
    __tablename__ = "opponent_teams"

    team_id = Column(Integer, primary_key=True)
    team_name = Column(String(150), unique=True, nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_by = relationship("User")
    roster = relationship("OpponentPlayer", back_populates="team", cascade="all, delete-orphan", order_by="OpponentPlayer.player_name")


class OpponentPlayer(Base):
    """One player on an opponent team's roster -- name, and whatever's
    known about them (jersey #, bats/throws, position). Optional --
    Game Tracking still works with just hand + batting order typed in
    if a team's roster isn't built out yet."""
    __tablename__ = "opponent_players"

    opponent_player_id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("opponent_teams.team_id"), nullable=False)
    player_name = Column(String(150), nullable=False)
    jersey_number = Column(String(10), nullable=True)
    bats = Column(String(1), nullable=True)  # 'R' / 'L' / 'S' (switch)
    throws = Column(String(1), nullable=True)  # 'R' / 'L' -- relevant if this player pitches
    position = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)

    team = relationship("OpponentTeam", back_populates="roster")


class Season(Base):
    """A season a Game belongs to (e.g. "Fall 2026", "Spring 2027") --
    lets fall/practice games stay separate from real spring regular-
    season stats once games are actually aggregated into a stats page.
    is_official distinguishes "counts toward real record" (spring
    regular season) from practice/exhibition play (fall ball,
    intrasquad scrimmages) -- created as needed by coaches, not a
    fixed pre-seeded list, since season names/dates are program-
    specific."""
    __tablename__ = "seasons"

    season_id = Column(Integer, primary_key=True)
    season_name = Column(String(100), unique=True, nullable=False)
    is_official = Column(Boolean, default=True, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_by = relationship("User")
    games = relationship("Game", back_populates="season")


class Game(Base):
    """A tracked game -- opponent, date, home/away. Both our hitting
    (our batters facing the opposing pitcher) and our pitching (our
    pitcher facing the opposing batters) get tracked here, in the same
    GamePitch table -- see that model for how the two sides share one
    schema via is_our_team_batting rather than needing two separate
    tracking systems (same "one entry point" reasoning already applied
    to Hitter Tracking's intended-zone field).

    opponent_team_id links to a reusable OpponentTeam (create once,
    pick from a list for future games). opponent_name stays as a
    nullable legacy field -- games created before opponent teams
    existed still display correctly from it; new games use the team
    link instead.

    is_intrasquad: when True, the "opponent" side of every pitch in
    this game is actually one of OUR OWN roster players (Squad A vs
    Squad B), not an external opponent -- see GamePitch.
    opponent_our_player_id for how that's captured so both squads'
    stats stay attributed to real player profiles, not lost to a
    generic hand/order entry or a disconnected OpponentPlayer.

    season_id: which Season this game counts toward (e.g. "Fall 2026"
    vs "Spring 2027") -- keeps fall/practice stats separate from real
    spring regular-season stats once games get aggregated. Nullable
    for backward compatibility with games created before seasons
    existed.

    opponent_starting_pitcher_id: their starting pitcher, from the
    linked OpponentTeam's roster -- only meaningful for external games
    with a real OpponentTeam linked (not intrasquad, not a one-off
    typed name)."""
    __tablename__ = "games"

    game_id = Column(Integer, primary_key=True)
    season_id = Column(Integer, ForeignKey("seasons.season_id"), nullable=True)
    opponent_team_id = Column(Integer, ForeignKey("opponent_teams.team_id"), nullable=True)
    opponent_name = Column(String(150), nullable=True)
    is_intrasquad = Column(Boolean, default=False, nullable=False)
    game_date = Column(Date, default=date.today, nullable=False)
    is_home = Column(Boolean, nullable=True)  # True=home, False=away, None=unspecified (e.g. neutral site)
    our_score = Column(Integer, default=0, nullable=False)
    opponent_score = Column(Integer, default=0, nullable=False)
    status = Column(String(20), default="Scheduled", nullable=False)  # "Scheduled" / "In Progress" / "Paused" / "Final" / "Cancelled"
    starting_pitcher_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)
    # Squad A's starting pitcher (starting_pitcher_id above) has always
    # been formally tracked -- Squad A's ongoing "who's pitching" is
    # derived from PitchingChange, falling back to this field (see
    # get_current_pitcher_id() in modules/game_tracking.py). Squad B
    # never had an equivalent: its pitcher was picked live, every
    # single plate appearance, with nothing saved. This column adds
    # just the STARTING pick for Squad B (mirroring starting_pitcher_id)
    # -- added via migrations/migrate_squad_b_starting_pitcher.py, not
    # backed by a parallel PitchingChange-style table, so Squad B still
    # has no formal "pitching change" history the way Squad A does.
    # Live tracking uses this as a smarter DEFAULT for the per-PA
    # opposing-pitcher picker (falling back further to whichever Squad B
    # pitcher most recently appeared in this game's pitches once any
    # have been recorded) -- always overridable, same as every other
    # auto-suggested default on this page.
    squad_b_starting_pitcher_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)
    opponent_starting_pitcher_id = Column(Integer, ForeignKey("opponent_players.opponent_player_id"), nullable=True)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    created_by = relationship("User")
    season = relationship("Season", back_populates="games")
    opponent_team = relationship("OpponentTeam")
    lineup_slots = relationship("GameLineupSlot", back_populates="game", cascade="all, delete-orphan", order_by="GameLineupSlot.batting_order")
    starting_pitcher = relationship("Player", foreign_keys=[starting_pitcher_id])
    squad_b_starting_pitcher = relationship("Player", foreign_keys=[squad_b_starting_pitcher_id])
    opponent_lineup_slots = relationship("OpponentLineupSlot", back_populates="game", cascade="all, delete-orphan", order_by="OpponentLineupSlot.batting_order")
    opponent_starting_pitcher = relationship("OpponentPlayer", foreign_keys=[opponent_starting_pitcher_id])
    pitches = relationship("GamePitch", back_populates="game", cascade="all, delete-orphan", order_by="GamePitch.pitch_sequence")
    pitching_changes = relationship("PitchingChange", back_populates="game", cascade="all, delete-orphan", order_by="PitchingChange.pitch_sequence_at_entry")
    lineup_substitutions = relationship("LineupSubstitution", back_populates="game", cascade="all, delete-orphan", order_by="LineupSubstitution.pitch_sequence_at_entry")
    video_clips = relationship("GameVideoClip", back_populates="game", cascade="all, delete-orphan", order_by="GameVideoClip.uploaded_at")
    runner_events = relationship("GameRunnerEvent", back_populates="game", cascade="all, delete-orphan", order_by="GameRunnerEvent.pitch_sequence_after")


class GameLineupSlot(Base):
    """One batting-order slot for a lineup in a given game -- who
    STARTED hitting where, and their starting defensive position.
    Pitching changes aren't tracked as a separate list in this first
    version -- who pitched is simply whatever's on the GamePitch
    records (pitcher_player_id), derived rather than pre-declared.

    squad: 'A' (default) or 'B'. For every external game this is always
    'A' -- the "OUR lineup" this table was originally built for. For
    intrasquad games (Squad A vs Squad B, both sides drawn from our own
    roster), the same table now also holds Squad B's batting order,
    distinguished by this column, so both squads get a real saved
    lineup instead of only Squad A having one and Squad B being picked
    ad hoc every at-bat. Squad B's PITCHING staff (starting
    pitcher/pitching changes) is intentionally NOT covered by this --
    that stays a per-at-bat pick, same as before this column existed.

    player_id/starting_position_id are this slot's ORIGINAL occupant --
    kept immutable once saved, same as PitchingChange never rewrites
    Game.starting_pitcher_id. Who's CURRENTLY in this slot (after any
    in-game substitutions) is derived, not stored here -- see
    LineupSubstitution below and game_tracking.py's
    get_current_slot_occupant_id()/get_current_slot_position_id(), the
    batting-side equivalent of get_current_pitcher_id() for pitching.

    batting_order can be renumbered in place when a new slot is
    inserted mid-order (game_tracking.py's _insert_lineup_slot_at --
    every existing slot at or after the insertion point shifts +1).
    This is safe: every foreign key that references a slot
    (LineupSubstitution.lineup_slot_id, GamePitch.batting_slot_id)
    points at lineup_slot_id, this row's stable primary key, never at
    the batting_order value -- so renumbering never invalidates a past
    pitch's or substitution's slot reference, it only changes what
    order number that slot currently displays as."""
    __tablename__ = "game_lineup_slots"

    lineup_slot_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    squad = Column(String(1), nullable=False, default="A")  # 'A' or 'B' -- see class docstring
    batting_order = Column(Integer, nullable=False)  # 1-9 (or more -- extra slots can be inserted anywhere mid-game, see class docstring)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    starting_position_id = Column(Integer, ForeignKey("positions.position_id"), nullable=True)

    game = relationship("Game", back_populates="lineup_slots")
    player = relationship("Player")
    starting_position = relationship("Position")
    substitutions = relationship("LineupSubstitution", back_populates="lineup_slot", cascade="all, delete-orphan", order_by="LineupSubstitution.pitch_sequence_at_entry")


class OpponentLineupSlot(Base):
    """One batting-order slot for the OPPONENT's lineup in a given game
    -- mirrors GameLineupSlot, but for a real named player from their
    OpponentTeam roster instead of one of ours. Only meaningful for
    external games with a real OpponentTeam linked (not intrasquad,
    not a one-off typed opponent name, and not useful without a team
    roster built out). Optional -- Game Tracking still works with just
    hand + batting order typed in if this isn't set up for a given
    game, same as before this existed."""
    __tablename__ = "opponent_lineup_slots"

    opponent_lineup_slot_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    batting_order = Column(Integer, nullable=False)  # 1-9
    opponent_player_id = Column(Integer, ForeignKey("opponent_players.opponent_player_id"), nullable=False)

    game = relationship("Game", back_populates="opponent_lineup_slots")
    opponent_player = relationship("OpponentPlayer")


class RunExpectancy(Base):
    """Lookup table for run expectancy by (outs, bases, count) -- Ryker's
    own real RE table (not a generic published one), keyed more finely
    than the standard 24-state RE24 matrix since it includes the count.
    Used to compute RE Before/RE After/Run Value on each GamePitch."""
    __tablename__ = "run_expectancy"

    re_id = Column(Integer, primary_key=True)
    outs = Column(Integer, nullable=False)
    bases = Column(String(3), nullable=False)  # e.g. "010" = runner on 2nd only
    count = Column(String(3), nullable=False)  # e.g. "0-0", "3-2"
    re_value = Column(Numeric(6, 3), nullable=False)


class PitchingChange(Base):
    """A formal record of a pitcher entering a game -- who, and when
    (inning/outs/pitch sequence at entry). The "current pitcher" for
    live tracking is derived from the MOST RECENT PitchingChange for
    the game (falling back to Game.starting_pitcher_id if none exist
    yet) -- the coach doesn't re-select the pitcher every plate
    appearance, only when an actual change happens."""
    __tablename__ = "pitching_changes"

    pitching_change_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    inning = Column(Integer, nullable=False)
    outs_at_entry = Column(Integer, nullable=False)
    pitch_sequence_at_entry = Column(Integer, nullable=False)  # the game's overall pitch # at the moment this pitcher entered -- used to order changes
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    game = relationship("Game", back_populates="pitching_changes")
    player = relationship("Player")


class LineupSubstitution(Base):
    """A formal record of a player entering an EXISTING batting-order
    slot (GameLineupSlot), replacing whoever currently occupies it --
    who, and when (inning/outs/pitch sequence at entry). Analogous to
    PitchingChange above, but scoped to ONE lineup slot rather than the
    whole team, since batting has many simultaneous "current occupants"
    (one per batting-order slot) instead of a single pitcher role.

    The "current occupant" of a given slot is derived from the MOST
    RECENT LineupSubstitution for that slot (falling back to
    GameLineupSlot.player_id -- the slot's original starter -- if none
    exist yet), the exact same "most-recent-wins, fall back to the
    starting field" idea PitchingChange already uses -- see
    game_tracking.py's get_current_slot_occupant_id(), the batting-side
    equivalent of get_current_pitcher_id().

    Adding a brand-new slot that wasn't part of the original lineup
    (an "extra hitter" cycling into a scrimmage) is a DIFFERENT
    operation from this table -- see GameLineupSlot's docstring and
    game_tracking.py's _insert_lineup_slot_at(); this table only covers
    swapping who's IN an existing slot.

    new_position_id optionally records that the incoming player takes
    over a different defensive position than the slot's previous
    occupant, going forward. This is informational only -- who's
    nominally playing where -- and is NOT used for any fielding-stat
    attribution (putouts/assists/errors by fielder remain a separate,
    out-of-scope future phase; this app doesn't track those at all
    yet)."""
    __tablename__ = "lineup_substitutions"

    lineup_substitution_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    lineup_slot_id = Column(Integer, ForeignKey("game_lineup_slots.lineup_slot_id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    inning = Column(Integer, nullable=False)
    outs_at_entry = Column(Integer, nullable=False)
    pitch_sequence_at_entry = Column(Integer, nullable=False)  # overall game pitch # at entry -- orders changes within the slot, same convention as PitchingChange.pitch_sequence_at_entry
    new_position_id = Column(Integer, ForeignKey("positions.position_id"), nullable=True)  # NULL = position unchanged from whoever/whatever was there before
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    game = relationship("Game", back_populates="lineup_substitutions")
    lineup_slot = relationship("GameLineupSlot", back_populates="substitutions")
    player = relationship("Player")
    new_position = relationship("Position")


class PlayerPitchArsenal(Base):
    """Which pitch types a given pitcher actually throws -- filters the
    pitch-type dropdown during live tracking to just their real
    arsenal. Optional: a pitcher with no arsenal configured yet still
    sees the full pitch type list (doesn't block data entry)."""
    __tablename__ = "player_pitch_arsenal"
    __table_args__ = (UniqueConstraint("player_id", "pitch_type_id", name="uq_player_pitch_arsenal"),)

    arsenal_id = Column(Integer, primary_key=True)
    player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    player = relationship("Player")
    pitch_type = relationship("PitchType")


class GamePitch(Base):
    """One pitch within a tracked game -- the fundamental unit, same as
    Ryker's own tracking sheet (one row per pitch). Covers BOTH sides
    of the ball via is_our_team_batting:
      - True: our_player_id is the BATTER (from our lineup), the
        opponent is the pitcher we don't have in our roster (hand only).
      - False: our_player_id is the PITCHER (ours), the opponent is the
        batter we don't have in our roster (hand + their batting order
        position only, matching Ryker's sheet's "Batting Order" column
        used for opponent lineup tracking when we're pitching).

    Base/out state (outs_before/after, bases_before/after as a simple
    3-char string like "010" matching Ryker's own sheet -- 1st/2nd/3rd,
    1=occupied) is entered by the coach per pitch, with sensible
    defaults suggested by the AB outcome but always overridable --
    deliberately not a fully automated rules engine (errors, odd
    advances, etc. are exactly the cases that need human judgment).

    Run Expectancy / Run Value are NOT computed in this first version
    -- deferred to the advanced-stats follow-up phase, once a standard
    RE24-style matrix is decided on."""
    __tablename__ = "game_pitches"

    game_pitch_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    pitch_sequence = Column(Integer, nullable=False)  # overall pitch # for the game, in order

    inning = Column(Integer, nullable=False)
    is_our_team_batting = Column(Boolean, nullable=False)

    our_player_id = Column(Integer, ForeignKey("players.player_id"), nullable=False)  # batter if is_our_team_batting, else pitcher
    opponent_hand = Column(String(1), nullable=True)  # 'R' / 'L' -- the OTHER side's hand (pitcher's hand if we're batting, batter's hand if we're pitching). Auto-filled if opponent_player_id is set and that player has a hand on file, but always independently editable.
    opponent_batting_order = Column(Integer, nullable=True)  # only meaningful when is_our_team_batting is False -- their lineup slot
    opponent_player_id = Column(Integer, ForeignKey("opponent_players.opponent_player_id"), nullable=True)  # optional: a specific named player from the opponent's roster, if their team roster is built out
    opponent_our_player_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)  # intrasquad games only: the OTHER side is actually one of our own roster players (Squad A vs Squad B) -- keeps their stats attributed to their real profile instead of a generic hand/order entry
    # Which GameLineupSlot the batter currently occupies, at the moment
    # this pitch was recorded -- set only when a real batter (our
    # Squad A, or our Squad B in an intrasquad game) is at the plate;
    # NULL for pitches where we're pitching, and NULL when batting
    # against a genuine external opponent (their batters aren't backed
    # by a GameLineupSlot at all). Lets game_tracking.py's
    # suggest_next_our_batter/suggest_next_squad_b_batter look up "the
    # next slot after this one" directly, instead of re-matching by
    # player identity -- which stays robust even if a player is
    # substituted out and later re-enters the same slot. See
    # LineupSubstitution and _resolve_current_batting_slot().
    batting_slot_id = Column(Integer, ForeignKey("game_lineup_slots.lineup_slot_id"), nullable=True)

    pa_pitch_number = Column(Integer, nullable=True)  # pitch # within this specific plate appearance
    balls_before = Column(Integer, nullable=True)
    strikes_before = Column(Integer, nullable=True)
    outs_before = Column(Integer, nullable=True)
    bases_before = Column(String(3), nullable=True)  # e.g. "010" = runner on 2nd only

    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    intended_zone = Column(Integer, nullable=True)  # 0=Bury, 1-9 grid -- DERIVED from intended_plate_x/z below, kept so existing execution-accuracy calculations elsewhere in the app (game_stats.py, etc.) keep working unchanged
    pitch_zone = Column(Integer, nullable=True)  # actual location, same convention -- DERIVED from actual_plate_x/z below
    # Precise pitch location, replacing manual zone-button entry per
    # Ryker's architecture doc (click the exact spot instead of picking
    # a coarse 1-9 zone). Feet, matching Statcast/Trackman convention:
    # plate_x = 0 at the center of the plate, negative = 3B/left side as
    # drawn on the graphic; plate_z = 0 at the ground. intended_* is
    # only set when we're pitching (we don't know an opposing pitcher's
    # intent when we're batting). intended_zone/pitch_zone above are
    # auto-derived from these via strike_zone.derive_old_zone() at save
    # time -- never entered separately, so the two can't drift.
    actual_plate_x = Column(Numeric(5, 3), nullable=True)
    actual_plate_z = Column(Numeric(5, 3), nullable=True)
    intended_plate_x = Column(Numeric(5, 3), nullable=True)
    intended_plate_z = Column(Numeric(5, 3), nullable=True)
    pitch_outcome = Column(String(20), nullable=True)  # "Ball" / "Called Strike" / "Swing and Miss" / "Foul" / "In Play" / "HBP"
    contact_quality = Column(String(20), nullable=True)  # "Barrel" / "Solid" / "Weak" / "Miss" -- same categories as Hitter Tracking
    # Only meaningful when pitch_outcome == "In Play". Swing/take itself
    # isn't a separate field -- it's already fully derivable from
    # pitch_outcome (Swing and Miss/Foul/In Play = swung; Ball/Called
    # Strike/HBP = didn't), so storing it again here would just be
    # redundant data that could drift out of sync. batted_ball_x/y are
    # raw field coordinates (see field_location.py) -- Pull/Straight/
    # Oppo is deliberately NOT computed/stored here, since that
    # classification depends on batter handedness (varies by scenario:
    # our batter, an intrasquad opponent, an external roster player, or
    # hand-only) and belongs in analysis code, not entry.
    batted_ball_type = Column(String(20), nullable=True)  # "Ground Ball" / "Line Drive" / "Fly Ball" / "Pop Up"
    batted_ball_x = Column(Numeric(6, 1), nullable=True)  # feet, right of the CF line
    batted_ball_y = Column(Numeric(6, 1), nullable=True)  # feet, from home plate toward the outfield

    # "Sword" -- broadcast slang for an ugly, off-balance checked swing
    # (per Ryker's definition). Not derivable from pitch_outcome/contact
    # quality -- it's a judgment call the coach makes live, so it's its
    # own flag rather than a computed value. Only meaningful on a pitch
    # that was actually swung at (Swing and Miss/Foul/In Play); left
    # False on takes.
    is_sword = Column(Boolean, default=False, nullable=False)

    ends_plate_appearance = Column(Boolean, default=False, nullable=False)
    ab_outcome = Column(String(30), nullable=True)  # only set when ends_plate_appearance -- "K", "BB", "1B", "2B", "3B", "HR", "HBP", "E", "FC", "Sac Bunt", "Sac Fly", "Groundout", "Flyout", "Lineout", etc.

    outs_after = Column(Integer, nullable=True)
    bases_after = Column(String(3), nullable=True)
    runs_scored_on_play = Column(Integer, default=0, nullable=False)

    # Run Expectancy / Run Value -- computed from RunExpectancy at save
    # time using Ryker's own table: re_before = lookup(outs_before,
    # bases_before, count_before). re_after = lookup(outs_after,
    # bases_after, "0-0") if this pitch ended the PA (0 if the inning
    # ended too), otherwise lookup(outs_before, bases_before, the new
    # count) since only the count changed. run_value = (re_after +
    # runs_scored_on_play) - re_before. Null if the state fell outside
    # the table (e.g. a count that doesn't appear in it).
    re_before = Column(Numeric(6, 3), nullable=True)
    re_after = Column(Numeric(6, 3), nullable=True)
    run_value = Column(Numeric(6, 3), nullable=True)

    notes = Column(Text, nullable=True)
    video_url = Column(String(500), nullable=True)  # optional clip for this specific pitch, same "pitch-videos" bucket

    game = relationship("Game", back_populates="pitches", foreign_keys=[game_id])
    our_player = relationship("Player", foreign_keys=[our_player_id])
    opponent_our_player = relationship("Player", foreign_keys=[opponent_our_player_id])
    pitch_type = relationship("PitchType")
    opponent_player = relationship("OpponentPlayer")
    batting_slot = relationship("GameLineupSlot", foreign_keys=[batting_slot_id])


class GameRunnerEvent(Base):
    """A base-running event that happens BETWEEN two pitches to the same
    batter -- a stolen base, caught stealing, pickoff, wild pitch,
    passed ball, or balk (Aug 2026, Ryker: "we need to be able to put
    if a guy steals a base, gets picked off etc.").

    GamePitch.bases_before/outs_before only ever change on a pitch that
    ENDS the plate appearance (see game_tracking.py's result_fields_body
    -- the "Bases after" field only shows up then); compute_current_state()
    otherwise just carries outs_before/bases_before straight forward
    from the previous pitch. That left literally no way to record
    something that happens MID-plate-appearance -- a runner stealing
    second on ball two, say. This table is the fix: a small,
    separately-recorded event, ordered by pitch_sequence_after (the
    pitch_sequence of the last GamePitch actually recorded when this
    happened -- 0 if it happened before the game's first pitch), the
    same "small event table keyed by pitch_sequence_at_entry" pattern
    PitchingChange/LineupSubstitution already use in this exact file.
    compute_current_state() folds every event matching the current gap
    on top of the pitch-derived state, including rolling to the next
    half-inning if an event's out pushes the count to 3 -- see that
    function's docstring in game_tracking.py.

    from_base/to_base: 1/2/3 for a base, 4 for home (the runner scored).
    to_base is NULL when is_out is True (Caught Stealing/Picked Off --
    Wild Pitch/Passed Ball/Balk/Stolen Base always advance, never out).
    Runs scored via to_base == 4 are added to Game.our_score/
    opponent_score at the moment the event is recorded (mirroring how
    record_pitch() bumps the score for a live-ball run), NOT re-derived
    every render -- compute_current_state()'s fold-forward only touches
    bases/outs, never the score total.

    our_player_id/opponent_player_id: OPTIONAL identification of the
    runner -- same "always overridable, don't force a pick you don't
    have" philosophy as GamePitch.opponent_player_id. A coach can log
    "runner on 2nd stole 3rd" without naming who if the opponent roster
    isn't built out; both may be left NULL to just tag the base-state
    change itself. Deliberately NOT a fully automated rules engine (no
    attempt to track which specific player occupies which base across
    the whole game) -- same human-judgment principle GamePitch's own
    docstring states for base/out entry generally."""
    __tablename__ = "game_runner_events"

    runner_event_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    pitch_sequence_after = Column(Integer, nullable=False)  # the pitch_sequence of the last actual pitch recorded before this event; 0 if none yet this game
    is_our_team_batting = Column(Boolean, nullable=False)  # which side had the runner -- same convention as GamePitch.is_our_team_batting, stored (not just used transiently) so an undo can reverse a scored run against the right side's total without re-deriving it
    event_type = Column(String(30), nullable=False)  # "Stolen Base" / "Caught Stealing" / "Picked Off" / "Wild Pitch" / "Passed Ball" / "Balk" / "Defensive Indifference"
    from_base = Column(Integer, nullable=False)  # 1, 2, or 3
    to_base = Column(Integer, nullable=True)  # 2, 3, or 4 (home) -- NULL when is_out
    is_out = Column(Boolean, default=False, nullable=False)
    our_player_id = Column(Integer, ForeignKey("players.player_id"), nullable=True)  # the runner, if a real Player (Squad A or intrasquad Squad B)
    opponent_player_id = Column(Integer, ForeignKey("opponent_players.opponent_player_id"), nullable=True)  # the runner, if a named external-opponent player
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    game = relationship("Game", back_populates="runner_events")
    our_player = relationship("Player")
    opponent_player = relationship("OpponentPlayer")
    created_by = relationship("User")


class GameVideoClip(Base):
    """One uploaded video clip for a game -- "upload now, match to the
    actual pitch later" (same pattern already proven on Video Review's
    pitcher bulk-upload against the Assessment/Video tables). Kept as
    its own table rather than writing straight to GamePitch.video_url
    on upload, so an uploaded-but-not-yet-matched clip has somewhere
    to live and survives across sessions until someone matches it --
    matching just copies this row's video_url onto the chosen
    GamePitch and sets matched_game_pitch_id, so GamePitch.video_url
    stays the one source of truth every other page/report reads from.

    Reuses the same "pitch-videos" Storage bucket as everywhere else
    video is uploaded in GBO -- no new bucket needed."""
    __tablename__ = "game_video_clips"

    game_video_clip_id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey("games.game_id"), nullable=False)
    video_url = Column(String(500), nullable=False)
    original_filename = Column(String(255), nullable=True)
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    matched_game_pitch_id = Column(Integer, ForeignKey("game_pitches.game_pitch_id"), nullable=True)

    game = relationship("Game", back_populates="video_clips")
    matched_game_pitch = relationship("GamePitch")


# ---------------------------------------------------------------------------
# INTENDED LOCATION & COMMAND TRACKER
#
# GBO's own command-tracking system (inspired by, but not a copy of, any
# third-party intended-zone tracker) -- captures where a pitcher/catcher/
# coach INTENDED a pitch to go alongside where it ACTUALLY crossed the
# plate, as continuous coordinates, so command (intent vs. execution) can
# be measured directly instead of inferred from strike% or a coarse 1-9
# zone. See the architecture doc agreed with Ryker (Aug 2026) for the
# full spec and phased rollout; this is the Phase 1 (MVP) schema only --
# Phase 2 adds no new columns (trend/heatmap/ellipse views are all
# computed from what's already here), Phase 3 (automated Rapsodo
# matching, game-tracking integration) is expected to need further
# additions and is deliberately not designed yet.
#
# Deliberately reuses BullpenSession as the session container (Command
# Tracker sessions are bullpens -- BullpenType already has a "Command"
# value) rather than introducing a second, competing Session table.
# CommandPitch is a NEW table rather than an extension of BullpenPitch:
# BullpenPitch.target_zone is the older, coarse 1-9-zone manual-tracking
# design already noted elsewhere in this file as being phased out in
# favor of continuous coordinates -- bolting continuous x/z onto it would
# extend a table on its way out rather than replace it cleanly. The two
# tables coexist for now; a bullpen session can have BullpenPitch rows,
# RapsodoPitch rows, and/or CommandPitch rows depending on which
# tracking workflows were used on it.
# ---------------------------------------------------------------------------

class CommandPitch(Base):
    """One tracked pitch in the Command Tracker -- intended location vs.
    actual location, plus GBO-derived command metrics computed at save
    time from those two points.

    Coordinates (intended_x/z, actual_x/z) are stored in FEET, matching
    the plate_x/plate_z convention already used everywhere else in GBO
    (strike_zone.py, GamePitch.intended_plate_x/z and actual_plate_x/z):
    x = 0 at the center of the plate, z = 0 at the ground. This is
    deliberately the SAME convention as GamePitch's coordinates (not a
    second, competing one) so a future Phase 3 game-tracking integration
    doesn't need any unit translation, and so a future automated Rapsodo
    actual-location match (Phase 3, see rapsodo_conventions.py's existing
    inches->feet conversion) can populate actual_x/z directly.

    intended_x/z are required -- the pitcher/catcher always has *some*
    target in mind, even a chase pitch well outside the zone, so there's
    no meaningful "no intended location" state for a tracked pitch.
    actual_x/z are nullable: Phase 1 enters them manually right after
    intended (see the Command Tracker module's fast-entry workflow), but
    the column allows a pitch to be logged with intent only and its
    actual location filled in later -- the same shape a future automated
    Rapsodo match (Phase 3) will need, without a schema change then.

    horizontal_miss/vertical_miss/miss_distance are stored already
    converted to INCHES (not feet) -- every consumer of these three
    columns (the session scorecard, command-by-pitch-type table, miss-
    bias/miss-direction-distribution reports) only ever wants the inches
    value coaches actually read ("Miss: 4.2 inches"), so the conversion
    happens once at save time rather than at every read site. See
    command_config.py for the target-radius thresholds these and the
    three within_*_target flags are classified against, and
    analytics/command_metrics.py for the actual calculation (miss
    distance, direction -- handedness-aware per Player.throws --  and
    classification), which is intentionally kept separate from this
    model so the math has exactly one implementation.

    source distinguishes how actual_x/z was populated: "manual" (Phase 1,
    a coach/tracker clicked it in) vs. the Phase 3 reserved values
    "rapsodo" / "trackman" / "game_tracking" for future automated
    matching -- external_pitch_id is the corresponding foreign system's
    pitch identifier (e.g. a future match to rapsodo_pitches via its
    rapsodo_unique_id), left NULL for manual entries."""
    __tablename__ = "command_pitches"

    command_pitch_id = Column(Integer, primary_key=True)
    bullpen_id = Column(Integer, ForeignKey("bullpen_sessions.bullpen_id"), nullable=False)
    pitch_number = Column(Integer, nullable=False)  # sequential within the session, same convention as BullpenPitch.pitch_number
    pitch_type_id = Column(Integer, ForeignKey("pitch_types.pitch_type_id"), nullable=True)
    batter_side = Column(String(1), nullable=True)  # 'R' or 'L' -- who the pitch was aimed against, if simulated/specified; optional in Phase 1
    balls = Column(Integer, nullable=True)  # count context at the time of the pitch, optional in Phase 1
    strikes = Column(Integer, nullable=True)

    intended_x = Column(Numeric(5, 3), nullable=False)  # feet, plate-center-at-0 -- see class docstring for convention
    intended_z = Column(Numeric(5, 3), nullable=False)  # feet, ground-at-0
    actual_x = Column(Numeric(5, 3), nullable=True)
    actual_z = Column(Numeric(5, 3), nullable=True)

    # Derived at save time by analytics/command_metrics.py -- never
    # entered directly, so these can't drift from intended/actual above.
    # Inches, not feet -- see class docstring.
    horizontal_miss = Column(Numeric(6, 2), nullable=True)  # actual_x - intended_x, converted to inches (sign preserved -- see command_metrics for the handedness-aware arm-side/glove-side interpretation)
    vertical_miss = Column(Numeric(6, 2), nullable=True)  # actual_z - intended_z, converted to inches (positive = high)
    miss_distance = Column(Numeric(6, 2), nullable=True)  # Euclidean distance, inches
    miss_direction = Column(String(30), nullable=True)  # e.g. "High Arm Side" -- handedness-aware, see command_metrics.classify_miss_direction

    # Target-radius classification against command_config.py's configured
    # thresholds -- nested (Precision inside Command inside Competitive),
    # all three NULL until actual_x/z (and therefore miss_distance) exist.
    within_precision_target = Column(Boolean, nullable=True)
    within_command_target = Column(Boolean, nullable=True)
    within_competitive_target = Column(Boolean, nullable=True)

    pitch_result = Column(String(30), nullable=True)  # e.g. "Ball" / "Strike" / "In Play" -- free-standing outcome, deliberately NOT used as a command metric (see architecture doc's Section 38 principle: command is intent-vs-actual location, not strike/ball)
    velocity = Column(Numeric(6, 2), nullable=True)  # mph, optional for manual tracking

    source = Column(String(20), default="manual", nullable=False)  # "manual" (Phase 1) / "rapsodo" / "trackman" / "game_tracking" (Phase 3, reserved)
    external_pitch_id = Column(String(100), nullable=True)  # foreign system's pitch identifier once Phase 3 automated matching exists; NULL for manual entries

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    bullpen = relationship("BullpenSession", back_populates="command_pitches")
    pitch_type = relationship("PitchType")
