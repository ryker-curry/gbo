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
from field_location import classify_spray_direction


def get_batting_pitches(session, player_id, season_id=None, game_id=None):
    """Every pitch where this player was the one batting -- our side,
    or (intrasquad only) the opponent side. game_id narrows to a single
    game (for the single-game report); season_id narrows to a season
    (for the season-aggregate Analytics/My Stats views). The two are
    independent filters -- pass whichever one is relevant, or neither
    for all-time."""
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
    if game_id is not None:
        query = query.filter(GamePitch.game_id == game_id)
    return query.all()


def get_pitching_pitches(session, player_id, season_id=None, game_id=None):
    """Every pitch where this player was the one pitching -- our side,
    or (intrasquad only) the opponent side. game_id/season_id: see
    get_batting_pitches' docstring, same convention."""
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
    if game_id is not None:
        query = query.filter(GamePitch.game_id == game_id)
    return query.all()


HIT_OUTCOMES = {"1B", "2B", "3B", "HR"}
NON_AB_OUTCOMES = {"BB", "HBP", "Sac Bunt", "Sac Fly"}


def _has_risp(first_pitch_of_pa):
    """Runner in scoring position (2nd or 3rd) at the START of this PA
    -- same convention as _is_leadoff_pa: the situation is read off the
    PA's first pitch, not re-checked pitch-by-pitch, since a mid-PA
    stolen base changing the situation is rare and "RISP AVG" is
    conventionally credited based on the state when the PA began."""
    bases = first_pitch_of_pa.bases_before or "000"
    return len(bases) == 3 and (bases[1] == "1" or bases[2] == "1")


def _reached_two_strikes(pa):
    return any(p.strikes_before == 2 for p in pa)


def _batting_slice(completed_pas):
    """PA/AB/H/BB/HBP/K/1B-2B-3B-HR counts + AVG/OBP/SLG for a list of
    already-filtered completed PAs -- shared by the overall line and
    every situational split (RISP/2-Strike/Leadoff) below so the same
    counting logic isn't repeated per split."""
    pa = len(completed_pas)
    endings = [p[-1] for p in completed_pas]
    bb = sum(1 for p in endings if p.ab_outcome == "BB")
    hbp = sum(1 for p in endings if p.ab_outcome == "HBP")
    sf = sum(1 for p in endings if p.ab_outcome == "Sac Fly")
    sac = sum(1 for p in endings if p.ab_outcome in ("Sac Bunt", "Sac Fly"))
    ab = pa - bb - hbp - sac
    singles = sum(1 for p in endings if p.ab_outcome == "1B")
    doubles = sum(1 for p in endings if p.ab_outcome == "2B")
    triples = sum(1 for p in endings if p.ab_outcome == "3B")
    hr = sum(1 for p in endings if p.ab_outcome == "HR")
    hits = singles + doubles + triples + hr
    k = sum(1 for p in endings if p.ab_outcome == "K")
    total_bases = singles + 2 * doubles + 3 * triples + 4 * hr
    avg = round(hits / ab, 3) if ab else None
    obp = round((hits + bb + hbp) / (ab + bb + hbp + sf), 3) if (ab + bb + hbp + sf) else None
    slg = round(total_bases / ab, 3) if ab else None
    return {
        "PA": pa, "AB": ab, "H": hits, "1B": singles, "2B": doubles, "3B": triples, "HR": hr,
        "BB": bb, "HBP": hbp, "K": k, "SF": sf,
        "AVG": avg, "OBP": obp, "SLG": slg,
        "OPS": round(obp + slg, 3) if obp is not None and slg is not None else None,
        "ISO": round(slg - avg, 3) if slg is not None and avg is not None else None,
    }


