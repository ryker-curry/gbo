"""Oct 31 2026: opponent lineup substitutions + restarts (Crowder 18-inning day)."""

from datetime import datetime
from types import SimpleNamespace as NS

from modules import game_tracking as gt


def _slot(order, pid, subs=()):
    return NS(opponent_lineup_slot_id=order, batting_order=order, opponent_player_id=pid, substitutions=list(subs))


def _sub(pid, seq, t=0):
    return NS(opponent_player_id=pid, pitch_sequence_at_entry=seq, created_at=datetime(2026, 10, 31, 12, t))


def _pa(seq, order, pid):
    return NS(pitch_sequence=seq, is_our_team_batting=False, ends_plate_appearance=True, ab_outcome="Groundout",
              opponent_batting_order=order, opponent_player_id=pid)


def _game(pitches, restarts=()):
    return NS(pitches=list(pitches), opponent_lineup_restarts=list(restarts))


SLOTS = [_slot(i, 100 + i) for i in range(1, 11)]   # 10-man order, player 101..110


def test_occupant_follows_latest_sub():
    s = _slot(2, 102, [_sub(202, 5), _sub(302, 9)])
    assert gt.get_current_opp_slot_occupant_id(s) == 302
    assert gt.get_current_opp_slot_occupant_id(_slot(3, 103)) == 103


def test_normal_order_continues():
    g = _game([_pa(1, 9, 109), _pa(2, 10, 110)])
    assert gt.suggest_next_opponent_order(g, SLOTS) == 1
    assert gt.suggest_next_opponent_lineup_player(g, SLOTS) == 101
    g = _game([_pa(1, 2, 102)])
    assert gt.suggest_next_opponent_lineup_player(g, SLOTS) == 103


def test_restart_goes_to_top():
    # They hit 3-6, then reset to the top.
    g = _game([_pa(1, 3, 103), _pa(2, 4, 104), _pa(3, 5, 105), _pa(4, 6, 106)],
              restarts=[NS(pitch_sequence_at_entry=4)])
    assert gt.suggest_next_opponent_order(g, SLOTS) == 1
    assert gt.suggest_next_opponent_lineup_player(g, SLOTS) == 101
    # After the #1 hitter bats, the order continues at #2.
    g.pitches.append(_pa(5, 1, 101))
    assert gt.suggest_next_opponent_order(g, SLOTS) == 2


def test_sub_shows_up_as_next_batter():
    slots = [_slot(i, 100 + i) for i in range(1, 11)]
    slots[1].substitutions.append(_sub(222, 4))   # new #2 hitter
    g = _game([_pa(4, 1, 101)])
    assert gt.suggest_next_opponent_lineup_player(g, slots) == 222
    # Picking the sub in the batter box suggests his spot (#2).
    assert gt.suggest_next_opponent_order(g, slots, batter_id=222) == 2


def test_no_lineup_saved_still_works():
    g = _game([_pa(1, 9, None)])
    assert gt.suggest_next_opponent_order(g, []) == 1
    assert gt.suggest_next_opponent_lineup_player(g, []) is None
    assert gt.suggest_next_opponent_order(_game([]), []) == 1
