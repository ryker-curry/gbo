"""Oct 2026 article batch: IVB over expected, slider type + fit, velo fade,
pitch-pair sequencing."""

import datetime as dt
from types import SimpleNamespace as NS

from analytics import ivb_expected, slider_fit, velo_fade, sequencing


def _rap(pid, label, ivb, rh, rs, n=1, velo=88.0, spin=2200, se=90.0, bullpen=1, run=8.0):
    return NS(player_id=pid, pitch_type=NS(type_name=label), raw_pitch_type=label, vb_spin=ivb, release_height=rh,
              release_side=rs, pitch_number=n, rapsodo_pitch_id=n, velocity=velo, total_spin=spin,
              spin_efficiency=se, bullpen_id=bullpen, import_id=1, hb_trajectory=run,
              pitch_date=dt.datetime(2026, 9, 1, 15))


def test_ivb_over_expected_follows_slot():
    players = {i: NS(player_id=i, height_in=74) for i in range(6)}
    team = []
    for i in range(6):                       # higher release -> higher slot -> more ride
        rh = 5.4 + 0.2 * i
        for k in range(10):
            team.append(_rap(i, "4-Seam Fastball", 12 + 1.5 * i + (k % 3 - 1) * 0.2, rh, 1.6))
    model = ivb_expected.fit_model(team, players)
    assert model["4-Seam Fastball"]["slope"] > 0
    # a pitcher with the lowest slot but the ride of the highest one carries well over expected
    me = NS(player_id=99, height_in=74)
    scored = ivb_expected.score_pitches([_rap(99, "4-Seam Fastball", 19.5, 5.4, 1.6)], me, model)
    row = ivb_expected.summary_by_type(scored, {"4-Seam Fastball"})[0]
    assert row["over"] > 3 and "carry" in row["read"]


def test_slider_types_and_fit():
    assert slider_fit.classify({"ivb": 1.0, "run": -2.0}) == "gyro"
    assert slider_fit.classify({"ivb": 0.0, "run": -14.0}) == "sweeper"
    assert slider_fit.classify({"ivb": 0.0, "run": -14.0}, ivb_over=4.0) == "carry_sweeper"
    assert slider_fit.classify({"ivb": -12.0, "run": -5.0}) == "curveball"
    assert slider_fit.classify({"ivb": 0.5, "run": -7.0}) == "between"
    assert slider_fit.fit_hint(96)[1] == "gyro"
    assert slider_fit.fit_hint(80)[1] == "sweeper"
    assert slider_fit.fit_hint(89)[0] == "neutral"
    notes = slider_fit.notes_for("sweeper", {"ivb": 0, "run": -17, "velo": 76}, {"velo": 88})
    assert any("past" in n for n in notes)


def test_velo_fade():
    ps = []
    for n in range(1, 41):
        label = "4-Seam Fastball" if n % 2 else "Slider"
        ps.append(_rap(1, label, 15, 6, 1.6, n=n, velo=90 - 0.06 * n))
    res = velo_fade.fade(velo_fade.points_from_rapsodo(ps, lambda p: p.pitch_type.type_name))
    assert res["ok"] and res["n"] == 20
    assert abs(res["per"] - (-1.5)) < 0.01 and res["drop"] < 0
    assert res["read"] in ("mild fade", "notable fade")
    few = velo_fade.fade(velo_fade.points_from_rapsodo(ps[:10], lambda p: p.pitch_type.type_name))
    assert not few["ok"]
    outs = velo_fade.by_outing(ps, lambda p: p.pitch_type.type_name)
    assert len(outs) == 1 and outs[0]["kind"] == "Bullpen"


def _gp(seq, pa_no, label, outcome, ends=False, b=0, s=0, x=0.0, z=2.5, gid=1, ab=None):
    return NS(game_id=gid, pitch_sequence=seq, pa_pitch_number=pa_no, pitch_type=NS(type_name=label),
              pitch_outcome=outcome, ends_plate_appearance=ends, balls_before=b, strikes_before=s,
              actual_plate_x=x, actual_plate_z=z, ab_outcome=ab, is_our_team_batting=False, our_player_id=7,
              opponent_our_player_id=None, game_pitch_id=seq)


def test_sequencing_pairs_stay_inside_plate_appearance():
    ps = [
        _gp(1, 1, "4-Seam Fastball", "Called Strike"),
        _gp(2, 2, "Slider", "Swing and Miss", s=1),
        _gp(3, 3, "Slider", "In Play", ends=True, s=2, ab="1B"),
        _gp(4, 1, "Changeup", "Ball"),                 # new PA: no SL -> CH pair
        _gp(5, 2, "4-Seam Fastball", "Swing and Miss", b=1, x=1.5),
    ]
    prs = sequencing.pairs(ps)
    assert [(a.pitch_sequence, b.pitch_sequence) for a, b in prs] == [(1, 2), (2, 3), (4, 5)]
    t = sequencing.table(ps)
    rows = {r["label"]: r for r in t["rows"]}
    assert rows["FB → SL"]["csw"] == 100 and rows["SL → SL"]["hits"] == 1
    assert rows["CH → FB"]["chase"] == 100
    assert sequencing.table(ps, count="two")["total"] == 1
