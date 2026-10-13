"""
GBO -- Pitcher insights from Ryker's Oct 2026 reading list ("use all of
these resources ... see if these fit our model and can improve our
model"). Pure functions -- callers pass ORM rows, nothing here queries.

  1. seam_shift()      Samuel Midgette / Driveline "Most Seam-Shifted
                       Sinkers": how far a pitch's real movement direction
                       sits from the direction its spin alone explains.
                       Rapsodo logs both (VB/HB trajectory = what the ball
                       did, VB/HB spin = what Magnus spin predicts); its
                       own SSW columns come through blank, so the gap is
                       computed here. Reported in clock minutes like the
                       Driveline graphic (1 hour = 30 deg, 1 min = 0.5 deg).
  2. plane()           Midgette, "Understanding a Pitcher's Plane": with no
                       biomech lab, the line from his primary fastball to
                       his primary breaking ball on the movement plot
                       approximates the plane his arm works in. Steep line
                       = vertical mover, flat = horizontal mover (the Luke
                       Wiseman thread: a vertical guy moving horizontally
                       loses command). Pitches far off that line are built
                       against his plane; release window = where each
                       pitch leaves the hand vs his fastball.
  3. get_ahead()       "Get Ahead, Then Miss Bats" (Skubal): 0-0 strike /
                       zone / swing / whiff rates and what happens after
                       0-1 vs 1-0 (Skubal: 41% K ahead vs 23% behind).
  4. usage_split()     Midgette's Yoendrys Gomez posts: same stuff, new
                       usage. Two periods side by side -- did the mix
                       change while the shapes held?
  5. outs_per_xbh()    Driveline "Outs per XBH" by pitch type.

Thresholds are labeled as GBO's starting points, not research cutoffs --
the articles give none for college data, and our samples are small.
"""

import math
from collections import defaultdict
from statistics import median, pstdev, mean

from game_stats import HIT_OUTCOMES, K_OUTCOMES, STRIKE_OUTCOMES
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import is_in_zone

FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker")
BREAKING = ("Slider", "Sweeper", "Curveball", "Slurve", "Knuckle Curve")
XBH = ("2B", "3B", "HR")
TB = {"1B": 1, "2B": 2, "3B": 3, "HR": 4}
NON_AB = {"BB", "IBB", "HBP", "Sac Bunt", "Sac Fly", "No Result", "CI"}

MIN_MOVE_IN = 4.0       # below this much break the direction is noise
MIN_TYPE_N = 10         # readings of a pitch type before we say anything
SSW_MIN = 30            # clock minutes. Driveline splits MLB sinkers at 50 (Hawk-Eye axis);
                        # Rapsodo reads tighter -- our staff's fastballs / changeups sit
                        # around 15-25 min, the clearly seam-shifted 2-seamers 30+.
SSW_MIN_IN = 3.0        # and the non-spin movement has to be real inches
# Seam-shifted wake is a fastball / changeup story; breaking balls are
# gyro-heavy, so their movement direction from spin is unreliable on
# Rapsodo (our sliders show 50-140 min "gaps" that are measurement, not seams).
SSW_TYPES = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker", "Changeup", "Splitter")
VERTICAL_DEG = 55       # FB->BB line steeper than this = vertical mover
HORIZONTAL_DEG = 35     # flatter than this = horizontal mover
OFF_PLANE_IN = 6.0      # pitch shape this far off his FB->BB line
RELEASE_OFFSET_IN = 3.0 # mean release this far from his FB = a tell
RELEASE_SD_IN = 6.0     # release point wander within a pitch type (staff 75th pct, all sessions pooled)
MIN_FIRST = 25          # first pitches before a pitcher is ranked
USAGE_SHIFT = 8.0       # usage points that count as a real change
VELO_SHIFT = 1.5
MOVE_SHIFT = 2.5


def _f(v):
    return float(v) if v is not None else None


def _type(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) is not None else None


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _sgn(throws):
    return -1.0 if throws == "L" else 1.0


# ---------------------------------------------------------------------------
# 1. Seam shift
# ---------------------------------------------------------------------------

def _wrap(deg):
    while deg > 180:
        deg -= 360
    while deg <= -180:
        deg += 360
    return deg


