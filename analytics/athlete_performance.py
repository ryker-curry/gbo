"""
GBO -- Athlete vs Performance (Nov 2026, Ryker): does a change in a
physical test (force plates, ForceFrame, med ball, body comp) line up with a
change on the mound (Rapsodo fastball)? Display: the staff page
shiny_app/modules/athlete_performance.py and the "Physical vs performance"
card on Player Profile -> Career Development.

Choices agreed with Ryker (AskUserQuestion, Nov 2026):
  - Testing periods are assessment_period labels ("Fall 2025", "Fall 2026").
    A player's period anchor is the median date of his tests in it; if he
    has a test more than once in a period, the latest counts.
  - On-field numbers per period = his Rapsodo fastballs (4-seam + 2-seam,
    bullpens and games, no rehab/recovery/low intent) within +/-30 days of
    that anchor. History (rapsodo_history) counts, via
    career_development.load_pitches.
  - Decline watch: fastball velo down 1.5+ mph from the earlier period, or a
    key force plate number (KEY_DECLINE) down 5%+ in the "worse" direction.
    Both at once is the strongest flag.
  - Lower-is-better tests (times, durations, body fat) are flipped so
    "improved" always means the same direction; neutral ones (bodyweight,
    ROM degrees, angles) are left as raw change and never called better or
    worse.
  - Derived: CMJ Peak Power / kg (peak power / CMJ bodyweight), IMTP Peak
    Force / kg (the sheet's / BM column, else peak vertical force / body
    weight), Throwing Arm ER/IR Ratio (ER / IR peak force).
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import timedelta

from assessment_period import period_label, parse_period_label
from pitch_type_config import FASTBALL_TYPES

WINDOW_DAYS = 30
VELO_DROP = 1.5
TEST_DROP_PCT = 5.0
LB_PER_KG = 2.2046226218

CMJ_PP_KG = "CMJ Peak Power / kg"
IMTP_KG = "IMTP Peak Force / kg"
ERIR = "Throwing Arm ER/IR Ratio"

DEFAULT_TESTS = [
    CMJ_PP_KG, "Countermovement Jump Height", "Countermovement Jump RSI-Modified", "CMJ Concentric Impulse",
    IMTP_KG, "IMTP RFD 0-100 ms",
    "Medicine Ball Shot Put Velocity", "Medicine Ball Shot Put Distance", "Body Weight", "Skeletal Muscle Mass",
    "Shoulder Strength: Throwing Arm ER Peak Force", "Shoulder Strength: Throwing Arm IR Peak Force", ERIR,
    "Hip Abduction Force (Drive Leg)", "Hip Adduction Force (Drive Leg)",
]
KEY_DECLINE = [CMJ_PP_KG, "Countermovement Jump RSI-Modified", IMTP_KG, "Countermovement Jump Height"]
DERIVED_UNITS = {CMJ_PP_KG: "W/kg", IMTP_KG: "N/kg", ERIR: "ratio"}

PERF_METRICS = {
    "velo": ("Fastball avg velo", "mph", 1),
    "velo_max": ("Fastball max velo", "mph", 1),
    "spin": ("Fastball spin", "rpm", 0),
    "ivb": ("Fastball IVB", "in", 1),
    "extension": ("Extension", "ft", 2),
}

_LOWER_WORDS = ("Time", "Duration", "Sprint", "Body Fat", "Fat Mass")
_NEUTRAL_WORDS = ("Bodyweight", "Body Weight", "Age", "Angle", "Body Mass Index", "Water", "BMR",
                  "Basal Metabolic", "Caloric")
_NEUTRAL_CATEGORIES = {"Mobility & ROM", "Pitcher-Specific"}


def direction(name, category=None):
    """+1 higher is better, -1 lower is better, 0 neither."""
    if category in _NEUTRAL_CATEGORIES or name == ERIR:
        return 0
    if any(w in name for w in _NEUTRAL_WORDS):
        return 0
    if any(w in name for w in _LOWER_WORDS):
        return -1
    return 1


def _period_key(label):
    d = parse_period_label(label)
    return (d.year, d.month) if d else (0, 0)


# ---------------------------------------------------------------- tests
def load_tests(db, player_ids=None):
    """{pid: {period: {"anchor": date, "tests": {name: value}}}} plus
    {name: (unit, category)}."""
    from models import Assessment, AssessmentResult, AssessmentTestType, AssessmentCategory
    q = (db.query(Assessment.player_id, Assessment.assessment_date, AssessmentTestType.test_name,
                  AssessmentTestType.unit, AssessmentCategory.category_name, AssessmentResult.value)
         .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
         .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
         .join(AssessmentCategory, AssessmentCategory.category_id == Assessment.category_id))
    if player_ids is not None:
        q = q.filter(Assessment.player_id.in_(list(player_ids)))
    meta = {}
    raw = defaultdict(lambda: defaultdict(dict))  # pid -> period -> name -> (date, value)
    dates = defaultdict(lambda: defaultdict(list))
    for pid, d, name, unit, cat, val in q.all():
        if val is None or d is None:
            continue
        meta[name] = (unit, cat)
        per = period_label(d)
        prev = raw[pid][per].get(name)
        if prev is None or d >= prev[0]:
            raw[pid][per][name] = (d, float(val))
        dates[pid][per].append(d)
    out = {}
    for pid, pers in raw.items():
        out[pid] = {}
        for per, tests in pers.items():
            t = {k: v for k, (_d, v) in tests.items()}
            _derive(t)
            ds = sorted(dates[pid][per])
            out[pid][per] = {"anchor": ds[len(ds) // 2], "tests": t}
    for k, u in DERIVED_UNITS.items():
        meta[k] = (u, "Derived")
    return out, meta


def _derive(t):
    pp, bw = t.get("CMJ Peak Power"), t.get("CMJ Bodyweight")
    if pp and bw:
        t[CMJ_PP_KG] = pp / bw
    if t.get("IMTP Peak Vertical Force / BM"):
        t[IMTP_KG] = t["IMTP Peak Vertical Force / BM"]
    else:
        f = t.get("Isometric Mid-Thigh Pull Peak Vertical Force")
        kg = t.get("IMTP Bodyweight") or (t["Body Weight"] / LB_PER_KG if t.get("Body Weight") else None)
        if f and kg:
            t[IMTP_KG] = f / kg
    er, ir = t.get("Shoulder Strength: Throwing Arm ER Peak Force"), t.get("Shoulder Strength: Throwing Arm IR Peak Force")
    if er and ir:
        t[ERIR] = er / ir


def periods(tests):
    """Every period label with data, oldest first."""
    return sorted({p for pers in tests.values() for p in pers}, key=_period_key)


# ---------------------------------------------------------------- mound
def perf_window(rows, anchor, days=WINDOW_DAYS):
    """Fastball summary within +/-days of anchor (standard sessions)."""
    lo, hi = anchor - timedelta(days=days), anchor + timedelta(days=days)
    fb = [r for r in rows if r["pitch"] in FASTBALL_TYPES and lo <= r["date"] <= hi
          and r["session_type"] not in ("Rehab", "Low Intent", "Recovery")]
    if not fb:
        return None
    v = [r["velo"] for r in fb if r["velo"] is not None]
    sp = [r["spin"] for r in fb if r["spin_ok"]]
    iv = [r["ivb"] for r in fb if r["ivb"] is not None]
    ex = [r["extension"] for r in fb if r["extension"]]
    m = lambda xs: sum(xs) / len(xs) if xs else None
    return {"n": len(fb), "velo": m(v), "velo_max": max(v) if v else None, "spin": m(sp),
            "ivb": m(iv), "extension": m(ex), "first": min(r["date"] for r in fb), "last": max(r["date"] for r in fb)}


# ---------------------------------------------------------------- team
def team_changes(db, period_a, period_b, player_ids=None):
    """One row per pitcher with tests in both periods: every shared test's
    change and his Rapsodo fastball change over the matching windows."""
    import career_development as cd
    from models import Player
    tests, meta = load_tests(db, player_ids)
    pitchers = {p.player_id: p for p in db.query(Player).filter(Player.is_pitcher.is_(True))}
    out = []
    for pid, pers in tests.items():
        p = pitchers.get(pid)
        if p is None or period_a not in pers or period_b not in pers:
            continue
        a, b = pers[period_a], pers[period_b]
        rows = cd.load_pitches(db, pid)["rows"]
        pa, pb = perf_window(rows, a["anchor"]), perf_window(rows, b["anchor"])
        changes = {}
        for name in set(a["tests"]) & set(b["tests"]):
            v1, v2 = a["tests"][name], b["tests"][name]
            pct = (v2 - v1) / abs(v1) * 100 if v1 else None
            d = direction(name, meta.get(name, (None, None))[1])
            changes[name] = {"v1": v1, "v2": v2, "abs": v2 - v1, "pct": pct,
                             "improve_pct": None if pct is None else (pct * d if d else pct), "dir": d}
        perf = {}
        for k in PERF_METRICS:
            x1, x2 = (pa or {}).get(k), (pb or {}).get(k)
            perf[k] = {"v1": x1, "v2": x2, "abs": None if x1 is None or x2 is None else x2 - x1}
        out.append({"pid": pid, "name": f"{p.first_name} {p.last_name}", "last": p.last_name, "active": p.active,
                    "anchor_a": a["anchor"], "anchor_b": b["anchor"], "perf_a": pa, "perf_b": pb,
                    "tests": changes, "perf": perf})
    return sorted(out, key=lambda r: r["last"]), meta


def test_options(changes, meta):
    """Tests with a change for 3+ pitchers -- defaults first, then the rest
    by category."""
    counts = defaultdict(int)
    for r in changes:
        for k in r["tests"]:
            counts[k] += 1
    ok = [k for k, n in counts.items() if n >= 3]
    first = [k for k in DEFAULT_TESTS if k in ok]
    rest = sorted((k for k in ok if k not in first), key=lambda k: (meta.get(k, ("", ""))[1] or "", k))
    return first + rest


def quadrant(test_change, perf_change, test_dir):
    """Label for the scatter / table. test_change is improve_pct when the
    test has a direction, raw % otherwise."""
    if test_change is None or perf_change is None:
        return None
    if test_dir == 0:
        return ("Test up" if test_change >= 0 else "Test down") + (", velo up" if perf_change >= 0 else ", velo down")
    if test_change >= 0 and perf_change >= 0:
        return "Both up"
    if test_change < 0 and perf_change < 0:
        return "Both down"
    return "Stronger, velo down" if test_change >= 0 else "Test down, velo up"


def scatter_points(changes, test, perf_key="velo"):
    pts = []
    for r in changes:
        t, pf = r["tests"].get(test), r["perf"][perf_key]
        if t is None or pf["abs"] is None:
            continue
        x = t["improve_pct"] if t["improve_pct"] is not None else None
        if x is None:
            continue
        pts.append({"pid": r["pid"], "name": r["name"], "last": r["last"], "x": x, "y": pf["abs"],
                    "test": t, "perf": pf, "quad": quadrant(x, pf["abs"], t["dir"])})
    return pts


def fit(pts):
    """OLS line + Pearson r, p and n (p from research_analysis.p_value)."""
    n = len(pts)
    if n < 3:
        return None
    xs, ys = [p["x"] for p in pts], [p["y"] for p in pts]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    syy = sum((y - my) ** 2 for y in ys)
    r = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sxx * syy) ** 0.5) if syy else 0.0
    try:
        from analytics.research_analysis import p_value
        p = p_value(r, n)
    except Exception:  # research_analysis pulls in the DB layer; p is optional
        p = None
    return {"n": n, "slope": slope, "intercept": my - slope * mx, "r": r, "p": p}


def decline_watch(changes):
    """Pitchers whose fastball velo fell VELO_DROP+ mph and/or a key force
    plate test got TEST_DROP_PCT+ worse. Strongest flags first."""
    out = []
    for r in changes:
        dv = r["perf"]["velo"]["abs"]
        velo_down = dv is not None and dv <= -VELO_DROP
        drops = []
        for k in KEY_DECLINE:
            t = r["tests"].get(k)
            if t and t["improve_pct"] is not None and t["improve_pct"] <= -TEST_DROP_PCT:
                drops.append((k, t["improve_pct"]))
        if not velo_down and not drops:
            continue
        level = "Both down" if velo_down and drops else ("Velo down" if velo_down else "Test down")
        out.append({**r, "level": level, "velo_change": dv, "drops": drops})
    order = {"Both down": 0, "Velo down": 1, "Test down": 2}
    return sorted(out, key=lambda r: (order[r["level"]], r["velo_change"] if r["velo_change"] is not None else 0))


# ---------------------------------------------------------------- one player
def player_path(db, pid, rows):
    """Per period for one player: anchor, every test value, and his fastball
    window. Oldest first."""
    tests, meta = load_tests(db, [pid])
    pers = tests.get(pid, {})
    out = []
    for per in sorted(pers, key=_period_key):
        a = pers[per]
        out.append({"period": per, "anchor": a["anchor"], "tests": a["tests"], "perf": perf_window(rows, a["anchor"])})
    return out, meta
