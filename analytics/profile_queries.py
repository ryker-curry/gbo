"""
GBO -- Pitcher/Hitter Profile: shared query layer.

Backs shiny_app/modules/pitcher_profile.py and hitter_profile.py (the
Aug 2026 filterable per-player deep-dive pages -- STUFF-LOCATION-
PITCHING-PLUS-PLAN.md sections 1/7's Phase 0 "unified filterable Lab
page", later renamed Pitcher/Hitter Profile per Ryker's naming call).
Same DB-querying role game_stats.py already plays for Analytics/My
Stats -- this module owns every query these two pages need, so the
Shiny modules themselves stay render-only, same separation as every
other *_server() module in this app.

Doesn't duplicate game_stats.py's get_pitching_pitches/
get_batting_pitches -- those stay the season/single-game query used by
Analytics/My Stats/Game Report. This module's queries are additive,
for the date-range + opponent-scope + handedness filtering this page
specifically needs and those two don't support.

game_scope convention (matches Game.is_intrasquad): "all" (no filter,
the default), "intrasquad", or "external".
"""

from sqlalchemy.orm import joinedload

from models import GamePitch, Game, RapsodoPitch, BullpenSession, PitchType


def _base_pitching_query(db, player_id):
    return (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(
            ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == player_id))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == player_id))
        )
    )


def _base_batting_query(db, player_id):
    return (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(
            ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.our_player_id == player_id))
            | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id == player_id))
        )
    )


def _apply_filters(query, date_from=None, date_to=None, pitch_type=None, game_scope="all", hand=None):
    if date_from is not None:
        query = query.filter(Game.game_date >= date_from)
    if date_to is not None:
        query = query.filter(Game.game_date <= date_to)
    if game_scope == "intrasquad":
        query = query.filter(Game.is_intrasquad.is_(True))
    elif game_scope == "external":
        query = query.filter(Game.is_intrasquad.is_(False))
    if pitch_type:
        query = query.join(PitchType, GamePitch.pitch_type_id == PitchType.pitch_type_id).filter(PitchType.type_name == pitch_type)
    if hand:
        query = query.filter(GamePitch.opponent_hand == hand)
    return query


def get_pitcher_profile_pitches(db, player_id, date_from=None, date_to=None, pitch_type=None, game_scope="all", opponent_hand=None):
    """Every GamePitch this player threw (our side, or the intrasquad
    'other squad' side -- same union get_pitching_pitches uses),
    matching every filter above. opponent_hand here is the actual
    OPPOSING BATTER's hand (GamePitch.opponent_hand) -- the same
    'vs RHH/vs LHH' split pitcher_game_report.py already offers."""
    query = _base_pitching_query(db, player_id)
    query = _apply_filters(query, date_from, date_to, pitch_type, game_scope, opponent_hand)
    return query.order_by(Game.game_date, GamePitch.pitch_sequence).all()


def get_hitter_profile_pitches(db, player_id, date_from=None, date_to=None, pitch_type=None, game_scope="all", pitcher_hand=None):
    """Every GamePitch this player saw as a batter, matching every
    filter above. pitcher_hand filters on GamePitch.opponent_hand --
    same column as get_pitcher_profile_pitches' opponent_hand, but it
    holds the PITCHER's hand here since our player is on the batting
    side of this row (GamePitch's own docstring: opponent_hand is
    always 'the other side's hand', whichever side that is)."""
    query = _base_batting_query(db, player_id)
    query = _apply_filters(query, date_from, date_to, pitch_type, game_scope, pitcher_hand)
    return query.order_by(Game.game_date, GamePitch.pitch_sequence).all()


