"""
GBO -- DB-touching counterpart to workload_metrics.py, kept in a
separate file on purpose so workload_metrics.py itself stays pure (no
DB/Streamlit dependency), matching the project's usual split between
computation and data access.

get_daily_pitch_counts() resolves the one thing workload_metrics.py's
compute_daily_acwr() needs from the database: a {date: total_pitches}
dict for one player, covering both bullpens and games/scrimmages, with
the max-across-three-tables rule applied per bullpen session (see
workload_metrics.py's module docstring for why summing would be
wrong). Also returns a per-player tracking_start_date, since that has
to be a real "first date this player had ANY record in GBO" -- not
just the earliest date with a nonzero pitch count -- or an early rest
day would get miscounted as "not yet tracked" instead of a real zero
(see compute_daily_acwr's docstring on the difference).
"""

from sqlalchemy import func

from models import Game, GamePitch, BullpenSession, BullpenPitch, RapsodoPitch, CommandPitch


def _game_pitch_dates(session, player_id, start_date=None, end_date=None):
    """One row per pitch this player THREW in a tracked game or
    intrasquad scrimmage -- same is_our_team_batting/opponent_our_player_id
    convention as game_stats.py's get_pitching_pitches (kept here as a
    lightweight date-only query instead of reusing that function
    directly, since we only need game_date per pitch, not full
    GamePitch/pitch_type objects)."""
    query = (
        session.query(Game.game_date)
        .join(Game, GamePitch.game_id == Game.game_id)
        .filter(
            ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == player_id))
            | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == player_id))
        )
    )
    if start_date is not None:
        query = query.filter(Game.game_date >= start_date)
    if end_date is not None:
        query = query.filter(Game.game_date <= end_date)
    return [row[0] for row in query.all()]


def _bullpen_session_pitch_counts(session, player_id, start_date=None, end_date=None):
    """One (session_date, pitch_count) pair per BullpenSession for this
    player, pitch_count = max(BullpenPitch rows, RapsodoPitch rows,
    CommandPitch rows) for that session -- see module docstring."""
    sessions_query = session.query(BullpenSession.bullpen_id, BullpenSession.session_date).filter(
        BullpenSession.player_id == player_id
    )
    if start_date is not None:
        sessions_query = sessions_query.filter(BullpenSession.session_date >= start_date)
    if end_date is not None:
        sessions_query = sessions_query.filter(BullpenSession.session_date <= end_date)
    sessions = sessions_query.all()
    if not sessions:
        return []

    bullpen_ids = [s.bullpen_id for s in sessions]

    def _counts_by_bullpen(model, pk_column):
        rows = (
            session.query(model.bullpen_id, func.count(pk_column))
            .filter(model.bullpen_id.in_(bullpen_ids))
            .group_by(model.bullpen_id)
            .all()
        )
        return dict(rows)

    bp_counts = _counts_by_bullpen(BullpenPitch, BullpenPitch.bullpen_pitch_id)
    rp_counts = _counts_by_bullpen(RapsodoPitch, RapsodoPitch.rapsodo_pitch_id)
    cp_counts = _counts_by_bullpen(CommandPitch, CommandPitch.command_pitch_id)

    results = []
    for s in sessions:
        count = max(bp_counts.get(s.bullpen_id, 0), rp_counts.get(s.bullpen_id, 0), cp_counts.get(s.bullpen_id, 0))
        results.append((s.session_date, count))
    return results


def get_daily_pitch_counts(session, player_id, start_date=None, end_date=None):
    """Returns (daily_pitch_counts, tracking_start_date):

      daily_pitch_counts: dict[date -> int], summed across every
      bullpen session AND every game/scrimmage pitch on that date.
      Sparse -- a date with zero total pitches simply isn't a key
      (compute_daily_acwr treats any date within its tracked range
      but missing from this dict as a real 0, so this is safe; only
      dates before tracking_start_date are treated as unknown).

      tracking_start_date: the earliest date this player has ANY
      record in GBO -- earliest BullpenSession.session_date or
      Game.game_date, whichever is first, ignoring start_date/end_date
      (a real history boundary shouldn't be clipped by the display
      window being requested). None if this player has no records at
      all yet.

    Pass both straight into workload_metrics.compute_daily_acwr()."""
    game_dates = _game_pitch_dates(session, player_id, start_date, end_date)
    bullpen_rows = _bullpen_session_pitch_counts(session, player_id, start_date, end_date)

    daily_counts = {}
    for d in game_dates:
        daily_counts[d] = daily_counts.get(d, 0) + 1
    for d, count in bullpen_rows:
        daily_counts[d] = daily_counts.get(d, 0) + count

    earliest_game = session.query(func.min(Game.game_date)).join(
        GamePitch, GamePitch.game_id == Game.game_id
    ).filter(
        ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.our_player_id == player_id))
        | ((GamePitch.is_our_team_batting.is_(True)) & (GamePitch.opponent_our_player_id == player_id))
    ).scalar()
    earliest_bullpen = session.query(func.min(BullpenSession.session_date)).filter(
        BullpenSession.player_id == player_id
    ).scalar()
    candidates = [d for d in (earliest_game, earliest_bullpen) if d is not None]
    tracking_start_date = min(candidates) if candidates else None

    return daily_counts, tracking_start_date
