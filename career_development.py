"""
GBO -- Career Development (Nov 2026, Ryker). Data + math for the Player
Profile "Career Development" tab: how a pitcher's Rapsodo metrics and game
numbers changed from season to season while at Pitt State. Display lives in
shiny_app/career_development_display.py.

Data:
  - rapsodo_history (models.RapsodoHistory): pitches from before GBO's own
    imports. Read ONLY here -- see that model's docstring for why it's not
    in rapsodo_pitches.
  - rapsodo_pitches: everything GBO imported itself (fall 2026 on). A
    history pitch with the same Rapsodo unique id is dropped, so nothing
    counts twice.
  - game outcomes: a rapsodo_pitches row matched to a charted GamePitch
    gives that pitch's result (fall 2026 intrasquads).
  - season_pitch_splits / season_pitching_lines: spring 2026 game numbers
    from the staff game-tracking workbook.

Conventions (same as the rest of GBO):
  - IVB = vb_spin, HB = hb_trajectory (analytics/bullpen_metrics.py).
  - Lefties are mirrored so release side and HB read arm side = positive
    for everyone. Hand comes from Player.throws, else the sign of the
    pitcher's median release side (Rapsodo's body frame: + = his right).
  - Arm angle is ESTIMATED: shoulder at release_graphics.SHOULDER_RATIO of
    the player's height (73 in when unknown) to the release point.
  - Seasons run August-July ("2025-26"); terms are Fall/Spring + year.
  - Spin rate/efficiency/gyro only from pitches with spin confidence >= 0.8
    (Ryker's research rule).

Verdict rule for "what changed" (shown on the tab too): a change counts only
when it's at least half a pooled standard deviation (Cohen's d >= 0.5) and
both seasons have 8+ pitches. Velocity, extension and Rapsodo in-zone % have
a better direction; release spreads (SD) are better when they shrink by
20%+, worse when they grow 25%+; everything else is just higher/lower.
"""

from __future__ import annotations

import math
from collections import defaultdict

from pitch_type_config import normalize_pitch_type, FASTBALL_TYPES

SHOULDER_RATIO = 0.70
DEFAULT_HEIGHT_IN = 73.0
MIN_PITCHES = 8
EFFECT = 0.5
ALL_FB = "All fastballs"
SPRING_TERM = "Spring 2026"
QUALIFIED_IP = 10

MODES = {
    "standard": "Training + live (no rehab, recovery or low intent)",
    "live": "Live only",
    "all": "All sessions",
}
_EXCLUDED_STANDARD = {"Rehab", "Low Intent", "Recovery"}

# id, label, unit, decimals, direction (+1 higher better, -1 lower better,
# 0 neither), spin-confidence filter, kind ("mean" or "sd")
METRICS = [
    ("velo", "Velocity", "mph", 1, 1, False, "mean"),
    ("velo_sd", "Velocity spread (SD)", "mph", 2, -1, False, "sd"),
    ("zone_pct", "In-zone % (Rapsodo)", "%", 1, 1, False, "mean"),
    ("spin", "Spin rate", "rpm", 0, 0, True, "mean"),
    ("spin_eff", "Spin efficiency", "%", 1, 0, True, "mean"),
    ("gyro", "Gyro degree", "°", 0, 0, True, "mean"),
    ("ivb", "Induced vertical break", "in", 1, 0, False, "mean"),
    ("hb", "Horizontal break, arm side", "in", 1, 0, False, "mean"),
    ("arm_angle", "Arm angle (est.)", "°", 1, 0, False, "mean"),
    ("rel_height", "Release height", "ft", 2, 0, False, "mean"),
    ("rel_side", "Release side", "ft", 2, 0, False, "mean"),
    ("rel_height_sd", "Release height spread (SD)", "ft", 2, -1, False, "sd"),
    ("rel_side_sd", "Release side spread (SD)", "ft", 2, -1, False, "sd"),
    ("extension", "Extension", "ft", 2, 1, False, "mean"),
]
_SD_BASE = {"velo_sd": "velo", "rel_height_sd": "rel_height", "rel_side_sd": "rel_side"}


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def season_of(d):
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def term_of(d):
    return ("Fall " if d.month >= 8 else "Spring ") + str(d.year)


