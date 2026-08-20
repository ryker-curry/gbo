"""
GBO — Bucket System computation (physical testing composite scoring).

Ryker's professor's real scoring system, confirmed directly against his
spreadsheet's actual data (not guessed):
  - Percentile = ROUND((value / team_max) * 100) for "higher is better"
    metrics, or ROUND((team_min / value) * 100) for "lower is better"
    metrics (times, contact durations). Verified exact match on Body
    Mass (23/23 players) and Hop Test Mean Contact Time (20/20 players)
    against his real historical data before building this.
  - No weighting anywhere -- every average is a plain mean.
  - Body Comp composite = average of ONLY Body Weight % and Skeletal
    Muscle Mass % (Fat Mass/Body Fat % are raw reference data only, not
    in the composite) -- matches his professor's email exactly.
  - Speed, Capacity, Mobility, and Shoulder Health are all computed
    (for reference/display) but excluded from the final Total -- see
    the Mobility/Shoulder Health section further down for why those
    two exist despite Shoulder Health (GIRD) originally having been
    excluded entirely from this file.
  - Total = ROUND(AVERAGE(Body Comp, Power, Strength), 0). Unchanged by
    every extension below -- still exactly the professor's original 3
    inputs, per Ryker's explicit call each time a new bucket's been
    added (Capacity, now Mobility/Shoulder Health) not to touch it.

"Team" comparison population = every player (active and inactive) with
at least one result for that test type, using each player's most recent value per
metric (an ongoing system, not a one-time snapshot like the original
spreadsheet).

---

Physical Development / Capacity extension (added after the Physical
Assessment & IDP design brief, per Ryker's explicit sign-off on 3
specific decisions):
  1. Arm Health feeds a new Capacity score -- previously excluded
     entirely from the bucket system (GIRD wasn't part of the
     professor's original spreadsheet at all, not a data-quality call).
  2. Physical Output is NOT a new composite -- it's the average of the
     EXISTING power_score and strength_score above, reused as-is.
     Deliberately does not touch Total (which also includes Body Comp)
     -- Output is Ryker's brief's definition (force/power production
     only), a narrower thing than Total.
  3. Balance/Development Profile is computed live against the CURRENT
     team-best every time, exactly like every other score in this
     module -- no snapshot-at-test-time mechanism. Same tradeoff the
     existing Total score already has (a teammate's new PR can nudge
     another athlete's percentile), left consistent rather than adding
     a second, different computation model into one file.

Capacity scoring only pulls from Arm Health tests that cleanly fit the
higher-is-better percentile model -- strength values. ROM/GIRD/pain/
workload rows stay excluded from the composite math, same reasoning
Ryker already applied to GIRD (a joint's mobility isn't a "the more the
better" quantity the way force output is -- see the movement_chart.py
history for the same lesson learned about a different metric). Scoped
to the THROWING arm only (this is a pitching-development profile, not
a general fitness score) -- non-throwing-arm strength stays available
as raw bilateral-comparison reference data, same treatment Body Fat %
gets in Body Comp.

---

Mobility + Shoulder Health buckets (added per Ryker's explicit call,
reversing the "Shoulder Health (GIRD) is excluded entirely" line
above -- that original call was about not building a composite at
all, not a permanent decision):

  - Mobility: NOT percentile-ranked ("higher is better") -- per
    Ryker's later call (Aug 2026), each field is instead checked
    pass/fail against a fixed minimum degree value. See MOBILITY_ROM_
    THRESHOLDS and compute_mobility_rom_report for the current design
    and research sourcing (this replaced an earlier percentile-based
    version of this bucket).
  - Shoulder Health: GIRD only for now, "lower is better" (smaller
    deficit = healthier), reusing this file's existing lower-is-better
    formula. Auto-calculated live from the Right/Left Internal
    Rotation fields (resolved to non-throwing IR - throwing IR via
    resolve_side_by_throws), not a separately entered value -- see
    compute_gird_percentiles for the full reasoning, including why a
    GIRD of 0 isn't literally the clinical target.
  - Named "Shoulder Health" rather than "Arm Health" (which is already
    an AssessmentCategory name, a different thing) since nothing here
    measures the elbow yet -- Ryker's explicit call is to rename this
    to Arm Health and fold in elbow metrics once that data exists.
  - Both are reference-only for now, same treatment as Speed and
    Capacity -- Total stays exactly Body Comp + Power + Strength.
    Ryker's stated intent is to eventually fold Mobility and Shoulder
    Health into Total once there's real confidence in the scoring, but
    that hasn't happened yet -- don't add them to total_inputs below
    without an explicit, separate go-ahead.
"""

from sqlalchemy.orm import joinedload
from models import Player, Assessment, AssessmentResult, AssessmentTestType

# (test_name, direction) -- direction is "higher" or "lower" (lower =
# lower raw value is the better score, e.g. sprint times).
# ONLY these 2 feed the Body Comp composite score -- see
# BODY_COMP_ENTRY_FIELDS below for the full set of 4 raw fields that
# are actually in the bucket spreadsheet (Fat Mass and Body Fat % are
# tracked as raw reference data, per Ryker's professor's email, but
# aren't part of the composite).
BODY_COMP_METRICS = [
    ("Body Weight", "higher"),
    ("Skeletal Muscle Mass", "higher"),
]

# All 4 Body Comp raw fields that are actually in the bucket
# spreadsheet -- used to scope the assessment ENTRY FORM (Ryker wants
# all 4 enterable, even though only 2 feed the calculation above).
BODY_COMP_ENTRY_FIELDS = {"Body Weight", "Body Fat Mass", "Skeletal Muscle Mass", "Percent Body Fat"}

# Same 4 fields as BODY_COMP_ENTRY_FIELDS, but as (test_name, direction)
# pairs for DISPLAY (percentile bars in the Body Comp breakdown, per
# Ryker's call) -- players see percentile bars for all 4, even though
# body_comp_score above still only averages the first 2. Body Fat Mass/
# Percent Body Fat use "lower" (less body fat scores toward 100), per
# Ryker's call -- the professor's original scoring never assigned them
# a direction at all since they were never part of the composite math,
# so this is a new, display-only decision, not a re-derivation of his
# spreadsheet. Order here is the order the bars render in.
BODY_COMP_DISPLAY_METRICS = [
    ("Body Weight", "higher"),
    ("Skeletal Muscle Mass", "higher"),
    ("Body Fat Mass", "lower"),
    ("Percent Body Fat", "lower"),
]

# sub_group_name -> [(test_name, direction), ...]
POWER_SUBGROUPS = {
    "Med Ball Throw": [
        ("Medicine Ball Shot Put Distance", "higher"),
    ],
    "Field Jumps": [
        ("Vertical Jump (Jump Mat)", "higher"),
        ("Broad Jump Distance", "higher"),
        ("Lateral Jump Distance (Drive Leg)", "higher"),
        ("Lateral Jump Distance (Plant Leg)", "higher"),
    ],
    "Countermovement Jump": [
        ("Countermovement Jump Height", "higher"),
        ("Countermovement Jump RSI-Modified", "higher"),
        ("Countermovement Jump Concentric Duration", "lower"),
        ("Countermovement Jump Concentric Mean Force", "higher"),
    ],
    "Repeated Hop": [
        ("Hop Test RSI (10/5)", "higher"),
        ("Hop Test Average Force", "higher"),
        ("Hop Test Mean Contact Time", "lower"),
    ],
    "Single Leg Jump": [
        ("Single-Leg Jump Height (Drive Leg)", "higher"),
        ("Single-Leg Jump Height (Plant Leg)", "higher"),
        ("Single-Leg Jump Concentric Impulse (Drive Leg)", "higher"),
        ("Single-Leg Jump Concentric Impulse (Plant Leg)", "higher"),
    ],
}

