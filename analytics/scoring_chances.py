"""
GBO -- Runs per Scoring Chance (Nov 2026, Ryker, from PEAR Ratings'
"2026 D1 Baseball: Runs per Scoring Chance" chart: "can we make it into
an individualized stat?").

A SCORING CHANCE is a half-inning in which a runner reached 2nd or 3rd,
or a run scored (PEAR's definition). R/Chance = runs in those
half-innings / number of them.

  Team offense   every half-inning our hitters batted (outside games:
                 our half; intrasquads: both halves -- everyone is ours).
  Pitching staff every half-inning our pitchers pitched (outside games:
                 their half; intrasquads: both halves). Lower is better.

Individual versions (Ryker's choices, Nov 23 2026):

  Pitcher  a chance = a half-inning where he threw a pitch with a runner
           on 2nd or 3rd, or a run charged to him scored. Runs are
           charged to the pitcher who put that runner on (the earned-run
           rule), not whoever was on the mound when he scored -- so an
           inherited runner a reliever lets in counts against the man
           who put him on, and the reliever's own chance still counts
           (with 0 runs if he got out of it). Done by replaying each game
           with run_scorers.walk_game(), carrying a (pitcher, PA) token on
           each base instead of the runner's identity.
  Hitter   a RISP PA = a plate appearance with a runner on 2nd or 3rd at
           any pitch of it. Runs = runs that scored on the play that
           ended it (a run on a steal / wild pitch mid-at-bat isn't his).
           RISP RE24 = the run value he added in those PAs (MIAA run
           expectancy, game_pitches.run_value) -- the better read, since
           R/RISP PA credits a sac fly the same as a 3-run double.

Runs include runner-event runs (steals home, wild pitches, balks...) and
the runs a coach's "End half-inning early" sweeps home, so team totals
match the scoreboard. Not adjusted for opponent.
"""

from collections import defaultdict

from gbo_cache import cached
from run_scorers import walk_game

MIN_PITCHER_CHANCES = 3   # below this: shown, flagged small sample, left off the scatter
MIN_HITTER_RISP_PA = 5


def _risp(bases):
    b = (bases or "000") + "000"
    return b[1] == "1" or b[2] == "1"


def pitcher_of(p):
    """Our pitcher on this pitch, or None (an outside team's pitcher)."""
    if not p.is_our_team_batting:
        return p.our_player_id
    return p.opponent_our_player_id   # intrasquad: the "other" side is ours too


def batter_id_of(p):
    """Our hitter on this pitch, or None (an outside team's hitter)."""
    if p.is_our_team_batting:
        return p.our_player_id
    return p.opponent_our_player_id


def _half_key(game_id, inning, our_batting, squad):
    return (game_id, inning, bool(our_batting), squad or None)


def _rate(n, d, nd=2):
    return round(n / d, nd) if d else None


def _pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def _load(db, date_from, date_to, game_scope):
    from models import Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd
    cols = (GamePitch.game_pitch_id, GamePitch.game_id, GamePitch.pitch_sequence, GamePitch.inning,
            GamePitch.is_our_team_batting, GamePitch.batting_squad, GamePitch.bases_before,
            GamePitch.bases_after, GamePitch.outs_after, GamePitch.ends_plate_appearance,
            GamePitch.ab_outcome, GamePitch.runs_scored_on_play, GamePitch.run_value,
            GamePitch.our_player_id, GamePitch.opponent_our_player_id, GamePitch.opponent_player_id,
            Game.is_intrasquad)
    q = db.query(*cols).join(Game, Game.game_id == GamePitch.game_id)
    if date_from:
        q = q.filter(Game.game_date >= date_from)
    if date_to:
        q = q.filter(Game.game_date <= date_to)
    if game_scope == "intrasquad":
        q = q.filter(Game.is_intrasquad.is_(True))
    elif game_scope == "external":
        q = q.filter(Game.is_intrasquad.is_(False))
    by_game = defaultdict(list)
    for r in q.all():
        by_game[r.game_id].append(r)
    gids = list(by_game)
    ev, fe = defaultdict(list), defaultdict(list)
    if gids:
        for e in db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id.in_(gids)).all():
            ev[e.game_id].append(e)
        for f in db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id.in_(gids)).all():
            fe[f.game_id].append(f)
    return by_game, ev, fe


