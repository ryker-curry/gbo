"""
GBO -- Compensation profile (Oct 2026, Ryker: "baseball players are elite
compensators. they make up for things they lack by being really good at
other things ... figure out how each guy compensates. is it leading to
injury risk? if we can clean up the thing he lacks ... does this lead to
better performance and less injury risk?"). Staff only, Player Profile.

1. DOMAINS -- each pitcher vs the active pitching staff this season.
   Every test becomes a z-score (0 = staff average, +1 = one SD better;
   "lower is better" tests flipped). Strength and force tests are per lb
   of body weight (Ryker's call) so size only counts once, in Size.
   Domain = mean of the z-scores of the tests he has. Needs MIN_STAFF
   pitchers with a test for that test to count.

2. VELO VS HIS BODY -- OLS of season average FB velo on the domains that
   correlate best with velo across the staff (|r| >= PICK_R, up to 3;
   Ryker: "pick by research results"; fallback Size, Lower-body power,
   Rotational power); each
   pitcher is predicted from a fit WITHOUT him (leave-one-out) so he
   can't explain himself. Residual = actual - expected; typical error =
   leave-one-out RMSE. Well above = velo the tests don't explain
   (mechanics, arm speed, elasticity) -- the compensation to look at.

3. RISK-PATTERN FLAGS -- research-based watch items, never diagnoses:
   arm-driven velo, range without strength, ER:IR strength ratio,
   total arc / GIRD deficit with above-median velo, lead (plant) hip IR,
   velo outrunning arm capacity. No injury log exists, so none of these
   are validated on this team.

4. FIX-THE-LIMITER TRACKING -- his domain scores over time (every test
   date, carrying each test's latest value forward, z-scored against
   TODAY's staff so the scale holds still), next to monthly FB velo,
   velo fade, game miss distance and Hold/Limited days. For each change
   in a domain: FB velo and Hold/Limited days in the WINDOW_DAYS before
   vs after the retest. Team view pools every pitcher's changes.
"""

import math
import time
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median, pstdev

import bucket_system as bs

MIN_STAFF = 5
MIN_MODEL = 10
STRONG, WEAK = 0.5, -0.5
WINDOW_DAYS = 42
FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker")

# Virtual tests built from Right/Left raw fields by throwing arm.
ER_THROW, IR_THROW = "Throwing-arm shoulder ER", "Throwing-arm shoulder IR"
GIRD, TAD = "GIRD", "Total arc deficit"
LEAD_HIP_IR = "Hip: Plant Leg Internal Rotation"
ER_FORCE = "Shoulder Strength: Throwing Arm ER Peak Force"
IR_FORCE = "Shoulder Strength: Throwing Arm IR Peak Force"
_R_ER, _L_ER = "Shoulder: Right External Rotation", "Shoulder: Left External Rotation"
_R_IR, _L_IR = "Shoulder: Right Internal Rotation", "Shoulder: Left Internal Rotation"


def pearson(xs, ys):
    """Plain Pearson r (None if fewer than 3 pairs or no spread) -- local copy so
    this module doesn't depend on the research tools."""
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _tests(groups, rel=False, skip=()):
    return [(n, d, rel) for g in groups for n, d in g if n not in skip]


DOMAINS = [
    ("Size", [("Body Weight", "higher", False), ("Skeletal Muscle Mass", "higher", False)]),
    ("Lower-body strength", _tests([bs.STRENGTH_SUBGROUPS["Lower Body Strength"]], rel=True)),
    ("Lower-body power", _tests([ms for sub, ms in bs.POWER_SUBGROUPS.items() if sub != "Med Ball Throw"])),
    ("Rotational power", _tests([bs.POWER_SUBGROUPS.get("Med Ball Throw", []), bs.MED_BALL_THROW_REFERENCE_METRICS])),
    ("Speed", _tests([bs.SPEED_METRICS])),
    ("Upper-body strength", _tests([bs.STRENGTH_SUBGROUPS["Upper Body Strength"]], rel=True,
                                   skip=("Grip Strength (Seated, Throwing Hand)",))),
    # Oct 2026 (Ryker): arm capacity split -- shoulder vs elbow stories differ.
    ("Shoulder strength", _tests([bs.CAPACITY_SUBGROUPS["Shoulder Strength"], bs.CAPACITY_SUBGROUPS["Scapular Strength"]],
                                 rel=True)),
    ("Forearm & grip", _tests([bs.CAPACITY_SUBGROUPS["Grip Strength"], bs.CAPACITY_SUBGROUPS["Forearm/Elbow Capacity"],
                               [("Grip Strength (Seated, Throwing Hand)", "higher")]], rel=True)),
    ("Shoulder mobility", [(ER_THROW, "higher", False), (IR_THROW, "higher", False), (GIRD, "lower", False),
                           (TAD, "lower", False)]),
    ("Hip mobility", [("Hip: Drive Leg Internal Rotation", "higher", False), (LEAD_HIP_IR, "higher", False),
                      ("Hip: Drive Leg External Rotation", "higher", False),
                      ("Hip: Plant Leg External Rotation", "higher", False)]),
]
DOMAIN_NAMES = [d for d, _t in DOMAINS]
VIRTUAL = {ER_THROW, IR_THROW, GIRD, TAD}
MODEL_DOMAINS = ("Size", "Lower-body power", "Rotational power")   # fallback when screening picks nothing
ARM_DOMAINS = ("Shoulder strength", "Forearm & grip")
PICK_R = 0.30
MAX_PREDICTORS = 3
RAW_NAMES = sorted({n for _d, ts in DOMAINS for n, _dir, _r in ts if n not in VIRTUAL}
                   | {"Body Weight", _R_ER, _L_ER, _R_IR, _L_IR})
