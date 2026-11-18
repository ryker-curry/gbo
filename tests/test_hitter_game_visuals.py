"""Oct 2026: Hitter Game Breakdown swing decisions map."""

from types import SimpleNamespace as NS

from visualizations.hitter_pitch_chart import swing_decision_chart


def _p(out, x=0.0, z=2.5):
    return NS(pitch_outcome=out, actual_plate_x=x, actual_plate_z=z, pa_pitch_number=1, balls_before=0,
              strikes_before=0, pitch_type=NS(type_name="Slider"))


def test_swing_decision_buckets():
    items = [(_p("In Play"), 0.1, 1), (_p("Swing and Miss", x=1.5, z=1.0), -0.1, 1),
             (_p("Ball", x=1.6), 0.05, 2), (_p("Called Strike"), -0.08, 2), (_p("Called Strike"), None, 3)]
    fig = swing_decision_chart(items, batter_hand="R")
    names = [t.name for t in fig.data]
    assert names == ["Good swing", "Bad swing", "Good take", "Bad take", "Not graded"]
    assert fig.data[2].marker.symbol == "circle-open" and fig.data[0].marker.symbol == "circle"
