"""
GBO -- VAAA and HAAAA: approach angles above expected (Oct 2026).

Ryker sent Paradigm Player Development's thread on HAAAA ("Horizontal
Approach Angle Above Average") and asked to "build both" -- HAAAA and its
vertical counterpart.

THE IDEA
  Raw approach angles mostly reflect context, not the pitch: where it
  crossed the plate, and (horizontally) where it was released -- a
  pitcher moves his raw HAA just by shifting on the rubber. So we predict
  the angle a pitch SHOULD have from its context, and the leftover is
  what's unusual about the pitch itself:
      VAAA  = observed VAA - expected VAA
      HAAAA = observed HAA - expected HAA

  Expected VAA  ~ plate height                       (per pitch type)
  Expected HAA  ~ horizontal plate location + release side
                                                     (per pitch type; lefties mirrored
                                                      into a righty's frame)
  Plain least-squares lines, fit on every Rapsodo reading the team has
  (bullpens and games -- the geometry is the same, and more data makes
  the lines steadier). Release HEIGHT is deliberately NOT in the VAA
  model: a low slot that makes a fastball flat is a real trait of the
  pitcher, the thing VAAA should show -- same as the standard industry
  VAAA, which adjusts for location only. Release SIDE is in the HAA model
  because Paradigm showed it's mostly rubber position (their fit: +0.09
  deg per inch of plate location, about -0.08 to -0.10 per inch of release
  side, R^2 0.97 across 3M+ D1 pitches).

  A group needs MIN_FIT readings for its own line; below that it falls
  back to a pooled line across all pitch types, flagged
  so the page can say the number is rougher.

SIGNS (shown everywhere)
  VAAA  + = flatter than expected for that height (fastballs up: good,
            "rides"); - = steeper (breaking balls: good, "drops").
  HAAAA uses Paradigm's convention so numbers compare to theirs:
        + = angle sharper toward a RIGHT-handed hitter than expected,
        - = sharper toward a LEFT-handed hitter.
        "toward same-handed hitter" = + for a RHP, - for a LHP.

INPUTS
  VAA/HAA are GBO's estimates (analytics/bullpen_metrics._pitch_level_vaa/
  _haa -- Rapsodo's own VAA export column is blank), so these inherit
  those estimates' caveats. _pitch_level_haa returns the angle in GBO's
  plate_x frame (+ = first-base side = toward a LHH), so it's negated
  here into Paradigm's frame (+ = toward a RHH).
"""

import numpy as np

from analytics.bullpen_metrics import _pitch_level_vaa, _pitch_level_haa, pitch_type_label

MIN_FIT = 60
_cache = {"key": None, "model": None}


def _rows(pitches, throws_by_player):
    """(label, throws, plate_x_in, plate_z_in, release_side_in, vaa, haa_p) per usable pitch."""
    out = []
    for p in pitches:
        label = pitch_type_label(p)
        if p.plate_x_ft is None or p.plate_z_ft is None:
            continue
        vaa = _pitch_level_vaa(p)["value_degrees"]
        haa = _pitch_level_haa(p)["value_degrees"]
        rs = -float(p.release_side) * 12 if p.release_side is not None else None  # GBO frame (+ = 1B side), inches
        out.append({
            "pitch": p, "label": label, "throws": throws_by_player.get(p.player_id),
            "x": float(p.plate_x_ft) * 12, "z": float(p.plate_z_ft) * 12, "rs": rs,
            "vaa": vaa, "haa": -haa if haa is not None else None,
        })
    return out


def _mirror(throws):
    return -1.0 if throws == "L" else 1.0


def _fit(X, y):
    X = np.column_stack([np.ones(len(y))] + [np.asarray(c, dtype=float) for c in X])
    coef, *_ = np.linalg.lstsq(X, np.asarray(y, dtype=float), rcond=None)
    pred = X @ coef
    ss_res = float(((np.asarray(y) - pred) ** 2).sum())
    ss_tot = float(((np.asarray(y) - np.mean(y)) ** 2).sum()) or 1.0
    return {"coef": coef.tolist(), "n": len(y), "r2": round(1 - ss_res / ss_tot, 3),
            "rmse": round((ss_res / len(y)) ** 0.5, 2)}


