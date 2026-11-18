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


def test_headline_weighting():
    """Nov 2026: headline metrics carry 2/3 of a group's score."""
    m = {"Countermovement Jump Height": {"percentile": 90}, "CMJ Peak Power": {"percentile": 90},
         "CMJ Eccentric Duration": {"percentile": 30}, "CMJ Eccentric Peak Velocity": {"percentile": 30}}
    assert bs.average_percentiles(m) == 70          # 2/3*90 + 1/3*30
    assert bs.average_percentiles({"CMJ Eccentric Duration": {"percentile": 30}}) == 30
    assert bs.average_percentiles({"30-Yard Sprint Time": {"percentile": 80}, "Acceleration: 10-Yard Sprint Time": {"percentile": 60}}) == 70
    assert bs.average_percentiles({"X": {"percentile": None}}) is None
    every = {n for g in (list(bs.POWER_SUBGROUPS.values()) + list(bs.STRENGTH_SUBGROUPS.values())
                         + list(bs.CAPACITY_SUBGROUPS.values()) + [bs.BODY_COMP_METRICS]) for n, _ in g}
    assert bs.HEADLINE_METRICS <= every            # every headliner is a scored metric
