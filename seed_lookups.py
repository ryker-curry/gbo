"""
GBO — Seed lookup tables.

Run after init_db.py creates the schema. Safe to re-run: each seed function
checks for existing rows before inserting.
"""

from database import get_session
from models import (
    Role, AssessmentCategory, AssessmentTestType, IDPStatus, SessionType,
    PlayerStatus, PlayerClass, Position, PitchType, TeamEventType, BullpenType, HitterSessionType,
)


def seed_roles(session):
    if session.query(Role).count() > 0:
        return
    roles = [
        Role(role_name="Administrator", description="Full access to users, roles, teams, players, all data and settings.",
             can_edit_assessments=True, can_edit_idp=True, can_edit_sessions=True, can_view_all_players=True, is_admin=True),
        # Head Coach and Coach are view-only for Assessments, Video Import,
        # and Rapsodo/Bullpen/Hitter Tracking (can_edit_assessments/
        # can_edit_sessions both False) -- Ryker's explicit call: the
        # Administrator is the only one who enters that data, coaching
        # staff just view results. IDP editing (can_edit_idp) is
        # unaffected -- coaches still manage IDP goals/action steps, only
        # the raw assessment/session/video DATA ENTRY is Administrator-only.
        Role(role_name="Head Coach", description="All players, all assessments/IDPs/reports/team dashboard -- view-only on assessments, sessions (Rapsodo/Bullpen/Hitter Tracking), and video; can still manage IDP goals.",
             can_edit_assessments=False, can_edit_idp=True, can_edit_sessions=False, can_view_all_players=True),
        Role(role_name="Coach", description="Assigned players only -- view-only on assessments, sessions (Rapsodo/Bullpen/Hitter Tracking), and video; can still manage IDP goals/reports.",
             can_edit_assessments=False, can_edit_idp=True, can_edit_sessions=False, can_view_all_players=False),
        Role(role_name="Strength Coach", description="Assessments, sessions, and IDP -- edit rights.",
             can_edit_assessments=True, can_edit_idp=True, can_edit_sessions=True, can_view_all_players=True),
        Role(role_name="Athletic Trainer", description="Assessments, sessions, and IDP progress notes -- edit rights.",
             can_edit_assessments=True, can_edit_idp=True, can_edit_sessions=True, can_view_all_players=True),
        Role(role_name="Sports Scientist", description="Assessment data (manual entry + Rapsodo import) and video upload -- edit rights. Sessions/IDP -- read-only.",
             can_edit_assessments=True, can_edit_idp=False, can_edit_sessions=False, can_view_all_players=True),
        Role(role_name="Data Analyst", description="Assessment and analytics data -- edit rights.",
             can_edit_assessments=True, can_edit_idp=False, can_edit_sessions=False, can_view_all_players=True),
        Role(role_name="Player", description="Own profile, assessments, IDP, and sessions only.",
             can_edit_assessments=False, can_edit_idp=False, can_edit_sessions=False, can_view_all_players=False),
    ]
    session.add_all(roles)
    session.commit()
    print(f"Seeded {len(roles)} roles.")


# The 11 real assessment categories, per Ryker's Master Player Profile
# Data Dictionary (PLAYER_PROFILE.xlsx). Anthropometrics and Body
# Composition have real test types (below); the rest are still headers
# only in Ryker's document, pending his protocol details.
ASSESSMENT_CATEGORIES = [
    ("Anthropometrics", True, 1),
    ("Body Composition", True, 2),
    ("Mobility & ROM", True, 3),
    ("Arm Health", True, 4),
    ("Upper Body Strength", True, 5),
    ("Lower Body Strength", True, 6),
    ("Explosive Power", True, 7),
    ("Rotational Power", True, 8),
    ("Speed", True, 9),
    ("Baseball Performance", True, 10),
    ("Pitcher-Specific", False, 11),
]

