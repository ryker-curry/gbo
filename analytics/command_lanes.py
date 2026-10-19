"""
GBO -- Command by target lane (Oct 2026). Ryker, after Trafton O'Brien's
"Learning to miss better: designing a pitch command system": split
command by WHERE THE CATCHER SET UP. His example -- fastball misses
averaged ~5" on middle targets but 11"+ on either corner -- shows when
"working the edges" really means losing the zone.

Lanes come from the called spot (intended_plate_x/z), from the HITTER's
side so "in" always means toward the batter (catcher's view: a right-
handed hitter stands on the negative-x / 3B side):
    horizontal: In / Middle / Away   (thirds of the plate width;
                targets off the plate count as In / Away)
    vertical:   Up / Middle / Down   (thirds of the zone height;
                targets above / below count as Up / Down)
Per lane: pitches, average miss (inches from the called box's nearest
edge -- command_metrics.compute_miss, the same miss every command stat in
GBO uses), Zone Execution % (in the box or within 6 in), and the most
common miss direction (arm side / glove side / high / low).
"""

from collections import Counter

import strike_zone
from analytics import command_metrics

H_LANES = ("In", "Middle", "Away")
V_LANES = ("Up", "Middle", "Down")


def lane_of(x, z, batter_hand):
    """(vertical, horizontal) lane for a target point, or None if the
    batter's side isn't known (then In/Away can't be named)."""
    if x is None or z is None or batter_hand not in ("R", "L"):
        return None
    x, z = float(x), float(z)
    third_w = strike_zone.ZONE_HALF_WIDTH * 2 / 3
    if abs(x) <= third_w / 2:
        h = "Middle"
    else:
        inside = (x < 0) if batter_hand == "R" else (x > 0)
        h = "In" if inside else "Away"
    third_h = (strike_zone.ZONE_TOP - strike_zone.ZONE_BOTTOM) / 3
    if z > strike_zone.ZONE_TOP - third_h:
        v = "Up"
    elif z < strike_zone.ZONE_BOTTOM + third_h:
        v = "Down"
    else:
        v = "Middle"
    return v, h


def _summ(items):
    """items: [(miss_in, hit_spot, direction)]"""
    n = len(items)
    if not n:
        return None
    misses = [m for m, _, _ in items if m is not None]
    hits = [h for _, h, _ in items if h is not None]
    dirs = Counter(d for _, _, d in items if d and d != "On Target")
    top = dirs.most_common(1)[0] if dirs else None
    return {
        "n": n,
        "avg_miss": round(sum(misses) / len(misses), 1) if misses else None,
        "hit_pct": round(100 * sum(hits) / len(hits)) if hits else None,
        "lean": top[0] if top and top[1] / n >= 0.4 else None,   # only call a lean when it's a real habit
    }


def compute_lanes(pitches, batter_hands, throws):
    """pitches: GamePitch rows THIS pitcher threw. batter_hands:
    {game_pitch_id: 'R'/'L'} (game_stats.get_batter_hands). throws: his
    hand (for arm/glove-side miss labels).
    -> {"grid": {(v, h): summary}, "rows": {lane label: summary},
        "overall": summary, "skipped": pitches without a called spot,
        location or batter side}."""
    grid, by_h, by_v, everything = {}, {}, {}, []
    skipped = 0
    for p in pitches:
        if None in (p.intended_plate_x, p.intended_plate_z, p.actual_plate_x, p.actual_plate_z):
            skipped += 1
            continue
        lane = lane_of(p.intended_plate_x, p.intended_plate_z, batter_hands.get(p.game_pitch_id))
        if lane is None:
            skipped += 1
            continue
        dx, dz, dist = command_metrics.compute_miss(p.intended_plate_x, p.intended_plate_z, p.actual_plate_x, p.actual_plate_z)
        item = (dist, strike_zone.pitch_hit_spot(p), command_metrics.classify_miss_direction(dx, dz, throws))
        grid.setdefault(lane, []).append(item)
        by_h.setdefault(lane[1], []).append(item)
        by_v.setdefault(lane[0], []).append(item)
        everything.append(item)
    rows = {}
    for h in H_LANES:
        if h in by_h:
            rows[f"{h} ({'toward the hitter' if h == 'In' else 'away from the hitter' if h == 'Away' else 'middle of the plate'})"] = _summ(by_h[h])
    for v in V_LANES:
        if v in by_v:
            rows[f"{v} ({'top third or above' if v == 'Up' else 'bottom third or below' if v == 'Down' else 'belt high'})"] = _summ(by_v[v])
    return {"grid": {k: _summ(v) for k, v in grid.items()}, "rows": rows, "overall": _summ(everything), "skipped": skipped,
            "h": {h: _summ(v) for h, v in by_h.items()}, "v": {v: _summ(x) for v, x in by_v.items()}}


def takeaway(res, min_n=5):
    """One plain sentence comparing middle targets to the corners, or None."""
    rows = res["h"]
    mid = rows.get("Middle")
    edges = [rows[k] for k in ("In", "Away") if rows.get(k) and rows[k]["n"] >= min_n and rows[k]["avg_miss"] is not None]
    if not mid or mid["n"] < min_n or mid["avg_miss"] is None or not edges:
        return None
    worst = max(edges, key=lambda r: r["avg_miss"])
    side = "in" if worst is rows.get("In") else "away"
    gap = worst["avg_miss"] - mid["avg_miss"]
    if gap >= 3:
        return (f"Misses grow on the corners: {mid['avg_miss']:.1f}\" on middle setups vs {worst['avg_miss']:.1f}\" when the "
                f"glove is {side}. Working that edge is costing the zone.")
    if gap <= -3:
        return (f"He's sharper on the corners than in the middle ({worst['avg_miss']:.1f}\" {side} vs {mid['avg_miss']:.1f}\" "
                f"middle) -- the middle setups are the ones drifting.")
    return f"Command holds across the plate: {mid['avg_miss']:.1f}\" middle vs {worst['avg_miss']:.1f}\" on his loosest corner."
