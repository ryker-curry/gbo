"""
GBO -- Hitter insights (Oct 2026, Ryker: "what else can we add for
hitters to be able to see?" -> "build 1-3. once those are complete
build 4-7"). Pure functions over one hitter's GamePitch list (as from
profile_queries.get_hitter_profile_pitches), used by Hitter Profile,
the hitter meeting report and the weekly hitter report:

  1. swing_decisions      -- every located pitch graded good swing /
                             good take / chase / taken strike / borderline
  2. attack_profile       -- how pitchers attack him: pitch mix by count,
                             location tendencies (inside/away, up/down)
  3. pitch_type_results   -- fastball / breaking / offspeed x pitcher hand
  4. first_pitch_two_strike
  7. team_percentiles     -- percentile rank vs teammates (in this module
                             so the metric math lives in one place)

Zone tiers come from strike_zone.classify_attack_zone (Heart / Shadow /
Chase / Waste -- the same Savant-style tiers Plate Discipline already
shows). Decision rules:
  Heart  : swing = good swing,  take = taken strike (bad)
  Shadow : borderline -- not graded either way, EXCEPT with 2 strikes,
           where taking a borderline pitch is the bad outcome (protect)
  Chase / Waste : swing = chase (bad), take = good take
Swing Decision % = good / graded.
"""

from collections import defaultdict

from game_stats import HIT_OUTCOMES, K_OUTCOMES, get_pitcher_hands, get_batter_hands
from pitch_type_config import FASTBALL_TYPES
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES, CONTACT_OUTCOMES
from strike_zone import classify_attack_zone, is_in_zone

TB = {"1B": 1, "2B": 2, "3B": 3, "HR": 4}
HARD_CONTACT = {"Barreled/Squared Up", "Solid"}
NON_AB = {"BB", "HBP", "Sac Bunt", "Sac Fly", "No Result", "CI"}

FAMILIES = ("Fastball", "Breaking", "Offspeed")
_BREAKING = {"Slider", "Curveball", "Sweeper", "Knuckle Curve", "Slurve"}
_OFFSPEED = {"Changeup", "Splitter", "Forkball", "Knuckleball"}

DECISIONS = ("Good swing", "Good take", "Chase", "Taken strike", "Borderline")
DECISION_COLORS = {"Good swing": "#3FB27F", "Good take": "#4C8DF6", "Chase": "#D64545",
                   "Taken strike": "#F2A65A", "Borderline": "#7A8594"}


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


def _rate(a, b, d=3):
    return round(a / b, d) if b else None


def family(p):
    name = p.pitch_type.type_name if getattr(p, "pitch_type", None) else None
    if name is None:
        return None
    if name in FASTBALL_TYPES or name in ("Sinker", "Cutter"):
        # Cutter grouped with fastballs: thrown near fastball speed and
        # hitters time it like one.
        return "Fastball"
    if name in _BREAKING:
        return "Breaking"
    if name in _OFFSPEED:
        return "Offspeed"
    return "Breaking" if "curve" in name.lower() or "slid" in name.lower() else "Offspeed"


def _loc(p):
    if p.actual_plate_x is None or p.actual_plate_z is None:
        return None
    return float(p.actual_plate_x), float(p.actual_plate_z)


def _swung(p):
    return p.pitch_outcome in SWING_OUTCOMES


def plate_appearances(pitches):
    """Group one hitter's pitches into PAs (a new PA starts at pitch #1,
    a new game, or after a PA-ending pitch -- so a PA cut short by an
    inning-ending caught stealing doesn't merge into his next one)."""
    ps = sorted(pitches, key=lambda p: (getattr(p, "game_id", 0) or 0, p.pitch_sequence or 0))
    pas, cur = [], []
    for p in ps:
        if cur and (p.pa_pitch_number == 1 or p.game_id != cur[-1].game_id or cur[-1].ends_plate_appearance):
            pas.append(cur)
            cur = []
        cur.append(p)
    if cur:
        pas.append(cur)
    return pas


