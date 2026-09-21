"""
GBO — Single-Game Pitcher Analytics Report.

Built to replace Ryker's Google Sheets "Game Pitch Tracking Sheet" /
"Game Stat Sheet" -- every stat here was matched against the exact
column list in those two sheets, using Ryker's own definitions where
the sheet's column names weren't self-explanatory (Early/Ahead/A3P/
Dominant Pitch, confirmed directly with him). See the per-stat
docstrings below for exactly how each one is computed.

Scope, deliberately NOT built here (flagged to Ryker, not silently
approximated):
  - SBA (stolen bases allowed) -- not tracked anywhere in GBO yet.
  - "2 Out BB Score" / "Leadoff BB Score" (did THAT SPECIFIC walked
    runner later score) -- GBO's bases_before/bases_after model tracks
    base OCCUPANCY, not runner IDENTITY, so there's no way to trace one
    particular runner through the rest of the inning without a real
    schema change. Only the raw counts (2 Out BB, Leadoff BB) are
    computed here.
  - IBB (intentional walk) as distinct from a regular BB -- GBO's
    AB_OUTCOMES list (game_tracking.py) has no separate IBB value, so
    IBB is always reported as 0 here. Every BB is treated as
    unintentional for wOBA purposes.

Known approximations (clearly flagged, not silently guessed):
  - ER = R (total runs allowed). GBO has no earned/unearned run
    distinction (no formal error-attribution model), so ERA here is
    really "runs-allowed average," not true ERA. Labeled as such
    everywhere it's shown.
  - wOBA weights and the FIP constant are generic, commonly-cited
    linear-weight values (see the constants below), NOT recalculated
    for a specific season/league. Good enough for a relative read
    within one team's own games; not a claim of MLB-exact wOBA.

Zone-dependent stats (Zone Swings, Whiffs vs. Zone Whiffs, Chase%,
Zone Whiff%, Execution Score/%) all depend on actual_plate_x/z, which
per Ryker's call is no longer captured live -- it's filled in later via
Game Tracking's Video Review section. Any of this report run before
Video Review is done for a game will correctly show those specific
numbers as unavailable (None), not zero -- zero would incorrectly
imply "reviewed and found bad," when the truth is "not reviewed yet."
"""

from models import GamePitch, PitchType, Player, Game
import strike_zone
from pitch_type_config import FASTBALL_TYPES

# Pitch outcomes that reach the batter and get a swing/take decision --
# used throughout to distinguish "a pitch was thrown" (all rows) from
# "a pitch that was actually contested" for swing-rate-style stats.
STRIKE_OUTCOMES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
SWING_OUTCOMES = {"Swing and Miss", "Foul", "In Play"}
CSW_OUTCOMES = {"Called Strike", "Swing and Miss"}  # the industry-standard CSW% definition -- no fouls
DOMINANT_OUTCOMES = {"Called Strike", "Swing and Miss", "Foul"}  # Ryker's own Dominant Pitch definition -- includes fouls, see module docstring
# Both count as a strikeout everywhere below -- "K (Looking)" is a
# separate AB_OUTCOMES value (game_tracking.py) purely so a strikeout
# looking shows as its own result on the sheet; it's still a K/out for
# every stat here.
K_OUTCOMES = {"K", "K (Looking)"}
OUT_AB_OUTCOMES = {"Groundout", "Flyout", "Lineout", "Double Play", "Sac Bunt", "Sac Fly"} | K_OUTCOMES
HIT_AB_OUTCOMES = {"1B", "2B", "3B", "HR"}
XBH_AB_OUTCOMES = {"2B", "3B", "HR"}
NON_AB_OUTCOMES = {"BB", "HBP", "Sac Bunt", "Sac Fly"}  # excluded from the standard AB count, per the official scoring rule

# Generic, commonly-cited linear weights -- NOT season/park-adjusted.
# See module docstring. Kept as named constants (not inline magic
# numbers) so they're easy to find and swap out later if Ryker gets a
# real season-specific set from a source he trusts more.
WOBA_WEIGHTS = {"uBB": 0.69, "HBP": 0.72, "1B": 0.89, "2B": 1.27, "3B": 1.62, "HR": 2.10}
FIP_CONSTANT = 3.10  # commonly-cited recent-MLB-average value -- swap for your league's real constant once known

# Staff-totals goal thresholds (Ryker, Sept 2026) -- see
# compute_staff_game_totals below. Only these two of the five staff-
# totals stats have a goal at all right now.
FPS_GOAL_PCT = 62.0
SECONDARY_STRIKE_GOAL_PCT = 58.0


def _outs_from_string(bases_str):
    return bases_str.count("1") if bases_str else 0


def _is_leadoff_pitch(p):
    """The FIRST pitch of a PA (pa_pitch_number == 1) that started with
    nobody on and nobody out -- i.e. this PA is the leadoff PA of a
    half-inning. Checked on pa_pitch_number == 1 rows only; every other
    pitch in that same PA inherits the same leadoff-ness (see
    _pa_is_leadoff below, which looks this up once per PA)."""
    return p.pa_pitch_number == 1 and p.outs_before == 0 and (p.bases_before or "000") == "000"