_CACHE = {"at": 0.0, "key": None, "data": None}
CACHE_SECONDS = 300


# ---------------------------------------------------------------------------
# Raw values -> per-test values per pitcher (virtual + per-lb applied)
# ---------------------------------------------------------------------------

def derive(raw, throws):
    """raw: {test_name: value} for one pitcher; throws 'R'/'L'/None.
    -> {test_name: value} with virtual tests added and strength left raw
    (per-lb is applied in test_values)."""
    out = dict(raw)
    if throws in ("R", "L"):
        er_t, er_n = (raw.get(_R_ER), raw.get(_L_ER)) if throws == "R" else (raw.get(_L_ER), raw.get(_R_ER))
        ir_t, ir_n = (raw.get(_R_IR), raw.get(_L_IR)) if throws == "R" else (raw.get(_L_IR), raw.get(_R_IR))
        if er_t is not None:
            out[ER_THROW] = er_t
        if ir_t is not None:
            out[IR_THROW] = ir_t
        if ir_t is not None and ir_n is not None:
            out[GIRD] = ir_n - ir_t
        if None not in (er_t, er_n, ir_t, ir_n):
            out[TAD] = (er_n + ir_n) - (er_t + ir_t)
    return out


def test_values(derived):
    """Per-test values used for scoring: relative tests divided by body weight."""
    bw = derived.get("Body Weight")
    out = {}
    for _d, tests in DOMAINS:
        for name, _dir, rel in tests:
            v = derived.get(name)
            if v is None:
                continue
            if rel:
                if not bw:
                    continue
                v = v / bw
            out[name] = float(v)
    return out


def staff_stats(values_by_pid):
    """{test: (mean, sd, n)} over pitchers -- only tests with MIN_STAFF+ and sd > 0."""
    by_test = defaultdict(list)
    for vals in values_by_pid.values():
        for t, v in vals.items():
            by_test[t].append(v)
    out = {}
    for t, vs in by_test.items():
        if len(vs) >= MIN_STAFF:
            sd = pstdev(vs)
            if sd > 0:
                out[t] = (mean(vs), sd, len(vs))
    return out


_DIR = {n: d for _dom, ts in DOMAINS for n, d, _r in ts}


def z_of(test, value, stats):
    st = stats.get(test)
    if st is None or value is None:
        return None
    z = (value - st[0]) / st[1]
    return -z if _DIR.get(test) == "lower" else z


def domains_for(vals, stats):
    """{domain: {"z", "tests": [(test, value, z)]}} -- domains with no scored test are left out."""
    out = {}
    for dom, tests in DOMAINS:
        rows = [(n, vals[n], z_of(n, vals[n], stats)) for n, _d, _r in tests if n in vals]
        rows = [r for r in rows if r[2] is not None]
        if rows:
            out[dom] = {"z": mean(r[2] for r in rows), "tests": rows}
    return out


def read(doms):
    """("leans on ...", "limited by ...") plain words."""
    ranked = sorted(doms.items(), key=lambda kv: -kv[1]["z"])
    strong = [d for d, v in ranked if v["z"] >= STRONG][:2]
    weak = [d for d, v in reversed(ranked) if v["z"] <= WEAK][:2]
    return strong, weak