def _slash(pas):
    """AVG/SLG/OBP/K%/BB% over completed PAs."""
    done = [pa for pa in pas if pa[-1].ends_plate_appearance and pa[-1].ab_outcome not in (None, "No Result")]
    ends = [pa[-1].ab_outcome for pa in done]
    ab = sum(1 for o in ends if o not in NON_AB)
    hits = sum(1 for o in ends if o in HIT_OUTCOMES)
    tb = sum(TB.get(o, 0) for o in ends)
    bb = sum(1 for o in ends if o == "BB")
    hbp = sum(1 for o in ends if o == "HBP")
    sf = sum(1 for o in ends if o == "Sac Fly")
    k = sum(1 for o in ends if o in K_OUTCOMES)
    return {"PA": len(done), "AB": ab, "H": hits, "AVG": _rate(hits, ab), "SLG": _rate(tb, ab),
            "OBP": _rate(hits + bb + hbp, ab + bb + hbp + sf), "K%": _pct(k, len(done)), "BB%": _pct(bb, len(done)),
            "K": k, "BB": bb}


# ---------------------------------------------------------------------------
# 1. Swing decisions
# ---------------------------------------------------------------------------

def decision_of(p):
    loc = _loc(p)
    if loc is None or p.pitch_outcome is None or p.pitch_outcome == "HBP":
        return None
    tier = classify_attack_zone(*loc)
    swung = _swung(p)
    two_k = (p.strikes_before or 0) >= 2
    if tier == "Heart":
        return "Good swing" if swung else "Taken strike"
    if tier == "Shadow":
        if two_k:
            return "Good swing" if swung else "Taken strike"
        return "Borderline"
    return "Chase" if swung else "Good take"


def swing_decisions(pitches):
    graded = []
    for p in pitches:
        d = decision_of(p)
        if d is not None:
            graded.append((p, d))
    counts = {d: sum(1 for _p, dd in graded if dd == d) for d in DECISIONS}
    scored = sum(counts[d] for d in ("Good swing", "Good take", "Chase", "Taken strike"))
    good = counts["Good swing"] + counts["Good take"]
    tiers = []
    for tier in ("Heart", "Shadow", "Chase", "Waste"):
        tp = [p for p, _d in graded if classify_attack_zone(*_loc(p)) == tier]
        sw = [p for p in tp if _swung(p)]
        tiers.append({
            "Zone": tier, "Pitches": len(tp), "Swing %": _pct(len(sw), len(tp)),
            "Whiff %": _pct(sum(1 for p in sw if p.pitch_outcome in WHIFF_OUTCOMES), len(sw)),
            "Ideal": {"Heart": "Swing", "Shadow": "Your call (protect w/ 2 strikes)",
                      "Chase": "Take", "Waste": "Take"}[tier],
        })
    return {
        "graded": graded, "counts": counts, "score": _pct(good, scored), "scored": scored,
        "chase_pct": _pct(counts["Chase"], counts["Chase"] + counts["Good take"]),
        "heart_take_pct": _pct(counts["Taken strike"], counts["Taken strike"] + counts["Good swing"]),
        "tiers": tiers,
    }


# ---------------------------------------------------------------------------
# 2. How pitchers attack me
# ---------------------------------------------------------------------------

COUNT_BUCKETS = ("First pitch", "Hitter ahead", "Even", "Pitcher ahead", "Two strikes")


def count_bucket(p):
    b, s = p.balls_before or 0, p.strikes_before or 0
    if b == 0 and s == 0:
        return "First pitch"
    if s >= 2:
        return "Two strikes"
    if b > s:
        return "Hitter ahead"
    if s > b:
        return "Pitcher ahead"
    return "Even"


def _side(p, bat_hand):
    """'In' / 'Middle' / 'Away' for this batter. Catcher's view: x + is the
    first-base side; a righty stands on the third-base (x -) side, so
    inside to a righty is x < 0."""
    loc = _loc(p)
    if loc is None or bat_hand not in ("R", "L"):
        return None
    x = loc[0] if bat_hand == "L" else -loc[0]
    third = 0.708 / 3
    return "In" if x > third else ("Away" if x < -third else "Middle")


