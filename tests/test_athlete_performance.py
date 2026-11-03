"""Athlete vs Performance math (analytics/athlete_performance.py)."""
from datetime import date

from analytics import athlete_performance as ap


def _fb(d, velo, stype="Live", pitch="4-Seam Fastball"):
    return dict(date=d, pitch=pitch, velo=velo, spin=2200.0, spin_ok=True, ivb=15.0, extension=6.5, session_type=stype)


def test_direction():
    assert ap.direction("Countermovement Jump Height") == 1
    assert ap.direction("Acceleration: 10-Yard Sprint Time") == -1
    assert ap.direction("Countermovement Jump Concentric Duration") == -1
    assert ap.direction("Percent Body Fat") == -1
    assert ap.direction("Body Weight") == 0
    assert ap.direction("Shoulder: Right External Rotation", "Mobility & ROM") == 0


def test_derived():
    t = {"CMJ Peak Power": 4856.0, "CMJ Bodyweight": 89.69, "Isometric Mid-Thigh Pull Peak Vertical Force": 2813.0,
         "Body Weight": 181.5, "Shoulder Strength: Throwing Arm ER Peak Force": 40.0,
         "Shoulder Strength: Throwing Arm IR Peak Force": 35.0}
    ap._derive(t)
    assert round(t[ap.CMJ_PP_KG], 1) == 54.1
    assert round(t[ap.IMTP_KG], 1) == round(2813 / (181.5 / ap.LB_PER_KG), 1)
    assert round(t[ap.ERIR], 3) == round(40 / 35, 3)


def test_perf_window_excludes_far_and_rehab():
    rows = [_fb(date(2026, 8, 20), 84.0), _fb(date(2026, 9, 15), 86.0), _fb(date(2026, 10, 30), 90.0),
            _fb(date(2026, 8, 21), 70.0, stype="Rehab"), _fb(date(2026, 8, 21), 75.0, pitch="Slider")]
    w = ap.perf_window(rows, date(2026, 8, 25))
    assert w["n"] == 2 and w["velo"] == 85.0 and w["velo_max"] == 86.0


def test_quadrants_and_watch():
    assert ap.quadrant(5, 1.0, 1) == "Both up"
    assert ap.quadrant(-6, -2.0, 1) == "Both down"
    assert ap.quadrant(4, -1.0, 1) == "Stronger, velo down"
    assert ap.quadrant(-4, 1.0, 1) == "Test down, velo up"
    base = {"perf": {"velo": {"abs": -2.0}}, "tests": {ap.CMJ_PP_KG: {"improve_pct": -8.0}}, "name": "A", "last": "A"}
    only_velo = {"perf": {"velo": {"abs": -1.6}}, "tests": {}, "name": "B", "last": "B"}
    fine = {"perf": {"velo": {"abs": -0.5}}, "tests": {ap.CMJ_PP_KG: {"improve_pct": -2.0}}, "name": "C", "last": "C"}
    w = ap.decline_watch([only_velo, fine, base])
    assert [r["name"] for r in w] == ["A", "B"]
    assert w[0]["level"] == "Both down" and w[1]["level"] == "Velo down"


def test_fit():
    pts = [{"x": x, "y": 0.1 * x + 0.2} for x in (-10, -2, 3, 8, 12)]
    f = ap.fit(pts)
    assert abs(f["slope"] - 0.1) < 1e-9 and abs(f["r"] - 1) < 1e-9 and f["n"] == 5
