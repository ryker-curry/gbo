"""Oct 2026 article batch, part 2: tunnel check, Rapsodo data check,
release outliers / beats his stuff, Arsenal Breadth+, outcome profile,
metric check, charter training."""

import datetime as dt
import random
from types import SimpleNamespace as NS

from analytics import (tunnel_check, rapsodo_check, outperform, arsenal_breadth, outcome_profile,
                       metric_check, charter_training)


def _rap(pid=1, label="4-Seam Fastball", velo=88.0, ivb=15.0, hb=8.0, spin=2200.0, bp=1, n=1, rid=None,
         rh=5.9, rs=1.6, ext=6.1, conf=0.9, x=0.0, z=2.5):
    return NS(player_id=pid, pitch_type=NS(type_name=label) if label else None, velocity=velo, vb_spin=ivb,
              hb_trajectory=hb, total_spin=spin, bullpen_id=bp, import_id=bp, pitch_number=n,
              rapsodo_pitch_id=rid if rid is not None else n, release_height=rh, release_side=rs,
              release_extension=ext, spin_confidence=conf, plate_x_ft=x, plate_z_ft=z,
              pitch_date=dt.datetime(2026, 9, bp, 15), spin_direction_clock="12:30", spin_efficiency=92.0)


def test_tunnel_check():
    fb = [_rap(ivb=16, hb=8, velo=88) for _ in range(5)]
    cb = [_rap(label="Curveball", ivb=-12, hb=-6, velo=73) for _ in range(5)]
    sl = [_rap(label="Slider", ivb=2, hb=-4, velo=81) for _ in range(5)]
    assert not tunnel_check.check(fb, cb)["ok"]
    assert tunnel_check.check(fb, sl)["ok"]


def test_rapsodo_check_flags_shifted_session():
    rng = random.Random(3)
    allp = [_rap(spin=2200 + rng.gauss(0, 40), bp=b, n=i) for b in range(1, 6) for i in range(10)]
    bad = [_rap(spin=1750 + rng.gauss(0, 40), bp=7, n=i, rid=100 + i) for i in range(10)]
    bad.append(_rap(label=None, bp=7, n=50, rid=200))
    rows = rapsodo_check.check(bad + allp[:10], allp + bad)
    top = rows[0]
    assert top["key"] == ("bp", 7) and any("spin" in i and "SD" in i for i in top["issues"])
    assert any("unclassified" in i for i in top["issues"])
    assert all(r["key"] != ("bp", 1) for r in rows)


def test_release_outliers_and_beats_stuff():
    profiles = {i: {"height": 5.8 + 0.02 * i, "side": 1.6, "ext": 6.0} for i in range(8)}
    profiles[9] = {"height": 4.6, "side": 1.6, "ext": 6.0}
    rel = outperform.release_outliers(profiles)
    assert rel[9]["height"]["tag"] == "very low release height" and rel[9]["score"] > 2
    pts = {i: (90 + 2 * i, 2.0 - 0.3 * i, 100) for i in range(8)}
    pts[99] = (100, -5.0, 100)        # far better results than his stuff predicts
    beats, fit = outperform.beats_stuff(pts)
    assert fit and beats[99]["value"] > 3
    assert outperform.describe_beats(beats[99]["value"]).startswith("getting more")


def test_arsenal_breadth():
    def arsenal(pid, spread):
        return ([_rap(pid=pid, velo=90, ivb=16, hb=8) for _ in range(10)]
                + [_rap(pid=pid, label="Curveball", velo=90 - spread, ivb=16 - 2 * spread, hb=8 - spread) for _ in range(10)])
    by = {pid: arsenal_breadth.spreads(arsenal(pid, s), lambda p: p.pitch_type.type_name)
          for pid, s in enumerate([2, 4, 6, 8, 10, 12])}
    br = arsenal_breadth.breadth_plus(by)
    assert br[5]["plus"] > 100 > br[0]["plus"]


def test_outcome_profile_uses_similar_shapes():
    train = []
    for i in range(200):     # high-ride fastballs whiff, low-ride ones don't
        hi = i % 2 == 0
        train.append({"pid": 50 + i % 5, "fam": "Fastballs", "label": "4-Seam Fastball", "v": 88.0,
                      "ivb": 19.0 if hi else 11.0, "run": 8.0,
                      "outcome": "Swing and Miss" if hi else "In Play", "bb": None if hi else "Ground Ball"})
    mine = [_rap(pid=1, ivb=19.0) for _ in range(10)]
    prof = outcome_profile.profile(mine, [], "R", train, 1)
    assert prof[0]["like"]["whiff"] > 80 and prof[0]["staff"]["whiff"] == 50


def test_metric_check():
    assert metric_check.spearman_brown(0.5) == 2 * 0.5 / 1.5
    groups = {i: [i] * 50 for i in range(6)}            # every pitcher perfectly consistent
    r = metric_check.split_half(groups, lambda xs: sum(xs) / len(xs))
    assert r["read"] == "stable"
    thin = metric_check.split_half({1: [1] * 10}, lambda xs: 1)
    assert thin["r"] is None


def test_charter_training():
    raps = ([_rap(pid=1, n=i, rid=i) for i in range(6)]
            + [_rap(pid=1, label="Slider", ivb=1, hb=-5, n=10 + i, rid=10 + i) for i in range(6)]
            + [_rap(pid=2, n=30 + i, rid=30 + i) for i in range(6)])          # one-pitch pitcher: not quizzed
    lab = lambda p: p.pitch_type.type_name if p.pitch_type else None
    card = charter_training.arsenal_card(raps, "L", lab)
    assert card[0]["run"] == -8.0          # lefty run flipped to arm side
    pool = charter_training.quiz_pool(raps, lab)
    assert {p.player_id for p in pool} == {1}
    assert charter_training.choices_for(pool, lab, 1) == ["4-Seam Fastball", "Slider"]
    s = charter_training.update_score(dict(charter_training.NEW_SCORE), True)
    s = charter_training.update_score(s, False)
    assert s == {"right": 1, "total": 2, "streak": 0, "best": 1}
