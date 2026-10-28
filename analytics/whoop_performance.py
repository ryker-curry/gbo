"""
GBO -- WHOOP vs performance explorer (Oct 2026, Ryker: "compare these
variables to performance such as velocity ... force plate metrics").

Pairs every performance session (a Rapsodo game day, a bullpen day, or an
assessment test date) with his WHOOP state going into it:
  - that morning: recovery, HRV vs his normal (z), resting HR
  - the night before: hours slept, sleep %, deep sleep
  - the day before: strain
  - the last 3 nights: average sleep
Rules (sports-science standard, see the WHOOP section of How to Read GBO):
  - Within-player: performance is also read as "vs his own average", so a
    92-mph guy and an 84-mph guy can be pooled.
  - Team pooling = repeated-measures correlation (rmcorr; Bakdash & Marusich
    2017): center both variables on each player's own mean, then correlate,
    df = sessions - players - 1.
  - Small samples are labelled early; MIN_SESSIONS before a read is trusted.
Choices (Ryker, Oct 2026): game and bullpen velo as SEPARATE outcomes; any
assessment test, countermovement-jump metrics listed first.
"""

import math
from collections import defaultdict
from datetime import timedelta

from analytics import whoop_metrics as wm

MIN_SESSIONS = 15   # per player, before a correlation is more than descriptive
MIN_TEAM = 20       # pooled sessions

# ------------------------------------------------------------------ predictors
PREDICTORS = {
    "recovery": ("Recovery % that morning", "{:.0f}"),
    "hrv_z": ("HRV vs his normal (SD)", "{:+.1f}"),
    "rhr": ("Resting HR that morning", "{:.0f}"),
    "sleep_hours": ("Hours slept the night before", "{:.1f}"),
    "sleep_performance": ("Sleep % (slept vs needed)", "{:.0f}"),
    "deep_hours": ("Deep sleep the night before (h)", "{:.1f}"),
    "prev_strain": ("Strain the day before", "{:.1f}"),
    "sleep_3d": ("Avg sleep, last 3 nights (h)", "{:.1f}"),
}


def whoop_context(rows, day):
    """WHOOP state going into `day` (rows: whoop_metrics.load_daily)."""
    by_day = {r["day"]: r for r in rows}
    r = by_day.get(day) or {}
    prev = by_day.get(day - timedelta(days=1)) or {}
    last3 = [by_day[d]["sleep_hours"] for d in (day - timedelta(days=i) for i in range(3))
             if d in by_day and by_day[d].get("sleep_hours") is not None]
    return {
        "recovery": r.get("recovery"), "hrv_z": wm.daily_hrv_z(rows, day), "rhr": r.get("rhr"),
        "sleep_hours": r.get("sleep_hours"), "sleep_performance": r.get("sleep_performance"),
        "deep_hours": r.get("deep_hours"), "prev_strain": prev.get("strain"),
        "sleep_3d": (sum(last3) / len(last3)) if len(last3) >= 2 else None,
        "zone": wm.recovery_zone(r.get("recovery")),
    }


# ------------------------------------------------------------------ outcomes
CMJ_PREFIX = "Countermovement Jump"


def outcome_choices(db, player_id=None):
    """{key: label}, velo first, then CMJ tests, then every other test with
    data (for one player, or anyone when player_id is None)."""
    from sqlalchemy import func
    from models import Assessment, AssessmentResult, AssessmentTestType
    out = {"fb_game": "FB velo, games (avg mph)", "fb_pen": "FB velo, bullpens (avg mph)",
           "fb_pen_max": "FB velo, bullpens (max mph)"}
    q = (db.query(AssessmentTestType.test_type_id, AssessmentTestType.test_name, AssessmentTestType.unit, func.count(AssessmentResult.result_id))
         .join(AssessmentResult, AssessmentResult.test_type_id == AssessmentTestType.test_type_id)
         .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id))
    if player_id is not None:
        q = q.filter(Assessment.player_id == player_id)
    tests = q.group_by(AssessmentTestType.test_type_id, AssessmentTestType.test_name, AssessmentTestType.unit).all()
    tests.sort(key=lambda t: (0 if t[1].startswith(CMJ_PREFIX) else 1, t[1]))
    for tid, name, unit, _n in tests:
        out[f"test:{tid}"] = f"{name}" + (f" ({unit})" if unit else "")
    return out


def outcome_sessions(db, player_id, key, date_from=None):
    """[(day, value)] one per session day for this outcome."""
    from models import RapsodoPitch, Assessment, AssessmentResult
    from sqlalchemy.orm import joinedload
    from pitch_type_config import FASTBALL_TYPES
    if key in ("fb_game", "fb_pen", "fb_pen_max"):
        q = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
             .filter(RapsodoPitch.player_id == player_id, RapsodoPitch.velocity.isnot(None)))
        q = q.filter(RapsodoPitch.bullpen_id.is_(None) if key == "fb_game" else RapsodoPitch.bullpen_id.isnot(None))
        by_day = defaultdict(list)
        for p in q.all():
            if p.pitch_date is None or not p.pitch_type or p.pitch_type.type_name not in FASTBALL_TYPES:
                continue
            d = p.pitch_date.date()
            if date_from is None or d >= date_from:
                by_day[d].append(float(p.velocity))
        agg = max if key == "fb_pen_max" else (lambda v: sum(v) / len(v))
        return sorted((d, agg(v)) for d, v in by_day.items() if v)
    if key.startswith("test:"):
        tid = int(key.split(":", 1)[1])
        rows = (db.query(Assessment.assessment_date, AssessmentResult.value)
                .join(AssessmentResult, AssessmentResult.assessment_id == Assessment.assessment_id)
                .filter(Assessment.player_id == player_id, AssessmentResult.test_type_id == tid).all())
        by_day = defaultdict(list)
        for d, v in rows:
            if v is not None and (date_from is None or d >= date_from):
                by_day[d].append(float(v))
        return sorted((d, max(v)) for d, v in by_day.items())   # best of the day's trials
    return []


