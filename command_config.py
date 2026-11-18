"""
GBO — Intended Location & Command Tracker: configurable target-radius
thresholds.

Single source of truth for the target-radius classification described in
the Command Tracker architecture doc (Section 10) -- how close an actual
pitch location has to land to its intended target. Every command metric
downstream (analytics/command_metrics.py, the session scorecard, the
command-by-pitch-type table) reads these constants rather than
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

Sept 2026, Ryker: switched from the original 3-tier system (Precise/
Good/Competitive/Major Miss at 3"/6"/9") to a 5-tier system matching the
tiered target-hit% breakdown used elsewhere in pro pitch-development
tools (Pearl Player Development's "Intended Target Results" report) --
4"/8"/12"/16"/20" bands. Radii are nested (tier 1 is the innermost
circle, each tier wraps the last), matching the same pattern as before:
    <= 4 inches       = tier 1 (Elite)
    4.01-8 inches     = tier 2 (Plus)
    8.01-12 inches    = tier 3 (Average)
    12.01-16 inches   = tier 4 (Fringe)
    16.01-20 inches   = tier 5 (Competitive)
    > 20 inches       = Major Miss

IMPORTANT -- CommandPitch's three stored boolean columns
(within_precision_target/within_command_target/within_competitive_target)
predate this 5-tier system and are still written at save time (see
target_flags() below, mapped onto the first three tiers) for backward
compatibility, but nothing reads them anymore: session_command_scorecard()
and command_by_pitch_type() in analytics/command_metrics.py now recompute
every tier percentage LIVE from each pitch's stored miss_distance instead
(the same pattern pitch_execution_score() already used safely). That
means changing the radii here takes effect immediately, everywhere,
for every historical pitch -- no migration or backfill needed. The three
stored columns are vestigial: kept in the schema so nothing breaks, but
not a source of truth for anything anymore.
"""

TIER_1_RADIUS_IN = 4.0
TIER_2_RADIUS_IN = 8.0
TIER_3_RADIUS_IN = 12.0
TIER_4_RADIUS_IN = 16.0
TIER_5_RADIUS_IN = 20.0

# Outermost tier radius -- anything beyond this is a Major Miss. Chart
# extents and legend text reference this rather than TIER_5_RADIUS_IN
# directly, so a future 6th tier only means adding one more entry to
# TARGET_RADII_IN plus updating this one name.
OUTERMOST_TARGET_RADIUS_IN = TIER_5_RADIUS_IN

TIER_1_LABEL = "Elite"
TIER_2_LABEL = "Plus"
TIER_3_LABEL = "Average"
TIER_4_LABEL = "Fringe"
TIER_5_LABEL = "Competitive"
MAJOR_MISS_LABEL = "Major Miss"

# How close (in inches) horizontal/vertical miss has to be to zero to
# still count as "on target" on that axis, rather than a meaningfully
# directional miss -- avoids labeling a pitch that missed by 0.05" as
# "Glove Side" just because it wasn't mathematically exact. Only
# affects the miss_direction LABEL, never miss_distance or the
# target-radius classification above.
MISS_DIRECTION_DEADZONE_IN = 0.5

# Ordered inner-to-outer list a chart (or a tiered hit% table) can
# iterate to draw the concentric target rings (Section 18) / build
# cumulative "% within N inches" columns, without hardcoding the five
# radii a second time.
TARGET_RADII_IN = [
    (TIER_1_RADIUS_IN, TIER_1_LABEL),
    (TIER_2_RADIUS_IN, TIER_2_LABEL),
    (TIER_3_RADIUS_IN, TIER_3_LABEL),
    (TIER_4_RADIUS_IN, TIER_4_LABEL),
    (TIER_5_RADIUS_IN, TIER_5_LABEL),
]


