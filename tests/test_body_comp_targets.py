"""Oct 2026: Body Comp ring scores toward a target, capped at 100."""

import bucket_system as bs


def test_target_score_caps_and_scales():
    assert bs.target_score(190, 200) == 95
    assert bs.target_score(230, 200) == 100
    assert bs.target_score(None, 200) is None and bs.target_score(190, None) is None


def test_apply_targets_only_touches_target_metrics():
    m = {"Body Weight": {"raw": 180.0, "percentile": 72, "unit": "lb"},
         "Percent Body Fat": {"raw": 14.0, "percentile": 60, "unit": "%"}}
    bs.apply_body_comp_targets(m, {"Body Weight": {"target": 200.0, "source": "median"}})
    assert m["Body Weight"]["percentile"] == 90 and m["Body Weight"]["target_source"] == "median"
    assert m["Percent Body Fat"]["percentile"] == 60 and "target" not in m["Percent Body Fat"]


def test_median_fallback_and_stored(monkeypatch):
    pool = {"Body Weight": {1: 180.0, 2: 200.0, 3: 210.0, 4: 230.0}, "Skeletal Muscle Mass": {}}
    monkeypatch.setattr(bs, "get_latest_values_by_player", lambda s, name, _cache=None: pool[name])
    monkeypatch.setattr(bs, "stored_body_comp_targets", lambda s: {})
    t = bs.body_comp_targets(None)
    assert t["Body Weight"] == {"target": 205.0, "source": "median", "median": 205.0}
    assert "Skeletal Muscle Mass" not in t
    monkeypatch.setattr(bs, "stored_body_comp_targets", lambda s: {"Body Weight": 215.0})
    assert bs.body_comp_targets(None)["Body Weight"]["source"] == "set"