def fit_model(team_pitches, throws_by_player):
    rows = _rows(team_pitches, throws_by_player)
    vaa_rows = [r for r in rows if r["vaa"] is not None]
    haa_rows = [r for r in rows if r["haa"] is not None and r["rs"] is not None and r["throws"] in ("R", "L")]

    vaa = {}
    by_type = {}
    for r in vaa_rows:
        by_type.setdefault(r["label"], []).append(r)
    for label, rs in by_type.items():
        if len(rs) >= MIN_FIT:
            vaa[label] = _fit([[r["z"] for r in rs]], [r["vaa"] for r in rs])
    if len(vaa_rows) >= MIN_FIT:
        vaa["*"] = _fit([[r["z"] for r in vaa_rows]], [r["vaa"] for r in vaa_rows])

    # Lefties are mirrored into a righty's frame (flip the sign of plate
    # location, release side and HAA -- the geometry is symmetric), so
    # each pitch type gets one line from every pitcher instead of being
    # split thin by hand. Predictions are flipped back for lefties.
    haa = {}
    groups = {}
    for r in haa_rows:
        f = _mirror(r["throws"])
        rec = (f * r["x"], f * r["rs"], f * r["haa"])
        groups.setdefault(r["label"], []).append(rec)
        groups.setdefault("*", []).append(rec)
    for key, recs in groups.items():
        if len(recs) >= MIN_FIT:
            haa[key] = _fit([[a for a, _b, _c in recs], [b for _a, b, _c in recs]], [c for _a, _b, c in recs])
    return {"vaa": vaa, "haa": haa}


def get_model(db):
    """Team model, refit only when the set of Rapsodo readings changes."""
    from models import RapsodoPitch, Player
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    key = db.query(func.count(RapsodoPitch.rapsodo_pitch_id), func.max(RapsodoPitch.rapsodo_pitch_id)).one()
    key = (id(db.get_bind()), key[0], key[1])   # demo vs real never share (Oct 2026)
    if _cache["key"] == key and _cache["model"] is not None:
        return _cache["model"]
    team = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.plate_x_ft.isnot(None), RapsodoPitch.plate_z_ft.isnot(None)).all())
    throws = {pid: t for pid, t in db.query(Player.player_id, Player.throws).all()}
    model = fit_model(team, throws)
    _cache["key"], _cache["model"] = key, model
    return model


def _predict(fit, feats):
    c = fit["coef"]
    return c[0] + sum(ci * f for ci, f in zip(c[1:], feats))


def score_pitches(pitches, throws, model):
    """Per-pitch VAA/VAAA/HAA/HAAAA for one pitcher's readings. Each
    value None when its inputs or its model aren't available."""
    out = []
    for r in _rows(pitches, {p.player_id: throws for p in pitches}):
        rec = {"pitch": r["pitch"], "label": r["label"], "vaa": r["vaa"], "haa": r["haa"],
               "vaaa": None, "haaaa": None, "vaa_pooled": False, "haa_pooled": False}
        if r["vaa"] is not None:
            fit = model["vaa"].get(r["label"]) or model["vaa"].get("*")
            if fit:
                rec["exp_vaa"] = _predict(fit, [r["z"]])
                rec["vaaa"] = r["vaa"] - rec["exp_vaa"]
                rec["vaa_pooled"] = r["label"] not in model["vaa"]
        if r["haa"] is not None and r["rs"] is not None and throws in ("R", "L"):
            key = r["label"] if r["label"] in model["haa"] else ("*" if "*" in model["haa"] else None)
            if key:
                f = _mirror(throws)
                rec["exp_haa"] = f * _predict(model["haa"][key], [f * r["x"], f * r["rs"]])
                rec["haaaa"] = r["haa"] - rec["exp_haa"]
                rec["haa_pooled"] = key == "*"
        out.append(rec)
    return out


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


def describe_vaaa(v, is_fastball):
    if v is None:
        return "—"
    if abs(v) < 0.3:
        return "typical"
    if v > 0:
        return "flatter than expected" + (" (plays up in the zone)" if is_fastball else "")
    return "steeper than expected" + ("" if is_fastball else " (more drop)")


def describe_haaaa(v, throws):
    if v is None:
        return "—"
    if abs(v) < 0.3:
        return "typical"
    toward_rhh = v > 0
    same = (toward_rhh and throws == "R") or (not toward_rhh and throws == "L")
    return f"sharper toward {'RHH' if toward_rhh else 'LHH'} ({'same' if same else 'opposite'}-handed)"


