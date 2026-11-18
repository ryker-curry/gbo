"""
GBO -- Throwing Workload math (Nov 2026, Ryker). Pure: no database, no UI.

Counts every throw, not just charted pitches, the way Driveline's workload
charts do:
  game      -- charted game / scrimmage pitches (GamePitch)
  bullpen   -- bullpen pitches (max of BullpenPitch / Rapsodo / Command per
               session, same rule as workload_queries.py)
  logged    -- throws staff typed in (catch play, long toss, flat ground,
               plyos, warm-up ...), from throw_logs source "manual"
  sensor    -- a PULSE / Motus / other sensor export for that day. A sensor
               sees every throw, so a sensor day's total IS the sensor
               count (pitches and logs aren't added on top).
  assumed   -- "padded" throws nobody logged: a warm-up before each bullpen
               and game outing, and routine catch play on throwing days.
               Never added on a sensor day, and logging anything for a day
               (or a "No throwing" 0) replaces the assumed catch play.

Ratio: acute = average throws per day over the last 9 days, chronic =
average per day over the last 28 (Driveline's windows), ratio = acute /
chronic. Bands from the Driveline chart Ryker shared: 0.8-1.2 in range,
0.7-0.8 or 1.2-1.3 watch, under 0.7 or over 1.3 outside. These are
planning guides, not injury predictors -- the ratio is noisy when the
chronic side is thin (his first 4 weeks), so those days are flagged.

Weekly build vs benchmarks (pro numbers, Driveline 2026 throwing volume
tables and Jackson Sigman): starters ~595 (A) to 665 (MLB) throws a week,
relievers ~490; Sigman's 500-700 a week / 2,000-3,000 a month once built
up -- and the first time a pitcher reaches it shouldn't be in season.
"""

from datetime import date, timedelta

ACUTE_DAYS = 9
CHRONIC_DAYS = 28

BAND_IN = (0.8, 1.2)
BAND_WATCH = (0.7, 1.3)

# Weekly / monthly benchmarks (pro). Kept as reference lines, not targets
# GBO enforces.
BENCH_WEEK_RANGE = (500, 700)          # Sigman
BENCH_MONTH_RANGE = (2000, 3000)       # Sigman
BENCH_SP_WEEK = {"A": 595, "MLB": 665}  # Driveline 2026 starters, median throws / week
BENCH_SP_MONTH_MLB = 2891
BENCH_RP_WEEK = 492                     # Driveline 2026 relievers, ~492-496 / week
BENCH_RP_MONTH = 2150                   # ~2,140-2,158 / month

LOG_TYPES = ["Catch play", "Long toss", "Flat ground", "Plyos / drills", "Warm-up", "Other", "No throwing"]
SENSOR_SOURCES = ("pulse", "motus", "sensor")
PARTS = ("game", "bullpen", "logged", "sensor", "assumed")

DEFAULT_ASSUME = {"pen_warmup": 25, "game_warmup": 35, "catch_play": 40, "catch_play_days": "practice"}


def zone(ratio):
    """"In range" / "Watch" / "Outside" (None in, None out)."""
    if ratio is None:
        return None
    if BAND_IN[0] <= ratio <= BAND_IN[1]:
        return "In range"
    if BAND_WATCH[0] <= ratio <= BAND_WATCH[1]:
        return "Watch"
    return "Outside"


def _catch_day(d, rule, practice_days):
    if rule == "off":
        return False
    if rule == "daily":
        return True
    if rule == "weekdays":
        return d.weekday() < 6          # Mon-Sat
    return d in practice_days            # "practice": team schedule practice days