# ---------------------------------------------------------------------------
# Velo vs his body (leave-one-out OLS)
# ---------------------------------------------------------------------------

def _ols(X, y):
    import numpy as np
    X1 = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(X1, y, rcond=None)
    return beta


def pick_predictors(doms_by_pid, velo_by_pid):
    """Oct 2026 (Ryker: "pick by research results"): domains whose staff-
    level correlation with FB velo is |r| >= PICK_R with MIN_MODEL+
    pitchers, strongest first, up to MAX_PREDICTORS -- re-picked as data
    comes in. Falls back to MODEL_DOMAINS. -> ([domains], {domain: (r, n)})."""
    screen = {}
    for dom in DOMAIN_NAMES:
        pr = [(d[dom]["z"], velo_by_pid[p]) for p, d in doms_by_pid.items()
              if dom in d and velo_by_pid.get(p) is not None]
        if len(pr) >= MIN_MODEL:
            r = pearson([a for a, _b in pr], [b for _a, b in pr])
            if r is not None:
                screen[dom] = (r, len(pr))
    picked = [d for d, (r, _n) in sorted(screen.items(), key=lambda kv: -abs(kv[1][0])) if abs(r) >= PICK_R]
    picked = picked[:MAX_PREDICTORS]
    return (picked or list(MODEL_DOMAINS)), screen


def velo_model(doms_by_pid, velo_by_pid, predictors=None):
    """-> {"n", "rmse", "pred": {pid: (expected, actual, resid)}, "beta", "predictors", "picked", "screen"} or None.
    The leave-one-out fit holds each pitcher out of the fit, but the
    predictors are picked on the whole staff -- note that in any write-up."""
    import numpy as np
    screen = {}
    if predictors is None:
        predictors, screen = pick_predictors(doms_by_pid, velo_by_pid)
    picked = bool(screen) and any(abs(r) >= PICK_R for r, _n in screen.values())
    pids = [pid for pid, d in doms_by_pid.items()
            if velo_by_pid.get(pid) is not None and all(m in d for m in predictors)]
    if len(pids) < MIN_MODEL:
        return None
    X = np.array([[doms_by_pid[p][m]["z"] for m in predictors] for p in pids])
    y = np.array([velo_by_pid[p] for p in pids])
    pred = {}
    for i, pid in enumerate(pids):
        keep = np.arange(len(pids)) != i
        b = _ols(X[keep], y[keep])
        e = float(b[0] + X[i] @ b[1:])
        pred[pid] = (e, float(y[i]), float(y[i] - e))
    rmse = math.sqrt(mean(r[2] ** 2 for r in pred.values()))
    return {"n": len(pids), "rmse": rmse, "pred": pred, "beta": [float(v) for v in _ols(X, y)],
            "predictors": list(predictors), "picked": picked, "screen": screen}


# ---------------------------------------------------------------------------
# Risk-pattern flags
# ---------------------------------------------------------------------------

