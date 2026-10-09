"""Oct 2026: pre-game Pitch Calling Card (Level-Pitch-Zone codes) + Card vs Calls."""

import random
from types import SimpleNamespace as NS

from analytics import pitch_card as pc


def _row(pid=1, throws="R", hand="R", digit=1, level=4, zone=3, group="putaway", v=0.0, batter=("our", 9),
         outcome="Swing and Miss", ilevel=None, izone=None, in_zone=True):
    return {"pid": pid, "throws": throws, "batter": batter, "hand": hand, "digit": digit, "level": level,
            "zone": zone if throws == "R" else 6 - zone, "ilevel": ilevel or level, "izone": izone or zone,
            "group": group, "v": v, "outcome": outcome, "cq": None, "game_id": 1, "in_zone": in_zone,
            "game_pitch_id": 0, "pa_pitch_number": 1}


def test_codes_and_groups():
    assert pc.code(2, 1, 4) == "214" and pc.parse("214") == (2, 1, 4) and pc.parse("21") is None
    assert pc.GROUP_OF["1-2"] == "putaway" and pc.GROUP_OF["3-1"] == "even"
    assert pc.PITCH_DIGIT["Cutter"] == 5 and pc.PITCH_DIGIT["Slider"] == 3 and pc.PITCH_DIGIT["Splitter"] == 4


def test_model_prefers_what_works_and_mirrors_lefties():
    rng = random.Random(2)
    rows = []
    for _ in range(300):                      # 2-strike sliders down-away (zone 5 for a RHP vs RHH) work
        rows.append(_row(digit=3, level=1, zone=5, v=0.08 + rng.gauss(0, 0.02), in_zone=False))
        rows.append(_row(digit=1, level=3, zone=3, v=-0.08 + rng.gauss(0, 0.02)))
    m = pc.Model(rows)
    pitcher = NS(player_id=1, first_name="A", last_name="B", throws="R")
    use = {1: {1: 0.6, 3: 0.4}}
    card = pc.build_card(m, pitcher, [{"key": ("our", 9), "name": "H", "bats": "R"}], use)
    assert card["rows"][0]["cells"]["putaway"]["primary"] == "135"
    lefty = NS(player_id=2, first_name="L", last_name="Y", throws="L")
    card_l = pc.build_card(m, lefty, [{"key": ("our", 9), "name": "H", "bats": "L"}], {2: {1: 0.6, 3: 0.4}})
    assert card_l["rows"][0]["cells"]["putaway"]["primary"] == "131"     # mirrored: away from a LHH is zone 1


def test_compare_statuses():
    card = {"rows": [{"key": ["our", 9], "cells": {"putaway": {"primary": "135", "backup": "413"}}}], "generic": {}}
    pitches = [_row(digit=3, ilevel=1, izone=5), _row(digit=3, ilevel=2, izone=5, outcome="Ball"),
               _row(digit=4, ilevel=2, izone=3, outcome="In Play")]
    res = pc.compare({1: card}, pitches)
    assert [r["status"] for r in res["rows"]] == ["match", "pitch", "off"]
    assert res["summary"]["match"]["whiff"] == 100.0
