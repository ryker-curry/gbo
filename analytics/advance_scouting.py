"""
GBO -- Advance Scouting Report (Oct 2026).

Ryker: build advance scouting reports (after weekly reports). Decisions
(AskUserQuestion, Oct 2026):
  - Data: our own charting (every pitch their pitchers threw to us in
    Game Tracking) + coach notes per pitcher (OpponentPlayer.notes).
  - One report = a series vs one team: staff overview with roles, a page
    per pitcher, and a series plan.
  - Staff build/edit; our hitters see it once a coach publishes it.
  - Approach points are auto-drafted from the numbers; a coach edits
    them before publishing.
  - WHICH pitcher threw each pitch comes from Game Tracking's new "Their
    pitcher" picker (GamePitch.opponent_player_id while we bat). Games
    before the picker existed stay team-level ("Unidentified RHP/LHP");
    nothing is backfilled onto their listed starter (Ryker's call -- we
    don't know when they changed pitchers).

FRAMES
  Batter hand = OUR hitter's (game_stats.get_batter_hands). Location
  grid is the catcher's view of plate_x with "in"/"away" relative to the
  hitter: inside to a RHH = third-base side (plate_x < 0).
"""

from collections import Counter, defaultdict

from sqlalchemy.orm import joinedload

from models import Game, GamePitch, OpponentPlayer, OpponentTeam
from game_stats import get_batter_hands
from pitch_type_config import FASTBALL_TYPES

STRIKES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
SWINGS = {"Swing and Miss", "Foul", "In Play"}
HITS = {"1B", "2B", "3B", "HR"}
NON_AB = {"BB", "IBB", "HBP", "Sac Bunt", "Sac Fly"}
KS = {"K", "K (Looking)", "K - Reached on Dropped 3rd"}
ROLES = ["", "Fri", "Sat", "Sun", "Starter", "Closer", "Setup", "Long", "Bullpen", "Not expected"]
STARTER_ROLES = ("Fri", "Sat", "Sun", "Starter")
MIN_PLAN_PITCHES = 15
X_THIRD = 0.708 / 3
Z_LOW, Z_HIGH = 2.17, 2.83


def _pct(a, b):
    return round(a / b * 100, 1) if b else None


def team_pitches(db, opponent_team_id):
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
            .filter(Game.opponent_team_id == opponent_team_id, Game.is_intrasquad.is_(False),
                    GamePitch.is_our_team_batting.is_(True))
            .order_by(Game.game_date, GamePitch.pitch_sequence).all())


def _label(p):
    return p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"


def _pas(pitches):
    by_game = defaultdict(list)
    for p in pitches:
        by_game[p.game_id].append(p)
    out = []
    for gid in by_game:
        cur = []
        for p in sorted(by_game[gid], key=lambda q: q.pitch_sequence):
            if p.pa_pitch_number == 1 and cur:
                out.append(cur)
                cur = []
            cur.append(p)
        if cur:
            out.append(cur)
    return [pa for pa in out if pa[-1].ends_plate_appearance and pa[-1].ab_outcome != "No Result"]


def _xy(p, loc=None):
    """(plate_x, plate_z): from `loc` ({game_pitch_id: (x, z)}, Rapsodo -- used
    when the pitcher is ours) when given, else the video-review location."""
    if loc is not None:
        return loc.get(p.game_pitch_id)
    if p.actual_plate_x is None or p.actual_plate_z is None:
        return None
    return float(p.actual_plate_x), float(p.actual_plate_z)


def _grid(pitches, hands, bat, loc=None):
    """3x3 % of located pitches vs one hitter hand: rows up/mid/down,
    cols in/mid/away (relative to the hitter)."""
    cells = Counter()
    n = 0
    for p in pitches:
        xy = _xy(p, loc)
        if hands.get(p.game_pitch_id) != bat or xy is None:
            continue
        x, z = xy
        in_side = -x if bat == "R" else x  # + = toward the hitter (RHH stands on the 3B side, plate_x < 0)
        col = 0 if in_side > X_THIRD else (2 if in_side < -X_THIRD else 1)
        row = 0 if z > Z_HIGH else (2 if z < Z_LOW else 1)
        cells[(row, col)] += 1
        n += 1
    if not n:
        return None
    return {"n": n, "pct": [[round(cells[(r, c)] / n * 100) for c in range(3)] for r in range(3)]}


def _rel_cell(p, bat, loc=None):
    """(row, col) relative to the hitter: rows up/mid/down, cols in/mid/away."""
    xy = _xy(p, loc)
    if bat not in ("R", "L") or xy is None:
        return None
    x, z = xy
    in_side = -x if bat == "R" else x
    col = 0 if in_side > X_THIRD else (2 if in_side < -X_THIRD else 1)
    row = 0 if z > Z_HIGH else (2 if z < Z_LOW else 1)
    return row, col


