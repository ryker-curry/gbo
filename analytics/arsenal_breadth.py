"""
GBO -- Arsenal Breadth+ (Oct 2026, from Bradley Greenberg's "Arsenal
Models in College Baseball"). How much speed and movement range a
pitcher's arsenal covers, weighted by how often he throws each pitch.

  speed spread     usage-weighted SD of each pitch type's median velo
                   (the article spreads time-to-plate; velo is the same
                   ordering, simpler to read)
  movement spread  usage-weighted average distance (inches) of each pitch
                   type's median (IVB, HB) from the arsenal's
                   usage-weighted center
  Breadth+         each spread z-scored across our staff, averaged 50/50,
                   100 + 25 x z (the article's scale: 100 = average,
                   25 = one SD)

DESCRIPTIVE only -- the article found breadth barely predicts results
(R^2 mostly under 0.2). Pitch types need MIN_TYPE readings to count.
"""

from collections import defaultdict
from statistics import median, mean, pstdev

MIN_TYPE = 5
MIN_STAFF = 5


def spreads(raps, label_of):
    groups = defaultdict(list)
    for p in raps:
        lab = label_of(p)
        if lab and p.velocity is not None and p.vb_spin is not None and p.hb_trajectory is not None:
            groups[lab].append(p)
    types = []
    for lab, ps in groups.items():
        if len(ps) < MIN_TYPE:
            continue
        types.append((lab, len(ps), median(float(p.velocity) for p in ps), median(float(p.vb_spin) for p in ps),
                      median(float(p.hb_trajectory) for p in ps)))
    if len(types) < 2:
        return None
    tot = sum(t[1] for t in types)
    w = [t[1] / tot for t in types]
    mv = sum(wi * t[2] for wi, t in zip(w, types))
    speed = sum(wi * (t[2] - mv) ** 2 for wi, t in zip(w, types)) ** 0.5
    ci = sum(wi * t[3] for wi, t in zip(w, types))
    ch = sum(wi * t[4] for wi, t in zip(w, types))
    move = sum(wi * ((t[3] - ci) ** 2 + (t[4] - ch) ** 2) ** 0.5 for wi, t in zip(w, types))
    return {"speed": speed, "move": move, "types": len(types),
            "velo_range": max(t[2] for t in types) - min(t[2] for t in types)}


def breadth_plus(by_pid):
    """by_pid: {pid: spreads() or None}. -> {pid: {"plus", "speed", "move", ...}}"""
    ok = {pid: s for pid, s in by_pid.items() if s}
    if len(ok) < MIN_STAFF:
        return {}
    out = {}
    stats = {}
    for k in ("speed", "move"):
        vals = [s[k] for s in ok.values()]
        stats[k] = (mean(vals), pstdev(vals) or 1e-9)
    for pid, s in ok.items():
        z = 0.5 * ((s["speed"] - stats["speed"][0]) / stats["speed"][1]) + 0.5 * ((s["move"] - stats["move"][0]) / stats["move"][1])
        out[pid] = {**s, "plus": 100 + 25 * z,
                    "speed_avg": stats["speed"][0], "move_avg": stats["move"][0]}
    return out
