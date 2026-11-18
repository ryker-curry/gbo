"""Step-by-step Live Tracking (phones/tablets): every button maps to a real value."""

import game_tracking_step_display as sd
from modules import game_tracking as gt


def test_buttons_use_real_values():
    assert {o for o, _l, _k in sd.OUTCOME_BUTTONS} == set(gt.PITCH_OUTCOMES)
    assert set(sd.IN_PLAY_AB) <= set(gt.AB_OUTCOMES)
    assert set(sd.NON_IN_PLAY_AB) <= set(gt.AB_OUTCOMES)
    assert set(sd.IN_PLAY_CQ) <= set(gt.CONTACT_QUALITY_OPTIONS) and "Miss" not in sd.IN_PLAY_CQ


def test_every_call_on_the_grid_decodes():
    import strike_zone
    for level in (1, 2, 3, 4):
        for zone in range(1, 6):
            strike_zone.decode_pitch_code(*strike_zone.parse_pitch_code(f"{level}{zone}"))


def test_paper_chart_shorthand():
    p = sd.parse_scoring
    assert p("6-3") == {"ab": "Groundout", "bbt": "Ground Ball", "fielder": 6}
    assert p("f7") == {"ab": "Flyout", "bbt": "Fly Ball", "fielder": 7}
    assert p("P4")["bbt"] == "Pop Up" and p("L6")["ab"] == "Lineout"
    assert p("1B")["ab"] == "1B" and p("2B9")["fielder"] == 9 and p("HR")["bbt"] == "Fly Ball"
    assert p("E5")["ab"] == "E" and p("FC6")["ab"] == "FC" and p("SF8")["ab"] == "Sac Fly"
    assert p("6-4-3")["ab"] == "Double Play" and p("DP6-4-3")["ab"] == "Double Play"
    assert p("3U")["ab"] == "Groundout" and p("3")["fielder"] == 3
    assert p("KL")["ab"] == "K (Looking)" and p("SH")["ab"] == "Sac Bunt"
    for bad in ("", "xyz", "SB"):
        try:
            p(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    for res in ("6-3", "F7", "1B", "E5", "FC6", "SF8", "6-4-3", "L6", "P4"):
        assert p(res)["ab"] in gt.AB_OUTCOMES
    assert all(sd.parse_scoring(r) for r in sd.QUICK_RESULTS)


def test_bare_outfielder_number_is_a_fly_out():
    from game_tracking_step_display import parse_scoring
    for n in (7, 8, 9):
        assert parse_scoring(str(n)) == {"ab": "Flyout", "bbt": "Fly Ball", "fielder": n}
    assert parse_scoring("6")["ab"] == "Groundout"
