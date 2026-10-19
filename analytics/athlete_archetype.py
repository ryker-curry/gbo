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


def load_full(db, pid):
    """(profile, raw) -- raw is needed to build an IDP goal."""
    import bucket_system as bs
    raw, _units = bs._batch_fetch_latest_values(db, NAMES, include_player_id=pid)
    return profile(pid, values(raw)), raw


def team(db):
    """[(Player, profile)] for every active player with a profile, Elastic -> Muscular."""
    import bucket_system as bs
    from models import Player
    raw, _units = bs._batch_fetch_latest_values(db, NAMES)
    vals = values(raw)
    out = []
    for p in db.query(Player).filter(Player.active.is_(True)).all():
        prof = profile(p.player_id, vals)
        if prof:
            out.append((p, prof))
    out.sort(key=lambda t: -t[1]["index"])
    return out


TRAINING = {
    "Elastic": {"focus": "Strength under the spring",
                "do": ["Heavy lower-body strength (trap bar, squat, split squat) 2-3x / week, 3-5 reps",
                       "Slow eccentrics and isometric holds to build force at the bottom",
                       "Keep one short plyo day so he doesn't lose his bounce"],
                "retest": "Net impulse, push / peak force per lb"},
    "Muscular": {"focus": "Speed and reactivity",
                 "do": ["Plyos with short ground contacts (pogos, hurdle hops, depth jumps)",
                        "Speed-strength: light jump squats, med-ball throws for speed, velocity-based lifting",
                        "Keep heavy strength in maintenance (1-2x / week)"],
                 "retest": "Jump height, RSI-mod, hop RSI, time to takeoff"},
    "Hybrid": {"focus": "Both, by block",
               "do": ["Alternate 3-4 week blocks: heavy strength, then speed / reactive",
                      "Train his biggest opportunity metric first",
                      "Retest every block to see which side moves"],
               "retest": "His lowest-percentile test"},
}


def goal_spec(pid, raw, prof):
    """IDP goal for his biggest opportunity: raise (or lower) that test to the
    team median, in the test's own units. None if it can't be built."""
    if not prof or prof["worst"]["pct"] >= 50:
        return None
    test = prof["worst"]["test"]
    rel = next(r for t, _s, _h, r in TESTS if t == test)
    hib = next(h for t, _s, h, _r in TESTS if t == test)
    pool = {k: float(v) for k, v in (raw.get(test) or {}).items() if v is not None}
    bw = raw.get("Body Weight") or {}
    if pid not in pool:
        return None
    if rel:
        rels = [v / float(bw[k]) for k, v in pool.items() if bw.get(k)]
        if not rels or not bw.get(pid):
            return None
        from statistics import median
        target = median(rels) * float(bw[pid])
    else:
        from statistics import median
        target = median(pool.values())
    base = pool[pid]
    if (hib and target <= base) or (not hib and target >= base):
        return None
    return {"test": test, "label": LABELS[test], "baseline": base, "target": target, "kind": prof["kind"]}


def open_goal(db, pid, test):
    """The player's existing not-Completed IDP goal on this test, or None --
    so the one-click "Make goal" button can't create the same goal twice."""
    from models import AssessmentTestType, IDPGoal, IDPStatus
    return (db.query(IDPGoal)
            .join(AssessmentTestType, AssessmentTestType.test_type_id == IDPGoal.target_test_type_id)
            .outerjoin(IDPStatus, IDPStatus.status_id == IDPGoal.status_id)
            .filter(IDPGoal.player_id == pid, AssessmentTestType.test_name == test,
                    (IDPStatus.status_name.is_(None)) | (IDPStatus.status_name != "Completed"))
            .first())


def create_goal(db, pid, sp, user_id):
    """Create the archetype IDP goal from goal_spec(). -> (created, message).
    Refuses (no write) if an open goal on the same test already exists."""
    from datetime import date, timedelta
    from models import AssessmentTestType, IDPGoal, IDPStatus
    if open_goal(db, pid, sp["test"]) is not None:
        return False, f"He already has an open IDP goal on {sp['test']} -- no new goal made."
    tt = db.query(AssessmentTestType).filter(AssessmentTestType.test_name == sp["test"]).first()
    st = db.query(IDPStatus).order_by(IDPStatus.display_order, IDPStatus.status_id).first()
    if tt is None or st is None:
        return False, "Couldn't make the goal -- test type or IDP statuses missing."
    verb = "Lower" if sp["target"] < sp["baseline"] else "Raise"
    db.add(IDPGoal(
        player_id=pid, category_id=tt.category_id, target_test_type_id=tt.test_type_id,
        baseline_value=round(sp["baseline"], 3), target_value=round(sp["target"], 3),
        target_date=date.today() + timedelta(weeks=8), status_id=st.status_id,
        description=(f"Athlete archetype ({sp['kind']}): biggest opportunity is {sp['label'].lower()}. "
                     f"{verb} {sp['test']} from {sp['baseline']:.2f} to the team middle ({sp['target']:.2f})."),
        created_by_user_id=user_id,
    ))
    db.commit()
    return True, f"Goal created: {sp['test']}."
