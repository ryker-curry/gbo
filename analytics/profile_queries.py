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
from sqlalchemy import or_

from models import GamePitch, Game, RapsodoPitch, RapsodoImport, BullpenSession, PitchType, Player


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


def _apply_filters(query, date_from=None, date_to=None, pitch_type=None, game_scope="all", hand=None, game_id=None):
    if game_id is not None:
        # A specific game overrides date_from/date_to/game_scope entirely
        # (Sept 2026, Ryker: "for everything in pitcher profile be able to
        # select a specific game as well as the entire season view") --
        # callers pass date_from/date_to=None alongside a set game_id (see
        # pitcher_profile.py's _current_filters), so this is normally the
        # only date-ish filter in play, but it's still unconditional here
        # too as a second guarantee against ever mixing a stale date range
        # with a picked game.
        query = query.filter(GamePitch.game_id == game_id)
        if pitch_type:
            query = query.join(PitchType, GamePitch.pitch_type_id == PitchType.pitch_type_id).filter(PitchType.type_name == pitch_type)
        if hand:
            query = query.filter(GamePitch.opponent_hand == hand)
        return query
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


def get_pitcher_profile_pitches(db, player_id, date_from=None, date_to=None, pitch_type=None, game_scope="all", opponent_hand=None, game_id=None):
    """Every GamePitch this player threw (our side, or the intrasquad
    'other squad' side -- same union get_pitching_pitches uses),
    matching every filter above. opponent_hand here is the actual
    OPPOSING BATTER's hand (GamePitch.opponent_hand) -- the same
    'vs RHH/vs LHH' split pitcher_game_report.py already offers.
    game_id (Sept 2026 addition): narrows to exactly one game, see
    _apply_filters' own docstring note for how it interacts with the
    other filters."""
    query = _base_pitching_query(db, player_id)
    query = _apply_filters(query, date_from, date_to, pitch_type, game_scope, opponent_hand, game_id)
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


