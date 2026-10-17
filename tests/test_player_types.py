"""Oct 2026: pitcher type + attack plan, athlete archetype goals."""
from types import SimpleNamespace as NS

from analytics import pitcher_type as pt, athlete_archetype as aa


def test_classify_order():
    assert pt.classify({"kind": "ride"}, {"A": 30, "B": 25, "C": 25, "D": 20}, 60, 88, [85, 86, 87, 88])[0] == "Kitchen Sink"
    assert pt.classify({"kind": "ride"}, {"A": 46, "B": 20, "C": 20, "D": 14}, 60, 88, [85, 86, 87, 88])[0] == "Ride & Spin"
    assert pt.classify({"kind": "ride"}, {"FB": 60, "CB": 40}, 60, 88, [85, 86, 87, 88])[0] == "Ride & Spin"
    assert pt.classify({"kind": "run"}, {"FB": 60, "SL": 40}, 60, 88, [])[0] == "Sink & Sweep"
    assert pt.classify({"kind": "mid"}, {"FB": 60, "SL": 40}, 70, 84, [84, 86, 88, 90])[0] == "Strike Thrower"
    t, power, _ = pt.classify({"kind": "mid"}, {"FB": 60, "SL": 40}, 60, 91, [84, 86, 88, 91])
    assert t == "Power Mix" and power


def _gp(i, t, b, s, bat, out="Called Strike"):
    return NS(game_pitch_id=i, pitch_type=NS(type_name=t), balls_before=b, strikes_before=s, pitch_outcome=out,
              is_pitch=True, _bat=bat)


def test_build_rows_and_gaps():
    ps = []
    i = 0
    for k in range(20):   # early vs RHH: all sliders -> gap vs a Ride & Spin "FB up" plan
        i += 1
        ps.append(_gp(i, "Slider", 0, 0, "R", "Swing and Miss" if k % 2 else "Ball"))
        i += 1
        ps.append(_gp(i, "4-Seam Fastball", 1, 2, "R"))
    hands = {p.game_pitch_id: p._bat for p in ps}
    plan = {"kind": "ride", "fb": {"velo": 90}}
    import analytics.pitcher_type as mod
    orig = mod.arsenal_plan.build_plan
    mod.arsenal_plan.build_plan = lambda *a, **k: plan
    try:
        r = pt.build(ps, [object()], "R", None, None, hands, {}, [85, 88, 90, 92])
    finally:
        mod.arsenal_plan.build_plan = orig
    assert r["type"] == "Ride & Spin"
    early_same = next(x for x in r["rows"] if x["stage"] == "early" and x["side"] == "same")
    assert early_same["status"] == "gap"
    assert r["whiff"] == "Slider"


def test_archetype_goal_spec():
    raw = {"Body Weight": {i: 200 for i in range(8)},
           "Countermovement Jump Height": {i: 20 + i for i in range(8)},
           "Countermovement Jump Concentric Mean Force": {i: 2000 - 50 * i for i in range(8)}}
    prof = aa.profile(7, aa.values(raw))
    sp = aa.goal_spec(7, raw, prof)
    assert prof["kind"] == "Elastic" and sp["test"] == "Countermovement Jump Concentric Mean Force"
    assert sp["target"] > sp["baseline"]
