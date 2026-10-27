"""
GBO -- WHOOP sports-science math (Oct 2026 WHOOP pilot).

Data: models.WhoopDaily (one row per WHOOP cycle, day_date = the morning he
woke up), written by the whoop-sync Edge Function.

Readiness follows the usual HRV-guided-training approach (Plews / Buchheit):
  - HRV is compared to HIS OWN normal, never to teammates (HRV varies a lot
    between people).
  - ln(RMSSD) is used because raw HRV is skewed.
  - "Now" = 7-day rolling mean of ln(RMSSD) (needs 4+ of the last 7 days).
  - "Normal" = mean +/- 0.5 SD of his daily ln(RMSSD) over the 60 days before
    that week (needs 14+ days). 0.5 SD is the smallest worthwhile change.
  - Resting HR is read the same way, in the other direction (up = worse).
Status: z = (7-day mean - baseline mean) / baseline SD.
  HRV z <= -1.0 -> flag, <= -0.5 -> watch.  RHR z >= 1.0 -> flag, >= 0.5 -> watch.
These are starting points, not proven cutoffs -- guidance for staff, not a
decision rule.

Performance comparisons pair each game with the WHOOP day of that game
(recovery he woke up with + the sleep the night before) and the strain of
the day before. Correlations are within one player, across his own games;
with small samples (< 8 games) they're reported as "not enough games yet".
"""

import math
from collections import defaultdict
from datetime import date, timedelta

HRV_WINDOW = 7
HRV_MIN_IN_WINDOW = 4
BASELINE_DAYS = 60
BASELINE_MIN = 14
SWC_SD = 0.5
FLAG_SD = 1.0
MIN_GAMES_FOR_TREND = 8

GOOD, WATCH, FLAG, NEUTRAL = "good", "watch", "flag", "neutral"


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def recovery_zone(score):
    """WHOOP's own colors: green 67-100, yellow 34-66, red 0-33."""
    s = _f(score)
    if s is None:
        return None
    return "green" if s >= 67 else ("yellow" if s >= 34 else "red")


ZONE_STATUS = {"green": GOOD, "yellow": WATCH, "red": FLAG}


def row_dict(r):
    """WhoopDaily ORM row -> plain dict of floats (what everything here uses)."""
    scored_rec = (r.recovery_score_state or "SCORED") == "SCORED"
    scored_sleep = (r.sleep_score_state or "SCORED") == "SCORED"
    return {
        "day": r.day_date,
        "recovery": _f(r.recovery_score) if scored_rec else None,
        "hrv": _f(r.hrv_rmssd_ms) if scored_rec else None,
        "rhr": _f(r.resting_hr) if scored_rec else None,
        "spo2": _f(r.spo2_pct) if scored_rec else None,
        "skin_temp": _f(r.skin_temp_c) if scored_rec else None,
        "calibrating": bool(r.user_calibrating),
        "strain": _f(r.day_strain),
        "sleep_hours": (_f(r.total_sleep_min) / 60.0) if scored_sleep and r.total_sleep_min is not None else None,
        "sleep_need_hours": (_f(r.sleep_need_min) / 60.0) if r.sleep_need_min is not None else None,
        "sleep_performance": _f(r.sleep_performance_pct) if scored_sleep else None,
        "sleep_consistency": _f(r.sleep_consistency_pct) if scored_sleep else None,
        "sleep_efficiency": _f(r.sleep_efficiency_pct) if scored_sleep else None,
        "resp_rate": _f(r.respiratory_rate) if scored_sleep else None,
        "deep_hours": (_f(r.deep_sleep_min) / 60.0) if r.deep_sleep_min is not None else None,
        "rem_hours": (_f(r.rem_sleep_min) / 60.0) if r.rem_sleep_min is not None else None,
    }


def load_daily(db, player_id, date_from=None, date_to=None):
    """[row_dict] oldest first. If two cycles land on one day (rare -- a
    timezone change), the later one wins."""
    from models import WhoopDaily
    q = db.query(WhoopDaily).filter(WhoopDaily.player_id == player_id)
    if date_from is not None:
        q = q.filter(WhoopDaily.day_date >= date_from)
    if date_to is not None:
        q = q.filter(WhoopDaily.day_date <= date_to)
    by_day = {}
    for r in q.order_by(WhoopDaily.day_date, WhoopDaily.cycle_id).all():
        by_day[r.day_date] = row_dict(r)
    return [by_day[d] for d in sorted(by_day)]


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _sd(xs):
    if len(xs) < 2:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _window(rows, key, start, end, transform=None):
    out = []
    for r in rows:
        if start <= r["day"] <= end and r.get(key) is not None:
            v = r[key]
            if transform:
                if v <= 0:
                    continue
                v = transform(v)
            out.append(v)
    return out


