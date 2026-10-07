"""
GBO -- Outcome profile by pitch shape (Oct 2026, from "Stuff or Not"
by Maloof & Haumacher: grade a pitch by what pitches SHAPED like it
actually do -- whiffs, called strikes, ground balls -- not by a run-value
number coaches have to translate).

For one of his pitch types: take its median shape (velo, IVB, arm-side
run), find the K most similar game pitches on our staff in the same
family (fastball / breaking / offspeed), from OTHER pitchers, that have
a Rapsodo reading linked to a charted result. Report their

  whiff %   whiffs / swings
  CSW %     (called strikes + whiffs) / pitches
  GB %      ground balls / balls in play

each pulled toward the family's staff rate by SHRINK pseudo-pitches so a
thin neighborhood doesn't swing wildly, next to that family's staff rate
and his own actual game rate. Similarity: distance on velo / VELO_SCALE,
IVB / MOVE_SCALE, run / MOVE_SCALE. No platoon split yet -- too few
linked pitches. "Early" until the family has more data.
"""

from statistics import median

from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES

K = 60
SHRINK = 20
VELO_SCALE = 2.0
MOVE_SCALE = 2.5
MIN_FAMILY = 40

FAMILY = {
    "4-Seam Fastball": "Fastballs", "Fastball": "Fastballs", "2-Seam Fastball": "Fastballs", "Sinker": "Fastballs",
    "Cutter": "Fastballs",
    "Slider": "Breaking balls", "Sweeper": "Breaking balls", "Slurve": "Breaking balls", "Curveball": "Breaking balls",
    "Knuckle Curve": "Breaking balls",
    "Changeup": "Offspeed", "Splitter": "Offspeed",
}


def _row(rap, gp, throws):
    if rap.velocity is None or rap.vb_spin is None or rap.hb_trajectory is None or rap.pitch_type is None:
        return None
    fam = FAMILY.get(rap.pitch_type.type_name)
    if fam is None:
        return None
    sgn = -1.0 if throws == "L" else 1.0
    return {"pid": rap.player_id, "fam": fam, "label": rap.pitch_type.type_name,
            "v": float(rap.velocity), "ivb": float(rap.vb_spin), "run": sgn * float(rap.hb_trajectory),
            "outcome": gp.pitch_outcome, "bb": gp.batted_ball_type}


def training_rows(pairs, throws_by_pid):
    """pairs: [(RapsodoPitch, GamePitch)]"""
    out = []
    for rap, gp in pairs:
        r = _row(rap, gp, throws_by_pid.get(rap.player_id))
        if r is not None and r["outcome"]:
            out.append(r)
    return out


def _rates(rows):
    n = len(rows)
    sw = [r for r in rows if r["outcome"] in SWING_OUTCOMES]
    wh = [r for r in rows if r["outcome"] in WHIFF_OUTCOMES]
    csw = [r for r in rows if r["outcome"] in ("Called Strike", "Swing and Miss")]
    bip = [r for r in rows if r["outcome"] == "In Play" and r["bb"]]
    gb = [r for r in bip if r["bb"] == "Ground Ball"]
    return {"whiff": (len(wh), len(sw)), "csw": (len(csw), n), "gb": (len(gb), len(bip))}


def _pct(num_den):
    a, b = num_den
    return 100.0 * a / b if b else None


def _shrunk(num_den, base_pct):
    a, b = num_den
    if base_pct is None:
        return _pct(num_den)
    return 100.0 * (a + SHRINK * base_pct / 100.0) / (b + SHRINK)


def profile(my_raps, my_game_rows, throws, train, my_pid):
    """my_raps: his RapsodoPitch rows (any source) -> shapes. my_game_rows: his
    training rows (his linked game pitches) for his actual rates.
    -> [{label, fam, n_shape, like: {whiff,csw,gb}, staff: {...}, his: {...}, his_n, k, early}]"""
    by = {}
    for p in my_raps:
        if p.pitch_type is None or p.velocity is None or p.vb_spin is None or p.hb_trajectory is None:
            continue
        by.setdefault(p.pitch_type.type_name, []).append(p)
    sgn = -1.0 if throws == "L" else 1.0
    out = []
    for lab, ps in sorted(by.items(), key=lambda kv: -len(kv[1])):
        fam = FAMILY.get(lab)
        if fam is None or len(ps) < 5:
            continue
        fam_rows = [r for r in train if r["fam"] == fam and r["pid"] != my_pid]
        if len(fam_rows) < MIN_FAMILY:
            out.append({"label": lab, "fam": fam, "early": True, "too_few": True, "fam_n": len(fam_rows)})
            continue
        v = median(float(p.velocity) for p in ps)
        ivb = median(float(p.vb_spin) for p in ps)
        run = median(sgn * float(p.hb_trajectory) for p in ps)

        def dist(r):
            return (((r["v"] - v) / VELO_SCALE) ** 2 + ((r["ivb"] - ivb) / MOVE_SCALE) ** 2
                    + ((r["run"] - run) / MOVE_SCALE) ** 2) ** 0.5
        near = sorted(fam_rows, key=dist)[:K]
        base = _rates(fam_rows)
        loc = _rates(near)
        mine = _rates([r for r in my_game_rows if r["label"] == lab])
        out.append({
            "label": lab, "fam": fam, "shape": (v, ivb, run), "k": len(near), "fam_n": len(fam_rows),
            "like": {k: _shrunk(loc[k], _pct(base[k])) for k in loc},
            "like_n": {k: loc[k][1] for k in loc},
            "staff": {k: _pct(base[k]) for k in base},
            "his": {k: _pct(mine[k]) for k in mine}, "his_n": {k: mine[k][1] for k in mine},
            "early": len(fam_rows) < 4 * K, "too_few": False,
        })
    return out
