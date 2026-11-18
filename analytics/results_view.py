"""
GBO -- Pitcher Profile > Results, rebuilt (Oct 2026, Ryker: "results
chart/graph needs work in pitcher profile").

Three pieces, all Shiny-free:

  scorecard()     one row per pitch type: usage, whiff, chase, hard-hit,
                  weak contact, RV/100, AVG/SLG against, K, BB, hits --
                  each graded against our staff on the SAME pitch type
                  (better / worse / same), so "is his slider good?" is
                  one look.
  contact_mix()   how balls in play were hit, per pitch type (adds to 100%).
  damage_grid()   run value by location on a 5x5 grid (catcher's view):
                  the 3x3 strike zone in the middle plus a ring for
                  pitches out of the zone.

Location is Rapsodo's (plate_x_ft / plate_z_ft on the linked
RapsodoPitch) -- never video review (Ryker, Oct 2026: "just use the
location from rapsodo"). Pass loc = sequencing.loc_map(...).

Run value is from the pitcher's side as stored on GamePitch: positive =
good for the hitter. RV/100 and the damage colors keep that convention
(red = hitter, blue = pitcher) like the rest of GBO.
"""

from collections import defaultdict

from game_stats import compute_pitch_type_breakdown
from plate_discipline import SWING_OUTCOMES
from strike_zone import is_in_zone, ZONE_BOTTOM, ZONE_TOP, ZONE_HALF_WIDTH

CONTACT_ORDER = [("Weak", "Weak"), ("Jammed", "Jammed"), ("Off the End", "Off the End"),
                 ("Clipped", "Clipped"), ("Solid Contact", "Solid"), ("Barreled", "Barreled")]
WEAK_KEYS = ("Weak %", "Jammed %", "Off the End %", "Clipped %")
HITS = ("1B", "2B", "3B", "HR")
MIN_PITCHES = 15      # fewer pitches of a type -> faded, not graded
MIN_CELL = 5          # fewer pitches in a damage cell -> gray

# (key, label, higher_is_better, "same" band). Bands are in the stat's own
# units: percentage points, runs per 100, or batting-average points.
METRICS = [
    ("whiff", "Whiff %", True, 5),
    ("chase", "Chase %", True, 5),
    ("hard", "Hard hit %", False, 8),
    ("weak", "Weak %", True, 8),
    ("rv100", "RV/100", False, 0.5),
    ("avg", "AVG", False, 0.040),
    ("slg", "SLG", False, 0.060),
]


def _chase(pitches, loc):
    """Swings at Rapsodo-located pitches outside the zone / those pitches."""
    out = [p for p in pitches if p.game_pitch_id in loc and not is_in_zone(*loc[p.game_pitch_id])]
    if not out:
        return None
    return round(100.0 * sum(1 for p in out if p.pitch_outcome in SWING_OUTCOMES) / len(out), 1)


def _row_stats(row, pitches, loc):
    ab = row.get("At Bats") or 0
    tb = (row.get("1B") or 0) + 2 * (row.get("2B") or 0) + 3 * (row.get("3B") or 0) + 4 * (row.get("HR") or 0)
    weak_parts = [row.get(k) for k in WEAK_KEYS]
    weak = round(sum(v for v in weak_parts if v is not None), 1) if row.get("Balls in Play") else None
    return {
        "type": row["Pitch Type"], "n": row["Total Pitches"], "usage": row["Pitch Usage %"],
        "whiff": row["Whiff %"], "chase": _chase(pitches, loc), "hard": row["Hard Hit %"], "weak": weak,
        "rv100": row["RV/100"], "bip": row["Balls in Play"],
        "avg": round(row["Hits"] / ab, 3) if ab else None,
        "slg": round(tb / ab, 3) if ab else None,
        "k": row["K's"], "bb": (row.get("BB") or 0) + (row.get("HBP") or 0), "hits": row["Hits"], "hr": row["HR"],
    }


def _by_type(pitches):
    out = defaultdict(list)
    for p in pitches:
        if p.pitch_type is not None and getattr(p, "is_pitch", True) is not False:
            out[p.pitch_type.type_name].append(p)
    return out


def _real(pitches):
    return [p for p in pitches if getattr(p, "is_pitch", True) is not False]