def get_pitcher_rapsodo_pitches(db, player_id, date_from=None, date_to=None, pitch_type=None):
    """Every RapsodoPitch for this player -- bullpen-sourced AND
    game-linked alike (Stuff+ is physical-characteristics-only, see
    pitch_grading.py's module docstring -- it doesn't care whether the
    reading came from a bullpen rep or a real outing). Date range reads
    off RapsodoPitch.pitch_date directly (works for both sources) so a
    bullpen-only pitcher still gets a populated Individual Pitches
    physical read even before any game linking exists. game_scope/
    opponent_hand aren't supported here -- outcome/opponent context
    lives on GamePitch, not RapsodoPitch; see rapsodo_by_game_pitch_id
    below for how the two get joined per-pitch."""
    query = (
        db.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.player_id == player_id)
    )
    if date_from is not None:
        query = query.filter(RapsodoPitch.pitch_date >= date_from)
    if date_to is not None:
        query = query.filter(RapsodoPitch.pitch_date <= date_to)
    if pitch_type:
        query = query.join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id).filter(PitchType.type_name == pitch_type)
    return query.order_by(RapsodoPitch.pitch_date).all()


def rapsodo_by_game_pitch_id(db, game_pitch_ids):
    """{game_pitch_id: RapsodoPitch} for every game_pitch_id in the
    given list that has a linked Rapsodo reading -- the join the
    Individual Pitches table needs to attach Stuff+'s physical inputs
    onto each GamePitch row. Empty dict (not a query) if
    game_pitch_ids is empty, avoiding a pointless IN () round trip."""
    if not game_pitch_ids:
        return {}
    rows = (
        db.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.game_pitch_id.in_(game_pitch_ids))
        .all()
    )
    return {r.game_pitch_id: r for r in rows}


def bullpen_ids_for_player(db, player_id, date_from=None, date_to=None):
    """Bullpen session ids for this player in the given date range --
    feeds bullpen_dashboard_display.register_bullpen_dashboard's
    get_target as a {"kind": "combined", ...} target, the same
    mechanism player_bullpens.py already uses for its 'Overall Pitch
    Tracking' combined view, just date-scoped here to match this page's
    own filters instead of always being all-time."""
    query = db.query(BullpenSession.bullpen_id).filter(BullpenSession.player_id == player_id)
    if date_from is not None:
        query = query.filter(BullpenSession.session_date >= date_from)
    if date_to is not None:
        query = query.filter(BullpenSession.session_date <= date_to)
    return [bid for (bid,) in query.all()]


def team_stuff_plus_baselines(db):
    """{pitch_type_label: baseline} across EVERY pitcher's RapsodoPitch
    rows team-wide (bullpen + game-linked alike, all-time) -- same
    'the team' population convention as command_metrics.py's Command+:
    not scoped to the viewing page's own filters, a stable roster-wide
    reference every profile page's Stuff+ scores are measured against.
    Groups by canonical pitch type first since
    pitch_grading.team_stuff_plus_baseline expects one type's pitches
    at a time (see its own docstring)."""
    from analytics.pitch_grading import team_stuff_plus_baseline
    rows = db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type)).filter(RapsodoPitch.pitch_type_id.isnot(None)).all()
    by_type = {}
    for r in rows:
        label = r.pitch_type.type_name if r.pitch_type else "Unspecified"
        by_type.setdefault(label, []).append(r)
    return {label: team_stuff_plus_baseline(pitches) for label, pitches in by_type.items()}


def team_location_plus_baseline(db):
    """{(attack_zone, pitch_type_label): baseline} across every located,
    run-value-bearing GamePitch thrown by one of OUR OWN pitchers,
    team-wide, all-time -- real opponents and intrasquad Squad-B outings
    alike (same union get_pitching_pitches uses, just not scoped to one
    player_id): (is_our_team_batting is False) covers every game where
    one of our real Squad-A pitchers is on the mound; (is_our_team_batting
    is True) & opponent_our_player_id set covers intrasquad games where
    the 'opposing' pitcher is our own Squad-B roster. An external
    opponent's own pitcher (is_our_team_batting True, opponent_our_player_id
    NULL) is deliberately excluded -- that's not one of ours. Same team
    population convention as team_stuff_plus_baselines/Command+ above."""
    from analytics.pitch_grading import team_location_plus_baseline as _baseline
    pitches = (
        db.query(GamePitch)
        .filter(
            (GamePitch.is_our_team_batting.is_(False))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id.isnot(None)))
        )
        .all()
    )
    return _baseline(pitches)


