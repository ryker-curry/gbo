"""
GBO -- Assessment bulk-import column spec (Sept 2026).

Single source of truth for which columns the Assessment importer expects
per category, and how each one maps to an AssessmentTestType (or, for a
couple of columns, straight onto the Player record instead of a test
result -- see kind="player_height"/"player_throws" below). This is the
SAME header text as GBO_Assessment_Import_Templates.xlsx (the workbook
already handed to Ryker to fill in) -- if a header here and a header in
that workbook ever drift apart, the importer will treat every column in
that sheet as unmapped, so keep them in lockstep by hand until the
template is generated from this file instead (not done yet).

One category per import (Ryker's explicit call, Sept 2026) -- a single
uploaded sheet is always scoped to exactly one of the lists below, never
several categories mixed together. services/assessment_import.py picks
which list to use from the category name the caller passes in.

kind values, and what services/assessment_import.py does with each:
  "value"          -- plain number -> one AssessmentResult row.
  "ftin_to_in"      -- a "43'10\"" -- style string -> decimal inches ->
                       one AssessmentResult row (Explosive Power's jump
                       distances/heights).
  "ftin_to_ft"      -- same parse, decimal feet instead (Rotational
                       Power's Medicine Ball Shot Put Distance).
  "player_height"   -- a "5'11\"" -- style string -> decimal inches,
                       written to Player.height_in directly. NOT an
                       AssessmentResult -- height is a player attribute,
                       not a per-date test value, and Player.height_in
                       already exists (see models.py), so Body
                       Composition's HT_FT column updates the player's
                       own profile instead of needing a new test type.
  "player_throws"   -- 'R'/'L' -- only ever WRITES Player.throws when
                       that player's throws is currently null (never
                       overwrites an existing value with something the
                       sheet says, since the app already treats
                       Player.throws as the source of truth everywhere
                       else -- see bucket_system.resolve_side_by_throws).
                       NOT an AssessmentResult.
  "unmapped_new"    -- a real column with real values, but no
                       AssessmentTestType exists for it yet. Values here
                       are never stored -- they're counted and reported
                       back in the import preview/result so nothing
                       silently vanishes, same as an entirely unrecognized
                       column (see _build_column_map in assessment_
                       import.py) -- this just also explains WHY it's
                       unmapped instead of leaving it a mystery. As of
                       Sept 2026 no column below actually uses this kind
                       -- the last of the original gaps (Body
                       Composition's Age/BMI/FFMI/TBW/ICW/ECW, Explosive
                       Power's 9 CMJ force-plate metrics, Upper Body
                       Strength's Glove Hand grip test) were closed by
                       adding their AssessmentTestType rows to
                       seed_lookups.py. Left in as a live kind, not
                       removed -- the next real schema gap (Anthropometrics/
                       Baseball Performance/Pitcher-Specific joining this
                       importer, or a future device export with a new
                       field) will need it again.

Every category also always has these three "base" columns, handled
directly by the importer, never through this spec:
    Player First Name, Player Last Name, Assessment Date
"""

from collections import namedtuple

ColumnSpec = namedtuple("ColumnSpec", ["header", "kind", "test_name", "unit"])


def _value_cols(tests):
    """tests: [(test_name, unit), ...] -- most categories are just a
    flat list of plain-number test types, header = "test_name (unit)"
    exactly like the template generator built it."""
    return [ColumnSpec(f"{name} ({unit})", "value", name, unit) for name, unit in tests]


MOBILITY_ROM = _value_cols([
    ("Shoulder: Right External Rotation", "°"), ("Shoulder: Left External Rotation", "°"),
    ("Shoulder: Right Internal Rotation", "°"), ("Shoulder: Left Internal Rotation", "°"),
    ("Shoulder: Right Flexion", "°"), ("Shoulder: Left Flexion", "°"),
    ("Shoulder: Right Extension", "°"), ("Shoulder: Left Extension", "°"),
    ("Elbow: Right Flexion", "°"), ("Elbow: Left Flexion", "°"),
    ("Elbow: Right Extension", "°"), ("Elbow: Left Extension", "°"),
    ("Hip: Right Internal Rotation", "°"), ("Hip: Left Internal Rotation", "°"),
    ("Hip: Right External Rotation", "°"), ("Hip: Left External Rotation", "°"),
    ("Hip: Right Abduction", "°"), ("Hip: Left Abduction", "°"),
    ("Hip: Right Adduction", "°"), ("Hip: Left Adduction", "°"),
    ("Hip: Right Flexion", "°"), ("Hip: Left Flexion", "°"),
    ("Hip: Right Extension", "°"), ("Hip: Left Extension", "°"),
])

