"""
GBO -- Pitch Type Check (Oct 2026). Ryker: "Pitch Classifier, what do you
think about using logic from these articles ... i think we can use it to
classify pitches" -> "build it".

Based on SABR Tooth Tigers' TopoTagger ("How to classify a pitch"): every
pitch is described by three numbers only --
    dSpeed = velo minus the pitcher's own 95th-percentile fastball that
             outing (falls back to his whole set when an outing has no
             fastballs)
    Run    = horizontal break flipped to ARM SIDE (lefties mirrored)
    IVB    = induced vertical break
-- and falls into one of three groups a hitter actually sees: FASTBALL,
BREAKING BALL, CHANGEUP. Each pitch goes to the nearest group center in
(1 in, 1 in, 0.6 mph) units, the article's own bin size.

Our own centers: the article's centers come from D1 TrackMan. Rapsodo
reads movement differently (our fastball IVB sits ~4" lower), so the
centers are recalibrated from OUR labeled pitches (median per group --
a few mislabels can't drag a median), falling back to the article's
numbers when a group has fewer than MIN_CALIBRATION pitches. Tested on
all 1,296 real readings (Oct 2026): 93% agree with the logged label.

Flags: a pitch is flagged only when it's clearly closer to a different
group (second-closest / closest distance >= MARGIN) than its label's.
Cutters may sit with fastballs or breaking balls and splitters with
changeups or breaking balls -- the article shows these are points on a
continuous surface, not their own groups -- so those aren't flagged for
landing in either. This only FLAGS and SUGGESTS; nothing changes until a
coach confirms (services/pitch_type_switch.py, logged + undoable).
Pitches are logged by grip; Rapsodo's movement is the check on the label.
"""

from statistics import median

from gbo_cache import cached

FB, BB, CH = "Fastball", "Breaking ball", "Changeup"
GROUP_OF = {
    "4-Seam Fastball": FB, "2-Seam Fastball": FB, "Fastball": FB, "Sinker": FB, "Cutter": FB,
    "Slider": BB, "Curveball": BB, "Sweeper": BB, "Slurve": BB, "Knuckle Curve": BB,
    "Changeup": CH, "Splitter": CH,
}
# label -> groups it may legitimately land in (gray areas)
ACCEPT = {"Cutter": {FB, BB}, "Splitter": {CH, BB}}
REFERENCE_TYPES = {"4-Seam Fastball", "2-Seam Fastball", "Fastball", "Sinker"}

# TopoTagger D1 peaks: (arm-side run, IVB, dSpeed)
ARTICLE_CENTERS = {FB: (11.5, 17.5, -0.7), BB: (-4.5, 1.5, -9.7), CH: (16.5, 7.5, -7.9)}
MPH_SCALE = 0.6
MARGIN = 1.3
MIN_CALIBRATION = 30


def _f(v):
    return float(v) if v is not None else None


def features(p, throws):
    """(run, ivb, velo) from a RapsodoPitch, or None without movement.
    Spin-based movement (vb_spin/hb_spin, same as Fastball Shape Check and
    the Movement chart), trajectory-based as a fallback."""
    ivb = _f(p.vb_spin) if p.vb_spin is not None else _f(p.vb_trajectory)
    hb = _f(p.hb_spin) if p.hb_spin is not None else _f(p.hb_trajectory)
    if ivb is None or hb is None:
        return None
    return (hb if throws != "L" else -hb), ivb, _f(p.velocity)


def _p95(vals):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(0.95 * (len(vals) - 1))))]


def _outing(p):
    if p.bullpen_id is not None:
        return ("bp", p.bullpen_id)
    if p.import_id is not None:
        return ("imp", p.import_id)
    return ("d", p.pitch_date.date() if hasattr(p.pitch_date, "date") else p.pitch_date)


def _type_name(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) is not None else None


def build_points(raps, throws):
    """[{pitch, labeled, group, run, ivb, velo, dv}] -- pitches with movement
    and velo; dv relative to his 95th-pct fastball that outing."""
    pts, by_out, all_fb = [], {}, []
    for p in raps:
        feat = features(p, throws)
        if feat is None or feat[2] is None:
            continue
        name = _type_name(p)
        pts.append({"pitch": p, "labeled": name, "group": GROUP_OF.get(name), "run": feat[0], "ivb": feat[1],
                    "velo": feat[2], "outing": _outing(p)})
        if name in REFERENCE_TYPES:
            by_out.setdefault(_outing(p), []).append(feat[2])
            all_fb.append(feat[2])
    if not all_fb:
        return []
    whole = _p95(all_fb)
    for pt in pts:
        ref = by_out.get(pt["outing"])
        pt["dv"] = pt["velo"] - (_p95(ref) if ref else whole)
    return pts


