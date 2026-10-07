"""
GBO -- Release angle consistency (Oct 2026, from Matt Creally's "What Can
We Learn From Pitch Release Angles?": the angle the ball leaves the hand
sets where it goes -- fastball horizontal release angle tracks horizontal
break at r = .93 -- and pitch-to-pitch variation in release angle is
where command comes from).

Rapsodo gives every reading a vertical release angle (release_angle) and
a horizontal one (horizontal_angle), in degrees.

  spread     the standard deviation of each angle WITHIN an outing (a
             bullpen or a Rapsodo game), pooled across outings -- so a
             mechanical change between days isn't counted as wobble.
             Outings need MIN_OUTING readings of that pitch type.
  grade      Release consistency: each pitch type's vertical and
             horizontal spread z-scored against our staff's pitchers for
             that pitch type (MIN_N readings each), flipped so tighter =
             better, averaged, 100 + 10 x z. Overall = usage-weighted.

Some spread is on purpose (aiming up vs down changes the angle), which is
why it's only compared within a pitch type and against teammates.
"""

import math
import time
from collections import defaultdict
from statistics import mean, pstdev

MIN_OUTING = 5
MIN_N = 15
MIN_STAFF = 4
_cache = {"key": None, "base": None}


def _outing(p):
    return ("bp", p.bullpen_id) if p.bullpen_id is not None else ("imp", p.import_id)


def _label(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) is not None else None


def _pooled_sd(groups):
    """groups: [[values]] -> pooled within-group SD, total n."""
    num = den = n = 0
    for vals in groups:
        if len(vals) < MIN_OUTING:
            continue
        m = mean(vals)
        num += sum((v - m) ** 2 for v in vals)
        den += len(vals) - 1
        n += len(vals)
    return (math.sqrt(num / den) if den > 0 else None), n


def spreads(raps, within_outing=True):
    """{pitch type: {"v", "h", "n", "outings"}} for one pitcher's readings."""
    by = defaultdict(lambda: defaultdict(lambda: ([], [])))
    for p in raps:
        lab = _label(p)
        if lab is None or p.release_angle is None or p.horizontal_angle is None:
            continue
        key = _outing(p) if within_outing else "all"
        by[lab][key][0].append(float(p.release_angle))
        by[lab][key][1].append(float(p.horizontal_angle))
    out = {}
    for lab, outs in by.items():
        v, n = _pooled_sd([vs for vs, _hs in outs.values()])
        h, _n = _pooled_sd([hs for _vs, hs in outs.values()])
        if v is not None and h is not None:
            out[lab] = {"v": v, "h": h, "n": n, "outings": sum(1 for vs, _h in outs.values() if len(vs) >= MIN_OUTING)}
    return out


def baselines(raps_by_pid):
    """{pitch type: {"v": (mean, sd), "h": (mean, sd), "n_pitchers"}} from every pitcher with MIN_N readings."""
    vals = defaultdict(lambda: {"v": [], "h": []})
    for raps in raps_by_pid.values():
        for lab, s in spreads(raps).items():
            if s["n"] >= MIN_N:
                vals[lab]["v"].append(s["v"])
                vals[lab]["h"].append(s["h"])
    out = {}
    for lab, d in vals.items():
        if len(d["v"]) >= MIN_STAFF:
            out[lab] = {"v": (mean(d["v"]), pstdev(d["v"]) or 1e-9), "h": (mean(d["h"]), pstdev(d["h"]) or 1e-9),
                        "n_pitchers": len(d["v"])}
    return out


def grade(sp, base):
    """Per pitch type grade + overall. -> {"by_type": {lab: grade}, "overall": grade or None}"""
    by = {}
    w = {}
    for lab, s in sp.items():
        b = base.get(lab)
        if b is None or s["n"] < MIN_N:
            continue
        zv = (s["v"] - b["v"][0]) / b["v"][1]
        zh = (s["h"] - b["h"][0]) / b["h"][1]
        by[lab] = 100 - 10 * (zv + zh) / 2
        w[lab] = s["n"]
    overall = sum(by[l] * w[l] for l in by) / sum(w.values()) if by else None
    return {"by_type": by, "overall": overall}


def read(sp, base):
    """One or two plain lines: best-repeated pitch and the one that wanders most."""
    items = []
    for lab, s in sp.items():
        b = base.get(lab)
        if b is None or s["n"] < MIN_N:
            continue
        items.append((s["v"] - b["v"][0], s["h"] - b["h"][0], lab))
    if not items:
        return []
    out = []
    best = min(items, key=lambda t: t[0] + t[1])
    worst = max(items, key=lambda t: max(t[0], t[1]))
    if best[0] + best[1] < -0.3:
        out.append(f"Repeats his {best[2].lower()} release well ({best[0]:+.1f}° vertical, {best[1]:+.1f}° horizontal vs team).")
    dv, dh, lab = worst
    if max(dv, dh) > 0.4:
        which = "horizontal" if dh >= dv else "vertical"
        out.append(f"The {lab.lower()}'s {which} release angle wanders ({max(dv, dh):+.1f}° vs team) -- "
                   f"{'side-to-side misses' if which == 'horizontal' else 'up/down misses'} usually follow.")
    return out


def team_baselines(db):
    """Cached staff baselines from every Rapsodo reading on file."""
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    from models import RapsodoPitch
    key = (id(db.get_bind()), db.query(func.count(RapsodoPitch.rapsodo_pitch_id)).scalar(),
           db.query(func.max(RapsodoPitch.rapsodo_pitch_id)).scalar())
    if _cache["key"] == key and _cache["base"] is not None:
        return _cache["base"]
    by = defaultdict(list)
    for r in (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
              .filter(RapsodoPitch.release_angle.isnot(None)).all()):
        by[r.player_id].append(r)
    base = baselines(by)
    _cache.update(key=key, base=base, at=time.time())
    return base
