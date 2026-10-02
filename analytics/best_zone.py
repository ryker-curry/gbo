"""
GBO -- Best Zone: distance from each pitch's best location area (Oct 2026).

Ryker sent Paradigm Player Development's "Miss Distance" thread and said
"build it". Their idea: for each pitch type x pitcher hand x batter hand,
map where the pitch gets the best results (their "blue" area), then
measure how far every pitch landed from that AREA (not from one spot).
Contact damage climbed with distance; going way off the plate bought a
few whiffs but swings and strikes collapsed. GBO's Miss Map measures misses
from the CALLED spot -- this measures from where the pitch plays best,
which also shows whether the call itself was a good one.

THE MAPS
  Starting maps (STARTING_ZONES): one rectangle per pitch family x
  matchup (same-handed / opposite-handed batter), written in the
  pitcher's own frame -- `arm` = feet toward his ARM side (a RHP's arm
  side is the catcher's left / third-base side), `z` = height in feet.
  These are educated defaults from the well-known patterns (four-seams
  up, breaking balls down and glove side, changeups down and arm side),
  NOT Paradigm's model, and the page says so.

  Our own data takes over per (family, matchup) once there are
  MIN_DATA_PITCHES located pitches with a run value: the plate is split
  into CELL_FT cells, each cell's average run value is shrunk toward the
  group's average (SHRINK_K pitches of prior weight, so a cell with 3
  pitches can't win on luck), and the best BEST_CELL_SHARE of cells (with
  MIN_CELL_N+ pitches) become the area. Lower run value = better for the
  pitcher (GamePitch.run_value is from the batter's side).

DISTANCE
  Inches from the pitch to the nearest edge of the area (0 = inside),
  banded like Paradigm: Inside / 0-3" / 3-6" / 6-12" / 12"+.

LIMITS
  Results by band use what GBO tracks -- strike %, swing %, whiffs per
  swing, hits per ball in play, run value per 100 pitches. No exit
  velocity, so no xwOBA. Small samples stay noisy for a while.
"""

from collections import defaultdict

ZONE_HALF_WIDTH = 0.708

BANDS = [("Inside", 0.0, 0.0), ("0-3\"", 0.0, 3.0), ("3-6\"", 3.0, 6.0), ("6-12\"", 6.0, 12.0), ("12\"+", 12.0, 1e9)]

FAMILY = {
    "4-Seam Fastball": "four_seam", "Fastball": "four_seam",
    "2-Seam Fastball": "sinker", "Sinker": "sinker",
    "Cutter": "cutter",
    "Slider": "slider", "Sweeper": "slider", "Slurve": "slider",
    "Curveball": "curveball", "Knuckle Curve": "curveball",
    "Changeup": "changeup", "Splitter": "changeup",
}

# (family, matchup) -> (arm_lo, arm_hi, z_lo, z_hi) in feet, pitcher's frame.
STARTING_ZONES = {
    ("four_seam", "same"): (-0.75, 0.75, 2.75, 3.85),
    ("four_seam", "opp"): (-0.75, 0.75, 2.75, 3.85),
    ("sinker", "same"): (0.0, 1.05, 1.3, 2.4),
    ("sinker", "opp"): (-0.25, 0.95, 1.3, 2.4),
    ("cutter", "same"): (-1.05, 0.15, 1.6, 3.1),
    ("cutter", "opp"): (-1.0, 0.1, 1.5, 3.0),
    ("slider", "same"): (-1.25, 0.0, 1.0, 2.3),
    ("slider", "opp"): (-1.0, 0.1, 0.9, 2.0),
    ("curveball", "same"): (-0.9, 0.5, 0.8, 2.0),
    ("curveball", "opp"): (-0.7, 0.7, 0.8, 2.0),
    ("changeup", "same"): (-0.1, 1.0, 0.9, 2.0),
    ("changeup", "opp"): (-0.3, 0.9, 0.9, 2.1),
}

ZONE_WORDS = {
    ("four_seam", "same"): "up in the zone", ("four_seam", "opp"): "up in the zone",
    ("sinker", "same"): "down and in", ("sinker", "opp"): "down, middle to arm side",
    ("cutter", "same"): "glove side, belt to knees", ("cutter", "opp"): "in on the hands",
    ("slider", "same"): "down and to the glove side", ("slider", "opp"): "down at the back foot",
    ("curveball", "same"): "at the knees or below", ("curveball", "opp"): "at the knees or below",
    ("changeup", "same"): "down and to the arm side", ("changeup", "opp"): "down and away",
}

