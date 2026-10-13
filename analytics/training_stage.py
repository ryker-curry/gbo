"""
GBO -- Mobility -> Stability -> Strength ladder (Oct 2026, from Samuel
Midgette's "Mobility, Stability, Strength: The Progression"): can he get
into the position, can he hold it under load, can he produce force from
it -- in that order. The first stage he's below the staff on is where his
training starts.

  Mobility   compensation.py's Shoulder mobility + Hip mobility domains,
             plus GIRD >= 20 deg / total arc deficit >= 5 deg on their own.
  Stability  the lead (plant) leg and decelerators: plant-leg single-leg
             jump / lateral jump / hip ab-adduction / mid-thigh pull (per
             lb), scapular I-Y-T, and throwing-arm ER:IR strength ratio.
             Plus a plant-vs-drive asymmetry check (plant leg 10%+ weaker).
  Strength   Lower-body strength, Upper-body strength, Rotational power,
             Lower-body power domains.

Staff z-scores (0 = staff average). Below = z <= WEAK (-0.5), same cut the
compensation profile uses. No published thresholds exist for these
stages; the cuts are GBO's.
"""

from statistics import mean, pstdev

from analytics import compensation as comp

WEAK = comp.WEAK
GIRD_FLAG = 20.0
TAD_FLAG = 5.0
ASYM_FLAG = 0.10
MIN_STAFF = comp.MIN_STAFF

STABILITY_TESTS = [   # (test, higher_is_better, per body weight)
    ("Single-Leg Jump Height (Plant Leg)", True, False),
    ("Single-Leg Jump Concentric Impulse (Plant Leg)", True, True),
    ("Lateral Jump Distance (Plant Leg)", True, False),
    ("Hip Abduction Force (Plant Leg)", True, True),
    ("Hip Adduction Force (Plant Leg)", True, True),
    ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)", True, True),
    ("Shoulder Strength: I Position Peak Force", True, True),
    ("Shoulder Strength: Y Position Peak Force", True, True),
    ("Shoulder Strength: T Position Peak Force", True, True),
]
PAIRS = [("Single-Leg Jump Height (Plant Leg)", "Single-Leg Jump Height (Drive Leg)", "single-leg jump"),
         ("Lateral Jump Distance (Plant Leg)", "Lateral Jump Distance (Drive Leg)", "lateral jump"),
         ("Hip Abduction Force (Plant Leg)", "Hip Abduction Force (Drive Leg)", "hip abduction"),
         ("Isometric Mid-Thigh Pull Peak Vertical Force (Plant Leg)",
          "Isometric Mid-Thigh Pull Peak Vertical Force (Drive Leg)", "mid-thigh pull")]
NAMES = sorted({t for t, *_ in STABILITY_TESTS} | {d for _p, d, _l in PAIRS} | {comp.ER_FORCE, comp.IR_FORCE, "Body Weight"})
SHORT = {t: t.split(": ")[-1].replace(" (Plant Leg)", " (plant leg)") for t, *_ in STABILITY_TESTS}


def stability_values(raw, pids):
    """raw {test: {pid: v}} -> {pid: {test: value}} (per-lb applied, ER:IR added)."""
    bw = raw.get("Body Weight") or {}
    out = {pid: {} for pid in pids}
    for t, _h, rel in STABILITY_TESTS:
        for pid, v in (raw.get(t) or {}).items():
            if pid not in out or v is None:
                continue
            v = float(v)
            if rel:
                if not bw.get(pid):
                    continue
                v /= float(bw[pid])
            out[pid][t] = v
    for pid in out:
        er, ir = (raw.get(comp.ER_FORCE) or {}).get(pid), (raw.get(comp.IR_FORCE) or {}).get(pid)
        if er and ir:
            out[pid]["ER:IR ratio"] = float(er) / float(ir)
    return out


def stability_z(vals):
    """{pid: (z or None, [weak test labels])}"""
    tests = [t for t, *_ in STABILITY_TESTS] + ["ER:IR ratio"]
    stats = {}
    for t in tests:
        xs = [v[t] for v in vals.values() if t in v]
        if len(xs) >= MIN_STAFF:
            stats[t] = (mean(xs), pstdev(xs) or 1e-9)
    out = {}
    for pid, v in vals.items():
        zs, weak = [], []
        for t in tests:
            if t in v and t in stats:
                z = (v[t] - stats[t][0]) / stats[t][1]
                zs.append(z)
                if z <= WEAK:
                    weak.append(SHORT.get(t, t))
        out[pid] = (mean(zs) if zs else None, weak)
    return out


