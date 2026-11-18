"""Oct 2026: SIERA (skill-interactive ERA), D2-scaled."""

import game_stats


def test_d2_average_pitcher_equals_d2_era():
    assert game_stats.siera(171, 116, 0, 0, 0, 1000) == 6.73


def test_direction():
    base = game_stats.siera(200, 100, 0, 0, 0, 1000)
    assert game_stats.siera(250, 100, 0, 0, 0, 1000) < base       # more K
    assert game_stats.siera(200, 140, 0, 0, 0, 1000) > base       # more BB
    low_k = game_stats.siera(100, 100, 0, 0, 0, 1000)
    assert game_stats.siera(100, 100, 200, 100, 0, 1000) < low_k  # ground balls help a contact pitcher
    assert game_stats.siera(100, 100, 50, 200, 50, 1000) > low_k  # fly balls / pop-ups hurt him
    assert game_stats.siera(0, 0, 0, 0, 0, 0) is None


def test_in_pitching_line(db):
    from models import GamePitch
    pitches = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False)).all()
    line = game_stats.compute_pitching_line(pitches)
    pa = [p for p in pitches if p.ends_plate_appearance and p.ab_outcome != "No Result"]
    count = lambda f: sum(1 for p in pa if f(p))
    assert line["SIERA"] == game_stats.siera(
        count(lambda p: p.ab_outcome in ("K", "K (Looking)")), count(lambda p: p.ab_outcome == "BB"),
        count(lambda p: p.batted_ball_type == "Ground Ball"), count(lambda p: p.batted_ball_type == "Fly Ball"),
        count(lambda p: p.batted_ball_type == "Pop Up"), len(pa))
    assert line["SIERA"] is not None
