"""
GBO -- Morning hub (Oct 2026, Ryker: "build it" -- after Indiana football's
"IUFB Performance Data: The Hub": every morning starts on one screen).

Three pieces, all staff-only, on the Dashboard:

  SOURCES    when each data source last brought in new data (game charting,
             Rapsodo, bullpens, testing, body weight, WHOOP, arm care).
  PULSE      a row of team numbers, each with its own trend: throwing load,
             fastball velo vs norm, strike %, availability, hitter
             decisions, WHOOP recovery, CMJ readiness.
  WATCH LIST a player shows up only when something is far outside HIS OWN
             history -- never because he's below the team. One flag puts
             him on WATCH; a severe flag, or flags from two or more
             different sources, moves him to PRIORITY.

FLAGS (latest value inside LOOKBACK_DAYS vs his own earlier values):
  Load      arm care workload ratio (pitch counts) or stress ratio
            1.3-1.5 watch, > 1.5 severe; a coach "Hold" = watch
  Velo      latest outing's avg fastball (Rapsodo, 3+ FB) vs his earlier
            outings (3+): -1.5 mph watch, -2.5 mph severe
  Command   latest game strike % (15+ pitches) vs his earlier games (3+):
            -10 pts watch, -18 severe
  Approach  hitters: latest game decision pts per pitch (8+ graded) vs his
            earlier games (3+): 1.5 SD below his own average watch, 2.5
            severe (and at least 0.3 pts / pitch worse); chase % (8+ pitches
            off the zone) +15 pts watch, +30 severe
  CMJ       jump height or mRSI vs his earlier tests: -8% watch, -15% severe
  Weight    body weight vs his earlier weigh-ins (60 days): -3% watch,
            -5% severe
  WHOOP     recovery vs his own last 30 days (7+ days): -25 watch, -40
            severe; HRV -20% watch, -30% severe

Starting points, not proven cutoffs -- each lives in FLAG_RULES so the staff
can tune them. Weight room isn't tracked yet (Ryker is talking to the
strength coach); it slots in as another source when it is.
"""

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, pstdev

LOOKBACK_DAYS = 14
HISTORY_DAYS = 120
SOURCES_ORDER = ["Load", "Velo", "Command", "Approach", "CMJ", "Weight", "WHOOP"]

# kind: abs (units) or pct (% change); bad: "low" (a drop is bad) or "high"
FLAG_RULES = {
    "velo": dict(source="Velo", label="Fastball velo", unit="mph", kind="abs", bad="low", watch=1.5, severe=2.5, min_prior=3),
    "strike": dict(source="Command", label="Strike %", unit="pts", kind="abs", bad="low", watch=10, severe=18, min_prior=3),
    "decision": dict(source="Approach", label="Decision pts / pitch", unit="", kind="z", bad="low", watch=1.5, severe=2.5,
                     min_abs=0.3, min_prior=3),
    "chase": dict(source="Approach", label="Chase %", unit="pts", kind="abs", bad="high", watch=15, severe=30, min_prior=3),
    "cmj_ht": dict(source="CMJ", label="CMJ height", unit="%", kind="pct", bad="low", watch=8, severe=15, min_prior=1),
    "cmj_rsi": dict(source="CMJ", label="CMJ mRSI", unit="%", kind="pct", bad="low", watch=8, severe=15, min_prior=1),
    "weight": dict(source="Weight", label="Body weight", unit="%", kind="pct", bad="low", watch=3, severe=5, min_prior=1,
                   prior_days=60),
    "recovery": dict(source="WHOOP", label="WHOOP recovery", unit="pts", kind="abs", bad="low", watch=25, severe=40,
                     min_prior=7, prior_days=30),
    "hrv": dict(source="WHOOP", label="HRV", unit="%", kind="pct", bad="low", watch=20, severe=30, min_prior=7,
                prior_days=30),
}
LOAD_WATCH, LOAD_SEVERE = 1.3, 1.5


# ---------------------------------------------------------------------------
# Pure core
# ---------------------------------------------------------------------------