def attack_profile(db, pitches, hand=None):
    """hand: None (all), 'R' or 'L' pitchers."""
    phands = get_pitcher_hands(db, pitches)
    bhands = get_batter_hands(db, pitches)
    ps = [p for p in pitches if hand is None or phands.get(p.game_pitch_id) == hand]
    mix = []
    for bucket in COUNT_BUCKETS:
        bp = [p for p in ps if count_bucket(p) == bucket]
        fam = defaultdict(int)
        for p in bp:
            f = family(p)
            if f:
                fam[f] += 1
        n = sum(fam.values())
        located = [p for p in bp if _loc(p)]
        inz = sum(1 for p in located if is_in_zone(*_loc(p)))
        mix.append({"Count": bucket, "Pitches": len(bp),
                    **{f: _pct(fam[f], n) for f in FAMILIES},
                    "In zone %": _pct(inz, len(located))})
    located = [p for p in ps if _loc(p)]
    sides = defaultdict(int)
    heights = defaultdict(int)
    for p in located:
        sd = _side(p, bhands.get(p.game_pitch_id))
        if sd:
            sides[sd] += 1
        z = _loc(p)[1]
        heights["Up" if z > 2.83 else ("Down" if z < 2.17 else "Middle")] += 1
    ns, nh = sum(sides.values()), sum(heights.values())
    by_family_loc = {f: [(p, _loc(p)) for p in located if family(p) == f] for f in FAMILIES}
    return {
        "n": len(ps), "located": len(located), "mix": mix,
        "sides": {k: _pct(sides[k], ns) for k in ("In", "Middle", "Away")},
        "heights": {k: _pct(heights[k], nh) for k in ("Up", "Middle", "Down")},
        "by_family_loc": by_family_loc,
        "bat_hands": bhands,
    }


def attack_takeaways(prof):
    lines = []
    first = next((m for m in prof["mix"] if m["Count"] == "First pitch"), None)
    two = next((m for m in prof["mix"] if m["Count"] == "Two strikes"), None)
    if first and first["Pitches"] >= 8:
        fb = first.get("Fastball") or 0
        lines.append(f"First pitch: fastball {fb:.0f}% of the time"
                     + (f", in the zone {first['In zone %']:.0f}%." if first["In zone %"] is not None else "."))
    if two and two["Pitches"] >= 8:
        top = max(FAMILIES, key=lambda f: two.get(f) or 0)
        lines.append(f"With two strikes they go {top.lower()} most ({two[top]:.0f}%).")
    s = prof["sides"]
    if all(s[k] is not None for k in s) and prof["located"] >= 15:
        if (s["Away"] or 0) >= 45:
            lines.append(f"They work you away -- {s['Away']:.0f}% of located pitches on the outer third or off.")
        elif (s["In"] or 0) >= 40:
            lines.append(f"They come inside -- {s['In']:.0f}% of located pitches on the inner third or in.")
    h = prof["heights"]
    if prof["located"] >= 15 and (h["Down"] or 0) >= 45:
        lines.append(f"They live down -- {h['Down']:.0f}% of pitches at the bottom of the zone or below.")
    elif prof["located"] >= 15 and (h["Up"] or 0) >= 40:
        lines.append(f"They elevate -- {h['Up']:.0f}% of pitches at the top of the zone or above.")
    return lines


# ---------------------------------------------------------------------------
# 3. Results by pitch type
# ---------------------------------------------------------------------------

def _family_row(ps, label):
    sw = [p for p in ps if _swung(p)]
    located = [p for p in ps if _loc(p)]
    out = [p for p in located if not is_in_zone(*_loc(p))]
    chase = [p for p in out if _swung(p)]
    ends = [p for p in ps if p.ends_plate_appearance and p.ab_outcome not in (None, "No Result")]
    ab = [p for p in ends if p.ab_outcome not in NON_AB]
    hits = sum(1 for p in ab if p.ab_outcome in HIT_OUTCOMES)
    tb = sum(TB.get(p.ab_outcome, 0) for p in ab)
    bip = [p for p in ps if p.pitch_outcome == "In Play"]
    hard = [p for p in bip if (p.contact_quality or "") in HARD_CONTACT]
    return {"Pitch": label, "Seen": len(ps), "Swing %": _pct(len(sw), len(ps)),
            "Whiff %": _pct(sum(1 for p in sw if p.pitch_outcome in WHIFF_OUTCOMES), len(sw)),
            "Chase %": _pct(len(chase), len(out)), "AB": len(ab), "AVG": _rate(hits, len(ab)),
            "SLG": _rate(tb, len(ab)), "Hard contact %": _pct(len(hard), len(bip)),
            "K": sum(1 for p in ends if p.ab_outcome in K_OUTCOMES)}


