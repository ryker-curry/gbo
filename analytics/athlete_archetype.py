"""
GBO -- Athlete archetype from jump / force-plate tests (Oct 2026, from
Georgia Southern's player profile reports, Hunter Lakey: "where they
stack up, strengths/weaknesses, & how they best utilize their hardware").

Every test becomes a percentile vs the active roster (all players with
that test). Tests split into two sides:

  FORCE side    (muscular / force-driven): how much force he puts into the
                ground -- impulse, mean / peak force, braking (eccentric)
                force, mid-thigh pull. Divided by body weight so size only
                counts once.
  VELOCITY side (elastic / velocity-driven): how fast and springy -- jump
                height, RSI-modified, hop RSI, concentric velocity, and a
                SHORT concentric duration.

Spectrum index = (velocity-side mean pct - force-side mean pct) / 100,
-1 (all force) to +1 (all spring). Elastic above +ARCH_BAND, Muscular below
-ARCH_BAND, Hybrid between. Overall output = mean of every percentile.

Training lean (Georgia Southern's read, general tendencies -- not tested on
our team): an Elastic athlete's next step is usually strength under the
spring; a Muscular athlete's is speed / reactive work; a Hybrid trains both.
Works off whatever tests exist; the 9 Hawkin CMJ metrics slot in
automatically once they're entered.
"""

from statistics import mean

ARCH_BAND = 0.15
MIN_POOL = 6          # players with a test before it's ranked
MIN_SIDE = 1          # tests needed on each side

# (test name, side, higher_is_better, per body weight)
TESTS = [
    ("Countermovement Jump Height", "velocity", True, False),
    ("Countermovement Jump RSI-Modified", "velocity", True, False),
    ("Hop Test RSI (10/5)", "velocity", True, False),
    ("Countermovement Jump Concentric Duration", "velocity", False, False),
    ("CMJ Concentric Peak Velocity", "velocity", True, False),
    ("Vertical Jump (Jump Mat)", "velocity", True, False),
    ("Countermovement Jump Concentric Mean Force", "force", True, True),
    ("CMJ Concentric Impulse", "force", True, True),
    ("CMJ Concentric Peak Force", "force", True, True),
    ("CMJ Eccentric Peak Force", "force", True, True),
    ("Single-Leg Jump Concentric Impulse (Drive Leg)", "force", True, True),
    ("Single-Leg Jump Concentric Impulse (Plant Leg)", "force", True, True),
    ("Isometric Mid-Thigh Pull Peak Vertical Force", "force", True, True),
]
LABELS = {
    "Countermovement Jump Height": "Jump height", "Countermovement Jump RSI-Modified": "RSI-mod",
    "Hop Test RSI (10/5)": "Hop RSI", "Countermovement Jump Concentric Duration": "Time to takeoff",
    "CMJ Concentric Peak Velocity": "Peak velocity", "Vertical Jump (Jump Mat)": "Vertical (mat)",
    "Countermovement Jump Concentric Mean Force": "Push force / lb", "CMJ Concentric Impulse": "Net impulse / lb",
    "CMJ Concentric Peak Force": "Peak force / lb", "CMJ Eccentric Peak Force": "Braking force / lb",
    "Single-Leg Jump Concentric Impulse (Drive Leg)": "Drive-leg impulse / lb",
    "Single-Leg Jump Concentric Impulse (Plant Leg)": "Plant-leg impulse / lb",
    "Isometric Mid-Thigh Pull Peak Vertical Force": "Mid-thigh pull / lb",
}
NAMES = [t for t, *_ in TESTS] + ["Body Weight"]


def _pct_rank(v, pool, higher):
    below = sum(1 for x in pool if (x < v if higher else x > v))
    equal = sum(1 for x in pool if x == v)
    return round(100.0 * (below + 0.5 * equal) / len(pool))


def values(raw):
    """raw: {test: {pid: value}} -> {test: {pid: value}} with per-lb applied."""
    bw = raw.get("Body Weight") or {}
    out = {}
    for name, _side, _hib, rel in TESTS:
        vals = {}
        for pid, v in (raw.get(name) or {}).items():
            if v is None:
                continue
            v = float(v)
            if rel:
                w = bw.get(pid)
                if not w:
                    continue
                v = v / float(w)
            vals[pid] = v
        if vals:
            out[name] = vals
    return out


def profile(pid, vals):
    """-> None or {"kind", "index", "output", "force", "velocity", "metrics": [...],
    "best", "worst", "lines"}"""
    metrics = []
    for name, side, hib, _rel in TESTS:
        pool = vals.get(name) or {}
        if pid not in pool or len(pool) < MIN_POOL:
            continue
        pct = _pct_rank(pool[pid], list(pool.values()), hib)
        metrics.append({"test": name, "label": LABELS[name], "side": side, "pct": pct, "value": pool[pid],
                        "pool": len(pool)})
    f = [m["pct"] for m in metrics if m["side"] == "force"]
    v = [m["pct"] for m in metrics if m["side"] == "velocity"]
    if len(f) < MIN_SIDE or len(v) < MIN_SIDE:
        return None
    fm, vm = mean(f), mean(v)
    idx = (vm - fm) / 100.0
    kind = "Elastic" if idx > ARCH_BAND else ("Muscular" if idx < -ARCH_BAND else "Hybrid")
    best = max(metrics, key=lambda m: m["pct"])
    worst = min(metrics, key=lambda m: m["pct"])
    lines = [{
        "Elastic": "Velocity-driven: quick off the ground and springy -- wins with speed and stiffness more than brute "
                   "force. Strength under the spring usually has the most upside.",
        "Muscular": "Force-driven: puts a lot of force into the ground and takes a little longer to do it. Speed and "
                    "reactive work (short ground contacts, plyos, med-ball speed) usually has the most upside.",
        "Hybrid": "Balanced: no big lean either way. Train both -- heavy strength and fast reactive work.",
    }[kind]]
    lines.append(f"Superpower: {best['label']} ({_ord(best['pct'])} percentile on the team).")
    if worst["pct"] < 40:
        lines.append(f"Biggest opportunity: {worst['label']} ({_ord(worst['pct'])}).")
    return {"kind": kind, "index": idx, "output": round(mean(m["pct"] for m in metrics)), "force": round(fm),
            "velocity": round(vm), "metrics": metrics, "best": best, "worst": worst, "lines": lines}


def _ord(n):
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def load(db, pid):
    import bucket_system as bs
    raw, _units = bs._batch_fetch_latest_values(db, NAMES, include_player_id=pid)
    return profile(pid, values(raw))