def _pitcher_id(p):
    """The real pitcher on this pitch, regardless of which side of the
    is_our_team_batting split recorded it. our_player_id IS the pitcher
    on an ordinary (is_our_team_batting False) row -- but for an
    intrasquad game's OTHER squad's pitching (is_our_team_batting True
    -- one of our own players batting against another of our own
    roster pitching), the real pitcher is opponent_our_player_id
    instead (see models.GamePitch's docstring). Needed anywhere a
    report has to find "who pitched this" without knowing in advance
    which side of an intrasquad game recorded the row (Ryker, Sept
    2026: reports were silently missing whichever squad's pitching got
    recorded as the "opponent" side -- see compute_pitcher_game_report
    and compute_staff_game_totals below, both fixed to use this)."""
    return p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id


def _batter_hand(p, players_by_id):
    """The batter's handedness on this pitch, regardless of which side
    recorded it. On an ordinary (is_our_team_batting False) row,
    opponent_hand already holds the batter's hand directly. On an
    intrasquad game's OTHER squad's pitching (is_our_team_batting
    True), our_player_id is the real batter (one of our own roster)
    and opponent_hand instead holds the PITCHER's hand -- so the
    batter's hand has to come from their own Player.bats instead.
    players_by_id: {player_id: Player}, pre-loaded by the caller."""
    if p.is_our_team_batting:
        batter = players_by_id.get(p.our_player_id)
        return batter.bats if batter else None
    return p.opponent_hand


def compute_pitcher_game_report(session, game_id, pitcher_player_id):
    """The full report for one pitcher, one game: header stats + a
    pitch-type breakdown split three ways (Overall / vs RHH / vs LHH).
    Returns None if this pitcher has no recorded pitches in this game.

    All pitches attributed to this pitcher = GamePitch rows in this
    game where this pitcher was the one actually throwing -- normally
    that means is_our_team_batting is False and our_player_id matches
    (our_player_id IS the pitcher, not the batter, on those rows --
    see models.py's GamePitch docstring). For an INTRASQUAD game,
    though, this pitcher might instead have faced our own lineup as
    the "other squad" on some pitches (is_our_team_batting True,
    opponent_our_player_id is the real pitcher there -- see
    _pitcher_id) -- every intrasquad pitcher's real outing can include
    both directions, so both get checked (Ryker, Sept 2026: "for
    intrasquads coach needs to be able to see both teams" -- this was
    silently dropping whichever squad's pitching landed on the
    "batting" side of the split). This is exact, not a heuristic --
    Game Tracking already records who was actually pitching on every
    single pitch (including mid-game pitching changes and, for
    intrasquad games, the free-picked opposing pitcher), not just who
    started."""
    game = session.query(Game).filter(Game.game_id == game_id).first()
    if game is not None and game.is_intrasquad:
        all_pitches = [
            p for p in session.query(GamePitch).filter(GamePitch.game_id == game_id).order_by(GamePitch.pitch_sequence).all()
            if _pitcher_id(p) == pitcher_player_id
        ]
    else:
        all_pitches = (
            session.query(GamePitch)
            .filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == pitcher_player_id)
            .order_by(GamePitch.pitch_sequence)
            .all()
        )
    if not all_pitches:
        return None

    pitch_types = {pt.pitch_type_id: pt.type_name for pt in session.query(PitchType).all()}
    # Only needed for _batter_hand's intrasquad-batting-side lookup --
    # harmless (and just as cheap) to build unconditionally.
    players_by_id = {pl.player_id: pl for pl in session.query(Player).filter(Player.player_id.in_({p.our_player_id for p in all_pitches})).all()}

    # Group into PAs (pa_pitch_number resets to 1 at the start of each
    # PA) so PA-level stats (Early/Ahead/A3P/Leadoff/AB-outcome-based
    # counts) are computed once per PA, not once per pitch.
    pas = []
    current_pa = []
    for p in all_pitches:
        if p.pa_pitch_number == 1 and current_pa:
            pas.append(current_pa)
            current_pa = []
        current_pa.append(p)
    if current_pa:
        pas.append(current_pa)
    # Only fully-ended PAs count toward PA-level stats -- a PA still in
    # progress (e.g. report pulled mid-at-bat) has no ab_outcome yet.
    completed_pas = [pa for pa in pas if pa[-1].ends_plate_appearance]

    header = _compute_header_stats(all_pitches, completed_pas)
    breakdown_overall = _compute_pitch_type_breakdown(all_pitches, completed_pas, pitch_types)
    breakdown_rhh = _compute_pitch_type_breakdown(
        [p for p in all_pitches if _batter_hand(p, players_by_id) == "R"],
        [pa for pa in completed_pas if _batter_hand(pa[0], players_by_id) == "R"],
        pitch_types,
    )
    breakdown_lhh = _compute_pitch_type_breakdown(
        [p for p in all_pitches if _batter_hand(p, players_by_id) == "L"],
        [pa for pa in completed_pas if _batter_hand(pa[0], players_by_id) == "L"],
        pitch_types,
    )

    return {
        "header": header,
        "breakdown_overall": breakdown_overall,
        "breakdown_vs_rhh": breakdown_rhh,
        "breakdown_vs_lhh": breakdown_lhh,
    }