# ---------------------------------------------------------------- loading
def load_pitches(db, player_id):
    """Every Rapsodo pitch for one player (history + GBO imports), as plain
    dicts in one shape. Column-level queries only (Supabase egress)."""
    from models import (Player, PitchType, RapsodoPitch, RapsodoHistory, RapsodoImport,
                        BullpenSession, BullpenType, GamePitch)

    p = db.query(Player.throws, Player.height_in).filter(Player.player_id == player_id).first()
    throws, height = (p[0], _f(p[1])) if p else (None, None)
    names = {pid: n for pid, n in db.query(PitchType.pitch_type_id, PitchType.type_name)}

    live = (db.query(RapsodoPitch.rapsodo_unique_id, RapsodoPitch.pitch_date, RapsodoPitch.raw_pitch_type,
                     RapsodoPitch.pitch_type_id, RapsodoPitch.velocity, RapsodoPitch.total_spin,
                     RapsodoPitch.spin_efficiency, RapsodoPitch.spin_confidence, RapsodoPitch.gyro_degree,
                     RapsodoPitch.vb_spin, RapsodoPitch.hb_trajectory, RapsodoPitch.release_height,
                     RapsodoPitch.release_side, RapsodoPitch.release_extension, RapsodoPitch.is_strike,
                     RapsodoPitch.bullpen_id, RapsodoPitch.import_id, RapsodoImport.game_id,
                     BullpenType.type_name, GamePitch.pitch_outcome, GamePitch.run_value,
                     RapsodoPitch.game_pitch_id)
            .join(RapsodoImport, RapsodoImport.import_id == RapsodoPitch.import_id)
            .outerjoin(BullpenSession, BullpenSession.bullpen_id == RapsodoPitch.bullpen_id)
            .outerjoin(BullpenType, BullpenType.bullpen_type_id == BullpenSession.bullpen_type_id)
            .outerjoin(GamePitch, GamePitch.game_pitch_id == RapsodoPitch.game_pitch_id)
            .filter(RapsodoPitch.player_id == player_id).all())
    live_ids = {r[0] for r in live if r[0]}
    hist = (db.query(RapsodoHistory.source_uid, RapsodoHistory.pitch_date, RapsodoHistory.raw_pitch_type,
                     RapsodoHistory.pitch_type_id, RapsodoHistory.velocity, RapsodoHistory.total_spin,
                     RapsodoHistory.spin_efficiency, RapsodoHistory.spin_confidence, RapsodoHistory.gyro_degree,
                     RapsodoHistory.vb_spin, RapsodoHistory.hb_trajectory, RapsodoHistory.release_height,
                     RapsodoHistory.release_side, RapsodoHistory.release_extension, RapsodoHistory.is_strike,
                     RapsodoHistory.session_key, RapsodoHistory.session_type, RapsodoHistory.source)
            .filter(RapsodoHistory.player_id == player_id).all())

    rows = []
    for r in hist:
        if r[0] in live_ids or r[1] is None:
            continue
        rows.append(_row(r[1], names.get(r[3]) or normalize_pitch_type(r[2]), r[4:15],
                         session_key=r[15] or str(r[1].date()), session_type=r[16] or "Live",
                         source=r[17], outcome=None, run_value=None))
    for r in live:
        if r[1] is None:
            continue
        is_game = r[17] is not None or r[21] is not None
        stype = "Live" if is_game else (r[18] or "Bullpen")
        key = f"game-{r[17]}" if r[17] is not None else (f"pen-{r[15]}" if r[15] is not None else f"import-{r[16]}")
        rows.append(_row(r[1], names.get(r[3]) or normalize_pitch_type(r[2]), r[4:15],
                         session_key=key, session_type=stype, source="gbo",
                         outcome=r[19], run_value=_f(r[20])))
    rows = [r for r in rows if r["pitch"] and r["velo"] is not None]

    sides = sorted(r["_side_raw"] for r in rows if r["_side_raw"] is not None)
    if throws in ("R", "L"):
        sign = 1 if throws == "R" else -1
    else:
        sign = -1 if sides and sides[len(sides) // 2] < 0 else 1
    shoulder = SHOULDER_RATIO * (height or DEFAULT_HEIGHT_IN) / 12
    for r in rows:
        raw_side = r.pop("_side_raw")
        r["rel_side"] = abs(raw_side) if raw_side is not None else None
        if r["hb"] is not None:
            r["hb"] = r["hb"] * sign
        r["arm_angle"] = (math.degrees(math.atan2(r["rel_height"] - shoulder, r["rel_side"]))
                          if r["rel_height"] is not None and r["rel_side"] is not None else None)
    rows.sort(key=lambda r: r["dt"])
    return {"rows": rows, "hand": "R" if sign > 0 else "L", "shoulder_ft": shoulder,
            "height_known": height is not None}


def _row(dt, pitch, vals, **extra):
    velo, spin, eff, conf, gyro, vb, hb, rh, rs, ext, strike = (_f(v) if not isinstance(v, bool) else v for v in vals)
    return dict(dt=dt, date=dt.date(), season=season_of(dt), term=term_of(dt), pitch=pitch,
                velo=velo, spin=spin, spin_eff=eff, spin_conf=conf, gyro=gyro, ivb=vb, hb=hb,
                rel_height=rh, _side_raw=rs, extension=ext if ext else None,
                zone=None if strike is None else (100.0 if strike else 0.0),
                spin_ok=conf is not None and conf >= 0.8 and spin is not None and spin > 500, **extra)


# ---------------------------------------------------------------- filters
def keep_mode(mode):
    if mode == "all":
        return lambda r: True
    if mode == "live":
        return lambda r: r["session_type"] == "Live"
    return lambda r: r["session_type"] not in _EXCLUDED_STANDARD


def pitch_match(pitch):
    if pitch == ALL_FB:
        return lambda r: r["pitch"] in FASTBALL_TYPES
    return lambda r: r["pitch"] == pitch


def pitch_options(rows):
    """[(value, label)] most-thrown first; 'All fastballs' leads when the
    pitcher has more than one fastball tag (e.g. Ryker's 2-seam tag only
    starts in Feb 2025, so his career fastball comparison needs both)."""
    counts = defaultdict(int)
    for r in rows:
        counts[r["pitch"]] += 1
    opts = [(p, f"{p} ({n})") for p, n in sorted(counts.items(), key=lambda kv: -kv[1])]
    fbs = [p for p in counts if p in FASTBALL_TYPES]
    if len(fbs) > 1:
        opts.insert(0, (ALL_FB, f"{ALL_FB} ({sum(counts[p] for p in fbs)})"))
    return opts


def seasons(rows):
    return sorted({r["season"] for r in rows})


def default_view(rows):
    """Starting pitch + seasons: the main pitch, earliest season with 20+ of
    it (else the earliest), and the latest."""
    opts = pitch_options(rows)
    if not opts:
        return None, None, None
    pitch = opts[0][0]
    keep, match = keep_mode("standard"), pitch_match(pitch)
    by = defaultdict(int)
    for r in rows:
        if keep(r) and match(r):
            by[r["season"]] += 1
    ss = sorted(by)
    if not ss:
        return pitch, None, None
    good = [s for s in ss if by[s] >= 20]
    return pitch, (good[0] if good else ss[0]), ss[-1]


# ---------------------------------------------------------------- math
def _stats(vals):
    n = len(vals)
    if not n:
        return 0, None, None
    m = sum(vals) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1)) if n > 1 else None
    return n, m, sd