def pitch_type_results(db, pitches):
    """{'All': rows, 'vs RHP': rows, 'vs LHP': rows}; each rows list has one
    row per family plus a weak-spot summary."""
    phands = get_pitcher_hands(db, pitches)
    out = {}
    for label, keep in (("All", None), ("vs RHP", "R"), ("vs LHP", "L")):
        ps = [p for p in pitches if keep is None or phands.get(p.game_pitch_id) == keep]
        out[label] = [_family_row([p for p in ps if family(p) == f], f) for f in FAMILIES]
    return out


def pitch_type_takeaways(res, min_seen=15):
    lines = []
    for split in ("vs RHP", "vs LHP"):
        rows = [r for r in res[split] if r["Seen"] >= min_seen]
        if len(rows) < 2:
            continue
        worst = max(rows, key=lambda r: (r["Whiff %"] or 0))
        if (worst["Whiff %"] or 0) >= 30:
            lines.append(f"{split}: {worst['Pitch'].lower()} is the problem -- {worst['Whiff %']:.0f}% whiff rate on "
                         f"{worst['Seen']} seen.")
        best = max(rows, key=lambda r: (r["SLG"] or 0))
        if best["AB"] >= 5 and (best["SLG"] or 0) >= 0.450:
            slg = f"{best['SLG']:.3f}"
            slg = slg[1:] if slg.startswith("0") else slg
            lines.append(f"{split}: you do damage on the {best['Pitch'].lower()} ({slg} SLG).")
    return lines


# ---------------------------------------------------------------------------
# 4. First pitch & two strikes
# ---------------------------------------------------------------------------

def first_pitch_two_strike(pitches):
    pas = plate_appearances(pitches)
    firsts = [pa[0] for pa in pas if pa[0].pa_pitch_number == 1]
    fp_sw = [p for p in firsts if _swung(p)]
    fp_strike = [p for p in firsts if p.pitch_outcome in ("Called Strike", "Swing and Miss", "Foul", "In Play")]
    fp_taken_k = [p for p in firsts if p.pitch_outcome == "Called Strike"]
    fp_inplay = [p for p in firsts if p.pitch_outcome == "In Play" and p.ab_outcome not in (None, "No Result")]
    fp_hits = sum(1 for p in fp_inplay if p.ab_outcome in HIT_OUTCOMES)
    fp_tb = sum(TB.get(p.ab_outcome, 0) for p in fp_inplay)
    after_strike = [pa for pa in pas if pa[0].pa_pitch_number == 1 and pa[0].pitch_outcome in
                    ("Called Strike", "Swing and Miss", "Foul")]
    after_ball = [pa for pa in pas if pa[0].pa_pitch_number == 1 and pa[0].pitch_outcome == "Ball"]
    first = {
        "PAs": len(firsts), "Swing %": _pct(len(fp_sw), len(firsts)),
        "Strike seen %": _pct(len(fp_strike), len(firsts)),
        "Took a strike %": _pct(len(fp_taken_k), len(firsts)),
        "In play": len(fp_inplay), "AVG in play": _rate(fp_hits, len(fp_inplay)),
        "SLG in play": _rate(fp_tb, len(fp_inplay)),
        "After 0-1": _slash(after_strike), "After 1-0": _slash(after_ball),
    }
    two = [pa for pa in pas if any((p.strikes_before or 0) >= 2 for p in pa)]
    two_pitches = [p for pa in two for p in pa if (p.strikes_before or 0) >= 2]
    located = [p for p in two_pitches if _loc(p)]
    out = [p for p in located if not is_in_zone(*_loc(p))]
    sw = [p for p in two_pitches if _swung(p)]
    fouls = sum(1 for p in two_pitches if p.pitch_outcome == "Foul")
    tline = _slash(two)
    twos = {
        "PAs": len(two), "K %": tline["K%"], "AVG": tline["AVG"], "SLG": tline["SLG"],
        "Chase %": _pct(sum(1 for p in out if _swung(p)), len(out)),
        "Whiff %": _pct(sum(1 for p in sw if p.pitch_outcome in WHIFF_OUTCOMES), len(sw)),
        "Contact %": _pct(sum(1 for p in sw if p.pitch_outcome in CONTACT_OUTCOMES), len(sw)),
        "Foul-offs per PA": round(fouls / len(two), 2) if two else None,
        "Pitches per PA": round(sum(len(pa) for pa in two) / len(two), 1) if two else None,
        "Looking Ks": sum(1 for pa in two if pa[-1].ab_outcome == "K (Looking)"),
    }
    return {"first": first, "two": twos}