ROW_WORDS = ("up", "belt-high", "down")
COL_WORDS = ("in", "middle", "away")
MIN_CELL_SWINGS = 6


def _family(p):
    from analytics.hitter_insights import family
    return family(p)


def whiff_grids(pitches, hands, loc=None):
    """Approach panel (Oct 2026, Paradigm's "How to Beat an Ace"): where his
    pitches get swings and misses. {family: {"cells": 3x3 [whiffs, swings],
    "chase": %, "n"}}; hitter-relative, both hitter hands pooled."""
    from strike_zone import is_in_zone
    out = {}
    for fam in ("Fastball", "Breaking", "Offspeed"):
        ps = [p for p in pitches if _family(p) == fam]
        if not ps:
            continue
        cells = [[[0, 0] for _c in range(3)] for _r in range(3)]
        oz = osw = 0
        for p in ps:
            rc = _rel_cell(p, hands.get(p.game_pitch_id), loc)
            if rc is None:
                continue
            if p.pitch_outcome in SWINGS:
                cells[rc[0]][rc[1]][1] += 1
                if p.pitch_outcome == "Swing and Miss":
                    cells[rc[0]][rc[1]][0] += 1
            if not is_in_zone(*_xy(p, loc)):
                oz += 1
                osw += p.pitch_outcome in SWINGS
        out[fam] = {"cells": cells, "chase": _pct(osw, oz), "n": len(ps)}
    return out


def _batter_key(p):
    """Who was hitting: our hitter when we bat; theirs (or the intrasquad
    hitter) when we pitch."""
    if p.is_our_team_batting:
        return ("us", p.our_player_id)
    if p.opponent_player_id is not None:
        return ("opp", p.opponent_player_id)
    if getattr(p, "opponent_our_player_id", None) is not None:
        return ("us", p.opponent_our_player_id)
    return ("order", p.opponent_batting_order)


def times_through(pitches):
    """Pitch mix the 1st / 2nd / 3rd+ time a hitter sees him in a game."""
    seen = defaultdict(int)
    by = defaultdict(list)
    for pa in _pas(pitches):
        key = (pa[0].game_id, _batter_key(pa[0]))
        seen[key] += 1
        by[min(seen[key], 3)].extend(pa)
    out = []
    for t in (1, 2, 3):
        sub = by.get(t, [])
        if not sub:
            continue
        c = Counter(_label(p) for p in sub)
        top, k = c.most_common(1)[0]
        out.append({"tto": t, "n": len(sub), "fb": _pct(sum(1 for p in sub if _label(p) in FASTBALL_TYPES), len(sub)),
                    "top": top, "top_pct": _pct(k, len(sub)),
                    "strike": _pct(sum(1 for p in sub if p.pitch_outcome in STRIKES), len(sub)),
                    "mix": [(lab, _pct(v, len(sub))) for lab, v in c.most_common(4)]})
    return out


def damage_grids(db):
    """Our hitters' SLG on balls in play by hitter-relative cell, split by
    PITCHER hand (all our charted at-bats). {"R"|"L": 3x3 [tb, bip]}"""
    from analytics import profile_queries
    from game_stats import get_pitcher_hands
    team = profile_queries.get_team_hitting_pitches(db, None, None, None, "all")
    ps = [p for v in team.values() for p in v if p.pitch_outcome == "In Play"]
    if not ps:
        return {}
    bh = get_batter_hands(db, ps)
    ph = get_pitcher_hands(db, ps)
    tb = {"1B": 1, "2B": 2, "3B": 3, "HR": 4}
    out = {h: [[[0, 0] for _c in range(3)] for _r in range(3)] for h in ("R", "L")}
    for p in ps:
        h = ph.get(p.game_pitch_id)
        rc = _rel_cell(p, bh.get(p.game_pitch_id))
        if h not in out or rc is None or p.ab_outcome in ("Sac Bunt", "Sac Fly"):
            continue
        out[h][rc[0]][rc[1]][0] += tb.get(p.ab_outcome, 0)
        out[h][rc[0]][rc[1]][1] += 1
    return out


def approach_points(prof, damage, hand):
    """Lines that pair where he gets whiffs with where we do (or don't) damage."""
    pts = []
    dmg = (damage or {}).get(hand)
    for fam, g in (prof.get("whiff_grids") or {}).items():
        best = None
        for r in range(3):
            for c in range(3):
                wh, sw = g["cells"][r][c]
                if sw >= MIN_CELL_SWINGS and wh / sw >= 0.4 and (best is None or wh / sw > best[0]):
                    best = (wh / sw, r, c, wh, sw)
        if best is None:
            continue
        _rate, r, c, wh, sw = best
        where = f"{ROW_WORDS[r]} and {COL_WORDS[c]}" if (r, c) != (1, 1) else "middle-middle"
        name = {"Fastball": "fastball", "Breaking": "breaking ball", "Offspeed": "changeup"}[fam]
        line = f"His {name} gets whiffs {where} ({wh} of {sw} swings)"
        if dmg:
            t, n = dmg[r][c]
            if n >= 3:
                line += f"; we slug {t / n:.3f}".replace("0.", ".") + f" there vs {hand}HP"
                line += " -- lay off it." if t / n < 0.35 else " -- but we hit it there when we connect."
            else:
                line += " -- lay off it until two strikes."
        else:
            line += " -- lay off it until two strikes."
        pts.append((2.3, line))
    return pts


