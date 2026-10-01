"""
GBO -- Player Ratings: the MLB-The-Show-style Overall on Player Profile
(Oct 2026, Ryker: "an overall profile combining everything with an
overall similar to mlb the show").

Decisions made with Ryker before building (AskUserQuestion, Oct 1 2026):
  - Visible to everyone, players included.
  - Hybrid scale: real outside benchmarks where one exists,
    PSU-roster-relative for everything else (Stuff+, Command+, results,
    hitting rates). Oct 2026 change (Ryker: "change the benchmarks for
    velocity to be based on our own teams velocity stats"): fastball
    velocity is now roster-relative too -- graded against every PSU
    pitcher's average game fastball for the same season.
  - Player Profile layout: this card on top, then Athlete / Baseball
    tabs.
  - Athleticism (the Bucket System) is 15% of the Overall.

Pure computation + one roster-loading helper per role; every number
here is built from existing GBO metrics (pitching_staff_leaderboard_rows
for pitchers, compute_batting_line/compute_hitter_discipline for
hitters, compute_bucket_system for athleticism) -- no new data.

THE 0-99 SCALE
  Team average = 70, one standard deviation = 15 points, floor 40,
  cap 99 (so roughly: 55 = 1 SD below the PSU average, 85 = 1 SD
  above, 99 = 2 SD+). GBO's "+" stats (100 = team average, 10 = 1 SD)
  convert with plus_to_rating(). The 70 anchor is a deliberate
  Show-like choice: in MLB The Show a 70 is an everyday player, not a
  failing grade.

  Fastball velocity is roster-relative (see roster_fastball_velos):
  z-score of this pitcher's average game fastball against every PSU
  pitcher with MIN_VELO_FASTBALLS+ game fastballs that season, needing
  MIN_BASELINE_PITCHERS such pitchers for a baseline. Athleticism maps the
  Bucket System total (already a percent-of-team-max score, so it runs
  high) through ATHLETE_ANCHORS the same way.

  Tiers use MLB The Show's own cut lines: Diamond 85+, Gold 80-84,
  Silver 75-79, Bronze 65-74, Common below 65.

ATTRIBUTES AND WEIGHTS (Baseball rating = weighted average of the
attributes this player actually has; missing ones are dropped and the
remaining weights renormalized, never zero-filled):
  Pitchers: VELO 20% (avg game fastball vs. the PSU staff), STUFF 25% (Stuff+),
            CMD 20% (avg of Command+ and Location+), ARS 10% (Arsenal,
            usage-weighted Pitching+), RES 25% (Results composite:
            FIP/WHIP/K-BB/CSW/Zone Execution).
  Hitters:  CON 25% (AVG + Whiff%), POW 25% (ISO + SLG), EYE 15%
            (Chase% + BB%), RES 25% (wOBA), SPD 10% (Bucket System
            speed score).
  Overall = 85% Baseball + 15% Athlete (or whichever of the two exists).

PERCENTILE OVERALL (Oct 2026, Ryker: "right now everybody is about a 78,
need to adjust the scoring so we have diamonds")
  Averaging several attributes squeezes the composite (strengths and
  weaknesses cancel), so the raw Overall only spread ~6 points and
  nobody reached Diamond. The Overall, Baseball and Athlete numbers are
  now ROSTER PERCENTILES mapped onto a Show-shaped curve
  (PERCENTILE_CURVE), with Ryker's tier split:
      top 10% Diamond (85-99) · next 15% Gold (80-84) · next 25% Silver
      (75-79) · next 30% Bronze (65-74) · bottom 20% Common (<65)
  Overall and Baseball rank against qualified (non-provisional)
  players of the same primary role; Athlete ranks against every player
  with a Bucket System score. Provisional players are placed on the
  same curve but never count toward the pool. Pools smaller than
  MIN_PERCENTILE_POOL fall back to the raw (unranked) value. The
  attribute bars (Velocity, Stuff, Contact...) are NOT percentiled --
  they keep the 70-average/15-per-SD scale so strengths/weaknesses
  still read on the card.

RELIABILITY
  A pitcher with fewer than PROVISIONAL_BF batters faced, or a hitter
  with fewer than PROVISIONAL_PA plate appearances, in the window gets
  provisional=True -- the card says so rather than hiding the number.
  Roster-relative hitter attributes need at least MIN_BASELINE_HITTERS
  qualified hitters (MIN_BASELINE_PA each) to build a baseline at all.
"""