def vs_own(series, as_of, rule, lookback=LOOKBACK_DAYS):
    """series: [(date, value)] for one player and one measure (any order).
    The latest point inside the lookback window vs his earlier points.
    -> {"date", "latest", "base", "diff", "level": None/"watch"/"severe", "n_prior"} or None."""
    pts = sorted((d, float(v)) for d, v in series if d is not None and v is not None and d <= as_of)
    if not pts:
        return None
    d_last, latest = pts[-1]
    if d_last <= as_of - timedelta(days=lookback):
        return None
    lo = d_last - timedelta(days=rule.get("prior_days", HISTORY_DAYS))
    prior = [v for d, v in pts if lo <= d < d_last]
    if len(prior) < rule["min_prior"]:
        return None
    base = mean(prior)
    sign = -1 if rule["bad"] == "low" else 1
    level = None
    if rule["kind"] == "pct":
        if not base:
            return None
        diff = 100.0 * (latest - base) / abs(base)
        worse = diff * sign
    elif rule["kind"] == "z":
        diff = latest - base
        sd = pstdev(prior) if len(prior) > 1 else 0.0
        worse = (diff * sign / sd) if sd else 0.0
        if abs(diff) < rule.get("min_abs", 0):
            worse = 0.0
    else:
        diff = latest - base
        worse = diff * sign
    if worse >= rule["severe"]:
        level = "severe"
    elif worse >= rule["watch"]:
        level = "watch"
    return {"date": d_last, "latest": latest, "base": base, "diff": diff, "level": level, "n_prior": len(prior)}


def _num(v, unit):
    if unit == "mph":
        return f"{v:.1f} mph"
    if unit in ("pts", "%") and abs(v) >= 1:
        return f"{v:.0f}"
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"


def describe(key, r):
    """One plain line for a flag."""
    rule = FLAG_RULES[key]
    lab, kind = rule["label"], rule["kind"]
    if kind == "pct":
        change = f"{r['diff']:+.0f}%"
    elif kind == "z":
        change = f"{r['diff']:+.2f}"
    elif rule["unit"] == "mph":
        change = f"{r['diff']:+.1f} mph"
    else:
        change = f"{r['diff']:+.0f}"
    latest = (f"{r['latest']:.1f}" if rule["unit"] == "mph" else
              f"{r['latest']:.2f}" if kind == "z" or abs(r["latest"]) < 10 else f"{r['latest']:.0f}")
    base = (f"{r['base']:.1f}" if rule["unit"] == "mph" else
            f"{r['base']:.2f}" if kind == "z" or abs(r["base"]) < 10 else f"{r['base']:.0f}")
    return f"{lab} {change} · {latest} vs his {base} average ({r['n_prior']} before)"


def flag(source, key, text, severe, when, detail=""):
    return {"source": source, "key": key, "text": text, "severe": bool(severe), "date": when, "detail": detail}


def series_flags(by_player_key, as_of, lookback=LOOKBACK_DAYS):
    """{(pid, key): [(date, value)]} -> {pid: [flag]} for every FLAG_RULES key."""
    out = defaultdict(list)
    for (pid, key), series in by_player_key.items():
        rule = FLAG_RULES[key]
        r = vs_own(series, as_of, rule, lookback)
        if r and r["level"]:
            out[pid].append(flag(rule["source"], key, describe(key, r), r["level"] == "severe", r["date"]))
    return out


def load_flag(row):
    """An arm_care.pitcher_row dict -> flag or None."""
    stress = (row.get("stress") or {})
    ratio, sratio = row.get("ratio"), (stress.get("ratio") if stress.get("full") else None)
    worst = max([x for x in (ratio, sratio) if x is not None], default=None)
    if row.get("source") == "coach" and row.get("status") == "Hold":
        return flag("Load", "hold", f"On hold (coach) -- {row.get('reason', '')}".strip(" -"), False, None)
    if worst is None or worst < LOAD_WATCH:
        return None
    which = "stress" if (sratio is not None and sratio == worst and (ratio is None or sratio > ratio)) else "pitch-count"
    txt = f"Workload {which} ratio {worst:.2f} (acute:chronic) · {row.get('seven_day', 0)} pitches in 7 days"
    return flag("Load", "load", txt, worst > LOAD_SEVERE, row.get("last"))


def tier(flags):
    """None / "watch" / "priority"."""
    if not flags:
        return None
    if any(f["severe"] for f in flags) or len({f["source"] for f in flags}) >= 2:
        return "priority"
    return "watch"


