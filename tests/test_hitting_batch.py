"""Oct 2026 hitting article batch: decision runs, Decision Score, count by
count, PA length / early win, run leverage, in-zone whiff flag, results by
pitch shape, advance-scouting approach panel."""

from types import SimpleNamespace as NS

from analytics import (decision_value, decision_score, hitter_counts, leverage, zone_whiff, shape_results,
                       advance_scouting)


def _gp(seq=1, x=0.0, z=2.5, out="Called Strike", b=0, s=0, rv=0.0, pa_no=1, ends=False, ab=None, gid=1,
        label="4-Seam Fastball", cq=None, outs=0, bases="000", inning=1, batting=True, runs=0, pid=5):
    return NS(game_pitch_id=seq + 1000 * gid, game_id=gid, pitch_sequence=seq, actual_plate_x=x, actual_plate_z=z,
              pitch_outcome=out, balls_before=b, strikes_before=s, run_value=rv, pa_pitch_number=pa_no,
              ends_plate_appearance=ends, ab_outcome=ab, pitch_type=NS(type_name=label), contact_quality=cq,
              outs_before=outs, bases_before=bases, inning=inning, is_our_team_batting=batting,
              our_player_id=pid, opponent_our_player_id=None, runs_scored_on_play=runs)


def test_decision_value_counts_context():
    # Heart takes cost runs, Heart swings gain -- table learns it
    train = ([_gp(seq=i, out="Called Strike", rv=-0.10, b=3, s=1) for i in range(30)]
             + [_gp(seq=100 + i, out="In Play", rv=0.15, b=3, s=1) for i in range(30)])
    t = decision_value.build_table(train)
    take = _gp(out="Called Strike", b=3, s=1)
    swing = _gp(out="In Play", b=3, s=1)
    assert decision_value.credit(t, take)[0] < 0 < decision_value.credit(t, swing)[0]
    sc = decision_value.score(t, [take] * 5)
    assert sc["runs"] < 0 and sc["n"] == 5 and sc["notes"] and "taking Heart" in sc["notes"][0]


def test_decision_score_scale():
    base = {"Swing Decision %": 60, "Decision RV/100": 0.0, "Chase %": 30, "Zone Swing %": 65,
            "Zone contact %": 80, "Whiff %": 25, "BB%": 9, "K%": 22}
    m = {i: {k: v + (i - 2) * (1 if k not in ("Chase %", "Whiff %", "K%") else -1) for k, v in base.items()}
         for i in range(5)}
    sc = decision_score.scores(m)
    assert sc[4] > 100 > sc[0] and abs(sc[2] - 100) < 1


def test_count_table_and_pa_length():
    ps = [_gp(seq=1, out="Ball", rv=0.05, pa_no=1), _gp(seq=2, b=1, out="Ball", rv=0.06, pa_no=2),
          _gp(seq=3, b=2, out="In Play", rv=0.4, pa_no=3, ends=True, ab="1B", cq="Solid")]
    rows = {r["count"]: r for r in hitter_counts.count_table(ps)}
    assert rows["2-0"]["key"] and rows["2-0"]["n"] == 1 and rows["2-0"]["rv"] == 40.0
    pl = hitter_counts.pa_length(ps)
    assert pl["rows"][1]["pas"] == 1 and pl["early"] == 100.0
    k = [_gp(seq=1, out="Swing and Miss", s=0), _gp(seq=2, s=1, out="Swing and Miss", pa_no=2),
         _gp(seq=3, s=2, out="Swing and Miss", pa_no=3, ends=True, ab="K")]
    assert hitter_counts.pa_length(k)["early"] == 0.0


def test_leverage():
    pas = []
    seq = 0
    for i in range(30):      # bases-loaded 2-out PAs swing runs a lot, empty 0-out barely
        seq += 1
        pas.append(_gp(seq=seq, outs=2, bases="111", out="In Play", ends=True, ab="2B", rv=1.5 if i % 2 else -0.8))
        seq += 1
        pas.append(_gp(seq=seq, outs=0, bases="000", out="In Play", ends=True, ab="Groundout", rv=-0.2, pid=6))
    t = leverage.build_table(pas)
    assert t[(2, "111")] > leverage.HIGH and t[(0, "000")] < 1
    late = [_gp(seq=1, inning=8, outs=0, bases="000")]
    ctx = leverage.pa_context(late, t, {late[0].game_pitch_id: (3, 2)})
    assert ctx["late_close"] and ctx["high"]


def test_zone_whiff_flag():
    ps = [_gp(seq=i, out="Foul") for i in range(40)] + [_gp(seq=100 + i, out="Swing and Miss") for i in range(20)]
    r = zone_whiff.rolling(ps)
    assert r["flag"] and r["last"] > r["base"]


def test_shape_results_groups():
    gp = _gp(label="4-Seam Fastball")
    rap = NS(vb_spin=18.0, hb_trajectory=8.0, velocity=89.0, release_height=6.0, release_side=1.8, player_id=1)
    g = shape_results.groups_of(gp, rap, NS(throws="R", height_in=74))
    assert g["Fastball shape"] == "Riding" and g["Fastball velo"] == "88+" and "Arm slot" in g
    sl = shape_results.groups_of(_gp(label="Slider"), NS(vb_spin=0.0, hb_trajectory=-14.0, velocity=78.0,
                                                          release_height=5.0, release_side=2.5, player_id=1),
                                 NS(throws="R", height_in=74))
    assert sl["Breaking ball"] == "Sweeper"


def test_approach_point_pairs_whiffs_with_damage():
    cells = [[[0, 0] for _ in range(3)] for _ in range(3)]
    cells[2][2] = [5, 8]                                     # low-away breaking ball whiffs
    prof = {"whiff_grids": {"Breaking": {"cells": cells, "chase": 40.0, "n": 30}}, "hand": "R"}
    dmg = {"R": [[[0, 0] for _ in range(3)] for _ in range(3)]}
    dmg["R"][2][2] = [1, 5]                                  # we slug .200 there
    pts = advance_scouting.approach_points(prof, dmg, "R")
    assert pts and "down and away" in pts[0][1] and "lay off" in pts[0][1]


def test_decision_floor():
    from analytics import decision_floor
    train = ([_gp(seq=i, out="Called Strike", rv=-0.10, b=1, s=1) for i in range(30)]
             + [_gp(seq=100 + i, out="In Play", rv=0.15, b=1, s=1) for i in range(30)])
    t = decision_value.build_table(train)
    pas = []
    for k in range(20):          # 20 one-pitch PAs on Heart pitches: swing = right, take = wrong
        good = k % 4 != 0
        pas.append(_gp(seq=1000 + k, pa_no=1, ends=True, b=1, s=1, out="In Play" if good else "Called Strike",
                       ab="1B" if good else None))
    fl = decision_floor.floor(t, pas)
    assert fl["n_pa"] == 20 and abs(fl["quality"] - 75.0) < 1e-9 and len(fl["windows"]) == 11
    assert fl["floor"] <= fl["quality"] and fl["read"]
    assert decision_floor.floor(t, pas[:5])["floor"] is None
