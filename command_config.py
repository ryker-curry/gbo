"""
GBO — Intended Location & Command Tracker: configurable target-radius
thresholds.

Single source of truth for the target-radius classification described in
the Command Tracker architecture doc (Section 10) -- how close an actual
pitch location has to land to its intended target to count as
"Precise" / "Good" / "Competitive" / a "Major Miss". Every command
metric downstream (analytics/command_metrics.py, the session scorecard,
the command-by-pitch-type table) reads these constants rather than
hardcoding inch values, so the thresholds can be tuned later without
touching any calculation code.

All radii here are in INCHES -- the unit coaches think in and the unit
displayed everywhere in the UI ("Miss: 4.2 inches"). Internally, pitch
locations themselves are stored in FEET on CommandPitch
(intended_x/z, actual_x/z -- same plate_x/plate_z convention as
strike_zone.py and GamePitch: x = 0 at the center of the plate, z = 0 at
the ground), matching every other coordinate already in GBO. The derived
miss-distance columns (horizontal_miss/vertical_miss/miss_distance on
CommandPitch) are stored already converted to inches, since coaches --
and every analytics function that reads them -- only ever need the
inches value, never the raw feet difference. See models.py's
CommandPitch docstring for the full reasoning.

Radii are nested (Precision is the innermost circle, Command wraps it,
Competitive wraps that), matching Section 10's example:
    <= 3 inches      = Precise
    3.01-6 inches    = Good
    6.01-9 inches    = Competitive
    > 9 inches       = Major Miss
"""

PRECISION_TARGET_RADIUS_IN = 3.0
COMMAND_TARGET_RADIUS_IN = 6.0
COMPETITIVE_TARGET_RADIUS_IN = 9.0

# How close (in inches) horizontal/vertical miss has to be to zero to
# still count as "on target" on that axis, rather than a meaningfully
# directional miss -- avoids labeling a pitch that missed by 0.05" as
# "Glove Side" just because it wasn't mathematically exact. Only
# affects the miss_direction LABEL, never miss_distance or the
# target-radius classification above.
MISS_DIRECTION_DEADZONE_IN = 0.5

PRECISE_LABEL = "Precise"
GOOD_LABEL = "Good"
COMPETITIVE_LABEL = "Competitive"
MAJOR_MISS_LABEL = "Major Miss"

# Ordered outer-to-inner-independent list a chart can iterate to draw the
# concentric target rings (Section 18) without hardcoding the three radii
# a second time.
TARGET_RADII_IN = [
    (PRECISION_TARGET_RADIUS_IN, PRECISE_LABEL),
    (COMMAND_TARGET_RADIUS_IN, GOOD_LABEL),
    (COMPETITIVE_TARGET_RADIUS_IN, COMPETITIVE_LABEL),
]


def classify_miss(miss_distance_in):
    """miss_distance_in (inches, already Euclidean-combined horizontal +
    vertical miss) -> one of the four labels above, per the configured
    radii above. Returns None if miss_distance_in is None (no actual
    location recorded yet -- e.g. a pitch whose actual location is still
    pending a future Rapsodo match; see CommandPitch.source)."""
    if miss_distance_in is None:
        return None
    miss_distance_in = float(miss_distance_in)
    if miss_distance_in <= PRECISION_TARGET_RADIUS_IN:
        return PRECISE_LABEL
    if miss_distance_in <= COMMAND_TARGET_RADIUS_IN:
        return GOOD_LABEL
    if miss_distance_in <= COMPETITIVE_TARGET_RADIUS_IN:
        return COMPETITIVE_LABEL
    return MAJOR_MISS_LABEL


# Sept 2026, Ryker: a simpler 0/1/2 "execution score" per pitch, meant
# to be readable at a glance without knowing what "Competitive" or
# "Major Miss" mean -- 2 = perfectly executed, 1 = a close/good miss, 0
# = not even close. Deliberately NOT a second, independently-tuned
# scale: it collapses classify_miss's four tiers by reusing the exact
# same PRECISION_TARGET_RADIUS_IN / COMPETITIVE_TARGET_RADIUS_IN
# thresholds above (Precise -> 2, Good or Competitive -> 1, Major Miss
# -> 0), so it can never disagree with classify_miss, the within_*_target
# flags, or the Precision/Competitive/Major Miss percentages already
# shown everywhere -- just a friendlier read of the same math. Averaged
# across a session's pitches and scaled to 0-100, this is also the
# "Execution %" shown on the command scorecard (see
# analytics/command_metrics.py's session_command_scorecard).
EXECUTION_SCORE_PERFECT = 2
EXECUTION_SCORE_CLOSE = 1
EXECUTION_SCORE_MISS = 0
MAX_EXECUTION_SCORE = EXECUTION_SCORE_PERFECT

EXECUTION_SCORE_LABELS = {
    EXECUTION_SCORE_PERFECT: "Perfect Execution",
    EXECUTION_SCORE_CLOSE: "Close Miss",
    EXECUTION_SCORE_MISS: "Missed Execution",
}


def execution_score(miss_distance_in):
    """miss_distance_in (inches) -> 0, 1, or 2 -- see the block comment
    above for what each score means and why the thresholds match
    classify_miss exactly. Returns None if miss_distance_in is None (no
    actual location recorded yet)."""
    if miss_distance_in is None:
        return None
    miss_distance_in = float(miss_distance_in)
    if miss_distance_in <= PRECISION_TARGET_RADIUS_IN:
        return EXECUTION_SCORE_PERFECT
    if miss_distance_in <= COMPETITIVE_TARGET_RADIUS_IN:
        return EXECUTION_SCORE_CLOSE
    return EXECUTION_SCORE_MISS


def execution_score_label(score):
    """0/1/2 -> its display label above. None (or an unrecognized score)
    passes through as None."""
    return EXECUTION_SCORE_LABELS.get(score)


def target_flags(miss_distance_in):
    """miss_distance_in -> (within_precision_target, within_command_target,
    within_competitive_target) booleans, matching the three CommandPitch
    columns of the same name -- each True if the miss landed inside that
    radius (radii are nested, so a Precise pitch is also within the
    Command and Competitive radii). Returns (None, None, None) if
    miss_distance_in is None."""
    if miss_distance_in is None:
        return None, None, None
    miss_distance_in = float(miss_distance_in)
    return (
        miss_distance_in <= PRECISION_TARGET_RADIUS_IN,
        miss_distance_in <= COMMAND_TARGET_RADIUS_IN,
        miss_distance_in <= COMPETITIVE_TARGET_RADIUS_IN,
    )
