"""Pitches per out / per batter faced (Oct 2026, Ryker)."""

from tests.test_tbip import _pa
from game_stats import compute_pitching_line
from analytics import pitcher_game_report as pgr


def _outing():
    # 4 hitters, 8 pitches: K (3 pitches), E (1), Groundout (2), Flyout (2) -> 3 outs
    seq, out = 0, []
    for outcome, n, ob, oa in (("K", 3, 0, 1), ("E", 1, 1, 1), ("Groundout", 2, 1, 2), ("Flyout", 2, 2, 3)):
        for k in range(n):
            seq += 1
            last = k == n - 1
            p = _pa(outcome if last else None, ob, oa if last else ob, seq)
            p.ends_plate_appearance = last
            p.pitch_outcome = "In Play" if last and outcome != "K" else ("Swing and Miss" if last else "Foul")
            p.pa_pitch_number = k + 1
            out.append(p)
    return out


def test_pitching_line_pitches_per_out_and_bf():
    line = compute_pitching_line(_outing())
    assert line["Pitches"] == 8 and line["Outs"] == 3 and line["Errors Behind"] == 1
    assert line["Pitches/Out"] == round(8 / 3, 2)
    assert line["Pitches/Out (E as outs)"] == 2.0
    assert line["Pitches/BF"] == 2.0


def test_pickoff_counts_as_an_out():
    line = compute_pitching_line(_outing(), extra_outs=1)
    assert line["Outs"] == 4 and line["Pitches/Out"] == 2.0


def test_header_stats_match():
    ps = _outing()
    from game_stats import _group_into_plate_appearances
    pas = [pa for pa in _group_into_plate_appearances(ps) if pa[-1].ends_plate_appearance]
    h = pgr._compute_header_stats(ps, pas)
    assert h["outs"] == 3 and h["errors_behind"] == 1
    assert h["pitches_per_out"] == round(8 / 3, 2) and h["pitches_per_out_e"] == 2.0 and h["pitches_per_bf"] == 2.0
