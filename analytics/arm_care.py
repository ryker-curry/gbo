"""
GBO -- Arm Care & Availability (Oct 2026, Ryker approved: rest chart as
proposed, staff only, under Pitching).

Per pitcher, as of a date:
  last outing   -- most recent day he threw (games + bullpens, from
                   workload_queries.get_daily_pitch_counts -- bullpens are
                   max(BullpenPitch, Rapsodo, Command) per session so nothing
                   double-counts), its pitch count and whether it was a game
  required rest -- REST_CHART on that day's pitch count
  days of rest  -- full days since that outing
  7-day load    -- pitches in the last 7 days
  workload ratio-- acute:chronic (workload_metrics.compute_daily_acwr);
                   "building history" for his first 4 weeks
  auto status   -- Down    : not rested yet (or threw today)
                   Limited : rested, but workload ratio > 1.5 (spike) --
                             LIMITED_PITCHES max
                   Available otherwise
  coach status  -- an active PitcherAvailability "status" row overrides
                   (Available / Limited / Hold)
  plans         -- upcoming planned outings, each flagged if he won't be
                   rested (or is on hold) by then

Rest chart = college-adjusted Pitch Smart (approved as-is). Guidance, not
a medical decision -- the athletic trainer and coaches have the final say.
"""

from datetime import date, timedelta

from models import Player, Game, GamePitch, PitcherAvailability
from analytics.workload_queries import get_daily_pitch_counts
from analytics.workload_metrics import compute_daily_acwr, ZONE_ELEVATED_MAX, ZONE_SWEET_SPOT_MAX, ZONE_UNDER_TRAINING_MAX

REST_CHART = [(30, 0), (45, 1), (60, 2), (75, 3), (10 ** 6, 4)]
LIMITED_PITCHES = 25
STATUS_ORDER = {"Available": 0, "Limited": 1, "Down": 2, "Hold": 3}


def required_rest(pitches):
    if not pitches:
        return 0
    for cap, days in REST_CHART:
        if pitches <= cap:
            return days
    return REST_CHART[-1][1]


def _game_days(db, pid, d0, d1):
    rows = (db.query(Game.game_date).join(GamePitch, GamePitch.game_id == Game.game_id)
            .filter(((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == pid))
                    | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == pid)))
            .filter(Game.game_date >= d0, Game.game_date <= d1).distinct().all())
    return {r[0] for r in rows}


def _entries(db, pid):
    try:
        return db.query(PitcherAvailability).filter(PitcherAvailability.player_id == pid,
                                                    PitcherAvailability.cleared.is_(False)).all()
    except Exception:
        db.rollback()   # table not migrated yet -- board still works without overrides
        return []


def _active_status(entries, on):
    act = [e for e in entries if e.kind == "status" and (e.start_date is None or e.start_date <= on)
           and (e.end_date is None or e.end_date >= on)]
    return max(act, key=lambda e: e.created_at) if act else None


def pitcher_row(db, player, as_of):
    pid = player.player_id
    start = as_of - timedelta(days=60)
    counts, tracking_start = get_daily_pitch_counts(db, pid, start, as_of)
    days = sorted(d for d, n in counts.items() if n > 0 and d <= as_of)
    last = days[-1] if days else None
    last_n = counts.get(last, 0) if last else 0
    req = required_rest(last_n)
    days_rest = (as_of - last).days - 1 if last else None     # full days off since the outing
    ready_on = last + timedelta(days=req + 1) if last else None
    seven = sum(n for d, n in counts.items() if as_of - timedelta(days=6) <= d <= as_of)
    acwr_rows = compute_daily_acwr(counts, tracking_start, as_of, as_of) if counts else []
    acwr = acwr_rows[-1] if acwr_rows else None
    ratio = acwr["acwr"] if acwr and acwr["has_full_history"] else None
    building = bool(acwr) and not acwr["has_full_history"]

    if last is not None and (last == as_of or as_of < ready_on):
        auto, reason = "Down", ("Threw today" if last == as_of else f"Rest until {ready_on.strftime('%a %b %d')}")
    elif ratio is not None and ratio > ZONE_ELEVATED_MAX:
        auto, reason = "Limited", f"Workload spike (ratio {ratio:.2f}) -- {LIMITED_PITCHES} pitches max"
    else:
        auto, reason = "Available", ("Fully rested" if last else "No recent throwing tracked")

    entries = _entries(db, pid)
    override = _active_status(entries, as_of)
    status, source = (override.status, "coach") if override else (auto, "auto")
    if override:
        until = f" until {override.end_date.strftime('%b %d')}" if override.end_date else ""
        reason = f"Coach set {override.status}{until}" + (f" -- {override.note}" if override.note else "")
        if override.status == "Limited":
            reason += f" ({LIMITED_PITCHES} pitches max)" if "max" not in reason else ""

    plans = []
    for e in sorted((e for e in entries if e.kind == "plan" and e.planned_date and e.planned_date >= as_of),
                    key=lambda e: e.planned_date):
        warn = None
        hold = _active_status(entries, e.planned_date)
        if hold is not None and hold.status == "Hold":
            warn = "on hold that day"
        elif ready_on is not None and e.planned_date < ready_on:
            warn = f"not rested until {ready_on.strftime('%a %b %d')}"
        plans.append({"id": e.availability_id, "date": e.planned_date, "type": e.plan_type, "note": e.note, "warn": warn})

    if ratio is None:
        ratio_label = "Building history" if building else "—"
    elif ratio < ZONE_UNDER_TRAINING_MAX:
        ratio_label = "Under-thrown"
    elif ratio <= ZONE_SWEET_SPOT_MAX:
        ratio_label = "Normal"
    elif ratio <= ZONE_ELEVATED_MAX:
        ratio_label = "Caution"
    else:
        ratio_label = "Spike"
    return {
        "player": player, "last": last, "last_pitches": last_n, "last_was_game": bool(last and last in _game_days(db, pid, last, last)),
        "required_rest": req if last else None, "days_rest": days_rest, "ready_on": ready_on,
        "seven_day": seven, "ratio": ratio, "ratio_label": ratio_label,
        "status": status, "auto_status": auto, "source": source, "reason": reason,
        "override": override, "plans": plans,
    }


def board(db, as_of=None):
    as_of = as_of or date.today()
    pitchers = (db.query(Player).filter(Player.is_pitcher.is_(True), Player.active.is_(True))
                .order_by(Player.last_name, Player.first_name).all())
    rows = [pitcher_row(db, p, as_of) for p in pitchers]
    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 9), r["player"].last_name))
    return rows
