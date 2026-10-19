"""
GBO -- Pitcher Type + attack plan (Oct 2026, Ryker: "do we have anything
similar to [athlete types] but for pitcher type ... how each pitcher
attacks or should based on arsenal?").

  1. TYPE -- one plain label from his own shapes (arsenal_plan: ride / run
     / in-between), usage and velo vs our staff:
        Kitchen Sink      4+ pitches each thrown 12%+ of the time and no pitch
                          (fastball included) over 45% -- he truly mixes
        Ride & Spin       riding fastball (vertical mover)
        Sink & Sweep      running / sinking fastball (horizontal mover)
        Strike Thrower    below-staff velo but fills the zone (66%+ strikes)
        Power Mix         everything else -- fastball-led, two or three pitches
     plus a "Power" tag when his fastball velo is top-quarter on our staff.

  2. PLAN -- a short attack plan per count stage (early / ahead / put-away)
     for same-handed and opposite-handed hitters, written with HIS pitch
     names. Standard pitch-design attack logic, not a fitted model.

  3. CHECK -- what he actually threw in games in each stage / side (most
     used pitch and its share), and for location calls (up, down, in, away)
     how often that pitch actually went there (Rapsodo locations). Each row
     is "matches", "partly" or "gap", so the coach sees where the plan and
     the games disagree.
"""

from collections import Counter, defaultdict
from statistics import median

from analytics import arsenal_plan
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from game_stats import STRIKE_OUTCOMES

MIN_USE = 12.0           # % usage for a pitch to count in the arsenal
KITCHEN_SINK_N = 4
STRIKE_THROWER_PCT = 66.0
MIN_STAGE = 8            # pitches in a stage/side before we judge it
MATCH_SHARE = 40.0       # plan pitch used this often = matches
PARTLY_SHARE = 25.0

FAMILY = {"4-Seam Fastball": "FB", "Fastball": "FB", "2-Seam Fastball": "SINK", "Sinker": "SINK",
          "Cutter": "CUT", "Slider": "SL", "Sweeper": "SL", "Slurve": "SL", "Curveball": "CB",
          "Knuckle Curve": "CB", "Changeup": "CH", "Splitter": "CH"}
FALLBACK = {"SINK": ["FB"], "FB": ["SINK"], "CB": ["SL", "CUT"], "SL": ["CB", "CUT"], "CH": ["SINK", "CB", "SL"],
            "CUT": ["SL", "FB"], "WHIFF": ["SL", "CB", "CH"]}

STAGES = (("early", "Early (no strikes)"), ("ahead", "Ahead / even (0-1, 1-1)"), ("behind", "Behind (2-1, 3-1)"),
          ("put", "Put-away (2 strikes)"))
SIDES = (("same", "Same-handed hitters"), ("opp", "Opposite-handed hitters"))

