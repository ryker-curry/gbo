"""
GBO -- Arsenal Plan / Recommender (Oct 2026).

Ryker sent Paradigm's REAPER thread ("takes a pitcher's release height
and fastball shape, then reverse engineers the arsenal that should work
around it -- keep this pitch, adjust that one, add what is missing") and
said "build it".

WHAT THIS IS (and isn't)
  REAPER's targets come from a model trained on millions of D1/MLB
  pitches with outcomes. GBO doesn't have that, so targets here come
  from established public pitch-design rules relative to HIS fastball
  and arm slot (TARGET RULES below), plus our own Stuff+ where it exists.
  Starting points, labeled that way on the page; a coach can override
  any target (models.ArsenalTarget) and the override is used instead.

FRAME
  Movement in the pitcher's own frame: IVB = vb_spin (Rapsodo induced
  vertical break), RUN = hb_trajectory flipped so + = his ARM side for
  either hand (same HB field the Movement chart uses -- see
  visualizations/bullpen_charts.py on why hb_trajectory, not hb_spin).
  Shapes are medians (robust to a few mis-reads).

SLOT
  Estimated arm angle (analytics/bullpen_metrics._pitch_level_arm_angle,
  needs Player.height_in): high >= HIGH_SLOT_DEG, low < LOW_SLOT_DEG.
  Without a height, release height stands in (>= 6.1 ft high, < 5.4 ft low).

TARGET RULES (relative to his primary fastball: velo V, IVB I, run R)
  changeup  V-9 mph, IVB max(I-12, 2), run R+1   (fade with the FB, ~12" less ride)
  slider    V-7, IVB +1, run -3                   (gyro/tight; "bullet")
  sweeper   V-10, IVB 0, run -14 (-16 low slot)   (big glove-side sweep)
  curveball V-13, IVB -12 (-14 high, -8 low), run -6 (-4 high, -9 low)
  cutter    V-4, IVB I-7, run -2
  sinker    V-1, IVB I-8, run R+5                 (when his primary is a 4-seam)
  four_seam V+1, IVB I+7, run R-5                 (when his primary is a sinker)

WHICH PITCHES FIT HIM (recommended set; "core" vs "option")
  ride/high slot (IVB >= 17 or high slot): core changeup, slider, curveball; option cutter
  run/low slot   (low slot, or run >= 14 with IVB <= 13): core changeup, sweeper; option sinker/4-seam pair
  in between:    core changeup, slider; option curveball, sweeper (if arm angle < 45)

KEEP / TUNE / ADD
  Each current pitch is matched to its family's target (a "Slider" that
  sweeps -- run <= -10 -- is compared to the sweeper target when that
  fits him better). Distance = inches between current and target shape.
  KEEP: within KEEP_IN and velo within KEEP_MPH.  TUNE: otherwise, with
  the exact changes (ride, sweep/run, mph).  ADD: a core pitch he
  doesn't throw (fewer than MIN_PITCHES readings).
"""

from collections import defaultdict
from statistics import median

FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball", "Sinker")
FAMILY = {
    "4-Seam Fastball": "four_seam", "Fastball": "four_seam",
    "2-Seam Fastball": "sinker", "Sinker": "sinker",
    "Changeup": "changeup", "Splitter": "changeup",
    "Slider": "slider", "Sweeper": "sweeper", "Slurve": "sweeper",
    "Curveball": "curveball", "Knuckle Curve": "curveball",
    "Cutter": "cutter",
}
NAMES = {"four_seam": "4-Seam Fastball", "sinker": "Sinker", "changeup": "Changeup", "slider": "Slider",
         "sweeper": "Sweeper", "curveball": "Curveball", "cutter": "Cutter"}

HIGH_SLOT_DEG = 50
LOW_SLOT_DEG = 32
MIN_PITCHES = 5
KEEP_IN = 3.0
KEEP_MPH = 2.0


def _f(v):
    return float(v) if v is not None else None


def shape(pitches, throws):
    """Median (velo, ivb, run_armside) of a group, plus n."""
    rows = [(_f(p.velocity), _f(p.vb_spin), _f(p.hb_trajectory)) for p in pitches]
    rows = [r for r in rows if r[1] is not None and r[2] is not None]
    if not rows:
        return None
    sgn = 1 if throws != "L" else -1
    velos = [r[0] for r in rows if r[0] is not None]
    return {"velo": median(velos) if velos else None, "ivb": median(r[1] for r in rows),
            "run": median(sgn * r[2] for r in rows), "n": len(rows)}


