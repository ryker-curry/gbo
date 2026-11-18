"""
GBO -- Hitter game card (Oct 2026, Ryker: "build something like this into
hitter game reports" -- Josh Rodrigues' post-game hitting report).

One game, one hitter, read three ways:
  TILES      Zone Swing %, Decision pts, Hard Hit %, Chase %, Whiff %, each
             against the TEAM in the same game and the team season-to-date.
  PITCHES    every located pitch he saw -- shape = what he did (swing in
             play, whiff, foul, take), color = decision (good / neutral /
             poor), gold ring = a 2-strike or 3-ball pitch.
  BY AREA    Heart (swing at these) / Edges = Shadow (your call) / Chase =
             Chase + Waste (take these): how often he swung there vs the
             team, his decision points there, and his share of swings.

DECISION POINTS = analytics.decision_value credit x 10 (Ryker: points, not
runs -- easier for hitters to read). The tile shows points per graded
pitch, with the game total under it.

TEAM = active non-pitchers (analytics.hitter_report.team_hitting), pooled:
every team pitch / swing counted once, so a guy with 2 PAs doesn't count as
much as a guy with 5.

Every rate needs a located pitch (actual_plate_x/z) except Hard Hit % (balls
in play with a contact call) and Whiff % (swings).
"""

from analytics import decision_value as dv
from analytics.hitter_insights import HARD_CONTACT
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import classify_attack_zone, is_in_zone

PTS = 10.0                 # points per run of decision value
NEUTRAL_PTS = 0.2          # |credit| under this many points = neutral decision
AREAS = [
    ("heart", "Heart", "swing at these"),
    ("edges", "Edges", "your call"),
    ("chase", "Chase", "take these"),
]
# tile key -> (label, higher is better, kind, a 'clear' gap vs the team)
TILES = [
    ("zone_swing", "Zone Swing %", True, "pct", 8.0),
    ("dec", "Decision Pts", True, "pts", 0.3),
    ("hard", "Hard Hit %", True, "pct", 10.0),
    ("chase", "Chase %", False, "pct", 6.0),
    ("whiff", "Whiff %", False, "pct", 8.0),
]


def _xz(p):
    if p.actual_plate_x is None or p.actual_plate_z is None:
        return None
    return float(p.actual_plate_x), float(p.actual_plate_z)


def area_of(p):
    xz = _xz(p)
    if xz is None:
        return None
    t = classify_attack_zone(*xz)
    return {"Heart": "heart", "Shadow": "edges"}.get(t, "chase")


def action(p):
    """swing / whiff / foul / take (None = not a pitch outcome we can read)."""
    o = p.pitch_outcome
    if o in WHIFF_OUTCOMES:
        return "whiff"
    if o == "Foul":
        return "foul"
    if o == "In Play":
        return "swing"
    if o in dv.TAKES:
        return "take"
    return None


def decision(cr_pts):
    if cr_pts is None:
        return None
    if cr_pts >= NEUTRAL_PTS:
        return "good"
    if cr_pts <= -NEUTRAL_PTS:
        return "poor"
    return "neutral"


def _pct(a, b):
    return 100.0 * a / b if b else None


def rates(pitches, table):
    """Pooled rates + counts for any pitch list (one hitter or the team)."""
    located = [p for p in pitches if _xz(p) is not None]
    inz = [p for p in located if is_in_zone(*_xz(p))]
    outz = [p for p in located if not is_in_zone(*_xz(p))]
    swings = [p for p in pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in swings if p.pitch_outcome in WHIFF_OUTCOMES]
    bip = [p for p in pitches if p.pitch_outcome == "In Play"]
    called = [p for p in bip if p.contact_quality]
    hard = [p for p in called if p.contact_quality in HARD_CONTACT]
    credits = [c for c in (dv.credit(table, p) for p in pitches) if c is not None]
    pts = PTS * sum(c[0] for c in credits)
    areas = {}
    for key, *_ in AREAS:
        ps = [p for p in located if area_of(p) == key]
        sw = [p for p in ps if p.pitch_outcome in SWING_OUTCOMES]
        cr = [c for c in (dv.credit(table, p) for p in ps) if c is not None]
        areas[key] = {"n": len(ps), "swings": len(sw), "swing_pct": _pct(len(sw), len(ps)),
                      "pts": PTS * sum(c[0] for c in cr) if cr else None}
    return {
        "pitches": len(pitches), "located": len(located), "swings": len(swings), "bip": len(bip),
        "zone_n": len(inz), "zone_swings": sum(1 for p in inz if p.pitch_outcome in SWING_OUTCOMES),
        "chase_n": len(outz), "chase_swings": sum(1 for p in outz if p.pitch_outcome in SWING_OUTCOMES),
        "whiffs": len(whiffs), "hard_n": len(called), "hard": len(hard),
        "graded": len(credits), "pts": pts,
        "zone_swing": _pct(sum(1 for p in inz if p.pitch_outcome in SWING_OUTCOMES), len(inz)),
        "chase": _pct(sum(1 for p in outz if p.pitch_outcome in SWING_OUTCOMES), len(outz)),
        "whiff": _pct(len(whiffs), len(swings)),
        "hard_pct": _pct(len(hard), len(called)),
        "dec": pts / len(credits) if credits else None,
        "areas": areas,
    }


