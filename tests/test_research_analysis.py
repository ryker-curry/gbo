"""Research project analysis (Oct 2026): stats helpers, pairing, CSV."""

import datetime as dt

import pytest
from types import SimpleNamespace as NS

from analytics import research_analysis as ra


def test_stats_match_known_values():
    assert abs(ra.p_value(0.5, 20) - 0.0248) < 0.0005
    assert abs(ra.p_value(0.3, 30) - 0.107) < 0.001
    lo, hi = ra.fisher_ci(0.5, 20)
    assert abs(lo - 0.074) < 0.002 and abs(hi - 0.772) < 0.002
    assert abs(ra.spearman([1, 2, 3, 4, 5], [2, 1, 4, 3, 5]) - 0.8) < 1e-9
    assert ra.bh_flags([0.001, 0.02, 0.04, 0.5, None]) == {0, 1}
    assert ra.strength(0.45) == "moderate" and ra.strength(-0.6) == "large"


def _ds():
    d = dt.date(2026, 9, 1)
    ds = {}
    for i in range(8):
        tests = {"Broad Jump Distance": (90.0 + 2 * i, d, "in"), "Body Weight": (180.0 + i, d, "lb"),
                 "Hex Bar Deadlift Max": (300.0 + 10 * i, d, "lb"),
                 "30-Yard Sprint Time": (4.4 - 0.02 * i, d, "s")}
        ds[i] = {"player": NS(first_name="P", last_name=str(i), throws="R" if i % 2 else "L"),
                 "tests": tests, "fb": {"avg_velo": 80.0 + i, "peak_velo": 82.0 + i, "avg_spin": 2100.0,
                                        "bauer": 2100.0 / (80 + i), "n_velo": 20, "n_spin": 20}}
    return ds


def test_correlations_and_reads():
    rows, m = ra.correlations(_ds(), "avg_velo")
    by = {r["test"]: r for r in rows}
    assert by["Broad Jump Distance"]["r"] > 0.99 and by["Broad Jump Distance"]["n"] == 8
    assert by["30-Yard Sprint Time"]["r"] < -0.99
    assert "better result goes with more FB velo" in ra.meaning(by["30-Yard Sprint Time"], "avg_velo")
    assert by["Front Squat Max"]["r"] is None and m >= 3
    rel = ra.pairs(_ds(), "Hex Bar Deadlift Max", "avg_velo", relative=True)
    assert abs(rel[0][1] - 300 / 180) < 1e-9
    assert len(ra.pairs(_ds(), "Broad Jump Distance", "avg_velo", hand="R")) == 4


def test_checklist_and_csv():
    rows = ra.checklist(_ds())
    assert rows[0]["cats"]["Field testing & ROM"]["done"] == 1 and not rows[0]["complete"]
    assert ra.CALC_GROUP not in rows[0]["cats"]
    csv_text = ra.to_csv(_ds())
    head = csv_text.splitlines()[0].split(",")
    assert head.count("Body Weight") == 1 and "fb_avg_velo" in head and len(csv_text.splitlines()) == 9


def test_variables_grouped_by_tab_with_calculated():
    groups = [g for g, _ in ra.BATTERY]
    assert groups[0] == "Shoulder dynamometry" and groups[-1] == ra.CALC_GROUP
    assert "Shoulder: Throw External Rotation" in ra.TESTS
    assert any(t.startswith("Dynamic Strength Index") for t in ra.TESTS)
    v = {"CMJ Concentric Peak Force": 2400.0, "Isometric Mid-Thigh Pull Peak Vertical Force": 3000.0,
         "Hip Abduction Force (Drive Leg)": 200.0, "Hip Abduction Force (Plant Leg)": 150.0}
    fns = {lab: fn for lab, _u, fn in ra.DERIVED_FNS}
    dsi = [fn for lab, fn in fns.items() if lab.startswith("Dynamic Strength Index")][0]
    assert dsi(v) == pytest.approx(0.8)
    assert fns["Hip ABD max force asymmetry (drive vs plant)"](v) == pytest.approx(25.0)
    assert ra.relative_ok("Hex Bar Deadlift Max") and not ra.relative_ok("30-Yard Sprint Time")