def slot_of(arm_angle, release_height):
    if arm_angle is not None:
        return "high" if arm_angle >= HIGH_SLOT_DEG else ("low" if arm_angle < LOW_SLOT_DEG else "mid")
    if release_height is not None:
        return "high" if release_height >= 6.1 else ("low" if release_height < 5.4 else "mid")
    return "mid"


def profile_kind(fb, slot):
    if fb["ivb"] >= 17 or slot == "high":
        return "ride"
    if slot == "low" or (fb["run"] >= 14 and fb["ivb"] <= 13):
        return "run"
    return "mid"


def targets_for(fb, slot, primary_family):
    V, I, R = fb["velo"] or 85.0, fb["ivb"], fb["run"]
    t = {
        "changeup": (V - 9, max(I - 12, 2.0), R + 1),
        "slider": (V - 7, 1.0, -3.0),
        "sweeper": (V - 10, 0.0, -16.0 if slot == "low" else -14.0),
        "curveball": (V - 13, {"high": -14.0, "low": -8.0}.get(slot, -12.0), {"high": -4.0, "low": -9.0}.get(slot, -6.0)),
        "cutter": (V - 4, I - 7, -2.0),
    }
    if primary_family == "four_seam":
        t["sinker"] = (V - 1, I - 8, R + 5)
    else:
        t["four_seam"] = (V + 1, I + 7, R - 5)
    return {k: {"velo": round(v[0], 1), "ivb": round(v[1], 1), "run": round(v[2], 1)} for k, v in t.items()}


def recommended(kind, arm_angle, primary_family):
    pair = "sinker" if primary_family == "four_seam" else "four_seam"
    if kind == "ride":
        return {"core": ["changeup", "slider", "curveball"], "option": ["cutter"]}
    if kind == "run":
        return {"core": ["changeup", "sweeper"], "option": [pair, "slider"]}
    opts = ["curveball"] + (["sweeper"] if arm_angle is None or arm_angle < 45 else [])
    return {"core": ["changeup", "slider"], "option": opts}


def _tune_text(cur, tgt):
    bits = []
    d_ivb = tgt["ivb"] - cur["ivb"]
    d_run = tgt["run"] - cur["run"]
    if abs(d_ivb) >= 1.5:
        bits.append(f"{'add' if d_ivb > 0 else 'take off'} {abs(d_ivb):.0f}\" of ride")
    if abs(d_run) >= 1.5:
        n = abs(d_run)
        if d_run < 0:
            bits.append(f"{n:.0f}\" less arm-side run" if cur["run"] > 0 and tgt["run"] >= 0
                        else f"{n:.0f}\" more glove-side sweep")
        else:
            bits.append(f"{n:.0f}\" less sweep" if cur["run"] < 0 and tgt["run"] <= 0
                        else f"{n:.0f}\" more arm-side run")
    if cur.get("velo") is not None and tgt.get("velo") is not None:
        d_v = tgt["velo"] - cur["velo"]
        if abs(d_v) >= KEEP_MPH:
            bits.append(f"throw it {abs(d_v):.0f} mph {'harder' if d_v > 0 else 'softer'}")
    return ", ".join(bits)


def _dist(cur, tgt):
    return ((cur["ivb"] - tgt["ivb"]) ** 2 + (cur["run"] - tgt["run"]) ** 2) ** 0.5