def flags(pid, doms, derived, model, velo_by_pid):
    """[{"name", "level": "watch" | "high", "why"}]"""
    out = []
    z = {d: v["z"] for d, v in doms.items()}
    staff_velos = [v for v in velo_by_pid.values() if v is not None]
    velo = velo_by_pid.get(pid)
    med_velo = median(staff_velos) if staff_velos else None
    above_med = velo is not None and med_velo is not None and velo >= med_velo

    pr = (model or {}).get("pred", {}).get(pid)
    lower = [z[d] for d in ("Lower-body strength", "Lower-body power") if d in z]
    if pr and pr[2] >= model["rmse"] and lower and min(lower) <= WEAK:
        weak = min(("Lower-body strength", "Lower-body power"), key=lambda d: z.get(d, 9))
        out.append({"name": "Arm-driven velo", "level": "high" if min(lower) <= -1 else "watch",
                    "why": f"throws {pr[2]:+.1f} mph above what his body predicts while his {weak.lower()} is "
                           f"{z[weak]:+.1f} SD vs the staff -- the velo may be coming from the arm, not the lower half."})

    erz = next((zz for n, _v, zz in doms.get("Shoulder mobility", {}).get("tests", []) if n == ER_THROW), None)
    if erz is not None and erz >= STRONG and z.get("Shoulder strength", 0) <= WEAK:
        out.append({"name": "Range without strength", "level": "watch",
                    "why": f"throwing-arm ER range is {erz:+.1f} SD but shoulder strength is {z['Shoulder strength']:+.1f} "
                           "SD -- lots of layback without the strength to control it."})

    er_f, ir_f = derived.get(ER_FORCE), derived.get(IR_FORCE)
    if er_f and ir_f:
        ratio = er_f / ir_f
        if ratio < 0.75:
            out.append({"name": "ER:IR strength ratio", "level": "high" if ratio < 0.65 else "watch",
                        "why": f"shoulder ER:IR force ratio {ratio:.2f} (under about 0.75 -- the decelerators are "
                               "weak relative to the accelerators)."})

    tad, gird = derived.get(TAD), derived.get(GIRD)
    if above_med and ((tad is not None and tad > 5) or (gird is not None and gird > 15)):
        bits = []
        if tad is not None and tad > 5:
            bits.append(f"total arc deficit {tad:.0f}°")
        if gird is not None and gird > 15:
            bits.append(f"GIRD {gird:.0f}°")
        hi = (tad is not None and tad > 10) or (gird is not None and gird > 20)
        out.append({"name": "Shoulder motion loss with velo", "level": "high" if hi else "watch",
                    "why": f"{' and '.join(bits)} with above-median FB velo ({velo:.1f} mph)."})

    hip = derived.get(LEAD_HIP_IR)
    st = bs._mobility_rom_status(hip, bs.MOBILITY_ROM_THRESHOLDS.get(LEAD_HIP_IR)) if hip is not None else None
    if st in ("red", "yellow"):
        out.append({"name": "Lead-hip internal rotation", "level": "high" if st == "red" else "watch",
                    "why": f"plant-leg hip IR {hip:.0f}° -- limited lead-hip rotation tends to push rotation "
                           "up the chain to the trunk and arm."})

    arm = [d for d in ARM_DOMAINS if d in z]
    if velo is not None and len(staff_velos) >= MIN_STAFF and arm:
        sd = pstdev(staff_velos)
        vz = (velo - mean(staff_velos)) / sd if sd else 0.0
        weakest = min(arm, key=lambda d: z[d])
        gap = vz - z[weakest]
        if gap >= 1.0:
            out.append({"name": "Velo outrunning arm capacity", "level": "high" if gap >= 2 else "watch",
                        "why": f"FB velo {vz:+.1f} SD vs the staff but {weakest.lower()} {z[weakest]:+.1f} SD."})
    return out


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _season():
    return bs.season_date_range(bs.current_season_label())


def load(db, use_cache=True):
    """{"players", "derived", "values", "stats", "doms", "velo", "model", "history_raw", "fb", "avail", "miss"}"""
    from models import Player
    if use_cache and _CACHE["data"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["data"]
    start, end = _season()
    players = {p.player_id: p for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all()}
    cache, _units = bs._batch_fetch_latest_values(db, RAW_NAMES, season_start=start, season_end=end)
    raw = defaultdict(dict)
    for name in RAW_NAMES:
        for pid, v in (cache.get(name) or {}).items():
            if pid in players and v is not None:
                raw[pid][name] = float(v)
    derived = {pid: derive(raw.get(pid, {}), players[pid].throws) for pid in players}
    values = {pid: test_values(d) for pid, d in derived.items()}
    stats = staff_stats(values)
    doms = {pid: domains_for(v, stats) for pid, v in values.items()}
    fb = _fb_readings(db, list(players))
    velo = {}
    for pid in players:
        vs = [v for d, v in fb.get(pid, []) if (start is None or d >= start) and (end is None or d < end)]
        velo[pid] = mean(vs) if len(vs) >= 5 else None
    data = {"players": players, "derived": derived, "values": values, "stats": stats, "doms": doms, "velo": velo,
            "model": velo_model(doms, velo), "fb": fb}
    _CACHE["at"], _CACHE["data"] = time.time(), data
    return data


def _fb_readings(db, pids):
    """{pid: [(date, velo)]} all Rapsodo fastball readings, oldest first."""
    from models import RapsodoPitch, PitchType
    if not pids:
        return {}
    rows = (db.query(RapsodoPitch.player_id, RapsodoPitch.pitch_date, RapsodoPitch.velocity)
            .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id)
            .filter(PitchType.type_name.in_(FASTBALLS), RapsodoPitch.player_id.in_(pids),
                    RapsodoPitch.velocity.isnot(None), RapsodoPitch.pitch_date.isnot(None)).all())
    out = defaultdict(list)
    for pid, d, v in rows:
        out[pid].append((d.date() if hasattr(d, "date") else d, float(v)))
    for v in out.values():
        v.sort()
    return out


