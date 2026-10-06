"""
GBO -- Slider type + fit (Oct 2026).

From Ryker's article batch (Columbia SABRLions' "Inside the Trackman
Pt. 2: Slider Pitch Design Breakdown"), approved as "Slider type + fit"
on the Arsenal Plan view. Two pieces:

1) TYPE -- what his glove-side breaking ball actually is, by shape (his
   frame: run + = arm side, so glove-side sweep = -run; IVB = vb_spin):
     gyro slider    |run| <= GYRO_RUN, IVB above CURVE_IVB and at most
                    GYRO_IVB[1] (the article's gyro window is 0 to 5" of
                    break and IVB about -2 to +3; widened down to CURVE_IVB
                    because a lot of our gyro sliders read a few inches of
                    drop on Rapsodo)
     sweeper        glove-side sweep >= SWEEP_IN
     carry sweeper  a sweeper whose IVB is CARRY_IN+ over expected for its
                    type and his slot (analytics/ivb_expected.py) -- the
                    "carry" shape most of the article's top sweepers had
     curveball      IVB <= CURVE_IVB (true downward break)
     slurve         between sweeper and curveball (some sweep, some depth)
     cutter-ish     IVB > GYRO_IVB[1] with small sweep -- rides like a cutter
     in-between     5-10" of sweep -- a traditional slider between the two

2) FIT -- which slider his fastball suggests. The article's tell is
   fastball spin efficiency: very efficient backspin (~95%+) points to a
   pronator, who usually spins a hard gyro slider better; ~80% points to
   a supinator, who usually sweeps it. Our staff's 4-seams average ~89%,
   so the cutoffs are PRONATOR_SE / SUPINATOR_SE with "either" between.
   This is a HINT shown beside the existing arm-slot rule (arsenal_plan
   recommended()), and the page says when the two disagree.

Plus the article's caution: past ~SWEEP_CAP" of sweep, more sweep adds
little -- velo matters more (80 mph / 15" beat 75 mph / 20").
"""

from statistics import median

BREAKERS = ("Slider", "Sweeper", "Slurve", "Curveball", "Knuckle Curve")
GYRO_RUN = 5.0
GYRO_IVB = (-2.0, 3.0)
SWEEP_IN = 10.0
SWEEP_CAP = 12.0
CARRY_IN = 3.0
CURVE_IVB = -6.0
PRONATOR_SE = 93.0
SUPINATOR_SE = 85.0
MIN_SE = 5

TYPE_NAMES = {
    "gyro": "Gyro slider", "sweeper": "Sweeper", "carry_sweeper": "Carry sweeper", "curveball": "Curveball",
    "slurve": "Slurve", "cutter": "Cutter-type slider", "between": "Traditional slider (between gyro and sweeper)",
}


def classify(cur, ivb_over=None):
    """cur: arsenal_plan.shape() dict (ivb, run arm-side +). -> type key."""
    ivb, run = cur["ivb"], cur["run"]
    sweep = -run
    if ivb <= CURVE_IVB:
        return "curveball" if sweep < SWEEP_IN else "slurve"
    if sweep >= SWEEP_IN:
        return "carry_sweeper" if ivb_over is not None and ivb_over >= CARRY_IN else "sweeper"
    if ivb > GYRO_IVB[1]:
        return "cutter" if sweep < 6 else "between"
    if abs(run) <= GYRO_RUN:
        return "gyro"
    return "between"


def fb_spin_efficiency(fb_pitches):
    vals = [float(p.spin_efficiency) for p in fb_pitches if p.spin_efficiency is not None]
    vals = [v for v in vals if 0 < v <= 100]
    return (median(vals), len(vals)) if len(vals) >= MIN_SE else (None, len(vals))


def fit_hint(se):
    """-> (lean, suggested) lean: pronator/supinator/neutral/None."""
    if se is None:
        return None, None
    if se >= PRONATOR_SE:
        return "pronator", "gyro"
    if se <= SUPINATOR_SE:
        return "supinator", "sweeper"
    return "neutral", "either"


def slot_suggestion(plan):
    """What the existing arm-slot rule (arsenal_plan.recommended) leans toward: gyro / sweeper / either."""
    from analytics.arsenal_plan import recommended, FAMILY
    if not plan:
        return "either"
    rec = recommended(plan["kind"], plan.get("arm_angle"), FAMILY.get(plan["primary"], "four_seam"))
    core = set(rec["core"])
    if "sweeper" in core and "slider" not in core:
        return "sweeper"
    if "slider" in core and "sweeper" not in core:
        return "gyro"
    return "either"


def notes_for(type_key, cur, fb):
    out = []
    sweep = -cur["run"]
    if type_key in ("sweeper", "carry_sweeper") and sweep > SWEEP_CAP:
        out.append(f"{sweep:.0f}\" of sweep is already past ~{SWEEP_CAP:.0f}\" -- more sweep adds little from here; "
                   "adding velo would help more.")
    if type_key == "gyro" and cur.get("velo") and fb.get("velo") and fb["velo"] - cur["velo"] > 9:
        out.append(f"{fb['velo'] - cur['velo']:.0f} mph off the fastball is a big gap for a gyro slider -- they play best "
                   "hard (about 5-8 mph off).")
    if type_key == "between":
        out.append("Sits between a gyro and a sweeper. Fine if it's getting outs; if not, pick a lane -- tighter and "
                   "harder, or open it up into a sweeper.")
    if type_key == "carry_sweeper":
        out.append("Carry sweepers (sweep plus more ride than his slot predicts) were the most common shape among the "
                   "article's best sweepers.")
    return out


def build(plan, his_pitches, label_of, throws, ivb_over_by_label):
    """Rows for his breaking balls + the fit hint. plan: arsenal_plan.build_plan output."""
    from analytics.arsenal_plan import shape, FASTBALLS
    if plan is None:
        return None
    fb_ps = [p for p in his_pitches if label_of(p) == plan["primary"]]
    se, n_se = fb_spin_efficiency(fb_ps)
    lean, suggested = fit_hint(se)
    slot_s = slot_suggestion(plan)
    groups = {}
    for p in his_pitches:
        lab = label_of(p)
        if lab in BREAKERS:
            groups.setdefault(lab, []).append(p)
    rows = []
    for lab, ps in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        cur = shape(ps, throws)
        if cur is None or cur["n"] < 5:
            continue
        over = ivb_over_by_label.get(lab)
        t = classify(cur, over)
        rows.append({"label": lab, "cur": cur, "type": t, "type_name": TYPE_NAMES[t], "ivb_over": over,
                     "notes": notes_for(t, cur, plan["fb"])})
    agree = None
    if suggested in ("gyro", "sweeper") and slot_s in ("gyro", "sweeper"):
        agree = suggested == slot_s
    return {"se": se, "n_se": n_se, "lean": lean, "suggested": suggested, "slot_suggested": slot_s,
            "agree": agree, "rows": rows, "fastball_types": FASTBALLS}