STRENGTH_SUBGROUPS = {
    "Lower Body Strength": [
        ("Hex Bar Deadlift Max", "higher"),
        ("Front Squat Max", "higher"),
        ("Hip Abduction Force (Drive Leg)", "higher"),
        ("Hip Abduction Force (Plant Leg)", "higher"),
        ("Hip Adduction Force (Drive Leg)", "higher"),
        ("Hip Adduction Force (Plant Leg)", "higher"),
        # Isometric Mid-Thigh Pull -- previously its own "Mid-Thigh Pull"
        # subgroup (a separate "Mid-Thigh Pull — <score>" header on the
        # Development Profile breakdown), folded into Lower Body Strength
        # per Ryker's explicit call so it's just part of the one Lower
        # Body Strength score/bar group instead of a standalone section.
        ("Isometric Mid-Thigh Pull Average Force", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", "higher"),
    ],
    "Upper Body Strength": [
        ("Neutral Grip/DB Bench Press Max Load", "higher"),
        ("Neutral Grip Chin Up Max External Load", "higher"),
        ("Grip Strength (Seated, Throwing Hand)", "higher"),
    ],
}

# Shown for reference, excluded from the final Total.
SPEED_METRICS = [
    ("Acceleration: 10-Yard Sprint Time", "lower"),
    ("Top Speed: Flying 10 Sprint Time", "lower"),
]

# Feeds the new Capacity score (Physical Development extension) --
# throwing-arm strength/stability metrics only, matching the
# higher-is-better shape every other bucket in this file already
# requires. Non-throwing-arm strength, all ROM/GIRD, ER:IR ratio, pain,
# and workload rows are deliberately NOT here -- they either don't fit
# a clean higher-is-better model (ROM, ratios) or aren't a physical
# quality at all (pain, workload counts). Those stay visible as raw
# reference data on the assessment entry/history views, same as Body
# Fat % already is for Body Comp.
CAPACITY_SUBGROUPS = {
    "Shoulder Strength": [
        ("Shoulder Strength: Throwing Arm ER Peak Force", "higher"),
        ("Shoulder Strength: Throwing Arm IR Peak Force", "higher"),
    ],
    "Scapular Strength": [
        ("Shoulder Strength: I Position Peak Force", "higher"),
        ("Shoulder Strength: Y Position Peak Force", "higher"),
        ("Shoulder Strength: T Position Peak Force", "higher"),
    ],
    "Grip Strength": [
        ("Grip Strength: Throwing Hand Grip Strength", "higher"),
    ],
    "Forearm/Elbow Capacity": [
        ("Forearm/Elbow Capacity: FCU Isometric Strength (Throwing Arm)", "higher"),
        ("Forearm/Elbow Capacity: FDS Isometric Strength (Throwing Arm)", "higher"),
    ],
}

# Range of Motion / Mobility (Physical Development extension). Per
# Ryker's explicit call (Aug 2026), Mobility & ROM is NOT percentile-
# ranked against the team ("higher is better") like every other bucket
# in this file -- more range past a healthy point isn't meaningfully
# "better," so instead each metric is checked pass/fail against a
# fixed minimum degree value. This REPLACES the percentile-based
# Mobility scoring an earlier round of this file had (MOBILITY_
# SUBGROUPS / MOBILITY_SHOULDER_SIDED_FIELDS / compute_mobility_
# shoulder_metrics, all removed -- see git history if that scoring
# model is ever wanted back) -- there's no more "Shoulder — 82" or
# "Hip — 78" score, no percentile bars, just a met/did-not-meet flag
# per metric. See compute_mobility_rom_report below for how this dict
# gets turned into that report.
#
# Values are the degree BELOW WHICH a metric is flagged, or None if no
# threshold is configured yet for that metric (still displays with its
# raw value, just no pass/fail flag -- same "don't fabricate a number"
# caution this file uses everywhere else, e.g. DEVELOPMENT_PROFILE_
# BANDS' "not validated thresholds" note). Shoulder External/Internal
# Rotation and Hip Internal/External Rotation below are backed by
# actual baseball-pitcher research (see each value's source comment);
# the rest (Shoulder/Elbow Flexion/Extension, Hip Abduction/Adduction/
# Flexion/Extension) are left at None because the research found was
# either general-population goniometry ceilings (AAOS reference
# values -- a MAXIMUM most healthy people can reach, not a validated
# MINIMUM floor to flag against) or simply didn't exist for a
# baseball-specific population. Using a general-population max as a
# "flag if below" floor would false-positive constantly, so those stay
# unconfigured until there's a real baseball-specific number or
# Ryker's own clinical call to set them. Fill in a real number instead
# of guessing.
#
# Shoulder fields are entered anatomically (Right/Left), not by
# Throwing/Non-Throwing Arm role -- so a coach measuring a player
# doesn't need to know that player's handedness at data-entry time.
# The threshold check below is applied directly to whichever raw
# Right/Left value was entered (no Player.throws resolution needed for
# a flat pass/fail floor) -- unlike GIRD/Total Arc below, which ARE
# resolved to Throwing/Non-Throwing Arm since they're inherently a
# side-to-side comparison, not an absolute floor.
#
# Hip fields are ALSO entered anatomically (Right/Left) as of Ryker's
# follow-up call -- an earlier version of this dict had hip entered
# directly as Drive Leg/Plant Leg (reasoning: "which leg is which" is
# unambiguous from the pitching motion itself, so why not enter it that
# way), but that turned out to be confusing to actually type in at
# assessment time (a coach has to stop and work out which leg is
# "drive" for this particular player). Drive Leg/Plant Leg is still the
# right framing for INTERPRETING the result -- the McCulloch et al.
# 2014 thresholds below are keyed to that role, not to anatomical side
# -- so entry stays Right/Left (via HIP_ROM_BASE_METRICS, resolved the
# same Player.throws-based way as GIRD/Total Arc below: drive leg =
# throwing-side leg, plant leg = glove-side leg) while the threshold
# dict below and the report stay keyed by role. See
# compute_mobility_rom_report for where that resolution happens.
#
# One consequence worth knowing: a player with no Player.throws on
# file can't be resolved to a side, so their hip ROM values won't show
# on the report until handedness is set on their profile -- same
# limitation GIRD/Total Arc already had.
MOBILITY_ROM_THRESHOLDS = {
    # Shoulder External Rotation (throwing arm, 90° abduction) --
    # Wilk et al. 2011, uninjured high school pitchers: throwing-arm
    # mean 130° ± 11°. Floor set ~2 SD below that mean.
    "Shoulder: Right External Rotation": 110,
    "Shoulder: Left External Rotation": 110,
    # Shoulder Internal Rotation (throwing arm, 90° abduction) -- Wilk
    # 2011: throwing-arm mean 60° ± 11°; college/pro cohorts (IJSPT
    # 2021) run closer to 62-65°. Floor set conservatively below both.
    # Note: a same-side absolute floor is a supplementary check only --
    # GIRD (IR deficit vs. the non-throwing arm, computed separately
    # below via compute_gird_percentiles) is the better-validated,
    # more commonly cited red flag in this literature than any single
    # absolute IR number.
    "Shoulder: Right Internal Rotation": 45,
    "Shoulder: Left Internal Rotation": 45,
    "Shoulder: Right Flexion": None,
    "Shoulder: Left Flexion": None,
    "Shoulder: Right Extension": None,
    "Shoulder: Left Extension": None,
    "Elbow: Right Flexion": None,
    "Elbow: Left Flexion": None,
    # Elbow Extension is a well-documented throwing-elbow finding
    # (pitchers commonly develop a flexion contracture -- can't reach
    # full 0° extension -- from repetitive valgus loading). Polarity
    # confirmed (per Ryker, Aug 2026): standard goniometry convention,
    # 0° = fully straight, POSITIVE = hyperextension past straight,
    # NEGATIVE = flexion contracture (short of straight). A red-flag
    # threshold for this would be a NEGATIVE floor (e.g. "flag if worse
    # than -X°," not "flag if below X°" the way every other metric in
    # this dict works) -- _mobility_rom_status's current "raw < X ->
    # red" comparison already reads correctly for a negative threshold
    # (more negative = worse = still "less than"), so no code change is
    # needed there, just a real research-backed negative number here
    # once one exists. Left None for now -- no baseball-specific
    # contracture-degree threshold was found in the same literature
    # sweep that sourced the other values in this dict.
    "Elbow: Right Extension": None,
    "Elbow: Left Extension": None,
    # Hip Internal/External Rotation -- McCulloch et al. 2014,
    # professional pitchers (right-handed, n=77): Drive/stance leg IR
    # 32.2° ± 8.2°, ER 30.8° ± 9.7°; Plant/stride leg IR 30.8° ± 8.4°,
    # ER 36.3° ± 7.7° (stride leg runs higher in ER -- an adaptive
    # asymmetry the study found in most pitchers, not a per-leg data
    # entry error). Floors set ~1.5 SD below each leg's own mean.
    "Hip: Drive Leg Internal Rotation": 20,
    "Hip: Plant Leg Internal Rotation": 20,
    "Hip: Drive Leg External Rotation": 18,
    "Hip: Plant Leg External Rotation": 24,
    "Hip: Drive Leg Abduction": None,
    "Hip: Plant Leg Abduction": None,
    "Hip: Drive Leg Adduction": None,
    "Hip: Plant Leg Adduction": None,
    "Hip: Drive Leg Flexion": None,
    "Hip: Plant Leg Flexion": None,
    "Hip: Drive Leg Extension": None,
    "Hip: Plant Leg Extension": None,
}

# The 6 hip metrics above are entered as "Hip: Right {base}" / "Hip:
# Left {base}" (see seed_lookups.py's MOBILITY_ROM_TESTS), NOT as the
# "Hip: Drive Leg {base}" / "Hip: Plant Leg {base}" names used as keys
# in MOBILITY_ROM_THRESHOLDS above -- compute_mobility_rom_report
# resolves Right/Left -> Drive Leg/Plant Leg per player (via
# resolve_side_by_throws, same as GIRD/Total Arc) before doing the
# threshold lookup/status check, so this list is what drives that
# resolution loop.
HIP_ROM_BASE_METRICS = [
    "Internal Rotation", "External Rotation", "Abduction", "Adduction", "Flexion", "Extension",
]

# Shoulder Health bucket (Physical Development extension, reference
# only -- not in Total yet). Named "Shoulder Health" rather than "Arm
# Health" since nothing here measures the elbow yet -- rename (and
# fold in elbow metrics) once that's actually being tested, per
# Ryker's call.
#
# GIRD only for now, per Ryker's call. GIRD (Glenohumeral Internal
# Rotation Deficit) = non-throwing arm IR - throwing arm IR, in
# degrees -- the standard formula from the sports-medicine literature
# (Wilk et al./Burkhart's "disabled throwing shoulder" work): how much
# internal rotation the throwing shoulder has lost relative to the
# other side.
#
# Auto-calculated live from the two raw Internal Rotation fields on
# the Mobility & ROM sheet (see compute_gird_percentiles below) --
# NOT a separately, manually-entered value. Per Ryker's explicit call:
# he wants GIRD derived automatically once both IR measurements are
# collected, not typed in as its own number. Sourced from the same
# Right/Left Internal Rotation raw fields MOBILITY_SHOULDER_SIDED_
# FIELDS above already uses for the Mobility bucket, resolved to
# throwing/non-throwing per player the same way (resolve_side_by_
# throws) -- reusing them here for a second, different derived score
# (a bilateral deficit, not a raw angle) is intentional, not
# duplication.
#
# "Lower is better" -- a smaller deficit (closer to symmetric with the
# non-throwing arm) is healthier, reusing this file's existing
# lower-is-better formula (team_min / value * 100, same as sprint
# times) rather than inventing threshold-based scoring. Note: a GIRD
# of exactly 0 isn't the literal clinical ideal -- a small deficit is
# a normal throwing-arm adaptation -- like every bucket in this
# system, this is a team-relative ranking, not an absolute medical
# verdict.
GIRD_RIGHT_IR_TEST = "Shoulder: Right Internal Rotation"
GIRD_LEFT_IR_TEST = "Shoulder: Left Internal Rotation"

# Provisional Development Profile bands, expressed as a percentage
# imbalance between Output and Capacity (see compute_balance_pct below)
# -- NOT validated thresholds. Flagged in the design brief as a
# placeholder until there's enough DevelopmentProfileSnapshot-style
# history to set real cutoffs from the team's own distribution. Deliberately
# plain module constants, not a database config table -- matches how
# every other threshold in this file (subgroup membership, metric
# direction) is already just Python data, not DB-driven.
DEVELOPMENT_PROFILE_BANDS = {
    "balanced_max_abs_pct": 10,     # |balance_pct| <= this -> Balanced/Optimized (if not also Developing)
    "developing_score_floor": 60,   # both output_score AND capacity_score below this -> Developing, regardless of balance_pct
}

# Categories where data entry should be limited to ONLY the metrics in
# the bucket spreadsheet -- Ryker's explicit rule, so a coach entering
# e.g. Body Composition data isn't shown 15 extra InBody fields that
# have nothing to do with the bucket system. Arm Health is deliberately
# NOT included here -- Capacity draws from several of its fields, but
# it's meant to stay a broader, unrestricted clinical entry form (not
# narrowed to just bucket inputs), unlike Body Comp/Power/Strength/
# Speed which get filtered down to exactly the spreadsheet's fields.
# GIRD is no longer entered on Arm Health at all -- see
# compute_gird_percentiles below, it's now auto-calculated from the
# Mobility sheet's Internal Rotation fields instead.
BUCKET_RELEVANT_CATEGORIES = {
    "Body Composition", "Explosive Power", "Rotational Power",
    "Lower Body Strength", "Upper Body Strength", "Speed",
}


def get_bucket_test_names_for_category(category_name):
    """Every test name in the bucket system that belongs to the given
    category -- used to filter the entry form down to just these for
    BUCKET_RELEVANT_CATEGORIES. Returns an empty set for a category
    with no bucket-system metrics."""
    if category_name == "Body Composition":
        return set(BODY_COMP_ENTRY_FIELDS)
    if category_name == "Rotational Power":
        return {name for name, _ in POWER_SUBGROUPS["Med Ball Throw"]}
    if category_name == "Explosive Power":
        names = set()
        for sub_name, metrics in POWER_SUBGROUPS.items():
            if sub_name != "Med Ball Throw":  # that one's under Rotational Power in GBO's category structure
                names.update(name for name, _ in metrics)
        return names
    if category_name == "Lower Body Strength":
        return {name for name, _ in STRENGTH_SUBGROUPS["Lower Body Strength"]}
    if category_name == "Upper Body Strength":
        return {name for name, _ in STRENGTH_SUBGROUPS["Upper Body Strength"]}
    if category_name == "Speed":
        return {name for name, _ in SPEED_METRICS}
    return set()


def get_latest_values_by_player(session, test_name, _cache=None):
    """{player_id: value} -- each player's most recent result for this
    test type, across the whole roster -- ACTIVE AND INACTIVE both
    count toward the comparison pool (Ryker's explicit call, so last
    year's players' data still contributes to percentiles even though
    they're hidden from the current roster everywhere else in the
    app). Returns {} if the test type doesn't exist yet (e.g. not
    seeded).

    _cache: an optional pre-fetched {test_name: {player_id: value}}
    dict from _batch_fetch_latest_values() -- when provided and this
    test_name is in it, this skips the database round trip entirely
    and returns straight from memory. compute_bucket_system() below
    passes one in so a single player's full score rollup (~60 metrics)
    costs a couple of queries total instead of one (or two) queries
    PER METRIC -- that per-metric query loop was the actual cause of
    Assessments/Dashboard/My Assessments feeling slow (and, over a
    hosted DB connection with real network latency per round trip,
    occasionally slow enough to trip the browser's websocket timeout
    and show "Disconnected from the server"). Falls back to a live
    query when _cache is None or doesn't have this test_name, so this
    function is still correct as a plain standalone call."""
    if _cache is not None and test_name in _cache:
        return _cache[test_name]

    test_type = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == test_name).first()
    if test_type is None:
        return {}
    rows = (
        session.query(AssessmentResult, Assessment.player_id, Assessment.assessment_date)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
        .join(Player, Assessment.player_id == Player.player_id)
        .filter(AssessmentResult.test_type_id == test_type.test_type_id)
        .all()
    )
    latest = {}
    for result, player_id, assessment_date in rows:
        if player_id not in latest or assessment_date > latest[player_id][1]:
            latest[player_id] = (float(result.value), assessment_date)
    return {pid: v for pid, (v, _) in latest.items()}


