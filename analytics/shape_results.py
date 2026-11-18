"""
GBO -- Hitter results by pitch shape (Oct 2026, from Columbia SABRLions'
"How to Use a Pitcher's Metrics Against Them: A D1 Hitter's Data Bible":
riding vs "dead-zone" vs sinking fastballs, gyro vs sweeping sliders,
release height -- know which shapes you handle and which beat you).

Only pitches with a Rapsodo reading linked to the charted pitch count --
in practice intrasquads against our own staff, since opponents have no
shape data. Groups (pitcher's frame: run + = his arm side):

  Fastball shape  riding: ride >= RIDE_IN
                  sinking / running: ride <= SINK_IN, or run >= RUN_IN with ride < 13
                  dead zone / in-between: the rest (the article's 11-15" ride,
                  11-15" run "A-swing" fastball lives here)
  Breaking ball   slider_fit.classify: gyro / traditional / sweeper /
                  curveball / slurve (cutter-type grouped with gyro)
  Arm slot        estimated arm angle: high >= 50, low < 32 (arsenal_plan)
  Fastball velo   under 84 / 84-87 / 88+

Per group: pitches, swing %, whiff % (of swings), CSW %, hard-contact %
(barreled / solid of balls in play), RV/100 (+ = good for the hitter).
"""

from collections import defaultdict

from analytics.hitter_insights import family, HARD_CONTACT
from analytics.bullpen_metrics import _pitch_level_arm_angle
from analytics import slider_fit
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES

RIDE_IN = 16.0
SINK_IN = 10.0
RUN_IN = 15.0
HIGH_SLOT, LOW_SLOT = 50, 32
VELO_BANDS = (("Under 84", 0, 84), ("84-87", 84, 88), ("88+", 88, 200))
BREAK_NAMES = {"gyro": "Gyro / tight slider", "cutter": "Gyro / tight slider", "between": "Traditional slider",
               "sweeper": "Sweeper", "carry_sweeper": "Sweeper", "curveball": "Curveball", "slurve": "Slurve"}
DIMENSIONS = ("Fastball shape", "Breaking ball", "Arm slot", "Fastball velo")


def _f(v):
    return float(v) if v is not None else None


def groups_of(gp, rap, pitcher):
    """{dimension: group label} for one charted pitch with its Rapsodo reading."""
    out = {}
    fam = family(gp)
    ivb = _f(rap.vb_spin)
    hb = _f(rap.hb_trajectory)
    throws = getattr(pitcher, "throws", None) or "R"
    run = (-hb if throws == "L" else hb) if hb is not None else None
    if fam == "Fastball" and ivb is not None and run is not None:
        if ivb >= RIDE_IN:
            out["Fastball shape"] = "Riding"
        elif ivb <= SINK_IN or (run >= RUN_IN and ivb < 13):
            out["Fastball shape"] = "Sinking / running"
        else:
            out["Fastball shape"] = "Dead zone / in-between"
        v = _f(rap.velocity)
        if v is not None:
            out["Fastball velo"] = next(lab for lab, lo, hi in VELO_BANDS if lo <= v < hi)
    if fam == "Breaking" and ivb is not None and run is not None:
        out["Breaking ball"] = BREAK_NAMES.get(slider_fit.classify({"ivb": ivb, "run": run}), "Other breaking")
    aa = _pitch_level_arm_angle(rap, pitcher)["value_degrees"] if pitcher is not None else None
    if aa is not None:
        out["Arm slot"] = "High slot" if aa >= HIGH_SLOT else ("Low slot" if aa < LOW_SLOT else "Three-quarter")
    return out


def _rates(ps):
    n = len(ps)
    sw = [p for p in ps if p.pitch_outcome in SWING_OUTCOMES]
    wh = [p for p in sw if p.pitch_outcome in WHIFF_OUTCOMES]
    csw = [p for p in ps if p.pitch_outcome in ("Called Strike", "Swing and Miss")]
    bip = [p for p in ps if p.pitch_outcome == "In Play"]
    hard = [p for p in bip if (p.contact_quality or "") in HARD_CONTACT]
    rv = [float(p.run_value) for p in ps if p.run_value is not None]

    def pct(a, b):
        return 100.0 * a / b if b else None
    return {"n": n, "swing": pct(len(sw), n), "whiff": pct(len(wh), len(sw)), "csw": pct(len(csw), n),
            "hard": pct(len(hard), len(bip)), "bip": len(bip), "rv100": 100.0 * sum(rv) / n if n and rv else None}


def table(pitches, rap_by_gp, pitchers_by_id):
    """-> {dimension: {group: rates}}"""
    buckets = defaultdict(lambda: defaultdict(list))
    for gp in pitches:
        rap = rap_by_gp.get(gp.game_pitch_id)
        if rap is None:
            continue
        for dim, grp in groups_of(gp, rap, pitchers_by_id.get(rap.player_id)).items():
            buckets[dim][grp].append(gp)
    return {dim: {g: _rates(ps) for g, ps in gs.items()} for dim, gs in buckets.items()}


ORDER = {
    "Fastball shape": ("Riding", "Dead zone / in-between", "Sinking / running"),
    "Breaking ball": ("Gyro / tight slider", "Traditional slider", "Sweeper", "Slurve", "Curveball", "Other breaking"),
    "Arm slot": ("High slot", "Three-quarter", "Low slot"),
    "Fastball velo": tuple(lab for lab, _lo, _hi in VELO_BANDS),
}


def takeaway(mine, min_n=15):
    """Best and worst group by RV/100 with min_n pitches, across dimensions."""
    items = [(r["rv100"], dim, g, r["n"]) for dim, gs in mine.items() for g, r in gs.items()
             if r["rv100"] is not None and r["n"] >= min_n]
    if len(items) < 2:
        return []
    items.sort()
    lo, hi = items[0], items[-1]
    if hi[0] - lo[0] < 2:
        return []
    return [f"Handles best: {hi[2].lower()} ({hi[1].lower()}, {hi[0]:+.1f} RV/100 over {hi[3]}).",
            f"Struggles most: {lo[2].lower()} ({lo[1].lower()}, {lo[0]:+.1f} RV/100 over {lo[3]})."]