ARM_HEALTH = _value_cols([
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
    ("Forearm/Elbow Capacity: FCU Isometric Strength (Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FDS Isometric Strength (Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FCU Isometric Strength (Non-Throwing Arm)", "lbs"),
    ("Forearm/Elbow Capacity: FDS Isometric Strength (Non-Throwing Arm)", "lbs"),
    ("Pain & Readiness: Shoulder Pain", "0-10"), ("Pain & Readiness: Elbow Pain", "0-10"),
    ("Pain & Readiness: Overall Arm Readiness", "0-10"),
    ("Throwing Workload: Daily Throw Count", "throws"), ("Throwing Workload: Bullpen Pitch Count", "pitches"),
    ("Throwing Workload: Game Pitch Count", "pitches"),
])

UPPER_BODY_STRENGTH = _value_cols([
    ("Neutral Grip Chin Up Max External Load", "lbs"),
    ("Neutral Grip/DB Bench Press Max Load", "lbs"),
    ("Grip Strength (Seated, Throwing Hand)", "lbs"),
    # Sept 2026: Glove Hand counterpart added to seed_lookups.py, closing
    # what used to be an "unmapped_new" gap -- header keeps the same text
    # minus the "*NEW* " prefix it had while unmapped.
    ("Grip Strength (Seated, Glove Hand)", "lbs"),
])

LOWER_BODY_STRENGTH = _value_cols([
    ("Hex Bar Deadlift Max", "lbs"), ("Front Squat Max", "lbs"),
    ("Hip Abduction Force (Drive Leg)", "N"), ("Hip Abduction Force (Plant Leg)", "N"),
    ("Hip Adduction Force (Drive Leg)", "N"), ("Hip Adduction Force (Plant Leg)", "N"),
    ("Isometric Mid-Thigh Pull Average Force", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "N"),
    ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", "N"),
])

_FT_IN_UNIT = "ft'in\""

EXPLOSIVE_POWER = [
    ColumnSpec("Vertical Jump (Jump Mat) (in)", "value", "Vertical Jump (Jump Mat)", "in"),
    ColumnSpec(f"Broad Jump Distance ({_FT_IN_UNIT})", "ftin_to_in", "Broad Jump Distance", "in"),
    ColumnSpec(f"Lateral Jump Distance (Drive Leg) ({_FT_IN_UNIT})", "ftin_to_in", "Lateral Jump Distance (Drive Leg)", "in"),
    ColumnSpec(f"Lateral Jump Distance (Plant Leg) ({_FT_IN_UNIT})", "ftin_to_in", "Lateral Jump Distance (Plant Leg)", "in"),
    ColumnSpec("Countermovement Jump Height (in)", "value", "Countermovement Jump Height", "in"),
    ColumnSpec("Countermovement Jump RSI-Modified (ratio)", "value", "Countermovement Jump RSI-Modified", "ratio"),
    ColumnSpec("Countermovement Jump Concentric Duration (ms)", "value", "Countermovement Jump Concentric Duration", "ms"),
    ColumnSpec("Countermovement Jump Concentric Mean Force (N)", "value", "Countermovement Jump Concentric Mean Force", "N"),
    ColumnSpec("Hop Test RSI (10/5) (ratio)", "value", "Hop Test RSI (10/5)", "ratio"),
    ColumnSpec("Hop Test Average Force (N)", "value", "Hop Test Average Force", "N"),
    ColumnSpec("Hop Test Mean Contact Time (ms)", "value", "Hop Test Mean Contact Time", "ms"),
    ColumnSpec(f"Single-Leg Jump Height (Drive Leg) ({_FT_IN_UNIT})", "ftin_to_in", "Single-Leg Jump Height (Drive Leg)", "in"),
    ColumnSpec("Single-Leg Jump Concentric Impulse (Drive Leg) (Ns)", "value", "Single-Leg Jump Concentric Impulse (Drive Leg)", "Ns"),
    ColumnSpec(f"Single-Leg Jump Height (Plant Leg) ({_FT_IN_UNIT})", "ftin_to_in", "Single-Leg Jump Height (Plant Leg)", "in"),
    ColumnSpec("Single-Leg Jump Concentric Impulse (Plant Leg) (Ns)", "value", "Single-Leg Jump Concentric Impulse (Plant Leg)", "Ns"),
    # Sept 2026: the 9 real CMJ force-plate metrics, added to
    # seed_lookups.py -- closing what used to be an "unmapped_new" gap.
    # Headers keep the same text minus the "*NEW* " prefix they had while
    # unmapped, so a sheet already using the old headers just needs that
    # prefix dropped, not a full re-type.
    ColumnSpec("CMJ Bodyweight (kg)", "value", "CMJ Bodyweight", "kg"),
    ColumnSpec("CMJ Concentric Impulse (N s)", "value", "CMJ Concentric Impulse", "N s"),
    ColumnSpec("CMJ Peak Power (W)", "value", "CMJ Peak Power", "W"),
    ColumnSpec("CMJ Concentric Peak Force (N)", "value", "CMJ Concentric Peak Force", "N"),
    ColumnSpec("CMJ Concentric Peak Velocity (m/s)", "value", "CMJ Concentric Peak Velocity", "m/s"),
    ColumnSpec("CMJ Eccentric Duration (ms)", "value", "CMJ Eccentric Duration", "ms"),
    ColumnSpec("CMJ Eccentric Peak Force (N)", "value", "CMJ Eccentric Peak Force", "N"),
    ColumnSpec("CMJ Eccentric Peak Power (W)", "value", "CMJ Eccentric Peak Power", "W"),
    ColumnSpec("CMJ Eccentric Peak Velocity (m/s)", "value", "CMJ Eccentric Peak Velocity", "m/s"),
]