def test_history(db, pids):
    """{pid: [(date, {test: value})]} -- every assessment date with the
    domain tests, values carried forward (latest on or before that date)."""
    from models import Assessment, AssessmentResult, AssessmentTestType
    if not pids:
        return {}
    rows = (db.query(Assessment.player_id, Assessment.assessment_date, AssessmentTestType.test_name, AssessmentResult.value)
            .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
            .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
            .filter(Assessment.player_id.in_(pids), AssessmentTestType.test_name.in_(RAW_NAMES),
                    AssessmentResult.value.isnot(None)).all())
    by = defaultdict(lambda: defaultdict(dict))
    for pid, d, name, v in rows:
        by[pid][d][name] = float(v)
    out = {}
    for pid, days in by.items():
        state, seq = {}, []
        for d in sorted(days):
            state.update(days[d])
            seq.append((d, dict(state), set(days[d])))
        out[pid] = seq
    return out


_SOURCES = {ER_THROW: {_R_ER, _L_ER}, IR_THROW: {_R_IR, _L_IR}, GIRD: {_R_IR, _L_IR}, TAD: {_R_ER, _L_ER, _R_IR, _L_IR}}
_DOMAIN_RAW = {dom: set().union(*[_SOURCES.get(n, {n}) for n, _d, _r in ts]) for dom, ts in DOMAINS}


def domain_timeline(seq, throws, stats):
    """[(date, {domain: z})] from test_history's carried-forward states --
    a domain only gets a point on dates one of its own tests was measured."""
    out = []
    for d, raw, measured in seq:
        doms = domains_for(test_values(derive(raw, throws)), stats)
        z = {k: v["z"] for k, v in doms.items() if measured & _DOMAIN_RAW[k]}
        if z:
            out.append((d, z))
    return out


def changes(timeline, domain, min_change=0.25):
    """[(date_before, date_after, z_before, z_after)] consecutive changes of
    at least min_change in one domain."""
    pts = [(d, z[domain]) for d, z in timeline if domain in z]
    out = []
    for (d0, z0), (d1, z1) in zip(pts, pts[1:]):
        if abs(z1 - z0) >= min_change:
            out.append((d0, d1, z0, z1))
    return out


def _window(readings, center, before):
    lo, hi = (center - timedelta(days=WINDOW_DAYS), center) if before else (center, center + timedelta(days=WINDOW_DAYS))
    vs = [v for d, v in readings if lo <= d < hi]
    return mean(vs) if len(vs) >= 5 else None


def hold_days(avail_rows, lo, hi):
    """Days in [lo, hi) covered by a Hold / Limited status."""
    days = set()
    for r in avail_rows:
        if r.kind != "status" or r.status not in ("Hold", "Limited") or r.start_date is None:
            continue
        a = max(r.start_date, lo)
        b = min(r.end_date or date.today(), hi - timedelta(days=1))
        while a <= b:
            days.add(a)
            a += timedelta(days=1)
    return len(days)


def change_effects(chg, fb, avail_rows):
    """For each change: velo and Hold/Limited days WINDOW_DAYS before vs after the retest."""
    out = []
    for d0, d1, z0, z1 in chg:
        vb, va = _window(fb, d1, True), _window(fb, d1, False)
        hb = hold_days(avail_rows, d1 - timedelta(days=WINDOW_DAYS), d1)
        ha = hold_days(avail_rows, d1, d1 + timedelta(days=WINDOW_DAYS))
        out.append({"from": d0, "to": d1, "z0": z0, "z1": z1, "velo_before": vb, "velo_after": va,
                    "dvelo": (va - vb) if vb is not None and va is not None else None,
                    "hold_before": hb, "hold_after": ha, "after_complete": d1 + timedelta(days=WINDOW_DAYS) <= date.today()})
    return out


def monthly(fb, avail_rows, misses, outings=()):
    """[{month, velo, n, hold, miss, fade}] -- misses: [(date, inches, ...)];
    outings: velo_fade.by_outing() rows (fade = mean mph per 25 pitches)."""
    by = defaultdict(lambda: {"v": [], "m": [], "f": []})
    for o in outings:
        if o.get("date") is not None and o["fade"].get("ok"):
            by[(o["date"].year, o["date"].month)]["f"].append(o["fade"]["per"])
    for d, v in fb:
        by[(d.year, d.month)]["v"].append(v)
    for d, m, *_rest in misses:
        by[(d.year, d.month)]["m"].append(m)
    for r in avail_rows:
        if r.start_date is not None:
            by[(r.start_date.year, r.start_date.month)]
    out = []
    for (y, m) in sorted(by):
        lo = date(y, m, 1)
        hi = date(y + (m == 12), m % 12 + 1, 1)
        b = by[(y, m)]
        out.append({"month": lo, "velo": mean(b["v"]) if len(b["v"]) >= 5 else None, "n": len(b["v"]),
                    "miss": mean(b["m"]) if len(b["m"]) >= 10 else None, "hold": hold_days(avail_rows, lo, hi),
                    "fade": mean(b["f"]) if b["f"] else None})
    return out


