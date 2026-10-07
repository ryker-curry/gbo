"""
GBO -- Hitting Leaderboard data (Oct 2026, Ryker: "create a hitters
leaderboard just like pitching staff leaderboard"; approved: coaches +
players, adjustable minimum PA (default 10), date range on both boards).

rows(db, date_from, date_to, game_scope) -> one dict per OUR hitter who
batted in the window: the box-score/rate line (game_stats.
compute_batting_line), plus stats vs 2026 D2 (league_baselines.
hitting_plus) and GBO's own charting stats (hitter_insights.core_metrics:
swing decisions, chase, whiff, zone swing, hard contact, pitches/PA,
2-strike K%). Batter = our_player_id when we bat; in intrasquads our
hitters also bat as the "opponent" (opponent_our_player_id).
None = not enough data (never 0), so sorting can push it to the bottom.
"""

from collections import defaultdict

from sqlalchemy.orm import joinedload

from models import Game, GamePitch, Player
import game_stats
from analytics import hitter_insights, league_baselines


def _query(db, date_from=None, date_to=None, game_scope="all"):
    q = (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
         .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game).selectinload(Game.pitches))
         .filter((GamePitch.is_our_team_batting.is_(True))
                 | ((GamePitch.is_our_team_batting.is_(False)) & (GamePitch.opponent_our_player_id.isnot(None)))))
    if date_from is not None:
        q = q.filter(Game.game_date >= date_from)
    if date_to is not None:
        q = q.filter(Game.game_date <= date_to)
    if game_scope == "intrasquad":
        q = q.filter(Game.is_intrasquad.is_(True))
    elif game_scope == "external":
        q = q.filter(Game.is_intrasquad.is_(False))
    return q


def _babip(line):
    ab, h, hr, k, sf = (line.get(x) or 0 for x in ("AB", "H", "HR", "K", "SF"))
    den = ab - k - hr + sf
    return round((h - hr) / den, 3) if ab and den > 0 else None


def rows(db, date_from=None, date_to=None, game_scope="all"):
    by_player = defaultdict(list)
    for p in _query(db, date_from, date_to, game_scope).order_by(GamePitch.game_id, GamePitch.pitch_sequence).all():
        pid = p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id
        if pid is not None:
            by_player[pid].append(p)
    if not by_player:
        return []
    players = {pl.player_id: pl for pl in db.query(Player).filter(Player.player_id.in_(list(by_player))).all()}
    from analytics import decision_value, decision_score, decision_floor
    dv_table = decision_value.team_table(db)
    out = []
    for pid, ps in by_player.items():
        pl = players.get(pid)
        if pl is None:
            continue
        line = game_stats.compute_batting_line(ps)
        if not line.get("PA"):
            continue
        core = hitter_insights.core_metrics(ps, dv_table)
        plus = league_baselines.hitting_plus(line)
        out.append({
            "player": pl, "Hitter": f"{pl.first_name} {pl.last_name}", "PA": line.get("PA"),
            "AVG": line.get("AVG"), "OBP": line.get("OBP"), "SLG": line.get("SLG"), "OPS": line.get("OPS"),
            "ISO": line.get("ISO"), "wOBA": line.get("wOBA"), "BABIP": _babip(line),
            "K %": line.get("K %"), "BB %": line.get("BB %"), "BB/K": line.get("BB/K"),
            "QAB %": line.get("QAB %"),
            "H": line.get("H"), "2B": line.get("2B"), "3B": line.get("3B"), "HR": line.get("HR"),
            "BB": line.get("BB"), "K": line.get("K"),
            **plus,
            "Swing Decision %": core.get("Swing Decision %"), "Chase %": core.get("Chase %"),
            "Zone Swing %": core.get("Zone Swing %"), "Whiff %": core.get("Whiff %"),
            "Hard contact %": core.get("Hard contact %"), "Pitches/PA": core.get("Pitches/PA"),
            "2-strike K %": core.get("2-strike K %"),
            "Decision RV/100": core.get("Decision RV/100"),
            **_floor_cols(decision_floor.floor(dv_table, ps)),
            "_core": core,
        })
    # Oct 2026: Decision Score among hitters with 10+ PA (analytics/decision_score.py)
    pool = {r["player"].player_id: r["_core"] for r in out if (r["PA"] or 0) >= 10}
    ds = decision_score.scores(pool)
    for r in out:
        r["Decision Score"] = ds.get(r["player"].player_id)
    return out


def _floor_cols(fl):
    """Oct 2026 (analytics/decision_floor.py): decision quality and floor."""
    return {"Decision Q %": round(fl["quality"], 1) if fl["quality"] is not None else None,
            "Decision Floor": round(fl["floor"], 1) if fl["floor"] is not None else None}
