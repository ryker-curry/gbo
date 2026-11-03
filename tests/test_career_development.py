"""Career Development math (career_development.py) on synthetic pitches."""
from datetime import datetime

import career_development as cd


def _p(dt, pitch="4-Seam Fastball", velo=85.0, rh=5.9, rs=2.0, stype="Live", **kw):
    r = dict(dt=dt, date=dt.date(), season=cd.season_of(dt), term=cd.term_of(dt), pitch=pitch, velo=velo,
             spin=2200.0, spin_eff=95.0, spin_conf=0.9, gyro=10.0, ivb=15.0, hb=10.0, rel_height=rh,
             rel_side=rs, extension=6.5, zone=100.0, spin_ok=True, arm_angle=40.0,
             session_key=str(dt.date()), session_type=stype, source="test", outcome=None, run_value=None)
    r.update(kw)
    return r


def _season(year, month, velo, n=20, **kw):
    return [_p(datetime(year, month, 1 + i % 27, 15), velo=velo + (i % 3 - 1) * 0.5, **kw) for i in range(n)]


def test_season_and_term():
    assert cd.season_of(datetime(2025, 8, 1)) == "2025-26"
    assert cd.season_of(datetime(2026, 7, 31)) == "2025-26"
    assert cd.term_of(datetime(2026, 2, 3)) == "Spring 2026"


def test_velocity_gain_is_better_and_small_sample_flagged():
    rows = _season(2025, 9, 84.0) + _season(2026, 9, 86.0)
    summ = cd.season_summary(rows, "4-Seam Fastball", "standard")
    by = {r["metric"]: r for r in cd.compare(summ, "2025-26", "2026-27")}
    assert by["velo"]["verdict"] == "Better"
    assert by["ivb"]["verdict"] == "No clear change"
    few = _season(2025, 9, 84.0, n=5) + _season(2026, 9, 86.0)
    by = {r["metric"]: r for r in cd.compare(cd.season_summary(few, "4-Seam Fastball", "standard"), "2025-26", "2026-27")}
    assert by["velo"]["verdict"] == "Small sample"


def test_rehab_excluded_from_standard_and_all_fastballs_option():
    rows = _season(2024, 11, 80.0, stype="Rehab") + _season(2025, 9, 84.0, pitch="2-Seam Fastball")
    assert set(cd.season_summary(rows, "4-Seam Fastball", "standard")) == set()
    assert set(cd.season_summary(rows, cd.ALL_FB, "all")) == {"2024-25", "2025-26"}
    assert cd.pitch_options(rows)[0][0] == cd.ALL_FB


def test_default_view_skips_thin_first_season():
    rows = _season(2022, 10, 87.0, n=9) + _season(2023, 11, 83.0) + _season(2026, 9, 83.5)
    pitch, s_from, s_to = cd.default_view(rows)
    assert (pitch, s_from, s_to) == ("4-Seam Fastball", "2023-24", "2026-27")


def test_verdict_counts():
    rows = [{"verdict": v} for v in ("Better", "Worse", "Higher", "Lower", "No clear change", "Small sample")]
    assert cd.verdict_counts(rows) == {"better": 1, "worse": 1, "changed": 2, "same": 1}