def pitcher_profile(db, pitches, hand_label=None, loc=None):
    """Everything the report shows for one of their pitchers (or one
    team-level 'Unidentified' group). loc = Rapsodo locations when the
    pitcher is ours (Self-scout); their pitchers use video review."""
    pitches = [p for p in pitches if getattr(p, "is_pitch", True) is not False]
    hands = get_batter_hands(db, pitches)
    n = len(pitches)
    pas = _pas(pitches)
    bf = len(pas)
    ab = sum(1 for pa in pas if pa[-1].ab_outcome not in NON_AB)
    hits = sum(1 for pa in pas if pa[-1].ab_outcome in HITS)
    ks = sum(1 for pa in pas if pa[-1].ab_outcome in KS)
    bbs = sum(1 for pa in pas if pa[-1].ab_outcome == "BB")
    games = sorted({p.game for p in pitches if p.game is not None}, key=lambda g: g.game_date)

    by_type = defaultdict(list)
    for p in pitches:
        by_type[_label(p)].append(p)
    n_r = sum(1 for p in pitches if hands.get(p.game_pitch_id) == "R")
    n_l = sum(1 for p in pitches if hands.get(p.game_pitch_id) == "L")
    arsenal = []
    for lab, ps in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        sw = sum(1 for p in ps if p.pitch_outcome in SWINGS)
        arsenal.append({
            "pitch": lab, "n": len(ps), "usage": _pct(len(ps), n),
            "vs_r": _pct(sum(1 for p in ps if hands.get(p.game_pitch_id) == "R"), n_r),
            "vs_l": _pct(sum(1 for p in ps if hands.get(p.game_pitch_id) == "L"), n_l),
            "strike": _pct(sum(1 for p in ps if p.pitch_outcome in STRIKES), len(ps)),
            "whiff": _pct(sum(1 for p in ps if p.pitch_outcome == "Swing and Miss"), sw),
            "is_fb": lab in FASTBALL_TYPES,
        })

    def mix(sub):
        if not sub:
            return None
        c = Counter(_label(p) for p in sub)
        top, k = c.most_common(1)[0]
        return {"n": len(sub), "fb": _pct(sum(1 for p in sub if _label(p) in FASTBALL_TYPES), len(sub)),
                "top": top, "top_pct": _pct(k, len(sub)),
                "strike": _pct(sum(1 for p in sub if p.pitch_outcome in STRIKES), len(sub)),
                "ball": _pct(sum(1 for p in sub if p.pitch_outcome == "Ball"), len(sub))}

    first = [p for p in pitches if (p.balls_before, p.strikes_before) == (0, 0)]
    ahead = [p for p in pitches if (p.strikes_before or 0) > (p.balls_before or 0)]
    behind = [p for p in pitches if (p.balls_before or 0) > (p.strikes_before or 0)]
    two_k = [p for p in pitches if p.strikes_before == 2]
    fbs = [p for p in pitches if _label(p) in FASTBALL_TYPES]
    first_swing = _pct(sum(1 for p in first if p.pitch_outcome in SWINGS), len(first))

    innings = sorted({(p.game_id, p.inning) for p in pitches})
    return {
        "hand": hand_label, "n": n, "bf": bf, "games": games, "innings": len(innings),
        "k_pct": _pct(ks, bf), "bb_pct": _pct(bbs, bf), "avg": round(hits / ab, 3) if ab else None,
        "strike": _pct(sum(1 for p in pitches if p.pitch_outcome in STRIKES), n),
        "arsenal": arsenal, "first": mix(first), "ahead": mix(ahead), "behind": mix(behind), "two_k": mix(two_k),
        "first_swing": first_swing,
        "fb_grid": {"R": _grid(fbs, hands, "R", loc), "L": _grid(fbs, hands, "L", loc)},
        "whiff_grids": whiff_grids(pitches, hands, loc), "tto": times_through(pitches),
        "count_hand": count_hand_table(pitches, hands),
        "pitches_per_inning": round(n / len(innings), 1) if innings else None,
    }