def season_summary(rows, pitch, mode):
    """{season: {metric_id: (n, value, sd)}} -- value is the mean, or the SD
    itself for the *_sd spread metrics."""
    keep, match = keep_mode(mode), pitch_match(pitch)
    by = defaultdict(list)
    for r in rows:
        if keep(r) and match(r):
            by[r["season"]].append(r)
    field = {"velo": "velo", "zone_pct": "zone", "spin": "spin", "spin_eff": "spin_eff", "gyro": "gyro",
             "ivb": "ivb", "hb": "hb", "arm_angle": "arm_angle", "rel_height": "rel_height",
             "rel_side": "rel_side", "extension": "extension"}
    out = {}
    for s, rs in by.items():
        d = {}
        for mid, _l, _u, _dp, _dir, spin_only, kind in METRICS:
            src = _SD_BASE.get(mid) or field[mid]
            vals = [r[src] for r in rs if r[src] is not None and (not spin_only or r["spin_ok"])]
            n, m, sd = _stats(vals)
            d[mid] = (n, sd, None) if kind == "sd" else (n, m, sd)
        out[s] = d
    return out


def compare(summary, s_from, s_to):
    """Rows for the 'What changed' table: metric, the two season values,
    change, pitch counts and a verdict."""
    a, b = summary.get(s_from), summary.get(s_to)
    if not a or not b or s_from == s_to:
        return []
    out = []
    for mid, label, unit, dp, direction, _spin, kind in METRICS:
        n1, v1, sd1 = a[mid]
        n2, v2, sd2 = b[mid]
        verdict = "No clear change"
        if n1 < MIN_PITCHES or n2 < MIN_PITCHES or v1 is None or v2 is None:
            verdict = "Small sample"
        elif kind == "sd":
            ratio = v2 / v1 if v1 else 1
            verdict = "Better" if ratio < 0.8 else "Worse" if ratio > 1.25 else verdict
        else:
            pooled = math.sqrt(((n1 - 1) * (sd1 or 0) ** 2 + (n2 - 1) * (sd2 or 0) ** 2) / max(n1 + n2 - 2, 1))
            d = (v2 - v1) / pooled if pooled else 0
            if abs(d) >= EFFECT:
                verdict = ("Higher" if d > 0 else "Lower") if direction == 0 else \
                    ("Better" if d * direction > 0 else "Worse")
        out.append(dict(metric=mid, label=f"{label} ({unit})", dp=dp, v1=v1, v2=v2,
                        change=None if v1 is None or v2 is None else v2 - v1,
                        n=f"{n1} / {n2}", verdict=verdict))
    return out