def compute_batting_line(pitches):
    """The slash-line/box-score-style header line for a hitter -- same
    function for a single game (get_batting_pitches(..., game_id=)) or
    aggregated across a season/all-time, exactly like
    compute_pitching_line()'s equivalent split.

    wOBA uses the same generic, documented linear weights as the
    pitching-against side (WOBA_WEIGHTS above) -- not season/park-
    adjusted, a relative read within GBO's own games only.

    RISP/2-Strike/Leadoff are situational splits, each using
    _batting_slice() on a filtered subset of completed PAs:
      - RISP: a runner on 2nd or 3rd AT THE START of the PA (see
        _has_risp) -- the standard "AVG with runners in scoring
        position" convention.
      - 2-Strike: the PA reached a 2-strike count at ANY point (see
        _reached_two_strikes) -- how he performs once the pitcher's
        put him in a defensive count, mirroring the Putaway-side logic
        already used for pitchers.
      - Leadoff: the PA was the first batter of an inning (reuses
        _is_leadoff_pa, the same helper compute_pitching_line() uses
        from the pitcher's side of the exact same PAs)."""
    all_pas = _group_into_plate_appearances(pitches)
    completed_pas = [pa for pa in all_pas if pa[-1].ends_plate_appearance]

    base = _batting_slice(completed_pas)
    pa, ab, bb, hbp, sf = base["PA"], base["AB"], base["BB"], base["HBP"], base["SF"]
    singles, doubles, triples, hr = base["1B"], base["2B"], base["3B"], base["HR"]
    k = base["K"]

    woba_num = (
        WOBA_WEIGHTS["uBB"] * bb + WOBA_WEIGHTS["HBP"] * hbp + WOBA_WEIGHTS["1B"] * singles
        + WOBA_WEIGHTS["2B"] * doubles + WOBA_WEIGHTS["3B"] * triples + WOBA_WEIGHTS["HR"] * hr
    )
    woba_den = ab + bb + sf + hbp

    risp_pas = [p for p in completed_pas if _has_risp(p[0])]
    two_strike_pas = [p for p in completed_pas if _reached_two_strikes(p)]
    two_strike_k = sum(1 for p in two_strike_pas if p[-1].ab_outcome == "K")
    leadoff_pas = [p for p in completed_pas if _is_leadoff_pa(p[0])]

    rv_values = [float(p.run_value) for p in pitches if p.run_value is not None]

    return {
        "PA": pa, "AB": ab, "H": base["H"], "1B": singles, "2B": doubles, "3B": triples, "HR": hr,
        "BB": bb, "HBP": hbp, "K": k,
        "AVG": base["AVG"],
        "Total RV": round(sum(rv_values), 3) if rv_values else None,
        "Avg RV/PA": round(sum(rv_values) / len(rv_values), 3) if rv_values else None,
        "pitch_count": len(pitches),
        # Slash line & rate stats
        "OBP": base["OBP"], "SLG": base["SLG"], "OPS": base["OPS"], "ISO": base["ISO"],
        "wOBA": round(woba_num / woba_den, 3) if woba_den else None,
        "BB %": _rate(bb, pa), "K %": _rate(k, pa),
        "BB/K": round(bb / k, 2) if k else None,
        # Situational splits
        "RISP AVG": _batting_slice(risp_pas)["AVG"], "RISP OBP": _batting_slice(risp_pas)["OBP"],
        "RISP PA": len(risp_pas), "RISP AB": _batting_slice(risp_pas)["AB"],
        "2-Strike AVG": _batting_slice(two_strike_pas)["AVG"], "2-Strike PA": len(two_strike_pas),
        "2-Strike K %": _rate(two_strike_k, len(two_strike_pas)),
        "Leadoff AVG": _batting_slice(leadoff_pas)["AVG"], "Leadoff PA": len(leadoff_pas),
    }


