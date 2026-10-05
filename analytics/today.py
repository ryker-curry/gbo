"""
GBO -- "Today" box at the top of every dashboard (Oct 2026, Ryker
approved Part 2). Pure data; shiny_app/modules/today_box.py draws it.

coach_today(db, player_ids, today)  -> who can throw, last game, charting
                                       to fix, goals off track
player_today(db, player_id, today)  -> my status (pitchers), my last game,
                                       my goals, my weekly report
Every piece is wrapped so one failing part never blanks the whole box.
"""

from datetime import date, timedelta

from sqlalchemy.orm import joinedload

from models import Game, GamePitch, IDPGoal, Player
import game_stats

DONE_GOAL = ("completed", "complete", "achieved", "cancelled", "canceled")
HEALTH_DAYS = 14


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:
        return None


def _name(p):
    return f"{p.first_name} {p.last_name}"


def _game_line(g):
    from analytics.team_report import opponent_label
    res = ""
    if g.status == "Final" and not g.is_intrasquad and g.our_score is not None and g.opponent_score is not None:
        wl = "W" if g.our_score > g.opponent_score else ("L" if g.our_score < g.opponent_score else "T")
        res = f"{wl} {g.our_score}-{g.opponent_score}"
    return {"game_id": g.game_id, "date": g.game_date, "opponent": opponent_label(g), "result": res,
            "intrasquad": bool(g.is_intrasquad)}


# ---- coaches ------------------------------------------------------------------
def arm_summary(db, today, player_ids=None):
    from analytics import arm_care
    rows = arm_care.board(db, as_of=today)
    if player_ids is not None:
        rows = [r for r in rows if r["player"].player_id in player_ids]
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("Available", "Limited", "Down", "Hold")}
    out = [{"name": _name(r["player"]), "status": r["status"], "reason": r["reason"], "ready_on": r["ready_on"]}
           for r in rows if r["status"] != "Available"]
    return {"counts": counts, "total": len(rows), "not_available": out}


def last_game(db, today):
    gids = {gid for (gid,) in db.query(GamePitch.game_id).distinct().all()}
    if not gids:
        return None
    g = (db.query(Game).options(joinedload(Game.opponent_team))
         .filter(Game.game_id.in_(gids), Game.game_date <= today, Game.is_intrasquad.is_(False))
         .order_by(Game.game_date.desc(), Game.game_id.desc()).first())
    return _game_line(g) if g else None


def health_summary(db, today):
    from analytics import data_health
    res = data_health.check_range(db, today - timedelta(days=HEALTH_DAYS), today)
    if not res:
        return None
    to_fix = [r for r in res if r["grade"] != "green"]
    no_box = [r for r in res if not r["game"].is_intrasquad and not r["has_box"]]
    box_off = [r for r in res if r["has_box"] and any(not x["ok"] for x in r["box_rows"])]
    return {"games": len(res), "to_fix": len(to_fix), "no_box": len(no_box), "box_off": len(box_off),
            "avg": round(sum(r["score"] for r in res) / len(res))}


def goals_off_track(db, player_ids=None):
    from analytics import game_goals
    q = db.query(IDPGoal).options(joinedload(IDPGoal.status), joinedload(IDPGoal.player),
                                  joinedload(IDPGoal.target_pitch_type))
    if player_ids is not None:
        q = q.filter(IDPGoal.player_id.in_(list(player_ids) or [-1]))
    goals = [g for g in q.all() if not (g.status and g.status.status_name.lower() in DONE_GOAL)]
    info = game_goals.goal_info(db, [g.goal_id for g in goals])
    out = []
    for g in goals:
        if g.goal_id not in info:
            continue
        p = game_goals.progress(db, g, info[g.goal_id])
        if p and p["status"] == "Off track":
            out.append({"name": _name(g.player) if g.player else "", "label": p["label"],
                        "current": game_goals.fmt(p["key"], p["current"]), "target": game_goals.fmt(p["key"], p["target"]),
                        "higher_better": p["higher_better"]})
    return out


def coach_today(db, player_ids=None, today=None, pitching=True):
    today = today or date.today()
    pid_set = set(player_ids) if player_ids is not None else None
    return {
        "today": today,
        "arm": _safe(arm_summary, db, today, pid_set) if pitching else None,
        "last_game": _safe(last_game, db, today),
        "health": _safe(health_summary, db, today),
        "goals_off": _safe(goals_off_track, db, pid_set) or [],
    }


# ---- players -----------------------------------------------------------------
def _pitching_game(db, player_id, today):
    from analytics.player_report import pitcher_games, pitcher_pitches
    games = [g for g in pitcher_games(db, player_id) if g.game_date and g.game_date <= today]
    if not games:
        return None
    g = games[0]
    line = game_stats.compute_pitching_line(pitcher_pitches(db, player_id, game_id=g.game_id))
    stats = [("IP", line.get("IP")), ("H", line.get("H Allowed")), ("R", line.get("Runs Allowed")),
             ("BB", line.get("BB")), ("K", line.get("K")), ("Pitches", line.get("Pitches")),
             ("Strike %", line.get("Strike %"))]
    return {**_game_line(g), "stats": stats}


def _hitting_game(db, player_id, today):
    from analytics.hitter_report import hitter_games, hitter_pitches
    games = [g for g in hitter_games(db, player_id) if g.game_date and g.game_date <= today]
    if not games:
        return None
    g = games[0]
    line = game_stats.compute_batting_line(hitter_pitches(db, player_id, game_id=g.game_id))
    stats = [("H-AB", f"{line.get('H', 0)}-{line.get('AB', 0)}"), ("BB", line.get("BB")), ("K", line.get("K")),
             ("QAB", f"{line.get('QAB', 0)} of {line.get('PA', 0)}")]
    return {**_game_line(g), "stats": stats}


def my_goals(db, player_id, limit=4):
    from analytics.player_report import idp_goals
    return (idp_goals(db, player_id, limit=limit) or [])[:limit]


def player_today(db, player_id, today=None):
    from analytics import arm_care, weekly_report
    today = today or date.today()
    p = db.query(Player).filter(Player.player_id == player_id).first()
    if p is None:
        return None
    arm = _safe(arm_care.pitcher_row, db, p, today) if p.is_pitcher else None
    if arm is not None:
        arm = {"status": arm["status"], "reason": arm["reason"], "ready_on": arm["ready_on"],
               "last": arm["last"], "last_pitches": arm["last_pitches"]}
    game = _safe(_pitching_game, db, player_id, today) if p.is_pitcher else _safe(_hitting_game, db, player_id, today)
    week = _safe(weekly_report.last_completed_week, today)
    return {"today": today, "player": p, "is_pitcher": bool(p.is_pitcher), "arm": arm, "last_game": game,
            "goals": _safe(my_goals, db, player_id) or [], "week": week}
