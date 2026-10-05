from models import Game, GamePitch, RapsodoPitch, GameRunnerEvent


def test_seed_builds(db):
    assert db.query(Game).count() == 7
    assert db.query(GamePitch).count() > 400
    assert db.query(RapsodoPitch).filter(RapsodoPitch.game_pitch_id.isnot(None)).count() > 150
    assert db.query(GameRunnerEvent).count() == 1


def test_counts_are_legal(db):
    for p in db.query(GamePitch).all():
        assert 0 <= p.balls_before <= 3 and 0 <= p.strikes_before <= 2, p.game_pitch_id
