"""TBIP (Oct 2026): bases allowed per inning = (BB + HBP + 1B + 2x2B + 3x3B + 4xHR) / IP."""

from types import SimpleNamespace as NS

from game_stats import compute_pitching_line


def _pa(outcome, outs_before, outs_after, seq):
    return NS(ends_plate_appearance=True, ab_outcome=outcome, pitch_outcome="In Play", outs_before=outs_before,
              outs_after=outs_after, balls_before=0, strikes_before=0, pa_pitch_number=1, pitch_sequence=seq,
              inning=1, game_id=1, runs_scored_on_play=0, unearned_runs_on_play=0, earned_runs_on_play=0, run_value=None,
              intended_plate_x=None, intended_plate_z=None, actual_plate_x=None, actual_plate_z=None,
              contact_quality=None, batted_ball_type=None, is_our_team_batting=False, bases_before="000",
              pitch_type=None, intended_zone=None, pitch_zone=None, our_player_id=1)


def test_tbip_counts_bases_per_inning():
    pas = [_pa("BB", 0, 0, 1), _pa("HBP", 0, 0, 2), _pa("1B", 0, 0, 3), _pa("2B", 0, 0, 4), _pa("HR", 0, 0, 5),
           _pa("K", 0, 1, 6), _pa("Groundout", 1, 2, 7), _pa("Flyout", 2, 3, 8)]
    line = compute_pitching_line(pas)
    assert line["Bases Allowed"] == 1 + 1 + 1 + 2 + 4
    assert line["TBIP"] == 9.0          # 9 bases over 1 inning
