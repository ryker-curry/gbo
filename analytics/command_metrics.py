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
from collections import defaultdict
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
    """Section 8: horizontal miss, vertical miss, and miss distance --
    all converted to INCHES (intended_x/z and actual_x/z themselves are
    in feet, GBO's usual plate_x/plate_z convention; see
    command_config.py's module docstring for why the derived miss values
    are stored in inches instead).

    Sept 2026, Ryker: pitches are CALLED as a spoken level/zone sequence
    (see strike_zone.call_cell) -- a called "212" is a target CELL, not
    one exact coordinate, so a miss should be measured from that cell's
    nearest edge, not from the single intended_x/z point wherever it
    happened to be clicked/decoded (a pitch that's just off the black on
    the called side should barely miss, not show a big number just
    because it's far from that one point). The called cell is derived
    from intended_x/z itself (wherever it was entered IS where the call
    was aimed -- no separate level/zone field needed), then actual_x/z
    is measured against that cell's boundaries via
    strike_zone.zone_miss_components_in (same math
    strike_zone.distance_from_cell_in already used for
    pitch_execution_score, just also broken into the per-axis
    components this function has always returned).

    horizontal_miss = 0 if actual_x already falls within the called
    cell's horizontal bounds, else the signed distance from the near
    edge (positive = beyond the high edge, negative = beyond the low
    edge -- RAW plate-coordinate direction, NOT yet handedness-adjusted,
    same convention as before; see classify_miss_direction for the
    arm-side/glove-side interpretation of this sign). vertical_miss = 0
    if actual_z falls within the cell's vertical bounds, else the
    signed distance from the near edge, positive = high, negative = low.

    Returns (horizontal_miss_in, vertical_miss_in, miss_distance_in), or
    (None, None, None) if any of the four inputs is None (most commonly:
    actual_x/z not entered yet -- a pitch tracked with intent only)."""
    if intended_x is None or intended_z is None or actual_x is None or actual_z is None:
        return None, None, None
    intended_x, intended_z = float(intended_x), float(intended_z)
    actual_x, actual_z = float(actual_x), float(actual_z)
    level, zone = strike_zone.call_cell(intended_x, intended_z)
    return strike_zone.zone_miss_components_in(level, zone, actual_x, actual_z)


