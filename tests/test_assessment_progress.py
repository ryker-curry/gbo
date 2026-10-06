"""My Assessments (Oct 2026): change since last test, true team rank,
progress chart, compact Mobility section."""

import datetime as dt

from analytics import assessment_progress as ap
from visualizations import progress_chart

D1, D2, D3 = dt.date(2025, 8, 25), dt.date(2026, 8, 20), dt.date(2026, 9, 11)


def test_direction_map():
    d = ap.direction_map()
    assert d["Vertical Jump (Jump Mat)"] == "higher"
    assert d["30-Yard Sprint Time"] == "lower"
    assert d["Body Weight"] is None          # neutral: heavier isn't automatically better


def test_change_for():
    assert ap.change_for([(D1, 30.0)], "higher") is None
    c = ap.change_for([(D1, 30.0), (D2, 27.2)], "higher")
    assert round(c["delta"], 1) == -2.8 and c["better"] is False and c["prev_date"] == D1
    c = ap.change_for([(D1, 4.10), (D2, 4.00)], "lower")
    assert c["better"] is True
    assert ap.change_for([(D1, 180.0), (D2, 184.0)], None)["better"] is None
    # measured from the test before the value the bar shows, not the newest
    c = ap.change_for([(D1, 25.0), (D2, 27.0), (D3, 29.0)], "higher", current_raw=27.0)
    assert c["delta"] == 2.0 and c["latest_date"] == D2


def test_team_rank_pct():
    team = [23.0, 26.3, 27.2, 30.0, 40.3]
    assert ap.team_rank_pct(27.2, team, "higher") == 50      # beats 2 of 4
    assert ap.team_rank_pct(40.3, team, "higher") == 100
    assert ap.team_rank_pct(1.70, [1.70, 1.80, 1.90], "lower") == 100
    assert ap.team_rank_pct(5.0, [5.0], "higher") is None


def test_progress_svg():
    svg = progress_chart.render_svg([(D1, 30.4), (D2, 27.2)], "in", team_avg=30.2, name="Vertical Jump")
    assert svg.startswith("<svg") and "27.2 in" in svg and "Team avg 30.2 in" in svg and "<path" in svg
    one = progress_chart.render_svg([(D2, 27.2)], "in")
    assert "<path" not in one and "27.2 in" in one
    assert progress_chart.render_svg([], "in") == ""


def test_compact_mobility():
    import bucket_display
    report = [
        {"test_name": "Shoulder: Right Internal Rotation", "raw": 27.0, "unit": "°", "threshold": 45.0, "status": "red"},
        {"test_name": "Shoulder: Left Internal Rotation", "raw": 57.0, "unit": "°", "threshold": 45.0, "status": "green"},
        {"test_name": "Hip: Plant Leg External Rotation", "raw": 27.0, "unit": "°", "threshold": 24.0, "status": "yellow"},
        {"test_name": "Elbow: Right Flexion", "raw": 121.0, "unit": "°", "threshold": None, "status": None},
    ]
    html = str(bucket_display.build_mobility_rom_report(report, compact=True))
    assert "Needs attention (2)" in html and "Show all 4 measurements" in html
    assert html.index("Right Internal Rotation") < html.index("Plant Leg External Rotation")   # red before caution
    full = str(bucket_display.build_mobility_rom_report(report))
    assert "Needs attention" not in full and "Show all" not in full


def test_breakdown_groups_split_into_tabs():
    import bucket_display
    empty_m = {}
    bd = {"body_comp_score": 70, "body_comp_metrics": {"Body Weight": {"raw": 180.0, "percentile": 80, "unit": "lb"}},
          "power_score": None, "power_subgroup_scores": {}, "power_subgroup_metrics": {},
          "strength_score": None, "strength_subgroup_scores": {}, "strength_subgroup_metrics": {},
          "speed_score": 90, "speed_metrics": {"30-Yard Sprint Time": {"raw": 4.0, "percentile": 90, "unit": "s"}},
          "capacity_subgroup_metrics": empty_m, "mobility_rom_report": [], "movement_flag": None,
          "shoulder_health_metrics": {}}
    keys = [k for k, _, _ in bucket_display.breakdown_groups(bd, "t")]
    assert keys == ["body_comp", "power", "strength", "speed"]       # no Mobility tab without ROM data
    assert "Body Weight" in str(bucket_display.build_full_breakdown(bd, "t"))
