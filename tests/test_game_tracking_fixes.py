"""Oct 2026 Game Tracking bug fixes: who bats first, replay side, suggested
results, hand-entered result checks."""

from types import SimpleNamespace as NS

from modules import game_tracking as gt


class _RE(dict):
    def get(self, k, default=None):
        return 0.0


def _game(**kw):
    base = dict(is_intrasquad=False, uses_three_squad_intrasquad=False, intrasquad_away_squad=None, is_home=None)
    base.update(kw)
    return NS(**base)


def test_first_batting_side():
    assert gt.first_batting_is_ours(None) is True
    assert gt.first_batting_is_ours(_game(is_intrasquad=True, intrasquad_away_squad="A")) is True
    assert gt.first_batting_is_ours(_game(is_intrasquad=True, intrasquad_away_squad="B")) is False
    assert gt.first_batting_is_ours(_game(is_intrasquad=True, uses_three_squad_intrasquad=True, intrasquad_away_squad="B")) is True
    assert gt.first_batting_is_ours(_game(is_home=True)) is False      # home team bats second
    assert gt.first_batting_is_ours(_game(is_home=False)) is True
    assert gt.first_batting_is_ours(_game(is_home=None)) is True       # neutral site: as before


def _pitch(gid, seq, game, ours, outcome, ends=False, outs_after=None, runs=0):
    return NS(game_id=gid, game_pitch_id=seq, pitch_sequence=seq, inning=1, is_our_team_batting=ours,
              ends_plate_appearance=ends, pitch_outcome=outcome, outs_after=outs_after, bases_after="000" if ends else None,
              runs_scored_on_play=runs, batting_squad=None, pa_pitch_number=None, game=game)


def test_replay_keeps_b_away_side():
    """Game 27 (10/7): Team B batted first. Replay used to start with Team A
    up, flipping every pitch's side and swapping the score."""
    g = _game(is_intrasquad=True, intrasquad_away_squad="B")
    pitches = [_pitch(27, 1, g, False, "Ball"), _pitch(27, 2, g, False, "In Play", ends=True, outs_after=0, runs=1),
               _pitch(27, 3, g, False, "Called Strike")]
    res = gt.replay_game(pitches, [], _RE(), [])
    assert res["side_changed_pitch_ids"] == []
    assert (res["our_score"], res["opponent_score"]) == (0, 1)
    assert gt.compute_current_state([], game=g)["is_our_batting"] is False


def test_inning_label_follows_who_batted_first():
    home = _game(is_home=True)
    assert gt._inning_display(1, home, {"is_our_batting": False}).endswith("(Top)")
    assert gt._inning_display(2, home, {"is_our_batting": True}).endswith("(Bot)")


def test_no_suggested_run_on_inning_ending_play():
    outs, bases, runs = gt.suggest_after_state("FC", "111", 2)
    assert (outs, bases, runs) == (3, "000", 0)
    assert gt.suggest_after_state("1B", "001", 2) == (2, "100", 1)     # a hit still scores the runner


def test_check_after_state():
    assert gt.check_after_state(1, "000", 0, 0) is not None            # outs went down
    assert gt.check_after_state(1, "000", 4, 0) is not None
    assert gt.check_after_state(0, "100", 0, 3) is not None            # 3 runs, 1 runner + batter
    assert gt.check_after_state(0, "111", 0, 4) is None                # grand slam
    assert gt.check_after_state(2, "001", 3, 0) is None


def _pa(seq, batter, ab, before, after, outs_after=0, runs=0, inning=2):
    return NS(pitch_sequence=seq, inning=inning, is_our_team_batting=True, batting_squad=None, our_player_id=batter,
              opponent_our_player_id=None, opponent_player_id=None, ends_plate_appearance=True, ab_outcome=ab,
              bases_before=before, bases_after=after, outs_after=outs_after, runs_scored_on_play=runs)


def _ev(after, frm, to, out=False, pid=None, n=0):
    return NS(pitch_sequence_after=after, from_base=frm, to_base=to, is_out=out, our_player_id=pid,
              opponent_player_id=None, created_at=n, runner_event_id=n)


def test_runners_on_base_follows_plays():
    ps = [_pa(1, 11, "1B", "000", "100"), _pa(2, 12, "BB", "100", "110"), _pa(3, 13, "FC", "110", "101", outs_after=1)]
    # walk pushes 11 to 2nd; on the FC the lead runner goes to 3rd and the batter is on 1st
    assert gt.runners_on_base(ps, []) == {3: ("our", 11), 1: ("our", 13)}
    # a steal moves the named runner; a caught stealing removes him
    assert gt.runners_on_base(ps, [_ev(3, 1, 2, n=1)]) == {3: ("our", 11), 2: ("our", 13)}
    assert gt.runners_on_base(ps, [_ev(3, 3, None, out=True, n=1)]) == {1: ("our", 13)}


def test_runners_on_base_scores_lead_runner_and_resets_each_half():
    ps = [_pa(1, 11, "2B", "000", "010"), _pa(2, 12, "1B", "010", "100", runs=1)]
    assert gt.runners_on_base(ps, []) == {1: ("our", 12)}
    ps.append(_pa(3, 13, "Groundout", "100", "000", outs_after=3))
    assert gt.runners_on_base(ps, []) == {}


def test_new_runner_causes():
    assert "Fielding Error" in gt.RUNNER_ADVANCE_TYPES and "Out on Bases" in gt.RUNNER_EVENT_OUT_TYPES
    assert not set(gt.RUNNER_ADVANCE_TYPES) & set(gt.RUNNER_EVENT_OUT_TYPES)