# type -> stage -> side -> [(family, where)]  ("where" in up/down/in/away/above/below/zone/edge)
PLANS = {
    "Ride & Spin": {
        "early": {"same": [("FB", "up")], "opp": [("FB", "up"), ("CB", "zone")]},
        "ahead": {"same": [("FB", "above"), ("SL", "away")], "opp": [("FB", "above"), ("CB", "below")]},
        "behind": {"same": [("FB", "zone")], "opp": [("FB", "zone")]},
        "put": {"same": [("SL", "below"), ("CB", "below")], "opp": [("CH", "below"), ("CB", "below")]},
    },
    "Sink & Sweep": {
        "early": {"same": [("SINK", "in")], "opp": [("SINK", "away"), ("CH", "down")]},
        "ahead": {"same": [("SL", "away")], "opp": [("CH", "down"), ("SINK", "in")]},
        "behind": {"same": [("SINK", "zone")], "opp": [("SINK", "zone"), ("CH", "zone")]},
        "put": {"same": [("SL", "away")], "opp": [("CH", "below")]},
    },
    "Power Mix": {
        "early": {"same": [("FB", "zone")], "opp": [("FB", "zone")]},
        "ahead": {"same": [("FB", "up")], "opp": [("FB", "up")]},
        "behind": {"same": [("FB", "zone")], "opp": [("FB", "zone")]},
        "put": {"same": [("WHIFF", "below")], "opp": [("WHIFF", "below")]},
    },
    "Strike Thrower": {
        "early": {"same": [("FB", "edge")], "opp": [("FB", "edge")]},
        "ahead": {"same": [("SL", "away"), ("CB", "below")], "opp": [("CH", "down"), ("CB", "below")]},
        "behind": {"same": [("FB", "edge")], "opp": [("FB", "edge"), ("CH", "zone")]},
        "put": {"same": [("WHIFF", "below")], "opp": [("WHIFF", "below")]},
    },
    "Kitchen Sink": {
        "early": {"same": [("ANY", "zone")], "opp": [("ANY", "zone")]},
        "ahead": {"same": [("SL", "away"), ("CB", "below")], "opp": [("CH", "down"), ("CB", "below")]},
        "behind": {"same": [("ANY", "zone")], "opp": [("ANY", "zone")]},
        "put": {"same": [("WHIFF", "below")], "opp": [("WHIFF", "below")]},
    },
}
WHY = {
    "Ride & Spin": "Riding fastball plays at the top of the zone; the breaking ball drops off the same tunnel. "
                   "Work up-down: fastball up, spin down.",
    "Sink & Sweep": "Sinker runs in on same-handed hitters, sweeper goes the other way. Work side to side: "
                    "in with the sinker, away with the sweeper; changeup down to opposite-handed hitters.",
    "Power Mix": "The fastball is the weapon -- attack the zone with it early, elevate it when ahead, and finish "
                 "with his best swing-and-miss pitch.",
    "Strike Thrower": "Velo isn't the weapon; strikes on the edges are. Get ahead on the corners, then expand off "
                      "the plate.",
    "Kitchen Sink": "Lots of pitches -- the edge is unpredictability. Any pitch for strike one, then lean on his "
                    "best two secondaries.",
}
WHERE_WORD = {"up": "up in the zone", "above": "above the zone", "down": "down in the zone", "below": "below the zone",
              "in": "in", "away": "away", "zone": "in the zone", "edge": "on the edges"}


def _type(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) is not None else None


def usage(pitches):
    c = Counter(_type(p) for p in pitches if _type(p) and getattr(p, "is_pitch", True) is not False)
    n = sum(c.values())
    return {t: 100.0 * k / n for t, k in c.items()} if n else {}


def classify(plan, use, strike_pct, fb_velo, staff_velos):
    """-> (type, power_tag, reasons)"""
    arsenal = [t for t, u in use.items() if u >= MIN_USE]
    q75 = sorted(staff_velos)[int(0.75 * (len(staff_velos) - 1))] if len(staff_velos) >= 4 else None
    med = median(staff_velos) if staff_velos else None
    power = bool(fb_velo and q75 and fb_velo >= q75)
    kind = (plan or {}).get("kind")
    if len(arsenal) >= KITCHEN_SINK_N and max(use.values()) < 45.0:
        return "Kitchen Sink", power, f"{len(arsenal)} pitches thrown 12%+ of the time"
    if kind == "ride":
        return "Ride & Spin", power, "riding fastball / vertical mover"
    if kind == "run":
        return "Sink & Sweep", power, "running or sinking fastball / horizontal mover"
    if strike_pct is not None and strike_pct >= STRIKE_THROWER_PCT and fb_velo and med and fb_velo < med:
        return "Strike Thrower", power, f"{strike_pct:.0f}% strikes with below-staff velo"
    return "Power Mix", power, "fastball-led, in-between shape"


def whiff_pitch(pitches):
    sw, wh = Counter(), Counter()
    for p in pitches:
        t = _type(p)
        if t and FAMILY.get(t) not in ("FB", "SINK") and p.pitch_outcome in SWING_OUTCOMES:
            sw[t] += 1
            wh[t] += p.pitch_outcome in WHIFF_OUTCOMES
    best = [(wh[t] / sw[t], t) for t in sw if sw[t] >= 8]
    return max(best)[1] if best else None


