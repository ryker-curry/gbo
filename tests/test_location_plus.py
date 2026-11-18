"""Location+ (Oct 2026 rebuild): grades the spot, not the pitch's own result;
pitchers spread out on a pitcher-level scale; old math kept as result_value."""

import random
from types import SimpleNamespace as NS

from analytics import pitch_grading as pg


def _gp(x, z, rv, pid=1, t="Slider"):
    return NS(actual_plate_x=x, actual_plate_z=z, run_value=rv, pitch_type=NS(type_name=t),
              is_our_team_batting=False, our_player_id=pid, opponent_our_player_id=None)


def _team(rnd):
    pitches = []
    for pid in range(1, 8):
        edge_share = pid / 8                      # pitcher 7 lives on the edges, pitcher 1 over the heart
        for _ in range(60):
            if rnd.random() < edge_share:
                pitches.append(_gp(0.8, 2.0, rnd.gauss(-0.05, 0.1), pid))   # edge: good for us
            else:
                pitches.append(_gp(0.0, 2.5, rnd.gauss(0.06, 0.1), pid))    # heart: bad for us
    return pitches


def test_spot_not_result():
    b = pg.team_location_plus_baseline(_team(random.Random(1)))
    good_result = _gp(0.0, 2.5, -0.5)
    bad_result = _gp(0.0, 2.5, +0.9)
    assert pg.location_plus(good_result, b) == pg.location_plus(bad_result, b)      # same spot, same grade
    assert pg.location_plus(_gp(0.8, 2.0, 0.9), b) > pg.location_plus(_gp(0.0, 2.5, -0.5), b)
    # the old result-based math is still available for "color by result"
    assert pg.result_value(good_result, b) > pg.result_value(bad_result, b)


def test_pitcher_scale():
    rnd = random.Random(2)
    team = _team(rnd)
    b = pg.team_location_plus_baseline(team)
    assert b["__meta__"]["pitcher_scale"] is not None
    grade = {pid: pg.location_plus_for_group([pg.location_plus(p, b) for p in team if p.our_player_id == pid], b)
             for pid in range(1, 8)}
    assert grade[7] > 110 and grade[1] < 90
    few = [pg.location_plus(p, b) for p in team if p.our_player_id == 7][:3]
    assert abs(pg.location_plus_for_group(few, b) - 100) < abs(grade[7] - 100)


def test_bundle_pitching_plus_is_blend(db):
    from analytics import profile_queries
    from models import GamePitch, RapsodoPitch
    ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == 1).all()
    raps = db.query(RapsodoPitch).filter(RapsodoPitch.player_id == 1).all()
    bundle = profile_queries.compute_grading_bundle(db, ps, raps)
    for row in bundle["arsenal_rows"]:
        if row["Stuff+"] is not None and row["Location+"] is not None:
            assert row["Pitching+"] == pg.pitching_plus(row["Stuff+"], row["Location+"])