# ---------------------------------------------------------------------------
# Core numbers (used by percentiles, meeting report, weekly report)
# ---------------------------------------------------------------------------

def core_metrics(pitches):
    pas = plate_appearances(pitches)
    line = _slash(pas)
    sd = swing_decisions(pitches)
    sw = [p for p in pitches if _swung(p)]
    located = [p for p in pitches if _loc(p)]
    inz = [p for p in located if is_in_zone(*_loc(p))]
    bip = [p for p in pitches if p.pitch_outcome == "In Play"]
    hard = [p for p in bip if (p.contact_quality or "") in HARD_CONTACT]
    fp = first_pitch_two_strike(pitches)
    # Oct 2026: Quality at-bats (Brian Cain's definition, game_stats.
    # _is_quality_at_bat -- the same check Hitter Game Report uses).
    from game_stats import _is_quality_at_bat
    done = [pa for pa in pas if pa[-1].ends_plate_appearance and pa[-1].ab_outcome not in (None, "No Result")]
    qab = sum(1 for pa in done if _is_quality_at_bat(pa))
    return {
        "QAB": qab, "QAB%": _pct(qab, len(done)),
        "pitches": len(pitches), "PA": line["PA"], "AVG": line["AVG"], "OBP": line["OBP"], "SLG": line["SLG"],
        "K%": line["K%"], "BB%": line["BB%"], "H": line["H"], "AB": line["AB"], "K": line["K"], "BB": line["BB"],
        # Oct 2026 audit (Ryker): ONE Chase % everywhere -- the standard
        # definition, any swing at a pitch outside the strike zone (same as
        # Plate Discipline / FanGraphs O-Swing%). Swing Decisions' own
        # "swung at a clear ball" rate is sd["chase_pct"], labelled differently.
        "Swing Decision %": sd["score"],
        "Chase %": _pct(sum(1 for p in located if not is_in_zone(*_loc(p)) and _swung(p)),
                        sum(1 for p in located if not is_in_zone(*_loc(p)))),
        "Zone Swing %": _pct(sum(1 for p in inz if _swung(p)), len(inz)),
        "Whiff %": _pct(sum(1 for p in sw if p.pitch_outcome in WHIFF_OUTCOMES), len(sw)),
        "Hard contact %": _pct(len(hard), len(bip)),
        "Pitches/PA": round(len(pitches) / len(pas), 2) if pas else None,
        "2-strike K %": fp["two"]["K %"],
    }


# metric -> (label, higher_is_better, what it means)
PERCENTILE_METRICS = [
    ("AVG", "AVG", True, "Hits per at-bat"),
    ("OBP", "OBP", True, "How often you get on base"),
    ("SLG", "SLG", True, "Total bases per at-bat"),
    ("Swing Decision %", "Swing decisions", True, "Swung at strikes, took balls"),
    ("Chase %", "Chase %", False, "Swings at pitches off the plate"),
    ("Zone Swing %", "Zone swing %", True, "Swings at pitches in the zone"),
    ("Whiff %", "Whiff %", False, "Misses per swing"),
    ("K%", "K %", False, "Strikeouts per plate appearance"),
    ("BB%", "BB %", True, "Walks per plate appearance"),
    ("Hard contact %", "Hard contact %", True, "Barreled or solid contact per ball in play"),
    ("Pitches/PA", "Pitches per PA", True, "Makes the pitcher work"),
    ("QAB%", "Quality at-bat %", True, "Brian Cain QABs per PA (goal: 54% a game, .500 season)"),
]
MIN_PA_FOR_RANK = 10


