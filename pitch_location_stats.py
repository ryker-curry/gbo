"""
GBO — Location-based pitcher command analytics, built from the precise
plate_x/plate_z coordinates Game Tracking captures (see strike_zone.py)
rather than just the binary in-zone/out-of-zone check plate_discipline.py
already uses, or the single intended-vs-actual zone MATCH game_stats.py's
Execution % already uses. Requested directly by Ryker once real
coordinates were available instead of the old 9-zone buttons.

Two additions:

  1. compute_command_precision() -- Miss Distance (real inches between
     intended and actual location, per pitch and averaged per pitch
     type) plus Directional Miss Bias (average horizontal/vertical
     miss, labeled Arm-side/Glove-side and High/Low). A continuous
     command-precision number, unlike Execution %'s binary hit/miss (a
     1-inch miss and a 12-inch miss currently score identically there).

  2. compute_attack_zones() -- Heart/Shadow/Chase/Waste rates per pitch
     type, from strike_zone.classify_attack_zone(). Replaces the
     current binary Zone %/Chase % with a finer read on whether a
     pitcher lives on the edges or middles the ball.

IMPORTANT caveats, not silently glossed over:
  - Miss Distance/Directional Bias only use pitches with BOTH
    intended_plate_x/z (set live, pitching only) AND actual_plate_x/z
    (set in post-game Video Review) recorded -- pitches missing either
    are excluded. Every row reports how many pitches were actually
    "Reviewed" (both coordinates present) so a small sample isn't
    silently overstated as the full pitch count.
  - Directional Bias's Arm-side/Glove-side labels assume this app's
    documented plate_x sign convention (negative = 3B/left side, see
    strike_zone.py) and the standard RHP/LHP arm-side mapping: RHP
    arm-side = 3B side (negative x), LHP arm-side = 1B side (positive
    x) -- verified against the well-known fact that a RHP's arm-side
    run moves a fastball IN on a right-handed hitter (toward the 3B
    side). If throws isn't on file for a player, falls back to raw
    3B-side/1B-side labels rather than guessing a hand.
  - A near-zero average horizontal bias does NOT necessarily mean
    tight command -- a pitch type that misses arm-side and glove-side
    equally often will average out to ~0 even though it's actually
    wild in both directions. Miss Distance (the average magnitude,
    direction-agnostic) is the number to check for that; Directional
    Bias is specifically about systematic tendency, not spread.
  - Heart/Shadow/Chase/Waste boundaries are a GBO approximation of
    Baseball Savant's own four-tier system, not its exact published
    numbers (Savant's precise proprietary boundaries aren't fully
    public) -- see strike_zone.py's module comment for exactly what
    was used and where it came from. Comparable game-to-game and
    pitcher-to-pitcher within GBO, not a claim to match Savant's own
    Heart%/Shadow% figures exactly.
"""

from strike_zone import classify_attack_zone


def _pct(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def compute_command_precision(pitches, throws=None):
    """Miss Distance + Directional Miss Bias, overall and per pitch
    type, for a pitcher's own get_pitching_pitches() list. throws is
    the pitcher's Player.throws ('R'/'L') -- pass None (unknown) to get
    raw 3B-side/1B-side labels instead of Arm-side/Glove-side.
    Returns (overall_row, [row_per_pitch_type])."""
    reviewed = [
        p for p in pitches
        if p.intended_plate_x is not None and p.intended_plate_z is not None
        and p.actual_plate_x is not None and p.actual_plate_z is not None
    ]
    overall = _command_row("Overall", reviewed, throws)
    by_type = {}
    for p in reviewed:
        if p.pitch_type is not None:
            by_type.setdefault(p.pitch_type.type_name, []).append(p)
    rows = [
        _command_row(label, plist, throws)
        for label, plist in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]
    return overall, rows


def _command_row(label, plist, throws):
    n = len(plist)
    if n == 0:
        return {
            "Pitch Type": label, "Reviewed": 0, "Avg Miss (in)": None,
            "Horizontal Bias (in)": None, "Horizontal Label": None,
            "Vertical Bias (in)": None, "Vertical Label": None,
        }
    dists, horiz, vert = [], [], []
    for p in plist:
        dx = (float(p.actual_plate_x) - float(p.intended_plate_x)) * 12  # feet -> inches
        dz = (float(p.actual_plate_z) - float(p.intended_plate_z)) * 12
        dists.append((dx ** 2 + dz ** 2) ** 0.5)
        horiz.append(dx)
        vert.append(dz)
    avg_dist = sum(dists) / n
    avg_horiz = sum(horiz) / n
    avg_vert = sum(vert) / n

    if throws == "R":
        horiz_label = "Arm-side" if avg_horiz < 0 else "Glove-side" if avg_horiz > 0 else "Even"
    elif throws == "L":
        horiz_label = "Arm-side" if avg_horiz > 0 else "Glove-side" if avg_horiz < 0 else "Even"
    else:
        horiz_label = "3B-side" if avg_horiz < 0 else "1B-side" if avg_horiz > 0 else "Even"
    vert_label = "High" if avg_vert > 0 else "Low" if avg_vert < 0 else "Even"

    return {
        "Pitch Type": label, "Reviewed": n,
        "Avg Miss (in)": round(avg_dist, 1),
        "Horizontal Bias (in)": round(abs(avg_horiz), 1), "Horizontal Label": horiz_label,
        "Vertical Bias (in)": round(abs(avg_vert), 1), "Vertical Label": vert_label,
    }


def compute_attack_zones(pitches):
    """Heart/Shadow/Chase/Waste rates, overall and per pitch type, from
    actual_plate_x/z -- works for either a pitcher's or a hitter's
    pitch list, same "located" convention as plate_discipline.py.
    Returns (overall_row, [row_per_pitch_type])."""
    located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
    overall = _zone_row("Overall", located)
    by_type = {}
    for p in located:
        if p.pitch_type is not None:
            by_type.setdefault(p.pitch_type.type_name, []).append(p)
    rows = [
        _zone_row(label, plist)
        for label, plist in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]
    return overall, rows


def _zone_row(label, plist):
    n = len(plist)
    if n == 0:
        return {"Pitch Type": label, "Located": 0, "Heart %": None, "Shadow %": None, "Chase Zone %": None, "Waste %": None}
    counts = {"Heart": 0, "Shadow": 0, "Chase": 0, "Waste": 0}
    for p in plist:
        tier = classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z))
        counts[tier] += 1
    return {
        "Pitch Type": label, "Located": n,
        "Heart %": _pct(counts["Heart"], n), "Shadow %": _pct(counts["Shadow"], n),
        "Chase Zone %": _pct(counts["Chase"], n), "Waste %": _pct(counts["Waste"], n),
    }
