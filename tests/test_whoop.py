"""WHOOP pilot (Oct 2026): baselines, readiness, performance pairing,
charts, display pieces and nav. Synthetic data only."""

import math
import random
from datetime import date, datetime, timedelta

from analytics import whoop_metrics as wm


def _rows(n=80, end=date(2026, 10, 27), hrv=70.0, rhr=52.0, last_week_hrv=None, last_week_rhr=None, seed=1):
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        d = end - timedelta(days=n - 1 - i)
        recent = (end - d).days < 7
        h = (last_week_hrv if (recent and last_week_hrv) else hrv) * math.exp(rnd.gauss(0, 0.08))
        r = (last_week_rhr if (recent and last_week_rhr) else rhr) + rnd.gauss(0, 1.5)
        out.append({"day": d, "recovery": 60 + rnd.gauss(0, 15), "hrv": h, "rhr": r, "spo2": 97, "skin_temp": 33.5,
                    "calibrating": False, "strain": 10 + rnd.gauss(0, 3), "sleep_hours": 7 + rnd.gauss(0, .6),
                    "sleep_need_hours": 8.2, "sleep_performance": 85, "sleep_consistency": 70,
                    "sleep_efficiency": 90, "resp_rate": 15, "deep_hours": 1.6, "rem_hours": 1.8})
    return out


def test_normal_week_is_ready():
    rd = wm.readiness(_rows(), date(2026, 10, 27))
    assert rd["hrv"]["status"] == wm.GOOD and rd["rhr"]["status"] == wm.GOOD
    assert rd["label"] == "Ready"
    lo, hi = rd["hrv"]["band"]
    assert lo < 70 < hi


def test_hrv_drop_and_rhr_rise_flag():
    rd = wm.readiness(_rows(last_week_hrv=50.0, last_week_rhr=58.0), date(2026, 10, 27))
    assert rd["hrv"]["status"] == wm.FLAG and rd["hrv"]["z"] < -1
    assert rd["rhr"]["status"] == wm.FLAG
    assert rd["label"] == "Back off"


def test_building_baseline_with_little_data():
    rd = wm.readiness(_rows(n=10), date(2026, 10, 27))
    assert rd["status"] == wm.NEUTRAL
    assert rd["hrv"]["label"].startswith("Building baseline")


def test_no_rows():
    rd = wm.readiness([], date(2026, 10, 27))
    assert rd["status"] == wm.NEUTRAL and rd["today"] is None


def test_recovery_zones():
    assert wm.recovery_zone(67) == "green" and wm.recovery_zone(66) == "yellow"
    assert wm.recovery_zone(34) == "yellow" and wm.recovery_zone(33) == "red" and wm.recovery_zone(None) is None


def test_relationship_reads():
    games = [{"day": date(2026, 9, i + 1), "recovery": 30 + 6 * i, "fb_velo": 84 + 0.1 * i + (0.3 if i % 2 else 0)} for i in range(10)]
    rel = wm.relationship(games, "recovery", "fb_velo")
    assert rel["ok"] and rel["r"] > 0.6 and "positive" in rel["read"]
    few = wm.relationship(games[:4], "recovery", "fb_velo")
    assert not few["ok"] and "Early read" in few["read"]
    assert "needs more games" in wm.relationship(games[:2], "recovery", "fb_velo")["read"]


def test_daily_hrv_z_and_rolling():
    rows = _rows()
    assert wm.daily_hrv_z(rows, rows[-1]["day"]) is not None
    roll = wm.rolling_hrv(rows)
    assert roll[0][1] is None and roll[-1][1] is not None


def test_charts_render():
    from visualizations import whoop_charts as wc
    rows = _rows(30)
    rd = wm.readiness(_rows(), date(2026, 10, 27))
    assert wc.hrv_svg(rows, wm.rolling_hrv(rows), rd["hrv"]["band"]).startswith("<svg")
    assert wc.recovery_svg(rows).startswith("<svg")
    assert wc.sleep_svg(rows).startswith("<svg")
    assert wc.strain_svg(rows).startswith("<svg")
    games = [{"day": date(2026, 9, i + 1), "opponent": "X", "recovery": 40 + 5 * i, "fb_velo": 85 + .2 * i} for i in range(5)]
    assert wc.scatter_svg(games, "recovery", "fb_velo", "Recovery", "FB velo", wm.relationship(games, "recovery", "fb_velo")).startswith("<svg")
    assert wc.hrv_svg([], [], None) == ""