def resolve(fam, have, whiff):
    """Family code -> one of his pitch names (or None)."""
    by_fam = defaultdict(list)
    for t, u in sorted(have.items(), key=lambda kv: -kv[1]):
        by_fam[FAMILY.get(t)].append(t)
    if fam == "ANY":
        return "any pitch"
    if fam == "WHIFF":
        if whiff:
            return whiff
        for f in FALLBACK["WHIFF"]:
            if by_fam.get(f):
                return by_fam[f][0]
        return None
    if by_fam.get(fam):
        return by_fam[fam][0]
    for f in FALLBACK.get(fam, []):
        if by_fam.get(f):
            return by_fam[f][0]
    return None


def stage_of(p):
    """early = no strikes; ahead = 0-1 / 1-1; behind = 2-1 / 3-1 (hitter's
    counts -- was lumped into "early" before); put = 2 strikes."""
    s, b = p.strikes_before or 0, p.balls_before or 0
    if s >= 2:
        return "put"
    if s == 0:
        return "early"
    return "ahead" if s >= b else "behind"


def _side(p, hands, throws):
    h = hands.get(p.game_pitch_id)
    if h not in ("R", "L") or throws not in ("R", "L"):
        return None
    return "same" if h == throws else "opp"


def _at(where, xz, bat):
    x, z = xz
    inside = (x < 0) if bat == "R" else (x > 0)    # catcher's view: RHH stands on the 3B (negative) side
    return {"up": z >= 2.6, "above": z > 3.4, "down": z <= 2.4, "below": z < 1.6,
            "in": inside, "away": not inside, "zone": abs(x) <= 0.83 and 1.5 <= z <= 3.5,
            "edge": 0.45 <= abs(x) <= 1.0 or 1.3 <= z <= 1.9 or 3.1 <= z <= 3.7}[where]