MIN_DATA_PITCHES = 250
CELL_FT = 0.5
SHRINK_K = 15
MIN_CELL_N = 6
BEST_CELL_SHARE = 0.25
GRID_X = (-1.5, 1.5)
GRID_Z = (0.5, 4.5)


def family_of(label):
    return FAMILY.get(label)


def matchup(throws, bat_hand):
    if throws not in ("R", "L") or bat_hand not in ("R", "L"):
        return None
    return "same" if throws == bat_hand else "opp"


def arm_x(plate_x, throws):
    """Plate x (feet, + = first-base side) -> + = pitcher's arm side."""
    return -plate_x if throws == "R" else plate_x


def to_plate_x(arm, throws):
    return -arm if throws == "R" else arm


def _rect_distance_in(ax, z, rect):
    lo_x, hi_x, lo_z, hi_z = rect
    dx = max(lo_x - ax, 0.0, ax - hi_x)
    dz = max(lo_z - z, 0.0, z - hi_z)
    return (dx * dx + dz * dz) ** 0.5 * 12.0


def band_of(dist_in):
    if dist_in is None:
        return None
    if dist_in <= 0.0:
        return "Inside"
    for name, lo, hi in BANDS[1:]:
        if lo < dist_in <= hi:
            return name
    return "12\"+"


# ---------------------------------------------------------------------------
# Map building
# ---------------------------------------------------------------------------

