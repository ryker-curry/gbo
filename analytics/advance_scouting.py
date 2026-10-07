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
NON_AB = {"BB", "HBP", "Sac Bunt", "Sac Fly"}
KS = {"K", "K (Looking)"}
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


def _grid(pitches, hands, bat):
    """3x3 % of located pitches vs one hitter hand: rows up/mid/down,
    cols in/mid/away (relative to the hitter)."""
    cells = Counter()
    n = 0
    for p in pitches:
        if hands.get(p.game_pitch_id) != bat or p.actual_plate_x is None or p.actual_plate_z is None:
            continue
        x, z = float(p.actual_plate_x), float(p.actual_plate_z)
        in_side = -x if bat == "R" else x  # + = toward the hitter (RHH stands on the 3B side, plate_x < 0)
        col = 0 if in_side > X_THIRD else (2 if in_side < -X_THIRD else 1)
        row = 0 if z > Z_HIGH else (2 if z < Z_LOW else 1)
        cells[(row, col)] += 1
        n += 1
    if not n:
        return None
    return {"n": n, "pct": [[round(cells[(r, c)] / n * 100) for c in range(3)] for r in range(3)]}


def _rel_cell(p, bat):
    """(row, col) relative to the hitter: rows up/mid/down, cols in/mid/away."""
    if bat not in ("R", "L") or p.actual_plate_x is None or p.actual_plate_z is None:
        return None
    x, z = float(p.actual_plate_x), float(p.actual_plate_z)
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


def whiff_grids(pitches, hands):
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
            rc = _rel_cell(p, hands.get(p.game_pitch_id))
            if rc is None:
                continue
            if p.pitch_outcome in SWINGS:
                cells[rc[0]][rc[1]][1] += 1
                if p.pitch_outcome == "Swing and Miss":
                    cells[rc[0]][rc[1]][0] += 1
            if not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z)):
                oz += 1
                osw += p.pitch_outcome in SWINGS
        out[fam] = {"cells": cells, "chase": _pct(osw, oz), "n": len(ps)}
    return out


def times_through(pitches):
    """Pitch mix the 1st / 2nd / 3rd+ time a hitter sees him in a game."""
    seen = defaultdict(int)
    by = defaultdict(list)
    for pa in _pas(pitches):
        key = (pa[0].game_id, pa[0].our_player_id)
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


def pitcher_profile(db, pitches, hand_label=None):
    """Everything the report shows for one of their pitchers (or one
    team-level 'Unidentified' group)."""
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
        "fb_grid": {"R": _grid(fbs, hands, "R"), "L": _grid(fbs, hands, "L")},
        "whiff_grids": whiff_grids(pitches, hands), "tto": times_through(pitches),
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
        cells = [(g["pct"][r][c], r, c) for r in range(3) for c in range(3)]
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


def build(db, opponent_team_id, roles=None):
    """{team, pitchers: [{player|None, name, hand, role, notes, profile, points}], team_rhp, team_lhp}"""
    roles = {int(k): v for k, v in (roles or {}).items() if v}
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
        pitchers.append({"id": pid, "player": op, "name": op.player_name, "hand": op.throws, "role": roles.get(pid, ""),
                         "notes": op.notes, "profile": prof, "points": draft_points(prof, op.player_name, damage)})
    order = {r: i for i, r in enumerate(ROLES[1:])}
    pitchers.sort(key=lambda x: (order.get(x["role"], 99), -(x["profile"]["n"] if x["profile"] else 0), x["name"]))
    unident = []
    for h in ("R", "L"):
        if unknown[h]:
            prof = pitcher_profile(db, unknown[h], h)
            unident.append({"id": None, "player": None, "name": f"Unidentified {h}HP (before 'Their pitcher' tracking)",
                            "hand": h, "role": "", "notes": None, "profile": prof, "points": draft_points(prof, damage=damage)})
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