def metric_status(rows, as_of, key, higher_is_better=True, log=False):
    """7-day mean vs his 60-day normal for one metric. Returns a dict:
    now, base_mean, base_sd, z, n_week, n_base, status, label, band (lo, hi)
    in the metric's own units."""
    tf = math.log if log else None
    week = _window(rows, key, as_of - timedelta(days=HRV_WINDOW - 1), as_of, tf)
    base = _window(rows, key, as_of - timedelta(days=HRV_WINDOW + BASELINE_DAYS - 1), as_of - timedelta(days=HRV_WINDOW), tf)
    out = {"n_week": len(week), "n_base": len(base), "now": None, "base_mean": None, "base_sd": None,
           "z": None, "band": None, "status": NEUTRAL, "label": "No data"}
    back = math.exp if log else (lambda v: v)
    if len(week) >= HRV_MIN_IN_WINDOW:
        out["now"] = back(_mean(week))
    if len(base) < BASELINE_MIN:
        out["label"] = f"Building baseline ({len(base)}/{BASELINE_MIN} days)" if rows else "No data"
        return out
    m, s = _mean(base), _sd(base)
    out["base_mean"], out["base_sd"] = back(m), s
    if s:
        out["band"] = (back(m - SWC_SD * s), back(m + SWC_SD * s))
    if out["now"] is None or not s:
        out["label"] = "Not enough days this week"
        return out
    z = (_mean(week) - m) / s
    out["z"] = z
    bad = -z if higher_is_better else z
    if bad >= FLAG_SD:
        out["status"], out["label"] = FLAG, ("Well below normal" if higher_is_better else "Well above normal")
    elif bad >= SWC_SD:
        out["status"], out["label"] = WATCH, ("Below normal" if higher_is_better else "Above normal")
    elif bad <= -SWC_SD:
        out["status"], out["label"] = GOOD, ("Above normal" if higher_is_better else "Below normal")
    else:
        out["status"], out["label"] = GOOD, "Normal"
    return out


_RANK = {FLAG: 3, WATCH: 2, GOOD: 1, NEUTRAL: 0}


def readiness(rows, as_of=None):
    """Everything the Recovery tab / board header needs for one player."""
    as_of = as_of or (rows[-1]["day"] if rows else date.today())
    today = next((r for r in reversed(rows) if r["day"] <= as_of), None)
    if today is not None and today["day"] < as_of - timedelta(days=2):
        today = None  # stale: no WHOOP day in the last 3 days
    hrv = metric_status(rows, as_of, "hrv", higher_is_better=True, log=True)
    rhr = metric_status(rows, as_of, "rhr", higher_is_better=False)
    sleep_week = _window(rows, "sleep_hours", as_of - timedelta(days=6), as_of)
    need_week = _window(rows, "sleep_need_hours", as_of - timedelta(days=6), as_of)
    statuses = [s["status"] for s in (hrv, rhr) if s["status"] != NEUTRAL]
    overall = max(statuses, key=lambda s: _RANK[s]) if statuses else NEUTRAL
    if overall == FLAG:
        label = "Back off"
    elif overall == WATCH:
        label = "Monitor"
    elif overall == GOOD:
        label = "Ready"
    else:
        label = hrv["label"] if rows else "No WHOOP data"
    return {
        "as_of": as_of, "today": today, "hrv": hrv, "rhr": rhr,
        "zone": recovery_zone(today["recovery"]) if today else None,
        "sleep_avg_7d": _mean(sleep_week), "sleep_need_avg_7d": _mean(need_week),
        "sleep_debt_7d": (sum(need_week) - sum(sleep_week)) if sleep_week and len(sleep_week) == len(need_week) else None,
        "status": overall, "label": label, "days": len(rows),
    }


def rolling_hrv(rows):
    """[(day, 7-day mean HRV in ms or None)] for the trend line."""
    out = []
    for r in rows:
        w = _window(rows, "hrv", r["day"] - timedelta(days=HRV_WINDOW - 1), r["day"], math.log)
        out.append((r["day"], math.exp(_mean(w)) if len(w) >= HRV_MIN_IN_WINDOW else None))
    return out


def daily_hrv_z(rows, day):
    """Single-morning ln(RMSSD) z vs his 60 days before it (None if no baseline)."""
    r = next((x for x in rows if x["day"] == day), None)
    if r is None or not r.get("hrv") or r["hrv"] <= 0:
        return None
    base = _window(rows, "hrv", day - timedelta(days=BASELINE_DAYS), day - timedelta(days=1), math.log)
    if len(base) < BASELINE_MIN:
        return None
    s = _sd(base)
    return (math.log(r["hrv"]) - _mean(base)) / s if s else None


# --------------------------------------------------------------- performance
def _whoop_context(rows, day):
    by_day = {r["day"]: r for r in rows}
    r = by_day.get(day) or {}
    prev = by_day.get(day - timedelta(days=1)) or {}
    return {
        "recovery": r.get("recovery"), "hrv": r.get("hrv"), "rhr": r.get("rhr"),
        "hrv_z": daily_hrv_z(rows, day), "sleep_hours": r.get("sleep_hours"),
        "sleep_performance": r.get("sleep_performance"), "prev_strain": prev.get("strain"),
        "has_whoop": bool(r),
    }


