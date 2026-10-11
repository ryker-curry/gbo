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
