import game_stats
from analytics import box_score, data_health
from models import Game, GamePitch


def test_charted_line_matches_batting_line(db):
    line = box_score.charted_line(db, 1)
    ours = db.query(GamePitch).filter(GamePitch.game_id == 1, GamePitch.is_our_team_batting.is_(True)).all()
    bl = game_stats.compute_batting_line(ours)
    assert line["our"]["h"] == bl["H"]
    assert line["our"]["bb"] == bl["BB"]
    assert line["our"]["k"] == bl["K"]


def test_box_score_round_trip_and_health_check(db):
    charted = box_score.charted_line(db, 2)
    vals = {f"{s}_{k}": charted[s][k] for s in box_score.SIDES for k in box_score.STATS}
    vals["opp_h"] += 1            # official has one more opponent hit than we charted
    vals["our_e"] = None          # left blank -> not compared
    box_score.save(db, 2, vals)
    rows = box_score.compare(box_score.official_line(box_score.get_official(db, 2)), charted)
    assert len(rows) == 9
    assert [(r["side"], r["stat"], r["diff"]) for r in rows if not r["ok"]] == [("opp", "h", -1)]
    res = data_health.check_game(db, db.query(Game).get(2))
    box = next(c for c in res["checks"] if c["key"] == "box")
    assert (box["missing"], box["total"]) == (1, 9)
    # games with no box score: check doesn't apply
    res1 = data_health.check_game(db, db.query(Game).get(3))
    assert next(c for c in res1["checks"] if c["key"] == "box")["total"] == 0
