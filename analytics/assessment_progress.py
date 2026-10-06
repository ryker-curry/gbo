"""
GBO -- testing progress for My Assessments (Oct 2026, Ryker: "need to make
the my assessments page better for player login"). Approved pieces:

  * change since last test on every scored bar (green better / red worse),
  * a strengths / work-on summary in plain English,
  * a progress chart for any test,
  * a shorter Mobility section (lives in bucket_display).

Pure data helpers here -- no Shiny. Direction (is up good?) comes from the
same (test_name, direction) lists bucket_system scores with, so a change is
colored the same way the bar is ranked. Body Weight, BMR and Caloric Intake
are neutral: up isn't automatically better.
"""

from collections import defaultdict

from sqlalchemy.orm import joinedload

import bucket_system as bs
from models import Assessment, AssessmentResult, BullpenPitch

NEUTRAL = {"Body Weight", "Basal Metabolic Rate (BMR)", "Recommended Caloric Intake"}

# Tests the strengths / work-on card never picks: not a "skill" (weight) or
# shown elsewhere as a flag rather than a ranking (GIRD).
NOT_A_STRENGTH = {"Body Weight", "Shoulder ROM: GIRD"}

# Categories the progress chart offers, in page order. Anthropometrics and
# Pitcher-Specific (Rapsodo, per pitch type) stay in the full history table.
CHART_CATEGORIES = ["Body Composition", "Explosive Power", "Rotational Power", "Upper Body Strength",
                    "Lower Body Strength", "Speed", "Arm Health", "Mobility & ROM"]


def direction_map():
    """test_name -> "higher" / "lower" / None (neutral)."""
    out = {}
    lists = [bs.BODY_COMP_DISPLAY_METRICS, bs.MED_BALL_THROW_REFERENCE_METRICS, bs.SPEED_METRICS]
    lists += list(bs.POWER_SUBGROUPS.values()) + list(bs.STRENGTH_SUBGROUPS.values())
    lists += list(bs.CAPACITY_SUBGROUPS.values())
    for metrics in lists:
        for name, d in metrics:
            out[name] = None if name in NEUTRAL else d
    # ROM entry fields: every threshold is a minimum, so more range = better.
    for name in bs.MOBILITY_ROM_THRESHOLDS:
        if not name.startswith("Hip:"):
            out.setdefault(name, "higher")
    for base in bs.HIP_ROM_BASE_METRICS:
        out.setdefault(f"Hip: Right {base}", "higher")
        out.setdefault(f"Hip: Left {base}", "higher")
    return out


def history(db, player_id):
    """{test_name: {"unit", "category", "points": [(date, value), ...] oldest first}}.
    Same-day duplicates are averaged. Skips Rapsodo entries tied to a
    bullpen (they live on the bullpen pages), same as the history table."""
    linked = db.query(BullpenPitch.linked_assessment_id).filter(BullpenPitch.linked_assessment_id.isnot(None))
    rows = (
        db.query(Assessment)
        .options(joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                 joinedload(Assessment.category))
        .filter(Assessment.player_id == player_id, ~Assessment.assessment_id.in_(linked))
        .all()
    )
    acc = defaultdict(lambda: defaultdict(list))
    meta = {}
    for a in rows:
        cat = a.category.category_name if a.category else None
        if a.pitch_type_id is not None:
            continue  # per-pitch-type Rapsodo numbers don't make one line
        for r in a.results:
            if r.value is None or r.test_type is None:
                continue
            name = r.test_type.test_name
            acc[name][a.assessment_date].append(float(r.value))
            meta.setdefault(name, {"unit": r.test_type.unit or "", "category": cat})
    out = {}
    for name, by_day in acc.items():
        pts = [(d, sum(v) / len(v)) for d, v in sorted(by_day.items())]
        out[name] = {**meta[name], "points": pts}
    return out


def change_for(points, direction, current_raw=None):
    """Change from the previous test to the latest one.
    -> {"delta", "prev_date", "latest_date", "better"} or None if only one test.
    current_raw: the value the page is showing (bucket_system's latest in the
    season window) -- the change is measured from the test before THAT one."""
    if len(points) < 2:
        return None
    idx = len(points) - 1
    if current_raw is not None:
        hits = [i for i, (_, v) in enumerate(points) if abs(v - float(current_raw)) < 1e-6]
        if hits:
            idx = hits[-1]
    if idx == 0:
        return None
    (pd, pv), (ld, lv) = points[idx - 1], points[idx]
    delta = lv - pv
    if abs(delta) < 1e-9 or direction is None:
        better = None
    else:
        better = (delta > 0) == (direction == "higher")
    return {"delta": delta, "prev_date": pd, "latest_date": ld, "better": better}


def changes(hist, dirs=None):
    """{test_name: change_for(...)} for every test with 2+ results."""
    dirs = dirs if dirs is not None else direction_map()
    out = {}
    for name, h in hist.items():
        c = change_for(h["points"], dirs.get(name))
        if c is not None:
            out[name] = c
    return out