def _compute_header_stats(all_pitches, completed_pas):
    total_pitches = len(all_pitches)
    strikes = sum(1 for p in all_pitches if p.pitch_outcome in STRIKE_OUTCOMES)
    balls = sum(1 for p in all_pitches if p.pitch_outcome == "Ball")

    # IP: outs recorded on THIS pitcher's own PA-ending pitches. Each
    # ending pitch's outs_after/outs_before is the real recorded delta
    # for that specific play (0-3), stored BEFORE any inning-transition
    # display normalization -- see compute_current_state in
    # game_tracking.py, which does that normalization only for display,
    # never on the stored row. Summing the raw deltas is exact.
    total_outs = sum(
        (pa[-1].outs_after - pa[-1].outs_before) for pa in completed_pas
        if pa[-1].outs_after is not None and pa[-1].outs_before is not None
    )
    ip_whole = total_outs // 3
    ip_partial = total_outs % 3
    ip_display = f"{ip_whole}.{ip_partial}"
    ip_decimal = ip_whole + ip_partial / 3.0  # for rate stats (ERA, WHIP, K/9) -- the real fractional innings, not the X.Y display convention

    ab = sum(1 for pa in completed_pas if pa[-1].ab_outcome not in NON_AB_OUTCOMES)
    bf = len(completed_pas)
    hits = sum(1 for pa in completed_pas if pa[-1].ab_outcome in HIT_AB_OUTCOMES)
    xbh = sum(1 for pa in completed_pas if pa[-1].ab_outcome in XBH_AB_OUTCOMES)
    bb = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "BB")
    hbp = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "HBP")
    ks = sum(1 for pa in completed_pas if pa[-1].ab_outcome in K_OUTCOMES)
    runs = sum((pa[-1].runs_scored_on_play or 0) for pa in completed_pas)

    leadoff_pas = [pa for pa in completed_pas if _is_leadoff_pitch(pa[0])]
    leadoff_outs = sum(1 for pa in leadoff_pas if pa[-1].ab_outcome in OUT_AB_OUTCOMES)
    leadoff_bb = sum(1 for pa in leadoff_pas if pa[-1].ab_outcome == "BB")

    two_out_bb = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "BB" and pa[-1].outs_before == 2)

    # "0-2 Hits" / "X-2 Barrel": contact quality/result specifically at
    # an 0-2 or 1-2 count -- the count on the PA's OWN final pitch (the
    # one that ended it), not any earlier pitch in the PA.
    zero_two_hits = sum(1 for pa in completed_pas if pa[-1].ab_outcome in HIT_AB_OUTCOMES and pa[-1].balls_before == 0 and pa[-1].strikes_before == 2)
    zero_two_barrel = sum(1 for pa in completed_pas if pa[-1].contact_quality == "Barreled/Squared Up" and pa[-1].balls_before == 0 and pa[-1].strikes_before == 2)
    one_two_barrel = sum(1 for pa in completed_pas if pa[-1].contact_quality == "Barreled/Squared Up" and pa[-1].balls_before == 1 and pa[-1].strikes_before == 2)

    early_count, ahead_count, a3p_yes = _compute_early_ahead_a3p(completed_pas)

    execution_hits, execution_total = _compute_execution(all_pitches)

    whip = round((bb + hits) / ip_decimal, 2) if ip_decimal else None
    k_bb = round(ks / bb, 2) if bb else None
    k_pct = round(ks / bf * 100, 1) if bf else None
    era = round(runs * 9 / ip_decimal, 2) if ip_decimal else None  # "ERA" = runs-allowed average, ER not distinguished from R -- see module docstring
    fip = round((13 * sum(1 for pa in completed_pas if pa[-1].ab_outcome == "HR") + 3 * (bb + hbp) - 2 * ks) / ip_decimal + FIP_CONSTANT, 2) if ip_decimal else None
    oba = round(hits / ab, 3) if ab else None  # Opponent Batting Average against -- Hits / AB, the standard AVG formula
    woba = _compute_woba(completed_pas, ab, bb, hbp)

    return {
        "pitches": total_pitches, "strikes": strikes, "strike_pct": round(strikes / total_pitches * 100, 1) if total_pitches else None,
        "balls": balls, "ball_pct": round(balls / total_pitches * 100, 1) if total_pitches else None,
        "pitches_per_inning": round(total_pitches / ip_decimal, 1) if ip_decimal else None,
        "ip_display": ip_display, "ip_decimal": ip_decimal,
        "ab": ab, "bf": bf, "pitches_per_bf": round(total_pitches / bf, 1) if bf else None,
        "runs": runs, "earned_runs_approx": runs,
        "hits": hits, "xbh": xbh, "bb": bb, "hbp": hbp, "whip": whip, "ks": ks, "k_bb": k_bb, "k_pct": k_pct,
        "leadoff_pas": len(leadoff_pas), "leadoff_outs": leadoff_outs,
        "leadoff_out_pct": round(leadoff_outs / len(leadoff_pas) * 100, 1) if leadoff_pas else None,
        "leadoff_bb": leadoff_bb, "two_out_bb": two_out_bb,
        "zero_two_hits": zero_two_hits, "zero_two_barrel": zero_two_barrel, "one_two_barrel": one_two_barrel,
        "early": early_count, "ahead": ahead_count, "a3p_yes": a3p_yes,
        "e_plus_a_pct": round((early_count + ahead_count) / bf * 100, 1) if bf else None,
        "execution_hits": execution_hits, "execution_reviewed": execution_total,
        "execution_pct": round(execution_hits / execution_total * 100, 1) if execution_total else None,
        "era": era, "fip": fip, "woba": woba, "oba": oba,
        "k_per_9": round(ks * 9 / ip_decimal, 2) if ip_decimal else None,
    }