from statistics import mean, stdev

RATING_FLOOR, RATING_CAP = 40, 99
TEAM_AVG_RATING = 70
POINTS_PER_SD = 15

ATHLETE_WEIGHT = 0.15

PITCHER_WEIGHTS = {"VELO": 0.20, "STUFF": 0.25, "CMD": 0.20, "ARS": 0.10, "RES": 0.25}
HITTER_WEIGHTS = {"CON": 0.25, "POW": 0.25, "EYE": 0.15, "RES": 0.25, "SPD": 0.10}

ATTRIBUTE_LABELS = {
    "VELO": "Velocity", "STUFF": "Stuff", "CMD": "Command", "ARS": "Arsenal", "RES": "Results",
    "CON": "Contact", "POW": "Power", "EYE": "Eye", "SPD": "Speed", "ATH": "Athleticism",
}

# Velocity baseline (roster-relative since Oct 2026): a pitcher counts
# toward the staff average/SD only with this many game fastballs in the
# window, and the baseline needs this many such pitchers to exist.
MIN_VELO_FASTBALLS = 10
MIN_BASELINE_PITCHERS = 5
# (Bucket System 0-100 score, rating) -- used for ATH (total_score) and SPD (speed_score).
ATHLETE_ANCHORS = [(50, 45), (70, 60), (80, 72), (90, 85), (100, 99)]

PROVISIONAL_BF = 50
PROVISIONAL_PA = 30
MIN_BASELINE_HITTERS = 5
MIN_BASELINE_PA = 10

TIERS = [(85, "diamond"), (80, "gold"), (75, "silver"), (65, "bronze")]

# (roster percentile 0-100, rating) -- piecewise-linear. Lands the tier
# lines exactly on Ryker's split: 20th pct = 65 (Bronze starts), 50th =
# 75 (Silver), 75th = 80 (Gold), 90th = 85 (Diamond), best = 99.
PERCENTILE_CURVE = [(0, 45), (20, 65), (50, 75), (75, 80), (90, 85), (100, 99)]
MIN_PERCENTILE_POOL = 5
ROSTER_CACHE_SECONDS = 300


def _clamp(r):
    return int(round(max(RATING_FLOOR, min(RATING_CAP, r))))


def z_to_rating(z):
    return None if z is None else _clamp(TEAM_AVG_RATING + POINTS_PER_SD * z)


def plus_to_rating(plus):
    """GBO "+" scale (100 avg, 10 per SD) -> 0-99."""
    return None if plus is None else z_to_rating((float(plus) - 100.0) / 10.0)


def anchored_rating(value, anchors):
    if value is None:
        return None
    v = float(value)
    if v <= anchors[0][0]:
        x0, y0 = anchors[0]
        x1, y1 = anchors[1]
    elif v >= anchors[-1][0]:
        x0, y0 = anchors[-2]
        x1, y1 = anchors[-1]
    else:
        for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
            if x0 <= v <= x1:
                break
    return _clamp(y0 + (v - x0) * (y1 - y0) / (x1 - x0))


def tier_for(rating):
    if rating is None:
        return "common"
    for cut, name in TIERS:
        if rating >= cut:
            return name
    return "common"


def weighted_rating(ratings, weights):
    """ratings: {key: 0-99 or None}. Weighted mean over keys present,
    weights renormalized. None if nothing is present."""
    num = den = 0.0
    for key, w in weights.items():
        r = ratings.get(key)
        if r is None:
            continue
        num += w * r
        den += w
    return int(round(num / den)) if den else None


def combine_overall(baseball, athlete):
    if baseball is None and athlete is None:
        return None
    if baseball is None:
        return athlete
    if athlete is None:
        return baseball
    return int(round((1 - ATHLETE_WEIGHT) * baseball + ATHLETE_WEIGHT * athlete))