def _all_bucket_test_names():
    """Every AssessmentTestType name this file's scoring touches,
    anywhere -- unioned once so compute_bucket_system() can batch-fetch
    all of them in a couple of queries instead of one round trip per
    metric (see _batch_fetch_latest_values). Keep this in sync any time
    a new (test_name, direction) pair is added to one of the subgroup
    dicts/lists above -- a name missing from here just means that one
    metric quietly falls back to its own live query instead of using
    the batch, not a correctness problem."""
    names = set()
    names.update(name for name, _ in BODY_COMP_DISPLAY_METRICS)
    for metrics in POWER_SUBGROUPS.values():
        names.update(name for name, _ in metrics)
    for metrics in STRENGTH_SUBGROUPS.values():
        names.update(name for name, _ in metrics)
    names.update(name for name, _ in SPEED_METRICS)
    for metrics in CAPACITY_SUBGROUPS.values():
        names.update(name for name, _ in metrics)
    # Shoulder/Elbow ROM: entered anatomically, so the threshold dict's
    # own keys ARE the entry field names.
    names.update(name for name in MOBILITY_ROM_THRESHOLDS if not name.startswith("Hip:"))
    # Hip ROM: threshold dict keys are Drive Leg/Plant Leg (role-based),
    # but the actual entry fields are Right/Left -- see HIP_ROM_BASE_
    # METRICS' comment above.
    for base_metric in HIP_ROM_BASE_METRICS:
        names.add(f"Hip: Right {base_metric}")
        names.add(f"Hip: Left {base_metric}")
    return names


def _batch_fetch_latest_values(session, test_names):
    """Batched replacement for calling get_latest_values_by_player()
    once per metric -- the naive per-metric loop compute_bucket_system()
    used to run cost roughly 60 metrics x up to 2 queries each, more
    than a hundred sequential round trips to the database for one
    player's page load. This does the same lookup for every requested
    test name in exactly 2 queries total: one to resolve test_type_id +
    unit for all of them, one to pull every result row for all of them
    -- then groups down to latest-per-player in Python, which is fast.

    Returns (values_by_test_name, units_by_test_name):
      - values_by_test_name: {test_name: {player_id: value}} -- every
        SEEDED test_name from the input is guaranteed a key here (an
        empty dict if it's seeded but has no results yet), so callers
        never need to fall back to a live query for a name that's
        simply data-less. A test_name that isn't seeded at all (no
        AssessmentTestType row) is absent, matching
        get_latest_values_by_player's existing "not found" behavior.
      - units_by_test_name: {test_name: unit_or_None}, for the same
        seeded names -- avoids a second redundant per-metric query
        compute_metric_percentiles used to run just to read the unit.
    """
    test_names = list(set(test_names))
    if not test_names:
        return {}, {}

    type_rows = (
        session.query(AssessmentTestType.test_type_id, AssessmentTestType.test_name, AssessmentTestType.unit)
        .filter(AssessmentTestType.test_name.in_(test_names))
        .all()
    )
    name_by_type_id = {row.test_type_id: row.test_name for row in type_rows}
    units_by_test_name = {row.test_name: row.unit for row in type_rows}
    type_ids = list(name_by_type_id.keys())
    if not type_ids:
        return {}, {}

    result_rows = (
        session.query(AssessmentResult.test_type_id, AssessmentResult.value, Assessment.player_id, Assessment.assessment_date)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
        .filter(AssessmentResult.test_type_id.in_(type_ids))
        .all()
    )

    # {test_type_id: {player_id: (value, date)}} -- latest per player, per test
    latest_by_type_id = {}
    for test_type_id, value, player_id, assessment_date in result_rows:
        bucket = latest_by_type_id.setdefault(test_type_id, {})
        if player_id not in bucket or assessment_date > bucket[player_id][1]:
            bucket[player_id] = (float(value), assessment_date)

    # Every seeded name gets an entry (possibly empty) -- see docstring.
    values_by_test_name = {name: {} for name in name_by_type_id.values()}
    for test_type_id, by_player in latest_by_type_id.items():
        test_name = name_by_type_id.get(test_type_id)
        if test_name is not None:
            values_by_test_name[test_name] = {pid: v for pid, (v, _) in by_player.items()}

    return values_by_test_name, units_by_test_name


