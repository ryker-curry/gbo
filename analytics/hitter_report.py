"""
GBO -- Hitter Meeting Report data (Oct 2026, Ryker: "build 4-7" -> #5, a
one-page printable sheet for a hitter to go through with a coach, the
hitting twin of analytics/player_report.py). game_report() / season_report()
return plain dicts for visualizations/hitter_report_sheet.py.

Comparisons: "You" (this game or season) vs a reference column (season
to date for a game report, last 3 games for a season report) vs the team
average (all active hitters, same season). Marks: good / ok / bad vs the
team using each metric's scale; nothing is marked under MIN_PA.
"""

from collections import defaultdict

from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from models import Game, GamePitch, Player, Season
from analytics import hitter_insights as hi, hitter_hot_zones as hz
from analytics.player_report import idp_goals
from game_stats import get_pitcher_hands

MIN_PA = 4

# key, label, plain meaning, higher-is-better, scale for a 'clear' gap, kind
METRICS = [
    ("AVG", "AVG", "Hits per at-bat", True, 0.040, "avg"),
    ("OBP", "OBP", "How often you reach base", True, 0.040, "avg"),
    ("SLG", "SLG", "Total bases per at-bat", True, 0.070, "avg"),
    ("Swing Decision %", "Swing decisions", "Swung at strikes, took balls", True, 5.0, "%"),
    ("Chase %", "Chase %", "Swings at pitches off the plate", False, 5.0, "%"),
    ("Whiff %", "Whiff %", "Misses per swing", False, 5.0, "%"),
    ("K%", "Strikeout %", "Strikeouts per plate appearance", False, 5.0, "%"),
    ("BB%", "Walk %", "Walks per plate appearance", True, 3.0, "%"),
    ("Hard contact %", "Hard contact %", "Barreled/solid per ball in play", True, 8.0, "%"),
    ("Pitches/PA", "Pitches per PA", "Makes the pitcher work", True, 0.3, "num"),
]


def _batter_filter(player_id):
    return or_(
        and_(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == player_id),
        and_(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id == player_id),
    )


def hitter_pitches(db, player_id, season_id=None, game_id=None):
    q = (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
         .options(joinedload(GamePitch.pitch_type)).filter(_batter_filter(player_id)))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    if game_id is not None:
        q = q.filter(GamePitch.game_id == game_id)
    return q.order_by(Game.game_date, GamePitch.pitch_sequence).all()


def hitter_games(db, player_id, season_id=None):
    ids = {gid for (gid,) in db.query(GamePitch.game_id).filter(_batter_filter(player_id)).distinct().all()}
    if not ids:
        return []
    q = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id.in_(ids))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    return q.order_by(Game.game_date.desc(), Game.game_id.desc()).all()


def team_hitting(db, season_id):
    """{player_id: pitches} for active non-pitchers in this season."""
    hitter_ids = [pid for (pid,) in db.query(Player.player_id)
                  .filter(Player.active.is_(True), Player.is_pitcher.is_(False)).all()]
    if not hitter_ids:
        return {}
    q = (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
         .options(joinedload(GamePitch.pitch_type))
         .filter(or_(and_(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id.in_(hitter_ids)),
                     and_(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id.in_(hitter_ids)))))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    out = defaultdict(list)
    for p in q.all():
        out[p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id].append(p)
    return out


def team_average(team_by_player):
    """Plain average of each metric across hitters with MIN_PA+ PAs."""
    per = [hi.core_metrics(ps) for ps in team_by_player.values()]
    per = [m for m in per if (m["PA"] or 0) >= MIN_PA]
    out = {}
    for key, *_ in METRICS:
        vals = [m[key] for m in per if m.get(key) is not None]
        out[key] = sum(vals) / len(vals) if vals else None
    return out


def _mark(you, team, hib, scale, pa):
    if you is None or team is None or (pa or 0) < MIN_PA:
        return None
    diff = (you - team) / scale
    if not hib:
        diff = -diff
    return "good" if diff >= 1 else "bad" if diff <= -1 else "ok"


