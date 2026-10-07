"""
GBO -- Release outliers + "beats his stuff" (Oct 2026, from Paradigm's
"The Top 5 Ways to Outperform Your Stuff": arms without big stuff win
with an unusual release, command, mix -- so show (1) how unusual his
release is vs our staff and (2) whether his results beat what his
Stuff+ predicts).

RELEASE OUTLIERS
  Per pitcher, median release height, release side (absolute -- lefties
  and righties compared by distance from center) and extension over his
  Rapsodo readings. Each as a z-score vs the staff (one value per
  pitcher, MIN_READINGS+ readings). |z| >= TAG_Z (~top/bottom 10%) gets
  a plain tag ("very low release"). Outlier score = largest |z|.

BEATS HIS STUFF
  RV/100 = 100 x sum(run_value) / pitches (negative = good for the
  pitcher, same convention as the Results tab). Across the staff (pitchers
  with MIN_PITCHES+ game pitches and a Stuff+), fit a line RV/100 ~
  Stuff+. "Beats stuff" = predicted RV/100 - actual, in runs per 100
  pitches: + = he gives up fewer runs than pitchers with his stuff
  usually do. Needs MIN_STAFF pitchers for the line.
"""

import time
from statistics import median, mean, pstdev

MIN_READINGS = 10
TAG_Z = 1.28
MIN_PITCHES = 60
MIN_STAFF = 5
_cache = {}
CACHE_SECONDS = 600


def rv_per_100(pitches):
    rvs = [float(p.run_value) for p in pitches if getattr(p, "run_value", None) is not None]
    if not pitches or not rvs:
        return None
    return 100.0 * sum(rvs) / len(pitches)


def release_profile(raps):
    def med(f, absval=False):
        vals = [float(getattr(p, f)) for p in raps if getattr(p, f) is not None and (f != "release_extension" or float(getattr(p, f)) > 0)]
        if len(vals) < MIN_READINGS:
            return None
        return median(abs(v) for v in vals) if absval else median(vals)
    return {"height": med("release_height"), "side": med("release_side", absval=True),
            "ext": med("release_extension")}


FIELDS = {"height": ("release height", "ft", "high", "low"),
          "side": ("release side", "ft from center", "wide", "tight to center"),
          "ext": ("extension", "ft", "long", "short")}


def release_outliers(profiles):
    """profiles: {pid: release_profile}. -> {pid: {field: {value, z, pct, tag}}, "score"}"""
    out = {pid: {} for pid in profiles}
    for f, (name, unit, hi, lo) in FIELDS.items():
        vals = {pid: pr[f] for pid, pr in profiles.items() if pr and pr[f] is not None}
        if len(vals) < MIN_STAFF:
            continue
        mu, sd = mean(vals.values()), pstdev(vals.values()) or 1e-9
        allv = sorted(vals.values())
        for pid, v in vals.items():
            z = (v - mu) / sd
            pct = round(100 * sum(1 for x in allv if x < v) / max(len(allv) - 1, 1))
            tag = None
            if z >= TAG_Z:
                tag = f"very {hi} {name}"
            elif z <= -TAG_Z:
                tag = f"very {lo} {name}"
            out[pid][f] = {"value": v, "z": z, "pct": pct, "tag": tag, "unit": unit, "name": name}
    for pid, d in out.items():
        zs = [abs(x["z"]) for x in d.values()]
        d["score"] = max(zs) if zs else None
    return out


def beats_stuff(points):
    """points: {pid: (stuff_plus, rv100, n_pitches)}. -> ({pid: runs_per_100_better}, fit or None)"""
    use = [(s, r) for s, r, n in points.values() if s is not None and r is not None and n >= MIN_PITCHES]
    if len(use) < MIN_STAFF:
        return {}, None
    xs, ys = [u[0] for u in use], [u[1] for u in use]
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    a = my - b * mx
    out = {}
    for pid, (s, r, n) in points.items():
        if s is None or r is None:
            continue
        out[pid] = {"value": (a + b * s) - r, "expected": a + b * s, "actual": r, "n": n,
                    "reliable": n >= MIN_PITCHES}
    return out, {"a": a, "b": b, "n": len(use)}


def describe_beats(v):
    if v is None:
        return "—"
    if abs(v) < 1.0:
        return "results match his stuff"
    return "getting more out of his stuff than it predicts" if v > 0 else "results trail his stuff"


def staff_summary(db, date_from=None, date_to=None, game_scope="all"):
    """{pid: {"release": detail, "beats": detail}} + fit, from the leaderboard rows, cached briefly."""
    from sqlalchemy import func
    from models import GamePitch, RapsodoPitch
    from analytics.profile_queries import pitching_staff_leaderboard_rows
    stamp = (db.query(func.count(GamePitch.game_pitch_id)).scalar(), db.query(func.count(RapsodoPitch.rapsodo_pitch_id)).scalar())
    key = (id(db.get_bind()), date_from, date_to, game_scope, stamp)
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    rows = pitching_staff_leaderboard_rows(db, date_from=date_from, date_to=date_to, game_scope=game_scope)
    res = {"by_pid": {r["player"].player_id: {"release": r.get("_release_detail") or {}, "beats": r.get("_beats")}
                      for r in rows},
           "n_staff": len(rows)}
    _cache.clear()
    _cache[key] = (time.time(), res)
    return res


def summarize_rows(rows):
    """rows: leaderboard rows carrying _release (release_profile) and RV/100 / _pitches."""
    profiles = {r["player"].player_id: r.get("_release") for r in rows}
    rel = release_outliers(profiles)
    pts = {r["player"].player_id: (r.get("Stuff+"), r.get("RV/100"), r.get("_pitches", 0)) for r in rows}
    beats, fit = beats_stuff(pts)
    return {"release": rel, "beats": beats, "fit": fit, "n_staff": len(rows)}