def classify_miss(miss_distance_in):
    """miss_distance_in (inches, already Euclidean-combined horizontal +
    vertical miss) -> one of the six labels above, per the configured
    radii above. Returns None if miss_distance_in is None (no actual
    location recorded yet -- e.g. a pitch whose actual location is still
    pending a future Rapsodo match; see CommandPitch.source)."""
    if miss_distance_in is None:
        return None
    d = float(miss_distance_in)
    if d <= TIER_1_RADIUS_IN:
        return TIER_1_LABEL
    if d <= TIER_2_RADIUS_IN:
        return TIER_2_LABEL
    if d <= TIER_3_RADIUS_IN:
        return TIER_3_LABEL
    if d <= TIER_4_RADIUS_IN:
        return TIER_4_LABEL
    if d <= TIER_5_RADIUS_IN:
        return TIER_5_LABEL
    return MAJOR_MISS_LABEL


# Sept 2026, Ryker: a simpler graded "execution score" per pitch, meant
# to be readable at a glance -- one point per tier above, 4 = landed in
# the tightest (Elite) band, down to 0 = beyond the outermost (20")
# tier entirely. Deliberately NOT a second, independently-tuned scale:
# it's built from the exact same TIER_*_RADIUS_IN thresholds as
# classify_miss, so it can never disagree with the tiered hit%
# breakdown shown everywhere -- just a single-number read of the same
# math. Averaged across a session's pitches and scaled to 0-100 (score
# / MAX_EXECUTION_SCORE * 100), this is also the "Command Execution %"
# shown on the command scorecard (see
# analytics/command_metrics.py's session_command_scorecard).
MAX_EXECUTION_SCORE = 4

EXECUTION_SCORE_LABELS = {
    4: TIER_1_LABEL,
    3: TIER_2_LABEL,
    2: TIER_3_LABEL,
    1: TIER_4_LABEL,
    0: "Missed Execution",
}


def execution_score(miss_distance_in):
    """miss_distance_in (inches) -> an int 0-4 -- see the block comment
    above for what each score means and why the thresholds match
    classify_miss exactly. Returns None if miss_distance_in is None (no
    actual location recorded yet)."""
    if miss_distance_in is None:
        return None
    d = float(miss_distance_in)
    if d <= TIER_1_RADIUS_IN:
        return 4
    if d <= TIER_2_RADIUS_IN:
        return 3
    if d <= TIER_3_RADIUS_IN:
        return 2
    if d <= TIER_4_RADIUS_IN:
        return 1
    return 0


def execution_score_label(score):
    """0-4 -> its display label above. None (or an unrecognized score)
    passes through as None."""
    return EXECUTION_SCORE_LABELS.get(score)


def target_flags(miss_distance_in):
    """miss_distance_in -> (within_precision_target, within_command_target,
    within_competitive_target) booleans, matching the three legacy
    CommandPitch columns of the same name. Mapped onto the first three of
    the five tiers above (4"/8"/12") for backward compatibility -- these
    columns are written at save time but nothing reads them anymore (see
    module docstring); the tiered hit% breakdown is computed live from
    miss_distance instead. Returns (None, None, None) if miss_distance_in
    is None."""
    if miss_distance_in is None:
        return None, None, None
    d = float(miss_distance_in)
    return (
        d <= TIER_1_RADIUS_IN,
        d <= TIER_2_RADIUS_IN,
        d <= TIER_3_RADIUS_IN,
    )


def tier_hit_pct(miss_distances_in):
    """A list of non-None miss distances (inches) -> an ordered dict-like
    list of (label, pct_within) tuples, one per tier in TARGET_RADII_IN,
    each the % of the given distances landing within that tier's radius
    (cumulative -- the 8" column includes everything the 4" column
    counted, plus more). Returns [] if miss_distances_in is empty."""
    n = len(miss_distances_in)
    if n == 0:
        return []
    out = []
    for radius, label in TARGET_RADII_IN:
        hits = sum(1 for d in miss_distances_in if d <= radius)
        out.append((label, round(100 * hits / n, 1)))
    return out