def get_pitcher_rapsodo_pitches(db, player_id, date_from=None, date_to=None, pitch_type=None, game_scope="all", game_id=None, game_linked_only=False):
    """Every RapsodoPitch for this player -- bullpen-sourced AND
    game-linked alike by default (Stuff+ is physical-characteristics-
    only, see pitch_grading.py's module docstring -- it doesn't care
    whether the reading came from a bullpen rep or a real outing). Date
    range reads off RapsodoPitch.pitch_date directly (works for both
    sources) so a bullpen-only pitcher still gets a populated
    Individual Pitches physical read even before any game linking
    exists.

    game_linked_only (Sept 2026, Ryker: "i want pitcher profile to only
    pull pitches from games") -- when True, drops every bullpen-sourced
    reading regardless of game_scope/date range, via
    RapsodoPitch.bullpen_id.is_(None) (the same "bullpen_id/game import
    are mutually exclusive per row" invariant models.RapsodoPitch's own
    bullpen_id comment documents -- a NULL bullpen_id already means this
    reading came from a game import, whether or not it's been matched
    to a specific charted GamePitch yet). Composes with game_scope's own
    OR-based bullpen-always-included clause below without needing to
    touch that clause -- once bullpen rows are excluded up front, that
    OR's bullpen branch simply never matches anything, leaving only the
    real intrasquad/external filter for what's left. Only
    pitcher_profile.py passes this True so far; every other caller of
    this function keeps today's bullpen-inclusive behavior unchanged.

    game_scope (Sept 2026 addition, same convention as _apply_filters
    above): unlike the GamePitch-only queries, "intrasquad"/"external"
    here only narrows which GAME-linked pitches count -- a bullpen
    reading isn't a game at all, so it's never excluded by this filter
    regardless of scope (an outer join + OR, not a plain filter, since
    RapsodoPitch.game_pitch_id/bullpen_id are mutually exclusive per
    row -- see that column's own comment on models.RapsodoPitch).
    opponent_hand still isn't supported here -- that context lives on
    GamePitch, not RapsodoPitch; see rapsodo_by_game_pitch_id below for
    how the two get joined per-pitch.

    game_id (Sept 2026 addition, same "pick one game" feature as
    get_pitcher_profile_pitches): unlike game_scope, this DOES exclude
    every bullpen-only reading, on purpose -- picking one specific game
    means "just that outing's pitches," and a bullpen rep with no tie
    to that game isn't part of it. Matches via RapsodoImport.game_id
    (set on an import made against an Intrasquad Game rather than a
    Bullpen Session -- see that column's own comment on
    models.RapsodoImport) rather than RapsodoPitch.game_pitch_id, since
    the latter is only set once a reading has been individually matched
    to a charted pitch (services/rapsodo_import.py's matching step) --
    using it here would silently drop this game's still-unmatched
    readings. Takes priority over game_scope, same as
    get_pitcher_profile_pitches/_apply_filters."""
    query = (
        db.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.player_id == player_id)
    )
    if game_linked_only:
        query = query.filter(RapsodoPitch.bullpen_id.is_(None))
    if game_id is not None:
        query = query.join(RapsodoImport, RapsodoPitch.import_id == RapsodoImport.import_id).filter(RapsodoImport.game_id == game_id)
        if pitch_type:
            query = query.join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id).filter(PitchType.type_name == pitch_type)
        return query.order_by(RapsodoPitch.pitch_date).all()
    if date_from is not None:
        query = query.filter(RapsodoPitch.pitch_date >= date_from)
    if date_to is not None:
        query = query.filter(RapsodoPitch.pitch_date <= date_to)
    if pitch_type:
        query = query.join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id).filter(PitchType.type_name == pitch_type)
    if game_scope in ("intrasquad", "external"):
        query = (
            query.outerjoin(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
            .outerjoin(Game, GamePitch.game_id == Game.game_id)
        )
        wants_intrasquad = game_scope == "intrasquad"
        query = query.filter(or_(RapsodoPitch.bullpen_id.isnot(None), Game.is_intrasquad.is_(wants_intrasquad)))
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


def team_stuff_plus_training_pitches(db):
    """{pitch_type_label: [(RapsodoPitch, run_value), ...]} -- every
    RapsodoPitch reading team-wide that IS linked to a real game outcome
    (RapsodoPitch.game_pitch_id set, joined GamePitch.run_value not
    null), all-time, grouped by canonical pitch type. This is the
    TRAINING population for pitch_grading.fit_stuff_plus_model -- a
    bullpen-only reading has no run_value and is correctly excluded here
    (it can still be SCORED once a model exists, just never used to fit
    one -- see that function's docstring). Same team-wide/all-time
    population convention as team_location_plus_baseline below, which
    Stuff+'s training population deliberately mirrors now that both are
    genuinely outcome-based."""
    rows = (
        db.query(RapsodoPitch, GamePitch.run_value)
        .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.pitch_type_id.isnot(None))
        .filter(GamePitch.run_value.isnot(None))
        .all()
    )
    by_type = {}
    for rapsodo_pitch, run_value in rows:
        label = rapsodo_pitch.pitch_type.type_name if rapsodo_pitch.pitch_type else "Unspecified"
        by_type.setdefault(label, []).append((rapsodo_pitch, run_value))
    return by_type