def _tile_value(r, key):
    return r["hard_pct"] if key == "hard" else r[key]


def _sub(r, key):
    if key == "zone_swing":
        return f"{r['zone_swings']} of {r['zone_n']} in the zone"
    if key == "dec":
        return f"{r['pts']:+.0f} pts · {r['graded']} pitches"
    if key == "hard":
        return f"{r['hard']} of {r['hard_n']} balls in play"
    if key == "chase":
        return f"{r['chase_swings']} of {r['chase_n']} off the zone"
    return f"{r['whiffs']} of {r['swings']} swings"


def _mark(you, ref, hib, gap):
    if you is None or ref is None:
        return None
    d = (you - ref) / gap * (1 if hib else -1)
    return "good" if d >= 1 else "poor" if d <= -1 else None


def pitch_items(pitches, table, pa_of=None):
    """One dict per located pitch, in game order, for the decisions plot."""
    out = []
    for p in sorted(pitches, key=lambda q: (q.game_id or 0, q.pitch_sequence or 0)):
        xz = _xz(p)
        if xz is None:
            continue
        c = dv.credit(table, p)
        pts = PTS * c[0] if c is not None else None
        b, s = p.balls_before, p.strikes_before
        out.append({
            "x": xz[0], "z": xz[1], "action": action(p), "pts": pts, "decision": decision(pts),
            "two_three": (s == 2) or (b == 3), "area": area_of(p),
            "count": f"{b}-{s}" if b is not None and s is not None else "—",
            "pitch": p.pitch_type.type_name if getattr(p, "pitch_type", None) else "Unspecified",
            "result": p.ab_outcome or p.pitch_outcome or "—",
            "ab": (pa_of or {}).get(p.game_pitch_id),
        })
    return out


def build(pitches, team_game, team_season, table, pa_count=None, pa_of=None):
    """-> dict for visualizations.hitter_game_card. team_game / team_season:
    flat pitch lists for the team in this game and season to date."""
    me = rates(pitches, table)
    tg = rates(team_game, table) if team_game else None
    ts = rates(team_season, table) if team_season else None
    ref = ts or tg
    tiles = []
    for key, label, hib, kind, gap in TILES:
        you = _tile_value(me, key)
        tiles.append({"key": key, "label": label, "kind": kind, "you": you, "sub": _sub(me, key),
                      "game": _tile_value(tg, key) if tg else None,
                      "season": _tile_value(ts, key) if ts else None,
                      "mark": _mark(you, _tile_value(ref, key) if ref else None, hib, gap)})
    areas = []
    for key, label, hint in AREAS:
        a = me["areas"][key]
        areas.append({"key": key, "label": label, "hint": hint, **a,
                      "share": _pct(a["swings"], sum(x["swings"] for x in me["areas"].values())),
                      "team_game": tg["areas"][key]["swing_pct"] if tg else None,
                      "team_season": ts["areas"][key]["swing_pct"] if ts else None})
    return {"tiles": tiles, "areas": areas, "me": me, "pa": pa_count,
            "pitches": pitch_items(pitches, table, pa_of),
            "swings": [(x, z) for x, z in ((float(p.actual_plate_x), float(p.actual_plate_z)) for p in pitches
                                           if p.pitch_outcome in SWING_OUTCOMES and _xz(p) is not None)]}


def load(db, player_id, game_id):
    """Everything the card needs from the database, or None."""
    from models import Game
    from analytics.hitter_report import hitter_pitches, team_hitting
    from game_stats import _group_into_plate_appearances
    game = db.query(Game).filter(Game.game_id == game_id).first()
    if game is None:
        return None
    pitches = hitter_pitches(db, player_id, game_id=game_id)
    if not pitches:
        return None
    team = team_hitting(db, game.season_id)
    team_season = [p for ps in team.values() for p in ps]
    team_game = [p for p in team_season if p.game_id == game_id]
    pas = _group_into_plate_appearances(pitches)
    pa_of = {p.game_pitch_id: k for k, pa in enumerate(pas, start=1) for p in pa}
    return build(pitches, team_game, team_season, dv.team_table(db), pa_count=len(pas), pa_of=pa_of)