def last_tested(hist):
    dates = [h["points"][-1][0] for h in hist.values() if h["points"]]
    return max(dates) if dates else None


def scored_metrics(bucket_data):
    """Every percentile-ranked metric on the page: [(name, raw, unit, pct)]."""
    out = []

    def take(d):
        for name, v in (d or {}).items():
            if v.get("percentile") is not None and name not in NOT_A_STRENGTH:
                out.append((name, v["raw"], v.get("unit") or "", v["percentile"]))

    from bucket_system import BODY_COMP_METRICS
    bars = {n for n, _ in BODY_COMP_METRICS}
    take({k: v for k, v in (bucket_data.get("body_comp_metrics") or {}).items() if k in bars})
    ref = {n for n, _ in bs.MED_BALL_THROW_REFERENCE_METRICS}
    for m in (bucket_data.get("power_subgroup_metrics") or {}).values():
        take({k: v for k, v in m.items() if k not in ref})
    for m in (bucket_data.get("strength_subgroup_metrics") or {}).values():
        take(m)
    take(bucket_data.get("speed_metrics"))
    for m in (bucket_data.get("capacity_subgroup_metrics") or {}).values():
        take(m)
    return out


def team_rank_pct(value, team_values, direction):
    """Share of teammates this value beats (ties count half), 0-100.
    NOT the page's bar number -- bucket_system's "percentile" is % of the
    team's best (value / best), which reads high for everyone on sprint
    times. This is a true rank, so "better than X% of our team" is literal."""
    others = list(team_values)
    try:
        others.remove(value)
    except ValueError:
        pass
    if not others:
        return None
    if direction == "lower":
        beat = sum(1 for v in others if v > value) + 0.5 * sum(1 for v in others if v == value)
    else:
        beat = sum(1 for v in others if v < value) + 0.5 * sum(1 for v in others if v == value)
    return round(100 * beat / len(others))


def strengths_and_work_on(db, bucket_data, n=3):
    """(top n, bottom n) of [(name, raw, unit, rank_pct)] by true team rank
    (same season window and roster the bars use). The two lists never share
    a test; with fewer than 2n tests they split what there is."""
    dirs = direction_map()
    start, end = bs.season_date_range(bucket_data.get("season_label") or bs.current_season_label())
    ranked = []
    for name, raw, unit, _ in scored_metrics(bucket_data):
        d = dirs.get(name) or "higher"
        team = bs.get_latest_values_by_player(db, name, season_start=start, season_end=end)
        r = team_rank_pct(float(raw), [float(v) for v in team.values()], d)
        if r is not None:
            ranked.append((name, raw, unit, r))
    ranked.sort(key=lambda m: -m[3])
    if len(ranked) < 2:
        return ranked, []
    k = min(n, len(ranked) // 2)
    return ranked[:k], list(reversed(ranked[-k:]))


def chart_choices(hist):
    """{category: {test_name: label}} for the progress-chart picker, only
    tests with at least one result, in page order."""
    groups = defaultdict(dict)
    for name, h in hist.items():
        cat = h["category"]
        if cat in CHART_CATEGORIES:
            n = len(h["points"])
            groups[cat][name] = f"{name} ({n} test{'s' if n != 1 else ''})"
    return {c: dict(sorted(groups[c].items())) for c in CHART_CATEGORIES if groups.get(c)}


def default_chart_test(hist, prefer=()):
    """First of `prefer` (the work-on tests) with 2+ results, else the test
    with the most results (ties: page order) -- a line, not a dot."""
    for name in prefer:
        if name in hist and len(hist[name]["points"]) > 1 and hist[name]["category"] in CHART_CATEGORIES:
            return name
    best = None
    for cat in CHART_CATEGORIES:
        for name, h in sorted(hist.items()):
            if h["category"] == cat and (best is None or len(h["points"]) > len(hist[best]["points"])):
                best = name
    return best


def bucket_metric_dicts(bucket_data):
    """Every {test_name: {"raw", ...}} dict shown as bars on the page."""
    out = [bucket_data.get("body_comp_metrics") or {}, bucket_data.get("speed_metrics") or {}]
    for key in ("power_subgroup_metrics", "strength_subgroup_metrics", "capacity_subgroup_metrics"):
        out += list((bucket_data.get(key) or {}).values())
    return out


def changes_for_bucket(hist, bucket_data, dirs=None):
    """{test_name: change} measured from the test before the value each bar
    is showing (bucket_system's latest in the season window)."""
    dirs = dirs if dirs is not None else direction_map()
    out = {}
    for d in bucket_metric_dicts(bucket_data):
        for name, v in d.items():
            h = hist.get(name)
            if h:
                c = change_for(h["points"], dirs.get(name), v.get("raw"))
                if c is not None:
                    out[name] = c
    return out


def team_average(db, test_name):
    """Current active roster's average of each player's latest result."""
    start, end = bs.season_date_range(bs.current_season_label())  # same window the percentiles use
    vals = list(bs.get_latest_values_by_player(db, test_name, season_start=start, season_end=end).values())
    vals = [float(v) for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None
