"""
GBO -- Hitter Hot Zones (Oct 2026, Ryker: "add heat maps for hitters
based on vs rhp, lhp and just one altogether. want hitters to know
where their hot zone is"). AVG / SLG on balls in play by pitch location,
13-zone layout (the 9 strike-zone cells plus 4 outside corners: up-left,
up-right, down-left, down-right), catcher's view like every other zone
chart in GBO.

Balls in play = pitch_outcome "In Play", sacrifices left out (they're
not at-bats). AVG = hits / BIP, SLG = total bases / BIP. Pitcher hand
comes from game_stats.get_pitcher_hands (roster throws, not the raw
opponent_hand column).
"""

from game_stats import get_pitcher_hands, HIT_OUTCOMES
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, derive_old_zone

TOTAL_BASES = {"1B": 1, "2B": 2, "3B": 3, "HR": 4}
SAC = {"Sac Bunt", "Sac Fly"}
OUTER = ("OUL", "OUR", "ODL", "ODR")   # outside: up-left, up-right, down-left, down-right (catcher's view)
ZONES = tuple(range(1, 10)) + OUTER
MIN_BIP = 3                             # fewer than this -> muted cell

_MID_X = 0.0
_MID_Z = (ZONE_BOTTOM + ZONE_TOP) / 2


def zone_of(p):
    """1-9 inside the zone, or an OUTER key. None if unlocated."""
    x, z = p.actual_plate_x, p.actual_plate_z
    if x is not None and z is not None:
        x, z = float(x), float(z)
        if abs(x) <= ZONE_HALF_WIDTH and ZONE_BOTTOM <= z <= ZONE_TOP:
            return derive_old_zone(x, z)
        return ("OU" if z >= _MID_Z else "OD") + ("L" if x < _MID_X else "R")
    if p.pitch_zone in range(1, 10):
        return p.pitch_zone
    return None


def _empty():
    return {z: {"bip": 0, "hits": 0, "tb": 0} for z in ZONES}


def _finish(cells):
    for c in cells.values():
        c["avg"] = c["hits"] / c["bip"] if c["bip"] else None
        c["slg"] = c["tb"] / c["bip"] if c["bip"] else None
    return cells


def hot_zones(pitches):
    cells = _empty()
    for p in pitches:
        if p.pitch_outcome != "In Play" or p.ab_outcome in SAC:
            continue
        z = zone_of(p)
        if z is None:
            continue
        c = cells[z]
        c["bip"] += 1
        if p.ab_outcome in HIT_OUTCOMES:
            c["hits"] += 1
            c["tb"] += TOTAL_BASES.get(p.ab_outcome, 0)
    return _finish(cells)


def totals(cells):
    bip = sum(c["bip"] for c in cells.values())
    hits = sum(c["hits"] for c in cells.values())
    tb = sum(c["tb"] for c in cells.values())
    return {"bip": bip, "avg": hits / bip if bip else None, "slg": tb / bip if bip else None}


def panels(db, pitches):
    """[(label, cells, totals)] for All, vs RHP, vs LHP."""
    hands = get_pitcher_hands(db, pitches)
    out = []
    for label, keep in (("All pitchers", None), ("vs RHP", "R"), ("vs LHP", "L")):
        ps = pitches if keep is None else [p for p in pitches if hands.get(p.game_pitch_id) == keep]
        cells = hot_zones(ps)
        out.append((label, cells, totals(cells)))
    return out


def hottest(cells, metric="avg"):
    ok = [(z, c) for z, c in cells.items() if c["bip"] >= MIN_BIP and c[metric] is not None]
    if not ok:
        return None
    return max(ok, key=lambda zc: (zc[1][metric], zc[1]["bip"]))