def team_percentiles(pitches_by_player, player_id):
    """{metric: {"value", "pct", "label", "desc", "n_players"}} -- true
    percentile rank among teammates with MIN_PA_FOR_RANK+ PAs in the same
    window (the player himself is always included so he gets a rank).
    0 = worst on the team, 100 = best."""
    metrics = {pid: core_metrics(ps) for pid, ps in pitches_by_player.items()}
    pool = {pid: m for pid, m in metrics.items() if (m["PA"] or 0) >= MIN_PA_FOR_RANK or pid == player_id}
    mine = metrics.get(player_id)
    out = {}
    if mine is None:
        return out
    for key, label, hib, desc in PERCENTILE_METRICS:
        v = mine.get(key)
        vals = [m.get(key) for m in pool.values() if m.get(key) is not None]
        if v is None or len(vals) < 2:
            out[key] = {"value": v, "pct": None, "label": label, "desc": desc, "n_players": len(vals)}
            continue
        if hib:
            below = sum(1 for x in vals if x < v)
        else:
            below = sum(1 for x in vals if x > v)
        ties = sum(1 for x in vals if x == v) - 1
        pct = round(100.0 * (below + 0.5 * ties) / (len(vals) - 1)) if len(vals) > 1 else None
        out[key] = {"value": v, "pct": pct, "label": label, "desc": desc, "n_players": len(vals)}
    return out


# ---------------------------------------------------------------------------
# 2b. Count-by-count attack plan (Oct 2026, Ryker: "show the different count
# states and the percentage of pitches thrown ... a trend of what location
# pitchers tend to throw pitches in certain counts. like do they try to go
# fastballs hard in late or go away?")
#
# Locations are from the HITTER's side of the plate: In / Middle / Away
# (inner third / middle third / outer third, extended past the plate) and
# Up / Middle / Down (thirds of the zone, extended above/below it).
# ---------------------------------------------------------------------------

COUNTS = ("0-0", "1-0", "0-1", "2-0", "1-1", "0-2", "3-0", "2-1", "1-2", "3-1", "2-2", "3-2")
COUNT_GROUPS = {
    "Hitter's counts": ("1-0", "2-0", "3-0", "2-1", "3-1"),
    "Even": ("0-0", "1-1", "2-2"),
    "Pitcher's counts": ("0-1", "0-2", "1-2"),
    "Two strikes": ("0-2", "1-2", "2-2", "3-2"),
}
H_CELLS = ("In", "Middle", "Away")
V_CELLS = ("Up", "Middle", "Down")
MIN_TENDENCY = 6          # located pitches of a family in a count before calling a tendency
TENDENCY_PCT = 40.0       # a cell (or half) has to hold this share to be called out


def count_of(p):
    if p.balls_before is None or p.strikes_before is None:
        return None
    return f"{min(p.balls_before, 3)}-{min(p.strikes_before, 2)}"


def _vert(z):
    third = (3.5 - 1.5) / 3
    return "Up" if z > 3.5 - third else ("Down" if z < 1.5 + third else "Middle")


def _cell(p, bat_hand):
    loc = _loc(p)
    side = _side(p, bat_hand)
    if loc is None or side is None:
        return None
    return side, _vert(loc[1])


def count_table(db, pitches, hand=None):
    """One row per count: pitches seen there, share of all pitches he saw,
    and the mix by pitch TYPE (columns = every type he saw, most common
    first) plus fastball/breaking/offspeed and in-zone %."""
    phands = get_pitcher_hands(db, pitches)
    ps = [p for p in pitches if hand is None or phands.get(p.game_pitch_id) == hand]
    total = len(ps)
    type_counts = defaultdict(int)
    for p in ps:
        if p.pitch_type:
            type_counts[p.pitch_type.type_name] += 1
    types = [t for t, _n in sorted(type_counts.items(), key=lambda kv: -kv[1])]
    rows = []
    for c in COUNTS:
        cp = [p for p in ps if count_of(p) == c]
        n = len(cp)
        if not n:
            continue
        by_t = defaultdict(int)
        by_f = defaultdict(int)
        for p in cp:
            if p.pitch_type:
                by_t[p.pitch_type.type_name] += 1
            f = family(p)
            if f:
                by_f[f] += 1
        located = [p for p in cp if _loc(p)]
        inz = sum(1 for p in located if is_in_zone(*_loc(p)))
        rows.append({"Count": c, "Seen": n, "% of pitches": _pct(n, total),
                     "types": {t: _pct(by_t[t], n) for t in types},
                     "families": {f: _pct(by_f[f], n) for f in FAMILIES},
                     "In zone %": _pct(inz, len(located)), "located": len(located)})
    return {"rows": rows, "types": types, "total": total}


