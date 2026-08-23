"""
GBO — Command Tracker: intended-vs-actual command calculations.

Pure data logic -- no Streamlit/Shiny, no database queries of its own.
Same separation analytics/bullpen_metrics.py already follows: every
function here either (a) takes plain intended/actual coordinates and
returns the derived per-pitch fields to save onto a CommandPitch row, or
(b) takes a list of already-loaded CommandPitch ORM objects (the
caller/module is responsible for querying/filtering by bullpen_id,
joinedload-ing .pitch_type, etc.) and returns plain dicts/lists a page
can render however it wants.

Two layers:
  1. Per-pitch (compute_miss, classify_miss_direction,
     compute_command_pitch_fields) -- called ONCE, at save time, by the
     Command Tracker module. These are what actually populate
     CommandPitch.horizontal_miss/vertical_miss/miss_distance/
     miss_direction/within_*_target -- never recomputed on every read,
     per the CommandPitch docstring in models.py.
  2. Aggregate (session_command_scorecard, command_by_pitch_type,
     miss_bias, miss_direction_distribution, individual_pitch_rows) --
     read those already-stored fields back off a list of CommandPitch
     rows to build the reports in the architecture doc's Sections 11-16
     and 21. These never recompute miss_distance/direction themselves --
     single source of truth stays layer 1.

Handedness (arm-side vs. glove-side) convention -- ported from the
existing get_zone_labels() in shiny_app/modules/bullpen_tracking.py so
Command Tracker agrees with the rest of GBO rather than inventing a
second convention: in GBO's plate_x coordinate system (0 = center,
matching strike_zone.py/GamePitch), the NEGATIVE-x side is Arm Side for
a RHP (Player.throws == "R") and Glove Side for a LHP; the POSITIVE-x
side is the reverse. A pitch with unknown/missing throws falls back to
plain "Left"/"Right" labels, same as get_zone_labels() does.
"""

import math
from statistics import mean, median, stdev

import command_config

FEET_TO_INCHES = 12.0

HIGH_LABEL = "High"
LOW_LABEL = "Low"
ARM_SIDE_LABEL = "Arm Side"
GLOVE_SIDE_LABEL = "Glove Side"
LEFT_LABEL = "Left"
RIGHT_LABEL = "Right"
ON_TARGET_LABEL = "On Target"


# ---------------------------------------------------------------------------
# Layer 1: per-pitch calculation -- called once, at save time
# ---------------------------------------------------------------------------

def compute_miss(intended_x, intended_z, actual_x, actual_z):
    """Section 8: horizontal miss, vertical miss, and Euclidean miss
    distance -- all converted to INCHES (intended_x/z and actual_x/z
    themselves are in feet, GBO's usual plate_x/plate_z convention; see
    command_config.py's module docstring for why the derived miss values
    are stored in inches instead).

    horizontal_miss = (actual_x - intended_x) * 12, sign preserved
    (RAW plate-coordinate direction, NOT yet handedness-adjusted -- see
    classify_miss_direction for the arm-side/glove-side interpretation
    of this sign). vertical_miss = (actual_z - intended_z) * 12,
    positive = high, negative = low.

    Returns (horizontal_miss_in, vertical_miss_in, miss_distance_in), or
    (None, None, None) if any of the four inputs is None (most commonly:
    actual_x/z not entered yet -- a pitch tracked with intent only)."""
    if intended_x is None or intended_z is None or actual_x is None or actual_z is None:
        return None, None, None
    horizontal_miss_in = round((float(actual_x) - float(intended_x)) * FEET_TO_INCHES, 2)
    vertical_miss_in = round((float(actual_z) - float(intended_z)) * FEET_TO_INCHES, 2)
    miss_distance_in = round(math.hypot(horizontal_miss_in, vertical_miss_in), 2)
    return horizontal_miss_in, vertical_miss_in, miss_distance_in