def _event_half(e, ps_sorted, by_seq):
    """Half-inning a runner event belongs to: its anchor pitch's inning when
    that pitch is the same side, else the next pitch of that side."""
    side = (bool(e.is_our_team_batting), e.batting_squad or None)
    anchor = by_seq.get(e.pitch_sequence_after)
    if anchor is not None and (bool(anchor.is_our_team_batting), anchor.batting_squad or None) == side:
        return _half_key(e.game_id, anchor.inning, *side), anchor
    for p in ps_sorted:
        if p.pitch_sequence > (e.pitch_sequence_after or 0) and \
                (bool(p.is_our_team_batting), p.batting_squad or None) == side:
            return _half_key(e.game_id, p.inning, *side), None
    if anchor is not None:
        return _half_key(e.game_id, anchor.inning, *side), None
    return None, None


@cached("scoring_chances", {"game_pitches", "game_runner_events", "game_forced_half_inning_ends", "games"})
def scoring_chances(db, date_from=None, date_to=None, game_scope="all"):
    """-> {"team": {"offense": {...}, "staff": {...}},
           "pitchers": {player_id: {...}}, "hitters": {player_id: {...}}}"""
    return compute(*_load(db, date_from, date_to, game_scope))


def compute(by_game, ev, fe):
    """Pure part (no DB) -- by_game {game_id: [pitch rows]}, ev/fe
    {game_id: [runner events / forced ends]}. Pitch rows need the
    GamePitch columns _load() selects plus is_intrasquad."""
    halves = {}                       # key -> {"intrasquad", "our_batting", "chance", "runs"}
    p_halves = defaultdict(set)       # pitcher -> {half keys he pitched in}
    p_risp = defaultdict(set)         # pitcher -> {half keys he pitched with RISP}
    p_runs = defaultdict(lambda: defaultdict(int))   # pitcher -> half -> runs charged
    hit = defaultdict(lambda: {"pa": 0, "risp_pa": 0, "risp_runs": 0, "risp_pa_scored": 0, "risp_re24": 0.0})

    def half(key, intrasquad):
        h = halves.get(key)
        if h is None:
            h = halves[key] = {"intrasquad": bool(intrasquad), "our_batting": key[2], "chance": False, "runs": 0}
        return h

    for gid, ps in by_game.items():
        ps = sorted(ps, key=lambda p: p.pitch_sequence)
        intrasquad = bool(ps[0].is_intrasquad)
        by_id = {p.game_pitch_id: p for p in ps}
        by_seq = {p.pitch_sequence: p for p in ps}
        key_of = {p.game_pitch_id: _half_key(gid, p.inning, p.is_our_team_batting, p.batting_squad) for p in ps}

        # -- half-innings: chance flags + pitcher appearances
        for p in ps:
            k = key_of[p.game_pitch_id]
            h = half(k, intrasquad)
            if _risp(p.bases_before) or ((p.outs_after or 0) < 3 and p.ends_plate_appearance and _risp(p.bases_after)):
                h["chance"] = True
            pid = pitcher_of(p)
            if pid:
                p_halves[pid].add(k)
                if _risp(p.bases_before):
                    p_risp[pid].add(k)
        ev_half = {}
        for e in ev.get(gid, []):
            k, anchor = _event_half(e, ps, by_seq)
            if k is None:
                continue
            ev_half[e.runner_event_id] = (k, anchor)
            if not e.is_out and e.to_base in (2, 3):
                half(k, intrasquad)["chance"] = True

        # -- runs, charged to the pitcher responsible for the runner
        def token(p):
            return ("pa", pitcher_of(p), p.game_pitch_id)

        res = walk_game(ps, ev.get(gid, []), fe.get(gid, []), None, batter_fn=token, honor_named=False)
        fe_by_id = {f.forced_end_id: f for f in fe.get(gid, [])}
        for kind, ref, who, _inferred in res["scored"]:
            if kind == "pitch":
                p = by_id.get(ref)
                if p is None:
                    continue
                k, mound = key_of[ref], pitcher_of(p)
            elif kind == "event":
                k, anchor = ev_half.get(ref, (None, None))
                if k is None:
                    continue
                mound = pitcher_of(anchor) if anchor is not None else None
            else:
                f = fe_by_id.get(ref)
                if f is None:
                    continue
                k = _half_key(gid, f.inning, f.is_our_team_batting, f.batting_squad)
                anchor = by_seq.get(f.pitch_sequence_after)
                mound = f.credited_player_id or (pitcher_of(anchor) if anchor is not None else None)
            h = half(k, intrasquad)
            h["runs"] += 1
            h["chance"] = True
            charged = who[1] if (isinstance(who, tuple) and len(who) == 3 and who[0] == "pa" and who[1]) else mound
            if charged:
                p_runs[charged][k] += 1

        # -- hitters: plate appearances
        cur, cur_key = [], None
        for p in ps:
            k = key_of[p.game_pitch_id]
            if k != cur_key:
                cur, cur_key = [], k
            cur.append(p)
            if not p.ends_plate_appearance:
                continue
            pa, cur = cur, []
            if p.ab_outcome in (None, "No Result"):
                continue
            bid = batter_id_of(p)
            if not bid:
                continue
            s = hit[bid]
            s["pa"] += 1
            if any(_risp(x.bases_before) for x in pa):
                runs = p.runs_scored_on_play or 0
                s["risp_pa"] += 1
                s["risp_runs"] += runs
                s["risp_pa_scored"] += 1 if runs > 0 else 0
                s["risp_re24"] += sum(float(x.run_value or 0) for x in pa)

    # -- team
    def team_side(keys):
        ks = [halves[k] for k in keys]
        ch = [h for h in ks if h["chance"]]
        runs = sum(h["runs"] for h in ch)
        return {"half_innings": len(ks), "chances": len(ch), "chance_pct": _pct(len(ch), len(ks)),
                "runs": runs, "r_per_chance": _rate(runs, len(ch)),
                "zero_pct": _pct(sum(1 for h in ch if h["runs"] == 0), len(ch)),
                "multi_pct": _pct(sum(1 for h in ch if h["runs"] >= 2), len(ch))}

    team = {
        "offense": team_side([k for k, h in halves.items() if h["our_batting"] or h["intrasquad"]]),
        "staff": team_side([k for k, h in halves.items() if (not h["our_batting"]) or h["intrasquad"]]),
    }

    pitchers = {}
    for pid, ks in p_halves.items():
        chance_keys = set(p_risp[pid]) | {k for k, r in p_runs[pid].items() if r > 0}
        runs = sum(p_runs[pid].values())
        n = len(chance_keys)
        pitchers[pid] = {
            "innings": len(ks), "chances": n, "chance_pct": _pct(n, len(ks)), "runs": runs,
            "r_per_chance": _rate(runs, n),
            "escaped": sum(1 for k in chance_keys if p_runs[pid].get(k, 0) == 0),
            "escape_pct": _pct(sum(1 for k in chance_keys if p_runs[pid].get(k, 0) == 0), n),
            "multi": sum(1 for k in chance_keys if p_runs[pid].get(k, 0) >= 2),
            "small_sample": n < MIN_PITCHER_CHANCES,
        }

    hitters = {}
    for bid, s in hit.items():
        n = s["risp_pa"]
        hitters[bid] = {
            "pa": s["pa"], "risp_pa": n, "risp_runs": s["risp_runs"],
            "r_per_risp_pa": _rate(s["risp_runs"], n), "risp_pa_scored": s["risp_pa_scored"],
            "cash_pct": _pct(s["risp_pa_scored"], n),
            "risp_re24": round(s["risp_re24"], 2) if n else None,
            "re24_per_risp_pa": _rate(s["risp_re24"], n, 3),
            "small_sample": n < MIN_HITTER_RISP_PA,
        }
    return {"team": team, "pitchers": pitchers, "hitters": hitters}


def pitcher_line(db, player_id, date_from=None, date_to=None, game_scope="all"):
    d = scoring_chances(db, date_from, date_to, game_scope)
    return d["pitchers"].get(player_id), d["team"]["staff"]


def hitter_line(db, player_id, date_from=None, date_to=None, game_scope="all"):
    d = scoring_chances(db, date_from, date_to, game_scope)
    return d["hitters"].get(player_id), d["team"]["offense"]
