"""Release angle consistency + pitch mix over time (Oct 2026)."""

import datetime as dt
import random
from types import SimpleNamespace as NS

from analytics import release_consistency as rc, trends


def _r(pid, label, va, ha, bp, n=1, day=1):
    return NS(player_id=pid, pitch_type=NS(type_name=label), raw_pitch_type=label, release_angle=va,
              horizontal_angle=ha, bullpen_id=bp, import_id=bp, pitch_number=n,
              pitch_date=dt.datetime(2026, 9, day, 15))


def test_spread_is_within_outing():
    # two outings with different average angles but tight inside each -> small spread
    raps = [_r(1, "4-Seam Fastball", -1.0 + (i % 2) * 0.1, 1.0, bp=1) for i in range(10)]
    raps += [_r(1, "4-Seam Fastball", -3.0 + (i % 2) * 0.1, 1.0, bp=2) for i in range(10)]
    sp = rc.spreads(raps)["4-Seam Fastball"]
    assert sp["v"] < 0.1 and sp["outings"] == 2


def test_grade_and_read():
    rng = random.Random(1)
    by = {pid: [_r(pid, "Slider", rng.gauss(0, 1.0 + 0.2 * pid), rng.gauss(0, 1.5 + 0.2 * pid), bp=pid * 10 + b)
                for b in range(3) for _ in range(8)] for pid in range(6)}
    base = rc.baselines(by)
    g_tight = rc.grade(rc.spreads(by[0]), base)["overall"]
    g_loose = rc.grade(rc.spreads(by[5]), base)["overall"]
    assert g_tight > 100 > g_loose
    assert any("wanders" in t for t in rc.read(rc.spreads(by[5]), base))


def test_mix_over_time_from_bullpens():
    raps = []
    for d in range(1, 7):
        n_sl = 2 if d <= 3 else 6
        raps += [_r(1, "4-Seam Fastball", 0, 0, bp=d, day=d) for _ in range(10 - n_sl)]
        raps += [_r(1, "Slider", 0, 0, bp=d, day=d) for _ in range(n_sl)]
    mix = trends.mix_over_time(bullpen_raps=raps, by="game")
    assert len(mix["buckets"]) == 6 and mix["series"]["Slider"][-1] == 60.0
    assert mix["read"] and ("Slider usage up" in mix["read"] or "Fastball usage down" in mix["read"])