def test_display_builds():
    import whoop_display as wd

    class Conn:
        status = "connected"; last_error = None; whoop_name = "Test Player"
        last_synced_at = datetime.utcnow() - timedelta(minutes=30)

    rows = _rows()
    rd = wm.readiness(rows, date(2026, 10, 27))
    assert wd.kpi_row(rd) is not None
    assert wd.trend_cards(rows[-30:], rd) is not None
    games = [dict({"day": date(2026, 9, i + 1), "opponent": "X", "pitches": 40, "fb_velo": 85 + .2 * i, "fb_max": 87,
                   "strike_pct": 62.0, "zone_exec_pct": 40.0}, **wm._whoop_context(rows, date(2026, 10, 1 + i))) for i in range(5)]
    assert wd.performance_section(games, True) is not None
    assert wd.performance_section([], False) is not None
    assert wd.connection_card(None, ("https://x/?connect=abc", datetime(2026, 11, 3)), True, "a", "b") is not None
    assert wd.connection_card(Conn(), None, True, "a", "b") is not None
    assert wd.synced_text(Conn()).startswith("Synced")


def test_load_daily_and_board_on_sqlite(db, seeded):
    from models import Player, WhoopConnection, WhoopDaily
    p = db.query(Player).filter(Player.active.is_(True)).first()
    db.add(WhoopConnection(player_id=p.player_id, status="connected", connected_at=datetime.utcnow()))
    for i in range(40):
        d = date(2026, 10, 27) - timedelta(days=i)
        db.add(WhoopDaily(player_id=p.player_id, cycle_id=1000 + i, day_date=d, recovery_score_state="SCORED",
                          recovery_score=60, hrv_rmssd_ms=70 + (i % 5), resting_hr=52, sleep_score_state="SCORED",
                          total_sleep_min=420, sleep_need_min=480, day_strain=11))
    db.commit()
    try:
        rows = wm.load_daily(db, p.player_id)
        assert len(rows) == 40 and rows[0]["day"] < rows[-1]["day"] and rows[-1]["sleep_hours"] == 7.0
        board = wm.team_board(db, date(2026, 10, 27))
        assert any(b["player"].player_id == p.player_id for b in board)
        outs = (wm.pitcher_outings if p.is_pitcher else wm.hitter_games)(db, p.player_id, rows)
        assert isinstance(outs, list)
    finally:
        db.query(WhoopDaily).filter(WhoopDaily.player_id == p.player_id).delete()
        db.query(WhoopConnection).filter(WhoopConnection.player_id == p.player_id).delete()
        db.commit()


def test_connect_link(db, seeded):
    from models import Player, WhoopConnectLink
    from services import whoop_service
    p = db.query(Player).first()
    url = whoop_service.make_connect_link(db, p.player_id)
    try:
        assert url.startswith(whoop_service.CALLBACK_URL + "?connect=")
        open_link = whoop_service.latest_open_link(db, p.player_id)
        assert open_link and open_link[0] == url
        ok, msg = whoop_service.sync_now(db, p.player_id)   # SQLite has no Vault
        assert not ok and "isn't set up" in msg
    finally:
        db.query(WhoopConnectLink).filter(WhoopConnectLink.player_id == p.player_id).delete()
        db.commit()


def test_nav_has_recovery_board():
    import nav
    for role in ("Head Coach", "Sports Scientist", "Athletic Trainer", "Strength Coach", "Data Analyst", "Administrator"):
        keys = {pg.key for s in nav.build_nav_sections(role, None, True) for pg in s.pages}
        assert "recovery_board" in keys, role
    for pitcher in (True, False):
        keys = {pg.key for s in nav.build_nav_sections("Player", None, pitcher) for pg in s.pages}
        assert "recovery_board" in keys


def test_health_signals_flag_fever_pattern():
    rows = _rows()
    for r in rows:
        r["skin_temp"], r["resp_rate"], r["spo2"] = 33.5 + (0.1 if r["day"].day % 2 else -0.1), 15.0 + (0.2 if r["day"].day % 3 else -0.2), 97.0
    rows[-1]["skin_temp"], rows[-1]["resp_rate"] = 35.0, 17.5
    hs = {h["key"]: h for h in wm.health_signals(rows)}
    assert hs["skin_temp"]["status"] == wm.FLAG and hs["resp_rate"]["status"] == wm.FLAG
    assert hs["spo2"]["status"] == wm.GOOD
    flags = wm.day_flags(rows)
    assert flags[rows[-1]["day"]]["skin_temp"] == wm.FLAG