def compute_percentile(value, team_values, direction):
    """The confirmed formula: value/max*100 (higher-better) or
    min/value*100 (lower-better), rounded to a whole number. team_values
    should include the player's own value. Returns None if there's
    nothing to compare against (no team data, or value is 0 for a
    lower-is-better metric)."""
    if not team_values or value is None:
        return None
    if direction == "higher":
        team_max = max(team_values)
        if team_max == 0:
            return None
        return round((value / team_max) * 100)
    else:
        team_min = min(team_values)
        if value == 0:
            return None
        return round((team_min / value) * 100)


def compute_metric_percentiles(session, player_id, metrics, _cache=None, _units=None):
    """metrics: [(test_name, direction), ...]. Returns
    {test_name: {"raw": value, "percentile": pct, "unit": unit}} for
    whichever of these metrics the player actually has a result for.

    _cache/_units: optional pre-fetched dicts from
    _batch_fetch_latest_values() -- see get_latest_values_by_player's
    docstring. When provided, this skips both the per-metric results
    query AND the per-metric unit lookup query."""
    out = {}
    for test_name, direction in metrics:
        by_player = get_latest_values_by_player(session, test_name, _cache=_cache)
        if player_id not in by_player:
            continue
        value = by_player[player_id]
        pct = compute_percentile(value, list(by_player.values()), direction)
        if _units is not None and test_name in _units:
            unit = _units[test_name]
        else:
            test_type = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == test_name).first()
            unit = test_type.unit if test_type else None
        out[test_name] = {"raw": value, "percentile": pct, "unit": unit}
    return out


def get_player_throws_map(session):
    """{player_id: 'R'/'L'/None} for every player -- active and
    inactive, matching get_latest_values_by_player's scope. Used to
    resolve anatomical Right/Left mobility entries to throwing/
    non-throwing arm per player."""
    return {p.player_id: p.throws for p in session.query(Player).all()}


def resolve_side_by_throws(session, right_test_name, left_test_name, _cache=None, _throws_map=None):
    """Takes a raw Right/Left pair of AssessmentTestType names (e.g.
    "Shoulder: Right External Rotation" / "...Left...") and resolves
    each player's own THROWING-ARM value and NON-THROWING-ARM value
    from the correct raw column based on that player's Player.throws
    ('R' or 'L').

    This is the core of the Right/Left -> Throwing/Non-Throwing
    translation used by GIRD and Total Arc (compute_gird_percentiles/
    compute_mobility_rom_report below): a right-handed pitcher's
    throwing arm is his Right
    column, a left-handed pitcher's throwing arm is his Left column --
    so the "Throwing Arm X" comparison pool is a mix of different raw
    columns depending on each player's own handedness.

    Players with no Player.throws on file are skipped entirely (can't
    resolve a side without knowing handedness) -- not defaulted to
    either side, since guessing would silently mis-score them.

    _cache/_throws_map: optional pre-fetched data (see
    get_latest_values_by_player/get_player_throws_map) -- when
    provided, skips their live queries.

    Returns (throwing_by_player, non_throwing_by_player), each a plain
    {player_id: value} dict, only including players who have both a
    known throws side AND a raw value for the appropriate column."""
    right_by_player = get_latest_values_by_player(session, right_test_name, _cache=_cache)
    left_by_player = get_latest_values_by_player(session, left_test_name, _cache=_cache)
    throws_map = _throws_map if _throws_map is not None else get_player_throws_map(session)

    throwing_by_player = {}
    non_throwing_by_player = {}
    for pid, throws in throws_map.items():
        if throws == "R":
            throwing_side, non_throwing_side = right_by_player, left_by_player
        elif throws == "L":
            throwing_side, non_throwing_side = left_by_player, right_by_player
        else:
            continue
        if pid in throwing_side:
            throwing_by_player[pid] = throwing_side[pid]
        if pid in non_throwing_side:
            non_throwing_by_player[pid] = non_throwing_side[pid]
    return throwing_by_player, non_throwing_by_player


def compute_gird_percentiles(session, player_id, _cache=None, _throws_map=None):
    """GIRD (Glenohumeral Internal Rotation Deficit), computed live --
    non-throwing arm IR minus throwing arm IR, in degrees -- from the
    Right/Left Internal Rotation fields (GIRD_RIGHT_IR_TEST /
    GIRD_LEFT_IR_TEST above), resolved to throwing/non-throwing per
    player via resolve_side_by_throws. NOT a separately-entered value.
    Per Ryker's explicit call: enter both IR measurements once, GIRD
    derives automatically, no manual GIRD entry step needed at all.

    "Lower is better" -- team_min / value * 100, same formula and
    convention as every other lower-is-better metric in this file (see
    compute_percentile). Only includes players who have a known
    Player.throws AND both raw IR values on file -- same "skip if
    incomplete" behavior compute_metric_percentiles already has for a
    plain single-field metric.

    Returns {"Shoulder ROM: GIRD": {"raw": ..., "percentile": ...,
    "unit": "°"}} (empty dict if this player can't be resolved) --
    same shape compute_metric_percentiles returns, so render_metric_bars
    and the rest of the display layer don't need to know GIRD is
    computed differently under the hood. Kept the "Shoulder ROM: GIRD"
    label (its old Arm Health field name) purely for display
    continuity -- it's no longer read from that stored field."""
    throwing_ir, non_throwing_ir = resolve_side_by_throws(
        session, GIRD_RIGHT_IR_TEST, GIRD_LEFT_IR_TEST, _cache=_cache, _throws_map=_throws_map
    )
    gird_by_player = {
        pid: non_throwing_ir[pid] - throwing_ir[pid]
        for pid in throwing_ir
        if pid in non_throwing_ir
    }
    if player_id not in gird_by_player:
        return {}
    pct = compute_percentile(gird_by_player[player_id], list(gird_by_player.values()), "lower")
    return {"Shoulder ROM: GIRD": {"raw": gird_by_player[player_id], "percentile": pct, "unit": "°"}}


SHOULDER_RIGHT_ER_TEST = "Shoulder: Right External Rotation"
SHOULDER_LEFT_ER_TEST = "Shoulder: Left External Rotation"
SHOULDER_RIGHT_FLEXION_TEST = "Shoulder: Right Flexion"
SHOULDER_LEFT_FLEXION_TEST = "Shoulder: Left Flexion"
SHOULDER_RIGHT_EXTENSION_TEST = "Shoulder: Right Extension"
SHOULDER_LEFT_EXTENSION_TEST = "Shoulder: Left Extension"


