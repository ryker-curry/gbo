"""
GBO -- Fastball Shape Check (Oct 2026).

Ryker: "build this into the website. fastball shape check. if it fits
the other type then we can switch it." Context from the same
conversation: pitches are LOGGED BY GRIP (the pitcher's own name for
the pitch -- same as MLB, where each pitch "is classified as the
pitcher himself calls it"), and the Rapsodo movement data is the check
on that label. This module only finds and explains mismatches; it never
changes anything (services/pitch_type_switch.py does the switching,
after a coach confirms each pitch).

Decisions agreed with Ryker (AskUserQuestion, Oct 2026):
  - Compare each pitcher against HIS OWN pitches (per-pitcher, like
    MLB's per-pitcher classifiers), falling back to general shape
    guidelines when he doesn't throw enough of both fastballs.
  - Review list, then switch -- nothing changes until confirmed.
  - A switch updates the Rapsodo reading AND its matched game pitch,
    logged so it can be undone.
  - Lives on Pitcher Profile (its own View) + a heads-up after a
    Rapsodo import.

WHAT'S CHECKED
  RapsodoPitch rows labeled 4-Seam Fastball, 2-Seam Fastball, or plain
  "Fastball" (unspecified -- these get a suggested type, never a
  mismatch flag). Three features per pitch:
    IVB  = vb_spin (spin-induced vertical break, in -- the Movement
           chart's own IVB)
    Run  = hb_spin flipped to ARM SIDE (Rapsodo reports + = pitcher's
           right, see rapsodo_conventions.py, so a LHP's arm-side run is
           negative raw -> multiplied by -1)
    Velo = velocity (mph), weighted half -- a 2-seam usually sits 1-2
           mph under the 4-seam but velo alone shouldn't decide it.

PER-PITCHER MODE (he has MIN_GROUP+ readings labeled 4-seam AND
2-seam): each group's center is its MEDIAN (so a handful of mislabeled
pitches can't drag the center toward the wrong group). Distance to each
center is in scaled units (IVB_SCALE / RUN_SCALE inches, VELO_SCALE
mph). A pitch is flagged when it's closer to the OTHER group by at
least MARGIN units. If his two group centers are themselves too close
together (< MIN_SEPARATION -- his 4-seam and 2-seam basically move the
same), per-pitcher mode is skipped and the guidelines are used instead.

GUIDELINE MODE (otherwise): GBO starting guidelines, meant to be tuned
--
    looks like a 4-seam: IVB >= GUIDE_4S_MIN_IVB and IVB exceeds arm-side
                         run by GUIDE_4S_RIDE_OVER_RUN+
    looks like a 2-seam: arm-side run exceeds IVB by GUIDE_2S_RUN_OVER_RIDE+
                         and IVB <= GUIDE_2S_MAX_IVB
  Anything in between gets no call (not flagged).
"""

from statistics import median

FOUR_SEAM = "4-Seam Fastball"
TWO_SEAM = "2-Seam Fastball"
GENERIC = "Fastball"
CHECKED_TYPES = (FOUR_SEAM, TWO_SEAM, GENERIC)

MIN_GROUP = 10
IVB_SCALE = 2.0      # inches per unit
RUN_SCALE = 2.0      # inches per unit
VELO_SCALE = 1.5     # mph per unit
VELO_WEIGHT = 0.5
MARGIN = 1.0         # must be this many units closer to the other group
MIN_SEPARATION = 1.5 # units between his own 4S and 2S centers

GUIDE_4S_MIN_IVB = 14.0
GUIDE_4S_RIDE_OVER_RUN = 4.0
GUIDE_2S_MAX_IVB = 13.0
GUIDE_2S_RUN_OVER_RIDE = 2.0


def _f(v):
    return float(v) if v is not None else None


def features(pitch, throws):
    """(ivb, arm_side_run, velo) or None if movement is missing."""
    ivb, hb = _f(pitch.vb_spin), _f(pitch.hb_spin)
    if ivb is None or hb is None:
        return None
    run = hb if throws != "L" else -hb
    return ivb, run, _f(pitch.velocity)


def _type_name(pitch):
    return pitch.pitch_type.type_name if getattr(pitch, "pitch_type", None) is not None else None


def _center(feats):
    return (
        median(f[0] for f in feats),
        median(f[1] for f in feats),
        median(f[2] for f in feats if f[2] is not None) if any(f[2] is not None for f in feats) else None,
    )


