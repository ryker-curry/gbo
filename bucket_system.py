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

"Team" comparison population = every active player with at least one
result for that test type, using each player's most recent value per
metric (an ongoing system, not a one-time snapshot like the original
spreadsheet).
"""

from sqlalchemy.orm import joinedload
from models import Player, Assessment, AssessmentResult, AssessmentTestType

# (test_name, direction) -- direction is "higher" or "lower" (lower =
# lower raw value is the better score, e.g. sprint times).
BODY_COMP_METRICS = [
    ("Body Weight", "higher"),
    ("Skeletal Muscle Mass", "higher"),
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


def get_latest_values_by_player(session, test_name):
    """{player_id: (value, assessment_date)} -- each active player's most
    recent result for this test type, across the whole roster. Returns
    {} if the test type doesn't exist yet (e.g. not seeded)."""
    test_type = session.query(AssessmentTestType).filter(AssessmentTestType.test_name == test_name).first()
    if test_type is None:
        return {}
    rows = (
        session.query(AssessmentResult, Assessment.player_id, Assessment.assessment_date)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
        .join(Player, Assessment.player_id == Player.player_id)
        .filter(AssessmentResult.test_type_id == test_type.test_type_id, Player.active.is_(True))
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


def compute_bucket_system(session, player_id):
    """The full rollup for one player: raw values + percentiles per
    metric, sub-group percentiles (Breakdown 1), bucket percentiles
    (Breakdown 2: Body Comp/Power/Strength/Speed), and the final Total
    (Breakdown 3, Body Comp + Power + Strength only)."""
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
    }