def pitcher_outings(db, player_id, rows, date_from=None, date_to=None):
    """One dict per game he pitched: date, opponent, pitches, fb_velo (avg
    game Rapsodo fastball), fb_max, strike_pct, zone_exec_pct + WHOOP context."""
    from analytics.profile_queries import get_pitcher_profile_pitches, rapsodo_by_game_pitch_id
    from game_stats import compute_pitching_line
    from pitch_type_config import FASTBALL_TYPES
    pitches = get_pitcher_profile_pitches(db, player_id, date_from=date_from, date_to=date_to)
    by_game = defaultdict(list)
    for gp in pitches:
        by_game[gp.game_id].append(gp)
    raps = rapsodo_by_game_pitch_id(db, [gp.game_pitch_id for gp in pitches if gp.game_pitch_id is not None])
    out = []
    for gid, gps in by_game.items():
        g = gps[0].game
        line = compute_pitching_line(gps)
        fb = [raps[gp.game_pitch_id].velocity for gp in gps
              if gp.game_pitch_id in raps and raps[gp.game_pitch_id].pitch_type
              and raps[gp.game_pitch_id].pitch_type.type_name in FASTBALL_TYPES and raps[gp.game_pitch_id].velocity is not None]
        fb = [float(v) for v in fb]
        row = {"game_id": gid, "day": g.game_date, "opponent": "Intrasquad" if g.is_intrasquad else (g.opponent_name or "Game"),
               "pitches": line.get("Pitches"), "fb_velo": _mean(fb), "fb_max": max(fb) if fb else None, "n_fb": len(fb),
               "strike_pct": line.get("Strike %"), "zone_exec_pct": line.get("Zone Execution %")}
        row.update(_whoop_context(rows, g.game_date))
        out.append(row)
    out.sort(key=lambda r: r["day"])
    return out


def hitter_games(db, player_id, rows, date_from=None, date_to=None):
    """One dict per game he hit in: date, opponent, PA, wOBA, K% + WHOOP context."""
    from analytics.profile_queries import get_hitter_profile_pitches
    from game_stats import compute_batting_line
    pitches = get_hitter_profile_pitches(db, player_id, date_from=date_from, date_to=date_to)
    by_game = defaultdict(list)
    for gp in pitches:
        by_game[gp.game_id].append(gp)
    out = []
    for gid, gps in by_game.items():
        g = gps[0].game
        line = compute_batting_line(gps)
        row = {"game_id": gid, "day": g.game_date, "opponent": "Intrasquad" if g.is_intrasquad else (g.opponent_name or "Game"),
               "pa": line.get("PA"), "woba": line.get("wOBA"), "k_pct": line.get("K %"), "avg": line.get("AVG")}
        row.update(_whoop_context(rows, g.game_date))
        out.append(row)
    out.sort(key=lambda r: r["day"])
    return out


def relationship(games, x_key, y_key, min_n=MIN_GAMES_FOR_TREND):
    """Pearson r + least-squares slope across his own games. Plain-English
    read; 'not enough games' under min_n."""
    pts = [(float(g[x_key]), float(g[y_key])) for g in games if g.get(x_key) is not None and g.get(y_key) is not None]
    res = {"n": len(pts), "points": pts, "r": None, "slope": None, "intercept": None, "ok": False}
    if len(pts) < 3:
        res["read"] = f"{len(pts)} game{'s' if len(pts) != 1 else ''} with both numbers -- needs more games."
        return res
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    if not sxx or not syy:
        res["read"] = "No spread in one of the two numbers yet."
        return res
    res["r"] = sxy / math.sqrt(sxx * syy)
    res["slope"] = sxy / sxx
    res["intercept"] = my - res["slope"] * mx
    res["ok"] = len(pts) >= min_n
    r = res["r"]
    strength = "no clear" if abs(r) < 0.2 else ("a weak" if abs(r) < 0.4 else ("a moderate" if abs(r) < 0.6 else "a strong"))
    direction = "" if abs(r) < 0.2 else (" positive" if r > 0 else " negative")
    res["read"] = (f"{strength.capitalize()}{direction} relationship (r = {r:+.2f}, {len(pts)} games)."
                   + ("" if res["ok"] else f" Early read -- wait for {min_n}+ games before trusting it."))
    return res


# --------------------------------------------------------------- team board
def team_board(db, as_of=None):
    """One dict per active WHOOP connection: player, connection, readiness."""
    from models import WhoopConnection, Player
    from sqlalchemy.orm import joinedload
    as_of = as_of or date.today()
    conns = (db.query(WhoopConnection).options(joinedload(WhoopConnection.player))
             .filter(WhoopConnection.active.is_(True)).all())
    out = []
    for c in conns:
        p = c.player
        if p is None or not p.active:
            continue
        rows = load_daily(db, c.player_id, date_from=as_of - timedelta(days=HRV_WINDOW + BASELINE_DAYS + 2), date_to=as_of)
        out.append({"player": p, "connection": c, "ready": readiness(rows, as_of), "rows": rows})
    out.sort(key=lambda x: (-_RANK[x["ready"]["status"]], x["player"].last_name or "", x["player"].first_name or ""))
    return out
