"""
GBO — shared game-stats computation, used by both Analytics (coach-
facing) and My Stats (player-facing), so the logic lives in one place
rather than being duplicated and risking drift between the two.

Correctly attributes both sides of an intrasquad game to real player
profiles: a player's batting line includes pitches where they were
our_player_id while batting AND pitches where they were
opponent_our_player_id while the other side batted (intrasquad only)
-- easy to miss if only querying our_player_id, which is exactly the
gap flagged when intrasquad support was built.

This is a first, honest pass at counting stats + Run Value -- NOT the
full Baseball-Savant-style page (Whiff%/CSW%/Chase%/Putaway%/splits
etc. are still a deferred follow-up).
"""

from sqlalchemy.orm import joinedload
from models import GamePitch, Game


def get_batting_pitches(session, player_id, season_id=None):
    """Every pitch where this player was the one batting -- our side,
    or (intrasquad only) the opponent side."""
    query = (
        session.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type))
        .filter(
            ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.our_player_id == player_id))
            | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id == player_id))
        )
    )
    if season_id is not None:
        query = query.filter(Game.season_id == season_id)
    return query.all()


def get_pitching_pitches(session, player_id, season_id=None):
    """Every pitch where this player was the one pitching -- our side,
    or (intrasquad only) the opponent side."""
    query = (
        session.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type))
        .filter(
            ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == player_id))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == player_id))
        )
    )
    if season_id is not None:
        query = query.filter(Game.season_id == season_id)
    return query.all()


HIT_OUTCOMES = {"1B", "2B", "3B", "HR"}
NON_AB_OUTCOMES = {"BB", "HBP", "Sac Bunt", "Sac Fly"}


def compute_batting_line(pitches):
    pa_pitches = [p for p in pitches if p.ends_plate_appearance]
    pa = len(pa_pitches)
    bb = sum(1 for p in pa_pitches if p.ab_outcome == "BB")
    hbp = sum(1 for p in pa_pitches if p.ab_outcome == "HBP")
    sac = sum(1 for p in pa_pitches if p.ab_outcome in ("Sac Bunt", "Sac Fly"))
    ab = pa - bb - hbp - sac
    singles = sum(1 for p in pa_pitches if p.ab_outcome == "1B")
    doubles = sum(1 for p in pa_pitches if p.ab_outcome == "2B")
    triples = sum(1 for p in pa_pitches if p.ab_outcome == "3B")
    hr = sum(1 for p in pa_pitches if p.ab_outcome == "HR")
    hits = singles + doubles + triples + hr
    k = sum(1 for p in pa_pitches if p.ab_outcome == "K")
    rv_values = [float(p.run_value) for p in pitches if p.run_value is not None]
    return {
        "PA": pa, "AB": ab, "H": hits, "1B": singles, "2B": doubles, "3B": triples, "HR": hr,
        "BB": bb, "HBP": hbp, "K": k,
        "AVG": round(hits / ab, 3) if ab > 0 else None,
        "Total RV": round(sum(rv_values), 3) if rv_values else None,
        "Avg RV/PA": round(sum(rv_values) / len(rv_values), 3) if rv_values else None,
        "pitch_count": len(pitches),
    }


def compute_pitching_line(pitches):
    pa_pitches = [p for p in pitches if p.ends_plate_appearance]
    batters_faced = len(pa_pitches)
    k = sum(1 for p in pa_pitches if p.ab_outcome == "K")
    bb = sum(1 for p in pa_pitches if p.ab_outcome == "BB")
    hits_allowed = sum(1 for p in pa_pitches if p.ab_outcome in HIT_OUTCOMES)
    hr_allowed = sum(1 for p in pa_pitches if p.ab_outcome == "HR")
    runs_allowed = sum(p.runs_scored_on_play or 0 for p in pitches)
    exec_attempts = [p for p in pitches if p.intended_zone is not None and p.pitch_zone is not None]
    exec_hits = sum(1 for p in exec_attempts if p.intended_zone == p.pitch_zone)
    rv_values = [float(p.run_value) for p in pitches if p.run_value is not None]
    return {
        "Batters Faced": batters_faced, "Pitches": len(pitches), "K": k, "BB": bb,
        "H Allowed": hits_allowed, "HR Allowed": hr_allowed, "Runs Allowed": runs_allowed,
        "Execution %": round(100 * exec_hits / len(exec_attempts), 1) if exec_attempts else None,
        "Total RV Allowed": round(sum(rv_values), 3) if rv_values else None,
        "Avg RV Allowed/Pitch": round(sum(rv_values) / len(rv_values), 3) if rv_values else None,
    }