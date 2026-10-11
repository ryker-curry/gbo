"""
GBO -- Pitch-pair sequencing (Oct 2026).

From Ryker's article batch (Paradigm's "Sequencing vs Tunneling: What
Actually Matters" -- sequencing is pitch choice by count, hitter and
situation; GBO already had usage by count but nothing on what follows
what). Approved as "Pitch-pair sequencing", its own Pitcher Profile view.

A PAIR is two back-to-back pitches to the same hitter in the same plate
appearance (A then B). For each pair we grade what B did:

  times     how often he threw A then B
  share     of everything he threw right after an A, how often it was B
  strike %  B was a strike (called, swinging, foul, in play)
  CSW %     B was a called strike or a whiff
  whiff %   whiffs / swings on B
  chase %   swings / B's located pitches outside the zone
  in play   B put in play, and how many of those were hits

Count filter is the count BEFORE B (ahead / even / behind / two strikes,
from the pitcher's side). Batter-hand filter uses game_stats.
get_batter_hands. Charted game pitches only (needs the pitch result).
Pairs with fewer than MIN_N show in gray -- with a handful of games,
most pitchers have only a few reliable pairs.
"""

from collections import defaultdict

from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import is_in_zone, ZONE_BOTTOM, ZONE_TOP, ZONE_HALF_WIDTH

MIN_N = 8
STRIKE_OUTCOMES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
HIT_OUTCOMES = {"1B", "2B", "3B", "HR"}

COUNT_FILTERS = {"all": "All counts", "ahead": "Ahead", "even": "Even", "behind": "Behind", "two": "Two strikes"}

SHORT = {
    "4-Seam Fastball": "FB", "Fastball": "FB", "2-Seam Fastball": "2S", "Sinker": "SI", "Cutter": "CT",
    "Slider": "SL", "Sweeper": "SW", "Slurve": "SV", "Curveball": "CB", "Knuckle Curve": "KC",
    "Changeup": "CH", "Splitter": "SP",
}


def short(label):
    return SHORT.get(label, label[:3].upper() if label else "?")


def pitcher_of(p):
    return p.our_player_id if not p.is_our_team_batting else p.opponent_our_player_id


def count_bucket(p):
    b, s = p.balls_before, p.strikes_before
    if b is None or s is None:
        return None
    return "ahead" if s > b else ("even" if s == b else "behind")


def count_ok(p, flt):
    if flt == "all":
        return True
    if flt == "two":
        return p.strikes_before == 2
    return count_bucket(p) == flt


def pairs(pitches):
    """[(A, B)] back-to-back pitches in the same plate appearance by the same pitcher.
    Clock violations / intentional walks (is_pitch False) aren't pitches."""
    ordered = sorted((p for p in pitches if getattr(p, "is_pitch", True) is not False),
                     key=lambda p: (p.game_id, p.pitch_sequence))
    out = []
    for a, b in zip(ordered, ordered[1:]):
        if a.game_id != b.game_id or a.ends_plate_appearance:
            continue
        if b.pitch_sequence - a.pitch_sequence not in (1, 2):   # 2 = a clock violation in between
            continue
        if (a.pa_pitch_number is not None and b.pa_pitch_number is not None
                and b.pa_pitch_number - a.pa_pitch_number != b.pitch_sequence - a.pitch_sequence):
            continue
        if pitcher_of(a) != pitcher_of(b):
            continue
        if a.pitch_type is None or b.pitch_type is None:
            continue
        out.append((a, b))
    return out