def compute_batted_ball_profile(pitches, bats=None):
    """Batted-ball breakdown for a hitter's own balls in play (pitch_
    outcome == "In Play"): GB%/FB%/LD%/Pop-Up% (from batted_ball_type,
    already captured live -- see BATTED_BALL_TYPES above), Pull%/
    Center%/Oppo% (a genuinely new derived stat -- field_location.py's
    own docstring explains why this classification deliberately isn't
    computed/stored at entry time, and belongs here instead), and
    Barrel%/Hard-Contact% from the recorded contact_quality (no exit
    velocity in GBO, so this is the coach's own live "Barrel/Solid/
    Weak/Miss" call, not a measured Statcast Barrel).

    bats is the hitter's Player.bats ('R'/'L'/'S') -- pass None or 'S'
    (switch) to get side-neutral Left/Center/Right-Field % instead of
    batter-relative Pull/Center/Oppo, since GBO doesn't track which
    side a switch-hitter actually batted from on a given PA.
    """
    balls_in_play = [p for p in pitches if p.pitch_outcome == "In Play"]
    n = len(balls_in_play)

    type_counts = {
        bb_type: sum(1 for p in balls_in_play if p.batted_ball_type == bb_type)
        for bb_type in BATTED_BALL_TYPES
    }

    located = [p for p in balls_in_play if p.batted_ball_x is not None and p.batted_ball_y is not None]
    spray_counts = {"Pull": 0, "Center": 0, "Oppo": 0, "Left Field": 0, "Right Field": 0}
    for p in located:
        label = classify_spray_direction(float(p.batted_ball_x), float(p.batted_ball_y), bats)
        if label is not None:
            spray_counts[label] = spray_counts.get(label, 0) + 1
    use_side_neutral = bats not in ("R", "L")

    barrels = sum(1 for p in balls_in_play if p.contact_quality == "Barrel")
    solid = sum(1 for p in balls_in_play if p.contact_quality == "Solid")
    hard_contact = barrels + solid

    result = {
        "Balls in Play": n, "Located": len(located),
        "Ground Ball %": _rate(type_counts["Ground Ball"], n), "Fly Ball %": _rate(type_counts["Fly Ball"], n),
        "Line Drive %": _rate(type_counts["Line Drive"], n), "Pop Up %": _rate(type_counts["Pop Up"], n),
        "Barrel": barrels, "Barrel %": _rate(barrels, n),
        "Hard Contact": hard_contact, "Hard Contact %": _rate(hard_contact, n),
        "Spray Mode": "Left/Center/Right Field" if use_side_neutral else "Pull/Center/Oppo",
    }
    if use_side_neutral:
        result.update({
            "Left Field %": _rate(spray_counts["Left Field"], len(located)),
            "Center %": _rate(spray_counts["Center"], len(located)),
            "Right Field %": _rate(spray_counts["Right Field"], len(located)),
        })
    else:
        result.update({
            "Pull %": _rate(spray_counts["Pull"], len(located)),
            "Center %": _rate(spray_counts["Center"], len(located)),
            "Oppo %": _rate(spray_counts["Oppo"], len(located)),
        })
    return result


# Generic, commonly-cited linear weights for wOBA -- NOT season/park-
# adjusted for a specific year or league. Good enough for a relative
# read within one team's own games, not a claim of MLB-exact wOBA.
# IBB is always 0 in this formula -- GamePitch.ab_outcome has no
# separate intentional-walk value (see compute_pitch_type_breakdown's
# docstring), so every BB is treated as unintentional here too.
WOBA_WEIGHTS = {"uBB": 0.69, "HBP": 0.72, "1B": 0.89, "2B": 1.27, "3B": 1.62, "HR": 2.10}
# Commonly-cited recent-MLB-average constant -- swap for a real
# league-specific value once Ryker has one he trusts more.
FIP_CONSTANT = 3.10


def _innings_pitched(pa_pitches):
    """Outs recorded on this pitcher's own PA-ending pitches, converted
    to the X.Y innings-pitched display convention (Y = outs past the
    last full inning, 0-2, NOT a true decimal third). Each ending
    pitch's outs_after/outs_before is the real recorded delta for that
    specific play (0-3), stored before any inning-transition display
    normalization -- game_tracking.py's compute_current_state() does
    that normalization only for the live display, never on the stored
    row, so summing the raw deltas here is exact, not an approximation.
    Returns (display_string, decimal_value) -- decimal_value is the
    real fractional innings (outs/3), used for rate stats (ERA, WHIP,
    K/9) where X.Y would silently be wrong (X.2 innings is NOT X + 0.2
    innings)."""
    total_outs = sum(
        (p.outs_after - p.outs_before) for p in pa_pitches
        if p.outs_after is not None and p.outs_before is not None
    )
    whole, partial = divmod(total_outs, 3)
    return f"{whole}.{partial}", whole + partial / 3.0


