"""
GBO -- Zone Execution % breakdown (Oct 2026, Ryker approved).

Hit = landed in the called cell or within strike_zone.HIT_SPOT_CUSHION_IN
(3 in) of it -- strike_zone.pitch_hit_spot, the same definition every
"Zone Execution %" / "Hit-the-spot %" number in GBO now uses.

breakdown(pitches, throws) -> {
  "overall":  {"pct", "hits", "n"},
  "by_type":  [{"label", "pct", "hits", "n"}]   most-thrown first
  "by_count": [{"label", "pct", "hits", "n"}]   first pitch / ahead / even / behind / two strikes
  "miss":     {"n", "up", "down", "arm", "glove", "over_middle", "lean"}  (% of MISSES)
}
Counts are from the pitcher's side: ahead = more strikes than balls.
Miss direction is measured from the called cell, arm/glove side by his hand.
"""

from collections import defaultdict

import strike_zone as sz
from analytics.command_metrics import miss_direction_axes

COUNT_GROUPS = ("First pitch", "Ahead", "Even", "Behind", "Two strikes")
MIN_SHOW = 5


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


def _row(label, flags):
    n = len(flags)
    hits = sum(1 for f in flags if f)
    return {"label": label, "pct": _pct(hits, n), "hits": hits, "n": n}


def count_group(p):
    b, s = p.balls_before, p.strikes_before
    if b is None or s is None:
        return None
    if b == 0 and s == 0:
        return "First pitch"
    if s == 2:
        return "Two strikes"
    if s > b:
        return "Ahead"
    if b > s:
        return "Behind"
    return "Even"


def breakdown(pitches, throws=None):
    graded = [(p, sz.pitch_hit_spot(p)) for p in pitches]
    graded = [(p, f) for p, f in graded if f is not None]
    if not graded:
        return None
    by_type = defaultdict(list)
    by_count = defaultdict(list)
    for p, f in graded:
        by_type[p.pitch_type.type_name if p.pitch_type else "Unspecified"].append(f)
        g = count_group(p)
        if g:
            by_count[g].append(f)
    misses = [p for p, f in graded if not f]
    dirs = {"up": 0, "down": 0, "arm": 0, "glove": 0}
    over_middle = 0
    for p in misses:
        level, zone = sz.call_cell(float(p.intended_plate_x), float(p.intended_plate_z))
        h, v, _d = sz.zone_miss_components_in(level, zone, float(p.actual_plate_x), float(p.actual_plate_z))
        h_lab, v_lab = miss_direction_axes(h, v, throws)
        if v_lab == "High":
            dirs["up"] += 1
        elif v_lab == "Low":
            dirs["down"] += 1
        if h_lab == "Arm Side":
            dirs["arm"] += 1
        elif h_lab == "Glove Side":
            dirs["glove"] += 1
        called_tier = sz.classify_attack_zone(float(p.intended_plate_x), float(p.intended_plate_z))
        if called_tier != "Heart" and sz.classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z)) == "Heart":
            over_middle += 1
    nm = len(misses)
    miss = {k: _pct(v, nm) for k, v in dirs.items()}
    miss["n"] = nm
    miss["over_middle"] = _pct(over_middle, nm)
    lean = []
    if nm >= MIN_SHOW:
        if (miss["up"] or 0) - (miss["down"] or 0) >= 15:
            lean.append("up")
        elif (miss["down"] or 0) - (miss["up"] or 0) >= 15:
            lean.append("down")
        if throws in ("R", "L"):
            if (miss["arm"] or 0) - (miss["glove"] or 0) >= 15:
                lean.append("arm side")
            elif (miss["glove"] or 0) - (miss["arm"] or 0) >= 15:
                lean.append("glove side")
    miss["lean"] = " and ".join(lean) if lean else None
    types = sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    return {
        "overall": _row("All pitches", [f for _p, f in graded]),
        "by_type": [_row(t, fl) for t, fl in types],
        "by_count": [_row(g, by_count[g]) for g in COUNT_GROUPS if by_count.get(g)],
        "miss": miss,
    }