def team_pitching_lines(db, date_from=None, date_to=None):
    """List of per-pitcher line dicts (one per pitcher who threw at
    least one pitch in this population), each a
    game_stats.compute_pitching_line() dict merged with a "CSW %" key
    (analytics.performance_score.csw_pct) -- the query-layer input
    analytics.performance_score.team_pitcher_results_baseline() expects.
    Same team population union as team_location_plus_baseline above
    (real Squad-A outings + intrasquad Squad-B reps, external
    opponents' own pitchers excluded), grouped by whichever id field is
    actually OUR pitcher on each row (our_player_id when we're pitching,
    opponent_our_player_id when we're the intrasquad 'opponent').

    Unlike team_stuff_plus_baselines/team_location_plus_baseline above
    (deliberately all-time, a stable roster-wide reference for a
    per-pitch grade), date_from/date_to default to None (all-time) but
    are meant to be passed -- Ryker's Aug 31 2026 call: Results/
    Performance is built from box-score outcomes (FIP, WHIP, wOBA...),
    which mix fall and spring ball into a meaningless number if pooled
    together the way a release-point grade can tolerate. Callers
    (pitcher_profile.py's pp_body) pass the page's own date filter so
    the team baseline and the one pitcher's own line it's compared
    against cover the SAME window -- a fall-only filter yields a fall
    Performance score, a spring-only filter a separate spring one."""
    from game_stats import compute_pitching_line
    from analytics.performance_score import csw_pct
    query = (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(
            (GamePitch.is_our_team_batting.is_(False))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id.isnot(None)))
        )
    )
    if date_from is not None:
        query = query.filter(Game.game_date >= date_from)
    if date_to is not None:
        query = query.filter(Game.game_date <= date_to)
    pitches = query.all()
    by_player = {}
    for p in pitches:
        pid = p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id
        if pid is None:
            continue
        by_player.setdefault(pid, []).append(p)
    lines = []
    for pid, ps in by_player.items():
        line = compute_pitching_line(ps)
        line["CSW %"] = csw_pct(ps)
        lines.append(line)
    return lines


def team_hitting_lines(db, date_from=None, date_to=None):
    """List of per-hitter line dicts (one per hitter with at least one
    plate-appearance pitch in this population), each a
    game_stats.compute_batting_line() dict merged with
    plate_discipline.compute_hitter_discipline()'s "Chase %"/"Whiff %"/
    "Zone Swing %" for the same pitches -- the query-layer input
    analytics.performance_score.team_hitter_results_baseline() expects.
    Mirrors team_pitching_lines' population/grouping logic (and its
    same date_from/date_to fall-vs-spring reasoning -- see that
    docstring), on the batting side of the same union
    _base_batting_query uses per-player (our_player_id when we're
    batting, opponent_our_player_id when we're the intrasquad
    'opponent')."""
    from game_stats import compute_batting_line
    from plate_discipline import compute_hitter_discipline
    query = (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(
            (GamePitch.is_our_team_batting.is_(True))
            | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id.isnot(None)))
        )
    )
    if date_from is not None:
        query = query.filter(Game.game_date >= date_from)
    if date_to is not None:
        query = query.filter(Game.game_date <= date_to)
    pitches = query.all()
    by_player = {}
    for p in pitches:
        pid = p.opponent_our_player_id if not p.is_our_team_batting else p.our_player_id
        if pid is None:
            continue
        by_player.setdefault(pid, []).append(p)
    lines = []
    for pid, ps in by_player.items():
        line = compute_batting_line(ps)
        discipline = compute_hitter_discipline(ps)
        line["Chase %"] = discipline["Chase %"]
        line["Whiff %"] = discipline["Whiff %"]
        line["Zone Swing %"] = discipline["Zone Swing %"]
        lines.append(line)
    return lines
