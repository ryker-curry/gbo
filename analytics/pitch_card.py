"""
GBO -- Pitch Calling Card (Oct 2026, Ryker: no phone/tablet in the dugout,
so the pitching coach carries a pocket card made before the game).

CODES -- Ryker's Level-Pitch-Zone notation, e.g. "214":
  level  1 dirt/below · 2 knees · 3 middle · 4 top and above
         (strike_zone.LEVEL_TO_PLATE_Z / call_level)
  pitch  1 fastball (4-seam, 2-seam, sinker) · 2 curveball ·
         3 slider/sweeper · 4 changeup/splitter · 5 cutter
  zone   1-5 across the plate, physical side fixed: 1 = off the plate on
         the 3B side (in to a RHH), 5 = off on the 1B side
         (strike_zone.ZONE_TO_PLATE_X / call_zone)

COUNT GROUPS (columns): First pitch 0-0 · Ahead 0-1 · Even/behind 1-0,
2-0, 3-0, 1-1, 2-1, 3-1 · Full 2-2, 3-2 · Put-away 0-2, 1-2.

VALUE MODEL -- pitcher's side of GamePitch.run_value (v = -run_value, so
higher = better for us) on every charted game pitch with an ACTUAL
location, pitch type and count. Left-handed pitchers are mirrored to a
righty frame (zone 6 - z, batter hand flipped) so both hands share one
table; platoon = same / opposite hand. Shrunk layer by layer so thin
cells lean on the layer above:
    pitch x platoon x count group                        (k = K1)
      -> + attack tier (Heart/Shadow/Chase/Waste)         (k = K2)
        -> + exact level/zone cell                        (k = K3)
  + his own edge with that pitch in that cell, all counts (k = KP_CELL)
  + his own edge with that pitch overall                  (k = KP_TYPE)
  + the hitter's edge vs that pitch, in / out of zone     (k = KH)
Each cell gets the best code he throws and a backup with a different
pitch. Coaches edit any cell before printing; the card is a starting
point, and the Card vs Calls report checks it after the game.
"""

from collections import defaultdict
from statistics import mean

import strike_zone as sz

PITCH_DIGIT = {"4-Seam Fastball": 1, "2-Seam Fastball": 1, "Fastball": 1, "Sinker": 1, "Curveball": 2,
               "Slider": 3, "Sweeper": 3, "Changeup": 4, "Splitter": 4, "Cutter": 5}
DIGIT_NAME = {1: "FB", 2: "CB", 3: "SL", 4: "CH", 5: "CT"}
GROUPS = [("first", "1st pitch", ("0-0",)), ("ahead", "Ahead", ("0-1",)),
          ("even", "Even/behind", ("1-0", "2-0", "3-0", "1-1", "2-1", "3-1")),
          ("full", "2-2 / 3-2", ("2-2", "3-2")), ("putaway", "Put-away", ("0-2", "1-2"))]
GROUP_OF = {c: g for g, _l, cs in GROUPS for c in cs}
# Every level/zone cell except dead middle (3-3) -- nobody calls a pitch there.
CELLS = [(lv, z) for lv in (1, 2, 3, 4) for z in (1, 2, 3, 4, 5) if (lv, z) != (3, 3)]
K1, K2, K3, KP_CELL, KP_TYPE, KH = 20, 20, 15, 20, 30, 25
MIN_USE = 0.05
MIN_HITTER_P = 15
WHIFF = "Swing and Miss"
SWINGS = {"Swing and Miss", "Foul", "In Play"}


def code(level, digit, zone):
    return f"{level}{digit}{zone}"


def parse(c):
    c = (c or "").strip()
    if len(c) != 3 or not c.isdigit():
        return None
    return int(c[0]), int(c[1]), int(c[2])


def tier(level, zone):
    return sz.classify_attack_zone(sz.ZONE_TO_PLATE_X[zone], sz.LEVEL_TO_PLATE_Z[level])


def mirror_zone(zone):
    return 6 - zone


def platoon(p_throws, b_hand):
    if b_hand not in ("R", "L") or p_throws not in ("R", "L"):
        return None
    return "same" if b_hand == p_throws else "opp"


