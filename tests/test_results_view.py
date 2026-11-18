"""Pitcher Profile > Results rebuild (Oct 2026): scorecard vs staff,
contact mix, damage grid on Rapsodo location."""

from types import SimpleNamespace as NS

from analytics import results_view as rv
from models import GamePitch, Player
from strike_zone import ZONE_BOTTOM, ZONE_TOP


def test_damage_cells():
    assert rv.cell_of(0.0, (ZONE_BOTTOM + ZONE_TOP) / 2) == (2, 2)       # middle-middle
    assert rv.cell_of(-2.0, 5.0) == (0, 0)                               # way up, 3B side
    assert rv.cell_of(2.0, 0.5) == (4, 4)                                # bounced, 1B side
    ps = [NS(game_pitch_id=i, is_pitch=True, run_value=0.1 if i < 3 else -0.05, pitch_outcome="In Play",
             ends_plate_appearance=True, ab_outcome="1B" if i < 3 else "Groundout") for i in range(6)]
    loc = {i: (0.0, 2.5) for i in range(6)}
    g = rv.damage_grid(ps, loc)
    c = g["cells"][(2, 2)]
    assert g["located"] == 6 and c["n"] == 6 and c["hits"] == 3 and c["bip"] == 6 and not c["thin"]
    assert abs(c["avg_rv"] - 0.025) < 1e-9


def test_scorecard_on_seed(db):
    pid = db.query(GamePitch.our_player_id).filter(GamePitch.is_our_team_batting.is_(False)).first()[0]
    mine = db.query(GamePitch).filter(GamePitch.our_player_id == pid, GamePitch.is_our_team_batting.is_(False)).all()
    team = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False)).all()
    assert db.query(Player).get(pid) is not None
    sc = rv.scorecard(mine, team, {})
    assert sc["rows"] and sc["total"]["n"] >= sum(r["n"] for r in sc["rows"])
    for r in sc["rows"]:
        assert set(r["grade"]) == {k for k, *_ in rv.METRICS}
        assert all(g in (None, "better", "worse", "same") for g in r["grade"].values())
        if r["avg"] is not None:
            assert 0 <= r["avg"] <= r["slg"] <= 4
    for m in rv.contact_mix(mine):
        assert abs(sum(v for _l, v in m["parts"]) + m["unrated"] - 100) < 1.5