def miss_direction_axes(horizontal_miss_in, vertical_miss_in, throws):
    """The same handedness-aware per-axis labels classify_miss_direction
    combines into one string below, returned SEPARATELY instead --
    (horizontal_label, vertical_label), each one of Arm Side/Glove Side
    (or Left/Right if throws is unknown) / High/Low, or None on an axis
    within command_config.MISS_DIRECTION_DEADZONE_IN of the target (no
    meaningful direction on that axis). (None, None) if either miss
    value is None.

    Ryker, Sept 2026: "would like to be able to see a miss bias for
    each individual pitch ... just if they miss glove or arm side and
    up or down" -- no combined string, no inches, just these two facts
    per pitch, for command_metrics.miss_direction_rows below."""
    if horizontal_miss_in is None or vertical_miss_in is None:
        return None, None
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

    return horizontal_label, vertical_label


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

    Returns None if either miss value is None (no actual location yet).
    Just combines miss_direction_axes' two labels into one string --
    see that function if only one axis is needed on its own."""
    if horizontal_miss_in is None or vertical_miss_in is None:
        return None
    horizontal_label, vertical_label = miss_direction_axes(horizontal_miss_in, vertical_miss_in, throws)
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
    """Session/pitch-type "Command Execution %" -- the average 0/1/2 execution
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

    def __init__(self, game_pitch, throws, pitch_number):
        p = game_pitch
        self.pitch_number = pitch_number
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
    computable without a known intent.

    pitch_number (Ryker, Sept 2026: the Command Chart -- Miss From
    Target hover text was showing "Pitch #52" using GamePitch's own
    pitch_sequence, which is the game-wide count across BOTH pitchers,
    not this pitcher's own count -- same "specific to that pitcher"
    complaint already fixed elsewhere on Pitcher Game Report) is
    computed here as each pitch's own 1-based position within ITS GAME,
    in pitch_sequence order -- grouped by game_id first so (a) two
    pitchers who both threw in the same game are numbered
    independently instead of sharing one running count, and (b) a
    multi-game view (Pitcher Profile's own use of this same function
    across a date range) restarts the count at 1 for each game instead
    of running one continuous number across game boundaries."""
    eligible = [p for p in game_pitches if p.intended_plate_x is not None]
    by_game = defaultdict(list)
    for p in eligible:
        by_game[p.game_id].append(p)
    pitch_number_by_id = {}
    for pitches_in_game in by_game.values():
        for idx, p in enumerate(sorted(pitches_in_game, key=lambda p: p.pitch_sequence), start=1):
            pitch_number_by_id[p.game_pitch_id] = idx
    return [_GamePitchCommandView(p, throws, pitch_number_by_id[p.game_pitch_id]) for p in eligible]


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
# Pitch-type-fair Command+ -- Sept 2026, informed by FanGraphs' "Kirby
# Index" article (Ryker: "make sure the command+ model is good"). The
# original Command+ above compares a whole session's OVERALL average
# danger_adjusted_miss to one pooled, all-pitch-types team baseline --
# but a called slider and a called fastball don't miss by the same
# amount even when both are well commanded (breaking stuff is just
# harder to spot up), so pooling them lets a pitcher's SCORE be a
# function of his pitch MIX, not just his command. This section grades
# every located pitch against its own pitch type's team baseline
# instead, and averages those per-pitch scores into one session number
# -- mathematically identical to averaging z-scores first and
# converting once, since command_plus()'s formula is linear in z
# (100 + 10*z_i averaged == 100 + 10*avg(z_i)).
#
# Thin-sample fallback (Ryker's call, Sept 2026): a pitch type below
# MIN_BASELINE_PITCHES team-wide (curveball/changeup/etc. right now,
# almost certainly, this early in a season) falls back to the POOLED
# baseline for that one pitch's z-score rather than going unscored --
# same "not enough of its own kind yet, use the wider pool" idea as
# Stuff+/Arsenal's own Reliable Yes/No flag elsewhere in GBO, just
# applied silently per pitch here (no separate flag surfaced -- a
# thin-type pitch still gets a real Command+ contribution, just a less
# type-specific one, the same way it always did before this change).
# ---------------------------------------------------------------------------

def team_command_plus_baselines(pitches):
    """Same population team_command_plus_baseline() above normalizes
    against, split by pitch type as well as pooled. Returns
    {"pooled": (mean, stdev, n), "by_type": {pitch_type_label: (mean,
    stdev, n)}} -- "pooled" is exactly team_command_plus_baseline()'s
    own return (kept as the thin-type fallback, see module comment
    above), "by_type" has one entry per pitch type actually thrown among
    the located pitches passed in (Unspecified included, same
    pitch_type_label() convention command_by_pitch_type already uses)."""
    pooled = team_command_plus_baseline(pitches)
    by_type = defaultdict(list)
    for p in _located(pitches):
        by_type[pitch_type_label(p)].append(p)
    return {
        "pooled": pooled,
        "by_type": {label: team_command_plus_baseline(group) for label, group in by_type.items()},
    }


def _baseline_for_pitch(pitch, baselines):
    """Which (mean, stdev, n) one pitch's Command+ z-score should be
    graded against -- its own pitch type's baseline if that type has
    hit MIN_BASELINE_PITCHES team-wide, else baselines["pooled"] (see
    module comment above for why)."""
    type_baseline = baselines["by_type"].get(pitch_type_label(pitch))
    if type_baseline is not None and type_baseline[2] >= MIN_BASELINE_PITCHES:
        return type_baseline
    return baselines["pooled"]


def session_command_plus(pitches, baselines):
    """Command+ for a window of pitches (a game, a date range, a
    bullpen session) -- pitch-type-fair replacement for the old "compare
    this window's overall average danger_adjusted_miss to one pooled
    baseline" approach (see module comment above for why that could
    distort a score by pitch mix). `baselines` is
    team_command_plus_baselines()'s return -- computed once by the
    caller and reused across every pitcher/window being scored against
    the same team population, same precedent as the old
    team_command_plus_baseline() being computed once per page render
    rather than per pitcher.

    None if there are no located pitches in `pitches`, or none of them
    has a usable baseline (missing mean, or a zero/undefined stdev --
    e.g. every located pitch of every applicable type/pool has an
    identical danger_adjusted_miss, or the pooled fallback itself has
    fewer than 2 located pitches team-wide)."""
    z_scores = []
    for p in _located(pitches):
        mean, stdev, _n = _baseline_for_pitch(p, baselines)
        value = danger_adjusted_miss(p)
        if value is None or mean is None or not stdev:
            continue
        z_scores.append((mean - value) / stdev)
    if not z_scores:
        return None
    return round(100 + 10 * (sum(z_scores) / len(z_scores)), 1)


# ---------------------------------------------------------------------------
# Layer 2: aggregate reports -- read already-stored CommandPitch fields
# ---------------------------------------------------------------------------

def _tier_hit_pcts(located):
    """located: pitches already filtered to have a miss_distance (see
    _located). Returns (tier_pcts, major_miss_pct) computed LIVE from
    each pitch's stored miss_distance via command_config.tier_hit_pct --
    Sept 2026, Ryker: switched off reading CommandPitch's stored
    within_precision_target/within_command_target/within_competitive_target
    booleans (populated once at save time, so they'd go stale for
    historical bullpen pitches if the radius bands in command_config.py
    ever change) in favor of this, the same "recompute fresh every time"
    pattern pitch_execution_score() already used safely. Works
    identically for a real CommandPitch row or a _GamePitchCommandView,
    since both only need miss_distance. tier_pcts is a
    {tier_label: pct_within} dict, one entry per command_config.TARGET_RADII_IN
    tier (cumulative -- each tier's pct includes everything the
    tighter tiers before it counted, plus more); major_miss_pct is the
    % beyond the outermost tier. (({label: None}, None) if `located` is
    empty.)"""
    if not located:
        return {label: None for _, label in command_config.TARGET_RADII_IN}, None
    distances = [float(p.miss_distance) for p in located]
    tier_pcts = dict(command_config.tier_hit_pct(distances))
    outermost_label = command_config.TARGET_RADII_IN[-1][1]
    major_miss_pct = round(100 - tier_pcts[outermost_label], 1)
    return tier_pcts, major_miss_pct


def miss_direction_grid(pitches, throws):
    """Aggregated 3x3 miss-direction grid (vertical High/On Target/Low x
    horizontal Arm Side/On Target/Glove Side -- Left/Right if throws is
    unknown, same fallback as classify_miss_direction) -- % of LOCATED
    pitches landing in each of the 9 cells, e.g. for a "Pitch Targeting
    Plan"-style report (Pearl Player Development's per-pitch-type miss
    grid). Returns a list of 3 row dicts, one per vertical label, each
    shaped {"Vertical": label, <horizontal label>: pct, ...} -- ready to
    hand straight to a table renderer. None if there are no located
    pitches."""
    located = _located(pitches)
    n = len(located)
    if n == 0:
        return None
    h_first, h_last = (ARM_SIDE_LABEL, GLOVE_SIDE_LABEL) if throws in ("L", "R") else (LEFT_LABEL, RIGHT_LABEL)
    counts = defaultdict(int)
    for p in located:
        h, v = miss_direction_axes(p.horizontal_miss, p.vertical_miss, throws)
        counts[(v or ON_TARGET_LABEL, h or ON_TARGET_LABEL)] += 1
    rows = []
    for v_label in (HIGH_LABEL, ON_TARGET_LABEL, LOW_LABEL):
        row = {"Vertical": v_label}
        for h_label in (h_first, ON_TARGET_LABEL, h_last):
            row[h_label] = round(100 * counts.get((v_label, h_label), 0) / n, 1)
        rows.append(row)
    return rows


# Sept 2026: a pitch-type's bias computed from just 1-2 pitches is noise,
# not a real aim recommendation -- same "not enough of its own kind yet"
# floor idea as MIN_BASELINE_PITCHES above, just a much lower bar since
# this only needs a stable AVERAGE, not a full baseline distribution.
MIN_TARGETING_PITCHES = 5


def pitch_targeting_plan(pitches, throws, min_pitches=MIN_TARGETING_PITCHES):
    """Pearl Player Development's forward "Pitch Targeting Plan": one row
    per pitch type with at least `min_pitches` located pitches,
    recommending an aim point shifted OPPOSITE this pitcher's average
    miss bias for that pitch type (see miss_bias) -- if he tends to miss
    glove-side on his slider, the recommendation is to aim slightly
    arm-side of the true target so the average actual result lands back
    on it. recommended_aim_horizontal_in/recommended_aim_vertical_in are
    signed inches in the SAME raw plate-coordinate convention as
    CommandPitch.horizontal_miss/vertical_miss (not handedness-flipped --
    a chart plots the recommended point in real plate coordinates, same
    as the intended/actual points already on it); "Bias" is the
    handedness-aware display string (miss_bias's own label convention)
    for a human-readable caption next to that same point."""
    groups = {}
    order = []
    for p in pitches:
        label = pitch_type_label(p)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)

    plan = []
    for label in order:
        group = groups[label]
        located = _located(group)
        n = len(located)
        if n < min_pitches:
            continue
        h_mean = _avg([p.horizontal_miss for p in located])
        v_mean = _avg([p.vertical_miss for p in located])
        if h_mean is None or v_mean is None:
            continue
        bias = miss_bias(group, throws)
        bias_label = (
            f'{bias["horizontal_bias_in"]}" {bias["horizontal_bias_label"]} / '
            f'{bias["vertical_bias_in"]}" {bias["vertical_bias_label"]}'
            if bias["horizontal_bias_in"] is not None else "—"
        )
        plan.append({
            "Pitch Type": label,
            "Located": n,
            "Bias": bias_label,
            "recommended_aim_horizontal_in": round(-h_mean, 2),
            "recommended_aim_vertical_in": round(-v_mean, 2),
        })
    return plan


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
    tier_pcts, major_miss_pct = _tier_hit_pcts(located)
    return {
        "total_pitches": len(pitches),
        "located_pitches": n,
        "avg_miss_distance": _avg([p.miss_distance for p in located]) if n else None,
        "median_miss_distance": _med([p.miss_distance for p in located]) if n else None,
        "avg_danger_adjusted_miss": _avg([danger_adjusted_miss(p) for p in located]) if n else None,
        "tier_pcts": tier_pcts,
        "major_miss_pct": major_miss_pct,
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
        tier_pcts, major_miss_pct = _tier_hit_pcts(located)
        rows.append({
            "Pitch Type": label,
            "Pitches": len(group),
            "Located": n,
            "Avg Miss": _avg([p.miss_distance for p in located]) if n else None,
            "Danger-Adj. Miss": _avg([danger_adjusted_miss(p) for p in located]) if n else None,
            "Median Miss": _med([p.miss_distance for p in located]) if n else None,
            "Tier Pcts": tier_pcts,
            "Major Miss %": major_miss_pct,
            "Command Execution %": _execution_pct(located),
            "Horizontal Miss": _avg([abs(p.horizontal_miss) for p in located]) if n else None,
            "Vertical Miss": _avg([abs(p.vertical_miss) for p in located]) if n else None,
            "Miss Bias": miss_bias(group, throws),
            "Miss Direction Grid": miss_direction_grid(group, throws),
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
    # CommandPitch.intended_x/z and actual_x/z are Numeric DB columns --
    # SQLAlchemy hands those back as decimal.Decimal, which can't mix
    # with the plain floats in strike_zone's cell-bounds arithmetic
    # (TypeError: unsupported operand type(s) for -: 'float' and
    # 'decimal.Decimal'). Cast to float up front, same as every other
    # per-pitch calculation in this module already does (see
    # compute_miss above).
    intended_x, intended_z = float(pitch.intended_x), float(pitch.intended_z)
    actual_x, actual_z = float(pitch.actual_x), float(pitch.actual_z)
    level, zone = strike_zone.call_cell(intended_x, intended_z)
    distance_in = strike_zone.distance_from_cell_in(level, zone, actual_x, actual_z)
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


def miss_direction_rows(pitches, throws):
    """Per-pitch #, Pitch Type, Called (the pitcher's own Level+Zone
    shorthand, e.g. "25"), Horizontal (Arm Side/Glove Side/Even),
    Vertical (High/Low/Even) -- deliberately no inches or distance, and
    no combined Direction string. Ryker, Sept 2026: "would like to be
    able to see a miss bias for each individual pitch, that would be
    one of the main takeaways from command tracking ... figure out why
    they miss where they miss ... it could even be based on where they
    are trying to throw the pitch. like if i am trying to go down and
    away do i always miss arm side, am i trying to go too far or am i
    not getting it out there" -- scanning down the Called column for a
    repeated code (e.g. every "25") and comparing the Horizontal/
    Vertical next to it is exactly this: does a given call tend to miss
    the same way.

    "Called" is the raw two-digit code (Level then Zone -- see
    strike_zone.py's coach's-call grid comment) instead of a translated
    English zone name like "Down & Away": that translation is relative
    to the BATTER's hand, not the pitcher's, and needs a convention this
    module hasn't verified is unambiguous yet (see strike_zone.py's
    ZONE_TO_PLATE_X comments, which describe zones by arm/glove side for
    a RHP -- a different frame than game_tracking.py's own in/away UI
    hint text). The raw code is exactly what the coach already calls
    live, so nothing is lost by leaving it untranslated for now.

    Only includes located pitches (has an actual location -- see
    _located)."""
    rows = []
    for p in _located(pitches):
        horizontal, vertical = miss_direction_axes(p.horizontal_miss, p.vertical_miss, throws)
        called = "—"
        if p.intended_x is not None and p.intended_z is not None:
            level, zone = strike_zone.call_cell(float(p.intended_x), float(p.intended_z))
            if level is not None and zone is not None:
                called = f"{level}{zone}"
        rows.append({
            "#": p.pitch_number,
            "Pitch Type": pitch_type_label(p),
            "Called": called,
            "Horizontal": horizontal or "Even",
            "Vertical": vertical or "Even",
        })
    return rows


def call_location_label(level, zone, throws):
    """Level (1-4) / Zone (1-5) call-grid cell (strike_zone.py's own
    coach's-call shorthand -- see that module's comment for what each
    value means) -> a combined High/Low + Arm Side/Glove Side label
    (e.g. "Low + Glove Side", "Middle", "High + Arm Side"), collapsed
    to the SAME 3-bucket-per-axis vocabulary miss_bias/miss_direction_
    grid already use (not all 20 raw Level-Zone cells) -- so a single
    game's worth of calls groups into a handful of meaningful buckets
    instead of one row per exact code. Level 1 (dirt/below) and 2
    (knees) both collapse to Low; level 3 is the vertical middle
    (no label); level 4 is High. Zone 1/2 are always the physical
    3B-side columns and 4/5 the 1B-side ones (see strike_zone.py's own
    Zone comment) -- which one reads as Arm Side vs. Glove Side is
    what flips with the pitcher's throwing hand, same convention
    classify_miss_direction/normalize_horizontal_to_arm_side use; zone
    3 is the horizontal middle (no label). throws unknown falls back to
    plain Left/Right, same fallback classify_miss_direction uses.

    Sept 2026, Ryker: "I just want to see where they typically missed
    based on pitch call. like if the pitch call is low and glove side
    where do they tend to miss" -- this is the "low and glove side"
    half of that ask; miss_by_call below pairs it with the actual
    miss tendency."""
    vertical = HIGH_LABEL if level == 4 else (LOW_LABEL if level in (1, 2) else None)
    if zone in (1, 2):
        horizontal = ARM_SIDE_LABEL if throws == "R" else (GLOVE_SIDE_LABEL if throws == "L" else LEFT_LABEL)
    elif zone in (4, 5):
        horizontal = GLOVE_SIDE_LABEL if throws == "R" else (ARM_SIDE_LABEL if throws == "L" else RIGHT_LABEL)
    else:
        horizontal = None
    if vertical and horizontal:
        return f"{vertical} + {horizontal}"
    return vertical or horizontal or "Middle"


def miss_by_call(pitches, throws):
    """Grouped by pitch type AND the pitcher's own call (call_location_label
    above), each group's actual miss tendency via miss_bias -- e.g. "his
    Slider called Low + Glove Side missed 1.8\" Arm Side / 0.6\" High on
    average". Replaces scanning a raw per-pitch list or a by-pitch-type
    grid for a pattern by hand: this IS the pattern, aggregated (Ryker,
    Sept 2026, see call_location_label's docstring for the original ask;
    Ryker again the same day: "for miss by call i need to know pitch
    type, not just location" -- the same call can miss differently pitch
    to pitch, so Pitch Type is its own column/group key here, not folded
    away).

    Only pitches with both a located actual position (see _located) AND
    an intended position (needed to know what was called) count. Returns
    a list of {"Pitch Type": label, "Called": label, "Pitches": n,
    "Miss Bias": miss_bias(...) dict} rows, sorted by Pitches descending
    (the pitch-type/call combo thrown most often leads) -- empty list if
    nothing qualifies."""
    groups = defaultdict(list)
    for p in _located(pitches):
        if p.intended_x is None or p.intended_z is None:
            continue
        level, zone = strike_zone.call_cell(float(p.intended_x), float(p.intended_z))
        if level is None or zone is None:
            continue
        groups[(pitch_type_label(p), call_location_label(level, zone, throws))].append(p)
    rows = [
        {"Pitch Type": pitch_type, "Called": called, "Pitches": len(group), "Miss Bias": miss_bias(group, throws)}
        for (pitch_type, called), group in groups.items()
    ]
    rows.sort(key=lambda r: -r["Pitches"])
    return rows