def daily_parts(start, end, game=None, bullpen=None, logs=None, practice_days=(), assume=None, tracking_start=None):
    """One row per day in [start, end]:
      {"date", "game", "bullpen", "logged", "sensor", "assumed", "total",
       "high_intent", "tracked"}
    game / bullpen: {date: pitches}. logs: [{"date", "throws", "throw_type",
    "source", "high_intent"}]. Days before tracking_start are "tracked":
    False (unknown, not zero) and get no assumed throws."""
    game, bullpen, logs = game or {}, bullpen or {}, logs or []
    a = dict(DEFAULT_ASSUME, **(assume or {}))
    practice_days = set(practice_days)
    by_day = {}
    for lg in logs:
        by_day.setdefault(lg["date"], []).append(lg)
    rows, d = [], start
    while d <= end:
        tracked = tracking_start is not None and d >= tracking_start
        day_logs = by_day.get(d, [])
        sensor = [x for x in day_logs if x["source"] in SENSOR_SOURCES]
        manual = [x for x in day_logs if x["source"] not in SENSOR_SOURCES]
        r = {"date": d, "game": 0, "bullpen": 0, "logged": 0, "sensor": 0, "assumed": 0, "high_intent": None,
             "tracked": tracked}
        hi = [x.get("high_intent") for x in day_logs if x.get("high_intent") is not None]
        if hi:
            r["high_intent"] = sum(hi)
        if sensor:
            r["sensor"] = sum(int(x["throws"] or 0) for x in sensor)
        else:
            g, b = int(game.get(d, 0) or 0), int(bullpen.get(d, 0) or 0)
            r["game"], r["bullpen"] = g, b
            r["logged"] = sum(int(x["throws"] or 0) for x in manual)
            if tracked:
                warm_logged = any(x["throw_type"] == "Warm-up" for x in manual)
                if not warm_logged:
                    if g:
                        r["assumed"] += a["game_warmup"]
                    elif b:
                        r["assumed"] += a["pen_warmup"]
                if not manual and not g and not b and _catch_day(d, a["catch_play_days"], practice_days):
                    r["assumed"] += a["catch_play"]
        r["total"] = r["game"] + r["bullpen"] + r["logged"] + r["sensor"] + r["assumed"]
        rows.append(r)
        d += timedelta(days=1)
    return rows


def with_ratio(rows, acute_days=ACUTE_DAYS, chronic_days=CHRONIC_DAYS):
    """Adds acute / chronic (average throws per day), their per-week
    equivalents, ratio, zone and full_history to each row from daily_parts.
    Rows must be consecutive days, oldest first; untracked days are left
    out of both windows."""
    out = []
    for i, r in enumerate(rows):
        def win(n):
            vals = [x["total"] for x in rows[max(0, i - n + 1): i + 1] if x["tracked"]]
            return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)
        ac, an = win(acute_days)
        ch, cn = win(chronic_days)
        ratio = round(ac / ch, 2) if ac is not None and ch else None
        out.append(dict(r, acute=None if ac is None else round(ac, 1), chronic=None if ch is None else round(ch, 1),
                        acute_week=None if ac is None else round(ac * 7), chronic_week=None if ch is None else round(ch * 7),
                        ratio=ratio, zone=zone(ratio), full_history=cn >= chronic_days and an >= acute_days))
    return out


def weekly(rows):
    """Monday-Sunday totals: [{"week_start", "total", "assumed", "days"}]."""
    weeks = {}
    for r in rows:
        if not r["tracked"]:
            continue
        ws = r["date"] - timedelta(days=r["date"].weekday())
        w = weeks.setdefault(ws, {"week_start": ws, "total": 0, "assumed": 0, "days": 0})
        w["total"] += r["total"]
        w["assumed"] += r["assumed"]
        w["days"] += 1
    return [weeks[k] for k in sorted(weeks)]


def summary(rows, as_of):
    """Team-table numbers for one pitcher as of a date (rows from with_ratio,
    ending on as_of)."""
    last = next((r for r in reversed(rows) if r["date"] <= as_of), None)
    if last is None:
        return None
    lo = as_of - timedelta(days=6)
    last7 = [r for r in rows if lo <= r["date"] <= as_of and r["tracked"]]
    last28 = [r for r in rows if as_of - timedelta(days=27) <= r["date"] <= as_of and r["tracked"]]
    t28 = sum(r["total"] for r in last28)
    return {
        "last7": sum(r["total"] for r in last7),
        "acute_week": last["acute_week"], "chronic_week": last["chronic_week"],
        "ratio": last["ratio"], "zone": last["zone"], "full_history": last["full_history"],
        "assumed_pct": round(100 * sum(r["assumed"] for r in last28) / t28) if t28 else None,
        "sensor_days": sum(1 for r in last28 if r["sensor"]),
        "tracked_days": len(last28),
    }
