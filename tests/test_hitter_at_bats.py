"""Hitter Game Report at-bat by at-bat (Oct 2026): location wording."""

from modules.hitter_game_report import location_words


def test_location_words():
    assert location_words(0.0, 2.5, "R") == "In zone -- middle-middle"
    assert location_words(-0.6, 3.3, "R") == "In zone -- up and in"        # RHB stands on the 3B (negative) side
    assert location_words(-0.6, 3.3, "L") == "In zone -- up and away"
    assert location_words(1.3, 1.0, "R").startswith("Ball -- down and away")
    assert location_words(0.6, 2.5, None) == "In zone -- 1B side"
    assert location_words(None, 2.5, "R") == "Not located"
