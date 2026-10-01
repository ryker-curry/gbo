"""
GBO -- Player Ratings: the MLB-The-Show-style Overall on Player Profile
(Oct 2026, Ryker: "an overall profile combining everything with an
overall similar to mlb the show").

Decisions made with Ryker before building (AskUserQuestion, Oct 1 2026):
  - Visible to everyone, players included.
  - Hybrid scale: real outside benchmarks where one exists (fastball
    velocity), PSU-roster-relative for everything else (Stuff+,
    Command+, results, hitting rates).
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

  Fastball velocity uses VELO_ANCHORS (an outside benchmark, not
  roster-relative) -- a GBO starting point for college pitchers, meant
  to be tuned once Ryker looks at real cards. Athleticism maps the
  Bucket System total (already a percent-of-team-max score, so it runs
  high) through ATHLETE_ANCHORS the same way.

  Tiers use MLB The Show's own cut lines: Diamond 85+, Gold 80-84,
  Silver 75-79, Bronze 65-74, Common below 65.

ATTRIBUTES AND WEIGHTS (Baseball rating = weighted average of the
attributes this player actually has; missing ones are dropped and the
remaining weights renormalized, never zero-filled):
  Pitchers: VELO 20% (avg game fastball), STUFF 25% (Stuff+),
            CMD 20% (avg of Command+ and Location+), ARS 10% (Arsenal,
            usage-weighted Pitching+), RES 25% (Results composite:
            FIP/WHIP/K-BB/CSW/Zone Execution).
  Hitters:  CON 25% (AVG + Whiff%), POW 25% (ISO + SLG), EYE 15%
            (Chase% + BB%), RES 25% (wOBA), SPD 10% (Bucket System
            speed score).
  Overall = 85% Baseball + 15% Athlete (or whichever of the two exists).

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

# (avg game fastball mph, rating) -- piecewise-linear, clamped.
VELO_ANCHORS = [(78, 45), (82, 55), (85, 65), (88, 75), (91, 85), (94, 93), (97, 99)]
# (Bucket System 0-100 score, rating) -- used for ATH (total_score) and SPD (speed_score).
ATHLETE_ANCHORS = [(50, 45), (70, 60), (80, 72), (90, 85), (100, 99)]

PROVISIONAL_BF = 50
PROVISIONAL_PA = 30
MIN_BASELINE_HITTERS = 5
MIN_BASELINE_PA = 10

TIERS = [(85, "diamond"), (80, "gold"), (75, "silver"), (65, "bronze")]


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

def pitcher_attributes(row, avg_fastball_velo):
    """row: one dict from profile_queries.pitching_staff_leaderboard_rows
    (or None). Returns {key: (rating, raw_text)}."""
    row = row or {}
    cmd_plus = _mean_or_none([row.get("Command+"), row.get("Location+")])

    def fmt_plus(v):
        return f"{float(v):.0f}" if v is not None else None

    out = {
        "VELO": (anchored_rating(avg_fastball_velo, VELO_ANCHORS), f"{float(avg_fastball_velo):.1f} mph FB" if avg_fastball_velo is not None else None),
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
               hitter_line=None, hitter_baseline_=None, pa=None):
    """Everything the Player Profile card needs, for one player. Pitching
    and hitting are both computed when there's data for them (two-way
    players); the Overall uses the primary role -- pitching for a player
    flagged is_pitcher, hitting otherwise -- falling back to the other
    role if the primary one has no baseball data at all."""
    bd = bucket_data or {}
    athlete = anchored_rating(bd.get("total_score"), ATHLETE_ANCHORS)

    roles = {}
    if pitcher_row is not None or avg_fastball_velo is not None:
        attrs = pitcher_attributes(pitcher_row, avg_fastball_velo)
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


# ---------------------------------------------------------- DB loaders

def load_player_card(db, player, bucket_data, date_from, date_to, avg_fastball_velo=None):
    """Runs the roster-wide queries a card needs (pitching leaderboard
    rows, roster hitting lines) for the given window and builds this
    player's card."""
    from analytics.profile_queries import pitching_staff_leaderboard_rows

    pitcher_row = None
    bf = None
    rows = pitching_staff_leaderboard_rows(db, date_from=date_from, date_to=date_to)
    for row in rows:
        if row["player"].player_id == player.player_id:
            pitcher_row = row
            bf = row.get("BF")
            break

    hitter_lines = roster_hitting_lines(db, date_from, date_to)
    hitter_line = hitter_lines.get(player.player_id)
    baseline = hitter_baseline(list(hitter_lines.values()))

    card = build_card(
        is_pitcher=bool(getattr(player, "is_pitcher", False)),
        bucket_data=bucket_data,
        pitcher_row=pitcher_row, avg_fastball_velo=avg_fastball_velo, bf=bf,
        hitter_line=hitter_line, hitter_baseline_=baseline, pa=(hitter_line or {}).get("PA"),
    )
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