def _distance(feat, center):
    d = ((feat[0] - center[0]) / IVB_SCALE) ** 2 + ((feat[1] - center[1]) / RUN_SCALE) ** 2
    if feat[2] is not None and center[2] is not None:
        d += (VELO_WEIGHT * (feat[2] - center[2]) / VELO_SCALE) ** 2
    return d ** 0.5


def guideline_call(feat):
    ivb, run, _velo = feat
    if ivb >= GUIDE_4S_MIN_IVB and ivb - run >= GUIDE_4S_RIDE_OVER_RUN:
        return FOUR_SEAM
    if run - ivb >= GUIDE_2S_RUN_OVER_RIDE and ivb <= GUIDE_2S_MAX_IVB:
        return TWO_SEAM
    return None


def check_pitcher(pitches, throws):
    """pitches: this pitcher's RapsodoPitch rows (any types -- only
    fastballs are looked at). throws: 'R'/'L'.

    Returns {
      "mode": "per_pitcher" | "guidelines" | "none",
      "centers": {FOUR_SEAM: (ivb, run, velo), TWO_SEAM: ...} (per-pitcher mode),
      "counts": {type: n},
      "flags": [ {pitch, labeled, suggested, ivb, run, velo, reason, kind} ... ],
      "points": [ {pitch, labeled, ivb, run, velo, flagged} ... ]  (for the chart)
    }
    kind: "mismatch" (labeled 4S/2S but fits the other) or
          "unlabeled" (plain "Fastball" with a suggested type)."""
    rows = []
    for p in pitches:
        label = _type_name(p)
        if label not in CHECKED_TYPES:
            continue
        feat = features(p, throws)
        if feat is None:
            continue
        rows.append((p, label, feat))

    counts = {}
    for _p, label, _f_ in rows:
        counts[label] = counts.get(label, 0) + 1
    result = {"mode": "none", "centers": {}, "counts": counts, "flags": [], "points": []}
    if not rows:
        return result

    groups = {t: [f for _p, l, f in rows if l == t] for t in (FOUR_SEAM, TWO_SEAM)}
    centers = {}
    if len(groups[FOUR_SEAM]) >= MIN_GROUP and len(groups[TWO_SEAM]) >= MIN_GROUP:
        centers = {t: _center(groups[t]) for t in (FOUR_SEAM, TWO_SEAM)}
        sep = _distance(centers[FOUR_SEAM], centers[TWO_SEAM])
        if sep < MIN_SEPARATION:
            centers = {}
    result["mode"] = "per_pitcher" if centers else "guidelines"
    result["centers"] = centers

    flagged_ids = set()
    for p, label, feat in rows:
        ivb, run, velo = feat
        suggested, reason = None, None
        if centers:
            d4 = _distance(feat, centers[FOUR_SEAM])
            d2 = _distance(feat, centers[TWO_SEAM])
            closer = FOUR_SEAM if d4 < d2 else TWO_SEAM
            c = centers[closer]
            if label == GENERIC or (label != closer and abs(d4 - d2) >= MARGIN):
                suggested = closer
                reason = (f"Moves like his {'4-seam' if closer == FOUR_SEAM else '2-seam'}: "
                          f"{ivb:.1f}\" ride / {run:.1f}\" run vs. his "
                          f"{'4-seam' if closer == FOUR_SEAM else '2-seam'} avg {c[0]:.1f}\" / {c[1]:.1f}\"")
        else:
            call = guideline_call(feat)
            if call is not None and (label == GENERIC or call != label):
                suggested = call
                reason = (f"{ivb:.1f}\" ride / {run:.1f}\" arm-side run reads as a "
                          f"{'4-seam (ride well over run)' if call == FOUR_SEAM else '2-seam (run over ride)'} "
                          f"-- general guideline, he doesn't throw enough of both to compare to himself")
        if suggested is not None and suggested != label:
            flagged_ids.add(p.rapsodo_pitch_id)
            result["flags"].append({
                "pitch": p, "labeled": label, "suggested": suggested,
                "ivb": ivb, "run": run, "velo": velo, "reason": reason,
                "kind": "unlabeled" if label == GENERIC else "mismatch",
            })
        result["points"].append({"pitch": p, "labeled": label, "ivb": ivb, "run": run, "velo": velo})
    for pt in result["points"]:
        pt["flagged"] = pt["pitch"].rapsodo_pitch_id in flagged_ids
    return result
