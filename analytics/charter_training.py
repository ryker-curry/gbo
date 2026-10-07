"""
GBO -- Charter training data (Oct 2026, from Columbia SABRLions' "Building
a Trackman Team": per-pitcher cheat sheets plus a pitch-ID game built
from real roster pitches, so new charters learn each arm before a game).

Pure helpers -- the page is shiny_app/modules/charter_training.py.
Every game stat (Command+, Whiff/CSW, RV/100, pitch mix) depends on the
pitch type being charted right, and GBO has no game video clips, so the
quiz uses real Rapsodo readings: shape numbers in, pitch type out.

Run is shown ARM-SIDE (+ = toward his arm side) for either hand, so a
lefty's changeup reads like a righty's -- same frame as Arsenal Plan.
"""

import random
from collections import defaultdict
from statistics import median

MIN_TYPE = 5


def _f(v):
    return float(v) if v is not None else None


def _pctl(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    return vals[min(len(vals) - 1, int(round(q * (len(vals) - 1))))]


def arm_run(p, throws):
    hb = _f(p.hb_trajectory)
    if hb is None:
        return None
    return -hb if throws == "L" else hb


def arsenal_card(raps, throws, label_of):
    """[{label, n, usage, velo, ivb, run, spin, clock}] most-thrown first."""
    groups = defaultdict(list)
    for p in raps:
        lab = label_of(p)
        if lab:
            groups[lab].append(p)
    total = sum(len(v) for v in groups.values()) or 1
    rows = []
    for lab, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(ps) < MIN_TYPE:
            continue

        def med(vals):
            vals = [v for v in vals if v is not None]
            return median(vals) if vals else None
        clocks = [p.spin_direction_clock for p in ps if p.spin_direction_clock]
        rows.append({
            "label": lab, "n": len(ps), "usage": 100.0 * len(ps) / total,
            "velo": med(_f(p.velocity) for p in ps), "ivb": med(_f(p.vb_spin) for p in ps),
            "run": med(arm_run(p, throws) for p in ps), "spin": med(_f(p.total_spin) for p in ps),
            "clock": max(set(clocks), key=clocks.count) if clocks else None,
            # typical range (10th-90th percentile) -- min/max let one misread stretch it
            "velo_lo": _pctl([_f(p.velocity) for p in ps if p.velocity is not None], 0.1),
            "velo_hi": _pctl([_f(p.velocity) for p in ps if p.velocity is not None], 0.9),
        })
    return rows


def quiz_pool(raps, label_of):
    """Readings usable as quiz questions: labeled, with velo + movement, from
    pitchers who throw 2+ types (MIN_TYPE readings each)."""
    by_pid = defaultdict(lambda: defaultdict(int))
    for p in raps:
        lab = label_of(p)
        if lab:
            by_pid[p.player_id][lab] += 1
    ok_pids = {pid for pid, c in by_pid.items() if sum(1 for n in c.values() if n >= MIN_TYPE) >= 2}
    return [p for p in raps if p.player_id in ok_pids and label_of(p) and p.velocity is not None
            and p.vb_spin is not None and p.hb_trajectory is not None]


def pick(pool, rng=None, pitcher_id=None, exclude=None):
    rng = rng or random
    cands = [p for p in pool if (pitcher_id is None or p.player_id == pitcher_id)
             and (exclude is None or p.rapsodo_pitch_id != exclude)]
    return rng.choice(cands) if cands else None


def choices_for(pool, label_of, pitcher_id=None):
    """Answer options: his pitch types (named mode) or every type in the pool."""
    labs = {label_of(p) for p in pool if pitcher_id is None or p.player_id == pitcher_id}
    return sorted(l for l in labs if l)


def update_score(score, correct):
    """score: {"right", "total", "streak", "best"} -> new dict."""
    s = dict(score)
    s["total"] += 1
    if correct:
        s["right"] += 1
        s["streak"] += 1
        s["best"] = max(s["best"], s["streak"])
    else:
        s["streak"] = 0
    return s


NEW_SCORE = {"right": 0, "total": 0, "streak": 0, "best": 0}