def draft_points(prof, name="He", damage=None):
    """3-4 plain approach points from the numbers (coach edits them)."""
    if not prof or prof["n"] < MIN_PLAN_PITCHES:
        return []
    pts = []
    f, b, t = prof["first"], prof["behind"], prof["two_k"]
    if f and f["n"] >= 6:
        if (f["fb"] or 0) >= 65 and (f["strike"] or 0) >= 55:
            pts.append((3, f"Hunt the 0-0 fastball -- {f['fb']:.0f}% of first pitches are heaters and {f['strike']:.0f}% are strikes. "
                           f"Be ready to hit it early."))
        elif (f["fb"] or 100) <= 50:
            pts.append((2.5, f"He steals strike one with the {f['top'].lower()} ({f['top_pct']:.0f}% of first pitches). "
                             f"Don't give it away -- be ready to ambush it or take it."))
    if b and b["n"] >= 6 and (b["fb"] or 0) >= 70:
        pts.append((2.4, f"Behind in the count it's the fastball {b['fb']:.0f}% of the time -- sit on it in hitter's counts."))
    if t and t["n"] >= 6:
        line = f"With two strikes it's the {t['top'].lower()} ({t['top_pct']:.0f}%)"
        if (t["ball"] or 0) >= 45:
            line += f" and {t['ball']:.0f}% of two-strike pitches are balls -- shrink the zone and spit on it below the knees."
        else:
            line += " -- shorten up and protect, he'll throw it in the zone."
        pts.append((2.2, line))
    for bat in ("R", "L"):
        g = prof["fb_grid"].get(bat)
        if not g or g["n"] < 8:
            continue
        rows = [sum(g["pct"][r]) for r in range(3)]
        cols = [sum(g["pct"][r][c] for r in range(3)) for c in range(3)]
        r_i = max(range(3), key=lambda i: rows[i])
        c_i = max(range(3), key=lambda i: cols[i])
        if rows[r_i] >= 45 or cols[c_i] >= 45:
            where = []
            if rows[r_i] >= 45:
                where.append(["up", "belt-high", "down"][r_i])
            if cols[c_i] >= 45:
                where.append(["in", "over the middle", "away"][c_i])
            pts.append((1.8, f"Vs {bat}HH his fastball lives {' and '.join(where)} ({max(rows[r_i], cols[c_i])}% of located fastballs)."))
    pts += approach_points(prof, damage, prof.get("hand"))
    if (prof["bb_pct"] or 0) >= 12 and prof["bf"] >= 10:
        pts.append((2.0, f"Make him throw strikes -- he's walked {prof['bb_pct']:.0f}% of our hitters."))
    if (prof["strike"] or 100) <= 58 and prof["n"] >= 30:
        pts.append((1.9, f"Only {prof['strike']:.0f}% strikes against us -- work deep counts early."))
    return [t for _s, t in sorted(pts, key=lambda x: -x[0])][:4]


def build(db, opponent_team_id, roles=None, lines=None):
    """{team, pitchers: [{player|None, name, hand, role, notes, profile, points, line}], unidentified, ...}
    lines = coach-edited one-liners {'p:<id>': text} (AdvanceReport.lines)."""
    roles = {int(k): v for k, v in (roles or {}).items() if v}
    lines = lines or {}
    team = db.query(OpponentTeam).filter(OpponentTeam.team_id == opponent_team_id).first()
    ps = team_pitches(db, opponent_team_id)
    by_pitcher = defaultdict(list)
    unknown = {"R": [], "L": []}
    for p in ps:
        if p.opponent_player_id is not None:
            by_pitcher[p.opponent_player_id].append(p)
        else:
            unknown["L" if p.opponent_hand == "L" else "R"].append(p)
    roster = {op.opponent_player_id: op for op in db.query(OpponentPlayer).filter(OpponentPlayer.team_id == opponent_team_id).all()}
    damage = damage_grids(db)
    ids = set(by_pitcher) | {pid for pid in roles} | {pid for pid, op in roster.items()
                                                      if (op.position or "").upper().startswith("P") or op.notes}
    pitchers = []
    for pid in ids:
        op = roster.get(pid)
        if op is None:
            continue
        prof = pitcher_profile(db, by_pitcher[pid], op.throws) if by_pitcher.get(pid) else None
        auto = pitcher_line(prof)
        pitchers.append({"id": pid, "player": op, "name": op.player_name, "hand": op.throws, "role": roles.get(pid, ""),
                         "notes": op.notes, "profile": prof, "points": draft_points(prof, op.player_name, damage),
                         "auto_line": auto, "line": lines.get(f"p:{pid}") or auto})
    order = {r: i for i, r in enumerate(ROLES[1:])}
    pitchers.sort(key=lambda x: (order.get(x["role"], 99), -(x["profile"]["n"] if x["profile"] else 0), x["name"]))
    unident = []
    for h in ("R", "L"):
        if unknown[h]:
            prof = pitcher_profile(db, unknown[h], h)
            unident.append({"id": None, "player": None, "name": f"Unidentified {h}HP (before 'Their pitcher' tracking)",
                            "hand": h, "role": "", "notes": None, "profile": prof, "points": draft_points(prof, damage=damage),
                            "auto_line": pitcher_line(prof), "line": pitcher_line(prof)})
    games = sorted({p.game for p in ps if p.game is not None}, key=lambda g: g.game_date)
    return {"team": team, "pitchers": pitchers, "unidentified": unident, "games": games, "n": len(ps),
            "damage": damage}


