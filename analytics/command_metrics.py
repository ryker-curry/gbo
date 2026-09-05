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
import strike_zone

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


def _execution_pct(located_pitches):
    """Session/pitch-type "Execution %" -- the average 0/1/2 execution
    score (see pitch_execution_score) across already-located pitches,
    scaled to 0-100 against the max possible score (2) so it
    reads on the same 0-100 scale as Precision %/Command Target %/
    Major Miss % next to it. 100% would mean every pitch scored a
    perfect 2; 0% would mean every pitch scored a 0. None if there are
    no located pitches."""
    scores = [pitch_execution_score(p) for p in located_pitches]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    return round(sum(scores) / (len(scores) * command_config.MAX_EXECUTION_SCORE) * 100, 1)


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
# Danger-adjusted miss -- 2026-08-23 Command+ design conversation with
# Ryker: a miss that drifts AWAY from the heart of the zone is more
# forgivable than one that drifts TOWARD it, even at an identical raw
# miss_distance -- plain Euclidean miss distance can't tell the two apart.
# This corrects for that, in the SAME inches unit as miss_distance so it
# reads as directly comparable rather than a separate index (NOT yet a
# true mean-100 Command+ index -- that needs a league/organizational
# baseline to normalize against, which GBO doesn't have enough games
# logged for yet; this is the inches-based building block for that,
# usable right now with the data already on hand).
#
#   danger_delta = center_dist_actual - center_dist_intended
#   danger_adjusted_miss = miss_distance - danger_delta   (k=1, linear --
#       Ryker's own picks from that conversation: a fixed zone-center
#       reference since GBO doesn't track individual batter height/stance
#       anywhere to derive a batter-specific center from, a linear rather
#       than escalating-near-the-heart curve, and direction weighted
#       equally with raw distance rather than lighter or heavier)
#
# Bounded in [0, 2 x miss_distance] for k=1, by the reverse triangle
# inequality (|center_dist_actual - center_dist_intended| <= miss_distance
# always) -- 0 when the miss drifted directly away from center as far as
# it possibly could have for that miss_distance, 2x miss_distance when it
# drifted directly toward center as far as it possibly could have. No
# separate floor/cap logic needed.
#
# Computed fresh from intended_x/z + actual_x/z rather than stored on
# CommandPitch -- same no-migration precedent as game_pitches_command_view
# above: no schema change, and it works identically for a real
# CommandPitch row or a _GamePitchCommandView-adapted GamePitch, since
# both already expose those same four attributes.
# ---------------------------------------------------------------------------

ZONE_CENTER_X_FT = 0.0
ZONE_CENTER_Z_FT = 2.5  # ft -- matches strike_zone.py's ZONE_BOTTOM/ZONE_TOP midpoint (1.5/3.5 ft). Restated here rather than imported to avoid a new cross-module dependency for two constants -- must stay in sync if strike_zone.py's zone ever changes.


def _center_distance_in(x, z):
    """Euclidean distance from the zone center, in inches (x/z are feet,
    GBO's usual plate_x/plate_z convention). None if either is missing."""
    if x is None or z is None:
        return None
    return math.hypot((float(x) - ZONE_CENTER_X_FT) * FEET_TO_INCHES, (float(z) - ZONE_CENTER_Z_FT) * FEET_TO_INCHES)


def danger_adjusted_miss(pitch):
    """danger_delta/danger_adjusted_miss for one already-loaded pitch
    (a CommandPitch row or a _GamePitchCommandView) -- see the module
    comment just above for the formula and reasoning. None if the pitch
    has no actual location yet (miss_distance is None), or, degenerately,
    no intended location (shouldn't happen for anything that already has
    a miss_distance, but checked rather than assumed)."""
    if pitch.miss_distance is None:
        return None
    center_dist_intended = _center_distance_in(pitch.intended_x, pitch.intended_z)
    center_dist_actual = _center_distance_in(pitch.actual_x, pitch.actual_z)
    if center_dist_intended is None or center_dist_actual is None:
        return None
    danger_delta = center_dist_actual - center_dist_intended
    return round(float(pitch.miss_distance) - danger_delta, 2)


# ---------------------------------------------------------------------------
# Command+ -- 2026-08-23 design conversation, part 2: a mean-100 index over
# danger_adjusted_miss, scaled the same way Stuff+/Location+ are (100 =
# average, roughly 10 points per standard deviation), EXCEPT the baseline
# population is GBO's own team, not an MLB-wide dataset -- GBO has no
# access to league-wide Trackman/Statcast pitch data to calibrate against,
# so this is a GBO-internal scale ("better than your own team's average"),
# not a claim to match a published Stuff+/Location+ number. Ryker's
# 2026-08-23 call on what counts as "the team": every located pitch from
# our own pitchers across every GAME (intrasquad and real opponents alike,
# fall scrimmages and the spring season both), NOT bullpen sessions --
# see the UI module that builds this population for exactly how that
# query works (it's a DB query, so it can't live in this
# no-database-access module -- see the module docstring at the top of
# this file).
# ---------------------------------------------------------------------------

# A baseline built from a handful of pitches swings wildly with every new
# pitch logged and isn't trustworthy yet -- 20 is a starting floor, not a
# statistically rigorous minimum. Easy to raise once GBO has more of a
# season's worth of data to see how noisy Command+ actually is in
# practice below that.
MIN_BASELINE_PITCHES = 20


