"""Command by target lane (Oct 2026)."""

from types import SimpleNamespace as NS

from analytics import command_lanes as cl


def test_lane_of_from_hitter_side():
    assert cl.lane_of(0.0, 2.5, "R") == ("Middle", "Middle")
    assert cl.lane_of(-0.6, 3.3, "R") == ("Up", "In")      # RHH on the 3B (negative) side
    assert cl.lane_of(-0.6, 3.3, "L") == ("Up", "Away")
    assert cl.lane_of(0.9, 1.2, "R") == ("Down", "Away")    # off-plate target counts as the edge
    assert cl.lane_of(0.0, 2.5, None) is None


def _p(i, ix, iz, ax, az):
    return NS(game_pitch_id=i, intended_plate_x=ix, intended_plate_z=iz, actual_plate_x=ax, actual_plate_z=az)


def test_corners_miss_more_takeaway():
    ps = [_p(i, 0.0, 2.5, 0.0, 2.6) for i in range(6)]                    # middle: on target
    ps += [_p(10 + i, 0.6, 2.5, -0.4, 2.5) for i in range(6)]             # away (for RHH): ~1 ft miss
    hands = {p.game_pitch_id: "R" for p in ps}
    res = cl.compute_lanes(ps, hands, "R")
    rows = res["h"]
    assert rows["Middle"]["n"] == 6 and rows["Away"]["n"] == 6
    assert rows["Away"]["avg_miss"] > rows["Middle"]["avg_miss"] + 3
    assert "corners" in cl.takeaway(res)
