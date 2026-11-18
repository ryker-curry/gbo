"""Oct 2026 reading-list features: seam shift, plane, get ahead, usage split,
outs/XBH, damage by count, athlete archetype, training ladder, stress load."""

import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS

from analytics import pitch_insights as pi, athlete_archetype as aa, stress_load as sl, hitter_insights as hi


def _rap(t, ht, vt, hs, vs, velo=90, rh=6.0, rs=1.5, gid=None, d=None):
    return NS(pitch_type=NS(type_name=t), hb_trajectory=ht, vb_trajectory=vt, hb_spin=hs, vb_spin=vs, velocity=velo,
              release_height=rh, release_side=rs, game_pitch_id=gid, pitch_date=d or datetime(2026, 9, 1))


def test_ssw_gap_and_flag():
    # Spin says 12 in run / 8 in ride; ball actually ran 12 / sank to 0 -> extra sink.
    r = _rap("Sinker", 12, 0, 12, 8)
    s = pi.ssw_of(r, "R")
    assert s["gap"] > 0 and s["v"] == -8
    by = pi.seam_shift_by_type([r] * 12, "R")
    assert by["Sinker"]["ssw"] and "sink" in by["Sinker"]["words"]
    # Lefty mirrored -> same answer.
    assert abs(pi.ssw_of(_rap("Sinker", -12, 0, -12, 8), "L")["gap"] - s["gap"]) < 1e-9
    # Plain 4-seam: no gap.
    assert not pi.seam_shift_by_type([_rap("4-Seam Fastball", 8, 16, 8, 16)] * 12, "R")["4-Seam Fastball"]["ssw"]


def test_plane_vertical_and_off_plane():
    raps = ([_rap("4-Seam Fastball", 6, 18, 6, 18)] * 12 + [_rap("Curveball", 2, -12, 2, -12)] * 12
            + [_rap("Sweeper", -16, 0, -16, 0, rs=1.9)] * 12)
    pl = pi.plane(raps, "R")
    assert pl["kind"] == "vertical"
    off = {o["type"]: o["off"] for o in pl["off"]}
    assert off["Sweeper"]
    assert any(r["type"] == "Sweeper" and r["tell"] for r in pl["release"])


def _gp(seq, gid, b, s, outcome, pa_n, ends=False, ab=None, ob=0, oa=0, t="4-Seam Fastball", rv=None, bbt=None):
    return NS(game_pitch_id=seq + 1000 * gid, game_id=gid, pitch_sequence=seq, balls_before=b, strikes_before=s,
              pitch_outcome=outcome, pa_pitch_number=pa_n, ends_plate_appearance=ends, ab_outcome=ab, outs_before=ob,
              outs_after=oa, pitch_type=NS(type_name=t), is_pitch=True, run_value=rv, batted_ball_type=bbt,
              game=NS(game_date=date(2026, 9, 1 + gid)), actual_plate_x=None, actual_plate_z=None, contact_quality=None)


def test_get_ahead_and_outs_xbh():
    ps = []
    seq = 0
    for i in range(6):   # strike one, then K
        ps += [_gp(seq, 1, 0, 0, "Called Strike", 1), _gp(seq + 1, 1, 0, 1, "Swing and Miss", 2),
               _gp(seq + 2, 1, 0, 2, "Swing and Miss", 3, True, "K", 0, 1)]
        seq += 3
    for i in range(4):   # ball one, then double
        ps += [_gp(seq, 1, 0, 0, "Ball", 1), _gp(seq + 1, 1, 1, 0, "In Play", 2, True, "2B", t="Slider")]
        seq += 2
    g = pi.get_ahead(ps)
    assert g["first"]["n"] == 10 and g["ahead"]["k"] == 100.0 and g["behind"]["k"] == 0.0 and g["gap"] == 100.0
    rows = {r["type"]: r for r in pi.outs_per_xbh(ps)}
    assert rows["4-Seam Fastball"]["outs"] == 6 and rows["4-Seam Fastball"]["ratio"] is None
    assert rows["Slider"]["xbh"] == 4 and rows["Slider"]["ratio"] == 0