def staff_game_misses(db, pids):
    """{pid: [(date, inches, nth)]} -- intended vs actual location on every
    charted game pitch; nth = his pitch count in that game (1 = first)."""
    from sqlalchemy import and_, or_
    from models import GamePitch, Game
    if not pids:
        return {}
    rows = (db.query(GamePitch.our_player_id, GamePitch.opponent_our_player_id, GamePitch.is_our_team_batting,
                     GamePitch.game_id, GamePitch.pitch_sequence, GamePitch.intended_plate_x, GamePitch.intended_plate_z,
                     GamePitch.actual_plate_x, GamePitch.actual_plate_z, Game.game_date)
            .join(Game, Game.game_id == GamePitch.game_id)
            .filter(or_(and_(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id.in_(pids)),
                        and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id.in_(pids))))
            .all())
    by = defaultdict(list)
    for our, opp, batting, gid, seq, ix, iz, ax, az, gdate in rows:
        pid = opp if batting else our
        by[(pid, gid)].append((seq or 0, ix, iz, ax, az, gdate))
    out = defaultdict(list)
    for (pid, _gid), ps in by.items():
        ps.sort(key=lambda t: t[0])
        for nth, (_seq, ix, iz, ax, az, gdate) in enumerate(ps, start=1):
            if None in (ix, iz, ax, az) or gdate is None:
                continue
            out[pid].append((gdate, 12 * math.hypot(float(ax) - float(ix), float(az) - float(iz)), nth))
    return out


def game_misses(db, pid):
    """[(date, inches, nth)] for one pitcher."""
    return staff_game_misses(db, [pid]).get(pid, [])


def team_effects(data, history, avail_by_pid, min_change=0.25):
    """Pool every pitcher's domain changes -> {domain: {"n", "r", "improved_dvelo", "n_improved"}}."""
    out = {}
    for dom in DOMAIN_NAMES:
        dz, dv, imp = [], [], []
        for pid, p in data["players"].items():
            tl = domain_timeline(history.get(pid, []), p.throws, data["stats"])
            for e in change_effects(changes(tl, dom, min_change), data["fb"].get(pid, []), avail_by_pid.get(pid, [])):
                if e["dvelo"] is None:
                    continue
                dz.append(e["z1"] - e["z0"])
                dv.append(e["dvelo"])
                if e["z1"] > e["z0"]:
                    imp.append(e["dvelo"])
        out[dom] = {"n": len(dz), "r": pearson(dz, dv) if len(dz) >= 8 else None,
                    "improved_dvelo": mean(imp) if imp else None, "n_improved": len(imp)}
    return out


# ---------------------------------------------------------------------------
# What works for HIM (n-of-1, Oct 2026 fine-tuning)
# ---------------------------------------------------------------------------

NOF1_MIN = 4
NOF1_SOLID = 6
NOF1_WINDOW = 21
DOMAIN_OF = {n: dom for dom, ts in DOMAINS for n, _d, _r in ts}


def _velo_near(fb, d, days=NOF1_WINDOW):
    vs = [v for dd, v in fb if abs((dd - d).days) <= days]
    return mean(vs) if len(vs) >= 5 else None


def own_drivers(seq, throws, fb):
    """His own history only: for each test measured on NOF1_MIN+ dates with
    FB velo within NOF1_WINDOW days, how his velo moves with it.
    -> [{"test", "domain", "n", "r", "diff"}] strongest |r| first.
    diff = his velo when the test was in his better half minus his worse half."""
    series = defaultdict(list)
    for d, raw, measured in seq:
        vals = test_values(derive(raw, throws))
        for t, v in vals.items():
            if measured & _SOURCES.get(t, {t}):
                series[t].append((d, v))
    out = []
    for t, pts in series.items():
        pairs = [(v, _velo_near(fb, d)) for d, v in pts]
        pairs = [(v, y) for v, y in pairs if y is not None]
        if len(pairs) < NOF1_MIN:
            continue
        xs, ys = [v for v, _y in pairs], [y for _v, y in pairs]
        r = pearson(xs, ys)
        if r is None:
            continue
        order = sorted(pairs, key=lambda vy: vy[0], reverse=_DIR.get(t) != "lower")   # best first
        h = len(order) // 2
        diff = mean(y for _v, y in order[:h]) - mean(y for _v, y in order[-h:])
        out.append({"test": t, "domain": DOMAIN_OF.get(t), "n": len(pairs),
                    "r": r if _DIR.get(t) != "lower" else -r, "diff": diff})
    out.sort(key=lambda row: -abs(row["r"]))
    return out