def _mean_or_none(values):
    vals = [float(v) for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


# ----------------------------------------------------------------- pitchers

def velo_baseline(staff_velos):
    """staff_velos: {player_id: (avg_mph, n_fastballs)} from
    roster_fastball_velos. Returns (mean, sd) over qualified pitchers,
    or None if there aren't enough of them."""
    vals = [v for v, n in staff_velos.values() if v is not None and n >= MIN_VELO_FASTBALLS]
    if len(vals) < MIN_BASELINE_PITCHERS:
        return None
    sd = stdev(vals)
    return (mean(vals), sd) if sd > 0 else None


def velo_rating(avg_fastball_velo, baseline):
    if avg_fastball_velo is None or baseline is None:
        return None
    return z_to_rating((float(avg_fastball_velo) - baseline[0]) / baseline[1])


def pitcher_attributes(row, avg_fastball_velo, velo_base=None):
    """row: one dict from profile_queries.pitching_staff_leaderboard_rows
    (or None). velo_base: velo_baseline() output. Returns
    {key: (rating, raw_text)}."""
    row = row or {}
    cmd_plus = _mean_or_none([row.get("Command+"), row.get("Location+")])

    def fmt_plus(v):
        return f"{float(v):.0f}" if v is not None else None

    out = {
        "VELO": (
            velo_rating(avg_fastball_velo, velo_base),
            (f"{float(avg_fastball_velo):.1f} mph FB" + (f" (staff avg {velo_base[0]:.1f})" if velo_base else ""))
            if avg_fastball_velo is not None else None,
        ),
        "STUFF": (plus_to_rating(row.get("Stuff+")), f"Stuff+ {fmt_plus(row.get('Stuff+'))}" if row.get("Stuff+") is not None else None),
        "CMD": (plus_to_rating(cmd_plus), " · ".join(x for x in [
            f"Command+ {fmt_plus(row.get('Command+'))}" if row.get("Command+") is not None else None,
            f"Location+ {fmt_plus(row.get('Location+'))}" if row.get("Location+") is not None else None,
        ] if x) or None),
        "ARS": (plus_to_rating(row.get("Arsenal")), f"Arsenal {fmt_plus(row.get('Arsenal'))}" if row.get("Arsenal") is not None else None),
        "RES": (plus_to_rating(row.get("Results")), f"Results {fmt_plus(row.get('Results'))}" if row.get("Results") is not None else None),
    }
    return out


# ------------------------------------------------------------------ hitters

def _hitter_metric_values(line):
    """The raw numbers each hitter attribute is built from (all floats or
    None). sign: +1 higher-is-better, -1 lower-is-better."""
    return {
        "AVG": (line.get("AVG"), +1), "Whiff %": (line.get("Whiff %"), -1),
        "ISO": (line.get("ISO"), +1), "SLG": (line.get("SLG"), +1),
        "Chase %": (line.get("Chase %"), -1), "BB %": (line.get("BB %"), +1),
        "wOBA": (line.get("wOBA"), +1),
    }


HITTER_ATTRIBUTE_METRICS = {
    "CON": ("AVG", "Whiff %"),
    "POW": ("ISO", "SLG"),
    "EYE": ("Chase %", "BB %"),
    "RES": ("wOBA",),
}


def hitter_baseline(lines):
    """lines: merged batting lines (compute_batting_line + discipline)
    for every roster hitter in the window. Only hitters with
    MIN_BASELINE_PA+ count. Returns {metric: (mean, sd)} or None if too
    few qualified hitters."""
    qualified = [l for l in lines if (l.get("PA") or 0) >= MIN_BASELINE_PA]
    if len(qualified) < MIN_BASELINE_HITTERS:
        return None
    base = {}
    for metric in ("AVG", "Whiff %", "ISO", "SLG", "Chase %", "BB %", "wOBA"):
        vals = [float(l[metric]) for l in qualified if l.get(metric) is not None]
        base[metric] = (mean(vals), stdev(vals)) if len(vals) >= 2 and stdev(vals) > 0 else None
    return base


def hitter_attributes(line, baseline, speed_score):
    """line: this hitter's merged batting line (or None). Returns
    {key: (rating, raw_text)}."""
    out = {}
    line = line or {}
    vals = _hitter_metric_values(line)
    for key, metrics in HITTER_ATTRIBUTE_METRICS.items():
        zs = []
        for m in metrics:
            v, sign = vals[m]
            b = (baseline or {}).get(m)
            if v is None or b is None:
                continue
            zs.append(sign * (float(v) - b[0]) / b[1])
        rating = z_to_rating(sum(zs) / len(zs)) if zs else None
        raw = " · ".join(_fmt_hitting(m, vals[m][0]) for m in metrics if vals[m][0] is not None) or None
        out[key] = (rating, raw)
    out["SPD"] = (anchored_rating(speed_score, ATHLETE_ANCHORS), f"Speed score {speed_score:.0f}" if speed_score is not None else None)
    return out


def _fmt_hitting(metric, v):
    if metric in ("AVG", "ISO", "SLG", "wOBA"):
        return f"{metric} {float(v):.3f}".replace(" 0.", " .")
    return f"{metric} {float(v):.1f}"


# ------------------------------------------------------------- full card

def build_card(*, is_pitcher, bucket_data, pitcher_row=None, avg_fastball_velo=None, bf=None,
               hitter_line=None, hitter_baseline_=None, pa=None, velo_base=None):
    """Everything the Player Profile card needs, for one player. Pitching
    and hitting are both computed when there's data for them (two-way
    players); the Overall uses the primary role -- pitching for a player
    flagged is_pitcher, hitting otherwise -- falling back to the other
    role if the primary one has no baseball data at all."""
    bd = bucket_data or {}
    athlete = anchored_rating(bd.get("total_score"), ATHLETE_ANCHORS)

    roles = {}
    if pitcher_row is not None or avg_fastball_velo is not None:
        attrs = pitcher_attributes(pitcher_row, avg_fastball_velo, velo_base)
        roles["pitching"] = {
            "attributes": attrs,
            "baseball": weighted_rating({k: v[0] for k, v in attrs.items()}, PITCHER_WEIGHTS),
            "sample": f"{bf} BF" if bf else None,
            "provisional": (bf or 0) < PROVISIONAL_BF,
            "weights": PITCHER_WEIGHTS,
        }
    if hitter_line is not None and (pa or 0) > 0:
        attrs = hitter_attributes(hitter_line, hitter_baseline_, bd.get("speed_score"))
        roles["hitting"] = {
            "attributes": attrs,
            "baseball": weighted_rating({k: v[0] for k, v in attrs.items()}, HITTER_WEIGHTS),
            "sample": f"{pa} PA" if pa else None,
            "provisional": (pa or 0) < PROVISIONAL_PA,
            "weights": HITTER_WEIGHTS,
        }

    order = ["pitching", "hitting"] if is_pitcher else ["hitting", "pitching"]
    primary = next((r for r in order if r in roles and roles[r]["baseball"] is not None), None)
    if primary is None:
        primary = next((r for r in order if r in roles), None)
    baseball = roles[primary]["baseball"] if primary else None
    overall = combine_overall(baseball, athlete)
    return {
        "overall": overall,
        "tier": tier_for(overall),
        "baseball": baseball,
        "athlete": athlete,
        "primary_role": primary,
        "roles": roles,
        "provisional": bool(primary and roles[primary]["provisional"]),
        "athlete_raw": f"Bucket total {bd['total_score']:.0f}" if bd.get("total_score") is not None else None,
    }


# ------------------------------------------------------ percentile layer

def roster_percentile(value, pool, is_member):
    """0-100. Members: share of the OTHER pool members below (ties
    count half), so the best qualified player is 100 and the worst 0.
    Non-members (provisional players): share of the pool below."""
    if value is None or not pool:
        return None
    below = sum(1 for v in pool if v < value)
    equal = sum(1 for v in pool if v == value)
    if is_member:
        n = len(pool) - 1
        if n <= 0:
            return 50.0
        return 100.0 * (below + 0.5 * max(equal - 1, 0)) / n
    return 100.0 * (below + 0.5 * equal) / len(pool)


def percentile_rating(pct):
    """Roster percentile -> rating on PERCENTILE_CURVE. Floors (not
    rounds) so the tier lines land exactly on the percentile split -- a
    player at the 89.9th percentile is Gold (84), not rounded up into
    Diamond."""
    if pct is None:
        return None
    import math
    v = max(0.0, min(100.0, float(pct)))
    for (x0, y0), (x1, y1) in zip(PERCENTILE_CURVE, PERCENTILE_CURVE[1:]):
        if x0 <= v <= x1:
            r = y0 + (v - x0) * (y1 - y0) / (x1 - x0)
            return int(max(RATING_FLOOR, min(RATING_CAP, math.floor(r + 1e-9))))
    return RATING_CAP


def apply_roster_percentiles(card, raw_cards, player_id):
    """Rescales card's overall/baseball/athlete to roster percentiles.
    raw_cards: {player_id: raw build_card() output} for the roster.
    Keeps the raw composites as overall_raw/baseball_raw/athlete_raw_value
    and adds *_pct and pool sizes for the breakdown. Returns card."""
    role = card.get("primary_role")
    card["overall_raw"], card["baseball_raw"], card["athlete_raw_value"] = card["overall"], card["baseball"], card["athlete"]

    def scale(field, value, pool_cards):
        """pool_cards: list of (pid, raw_card). The player's own pool slot
        (if he qualifies) is filled with his CURRENT value, so the page's
        live numbers and the ranking always agree."""
        member = any(pid == player_id and c.get(field) is not None for pid, c in pool_cards)
        pool = [c[field] for pid, c in pool_cards if pid != player_id and c.get(field) is not None]
        if member and value is not None:
            pool.append(value)
        if value is None or len(pool) < MIN_PERCENTILE_POOL:
            return value, None, len(pool)
        pct = roster_percentile(value, pool, member)
        return percentile_rating(pct), pct, len(pool)

    role_pool = [(pid, c) for pid, c in raw_cards.items() if c.get("primary_role") == role and not c.get("provisional")]
    card["overall"], card["overall_pct"], card["overall_pool"] = scale("overall", card["overall_raw"], role_pool)
    card["baseball"], card["baseball_pct"], card["baseball_pool"] = scale("baseball", card["baseball_raw"], role_pool)
    athlete_pool = [(pid, c) for pid, c in raw_cards.items() if c.get("athlete") is not None]
    card["athlete"], card["athlete_pct"], card["athlete_pool"] = scale("athlete", card["athlete_raw_value"], athlete_pool)
    card["tier"] = tier_for(card["overall"])
    return card


_ROSTER_CACHE = {}


def roster_context(db, date_from, date_to, season_label=None):
    """Everything roster-wide a card needs, computed once and cached for
    ROSTER_CACHE_SECONDS per season window (it grades the whole staff
    and scores every player's Bucket System, too slow to redo on every
    page load). New games/imports/assessments show up within that
    window. Returns dict with pitch_rows, staff_velos, velo_base,
    hit_lines, hit_base, buckets, raw_cards."""
    import time
    from models import Player
    from analytics.profile_queries import pitching_staff_leaderboard_rows
    from bucket_system import build_roster_batch_cache, compute_bucket_system

    key = (date_from, date_to, season_label)
    hit = _ROSTER_CACHE.get(key)
    if hit and time.time() - hit[0] < ROSTER_CACHE_SECONDS:
        return hit[1]

    pitch_rows = {r["player"].player_id: r for r in pitching_staff_leaderboard_rows(db, date_from=date_from, date_to=date_to)}
    staff_velos = roster_fastball_velos(db, date_from, date_to)
    velo_base = velo_baseline(staff_velos)
    hit_lines = roster_hitting_lines(db, date_from, date_to)
    hit_base = hitter_baseline(list(hit_lines.values()))

    buckets = {}
    try:
        cache, units, throws_map, _active_only = build_roster_batch_cache(db, season_label=season_label)
        for p in db.query(Player).filter(Player.active.is_(True)).all():
            try:
                buckets[p.player_id] = compute_bucket_system(db, p.player_id, season_label=season_label, _cache=cache, _units=units, _throws_map=throws_map) or {}
            except Exception:
                buckets[p.player_id] = {}
    except Exception:
        buckets = {}

    players = {p.player_id: p for p in db.query(Player).filter(
        Player.player_id.in_(set(pitch_rows) | set(staff_velos) | set(hit_lines) | set(buckets))
    ).all()}
    raw_cards = {}
    for pid, p in players.items():
        own_v = staff_velos.get(pid)
        line = hit_lines.get(pid)
        row = pitch_rows.get(pid)
        raw_cards[pid] = build_card(
            is_pitcher=bool(p.is_pitcher), bucket_data=buckets.get(pid, {}),
            pitcher_row=row, avg_fastball_velo=own_v[0] if own_v else None, bf=(row or {}).get("BF"),
            hitter_line=line, hitter_baseline_=hit_base, pa=(line or {}).get("PA"), velo_base=velo_base,
        )
    ctx = dict(pitch_rows=pitch_rows, staff_velos=staff_velos, velo_base=velo_base,
               hit_lines=hit_lines, hit_base=hit_base, buckets=buckets, raw_cards=raw_cards)
    _ROSTER_CACHE.clear()
    _ROSTER_CACHE[key] = (time.time(), ctx)
    return ctx


# ---------------------------------------------------------- DB loaders

def load_player_card(db, player, bucket_data, date_from, date_to, avg_fastball_velo=None, season_label=None):
    """This player's card for the given window: attributes from the
    roster-wide context (roster_context, cached briefly), Overall/
    Baseball/Athlete as roster percentiles (apply_roster_percentiles).
    bucket_data is the page's own live Bucket System rollup for him."""
    ctx = roster_context(db, date_from, date_to, season_label)
    pid = player.player_id
    pitcher_row = ctx["pitch_rows"].get(pid)
    own = ctx["staff_velos"].get(pid)
    if own is not None and own[0] is not None:
        avg_fastball_velo = own[0]
    hitter_line = ctx["hit_lines"].get(pid)

    card = build_card(
        is_pitcher=bool(getattr(player, "is_pitcher", False)),
        bucket_data=bucket_data,
        pitcher_row=pitcher_row, avg_fastball_velo=avg_fastball_velo, bf=(pitcher_row or {}).get("BF"),
        hitter_line=hitter_line, hitter_baseline_=ctx["hit_base"], pa=(hitter_line or {}).get("PA"),
        velo_base=ctx["velo_base"],
    )
    apply_roster_percentiles(card, ctx["raw_cards"], pid)
    # Raw inputs too, so Player Profile's Baseball tab can show the
    # underlying lines without re-running these roster queries.
    card["pitcher_row"] = pitcher_row
    card["hitter_line"] = hitter_line
    return card


def roster_hitting_lines(db, date_from=None, date_to=None):
    """{player_id: compute_batting_line() merged with Chase %/Whiff %/
    Zone Swing %/BB %} for every roster hitter in the window -- same
    population as profile_queries.team_hitting_lines, just keyed by
    player so one hitter's line can be picked out."""
    from sqlalchemy.orm import joinedload
    from models import Game, GamePitch
    from game_stats import compute_batting_line
    from plate_discipline import compute_hitter_discipline

    query = (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(
            (GamePitch.is_our_team_batting.is_(True))
            | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id.isnot(None)))
        )
    )
    if date_from is not None:
        query = query.filter(Game.game_date >= date_from)
    if date_to is not None:
        query = query.filter(Game.game_date <= date_to)
    by_player = {}
    for p in query.all():
        pid = p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id
        if pid is not None:
            by_player.setdefault(pid, []).append(p)
    lines = {}
    for pid, ps in by_player.items():
        line = compute_batting_line(ps)
        disc = compute_hitter_discipline(ps)
        line["Chase %"] = disc["Chase %"]
        line["Whiff %"] = disc["Whiff %"]
        line["Zone Swing %"] = disc["Zone Swing %"]
        lines[pid] = line
    return lines


def roster_fastball_velos(db, date_from=None, date_to=None):
    """{player_id: (avg_mph, n)} -- every pitcher's average GAME fastball
    velocity (Rapsodo readings matched to a GamePitch, fastball types
    only -- the same pitches Player Profile's VELO stat has always used)
    for games in the window."""
    from models import Game, GamePitch, PitchType, RapsodoPitch
    from pitch_type_config import FASTBALL_TYPES

    query = (
        db.query(RapsodoPitch.player_id, RapsodoPitch.velocity)
        .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
        .join(Game, GamePitch.game_id == Game.game_id)
        .join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id)
        .filter(PitchType.type_name.in_(FASTBALL_TYPES), RapsodoPitch.velocity.isnot(None))
    )
    if date_from is not None:
        query = query.filter(Game.game_date >= date_from)
    if date_to is not None:
        query = query.filter(Game.game_date <= date_to)
    by_player = {}
    for pid, velo in query.all():
        by_player.setdefault(pid, []).append(float(velo))
    return {pid: (sum(v) / len(v), len(v)) for pid, v in by_player.items()}
