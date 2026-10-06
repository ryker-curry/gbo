"""
GBO -- IVB over expected (Oct 2026).

Ryker sent a batch of pitching articles (Paradigm's VAA piece, Trafton
O'Brien's "Pitch Design, Advanced Metrics, and Undervalued Pitchers",
Columbia SABRLions' slider breakdown) and picked "IVB over expected" to
build. The idea in all three: ride (IVB) mostly follows arm slot -- a
higher slot gets more backspin on top, a lower slot gets more tilt and
run -- so raw IVB says as much about the slot as about the pitch. The
part that is UNUSUAL for his slot is what fools hitters:

    IVB over expected = IVB - expected IVB for his arm angle

  Expected IVB ~ estimated arm angle, one least-squares line per pitch
  type, fit on every Rapsodo reading the team has (same pattern as
  analytics/approach_angles.py's VAAA). Each pitcher's readings are
  weighted 1/n so a pitcher with 200 readings doesn't set the line by
  himself. Pitch types with fewer than MIN_FIT readings (or fewer than
  MIN_PITCHERS pitchers) fall back to a pooled line, flagged rough.

  The baseline is OUR staff, not a league -- say "vs our staff" on the
  page. On our data (Oct 2026) the 4-seam line is the strongest (r ~0.43,
  ~0.11" of IVB per degree of slot); breaking-ball lines are nearly
  flat, so for them the number reads as "vs our average slider".

INPUTS
  IVB = vb_spin (Rapsodo induced vertical break, in -- the Movement
  chart's IVB). Arm angle = bullpen_metrics._pitch_level_arm_angle
  (needs Player.height_in), clamped to ARM_CLAMP so a few release-side
  ~0 readings (arm angle ~90) can't swing the line.
"""

import numpy as np

from analytics.bullpen_metrics import _pitch_level_arm_angle, pitch_type_label

MIN_FIT = 40
MIN_PITCHERS = 4
ARM_CLAMP = (0.0, 75.0)
TYPICAL_IN = 1.5          # within +/- this many inches reads as "typical for his slot"
_cache = {"key": None, "model": None}


def _clamp(a):
    return max(ARM_CLAMP[0], min(ARM_CLAMP[1], a))


def _rows(pitches, players):
    """[{pitch, label, player_id, ivb, arm}] for readings with IVB and an arm angle."""
    out = []
    for p in pitches:
        if p.vb_spin is None:
            continue
        aa = _pitch_level_arm_angle(p, players.get(p.player_id))["value_degrees"]
        if aa is None:
            continue
        out.append({"pitch": p, "label": pitch_type_label(p), "player_id": p.player_id,
                    "ivb": float(p.vb_spin), "arm": _clamp(float(aa))})
    return out


def _fit(rows):
    counts = {}
    for r in rows:
        counts[r["player_id"]] = counts.get(r["player_id"], 0) + 1
    w = np.array([1.0 / counts[r["player_id"]] for r in rows])
    x = np.array([r["arm"] for r in rows])
    y = np.array([r["ivb"] for r in rows])
    X = np.column_stack([np.ones(len(y)), x])
    sw = np.sqrt(w)
    coef, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
    pred = X @ coef
    ybar = float(np.average(y, weights=w))
    ss_res = float((w * (y - pred) ** 2).sum())
    ss_tot = float((w * (y - ybar) ** 2).sum()) or 1.0
    return {"icpt": float(coef[0]), "slope": float(coef[1]), "n": len(rows), "pitchers": len(counts),
            "r2": round(1 - ss_res / ss_tot, 3)}


def fit_model(team_pitches, players):
    """{label: fit, "*": pooled fit}. players: {player_id: Player}."""
    rows = _rows(team_pitches, players)
    by = {}
    for r in rows:
        by.setdefault(r["label"], []).append(r)
    model = {}
    for label, rs in by.items():
        if len(rs) >= MIN_FIT and len({r["player_id"] for r in rs}) >= MIN_PITCHERS:
            model[label] = _fit(rs)
    if len(rows) >= MIN_FIT:
        model["*"] = _fit(rows)
    return model


def get_model(db):
    """Team model, refit only when the set of Rapsodo readings changes."""
    from models import RapsodoPitch, Player
    from sqlalchemy import func
    from sqlalchemy.orm import joinedload
    key = db.query(func.count(RapsodoPitch.rapsodo_pitch_id), func.max(RapsodoPitch.rapsodo_pitch_id)).one()
    key = (id(db.get_bind()), key[0], key[1])
    if _cache["key"] == key and _cache["model"] is not None:
        return _cache["model"]
    team = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.vb_spin.isnot(None)).all())
    players = {p.player_id: p for p in db.query(Player).all()}
    model = fit_model(team, players)
    _cache["key"], _cache["model"] = key, model
    return model


def expected(model, label, arm):
    fit = model.get(label) or model.get("*")
    if fit is None or arm is None:
        return None, False
    return fit["icpt"] + fit["slope"] * _clamp(arm), label not in model


def score_pitches(pitches, player, model):
    """Per-reading {pitch, label, ivb, arm, exp, over, pooled}."""
    out = []
    for r in _rows(pitches, {p.player_id: player for p in pitches}):
        exp, pooled = expected(model, r["label"], r["arm"])
        out.append({**r, "exp": exp, "over": (r["ivb"] - exp) if exp is not None else None, "pooled": pooled})
    return out


def describe(over, is_fastball):
    if over is None:
        return "—"
    if abs(over) < TYPICAL_IN:
        return "typical for his slot"
    if is_fastball:
        return "rides more than his slot (carry)" if over > 0 else "less ride than his slot (sink / run)"
    return "more carry than expected" if over > 0 else "more depth than expected"


def summary_by_type(scored, fastball_types):
    """Per pitch type: n, ivb, arm, exp, over, read, rough -- most-thrown first."""
    groups = {}
    for r in scored:
        if r["over"] is not None:
            groups.setdefault(r["label"], []).append(r)
    rows = []
    for label, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        ivb = sum(r["ivb"] for r in rs) / n
        exp = sum(r["exp"] for r in rs) / n
        over = ivb - exp
        rows.append({"label": label, "n": n, "ivb": ivb, "arm": sum(r["arm"] for r in rs) / n, "exp": exp,
                     "over": over, "read": describe(over, label in fastball_types),
                     "rough": any(r["pooled"] for r in rs)})
    return rows


def over_for_type(scored, label):
    vals = [r["over"] for r in scored if r["label"] == label and r["over"] is not None]
    return sum(vals) / len(vals) if vals else None