# ---------------------------------------------------------------------
# Shoulder ROM compound classification (Aug 2026, per Ryker's detailed
# ROM redesign spec -- "Phase 1: Shoulder logic"). This is a DIFFERENT
# kind of check than everything in MOBILITY_ROM_THRESHOLDS above: those
# are single-value floor checks (one raw number vs. one threshold).
# These are DERIVED, bilateral, and in GIRD's case CONTEXTUAL --
# they're computed from two raw fields (or, for GIRD, from another
# derived value too) and explicitly must NOT flag a normal throwing
# adaptation just because a same-side absolute number looks "low."
# See compute_shoulder_rom_profile below for where these get applied.
#
# Each entry carries the full metadata Ryker's spec asked for
# (population/level/protocol/citation/evidence strength/notes) so this
# can grow into a real reference-standards table later without a
# reshape -- for now it's still a plain Python dict (per Ryker's call:
# a structured config file now, a DB-backed staff-editable table is a
# later phase, not this one).
#
# "direction" controls which side of the bound is "bad":
#   "ceiling" -- LOWER is better (a magnitude/deficit metric: Total Arc
#     Deficit, GIRD). value <= green_threshold -> green, <=
#     yellow_threshold -> yellow, above that -> red.
#   "floor" -- HIGHER is better (ERG: the throwing arm is EXPECTED to
#     gain ER, so a small or negative gain is the concerning direction,
#     the reverse of every other metric in this file). value >=
#     green_threshold -> green, >= yellow_threshold -> yellow, below
#     that -> red.
SHOULDER_ROM_STANDARDS = {
    "Total Arc Deficit": {
        "variable": "Throwing Arm Total Arc Deficit vs. Non-Throwing Arm",
        "population": "Baseball pitchers",
        "position": "Pitcher",
        "level_of_play": "College (Ryker's call -- not level-differentiated yet)",
        "direction": "ceiling",
        "green_threshold": 5,   # <=5 deg deficit
        "yellow_threshold": 10,  # <=10 deg deficit (>10 = red)
        "unit": "°",
        "measurement_protocol": (
            "Total Arc = Shoulder Internal Rotation + Shoulder External Rotation, each arm. "
            "Total Arc Deficit = Throwing Arm Total Arc - Non-Throwing Arm Total Arc, evaluated "
            "one-directionally (only a THROWING-side loss is flagged -- a throwing arm with MORE "
            "total arc than the non-throwing arm is not penalized)."
        ),
        "research_source": (
            "Concept -- total rotational motion, not isolated IR, is the more clinically meaningful "
            "shoulder ROM measure in throwing athletes -- per Wilk et al. 2011. The specific 5/10 "
            "degree cut points here are a GBO starting point pending stronger baseball-specific "
            "total-arc-deficit literature, not a number pulled directly from that citation."
        ),
        "citation": "Wilk KE, et al. Correlation of glenohumeral internal rotation deficit and total rotation with shoulder injuries in professional baseball pitchers. Am J Sports Med. 2011;39(2):329-335.",
        "evidence_strength": "Moderate (concept well-supported; exact cut points are GBO-set, not directly cited)",
        "notes": "This is the primary shoulder red flag per Ryker's spec -- total arc loss matters more than isolated IR loss alone.",
    },
    "GIRD": {
        "variable": "GIRD (Glenohumeral Internal Rotation Deficit), contextualized by Total Arc",
        "population": "Baseball pitchers",
        "position": "Pitcher",
        "level_of_play": "College (Ryker's call -- not level-differentiated yet)",
        "direction": "ceiling",
        "green_threshold": 15,
        "green_inclusive": False,  # Ryker's spec: "Green: <15°" (strict), vs. Total Arc Deficit's inclusive "0-5°" -- these two tables use different boundary conventions in his own spec, kept exact rather than normalized to one style
        "yellow_threshold": 20,
        "unit": "°",
        "measurement_protocol": "Non-Throwing Arm Internal Rotation - Throwing Arm Internal Rotation, at 90° abduction.",
        "research_source": "Wilk et al. 2011; Burkhart's 'disabled throwing shoulder' GIRD work.",
        "citation": "Wilk KE, et al. Am J Sports Med. 2011;39(2):329-335.",
        "evidence_strength": "Moderate -- GIRD alone is a widely-cited screen, but per the same literature it should be read alongside Total Arc, not in isolation (see 'contextual override' below).",
        "notes": (
            "CONTEXTUAL OVERRIDE (per Ryker's explicit call): a raw-threshold GIRD status of yellow or "
            "red is downgraded ONE tier (red->yellow, yellow->green) whenever this player's Total Arc "
            "Deficit status is green -- i.e. total rotational motion is preserved. Isolated IR loss "
            "with a preserved total arc is a common, likely-benign throwing adaptation, not a true "
            "mobility deficit -- flagging it the same as a GIRD paired with real total-arc loss would "
            "over-flag normal throwing shoulders. See compute_shoulder_rom_profile for where this is "
            "applied and _shoulder_rom_explanation for how it's worded to the user."
        ),
    },
    "External Rotation Gain (ERG)": {
        "variable": "Throwing Arm ER Gain vs. Non-Throwing Arm (Throwing ER - Non-Throwing ER)",
        "population": "Baseball pitchers",
        "position": "Pitcher",
        "level_of_play": "College (Ryker's call -- not level-differentiated yet)",
        "direction": "floor",  # inverted vs. everything else here -- LOWER is worse
        "green_threshold": 5,   # >=5 deg gain = expected adaptation present
        "yellow_threshold": 0,  # 0-5 deg gain = monitor; <0 (throwing arm has LESS ER) = red
        "unit": "°",
        "measurement_protocol": "Throwing Arm External Rotation - Non-Throwing Arm External Rotation, at 90° abduction.",
        "research_source": (
            "The throwing shoulder developing additional external rotation is a well-documented "
            "adaptation in the literature; the specific 5°/0° cut points are GBO's own interpretation "
            "of Ryker's spec ('pay particular attention when throwing ER is <5° greater than "
            "non-throwing ER') -- not a number drawn from a specific cited study. Treat as a starting "
            "point to refine once Pitt State's own pitcher data accumulates."
        ),
        "citation": None,
        "evidence_strength": "Low-moderate (adaptation concept is well-supported; exact cut points are a GBO estimate, not directly cited)",
        "notes": "Direction is inverted vs. every other metric here -- a LOWER (or negative) ERG is the concerning direction, since it means the expected throwing-arm adaptation didn't develop.",
    },
}


def _shoulder_rom_classify(value, standard):
    """Applies one SHOULDER_ROM_STANDARDS entry's green/yellow/red
    bounds to a computed value. direction="ceiling" -> lower is better
    (value <= green -> green [or < green if the standard sets
    green_inclusive=False -- Ryker's spec worded GIRD's green cutoff as
    a strict "<15°" but Total Arc Deficit's as an inclusive "0-5°", so
    this is per-standard, not normalized to one style], <= yellow ->
    yellow, else red). direction="floor" -> higher is better (value >=
    green -> green, >= yellow -> yellow, else red)."""
    green, yellow, direction = standard["green_threshold"], standard["yellow_threshold"], standard["direction"]
    if direction == "ceiling":
        is_green = value < green if standard.get("green_inclusive", True) is False else value <= green
        if is_green:
            return "green"
        if value <= yellow:
            return "yellow"
        return "red"
    if value >= green:
        return "green"
    if value >= yellow:
        return "yellow"
    return "red"


_STATUS_DOWNGRADE = {"red": "yellow", "yellow": "green", "green": "green"}


def _shoulder_rom_explanation(metric_key, raw, status, extra=None):
    """Plain-language 'why this matters' text for one Shoulder ROM
    compound metric + its final status, matching the tone/format of
    Ryker's spec examples exactly (numbers first, then a short causal
    sentence -- never language stating an injury WILL happen; red uses
    'associated with' / 'priority review' framing only, per his
    explicit safety requirement). Returns (explanation, recommendation)
    -- recommendation is None for green (nothing to act on)."""
    extra = extra or {}
    if metric_key == "Total Arc Deficit":
        deficit = max(0, -raw)  # raw = throwing_arc - non_throwing_arc; deficit only counts a THROWING-side loss
        if status == "green":
            return (
                f"Total rotational motion is well-preserved between the throwing and non-throwing "
                f"shoulders (throwing-side difference: {raw:+.0f}°).",
                None,
            )
        if status == "yellow":
            return (
                f"The throwing shoulder has {deficit:.0f}° less total rotational motion than the "
                f"non-throwing shoulder. Worth monitoring as part of this player's development plan.",
                "Consider targeted mobility work and re-check at the next testing cycle.",
            )
        return (
            f"The throwing shoulder has {deficit:.0f}° less total rotational motion than the "
            f"non-throwing shoulder. A substantial loss of total arc is more concerning than internal "
            f"rotation loss alone.",
            "Red Flag — Priority Review: recommend evaluation by appropriate performance/sports medicine staff.",
        )
    if metric_key == "GIRD":
        tad_status = extra.get("total_arc_deficit_status")
        downgraded = extra.get("downgraded", False)
        tad_raw = extra.get("total_arc_deficit_raw")
        tad_label = f"{-max(0, -tad_raw):.0f}°" if tad_raw is not None else "—"  # signed throwing-vs-non-throwing diff, for display
        if downgraded:
            return (
                f"The throwing shoulder has reduced internal rotation (GIRD: {raw:.0f}°), but total "
                f"rotational motion is preserved (Total Arc difference: {tad_label}). This pattern may "
                f"represent a normal throwing adaptation rather than a mobility deficit.",
                None,
            )
        if status == "green":
            return (f"GIRD ({raw:.0f}°) is within the expected range for a healthy throwing shoulder.", None)
        if status == "yellow":
            return (
                f"GIRD is {raw:.0f}°, and total rotational motion is not fully preserved "
                f"(Total Arc difference: {tad_label}). Worth monitoring alongside total arc at the "
                f"next testing cycle.",
                "Consider targeted internal rotation mobility work and re-check at the next testing cycle.",
            )
        return (
            f"GIRD is {raw:.0f}°, and total rotational motion is also compromised "
            f"(Total Arc difference: {tad_label}). This combination -- IR loss WITHOUT a preserved "
            f"total arc -- is a more concerning pattern than an isolated internal rotation loss.",
            "Red Flag — Priority Review: recommend evaluation by appropriate performance/sports medicine staff.",
        )
    if metric_key == "External Rotation Gain (ERG)":
        if status == "green":
            return (
                f"The throwing shoulder shows {raw:.0f}° more external rotation than the non-throwing "
                f"shoulder, consistent with the expected throwing-arm adaptation.",
                None,
            )
        if status == "yellow":
            return (
                f"The throwing shoulder shows only {raw:.0f}° more external rotation than the "
                f"non-throwing shoulder -- less than the gain typically seen in throwing athletes.",
                "Worth incorporating into this player's mobility development plan and re-checking at the next testing cycle.",
            )
        return (
            f"The throwing shoulder does NOT show the expected external rotation gain -- it actually "
            f"has {abs(raw):.0f}° LESS external rotation than the non-throwing shoulder, an atypical "
            f"pattern worth flagging for review.",
            "Red Flag — Priority Review: recommend evaluation by appropriate performance/sports medicine staff.",
        )
    return ("", None)