# ---------------------------------------------------------------------------
# Delivery compensations (Oct 2026 fine-tuning)
# ---------------------------------------------------------------------------

EDGE_FB = 10
MIN_OUTING_FB = 20
# (key, label, unit, scale) -- Rapsodo release fields are in ft -> inches.
DRIFT_METRICS = [("velo", "Velo", "mph", 1.0), ("height", "Release height", "in", 12.0),
                 ("side", "Release side (width)", "in", 12.0), ("ext", "Extension", "in", 12.0),
                 ("spin", "Spin", "rpm", 1.0)]


def staff_fb_raps(db, pids):
    """{pid: [(outing_key, pitch_number, date, velo, height, side, ext, spin)]} fastballs only."""
    from models import RapsodoPitch, PitchType
    if not pids:
        return {}
    rows = (db.query(RapsodoPitch.player_id, RapsodoPitch.bullpen_id, RapsodoPitch.import_id, RapsodoPitch.pitch_number,
                     RapsodoPitch.pitch_date, RapsodoPitch.velocity, RapsodoPitch.release_height,
                     RapsodoPitch.release_side, RapsodoPitch.release_extension, RapsodoPitch.total_spin)
            .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id)
            .filter(PitchType.type_name.in_(FASTBALLS), RapsodoPitch.player_id.in_(pids)).all())
    out = defaultdict(list)
    f = lambda v: float(v) if v is not None else None
    for pid, bp, imp, n, d, v, h, sd, ext, sp in rows:
        out[pid].append((("bp", bp) if bp is not None else ("imp", imp), n or 0, d, f(v), f(h), f(sd), f(ext), f(sp)))
    return out


def tire_drift(rows):
    """Average (last EDGE_FB - first EDGE_FB fastballs) per outing with MIN_OUTING_FB+.
    Side is width from center (|side|), so + = wider late. -> {key: (avg, n_outings)}"""
    by = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    acc = defaultdict(list)
    for ps in by.values():
        if len(ps) < MIN_OUTING_FB:
            continue
        ps.sort(key=lambda r: r[1])
        first, last = ps[:EDGE_FB], ps[-EDGE_FB:]
        for i, (key, _l, _u, scale) in enumerate(DRIFT_METRICS):
            col = 3 + i
            a = [r[col] for r in first if r[col] is not None]
            b = [r[col] for r in last if r[col] is not None]
            if len(a) >= EDGE_FB // 2 and len(b) >= EDGE_FB // 2:
                if key == "side":
                    a, b = [abs(x) for x in a], [abs(x) for x in b]
                acc[key].append((mean(b) - mean(a)) * scale)
    return {k: (mean(v), len(v)) for k, v in acc.items()}


def early_late(misses):
    """Game miss distance on his pitches 1-25 vs 50+ -> (early, late) or Nones (10+ each)."""
    e = [m for _d, m, nth in misses if nth <= 25]
    late = [m for _d, m, nth in misses if nth >= 50]
    return (mean(e) if len(e) >= 10 else None), (mean(late) if len(late) >= 10 else None)


