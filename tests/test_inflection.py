"""Oct 2026: inflection points (breakpoint model + velo-line split)."""

from types import SimpleNamespace as NS

import numpy as np

from analytics import inflection as inf


def test_plateau_found_and_line_not_bent():
    rng = np.random.default_rng(1)
    x = rng.uniform(170, 240, 32)
    y = np.where(x < 200, 78 + 0.25 * (x - 170), 85.5) + rng.normal(0, 0.8, 32)
    f = inf.breakpoint_fit(x, y)
    assert 190 < f["k"] < 206 and f["p_line"] < 0.05 and f["p_chance"] < 0.05
    assert inf.pattern(f)[0] == "plateau" and f["n_below"] + f["n_above"] == 32
    y2 = 80 + 0.1 * (x - 170) + rng.normal(0, 0.8, 32)
    assert inf.pattern(inf.breakpoint_fit(x, y2))[0] == "line"
    assert inf.breakpoint_fit(x[:8], y[:8]) is None


def test_velo_line_split_and_derived_metrics():
    x = np.arange(170, 202, 1.0)
    y = np.where(x >= 186, 86.0, 82.0)
    sp = inf.velo_line_split(x, y, 85)
    assert sp["higher"] and 185 < sp["cutoff"] < 186 and sp["in_fast"] == sp["in_n"] and sp["out_fast"] == 0
    rec = {"player": NS(height_in=72, throws="R"),
           "tests": {"Body Weight": (200.0,), "Skeletal Muscle Mass": (100.0,)}, "fb": {"avg_velo": 85.0}}
    assert inf.metric_value(rec, "smm_pct", "") == 50.0
    assert abs(inf.metric_value(rec, "bw_in", "") - 200 / 72) < 1e-9
    assert inf.pairs({1: rec}, "Skeletal Muscle Mass per inch of height", "avg_velo") == [(1, 100 / 72, 85.0)]