# (test_name, unit) -- from Ryker's fully-populated Anthropometrics sheet
ANTHROPOMETRICS_TESTS = [
    ("Standing Height", "in"), ("Seated Height", "in"), ("Wing Span", "in"),
    ("Throwing Arm Length", "in"), ("Non-Throwing Arm Length", "in"),
    ("Throwing Forearm Length", "in"), ("Non-Throwing Forearm Length", "in"),
    ("Throwing Hand Length", "in"), ("Non-Throwing Hand Length", "in"),
    ("Shoulder Width", "in"), ("Torso Length", "in"), ("Hip Width", "in"),
    ("Right Femur Length", "in"), ("Left Femur Length", "in"),
    ("Right Tibia Length", "in"), ("Left Tibia Length", "in"),
    ("Right Foot Length", "in"), ("Left Foot Length", "in"),
]

# (test_name, unit) -- from Ryker's fully-populated Body Composition (InBody770) sheet
BODY_COMPOSITION_TESTS = [
    ("Body Weight", "lb"), ("Body Fat Mass", "lb"), ("Skeletal Muscle Mass", "lb"),
    ("Percent Body Fat", "%"), ("Skeletal Muscle Mass %", "%"), ("Fat-Free Mass", "lb"),
    ("Fat Mass Index (FMI)", "kg/m2"), ("Skeletal Muscle Index (SMI)", "kg/m2"),
    ("ECW/TBW Ratio", "ratio"), ("Throwing Arm Lean Mass", "lb"),
    ("Non-Throwing Arm Lean Mass", "lb"), ("Trunk Lean Mass", "lb"),
    ("Right Leg Lean Mass", "lb"), ("Left Leg Lean Mass", "lb"),
    ("Throwing Arm Fat Mass", "lb"), ("Non-Throwing Arm Fat Mass", "lb"),
    ("Trunk Fat Mass", "lb"), ("Right Leg Fat Mass", "lb"), ("Left Leg Fat Mass", "lb"),
]

# (test_name, unit) -- pruned down to exactly what's actually measured
# (Aug 2026, per Ryker's explicit correction): Shoulder ER/IR/Flexion/
# Extension, Elbow Flexion/Extension, and the full Hip block -- all
# entered as Right/Left (Shoulder/Elbow) or Drive Leg/Plant Leg (Hip)
# pairs. The original draft of this sheet also had Cervical Spine,
# Elbow Pronation/Supination, T-Spine, Lumbar Spine, and Ankle -- those
# were things Ryker intended to measure but never actually collected,
# so they're removed here rather than sitting on the entry form as
# permanently-empty fields. Shoulder Total Arc and GIRD were also on
# the original sheet as manual-entry fields, but per Ryker's call
# neither should ever be typed in at all -- both are auto-calculated
# live from the ER/IR values below instead (both computed inside
# compute_mobility_rom_report in bucket_system.py), so they're removed
# from this manual-entry list entirely, not just left empty. Note:
# Mobility & ROM is checked pass/fail against a fixed threshold now,
# not percentile-ranked against the team -- see MOBILITY_ROM_
# THRESHOLDS in bucket_system.py for the current design.
MOBILITY_ROM_TESTS = [
    ("Shoulder: Right External Rotation", "°"), ("Shoulder: Left External Rotation", "°"),
    ("Shoulder: Right Internal Rotation", "°"), ("Shoulder: Left Internal Rotation", "°"),
    ("Shoulder: Right Flexion", "°"), ("Shoulder: Left Flexion", "°"),
    ("Shoulder: Right Extension", "°"), ("Shoulder: Left Extension", "°"),
    ("Elbow: Flexion", "°"), ("Elbow: Extension", "°"),
    ("Hip: Drive Leg Internal Rotation", "°"), ("Hip: Drive Leg External Rotation", "°"),
    ("Hip: Plant Leg Internal Rotation", "°"), ("Hip: Plant Leg External Rotation", "°"),
    ("Hip: Drive Leg Abduction", "°"), ("Hip: Plant Leg Abduction", "°"),
    ("Hip: Drive Leg Adduction", "°"), ("Hip: Plant Leg Adduction", "°"),
    ("Hip: Drive Leg Flexion", "°"), ("Hip: Plant Leg Flexion", "°"),
    ("Hip: Drive Leg Extension", "°"), ("Hip: Plant Leg Extension", "°"),
]