def team_pitcher_primary_fastball_velocity(db):
    """{player_id: average velocity (float)} of each pitcher's own
    PRIMARY fastball -- whichever of 4-Seam Fastball/2-Seam Fastball
    that pitcher has thrown more of in real games -- computed from that
    SAME pitcher's own real-game (GamePitch-linked; bullpen excluded)
    RapsodoPitch readings of that one type. Feeds pitch_grading.
    STUFF_PLUS_FEATURE_NAMES's velocity_differential, currently only
    weighted for Changeup (Ryker's Sept 2026 follow-up call, after
    noting Stuff+ couldn't see a changeup's real value driver --
    velocity SEPARATION from a pitcher's own fastball -- without this).

    "Primary" is picked per pitcher, not assumed team-wide, because not
    every pitcher throws both fastball types -- checked against live
    data, 2 of GBO's real-game changeup-throwers have logged real-game
    2-Seam Fastball only, zero 4-Seam Fastball, so always comparing to
    4-Seam Fastball specifically would leave them with no differential
    at all.

    A pitcher whose primary fastball type has fewer than
    pitch_grading.MIN_PITCHER_FASTBALL_VELO_PITCHES real-game readings
    is left out of the returned dict entirely, rather than given a
    value built from 1-2 pitches -- callers already treat a missing
    player_id as "no differential available" the same way every other
    optional feature in this module degrades (see
    pitch_grading._stuff_plus_features)."""
    from statistics import mean
    from analytics.pitch_grading import MIN_PITCHER_FASTBALL_VELO_PITCHES

    rows = (
        db.query(RapsodoPitch.player_id, RapsodoPitch.velocity, PitchType.type_name)
        .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
        .join(PitchType, RapsodoPitch.pitch_type_id == PitchType.pitch_type_id)
        .filter(PitchType.type_name.in_(["4-Seam Fastball", "2-Seam Fastball"]))
        .filter(RapsodoPitch.velocity.isnot(None))
        .all()
    )
    by_player_type = {}
    for player_id, velocity, type_name in rows:
        by_player_type.setdefault(player_id, {}).setdefault(type_name, []).append(float(velocity))

    result = {}
    for player_id, velocities_by_type in by_player_type.items():
        # Whichever fastball type has more real-game readings for THIS
        # pitcher -- ties broken arbitrarily by dict iteration order,
        # not worth a tiebreak rule at GBO's current data volume.
        primary_type, velocities = max(velocities_by_type.items(), key=lambda item: len(item[1]))
        if len(velocities) < MIN_PITCHER_FASTBALL_VELO_PITCHES:
            continue
        result[player_id] = mean(velocities)
    return result


def team_stuff_plus_baselines(db):
    """{pitch_type_label: model} across every canonical pitch type that
    has enough real-game training data -- see
    pitch_grading.fit_stuff_plus_model / MIN_STUFF_TRAINING_PITCHES. A
    type with too little real-game data simply doesn't appear in the
    returned dict; callers already treat a missing key as "no model" via
    `.get(label)` (not `.get(label, {})` -- pitch_grading.stuff_plus
    expects None, not an empty dict, when nothing was fit yet).

    Aug 31 2026 methodology fix (Ryker's call): this used to build a
    plain mean/stdev baseline off EVERY RapsodoPitch team-wide, bullpen
    and game-linked pooled together with no outcome involved at all --
    see pitch_grading.py's module docstring for the full reasoning on
    why that wasn't actually "Stuff+" in any trained sense. Training now
    comes only from team_stuff_plus_training_pitches above (real-game,
    run-value-bearing pitches); the fitted model this returns can still
    score ANY pitch of that type, bullpen included, once it exists."""
    from analytics.pitch_grading import fit_stuff_plus_model
    training_by_type = team_stuff_plus_training_pitches(db)
    # Sept 2026: built once here and threaded into every type's fit
    # below, rather than each caller of stuff_plus() needing to pass it
    # through separately -- fit_stuff_plus_model stores this dict on the
    # model it returns, so stuff_plus() can look a pitcher's own
    # reference back up at SCORING time straight from the model, and
    # every existing stuff_plus() call site keeps working unchanged.
    pitcher_fastball_velocities = team_pitcher_primary_fastball_velocity(db)
    models = {}
    for label, pairs in training_by_type.items():
        # Sept 2026: Stuff+'s weights are fixed per pitch type now, not
        # fit -- fit_stuff_plus_model needs `label` to pick the right
        # type's weight set out of pitch_grading.STUFF_PLUS_FIXED_WEIGHTS
        # (see that function's docstring). This is still the one and
        # only call site.
        model = fit_stuff_plus_model(pairs, label, pitcher_fastball_velocities)
        if model is not None:
            models[label] = model
    return models


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


def _pitching_staff_query(db, date_from=None, date_to=None, game_scope="all"):
    """Shared GamePitch query behind team_pitching_lines_by_player and
    pitching_staff_leaderboard_rows below -- same team population as
    team_location_plus_baseline (real Squad-A outings + intrasquad
    Squad-B reps, external opponents' own pitchers excluded), with the
    same date_from/date_to and game_scope (All/Intrasquad/External,
    matching Game.is_intrasquad) filtering every other filtered query
    in this module already uses."""
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
    if game_scope == "intrasquad":
        query = query.filter(Game.is_intrasquad.is_(True))
    elif game_scope == "external":
        query = query.filter(Game.is_intrasquad.is_(False))
    return query