def _stats(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < MIN_STAFF:
        return None
    sd = pstdev(vals)
    return (mean(vals), sd) if sd > 0 else None


def delivery_staff(drifts_by_pid, el_by_pid):
    """Staff reference: {metric: (mean, sd)} for drift, plus "cmd" for late - early miss."""
    out = {}
    for key, *_rest in DRIFT_METRICS:
        st = _stats([d[key][0] for d in drifts_by_pid.values() if key in d])
        if st:
            out[key] = st
    st = _stats([(l - e) for e, l in el_by_pid.values() if e is not None and l is not None])
    if st:
        out["cmd"] = st
    return out


_LINKS = {
    "ext": (("Lower-body power", "Lower-body strength", "Hip mobility"),
            "the lower half may be giving out and the arm taking over"),
    "height": (("Shoulder strength", "Upper-body strength", "Forearm & grip"),
               "the arm slot sinks as the shoulder tires"),
    "velo": (("Lower-body strength", "Lower-body power", "Shoulder strength", "Forearm & grip"),
             "he runs out of gas sooner than most of the staff"),
    "side": (("Hip mobility", "Lower-body strength"), "the arm drifts away from his body late"),
    "cmd": (("Lower-body strength", "Hip mobility", "Lower-body power"), "command falls off as he tires"),
}


def delivery_flags(drift, el, staff, weak, release_grade=None):
    """[{"name", "level", "why"}] -- only when he's > 1 SD worse than the staff."""
    out = []
    bad_dir = {"velo": -1, "height": -1, "ext": -1, "spin": -1, "side": +1}
    for key, label, unit, _scale in DRIFT_METRICS:
        if key not in drift or key not in staff:
            continue
        v, n = drift[key]
        m, sd = staff[key]
        z = (v - m) / sd * bad_dir[key]                       # + = worse than staff
        if z >= 1:
            limiters, words = _LINKS.get(key, ((), ""))
            hit = [w for w in weak if w in limiters]
            tail = f" With his {hit[0].lower()} limiter, {words}." if hit and words else ""
            out.append({"name": f"{label} late in outings", "level": "high" if z >= 2 else "watch",
                        "why": f"changes {v:+.1f} {unit} from his first to last {EDGE_FB} fastballs (staff {m:+.1f}; "
                               f"{n} outing{'s' if n != 1 else ''}).{tail}"})
    e, l = el
    if e is not None and l is not None and "cmd" in staff:
        m, sd = staff["cmd"]
        z = ((l - e) - m) / sd
        if z >= 1:
            hit = [w for w in weak if w in _LINKS["cmd"][0]]
            tail = f" With his {hit[0].lower()} limiter, {_LINKS['cmd'][1]}." if hit else ""
            out.append({"name": "Command fades late", "level": "high" if z >= 2 else "watch",
                        "why": f"game misses {e:.1f}\" on pitches 1-25 vs {l:.1f}\" on 50+ (staff change "
                               f"{m:+.1f}\").{tail}"})
    if release_grade is not None and release_grade <= 90:
        hit = [w for w in weak if w in ("Hip mobility", "Lower-body strength", "Lower-body power")]
        out.append({"name": "Release angle wanders", "level": "high" if release_grade <= 80 else "watch",
                    "why": f"release consistency {release_grade:.0f} (100 = staff average)."
                           + (f" A {hit[0].lower()} limiter can make the delivery harder to repeat." if hit else "")})
    return out


def load_delivery(db, data):
    """Staff drift / early-late for the delivery card, cached with load()."""
    if data.get("delivery") is not None:
        return data["delivery"]
    pids = list(data["players"])
    raps = staff_fb_raps(db, pids)
    misses = staff_game_misses(db, pids)
    drifts = {pid: tire_drift(raps.get(pid, [])) for pid in pids}
    el = {pid: early_late(misses.get(pid, [])) for pid in pids}
    data["delivery"] = {"drifts": drifts, "el": el, "misses": misses, "staff": delivery_staff(drifts, el)}
    return data["delivery"]


# ---------------------------------------------------------------------------
# IDP goal from a limiter (Oct 2026 fine-tuning)
# ---------------------------------------------------------------------------

IDP_WEEKS = 8


def idp_goal_spec(pid, domain, data):
    """Weakest test in the domain -> {"test", "baseline", "target", "unit_note", "z"} in RAW units
    (per-lb tests converted back with his body weight). None if not possible."""
    doms = data["doms"].get(pid, {})
    d = doms.get(domain)
    if not d:
        return None
    rel = {n for n, _d, r in dict(DOMAINS)[domain] if r}
    for name, _v, z in sorted(d["tests"], key=lambda t: t[2]):
        if name in VIRTUAL:
            continue
        raw = data["derived"][pid].get(name)
        st = data["stats"].get(name)
        if raw is None or st is None:
            continue
        target = st[0]
        if name in rel:
            bw = data["derived"][pid].get("Body Weight")
            if not bw:
                continue
            target = st[0] * bw
        better_already = (raw >= target) if _DIR.get(name) != "lower" else (raw <= target)
        if better_already:
            continue
        return {"test": name, "baseline": raw, "target": target, "z": z, "per_lb": name in rel}
    return None