def command_plus(danger_adjusted_value, baseline_mean, baseline_stdev):
    """One danger_adjusted_miss value -> a mean-100 Command+ score against
    a baseline population's own mean/stdev (see team_command_plus_baseline
    below for how that population is built). LOWER danger_adjusted_miss is
    BETTER (0in = as good as executed perfectly), so the sign is flipped
    from the usual "bigger raw number = bigger + score" pattern -- landing
    BELOW the baseline mean (a smaller miss) scores ABOVE 100:

        command_plus = 100 + 10 * (baseline_mean - value) / baseline_stdev

    None if any input is None, or if baseline_stdev is 0 (can't scale
    against a population with no spread -- e.g. a baseline of one pitch,
    or every pitch in it landing at an identical miss)."""
    if danger_adjusted_value is None or baseline_mean is None or not baseline_stdev:
        return None
    return round(100 + 10 * (baseline_mean - danger_adjusted_value) / baseline_stdev, 1)


def team_command_plus_baseline(pitches):
    """Mean + stdev of danger_adjusted_miss across a population of
    already-loaded pitches -- the population command_plus() above
    normalizes against. Pass every pitch in whatever pool counts as "the
    team" (the calling UI module owns that query/scope -- see this
    module's Command+ comment above for what Ryker picked). Returns
    (mean, stdev, n) -- n is the population size actually used, so a
    caller can compare it against MIN_BASELINE_PITCHES before trusting
    the number. (None, None, 0) if the population has no located pitches
    at all."""
    located = _located(pitches)
    values = [v for v in (danger_adjusted_miss(p) for p in located) if v is not None]
    n = len(values)
    if n == 0:
        return None, None, 0
    return _avg(values), _sd(values), n


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
        "avg_danger_adjusted_miss": _avg([danger_adjusted_miss(p) for p in located]) if n else None,
        "precision_pct": _pct_true([p.within_precision_target for p in located]) if n else None,
        "command_target_pct": _pct_true([p.within_command_target for p in located]) if n else None,
        "competitive_pct": _pct_true([p.within_competitive_target for p in located]) if n else None,
        "major_miss_pct": _pct_false([p.within_competitive_target for p in located]) if n else None,
        "avg_execution_score": _avg([pitch_execution_score(p) for p in located]) if n else None,
        "execution_pct": _execution_pct(located),
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
            "Danger-Adj. Miss": _avg([danger_adjusted_miss(p) for p in located]) if n else None,
            "Median Miss": _med([p.miss_distance for p in located]) if n else None,
            "Precision %": _pct_true([p.within_precision_target for p in located]) if n else None,
            "Command Target %": _pct_true([p.within_command_target for p in located]) if n else None,
            "Competitive %": _pct_true([p.within_competitive_target for p in located]) if n else None,
            "Major Miss %": _pct_false([p.within_competitive_target for p in located]) if n else None,
            "Execution %": _execution_pct(located),
            "Horizontal Miss": _avg([abs(p.horizontal_miss) for p in located]) if n else None,
            "Vertical Miss": _avg([abs(p.vertical_miss) for p in located]) if n else None,
            "Miss Bias": miss_bias(group, throws),
        })
    return rows


def pitch_execution_score(pitch):
    """A pitch's 0/1/2 execution score (see command_config.execution_score
    for what each value means), graded against the coach's CALLED CELL
    rather than a single point -- Sept 2026, Ryker: pitches are called
    as a spoken level/zone sequence (see strike_zone.call_cell), so
    landing anywhere in that same cell is a perfect 2, not just an exact
    coordinate match. The called cell is derived from the pitch's own
    intended_x/z (wherever it was entered IS where the call was aimed --
    no separate level/zone field needed), then the ACTUAL location is
    measured against that cell's boundaries rather than against
    intended_x/z as an exact point (strike_zone.distance_from_cell_in).
    Same PRECISION/COMPETITIVE inch thresholds as
    command_config.execution_score -- just a more forgiving distance
    feeding into them. Works identically for a real CommandPitch row or
    a _GamePitchCommandView, same as danger_adjusted_miss above. None if
    the pitch has no actual location yet (or, degenerately, no intended
    location)."""
    if pitch.actual_x is None or pitch.actual_z is None:
        return None
    if pitch.intended_x is None or pitch.intended_z is None:
        return None
    level, zone = strike_zone.call_cell(pitch.intended_x, pitch.intended_z)
    distance_in = strike_zone.distance_from_cell_in(level, zone, pitch.actual_x, pitch.actual_z)
    return command_config.execution_score(distance_in)


def individual_pitch_rows(pitches):
    """Section 34's per-pitch table: #, Pitch Type, Intended, Actual,
    Miss, Direction. Intended/Actual are formatted here as plain
    (x, z) feet pairs for a basic default -- the Command Tracker module
    is free to reformat these (e.g. to inches-from-center, or onto the
    strike zone graphic) when it builds the real table."""
    rows = []
    for p in pitches:
        score = pitch_execution_score(p)
        rows.append({
            "#": p.pitch_number,
            "Pitch Type": pitch_type_label(p),
            "Intended": f"({float(p.intended_x):.2f}, {float(p.intended_z):.2f})",
            "Actual": f"({float(p.actual_x):.2f}, {float(p.actual_z):.2f})" if p.actual_x is not None else "—",
            "Miss (in)": float(p.miss_distance) if p.miss_distance is not None else None,
            "Danger-Adj. Miss (in)": danger_adjusted_miss(p),
            "Direction": p.miss_direction or "—",
            "Execution": score,
            "Execution Label": command_config.execution_score_label(score) or "—",
        })
    return rows
