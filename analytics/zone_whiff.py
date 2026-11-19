"""
GBO -- In-zone whiff "check engine light" (Oct 2026, from SABR Tooth
Tigers' "Are In-Zone Misses a Check Engine Light for Your Swing?": most
hitters switch between a low-whiff and a high-whiff state, about 10
points apart, and a rolling in-zone whiff rate spots the switch early).

In-zone swings (located pitches inside the strike zone that he swung at),
in the order he saw them. Rolling WINDOW-swing whiff %, against his own
rate over the whole range. FLAG when the latest window is FLAG_PTS or
more above his normal and he has MIN_SWINGS in-zone swings. The article's
state model needs bat-tracking data; this is the simple rolling version.
"""

from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import is_in_zone, zone_whiff_location

WINDOW = 30
FLAG_PTS = 10.0
MIN_SWINGS = 40


def zone_swings(pitches):
    ps = sorted(pitches, key=lambda p: (getattr(p, "game_id", 0) or 0, p.pitch_sequence or 0))
    # Nov 2026: same season-sourced locations as Zone Whiff % everywhere
    # else (Rapsodo fall / SmartPark spring, strike_zone.zone_whiff_location).
    out = []
    for p in ps:
        if p.pitch_outcome not in SWING_OUTCOMES:
            continue
        loc = zone_whiff_location(p)
        if loc is not None and is_in_zone(*loc):
            out.append(p)
    return out


def rolling(pitches):
    """-> {n, base, points: [(i, pct)], last, flag, gap}"""
    sw = zone_swings(pitches)
    n = len(sw)
    miss = [1 if p.pitch_outcome in WHIFF_OUTCOMES else 0 for p in sw]
    base = 100.0 * sum(miss) / n if n else None
    pts = []
    for i in range(WINDOW, n + 1):
        pts.append((i, 100.0 * sum(miss[i - WINDOW:i]) / WINDOW))
    last = pts[-1][1] if pts else None
    gap = (last - base) if last is not None and base is not None else None
    return {"n": n, "base": base, "points": pts, "last": last, "gap": gap,
            "flag": bool(n >= MIN_SWINGS and gap is not None and gap >= FLAG_PTS)}