def asymmetry(raw, pid):
    out = []
    for plant, drive, label in PAIRS:
        p, d = (raw.get(plant) or {}).get(pid), (raw.get(drive) or {}).get(pid)
        if p and d and float(d) > 0 and (float(d) - float(p)) / float(d) >= ASYM_FLAG:
            out.append(f"Plant leg {100 * (float(d) - float(p)) / float(d):.0f}% weaker on {label}")
    return out


def _fmt(z):
    return f"{z:+.1f}"


def ladder(pid, data, raw, stab):
    """data = compensation.load(db); raw = bucket values for NAMES; stab = stability_z(...)."""
    if pid not in data["players"]:
        return None
    doms = data["doms"].get(pid, {})
    der = data["derived"].get(pid, {})
    # Mobility
    mob_ev, mob_bad = [], False
    for d in ("Shoulder mobility", "Hip mobility"):
        if doms.get(d) is not None:
            mob_ev.append(f"{d}: {_fmt(doms[d])} vs staff")
            mob_bad |= doms[d] <= WEAK
    if der.get(comp.GIRD) is not None:
        mob_ev.append(f"GIRD {der[comp.GIRD]:.0f}°")
        mob_bad |= der[comp.GIRD] >= GIRD_FLAG
    if der.get(comp.TAD) is not None:
        mob_ev.append(f"Total arc deficit {der[comp.TAD]:.0f}°")
        mob_bad |= der[comp.TAD] >= TAD_FLAG
    mob = {"name": "Mobility", "question": "Can he get into the positions his delivery needs?",
           "status": "untested" if not mob_ev else ("limiter" if mob_bad else "ok"), "evidence": mob_ev}
    # Stability
    sz, weak = stab.get(pid, (None, []))
    asym = asymmetry(raw, pid)
    st_ev = ([f"Lead-leg / decel tests: {_fmt(sz)} vs staff"] if sz is not None else []) + \
        [f"Below staff: {', '.join(weak[:3])}"] * bool(weak) + asym
    st_bad = (sz is not None and sz <= WEAK) or len(weak) >= 2 or bool(asym)
    sta = {"name": "Stability", "question": "Can he hold those positions under load (lead-leg block, decel)?",
           "status": "untested" if sz is None and not asym else ("limiter" if st_bad else "ok"), "evidence": st_ev}
    # Strength
    s_doms = [d for d in ("Lower-body strength", "Upper-body strength", "Rotational power", "Lower-body power")
              if doms.get(d) is not None]
    s_ev = [f"{d}: {_fmt(doms[d])}" for d in s_doms]
    s_bad = any(doms[d] <= WEAK for d in s_doms)
    stre = {"name": "Strength", "question": "Can he produce force from those positions?",
            "status": "untested" if not s_doms else ("limiter" if s_bad else "ok"), "evidence": s_ev}
    stages = [mob, sta, stre]
    start = next((s["name"] for s in stages if s["status"] == "limiter"), None)
    untested = [s["name"].lower() for s in stages if s["status"] == "untested"]
    if start == "Mobility":
        read = "Start with mobility -- strength and stability work can't fix range he doesn't have."
    elif start == "Stability":
        read = "Range is there; next is holding it -- lead-leg block, landing and decel work before chasing strength."
    elif start == "Strength":
        read = "Range and control are in place -- strength is the next ceiling (and usually velo's)."
    else:
        read = "No stage below staff -- keep building all three."
    if untested:
        read += f" Not tested yet: {', '.join(untested)}."
    return {"stages": stages, "start": start, "read": read}


def load(db):
    """-> (compensation data, raw, stability z) for the active pitching staff."""
    import bucket_system as bs
    data = comp.load(db)
    start, end = comp._season()
    raw, _u = bs._batch_fetch_latest_values(db, NAMES, season_start=start, season_end=end)
    stab = stability_z(stability_values(raw, list(data["players"])))
    return data, raw, stab