def verdict_counts(rows):
    key = {"Better": "better", "Worse": "worse", "Higher": "changed", "Lower": "changed", "No clear change": "same"}
    c = {"better": 0, "worse": 0, "changed": 0, "same": 0}
    for r in rows:
        k = key.get(r["verdict"])
        if k:
            c[k] += 1
    return c


def sessions(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["session_key"]].append(r)
    out = []
    for k, rs in by.items():
        fb = [r["velo"] for r in rs if r["pitch"] in FASTBALL_TYPES and r["velo"]]
        sp = [r["spin"] for r in rs if r["pitch"] in FASTBALL_TYPES and r["spin_ok"]]
        out.append(dict(date=rs[0]["date"], season=rs[0]["season"], type=rs[0]["session_type"], pitches=len(rs),
                        fb_velo=sum(fb) / len(fb) if fb else None, fb_max=max(fb) if fb else None,
                        fb_spin=sum(sp) / len(sp) if sp else None))
    return sorted(out, key=lambda s: s["date"], reverse=True)


# ---------------------------------------------------------------- games
def game_terms(db, player_id, rows):
    """Game numbers by term and pitch: outside splits (spring 2026 workbook)
    plus terms computed from Rapsodo pitches matched to charted GBO game
    pitches. Whiff % = whiffs / swings; CSW % = (called + whiffs) / pitches;
    runs saved per 100 = -(sum of run value) / pitches x 100."""
    from models import SeasonPitchSplit
    out = []
    for s in db.query(SeasonPitchSplit).filter(SeasonPitchSplit.player_id == player_id):
        out.append(dict(term=s.term, pitch=s.pitch_label, pitches=s.pitches, strike_pct=_f(s.strike_pct),
                        called_pct=_f(s.called_pct), whiff_pct=_f(s.whiff_pct), csw_pct=_f(s.csw_pct),
                        rs100=_f(s.runs_saved_per_100)))
    by = defaultdict(list)
    for r in rows:
        if r.get("outcome"):
            by[(r["term"], r["pitch"])].append(r)
            by[(r["term"], "All pitches")].append(r)
    pct = lambda a, b: a / b * 100 if b else None
    for (term, pitch), rs in by.items():
        n = len(rs)
        oc = [r["outcome"] for r in rs]
        balls = sum(o in ("Ball", "HBP") for o in oc)
        called = sum(o == "Called Strike" for o in oc)
        whiff = sum(o == "Swing and Miss" for o in oc)
        swings = sum(o in ("Swing and Miss", "Foul", "In Play") for o in oc)
        rv = sum(r["run_value"] or 0 for r in rs)
        out.append(dict(term=term, pitch=pitch, pitches=n, strike_pct=pct(n - balls, n), called_pct=pct(called, n),
                        whiff_pct=pct(whiff, swings), csw_pct=pct(called + whiff, n), rs100=-rv / n * 100))
    term_key = lambda t: (int(t.split()[-1]), 1 if t.startswith("Fall") else 0)
    return sorted(out, key=lambda r: (tuple(-x for x in term_key(r["term"])), r["pitch"] == "All pitches", -r["pitches"]))


