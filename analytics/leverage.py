"""
GBO -- Run leverage (Oct 2026, from Luke VanHouten's "Grasping the
Clutch: Leverage Index").

Tango's Leverage Index measures how much a plate appearance can swing WIN
expectancy. That needs a win-expectancy table for our level, which we
don't have, and borrowing MLB's would be wrong for D2 scoring -- so this
is GBO's own, simpler version (labeled "run leverage", never "LI"):

  RUN LEVERAGE of a PA = how much PAs that start in the same outs / bases
  state swing runs on our charted games -- the average |PA run value|
  (GamePitch.run_value summed over the PA) in that state, divided by the
  average over all PAs. 1.0 = an average spot; bases loaded, 2 outs runs
  well above 1. Each state is pulled toward 1.0 by SHRINK PAs.

  LATE & CLOSE: the PA came in the LATE_INNING or later with the batting
  side within CLOSE_RUNS (score rebuilt from runs scored on each pitch).

  HIGH LEVERAGE = run leverage >= HIGH or late & close.

Descriptive context only: the article found clutch performance doesn't
predict anything, and our samples are small.
"""

from collections import defaultdict

SHRINK = 10
HIGH = 1.5
LATE_INNING = 7
CLOSE_RUNS = 2
_cache = {"key": None, "table": None}


def _batter(p):
    return p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id


def all_pas(pitches):
    """Group every charted pitch into PAs (same game, same batter, consecutive)."""
    ps = sorted(pitches, key=lambda p: (p.game_id, p.pitch_sequence))
    pas, cur = [], []
    for p in ps:
        if cur and (p.game_id != cur[-1].game_id or cur[-1].ends_plate_appearance or p.pa_pitch_number == 1
                    or _batter(p) != _batter(cur[-1]) or p.is_our_team_batting != cur[-1].is_our_team_batting):
            pas.append(cur)
            cur = []
        cur.append(p)
    if cur:
        pas.append(cur)
    return pas


def _state(pa):
    p = pa[0]
    if p.outs_before is None or p.bases_before is None:
        return None
    return (p.outs_before, p.bases_before)


def build_table(pitches):
    sums = defaultdict(lambda: [0.0, 0])
    tot, n = 0.0, 0
    for pa in all_pas(pitches):
        if not pa[-1].ends_plate_appearance:
            continue
        rv = [float(p.run_value) for p in pa if p.run_value is not None]
        st = _state(pa)
        if not rv or st is None:
            continue
        a = abs(sum(rv))
        sums[st][0] += a
        sums[st][1] += 1
        tot += a
        n += 1
    if not n or tot == 0:
        return {}
    avg = tot / n
    # each state's mean |RV| / overall mean, pulled toward 1.0 by SHRINK PAs
    return {st: (s / avg + SHRINK * 1.0) / (c + SHRINK) for st, (s, c) in sums.items()}


def team_table(db):
    from sqlalchemy import func
    from models import GamePitch
    key = (id(db.get_bind()), db.query(func.count(GamePitch.game_pitch_id)).scalar(),
           db.query(func.max(GamePitch.game_pitch_id)).scalar())
    if _cache["key"] == key and _cache["table"] is not None:
        return _cache["table"]
    table = build_table(db.query(GamePitch).filter(GamePitch.run_value.isnot(None)).all())
    _cache.update(key=key, table=table)
    return table


def score_before(game_pitches):
    """{game_pitch_id: (batting_runs, fielding_runs)} before each pitch, one game."""
    runs = {True: 0, False: 0}
    out = {}
    for p in sorted(game_pitches, key=lambda p: p.pitch_sequence):
        side = bool(p.is_our_team_batting)
        out[p.game_pitch_id] = (runs[side], runs[not side])
        runs[side] += p.runs_scored_on_play or 0
    return out


def pa_context(pa, table, scores):
    """-> {"lev", "late_close", "high", "inning", "diff"}"""
    st = _state(pa)
    lev = table.get(st, 1.0) if st is not None else None
    sc = scores.get(pa[0].game_pitch_id)
    diff = (sc[0] - sc[1]) if sc else None
    inning = pa[0].inning
    late_close = bool(inning is not None and inning >= LATE_INNING and diff is not None and abs(diff) <= CLOSE_RUNS)
    return {"lev": lev, "late_close": late_close, "high": (lev is not None and lev >= HIGH) or late_close,
            "inning": inning, "diff": diff}


def describe(ctx):
    if ctx["lev"] is None:
        return "—"
    tag = "high" if ctx["lev"] >= HIGH else ("low" if ctx["lev"] < 0.7 else "normal")
    s = f"Run leverage {ctx['lev']:.1f} ({tag})"
    if ctx["late_close"]:
        s += " · late & close"
    return s
