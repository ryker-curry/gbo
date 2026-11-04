"""Nov 2026: substitute lifts stay out of scoring; pitchers are scored
against pitchers and position players against position players."""
import bucket_system as bs


def test_is_substitute():
    notes = "Position players testing sheet | *Front Squat Max = leg press 720 x3"
    assert bs.is_substitute(notes, "Front Squat Max")
    assert not bs.is_substitute(notes, "Hex Bar Deadlift Max")
    assert not bs.is_substitute(None, "Front Squat Max")


def test_same_group_pool(monkeypatch):
    groups = {1: True, 2: True, 3: False, 4: False}
    monkeypatch.setattr(bs, "player_groups", lambda session: groups)
    cache = {"Front Squat Max": {1: 300.0, 2: 350.0, 3: 400.0, 4: 450.0}}
    assert bs.same_group_pool(cache, None, 1, True) == {"Front Squat Max": {1: 300.0, 2: 350.0}}
    assert bs.same_group_pool(cache, None, 3, False) == {"Front Squat Max": {3: 400.0, 4: 450.0}}
    # a hitter at 400 is 89% of the top position player, not 100% of a pooled max
    pool = bs.same_group_pool(cache, None, 3, False)["Front Squat Max"]
    assert bs.compute_percentile(400.0, list(pool.values()), "higher") == 89
    assert cache["Front Squat Max"][1] == 300.0   # shared cache untouched
