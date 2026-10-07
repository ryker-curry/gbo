"""
GBO -- Decision runs: swing / take decisions valued in runs (Oct 2026).

From Ryker's hitting article batch: Paradigm's "Swing Decisions" and
"How to Quantify Hitter Process", Matt Creally's "Using Linear Weights to
Evaluate Swing Decisions", and BEAR Part III. Upgrades the rule-based
Swing Decision % (hitter_insights.swing_decisions) with count context:
a take on a Heart pitch at 3-1 and at 0-2 are not the same mistake.

VALUE TABLE (team-wide, every charted pitch with a location, a count and
a run value -- both sides of our intrasquads, since it's the same hitters
and pitchers):
  region  Heart / Shadow-in / Shadow-out / Chase / Waste
          (strike_zone.classify_attack_zone, Shadow split by is_in_zone)
  count   the ball-strike count before the pitch
  action  swing (whiff / foul / in play) or take (ball / called strike)
  value   average run_value (hitter's side: + = good for the hitter), each
          (region, count, action) cell pulled toward its (region, action)
          average by SHRINK pseudo-pitches, and that toward the action's
          overall average -- so a thin cell can't swing wildly.

CREDIT per pitch = value(what he did) - value(the other choice) in that
region and count. + = good decision. Summed = Decision runs; per 100
graded pitches = Decision RV/100.

GamePitch.run_value = RE(after) + runs scored - RE(before) -- the batting
team's side (+ = good for the hitter), the same number game_stats' hitter
"Total RV" sums as-is.
"""

import time
from collections import defaultdict

from plate_discipline import SWING_OUTCOMES
from strike_zone import classify_attack_zone, is_in_zone

REGIONS = ("Heart", "Shadow-in", "Shadow-out", "Chase", "Waste")
TAKES = {"Ball", "Called Strike"}
SHRINK = 15
COUNT_GROUPS = {
    "Hitter's counts": ("1-0", "2-0", "3-0", "2-1", "3-1"),
    "First pitch / even": ("0-0", "1-1"),
    "Pitcher's counts": ("0-1", "0-2", "1-2"),
    "Full / 2-2": ("2-2", "3-2"),
}
_cache = {"key": None, "table": None, "at": 0.0}


def region_of(p):
    if p.actual_plate_x is None or p.actual_plate_z is None:
        return None
    x, z = float(p.actual_plate_x), float(p.actual_plate_z)
    tier = classify_attack_zone(x, z)
    if tier == "Shadow":
        return "Shadow-in" if is_in_zone(x, z) else "Shadow-out"
    return tier


def action_of(p):
    if p.pitch_outcome in SWING_OUTCOMES:
        return "swing"
    if p.pitch_outcome in TAKES:
        return "take"
    return None


def count_of(p):
    if p.balls_before is None or p.strikes_before is None:
        return None
    return f"{p.balls_before}-{p.strikes_before}"


def group_of(count):
    for g, cs in COUNT_GROUPS.items():
        if count in cs:
            return g
    return None


def build_table(pitches):
    """{(region, count, action): value, (region, None, action): value, (None, None, action): value}"""
    sums = defaultdict(lambda: [0.0, 0])
    for p in pitches:
        if p.run_value is None:
            continue
        r, c, a = region_of(p), count_of(p), action_of(p)
        if r is None or c is None or a is None:
            continue
        v = float(p.run_value)
        for key in ((r, c, a), (r, None, a), (None, None, a)):
            sums[key][0] += v
            sums[key][1] += 1
    table = {}
    for a in ("swing", "take"):
        s, n = sums.get((None, None, a), [0.0, 0])
        table[(None, None, a)] = s / n if n else 0.0
    for (r, c, a), (s, n) in sums.items():
        if r is not None and c is None:
            base = table[(None, None, a)]
            table[(r, None, a)] = (s + SHRINK * base) / (n + SHRINK)
    for (r, c, a), (s, n) in sums.items():
        if r is not None and c is not None:
            base = table.get((r, None, a), table[(None, None, a)])
            table[(r, c, a)] = (s + SHRINK * base) / (n + SHRINK)
    return table


def value(table, region, count, action):
    for key in ((region, count, action), (region, None, action), (None, None, action)):
        if key in table:
            return table[key]
    return 0.0


def credit(table, p):
    """-> (credit, region, count, action) or None for an ungradable pitch."""
    r, c, a = region_of(p), count_of(p), action_of(p)
    if r is None or c is None or a is None:
        return None
    other = "take" if a == "swing" else "swing"
    return value(table, r, c, a) - value(table, r, c, other), r, c, a


def score(table, pitches):
    """One hitter's decisions. -> {runs, per100, n, by: {(region, group, action): runs}, notes}"""
    rows = [x for x in (credit(table, p) for p in pitches) if x is not None]
    by = defaultdict(lambda: [0.0, 0])
    for cr, r, c, a in rows:
        key = (r, group_of(c), a)
        by[key][0] += cr
        by[key][1] += 1
    runs = sum(x[0] for x in rows)
    n = len(rows)
    return {"runs": runs, "per100": 100.0 * runs / n if n else None, "n": n,
            "by": {k: {"runs": v[0], "n": v[1]} for k, v in by.items()}, "notes": notes({k: v for k, v in by.items()})}


def notes(by, k=2, min_runs=0.3):
    """Biggest leaks and gains as coaching lines."""
    items = [(v[0], v[1], r, g, a) for (r, g, a), v in by.items() if g is not None]
    out = []
    for runs, n, r, g, a in sorted(items)[:k]:
        if runs <= -min_runs:
            verb = "swinging at" if a == "swing" else "taking"
            out.append(f"{runs:+.1f} runs {verb} {r} pitches in {g.lower()} ({n} pitches).")
    best = sorted(items, reverse=True)[:1]
    for runs, n, r, g, a in best:
        if runs >= min_runs:
            verb = "swinging at" if a == "swing" else "taking"
            out.append(f"Best habit: {runs:+.1f} runs {verb} {r} pitches in {g.lower()} ({n} pitches).")
    return out


def team_table(db):
    """Value table from every charted pitch, cached until the pitch count changes."""
    from sqlalchemy import func
    from models import GamePitch
    key = (id(db.get_bind()), db.query(func.count(GamePitch.game_pitch_id)).scalar(),
           db.query(func.max(GamePitch.game_pitch_id)).scalar())
    if _cache["key"] == key and _cache["table"] is not None:
        return _cache["table"]
    ps = (db.query(GamePitch).filter(GamePitch.run_value.isnot(None), GamePitch.actual_plate_x.isnot(None)).all())
    table = build_table(ps)
    _cache.update(key=key, table=table, at=time.time())
    return table
