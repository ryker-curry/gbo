"""Throwing Workload: daily parts, assumed throws, ratio, sensor CSV import."""

from datetime import date, timedelta

from analytics import throwing_workload as tw

D = date(2026, 10, 1)


def _days(n):
    return [D + timedelta(days=i) for i in range(n)]


def test_assumed_warmups_and_catch_play():
    rows = tw.daily_parts(D, D + timedelta(days=3), game={D: 60}, bullpen={D + timedelta(days=1): 30},
                          practice_days={D + timedelta(days=2)}, tracking_start=D)
    assert [r["assumed"] for r in rows] == [35, 25, 40, 0]          # game warm-up, pen warm-up, catch play, off day
    assert rows[0]["total"] == 95 and rows[1]["total"] == 55


def test_logging_replaces_assumptions_and_rest_day():
    d2 = D + timedelta(days=1)
    logs = [{"date": D, "throws": 20, "throw_type": "Warm-up", "source": "manual"},
            {"date": d2, "throws": 0, "throw_type": "No throwing", "source": "manual"}]
    rows = tw.daily_parts(D, d2, game={D: 50}, logs=logs, practice_days={D, d2}, tracking_start=D)
    assert rows[0]["assumed"] == 0 and rows[0]["total"] == 70
    assert rows[1]["assumed"] == 0 and rows[1]["total"] == 0


def test_sensor_day_uses_sensor_count_only():
    logs = [{"date": D, "throws": 140, "throw_type": "Sensor total", "source": "pulse", "high_intent": 30},
            {"date": D, "throws": 40, "throw_type": "Catch play", "source": "manual"}]
    r = tw.daily_parts(D, D, game={D: 60}, logs=logs, tracking_start=D)[0]
    assert r["total"] == 140 and r["game"] == 0 and r["assumed"] == 0 and r["high_intent"] == 30


def test_untracked_days_are_unknown_not_zero():
    rows = tw.daily_parts(D, D + timedelta(days=2), practice_days=set(_days(3)), tracking_start=D + timedelta(days=2))
    assert [r["tracked"] for r in rows] == [False, False, True]
    assert rows[0]["assumed"] == 0
    out = tw.with_ratio(rows)
    assert out[0]["ratio"] is None and out[2]["acute"] == 40.0


def test_ratio_and_zones():
    logs = [{"date": d, "throws": 70, "throw_type": "Catch play", "source": "manual"} for d in _days(28)]
    logs += [{"date": d, "throws": 140, "throw_type": "Catch play", "source": "manual"} for d in _days(37)[28:]]
    rows = tw.with_ratio(tw.daily_parts(D, D + timedelta(days=36), logs=logs, tracking_start=D))
    assert rows[27]["ratio"] == 1.0 and rows[27]["zone"] == "In range" and rows[27]["full_history"] is True
    assert rows[27]["chronic_week"] == 490
    last = rows[-1]                                  # 9 days at 140 vs 28-day avg (19*70 + 9*140)/28
    assert last["acute"] == 140.0 and last["ratio"] == round(140 / ((19 * 70 + 9 * 140) / 28), 2)
    assert last["zone"] == "Outside"
    assert [tw.zone(v) for v in (0.65, 0.75, 1.0, 1.25, 1.4)] == ["Outside", "Watch", "In range", "Watch", "Outside"]


def test_weekly_monday_start():
    rows = tw.daily_parts(date(2026, 11, 2), date(2026, 11, 10), practice_days=set(), tracking_start=date(2026, 11, 2),
                          logs=[{"date": date(2026, 11, 2) + timedelta(days=i), "throws": 10, "throw_type": "Other",
                                 "source": "manual"} for i in range(9)])
    w = tw.weekly(rows)
    assert [(x["week_start"], x["total"], x["days"]) for x in w] == [(date(2026, 11, 2), 70, 7), (date(2026, 11, 9), 20, 2)]


def test_sensor_csv_per_day_and_per_throw(db):
    from services import throw_sensor_import as tsi
    from models import ThrowLog
    assert tsi.find_columns(["Athlete Name", "Session Date", "High Intent Throws", "Total Throws"])["throws"] == "Total Throws"
    per_day = b"Athlete,Date,Throws,High Effort,Workload\nShane Holman,10/02/2026,120,25,30.5\n\"Lou, Lefty\",2026-10-02,90,,\nNobody Here,10/02/2026,50,,\n"
    plan = tsi.build_plan(db, per_day)
    assert plan["ok"] and plan["unmatched"] == ["Nobody Here"]
    got = {(d["player"], d["throws"], d["high_intent"]) for d in plan["days"]}
    assert ("Shane Holman", 120, 25) in got and ("Lefty Lou", 90, None) in got
    tsi.commit_plan(db, plan, "pulse", 1)
    tsi.commit_plan(db, plan, "pulse", 1)            # re-import replaces, no double count
    rows = db.query(ThrowLog).filter(ThrowLog.player_id == 1, ThrowLog.source == "pulse").all()
    assert len(rows) == 1 and rows[0].throws == 120
    per_throw = b"Player Name,Timestamp,Peak Torque\nShane Holman,2026-10-03T15:01:02Z,60.1\nShane Holman,2026-10-03T15:02:00Z,72.4\n"
    p2 = tsi.build_plan(db, per_throw)
    assert p2["per_throw"] and p2["days"][0]["throws"] == 2 and p2["days"][0]["peak_torque"] == 72.4
    bad = tsi.build_plan(db, b"foo,bar\n1,2\n")
    assert not bad["ok"] and "date column" in bad["error"]


def test_pitcher_rows_from_db(db):
    from analytics import throwing_workload_queries as twq
    rows = twq.pitcher_rows(db, 1, date(2026, 9, 1), date(2026, 10, 5))
    assert rows and any(r["game"] for r in rows)
    game_day = next(r for r in rows if r["game"])
    assert game_day["assumed"] == tw.DEFAULT_ASSUME["game_warmup"]
    sensor_day = next(r for r in rows if r["date"] == date(2026, 10, 2))
    assert sensor_day["total"] == 120
    t = twq.team_table(db, date(2026, 10, 5))
    assert {r["player"].player_id for r in t} == {1, 2, 3}
