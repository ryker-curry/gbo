"""Oct 2026: all-balls-in-play spray chart (hits solid, outs hollow)."""

from types import SimpleNamespace as NS

from visualizations.spray_chart import all_bip_spray_chart


def _bip(ab, x=10.0, y=150.0, out="In Play"):
    return NS(pitch_outcome=out, batted_ball_x=x, batted_ball_y=y, ab_outcome=ab, contact_quality="Solid")


def test_all_bip_groups_hits_and_outs():
    ps = [_bip("1B"), _bip("Groundout"), _bip("Flyout"), _bip("Double Play"), _bip("FC"),
          _bip("Lineout", x=None), _bip(None, out="Foul")]
    fig = all_bip_spray_chart(ps)
    labels = {"Single", "Groundout", "Flyout", "Lineout", "Other (DP / FC / E / Sac)"}
    names = [t.name for t in fig.data if t.name in labels]
    assert names == ["Single", "Groundout", "Flyout", "Other (DP / FC / E / Sac)"]
    other = [t for t in fig.data if t.name and t.name.startswith("Other")][0]
    assert len(other.x) == 2 and other.marker.color == "rgba(0,0,0,0)"
    assert all_bip_spray_chart([_bip("1B", x=None)]) is None
