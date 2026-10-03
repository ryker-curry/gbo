"""
GBO -- Stuff+ Breakdown (Oct 2026, Ryker, after Kyle Bland's "Why doesn't
he get whiffs if he has good Stuff?" thread / blandalytics model
drilldown). Answers two questions per pitch type:

1. Why is his Stuff+ what it is?  GBO's Stuff+ is a fixed-weight linear
   composite (see pitch_grading.stuff_plus):
       Stuff+ = 100 + 10 * (sum_f w_f * z_f - p_mean) / p_sd
   so it splits EXACTLY into one piece per feature -- no SHAP needed:
       contribution_f = 10 * w_f * z_f / p_sd
       base           = 100 - 10 * p_mean / p_sd   (~100)
   Averaged over his pitches of that type, base + sum(contributions)
   equals his average Stuff+ for it.

2. Are the results matching the stuff?  Run value (pitcher's side --
   GamePitch.run_value is the batter's, so it's negated here) per 100
   pitches, split by what happened (whiffs, called strikes, fouls,
   balls, balls in play), compared with the team's average for the same
   pitch type. The bucket gaps add up to his total gap vs the team, so
   "good stuff, no results" shows WHERE it leaks (usually balls or
   contact).
"""

from statistics import mean

from analytics import profile_queries
from analytics.pitch_grading import _stuff_plus_features

FEATURE_LABELS = {
    "velocity": ("Velocity", "mph", 1),
    "velocity_differential": ("Speed gap vs FB", "mph", 1),
    "vb_trajectory": ("Vertical break", "in", 1),
    "hb_trajectory": ("Horizontal break", "in", 1),
    "total_spin": ("Spin rate", "rpm", 0),
    "spin_efficiency": ("Spin efficiency", "%", 0),
    "spin_axis_offset": ("Axis off backspin", "°", 0),
    "gyro_degree": ("Gyro", "°", 0),
    "release_height": ("Release height", "ft", 2),
    "release_side": ("Release side", "ft", 2),
}

# What a coach can say to the player about each feature (direction the
# weight rewards). Negative weights read the other way.
FEATURE_TIPS = {
    "velocity": "more velo",
    "velocity_differential": "more speed separation from his fastball",
    "vb_trajectory": "more vertical break",
    "hb_trajectory": "more horizontal break",
    "total_spin": "more spin",
    "spin_efficiency": "more efficient (less wasted) spin",
    "spin_axis_offset": "axis further off pure backspin",
    "gyro_degree": "more gyro",
}

OUTCOME_BUCKETS = (
    ("Whiffs", ("Swing and Miss",)),
    ("Called strikes", ("Called Strike",)),
    ("Fouls", ("Foul",)),
    ("Balls", ("Ball", "HBP")),
    ("Balls in play", ("In Play",)),
)

MIN_PITCHES_FOR_BREAKDOWN = 5      # Rapsodo readings of a type to show bars
MIN_PITCHES_FOR_OUTCOMES = 75      # game pitches before outcome gaps mean much


def _type_name(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) else None


def _contribs_for_pitch(rp, model):
    """{feature: Stuff+ points} for one pitch, or None if nothing scored."""
    pv = model.get("pitcher_fastball_velocities", {}).get(rp.player_id)
    feats = _stuff_plus_features(rp, pv)
    p_mean, p_sd = model["prediction_baseline"]
    if not p_sd:
        return None
    out = {}
    for name, w in model["quality_weights"].items():
        if not w:
            continue
        v = feats.get(name)
        b_mean, b_sd = model["feature_baseline"].get(name, (None, None))
        if v is None or b_mean is None or not b_sd:
            continue
        out[name] = 10.0 * w * (v - b_mean) / b_sd / p_sd
    return out or None


def _percentile(value, pool):
    if value is None or not pool:
        return None
    below = sum(1 for x in pool if x < value)
    ties = sum(1 for x in pool if x == value)
    return round(100.0 * (below + 0.5 * ties) / len(pool))


def stuff_breakdown(rapsodo_pitches, models, training_by_type):
    """One dict per pitch type he threw (most-thrown first):
       {label, n, stuff_plus, base, features: [{name, label, unit, contrib,
        value, team_avg, pct, weight}], team_values: {feature: [...]},
        his_values: {feature: [...]}, enough}
    features sorted by |contrib| desc. Types with no Stuff+ model yet are
    returned with features=[] and a reason."""
    by_type = {}
    for rp in rapsodo_pitches:
        label = _type_name(rp)
        if label:
            by_type.setdefault(label, []).append(rp)
    out = []
    for label, rps in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        model = models.get(label)
        if model is None:
            out.append({"label": label, "n": len(rps), "stuff_plus": None, "features": [],
                        "reason": "Not enough team game data on this pitch type for a Stuff+ model yet."})
            continue
        per_pitch = [c for c in (_contribs_for_pitch(rp, model) for rp in rps) if c]
        if not per_pitch:
            out.append({"label": label, "n": len(rps), "stuff_plus": None, "features": [],
                        "reason": "No usable Rapsodo readings for this pitch type."})
            continue
        p_mean, p_sd = model["prediction_baseline"]
        base = 100.0 - 10.0 * p_mean / p_sd
        names = [n for n, w in model["quality_weights"].items() if w and n in model["feature_baseline"]]
        pv_map = model.get("pitcher_fastball_velocities", {})
        his_vals = {n: [] for n in names}
        for rp in rps:
            f = _stuff_plus_features(rp, pv_map.get(rp.player_id))
            for n in names:
                if f.get(n) is not None:
                    his_vals[n].append(f[n])
        # Same pitch type ONLY: the comparison pool is the team's game
        # pitches whose own Rapsodo pitch type is exactly this label
        # (2-Seam vs 2-Seam, never 2-Seam vs 4-Seam) -- the same pool
        # this type's Stuff+ model was built from.
        pool = [trp for trp, _rv in training_by_type.get(label, []) if _type_name(trp) == label]
        team_vals = {n: [] for n in names}
        for trp in pool:
            f = _stuff_plus_features(trp, pv_map.get(trp.player_id))
            for n in names:
                if f.get(n) is not None:
                    team_vals[n].append(f[n])
        feats = []
        for n in names:
            contrib = mean(c.get(n, 0.0) for c in per_pitch)
            his_avg = mean(his_vals[n]) if his_vals[n] else None
            lab, unit, dec = FEATURE_LABELS.get(n, (n, "", 1))
            feats.append({
                "name": n, "label": lab, "unit": unit, "decimals": dec,
                "contrib": contrib, "value": his_avg,
                "team_avg": model["feature_baseline"][n][0],
                "pct": _percentile(his_avg, team_vals[n]),
                "weight": model["quality_weights"][n],
            })
        feats.sort(key=lambda d: -abs(d["contrib"]))
        out.append({
            "label": label, "n": len(per_pitch), "base": base,
            "stuff_plus": base + sum(d["contrib"] for d in feats),
            "features": feats, "team_values": team_vals, "his_values": his_vals,
            "enough": len(per_pitch) >= MIN_PITCHES_FOR_BREAKDOWN, "reason": None,
            "team_n": len(pool), "team_pitchers": len({trp.player_id for trp in pool}),
        })
    return out