# (test_name, unit) -- from Ryker's fully-populated Arm Health sheet.
# "Weekly Throw Count" and "Days Since Last Appearance" are excluded --
# both are system-computed rolling aggregates (not values read off any
# device), so they belong on a future dashboard, not a manual entry form.
ARM_HEALTH_TESTS = [
    ("Shoulder ROM: Throwing Arm External Rotation", "°"), ("Shoulder ROM: Throwing Arm Internal Rotation", "°"),
    ("Shoulder ROM: Throwing Arm Total Arc", "°"), ("Shoulder ROM: Non-Throwing Arm External Rotation", "°"),
    ("Shoulder ROM: Non-Throwing Arm Internal Rotation", "°"), ("Shoulder ROM: Non-Throwing Arm Total Arc", "°"),
    ("Shoulder ROM: GIRD", "°"), ("Shoulder ROM: Flexion", "°"), ("Shoulder ROM: Extension", "°"),
    ("Shoulder Strength: Throwing Arm ER Peak Force", "lbs"), ("Shoulder Strength: Throwing Arm IR Peak Force", "lbs"),
    ("Shoulder Strength: Throwing Arm ER:IR Ratio", "ratio"),
    ("Shoulder Strength: Non-Throwing Arm ER Peak Force", "lbs"), ("Shoulder Strength: Non-Throwing Arm IR Peak Force", "lbs"),
    ("Shoulder Strength: Non-Throwing Arm ER:IR Ratio", "ratio"),
    ("Shoulder Strength: I Position Peak Force", "lbs"), ("Shoulder Strength: Y Position Peak Force", "lbs"),
    ("Shoulder Strength: T Position Peak Force", "lbs"),
    ("Elbow ROM: Flexion", "°"), ("Elbow ROM: Extension", "°"), ("Elbow ROM: Pronation", "°"), ("Elbow ROM: Supination", "°"),
    ("Grip Strength: Throwing Hand Grip Strength", "lbs"), ("Grip Strength: Non-Throwing Hand Grip Strength", "lbs"),
    # New for the Physical Development / Capacity work -- isolated
    # wrist-flexion/ulnar-deviation dynamometry, distinct from the
    # compound Grip Strength tests above. Framed as forearm/elbow
    # capacity metrics, not an injury predictor, per Ryker's explicit
    # call (see the design brief) -- current research shows FCU/FDS
    # contribute to varus stress-shielding of the UCL mechanistically,
    # but there's no validated individual risk threshold yet.
    ("Forearm/Elbow Capacity: FCU Isometric Strength (Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FDS Isometric Strength (Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FCU Isometric Strength (Non-Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FDS Isometric Strength (Non-Throwing Arm)", "lbs"),
    ("Pain & Readiness: Shoulder Pain", "0-10"), ("Pain & Readiness: Elbow Pain", "0-10"),
    ("Pain & Readiness: Overall Arm Readiness", "0-10"),
    ("Throwing Workload: Daily Throw Count", "throws"), ("Throwing Workload: Bullpen Pitch Count", "pitches"),
    ("Throwing Workload: Game Pitch Count", "pitches"),
]

# (test_name, unit) -- from Ryker's fully-populated Upper Body Strength sheet
# (test_name, unit) -- matches Ryker's bucket-system spreadsheet exactly
# (raw metrics only, DRIVE/PLANT leg framing per the spreadsheet, units as
# given there -- not GBO's earlier framing/units for the tests this replaces)
UPPER_BODY_STRENGTH_TESTS = [
    ("Neutral Grip Chin Up Max External Load", "lbs"),
    ("Neutral Grip/DB Bench Press Max Load", "lbs"),
    ("Grip Strength (Seated, Throwing Hand)", "lbs"),
]

