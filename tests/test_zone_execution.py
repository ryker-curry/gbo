from types import SimpleNamespace as NS

import strike_zone as sz
from analytics import zone_execution as ze


def test_hit_spot_cell_plus_cushion():
    # called low-away box (level 2, zone 4) for a RHH -- aim at its middle
    lo, hi = sz._LEVEL_Z_BOUNDS[2]
    xl, xh = sz._ZONE_X_BOUNDS[4]
    ix, iz = (xl + xh) / 2, (lo + hi) / 2
    assert sz.hit_spot(ix, iz, ix, iz) is True                       # bullseye
    assert sz.hit_spot(ix, iz, xh + 5 / 12, iz) is True               # 5 in outside the box (half-foot cushion)
    assert sz.hit_spot(ix, iz, xh + 8 / 12, iz) is False              # 8 in outside
    assert sz.hit_spot(ix, iz, 1.6, iz) is False                      # way off the plate: no longer a "hit"
    assert sz.hit_spot(None, iz, ix, iz) is None


def test_off_plate_call_counts_anywhere_off_plate():
    xl, _xh = sz._ZONE_X_BOUNDS[5]
    assert sz.hit_spot(xl + 0.3, 2.5, 2.0, 2.5) is True               # called off the plate, went way off: did its job
    assert sz.hit_spot(xl + 0.3, 2.5, 0.0, 2.5) is False              # came back over the middle


def _p(ix, iz, ax, az, b=0, s=0, t="4-Seam Fastball"):
    return NS(intended_plate_x=ix, intended_plate_z=iz, actual_plate_x=ax, actual_plate_z=az, balls_before=b,
              strikes_before=s, pitch_type=NS(type_name=t))


def test_breakdown():
    lo, hi = sz._LEVEL_Z_BOUNDS[2]
    xl, xh = sz._ZONE_X_BOUNDS[4]
    ix, iz = (xl + xh) / 2, (lo + hi) / 2
    ps = [_p(ix, iz, ix, iz), _p(ix, iz, 0.0, 2.7, b=2, s=0), _p(ix, iz, ix, iz + 1.0, b=0, s=2, t="Slider")]
    r = ze.breakdown(ps, "R")
    assert r["overall"]["hits"] == 1 and r["overall"]["n"] == 3
    assert {x["label"] for x in r["by_count"]} == {"First pitch", "Behind", "Two strikes"}
    assert r["miss"]["n"] == 2 and r["miss"]["up"] == 100.0       # both misses came up
    assert r["miss"]["over_middle"] == 50.0                        # one of them over the heart