def _compute_early_ahead_a3p(completed_pas):
    """Ryker's exact definitions, confirmed directly with him:

    Early: ball put in play (pitch_outcome == "In Play" on the PA's
    final pitch) with the count AT THAT PITCH being 0-0, 1-0, 0-1, or
    1-1 -- i.e. contact within the first 3 pitches at a count that
    hasn't gone 2-0. The eventual result (hit, out, error) doesn't
    matter, only that contact happened at one of those counts.

    Ahead: the PA reaches an 0-2 or 1-2 count AT ANY POINT (not
    necessarily the final pitch) -- checked across every pitch in the
    PA, not just the last one. At most one Ahead credit per PA. By
    construction this can never also be Early (Early's four counts
    don't include 0-2/1-2), so every completed PA is Early, Ahead, or
    neither -- never both, matching Ryker's "only one outcome counted
    per batter" rule.

    A3P ("ahead after 3 pitches"): a yes/no per PA. Look at the count
    immediately AFTER the PA's 3rd pitch resolves. If the PA had a 4th
    pitch, that 4th pitch's balls_before/strikes_before IS exactly
    "the count after 3 pitches." If the PA ended at or before the 3rd
    pitch, the terminal count of its actual last pitch is used instead
    (there's no real "after pitch 3" state to check separately in that
    case -- the PA was already over). "Ahead" for A3P purposes means
    strikes > balls at that point.
    """
    early = 0
    ahead = 0
    a3p_yes = 0
    for pa in completed_pas:
        last = pa[-1]
        is_early = last.pitch_outcome == "In Play" and (last.balls_before, last.strikes_before) in {(0, 0), (1, 0), (0, 1), (1, 1)}
        is_ahead = any((p.balls_before, p.strikes_before) in {(0, 2), (1, 2)} for p in pa)
        if is_early:
            early += 1
        elif is_ahead:
            ahead += 1

        pitch4 = next((p for p in pa if p.pa_pitch_number == 4), None)
        if pitch4 is not None:
            balls_after_3, strikes_after_3 = pitch4.balls_before, pitch4.strikes_before
        else:
            # PA ended at or before the 3rd pitch -- use the terminal
            # pitch's own "count after" (its balls_before/strikes_before
            # plus what that final pitch itself did).
            balls_after_3 = last.balls_before + (1 if last.pitch_outcome == "Ball" else 0)
            strikes_after_3 = last.strikes_before + (1 if last.pitch_outcome in ("Called Strike", "Swing and Miss") or (last.pitch_outcome == "Foul" and last.strikes_before < 2) else 0)
        if strikes_after_3 > balls_after_3:
            a3p_yes += 1

    return early, ahead, a3p_yes


def _compute_execution(pitches):
    """Execution Score, per Ryker's definition: did the actual pitch
    land in the same 1-9/0-Bury zone as the intended one? Both
    intended_zone and pitch_zone are already derived/stored on
    GamePitch via strike_zone.derive_old_zone() -- intended_zone at
    live-entry time, pitch_zone only once Video Review sets an actual
    location. Only pitches where BOTH are set count toward the
    denominator -- a not-yet-reviewed pitch is excluded, not scored as
    a miss (see module docstring)."""
    reviewed = [p for p in pitches if p.intended_zone is not None and p.pitch_zone is not None]
    hits = sum(1 for p in reviewed if p.intended_zone == p.pitch_zone)
    return hits, len(reviewed)


def _compute_woba(completed_pas, ab, bb, hbp):
    singles = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "1B")
    doubles = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "2B")
    triples = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "3B")
    hrs = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "HR")
    sf = sum(1 for pa in completed_pas if pa[-1].ab_outcome == "Sac Fly")
    numerator = (
        WOBA_WEIGHTS["uBB"] * bb + WOBA_WEIGHTS["HBP"] * hbp + WOBA_WEIGHTS["1B"] * singles
        + WOBA_WEIGHTS["2B"] * doubles + WOBA_WEIGHTS["3B"] * triples + WOBA_WEIGHTS["HR"] * hrs
    )
    denominator = ab + bb + sf + hbp  # IBB always 0 -- see module docstring
    return round(numerator / denominator, 3) if denominator else None


def _compute_pitch_type_breakdown(pitches, completed_pas, pitch_types):
    """Per-pitch-type rows (Total Pitches, Usage%, Dominance%/CSW%,
    Whiff%, SwStr%, Chase%, Putaway%, GB%/FB%/LD%, FPS%, Execution%, ...),
    attributed by pitch_type_id, plus a Total row summing across all
    types. Zone-dependent columns (Zone Swings/Whiffs, Chase%, Zone
    Whiff%, Execution%) are None for any pitch type with no reviewed
    (actual-location-set) pitches yet."""
    total_pitches = len(pitches)
    rows = {}
    type_ids = sorted({p.pitch_type_id for p in pitches if p.pitch_type_id is not None})

    for type_id in type_ids:
        type_pitches = [p for p in pitches if p.pitch_type_id == type_id]
        rows[pitch_types.get(type_id, "Unknown")] = _pitch_type_row(type_pitches, completed_pas, type_id, total_pitches)

    rows["Total"] = _pitch_type_row(pitches, completed_pas, None, total_pitches, is_total_row=True)
    return rows


