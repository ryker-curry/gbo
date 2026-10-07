"""
GBO -- Trends over time (Oct 2026, Ryker approved; grouping: by game by
default, with a by-week option -- college games come in weekend clusters
and fall ball is sparse, so week smooths the noise when a coach wants it).

Each metric is a series of points (one per game or per week) plus a
rolling line that POOLS the pitches of the last N points (more honest than
averaging percentages), the player's own average over the whole range, the
team average over the same range, and the 2026 D2 average where one exists.
summary(): change from the first N points to the last N points.

Pitchers: strike %, first-pitch strike %, hit-the-spot %, K-BB%+, ERA+,
          and from Rapsodo (bullpens + games) avg velo and Stuff+ per type.
Hitters:  swing decision %, chase %, whiff %, hard contact %, K %, OPS+.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import joinedload

from models import RapsodoPitch, PitchType
from analytics import hitter_insights as hi, league_baselines as lb, game_goals
from analytics.player_report import stat_bundle
from analytics.bullpen_metrics import pitch_type_label

PITCHER_METRICS = [
    # key, label, unit, higher_is_better, D2 baseline
    ("p_strike", "Strike %", "%", True, None),
    ("p_fps", "First-pitch strike %", "%", True, None),
    ("p_spot", "Hit-the-spot %", "%", True, None),
    ("p_kbb_plus", "K-BB%+ (vs D2)", "", True, 100),
    ("p_era_plus", "ERA+ (vs D2)", "", True, 100),
]
HITTER_METRICS = [
    ("h_swing_dec", "Swing decision %", "%", True, None),
    ("h_qab", "Quality at-bat %", "%", True, None),
    ("h_chase", "Chase %", "%", False, None),
    ("h_whiff", "Whiff %", "%", False, None),
    ("h_hard", "Hard contact %", "%", True, None),
    ("h_k", "Strikeout %", "%", False, lb.hitting("K%")),
    ("h_ops_plus", "OPS+ (vs D2)", "", True, 100),
]


# Non-league reference lines: Brian Cain's QAB goal (54% per game).
BENCHMARKS = {"h_qab": (54.0, "Cain QAB goal")}


def _bucket_key(d, by):
    return d - timedelta(days=d.weekday()) if by == "week" else d


def _group(pitches, by):
    """[(key, label, [pitches])] oldest first; one per game or week."""
    g = defaultdict(list)
    labels = {}
    for p in pitches:
        d = p.game.game_date
        if by == "week":
            k = (_bucket_key(d, by),)
            labels[k] = f"Wk {k[0].strftime('%b %d')}"
        else:
            k = (d, p.game_id)
            opp = "Intrasquad" if p.game.is_intrasquad else (
                p.game.opponent_team.team_name if getattr(p.game, "opponent_team", None) else (p.game.opponent_name or ""))
            labels[k] = f"{d.strftime('%b %d')} {opp}".strip()
        g[k].append(p)
    return [(k, labels[k], g[k]) for k in sorted(g)]


def _series(db, groups, metrics, rolling, names):
    out = {}
    for key, label, unit, hib, d2 in metrics:
        pts, roll = [], []
        for i, (_k, lab, ps) in enumerate(groups):
            pts.append((lab, game_goals.value(db, key, ps, None, names)))
            window = [p for _k2, _l2, ps2 in groups[max(0, i - rolling + 1): i + 1] for p in ps2]
            roll.append((lab, game_goals.value(db, key, window, None, names)))
        out[key] = {"label": label, "unit": unit, "hib": hib, "d2": d2, "points": pts, "rolling": roll}
    return out


def _summary(db, key, groups, n, names):
    if len(groups) < 2:
        return None
    n = min(n, len(groups) // 2) or 1
    first = [p for _k, _l, ps in groups[:n] for p in ps]
    last = [p for _k, _l, ps in groups[-n:] for p in ps]
    a, b = game_goals.value(db, key, first, None, names), game_goals.value(db, key, last, None, names)
    if a is None or b is None:
        return None
    return {"first": a, "last": b, "change": b - a, "n": n, "since": groups[0][1]}


def build(db, pitches, team_pitches, is_pitcher, by="game", rolling=5):
    """pitches: this player's game pitches (pitching or batting side)."""
    names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    metrics = PITCHER_METRICS if is_pitcher else HITTER_METRICS
    groups = _group(pitches, by)
    series = _series(db, groups, metrics, rolling if by == "game" else max(1, rolling // 3), names)
    for key, *_ in metrics:
        series[key]["mine"] = game_goals.value(db, key, pitches, None, names)
        series[key]["team"] = game_goals.value(db, key, team_pitches, None, names) if team_pitches else None
        series[key]["summary"] = _summary(db, key, groups, 5 if by == "game" else 2, names)
        series[key]["bench"] = BENCHMARKS.get(key)
    return {"groups": [(k, l) for k, l, _ps in groups], "series": series, "by": by, "rolling": rolling}


def velo_stuff(db, player_id, date_from, date_to, by="game", stuff_models=None):
    """Per pitch type: avg velo, top velo and Stuff+ per day (game OR bullpen)
    or per week, from every Rapsodo reading."""
    from datetime import datetime, time
    q = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
         .filter(RapsodoPitch.player_id == player_id))
    if date_from is not None:
        q = q.filter(RapsodoPitch.pitch_date >= datetime.combine(date_from, time.min))
    if date_to is not None:
        q = q.filter(RapsodoPitch.pitch_date < datetime.combine(date_to + timedelta(days=1), time.min))
    raps = q.all()
    if stuff_models is None:
        try:
            from analytics import profile_queries
            stuff_models = profile_queries.team_stuff_plus_baselines(db)
        except Exception:
            stuff_models = {}
    from analytics.pitch_grading import stuff_plus
    by_type = defaultdict(lambda: defaultdict(list))
    for r in raps:
        if r.pitch_date is None:
            continue
        d = r.pitch_date.date()
        k = _bucket_key(d, "week" if by == "week" else "day")
        by_type[pitch_type_label(r)][k].append(r)
    out = {}
    for label, days in by_type.items():
        if sum(len(v) for v in days.values()) < 5:
            continue
        model = stuff_models.get(label)
        rows = []
        for k in sorted(days):
            rs = days[k]
            vs = [float(r.velocity) for r in rs if r.velocity is not None]
            sp = [x for x in (stuff_plus(r, model) for r in rs) if x is not None] if model else []
            bus = [float(r.total_spin) / float(r.velocity) for r in rs
                   if r.total_spin is not None and r.velocity is not None and float(r.velocity) > 0]
            rows.append({"date": k, "n": len(rs), "velo": sum(vs) / len(vs) if vs else None,
                         "top": max(vs) if vs else None, "stuff": sum(sp) / len(sp) if sp else None,
                         "bu": sum(bus) / len(bus) if bus else None,   # Oct 2026: Bauer units
                         "bullpen": all(r.bullpen_id is not None for r in rs)})
        out[label] = rows
    return out


def team_pitches_in_range(db, date_from, date_to, pitching=True):
    """Every pitch our staff threw (pitching=True) or our hitters saw, in games
    between the two dates -- the team reference line."""
    from models import Game
    from analytics import team_report
    q = db.query(Game.game_id)
    if date_from is not None:
        q = q.filter(Game.game_date >= date_from)
    if date_to is not None:
        q = q.filter(Game.game_date <= date_to)
    ids = [gid for (gid,) in q.all()]
    return team_report.pitching_pitches(db, ids) if pitching else team_report.hitting_pitches(db, ids)