def draft_series_plan(rep):
    """Series plan draft: the top point from each starter, else from the
    most-seen pitchers; plus a staff-wide line when the whole staff
    shares a tendency."""
    lines = []
    starters = [p for p in rep["pitchers"] if p["role"] in STARTER_ROLES and p["points"]]
    pool = starters or [p for p in rep["pitchers"] + rep["unidentified"] if p["points"]][:3]
    for p in pool:
        who = f"{p['role']} -- {p['name']}" if p["role"] else p["name"]
        lines.append(f"{who}: {p['points'][0]}")
    allp = [p for p in rep["pitchers"] + rep["unidentified"] if p["profile"]]
    tot = sum(p["profile"]["n"] for p in allp)
    if tot >= 40:
        fb0 = [p["profile"]["first"] for p in allp if p["profile"]["first"]]
        n0 = sum(f["n"] for f in fb0)
        fbn = sum((f["fb"] or 0) / 100 * f["n"] for f in fb0)
        if n0 >= 15 and fbn / n0 >= 0.65:
            lines.append(f"As a staff they start hitters with a fastball {fbn / n0 * 100:.0f}% of the time -- be on time for it.")
    return "\n".join(f"{i}. {l}" for i, l in enumerate(lines[:4], 1))


# =====================================================================
# Oct 2026 upgrades (Ryker, from Paradigm's "How to Build the Perfect
# Scouting Report"): count x hand usage, one-line plans, their hitters,
# self-scout and the post-series check.
# =====================================================================

COUNT_ROWS = [("0-0", "First pitch"), ("ahead", "Ahead"), ("even", "Even"), ("behind", "Behind"), ("two", "2 strikes")]
MIN_CELL_PITCHES = 10
PREDICTABLE_PCT = 70
MIN_HITTER_PAS = 8
HARD_CONTACT = ("Barreled/Squared Up", "Solid")
FAMILY_WORDS = {"Fastball": "fastballs", "Breaking": "breaking balls", "Offspeed": "changeups"}


def _count_key(p):
    b, s = p.balls_before or 0, p.strikes_before or 0
    keys = []
    if (b, s) == (0, 0):
        keys.append("0-0")
    if s == 2:
        keys.append("two")
    if s > b:
        keys.append("ahead")
    elif s == b:
        keys.append("even")
    else:
        keys.append("behind")
    return keys


def count_hand_table(pitches, hands):
    """{count_key: {"R": cell|None, "L": cell|None}} -- cell = {n, top, top_pct,
    fb, thin}; the pitch he goes to in each count, split by OUR hitter's hand."""
    by = defaultdict(list)
    for p in pitches:
        h = hands.get(p.game_pitch_id)
        if h not in ("R", "L"):
            continue
        for k in _count_key(p):
            by[(k, h)].append(p)
    out = {}
    for key, _label_ in COUNT_ROWS:
        out[key] = {}
        for h in ("R", "L"):
            sub = by.get((key, h), [])
            if not sub:
                out[key][h] = None
                continue
            c = Counter(_label(p) for p in sub)
            top, k = c.most_common(1)[0]
            out[key][h] = {"n": len(sub), "top": top, "top_pct": _pct(k, len(sub)),
                           "fb": _pct(sum(1 for p in sub if _label(p) in FASTBALL_TYPES), len(sub)),
                           "thin": len(sub) < MIN_CELL_PITCHES}
    return out


def predictable_spots(prof):
    """Count x hand cells where one pitch comes PREDICTABLE_PCT+ of the time."""
    out = []
    for key, label in COUNT_ROWS:
        for h in ("R", "L"):
            c = ((prof or {}).get("count_hand") or {}).get(key, {}).get(h)
            if c and not c["thin"] and (c["top_pct"] or 0) >= PREDICTABLE_PCT:
                out.append({"count": label, "hand": h, "pitch": c["top"], "pct": c["top_pct"], "n": c["n"]})
    out.sort(key=lambda r: -r["pct"])
    return out


def _short(name):
    return (name or "").replace("4-Seam Fastball", "FB").replace("2-Seam Fastball", "2S").replace("Fastball", "FB")