def _cell_index(ax, z):
    if not (GRID_X[0] <= ax < GRID_X[1] and GRID_Z[0] <= z < GRID_Z[1]):
        return None
    return int((ax - GRID_X[0]) // CELL_FT), int((z - GRID_Z[0]) // CELL_FT)


def _cell_rect(i, j):
    x0 = GRID_X[0] + i * CELL_FT
    z0 = GRID_Z[0] + j * CELL_FT
    return (x0, x0 + CELL_FT, z0, z0 + CELL_FT)


def build_maps(team_rows):
    """team_rows: iterable of (label, throws, bat_hand, plate_x, plate_z,
    run_value) for every located pitch our staff threw. Returns
    {(family, matchup): {"rects": [...], "source": "team"|"starting", "n": n}}."""
    groups = defaultdict(list)
    for label, throws, bat, px, pz, rv in team_rows:
        fam, mu = family_of(label), matchup(throws, bat)
        if fam is None or mu is None or rv is None or px is None or pz is None:
            continue
        groups[(fam, mu)].append((arm_x(float(px), throws), float(pz), float(rv)))

    maps = {}
    for key, rect in STARTING_ZONES.items():
        rows = groups.get(key, [])
        maps[key] = {"rects": [rect], "source": "starting", "n": len(rows)}
        if len(rows) < MIN_DATA_PITCHES:
            continue
        overall = sum(r for _x, _z, r in rows) / len(rows)
        cells = defaultdict(list)
        for ax, z, rv in rows:
            idx = _cell_index(ax, z)
            if idx is not None:
                cells[idx].append(rv)
        scored = [
            ((sum(v) + SHRINK_K * overall) / (len(v) + SHRINK_K), idx)
            for idx, v in cells.items() if len(v) >= MIN_CELL_N
        ]
        if len(scored) < 4:
            continue
        scored.sort()
        keep = max(1, round(len(scored) * BEST_CELL_SHARE))
        maps[key] = {"rects": [_cell_rect(*idx) for _s, idx in scored[:keep]], "source": "team", "n": len(rows)}
    return maps


def starting_maps():
    return {k: {"rects": [r], "source": "starting", "n": 0} for k, r in STARTING_ZONES.items()}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score(pitches, throws, bat_hands, maps, label_of):
    """Per located pitch: dict(pitch, label, family, matchup, dist, band).
    bat_hands: {game_pitch_id: 'R'/'L'/None}. label_of(p) -> pitch type name."""
    out = []
    for p in pitches:
        if p.actual_plate_x is None or p.actual_plate_z is None:
            continue
        label = label_of(p)
        fam, mu = family_of(label), matchup(throws, bat_hands.get(p.game_pitch_id))
        m = maps.get((fam, mu)) if fam and mu else None
        if m is None:
            continue
        ax, z = arm_x(float(p.actual_plate_x), throws), float(p.actual_plate_z)
        dist = min(_rect_distance_in(ax, z, r) for r in m["rects"])
        out.append({"pitch": p, "label": label, "family": fam, "matchup": mu, "dist": dist,
                    "band": band_of(dist), "source": m["source"]})
    return out


STRIKE = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
SWING = {"Swing and Miss", "Foul", "In Play"}
HITS = {"1B", "2B", "3B", "HR"}


def _pct(a, b):
    return round(a / b * 100, 1) if b else None


def _outcomes(rows):
    ps = [r["pitch"] for r in rows]
    n = len(ps)
    swings = sum(1 for p in ps if p.pitch_outcome in SWING)
    whiffs = sum(1 for p in ps if p.pitch_outcome == "Swing and Miss")
    bip = [p for p in ps if p.pitch_outcome == "In Play"]
    hits = sum(1 for p in bip if p.ab_outcome in HITS)
    rvs = [float(p.run_value) for p in ps if p.run_value is not None]
    return {
        "n": n, "strike_pct": _pct(sum(1 for p in ps if p.pitch_outcome in STRIKE), n),
        "swing_pct": _pct(swings, n), "whiff_pct": _pct(whiffs, swings),
        "bip": len(bip), "hit_pct_bip": _pct(hits, len(bip)),
        "rv100": round(sum(rvs) / len(rvs) * 100, 1) if rvs else None,
    }


def summary_by_type(scored):
    groups = defaultdict(list)
    for r in scored:
        groups[r["label"]].append(r)
    rows = []
    for label, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        counts = {b[0]: sum(1 for r in rs if r["band"] == b[0]) for b in BANDS}
        rows.append({
            "label": label, "n": n,
            "inside_pct": _pct(counts["Inside"], n),
            "near_pct": _pct(counts["Inside"] + counts["0-3\""], n),
            "far_pct": _pct(counts["6-12\""] + counts["12\"+"], n),
            "avg_dist": round(sum(r["dist"] for r in rs) / n, 1),
            "bands": {k: _pct(v, n) for k, v in counts.items()},
            "team_map": any(r["source"] == "team" for r in rs),
            "where": _where(rs),
        })
    return rows


def _where(rs):
    """Plain description of this pitch's best area, by matchup present."""
    fams = {(r["family"], r["matchup"]) for r in rs}
    by_mu = {}
    for mu in ("same", "opp"):
        ws = sorted({ZONE_WORDS.get((f, m), "?") for f, m in fams if m == mu})
        if ws:
            by_mu[mu] = " / ".join(ws)
    if len(set(by_mu.values())) == 1:
        return next(iter(by_mu.values()))
    names = {"same": "same-handed", "opp": "opposite-handed"}
    return "; ".join(f"{w} vs {names[mu]}" for mu, w in by_mu.items())


def results_by_band(scored):
    by = defaultdict(list)
    for r in scored:
        by[r["band"]].append(r)
    return [{"band": b[0], **_outcomes(by.get(b[0], []))} for b in BANDS]


# ---------------------------------------------------------------------------
# DB glue (cached; refit only when located pitches change)
# ---------------------------------------------------------------------------

_cache = {"key": None, "maps": None}


def label_of(p):
    return p.pitch_type.type_name if getattr(p, "pitch_type", None) is not None else "Unspecified"


def get_maps(db):
    from sqlalchemy import func, or_, and_
    from sqlalchemy.orm import joinedload
    from models import GamePitch, Player
    from game_stats import get_batter_hands
    from analytics.pitcher_game_report import _pitcher_id

    located = (GamePitch.actual_plate_x.isnot(None), GamePitch.actual_plate_z.isnot(None), GamePitch.run_value.isnot(None))
    key = db.query(func.count(GamePitch.game_pitch_id), func.max(GamePitch.game_pitch_id)).filter(*located).one()
    key = (key[0], key[1])
    if _cache["key"] == key and _cache["maps"] is not None:
        return _cache["maps"]
    pitches = (
        db.query(GamePitch).options(joinedload(GamePitch.pitch_type)).filter(*located)
        .filter(or_(GamePitch.is_our_team_batting.is_(False),
                    and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id.isnot(None))))
        .all()
    )
    throws = {pid: t for pid, t in db.query(Player.player_id, Player.throws).all()}
    hands = get_batter_hands(db, pitches) if pitches else {}
    rows = [(label_of(p), throws.get(_pitcher_id(p)), hands.get(p.game_pitch_id),
             p.actual_plate_x, p.actual_plate_z, p.run_value) for p in pitches]
    maps = build_maps(rows)
    _cache["key"], _cache["maps"] = key, maps
    return maps


def score_for_pitcher(db, pitches, throws):
    """Convenience: maps + batter hands + score, never raises (a failure
    just means no Best Zone section)."""
    from game_stats import get_batter_hands
    try:
        maps = get_maps(db)
        hands = get_batter_hands(db, pitches) if pitches else {}
        return score(pitches, throws, hands, maps, label_of), maps
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return [], None