def scorecard(mine, team, loc):
    """{"rows": [...], "total": {...}} -- each row has the stats above plus
    "grade": {metric: "better" / "worse" / "same" / None} vs our staff on
    that pitch type, and "staff": {metric: value}."""
    mine, team = _real(mine), _real(team)
    rows_m = compute_pitch_type_breakdown(mine)
    rows_t = {r["Pitch Type"]: r for r in compute_pitch_type_breakdown(team)}
    mine_by, team_by = _by_type(mine), _by_type(team)
    out, total = [], None
    for r in rows_m:
        if r["Pitch Type"] == "Total":
            total = _row_stats(r, mine, loc)
            continue
        s = _row_stats(r, mine_by.get(r["Pitch Type"], []), loc)
        t = rows_t.get(r["Pitch Type"])
        staff = _row_stats(t, team_by.get(r["Pitch Type"], []), loc) if t else {}
        grade = {}
        for key, _label, higher, band in METRICS:
            v, b = s.get(key), staff.get(key)
            if v is None or b is None or s["n"] < MIN_PITCHES:
                grade[key] = None
            elif abs(v - b) < band:
                grade[key] = "same"
            else:
                grade[key] = "better" if (v > b) == higher else "worse"
        s.update(grade=grade, staff={k: staff.get(k) for k, *_ in METRICS}, thin=s["n"] < MIN_PITCHES)
        out.append(s)
    return {"rows": out, "total": total}


def contact_mix(mine):
    """[{type, bip, parts: [(label, pct), ...]}] for pitch types with a ball in play."""
    out = []
    for r in compute_pitch_type_breakdown(_real(mine)):
        if r["Pitch Type"] == "Total" or not r["Balls in Play"]:
            continue
        parts = [(label, r.get(f"{key} %") or 0.0) for key, label in CONTACT_ORDER]
        out.append({"type": r["Pitch Type"], "bip": r["Balls in Play"], "parts": parts,
                    "unrated": round(max(0.0, 100.0 - sum(v for _l, v in parts)), 1)})
    return out


# 5x5 damage grid, catcher's view. Columns run 3B side -> 1B side (plate x
# negative -> positive), rows top -> bottom. Middle 3x3 = the strike zone in
# thirds; the outer ring = out of the zone.
def _band(v, lo, hi):
    if v < lo:
        return 0
    if v > hi:
        return 4
    third = (hi - lo) / 3
    return 1 + min(2, int((v - lo) / third))


def cell_of(x, z):
    col = _band(x, -ZONE_HALF_WIDTH, ZONE_HALF_WIDTH)
    row = 4 - _band(z, ZONE_BOTTOM, ZONE_TOP)
    return row, col


def damage_grid(mine, loc):
    """{"cells": {(row, col): {...}}, "located": n, "total": n}. Each cell:
    n pitches, avg_rv (per pitch, + = hitter), bip, hits, hr, k (strikeouts
    ending there)."""
    mine = _real(mine)
    cells = defaultdict(lambda: {"n": 0, "rv": [], "bip": 0, "hits": 0, "hr": 0, "k": 0})
    located = 0
    for p in mine:
        xy = loc.get(p.game_pitch_id)
        if xy is None:
            continue
        located += 1
        c = cells[cell_of(*xy)]
        c["n"] += 1
        if p.run_value is not None:
            c["rv"].append(float(p.run_value))
        if p.pitch_outcome == "In Play":
            c["bip"] += 1
        if p.ends_plate_appearance and p.ab_outcome in HITS:
            c["hits"] += 1
            c["hr"] += p.ab_outcome == "HR"
        if p.ends_plate_appearance and p.ab_outcome in ("K", "K (Looking)", "K - Reached on Dropped 3rd"):
            c["k"] += 1
    out = {}
    for key, c in cells.items():
        out[key] = {"n": c["n"], "avg_rv": (sum(c["rv"]) / len(c["rv"])) if c["rv"] else None,
                    "bip": c["bip"], "hits": c["hits"], "hr": c["hr"], "k": c["k"], "thin": c["n"] < MIN_CELL}
    return {"cells": out, "located": located, "total": len(mine)}
