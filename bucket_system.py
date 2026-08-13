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
  - Shoulder Health (GIRD) is excluded entirely, not computed at all
    (Ryker's explicit call).
  - Speed is computed (for reference/display) but excluded from the
    final Total, along with Shoulder Health.
  - Total = ROUND(AVERAGE(Body Comp, Power, Strength), 0).

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
    ],
    "Upper Body Strength": [
        ("Neutral Grip/DB Bench Press Max Load", "higher"),
        ("Neutral Grip Chin Up Max External Load", "higher"),
        ("Grip Strength (Seated, Throwing Hand)", "higher"),
    ],
    "Mid-Thigh Pull": [
        ("Isometric Mid-Thigh Pull Average Force", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "higher"),
        ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", "higher"),
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
# have nothing to do with the bucket system. Arm Health is NOT included
# here even though GIRD lives there -- GIRD is excluded from the bucket
# system entirely, so nothing in Arm Health is bucket-relevant anymore.
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
        names = set()
        for sub_name, metrics in STRENGTH_SUBGROUPS.items():
            if sub_name in ("Lower Body Strength", "Mid-Thigh Pull"):
                names.update(name for name, _ in metrics)
        return names
    if category_name == "Upper Body Strength":
        return {name for name, _ in STRENGTH_SUBGROUPS["Upper Body Strength"]}
    if category_name == "Speed":
        return {name for name, _ in SPEED_METRICS}
    return set()


def get_latest_values_by_player(session, test_name):
    """{player_id: (value, assessment_date)} -- each player's most
    recent result for this test type, across the whole roster --
    ACTIVE AND INACTIVE both count toward the comparison pool (Ryker's
    explicit call, so last year's players' data still contributes to
    percentiles even though they're hidden from the current roster
    everywhere else in the app). Returns {} if the test type doesn't
    exist yet (e.g. not seeded)."""
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


def compute_metric_percentiles(session, player_id, metrics):
    """metrics: [(test_name, direction), ...]. Returns
    {test_name: {"raw": value, "percentile": pct, "unit": unit}} for
    whichever of these metrics the player actually has a result for."""
    out = {}
    for test_name, direction in metrics:
        by_player = get_latest_values_by_player(session, test_name)
        if player_id not in by_player:
            continue
        value = by_player[player_id]
        pct = compute_percentile(value, list(by_player.values()), direction)
        test_type = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == test_name).first()
        out[test_name] = {"raw": value, "percentile": pct, "unit": test_type.unit if test_type else None}
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
    # Body Comp
    body_comp_metrics = compute_metric_percentiles(session, player_id, BODY_COMP_METRICS)
    body_comp_score = average_percentiles(body_comp_metrics)

    # Power (5 sub-groups)
    power_subgroup_scores = {}
    power_subgroup_metrics = {}
    for sub_name, metrics in POWER_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics)
        power_subgroup_metrics[sub_name] = m
        power_subgroup_scores[sub_name] = average_percentiles(m)
    power_score = round(sum(v for v in power_subgroup_scores.values() if v is not None) / len([v for v in power_subgroup_scores.values() if v is not None])) if any(v is not None for v in power_subgroup_scores.values()) else None

    # Strength (3 sub-groups)
    strength_subgroup_scores = {}
    strength_subgroup_metrics = {}
    for sub_name, metrics in STRENGTH_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics)
        strength_subgroup_metrics[sub_name] = m
        strength_subgroup_scores[sub_name] = average_percentiles(m)
    strength_score = round(sum(v for v in strength_subgroup_scores.values() if v is not None) / len([v for v in strength_subgroup_scores.values() if v is not None])) if any(v is not None for v in strength_subgroup_scores.values()) else None

    # Speed (reference only, excluded from Total)
    speed_metrics = compute_metric_percentiles(session, player_id, SPEED_METRICS)
    speed_score = average_percentiles(speed_metrics)

    # Total: Body Comp + Power + Strength only
    total_inputs = [v for v in [body_comp_score, power_score, strength_score] if v is not None]
    total_score = round(sum(total_inputs) / len(total_inputs)) if total_inputs else None

    # Capacity (Physical Development extension, throwing-arm strength only -- see module docstring)
    capacity_subgroup_scores = {}
    capacity_subgroup_metrics = {}
    for sub_name, metrics in CAPACITY_SUBGROUPS.items():
        m = compute_metric_percentiles(session, player_id, metrics)
        capacity_subgroup_metrics[sub_name] = m
        capacity_subgroup_scores[sub_name] = average_percentiles(m)
    capacity_score = round(sum(v for v in capacity_subgroup_scores.values() if v is not None) / len([v for v in capacity_subgroup_scores.values() if v is not None])) if any(v is not None for v in capacity_subgroup_scores.values()) else None

    # Output = power_score/strength_score averaged, reusing the
    # existing verified numbers above rather than a new composite.
    output_inputs = [v for v in [power_score, strength_score] if v is not None]
    output_score = round(sum(output_inputs) / len(output_inputs)) if output_inputs else None

    balance_pct = compute_balance_pct(output_score, capacity_score)
    development_profile = classify_development_profile(output_score, capacity_score, balance_pct)

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
    }