def summary_by_type(scored, throws, fastball_types):
    groups = {}
    for r in scored:
        groups.setdefault(r["label"], []).append(r)
    rows = []
    for label, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        vaa, _ = _mean(r["vaa"] for r in rs)
        vaaa, nv = _mean(r["vaaa"] for r in rs)
        haa, _ = _mean(r["haa"] for r in rs)
        haaaa, nh = _mean(r["haaaa"] for r in rs)
        rows.append({
            "label": label, "n": len(rs), "vaa": vaa, "vaaa": vaaa, "n_vaaa": nv,
            "haa": haa, "haaaa": haaaa, "n_haaaa": nh,
            "rough": any(r["vaa_pooled"] or r["haa_pooled"] for r in rs),
            "vaaa_text": describe_vaaa(vaaa, label in fastball_types),
            "haaaa_text": describe_haaaa(haaaa, throws),
        })
    return rows


# ---------------------------------------------------------------------------
# "How to use it" (Oct 2026, Ryker: numbers alone don't help pitch calling --
# turn each pitch's angles into a plain call-sheet line).
#
# STARTING POINTS, not proven on our data: the horizontal lines follow
# Paradigm's 2026 D1 findings (fastballs angled toward a same-handed hitter
# drew more swings inside / fewer away; RHP sliders angled toward a RHH drew
# more whiffs everywhere); the vertical lines follow the well-known VAA
# patterns (flat fastballs play up, steep breaking balls play down). The
# page labels them that way.
# ---------------------------------------------------------------------------

TIP_MIN_DEG = 0.3
TIP_MIN_N = 8
_FB_FOR_TIPS = {"4-Seam Fastball", "Fastball", "Cutter"}
_SINKERS = {"2-Seam Fastball", "Sinker"}
_BREAKING = {"Slider", "Sweeper", "Curveball", "Slurve", "Knuckle Curve"}
_OFFSPEED = {"Changeup", "Splitter"}


def usage_tips(row, throws):
    """Plain-English call-sheet lines for one summary_by_type() row."""
    label = row["label"]
    if row["n_vaaa"] < TIP_MIN_N and row["n_haaaa"] < TIP_MIN_N:
        return [f"Not enough tracked pitches yet ({row['n']}) -- needs {TIP_MIN_N}+ with location to say."]
    same = "RHH" if throws == "R" else "LHH"
    opp = "LHH" if throws == "R" else "RHH"
    tips = []

    v = row["vaaa"] if row["n_vaaa"] >= TIP_MIN_N else None
    if v is not None and abs(v) >= TIP_MIN_DEG:
        if label in _FB_FOR_TIPS:
            tips.append("Flatter than expected -- plays up in the zone. Elevate it, especially with 2 strikes."
                        if v > 0 else
                        "Steeper than expected -- easier to square up high. Keep it at the belt or below, or pair it with sink.")
        elif label in _SINKERS:
            tips.append("Steeper than expected -- good sink. Live at the knees for ground balls."
                        if v < 0 else
                        "Flatter than expected for a sinker -- it won't drop much. Keep it down; up in the zone it flattens out.")
        elif label in _BREAKING or label in _OFFSPEED:
            tips.append("Steeper than expected -- bury it at the knees or below. It looks like a strike longer."
                        if v < 0 else
                        "Flatter than expected -- less drop than it looks. Use it to steal strikes early, not as a chase pitch.")

    h = row["haaaa"] if row["n_haaaa"] >= TIP_MIN_N else None
    if h is not None and abs(h) >= TIP_MIN_DEG:
        toward_same = (h > 0) == (throws == "R")
        if label in _FB_FOR_TIPS or label in _SINKERS:
            tips.append(f"Angles in on {same} more than expected -- {same} swing more on the inner third and take more "
                        f"away. Go in to get swings, away to steal strikes."
                        if toward_same else
                        f"Angles away from {same} more than expected -- {same} swing at it more on the outer third. "
                        f"Work away to {same}; in on {opp} it gets to their hands.")
        elif label in _BREAKING:
            tips.append(f"Angles at {same} more than expected -- best vs {same}. Start it at their hip and let it sweep; "
                        f"more whiffs across the plate."
                        if toward_same else
                        f"Less angle at {same} than a typical {label.lower()} -- vs {same} bury it below the zone; "
                        f"can steal a backdoor strike vs {opp}.")
        elif label in _OFFSPEED:
            tips.append(f"Fades away from {opp} more than expected -- go low and away to {opp}."
                        if toward_same else
                        f"Angles toward {opp}'s hands more than expected -- keep it down, and lean on it more vs {same} away.")

    if not tips:
        tips.append("Typical angles for where it's thrown -- call it on movement and location; the angle doesn't add an edge.")
    return tips
