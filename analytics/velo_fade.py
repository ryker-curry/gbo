"""
GBO -- Velo fade by pitch number (Oct 2026).

From Ryker's article batch (Eric Briggs' R Shiny postgame report plots
velo by pitch number with a trend line per pitch type to spot fatigue),
approved as "Velo fade by pitch #". Also a direct fatigue measure for
Ryker's conditioning thesis.

Fastballs only (secondaries are thrown too unevenly through an outing to
trend). x = the pitch's number in the outing (every pitch type counts
toward the number, so "pitch 40" means the 40th pitch he threw), y =
Rapsodo velocity (and total spin).

  slope    least-squares mph per pitch, reported per PER pitches
           ("-0.8 mph per 25 pitches")
  first/last  average of his first and last EDGE fastballs
  drop     last - first

Needs MIN_FB fastballs with a velocity; below that the outing reads
"not enough". Rapsodo only -- charted game pitches have no velo, so for
games this works on intrasquads (and any game) with a Rapsodo file.

READ (per PER pitches): >= HELD = held velo, >= MILD = mild fade, below
= notable fade. Starting points, not proven cutoffs.
"""

from collections import defaultdict

FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker")
MIN_FB = 15
EDGE = 10
PER = 25
HELD = -0.5
MILD = -1.5


def _f(v):
    return float(v) if v is not None else None


def points_from_rapsodo(pitches, label_of):
    """[(pitch_number, velo, spin)] for fastballs with a velo, in pitch order.
    pitch_number is re-counted 1..n across ALL his readings in the outing."""
    ordered = sorted(pitches, key=lambda p: (p.pitch_number if p.pitch_number is not None else 10 ** 6,
                                              getattr(p, "rapsodo_pitch_id", 0) or 0))
    out = []
    for i, p in enumerate(ordered, start=1):
        if label_of(p) in FASTBALLS and p.velocity is not None:
            out.append((i, float(p.velocity), _f(p.total_spin)))
    return out


def _slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return 0.0, my
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return b, my - b * mx


def read(per):
    if per is None:
        return "—"
    if per >= HELD:
        return "held velo"
    if per >= MILD:
        return "mild fade"
    return "notable fade"


def fade(points):
    """-> {n, ok, per, intercept, slope, first, last, drop, spin_per, spin_drop, read, points}"""
    n = len(points)
    res = {"n": n, "ok": n >= MIN_FB, "points": points}
    if not res["ok"]:
        return res
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    b, a = _slope(xs, ys)
    edge = min(EDGE, n // 2)
    first = sum(ys[:edge]) / edge
    last = sum(ys[-edge:]) / edge
    res.update(slope=b, intercept=a, per=b * PER, first=first, last=last, drop=last - first, edge=edge,
               read=read(b * PER), max_x=xs[-1])
    sp = [(x, s) for x, _v, s in points if s is not None]
    if len(sp) >= MIN_FB:
        sb, _ = _slope([x for x, _ in sp], [s for _, s in sp])
        se = min(EDGE, len(sp) // 2)
        res["spin_per"] = sb * PER
        res["spin_drop"] = sum(s for _, s in sp[-se:]) / se - sum(s for _, s in sp[:se]) / se
    else:
        res["spin_per"] = res["spin_drop"] = None
    return res


def outing_key(p):
    if p.bullpen_id is not None:
        return ("bp", p.bullpen_id)
    return ("imp", p.import_id)


def by_outing(pitches, label_of):
    """[{date, key, kind, fade}] oldest first, one per bullpen / Rapsodo game import."""
    groups = defaultdict(list)
    for p in pitches:
        groups[outing_key(p)].append(p)
    out = []
    for key, ps in groups.items():
        dates = [p.pitch_date for p in ps if p.pitch_date is not None]
        day = min(dates).date() if dates else None
        out.append({"date": day, "key": key, "kind": "Bullpen" if key[0] == "bp" else "Game",
                    "fade": fade(points_from_rapsodo(ps, label_of))})
    out.sort(key=lambda o: (o["date"] is None, o["date"]))
    return out
