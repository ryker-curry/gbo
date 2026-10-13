"""Advance Scouting upgrades (Oct 2026): count x hand, one-line plans, their
hitters, self-scout, dugout card and the post-series check."""

import datetime as dt
from types import SimpleNamespace as NS

from analytics import advance_scouting as adv
from models import Game, GamePitch, Player
from visualizations import advance_report_sheet as sheet


def test_count_hand_and_predictable_spots():
    pt = lambda n: NS(type_name=n)
    ps = [NS(game_pitch_id=i, balls_before=0, strikes_before=0, pitch_type=pt("4-Seam Fastball"), is_pitch=True)
          for i in range(9)]
    ps.append(NS(game_pitch_id=9, balls_before=0, strikes_before=0, pitch_type=pt("Slider"), is_pitch=True))
    hands = {i: "R" for i in range(10)}
    ch = adv.count_hand_table(ps, hands)
    c = ch["0-0"]["R"]
    assert c["top"] == "4-Seam Fastball" and c["top_pct"] == 90 and c["n"] == 10 and not c["thin"]
    assert ch["0-0"]["L"] is None and ch["even"]["R"]["n"] == 10
    spots = adv.predictable_spots({"count_hand": ch})
    assert spots[0]["count"] == "First pitch" and spots[0]["pct"] == 90


def test_report_with_hitters_on_seed(db):
    rep = adv.build(db, 1, {}, {"p:200": "Coach's own line"})
    for p in rep["pitchers"]:
        if p["id"] == 200:
            assert p["line"] == "Coach's own line"
        if p["profile"]:
            assert set(p["profile"]["count_hand"]) == {k for k, _l in adv.COUNT_ROWS}
    hitters = adv.build_hitters(db, 1, {})
    assert hitters, "seed has Washburn hitters we pitched to"
    for h in hitters:
        pr = h["profile"]
        assert pr["pa"] > 0 and (h["small"] == (pr["pa"] < adv.MIN_HITTER_PAS))
        assert h["small"] or h["line"].startswith(("Get him out with", "No clear hole yet"))
    html = sheet.render_sheet(rep, None, hitters=hitters)
    assert "Their hitters" in html and "What he throws by count" in html
    card = sheet.render_card(rep, None, hitters)
    assert "Dugout card" in card and hitters[0]["name"] in card


def test_self_scout_on_seed(db):
    pid = db.query(GamePitch.our_player_id).filter(GamePitch.is_our_team_batting.is_(False)).first()[0]
    ss = adv.self_scout(db, pid)
    assert ss and ss["profile"]["n"] > 0 and isinstance(ss["spots"], list)
    assert db.query(Player).get(pid).last_name in sheet.render_self_scout(ss)


def test_series_check_on_seed(db):
    g = db.query(Game).filter(Game.opponent_team_id == 1).order_by(Game.game_date.desc()).first()
    chk = adv.series_check(db, 1, g.game_date)
    assert chk["games"] and chk["hitting"]["during"]["two_n"] >= 0
    assert "Plan vs. what happened" in sheet.render_series_check(chk)
    assert adv.series_check(db, 1, g.game_date + dt.timedelta(days=30))["games"] == []