def batter_hand(bats, p_throws):
    if bats == "S":
        return "L" if p_throws == "R" else "R"
    return bats if bats in ("R", "L") else None


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def load_pitches(db):
    """Every charted game pitch thrown by one of OUR pitchers, as light dicts:
    {pid, throws, batter: ("our"|"opp", id), hand, digit, level, zone (pitcher-
    normalized), raw_zone, group, v, outcome, cq, in_zone, ilevel, izone, game_id}."""
    from sqlalchemy.orm import joinedload
    from models import GamePitch, Player, OpponentPlayer
    players = {p.player_id: p for p in db.query(Player).all()}
    opps = {o.opponent_player_id: o for o in db.query(OpponentPlayer).all()}
    out = []
    for gp in db.query(GamePitch).options(joinedload(GamePitch.pitch_type)).all():
        if gp.is_our_team_batting:
            pid, batter = gp.opponent_our_player_id, ("our", gp.our_player_id)
        else:
            pid = gp.our_player_id
            batter = (("opp", gp.opponent_player_id) if gp.opponent_player_id else
                      (("our", gp.opponent_our_player_id) if gp.opponent_our_player_id else None))
        if pid is None or pid not in players:
            continue
        throws = players[pid].throws
        lab = gp.pitch_type.type_name if gp.pitch_type is not None else None
        digit = PITCH_DIGIT.get(lab)
        if digit is None or throws not in ("R", "L"):
            continue
        bats = None
        if batter is not None:
            src = players.get(batter[1]) if batter[0] == "our" else opps.get(batter[1])
            bats = getattr(src, "bats", None) if src is not None else None
        hand = batter_hand(bats, throws)
        cnt = (f"{gp.balls_before}-{gp.strikes_before}" if gp.balls_before is not None and gp.strikes_before is not None
               else None)
        cell = sz.call_cell(float(gp.actual_plate_x), float(gp.actual_plate_z)) if gp.actual_plate_x is not None \
            and gp.actual_plate_z is not None else None
        icell = sz.call_cell(float(gp.intended_plate_x), float(gp.intended_plate_z)) if gp.intended_plate_x is not None \
            and gp.intended_plate_z is not None else None
        def norm(z):
            return z if throws == "R" else mirror_zone(z)
        out.append({
            "pid": pid, "throws": throws, "batter": batter, "hand": hand, "digit": digit,
            "level": cell[0] if cell else None, "zone": norm(cell[1]) if cell else None,
            "ilevel": icell[0] if icell else None, "izone": icell[1] if icell else None,
            "group": GROUP_OF.get(cnt), "v": -float(gp.run_value) if gp.run_value is not None else None,
            "outcome": gp.pitch_outcome, "cq": gp.contact_quality, "game_id": gp.game_id,
            "in_zone": sz.is_in_zone(float(gp.actual_plate_x), float(gp.actual_plate_z)) if cell else None,
            "game_pitch_id": gp.game_pitch_id, "pa_pitch_number": gp.pa_pitch_number,
        })
    return out


def usage(pitches, raps_by_pid=None):
    """{pid: {digit: share}} from game pitches plus Rapsodo readings."""
    cnt = defaultdict(lambda: defaultdict(int))
    for p in pitches:
        cnt[p["pid"]][p["digit"]] += 1
    for pid, labels in (raps_by_pid or {}).items():
        for lab in labels:
            d = PITCH_DIGIT.get(lab)
            if d:
                cnt[pid][d] += 1
    return {pid: {d: n / sum(c.values()) for d, n in c.items()} for pid, c in cnt.items()}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _shrink(sum_n, prior, k):
    s, n = sum_n
    return (s + k * prior) / (n + k)