def build_plan(pitches, throws, arm_angle, release_height, overrides=None, label_of=None):
    """pitches: his RapsodoPitch rows. overrides: {family: {velo, ivb, run, note}}.
    Returns dict or None (no fastball shape)."""
    label_of = label_of or (lambda p: p.pitch_type.type_name if getattr(p, "pitch_type", None) else None)
    groups = defaultdict(list)
    for p in pitches:
        lab = label_of(p)
        if lab:
            groups[lab].append(p)
    fbs = [(lab, ps) for lab, ps in groups.items() if lab in FASTBALLS and len(ps) >= MIN_PITCHES]
    if not fbs:
        return None
    primary_label, primary_ps = max(fbs, key=lambda kv: len(kv[1]))
    fb = shape(primary_ps, throws)
    if fb is None:
        return None
    primary_family = FAMILY[primary_label]
    slot = slot_of(arm_angle, release_height)
    kind = profile_kind(fb, slot)
    targets = targets_for(fb, slot, primary_family)
    sources = {k: "rule" for k in targets}
    for fam, o in (overrides or {}).items():
        if fam in targets or fam in NAMES:
            targets[fam] = {"velo": o.get("velo"), "ivb": o["ivb"], "run": o["run"]}
            sources[fam] = "coach"
    rec = recommended(kind, arm_angle, primary_family)
    fits = set(rec["core"]) | set(rec["option"])

    rows, have = [], set()
    for lab, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cur = shape(ps, throws)
        fam = FAMILY.get(lab)
        if cur is None or fam is None or cur["n"] < MIN_PITCHES:
            continue
        if lab == primary_label:
            rows.append({"label": lab, "family": fam, "cur": cur, "target": None, "status": "anchor",
                         "text": "Primary fastball -- everything else is built off this shape.", "dist": None})
            have.add(fam)
            continue
        if fam in ("slider", "sweeper"):
            # Compare a slider-type pitch to whichever glove-side target he
            # should have; if both fit him, the one it's already closest to.
            options = ([f for f in ("slider", "sweeper") if f in rec["core"]]
                       or [f for f in ("slider", "sweeper") if f in fits] or [fam])
            fam = min(options, key=lambda f: _dist(cur, targets[f]))
        have.add(fam)
        tgt = targets.get(fam)
        if tgt is None:
            rows.append({"label": lab, "family": fam, "cur": cur, "target": None, "status": "keep",
                         "text": "No target for this pitch type.", "dist": None})
            continue
        dist = _dist(cur, tgt)
        velo_ok = tgt.get("velo") is None or cur["velo"] is None or abs(tgt["velo"] - cur["velo"]) < KEEP_MPH
        if dist <= KEEP_IN and velo_ok:
            status, text = "keep", "Close to its target shape -- keep it."
        else:
            status, text = "tune", "To reach the target: " + (_tune_text(cur, tgt) or "small shape change") + "."
        if fam not in fits:
            text += f" (A {NAMES[fam].lower()} isn't a natural fit for his slot/fastball -- worth a conversation.)"
        rows.append({"label": lab, "family": fam, "cur": cur, "target": tgt, "status": status, "text": text,
                     "dist": round(dist, 1), "source": sources.get(fam)})

    adds = []
    for fam in rec["core"] + rec["option"]:
        if fam in have or fam == primary_family:
            continue
        if fam in ("slider", "sweeper") and ({"slider", "sweeper"} & have) and fam not in rec["core"]:
            continue
        adds.append({"family": fam, "label": NAMES[fam], "target": targets[fam], "core": fam in rec["core"],
                     "source": sources.get(fam), "why": _why(fam, kind, slot)})
    return {"fb": fb, "primary": primary_label, "slot": slot, "kind": kind, "arm_angle": arm_angle,
            "rows": rows, "adds": adds, "targets": targets, "sources": sources}


def _why(fam, kind, slot):
    return {
        "changeup": "Every arsenal needs something slower with fade to get opposite-handed hitters off the fastball.",
        "slider": "A tight, hard breaking ball off the fastball gives a glove-side pitch that tunnels with it.",
        "sweeper": "His slot/fastball run sets up big glove-side sweep -- a weapon vs same-handed hitters.",
        "curveball": "A riding fastball from his slot pairs with a true downer curveball (big vertical separation).",
        "cutter": "A cutter bridges the fastball and breaking ball and gives a weak-contact pitch in on opposite-handed hitters.",
        "sinker": "A sinker gives a second fastball that moves the other way -- ground balls in on same-handed hitters.",
        "four_seam": "A riding 4-seam pairs with the sinker to work up in the zone.",
    }.get(fam, "")


def progress(pitches, throws, plan, label_of=None, max_sessions=8):
    """{label: [(date, dist_in, n), ...]} per session (calendar day) for
    every pitch that has a target -- is the shape moving toward it?"""
    label_of = label_of or (lambda p: p.pitch_type.type_name if getattr(p, "pitch_type", None) else None)
    tgt_by_label = {r["label"]: r["target"] for r in plan["rows"] if r.get("target")}
    out = {}
    for lab, tgt in tgt_by_label.items():
        by_day = defaultdict(list)
        for p in pitches:
            if label_of(p) == lab and p.pitch_date is not None:
                by_day[p.pitch_date.date()].append(p)
        series = []
        for day in sorted(by_day)[-max_sessions:]:
            s = shape(by_day[day], throws)
            if s and s["n"] >= 3:
                series.append((day, round(_dist(s, tgt), 1), s["n"]))
        if len(series) >= 2:
            out[lab] = series
    return out
