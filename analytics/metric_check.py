"""
GBO -- Metric check (Oct 2026, from "I Built a Baseball Metric. Here's
What I Learned": test your own stats before trusting them). Two checks,
staff-wide, on the date range picked on Data Health:

1) SPLIT-HALF RELIABILITY -- for each pitcher, split his pitches into odd
   and even (in order thrown), compute the stat on each half, and
   correlate the halves across pitchers. Stepped up to the full sample
   with Spearman-Brown (2r / (1 + r)). High = the stat mostly reflects
   the pitcher; low = mostly noise at our sample size. Pitchers need
   MIN_HALF pitches per half; the check needs MIN_PITCHERS pitchers.
     Whiff %, CSW %, Strike %, Chase %, Zone Execution % -- charted game pitches
     Stuff+ -- Rapsodo readings (bullpen + game), per-pitch Stuff+ averaged
     Command+ -- game pitches with a called spot

2) BULLPEN -> GAME -- does a pitcher's bullpen Stuff+ (bullpen readings
   only) line up with his game Whiff % and CSW %? Pearson r across
   pitchers with MIN_BP bullpen readings and MIN_GAME game pitches.

READ: >= STABLE stable, >= GETTING getting there, below = mostly noise.
"""

from statistics import mean

from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import is_in_zone, pitch_hit_spot

MIN_HALF = 20
MIN_PITCHERS = 5
MIN_BP = 20
MIN_GAME = 30
STABLE = 0.7
GETTING = 0.4
STRIKES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / (sxx * syy) ** 0.5


def spearman_brown(r):
    if r is None:
        return None
    if r <= 0:
        return r      # no step-up for a negative half-vs-half r -- it's noise either way
    return 2 * r / (1 + r)


def read(r):
    if r is None:
        return "—"
    if r >= STABLE:
        return "stable"
    if r >= GETTING:
        return "getting there"
    return "mostly noise so far"


def _pct(a, b):
    return 100.0 * a / b if b else None


def whiff(ps):
    sw = [p for p in ps if p.pitch_outcome in SWING_OUTCOMES]
    return _pct(sum(1 for p in sw if p.pitch_outcome in WHIFF_OUTCOMES), len(sw))


def csw(ps):
    return _pct(sum(1 for p in ps if p.pitch_outcome in ("Called Strike", "Swing and Miss")), len(ps))


def strike(ps):
    return _pct(sum(1 for p in ps if p.pitch_outcome in STRIKES), len(ps))


def chase(ps):
    out = [p for p in ps if p.actual_plate_x is not None and p.actual_plate_z is not None
           and not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    return _pct(sum(1 for p in out if p.pitch_outcome in SWING_OUTCOMES), len(out))


def zone_exec(ps):
    flags = [pitch_hit_spot(p) for p in ps]
    flags = [f for f in flags if f is not None]
    return _pct(sum(1 for f in flags if f), len(flags))


GAME_STATS = [("Whiff %", whiff), ("CSW %", csw), ("Strike %", strike), ("Chase %", chase),
              ("Zone Execution %", zone_exec)]


def split_half(groups, stat_fn, min_half=MIN_HALF):
    """groups: {pid: [items in order]}. stat_fn(list) -> value or None.
    -> {r, full, n_pitchers, read}"""
    xs, ys = [], []
    for items in groups.values():
        odd, even = items[0::2], items[1::2]
        if len(odd) < min_half or len(even) < min_half:
            continue
        a, b = stat_fn(odd), stat_fn(even)
        if a is None or b is None:
            continue
        xs.append(a)
        ys.append(b)
    if len(xs) < MIN_PITCHERS:
        return {"r": None, "full": None, "n_pitchers": len(xs), "read": "not enough pitchers yet"}
    r = pearson(xs, ys)
    full = spearman_brown(r)
    return {"r": r, "full": full, "n_pitchers": len(xs), "read": read(full)}


def bullpen_to_game(bp_stuff, game_groups):
    """bp_stuff: {pid: (avg_stuff, n)}; game_groups: {pid: [game pitches]}.
    -> {stat: {r, n, points: [(pid, stuff, value)]}}"""
    out = {}
    for name, fn in (("Whiff %", whiff), ("CSW %", csw)):
        pts = []
        for pid, (s, n) in bp_stuff.items():
            gps = game_groups.get(pid, [])
            if s is None or n < MIN_BP or len(gps) < MIN_GAME:
                continue
            v = fn(gps)
            if v is not None:
                pts.append((pid, s, v))
        r = pearson([p[1] for p in pts], [p[2] for p in pts]) if len(pts) >= MIN_PITCHERS else None
        out[name] = {"r": r, "n": len(pts), "points": pts}
    return out