def _is_leadoff_pa(pa_pitches_for_this_pa_first_pitch):
    p = pa_pitches_for_this_pa_first_pitch
    return p.pa_pitch_number == 1 and p.outs_before == 0 and (p.bases_before or "000") == "000"


def compute_pitching_line(pitches):
    """The box-score-style header line for a pitcher -- either for a
    single game (pass pitches from get_pitching_pitches(..., game_id=))
    or aggregated across a season/all-time, same function either way.

    Early/Ahead here use Ryker's exact per-plate-appearance definitions
    (confirmed directly with him, see compute_pitch_type_breakdown's
    docstring for the full explanation) -- NOT the looser "Ahead
    Pitches" per-pitch-thrown count in the pitch-type breakdown table,
    which predates this and is a coarser proxy. E+A% here is the real
    stat Ryker described: (Early PAs + Ahead PAs) / Batters Faced.

    ER is NOT distinguished from total runs allowed -- GBO has no
    earned/unearned run model (no formal error-attribution), so "ERA"
    here is really runs-allowed average. FIP and wOBA use generic,
    documented linear-weight constants, not a season/league-specific
    set. See this module's WOBA_WEIGHTS/FIP_CONSTANT for exactly what's
    used and why."""
    pa_pitches = [p for p in pitches if p.ends_plate_appearance]
    batters_faced = len(pa_pitches)
    k = sum(1 for p in pa_pitches if p.ab_outcome == "K")
    bb = sum(1 for p in pa_pitches if p.ab_outcome == "BB")
    hbp = sum(1 for p in pa_pitches if p.ab_outcome == "HBP")
    hits_allowed = sum(1 for p in pa_pitches if p.ab_outcome in HIT_OUTCOMES)
    hr_allowed = sum(1 for p in pa_pitches if p.ab_outcome == "HR")
    xbh_allowed = sum(1 for p in pa_pitches if p.ab_outcome in ("2B", "3B", "HR"))
    runs_allowed = sum(p.runs_scored_on_play or 0 for p in pitches)
    sac = sum(1 for p in pa_pitches if p.ab_outcome in ("Sac Bunt", "Sac Fly"))
    sf = sum(1 for p in pa_pitches if p.ab_outcome == "Sac Fly")
    ab = batters_faced - bb - hbp - sac

    exec_attempts = [p for p in pitches if p.intended_zone is not None and p.pitch_zone is not None]
    exec_hits = sum(1 for p in exec_attempts if p.intended_zone == p.pitch_zone)
    rv_values = [float(p.run_value) for p in pitches if p.run_value is not None]

    strikes = sum(1 for p in pitches if p.pitch_outcome in STRIKE_OUTCOMES)
    balls_thrown = sum(1 for p in pitches if p.pitch_outcome == "Ball")
    ip_display, ip_decimal = _innings_pitched(pa_pitches)

    # PA groups, needed for Early/Ahead/Leadoff/situational-count stats
    # below -- reconstructed the same way compute_pitch_type_breakdown
    # does (see _group_into_plate_appearances), since this function
    # doesn't currently receive pre-grouped PAs.
    all_pas = _group_into_plate_appearances(pitches)
    completed_pas = [pa for pa in all_pas if pa[-1].ends_plate_appearance]

    early_pas = 0
    ahead_pas = 0
    for pa in completed_pas:
        last = pa[-1]
        is_early = last.pitch_outcome == "In Play" and (last.balls_before, last.strikes_before) in {(0, 0), (1, 0), (0, 1), (1, 1)}
        is_ahead = any((p.balls_before, p.strikes_before) in {(0, 2), (1, 2)} for p in pa)
        if is_early:
            early_pas += 1
        elif is_ahead:
            ahead_pas += 1

    leadoff_pas = [pa for pa in completed_pas if _is_leadoff_pa(pa[0])]
    leadoff_outs = sum(1 for pa in leadoff_pas if pa[-1].ab_outcome in ("K", "Groundout", "Flyout", "Lineout", "Double Play", "Sac Bunt", "Sac Fly"))
    leadoff_bb = sum(1 for pa in leadoff_pas if pa[-1].ab_outcome == "BB")
    two_out_bb = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "BB" and pa[-1].outs_before == 2)
    zero_two_hits = sum(1 for pa in completed_pas if pa[-1].ab_outcome in HIT_OUTCOMES and pa[-1].balls_before == 0 and pa[-1].strikes_before == 2)
    zero_two_barrel = sum(1 for pa in completed_pas if pa[-1].contact_quality == "Barrel" and pa[-1].balls_before == 0 and pa[-1].strikes_before == 2)
    one_two_barrel = sum(1 for pa in completed_pas if pa[-1].contact_quality == "Barrel" and pa[-1].balls_before == 1 and pa[-1].strikes_before == 2)

    singles = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "1B")
    doubles = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "2B")
    triples = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "3B")
    woba_num = (
        WOBA_WEIGHTS["uBB"] * bb + WOBA_WEIGHTS["HBP"] * hbp + WOBA_WEIGHTS["1B"] * singles
        + WOBA_WEIGHTS["2B"] * doubles + WOBA_WEIGHTS["3B"] * triples + WOBA_WEIGHTS["HR"] * hr_allowed
    )
    woba_den = ab + bb + sf + hbp

    return {
        "Batters Faced": batters_faced, "Pitches": len(pitches), "K": k, "BB": bb,
        "H Allowed": hits_allowed, "HR Allowed": hr_allowed, "Runs Allowed": runs_allowed,
        "Execution %": round(100 * exec_hits / len(exec_attempts), 1) if exec_attempts else None,
        "Total RV Allowed": round(sum(rv_values), 3) if rv_values else None,
        "Avg RV Allowed/Pitch": round(sum(rv_values) / len(rv_values), 3) if rv_values else None,
        # New box-score-style stats, added to match Ryker's Game Stat Sheet:
        "IP": ip_display, "IP (decimal)": round(ip_decimal, 3),
        "Strikes": strikes, "Strike %": _rate(strikes, len(pitches)),
        "Balls": balls_thrown, "Ball %": _rate(balls_thrown, len(pitches)),
        "Pitches/Inning": round(len(pitches) / ip_decimal, 1) if ip_decimal else None,
        "AB": ab, "Hits": hits_allowed, "HBP": hbp, "XBH": xbh_allowed,
        "WHIP": round((bb + hits_allowed) / ip_decimal, 2) if ip_decimal else None,
        "K/BB": round(k / bb, 2) if bb else None,
        "K %": _rate(k, batters_faced), "K/9": round(k * 9 / ip_decimal, 2) if ip_decimal else None,
        "ERA (runs-allowed avg -- ER not tracked)": round(runs_allowed * 9 / ip_decimal, 2) if ip_decimal else None,
        "FIP": round((13 * hr_allowed + 3 * (bb + hbp) - 2 * k) / ip_decimal + FIP_CONSTANT, 2) if ip_decimal else None,
        "OBA (opponent AVG)": round(hits_allowed / ab, 3) if ab else None,
        "wOBA": round(woba_num / woba_den, 3) if woba_den else None,
        "Leadoff PAs": len(leadoff_pas), "Leadoff Outs": leadoff_outs,
        "Leadoff Out %": _rate(leadoff_outs, len(leadoff_pas)),
        "Leadoff BB": leadoff_bb, "2 Out BB": two_out_bb,
        "0-2 Hits": zero_two_hits, "0-2 Barrel": zero_two_barrel, "1-2 Barrel": one_two_barrel,
        "Early": early_pas, "Ahead (PA)": ahead_pas,
        "E+A %": _rate(early_pas + ahead_pas, batters_faced),
    }


