"""
GBO -- Baseball-Reference-style standard stat lines (Oct 31 2026, Ryker:
"a normal looking stat line like on a baseball reference page" for
Season Stats).

One row per season the player has Game Tracking data in, plus a Career
row (every game, any season). Columns follow B-Ref's "Standard Batting"
/ "Standard Pitching" tables in B-Ref's own order. Ryker chose to keep
the full column set and show a dash for anything GBO doesn't track yet:

  Pitching: W, L, SV (no decisions recorded), CG, SHO.
  Batting:  R, RBI, SB, CS (runner identity is optional on runner
            events and runs aren't tied to a specific runner).

Everything else is computed with the same game_stats.py functions the
rest of the page uses (pitching_line_for / compute_batting_line), so the
season row here always matches the cards below it. Two B-Ref
conventions that differ from GBO's cards, on purpose:
  - BB includes IBB (B-Ref counts intentional walks inside BB and also
    lists IBB on its own).
  - GDP counts the "Double Play" at-bat outcome.
"""

from collections import defaultdict

from models import Game, GameRunnerEvent, Season
from game_stats import (
    get_batting_pitches, get_pitching_pitches, compute_batting_line, pitching_line_for,
)
from analytics import league_baselines

DASH = "—"

PITCHING_COLUMNS = (
    "Season", "W", "L", "ERA", "G", "GS", "CG", "SHO", "SV", "IP", "H", "R", "ER", "HR",
    "BB", "IBB", "SO", "HBP", "BK", "WP", "BF", "ERA+", "FIP", "WHIP", "H9", "HR9", "BB9", "SO9", "SO/W",
)
BATTING_COLUMNS = (
    "Season", "G", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS", "BB", "SO",
    "BA", "OBP", "SLG", "OPS", "OPS+", "TB", "GDP", "HBP", "SH", "SF", "IBB",
)
# Column header tooltips (B-Ref-style abbreviations aren't obvious to everyone).
COLUMN_HELP = {
    "W": "Wins (not tracked yet)", "L": "Losses (not tracked yet)", "SV": "Saves (not tracked yet)",
    "CG": "Complete games (not tracked yet)", "SHO": "Shutouts (not tracked yet)",
    "G": "Games", "GS": "Games started", "IP": "Innings pitched", "ER": "Earned runs",
    "IBB": "Intentional walks", "SO": "Strikeouts", "HBP": "Hit by pitch", "BK": "Balks",
    "WP": "Wild pitches", "BF": "Batters faced", "ERA+": "ERA vs D2 average (100 = average, higher is better)",
    "FIP": "Fielding independent pitching", "H9": "Hits per 9", "HR9": "Home runs per 9",
    "BB9": "Walks per 9", "SO9": "Strikeouts per 9", "SO/W": "Strikeout-to-walk ratio",
    "PA": "Plate appearances", "AB": "At bats", "R": "Runs (not tracked yet)", "RBI": "Runs batted in (not tracked yet)",
    "SB": "Stolen bases (not tracked yet)", "CS": "Caught stealing (not tracked yet)",
    "BA": "Batting average", "OBP": "On-base %", "SLG": "Slugging %", "OPS": "OBP + SLG",
    "OPS+": "OPS vs D2 average (100 = average, higher is better)", "TB": "Total bases",
    "GDP": "Grounded into double play", "SH": "Sacrifice bunts", "SF": "Sacrifice flies",
}


def _f(v, d):
    return f"{v:.{d}f}" if v is not None else DASH


def _rate3(v):
    """.312 style, like B-Ref (no leading zero under 1)."""
    if v is None:
        return DASH
    s = f"{v:.3f}"
    return s[1:] if s.startswith("0.") else s


def _per9(n, ip):
    return _f(n * 9 / ip, 1) if ip else DASH


def _season_groups(db, pitches):
    """[(season_id, Season|None, [pitches])] newest season first, by the
    game each pitch belongs to."""
    game_ids = {p.game_id for p in pitches}
    if not game_ids:
        return [], {}
    games = {g.game_id: g for g in db.query(Game).filter(Game.game_id.in_(game_ids)).all()}
    by_season = defaultdict(list)
    for p in pitches:
        g = games.get(p.game_id)
        by_season[g.season_id if g else None].append(p)
    seasons = {s.season_id: s for s in db.query(Season).filter(Season.season_id.in_([k for k in by_season if k is not None])).all()}

    def sort_key(sid):
        s = seasons.get(sid)
        if s is None:
            return (0, "")
        return (1, s.start_date.isoformat() if s.start_date else "", s.season_name)
    ordered = sorted(by_season, key=sort_key, reverse=True)
    return [(sid, seasons.get(sid), by_season[sid]) for sid in ordered], games


def _season_label(season):
    if season is None:
        return "No season"
    return season.season_name + ("" if season.is_official else "*")