def test_readiness_uses_latest_scored_day_and_reports_staleness():
    rows = _rows(end=date(2026, 10, 16))
    rows.append(dict(rows[-1], day=date(2026, 10, 17), recovery=None, hrv=None, rhr=None, sleep_hours=None))
    rd = wm.readiness(rows, date(2026, 10, 27))
    assert rd["today"]["day"] == date(2026, 10, 16) and rd["stale_days"] == 10


def test_new_display_pieces_build():
    import whoop_display as wd
    from datetime import datetime as _dt
    rows = _rows()
    rows[-1].update(light_hours=3.5, awake_hours=0.3, in_bed_hours=7.9, disturbances=8,
                    bedtime=_dt(2026, 10, 26, 23, 40), wake_time=_dt(2026, 10, 27, 7, 35))
    rd = wm.readiness(rows, date(2026, 10, 27))
    assert wd.sleep_breakdown(rd["today"]) is not None
    assert wd.health_card(rd) is not None
    assert wd.daily_table(rows[-14:]) is not None
    assert wd.freshness_note(dict(rd, stale_days=5)) is not None and wd.freshness_note(rd) is None
    w = [{"day": date(2026, 10, 27), "sport": "Baseball", "start": _dt(2026, 10, 27, 15, 0), "minutes": 100.0,
          "strain": 9.7, "avg_hr": 110, "max_hr": 170, "zones": {"Z0": 31.0, "Z1": 53.4, "Z2": 12.4, "Z3": 3.0, "Z4": 0.1, "Z5": 0.0}}]
    assert wd.workouts_table(w) is not None and wd.workouts_table([]) is not None


def test_whoop_performance_pairs_and_reads(db, seeded):
    from analytics import whoop_performance as wp
    from models import Player, WhoopConnection, WhoopDaily, RapsodoPitch
    import whoop_display as wd
    raps = db.query(RapsodoPitch).filter(RapsodoPitch.velocity.isnot(None), RapsodoPitch.pitch_date.isnot(None)).all()
    assert raps
    pid = raps[0].player_id
    days = sorted({r.pitch_date.date() for r in raps if r.player_id == pid})
    db.add(WhoopConnection(player_id=pid, status="connected", connected_at=datetime.utcnow()))
    first = days[0] - timedelta(days=40)
    n = (days[-1] - first).days + 1
    for i in range(n):
        d = first + timedelta(days=i)
        db.add(WhoopDaily(player_id=pid, cycle_id=50000 + i, day_date=d, recovery_score_state="SCORED",
                          recovery_score=20 + (i * 7) % 75, hrv_rmssd_ms=60 + (i % 9), resting_hr=50,
                          sleep_score_state="SCORED", total_sleep_min=400 + (i % 5) * 20, sleep_need_min=480, day_strain=10))
    db.commit()
    try:
        choices = wp.outcome_choices(db, pid)
        assert list(choices)[:3] == ["fb_game", "fb_pen", "fb_pen_max"]
        rows = wm.load_daily(db, pid)
        tot = 0
        for key in ("fb_game", "fb_pen", "fb_pen_max"):
            paired, n_sess = wp.paired_sessions(db, pid, key, rows)
            tot += len(paired)
            if paired:
                assert abs(sum(p["diff"] for p in paired)) < 1e-6
                assert wd.player_explorer(paired, n_sess, key, choices[key], "recovery") is not None
                z = wp.zone_summary(paired)
                assert sum(n for _, n in z.values()) <= len(paired)
        assert tot > 0
        team = wp.team_read(db, "fb_pen", "sleep_hours")
        assert team["players"] and wd.team_explorer(team, "fb_pen", "FB", "sleep_hours") is not None
        for k in [k for k in choices if k.startswith("test:")][:2]:
            wp.paired_sessions(db, pid, k, rows)
    finally:
        db.query(WhoopDaily).filter(WhoopDaily.player_id == pid).delete()
        db.query(WhoopConnection).filter(WhoopConnection.player_id == pid).delete()
        db.commit()


def test_rmcorr_removes_between_player_differences():
    from analytics import whoop_performance as wp
    # two players: within each, more sleep -> slightly higher velo; between them, the
    # low-sleep guy throws much harder. Raw pooled r would be negative; rmcorr positive.
    a = [(6 + i * .2, 92 + i * .1) for i in range(10)]
    b = [(8 + i * .2, 84 + i * .1) for i in range(10)]
    raw = wp._pearson(a + b)[0]
    cen = [(x - 6.9, y - 92.45) for x, y in a] + [(x - 8.9, y - 84.45) for x, y in b]
    rm = wp._pearson(cen)[0]
    assert raw < 0 < rm
