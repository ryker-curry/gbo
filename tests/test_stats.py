"""Core math: if any of these drift, numbers on every page drift with them."""

from types import SimpleNamespace as P

import pytest

import game_stats
from analytics import arm_care, game_goals, hitter_insights, league_baselines, data_health, team_report
from analytics import stuff_breakdown as sb
from models import Game, GamePitch, Player


def _batting(db, pid):
    return (db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == pid)
            .order_by(GamePitch.game_id, GamePitch.pitch_sequence).all())


# ---- plus stats / league baselines --------------------------------------
def test_ops_plus_league_average_is_100():
    lg = league_baselines.HITTING["D2"]
    assert game_stats.ops_plus(lg["OBP"], lg["SLG"]) == 100
    assert league_baselines.hitting_plus({"OBP": lg["OBP"], "SLG": lg["SLG"]})["OPS+"] == 100


def test_era_plus_league_average_is_100_and_lower_era_is_better():
    lg = league_baselines.PITCHING["D2"]
    assert league_baselines.pitching_plus({"ERA": lg["era"], "K": 0, "BB": 0, "Batters Faced": 0})["ERA+"] == 100
    assert league_baselines.pitching_plus({"ERA": lg["era"] / 2})["ERA+"] == 200


def test_fip_constant():
    assert game_stats.FIP_CONSTANT == 4.72


# ---- QAB ------------------------------------------------------------------
@pytest.mark.parametrize("pid", [11, 12, 13, 14])
def test_qab_matches_batting_line(db, pid):
    ps = _batting(db, pid)
    line = game_stats.compute_batting_line(ps)
    core = hitter_insights.core_metrics(ps)
    assert core["QAB"] == line["QAB"]


# ---- swing decisions --------------------------------------------------------
def _p(x, z, outcome, strikes=0):
    return P(actual_plate_x=x, actual_plate_z=z, pitch_outcome=outcome, strikes_before=strikes, balls_before=0)


def test_swing_decision_rules():
    assert hitter_insights.decision_of(_p(0, 2.5, "Foul")) == "Good swing"
    assert hitter_insights.decision_of(_p(0, 2.5, "Called Strike")) == "Taken strike"
    assert hitter_insights.decision_of(_p(2.0, 0.5, "Swing and Miss")) == "Chase"
    assert hitter_insights.decision_of(_p(2.0, 0.5, "Ball")) == "Good take"
    assert hitter_insights.decision_of(_p(0, 2.5, "HBP")) is None


# ---- arm care ---------------------------------------------------------------
@pytest.mark.parametrize("n,days", [(0, 0), (30, 0), (31, 1), (45, 1), (60, 2), (75, 3), (76, 4), (120, 4)])
def test_rest_chart(n, days):
    assert arm_care.required_rest(n) == days


def test_arm_care_board_runs(db):
    import datetime as dt
    rows = arm_care.board(db, as_of=dt.date(2026, 9, 27))
    assert {r["player"].player_id for r in rows} >= {1, 2, 3}
    # every pitcher threw on 9/26, so nobody who went 31+ pitches is available the next day
    for r in rows:
        if r["last"] == dt.date(2026, 9, 26) and r["last_pitches"] > 30:
            assert r["status"] != "Available", r


# ---- game goals -------------------------------------------------------------
def test_goal_status_higher_and_lower_is_better():
    hib = next(k for k, v in game_goals.GAME_METRICS.items() if v[2])
    lib = next(k for k, v in game_goals.GAME_METRICS.items() if not v[2])
    assert game_goals.status(hib, 50, 60, 60) == "Met"
    assert game_goals.status(hib, 50, 56, 60) == "On track"
    assert game_goals.status(hib, 50, 45, 60) == "Off track"
    assert game_goals.status(lib, 10, 7, 8) == "Met"
    assert game_goals.status(hib, 50, None, 60) == "No games yet"


def test_goal_current_values(db):
    for key in game_goals.metrics_for(False):
        game_goals.current(db, 11, key)
    for key in game_goals.metrics_for(True):
        game_goals.current(db, 1, key)


# ---- Stuff+ breakdown -------------------------------------------------------
def test_stuff_breakdown_adds_up(db):
    from models import RapsodoPitch
    from analytics import profile_queries
    raps = db.query(RapsodoPitch).filter(RapsodoPitch.player_id == 1).all()
    models = profile_queries.team_stuff_plus_baselines(db)
    training = profile_queries.team_stuff_plus_training_pitches(db)
    rows = sb.stuff_breakdown(raps, models, training)
    scored = [r for r in rows if r["features"]]
    assert scored, "no pitch type got a Stuff+ model"
    for r in scored:
        assert r["base"] + sum(f["contrib"] for f in r["features"]) == pytest.approx(r["stuff_plus"], abs=0.6)


# ---- live tracking: inning ending on a caught stealing ----------------------
def test_this_at_bat_empty_after_half_inning_change():
    from modules.game_tracking import _current_pa_pitches
    prev = [P(inning=2, is_our_team_batting=True, ends_plate_appearance=False) for _ in range(3)]
    assert _current_pa_pitches(prev, {"new_pa": True}) == []
    nxt = prev + [P(inning=3, is_our_team_batting=False, ends_plate_appearance=False)]
    assert len(_current_pa_pitches(nxt)) == 1


# ---- data health / team report ---------------------------------------------
def test_data_health_scores(db):
    for g in db.query(Game).all():
        r = data_health.check_game(db, g)
        assert 0 <= r["score"] <= 100


def test_series_grouping(db):
    games = team_report.tracked_games(db)
    series = team_report.list_series(games)
    # Sept 5-6, 12-13 are series; 19 and 26 stand alone
    assert sorted(len(s["game_ids"]) for s in series if len(s["game_ids"]) > 1) == [2, 2]


def test_hands_lookup(db):
    ps = _batting(db, 14)
    hands = game_stats.get_pitcher_hands(db, ps)
    assert set(hands.values()) <= {"R", "L", None}
    assert db.query(Player).get(14).bats == "S"


def test_stuff_breakdown_for_pitcher_with_outcomes(db):
    from models import RapsodoPitch
    raps = db.query(RapsodoPitch).filter(RapsodoPitch.player_id == 1).all()
    gps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == 1).all()
    for _ in range(2):                   # second pass runs off the cache
        breakdown, outcomes = sb.get_for_pitcher(db, raps, gps)
        assert breakdown
        for e in breakdown:
            sb.why_line(e, outcomes)