# (test_name, unit) -- matches Ryker's bucket-system spreadsheet exactly
LOWER_BODY_STRENGTH_TESTS = [
    ("Hex Bar Deadlift Max", "lbs"), ("Front Squat Max", "lbs"),
    ("Hip Abduction Force (Drive Leg)", "N"), ("Hip Abduction Force (Plant Leg)", "N"),
    ("Hip Adduction Force (Drive Leg)", "N"), ("Hip Adduction Force (Plant Leg)", "N"),
    ("Isometric Mid-Thigh Pull Average Force", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", "N"),
]

# (test_name, unit) -- matches Ryker's bucket-system spreadsheet exactly
EXPLOSIVE_POWER_TESTS = [
    ("Vertical Jump (Jump Mat)", "in"),
    ("Broad Jump Distance", "ft"),
    ("Lateral Jump Distance (Drive Leg)", "ft"), ("Lateral Jump Distance (Plant Leg)", "ft"),
    ("Countermovement Jump Height", "in"),
    ("Countermovement Jump RSI-Modified", "ratio"),
    ("Countermovement Jump Concentric Duration", "ms"),
    ("Countermovement Jump Concentric Mean Force", "N"),
    ("Hop Test RSI (10/5)", "ratio"),
    ("Hop Test Average Force", "N"),
    ("Hop Test Mean Contact Time", "ms"),
    ("Single-Leg Jump Height (Drive Leg)", "in"), ("Single-Leg Jump Concentric Impulse (Drive Leg)", "Ns"),
    ("Single-Leg Jump Height (Plant Leg)", "in"), ("Single-Leg Jump Concentric Impulse (Plant Leg)", "Ns"),
]

# (test_name, unit) -- matches Ryker's bucket-system spreadsheet exactly
ROTATIONAL_POWER_TESTS = [
    ("Medicine Ball Shot Put Distance", "ft"),
]

# (test_name, unit) -- from Ryker's fully-populated Speed sheet, already
# matches the bucket-system spreadsheet exactly (10y accel / 10y fly).
# 20-Yard Sprint Time and Maximum Sprint Velocity aren't in the bucket
# spreadsheet, so per Ryker's rule they're excluded here too.
SPEED_TESTS = [
    ("Top Speed: Flying 10 Sprint Time", "s"),
    ("Acceleration: 10-Yard Sprint Time", "s"),
]

# (test_name, unit) -- from Ryker's fully-populated Pitch Characteristics
# sheet (Rapsodo 2.0). "Pitch Type" is excluded here -- it's categorical
# text (4-Seam Fastball, Slider, etc.), not a numeric measurement, so it's
# a dropdown on the assessment record itself (Assessment.pitch_type_id),
# not a row in this numeric test-value table. Spin Axis is stored as
# plain degrees (0-360) rather than clock format, per Ryker's decision.
PITCHER_SPECIFIC_TESTS = [
    ("Velocity", "mph"), ("Spin Rate", "rpm"), ("Spin Efficiency", "%"), ("Spin Axis", "°"),
    ("Horizontal Break", "in"), ("Induced Vertical Break", "in"),
    ("Release Height", "ft"), ("Release Side", "ft"), ("Extension", "ft"),
    ("Vertical Approach Angle", "°"), ("Horizontal Approach Angle", "°"),
    ("Plate Height", "ft"), ("Plate Side", "ft"),
]


def seed_assessment_categories_and_tests(session):
    existing = {c.category_name: c for c in session.query(AssessmentCategory).all()}

    for name, is_universal, order in ASSESSMENT_CATEGORIES:
        if name not in existing:
            cat = AssessmentCategory(category_name=name, is_universal=is_universal, display_order=order)
            session.add(cat)
            session.flush()
            existing[name] = cat
    session.commit()
    print(f"Ensured {len(ASSESSMENT_CATEGORIES)} assessment categories exist.")

    def seed_tests(category_name, tests):
        cat = existing[category_name]
        already = {t.test_name for t in session.query(AssessmentTestType).filter(AssessmentTestType.category_id == cat.category_id).all()}
        added = 0
        for i, (test_name, unit) in enumerate(tests, start=1):
            if test_name not in already:
                session.add(AssessmentTestType(category_id=cat.category_id, test_name=test_name, unit=unit, display_order=i))
                added += 1
        session.commit()
        if added:
            print(f"Seeded {added} test types for {category_name}.")

    seed_tests("Anthropometrics", ANTHROPOMETRICS_TESTS)
    seed_tests("Body Composition", BODY_COMPOSITION_TESTS)
    seed_tests("Mobility & ROM", MOBILITY_ROM_TESTS)
    seed_tests("Arm Health", ARM_HEALTH_TESTS)
    seed_tests("Upper Body Strength", UPPER_BODY_STRENGTH_TESTS)
    seed_tests("Lower Body Strength", LOWER_BODY_STRENGTH_TESTS)
    seed_tests("Explosive Power", EXPLOSIVE_POWER_TESTS)
    seed_tests("Rotational Power", ROTATIONAL_POWER_TESTS)
    seed_tests("Speed", SPEED_TESTS)
    seed_tests("Pitcher-Specific", PITCHER_SPECIFIC_TESTS)
    print(
        "NOTE: Baseball Performance has no data in the spreadsheet -- "
        "confirm whether to drop it or keep as a placeholder."
    )


def seed_pitch_types(session):
    """"Fastball" (generic/undifferentiated) is its own type, distinct
    from "4-Seam Fastball" -- Rapsodo's auto-classifier often doesn't
    distinguish 2-seam from 4-seam and just reports "Fastball". See
    pitch_type_config.py for the full raw-label -> canonical-type mapping
    used at Rapsodo import time."""
    if session.query(PitchType).count() > 0:
        return
    types = [
        PitchType(type_name="Fastball", display_order=0),
        PitchType(type_name="4-Seam Fastball", display_order=1),
        PitchType(type_name="2-Seam Fastball", display_order=2),
        PitchType(type_name="Cutter", display_order=3),
        PitchType(type_name="Slider", display_order=4),
        PitchType(type_name="Changeup", display_order=5),
        PitchType(type_name="Curveball", display_order=6),
        PitchType(type_name="Splitter", display_order=7),
    ]
    session.add_all(types)
    session.commit()
    print(f"Seeded {len(types)} pitch types.")


def seed_idp_statuses(session):
    if session.query(IDPStatus).count() > 0:
        return
    # PLACEHOLDER -- confirm these with Ryker before the Aug 7-13 IDP build window.
    statuses = [
        IDPStatus(status_name="Not Started", display_order=1),
        IDPStatus(status_name="In Progress", display_order=2),
        IDPStatus(status_name="Completed", display_order=3),
        IDPStatus(status_name="On Hold", display_order=4),
    ]
    session.add_all(statuses)
    session.commit()
    print(f"Seeded {len(statuses)} IDP statuses (PLACEHOLDER -- confirm naming with Ryker).")


def seed_session_types(session):
    if session.query(SessionType).count() > 0:
        return
    types = [
        SessionType(type_name="Arm Care", display_order=1),
        SessionType(type_name="Mobility", display_order=2),
        SessionType(type_name="Conditioning", display_order=3),
        SessionType(type_name="Lifting", display_order=4),
        SessionType(type_name="Hitting Drills", display_order=5),
        SessionType(type_name="Throwing", display_order=6),
        SessionType(type_name="Plyos", display_order=7),
        SessionType(type_name="Mechanical Work", display_order=8),
        SessionType(type_name="Med Ball", display_order=9),
        SessionType(type_name="Bullpen", display_order=10),
        SessionType(type_name="General", display_order=11),
    ]
    session.add_all(types)
    session.commit()
    print(f"Seeded {len(types)} session types.")


def seed_player_statuses(session):
    if session.query(PlayerStatus).count() > 0:
        return
    # PLACEHOLDER -- confirm the exact status list with Ryker.
    statuses = [
        PlayerStatus(status_name="Active", display_order=1),
        PlayerStatus(status_name="Injured", display_order=2),
        PlayerStatus(status_name="Redshirt", display_order=3),
        PlayerStatus(status_name="Medical Hold", display_order=4),
        PlayerStatus(status_name="Inactive", display_order=5),
    ]
    session.add_all(statuses)
    session.commit()
    print(f"Seeded {len(statuses)} player statuses (PLACEHOLDER -- confirm naming with Ryker).")


def seed_player_classes(session):
    if session.query(PlayerClass).count() > 0:
        return
    classes = [
        PlayerClass(class_name="Freshman", display_order=1),
        PlayerClass(class_name="Redshirt Freshman", display_order=2),
        PlayerClass(class_name="Sophomore", display_order=3),
        PlayerClass(class_name="Redshirt Sophomore", display_order=4),
        PlayerClass(class_name="Junior", display_order=5),
        PlayerClass(class_name="Redshirt Junior", display_order=6),
        PlayerClass(class_name="Senior", display_order=7),
        PlayerClass(class_name="Redshirt Senior", display_order=8),
        PlayerClass(class_name="Graduate", display_order=9),
    ]
    session.add_all(classes)
    session.commit()
    print(f"Seeded {len(classes)} player classes.")


def seed_positions(session):
    if session.query(Position).count() > 0:
        return
    positions = [
        Position(position_name="RHP", display_order=1),
        Position(position_name="LHP", display_order=2),
        Position(position_name="C", display_order=3),
        Position(position_name="1B", display_order=4),
        Position(position_name="2B", display_order=5),
        Position(position_name="3B", display_order=6),
        Position(position_name="SS", display_order=7),
        Position(position_name="LF", display_order=8),
        Position(position_name="CF", display_order=9),
        Position(position_name="RF", display_order=10),
        Position(position_name="DH", display_order=11),
        Position(position_name="UTL", display_order=12),
    ]
    session.add_all(positions)
    session.commit()
    print(f"Seeded {len(positions)} positions.")


def seed_team_event_types(session):
    if session.query(TeamEventType).count() > 0:
        return
    types = [
        TeamEventType(type_name="Lift", display_order=1),
        TeamEventType(type_name="Practice", display_order=2),
        TeamEventType(type_name="Game", display_order=3),
        TeamEventType(type_name="Other", display_order=4),
    ]
    session.add_all(types)
    session.commit()
    print(f"Seeded {len(types)} team event types.")


def seed_bullpen_types(session):
    """8-value list per the Rapsodo Bullpen Analytics spec (replaces the
    original 5-value list: High Intent Velo, Pitch Design, Execution
    Focused, Touch and Feel, Short Box -- see migrate_rapsodo_bullpen.py
    for the data migration that remaps any EXISTING database's rows onto
    these new names; this function only seeds a brand-new database)."""
    if session.query(BullpenType).count() > 0:
        return
    types = [
        BullpenType(type_name="Standard Bullpen", display_order=1),
        BullpenType(type_name="Pitch Design", display_order=2),
        BullpenType(type_name="Command", display_order=3),
        BullpenType(type_name="Velocity", display_order=4),
        BullpenType(type_name="Recovery", display_order=5),
        BullpenType(type_name="Live BP", display_order=6),
        BullpenType(type_name="Assessment", display_order=7),
        BullpenType(type_name="Other", display_order=8),
    ]
    session.add_all(types)
    session.commit()
    print(f"Seeded {len(types)} bullpen types.")


def seed_hitter_session_types(session):
    if session.query(HitterSessionType).count() > 0:
        return
    types = [
        HitterSessionType(type_name="Live ABs", display_order=1),
        HitterSessionType(type_name="Batting Practice", display_order=2),
        HitterSessionType(type_name="Intersquad", display_order=3),
        HitterSessionType(type_name="Scrimmage", display_order=4),
        HitterSessionType(type_name="Game", display_order=5),
    ]
    session.add_all(types)
    session.commit()
    print(f"Seeded {len(types)} hitter session types.")


def run_all_seeds():
    session = get_session()
    try:
        seed_roles(session)
        seed_assessment_categories_and_tests(session)
        seed_idp_statuses(session)
        seed_session_types(session)
        seed_player_statuses(session)
        seed_player_classes(session)
        seed_positions(session)
        seed_pitch_types(session)
        seed_team_event_types(session)
        seed_bullpen_types(session)
        seed_hitter_session_types(session)
    finally:
        session.close()


if __name__ == "__main__":
    run_all_seeds()