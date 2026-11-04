"""Nov 2026: Player Profile Hitting tab numbers (analytics/hitting_summary.py)."""
from datetime import date
from types import SimpleNamespace as NS

from analytics import hitting_summary as hs

_seq = [0]


def _pa(game, outcome, pitches=("Ball", "Called Strike", "In Play"), bases_before="000", bases_after="000",
        outs_before=0, outs_after=None, runs=0, d=date(2026, 3, 1), contact=None, bbt=None):
    """One plate appearance as GamePitch-like rows."""
    rows = []
    b = s = 0
    for i, o in enumerate(pitches, 1):
        _seq[0] += 1
        last = i == len(pitches)
        rows.append(NS(game_id=game, pitch_sequence=_seq[0], pa_pitch_number=i, balls_before=b, strikes_before=s,
                       pitch_outcome=o, ends_plate_appearance=last, ab_outcome=outcome if last else None,
                       bases_before=bases_before, bases_after=bases_after if last else bases_before,
                       outs_before=outs_before, outs_after=(outs_after if last else outs_before),
                       runs_scored_on_play=runs if last else 0, actual_plate_x=0.0, actual_plate_z=2.5,
                       contact_quality=contact if last else None, batted_ball_type=bbt if last else None,
                       batted_ball_x=None, batted_ball_y=None, is_pitch=True, run_value=None,
                       game=NS(game_date=d), pitch_type=None, inning=1))
        if o == "Ball":
            b += 1
        elif o in ("Called Strike", "Swing and Miss") or (o == "Foul" and s < 2):
            s += 1
    return rows


def test_productive_outs():
    pas = [
        _pa(1, "Groundout", bases_before="010", bases_after="001", outs_after=1),   # runner 2nd -> 3rd: productive
        _pa(1, "Flyout", bases_before="100", bases_after="100", outs_before=1, outs_after=2),  # nothing moved
        _pa(1, "K", pitches=("Called Strike", "Called Strike", "Swing and Miss"), bases_before="001", outs_after=1),
        _pa(1, "Sac Fly", bases_before="001", bases_after="000", outs_after=1, runs=1),
        _pa(1, "Double Play", bases_before="100", outs_before=0, outs_after=2),
        _pa(1, "Groundout", bases_before="000", outs_after=1),                      # bases empty: not an opportunity
        _pa(1, "1B", bases_before="010", bases_after="101", outs_after=0),          # not an out
    ]
    completed = hs._completed([p for pa in pas for p in pa])
    assert hs.productive_outs(completed) == (2, 5)


def test_summary_and_trend():
    ps = []
    for g, d in ((1, date(2026, 3, 1)), (2, date(2026, 3, 3)), (3, date(2026, 3, 5))):
        ps += _pa(g, "2B", d=d, contact="Barreled/Squared Up", bbt="Line Drive")
        ps += _pa(g, "BB", pitches=("Ball",) * 4, d=d)
        ps += _pa(g, "Groundout", d=d, outs_after=1, contact="Weak", bbt="Ground Ball")
    s = hs.summary(ps, bats="R")
    assert s["line"]["PA"] == 9
    assert s["extra"]["Pitches / PA"] == round(len(ps) / 9, 2)
    assert s["batted"]["Hard Contact %"] == 50.0
    t = hs.game_trend(ps)
    assert [r["PA"] for r in t] == [3, 3, 3] and t[-1]["roll_ops"] == t[0]["OPS"]
    for _l, src, key, _h, _k in hs.HEADLINE:
        assert key in s[src]


def test_render_tab_and_svg():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shiny_app"))
    import hitting_tab_display as htd
    ps = []
    for g, d in ((1, date(2026, 3, 1)), (2, date(2026, 3, 3))):
        ps += _pa(g, "1B", d=d, contact="Solid", bbt="Line Drive")
        ps += _pa(g, "K", pitches=("Called Strike", "Swing and Miss", "Swing and Miss"), d=d, outs_after=1)
    mine = hs.summary(ps, bats="L")
    mine["line"].update({"R": 1, "SB": 0, "CS": 0})
    html = str(htd.render_tab(NS(bats="L"), "2025-26", mine, hs.summary(ps), hs.game_trend(ps)))
    for word in ("QAB %", "Hard-Hit %", "Productive out %", "Chase %", "QAB % BY GAME"):
        assert word in html, word
    assert "Pull" not in html   # no spray locations charted -> spray row hidden
    assert htd.fmt(0.345, "avg") == ".345" and htd.fmt(1.012, "avg") == "1.012"