class Model:
    def __init__(self, pitches):
        rows = [p for p in pitches if p["v"] is not None and p["group"] and p["level"] and
                platoon(p["throws"], p["hand"])]
        self.n = len(rows)
        self.g0 = mean(p["v"] for p in rows) if rows else 0.0
        acc = defaultdict(lambda: [0.0, 0])

        def add(key, v):
            acc[key][0] += v
            acc[key][1] += 1
        for p in rows:
            pl = platoon(p["throws"], p["hand"])
            t = tier(p["level"], p["zone"])
            add(("L1", p["digit"], pl, p["group"]), p["v"])
            add(("L2", p["digit"], pl, p["group"], t), p["v"])
            add(("L3", p["digit"], pl, p["group"], p["level"], p["zone"]), p["v"])
        self.acc = acc
        dev = defaultdict(lambda: [0.0, 0])
        for p in rows:
            pl = platoon(p["throws"], p["hand"])
            r = p["v"] - self.base(p["digit"], pl, p["group"], p["level"], p["zone"])
            for key in (("PC", p["pid"], p["digit"], pl, p["level"], p["zone"]), ("PT", p["pid"], p["digit"]),
                        ("H", p["batter"], p["digit"], bool(p["in_zone"]))):
                dev[key][0] += r
                dev[key][1] += 1
        self.dev = dev

    def base(self, digit, pl, group, level, zone):
        l1 = _shrink(self.acc.get(("L1", digit, pl, group), (0.0, 0)), self.g0, K1)
        l2 = _shrink(self.acc.get(("L2", digit, pl, group, tier(level, zone)), (0.0, 0)), l1, K2)
        return _shrink(self.acc.get(("L3", digit, pl, group, level, zone), (0.0, 0)), l2, K3)

    def _d(self, key, k):
        s, n = self.dev.get(key, (0.0, 0))
        return s / (n + k)

    def score(self, pid, digit, pl, group, level, zone, batter=None, angle=None):
        b = self.base(digit, pl, group, level, zone)
        pc = self._d(("PC", pid, digit, pl, level, zone), KP_CELL)
        pt = self._d(("PT", pid, digit), KP_TYPE)
        in_z = sz.is_in_zone(sz.ZONE_TO_PLATE_X[zone], sz.LEVEL_TO_PLATE_Z[level])
        h = self._d(("H", batter, digit, in_z), KH) if batter is not None else 0.0
        a = 0.0
        if angle is not None:
            n_own = self.dev.get(("PT", pid, digit), (0.0, 0))[1]
            a = angle_bonus(digit, level, zone, *angle) * KA / (KA + n_own)
        return b + pc + pt + h + a, {"base": b, "pitcher": pc + pt, "hitter": h, "angle": a}

    def n_batter(self, batter):
        return sum(n for (k, b, *_r), (_s, n) in self.dev.items() if k == "H" and b == batter)


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Angle profile nudge (Oct 2026, Paradigm "The Angle Advantage"): a pitch's
# VAAA / HAAAA says where it should play -- flat fastballs up, steep ones and
# steep breakers down, arm-side angles open an inside lane, glove-side an
# away lane. Small (ANGLE_W runs per degree, capped at ANGLE_CAP degrees) and
# faded by KA / (KA + his game pitches of that pitch), so once real outcomes
# pile up they outweigh it. Zones are in the righty frame here (1-2 = arm side).
# ---------------------------------------------------------------------------

ANGLE_W = 0.01
ANGLE_CAP = 1.5
ANGLE_MIN = 0.3
KA = 60


def angle_bonus(digit, level, zone, vaaa, haaaa_arm):
    b = 0.0
    if vaaa is not None and abs(vaaa) >= ANGLE_MIN:
        m = min(abs(vaaa), ANGLE_CAP) * ANGLE_W
        if digit in (1, 5):
            if vaaa > 0:
                b += m if level == 4 else (-m / 2 if level in (1, 2) else 0)
            else:
                b += m if level in (1, 2) else (-m / 2 if level == 4 else 0)
        elif vaaa < 0:
            b += m if level in (1, 2) else 0
        else:
            b += -m / 2 if level == 1 else 0
    if haaaa_arm is not None and abs(haaaa_arm) >= ANGLE_MIN:
        m = min(abs(haaaa_arm), ANGLE_CAP) * ANGLE_W
        lane = (1, 2) if haaaa_arm > 0 else (4, 5)
        b += m if zone in lane else 0
    return b


def angle_note(angles, digits):
    """Short footer line, e.g. 'FB flat (+0.8 VAAA), SL glove-side'."""
    bits = []
    for d in digits:
        v, h = (angles or {}).get(d, (None, None))
        words = []
        if v is not None and abs(v) >= ANGLE_MIN:
            words.append(f"{'flat' if v > 0 else 'steep'} {v:+.1f}")
        if h is not None and abs(h) >= ANGLE_MIN:
            words.append("arm-side" if h > 0 else "glove-side")
        if words:
            bits.append(f"{DIGIT_NAME[d]} {' '.join(words)}")
    return ", ".join(bits)


def arsenal(pid, use):
    digits = [d for d, s in (use.get(pid) or {}).items() if s >= MIN_USE]
    return sorted(digits) or [1]


def best_two(model, pid, throws, hand, group, digits, batter=None, angles=None):
    """[(code, score, parts)] best code + backup with a different pitch
    (or a different spot if he only has one pitch). Codes in the REAL
    frame (zone un-mirrored for a lefty)."""
    pl = platoon(throws, hand)
    if pl is None:
        return []
    cand = []
    for d in digits:
        for lv, z in CELLS:
            s, parts = model.score(pid, d, pl, group, lv, z, batter, (angles or {}).get(d))
            real_z = z if throws == "R" else mirror_zone(z)
            cand.append((s, d, lv, real_z, parts))
    cand.sort(key=lambda c: -c[0])
    if not cand:
        return []
    top = cand[0]
    backup = next((c for c in cand[1:] if c[1] != top[1]), None) or (cand[1] if len(cand) > 1 else None)
    out = [(code(top[2], top[1], top[3]), top[0], top[4])]
    if backup:
        out.append((code(backup[2], backup[1], backup[3]), backup[0], backup[4]))
    return out