def team_pitching_lines_by_player(db, date_from=None, date_to=None, game_scope="all"):
    """{player_id: game_stats.compute_pitching_line() dict merged with a
    "CSW %" key (analytics.performance_score.csw_pct)} for every pitcher
    who threw at least one pitch in this population -- same population/
    grouping team_pitching_lines below has always used, just keyed by
    player_id instead of thrown away, so a caller that needs to know
    WHICH pitcher a line belongs to (pitching_staff_leaderboard_rows)
    doesn't have to re-run this same query a second time."""
    from game_stats import compute_pitching_line
    from analytics.performance_score import csw_pct
    pitches = _pitching_staff_query(db, date_from, date_to, game_scope).all()
    by_player = {}
    for p in pitches:
        pid = p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id
        if pid is None:
            continue
        by_player.setdefault(pid, []).append(p)
    lines = {}
    for pid, ps in by_player.items():
        line = compute_pitching_line(ps)
        line["CSW %"] = csw_pct(ps)
        lines[pid] = line
    return lines


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
    (pitcher_profile.py's pp_overview_section) pass the page's own date filter so
    the team baseline and the one pitcher's own line it's compared
    against cover the SAME window -- a fall-only filter yields a fall
    Performance score, a spring-only filter a separate spring one.

    Thin wrapper over team_pitching_lines_by_player (Sept 2026, added
    for pitching_staff_leaderboard_rows below) -- same values, just the
    dict's values() instead of the dict itself, unchanged return shape
    for every existing caller."""
    return list(team_pitching_lines_by_player(db, date_from, date_to).values())


def _fmt_grade(value):
    return f"{value:.1f}" if value is not None else "—"


def aggregate_trend_by_game(pitch_points):
    """pitch_points: list of (game_id, game_date, value) for individual
    graded pitches (value already non-None) -- one entry per pitch, as
    compute_grading_bundle/pitcher_profile.py's pp_trend_chart build
    them. Groups by game_id, not date alone, so two games on the same
    date (a doubleheader) stay separate points instead of silently
    averaging together. Returns one point per OUTING -- (date, mean,
    lo, hi) -- sorted by date: mean is that outing's average
    pitch-level grade, lo/hi its min/max, so
    visualizations/profile_charts.trend_chart can show each outing's
    spread (an error bar) around its average instead of one dot per
    pitch.

    Sept 2026, Ryker: raw pitch-by-pitch dots were too noisy to read as
    an actual trend across outings ("how is this useful?" -- fair
    question, given it took a whole page of pitches per outing to find
    the shape). An outing-level average is what "trend over time"
    actually means to a coach looking for whether a guy's pitching
    better or worse lately, not a per-pitch scatter.

    Moved here from pitcher_profile.py (Sept 2026, Pitching Staff
    Leaderboard) so compute_grading_bundle below -- now shared by both
    pitcher_profile.py and the new leaderboard -- can call it without
    reaching back into that page module."""
    from statistics import mean
    groups = {}
    for game_id, game_date, value in pitch_points:
        groups.setdefault(game_id, {"date": game_date, "values": []})["values"].append(value)
    rows = [
        (g["date"], round(mean(g["values"]), 1), round(min(g["values"]), 1), round(max(g["values"]), 1))
        for g in groups.values()
    ]
    rows.sort(key=lambda r: r[0])
    return rows


def compute_grading_bundle(db, game_pitches, rapsodo_pitches, stuff_baselines=None, location_baseline=None):
    """Shared derived-data pass over one filtered pitch window --
    Stuff+/Location+/Pitching+ per pitch, pitch usage counts,
    attack-zone counts, the Pitching+ trend series (one point per
    OUTING, not per pitch -- see aggregate_trend_by_game), the Arsenal
    rollup, and the Individual Pitches rows. Moved here from
    pitcher_profile.py (Sept 2026, Pitching Staff Leaderboard) so a
    roster-wide caller (pitching_staff_leaderboard_rows below) can call
    it once per pitcher without duplicating this ~60-line loop a second
    time -- pitcher_profile.py's own pp_overview_section/pp_zone_
    section/pp_arsenal_section still call this exact function, just
    through profile_queries now instead of a page-local nested def.

    stuff_baselines/location_baseline: pass these in (from
    team_stuff_plus_baselines/team_location_plus_baseline) when the
    caller is looping over many pitchers against the SAME team-wide
    baselines, to avoid re-fitting them on every call -- a single
    pitcher_profile.py page load still gets None here and fits them
    itself, unchanged behavior from before this was a parameter."""
    from strike_zone import classify_attack_zone
    from analytics.pitch_grading import stuff_plus, location_plus, pitching_plus, arsenal_summary

    if stuff_baselines is None:
        stuff_baselines = team_stuff_plus_baselines(db)
    if location_baseline is None:
        location_baseline = team_location_plus_baseline(db)

    game_pitch_ids = [p.game_pitch_id for p in game_pitches]
    rap_by_gp = rapsodo_by_game_pitch_id(db, game_pitch_ids)

    def _type_label(pitch_type_obj):
        return pitch_type_obj.type_name if pitch_type_obj is not None else "Unspecified"

    pitch_type_grades = {}
    individual_rows = []
    trend_pitch_points = []
    zone_counts = {"Heart": 0, "Shadow": 0, "Chase": 0, "Waste": 0}
    usage_counts = {}

    for p in game_pitches:
        label = _type_label(p.pitch_type)
        usage_counts[label] = usage_counts.get(label, 0) + 1

        rap = rap_by_gp.get(p.game_pitch_id)
        s_val = stuff_plus(rap, stuff_baselines.get(label)) if rap is not None else None
        l_val = location_plus(p, location_baseline)
        pi_val = pitching_plus(s_val, l_val)

        grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
        grp["n"] += 1
        if s_val is not None:
            grp["stuff_plus"].append(s_val)
        if l_val is not None:
            grp["location_plus"].append(l_val)
        if pi_val is not None:
            grp["pitching_plus"].append(pi_val)

        if p.actual_plate_x is not None and p.actual_plate_z is not None:
            zone = classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z))
            if zone:
                zone_counts[zone] += 1

        if pi_val is not None and p.game is not None:
            trend_pitch_points.append((p.game.game_id, p.game.game_date, pi_val))

        individual_rows.append({
            "Date": p.game.game_date.strftime("%Y-%m-%d") if p.game else "—",
            "#": p.pitch_sequence,
            "Pitch Type": label,
            "Velo": f"{float(rap.velocity):.1f}" if rap is not None and rap.velocity is not None else "—",
            "Result": p.pitch_outcome or "—",
            "Stuff+": _fmt_grade(s_val),
            "Location+": _fmt_grade(l_val),
            "Pitching+": _fmt_grade(pi_val),
        })

    # Any Rapsodo pitches with no game link at all (pure bullpen
    # reps) still count toward Arsenal's Stuff+ rollup -- see this
    # function's callers' original docstring note (kept from
    # pp_body's own comment, unchanged reasoning): stuff_baselines
    # holds fitted MODELS, trained only on real-game pitches, but a
    # fitted model scores any pitch from just its physical readings.
    linked_rapsodo_ids = {r.rapsodo_pitch_id for r in rap_by_gp.values()}
    for r in rapsodo_pitches:
        if r.rapsodo_pitch_id in linked_rapsodo_ids:
            continue
        label = _type_label(r.pitch_type)
        s_val = stuff_plus(r, stuff_baselines.get(label))
        if s_val is None:
            continue
        grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
        grp["n"] += 1
        grp["stuff_plus"].append(s_val)

    arsenal_rows = arsenal_summary(pitch_type_grades) if pitch_type_grades else []
    overview_stuff = [v for row in arsenal_rows for v in [row["Stuff+"]] if v is not None]
    overview_loc = [v for row in arsenal_rows for v in [row["Location+"]] if v is not None]
    overview_pitching = [v for row in arsenal_rows for v in [row["Pitching+"]] if v is not None]

    return {
        "stuff_plus_value": round(sum(overview_stuff) / len(overview_stuff), 1) if overview_stuff else None,
        "location_plus_value": round(sum(overview_loc) / len(overview_loc), 1) if overview_loc else None,
        "pitching_plus_value": round(sum(overview_pitching) / len(overview_pitching), 1) if overview_pitching else None,
        "usage_counts": usage_counts,
        "zone_counts": zone_counts,
        "trend_points": aggregate_trend_by_game(trend_pitch_points),
        "arsenal_rows": arsenal_rows,
        "individual_rows": individual_rows,
    }


def pitching_staff_leaderboard_rows(db, date_from=None, date_to=None, game_scope="all"):
    """One row per pitcher (Player object) who threw at least one
    qualifying pitch in this window, combining
    game_stats.compute_pitching_line()'s traditional box-score/rate
    stats with GBO's own team-relative pitch grades (Stuff+/Location+/
    Pitching+/Command+/Arsenal/Results/Performance) -- the exact same
    math pitcher_profile.py's Overview tab computes for one pitcher at
    a time, run once per roster pitcher against baselines computed ONCE
    up front (not re-fit per pitcher) instead of N times. Feeds
    shiny_app/modules/pitching_leaderboard.py (Sept 2026, Ryker: "create
    a pitching staff leaderboard").

    Same team population as team_pitching_lines_by_player/
    team_location_plus_baseline (our own Squad-A pitchers pitching,
    plus intrasquad games where our own Squad-B pitcher is logged as
    the 'opponent' -- an external opponent's own pitcher is never
    included, this is GBO's own roster only), further narrowed by
    game_scope ("all"/"intrasquad"/"external", matching
    Game.is_intrasquad) same as every other filtered query in this
    module.

    Each row is a plain dict with a "player" key (the Player object,
    for name/throws/etc.) plus every selectable leaderboard stat --
    None for any stat this pitcher doesn't have enough data for (never
    0, so the leaderboard's sort/format code can tell "no data" from
    "actually zero")."""
    from analytics import command_metrics, performance_score

    pitches = _pitching_staff_query(db, date_from, date_to, game_scope).all()
    by_player = {}
    for p in pitches:
        pid = p.opponent_our_player_id if p.is_our_team_batting else p.our_player_id
        if pid is None:
            continue
        by_player.setdefault(pid, []).append(p)
    if not by_player:
        return []

    players_by_id = {
        pl.player_id: pl for pl in db.query(Player).filter(Player.player_id.in_(by_player.keys())).all()
    }

    # Rapsodo pitches per pitcher, same window/game_scope, batched in
    # ONE query rather than N -- same population get_pitcher_rapsodo_
    # pitches uses for a single player, generalized to the whole roster
    # via .in_() instead of == one id.
    rap_query = (
        db.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.player_id.in_(by_player.keys()))
    )
    if date_from is not None:
        rap_query = rap_query.filter(RapsodoPitch.pitch_date >= date_from)
    if date_to is not None:
        rap_query = rap_query.filter(RapsodoPitch.pitch_date <= date_to)
    if game_scope in ("intrasquad", "external"):
        rap_query = (
            rap_query.outerjoin(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
            .outerjoin(Game, GamePitch.game_id == Game.game_id)
        )
        wants_intrasquad = game_scope == "intrasquad"
        rap_query = rap_query.filter(or_(RapsodoPitch.bullpen_id.isnot(None), Game.is_intrasquad.is_(wants_intrasquad)))
    rapsodo_by_player = {}
    for r in rap_query.all():
        rapsodo_by_player.setdefault(r.player_id, []).append(r)

    # Team-wide baselines, computed ONCE -- not re-fit per pitcher the
    # way a single pitcher_profile.py page load does (there's only ever
    # one pitcher on that page).
    stuff_baselines = team_stuff_plus_baselines(db)
    location_baseline = team_location_plus_baseline(db)
    all_command_pitches = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
    command_baselines = command_metrics.team_command_plus_baselines(
        command_metrics.game_pitches_command_view(all_command_pitches, None)
    )

    lines_by_player = team_pitching_lines_by_player(db, date_from, date_to, game_scope)
    results_baseline = None
    if len(lines_by_player) >= performance_score.MIN_BASELINE_PLAYERS:
        results_baseline = performance_score.team_pitcher_results_baseline(list(lines_by_player.values()))

    rows = []
    for pid, ps in by_player.items():
        player = players_by_id.get(pid)
        line = lines_by_player.get(pid)
        if player is None or line is None:
            continue
        rapsodo_pitches = rapsodo_by_player.get(pid, [])

        bundle = compute_grading_bundle(db, ps, rapsodo_pitches, stuff_baselines=stuff_baselines, location_baseline=location_baseline)

        cmd_view_pitches = command_metrics.game_pitches_command_view(ps, player.throws)
        command_plus_value = None
        if command_baselines["pooled"][2] >= command_metrics.MIN_BASELINE_PITCHES:
            command_plus_value = command_metrics.session_command_plus(cmd_view_pitches, command_baselines)

        arsenal_pitching_value = performance_score.usage_weighted_average(bundle["arsenal_rows"], "Pitching+")

        results_score = None
        if results_baseline is not None:
            results_score = performance_score.pitcher_results_score(line, results_baseline)

        performance_value = performance_score.combine_pitcher_performance(
            bundle["stuff_plus_value"], bundle["location_plus_value"], command_plus_value,
            arsenal_pitching_value, results_score,
        )

        # BB/9, HR/9 come straight from compute_pitching_line (added
        # there Sept 2026) rather than being re-derived here -- see
        # the comment on the row dict below.
        bb, k, bf = line["BB"], line["K"], line["Batters Faced"]
        bb_pct = round(100 * bb / bf, 1) if bf else None
        k_pct = line["K %"]
        k_minus_bb_pct = round(k_pct - bb_pct, 1) if (k_pct is not None and bb_pct is not None) else None

        rows.append({
            "player": player,
            "Pitcher": f"{player.first_name} {player.last_name}",
            "IP": line["IP"], "IP (decimal)": line["IP (decimal)"],
            "ERA": line["ERA"], "WHIP": line["WHIP"], "FIP": line["FIP"],
            # BB/9, HR/9 now come straight from compute_pitching_line
            # (added there Sept 2026) instead of being re-derived here
            # against the already-rounded "IP (decimal)" field -- that
            # double-rounding produced results a hundredth or two off
            # from every sibling rate stat (WHIP/K-9/ERA/FIP), which all
            # divide by compute_pitching_line's raw, unrounded innings
            # value. Caught by the leaderboard's own fixture test.
            "K/9": line["K/9"], "BB/9": line["BB/9"], "HR/9": line["HR/9"],
            "K %": k_pct, "BB %": bb_pct, "K-BB %": k_minus_bb_pct, "K/BB": line["K/BB"],
            "OBA": line["OBA (opponent AVG)"], "Strike %": line["Strike %"],
            "FPS %": line["First Pitch Strike %"], "CSW %": line["CSW %"],
            "Zone Execution %": line["Zone Execution %"],
            "BF": bf, "K": k, "BB": bb,
            "Stuff+": bundle["stuff_plus_value"], "Location+": bundle["location_plus_value"],
            "Pitching+": bundle["pitching_plus_value"], "Command+": command_plus_value,
            "Arsenal": arsenal_pitching_value, "Results": results_score, "Performance": performance_value,
        })

    return rows


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


def team_batting_line_for_seasons(db, season_ids):
    """Sept 2026 addition (Ryker: "add ops+ ... for hitters", OPS+
    baseline confirmed as "Team average, same season"). Pools EVERY
    batting pitch across the given season_id(s) into ONE
    game_stats.compute_batting_line() call (unlike team_hitting_lines
    above, which returns one line PER hitter) -- this is the single
    team-wide OBP/SLG an individual hitter's OPS+ is measured against,
    same union-of-our-batters/intrasquad-opponent-batters population
    team_hitting_lines uses, just not split out by player_id.

    season_ids: an iterable of Season.season_id values (a hitter's
    OPS+ baseline is pooled across every season their own filtered
    pitches touch -- see hitter_profile.py/hitter_game_report.py
    callers for how that set is built). Returns None if season_ids is
    empty/None or no pitches are found (no baseline available), so
    callers can skip showing OPS+ rather than dividing by a None SLG/
    OBP."""
    from game_stats import compute_batting_line
    if not season_ids:
        return None
    query = (
        db.query(GamePitch)
        .join(Game, GamePitch.game_id == Game.game_id)
        .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
        .filter(Game.season_id.in_(list(season_ids)))
        .filter(
            (GamePitch.is_our_team_batting.is_(True))
            | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id.isnot(None)))
        )
    )
    pitches = query.all()
    if not pitches:
        return None
    return compute_batting_line(pitches)