def key_rows(you, ref, team):
    rows = []
    for key, label, means, hib, scale, kind in METRICS:
        y = you.get(key)
        rows.append({"key": key, "label": label, "means": means, "kind": kind, "you": y,
                     "ref": ref.get(key) if ref else None, "team": team.get(key),
                     "mark": _mark(y, team.get(key), hib, scale, you.get("PA")),
                     "diff": None if y is None or team.get(key) is None else ((y - team[key]) / scale) * (1 if hib else -1)})
    return rows


def _fmtv(kind, v):
    if v is None:
        return "—"
    if kind == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0") else s
    if kind == "%":
        return f"{v:.0f}%"
    return f"{v:.1f}"


def takeaways(rows, pt_res, sd, pa):
    good, bad = [], []
    for r in sorted([r for r in rows if r["mark"] in ("good", "bad")], key=lambda r: -abs(r["diff"] or 0)):
        txt = f"{r['label']}: {_fmtv(r['kind'], r['you'])} (team {_fmtv(r['kind'], r['team'])})"
        if r["mark"] == "good" and len(good) < 3:
            good.append(txt + " -- keep doing that.")
        elif r["mark"] == "bad" and len(bad) < 3:
            bad.append(txt + ".")
    for line in hi.pitch_type_takeaways(pt_res, min_seen=10):
        (good if "damage" in line else bad).append(line)
    c = sd["counts"]
    if (pa or 0) >= MIN_PA and c["Taken strike"] >= 3 and (sd["heart_take_pct"] or 0) >= 25:
        bad.append(f"Took {c['Taken strike']} hittable strikes -- be ready to hit early.")
    if not good:
        good.append("Small sample -- keep stacking quality at-bats.")
    if not bad:
        bad.append("Nothing stands out as a problem -- keep the same approach.")
    return good[:4], bad[:4]


_ABBR = {"4-Seam Fastball": "FB", "Fastball": "FB", "2-Seam Fastball": "2S", "Sinker": "SI", "Cutter": "CT",
         "Slider": "SL", "Sweeper": "SW", "Curveball": "CB", "Changeup": "CH", "Splitter": "SP"}


def _abbr(p):
    name = p.pitch_type.type_name if p.pitch_type else None
    if name is None:
        return "?"
    return _ABBR.get(name, name[:2].upper())


def pa_log(pitches, db):
    """One line per PA for a game report."""
    phands = get_pitcher_hands(db, pitches)
    out = []
    for pa in hi.plate_appearances(pitches):
        last = pa[-1]
        seq = " ".join(_abbr(p) +
                       {"Ball": "b", "Called Strike": "k", "Swing and Miss": "s", "Foul": "f", "In Play": "x",
                        "HBP": "h"}.get(p.pitch_outcome or "", "") for p in pa)
        out.append({"inning": last.inning, "hand": phands.get(last.game_pitch_id),
                    "count": f"{last.balls_before}-{last.strikes_before}",
                    "result": last.ab_outcome if last.ends_plate_appearance else "(inning ended)",
                    "pitches": len(pa), "seq": seq, "quality": last.contact_quality})
    return out


def _bundle(db, pitches):
    sd = hi.swing_decisions(pitches)
    pt = hi.pitch_type_results(db, pitches)
    prof = hi.attack_profile(db, pitches)
    fp = hi.first_pitch_two_strike(pitches)
    return {"core": hi.core_metrics(pitches), "sd": sd, "pt": pt, "attack": prof,
            "attack_lines": hi.attack_takeaways(prof), "fp": fp}