def _wp_bk_counts(db, player_id, pitches):
    """Wild pitches / balks charged to this pitcher: runner events logged
    right after one of HIS pitches (pitch_sequence_after = his last
    pitch). One WP that moves two runners is two runner events but one
    WP, so it's counted once per (game, pitch, type)."""
    game_ids = {p.game_id for p in pitches}
    if not game_ids:
        return 0, 0
    his = {(p.game_id, p.pitch_sequence) for p in pitches}
    events = db.query(GameRunnerEvent).filter(
        GameRunnerEvent.game_id.in_(game_ids),
        GameRunnerEvent.event_type.in_(("Wild Pitch", "Balk")),
    ).all()
    seen = {(e.game_id, e.pitch_sequence_after, e.event_type) for e in events
            if (e.game_id, e.pitch_sequence_after) in his}
    wp = sum(1 for k in seen if k[2] == "Wild Pitch")
    bk = sum(1 for k in seen if k[2] == "Balk")
    return wp, bk


def _starts(player_id, games, game_ids):
    n = 0
    for gid in game_ids:
        g = games.get(gid)
        if g is not None and player_id in (
            g.starting_pitcher_id, getattr(g, "squad_b_starting_pitcher_id", None), getattr(g, "squad_c_starting_pitcher_id", None),
        ):
            n += 1
    return n


def _pitching_row(db, player_id, label, pitches, games):
    line = pitching_line_for(db, player_id, pitches)
    ip = line.get("IP (decimal)") or 0
    wp, bk = _wp_bk_counts(db, player_id, pitches)
    game_ids = {p.game_id for p in pitches}
    plus = league_baselines.pitching_plus(line)
    era_plus = plus.get("ERA+")
    k, bb = line["K"], line["BB"] + (line.get("IBB") or 0)   # B-Ref BB (incl. IBB) for BB, BB9, SO/W
    return {
        "Season": label, "W": DASH, "L": DASH, "ERA": _f(line.get("ERA"), 2),
        "G": str(len(game_ids)), "GS": str(_starts(player_id, games, game_ids)),
        "CG": DASH, "SHO": DASH, "SV": DASH,
        "IP": str(line["IP"]), "H": str(line["H Allowed"]), "R": str(line["Runs Allowed"]),
        "ER": str(line["ER Allowed"]), "HR": str(line["HR Allowed"]),
        "BB": str(bb), "IBB": str(line.get("IBB") or 0), "SO": str(k),
        "HBP": str(line["HBP"]), "BK": str(bk), "WP": str(wp), "BF": str(line["Batters Faced"]),
        "ERA+": str(era_plus) if era_plus is not None else DASH,
        "FIP": _f(line.get("FIP"), 2), "WHIP": _f(line.get("WHIP"), 3),
        "H9": _per9(line["H Allowed"], ip), "HR9": _per9(line["HR Allowed"], ip),
        "BB9": _per9(bb, ip), "SO9": _per9(k, ip),
        "SO/W": _f(k / bb, 2) if bb else DASH,
    }


def _completed_pa_endings(pitches):
    return [p for p in pitches if p.ends_plate_appearance and p.ab_outcome not in (None, "No Result")]


def _batting_row(label, pitches):
    line = compute_batting_line(pitches)
    plus = league_baselines.hitting_plus(line)
    ops_plus = plus.get("OPS+")
    endings = _completed_pa_endings(pitches)
    tb = line["1B"] + 2 * line["2B"] + 3 * line["3B"] + 4 * line["HR"]
    return {
        "Season": label, "G": str(len({p.game_id for p in pitches})),
        "PA": str(line["PA"]), "AB": str(line["AB"]), "R": DASH, "H": str(line["H"]),
        "2B": str(line["2B"]), "3B": str(line["3B"]), "HR": str(line["HR"]),
        "RBI": DASH, "SB": DASH, "CS": DASH,
        "BB": str(line["BB"] + (line.get("IBB") or 0)), "SO": str(line["K"]),
        "BA": _rate3(line.get("AVG")), "OBP": _rate3(line.get("OBP")), "SLG": _rate3(line.get("SLG")),
        "OPS": _rate3(line.get("OPS")), "OPS+": str(ops_plus) if ops_plus is not None else DASH,
        "TB": str(tb), "GDP": str(sum(1 for p in endings if p.ab_outcome == "Double Play")),
        "HBP": str(line["HBP"]), "SH": str(sum(1 for p in endings if p.ab_outcome == "Sac Bunt")),
        "SF": str(line.get("SF") or 0), "IBB": str(line.get("IBB") or 0),
    }


def pitching_stat_rows(db, player_id):
    """(season_rows, career_row, season_ids_in_row_order) or ([], None, [])."""
    pitches = get_pitching_pitches(db, player_id, None)
    groups, games = _season_groups(db, pitches)
    if not groups:
        return [], None, []
    rows = [_pitching_row(db, player_id, _season_label(s), ps, games) for _sid, s, ps in groups]
    career = _pitching_row(db, player_id, "Career", pitches, games)
    return rows, career, [sid for sid, _s, _ps in groups]


def batting_stat_rows(db, player_id):
    pitches = get_batting_pitches(db, player_id, None)
    groups, _games = _season_groups(db, pitches)
    if not groups:
        return [], None, []
    rows = [_batting_row(_season_label(s), ps) for _sid, s, ps in groups]
    career = _batting_row("Career", pitches)
    return rows, career, [sid for sid, _s, _ps in groups]
