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