_SHOULDER_ROM_STATUS_LABELS = {"green": "Good", "yellow": "Monitor", "red": "Red Flag — Priority Review"}


def compute_shoulder_rom_profile(session, player_id, _cache=None, _throws_map=None):
    """Shoulder ROM 'Phase 1' compound classification, per Ryker's Aug
    2026 ROM redesign spec -- Total Arc Deficit, GIRD (contextualized
    by Total Arc), and External Rotation Gain, each with a real
    red/yellow/green status, a plain-language explanation, and a
    recommendation (yellow/red only). Also includes Flexion/Extension
    side-to-side differences as REFERENCE-ONLY rows (status=None) --
    no baseball-specific research threshold exists for these yet, same
    "don't fabricate a flag" rule this file uses everywhere else (see
    MOBILITY_ROM_THRESHOLDS' docstring); they still show the raw
    difference so staff can watch for a real research-backed cutoff or
    a meaningful CHANGE over time later.

    Returns a list of row dicts, richer than compute_mobility_rom_
    report's plain rows: {"test_name", "raw", "unit", "threshold":
    None (these aren't a single-value floor check), "status",
    "status_label": the spec's own wording ("Good"/"Monitor"/"Red Flag
    — Priority Review") instead of the simpler existing "Clear"/
    "Caution"/"Below threshold" pill wording -- deliberately distinct
    since these are the injury-risk-aware compound metrics Ryker's
    spec specifically asked to word this way, "explanation", and
    "recommendation" (None unless yellow/red).

    Only includes rows for players who have all the needed raw values
    on file AND a known Player.throws (same "can't resolve a side
    without knowing handedness" limitation the rest of this Shoulder/
    Hip resolution logic already has)."""
    throwing_ir, non_throwing_ir = resolve_side_by_throws(
        session, GIRD_RIGHT_IR_TEST, GIRD_LEFT_IR_TEST, _cache=_cache, _throws_map=_throws_map
    )
    throwing_er, non_throwing_er = resolve_side_by_throws(
        session, SHOULDER_RIGHT_ER_TEST, SHOULDER_LEFT_ER_TEST, _cache=_cache, _throws_map=_throws_map
    )
    throwing_flex, non_throwing_flex = resolve_side_by_throws(
        session, SHOULDER_RIGHT_FLEXION_TEST, SHOULDER_LEFT_FLEXION_TEST, _cache=_cache, _throws_map=_throws_map
    )
    throwing_ext, non_throwing_ext = resolve_side_by_throws(
        session, SHOULDER_RIGHT_EXTENSION_TEST, SHOULDER_LEFT_EXTENSION_TEST, _cache=_cache, _throws_map=_throws_map
    )

    out = []

    has_rotation = player_id in throwing_ir and player_id in non_throwing_ir and player_id in throwing_er and player_id in non_throwing_er
    total_arc_deficit_status = None
    if has_rotation:
        throwing_arc = throwing_ir[player_id] + throwing_er[player_id]
        non_throwing_arc = non_throwing_ir[player_id] + non_throwing_er[player_id]
        tad_raw = throwing_arc - non_throwing_arc  # negative = throwing-side loss
        tad_standard = SHOULDER_ROM_STANDARDS["Total Arc Deficit"]
        total_arc_deficit_status = _shoulder_rom_classify(max(0, -tad_raw), tad_standard)
        explanation, recommendation = _shoulder_rom_explanation("Total Arc Deficit", tad_raw, total_arc_deficit_status)
        out.append({
            "test_name": "Shoulder: Total Arc Deficit (Throwing vs. Non-Throwing)", "raw": tad_raw, "unit": "°",
            "threshold": None, "status": total_arc_deficit_status,
            "status_label": _SHOULDER_ROM_STATUS_LABELS[total_arc_deficit_status],
            "explanation": explanation, "recommendation": recommendation,
        })

        gird_raw = non_throwing_ir[player_id] - throwing_ir[player_id]
        gird_standard = SHOULDER_ROM_STANDARDS["GIRD"]
        base_status = _shoulder_rom_classify(gird_raw, gird_standard)
        downgraded = total_arc_deficit_status == "green" and base_status in ("yellow", "red")
        gird_status = _STATUS_DOWNGRADE[base_status] if downgraded else base_status
        explanation, recommendation = _shoulder_rom_explanation(
            "GIRD", gird_raw, gird_status,
            extra={"total_arc_deficit_status": total_arc_deficit_status, "total_arc_deficit_raw": tad_raw, "downgraded": downgraded},
        )
        out.append({
            "test_name": "Shoulder: GIRD (contextualized by Total Arc)", "raw": gird_raw, "unit": "°",
            "threshold": None, "status": gird_status,
            "status_label": _SHOULDER_ROM_STATUS_LABELS[gird_status],
            "explanation": explanation, "recommendation": recommendation,
        })

        erg_raw = throwing_er[player_id] - non_throwing_er[player_id]
        erg_standard = SHOULDER_ROM_STANDARDS["External Rotation Gain (ERG)"]
        erg_status = _shoulder_rom_classify(erg_raw, erg_standard)
        explanation, recommendation = _shoulder_rom_explanation("External Rotation Gain (ERG)", erg_raw, erg_status)
        out.append({
            "test_name": "Shoulder: External Rotation Gain (ERG)", "raw": erg_raw, "unit": "°",
            "threshold": None, "status": erg_status,
            "status_label": _SHOULDER_ROM_STATUS_LABELS[erg_status],
            "explanation": explanation, "recommendation": recommendation,
        })

    if player_id in throwing_flex and player_id in non_throwing_flex:
        diff = throwing_flex[player_id] - non_throwing_flex[player_id]
        out.append({
            "test_name": "Shoulder: Flexion Difference (Throwing vs. Non-Throwing)", "raw": diff, "unit": "°",
            "threshold": None, "status": None, "status_label": None, "explanation": None, "recommendation": None,
        })
    if player_id in throwing_ext and player_id in non_throwing_ext:
        diff = throwing_ext[player_id] - non_throwing_ext[player_id]
        out.append({
            "test_name": "Shoulder: Extension Difference (Throwing vs. Non-Throwing)", "raw": diff, "unit": "°",
            "threshold": None, "status": None, "status_label": None, "explanation": None, "recommendation": None,
        })

    return out


# ---------------------------------------------------------------------
# Hip ROM derived metrics (Aug 2026, Phase 2 of Ryker's ROM redesign
# spec). Unlike Shoulder Phase 1, NONE of these get a red/yellow/green
# status -- per Ryker's own explicit instruction: "For hip ROM, do NOT
# invent injury-risk thresholds when strong baseball-specific evidence
# does not exist. Instead distinguish between Normative comparison and
# Evidence-supported red flag." The absolute-value Hip IR/ER floors
# already in MOBILITY_ROM_THRESHOLDS (McCulloch et al. 2014) ARE kept
# as-is -- that's a real (if purely descriptive, not injury-outcome)
# baseball-pitcher normative dataset, unlike anything found for hip
# TOTAL rotation or hip ASYMMETRY specifically. No baseball-specific
# research was found correlating hip total rotation or side-to-side
# hip differences with injury incidence, nor even a normative
# mean/SD for those specific derived numbers (as opposed to the raw
# per-leg IR/ER means McCulloch et al. does report) -- so per the
# same "don't fabricate a flag" rule this file uses everywhere else,
# these are shown as REFERENCE-ONLY values (status=None), not colored.
# If/when real baseball hip-ROM norms exist (e.g. once Pitt State's
# own multi-year data is usable, or new published research), these can
# gain real thresholds the same way Shoulder's did -- see
# SHOULDER_ROM_STANDARDS for that pattern.
_HIP_REFERENCE_NOTE = (
    "Reference value only -- no baseball-specific hip {label} threshold (injury-associated or "
    "normative) has been established in the literature yet. Shown to track change over time and "
    "support staff's own clinical judgment, not as a pass/fail flag."
)


