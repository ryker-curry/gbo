"""
GBO -- Decision quality & floor (Oct 2026, from Smitty's "Gone Hunting:
The Offensive Approach Behind the Dodgers' Back-to-Back Titles": the
Dodgers' edge wasn't the best average decisions, it was a lineup whose
WORST stretches stayed good -- a tight "floor" across every regular).

  right            a graded choice (swing or take) that was the better one
                   for that zone and count, by the Decision runs value table
                   (analytics/decision_value.py: credit > 0)
  Decision quality % of his graded choices that were right
  rolling          decision quality over each run of WINDOW straight plate
                   appearances (overlapping -- 20 PAs = 11 windows)
  Floor            the FLOOR_PCT percentile of those windows -- how good his
                   decisions stay when he's at his worst

Needs WINDOW+ PAs with a graded pitch; fewer than EARLY_WINDOWS windows
reads "early".
"""

from analytics import decision_value
from analytics.hitter_insights import plate_appearances

WINDOW = 10
FLOOR_PCT = 0.25
EARLY_WINDOWS = 5
TIGHT_GAP = 5.0      # points between quality and floor
WIDE_GAP = 12.0


def _pctl(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (k - lo)


def pa_choices(table, pitches):
    """[(right, total)] per plate appearance with at least one graded pitch, in order."""
    out = []
    for pa in plate_appearances(pitches):
        cr = [decision_value.credit(table, p) for p in pa]
        cr = [c[0] for c in cr if c is not None]
        if cr:
            out.append((sum(1 for c in cr if c > 0), len(cr)))
    return out


def floor(table, pitches):
    """-> {quality, floor, gap, windows: [pct], n_pa, n, early, read} (values None when too few PAs)"""
    pas = pa_choices(table, pitches)
    right = sum(r for r, _t in pas)
    tot = sum(t for _r, t in pas)
    res = {"n_pa": len(pas), "n": tot, "quality": 100.0 * right / tot if tot else None,
           "floor": None, "gap": None, "windows": [], "early": True, "read": None}
    if len(pas) < WINDOW:
        return res
    wins = []
    for i in range(WINDOW, len(pas) + 1):
        chunk = pas[i - WINDOW:i]
        r, t = sum(c[0] for c in chunk), sum(c[1] for c in chunk)
        wins.append(100.0 * r / t if t else None)
    wins = [w for w in wins if w is not None]
    res["windows"] = wins
    res["floor"] = _pctl(wins, FLOOR_PCT)
    res["gap"] = res["quality"] - res["floor"] if res["quality"] is not None and res["floor"] is not None else None
    res["early"] = len(wins) < EARLY_WINDOWS
    g = res["gap"]
    if g is not None:
        res["read"] = ("Tight -- the approach holds up in slumps." if g <= TIGHT_GAP else
                       "Wide gap -- decisions slip when he's struggling." if g >= WIDE_GAP else
                       "Some slippage in his worst stretches.")
    return res


def lineup(by_pid):
    """by_pid: {pid: floor()}. -> {median_quality, median_floor, spread (IQR of floors), low: [pids below median - 1 IQR-ish]}"""
    rows = {pid: r for pid, r in by_pid.items() if r["floor"] is not None}
    if len(rows) < 3:
        return None
    floors = [r["floor"] for r in rows.values()]
    q = [r["quality"] for r in rows.values()]
    mf, mq = _pctl(floors, 0.5), _pctl(q, 0.5)
    iqr = _pctl(floors, 0.75) - _pctl(floors, 0.25)
    low = sorted((pid for pid, r in rows.items() if r["floor"] < mf - max(iqr, 3.0)), key=lambda p: rows[p]["floor"])
    return {"median_quality": mq, "median_floor": mf, "spread": iqr, "low": low, "n": len(rows)}