def _outcome_rates(pitches):
    """{bucket: pitcher-side runs per 100 pitches}, total, n (pitches with run value)."""
    ps = [p for p in pitches if p.run_value is not None]
    n = len(ps)
    if not n:
        return None
    res = {}
    for bucket, outs in OUTCOME_BUCKETS:
        res[bucket] = -sum(float(p.run_value) for p in ps if p.pitch_outcome in outs) / n * 100.0
    res["_total"] = -sum(float(p.run_value) for p in ps) / n * 100.0
    res["_n"] = n
    res["_freq"] = {b: 100.0 * sum(1 for p in ps if p.pitch_outcome in outs) / n for b, outs in OUTCOME_BUCKETS}
    return res


def outcome_breakdown(game_pitches, team_game_pitches):
    """Per pitch type: his runs-saved/100 by outcome vs team for the same
    type. Positive gap = better than the team."""
    mine, team = {}, {}
    for p in game_pitches:
        if _type_name(p):
            mine.setdefault(_type_name(p), []).append(p)
    for p in team_game_pitches:
        if _type_name(p):
            team.setdefault(_type_name(p), []).append(p)
    out = {}
    for label, ps in mine.items():
        m = _outcome_rates(ps)
        t = _outcome_rates(team.get(label, []))
        if m is None or t is None:
            continue
        rows = []
        for bucket, _o in OUTCOME_BUCKETS:
            rows.append({"bucket": bucket, "his": m[bucket], "team": t[bucket], "gap": m[bucket] - t[bucket],
                         "his_freq": m["_freq"][bucket], "team_freq": t["_freq"][bucket]})
        out[label] = {"rows": rows, "his_total": m["_total"], "team_total": t["_total"],
                      "gap": m["_total"] - t["_total"], "n": m["_n"],
                      "enough": m["_n"] >= MIN_PITCHES_FOR_OUTCOMES}
    return out


def _fmt_val(f):
    if f["value"] is None:
        return ""
    return f"{f['value']:.{f['decimals']}f} {f['unit']}".replace(" %", "%").replace(" °", "°")


def _lc(label):
    return label.lower().replace("fb", "FB")


def why_line(entry, outcomes=None):
    """One plain-English sentence for the meeting report / profile."""
    if not entry or entry.get("stuff_plus") is None or not entry["features"]:
        return None
    feats = entry["features"]
    ups = [f for f in feats if f["contrib"] >= 1.0][:2]
    downs = [f for f in feats if f["contrib"] <= -1.0][:2]
    sp = entry["stuff_plus"]
    parts = []
    if ups:
        parts.append("helped by " + " and ".join(f"{_lc(f['label'])} ({f['contrib']:+.0f})" for f in ups))
    if downs:
        parts.append("held back by " + " and ".join(f"{_lc(f['label'])} ({f['contrib']:+.0f})" for f in downs))
    if not parts:
        parts.append("no single trait stands out from the team average")
    line = f"{entry['label']} {sp:.0f} Stuff+: " + "; ".join(parts) + "."
    o = (outcomes or {}).get(entry["label"])
    if o and o["enough"]:
        worst = min(o["rows"], key=lambda r: r["gap"])
        if sp >= 105 and o["gap"] < -0.5 and worst["gap"] < 0:
            line += f" Results lag the stuff -- most of it is {worst['bucket'].lower()}."
        elif sp <= 95 and o["gap"] > 0.5:
            line += " Plays better than its shape in games."
    return line


def get_for_pitcher(db, rapsodo_pitches, game_pitches):
    """Convenience: (breakdown list, outcomes dict). Team comparison uses
    every pitch our staff threw, all seasons."""
    from analytics.player_report import team_pitches
    models = profile_queries.team_stuff_plus_baselines(db)
    training = profile_queries.team_stuff_plus_training_pitches(db)
    breakdown = stuff_breakdown(rapsodo_pitches, models, training)
    outcomes = outcome_breakdown(game_pitches, team_pitches(db, None)) if game_pitches else {}
    return breakdown, outcomes