def watch_list(players, flags_by_pid):
    """players: [Player] -> [{"player", "tier", "flags"}], priority first."""
    rows = []
    for p in players:
        fl = flags_by_pid.get(p.player_id) or []
        t = tier(fl)
        if t:
            fl = sorted(fl, key=lambda f: (not f["severe"], SOURCES_ORDER.index(f["source"]) if f["source"] in SOURCES_ORDER else 99))
            rows.append({"player": p, "tier": t, "flags": fl})
    rows.sort(key=lambda r: (r["tier"] != "priority", -sum(f["severe"] for f in r["flags"]), -len(r["flags"]),
                             r["player"].last_name))
    return rows


# ---------------------------------------------------------------------------
# Database loaders -> {(pid, key): [(date, value)]}
# ---------------------------------------------------------------------------

def _is_fastball(name):
    n = (name or "").lower()
    return "fastball" in n or "sinker" in n


def velo_series(db, pids, start, end):
    from models import RapsodoPitch, PitchType
    if not pids:
        return {}
    rows = (db.query(RapsodoPitch.player_id, RapsodoPitch.pitch_date, RapsodoPitch.velocity, PitchType.type_name)
            .outerjoin(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id)
            .filter(RapsodoPitch.player_id.in_(pids), RapsodoPitch.velocity.isnot(None),
                    RapsodoPitch.pitch_date >= start, RapsodoPitch.pitch_date < end + timedelta(days=1)).all())
    by = defaultdict(list)
    for pid, when, v, name in rows:
        if _is_fastball(name) and v is not None and float(v) > 50:
            by[(pid, when.date() if hasattr(when, "date") else when)].append(float(v))
    out = defaultdict(list)
    for (pid, d), vs in by.items():
        if len(vs) >= 3:
            out[(pid, "velo")].append((d, mean(vs)))
    return out


