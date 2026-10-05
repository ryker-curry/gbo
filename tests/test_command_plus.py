"""Command+ (Oct 2026 fix): misses off the plate are never rewarded, misses
toward the middle cost extra, and pitchers spread out on a pitcher-level scale."""

import random
from types import SimpleNamespace as NS

from analytics import command_metrics as cm


def _view(ix, iz, ax, az, pid=1, t="4-Seam Fastball"):
    gp = NS(intended_plate_x=ix, intended_plate_z=iz, actual_plate_x=ax, actual_plate_z=az,
            pitch_type=NS(type_name=t), is_our_team_batting=False, our_player_id=pid,
            opponent_our_player_id=None, game_id=1, pitch_sequence=1, game_pitch_id=random.random())
    return cm._GamePitchCommandView(gp, "R", 1)


def test_wild_miss_off_plate_is_worse_than_small_miss():
    target = (0.7, 2.0)                     # called on the edge
    small = _view(*target, 0.75, 2.05)
    wild = _view(*target, 2.2, 2.0)         # way off the plate, away from the middle
    assert cm.danger_adjusted_miss(wild) > cm.danger_adjusted_miss(small)
    assert cm.danger_adjusted_miss(wild) >= wild.miss_distance   # never a bonus for missing away


def test_toward_middle_costs_extra():
    away = _view(0.5, 2.5, 1.0, 2.5)        # same 6 in miss, drifting away from the middle
    toward = _view(0.5, 2.5, 0.0, 2.5)      # 6 in miss, drifting into the heart
    assert cm.danger_adjusted_miss(toward) > cm.danger_adjusted_miss(away)
    assert cm.danger_adjusted_miss(away) == away.miss_distance


def test_pitcher_scale_spreads_and_shrinks():
    rnd = random.Random(3)
    pitches = []
    for pid, noise in enumerate([0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75], start=1):
        for _ in range(80):
            pitches.append(_view(0.6, 2.2, 0.6 + rnd.gauss(0, noise), 2.2 + rnd.gauss(0, noise), pid=pid))
    b = cm.team_command_plus_baselines(pitches)
    assert b["pitcher_scale"] is not None
    scores = {pid: cm.session_command_plus([p for p in pitches if p.pitcher_id == pid], b) for pid in range(1, 8)}
    assert scores[1] > 110 and scores[7] < 90           # spread like the other "+" grades
    assert scores[1] > scores[4] > scores[7]
    # a tiny sample stays near 100
    few = [p for p in pitches if p.pitcher_id == 1][:5]
    assert abs(cm.session_command_plus(few, b) - 100) < abs(scores[1] - 100)