def compute_hip_rom_profile(session, player_id, _cache=None, _throws_map=None):
    """Hip ROM derived values, per Ryker's ROM redesign spec: Drive Leg
    / Plant Leg Total Rotation (IR + ER per leg) and side-to-side
    differences for IR, ER, Total Rotation, Abduction, and Adduction.
    ALL reference-only (status=None, no color) -- see this section's
    module comment for why (no baseball-specific injury OR normative
    threshold exists for these specific derived numbers, unlike the
    raw per-leg IR/ER absolute floors in MOBILITY_ROM_THRESHOLDS).

    Differences are Drive Leg - Plant Leg throughout (positive = drive
    leg has more of that quality), matching the Throwing - Non-Throwing
    sign convention compute_shoulder_rom_profile uses above.

    Only includes rows for players who have both raw values needed AND
    a known Player.throws (can't resolve Drive/Plant without knowing
    handedness -- same limitation the rest of this file's Hip/Shoulder
    resolution already has). Returns a list of row dicts in the same
    shape compute_shoulder_rom_profile's rows use (test_name/raw/unit/
    threshold/status/status_label/explanation/recommendation) so
    build_mobility_rom_report renders them identically."""
    # Only resolves the 4 metrics this function actually uses (IR/ER/
    # Abduction/Adduction) -- NOT all of HIP_ROM_BASE_METRICS, which
    # also includes Flexion/Extension (used by the plain-threshold Hip
    # rows elsewhere in compute_mobility_rom_report, not here -- no
    # spec-requested derived Hip Flexion/Extension values exist).
    resolved = {}
    for base_metric in ("Internal Rotation", "External Rotation", "Abduction", "Adduction"):
        resolved[base_metric] = resolve_side_by_throws(
            session, f"Hip: Right {base_metric}", f"Hip: Left {base_metric}", _cache=_cache, _throws_map=_throws_map
        )

    out = []

    def _ref_row(test_name, raw, label, signed=True):
        # signed=False for the two Total Rotation rows -- those are
        # plain magnitudes (never negative), not a difference, so a
        # "+62°"-style leading plus sign would be visual noise; every
        # other row here IS a Drive-vs-Plant difference where the sign
        # is the whole point, so that's the default.
        row = {
            "test_name": test_name, "raw": raw, "unit": "°", "threshold": None, "status": None,
            "status_label": None, "explanation": _HIP_REFERENCE_NOTE.format(label=label), "recommendation": None,
        }
        if not signed:
            row["signed"] = False
        out.append(row)

    drive_ir, plant_ir = resolved["Internal Rotation"]
    drive_er, plant_er = resolved["External Rotation"]
    has_rotation = player_id in drive_ir and player_id in plant_ir and player_id in drive_er and player_id in plant_er
    if has_rotation:
        drive_total = drive_ir[player_id] + drive_er[player_id]
        plant_total = plant_ir[player_id] + plant_er[player_id]
        _ref_row("Hip: Drive Leg Total Rotation", drive_total, "Drive Leg Total Rotation", signed=False)
        _ref_row("Hip: Plant Leg Total Rotation", plant_total, "Plant Leg Total Rotation", signed=False)
        _ref_row("Hip: Internal Rotation Difference (Drive vs. Plant)", drive_ir[player_id] - plant_ir[player_id], "Internal Rotation asymmetry")
        _ref_row("Hip: External Rotation Difference (Drive vs. Plant)", drive_er[player_id] - plant_er[player_id], "External Rotation asymmetry")
        _ref_row("Hip: Total Rotation Difference (Drive vs. Plant)", drive_total - plant_total, "Total Rotation asymmetry")

    drive_abd, plant_abd = resolved["Abduction"]
    if player_id in drive_abd and player_id in plant_abd:
        _ref_row("Hip: Abduction Difference (Drive vs. Plant)", drive_abd[player_id] - plant_abd[player_id], "Abduction asymmetry")

    drive_add, plant_add = resolved["Adduction"]
    if player_id in drive_add and player_id in plant_add:
        _ref_row("Hip: Adduction Difference (Drive vs. Plant)", drive_add[player_id] - plant_add[player_id], "Adduction asymmetry")

    return out


# How far above a metric's MOBILITY_ROM_THRESHOLDS floor counts as
# "yellow" (caution) rather than "green" (clear) -- a flat degree
# buffer applied to every metric, per Ryker's call. Red is still
# "below the configured threshold" exactly as before; this just splits
# what used to be a single "met" (green) result into two tiers: yellow
# for raw values that clear the floor but only just, green for
# comfortably above it. A metric with no configured threshold (None in
# MOBILITY_ROM_THRESHOLDS) has no red/yellow/green status at all --
# same "don't fabricate a flag" rule as before. Bump this one number
# to widen/narrow the caution band for every metric at once; if a
# metric ever needs its own buffer instead of this shared one, give it
# a per-metric override rather than making this a dict.
MOBILITY_ROM_YELLOW_BUFFER = 10


def _mobility_rom_status(raw, threshold):
    """red/yellow/green/None for one raw value against its threshold
    -- None (no status) if threshold is None (not configured yet), red
    if below the threshold, yellow if within MOBILITY_ROM_YELLOW_BUFFER
    degrees above it, green otherwise."""
    if threshold is None:
        return None
    if raw < threshold:
        return "red"
    if raw < threshold + MOBILITY_ROM_YELLOW_BUFFER:
        return "yellow"
    return "green"


def compute_mobility_rom_report(session, player_id, _cache=None, _throws_map=None):
    """Red/yellow/green Mobility & ROM report -- replaces percentile
    scoring for this section entirely, per Ryker's explicit call (see
    MOBILITY_ROM_THRESHOLDS' docstring for the full rationale).

    Shoulder/Elbow: for every non-hip test_name in MOBILITY_ROM_
    THRESHOLDS, looks up this player's latest value (if any) directly
    (entered anatomically, Right/Left, no resolution needed) and
    statuses it via _mobility_rom_status.

    Hip: entered as Right/Left (see HIP_ROM_BASE_METRICS' comment for
    why), resolved per player to Drive Leg/Plant Leg via
    resolve_side_by_throws (drive leg = throwing-side leg, plant leg =
    glove-side leg) before the threshold lookup/status check -- same
    Player.throws-based resolution GIRD/Total Arc already use. A player
    with no Player.throws on file won't have hip ROM rows here at all
    (can't resolve a side without knowing handedness).

    Then appends Throwing Arm / Non-Throwing Arm Total Arc (External
    Rotation + Internal Rotation for that arm -- the standard "Total
    Arc of Motion" shoulder ROM measure, per Wilk et al. 2011:
    throwing-arm mean ~190° ± 15°, expected to stay roughly symmetric
    with the non-throwing arm) as two more raw reference rows (always
    threshold=None/status=None).

    Finally appends compute_shoulder_rom_profile's rows -- Total Arc
    Deficit, GIRD (contextualized by Total Arc), External Rotation
    Gain, and Flexion/Extension side-to-side differences (Aug 2026,
    Ryker's ROM redesign spec, "Phase 1: Shoulder logic"). These carry
    real red/yellow/green statuses plus "explanation"/"recommendation"/
    "status_label" keys the plain rows above don't have -- see that
    function's docstring. build_mobility_rom_report in bucket_display.py
    renders whichever keys are present per row, so this doesn't break
    the plain rows' simpler shape.

    Returns a list of dicts (only for metrics/sides with a raw value
    on file for this player -- no blank rows), each shaped at minimum:
      {"test_name": ..., "raw": ..., "unit": "°",
       "threshold": <float or None>, "status": "red"/"yellow"/"green"/None}
    (compute_shoulder_rom_profile's rows add "status_label",
    "explanation", "recommendation" on top of this). Ordered Shoulder,
    Elbow, Hip (Drive Leg then Plant Leg per metric, in HIP_ROM_BASE_
    METRICS' order), Total Arc reference rows, then the new compound
    Shoulder rows last."""
    out = []
    for test_name, threshold in MOBILITY_ROM_THRESHOLDS.items():
        if test_name.startswith("Hip:"):
            continue
        by_player = get_latest_values_by_player(session, test_name, _cache=_cache)
        if player_id not in by_player:
            continue
        raw = by_player[player_id]
        status = _mobility_rom_status(raw, threshold)
        out.append({"test_name": test_name, "raw": raw, "unit": "°", "threshold": threshold, "status": status})

    for base_metric in HIP_ROM_BASE_METRICS:
        right_test_name = f"Hip: Right {base_metric}"
        left_test_name = f"Hip: Left {base_metric}"
        drive_by_player, plant_by_player = resolve_side_by_throws(
            session, right_test_name, left_test_name, _cache=_cache, _throws_map=_throws_map
        )
        if player_id in drive_by_player:
            drive_name = f"Hip: Drive Leg {base_metric}"
            raw = drive_by_player[player_id]
            threshold = MOBILITY_ROM_THRESHOLDS.get(drive_name)
            out.append({"test_name": drive_name, "raw": raw, "unit": "°", "threshold": threshold, "status": _mobility_rom_status(raw, threshold)})
        if player_id in plant_by_player:
            plant_name = f"Hip: Plant Leg {base_metric}"
            raw = plant_by_player[player_id]
            threshold = MOBILITY_ROM_THRESHOLDS.get(plant_name)
            out.append({"test_name": plant_name, "raw": raw, "unit": "°", "threshold": threshold, "status": _mobility_rom_status(raw, threshold)})

    throwing_er, non_throwing_er = resolve_side_by_throws(
        session, SHOULDER_RIGHT_ER_TEST, SHOULDER_LEFT_ER_TEST, _cache=_cache, _throws_map=_throws_map
    )
    throwing_ir, non_throwing_ir = resolve_side_by_throws(
        session, GIRD_RIGHT_IR_TEST, GIRD_LEFT_IR_TEST, _cache=_cache, _throws_map=_throws_map
    )
    throwing_arc = {pid: throwing_er[pid] + throwing_ir[pid] for pid in throwing_er if pid in throwing_ir}
    non_throwing_arc = {pid: non_throwing_er[pid] + non_throwing_ir[pid] for pid in non_throwing_er if pid in non_throwing_ir}
    if player_id in throwing_arc:
        out.append({"test_name": "Throwing Arm Total Arc", "raw": throwing_arc[player_id], "unit": "°", "threshold": None, "status": None})
    if player_id in non_throwing_arc:
        out.append({"test_name": "Non-Throwing Arm Total Arc", "raw": non_throwing_arc[player_id], "unit": "°", "threshold": None, "status": None})

    out.extend(compute_shoulder_rom_profile(session, player_id, _cache=_cache, _throws_map=_throws_map))
    out.extend(compute_hip_rom_profile(session, player_id, _cache=_cache, _throws_map=_throws_map))
    return out