def game_series(db, pids, start, end):
    """Strike % per game for pitchers; decision pts / pitch and chase % per game for hitters."""
    from models import Game, GamePitch
    from analytics import decision_value as dv
    from plate_discipline import SWING_OUTCOMES
    from strike_zone import is_in_zone
    STRIKES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
    if not pids:
        return {}
    ps = (db.query(GamePitch, Game.game_date).join(Game, GamePitch.game_id == Game.game_id)
          .filter(Game.game_date >= start, Game.game_date <= end).all())
    pitch_by, bat_by = defaultdict(list), defaultdict(list)
    pidset = set(pids)
    for p, gd in ps:
        pitcher = p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id
        batter = p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id
        if pitcher in pidset and getattr(p, "is_pitch", True) is not False:
            pitch_by[(pitcher, p.game_id, gd)].append(p)
        if batter in pidset:
            bat_by[(batter, p.game_id, gd)].append(p)
    out = defaultdict(list)
    for (pid, _g, gd), lst in pitch_by.items():
        if len(lst) >= 15:
            out[(pid, "strike")].append((gd, 100.0 * sum(1 for p in lst if p.pitch_outcome in STRIKES) / len(lst)))
    table = dv.team_table(db) if bat_by else None
    for (pid, _g, gd), lst in bat_by.items():
        cr = [c[0] for c in (dv.credit(table, p) for p in lst) if c is not None]
        if len(cr) >= 8:
            out[(pid, "decision")].append((gd, 10.0 * sum(cr) / len(cr)))
        outz = [p for p in lst if p.actual_plate_x is not None and p.actual_plate_z is not None
                and not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
        if len(outz) >= 8:
            out[(pid, "chase")].append((gd, 100.0 * sum(1 for p in outz if p.pitch_outcome in SWING_OUTCOMES) / len(outz)))
    return out


TEST_KEYS = {"Countermovement Jump Height": "cmj_ht", "Countermovement Jump RSI-Modified": "cmj_rsi",
             "Body Weight": "weight"}


def test_series(db, pids, start, end):
    from models import Assessment, AssessmentResult, AssessmentTestType
    if not pids:
        return {}
    rows = (db.query(Assessment.player_id, Assessment.assessment_date, AssessmentTestType.test_name, AssessmentResult.value)
            .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
            .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
            .filter(Assessment.player_id.in_(pids), AssessmentTestType.test_name.in_(list(TEST_KEYS)),
                    Assessment.assessment_date >= start, Assessment.assessment_date <= end,
                    AssessmentResult.value.isnot(None)).all())
    by = defaultdict(list)
    for pid, d, name, v in rows:
        by[(pid, TEST_KEYS[name], d)].append(float(v))
    out = defaultdict(list)
    for (pid, key, d), vs in by.items():
        out[(pid, key)].append((d, max(vs) if key != "weight" else mean(vs)))   # best jump of the day
    return out


def whoop_series(db, pids, start, end):
    from models import WhoopDaily
    if not pids:
        return {}
    rows = (db.query(WhoopDaily.player_id, WhoopDaily.day_date, WhoopDaily.recovery_score, WhoopDaily.hrv_rmssd_ms)
            .filter(WhoopDaily.player_id.in_(pids), WhoopDaily.day_date >= start, WhoopDaily.day_date <= end).all())
    out = defaultdict(list)
    for pid, d, rec, hrv in rows:
        if rec is not None:
            out[(pid, "recovery")].append((d, float(rec)))
        if hrv is not None:
            out[(pid, "hrv")].append((d, float(hrv)))
    return out


def _safe(db, fn, *a):
    try:
        return fn(db, *a)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return {}


def build_watch(db, players, as_of=None, lookback=LOOKBACK_DAYS, arm_rows=None):
    """-> (watch list rows, arm care rows). arm_rows: pass arm_care rows if already built."""
    as_of = as_of or date.today()
    pids = [p.player_id for p in players]
    start = as_of - timedelta(days=HISTORY_DAYS + lookback)
    merged = defaultdict(list)
    for fn in (velo_series, game_series, test_series, whoop_series):
        for k, v in _safe(db, fn, pids, start, as_of).items():
            merged[k].extend(v)
    flags = series_flags(merged, as_of, lookback)
    if arm_rows is None:
        arm_rows = _arm_rows(db, [p for p in players if p.is_pitcher], as_of)
    for r in arm_rows:
        f = load_flag(r)
        if f:
            flags[r["player"].player_id].append(f)
    return watch_list(players, flags), arm_rows


def _arm_rows(db, pitchers, as_of):
    from analytics import arm_care
    rows = []
    for p in pitchers:
        try:
            rows.append(arm_care.pitcher_row(db, p, as_of))
        except Exception:
            db.rollback()
    return rows


# ---------------------------------------------------------------------------
# Sources (what's in) and pulse
# ---------------------------------------------------------------------------

def sources(db):
    """[{"name", "last": date or None}] -- the last day each source brought in data."""
    from sqlalchemy import func
    from models import (Game, GamePitch, RapsodoPitch, BullpenSession, Assessment, AssessmentResult,
                        AssessmentTestType, WhoopDaily, PitcherAvailability)

    def one(q):
        try:
            v = q.scalar()
        except Exception:
            db.rollback()
            return None
        return v.date() if hasattr(v, "hour") else v

    def testq(names):
        return (db.query(func.max(Assessment.assessment_date))
                .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
                .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
                .filter(AssessmentTestType.test_name.in_(names)))
    return [
        {"name": "Game charting", "last": one(db.query(func.max(Game.game_date)).join(GamePitch, GamePitch.game_id == Game.game_id))},
        {"name": "Rapsodo", "last": one(db.query(func.max(RapsodoPitch.pitch_date)))},
        {"name": "Bullpens", "last": one(db.query(func.max(BullpenSession.session_date)))},
        {"name": "CMJ", "last": one(testq(["Countermovement Jump Height", "CMJ Concentric Peak Velocity"]))},
        {"name": "Body weight", "last": one(testq(["Body Weight", "CMJ Bodyweight"]))},
        {"name": "Testing (any)", "last": one(db.query(func.max(Assessment.assessment_date)))},
        {"name": "WHOOP", "last": one(db.query(func.max(WhoopDaily.day_date)))},
        {"name": "Arm care", "last": one(db.query(func.max(PitcherAvailability.created_at)))},
    ]


def weekly(points, as_of, weeks=8, agg="sum"):
    """[(date, value)] -> list of `weeks` weekly values, oldest first (None where empty)."""
    out = []
    for w in range(weeks - 1, -1, -1):
        hi = as_of - timedelta(days=7 * w)
        lo = hi - timedelta(days=6)
        vs = [v for d, v in points if lo <= d <= hi]
        if not vs:
            out.append(None if agg != "sum" else 0)
        else:
            out.append(sum(vs) if agg == "sum" else mean(vs))
    return out


def pulse(db, players, arm_rows, as_of=None):
    """Team numbers with a trend each. -> [{"key", "label", "value", "display", "sub", "trend", "tone"}]"""
    from models import Game, GamePitch, RapsodoPitch, WhoopDaily
    as_of = as_of or date.today()
    pids = {p.player_id for p in players}
    pitchers = {p.player_id for p in players if p.is_pitcher}
    start = as_of - timedelta(days=7 * 8 - 1)
    tiles = []

    def safe(fn):
        try:
            t = fn()
            if t:
                tiles.append(t)
        except Exception:
            db.rollback()

    gp = []

    def _games():
        nonlocal gp
        gp = (db.query(GamePitch, Game.game_date).join(Game, GamePitch.game_id == Game.game_id)
              .filter(Game.game_date >= start, Game.game_date <= as_of).all())
    try:
        _games()
    except Exception:
        db.rollback()

    raps = []
    try:
        from sqlalchemy.orm import joinedload
        raps = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type)).filter(RapsodoPitch.pitch_date >= start,
                                              RapsodoPitch.pitch_date < as_of + timedelta(days=1)).all())
    except Exception:
        db.rollback()

    def _d(x):
        return x.date() if hasattr(x, "hour") else x

    # 1. throwing load: game pitches + Rapsodo pitches not already a game pitch
    def load_tile():
        pts = [(gd, 1) for p, gd in gp if (p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id) in pitchers
               and getattr(p, "is_pitch", True) is not False]
        pts += [(_d(r.pitch_date), 1) for r in raps if r.player_id in pitchers and r.game_pitch_id is None]
        trend = weekly(pts, as_of)
        this, before = trend[-1], [x for x in trend[-5:-1]]
        avg = mean(before) if any(before) else None
        pct = 100.0 * (this - avg) / avg if avg else None
        return {"key": "load", "label": "Throwing load", "value": pct,
                "display": "—" if pct is None else f"{pct:+.0f}%",
                "sub": f"{this} pitches this week vs {avg:.0f} a week before" if avg else f"{this} pitches this week",
                "trend": trend, "tone": None if pct is None else ("flag" if pct > 30 else "watch" if pct > 15 else "good")}
    safe(load_tile)

    # 2. fastball velo vs each pitcher's own norm
    def velo_tile():
        by = defaultdict(list)
        for r in raps:
            if r.player_id in pitchers and r.velocity is not None and _is_fastball(r.pitch_type.type_name if r.pitch_type else None):
                by[(r.player_id, _d(r.pitch_date))].append(float(r.velocity))
        per = defaultdict(list)
        for (pid, d), vs in by.items():
            if len(vs) >= 3:
                per[pid].append((d, mean(vs)))
        recent, at = 0, 0
        devs = []
        for pid, lst in per.items():
            lst.sort()
            norm = mean(v for _d2, v in lst)
            devs += [(d, v - norm) for d, v in lst]
            d_last, v_last = lst[-1]
            if d_last > as_of - timedelta(days=LOOKBACK_DAYS) and len(lst) >= 3:
                recent += 1
                at += v_last >= norm - 1.0
        trend = weekly(devs, as_of, agg="mean")
        pct = 100.0 * at / recent if recent else None
        return {"key": "velo", "label": "Velo at norm", "value": pct,
                "display": "—" if pct is None else f"{pct:.0f}%",
                "sub": f"{at} of {recent} pitchers within 1 mph of their own norm" if recent else "no recent Rapsodo outings",
                "trend": trend, "tone": None if pct is None else ("good" if pct >= 80 else "watch" if pct >= 60 else "flag")}
    safe(velo_tile)

    # 3. strike %
    def strike_tile():
        STR = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
        pts = [(gd, 1.0 if p.pitch_outcome in STR else 0.0) for p, gd in gp
               if (p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id) in pitchers
               and getattr(p, "is_pitch", True) is not False]
        trend = [None if v is None else 100 * v for v in weekly(pts, as_of, agg="mean")]
        recent = [v for d, v in pts if d > as_of - timedelta(days=LOOKBACK_DAYS)]
        season = [v for _d2, v in pts]
        val = 100 * mean(recent) if recent else None
        sea = 100 * mean(season) if season else None
        return {"key": "strike", "label": "Strike %", "value": val,
                "display": "—" if val is None else f"{val:.0f}%",
                "sub": (f"last {LOOKBACK_DAYS} days · {sea:.0f}% over 8 weeks" if val is not None and sea is not None
                        else "no games in the last two weeks"),
                "trend": trend, "tone": None if val is None else ("good" if val >= 62 else "watch" if val >= 58 else "flag")}
    safe(strike_tile)

    # 4. availability (arm care)
    def avail_tile():
        if not arm_rows:
            return None
        n = len(arm_rows)
        ok = sum(1 for r in arm_rows if r["status"] == "Available")
        lim = sum(1 for r in arm_rows if r["status"] == "Limited")
        pct = 100.0 * ok / n
        return {"key": "avail", "label": "Arms available", "value": pct, "display": f"{pct:.0f}%",
                "sub": f"{ok} of {n} available · {lim} limited · {n - ok - lim} down / hold", "trend": None,
                "tone": "good" if pct >= 75 else "watch" if pct >= 55 else "flag"}
    safe(avail_tile)

    # 5. hitter decisions
    def decision_tile():
        from analytics import decision_value as dv
        hitters = {p.player_id for p in players if not p.is_pitcher}
        bat = [(p, gd) for p, gd in gp if (p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id) in hitters]
        if not bat:
            return None
        table = dv.team_table(db)
        pts = []
        for p, gd in bat:
            c = dv.credit(table, p)
            if c is not None:
                pts.append((gd, 10.0 * c[0]))
        if not pts:
            return None
        trend = weekly(pts, as_of, agg="mean")
        recent = [v for d, v in pts if d > as_of - timedelta(days=LOOKBACK_DAYS)]
        val = mean(recent) if recent else None
        sea = mean(v for _d2, v in pts)
        return {"key": "decision", "label": "Hitter decisions", "value": val,
                "display": "—" if val is None else f"{val:+.2f}",
                "sub": (f"pts per pitch, last {LOOKBACK_DAYS} days · {sea:+.2f} over 8 weeks" if val is not None
                        else "no games in the last two weeks"),
                "trend": trend, "tone": None if val is None else ("good" if val >= sea else "watch")}
    safe(decision_tile)

    # 6. WHOOP recovery
    def whoop_tile():
        rows = (db.query(WhoopDaily.player_id, WhoopDaily.day_date, WhoopDaily.recovery_score)
                .filter(WhoopDaily.player_id.in_(pids), WhoopDaily.day_date >= start, WhoopDaily.day_date <= as_of,
                        WhoopDaily.recovery_score.isnot(None)).all())
        if not rows:
            return None
        pts = [(d, float(v)) for _p, d, v in rows]
        last_day = max(d for d, _v in pts)
        today = [v for d, v in pts if d == last_day]
        val = mean(today)
        n = len({p for p, d, _v in rows if d == last_day})
        return {"key": "whoop", "label": "WHOOP recovery", "value": val, "display": f"{val:.0f}%",
                "sub": f"{n} player{'s' if n != 1 else ''} · {last_day.strftime('%b %d')}",
                "trend": weekly(pts, as_of, agg="mean"),
                "tone": "good" if val >= 67 else "watch" if val >= 34 else "flag"}
    safe(whoop_tile)

    # 7. CMJ readiness: latest jump vs his own best in the last 120 days
    def cmj_tile():
        s = test_series(db, list(pids), as_of - timedelta(days=HISTORY_DAYS), as_of)
        rows = [(pid, lst) for (pid, k), lst in s.items() if k == "cmj_ht" and lst]
        if not rows:
            return None
        rec = []
        for pid, lst in rows:
            lst.sort()
            d, v = lst[-1]
            best = max(x for _d2, x in lst)
            if d > as_of - timedelta(days=30) and best:
                rec.append(100.0 * v / best)
        if not rec:
            return {"key": "cmj", "label": "CMJ readiness", "value": None, "display": "—",
                    "sub": "no jumps in the last 30 days", "trend": None, "tone": None}
        val = mean(rec)
        return {"key": "cmj", "label": "CMJ readiness", "value": val, "display": f"{val:.0f}%",
                "sub": f"of own best jump height · {len(rec)} jumped in 30 days", "trend": None,
                "tone": "good" if val >= 95 else "watch" if val >= 90 else "flag"}
    safe(cmj_tile)
    return tiles


def build(db, players, as_of=None):
    """Everything the hub draws."""
    as_of = as_of or date.today()
    watch, arm_rows = build_watch(db, players, as_of)
    return {"as_of": as_of, "sources": sources(db), "pulse": pulse(db, players, arm_rows, as_of),
            "watch": watch, "lookback": LOOKBACK_DAYS}
