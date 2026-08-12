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

compute_pitch_type_breakdown() below is the Whiff%/CSW%/Chase%/
Putaway%/GB-FB-LD% rate-stat rollup per pitch type -- the same shape
as the per-pitch-type breakdown table in Ryker's own game-tracking
spreadsheet. Built entirely from GamePitch fields pages/game_tracking.py
already captures; no new data entry required. A handful of columns from
that spreadsheet are deliberately NOT reproduced here because their
definition isn't unambiguous from the raw data alone -- see that
function's docstring.
"""

from sqlalchemy.orm import joinedload
from models import GamePitch, Game
from plate_discipline import SWING_OUTCOMES, WHIFF_OUTCOMES
from strike_zone import is_in_zone


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


# "Strike" here follows the standard box-score/Baseball-Savant
# convention: every pitch that isn't a Ball or HBP counts as a strike
# thrown, including a foul with 2 strikes already (which doesn't
# advance the count but is still a "strike" in a pitch-count sense).
STRIKE_OUTCOMES = {"Called Strike", "Swinging Strike", "Foul", "In Play"}
BATTED_BALL_TYPES = ("Ground Ball", "Fly Ball", "Line Drive")

# Ryker's definition: a pitch the pitcher fully won -- a swing and
# miss, a called strike, or a foul ball (the hitter had to defend it).
DOMINANT_OUTCOMES = {"Swinging Strike", "Called Strike", "Foul"}


def _rate(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def compute_pitch_type_breakdown(pitches):
    """Per-pitch-type rate-stat rollup for a pitcher, matching the shape
    of the breakdown table in Ryker's own game-tracking spreadsheet
    (Pitch Usage%, Strike%, Whiff%, CSW%, Chase%, Putaway%, GB/FB/LD%,
    Dominance%, Ahead%, A3P%, Sword%, etc.) -- built from the same
    GamePitch fields pages/game_tracking.py already captures (Sword
    from its own new checkbox), no other new data entry required.
    Reuses plate_discipline.py's SWING_OUTCOMES/WHIFF_OUTCOMES and
    strike_zone.is_in_zone rather than redefining swing/whiff/zone
    logic a second time.

    Returns a list of row dicts, one per pitch type actually thrown
    (pitches with no pitch_type set are excluded from the per-type rows
    but still count toward "Total"), plus a final "Total" row across
    every pitch. Sorted by pitch count, most-thrown first.

    A3P ("ahead after 3 pitches") is inherently a plate-appearance-level
    fact, not a per-pitch one, so it's attributed to whichever pitch
    type was thrown as the PA's 3rd pitch -- same convention already
    used for hits/BB/K attributing to the pitch that ended the PA. See
    _compute_a3p_attribution() for exactly which PAs count and why.

    Still deliberately NOT included, because the raw data doesn't make
    their definition unambiguous:
      - The rest of the count-leverage cluster beyond Ahead/A3P --
        "Early", "E+A%", "Early Ball in Play" -- still needs a real
        definition from Ryker before guessing further.
      - "Execution Score" -- Ryker's sheet implies a per-pitch
        coach-graded score; GBO keeps its existing, different
        objective "Execution %" in compute_pitching_line()
        (intended-vs-actual zone match) instead, per Ryker's decision.
      - "IBB" as distinct from "BB" -- GamePitch.ab_outcome's
        documented vocabulary doesn't include a separate intentional-
        walk value, so it's counted under "BB".
    """
    total_all = len(pitches)

    by_type = {}
    for p in pitches:
        if p.pitch_type is not None:
            by_type.setdefault(p.pitch_type.type_name, []).append(p)

    a3p_attempts, a3p_ahead = _compute_a3p_attribution(pitches)

    rows = [
        _pitch_type_row(label, type_pitches, total_all, a3p_attempts.get(label, 0), a3p_ahead.get(label, 0))
        for label, type_pitches in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]
    rows.append(_pitch_type_row(
        "Total", pitches, total_all, sum(a3p_attempts.values()), sum(a3p_ahead.values()),
    ))
    return rows


def _group_into_plate_appearances(pitches):
    """Reconstruct plate appearances from a flat pitch list, using
    pitch_sequence order and the ends_plate_appearance boundary --
    GamePitch has no separate PA identifier. Pitches missing
    pitch_sequence (shouldn't happen for real data) are skipped rather
    than guessed into a PA. A trailing group with no
    ends_plate_appearance pitch (the PA currently in progress) is
    included too, since A3P only looks at pitches #3/#4 which may
    already both be in hand even if the PA hasn't concluded yet."""
    sortable = [p for p in pitches if getattr(p, "pitch_sequence", None) is not None]
    sortable.sort(key=lambda p: p.pitch_sequence)
    pas, current = [], []
    for p in sortable:
        current.append(p)
        if p.ends_plate_appearance:
            pas.append(current)
            current = []
    if current:
        pas.append(current)
    return pas


def _compute_a3p_attribution(pitches):
    """For each plate appearance, was the pitcher ahead in the count
    (strikes > balls) after exactly 3 pitches -- attributed to
    whichever pitch type was thrown as that PA's 3rd pitch.

    Only counts a PA when the answer is actually determinable from
    stored data:
      - The PA had a 4th pitch: that pitch's balls_before/strikes_before
        IS the count as it stood after exactly 3 pitches were thrown.
      - The PA ended in a strikeout on exactly the 3rd pitch: that's
        unambiguously "ahead" (2-3 strikes locked in the pitcher's favor).
    A PA that ended by its 3rd pitch via a walk, HBP, or ball in play
    has no clean "count after 3 pitches" (GamePitch stores counts
    *before* each pitch, not after) and is excluded rather than guessed.

    Returns (attempts_by_pitch_type_name, ahead_by_pitch_type_name).
    """
    attempts, ahead = {}, {}
    for pa in _group_into_plate_appearances(pitches):
        third = next((p for p in pa if p.pa_pitch_number == 3), None)
        if third is None or third.pitch_type is None:
            continue
        label = third.pitch_type.type_name
        fourth = next((p for p in pa if p.pa_pitch_number == 4), None)
        if fourth is not None and fourth.strikes_before is not None and fourth.balls_before is not None:
            is_ahead = fourth.strikes_before > fourth.balls_before
        elif third.ends_plate_appearance and third.ab_outcome == "K":
            is_ahead = True
        else:
            continue
        attempts[label] = attempts.get(label, 0) + 1
        if is_ahead:
            ahead[label] = ahead.get(label, 0) + 1
    return attempts, ahead


def _pitch_type_row(label, pitches, total_all_types, a3p_attempts=0, a3p_ahead=0):
    n = len(pitches)
    strikes = [p for p in pitches if p.pitch_outcome in STRIKE_OUTCOMES]
    balls = [p for p in pitches if p.pitch_outcome == "Ball"]
    called_strikes = [p for p in pitches if p.pitch_outcome == "Called Strike"]
    swings = [p for p in pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in pitches if p.pitch_outcome in WHIFF_OUTCOMES]
    dominant = [p for p in pitches if p.pitch_outcome in DOMINANT_OUTCOMES]
    ahead = [p for p in pitches if p.strikes_before is not None and p.balls_before is not None and p.strikes_before > p.balls_before]
    swords = [p for p in pitches if getattr(p, "is_sword", False)]

    located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
    in_zone = [p for p in located if is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    out_zone = [p for p in located if not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    zone_swings = [p for p in in_zone if p.pitch_outcome in SWING_OUTCOMES]
    zone_whiffs = [p for p in in_zone if p.pitch_outcome in WHIFF_OUTCOMES]
    chase_swings = [p for p in out_zone if p.pitch_outcome in SWING_OUTCOMES]

    first_pitches = [p for p in pitches if p.pa_pitch_number == 1]
    first_pitch_strikes = [p for p in first_pitches if p.pitch_outcome in STRIKE_OUTCOMES]

    two_strike_pitches = [p for p in pitches if p.strikes_before == 2]
    putaway_pitches = [p for p in two_strike_pitches if p.ends_plate_appearance and p.ab_outcome == "K"]

    balls_in_play = [p for p in pitches if p.pitch_outcome == "In Play"]
    batted_ball_counts = {
        bb_type: sum(1 for p in balls_in_play if p.batted_ball_type == bb_type)
        for bb_type in BATTED_BALL_TYPES
    }

    # Hits/BB/K/etc. attribute to whichever pitch type actually ended
    # the plate appearance -- the same convention a real box score uses
    # ("2 of his 5 Ks came on the slider").
    pa_ending = [p for p in pitches if p.ends_plate_appearance]
    bb = sum(1 for p in pa_ending if p.ab_outcome == "BB")
    hbp = sum(1 for p in pa_ending if p.ab_outcome == "HBP")
    sf = sum(1 for p in pa_ending if p.ab_outcome == "Sac Fly")
    sac = sum(1 for p in pa_ending if p.ab_outcome in ("Sac Bunt", "Sac Fly"))
    k = sum(1 for p in pa_ending if p.ab_outcome == "K")
    singles = sum(1 for p in pa_ending if p.ab_outcome == "1B")
    doubles = sum(1 for p in pa_ending if p.ab_outcome == "2B")
    triples = sum(1 for p in pa_ending if p.ab_outcome == "3B")
    hr = sum(1 for p in pa_ending if p.ab_outcome == "HR")
    hits = singles + doubles + triples + hr
    bf = len(pa_ending)
    ab = bf - bb - hbp - sac

    rv_values = [float(p.run_value) for p in pitches if p.run_value is not None]
    total_rv = sum(rv_values) if rv_values else None

    return {
        "Pitch Type": label,
        "Total Pitches": n,
        "Pitch Usage %": _rate(n, total_all_types),
        "Strikes": len(strikes), "Balls": len(balls), "Strike %": _rate(len(strikes), n),
        "C. Strike": len(called_strikes), "Called Strike %": _rate(len(called_strikes), n),
        "FPS": len(first_pitch_strikes), "First Pitch Thrown": len(first_pitches),
        "FPS %": _rate(len(first_pitch_strikes), len(first_pitches)),
        "Swing %": _rate(len(swings), n), "Total Swings": len(swings), "Zone Swings": len(zone_swings),
        "Whiffs": len(whiffs), "Whiff %": _rate(len(whiffs), len(swings)),
        "CSW %": _rate(len(called_strikes) + len(whiffs), n),
        "Zone Whiffs": len(zone_whiffs), "Zone Whiff %": _rate(len(zone_whiffs), len(zone_swings)),
        "Pitches Out of Zone": len(out_zone), "Chase": len(chase_swings), "Chase %": _rate(len(chase_swings), len(out_zone)),
        "Putaway Opportunities": len(two_strike_pitches), "Putaway Pitch": len(putaway_pitches),
        "Putaway %": _rate(len(putaway_pitches), len(two_strike_pitches)),
        "Dominant Pitches": len(dominant), "Dominance %": _rate(len(dominant), n),
        "Ahead Pitches": len(ahead), "Ahead %": _rate(len(ahead), n),
        "A3P Opportunities": a3p_attempts, "A3P": a3p_ahead, "A3P %": _rate(a3p_ahead, a3p_attempts),
        "Swords": len(swords), "Sword %": _rate(len(swords), len(swings)),
        "Balls in Play": len(balls_in_play),
        "GroundBalls": batted_ball_counts["Ground Ball"], "Ground Ball %": _rate(batted_ball_counts["Ground Ball"], len(balls_in_play)),
        "FlyBalls": batted_ball_counts["Fly Ball"], "Fly Ball %": _rate(batted_ball_counts["Fly Ball"], len(balls_in_play)),
        "LineDrives": batted_ball_counts["Line Drive"], "Line Drive %": _rate(batted_ball_counts["Line Drive"], len(balls_in_play)),
        "BB": bb, "HBP": hbp, "SF": sf, "K's": k,
        "Hits": hits, "1B": singles, "2B": doubles, "3B": triples, "HR": hr,
        "At Bats": ab, "BF": bf,
        "RV": round(total_rv, 3) if total_rv is not None else None,
        "RV/100": round(100 * total_rv / n, 3) if total_rv is not None and n else None,
    }