def classify_miss_direction(horizontal_miss_in, vertical_miss_in, throws):
    """Section 9: handedness-aware miss direction label -- one of High,
    Low, Arm Side, Glove Side, High Arm Side, High Glove Side, Low Arm
    Side, Low Glove Side, or (an addition beyond the spec's 8, for a
    pitch that landed essentially exactly on its target on both axes,
    per command_config.MISS_DIRECTION_DEADZONE_IN) "On Target".

    throws: Player.throws, "R" / "L" / None. See module docstring for
    the sign convention this matches. Unknown throws falls back to
    plain Left/Right (no arm-side concept without knowing the pitcher's
    hand), same fallback shiny_app/modules/bullpen_tracking.py's
    get_zone_labels() already uses.

    Returns None if either miss value is None (no actual location yet)."""
    if horizontal_miss_in is None or vertical_miss_in is None:
        return None
    h = float(horizontal_miss_in)
    v = float(vertical_miss_in)
    dz = command_config.MISS_DIRECTION_DEADZONE_IN

    vertical_label = None
    if v >= dz:
        vertical_label = HIGH_LABEL
    elif v <= -dz:
        vertical_label = LOW_LABEL

    horizontal_label = None
    if abs(h) >= dz:
        if throws == "R":
            horizontal_label = GLOVE_SIDE_LABEL if h > 0 else ARM_SIDE_LABEL
        elif throws == "L":
            horizontal_label = ARM_SIDE_LABEL if h > 0 else GLOVE_SIDE_LABEL
        else:
            horizontal_label = RIGHT_LABEL if h > 0 else LEFT_LABEL

    if vertical_label and horizontal_label:
        return f"{vertical_label} {horizontal_label}"
    return vertical_label or horizontal_label or ON_TARGET_LABEL


def compute_command_pitch_fields(intended_x, intended_z, actual_x, actual_z, throws):
    """The one function the Command Tracker module should call at save
    time -- bundles compute_miss + classify_miss_direction +
    command_config.target_flags into the exact set of derived columns
    CommandPitch needs (Sections 8, 9, 10 in one pass). Returns a dict
    ready to spread into CommandPitch(**intended_and_actual_fields,
    **compute_command_pitch_fields(...)):

        horizontal_miss, vertical_miss, miss_distance, miss_direction,
        within_precision_target, within_command_target,
        within_competitive_target

    All values are None (rather than raising) if actual_x/actual_z
    aren't known yet -- a pitch can be saved with intent only."""
    horizontal_miss_in, vertical_miss_in, miss_distance_in = compute_miss(intended_x, intended_z, actual_x, actual_z)
    miss_direction = classify_miss_direction(horizontal_miss_in, vertical_miss_in, throws)
    within_precision, within_command, within_competitive = command_config.target_flags(miss_distance_in)
    return {
        "horizontal_miss": horizontal_miss_in,
        "vertical_miss": vertical_miss_in,
        "miss_distance": miss_distance_in,
        "miss_direction": miss_direction,
        "within_precision_target": within_precision,
        "within_command_target": within_command,
        "within_competitive_target": within_competitive,
    }


def normalize_horizontal_to_arm_side(horizontal_miss_in, throws):
    """Flips horizontal_miss's sign (if needed) so the RETURNED value is
    always positive = arm side, negative = glove side, regardless of
    pitcher handedness -- used only by miss_bias() below, where an
    aggregate signed average needs one consistent sign convention across
    a whole session/pitch-type group rather than per-pitch labels.
    Unknown throws is treated as "R" for this flip (there's no real
    arm-side concept without a known hand -- see classify_miss_direction
    -- but a bias NUMBER still needs some consistent sign to average;
    prefer miss_direction_distribution's Left/Right-labeled pitches
    instead of this function when throws is genuinely unknown)."""
    if horizontal_miss_in is None:
        return None
    horizontal_miss_in = float(horizontal_miss_in)
    return horizontal_miss_in if throws == "L" else -horizontal_miss_in


# ---------------------------------------------------------------------------
# Small local stats helpers -- None-filtering, same pattern as
# analytics/bullpen_metrics.py's _avg().
# ---------------------------------------------------------------------------

def _avg(values):
    vals = [float(v) for v in values if v is not None]
    return round(mean(vals), 2) if vals else None


def _med(values):
    vals = [float(v) for v in values if v is not None]
    return round(median(vals), 2) if vals else None


def _sd(values):
    vals = [float(v) for v in values if v is not None]
    return round(stdev(vals), 2) if len(vals) >= 2 else None


def _pct_true(flags):
    vals = [f for f in flags if f is not None]
    return round(sum(1 for f in vals if f) / len(vals) * 100, 1) if vals else None


def _pct_false(flags):
    vals = [f for f in flags if f is not None]
    return round(sum(1 for f in vals if not f) / len(vals) * 100, 1) if vals else None


