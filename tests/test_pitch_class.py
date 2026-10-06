"""Pitch Type Check (Oct 2026): fastball / breaking ball / changeup groups."""

from types import SimpleNamespace as NS

from analytics import pitch_class as pc

CENTERS = {pc.FB: (11.6, 13.4, -1.1), pc.BB: (-7.5, -4.8, -11.4), pc.CH: (14.4, 8.8, -8.1)}


def _p(t, velo, run, ivb, throws="R", bp=1):
    hb = run if throws == "R" else -run
    return NS(vb_spin=ivb, hb_spin=hb, vb_trajectory=None, hb_trajectory=None, velocity=velo,
              bullpen_id=bp, import_id=None, pitch_date=None, pitch_type=NS(type_name=t))


def _arsenal(throws="R"):
    out = [_p("4-Seam Fastball", 90 + i * 0.3, 11 + i % 3, 14 + i % 2, throws) for i in range(10)]
    out += [_p("Slider", 79 + i * 0.2, -7 - i % 2, -4, throws) for i in range(6)]
    out += [_p("Changeup", 82 + i * 0.2, 14, 8, throws) for i in range(6)]
    return out


def test_clean_arsenal_has_no_flags():
    res = pc.check_pitcher(_arsenal(), "R", CENTERS)
    assert res["flags"] == [] and res["agree_pct"] == 100.0


def test_mislabeled_changeup_logged_as_cutter_is_flagged():
    raps = _arsenal() + [_p("Cutter", 82.5, 13, 8)]
    res = pc.check_pitcher(raps, "R", CENTERS)
    assert len(res["flags"]) == 1
    f = res["flags"][0]
    assert f["labeled"] == "Cutter" and f["looks_like"] == pc.CH and f["suggested"] == "Changeup"


def test_lefty_mirrored_and_swapped_labels_caught():
    raps = _arsenal("L") + [_p("4-Seam Fastball", 79.5, -7, -4, "L"), _p("Slider", 91, 12, 14, "L")]
    res = pc.check_pitcher(raps, "L", CENTERS)
    got = {(f["labeled"], f["suggested"]) for f in res["flags"]}
    assert got == {("4-Seam Fastball", "Slider"), ("Slider", "4-Seam Fastball")}


def test_gray_areas_not_flagged():
    # a cutter that plays like a breaking ball, a splitter with breaking-ball drop
    raps = _arsenal() + [_p("Cutter", 82, -6, -2), _p("Splitter", 79, 6, -5)]
    res = pc.check_pitcher(raps, "R", CENTERS)
    assert res["flags"] == []
