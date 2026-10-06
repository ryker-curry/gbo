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
from strike_zone import is_in_zone

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
    """[(A, B)] back-to-back pitches in the same plate appearance by the same pitcher."""
    ordered = sorted(pitches, key=lambda p: (p.game_id, p.pitch_sequence))
    out = []
    for a, b in zip(ordered, ordered[1:]):
        if a.game_id != b.game_id or a.ends_plate_appearance:
            continue
        if b.pitch_sequence != a.pitch_sequence + 1:
            continue
        if a.pa_pitch_number is not None and b.pa_pitch_number is not None and b.pa_pitch_number != a.pa_pitch_number + 1:
            continue
        if pitcher_of(a) != pitcher_of(b):
            continue
        if a.pitch_type is None or b.pitch_type is None:
            continue
        out.append((a, b))
    return out


def _grade(bs):
    n = len(bs)
    swings = [p for p in bs if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in bs if p.pitch_outcome in WHIFF_OUTCOMES]
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


def table(pitches, hands=None, side="all", count="all"):
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
        g = _grade(bs)
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