def pitcher_line(prof):
    """One instruction for our hitters vs this pitcher (coach edits it)."""
    if not prof or prof["n"] < MIN_PLAN_PITCHES:
        return ""
    bits = []
    f, t = prof.get("first") or {}, prof.get("two_k") or {}
    if f.get("n", 0) >= 6:
        if (f.get("fb") or 0) >= 60:
            bits.append(f"Sit FB early ({f['fb']:.0f}% of first pitches)")
        elif f["top"] not in FASTBALL_TYPES and (f.get("top_pct") or 0) >= 35:
            bits.append(f"He steals strike one with the {_short(f['top'])} ({f['top_pct']:.0f}%)")
    if t.get("n", 0) >= 6:
        if t["top"] in FASTBALL_TYPES:
            bits.append(f"with 2 strikes he comes with the FB ({t['top_pct']:.0f}%) -- be on time")
        elif (t.get("ball") or 0) >= 45:
            bits.append(f"with 2 strikes it's the {_short(t['top'])} ({t['top_pct']:.0f}%) -- spit on it down")
        else:
            bits.append(f"with 2 strikes it's the {_short(t['top'])} ({t['top_pct']:.0f}%) -- shorten up")
    spots = predictable_spots(prof)
    if spots and len(bits) < 2:
        sp = spots[0]
        bits.append(f"{sp['count'].lower()} vs {sp['hand']}HH it's the {_short(sp['pitch'])} {sp['pct']:.0f}%")
    if not bits:
        return "Mixes his pitches in every count -- hunt mistakes over the plate."
    text = "; ".join(bits)
    return text[:1].upper() + text[1:] + "."


# ---------------------------------------------------------------- their hitters

def their_hitting_pitches(db, opponent_team_id):
    """Every pitch OUR pitchers threw to this team's hitters (we're in the field)."""
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
            .filter(Game.opponent_team_id == opponent_team_id, Game.is_intrasquad.is_(False),
                    GamePitch.is_our_team_batting.is_(False))
            .order_by(Game.game_date, GamePitch.pitch_sequence).all())


def _rapsodo_loc(db, pitches):
    from analytics import profile_queries, sequencing
    return sequencing.loc_map(profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches]))


def hitter_profile(pitches, bats, loc):
    """One of their hitters vs our pitchers. bats = his hand ('R'/'L'/'S'/None);
    a switch hitter is placed by the pitcher's hand (opposite side)."""
    from strike_zone import is_in_zone
    pitches = [p for p in pitches if getattr(p, "is_pitch", True) is not False]
    pas = _pas(pitches)
    res = [pa[-1].ab_outcome for pa in pas]
    ab = sum(1 for r in res if r not in NON_AB)
    hits = sum(1 for r in res if r in HITS)
    tb = sum({"1B": 1, "2B": 2, "3B": 3, "HR": 4}.get(r, 0) for r in res)
    bb = sum(1 for r in res if r in ("BB", "IBB", "HBP"))
    ks = sum(1 for r in res if r in KS)
    first = [p for p in pitches if (p.balls_before, p.strikes_before) == (0, 0)]
    located = [p for p in pitches if p.game_pitch_id in loc]
    out_zone = [p for p in located if not is_in_zone(*loc[p.game_pitch_id])]
    two_out = [p for p in out_zone if p.strikes_before == 2]

    def side(p):
        if bats in ("R", "L"):
            return bats
        if bats == "S":
            return "L" if (p.opponent_hand or "R") == "R" else "R"   # opponent_hand = our pitcher's hand here
        return None
    fam = {}
    for f in ("Fastball", "Breaking", "Offspeed"):
        ps = [p for p in pitches if _family(p) == f]
        if not ps:
            continue
        sw = [p for p in ps if p.pitch_outcome in SWINGS]
        bip = [p for p in ps if p.pitch_outcome == "In Play"]
        ftb = sum({"1B": 1, "2B": 2, "3B": 3, "HR": 4}.get(p.ab_outcome, 0) for p in bip)
        fam[f] = {"n": len(ps), "whiff": _pct(sum(1 for p in sw if p.pitch_outcome == "Swing and Miss"), len(sw)),
                  "swings": len(sw), "bip": len(bip), "slg_bip": round(ftb / len(bip), 3) if bip else None,
                  "hard": _pct(sum(1 for p in bip if p.contact_quality in HARD_CONTACT), len(bip)),
                  "hits": sum(1 for p in bip if p.ab_outcome in HITS)}
    grid = [[[0, 0] for _c in range(3)] for _r in range(3)]     # [total bases, balls in play]
    wgrid = [[[0, 0] for _c in range(3)] for _r in range(3)]    # [whiffs, swings]
    for p in pitches:
        rc = _rel_cell(p, side(p), loc)
        if rc is None:
            continue
        if p.pitch_outcome in SWINGS:
            wgrid[rc[0]][rc[1]][1] += 1
            wgrid[rc[0]][rc[1]][0] += p.pitch_outcome == "Swing and Miss"
        if p.pitch_outcome == "In Play" and p.ab_outcome not in ("Sac Bunt", "Sac Fly"):
            grid[rc[0]][rc[1]][0] += {"1B": 1, "2B": 2, "3B": 3, "HR": 4}.get(p.ab_outcome, 0)
            grid[rc[0]][rc[1]][1] += 1
    return {
        "pa": len(pas), "ab": ab, "hits": hits, "hr": sum(1 for r in res if r == "HR"),
        "avg": round(hits / ab, 3) if ab else None, "slg": round(tb / ab, 3) if ab else None,
        "obp": round((hits + bb) / len(pas), 3) if pas else None,
        "k_pct": _pct(ks, len(pas)), "bb_pct": _pct(bb, len(pas)),
        "first_swing": _pct(sum(1 for p in first if p.pitch_outcome in SWINGS), len(first)),
        "chase": _pct(sum(1 for p in out_zone if p.pitch_outcome in SWINGS), len(out_zone)),
        "two_chase": _pct(sum(1 for p in two_out if p.pitch_outcome in SWINGS), len(two_out)),
        "located": len(located), "n": len(pitches), "families": fam, "damage": grid, "whiff_grid": wgrid,
        "games": sorted({p.game for p in pitches if p.game is not None}, key=lambda g: g.game_date),
    }