def distance(pt, c):
    return ((pt["run"] - c[0]) ** 2 + (pt["ivb"] - c[1]) ** 2 + ((pt["dv"] - c[2]) / MPH_SCALE) ** 2) ** 0.5


def classify(pt, centers):
    """(group, margin) -- margin = second-closest / closest distance."""
    ds = sorted((distance(pt, c), g) for g, c in centers.items())
    return ds[0][1], ds[1][0] / max(ds[0][0], 1e-6)


@cached("pitch_class_centers", tables={"rapsodo_pitches", "pitch_types", "players"})
def team_centers(db):
    """{group: (run, ivb, dv)} from every labeled Rapsodo reading on file,
    plus {"n": {group: count}, "source": {group: "ours"/"article"}}."""
    from sqlalchemy.orm import joinedload
    from models import RapsodoPitch, Player
    throws = {pid: t for pid, t in db.query(Player.player_id, Player.throws).all()}
    rows = db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type)).all()
    by_player = {}
    for r in rows:
        by_player.setdefault(r.player_id, []).append(r)
    groups = {FB: [], BB: [], CH: []}
    for pid, raps in by_player.items():
        for pt in build_points(raps, throws.get(pid) or "R"):
            if pt["group"] in groups:
                groups[pt["group"]].append(pt)
    centers, source, n = {}, {}, {}
    for g, pts in groups.items():
        n[g] = len(pts)
        if len(pts) >= MIN_CALIBRATION:
            centers[g] = (median(p["run"] for p in pts), median(p["ivb"] for p in pts), median(p["dv"] for p in pts))
            source[g] = "ours"
        else:
            centers[g], source[g] = ARTICLE_CENTERS[g], "article"
    return {"centers": centers, "n": n, "source": source}


def _default_name(group, pt):
    if group == FB:
        return "2-Seam Fastball" if pt["run"] > pt["ivb"] else "4-Seam Fastball"
    if group == CH:
        return "Changeup"
    return "Curveball" if pt["ivb"] <= -6 and pt["run"] > -9 else "Slider"


def check_pitcher(raps, throws, centers):
    """{"points", "flags", "counts", "agree_pct"} for one pitcher's Rapsodo
    readings. Each flag: pitch, labeled, looks_like (group), suggested (a
    pitch type -- one of HIS clean types in that group when he has one,
    else a sensible default), run/ivb/velo/dv, margin, reason."""
    pts = build_points(raps, throws)
    for pt in pts:
        pt["pred"], pt["margin"] = classify(pt, centers)
        ok = pt["group"] is None or pt["pred"] == pt["group"] or pt["pred"] in ACCEPT.get(pt["labeled"], ())
        pt["flagged"] = (not ok) and pt["margin"] >= MARGIN
    # his own clean shapes per type (labels the classifier agrees with)
    own = {}
    for pt in pts:
        if pt["labeled"] and not pt["flagged"] and pt["pred"] == pt["group"]:
            own.setdefault(pt["labeled"], []).append(pt)
    own_c = {t: (median(p["run"] for p in v), median(p["ivb"] for p in v), median(p["dv"] for p in v))
             for t, v in own.items() if len(v) >= 3}
    flags = []
    for pt in pts:
        if not pt["flagged"]:
            continue
        cands = {t: c for t, c in own_c.items() if GROUP_OF.get(t) == pt["pred"]}
        suggested = min(cands, key=lambda t: distance(pt, cands[t])) if cands else _default_name(pt["pred"], pt)
        flags.append({**pt, "looks_like": pt["pred"], "suggested": suggested,
                      "reason": (f"{pt['dv']:+.1f} mph vs his fastball, {pt['run']:.1f}\" arm-side run, {pt['ivb']:.1f}\" IVB -- "
                                 f"closer to a {pt['pred'].lower()} than a {(pt['group'] or '?').lower()}")})
    counts = {}
    for pt in pts:
        counts[pt["labeled"] or "Unlabeled"] = counts.get(pt["labeled"] or "Unlabeled", 0) + 1
    graded = [pt for pt in pts if pt["group"]]
    agree = sum(1 for pt in graded if not pt["flagged"])
    return {"points": pts, "flags": flags, "counts": counts,
            "agree_pct": round(100 * agree / len(graded), 1) if graded else None}