# ------------------------------------------------------------------ analysis
def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def _pearson(pts):
    n = len(pts)
    if n < 3:
        return None
    mx, my = _mean([p[0] for p in pts]), _mean([p[1] for p in pts])
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    syy = sum((y - my) ** 2 for _, y in pts)
    sxy = sum((x - mx) * (y - my) for x, y in pts)
    if not sxx or not syy:
        return None
    return sxy / math.sqrt(sxx * syy), sxy / sxx, my - (sxy / sxx) * mx


def _strength(r):
    a = abs(r)
    word = "no clear" if a < 0.2 else ("a weak" if a < 0.4 else ("a moderate" if a < 0.6 else "a strong"))
    return word + ("" if a < 0.2 else (" positive" if r > 0 else " negative"))


def paired_sessions(db, player_id, outcome_key, rows, date_from=None):
    """[{day, value, diff (vs his own avg), **whoop_context}] -- sessions on
    days he has a WHOOP day."""
    sess = outcome_sessions(db, player_id, outcome_key, date_from)
    have = {r["day"] for r in rows}
    paired = [dict(day=d, value=v, **whoop_context(rows, d)) for d, v in sess if d in have]
    if paired:
        avg = _mean([p["value"] for p in paired])
        for p in paired:
            p["diff"] = p["value"] - avg
    return paired, len(sess)


def zone_summary(paired, value_key="value"):
    """{zone: (mean, n)} for green / yellow / red mornings."""
    out = {}
    for z in ("green", "yellow", "red"):
        vals = [p[value_key] for p in paired if p.get("zone") == z]
        out[z] = (_mean(vals), len(vals))
    return out


def player_read(paired, predictor):
    pts = [(p[predictor], p["value"]) for p in paired if p.get(predictor) is not None]
    res = {"n": len(pts), "points": pts, "r": None, "slope": None, "intercept": None, "ok": False}
    fit = _pearson(pts)
    if fit is None:
        res["read"] = f"{len(pts)} session{'s' if len(pts) != 1 else ''} with both numbers -- needs more before there's anything to read."
        return res
    res["r"], res["slope"], res["intercept"] = fit
    res["ok"] = len(pts) >= MIN_SESSIONS
    res["read"] = (f"{_strength(res['r']).capitalize()} relationship (r = {res['r']:+.2f}, {len(pts)} sessions)."
                   + ("" if res["ok"] else f" Early read -- wait for {MIN_SESSIONS}+ sessions."))
    return res


def team_read(db, outcome_key, predictor, as_of=None, date_from=None):
    """Repeated-measures correlation across every connected player."""
    from models import WhoopConnection
    out = {"players": [], "r": None, "n": 0, "n_players": 0, "zones": {}, "ok": False}
    centered, zone_diffs = [], defaultdict(list)
    for c in db.query(WhoopConnection).filter(WhoopConnection.active.is_(True)).all():
        rows = wm.load_daily(db, c.player_id)
        if not rows:
            continue
        paired, _ = paired_sessions(db, c.player_id, outcome_key, rows, date_from)
        pts = [(p[predictor], p["value"]) for p in paired if p.get(predictor) is not None]
        name = f"{c.player.first_name} {c.player.last_name}" if c.player else f"Player {c.player_id}"
        fit = _pearson(pts)
        out["players"].append({"name": name, "n": len(pts), "r": fit[0] if fit else None})
        if len(pts) >= 3:
            mx, my = _mean([x for x, _ in pts]), _mean([y for _, y in pts])
            centered += [(x - mx, y - my) for x, y in pts]
            out["n_players"] += 1
        for p in paired:
            if p.get("zone"):
                zone_diffs[p["zone"]].append(p["diff"])
    out["n"] = len(centered)
    if centered:
        sxx = sum(x * x for x, _ in centered)
        syy = sum(y * y for _, y in centered)
        sxy = sum(x * y for x, y in centered)
        if sxx and syy:
            out["r"] = sxy / math.sqrt(sxx * syy)
    out["df"] = max(out["n"] - out["n_players"] - 1, 0)
    out["ok"] = out["n"] >= MIN_TEAM and out["n_players"] >= 2
    out["zones"] = {z: (_mean(v), len(v)) for z, v in zone_diffs.items()}
    if out["r"] is None:
        out["read"] = "Not enough paired sessions yet."
    else:
        out["read"] = (f"Within-player, {_strength(out['r'])} relationship (rmcorr r = {out['r']:+.2f}, "
                       f"{out['n']} sessions, {out['n_players']} player{'s' if out['n_players'] != 1 else ''})."
                       + ("" if out["ok"] else f" Early read -- needs {MIN_TEAM}+ sessions across 2+ players."))
    return out