def location_grid(db, pitches, counts=None, fam=None, hand=None, _hands=None):
    """3x3 share of located pitches by (Up/Middle/Down) x (In/Middle/Away),
    hitter's side. counts: iterable of 'B-S' strings (None = all)."""
    phands, bhands = _hands or (get_pitcher_hands(db, pitches), get_batter_hands(db, pitches))
    grid = {(v, h): 0 for v in V_CELLS for h in H_CELLS}
    n = 0
    for p in pitches:
        if hand is not None and phands.get(p.game_pitch_id) != hand:
            continue
        if counts is not None and count_of(p) not in counts:
            continue
        if fam is not None and family(p) != fam:
            continue
        cell = _cell(p, bhands.get(p.game_pitch_id))
        if cell is None:
            continue
        side, vert = cell
        grid[(vert, side)] += 1
        n += 1
    return {"n": n, "pct": {k: _pct(v, n) for k, v in grid.items()}, "counts": grid}


_WORDS = {("Up", "In"): "up and in", ("Up", "Middle"): "up", ("Up", "Away"): "up and away",
          ("Middle", "In"): "in", ("Middle", "Middle"): "middle-middle", ("Middle", "Away"): "away",
          ("Down", "In"): "down and in", ("Down", "Middle"): "down", ("Down", "Away"): "down and away"}


def _describe(grid):
    """Plain-English tendency from a location_grid result, or None."""
    n = grid["n"]
    if n < MIN_TENDENCY:
        return None
    c = grid["counts"]
    cell, k = max(c.items(), key=lambda kv: kv[1])
    if 100.0 * k / n >= TENDENCY_PCT:
        return _WORDS[cell], round(100.0 * k / n), k
    halves = {
        "in": sum(c[(v, "In")] for v in V_CELLS), "away": sum(c[(v, "Away")] for v in V_CELLS),
        "up": sum(c[("Up", h)] for h in H_CELLS), "down": sum(c[("Down", h)] for h in H_CELLS),
    }
    word, k = max(halves.items(), key=lambda kv: kv[1])
    if 100.0 * k / n >= 55:
        return word, round(100.0 * k / n), k
    return None


def count_tendencies(db, pitches, hand=None):
    """Lines like '0-2 -- fastballs: up and in (45%, 9 of 20)' for every
    count (and count group) where a pitch family shows a clear location
    habit, plus how often they throw that family there."""
    out = []
    groups = [(c, (c,)) for c in COUNTS] + list(COUNT_GROUPS.items())
    table = {r["Count"]: r for r in count_table(db, pitches, hand)["rows"]}
    hands = (get_pitcher_hands(db, pitches), get_batter_hands(db, pitches))
    for label, cs in groups:
        for fam in FAMILIES:
            g = location_grid(db, pitches, cs, fam, hand, _hands=hands)
            d = _describe(g)
            if d is None:
                continue
            where, pct, k = d
            share = ""
            if len(cs) == 1 and label in table:
                share = f" -- {table[label]['families'].get(fam) or 0:.0f}% of pitches in this count are {fam.lower()}s"
            word = {"Fastball": "fastballs", "Breaking": "breaking balls", "Offspeed": "offspeed"}[fam]
            share = share.replace(f"{fam.lower()}s", word)
            out.append({"count": label, "family": fam, "where": where, "pct": pct, "k": k, "n": g["n"],
                        "group": len(cs) > 1,
                        "text": f"{', '.join(cs)}: {word} {where} ({pct}%, {k} of {g['n']}){share}"})
    return out
