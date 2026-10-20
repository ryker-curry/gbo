"""Fall Exit Report (Oct 2026): Part 1 builds for pitchers and hitters,
GBO suggests 3 priorities, saving creates IDP goals once (re-save updates)."""

from datetime import date

from models import Player, IDPGoal
from analytics import exit_report as er


def _first(db, pitcher):
    return db.query(Player).filter(Player.is_pitcher.is_(pitcher)).order_by(Player.player_id).first()


def test_pitcher_report_builds(db):
    p = _first(db, True)
    rep = er.build(db, p.player_id, 1)
    assert rep is not None and rep["side"] == "pitch"
    assert rep["rows"] and all("trend" in r for r in rep["rows"])
    assert rep["mix"] and "stuff_plus" in rep["mix"][0]
    assert len(rep["priorities_suggested"]) == er.N_PRIORITIES
    assert rep["workload"]["outings"] >= 1


def test_hitter_report_builds(db):
    h = _first(db, False)
    rep = er.build(db, h.player_id, 1)
    assert rep is not None and rep["side"] == "hit"
    assert len(rep["priorities_suggested"]) == er.N_PRIORITIES


def test_trend_respects_direction():
    assert er._trend(True, 4.0, 50, 60) == "up"
    assert er._trend(False, 3.0, 12, 6) == "up"      # walk % went down = better
    assert er._trend(True, 4.0, 50, 51) == "flat"
    assert er._trend(True, 4.0, None, 51) is None


def test_save_plan_creates_goals_once(db):
    p = _first(db, True)
    pri = [{"title": "Raise Strike %", "why": "test", "measure": "g:p_strike", "target": 66, "retest": "2027-01-15",
            "drills": "pens"},
           {"title": "Hip mobility", "why": "", "measure": "", "target": None, "retest": "2027-01-15", "drills": ""},
           er.blank_priority()]
    before = db.query(IDPGoal).filter(IDPGoal.player_id == p.player_id).count()
    rep, _ = er.save_plan(db, p.player_id, 1, "Fall", pri, "notes", date(2026, 10, 21), 1)
    after = db.query(IDPGoal).filter(IDPGoal.player_id == p.player_id).count()
    assert after == before + 2 and rep.status == "saved"
    saved = rep.priorities
    assert saved[0]["goal_id"] and saved[1]["goal_id"] and not saved[2].get("goal_id")
    g = db.query(IDPGoal).filter(IDPGoal.goal_id == saved[0]["goal_id"]).one()
    assert g.game_metric == "p_strike" and float(g.target_value) == 66 and g.target_date == date(2027, 1, 15)
    # re-save with an edit: same goals, updated
    saved[0]["target"] = 68
    rep, _ = er.save_plan(db, p.player_id, 1, "Fall", saved, "notes 2", date(2026, 10, 21), 1)
    assert db.query(IDPGoal).filter(IDPGoal.player_id == p.player_id).count() == after
    assert float(db.query(IDPGoal).filter(IDPGoal.goal_id == saved[0]["goal_id"]).one().target_value) == 68
