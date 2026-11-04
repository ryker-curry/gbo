"""
GBO -- Hitting tab on Player Profile (Nov 2026, Ryker: "for hitters under
player profile they should not have a tab that says pitching, theirs
should be hitting and include useful hitting stats. one could be qab%").

Everything here comes from game charting (GamePitch rows where he was
batting) and reuses game_stats / plate_discipline -- this module only adds
the pieces those don't already have:

  Pitches / PA      every tracked pitch he saw / completed PAs
  Leadoff OBP       OBP in the true leadoff PA of a half-inning
  Productive Out %  of his outs made with a runner on base, how many moved
                    a runner up or scored one (sac bunt / sac fly always
                    count; strikeouts never do; a double play never does).
                    "Moved up" = the runners' bases + runs after the play
                    beat the bases before it.
  Game trend        QAB % and OPS game by game, with a rolling 5-game line

Hard-Hit % is the charter's contact call (Barreled/Squared Up + Solid) --
GBO has no exit velocity.
"""

from collections import OrderedDict

from game_stats import (K_OUTCOMES, _batting_slice, _group_into_plate_appearances, compute_batted_ball_profile,
                        compute_batting_line, leadoff_pas)
from plate_discipline import compute_hitter_discipline

ROLL = 5
SAC = ("Sac Bunt", "Sac Fly")

# headline cards: (label, source, key, higher is better, format)
HEADLINE = [
    ("QAB %", "line", "QAB %", True, "pct"),
    ("OBP", "line", "OBP", True, "avg"),
    ("wOBA", "line", "wOBA", True, "avg"),
    ("Hard-Hit %", "batted", "Hard Contact %", True, "pct"),
    ("K %", "line", "K %", False, "pct"),
    ("BB %", "line", "BB %", True, "pct"),
    ("Chase %", "disc", "Chase %", False, "pct"),
    ("Zone Contact %", "disc", "Zone Contact %", True, "pct"),
]


def _completed(pitches):
    pas = _group_into_plate_appearances(pitches)
    return [pa for pa in pas if pa[-1].ends_plate_appearance and pa[-1].ab_outcome != "No Result"]


def _weight(bases):
    """Sum of occupied base numbers -- "010" (runner on 2nd) = 2."""
    return sum(i + 1 for i, c in enumerate(bases or "000") if c == "1")


def productive_outs(completed_pas):
    """(productive outs, outs made with a runner on base)."""
    made, productive = 0, 0
    for pa in completed_pas:
        first, last = pa[0], pa[-1]
        bases_before = first.bases_before or last.bases_before or "000"
        if _weight(bases_before) == 0:
            continue
        outcome = last.ab_outcome or ""
        outs_made = (last.outs_after - last.outs_before) if last.outs_after is not None and last.outs_before is not None else 0
        is_out = outcome in SAC or outs_made >= 1
        if not is_out:
            continue
        made += 1
        if outcome in K_OUTCOMES:
            continue
        if outcome in SAC:
            productive += 1
            continue
        if outs_made >= 2 or outcome == "Double Play":
            continue
        runs = last.runs_scored_on_play or 0
        before = _weight(last.bases_before or bases_before)
        if runs > 0 or (last.bases_after is not None and _weight(last.bases_after) > before):
            productive += 1
    return productive, made


def _pct(n, d):
    return round(100 * n / d, 1) if d else None


def summary(pitches, bats=None):
    """Everything the Hitting tab shows for one set of pitches (a player's,
    or the team's pooled)."""
    line = compute_batting_line(pitches)
    disc = compute_hitter_discipline(pitches)
    batted = compute_batted_ball_profile(pitches, bats=bats)
    completed = _completed(pitches)
    lead = _batting_slice(leadoff_pas(completed))
    po, po_opps = productive_outs(completed)
    pa = line["PA"]
    extra = {
        "Pitches / PA": round(line["pitch_count"] / pa, 2) if pa else None,
        "Leadoff OBP": lead["OBP"], "Leadoff PA": lead["PA"],
        "Productive Outs": po, "Productive Out Opps": po_opps, "Productive Out %": _pct(po, po_opps),
    }
    for side in ("Ahead", "Even", "Behind"):
        o, s = line.get(f"{side} OBP"), line.get(f"{side} SLG")
        extra[f"{side} OPS"] = round(o + s, 3) if o is not None and s is not None else None
    return {"line": line, "disc": disc, "batted": batted, "extra": extra}


def value(s, source, key):
    return (s.get(source) or {}).get(key)


def game_trend(pitches):
    """[{"date", "game_id", "PA", "QAB %", "OPS", "roll_qab", "roll_ops"}] oldest -> newest.
    The rolling values pool the last ROLL games' plate appearances (not an
    average of per-game rates), so a 1-PA game doesn't swing it."""
    by_game = OrderedDict()
    for p in sorted(pitches, key=lambda p: (_game_date(p), p.game_id or 0, p.pitch_sequence or 0)):
        by_game.setdefault(p.game_id, []).append(p)
    rows, ids = [], list(by_game)
    for i, gid in enumerate(ids):
        ps = by_game[gid]
        ln = compute_batting_line(ps)
        if not ln["PA"]:
            continue
        window = [p for g in ids[max(0, i - ROLL + 1): i + 1] for p in by_game[g]]
        rl = compute_batting_line(window)
        rows.append({"date": _game_date(ps[0]), "game_id": gid, "PA": ln["PA"], "QAB %": ln["QAB %"], "OPS": ln["OPS"],
                     "roll_qab": rl["QAB %"], "roll_ops": rl["OPS"]})
    return rows


def _game_date(p):
    g = getattr(p, "game", None)
    return getattr(g, "game_date", None) or getattr(p, "_game_date", None) or __import__("datetime").date.min


def load(db, player, date_from=None, date_to=None):
    """(player summary, team summary, trend, pitches) for the season window.
    Team = every active position player, pooled -- the comparison group."""
    from analytics import profile_queries as pq
    pitches = pq.get_hitter_profile_pitches(db, player.player_id, date_from=date_from, date_to=date_to)
    if not pitches:
        return None, None, [], []
    mine = summary(pitches, bats=player.bats)
    from run_scorers import running_line_for   # R / SB / CS need the runner events (same as batting_line_for)
    run = running_line_for(db, player.player_id, pitches)
    mine["line"].update({"R": run["R"], "SB": run["SB"], "CS": run["CS"]})
    team_by = pq.get_team_hitting_pitches(db, date_from=date_from, date_to=date_to)
    team_pitches = [p for ps in team_by.values() for p in ps]
    team = summary(team_pitches) if team_pitches else None
    return mine, team, game_trend(pitches), pitches