def test_usage_split_flags_mix_not_stuff():
    a = [_gp(i, 1, 0, 0, "Ball", 1, t="Sinker" if i % 2 else "4-Seam Fastball") for i in range(20)]
    b = [_gp(i, 2, 0, 0, "Ball", 1, t="Sinker" if i % 5 == 0 else "4-Seam Fastball") for i in range(20)]
    raps = [_rap("4-Seam Fastball", 6, 16, 6, 16)] * 6 + [_rap("Sinker", 15, 8, 15, 8)] * 6
    sp = pi.usage_split(a, b, raps, raps, "R")
    assert any(r["type"] == "Sinker" and r["shift"] for r in sp["rows"])
    assert any("Shapes and velo held" in x for x in sp["lines"])


def test_shadow_take_before_two_strikes_is_good():
    # x=0.80 ft is just outside the plate edge -> shadow
    p = NS(actual_plate_x=0.80, actual_plate_z=2.5, pitch_outcome="Ball", strikes_before=0, balls_before=2)
    from strike_zone import classify_attack_zone
    if classify_attack_zone(0.80, 2.5) == "Shadow":
        assert hi.decision_of(p) == "Good take"
        p.pitch_outcome = "Foul"
        assert hi.decision_of(p) == "Borderline"
        p.strikes_before = 2
        p.pitch_outcome = "Called Strike"
        assert hi.decision_of(p) == "Taken strike"


def test_count_damage_groups():
    ps = [NS(actual_plate_x=0.0, actual_plate_z=2.5, pitch_outcome="In Play", balls_before=2, strikes_before=0,
             ends_plate_appearance=True, ab_outcome="HR", contact_quality="Solid")] * 3
    d = hi.count_damage(ps)
    assert d[("hitter", "Heart")]["slg"] == 4.0 and d[("hitter", "Heart")]["swing"] == 100.0


def test_archetype():
    from tests.test_player_types import _cmj
    v = aa.values(_cmj())
    assert aa.profile(7, v)["kind"] == "Elastic"
    assert aa.profile(0, v)["kind"] == "Muscular"
    assert aa.profile(7, {"jump_ht": v["jump_ht"]}) is None


def test_stress_series_and_budget():
    today = date(2026, 10, 13)
    daily = {today - timedelta(days=k): 20.0 for k in range(1, 60) if k % 3 == 0}
    s = sl.series(daily, today - timedelta(days=1), today - timedelta(days=1), today - timedelta(days=60))
    assert s[-1]["full"] and 0.5 < s[-1]["ratio"] < 1.6
    b = sl.budget(daily, today, today - timedelta(days=60), per_pitch=1.0)
    assert b["units"] >= 0
    # Throwing exactly the budget lands the ratio at ~1.3.
    d2 = dict(daily)
    d2[today] = b["units"]
    r = sl.series(d2, today, today, today - timedelta(days=60))[-1]["ratio"]
    assert b["units"] == 0 or abs(r - 1.3) < 1e-6
    assert sl.pitch_units(92, 92, True) == sl.GAME_MULT
    assert sl.pitch_units(82, 92, False) < 1
    assert sl.zone(1.4) == "Caution" and sl.zone(1.6) == "Red"


def test_training_ladder():
    from analytics import training_stage as ts
    data = {"players": {1: object(), 2: object()},
            "doms": {1: {"Shoulder mobility": 0.2, "Hip mobility": 0.1, "Lower-body strength": -0.9},
                     2: {"Shoulder mobility": -0.8}},
            "derived": {1: {}, 2: {}}}
    raw = {"Single-Leg Jump Height (Plant Leg)": {1: 10.0}, "Single-Leg Jump Height (Drive Leg)": {1: 10.5}}
    stab = {1: (0.3, []), 2: (None, [])}
    lad = ts.ladder(1, data, raw, stab)
    assert lad["start"] == "Strength"
    assert ts.ladder(2, data, raw, stab)["start"] == "Mobility"
    raw2 = {"Single-Leg Jump Height (Plant Leg)": {1: 8.0}, "Single-Leg Jump Height (Drive Leg)": {1: 10.0}}
    assert ts.ladder(1, data, raw2, stab)["start"] == "Stability"
