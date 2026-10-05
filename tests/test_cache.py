import pytest

import gbo_cache
from analytics import profile_queries
from models import Player


pytestmark = pytest.mark.skipif(not gbo_cache.enabled(), reason="GBO_CACHE=0")


def test_cache_hits_and_clears_on_save(db):
    gbo_cache.clear()
    a = profile_queries.team_stuff_plus_baselines(db)
    before = gbo_cache.stats()["hit"]
    b = profile_queries.team_stuff_plus_baselines(db)
    assert a is b and gbo_cache.stats()["hit"] == before + 1

    # a roster save clears entries that read players, not the Stuff+ models
    import game_stats
    game_stats._hand_roster(db)
    assert any(k[0] == "hand_roster" for k in gbo_cache._store)
    p = db.query(Player).get(11)
    p.jersey_number = 7
    db.commit()
    assert not any(k[0] == "hand_roster" for k in gbo_cache._store)
    assert any(k[0] == "stuff_models" for k in gbo_cache._store)


def test_cached_matches_uncached(db):
    gbo_cache.clear()
    cached = profile_queries.team_stuff_plus_training_pitches(db)
    raw = profile_queries.team_stuff_plus_training_pitches.uncached(db)
    assert {k: len(v) for k, v in cached.items()} == {k: len(v) for k, v in raw.items()}


def test_bulk_update_clears(db):
    from models import GamePitch
    gbo_cache.clear()
    profile_queries.team_location_plus_baseline(db)
    assert any(k[0] == "location_baseline" for k in gbo_cache._store)
    db.query(GamePitch).filter(GamePitch.game_pitch_id == -1).update({"notes": "x"}, synchronize_session=False)
    db.commit()
    assert not any(k[0] == "location_baseline" for k in gbo_cache._store)
