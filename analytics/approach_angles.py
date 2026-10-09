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


# ---------------------------------------------------------------------------
# Staff extremes + rubber moves (Oct 2026, Ryker sent Paradigm's "The Angle
# Advantage": flag each pitch's top / bottom 10% angles with a one-line cue,
# and "before rebuilding a pitch, try a rubber-position change first").
# ---------------------------------------------------------------------------

EXTREME_PCT = 0.10
EXTREME_MIN_PITCHERS = 8
RUBBER_SHIFT_IN = 3.0
RUBBER_MIN_OUTING = 10
RUBBER_SIDE_OUTINGS = 3
_staff_cache = {"key": None, "data": None}
_FB_ALL = _FB_FOR_TIPS | _SINKERS


def staff_profiles(db):
    """{pid: {label: {"vaaa", "haaaa", "n_v", "n_h"}}} for every active pitcher,
    from all of his Rapsodo readings (cached with the model)."""
    from models import RapsodoPitch, Player
    from sqlalchemy.orm import joinedload
    model = get_model(db)
    if _staff_cache["key"] == _cache["key"] and _staff_cache["data"] is not None:
        return _staff_cache["data"]
    players = {p.player_id: p for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all()}
    raps = {}
    for r in (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
              .filter(RapsodoPitch.player_id.in_(list(players)), RapsodoPitch.plate_x_ft.isnot(None)).all()):
        raps.setdefault(r.player_id, []).append(r)
    out = {}
    for pid, rs in raps.items():
        prof = {}
        for row in summary_by_type(score_pitches(rs, players[pid].throws, model), players[pid].throws, _FB_ALL):
            prof[row["label"]] = {"vaaa": row["vaaa"], "haaaa": row["haaaa"], "n_v": row["n_vaaa"], "n_h": row["n_haaaa"]}
        out[pid] = prof
    data = {"profiles": out, "throws": {pid: p.throws for pid, p in players.items()}}
    _staff_cache["key"], _staff_cache["data"] = _cache["key"], data
    return data


def _arm_side(haaaa, throws):
    """HAAAA re-signed so + = toward the pitcher's arm side (same-handed hitter) for either hand."""
    return haaaa if throws == "R" else -haaaa


def _cue(label, kind):
    fb, sink = label in _FB_FOR_TIPS, label in _SINKERS
    brk_off = label in _BREAKING or label in _OFFSPEED
    return {
        ("flat", True): "live at the top of the zone -- the flat angle plays up there",
        ("steep", True): "work the lower third and finish below the zone",
        ("steep", False): "bury it below the zone for whiffs" if brk_off else "keep it at the knees",
        ("flat", False): "less drop than it looks -- steal strikes early, not a chase pitch",
        ("arm", True): "inside lane: go in on same-side hitters for swings",
        ("arm", False): "inside lane: start it at the inner third" if brk_off else "fade it in on same-side hitters",
        ("glove", True): "away lane: work away to same-side hitters",
        ("glove", False): "away lane: finish it away -- more chases off the plate",
    }[(kind, fb or sink)]


def staff_extremes(data, pct=EXTREME_PCT, min_pitchers=EXTREME_MIN_PITCHERS):
    """{pid: [{"label", "kind", "value", "rank", "of", "text"}]} -- each pitch in the top / bottom
    pct of OUR staff (same pitch type, TIP_MIN_N+ readings) for VAAA and arm-side HAAAA."""
    out = {}
    labels = {l for prof in data["profiles"].values() for l in prof}
    for label in labels:
        for metric, kinds in (("vaaa", ("flat", "steep")), ("haaaa", ("arm", "glove"))):
            vals = []
            for pid, prof in data["profiles"].items():
                r = prof.get(label)
                n = (r or {}).get("n_v" if metric == "vaaa" else "n_h", 0)
                v = (r or {}).get(metric)
                if v is None or n < TIP_MIN_N:
                    continue
                if metric == "haaaa":
                    v = _arm_side(v, data["throws"].get(pid))
                vals.append((v, pid))
            if len(vals) < min_pitchers:
                continue
            vals.sort(reverse=True)
            k = max(1, int(round(pct * len(vals))))
            for side, chunk in ((kinds[0], vals[:k]), (kinds[1], vals[-k:])):
                for v, pid in chunk:
                    if abs(v) < TIP_MIN_DEG or (v > 0) != (side == kinds[0]):
                        continue                      # extreme for us but not unusual (or wrong sign) -- skip
                    rank = vals.index((v, pid)) + 1 if side == kinds[0] else len(vals) - vals.index((v, pid))
                    word = {"flat": "flattest", "steep": "steepest", "arm": "most arm-side angle",
                            "glove": "most glove-side angle"}[side]
                    unit = "VAAA" if metric == "vaaa" else "HAAAA (arm side +)"
                    out.setdefault(pid, []).append({
                        "label": label, "kind": side, "value": v, "rank": rank, "of": len(vals),
                        "text": (f"{label}: {'top' if rank == 1 else f'#{rank}'} {word} on staff "
                                 f"({v:+.1f}° {unit}, of {len(vals)}) -- {_cue(label, side)}")})
    return out


def _outing_key(p):
    return ("bp", p.bullpen_id) if p.bullpen_id is not None else ("imp", p.import_id)


