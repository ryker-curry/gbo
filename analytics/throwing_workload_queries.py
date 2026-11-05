"""
GBO -- Throwing Workload: database side of analytics/throwing_workload.py.
Pitch counts come from workload_queries.py (same no-double-count rules as
Arm Care); throw_logs and throwing_assumptions are the new tables.
"""

from collections import Counter
from datetime import timedelta

from sqlalchemy import func

from models import (BullpenSession, Game, GamePitch, Player, TeamEventType, TeamScheduleEvent, ThrowingAssumption,
                    ThrowLog)
from analytics import throwing_workload as tw
from analytics.workload_queries import _bullpen_session_pitch_counts, _game_pitch_dates

LOOKBACK = tw.CHRONIC_DAYS + tw.ACUTE_DAYS   # extra history so the first shown day has full windows


def assumptions(db):
    try:
        s = db.query(ThrowingAssumption).filter(ThrowingAssumption.setting_id == 1).first()
    except Exception:
        db.rollback()
        s = None
    if s is None:
        return dict(tw.DEFAULT_ASSUME)
    return {"pen_warmup": s.pen_warmup, "game_warmup": s.game_warmup, "catch_play": s.catch_play,
            "catch_play_days": s.catch_play_days}


def practice_days(db, d0, d1):
    """Team practice days a pitcher would be throwing (whole team or
    pitchers-only practice events)."""
    rows = (db.query(TeamScheduleEvent.scheduled_date).join(TeamEventType,
                                                           TeamEventType.event_type_id == TeamScheduleEvent.event_type_id)
            .filter(func.lower(TeamEventType.type_name).like("%practice%"),
                    TeamScheduleEvent.scheduled_date >= d0, TeamScheduleEvent.scheduled_date <= d1,
                    (TeamScheduleEvent.pitchers_only.is_(None)) | (TeamScheduleEvent.pitchers_only.is_(True)))
            .all())
    return {r[0] for r in rows}


def _logs(db, pid, d0, d1):
    try:
        rows = (db.query(ThrowLog).filter(ThrowLog.player_id == pid, ThrowLog.log_date >= d0,
                                          ThrowLog.log_date <= d1).all())
    except Exception:          # table not created yet
        db.rollback()
        return []
    return [{"date": r.log_date, "throws": r.throws, "throw_type": r.throw_type, "source": r.source,
             "high_intent": r.high_intent, "id": r.throw_log_id} for r in rows]


def _first_record(db, pid):
    """Earliest date this pitcher has any throwing record in GBO."""
    cands = [
        db.query(func.min(Game.game_date)).join(GamePitch, GamePitch.game_id == Game.game_id).filter(
            ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == pid))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == pid))).scalar(),
        db.query(func.min(BullpenSession.session_date)).filter(BullpenSession.player_id == pid).scalar(),
    ]
    try:
        cands.append(db.query(func.min(ThrowLog.log_date)).filter(ThrowLog.player_id == pid).scalar())
    except Exception:
        db.rollback()
    cands = [c for c in cands if c is not None]
    return min(cands) if cands else None


def pitcher_rows(db, pid, d0, d1, assume=None, practice=None):
    """with_ratio rows for one pitcher, d0..d1 (history before d0 is loaded
    for the windows, then trimmed)."""
    h0 = d0 - timedelta(days=LOOKBACK)
    game = Counter(_game_pitch_dates(db, pid, h0, d1))
    pen = Counter()
    for d, n in _bullpen_session_pitch_counts(db, pid, h0, d1):
        pen[d] += n
    rows = tw.daily_parts(h0, d1, game=game, bullpen=pen, logs=_logs(db, pid, h0, d1),
                          practice_days=practice if practice is not None else practice_days(db, h0, d1),
                          assume=assume or assumptions(db), tracking_start=_first_record(db, pid))
    return [r for r in tw.with_ratio(rows) if r["date"] >= d0]


def team_table(db, as_of):
    """[{"player", **summary}] for every active pitcher, as of a date."""
    d0 = as_of - timedelta(days=tw.CHRONIC_DAYS - 1)
    a = assumptions(db)
    prac = practice_days(db, d0 - timedelta(days=LOOKBACK), as_of)
    out = []
    for p in (db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
              .order_by(Player.last_name, Player.first_name).all()):
        rows = pitcher_rows(db, p.player_id, d0, as_of, assume=a, practice=prac)
        s = tw.summary(rows, as_of) if rows else None
        out.append({"player": p, **(s or {})})
    return out


def recent_logs(db, pid, limit=12):
    try:
        return (db.query(ThrowLog).filter(ThrowLog.player_id == pid)
                .order_by(ThrowLog.log_date.desc(), ThrowLog.throw_log_id.desc()).limit(limit).all())
    except Exception:
        db.rollback()
        return []
