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


def _cmj(n=8):
    """n players: player i has more spring (height, mRSI, velocity) and less
    force as i goes up."""
    r = range(n)
    return {"CMJ Bodyweight": {i: 90.0 for i in r},
            "Countermovement Jump Height": {i: 12 + i for i in r},
            "CMJ Concentric Peak Velocity": {i: 2.5 + 0.05 * i for i in r},
            "Countermovement Jump RSI-Modified": {i: 0.4 + 0.03 * i for i in r},
            "CMJ Peak Power": {i: 4500 + 50 * i for i in r},
            "CMJ Concentric Impulse": {i: 260 - 3 * i for i in r},
            "CMJ Concentric Peak Force": {i: 2300 - 40 * i for i in r},
            "CMJ Eccentric Peak Force": {i: 2200 - 40 * i for i in r},
            "CMJ Eccentric Duration": {i: 560 - 10 * i for i in r},
            "Countermovement Jump Concentric Duration": {i: 300 - 8 * i for i in r}}


def test_archetype_gs_signature_and_spectrum():
    raw = _cmj()
    spring = aa.profile(7, aa.values(raw))
    force = aa.profile(0, aa.values(raw))
    assert spring["kind"] == "Elastic" and spring["index"] >= aa.ARCH_BAND
    assert force["kind"] == "Muscular" and force["index"] <= -aa.ARCH_BAND
    assert len(spring["signature"]) == 8 and sum(spring["counts"].values()) == 8
    assert [m["label"] for m in spring["metrics"]][0] == "Jump Ht" and len(spring["metrics"]) == 9
    assert spring["velocity"] > spring["force"]
    assert spring["how"].startswith("On the force plates he loads shallow")


def test_gs_index_matches_their_sample():
    # GS sample: 5 elastic, 2 muscular, 1 neutral -> +0.37 (Elastic)
    assert round((5 - 2) / 8, 2) == 0.38 and (5 - 2) / 8 >= aa.ARCH_BAND


def test_archetype_goal_spec():
    raw = _cmj()
    prof = aa.profile(7, aa.values(raw))
    sp = aa.goal_spec(7, raw, prof)
    assert prof["worst"]["side"] == "force"
    assert sp is not None and sp["target"] > sp["baseline"]
    assert sp["test"] in ("CMJ Concentric Impulse", "CMJ Concentric Peak Force", "CMJ Eccentric Peak Force",
                          "CMJ Concentric Peak Velocity")


def test_archetype_hop_and_dsi_rows():
    """Nov 2026: hop RSI / contact time and DSI join the signature; Elastic
    also reads Aerial, Muscular Terrestrial."""
    raw = _cmj()
    n = 8
    raw["Hop Test RSI (10/5)"] = {i: 0.8 + 0.1 * i for i in range(n)}
    raw["Hop Test Mean Contact Time"] = {i: 260 - 10 * i for i in range(n)}
    # CMJ concentric peak force 2300 - 40i; IMTP chosen so DSI runs ~0.50 (i=0) -> ~0.89 (i=7)
    raw["Isometric Mid-Thigh Pull Peak Vertical Force"] = {i: (2300 - 40 * i) / (0.50 + 0.056 * i) for i in range(n)}
    vals = aa.values(raw)
    spring, force = aa.profile(7, vals), aa.profile(0, vals)
    assert len(spring["signature"]) == 11
    s_dsi = next(s for s in spring["signature"] if s["key"] == "dsi")
    f_dsi = next(s for s in force["signature"] if s["key"] == "dsi")
    assert s_dsi["lean"] == "elastic" and f_dsi["lean"] == "muscular"
    assert force["dsi"]["band"] == "ballistic" and spring["dsi"]["band"] == "strength"
    assert spring["label"] == "Elastic / Aerial" and force["label"] == "Muscular / Terrestrial"
    assert "hop test" in spring["how"] and "aerial" in spring["how"]
    # DSI without a full team pool still reads (absolute cutoffs)
    only = {k: v for k, v in raw.items()}
    only["Isometric Mid-Thigh Pull Peak Vertical Force"] = {0: 4600.0}
    assert aa.profile(0, aa.values(only))["dsi"]["value"] == 0.5
    assert aa.label("Hybrid") == "Hybrid"
    only["Isometric Mid-Thigh Pull Peak Vertical Force"] = {0: 2000.0}   # DSI 1.15 -> flagged, no row
    bad = aa.profile(0, aa.values(only))
    assert bad["dsi"]["band"] == "check" and not any(s["key"] == "dsi" for s in bad["signature"])
