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

OFF-SPEED CHECK (Oct 2026, Ryker: Shane Holman's changeups/curveballs/
sliders were all charted as 4-seams -- "shouldve flagged some based on
rapsodo readings"). Runs FIRST, before the 4-seam/2-seam check, and asks
"is this a fastball at all?":
  1. His fastball reference = the pitches labeled fastball that sit at
     the top of his velocity range (within FB_BAND_MPH of his 90th
     percentile fastball-labeled velo). Median velo / IVB / run of those.
     Built from the hard ones only, so a pile of off-speed pitches
     mislabeled as 4-seams can't drag the reference down.
  2. A fastball-labeled pitch is flagged as off-speed when it's
     OFFSPEED_VELO_GAP+ mph under his fastball, or (any velo) it moves
     BREAK_RUN_GAP+ inches more glove-side AND BREAK_IVB_GAP+ inches less
     ride than his fastball.
  3. Suggested type = the nearest off-speed shape. Each candidate's shape
     is HIS OWN median for that type when he has MIN_OFFSPEED_GROUP+
     readings already labeled it; otherwise a starting guideline relative
     to his fastball (OFFSPEED_GUIDES). Candidates = his active arsenal's
     off-speed pitches when one is set up in GBO, else Changeup / Slider
     / Curveball (+ any off-speed type he already has readings of).
  Pitches flagged here are left out of the 4-seam/2-seam check (and its
  group centers) so they can't skew it.
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

# Off-speed check
FASTBALL_TYPES = (FOUR_SEAM, TWO_SEAM, GENERIC)
OFFSPEED_TYPES = ("Changeup", "Splitter", "Slider", "Curveball", "Cutter")
MIN_FB_REFERENCE = 5       # fastball-labeled readings with velo needed for a reference
FB_BAND_MPH = 3.0          # "his fastball" = within this of his 90th-pct FB-labeled velo
OFFSPEED_VELO_GAP = 5.0    # mph under his fastball -> not a fastball
BREAK_RUN_GAP = 10.0       # in more glove-side than his fastball ...
BREAK_IVB_GAP = 6.0        # ... and this much less ride -> not a fastball
MIN_OFFSPEED_GROUP = 5     # his own labeled readings needed to use his own shape
DEFAULT_OFFSPEED = ("Changeup", "Slider", "Curveball")
# Starting shapes relative to his fastball: (ride vs FB, arm-side run vs FB,
# mph under FB). Meant to be tuned.
OFFSPEED_GUIDES = {
    "Changeup":  (-7.0,   1.0,  8.0),
    "Splitter":  (-12.0, -2.0,  8.0),
    "Cutter":    (-6.0,  -9.0,  3.5),
    "Slider":    (-14.0, -14.0, 8.0),
    "Curveball": (-24.0, -14.0, 13.0),
}
OS_IVB_SCALE, OS_RUN_SCALE, OS_VELO_SCALE = 3.0, 3.0, 2.5


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



def _pct(vals, q):
    vals = sorted(vals)
    if not vals:
        return None
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def fastball_reference(fb_feats):
    """(ivb, run, velo) of his real fastball from fastball-labeled
    readings, using only the hard ones. None if too few with velo."""
    with_velo = [f for f in fb_feats if f[2] is not None]
    if len(with_velo) < MIN_FB_REFERENCE:
        return None
    top = _pct([f[2] for f in with_velo], 0.9)
    band = [f for f in with_velo if f[2] >= top - FB_BAND_MPH]
    return (median(f[0] for f in band), median(f[1] for f in band), median(f[2] for f in band))


def _offspeed_shapes(fb_ref, labeled_feats, arsenal):
    """{type: (ivb, run, velo)} for the off-speed types he could be
    throwing, and {type: "his"|"guide"} saying where each came from."""
    if arsenal:
        cands = [t for t in arsenal if t in OFFSPEED_TYPES]
    else:
        cands = list(DEFAULT_OFFSPEED) + [
            t for t in OFFSPEED_TYPES if t not in DEFAULT_OFFSPEED and labeled_feats.get(t)
        ]
    shapes, source = {}, {}
    for t in cands:
        own = labeled_feats.get(t) or []
        if len(own) >= MIN_OFFSPEED_GROUP:
            shapes[t] = _center(own)
            source[t] = "his"
        elif t in OFFSPEED_GUIDES:
            d_ivb, d_run, gap = OFFSPEED_GUIDES[t]
            shapes[t] = (fb_ref[0] + d_ivb, fb_ref[1] + d_run, fb_ref[2] - gap)
            source[t] = "guide"
    return shapes, source


def _os_distance(feat, shape):
    d = ((feat[0] - shape[0]) / OS_IVB_SCALE) ** 2 + ((feat[1] - shape[1]) / OS_RUN_SCALE) ** 2
    if feat[2] is not None and shape[2] is not None:
        d += ((feat[2] - shape[2]) / OS_VELO_SCALE) ** 2
    return d ** 0.5


def offspeed_call(feat, fb_ref):
    """Why this fastball-labeled pitch isn't a fastball, or None."""
    ivb, run, velo = feat
    if velo is not None and fb_ref[2] - velo >= OFFSPEED_VELO_GAP:
        return f"{fb_ref[2] - velo:.1f} mph under his fastball ({fb_ref[2]:.1f})"
    if fb_ref[1] - run >= BREAK_RUN_GAP and fb_ref[0] - ivb >= BREAK_IVB_GAP:
        return (f"{fb_ref[1] - run:.1f}\" more glove-side and {fb_ref[0] - ivb:.1f}\" less ride "
                f"than his fastball")
    return None


def check_pitcher(pitches, throws, arsenal=None):
    """pitches: this pitcher's RapsodoPitch rows (any types -- only
    fastballs are looked at). throws: 'R'/'L'.

    Returns {
      "mode": "per_pitcher" | "guidelines" | "none",
      "centers": {FOUR_SEAM: (ivb, run, velo), TWO_SEAM: ...} (per-pitcher mode),
      "counts": {type: n},
      "flags": [ {pitch, labeled, suggested, ivb, run, velo, reason, kind} ... ],
      "points": [ {pitch, labeled, ivb, run, velo, flagged} ... ]  (for the chart)
    }
    kind: "mismatch" (labeled 4S/2S but fits the other),
          "unlabeled" (plain "Fastball" with a suggested type), or
          "offspeed" (labeled a fastball but throws/moves like an
          off-speed pitch -- see OFF-SPEED CHECK above).
    arsenal: optional list of his active arsenal's pitch type names
    (limits which off-speed types can be suggested).
    Also returns "fb_ref" (ivb, run, velo) and "offspeed_sources"."""
    rows = []
    labeled_os = {}
    for p in pitches:
        label = _type_name(p)
        feat = features(p, throws)
        if feat is None:
            continue
        if label in OFFSPEED_TYPES:
            labeled_os.setdefault(label, []).append(feat)
        if label not in CHECKED_TYPES:
            continue
        rows.append((p, label, feat))

    # Off-speed pass: pull out fastball-labeled pitches that aren't fastballs.
    fb_ref = fastball_reference([f for _p, _l, f in rows])
    os_flags, os_sources = [], {}
    if fb_ref is not None:
        shapes, os_sources = _offspeed_shapes(fb_ref, labeled_os, arsenal)
        kept = []
        for p, label, feat in rows:
            why = offspeed_call(feat, fb_ref) if shapes else None
            if why is None:
                kept.append((p, label, feat))
                continue
            best = min(shapes, key=lambda t: _os_distance(feat, shapes[t]))
            ivb, run, velo = feat
            velo_txt = f"{velo:.1f} mph, " if velo is not None else ""
            os_flags.append({
                "pitch": p, "labeled": label, "suggested": best,
                "ivb": ivb, "run": run, "velo": velo, "kind": "offspeed",
                "reason": (f"Not a fastball: {why}. {velo_txt}{ivb:.1f}\" ride / {run:.1f}\" run is closest to "
                           f"{'his' if os_sources.get(best) == 'his' else 'a typical'} {best.lower()}"),
            })
        rows = kept

    counts = {}
    for _p, label, _f_ in rows:
        counts[label] = counts.get(label, 0) + 1
    for f in os_flags:
        counts[f["labeled"]] = counts.get(f["labeled"], 0) + 1
    result = {"mode": "none", "centers": {}, "counts": counts, "flags": list(os_flags), "points": [],
              "fb_ref": fb_ref, "offspeed_sources": os_sources}
    for f in os_flags:
        result["points"].append({"pitch": f["pitch"], "labeled": f["labeled"], "ivb": f["ivb"],
                                 "run": f["run"], "velo": f["velo"], "flagged": True,
                                 "offspeed": f["suggested"]})
    if not rows:
        if os_flags:
            result["mode"] = "guidelines"
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
    os_ids = {f["pitch"].rapsodo_pitch_id for f in os_flags}
    for pt in result["points"]:
        pt["flagged"] = pt["pitch"].rapsodo_pitch_id in flagged_ids or pt["pitch"].rapsodo_pitch_id in os_ids
    return result
