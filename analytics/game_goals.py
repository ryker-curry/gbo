"""
GBO -- Development goals on game stats (Oct 2026, Ryker approved: goals can
track game stats, progress updates automatically after every game, coaches
AND players can set them, lower-is-better stats are "under X" goals).

An IDPGoal with game_metric set is a game-stat goal:
  game_metric   -- key in GAME_METRICS
  metric_window -- "last5" / "last10" / "season" (games, newest first)
  baseline_value-- value when the goal was set
  target_value  -- the target (direction comes from GAME_METRICS)
  target_pitch_type_id -- only for pitch velo goals

progress(db, goal) -> current value, per-game series, status:
  Met            current is at/past the target
  On track       at least halfway from the baseline to the target
  Making progress moving the right way, less than halfway
  Off track      not better than the baseline
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from models import Game, GamePitch, PitchType, RapsodoPitch, Player
from analytics import hitter_insights as hi, league_baselines as lb
from analytics.player_report import stat_bundle

WINDOWS = {"last5": ("Last 5 games", 5), "last10": ("Last 10 games", 10), "season": ("Season to date", None)}

# key: (label, side, higher_is_better, unit, short description)
GAME_METRICS = {
    # hitters
    "h_chase": ("Chase %", "hit", False, "%", "swings at pitches off the plate"),
    "h_swing_dec": ("Swing decision %", "hit", True, "%", "swung at strikes, took balls"),
    "h_whiff": ("Whiff %", "hit", False, "%", "misses per swing"),
    "h_k": ("Strikeout %", "hit", False, "%", "strikeouts per plate appearance"),
    "h_bb": ("Walk %", "hit", True, "%", "walks per plate appearance"),
    "h_hard": ("Hard contact %", "hit", True, "%", "barreled/solid per ball in play"),
    "h_ops_plus": ("OPS+ (vs D2)", "hit", True, "", "100 = D2 average"),
    "h_two_k": ("2-strike K %", "hit", False, "%", "strikeouts once at two strikes"),
    # pitchers
    "p_strike": ("Strike %", "pitch", True, "%", "share of pitches that were strikes"),
    "p_fps": ("First-pitch strike %", "pitch", True, "%", "started hitters 0-1"),
    "p_spot": ("Hit-the-spot %", "pitch", True, "%", "landed in the called zone (video review)"),
    "p_bb": ("Walk %", "pitch", False, "%", "walks per batter faced"),
    "p_whiff": ("Whiff %", "pitch", True, "%", "misses per swing"),
    "p_kbb_plus": ("K-BB%+ (vs D2)", "pitch", True, "", "100 = D2 average"),
    "p_era_plus": ("ERA+ (vs D2)", "pitch", True, "", "100 = D2 average"),
    "p_velo": ("Velo (pitch type)", "pitch", True, " mph", "average game velo for one pitch type"),
}


def metrics_for(is_pitcher):
    side = "pitch" if is_pitcher else "hit"
    return {k: v for k, v in GAME_METRICS.items() if v[1] == side}


def _batting(db, pid):
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
            .filter(or_(and_(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == pid),
                        and_(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id == pid)))
            .order_by(Game.game_date, GamePitch.pitch_sequence).all())


def _pitching(db, pid):
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
            .filter(or_(and_(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == pid),
                        and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id == pid)))
            .order_by(Game.game_date, GamePitch.pitch_sequence).all())


def _by_game(pitches):
    g = defaultdict(list)
    for p in pitches:
        g[(p.game.game_date, p.game_id)].append(p)
    return [g[k] for k in sorted(g)]


def value(db, key, pitches, pitch_type_id=None, names=None):
    """The metric over a list of game pitches (one or many games)."""
    if not pitches:
        return None
    side = GAME_METRICS[key][1]
    if side == "hit":
        m = hi.core_metrics(pitches)
        if key == "h_chase":
            return m["Chase %"]
        if key == "h_swing_dec":
            return m["Swing Decision %"]
        if key == "h_whiff":
            return m["Whiff %"]
        if key == "h_k":
            return m["K%"]
        if key == "h_bb":
            return m["BB%"]
        if key == "h_hard":
            return m["Hard contact %"]
        if key == "h_two_k":
            return m["2-strike K %"]
        if key == "h_ops_plus":
            if m["OBP"] is None or m["SLG"] is None:
                return None
            return round(100 * (m["OBP"] / lb.hitting("OBP") + m["SLG"] / lb.hitting("SLG") - 1))
    if key == "p_velo":
        ids = [p.game_pitch_id for p in pitches if pitch_type_id is None or p.pitch_type_id == pitch_type_id]
        if not ids:
            return None
        vs = [float(v) for (v,) in db.query(RapsodoPitch.velocity).filter(
            RapsodoPitch.game_pitch_id.in_(ids), RapsodoPitch.velocity.isnot(None)).all()]
        return round(sum(vs) / len(vs), 1) if vs else None
    names = names or {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    b = stat_bundle(pitches, names)
    if b is None:
        return None
    if key == "p_strike":
        return b["strike_pct"]
    if key == "p_fps":
        return b["fps_pct"]
    if key == "p_spot":
        return b["execution_pct"]
    if key == "p_bb":
        return b["bb_pct"]
    if key == "p_whiff":
        return b["whiff_pct"]
    if key == "p_kbb_plus":
        if b["k_pct"] is None or b["bb_pct"] is None:
            return None
        return round(100 * (b["k_pct"] - b["bb_pct"]) / lb.pitching("kbb_pct"))
    if key == "p_era_plus":
        return round(100 * lb.pitching("era") / b["era"]) if b.get("era") else None
    return None


def current(db, player_id, key, window="last5", pitch_type_id=None):
    """(value, n_games, per-game series [(date, value)]) for the window."""
    side = GAME_METRICS[key][1]
    pitches = _batting(db, player_id) if side == "hit" else _pitching(db, player_id)
    games = _by_game(pitches)
    if window == "season":
        start = date(date.today().year if date.today().month >= 8 else date.today().year - 1, 8, 1)
        games = [g for g in games if g[0].game.game_date >= start]
    else:
        games = games[-WINDOWS.get(window, WINDOWS["last5"])[1]:]
    names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    flat = [p for g in games for p in g]
    series = [(g[0].game.game_date, value(db, key, g, pitch_type_id, names)) for g in games]
    return value(db, key, flat, pitch_type_id, names), len(games), series


def status(key, baseline, cur, target):
    if cur is None or target is None:
        return "No games yet"
    hib = GAME_METRICS[key][2]
    met = cur >= target if hib else cur <= target
    if met:
        return "Met"
    if baseline is None or baseline == target:
        return "Making progress"
    frac = (cur - baseline) / (target - baseline)
    if frac >= 0.5:
        return "On track"
    if frac > 0:
        return "Making progress"
    return "Off track"


STATUS_TONE = {"Met": "good", "On track": "good", "Making progress": "watch", "Off track": "flag", "No games yet": "neutral"}


def fmt(key, v):
    if v is None:
        return "—"
    unit = GAME_METRICS[key][3]
    if unit == "%":
        return f"{v:.0f}%"
    if unit == " mph":
        return f"{v:.1f} mph"
    return f"{v:.0f}"


def goal_info(db, goal_ids):
    """{goal_id: (game_metric, metric_window)} for the game-stat goals among
    goal_ids. Safe before the migration runs (returns {} and rolls back)."""
    from models import IDPGoal
    ids = list(goal_ids)
    if not ids:
        return {}
    try:
        rows = (db.query(IDPGoal.goal_id, IDPGoal.game_metric, IDPGoal.metric_window)
                .filter(IDPGoal.goal_id.in_(ids), IDPGoal.game_metric.isnot(None)).all())
        return {gid: (m, w) for gid, m, w in rows}
    except Exception:
        db.rollback()
        return {}


def progress(db, goal, info=None):
    """info: (game_metric, metric_window) from goal_info(); looked up if None."""
    if info is None:
        info = goal_info(db, [goal.goal_id]).get(goal.goal_id)
    if not info:
        return None
    key, window = info
    if not key or key not in GAME_METRICS:
        return None
    window = window or "last5"
    cur, n, series = current(db, goal.player_id, key, window, goal.target_pitch_type_id)
    base = float(goal.baseline_value) if goal.baseline_value is not None else None
    tgt = float(goal.target_value) if goal.target_value is not None else None
    st = status(key, base, cur, tgt)
    label, _side, hib, _u, desc = GAME_METRICS[key]
    pt = f" ({goal.target_pitch_type.type_name})" if getattr(goal, "target_pitch_type", None) else ""
    line = (f"{label}{pt}: {fmt(key, cur)} now -> target {'over' if hib else 'under'} {fmt(key, tgt)} "
            f"({WINDOWS.get(window, WINDOWS['last5'])[0].lower()}) · started at {fmt(key, base)} · {st}")
    return {"key": key, "label": label + pt, "current": cur, "baseline": base, "target": tgt, "status": st,
            "tone": STATUS_TONE[st], "games": n, "series": series, "window": window, "line": line,
            "higher_better": hib, "desc": desc}


def suggest_target(key, cur):
    """A sensible stretch target from the current value."""
    if cur is None:
        return None
    hib = GAME_METRICS[key][2]
    unit = GAME_METRICS[key][3]
    if unit == "%":
        step = 5.0
    elif unit == " mph":
        step = 1.5
    else:
        step = 15.0
    return round(cur + step, 1) if hib else round(max(cur - step, 0), 1)