def rubber_moves(raps, throws, model, game_pitches=None):
    """Release-side shifts of RUBBER_SHIFT_IN+ inches between consecutive outings
    (median release side, all pitches). For each: release side, HAAAA by pitch
    type and (when game_pitches given) game whiff / chase by pitch type for the
    RUBBER_SIDE_OUTINGS outings before vs from the move on.
    -> [{"date", "from_in", "to_in", "toward", "by_type": [...], "n_before", "n_after"}]"""
    from statistics import median
    scored = {id(r["pitch"]): r for r in score_pitches(raps, throws, model)}
    outs = {}
    for p in raps:
        if p.release_side is None or p.pitch_date is None:
            continue
        outs.setdefault(_outing_key(p), []).append(p)
    seq = []
    for key, ps in outs.items():
        if len(ps) < RUBBER_MIN_OUTING:
            continue
        side = median(-float(p.release_side) * 12 for p in ps)        # GBO frame: + = 1B side, inches
        seq.append((min(p.pitch_date for p in ps), side, ps))
    seq.sort(key=lambda t: t[0])
    moves = []
    for i in range(1, len(seq)):
        d = seq[i][1] - seq[i - 1][1]
        if abs(d) < RUBBER_SHIFT_IN:
            continue
        before = seq[max(0, i - RUBBER_SIDE_OUTINGS):i]
        after = seq[i:i + RUBBER_SIDE_OUTINGS]
        day = seq[i][0].date() if hasattr(seq[i][0], "date") else seq[i][0]
        moves.append({"date": day, "from_in": sum(s for _d, s, _p in before) / len(before),
                      "to_in": sum(s for _d, s, _p in after) / len(after),
                      "toward": "1B side" if d > 0 else "3B side",
                      "by_type": _move_by_type([p for _d, _s, ps in before for p in ps],
                                               [p for _d, _s, ps in after for p in ps], scored, throws,
                                               game_pitches, day, seq[i - 1][0], (seq[i + RUBBER_SIDE_OUTINGS][0]
                                                                                  if i + RUBBER_SIDE_OUTINGS < len(seq) else None)),
                      "n_before": len(before), "n_after": len(after)})
    return moves


def _game_rates(gps):
    from plate_discipline import SWING_OUTCOMES
    import strike_zone as sz
    sw = [g for g in gps if g.pitch_outcome in SWING_OUTCOMES]
    out_zone = [g for g in gps if g.actual_plate_x is not None and g.actual_plate_z is not None
                and not sz.is_in_zone(float(g.actual_plate_x), float(g.actual_plate_z))]
    whiff = 100 * sum(g.pitch_outcome == "Swing and Miss" for g in sw) / len(sw) if len(sw) >= 5 else None
    chase = 100 * sum(g.pitch_outcome in SWING_OUTCOMES for g in out_zone) / len(out_zone) if len(out_zone) >= 5 else None
    return whiff, chase, len(gps)


def _move_by_type(before, after, scored, throws, game_pitches, day, start, end):
    rows = []
    labels = sorted({pitch_type_label(p) for p in before + after})
    for label in labels:
        hb = [scored[id(p)]["haaaa"] for p in before if pitch_type_label(p) == label and id(p) in scored
              and scored[id(p)]["haaaa"] is not None]
        ha = [scored[id(p)]["haaaa"] for p in after if pitch_type_label(p) == label and id(p) in scored
              and scored[id(p)]["haaaa"] is not None]
        if len(hb) < 5 or len(ha) < 5:
            continue
        row = {"label": label, "haaaa_before": _arm_side(sum(hb) / len(hb), throws),
               "haaaa_after": _arm_side(sum(ha) / len(ha), throws), "n_before": len(hb), "n_after": len(ha)}
        if game_pitches is not None:
            def lab(g):
                return g.pitch_type.type_name if g.pitch_type is not None else None
            gd = lambda g: g.game.game_date if getattr(g, "game", None) is not None else None
            gb = [g for g in game_pitches if lab(g) == label and gd(g) and start.date() <= gd(g) < day] \
                if hasattr(start, "date") else []
            ga = [g for g in game_pitches if lab(g) == label and gd(g) and gd(g) >= day
                  and (end is None or gd(g) < (end.date() if hasattr(end, "date") else end))]
            row["game_before"], row["game_after"] = _game_rates(gb), _game_rates(ga)
        rows.append(row)
    return rows


def digit_angles(profile, digit_of):
    """Collapse a pitcher's per-label profile to {digit: (vaaa, haaaa)} weighted by readings
    (for the Pitch Calling Card, whose pitch digits merge e.g. 4-seam + 2-seam)."""
    acc = {}
    for label, r in (profile or {}).items():
        d = digit_of.get(label)
        if d is None:
            continue
        a = acc.setdefault(d, [0.0, 0, 0.0, 0])
        if r["vaaa"] is not None and r["n_v"]:
            a[0] += r["vaaa"] * r["n_v"]
            a[1] += r["n_v"]
        if r["haaaa"] is not None and r["n_h"]:
            a[2] += r["haaaa"] * r["n_h"]
            a[3] += r["n_h"]
    return {d: (a[0] / a[1] if a[1] >= TIP_MIN_N else None, a[2] / a[3] if a[3] >= TIP_MIN_N else None)
            for d, a in acc.items()}