def game_report(db, player_id, game_id):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == game_id).first()
    if player is None or game is None:
        return None
    mine = hitter_pitches(db, player_id, game_id=game_id)
    if not mine:
        return None
    season = hitter_pitches(db, player_id, season_id=game.season_id) if game.season_id is not None else mine
    b = _bundle(db, mine)
    sb = _bundle(db, season)  # zones / attack / pitch type need the bigger sample
    team = team_average(team_hitting(db, game.season_id))
    rows = key_rows(b["core"], sb["core"], team)
    good, bad = takeaways(rows, sb["pt"], b["sd"], b["core"]["PA"])
    return {"kind": "game", "player": player, "game": game, "season_id": game.season_id,
            "you": b["core"], "ref_label": "Season", "rows": rows, "good": good, "bad": bad,
            "sd": b["sd"], "zones": hz.hot_zones(season), "zones_label": "season to date",
            "pt": sb["pt"], "attack_lines": sb["attack_lines"], "fp": sb["fp"],
            "pa_log": pa_log(mine, db), "goals": idp_goals(db, player_id), "game_log": None}


def season_report(db, player_id, season_id):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if player is None:
        return None
    pitches = hitter_pitches(db, player_id, season_id=season_id)
    if not pitches:
        return None
    games = hitter_games(db, player_id, season_id=season_id)
    last3_ids = {g.game_id for g in games[:3]}
    last3 = hi.core_metrics([p for p in pitches if p.game_id in last3_ids]) if len(games) > 3 else None
    b = _bundle(db, pitches)
    team = team_average(team_hitting(db, season_id))
    rows = key_rows(b["core"], last3, team)
    good, bad = takeaways(rows, b["pt"], b["sd"], b["core"]["PA"])
    by_game = defaultdict(list)
    for p in pitches:
        by_game[p.game_id].append(p)
    log = [{"game": g, **hi.core_metrics(by_game[g.game_id])} for g in games[:6]]
    season = db.query(Season).filter(Season.season_id == season_id).first() if season_id is not None else None
    return {"kind": "season", "player": player, "game": None, "season_id": season_id,
            "season_name": season.season_name if season else "All games", "games": len(games),
            "you": b["core"], "ref_label": "Last 3 games", "rows": rows, "good": good, "bad": bad,
            "sd": b["sd"], "zones": hz.hot_zones(pitches), "zones_label": None,
            "pt": b["pt"], "attack_lines": b["attack_lines"], "fp": b["fp"],
            "pa_log": None, "goals": idp_goals(db, player_id), "game_log": log}


def range_report(db, player_id, game_ids, label):
    """Oct 2026 (Team Game Report): season-style hitter sheet for any set of
    games (a series or custom dates). Comparison column = his whole
    season; team column = our hitters over these same games."""
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if player is None or not game_ids:
        return None
    ids = set(game_ids)
    pitches = [p for p in hitter_pitches(db, player_id) if p.game_id in ids]
    if not pitches:
        return None
    games = [g for g in hitter_games(db, player_id) if g.game_id in ids]
    season_id = next((g.season_id for g in games if g.season_id), None)
    season_all = hitter_pitches(db, player_id, season_id=season_id) if season_id is not None else None
    b = _bundle(db, pitches)
    team_by = team_hitting(db, season_id)
    team_by = {pid: [p for p in ps if p.game_id in ids] for pid, ps in team_by.items()}
    team = team_average({k: v for k, v in team_by.items() if v})
    rows = key_rows(b["core"], hi.core_metrics(season_all) if season_all else None, team)
    good, bad = takeaways(rows, b["pt"], b["sd"], b["core"]["PA"])
    by_game = defaultdict(list)
    for p in pitches:
        by_game[p.game_id].append(p)
    log = [{"game": g, **hi.core_metrics(by_game[g.game_id])} for g in games[:6]]
    return {"kind": "season", "player": player, "game": None, "season_id": season_id,
            "season_name": label, "games": len(games),
            "you": b["core"], "ref_label": "His season", "rows": rows, "good": good, "bad": bad,
            "sd": b["sd"], "zones": hz.hot_zones(pitches), "zones_label": None,
            "pt": b["pt"], "attack_lines": b["attack_lines"], "fp": b["fp"],
            "pa_log": None, "goals": idp_goals(db, player_id), "game_log": log}
