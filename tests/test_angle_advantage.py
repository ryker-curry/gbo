"""Oct 2026 (Paradigm, "The Angle Advantage"): staff angle standouts, rubber moves, card angle nudge."""

import datetime as dt
from types import SimpleNamespace as NS

from analytics import approach_angles as aa
from analytics import pitch_card as pc


def test_staff_extremes_flags_top_and_bottom():
    profiles = {pid: {"4-Seam Fastball": {"vaaa": 0.1 * (pid - 5), "haaaa": 0.0, "n_v": 20, "n_h": 20}}
                for pid in range(10)}
    profiles[0]["4-Seam Fastball"]["vaaa"] = -1.2      # steepest
    profiles[9]["4-Seam Fastball"]["vaaa"] = 1.4       # flattest
    out = aa.staff_extremes({"profiles": profiles, "throws": {pid: "R" for pid in range(10)}})
    assert out[9][0]["kind"] == "flat" and "top of the zone" in out[9][0]["text"]
    assert out[0][0]["kind"] == "steep" and 5 not in out


def test_digit_angles_weights_and_arm_side():
    prof = {"4-Seam Fastball": {"vaaa": 1.0, "haaaa": 0.5, "n_v": 30, "n_h": 30},
            "2-Seam Fastball": {"vaaa": -1.0, "haaaa": 0.5, "n_v": 10, "n_h": 10}}
    d = aa.digit_angles(prof, pc.PITCH_DIGIT)
    assert abs(d[1][0] - 0.5) < 1e-9 and abs(d[1][1] - 0.5) < 1e-9


def test_angle_bonus_lanes():
    assert pc.angle_bonus(1, 4, 3, 1.0, None) > 0 > pc.angle_bonus(1, 2, 3, 1.0, None)
    assert pc.angle_bonus(3, 1, 3, -1.0, None) > 0
    assert pc.angle_bonus(1, 3, 1, None, 0.8) > 0 and pc.angle_bonus(1, 3, 5, None, 0.8) == 0
    assert pc.angle_bonus(1, 3, 5, None, -0.8) > 0


def test_rubber_moves_detects_shift():
    raps = []
    for k in range(6):
        side = 1.8 if k < 3 else 1.4          # ft; release moves ~4.8 in
        for i in range(12):
            raps.append(NS(release_side=side, pitch_date=dt.datetime(2026, 9, 1 + 3 * k, 15), bullpen_id=k,
                           import_id=None, player_id=1, plate_x_ft=None, plate_z_ft=None,
                           pitch_type=NS(type_name="Slider")))
    moves = aa.rubber_moves(raps, "R", {"vaa": {}, "haa": {}})
    assert len(moves) == 1 and moves[0]["date"] == dt.date(2026, 9, 10) and moves[0]["toward"] == "1B side"
