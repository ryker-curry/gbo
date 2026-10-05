import pytest

from analytics.pitch_grading import STUFF_PLUS_FIXED_WEIGHTS
from visualizations import grade_explainer as gx


@pytest.mark.parametrize("pitch", list(STUFF_PLUS_FIXED_WEIGHTS))
def test_stuff_shares_add_to_100(pitch):
    rows = gx.stuff_shares(pitch)
    assert abs(sum(p for _f, p, _n in rows) - 100) < 0.01
    assert all(f in gx.FEATURE_WORDS for f, _p, _n in rows)
    # gyro is "less is better" wherever it's weighted negative
    for f, _p, neg in rows:
        assert neg == (STUFF_PLUS_FIXED_WEIGHTS[pitch][f] < 0)


def test_render_has_every_grade_and_pitch():
    html = gx.render_html()
    for word in ("Stuff+", "Location+", "Command+", "Pitching+", "Arsenal", "Results", "Performance"):
        assert word in html
    for pitch in STUFF_PLUS_FIXED_WEIGHTS:
        assert f"<summary>{pitch}</summary>" in html
    assert html.count(" open>") == 1          # one pitch open at a time
    assert "60%" in html and "40%" in html    # Pitching+ blend