def _pitch_type_row(type_pitches, completed_pas, type_id, total_pitches_all_types, is_total_row=False):
    n = len(type_pitches)
    strikes = sum(1 for p in type_pitches if p.pitch_outcome in STRIKE_OUTCOMES)
    balls = sum(1 for p in type_pitches if p.pitch_outcome == "Ball")
    dominant = sum(1 for p in type_pitches if p.pitch_outcome in DOMINANT_OUTCOMES)
    csw = sum(1 for p in type_pitches if p.pitch_outcome in CSW_OUTCOMES)

    swings = [p for p in type_pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = sum(1 for p in type_pitches if p.pitch_outcome == "Swing and Miss")

    reviewed = [p for p in type_pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
    zone_swings = zone_whiffs = chases = out_of_zone_reviewed = None
    if reviewed:
        zone_swings = sum(1 for p in reviewed if p.pitch_outcome in SWING_OUTCOMES and strike_zone.is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z)))
        zone_whiffs = sum(1 for p in reviewed if p.pitch_outcome == "Swing and Miss" and strike_zone.is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z)))
        out_of_zone_reviewed = [p for p in reviewed if not strike_zone.is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
        chases = sum(1 for p in out_of_zone_reviewed if p.pitch_outcome in SWING_OUTCOMES)

    putaway_opportunities = sum(1 for p in type_pitches if p.strikes_before == 2)
    putaway_pitches = sum(1 for p in type_pitches if p.strikes_before == 2 and p.ends_plate_appearance and p.ab_outcome in K_OUTCOMES)

    in_play = [p for p in type_pitches if p.pitch_outcome == "In Play"]
    gb = sum(1 for p in in_play if p.batted_ball_type == "Ground Ball")
    fb = sum(1 for p in in_play if p.batted_ball_type == "Fly Ball")
    ld = sum(1 for p in in_play if p.batted_ball_type == "Line Drive")
    classified_in_play = sum(1 for p in in_play if p.batted_ball_type is not None)

    execution_hits, execution_total = _compute_execution(type_pitches)

    rv_values = [float(p.run_value) for p in type_pitches if p.run_value is not None]
    rv_total = round(sum(rv_values), 3) if rv_values else None
    rv_per_100 = round(sum(rv_values) / n * 100, 2) if n and rv_values else None

    # PAs where this pitch type was thrown as pitch #1 -- for Total,
    # that's every PA; for a specific type, only PAs that opened with it.
    first_pitches = [pa[0] for pa in completed_pas if pa[0].pa_pitch_number == 1 and (is_total_row or pa[0].pitch_type_id == type_id)]
    fps = sum(1 for p in first_pitches if p.pitch_outcome in STRIKE_OUTCOMES)

    early, ahead, _ = _compute_early_ahead_a3p([pa for pa in completed_pas if pa[-1].pitch_type_id == type_id] if not is_total_row else completed_pas)
    bf_for_type = len(completed_pas) if is_total_row else sum(1 for pa in completed_pas if pa[-1].pitch_type_id == type_id)

    ab_for_type = sum(1 for pa in completed_pas if (is_total_row or pa[-1].pitch_type_id == type_id) and pa[-1].ab_outcome not in NON_AB_OUTCOMES)
    hits_for_type = sum(1 for pa in completed_pas if (is_total_row or pa[-1].pitch_type_id == type_id) and pa[-1].ab_outcome in HIT_AB_OUTCOMES)

    return {
        "total_pitches": n,
        "usage_pct": round(n / total_pitches_all_types * 100, 1) if total_pitches_all_types else None,
        "strikes": strikes, "balls": balls,
        "strike_pct": round(strikes / n * 100, 1) if n else None,
        "dominant_pitches": dominant, "dominance_pct": round(dominant / n * 100, 1) if n else None,
        "csw": csw, "csw_pct": round(csw / n * 100, 1) if n else None,
        "fps": fps, "first_pitch_thrown": len(first_pitches), "fps_pct": round(fps / len(first_pitches) * 100, 1) if first_pitches else None,
        "early": early, "ahead": ahead,
        "total_swings": len(swings), "whiffs": whiffs, "whiff_pct": round(whiffs / len(swings) * 100, 1) if swings else None,
        "swstr_pct": round(whiffs / n * 100, 1) if n else None,
        "zone_swings": zone_swings, "zone_whiffs": zone_whiffs,
        "zone_whiff_pct": round(zone_whiffs / zone_swings * 100, 1) if zone_swings else None,
        "chases": chases, "out_of_zone_reviewed": len(out_of_zone_reviewed) if out_of_zone_reviewed is not None else None,
        "chase_pct": round(chases / len(out_of_zone_reviewed) * 100, 1) if out_of_zone_reviewed else None,
        "swords": sum(1 for p in type_pitches if p.is_sword),
        "putaway_opportunities": putaway_opportunities, "putaway_pitches": putaway_pitches,
        "putaway_pct": round(putaway_pitches / putaway_opportunities * 100, 1) if putaway_opportunities else None,
        "balls_in_play": len(in_play), "ground_balls": gb, "fly_balls": fb, "line_drives": ld,
        "ground_ball_pct": round(gb / classified_in_play * 100, 1) if classified_in_play else None,
        "fly_ball_pct": round(fb / classified_in_play * 100, 1) if classified_in_play else None,
        "line_drive_pct": round(ld / classified_in_play * 100, 1) if classified_in_play else None,
        "at_bats": ab_for_type, "bf": bf_for_type, "hits": hits_for_type,
        "execution_hits": execution_hits, "execution_reviewed": execution_total,
        "execution_pct": round(execution_hits / execution_total * 100, 1) if execution_total else None,
        "rv_total": rv_total, "rv_per_100": rv_per_100,
    }


# ---------------------------------------------------------------------
# Staff totals (Sept 2026, Ryker: "for pitcher game report add a staff
# totals portion... first pitch strike percentage, percentage of at
# bats ending in 4 pitches or less, lead off out percentage, secondary
# strike percentage (any pitch other than a fastball), shutdown inning
# (zero after we score). we will set goals for these... track these
# for each inning/pitcher as well as for the entire game.")
#
# Four of these five are ordinary pitching-side stats -- just computed
# across the WHOLE staff's pitches in this game instead of one
# pitcher's (compute_pitcher_game_report above already computes
# leadoff_out_pct and fps_pct the same way for one pitcher; these
# helpers are the shared, pitcher-agnostic versions so staff/inning/
# pitcher breakdowns all use identical math). "At bats" here means
# every COMPLETED PLATE APPEARANCE, including one that ends in a walk
# or HBP (Ryker's call) -- this is an efficiency stat about pitch
# economy, not the strict scorebook AB count OBA/wOBA use elsewhere in
# this module.
#
# Shutdown Inning is the odd one out: it's a half-inning-level stat
# that depends on BOTH sides' pitches (you need to see our own batting
# half-innings to know when we scored), not just our pitching pitches,
# so it's computed separately by _compute_shutdown_innings and merged
# in afterward.
# ---------------------------------------------------------------------

def _group_into_pas(pitches):
    """Same pa_pitch_number-reset grouping compute_pitcher_game_report
    uses above, pulled out standalone so staff/inning/pitcher subsets
    can each be grouped into PAs the same way without re-querying."""
    pas, current = [], []
    for p in pitches:
        if p.pa_pitch_number == 1 and current:
            pas.append(current)
            current = []
        current.append(p)
    if current:
        pas.append(current)
    return pas


def _fps_stat(completed_pas):
    first_pitches = [pa[0] for pa in completed_pas if pa[0].pa_pitch_number == 1]
    fps = sum(1 for p in first_pitches if p.pitch_outcome in STRIKE_OUTCOMES)
    return {
        "fps": fps, "fps_opportunities": len(first_pitches),
        "fps_pct": round(fps / len(first_pitches) * 100, 1) if first_pitches else None,
    }


def _ab4_stat(completed_pas):
    """"At bats" (really: completed PAs, see module note above) that
    ended in 4 pitches or less. pa[-1].pa_pitch_number on the PA's own
    ENDING pitch already equals that PA's total pitch count (it counts
    up from 1 within the PA), so no separate len(pa) needed."""
    short = sum(1 for pa in completed_pas if pa[-1].pa_pitch_number is not None and pa[-1].pa_pitch_number <= 4)
    return {
        "ab4": short, "ab4_opportunities": len(completed_pas),
        "ab4_pct": round(short / len(completed_pas) * 100, 1) if completed_pas else None,
    }


def _leadoff_out_stat(completed_pas):
    leadoff_pas = [pa for pa in completed_pas if _is_leadoff_pitch(pa[0])]
    outs = sum(1 for pa in leadoff_pas if pa[-1].ab_outcome in OUT_AB_OUTCOMES)
    return {
        "leadoff_outs": outs, "leadoff_opportunities": len(leadoff_pas),
        "leadoff_out_pct": round(outs / len(leadoff_pas) * 100, 1) if leadoff_pas else None,
    }


def _secondary_strike_stat(pitches, pitch_types):
    """Strike% on every pitch that ISN'T a fastball (Ryker's own
    definition: "any pitch other than a fastball"). A pitch with no
    pitch_type_id set (never charted) is excluded from both the
    numerator and denominator entirely -- rather than silently folding
    an unknown type into "secondary" -- since we genuinely don't know
    whether it was a fastball."""
    secondary = [p for p in pitches if pitch_types.get(p.pitch_type_id) is not None and pitch_types[p.pitch_type_id] not in FASTBALL_TYPES]
    strikes = sum(1 for p in secondary if p.pitch_outcome in STRIKE_OUTCOMES)
    return {
        "secondary_strikes": strikes, "secondary_pitches": len(secondary),
        "secondary_strike_pct": round(strikes / len(secondary) * 100, 1) if secondary else None,
    }


def _compute_shutdown_innings(session, game_id, game=None):
    """Every half-inning in this game in TRUE chronological order.
    Needs every pitch in the game, both sides, not just our pitching
    pitches.

    A "shutdown opportunity" is a defensive half-inning (we're
    pitching) immediately following an offensive half-inning where we
    scored >=1 run; "converted" means we allowed 0 runs in it -- the
    standard "shutdown inning" definition, matching Ryker's own "zero
    after we score." credited_pitcher_id is whoever threw that
    half-inning's FIRST pitch (a judgment call for a half with a
    mid-inning pitching change -- credits/debits whoever inherited the
    chance, same convention as how a "hold" is scored, not whoever
    happened to get the last out).

    For a TWO-SQUAD intrasquad game, "half-inning" here means a real
    half-inning as _group_into_frames determines it (contiguous
    same-pitcher stretches), not the raw stored `inning` column --
    confirmed against real data (games 14 and 17, Sept 2026) that the
    same inning-numbering inflation that breaks the "by inning"
    breakdown ALSO breaks this function's adjacency check, silently
    dropping real shutdown opportunities (e.g. game 17 showed only 2 of
    4 real opportunities under the raw column). A two-squad game's
    frames always alternate which squad is pitching, so no
    is_our_team_batting check is needed the way the raw-inning path
    needs one.

    For a THREE-squad intrasquad game, or an ordinary (non-intrasquad)
    game, this keeps the original raw-(inning, is_our_team_batting)
    algorithm, unchanged. A three-squad game's raw column is also
    inflated the same way, but frame-grouping can't safely stand in for
    it here: a third squad can rotate onto the mound in between, so
    "the very next half" isn't necessarily "the same opposing pitcher's
    defensive response" the way a shutdown is defined (Ryker, Sept
    2026: "I know this may not work for games that have three different
    lineups") -- so three-squad games are left as-is rather than given
    a definition Ryker hasn't specified yet."""
    if game is None:
        game = session.query(Game).filter(Game.game_id == game_id).first()

    all_pitches = (
        session.query(GamePitch)
        .filter(GamePitch.game_id == game_id)
        .order_by(GamePitch.pitch_sequence)
        .all()
    )
    if not all_pitches:
        return []

    if game is not None and game.is_intrasquad and not game.uses_three_squad_intrasquad:
        return _compute_shutdown_innings_two_squad_frames(all_pitches)

    halves = {}
    order = []
    for p in all_pitches:
        key = (p.inning, p.is_our_team_batting)
        if key not in halves:
            halves[key] = []
            order.append(key)
        halves[key].append(p)

    opportunities = []
    for i, key in enumerate(order):
        inning, is_our_batting = key
        if not is_our_batting:
            continue
        runs_we_scored = sum((p.runs_scored_on_play or 0) for p in halves[key])
        if runs_we_scored < 1:
            continue
        if i + 1 >= len(order):
            continue  # we scored in the game's last half-inning -- no next half to shut down
        next_key = order[i + 1]
        if next_key[1] is not False:
            continue  # defensive guard -- should always alternate batting -> pitching
        next_pitches = halves[next_key]
        runs_allowed = sum((p.runs_scored_on_play or 0) for p in next_pitches)
        opportunities.append({
            "inning": next_key[0],
            "runs_we_scored_before": runs_we_scored,
            "runs_allowed": runs_allowed,
            "shutdown": runs_allowed == 0,
            "credited_pitcher_id": next_pitches[0].our_player_id,
        })
    return opportunities


def _compute_shutdown_innings_two_squad_frames(all_pitches):
    """The two-squad-intrasquad path of _compute_shutdown_innings --
    same definition, keyed off _group_into_frames's real half-innings
    instead of the raw `inning` column. "inning" in each returned dict
    is a FRAME NUMBER (1-based, matching compute_staff_game_totals's
    by_inning numbering for intrasquad games), not a raw stored inning
    value -- see that function's shutdown-matching branch."""
    frames = _group_into_frames(all_pitches, True)
    opportunities = []
    for i in range(len(frames) - 1):
        runs_scored = sum((p.runs_scored_on_play or 0) for p in frames[i])
        if runs_scored < 1:
            continue
        next_pitches = frames[i + 1]
        runs_allowed = sum((p.runs_scored_on_play or 0) for p in next_pitches)
        opportunities.append({
            "inning": i + 2,
            "runs_we_scored_before": runs_scored,
            "runs_allowed": runs_allowed,
            "shutdown": runs_allowed == 0,
            "credited_pitcher_id": _pitcher_id(next_pitches[0]),
        })
    return opportunities


def _staff_stat_bundle(pitches, completed_pas, pitch_types):
    bundle = {}
    bundle.update(_fps_stat(completed_pas))
    bundle.update(_ab4_stat(completed_pas))
    bundle.update(_leadoff_out_stat(completed_pas))
    bundle.update(_secondary_strike_stat(pitches, pitch_types))
    return bundle


def _group_into_frames(our_pitches, is_intrasquad):
    """One group of pitches per REAL half-inning, for the Staff Totals
    "by inning" breakdown. our_pitches must already be sorted by
    pitch_sequence (compute_staff_game_totals guarantees this).

    For an ordinary (non-intrasquad) game, that's just the raw stored
    `inning` column, unchanged -- a real spring game's innings behave
    the way the schema assumes (Ryker, Sept 2026: "for real games in
    the spring it will not be this way").

    For an INTRASQUAD game, though, the raw `inning` column
    over-counts: the live tracker sometimes bumps the inning number
    (or even skips one) mid-frame while the exact same pitcher keeps
    throwing to the exact same batting squad -- confirmed against
    Ryker's own play-by-play account of the Sept 8 game (game_id 14):
    four of that game's ten real half-innings were each split across
    two different stored `inning` values with no actual pitching
    change in between (e.g. Shane Holman's 4-out top of the 2nd was
    stored as innings 3 AND 4), and two stored inning numbers (6, 13)
    were never used by anything at all. So for intrasquad games, group
    by CONTIGUOUS same-pitcher stretches instead (via _pitcher_id) --
    every one of those ten real half-innings collapses back to exactly
    one group this way, with no need to touch the stored data. This
    doesn't explain WHY the live tracker double-bumps in the first
    place (still open -- see compute_current_state in
    game_tracking.py) -- it only fixes how this one report displays
    what's already there.

    Returns a list of pitch-lists, one per real half-inning, in
    chronological order."""
    if not is_intrasquad:
        return [[p for p in our_pitches if p.inning == inning] for inning in sorted({p.inning for p in our_pitches})]

    frames = []
    current = []
    current_pid = None
    for p in our_pitches:
        pid = _pitcher_id(p)
        if current and pid != current_pid:
            frames.append(current)
            current = []
        current_pid = pid
        current.append(p)
    if current:
        frames.append(current)
    return frames


def compute_staff_game_totals(session, game_id):
    """Whole-game, whole-staff totals for the five "team pitching
    goals" stats (see module note above), computed three ways: one
    staff-wide total for the game, one row per inning (combining
    whichever of our pitchers threw that inning), and one row per
    pitcher (their whole game). Returns None if the staff threw no
    pitches in this game yet.

    "Our pitching pitches" -- for an ordinary game, GamePitch rows
    with is_our_team_batting False (our_player_id is the pitcher on
    those). For an INTRASQUAD game (two squads OR three), every single
    pitch in the game is thrown by one of our own roster, whichever
    side of the split it landed on -- so ALL of the game's pitches
    count, with _pitcher_id (not raw our_player_id) picking out who
    actually threw each one. Without this, a whole squad's pitching
    was silently invisible here (Ryker, Sept 2026: "for intrasquads
    coach needs to be able to see both teams") -- confirmed against
    real data: every intrasquad game on record had roughly half its
    pitches on the "wrong" side of the old is_our_team_batting filter."""
    game = session.query(Game).filter(Game.game_id == game_id).first()
    if game is None:
        return None
    all_game_pitches = (
        session.query(GamePitch)
        .filter(GamePitch.game_id == game_id)
        .order_by(GamePitch.pitch_sequence)
        .all()
    )
    our_pitches = all_game_pitches if game.is_intrasquad else [p for p in all_game_pitches if not p.is_our_team_batting]
    if not our_pitches:
        return None

    pitch_types = {pt.pitch_type_id: pt.type_name for pt in session.query(PitchType).all()}
    all_pas = _group_into_pas(our_pitches)
    completed_pas = [pa for pa in all_pas if pa[-1].ends_plate_appearance]

    staff_total = _staff_stat_bundle(our_pitches, completed_pas, pitch_types)

    shutdown_opps = _compute_shutdown_innings(session, game_id, game=game)
    two_squad_intrasquad = game.is_intrasquad and not game.uses_three_squad_intrasquad
    staff_total["shutdown_opportunities"] = len(shutdown_opps)
    staff_total["shutdown_converted"] = sum(1 for o in shutdown_opps if o["shutdown"])
    staff_total["shutdown_pct"] = round(staff_total["shutdown_converted"] / len(shutdown_opps) * 100, 1) if shutdown_opps else None

    # -- by inning -- see _group_into_frames's docstring for how "one
    # row per real half-inning" is determined (intrasquad games use
    # contiguous same-pitcher stretches instead of the raw, inflated
    # `inning` column; ordinary games are unaffected).
    frames = _group_into_frames(our_pitches, game.is_intrasquad)
    by_inning = []
    for i, inn_pitches in enumerate(frames, start=1):
        inn_pas = [pa for pa in all_pas if pa[0] in inn_pitches]
        inn_completed = [pa for pa in inn_pas if pa[-1].ends_plate_appearance]
        raw_innings_covered = {p.inning for p in inn_pitches}
        row = {"inning": i if game.is_intrasquad else inn_pitches[0].inning}
        row.update(_staff_stat_bundle(inn_pitches, inn_completed, pitch_types))
        if two_squad_intrasquad:
            inn_shutdown_opps = [o for o in shutdown_opps if o["inning"] == i]
        else:
            inn_shutdown_opps = [o for o in shutdown_opps if o["inning"] in raw_innings_covered]
        row["shutdown_opportunity"] = len(inn_shutdown_opps) > 0
        row["shutdown"] = inn_shutdown_opps[0]["shutdown"] if inn_shutdown_opps else None
        by_inning.append(row)

    # -- by pitcher, in the order each first took the mound -- keyed by
    # _pitcher_id, not raw our_player_id, so an intrasquad game's
    # "other squad" pitchers (recorded via opponent_our_player_id) get
    # their own row too, same as everyone else.
    pitcher_ids_in_order = []
    seen = set()
    for p in our_pitches:
        pid = _pitcher_id(p)
        if pid is not None and pid not in seen:
            seen.add(pid)
            pitcher_ids_in_order.append(pid)
    players = {pl.player_id: pl for pl in session.query(Player).filter(Player.player_id.in_(pitcher_ids_in_order)).all()}

    by_pitcher = []
    for pid in pitcher_ids_in_order:
        p_pitches = [p for p in our_pitches if _pitcher_id(p) == pid]
        p_pas = [pa for pa in all_pas if _pitcher_id(pa[0]) == pid]
        p_completed = [pa for pa in p_pas if pa[-1].ends_plate_appearance]
        player = players.get(pid)
        row = {
            "player_id": pid,
            "player_name": f"{player.first_name} {player.last_name}" if player else f"Player {pid}",
        }
        row.update(_staff_stat_bundle(p_pitches, p_completed, pitch_types))
        p_shutdown_opps = [o for o in shutdown_opps if o["credited_pitcher_id"] == pid]
        row["shutdown_opportunities"] = len(p_shutdown_opps)
        row["shutdown_converted"] = sum(1 for o in p_shutdown_opps if o["shutdown"])
        row["shutdown_pct"] = round(row["shutdown_converted"] / len(p_shutdown_opps) * 100, 1) if p_shutdown_opps else None
        by_pitcher.append(row)

    return {
        "staff_total": staff_total,
        "by_inning": by_inning,
        "by_pitcher": by_pitcher,
        "shutdown_opportunities_detail": shutdown_opps,
    }