def _located(pitches):
    """Pitches with a recorded actual location (miss_distance is only
    ever set once actual_x/z exist -- see compute_miss). Every aggregate
    below excludes intent-only pitches from its percentages/averages
    rather than silently treating a missing actual as a zero miss."""
    return [p for p in pitches if p.miss_distance is not None]


def pitch_type_label(pitch):
    """Display name for a pitch's type. Public -- pages group individual
    pitches by this same label to match command_by_pitch_type's rows."""
    return pitch.pitch_type.type_name if pitch.pitch_type is not None else "Unspecified"


class _GamePitchCommandView:
    """Lightweight duck-typed stand-in for a CommandPitch row, built from
    a GamePitch's own intended_plate_x/z/actual_plate_x/z columns -- lets
    real game pitches feed every aggregate function below (and
    visualizations/command_charts.py's command_chart()) exactly the way
    a bullpen session's real CommandPitch rows do, with NO second,
    parallel implementation of the miss/direction/target-band math and
    NO CommandPitch schema change or mirrored rows. Attribute names
    deliberately mirror CommandPitch's own column names 1:1 so every
    consumer below stays completely unaware of the difference."""
    __slots__ = (
        "pitch_number", "pitch_type", "intended_x", "intended_z",
        "actual_x", "actual_z", "horizontal_miss", "vertical_miss",
        "miss_distance", "miss_direction",
        "within_precision_target", "within_command_target", "within_competitive_target",
    )

    def __init__(self, game_pitch, throws):
        p = game_pitch
        self.pitch_number = p.pitch_sequence
        self.pitch_type = p.pitch_type
        self.intended_x = p.intended_plate_x
        self.intended_z = p.intended_plate_z
        self.actual_x = p.actual_plate_x
        self.actual_z = p.actual_plate_z
        derived = compute_command_pitch_fields(p.intended_plate_x, p.intended_plate_z, p.actual_plate_x, p.actual_plate_z, throws)
        for field_name, field_value in derived.items():
            setattr(self, field_name, field_value)


def game_pitches_command_view(game_pitches, throws):
    """Wrap a list of GamePitch ORM objects as command-view objects,
    ready to pass straight into session_command_scorecard/miss_bias/
    miss_direction_distribution/command_by_pitch_type/
    individual_pitch_rows above, and into
    visualizations/command_charts.py's command_chart(). Pitches with no
    intended location at all (a real external opponent's pitcher, whose
    intent GBO never captures -- see game_tracking.py's show_intended)
    are silently excluded here, same as this module's own docstring:
    command is fundamentally an intent-vs-actual comparison, not
    computable without a known intent."""
    return [_GamePitchCommandView(p, throws) for p in game_pitches if p.intended_plate_x is not None]


# ---------------------------------------------------------------------------
# Layer 2: aggregate reports -- read already-stored CommandPitch fields
# ---------------------------------------------------------------------------

def session_command_scorecard(pitches):
    """Section 21's Session Command Scorecard. total_pitches counts
    every tracked pitch (including any still awaiting an actual
    location); every percentage/average below is computed only over
    located_pitches (has an actual location), same as every other
    aggregate in this module.

    Deliberately does NOT compute a composite "Command Score" -- Section
    21 is explicit that GBO shows objective measurements for now, not an
    invented composite, until there's enough organizational data for a
    validated Command+ model."""
    located = _located(pitches)
    n = len(located)
    return {
        "total_pitches": len(pitches),
        "located_pitches": n,
        "avg_miss_distance": _avg([p.miss_distance for p in located]) if n else None,
        "median_miss_distance": _med([p.miss_distance for p in located]) if n else None,
        "precision_pct": _pct_true([p.within_precision_target for p in located]) if n else None,
        "command_target_pct": _pct_true([p.within_command_target for p in located]) if n else None,
        "competitive_pct": _pct_true([p.within_competitive_target for p in located]) if n else None,
        "major_miss_pct": _pct_false([p.within_competitive_target for p in located]) if n else None,
        "horizontal_command_mean_abs": _avg([abs(p.horizontal_miss) for p in located]) if n else None,
        "horizontal_command_stdev": _sd([p.horizontal_miss for p in located]) if n else None,
        "vertical_command_mean_abs": _avg([abs(p.vertical_miss) for p in located]) if n else None,
        "vertical_command_stdev": _sd([p.vertical_miss for p in located]) if n else None,
    }