def ssw_of(r, throws):
    """One Rapsodo reading -> {"gap": signed minutes, "h": extra arm-side in,
    "v": extra ride in} or None. Positive gap = the ball moved more toward
    his arm side / down than spin explains (sinker-style seam shift)."""
    ht, vt, hs, vs = (_f(r.hb_trajectory), _f(r.vb_trajectory), _f(r.hb_spin), _f(r.vb_spin))
    if None in (ht, vt, hs, vs):
        return None
    s = _sgn(throws)
    ht, hs = ht * s, hs * s
    if math.hypot(ht, vt) < MIN_MOVE_IN or math.hypot(hs, vs) < MIN_MOVE_IN:
        return None
    a_t = math.degrees(math.atan2(vt, ht))
    a_s = math.degrees(math.atan2(vs, hs))
    # Clockwise from the arm side = more arm-side run / more sink.
    gap = -_wrap(a_t - a_s) * 2.0
    return {"gap": gap, "h": ht - hs, "v": vt - vs}


def _shift_words(h, v):
    parts = []
    if abs(v) >= 1.0:
        parts.append(f"{abs(v):.1f} in more {'ride' if v > 0 else 'sink'}")
    if abs(h) >= 1.0:
        parts.append(f"{abs(h):.1f} in more {'arm-side run' if h > 0 else 'glove-side cut'}")
    return " and ".join(parts) or "about what the spin says"


def seam_shift_by_type(raps, throws):
    """{pitch type: {"n", "gap", "abs_gap", "h", "v", "ssw", "words"}} for one pitcher."""
    by = defaultdict(list)
    for r in raps:
        t = _type(r)
        s = ssw_of(r, throws) if t in SSW_TYPES else None
        if s:
            by[t].append(s)
    out = {}
    for t, rows in by.items():
        if len(rows) < MIN_TYPE_N:
            continue
        gap = median(x["gap"] for x in rows)
        h = median(x["h"] for x in rows)
        v = median(x["v"] for x in rows)
        out[t] = {"n": len(rows), "gap": gap, "abs_gap": abs(gap), "h": h, "v": v,
                  "ssw": abs(gap) >= SSW_MIN and math.hypot(h, v) >= SSW_MIN_IN, "words": _shift_words(h, v)}
    return out