def build(pitches, raps, throws, arm, rel_h, hands, loc, staff_velos, label_of=None):
    """pitches: his game pitches; raps: his Rapsodo readings; hands {gp_id: R/L};
    loc {gp_id: (x, z)}. -> dict or None."""
    plan = arsenal_plan.build_plan(raps, throws or "R", arm, rel_h, label_of=label_of) if raps else None
    real = [p for p in pitches if getattr(p, "is_pitch", True) is not False]
    if not real:
        return None
    use = usage(real)
    strikes = sum(1 for p in real if p.pitch_outcome in STRIKE_OUTCOMES)
    strike_pct = 100.0 * strikes / len(real)
    fb_velo = (plan or {}).get("fb", {}).get("velo") if plan else None
    kind, power, why_type = classify(plan, use, strike_pct, fb_velo, staff_velos)
    whiff = whiff_pitch(real)
    have = {t: u for t, u in use.items() if u >= 5}

    groups = defaultdict(list)
    for p in real:
        sd = _side(p, hands, throws)
        if sd:
            groups[(stage_of(p), sd)].append(p)
    rows = []
    for st, st_lbl in STAGES:
        for sd, sd_lbl in SIDES:
            calls = []
            for fam, where in PLANS[kind][st][sd]:
                name = resolve(fam, have, whiff)
                if name and (name, where) not in calls:
                    calls.append((name, where))
            plan_txt = " or ".join(f"{n} {WHERE_WORD[w]}" for n, w in calls) or "--"
            ps = groups.get((st, sd), [])
            actual, status, detail = "not enough pitches yet", None, ""
            if len(ps) >= MIN_STAGE:
                c = Counter(_type(p) for p in ps if _type(p))
                top, k = c.most_common(1)[0]
                actual = f"{top} {100.0 * k / len(ps):.0f}% of {len(ps)}"
                plan_names = {n for n, _w in calls if n != "any pitch"}
                share = 100.0 * sum(c[n] for n in plan_names) / len(ps) if plan_names else 100.0
                status = "match" if share >= MATCH_SHARE else ("partly" if share >= PARTLY_SHARE else "gap")
                if not calls:
                    # none of his pitches fit this spot's plan -- nothing to match against
                    status, detail = None, "no pitch in his mix fits the plan here"
                # location check for the first plan call
                if calls and calls[0][0] != "any pitch":
                    n, w = calls[0]
                    lp = [p for p in ps if _type(p) == n and p.game_pitch_id in loc]
                    if len(lp) >= 5:
                        hit = sum(1 for p in lp if _at(w, loc[p.game_pitch_id], hands.get(p.game_pitch_id)))
                        pct = 100.0 * hit / len(lp)
                        detail = f"{n} {WHERE_WORD[w]} {pct:.0f}% of the time"
                        if pct < 35 and status == "match":
                            status = "partly"
                if plan_names:
                    detail = (f"plan pitch{'es' if len(plan_names) > 1 else ''} {share:.0f}% of the time"
                              + (f"; {detail}" if detail else ""))
            rows.append({"stage": st, "stage_lbl": st_lbl, "side": sd, "side_lbl": sd_lbl, "plan": plan_txt,
                         "actual": actual, "status": status, "detail": detail})
    gaps = [r for r in rows if r["status"] == "gap"]
    lines = [WHY[kind]]
    for r in gaps[:2]:
        lines.append(f"{r['stage_lbl'].split(' (')[0]} vs {r['side_lbl'].lower()}: the plan says {r['plan']}, "
                     f"but he's throwing {r['actual'].split(' of ')[0]}.")
    if whiff:
        lines.append(f"Best swing-and-miss pitch in games: {whiff}.")
    return {"type": kind, "power": power, "why_type": why_type, "fb_velo": fb_velo, "strike_pct": strike_pct,
            "use": use, "whiff": whiff, "rows": rows, "lines": lines, "gaps": len(gaps),
            "plan_kind": (plan or {}).get("kind")}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _inputs(db, player, date_from, date_to):
    from analytics import profile_queries, sequencing
    from analytics.bullpen_metrics import average_estimated_arm_angle, pitch_type_label
    from game_stats import get_batter_hands
    pid = player.player_id
    pitches = profile_queries.get_pitcher_profile_pitches(db, pid, date_from=date_from, date_to=date_to) or []
    raps = profile_queries.get_pitcher_rapsodo_pitches(db, pid, date_from=date_from, date_to=date_to) or []
    fb_like = [r for r in raps if pitch_type_label(r) in arsenal_plan.FASTBALLS]
    arm, _n = average_estimated_arm_angle(fb_like or raps, player)
    hs = [float(r.release_height) for r in (fb_like or raps) if r.release_height is not None]
    hands = get_batter_hands(db, pitches) if pitches else {}
    loc = sequencing.loc_map(profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches]))
    return pitches, raps, arm, (sum(hs) / len(hs) if hs else None), hands, loc, pitch_type_label


def staff_fb_velos(db, date_from, date_to):
    from models import Player
    from analytics import profile_queries
    from analytics.bullpen_metrics import pitch_type_label
    out = []
    for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all():
        raps = profile_queries.get_pitcher_rapsodo_pitches(db, p.player_id, date_from=date_from, date_to=date_to) or []
        plan = arsenal_plan.build_plan(raps, p.throws or "R", None, None, label_of=pitch_type_label) if raps else None
        if plan and plan["fb"].get("velo"):
            out.append(plan["fb"]["velo"])
    return out


def for_pitcher(db, player, date_from, date_to, staff_velos=None):
    pitches, raps, arm, rel_h, hands, loc, lab = _inputs(db, player, date_from, date_to)
    if staff_velos is None:
        staff_velos = staff_fb_velos(db, date_from, date_to)
    return build(pitches, raps, player.throws, arm, rel_h, hands, loc, staff_velos, label_of=lab)


def team(db, date_from, date_to):
    """[(Player, result)] for active pitchers with charted game pitches."""
    from models import Player
    velos = staff_fb_velos(db, date_from, date_to)
    out = []
    for p in (db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
              .order_by(Player.last_name, Player.first_name).all()):
        t = for_pitcher(db, p, date_from, date_to, velos)
        if t:
            out.append((p, t))
    return out