def hitter_line(prof):
    """'Get him out with ___' (coach edits it)."""
    if not prof or prof["pa"] < MIN_HITTER_PAS:
        return ""
    fams = [(f, d) for f, d in prof["families"].items() if d["swings"] >= 5 or d["bip"] >= 3]
    if not fams:
        return ""

    def weakness(d):
        w = (d["whiff"] or 0) / 100
        s = d["slg_bip"] if d["slg_bip"] is not None else 0.35
        return w - s / 2
    best_f, best = max(fams, key=lambda fd: weakness(fd[1]))
    worst_f, worst = min(fams, key=lambda fd: weakness(fd[1]))
    slg = best["slg_bip"]
    clear = ((best["whiff"] or 0) >= 25 and (slg is None or slg <= 0.500)) or (slg is not None and slg <= 0.300)
    where = ""
    cells = [(prof["whiff_grid"][r][c], r, c) for r in range(3) for c in range(3)]
    good = [(wh / sw, r, c) for (wh, sw), r, c in cells if sw >= 4]
    if good:
        rate, r, c = max(good)
        if rate >= 0.35:
            where = f" {ROW_WORDS[r]} and {COL_WORDS[c]}" if (r, c) != (1, 1) else ""
    stats = []
    if best["whiff"] is not None:
        stats.append(f"{best['whiff']:.0f}% whiff")
    if best["slg_bip"] is not None:
        stats.append(f"{best['slg_bip']:.3f} SLG in play".replace("0.", ".", 1))
    if clear:
        line = f"Get him out with {FAMILY_WORDS[best_f]}{where}"
    else:
        line = f"No clear hole yet -- least damage vs {FAMILY_WORDS[best_f]}"
    if stats:
        line += f" ({', '.join(stats)})"
    if worst_f != best_f and (worst["slg_bip"] or 0) >= 0.5:
        line += f"; he damages {FAMILY_WORDS[worst_f]}"
    if (prof["chase"] or 0) >= 35:
        line += f"; chases {prof['chase']:.0f}%, expand late"
    return line + "."


def usual_order(db, opponent_team_id):
    """{opponent_player_id: most common batting-order spot} from their lineups."""
    from models import OpponentLineupSlot
    rows = (db.query(OpponentLineupSlot).join(Game, OpponentLineupSlot.game_id == Game.game_id)
            .filter(Game.opponent_team_id == opponent_team_id).all())
    spots = defaultdict(Counter)
    for r in rows:
        spots[r.opponent_player_id][r.batting_order] += 1
    return {pid: c.most_common(1)[0][0] for pid, c in spots.items()}


def build_hitters(db, opponent_team_id, lines=None):
    """[{id, name, bats, order, profile, line, small}] for their hitters we've faced,
    lineup order first. lines = coach-edited one-liners {'h:<id>': text}."""
    lines = lines or {}
    ps = their_hitting_pitches(db, opponent_team_id)
    by = defaultdict(list)
    for p in ps:
        if p.opponent_player_id is not None:
            by[p.opponent_player_id].append(p)
    if not by:
        return []
    loc = _rapsodo_loc(db, ps)
    roster = {op.opponent_player_id: op for op in
              db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id.in_(list(by))).all()}
    order = usual_order(db, opponent_team_id)
    out = []
    for pid, pitches in by.items():
        op = roster.get(pid)
        if op is None:
            continue
        prof = hitter_profile(pitches, op.bats, loc)
        auto = hitter_line(prof)
        out.append({"id": pid, "name": op.player_name, "bats": op.bats, "order": order.get(pid),
                    "profile": prof, "auto_line": auto, "line": lines.get(f"h:{pid}") or auto,
                    "small": prof["pa"] < MIN_HITTER_PAS, "notes": op.notes})
    out.sort(key=lambda h: (h["order"] or 99, -h["profile"]["pa"], h["name"]))
    return out


# ---------------------------------------------------------------- self-scout