def hitter_note(model, batter, digits):
    n = model.n_batter(batter) if batter is not None else 0
    if n < MIN_HITTER_P:
        return f"{n} P seen -- by hand" if n else "no history -- by hand"
    edges = []
    for d in digits:
        for in_z in (True, False):
            e = model._d(("H", batter, d, in_z), KH)
            edges.append((e, d, in_z))
    best = max(edges)
    worst = min(edges)
    bits = [f"{n} P"]
    if best[0] > 0.01:
        bits.append(f"beat w/ {DIGIT_NAME[best[1]]} {'in zone' if best[2] else 'chase'}")
    if worst[0] < -0.01:
        bits.append(f"hurts {DIGIT_NAME[worst[1]]} {'in zone' if worst[2] else 'off'}")
    return " · ".join(bits)


def build_card(model, pitcher, hitters, use, angles=None):
    """pitcher: Player; hitters: [{"key": ("our"|"opp", id), "name", "bats"}].
    -> {"pitcher_id", "pitcher", "throws", "digits", "rows": [...], "generic": {...}, "n": model.n}"""
    digits = arsenal(pitcher.player_id, use)
    rows = []
    for h in hitters:
        hand = batter_hand(h.get("bats"), pitcher.throws)
        cells = {}
        for g, _l, _cs in GROUPS:
            two = best_two(model, pitcher.player_id, pitcher.throws, hand, g, digits, tuple(h["key"]), angles)
            cells[g] = {"primary": two[0][0] if two else "", "backup": two[1][0] if len(two) > 1 else ""}
        rows.append({"key": list(h["key"]), "name": h["name"], "hand": hand or "?", "cells": cells,
                     "note": hitter_note(model, tuple(h["key"]), digits)})
    generic = {}
    for hand in ("R", "L"):
        generic[hand] = {}
        for g, _l, _cs in GROUPS:
            two = best_two(model, pitcher.player_id, pitcher.throws, hand, g, digits, angles=angles)
            generic[hand][g] = {"primary": two[0][0] if two else "", "backup": two[1][0] if len(two) > 1 else ""}
    return {"pitcher_id": pitcher.player_id, "pitcher": f"{pitcher.first_name} {pitcher.last_name}",
            "throws": pitcher.throws, "digits": digits, "rows": rows, "generic": generic, "n": model.n,
            "angle_note": angle_note(angles, digits)}


# ---------------------------------------------------------------------------
# Card vs Calls (after the game)
# ---------------------------------------------------------------------------

def card_cell(card, batter, hand, group):
    for r in card.get("rows", []):
        if tuple(r["key"]) == tuple(batter or ()):
            return r["cells"].get(group)
    return (card.get("generic", {}).get(hand) or {}).get(group)


def compare(cards_by_pid, pitches):
    """cards_by_pid: {pid: card}; pitches: load_pitches() rows for ONE game.
    -> {"rows": [per pitch], "summary": {status: {...}}}"""
    out = []
    for p in pitches:
        card = cards_by_pid.get(p["pid"])
        if card is None or p["ilevel"] is None or p["group"] is None:
            continue
        cell = card_cell(card, p["batter"], p["hand"], p["group"])
        if not cell:
            continue
        called = code(p["ilevel"], p["digit"], p["izone"])
        cards = [c for c in (cell.get("primary"), cell.get("backup")) if c]
        if called in cards:
            status = "match"
        elif any(parse(c) and parse(c)[1] == p["digit"] for c in cards):
            status = "pitch"
        else:
            status = "off"
        out.append({**p, "called": called, "card": " / ".join(cards), "status": status})
    return {"rows": out, "summary": summarize(out)}


def summarize(rows):
    by = defaultdict(list)
    for r in rows:
        by[r["status"]].append(r)
    res = {}
    for st, rs in by.items():
        sw = [r for r in rs if r["outcome"] in SWINGS]
        chase_opp = [r for r in rs if r["in_zone"] is False]
        vs = [r["v"] for r in rs if r["v"] is not None]
        res[st] = {"n": len(rs), "whiff": 100 * sum(r["outcome"] == WHIFF for r in rs) / len(rs),
                   "whiff_per_swing": 100 * sum(r["outcome"] == WHIFF for r in sw) / len(sw) if sw else None,
                   "chase": 100 * sum(r["outcome"] in SWINGS for r in chase_opp) / len(chase_opp) if chase_opp else None,
                   "hard": 100 * sum((r["cq"] or "") in ("Barrel", "Solid") for r in rs) / len(rs),
                   "rv100": 100 * mean(vs) if vs else None}
    return res
