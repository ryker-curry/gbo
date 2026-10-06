"""Hitter Game Report at-bat by at-bat (Oct 2026): location wording."""

from modules.hitter_game_report import location_words


def test_location_words():
    assert location_words(0.0, 2.5, "R") == "In zone -- middle-middle"
    assert location_words(-0.6, 3.3, "R") == "In zone -- up and in"        # RHB stands on the 3B (negative) side
    assert location_words(-0.6, 3.3, "L") == "In zone -- up and away"
    assert location_words(1.3, 1.0, "R").startswith("Ball -- down and away")
    assert location_words(0.6, 2.5, None) == "In zone -- 1B side"
    assert location_words(None, 2.5, "R") == "Not located"


def test_pitcher_of_intrasquad_sides(db):
    """Squad B batting (is_our_team_batting False): pitcher is our_player_id, not the batter."""
    from types import SimpleNamespace
    from models import Player
    from modules.hitter_game_report import _pitcher_of
    pitcher = db.query(Player).filter(Player.is_pitcher.is_(True)).first()
    batter = db.query(Player).filter(Player.is_pitcher.is_(False)).first()
    p = SimpleNamespace(is_our_team_batting=False, our_player_id=pitcher.player_id,
                        opponent_our_player_id=batter.player_id, opponent_player_id=None, opponent_hand=None)
    assert _pitcher_of(db, p) == (f"{pitcher.first_name} {pitcher.last_name}", pitcher.throws)
    p2 = SimpleNamespace(is_our_team_batting=True, our_player_id=batter.player_id,
                         opponent_our_player_id=pitcher.player_id, opponent_player_id=None, opponent_hand=None)
    assert _pitcher_of(db, p2)[0] == f"{pitcher.first_name} {pitcher.last_name}"
