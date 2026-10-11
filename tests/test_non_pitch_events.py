"""Oct 2026: pitch clock violations and intentional walks (is_pitch=False rows)."""

from types import SimpleNamespace as NS

import game_stats
from modules import game_tracking as gt


def test_count_after():
    assert gt.count_after(gt.CLOCK_BALL, 1, 2) == (2, 2)
    assert gt.count_after(gt.CLOCK_STRIKE, 0, 2) == (0, 3)      # batter violation can be strike three
    assert gt.count_after("Foul", 0, 2) == (0, 2)


def test_violation_and_ibb_end_at_bat():
    st = {"balls": 3, "strikes": 1}
    assert gt._ends_plate_appearance(st, gt.CLOCK_BALL)[0] is True
    assert gt._ends_plate_appearance({"balls": 1, "strikes": 2}, gt.CLOCK_STRIKE)[0] is True
    assert gt._ends_plate_appearance({"balls": 0, "strikes": 0}, gt.IBB_OUTCOME)[0] is True
    assert gt._ends_plate_appearance({"balls": 0, "strikes": 0}, gt.CLOCK_BALL)[0] is False
    assert gt.suggest_after_state("IBB", "100", 1) == (1, "110", 0)


def _pa_row(ab, is_pitch=True, outcome="In Play"):
    return NS(ends_plate_appearance=True, ab_outcome=ab, is_pitch=is_pitch, pitch_outcome=outcome)


def test_ibb_is_its_own_stat_but_on_base():
    pas = [[_pa_row("IBB", False, gt.IBB_OUTCOME)], [_pa_row("BB", outcome="Ball")], [_pa_row("1B")], [_pa_row("Groundout")]]
    s = game_stats._batting_slice(pas)
    assert (s["BB"], s["IBB"], s["AB"], s["PA"]) == (1, 1, 2, 4)
    assert s["OBP"] == 0.75


def test_non_pitch_rows_not_in_pitch_count(db):
    from models import GamePitch
    pitches = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False)).all()
    base = game_stats.compute_pitching_line(pitches)
    fake = NS(**{c.name: getattr(pitches[0], c.name) for c in GamePitch.__table__.columns})
    fake.is_pitch, fake.pitch_outcome, fake.ends_plate_appearance = False, gt.CLOCK_BALL, False
    fake.earned_runs_on_play, fake.runs_scored_on_play, fake.pitch_sequence = 0, 0, 10 ** 6
    line = game_stats.compute_pitching_line(pitches + [fake])
    assert line["Pitches"] == base["Pitches"] and line["Strike %"] == base["Strike %"]