# "Strike" here follows the standard box-score/Baseball-Savant
# convention: every pitch that isn't a Ball or HBP counts as a strike
# thrown, including a foul with 2 strikes already (which doesn't
# advance the count but is still a "strike" in a pitch-count sense).
STRIKE_OUTCOMES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
# Fixed to include Pop Up -- previously missing here (GamePitch.batted_ball_type
# has always allowed "Pop Up", see game_tracking.py, but this tuple only had
# the other three, so pop-ups were silently excluded from every GB/FB/LD %
# computed from it, on both the pitching and hitting sides).
BATTED_BALL_TYPES = ("Ground Ball", "Fly Ball", "Line Drive", "Pop Up")

# Ryker's definition: a pitch the pitcher fully won -- a swing and
# miss, a called strike, or a foul ball (the hitter had to defend it).
DOMINANT_OUTCOMES = {"Swing and Miss", "Called Strike", "Foul"}


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

    A3P ("ahead after 3 pitches") and Early/Ahead are all inherently
    plate-appearance-level facts, not per-pitch ones, so each is
    attributed to whichever pitch type was thrown as the relevant pitch
    of that PA (A3P -> the PA's 3rd pitch, Early/Ahead -> the PA's
    final/ending pitch) -- same convention already used for hits/BB/K
    attributing to the pitch that ended the PA. See
    _compute_a3p_attribution() and _compute_early_ahead_attribution()
    for exactly which PAs count and why.

    Early/Ahead here use Ryker's exact definitions, confirmed directly
    with him (previously this table used a looser "strikes_before >
    balls_before, per pitch thrown" proxy for "Ahead" -- that's been
    replaced, since it counted a different, coarser thing than what
    Ryker actually meant):
      - Early: the PA ended in a ball in play (pitch_outcome ==
        "In Play" on the PA's final pitch) with the count AT THAT PITCH
        being 0-0, 1-0, 0-1, or 1-1 -- contact within the first 3
        pitches at a count that hasn't gone 2-0. The eventual result
        (hit, out, error) doesn't change the credit.
      - Ahead: the PA reaches an 0-2 or 1-2 count AT ANY POINT (checked
        across every pitch in the PA, not just the last one). At most
        one Ahead credit per PA. By construction this can never also be
        Early (Early's four counts don't include 0-2/1-2) -- every
        completed PA is Early, Ahead, or neither, never both, matching
        Ryker's "only one outcome counted per batter" rule.
      - E+A % = (Early + Ahead) / Batters Faced -- see
        compute_pitching_line() for the game-level version of this same
        stat; this table's version is the same PAs, broken out by which
        pitch type ended each one.

    Still deliberately NOT included, because the raw data doesn't make
    their definition unambiguous:
      - "Execution Score" -- Ryker's sheet implies a per-pitch score;
        confirmed with him this IS an intended-vs-actual zone match,
        matching GBO's existing "Execution %" in compute_pitching_line()
        exactly -- see this table's own "Execution %" column, which now
        reuses that same logic per pitch type.
      - "IBB" as distinct from "BB" -- GamePitch.ab_outcome's
        documented vocabulary doesn't include a separate intentional-
        walk value, so it's counted under "BB".
      - "2 Out BB Score" / "Leadoff BB Score" (did that SPECIFIC walked
        runner later score) -- GBO's bases_before/bases_after model
        tracks base occupancy, not runner identity, so there's no way
        to trace one particular runner through the rest of the inning
        without a real schema change. Only the raw counts are available
        (compute_pitching_line()'s "Leadoff BB" / "2 Out BB").
    """
    total_all = len(pitches)

    by_type = {}
    for p in pitches:
        if p.pitch_type is not None:
            by_type.setdefault(p.pitch_type.type_name, []).append(p)

    a3p_attempts, a3p_ahead = _compute_a3p_attribution(pitches)
    early_by_type, ahead_by_type, bf_by_type = _compute_early_ahead_attribution(pitches)

    rows = [
        _pitch_type_row(
            label, type_pitches, total_all, a3p_attempts.get(label, 0), a3p_ahead.get(label, 0),
            early_by_type.get(label, 0), ahead_by_type.get(label, 0), bf_by_type.get(label, 0),
        )
        for label, type_pitches in sorted(by_type.items(), key=lambda kv: -len(kv[1]))
    ]
    rows.append(_pitch_type_row(
        "Total", pitches, total_all, sum(a3p_attempts.values()), sum(a3p_ahead.values()),
        sum(early_by_type.values()), sum(ahead_by_type.values()), sum(bf_by_type.values()),
    ))
    return rows


def _compute_early_ahead_attribution(pitches):
    """Early/Ahead PA counts (see compute_pitch_type_breakdown's
    docstring for the exact definitions), attributed to whichever pitch
    type ended each plate appearance. Also returns batters-faced per
    pitch type (the denominator for E+A %), since it's the same PA
    grouping work -- no need to recompute it separately."""
    early, ahead, bf = {}, {}, {}
    for pa in _group_into_plate_appearances(pitches):
        last = pa[-1]
        if not last.ends_plate_appearance or last.pitch_type is None:
            continue
        label = last.pitch_type.type_name
        bf[label] = bf.get(label, 0) + 1
        is_early = last.pitch_outcome == "In Play" and (last.balls_before, last.strikes_before) in {(0, 0), (1, 0), (0, 1), (1, 1)}
        is_ahead = any((p.balls_before, p.strikes_before) in {(0, 2), (1, 2)} for p in pa)
        if is_early:
            early[label] = early.get(label, 0) + 1
        elif is_ahead:
            ahead[label] = ahead.get(label, 0) + 1
    return early, ahead, bf


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


def _pitch_type_row(label, pitches, total_all_types, a3p_attempts=0, a3p_ahead=0, early_pas=0, ahead_pas=0, bf_for_early=0):
    n = len(pitches)
    strikes = [p for p in pitches if p.pitch_outcome in STRIKE_OUTCOMES]
    balls = [p for p in pitches if p.pitch_outcome == "Ball"]
    called_strikes = [p for p in pitches if p.pitch_outcome == "Called Strike"]
    swings = [p for p in pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in pitches if p.pitch_outcome in WHIFF_OUTCOMES]
    dominant = [p for p in pitches if p.pitch_outcome in DOMINANT_OUTCOMES]
    swords = [p for p in pitches if getattr(p, "is_sword", False)]

    # Execution %: intended-vs-actual zone match, same logic as
    # compute_pitching_line()'s game-level version, just scoped to this
    # pitch type -- confirmed with Ryker this IS what "Execution Score"
    # means in his sheet (see compute_pitch_type_breakdown's docstring).
    exec_attempts = [p for p in pitches if p.intended_zone is not None and p.pitch_zone is not None]
    exec_hits = sum(1 for p in exec_attempts if p.intended_zone == p.pitch_zone)

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
        "Early": early_pas, "Ahead": ahead_pas, "E+A %": _rate(early_pas + ahead_pas, bf_for_early),
        "A3P Opportunities": a3p_attempts, "A3P": a3p_ahead, "A3P %": _rate(a3p_ahead, a3p_attempts),
        "Swords": len(swords), "Sword %": _rate(len(swords), len(swings)),
        "Execution": exec_hits, "Execution Reviewed": len(exec_attempts), "Execution %": _rate(exec_hits, len(exec_attempts)),
        "Balls in Play": len(balls_in_play),
        "GroundBalls": batted_ball_counts["Ground Ball"], "Ground Ball %": _rate(batted_ball_counts["Ground Ball"], len(balls_in_play)),
        "FlyBalls": batted_ball_counts["Fly Ball"], "Fly Ball %": _rate(batted_ball_counts["Fly Ball"], len(balls_in_play)),
        "LineDrives": batted_ball_counts["Line Drive"], "Line Drive %": _rate(batted_ball_counts["Line Drive"], len(balls_in_play)),
        "PopUps": batted_ball_counts["Pop Up"], "Pop Up %": _rate(batted_ball_counts["Pop Up"], len(balls_in_play)),
        "BB": bb, "HBP": hbp, "SF": sf, "K's": k,
        "Hits": hits, "1B": singles, "2B": doubles, "3B": triples, "HR": hr,
        "At Bats": ab, "BF": bf,
        "RV": round(total_rv, 3) if total_rv is not None else None,
        "RV/100": round(100 * total_rv / n, 3) if total_rv is not None and n else None,
    }