import datetime as dt

from analytics import today
import today_box

DAY = dt.date(2026, 9, 27)


def test_coach_today(db):
    d = today.coach_today(db, today=DAY)
    assert d["arm"]["total"] == 3
    assert d["last_game"]["date"] == dt.date(2026, 9, 26) and d["last_game"]["result"]
    assert d["health"]["games"] >= 1
    allowed = today_box.allowed_titles("Head Coach", None, False)
    html = str(today_box.coach_box(d, allowed))
    assert "Who can throw today" in html and "Team Game Report" in html and "sidebar_go" in html


def test_coach_today_hitting_coach_has_no_arm_tile(db):
    allowed = today_box.allowed_titles("Coach", "Hitting", False)
    d = today.coach_today(db, today=DAY, pitching="Arm Care & Availability" in allowed)
    assert d["arm"] is None
    assert "Who can throw" not in str(today_box.coach_box(d, allowed))


def test_player_today_pitcher_and_hitter(db):
    p = today.player_today(db, 1, today=DAY)
    assert p["arm"]["status"] in ("Available", "Limited", "Down", "Hold")
    assert p["last_game"]["stats"][0][0] == "IP"
    html = str(today_box.player_box(p, today_box.allowed_titles("Player", None, True)))
    assert "My arm today" in html and "Pitcher Report" in html
    h = today.player_today(db, 11, today=DAY)
    assert h["arm"] is None and h["last_game"]["stats"][0][0] == "H-AB"
    assert "My arm" not in str(today_box.player_box(h, today_box.allowed_titles("Player", None, False)))