def miss_bias(pitches, throws):
    """Section 14: Average Miss Bias -- the SIGNED average miss on each
    axis (not absolute), so a pitcher who misses arm-side more often
    than glove-side shows up here even if his overall average miss
    DISTANCE looks unremarkable. Returns
        {horizontal_bias_in, horizontal_bias_label, vertical_bias_in, vertical_bias_label}
    e.g. {"horizontal_bias_in": 1.8, "horizontal_bias_label": "Arm Side",
          "vertical_bias_in": 2.4, "vertical_bias_label": "High"} --
    matching the "1.8\" Arm Side / 2.4\" High" display in Section 33's
    sample report. Values are None if there are no located pitches."""
    located = _located(pitches)
    if not located:
        return {
            "horizontal_bias_in": None, "horizontal_bias_label": None,
            "vertical_bias_in": None, "vertical_bias_label": None,
        }
    h_mean = _avg([normalize_horizontal_to_arm_side(p.horizontal_miss, throws) for p in located])
    v_mean = _avg([p.vertical_miss for p in located])
    return {
        "horizontal_bias_in": round(abs(h_mean), 2) if h_mean is not None else None,
        "horizontal_bias_label": (ARM_SIDE_LABEL if h_mean >= 0 else GLOVE_SIDE_LABEL) if h_mean is not None else None,
        "vertical_bias_in": round(abs(v_mean), 2) if v_mean is not None else None,
        "vertical_bias_label": (HIGH_LABEL if v_mean >= 0 else LOW_LABEL) if v_mean is not None else None,
    }


def miss_direction_distribution(pitches):
    """Section 15: percentage of LOCATED pitches falling into each
    miss_direction label already stored on each pitch (see
    classify_miss_direction) -- e.g. {"Glove Side": 42.0, "High": 18.0,
    ...}. Only includes labels that actually occurred; percentages sum
    to (approximately, after rounding) 100 across whatever's returned.
    Empty dict if there are no located pitches."""
    located = [p for p in pitches if p.miss_direction is not None]
    n = len(located)
    if n == 0:
        return {}
    counts = {}
    for p in located:
        counts[p.miss_direction] = counts.get(p.miss_direction, 0) + 1
    return {label: round(count / n * 100, 1) for label, count in counts.items()}


def command_by_pitch_type(pitches, throws):
    """Section 16: Command By Pitch Type -- one row per pitch type
    present in `pitches`, in first-seen order (matching
    bullpen_metrics.pitch_type_summary's convention). Each row has the
    same shape as session_command_scorecard's percentages/averages plus
    miss_bias's dict, scoped to just that pitch type's pitches."""
    groups = {}
    order = []
    for p in pitches:
        label = pitch_type_label(p)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)

    rows = []
    for label in order:
        group = groups[label]
        located = _located(group)
        n = len(located)
        rows.append({
            "Pitch Type": label,
            "Pitches": len(group),
            "Located": n,
            "Avg Miss": _avg([p.miss_distance for p in located]) if n else None,
            "Median Miss": _med([p.miss_distance for p in located]) if n else None,
            "Precision %": _pct_true([p.within_precision_target for p in located]) if n else None,
            "Command Target %": _pct_true([p.within_command_target for p in located]) if n else None,
            "Competitive %": _pct_true([p.within_competitive_target for p in located]) if n else None,
            "Major Miss %": _pct_false([p.within_competitive_target for p in located]) if n else None,
            "Horizontal Miss": _avg([abs(p.horizontal_miss) for p in located]) if n else None,
            "Vertical Miss": _avg([abs(p.vertical_miss) for p in located]) if n else None,
            "Miss Bias": miss_bias(group, throws),
        })
    return rows


def individual_pitch_rows(pitches):
    """Section 34's per-pitch table: #, Pitch Type, Intended, Actual,
    Miss, Direction. Intended/Actual are formatted here as plain
    (x, z) feet pairs for a basic default -- the Command Tracker module
    is free to reformat these (e.g. to inches-from-center, or onto the
    strike zone graphic) when it builds the real table."""
    rows = []
    for p in pitches:
        rows.append({
            "#": p.pitch_number,
            "Pitch Type": pitch_type_label(p),
            "Intended": f"({float(p.intended_x):.2f}, {float(p.intended_z):.2f})",
            "Actual": f"({float(p.actual_x):.2f}, {float(p.actual_z):.2f})" if p.actual_x is not None else "—",
            "Miss (in)": float(p.miss_distance) if p.miss_distance is not None else None,
            "Direction": p.miss_direction or "—",
        })
    return rows