def _grade(bs, loc=None):
    n = len(bs)
    swings = [p for p in bs if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in bs if p.pitch_outcome in WHIFF_OUTCOMES]
    if loc is not None:
        located = [p for p in bs if p.game_pitch_id in loc]
        out_zone = [p for p in located if not is_in_zone(*loc[p.game_pitch_id])]
    else:
        located = [p for p in bs if p.actual_plate_x is not None and p.actual_plate_z is not None]
        out_zone = [p for p in located if not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    chases = [p for p in out_zone if p.pitch_outcome in SWING_OUTCOMES]
    in_play = [p for p in bs if p.pitch_outcome == "In Play"]
    hits = [p for p in in_play if p.ab_outcome in HIT_OUTCOMES]

    def pct(a, b):
        return round(100.0 * a / b) if b else None
    return {
        "n": n,
        "strike": pct(sum(1 for p in bs if p.pitch_outcome in STRIKE_OUTCOMES), n),
        "csw": pct(sum(1 for p in bs if p.pitch_outcome in ("Called Strike", "Swing and Miss")), n),
        "whiff": pct(len(whiffs), len(swings)),
        "chase": pct(len(chases), len(out_zone)),
        "in_play": len(in_play), "hits": len(hits),
    }


def table(pitches, hands=None, side="all", count="all", loc=None):
    """Rows per (A, B) for one pitcher (or the team), most-thrown first."""
    prs = pairs(pitches)
    if side in ("R", "L"):
        prs = [(a, b) for a, b in prs if (hands or {}).get(b.game_pitch_id) == side]
    prs = [(a, b) for a, b in prs if count_ok(b, count)]
    by = defaultdict(list)
    after = defaultdict(int)
    for a, b in prs:
        la, lb = a.pitch_type.type_name, b.pitch_type.type_name
        by[(la, lb)].append(b)
        after[la] += 1
    rows = []
    for (la, lb), bs in by.items():
        g = _grade(bs, loc)
        g.update(first=la, second=lb, label=f"{short(la)} → {short(lb)}",
                 share=round(100.0 * len(bs) / after[la]) if after[la] else None,
                 reliable=len(bs) >= MIN_N, same=la == lb)
        rows.append(g)
    rows.sort(key=lambda r: (-r["n"], r["label"]))
    return {"rows": rows, "total": len(prs)}


def team_lookup(team_pitches, hands=None, side="all", count="all"):
    """{(A, B): row} over every pitch our staff threw -- the comparison column."""
    return {(r["first"], r["second"]): r for r in table(team_pitches, hands, side, count)["rows"]}


def takeaways(rows, min_n=MIN_N):
    """Up to two plain-English lines: best and worst reliable pair by CSW %."""
    rel = [r for r in rows if r["reliable"] and r["csw"] is not None]
    if len(rel) < 2:
        return []
    best = max(rel, key=lambda r: r["csw"])
    worst = min(rel, key=lambda r: r["csw"])
    if best["csw"] - worst["csw"] < 10:
        return [f"No pair stands out -- CSW % runs {worst['csw']}-{best['csw']}% across his regular pairs."]
    return [f"Best follow-up: {best['label']} ({best['csw']}% CSW over {best['n']}).",
            f"Weakest: {worst['label']} ({worst['csw']}% CSW over {worst['n']})."]



# =====================================================================
# Oct 2026 rebuild (Ryker: "the current sequencing chart is confusing")
# -- four plain questions instead of one table. Location is Rapsodo's
# (plate_x_ft / plate_z_ft on the linked RapsodoPitch), never video
# review (Ryker: "just use the location from rapsodo").
# =====================================================================

_THIRD_H = (ZONE_TOP - ZONE_BOTTOM) / 3
_THIRD_W = 2 * ZONE_HALF_WIDTH / 3
TYPE_ORDER = ["FB", "2S", "SI", "CT", "SL", "SW", "SV", "CB", "KC", "CH", "SP"]


def height(z):
    """'up' / 'mid' / 'down' -- zone thirds, anything above/below counts as up/down."""
    if z is None:
        return None
    if z >= ZONE_BOTTOM + 2 * _THIRD_H:
        return "up"
    if z < ZONE_BOTTOM + _THIRD_H:
        return "down"
    return "mid"


def inside(x, hand):
    """Feet toward the hitter (+ = in on him). plate x is negative toward the
    3B side, where a right-handed hitter stands."""
    if x is None or hand not in ("R", "L"):
        return None
    return -x if hand == "R" else x


def side_of(x, hand):
    i = inside(x, hand)
    if i is None:
        return None
    if i >= _THIRD_W / 2:
        return "in"
    if i <= -_THIRD_W / 2:
        return "away"
    return "mid"


def loc_map(rapsodo_by_gp):
    """{game_pitch_id: (x, z)} from profile_queries.rapsodo_by_game_pitch_id."""
    out = {}
    for gp_id, r in (rapsodo_by_gp or {}).items():
        if r.plate_x_ft is not None and r.plate_z_ft is not None:
            out[gp_id] = (float(r.plate_x_ft), float(r.plate_z_ft))
    return out


def _filtered_pairs(pitches, hands, side, count):
    prs = pairs(pitches)
    if side in ("R", "L"):
        prs = [(a, b) for a, b in prs if (hands or {}).get(b.game_pitch_id) == side]
    return [(a, b) for a, b in prs if count_ok(b, count)]


def _type_key(label):
    sh = short(label)
    return (TYPE_ORDER.index(sh) if sh in TYPE_ORDER else 99, sh)


def grid(pitches, hands=None, side="all", count="all", team_pitches=None, loc=None):
    """'What does he throw next?' -- {types: [...], cells: {(A, B): {...}}, after: {A: n}}.
    Each cell: share of next pitches after A, n, csw, team_csw, verdict
    ('better' / 'worse' / 'same' / 'thin')."""
    res = table(pitches, hands, side, count, loc)
    team = team_lookup(team_pitches, hands, side, count) if team_pitches is not None else {}
    used = defaultdict(int)
    after = defaultdict(int)
    for r in res["rows"]:
        used[r["first"]] += r["n"]
        used[r["second"]] += r["n"]
        after[r["first"]] += r["n"]
    types = sorted(used, key=_type_key)
    cells = {}
    for r in res["rows"]:
        t = team.get((r["first"], r["second"]))
        tc = t["csw"] if t else None
        if not r["reliable"] or r["csw"] is None:
            verdict = "thin"
        elif tc is None:
            verdict = "same"
        elif r["csw"] - tc >= 8:
            verdict = "better"
        elif r["csw"] - tc <= -8:
            verdict = "worse"
        else:
            verdict = "same"
        cells[(r["first"], r["second"])] = {"share": r["share"], "n": r["n"], "csw": r["csw"], "whiff": r["whiff"],
                                            "team_csw": tc, "verdict": verdict}
    return {"types": types, "cells": cells, "after": dict(after), "rows": res["rows"], "total": res["total"]}


PREDICTABLE_SHARE = 70
PREDICTABLE_MIN_N = 5


def predictability(pitches, hands=None, side="all"):
    """'Is he predictable?' -- for each (count before the pitch, previous pitch
    type): what comes next and how often. Rows sorted most predictable first;
    flagged when the top pitch is >= PREDICTABLE_SHARE % over >= PREDICTABLE_MIN_N."""
    by = defaultdict(lambda: defaultdict(int))
    for a, b in _filtered_pairs(pitches, hands, side, "all"):
        if b.balls_before is None or b.strikes_before is None:
            continue
        by[(b.balls_before, b.strikes_before, a.pitch_type.type_name)][b.pitch_type.type_name] += 1
    rows = []
    for (balls, strikes, prev), nxt in by.items():
        n = sum(nxt.values())
        top, top_n = max(nxt.items(), key=lambda kv: (kv[1], kv[0]))
        share = round(100.0 * top_n / n)
        mix = sorted(nxt.items(), key=lambda kv: -kv[1])
        rows.append({
            "count": f"{balls}-{strikes}", "balls": balls, "strikes": strikes, "after": prev,
            "n": n, "top": top, "top_share": share,
            "mix": " · ".join(f"{short(t)} {round(100.0 * k / n)}%" for t, k in mix),
            "flag": n >= PREDICTABLE_MIN_N and share >= PREDICTABLE_SHARE,
            "reliable": n >= PREDICTABLE_MIN_N,
        })
    rows.sort(key=lambda r: (not r["flag"], not r["reliable"], -r["top_share"], -r["n"]))
    return rows


def count_mix(pitches, hands=None, side="all"):
    """What he throws in each count, ignoring the previous pitch -- the
    baseline for predictability. {count: (n, top type, top share)}."""
    by = defaultdict(lambda: defaultdict(int))
    for p in pitches:
        if getattr(p, "is_pitch", True) is False or p.pitch_type is None or p.balls_before is None:
            continue
        if side in ("R", "L") and (hands or {}).get(p.game_pitch_id) != side:
            continue
        by[f"{p.balls_before}-{p.strikes_before}"][p.pitch_type.type_name] += 1
    out = {}
    for c, d in by.items():
        n = sum(d.values())
        top, k = max(d.items(), key=lambda kv: kv[1])
        out[c] = (n, top, round(100.0 * k / n))
    return out


VERT_MOVES = [("down", "Went down"), ("up", "Went up"), ("same", "Same height")]
HORZ_MOVES = [("in", "Went in"), ("away", "Went away"), ("same", "Same side")]


def location_moves(pitches, loc, hands=None, side="all", count="all"):
    """'Changing eye level / sides' -- pairs graded by where the 2nd pitch
    went relative to the 1st (Rapsodo location on both). Vertical: >= 0.75 ft
    lower / higher, or within 0.33 ft = same height. Horizontal is from the
    hitter's side (needs his hand): >= 0.5 ft in / away, within 0.25 ft = same."""
    vert, horz = defaultdict(list), defaultdict(list)
    used = 0
    for a, b in _filtered_pairs(pitches, hands, side, count):
        la, lb = loc.get(a.game_pitch_id), loc.get(b.game_pitch_id)
        if la is None or lb is None:
            continue
        used += 1
        dz = lb[1] - la[1]
        if dz <= -0.75:
            vert["down"].append(b)
        elif dz >= 0.75:
            vert["up"].append(b)
        elif abs(dz) <= 0.33:
            vert["same"].append(b)
        hand = (hands or {}).get(b.game_pitch_id)
        ia, ib = inside(la[0], hand), inside(lb[0], hand)
        if ia is not None and ib is not None:
            di = ib - ia
            if di >= 0.5:
                horz["in"].append(b)
            elif di <= -0.5:
                horz["away"].append(b)
            elif abs(di) <= 0.25:
                horz["same"].append(b)

    def rows(groups, moves):
        out = []
        for key, label in moves:
            bs = groups.get(key, [])
            g = _grade(bs, loc)
            g.update(key=key, label=label, reliable=len(bs) >= MIN_N)
            out.append(g)
        return out
    return {"vertical": rows(vert, VERT_MOVES), "horizontal": rows(horz, HORZ_MOVES), "pairs_used": used}


def plate_appearances(pitches):
    """[[pitch, ...]] per plate appearance (this pitcher's pitches, in order),
    complete ones only (last pitch ends the PA)."""
    ordered = sorted((p for p in pitches if getattr(p, "is_pitch", True) is not False or p.ends_plate_appearance),
                     key=lambda p: (p.game_id, p.pitch_sequence))
    pas, cur = [], []
    for p in ordered:
        if cur and (p.game_id != cur[-1].game_id or (p.pa_pitch_number or 1) <= (cur[-1].pa_pitch_number or 0)):
            cur = []   # a PA we didn't see end (pitching change, missing rows)
        cur.append(p)
        if p.ends_plate_appearance:
            pas.append(cur)
            cur = []
    return pas


def tag(p, loc):
    """'FB up' style label -- type plus Rapsodo height when known."""
    t = short(p.pitch_type.type_name) if p.pitch_type else "?"
    xy = (loc or {}).get(p.game_pitch_id)
    h = height(xy[1]) if xy else None
    return f"{t} {h}" if h and h != "mid" else t


K_RESULTS = ("K", "K (Looking)")
WALK_RESULTS = ("BB", "IBB", "HBP")


def finishing(pitches, loc=None, hands=None, side="all"):
    """'How does he finish hitters?' -- at-bats that reached two strikes.
    setups: (setup pitch, finishing pitch) -> K / hit / walk / other out.
    k_seqs: most common last-3-pitch sequences that ended in a strikeout."""
    setups = defaultdict(lambda: {"n": 0, "k": 0, "hit": 0, "walk": 0, "out": 0})
    k_seqs = defaultdict(int)
    two_strike_pas = 0
    for pa in plate_appearances(pitches):
        real = [p for p in pa if getattr(p, "is_pitch", True) is not False and p.pitch_type is not None]
        if not real:
            continue
        last = pa[-1]
        if side in ("R", "L") and (hands or {}).get(last.game_pitch_id) != side:
            continue
        if last.ab_outcome == "No Result":
            continue
        reached_two = any((p.strikes_before or 0) == 2 for p in real)
        if last.ab_outcome in K_RESULTS and len(real) >= 3:
            k_seqs[" → ".join(tag(p, loc) for p in real[-3:])] += 1
        if not reached_two or len(real) < 2 or last.is_pitch is False:
            continue
        two_strike_pas += 1
        key = (tag(real[-2], loc), tag(real[-1], loc))
        d = setups[key]
        d["n"] += 1
        res = last.ab_outcome
        if res in K_RESULTS:
            d["k"] += 1
        elif res in HIT_OUTCOMES:
            d["hit"] += 1
        elif res in WALK_RESULTS:
            d["walk"] += 1
        else:
            d["out"] += 1
    rows = []
    for (s1, s2), d in setups.items():
        rows.append({"setup": s1, "finish": s2, "label": f"{s1} → {s2}", **d,
                     "k_pct": round(100.0 * d["k"] / d["n"]) if d["n"] else None,
                     "reliable": d["n"] >= 4})
    rows.sort(key=lambda r: (-r["n"], -(r["k_pct"] or 0)))
    seqs = sorted(k_seqs.items(), key=lambda kv: -kv[1])[:5]
    return {"rows": rows, "k_seqs": seqs, "two_strike_pas": two_strike_pas}