def _game_rates(gps):
    swings = [p for p in gps if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = sum(1 for p in swings if p.pitch_outcome in WHIFF_OUTCOMES)
    bip = [p for p in gps if p.pitch_outcome == "In Play" and p.batted_ball_type]
    gb = sum(1 for p in bip if p.batted_ball_type == "Ground Ball")
    return {"pitches": len(gps), "swings": len(swings), "whiff": _pct(whiffs, len(swings)),
            "bip": len(bip), "gb": _pct(gb, len(bip))}


def seam_shift_staff(raps_by_pid, throws_by_pid, game_by_id):
    """Staff view. raps_by_pid {pid: [RapsodoPitch]}; game_by_id {game_pitch_id:
    GamePitch}. -> {"rows": [per pitcher x type, biggest gap first],
    "type_avg": {type: mean abs gap}, "split": {family: {"ssw": rates, "trad": rates}}}"""
    rows = []
    for pid, raps in raps_by_pid.items():
        th = throws_by_pid.get(pid)
        stats = seam_shift_by_type(raps, th)
        by_type = defaultdict(list)
        for r in raps:
            if r.game_pitch_id in game_by_id and _type(r):
                by_type[_type(r)].append(game_by_id[r.game_pitch_id])
        for t, s in stats.items():
            rows.append({"pid": pid, "type": t, **s, "game": _game_rates(by_type.get(t, []))})
    rows.sort(key=lambda x: -x["abs_gap"])
    type_avg = defaultdict(list)
    for r in rows:
        type_avg[r["type"]].append(r["abs_gap"])
    split = {}
    for fam, types in (("Fastballs", FASTBALLS), ("Changeups", ("Changeup", "Splitter"))):
        ssw, trad = [], []
        for pid, raps in raps_by_pid.items():
            stats = seam_shift_by_type(raps, throws_by_pid.get(pid))
            for r in raps:
                t = _type(r)
                if t in types and t in stats and r.game_pitch_id in game_by_id:
                    (ssw if stats[t]["ssw"] else trad).append(game_by_id[r.game_pitch_id])
        split[fam] = {"ssw": _game_rates(ssw), "trad": _game_rates(trad)}
    return {"rows": rows, "type_avg": {t: mean(v) for t, v in type_avg.items()}, "split": split}


# ---------------------------------------------------------------------------
# 2. Plane + preference
# ---------------------------------------------------------------------------

def _shape(raps, throws):
    rows = []
    s = _sgn(throws)
    for r in raps:
        h = _f(r.hb_trajectory) if r.hb_trajectory is not None else _f(r.hb_spin)
        v = _f(r.vb_trajectory) if r.vb_trajectory is not None else _f(r.vb_spin)
        if h is None or v is None:
            continue
        rows.append((h * s, v, _f(r.velocity), _f(r.release_height), _f(r.release_side)))
    if not rows:
        return None
    rel = [(x[3], x[4]) for x in rows if x[3] is not None and x[4] is not None]
    return {"n": len(rows), "h": median(x[0] for x in rows), "v": median(x[1] for x in rows),
            "velo": median([x[2] for x in rows if x[2] is not None]) if any(x[2] is not None for x in rows) else None,
            "rel_h": mean(a for a, _b in rel) * 12 if rel else None,
            "rel_s": mean(b for _a, b in rel) * 12 * s if rel else None,
            "rel_sd": math.sqrt((pstdev([a for a, _b in rel]) ** 2 + pstdev([b for _a, b in rel]) ** 2)) * 12
            if len(rel) >= 3 else None}


def plane(raps, throws, arm_angle=None):
    """-> dict or None. Keys: shapes {type: shape}, fb, bb (type names),
    angle (deg of the FB->BB line, 90 = straight up/down), kind
    ('vertical'/'horizontal'/'diagonal'), fb_says, agree, off (list of
    {type, dist}), release (list of {type, offset, sd, flag}), lines."""
    by = defaultdict(list)
    for r in raps:
        t = _type(r)
        if t:
            by[t].append(r)
    shapes = {t: _shape(rs, throws) for t, rs in by.items() if len(rs) >= MIN_TYPE_N}
    shapes = {t: s for t, s in shapes.items() if s}
    fbs = [t for t in shapes if t in FASTBALLS]
    bbs = [t for t in shapes if t in BREAKING]
    if not fbs or not bbs:
        return None
    fb = max(fbs, key=lambda t: shapes[t]["n"])
    bb = max(bbs, key=lambda t: shapes[t]["n"])
    F, B = shapes[fb], shapes[bb]
    dh, dv = B["h"] - F["h"], B["v"] - F["v"]
    angle = math.degrees(math.atan2(abs(dv), abs(dh) or 1e-9))
    kind = "vertical" if angle >= VERTICAL_DEG else ("horizontal" if angle <= HORIZONTAL_DEG else "diagonal")
    # What the fastball alone says (ride vs run), as a second opinion.
    if F["v"] >= 16 and F["h"] <= 12:
        fb_says = "vertical"
    elif F["h"] >= 14 or F["v"] <= 11:
        fb_says = "horizontal"
    else:
        fb_says = "diagonal"
    agree = fb_says == kind or "diagonal" in (fb_says, kind)
    L = math.hypot(dh, dv) or 1e-9
    off = []
    for t, s in shapes.items():
        if t in (fb, bb):
            continue
        dist = abs(dv * (s["h"] - F["h"]) - dh * (s["v"] - F["v"])) / L
        off.append({"type": t, "dist": dist, "off": dist >= OFF_PLANE_IN})
    off.sort(key=lambda x: -x["dist"])
    release = []
    for t, s in shapes.items():
        offset = None
        if None not in (s["rel_h"], s["rel_s"], F["rel_h"], F["rel_s"]) and t != fb:
            offset = math.hypot(s["rel_h"] - F["rel_h"], s["rel_s"] - F["rel_s"])
        release.append({"type": t, "n": s["n"], "offset": offset, "sd": s["rel_sd"],
                        "tell": offset is not None and offset >= RELEASE_OFFSET_IN,
                        "wander": s["rel_sd"] is not None and s["rel_sd"] >= RELEASE_SD_IN})
    release.sort(key=lambda x: (x["type"] != fb, -(x["offset"] or 0)))

    lines = []
    word = {"vertical": "a vertical mover", "horizontal": "a horizontal mover", "diagonal": "in between (diagonal)"}[kind]
    lines.append(f"His {fb.lower()} to {bb.lower()} line runs {angle:.0f}° -- he looks like {word}.")
    if arm_angle is not None:
        lines.append(f"Arm angle about {arm_angle:.0f}°.")
    if not agree:
        lines.append(f"Mixed signal: the fastball by itself reads {fb_says} ({F['v']:.0f} in ride, {F['h']:.0f} in run). "
                     "Check high-speed video before changing anything.")
    for o in off:
        if o["off"]:
            lines.append(f"The {o['type'].lower()} sits {o['dist']:.0f} in off his plane -- likely a pitch he has to manufacture.")
    for r in release:
        if r["tell"]:
            lines.append(f"The {r['type'].lower()} leaves his hand {r['offset']:.1f} in from his fastball release -- hitters can see it early.")
    wander = [r for r in release if r["wander"]]
    if wander:
        lines.append("Release point wanders on his " + ", ".join(f"{r['type'].lower()} ({r['sd']:.1f} in)" for r in wander)
                     + " -- a moving release usually means a moving plane.")
    if kind == "vertical":
        lines.append("Build around ride and depth: a firm splitter or vertical changeup and a 12-6 curve fit him; "
                     "a big sweeper is working against his plane.")
    elif kind == "horizontal":
        lines.append("Build around run and sweep: sinker, sweeper and a fading changeup fit him; "
                     "a 12-6 curve or chasing ride is working against his plane.")
    return {"shapes": shapes, "fb": fb, "bb": bb, "angle": angle, "kind": kind, "fb_says": fb_says,
            "agree": agree, "off": off, "release": release, "lines": lines}


# ---------------------------------------------------------------------------
# 3. Get ahead, then miss bats
# ---------------------------------------------------------------------------

def _pas(pitches):
    ps = sorted([p for p in pitches if getattr(p, "is_pitch", True) is not False],
                key=lambda p: (p.game_id or 0, p.pitch_sequence or 0))
    pas, cur = [], []
    for p in ps:
        if cur and (p.pa_pitch_number == 1 or p.game_id != cur[-1].game_id or cur[-1].ends_plate_appearance):
            pas.append(cur)
            cur = []
        cur.append(p)
    if cur:
        pas.append(cur)
    return pas


def _line(pas):
    done = [pa for pa in pas if pa[-1].ends_plate_appearance and pa[-1].ab_outcome not in (None, "No Result")]
    ends = [pa[-1].ab_outcome for pa in done]
    ab = sum(1 for o in ends if o not in NON_AB)
    h = sum(1 for o in ends if o in HIT_OUTCOMES)
    tb = sum(TB.get(o, 0) for o in ends)
    bb = sum(1 for o in ends if o in ("BB", "IBB"))
    hbp = sum(1 for o in ends if o == "HBP")
    k = sum(1 for o in ends if o in K_OUTCOMES)
    obp_den = ab + bb + hbp + sum(1 for o in ends if o == "Sac Fly")
    obp = (h + bb + hbp) / obp_den if obp_den else None
    slg = tb / ab if ab else None
    return {"pa": len(done), "k": _pct(k, len(done)), "bb": _pct(bb, len(done)),
            "ops": (obp + slg) if obp is not None and slg is not None else None}


def get_ahead(pitches, loc=None):
    """One pitcher's game pitches -> {"first": {...}, "ahead": line after 0-1,
    "behind": line after 1-0, "gap": K% points}."""
    loc = loc or {}
    pas = _pas(pitches)
    firsts = [pa[0] for pa in pas if pa[0].balls_before == 0 and pa[0].strikes_before == 0]
    n = len(firsts)
    strikes = sum(1 for p in firsts if p.pitch_outcome in STRIKE_OUTCOMES)
    swings = sum(1 for p in firsts if p.pitch_outcome in SWING_OUTCOMES)
    whiffs = sum(1 for p in firsts if p.pitch_outcome in WHIFF_OUTCOMES)
    located = [p for p in firsts if p.game_pitch_id in loc]
    zone = sum(1 for p in located if is_in_zone(*loc[p.game_pitch_id]))
    ahead = [pa for pa in pas if len(pa) >= 2 and pa[0].balls_before == 0 and pa[0].strikes_before == 0
             and pa[0].pitch_outcome in STRIKE_OUTCOMES and not pa[0].ends_plate_appearance]
    behind = [pa for pa in pas if len(pa) >= 2 and pa[0].balls_before == 0 and pa[0].strikes_before == 0
              and pa[0].pitch_outcome == "Ball"]
    a, b = _line(ahead), _line(behind)
    gap = (a["k"] - b["k"]) if a["k"] is not None and b["k"] is not None else None
    return {"first": {"n": n, "strike": _pct(strikes, n), "swing": _pct(swings, n),
                      "whiff100": round(100.0 * whiffs / n, 1) if n else None,
                      "zone": _pct(zone, len(located)), "located": len(located)},
            "ahead": a, "behind": b, "gap": gap}


def get_ahead_staff(pitches_by_pid, loc=None):
    """{pid: get_ahead(...)} for pitchers with MIN_FIRST first pitches, plus
    "avg" (pooled staff) under key None."""
    out = {}
    pooled = []
    for pid, ps in pitches_by_pid.items():
        g = get_ahead(ps, loc)
        pooled.extend(ps)
        if g["first"]["n"] >= MIN_FIRST:
            out[pid] = g
    out[None] = get_ahead(pooled, loc)
    return out


def rank_of(staff, pid, getter, higher=True):
    vals = [(p, getter(g)) for p, g in staff.items() if p is not None and getter(g) is not None]
    if pid not in dict(vals):
        return None
    vals.sort(key=lambda x: -x[1] if higher else x[1])
    return [p for p, _v in vals].index(pid) + 1, len(vals)


def get_ahead_lines(g, staff_avg):
    f, sf = g["first"], staff_avg["first"]
    out = []
    if f["strike"] is not None:
        out.append(f"Wins the first pitch {f['strike']:.0f}% of the time (staff {sf['strike'] or 0:.0f}%).")
    if g["gap"] is not None:
        out.append(f"After 0-1 he strikes out {g['ahead']['k']:.0f}% of hitters; after 1-0, {g['behind']['k']:.0f}% -- "
                   f"a {g['gap']:+.0f}-point swing (staff {staff_avg['gap'] or 0:+.0f}).")
        if g["gap"] >= 15:
            out.append("Strike one turns into strikeouts for him -- attack 0-0.")
        elif g["gap"] < 5:
            out.append("Getting ahead isn't turning into put-aways yet -- the 0-1 / 1-2 pitch is the work.")
    if f["whiff100"] is not None:
        out.append(f"{f['whiff100']:.1f} whiffs per 100 first pitches (staff {sf['whiff100'] or 0:.1f}).")
    return out


# ---------------------------------------------------------------------------
# 4. Usage split + 5. Outs per XBH
# ---------------------------------------------------------------------------

def usage(pitches):
    real = [p for p in pitches if getattr(p, "is_pitch", True) is not False and _type(p)]
    n = len(real)
    c = defaultdict(int)
    for p in real:
        c[_type(p)] += 1
    return {t: 100.0 * k / n for t, k in c.items()} if n else {}, n


def shapes_by_type(raps, throws):
    by = defaultdict(list)
    for r in raps:
        if _type(r):
            by[_type(r)].append(r)
    return {t: _shape(rs, throws) for t, rs in by.items() if len(rs) >= 5}


def results_line(pitches):
    real = [p for p in pitches if getattr(p, "is_pitch", True) is not False]
    pas = _pas(real)
    ln = _line(pas)
    swings = [p for p in real if p.pitch_outcome in SWING_OUTCOMES]
    whiff = _pct(sum(1 for p in swings if p.pitch_outcome in WHIFF_OUTCOMES), len(swings))
    rv = [float(p.run_value) for p in real if p.run_value is not None]
    return {**ln, "pitches": len(real), "whiff": whiff, "rv100": round(100 * sum(rv) / len(rv), 2) if rv else None}


def usage_split(a_pitches, b_pitches, a_raps, b_raps, throws):
    ua, na = usage(a_pitches)
    ub, nb = usage(b_pitches)
    sa, sb = shapes_by_type(a_raps, throws), shapes_by_type(b_raps, throws)
    types = sorted(set(ua) | set(ub), key=lambda t: -(ub.get(t, 0) + ua.get(t, 0)))
    rows = []
    for t in types:
        x, y = sa.get(t), sb.get(t)
        stuff = None
        if x and y:
            dv = (y["velo"] - x["velo"]) if x["velo"] is not None and y["velo"] is not None else 0.0
            dm = math.hypot(y["h"] - x["h"], y["v"] - x["v"])
            stuff = {"dvelo": dv, "dmove": dm, "changed": abs(dv) >= VELO_SHIFT or dm >= MOVE_SHIFT, "a": x, "b": y}
        rows.append({"type": t, "a": ua.get(t, 0.0), "b": ub.get(t, 0.0), "d": ub.get(t, 0.0) - ua.get(t, 0.0),
                     "shift": abs(ub.get(t, 0.0) - ua.get(t, 0.0)) >= USAGE_SHIFT, "stuff": stuff})
    ra, rb = results_line(a_pitches), results_line(b_pitches)
    lines = []
    moved = [r for r in rows if r["shift"]]
    stuff_changed = [r for r in rows if r["stuff"] and r["stuff"]["changed"]]
    if moved:
        lines.append("Usage changed: " + ", ".join(f"{r['type']} {r['a']:.0f}% → {r['b']:.0f}%" for r in moved) + ".")
    else:
        lines.append(f"No pitch moved more than {USAGE_SHIFT:.0f} points of usage.")
    if stuff_changed:
        lines.append("Stuff changed too: " + ", ".join(
            f"{r['type']} ({r['stuff']['dvelo']:+.1f} mph, {r['stuff']['dmove']:.1f} in of movement)" for r in stuff_changed) + ".")
    elif any(r["stuff"] for r in rows):
        lines.append("Shapes and velo held -- any change in results is the mix, not the stuff.")
    if ra["k"] is not None and rb["k"] is not None:
        lines.append(f"K% {ra['k']:.0f} → {rb['k']:.0f}, BB% {ra['bb']:.0f} → {rb['bb']:.0f}"
                     + (f", OPS against {ra['ops']:.3f} → {rb['ops']:.3f}".replace("0.", ".") if ra["ops"] is not None and rb["ops"] is not None else "")
                     + ".")
    return {"rows": rows, "a": {"n": na, **ra}, "b": {"n": nb, **rb}, "lines": lines}


def outs_on(p):
    """Outs recorded on a PA-ending pitch (strikeouts, in-play outs, double plays)."""
    if not p.ends_plate_appearance:
        return 0
    if p.outs_before is not None and p.outs_after is not None:
        return max(0, min(3, p.outs_after) - p.outs_before)
    return 1 if p.ab_outcome in K_OUTCOMES + ("Groundout", "Flyout", "Lineout", "Popout") else 0


def outs_per_xbh(pitches):
    """[{type, pitches, outs, xbh, ratio}] sorted best first (ratio None = no XBH)."""
    by = defaultdict(lambda: {"pitches": 0, "outs": 0, "xbh": 0})
    for p in pitches:
        if getattr(p, "is_pitch", True) is False or not _type(p):
            continue
        d = by[_type(p)]
        d["pitches"] += 1
        d["outs"] += outs_on(p)
        if p.ends_plate_appearance and p.ab_outcome in XBH:
            d["xbh"] += 1
    rows = [{"type": t, **d, "ratio": (d["outs"] / d["xbh"]) if d["xbh"] else None} for t, d in by.items()]
    rows.sort(key=lambda r: -(r["ratio"] if r["ratio"] is not None else r["outs"] + 1000))
    return rows