STAFF_METRICS = [
    ("strike_pct", "Strike %", 1, 1), ("fps_pct", "First-pitch strike %", 1, 1), ("ea_pct", "Early-and-ahead %", 1, 1),
    ("k_pct", "K %", 1, 1), ("whiff_pct", "Whiff %", 1, 1), ("csw_pct", "Called strike + whiff %", 1, 1),
    ("putaway_pct", "Putaway %", 1, 1), ("dominance_pct", "Dominance %", 1, 1), ("gb_pct", "Ground ball %", 1, 1),
    ("oba", "Opponent average", -1, 3), ("woba", "wOBA allowed", -1, 3), ("runs_saved_per_100", "Runs saved per 100 pitches", 1, 2),
    ("whip", "WHIP", -1, 2), ("fip", "FIP", -1, 2), ("siera", "SIERA", -1, 2),
]


def staff_compare(db, player_id, term=SPRING_TERM):
    """This pitcher's line for `term` against the median of the OTHER staff
    pitchers with QUALIFIED_IP+ innings. Percentile = share of them he beat.
    Returns (line, n_staff, rows) or (None, 0, [])."""
    from models import SeasonPitchingLine
    lines = db.query(SeasonPitchingLine).filter(SeasonPitchingLine.term == term).all()
    me = next((l for l in lines if l.player_id == player_id), None)
    if me is None:
        return None, 0, []
    others = [l for l in lines if l.player_id != player_id and (_f(l.ip) or 0) >= QUALIFIED_IP]
    out = []
    for col, label, direction, dp in STAFF_METRICS:
        mine = _f(getattr(me, col))
        vals = sorted(v for v in (_f(getattr(l, col)) for l in others) if v is not None)
        mid = None
        if vals:
            k = len(vals)
            mid = vals[k // 2] if k % 2 else (vals[k // 2 - 1] + vals[k // 2]) / 2
        pct = None
        if vals and mine is not None:
            beat = sum(1 if (mine > v if direction > 0 else mine < v) else 0.5 if mine == v else 0 for v in vals)
            pct = round(beat / len(vals) * 100)
        read = "No data" if pct is None else "Above staff" if pct >= 67 else "Below staff" if pct <= 33 else "Near staff"
        out.append(dict(label=label, dp=dp, mine=mine, median=mid, pct=pct, read=read))
    return me, len(others), out