def self_scout(db, player_id, date_from=None, date_to=None):
    """One of OUR pitchers seen the way an opponent would: the same pitcher
    page, every game (intrasquads too), Rapsodo locations, plus the counts
    a hitter could sit on."""
    from analytics import profile_queries
    from models import Player
    pl = db.query(Player).filter(Player.player_id == player_id).first()
    ps = profile_queries.get_pitcher_profile_pitches(db, player_id, date_from=date_from, date_to=date_to) or []
    if pl is None or not ps:
        return None
    loc = _rapsodo_loc(db, ps)
    prof = pitcher_profile(db, ps, pl.throws, loc=loc)
    return {"player": pl, "name": f"{pl.first_name} {pl.last_name}", "hand": pl.throws, "profile": prof,
            "line": pitcher_line(prof), "spots": predictable_spots(prof), "points": draft_points(prof, pl.first_name)}


# ---------------------------------------------------------------- post-series check

SERIES_DAYS = 6


def series_check(db, opponent_team_id, series_date, lines=None):
    """After the series is charted: their pitchers' plan vs what they did, our
    hitters vs the plan, and our pitchers vs their hitters' one-liners.
    Series = games vs this team from series_date through SERIES_DAYS later;
    'before' = everything we had charted before series_date."""
    import datetime as _dt
    if series_date is None:
        return None
    end = series_date + _dt.timedelta(days=SERIES_DAYS)
    allp = team_pitches(db, opponent_team_id)
    before = [p for p in allp if p.game and p.game.game_date < series_date]
    during = [p for p in allp if p.game and series_date <= p.game.game_date <= end]
    if not during:
        return {"games": [], "pitchers": [], "hitting": None, "their_hitters": []}
    names = {op.opponent_player_id: op.player_name for op in
             db.query(OpponentPlayer).filter(OpponentPlayer.team_id == opponent_team_id).all()}
    pitchers = []
    for pid in sorted({p.opponent_player_id for p in during if p.opponent_player_id is not None}):
        b = [p for p in before if p.opponent_player_id == pid]
        d = [p for p in during if p.opponent_player_id == pid]
        pb = pitcher_profile(db, b) if len(b) >= MIN_PLAN_PITCHES else None
        pd = pitcher_profile(db, d)

        def summ(pr):
            if not pr:
                return None
            f, t = pr.get("first") or {}, pr.get("two_k") or {}
            return {"n": pr["n"], "fb0": f.get("fb"), "two_top": t.get("top"), "two_pct": t.get("top_pct"),
                    "mix": [(a["pitch"], a["usage"]) for a in pr["arsenal"][:3]]}
        pitchers.append({"name": names.get(pid, f"#{pid}"), "planned": summ(pb), "actual": summ(pd)})

    def hit_summary(ps):
        first = [p for p in ps if (p.balls_before, p.strikes_before) == (0, 0)]
        first_fb = [p for p in first if _label(p) in FASTBALL_TYPES]
        two = [p for p in ps if p.strikes_before == 2]
        two_sw = [p for p in two if p.pitch_outcome in SWINGS]
        return {"first_fb_swing": _pct(sum(1 for p in first_fb if p.pitch_outcome in SWINGS), len(first_fb)),
                "first_fb_n": len(first_fb),
                "two_whiff": _pct(sum(1 for p in two_sw if p.pitch_outcome == "Swing and Miss"), len(two_sw)),
                "two_n": len(two)}
    hitting = {"before": hit_summary(before), "during": hit_summary(during)}

    lines = lines or {}
    theirs = []
    ours = their_hitting_pitches(db, opponent_team_id)
    pre = [p for p in ours if p.game and p.game.game_date < series_date]
    ser = [p for p in ours if p.game and series_date <= p.game.game_date <= end]
    if ser:
        loc = _rapsodo_loc(db, pre)
        bats = {op.opponent_player_id: op.bats for op in
                db.query(OpponentPlayer).filter(OpponentPlayer.team_id == opponent_team_id).all()}
        for pid in sorted({p.opponent_player_id for p in ser if p.opponent_player_id is not None}):
            pp = [p for p in pre if p.opponent_player_id == pid]
            prof = hitter_profile(pp, bats.get(pid), loc) if pp else None
            line = lines.get(f"h:{pid}") or hitter_line(prof)
            fams = [f for f, w in FAMILY_WORDS.items() if line and w in line.split(";")[0]]
            planned = fams[0] if fams else None
            sp = [p for p in ser if p.opponent_player_id == pid]
            pas = _pas(sp)
            fin = [pa[-1] for pa in pas]
            on_plan = [p for p in fin if planned and _family(p) == planned]
            theirs.append({"name": names.get(pid, f"#{pid}"), "planned": planned, "pa": len(pas),
                           "finished_with_plan": len(on_plan),
                           "outs_with_plan": sum(1 for p in on_plan if p.ab_outcome not in HITS and p.ab_outcome not in NON_AB),
                           "hits": sum(1 for p in fin if p.ab_outcome in HITS)})
    games = sorted({p.game for p in during if p.game is not None}, key=lambda g: g.game_date)
    return {"games": games, "pitchers": pitchers, "hitting": hitting, "their_hitters": theirs}