ROTATIONAL_POWER = [
    ColumnSpec(f"Medicine Ball Shot Put Distance ({_FT_IN_UNIT})", "ftin_to_ft", "Medicine Ball Shot Put Distance", "ft"),
    ColumnSpec("Medicine Ball Shot Put Velocity (mph)", "value", "Medicine Ball Shot Put Velocity", "mph"),
]

SPEED = _value_cols([
    ("Top Speed: Flying 10 Sprint Time", "s"),
    ("Acceleration: 10-Yard Sprint Time", "s"),
    ("30-Yard Sprint Time", "s"),
])

BODY_COMPOSITION = [
    ColumnSpec("Handedness", "player_throws", None, None),
    # Sept 2026: all 7 of these used to be "unmapped_new" -- real
    # AssessmentTestType rows now exist for each (see seed_lookups.py),
    # so the header text is unchanged (never had a "*NEW*" prefix to
    # begin with, since these are Ryker's own BC-export column names) and
    # a sheet already using the old template needs no changes at all.
    ColumnSpec("AGE_yrs", "value", "Age", "yrs"),
    ColumnSpec("HT_FT", "player_height", None, _FT_IN_UNIT),
    ColumnSpec("BM_lb", "value", "Body Weight", "lb"),
    ColumnSpec("SMM_lb", "value", "Skeletal Muscle Mass", "lb"),
    ColumnSpec("SMM%", "value", "Skeletal Muscle Mass %", "%"),
    ColumnSpec("BF%", "value", "Percent Body Fat", "%"),
    ColumnSpec("FFM_lb", "value", "Fat-Free Mass", "lb"),
    ColumnSpec("FM_lb", "value", "Body Fat Mass", "lb"),
    ColumnSpec("BMI", "value", "Body Mass Index (BMI)", "kg/m2"),
    ColumnSpec("FFMI", "value", "Fat-Free Mass Index (FFMI)", "kg/m2"),
    ColumnSpec("FMI", "value", "Fat Mass Index (FMI)", "kg/m2"),
    ColumnSpec("SMI", "value", "Skeletal Muscle Index (SMI)", "kg/m2"),
    ColumnSpec("FFM_THROW_ARM", "value", "Fat-Free Mass (Throwing Arm)", "lb"),
    ColumnSpec("FFM_GLOVE_ARM", "value", "Fat-Free Mass (Glove/Non-Throwing Arm)", "lb"),
    ColumnSpec("48. Lean Mass of Trunk", "value", "Trunk Lean Mass", "lb"),
    ColumnSpec("Lean_Mass_Drive_Leg", "value", "Lean Mass (Drive Leg)", "lb"),
    ColumnSpec("Lean_Mass_Plant_Leg", "value", "Lean Mass (Plant Leg)", "lb"),
    ColumnSpec("TBW_lb", "value", "Total Body Water", "lb"),
    ColumnSpec("TBW_%", "value", "Total Body Water %", "%"),
    ColumnSpec("ICW_lb", "value", "Intracellular Water", "lb"),
    ColumnSpec("ECW_lb", "value", "Extracellular Water", "lb"),
    ColumnSpec("ECW/TBW", "value", "ECW/TBW Ratio", "ratio"),
    ColumnSpec("BMR", "value", "Basal Metabolic Rate (BMR)", "kcal"),
    ColumnSpec("REC CAL", "value", "Recommended Caloric Intake", "kcal"),
]

# Category display name (must match AssessmentCategory.category_name
# exactly) -> its column spec list.
CATEGORY_SPECS = {
    "Body Composition": BODY_COMPOSITION,
    "Mobility & ROM": MOBILITY_ROM,
    "Arm Health": ARM_HEALTH,
    "Upper Body Strength": UPPER_BODY_STRENGTH,
    "Lower Body Strength": LOWER_BODY_STRENGTH,
    "Explosive Power": EXPLOSIVE_POWER,
    "Rotational Power": ROTATIONAL_POWER,
    "Speed": SPEED,
}

BASE_COLUMNS = ["Player First Name", "Player Last Name", "Assessment Date"]