def average_percentiles(metric_dict):
    """Plain mean of whatever percentiles are present (no weighting),
    rounded. None if nothing to average."""
    values = [m["percentile"] for m in metric_dict.values() if m["percentile"] is not None]
    if not values:
        return None
    return round(sum(values) / len(values))


def compute_balance_pct(output_score, capacity_score):
    """Percentage imbalance between Output and Capacity, NOT a flat
    difference -- (Output - Capacity) / midpoint * 100. A flat
    difference treats a 95/85 athlete and a 55/45 athlete as equally
    "imbalanced" (both are a 10-point gap) even though those are very
    different situations; expressing the gap as a percentage of the
    athlete's own overall level (the mean of the two scores) tells them
    apart. Positive = Output-dominant, negative = Capacity-dominant.
    Precedent: Samozino & Morin's force-velocity imbalance (FVimb) uses
    the same relative-percentage shape to compare two already-normalized
    physical qualities, for the same reason. Returns None if either
    input is None (nothing to compare)."""
    if output_score is None or capacity_score is None:
        return None
    midpoint = (output_score + capacity_score) / 2
    if midpoint == 0:
        return None
    return round((output_score - capacity_score) / midpoint * 100, 1)


def classify_development_profile(output_score, capacity_score, balance_pct):
    """Development Profile label from the Output/Capacity/Balance
    numbers -- provisional bands (DEVELOPMENT_PROFILE_BANDS), not
    validated thresholds. "Developing" takes priority over the balance
    bands: an athlete who's low on BOTH qualities isn't "Balanced" in
    the sense that term is meant to convey (strong AND proportionate),
    so that case is checked first. Returns None if there's not enough
    data to classify at all."""
    if output_score is None or capacity_score is None or balance_pct is None:
        return None
    floor = DEVELOPMENT_PROFILE_BANDS["developing_score_floor"]
    if output_score < floor and capacity_score < floor:
        return "Developing"
    balanced_max = DEVELOPMENT_PROFILE_BANDS["balanced_max_abs_pct"]
    if abs(balance_pct) <= balanced_max:
        return "Balanced/Optimized"
    return "Output-Dominant" if balance_pct > 0 else "Capacity-Dominant"


def compute_bucket_system(session, player_id):
    """The full rollup for one player: raw values + percentiles per
    metric, sub-group percentiles (Breakdown 1), bucket percentiles
    (Breakdown 2: Body Comp/Power/Strength/Speed), and the final Total
    (Breakdown 3, Body Comp + Power + Strength only).

    Also returns the Physical Development extension: capacity_score
    (new), output_score (= power_score/strength_score averaged, not a
    new composite), balance_pct, and development_profile. These are
    NEW keys appended to this same dict rather than a second function
    with a second round of queries -- existing callers (Player
    Dashboard, My Assessments, Analytics) are unaffected since they
    only read the keys they already know about."""
    # Batch-fetch every metric this whole rollup could possibly need in
    # 2 queries total (plus 1 for player throwing hands), instead of
    # each of the ~20 compute_metric_percentiles()/resolve_side_by_throws()
    # calls below hitting the database on its own -- see
    # _batch_fetch_latest_values's docstring. This is the fix for
    # Assessments/Dashboard/My Assessments feeling slow (and sometimes
    # disconnecting): a single player's rollup used to cost 100+
    # sequential round trips to the hosted database; now it costs 3.
    _cache, _units = _batch_fetch_latest_values(session, _all_bucket_test_names())
    _throws_map = get_player_throws_map(session)

    # Body Comp -- score is averaged from ONLY the 2 scoring metrics
    # (BODY_COMP_METRICS), but the metrics dict returned for display
    # (body_comp_metrics, rendered as percentile bars) uses all 4
    # entered fields (BODY_COMP_DISPLAY_METRICS), so players see Body
    # Fat Mass and Percent Body Fat too even though those 2 don't
    # affect body_comp_score.
    body_comp_score_metrics = compute_metric_percentiles(session, player_id, BODY_COMP_METRICS, _cache=_cache, _units=_units)
    body_comp_score = average_percentiles(body_comp_score_metrics)
    body_comp_metrics = compute_metric_percentiles(session, player_id, BODY_COMP_DISPLAY_METRICS, _cache=_cache, _units=_units)

    # Power (5 sub-groups)
    power_subgroup_scores = {}
    power_subgroup_metrics = {}
    for sub_name, metrics in POWER_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics, _cache=_cache, _units=_units)
        power_subgroup_metrics[sub_name] = m
        power_subgroup_scores[sub_name] = average_percentiles(m)
    power_score = round(sum(v for v in power_subgroup_scores.values() if v is not None) / len([v for v in power_subgroup_scores.values() if v is not None])) if any(v is not None for v in power_subgroup_scores.values()) else None

    # Strength (3 sub-groups)
    strength_subgroup_scores = {}
    strength_subgroup_metrics = {}
    for sub_name, metrics in STRENGTH_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics, _cache=_cache, _units=_units)
        strength_subgroup_metrics[sub_name] = m
        strength_subgroup_scores[sub_name] = average_percentiles(m)
    strength_score = round(sum(v for v in strength_subgroup_scores.values() if v is not None) / len([v for v in strength_subgroup_scores.values() if v is not None])) if any(v is not None for v in strength_subgroup_scores.values()) else None

    # Speed (reference only, excluded from Total)
    speed_metrics = compute_metric_percentiles(session, player_id, SPEED_METRICS, _cache=_cache, _units=_units)
    speed_score = average_percentiles(speed_metrics)

    # Total: Body Comp + Power + Strength only
    total_inputs = [v for v in [body_comp_score, power_score, strength_score] if v is not None]
    total_score = round(sum(total_inputs) / len(total_inputs)) if total_inputs else None

    # Capacity (Physical Development extension, throwing-arm strength only -- see module docstring)
    capacity_subgroup_scores = {}
    capacity_subgroup_metrics = {}
    for sub_name, metrics in CAPACITY_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics, _cache=_cache, _units=_units)
        capacity_subgroup_metrics[sub_name] = m
        capacity_subgroup_scores[sub_name] = average_percentiles(m)
    capacity_score = round(sum(v for v in capacity_subgroup_scores.values() if v is not None) / len([v for v in capacity_subgroup_scores.values() if v is not None])) if any(v is not None for v in capacity_subgroup_scores.values()) else None

    # Output = power_score/strength_score averaged, reusing the
    # existing verified numbers above rather than a new composite.
    output_inputs = [v for v in [power_score, strength_score] if v is not None]
    output_score = round(sum(output_inputs) / len(output_inputs)) if output_inputs else None

    balance_pct = compute_balance_pct(output_score, capacity_score)
    development_profile = classify_development_profile(output_score, capacity_score, balance_pct)

    # Mobility & ROM -- pass/fail against MOBILITY_ROM_THRESHOLDS, not
    # percentile-ranked against the team like every other bucket here.
    # See MOBILITY_ROM_THRESHOLDS' and compute_mobility_rom_report's
    # docstrings for the full rationale/sourcing.
    mobility_rom_report = compute_mobility_rom_report(session, player_id, _cache=_cache, _throws_map=_throws_map)

    # Shoulder Health (GIRD only for now, auto-computed -- see
    # compute_gird_percentiles' docstring). Reference only, not in
    # Total -- see module docstring.
    shoulder_health_metrics = compute_gird_percentiles(session, player_id, _cache=_cache, _throws_map=_throws_map)
    shoulder_health_score = average_percentiles(shoulder_health_metrics)

    return {
        "body_comp_score": body_comp_score,
        "body_comp_metrics": body_comp_metrics,
        "power_score": power_score,
        "power_subgroup_scores": power_subgroup_scores,
        "power_subgroup_metrics": power_subgroup_metrics,
        "strength_score": strength_score,
        "strength_subgroup_scores": strength_subgroup_scores,
        "strength_subgroup_metrics": strength_subgroup_metrics,
        "speed_score": speed_score,
        "speed_metrics": speed_metrics,
        "total_score": total_score,
        "capacity_score": capacity_score,
        "capacity_subgroup_scores": capacity_subgroup_scores,
        "capacity_subgroup_metrics": capacity_subgroup_metrics,
        "output_score": output_score,
        "balance_pct": balance_pct,
        "development_profile": development_profile,
        "mobility_rom_report": mobility_rom_report,
        "shoulder_health_score": shoulder_health_score,
        "shoulder_health_metrics": shoulder_health_metrics,
    }