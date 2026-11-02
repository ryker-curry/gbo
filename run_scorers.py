"""
GBO -- who scored, RBI, SB, CS (Nov 2026, Ryker: "lets find a way to get
runs scored as well"; chose "infer + confirm", the official RBI rule, and
showing these on the season stat line, hitter cards and the pitcher side).

Game Tracking stores the bases as an occupancy string ("010" = runner on
2nd), not as which player is on each base. So who scored is worked out by
replaying each half-inning:

  - the batter goes to the base his result puts him on
    (BATTER_REACH_BASE), runners already on fill the other occupied bases
    with the fewest-bases-moved legal placement (place_runners), anyone
    left over was put out;
  - when a play scores N runs, the N lead runners scored (runners can't
    pass each other); any run beyond the runners on base is the batter
    (a home run);
  - a runner event to home (to_base 4) is the runner it names, or whoever
    was on its from_base;
  - "End half-inning early" sweeps home the runs it recorded (lead
    runners first); anyone else is left on.

A coach can confirm or fix the scorers on a play in Game Tracking; those
rows (GamePlayRunScorer) replace the inference for that play, but only
while their count still matches the play's runs_scored_on_play (so editing
the runs on a play in Pitch Log falls back to inference instead of showing
stale names).

This same walk drives the drag-and-drop diamond in game_tracking.py
(runners_on_base() there is a thin wrapper around walk_game() here), so
the diamond and the stats can never disagree about who is where.

RBI is per the official rule: runs that score on the at-bat's final play,
including a bases-loaded walk / HBP, but none on an error or a double play.
Runs on a wild pitch, passed ball, steal, etc. are runner events, never on
the at-bat's play, so they are never RBIs.

SB / CS come straight from runner events ("Stolen Base" / "Caught
Stealing") that name the runner. A pickoff is not a caught stealing.
For pitchers, SB/CS allowed are the runner events logged right after one
of his pitches (the same anchor rule as wild pitches and balks).

R / SB / CS for a set of a hitter's pitches are counted over the games in
that set, so every card's numbers match its own filters. A game where he
only pinch-ran (no plate appearance) isn't in his pitch set, so a run he
scored there isn't counted on that card.
"""

from collections import defaultdict
from itertools import combinations

from gbo_cache import cached

BATTER_REACH_BASE = {"1B": 1, "BB": 1, "IBB": 1, "HBP": 1, "E": 1, "FC": 1, "2B": 2, "3B": 3,
                     "K - Reached on Dropped 3rd": 1}
NO_RBI_OUTCOMES = ("E", "Double Play")
SB_EVENT, CS_EVENT = "Stolen Base", "Caught Stealing"


# ---------------------------------------------------------------------------
# Identity helpers -- an identity is ("our", player_id), ("opp",
# opponent_player_id), or None when GBO can't tell.
# ---------------------------------------------------------------------------
def batter_of(p):
    if p.is_our_team_batting:
        return ("our", p.our_player_id) if p.our_player_id else None
    if p.opponent_our_player_id:
        return ("our", p.opponent_our_player_id)
    return ("opp", p.opponent_player_id) if p.opponent_player_id else None


def identity_of(our_player_id=None, opponent_player_id=None):
    if our_player_id:
        return ("our", our_player_id)
    if opponent_player_id:
        return ("opp", opponent_player_id)
    return None


def _bases_set(b):
    return {i + 1 for i, c in enumerate((b or "000")[:3]) if c == "1"}


def place_runners(start_bases, targets, batter_base):
    """Which runners already on base end up on which of `targets` (the
    occupied bases after the play, batter's own base excluded). Oct 2026,
    Ryker: on a fielder's choice with runners on 1st and 2nd where the lead
    runner was thrown out at 3rd, the old lead-first fill kept the lead
    runner on 2nd -- the wrong man. Runners can't go backward or pass each
    other, and when the batter reaches, every runner forced by him has to
    move up at least one base; any runner not placed was put out. Of the
    placements that obey those rules, take the one where runners move the
    fewest total bases. start_bases is lead-first; returns a list of
    (start_base, target) pairs, or None if no legal placement exists (the
    caller then falls back to the plain lead-first fill)."""
    targets = sorted(targets, reverse=True)
    forced = set()
    if batter_base:
        b = 1
        while b in start_bases:
            forced.add(b)
            b += 1
    best = None
    for kept in combinations(start_bases, len(targets)):
        pairs = list(zip(kept, targets))
        if any(t < s or (s in forced and t <= s) for s, t in pairs):
            continue
        cost = sum(t - s for s, t in pairs)
        if best is None or cost < best[0]:
            best = (cost, pairs)
    return best[1] if best else None


def predicted_scorers(runners, runs, batter):
    """Who scores if a play scores `runs` runs with `runners` ({base:
    identity}) on: lead runners first, then the batter. Used for the
    Game Tracking prefill and by walk_game()."""
    lead = [runners[b] for b in sorted(runners, reverse=True)]
    out = lead[:runs]
    if runs > len(lead):
        out.append(batter)
        out.extend([None] * (runs - len(lead) - 1))
    return out


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------
def walk_game(pitches, runner_events=(), forced_ends=(), confirmed=None):
    """Replay one game. Returns {"runners": {base: identity} at the end,
    "scored": [(kind, ref_id, identity, inferred)]} where kind is "pitch"
    (ref_id = game_pitch_id), "event" (runner_event_id) or "forced"
    (forced_end_id). confirmed: {game_pitch_id: [identity, ...]} from
    GamePlayRunScorer."""
    confirmed = confirmed or {}
    ev_after = defaultdict(list)
    for e in runner_events or []:
        ev_after[e.pitch_sequence_after].append(e)
    for k in ev_after:
        ev_after[k].sort(key=lambda e: (e.created_at or 0, getattr(e, "runner_event_id", 0) or 0))
    fe_after = defaultdict(list)
    for f in forced_ends or []:
        fe_after[f.pitch_sequence_after].append(f)
    scored = []

    def apply_events(runners, anchor):
        for e in ev_after.get(anchor, []):
            who = runners.pop(e.from_base, None)
            named = identity_of(e.our_player_id, e.opponent_player_id)
            if named:
                who = named
            if e.is_out:
                continue
            if e.to_base in (1, 2, 3):
                runners[e.to_base] = who
            elif e.to_base == 4:
                scored.append(("event", getattr(e, "runner_event_id", None), who, named is None))
        for f in fe_after.get(anchor, []):
            # runs_scored is what was swept home when it fired (often 0 --
            # the runners were just left on); lead runners first.
            n = getattr(f, "runs_scored", None)
            lead = sorted(runners, reverse=True)
            for b in lead[:len(lead) if n is None else n]:
                scored.append(("forced", getattr(f, "forced_end_id", None), runners[b], True))
            runners.clear()

    runners, half = {}, None
    apply_events(runners, 0)
    for p in sorted(pitches, key=lambda x: x.pitch_sequence):
        key = (p.inning, bool(p.is_our_team_batting), p.batting_squad)
        if key != half:
            runners, half = {}, key
        on_before = _bases_set(p.bases_before)
        runners = {b: runners.get(b) for b in on_before}
        if p.ends_plate_appearance and p.ab_outcome not in (None, "No Result"):
            rs = p.runs_scored_on_play or 0
            batter = batter_of(p)
            lead_desc = sorted(runners, reverse=True)
            gpid = getattr(p, "game_pitch_id", None)
            conf = confirmed.get(gpid)
            if rs and conf is not None and len(conf) == rs:
                for who in conf:
                    scored.append(("pitch", gpid, who, False))
                # take the confirmed men off the bases; any other run came
                # from the lead runners still unaccounted for
                left = list(lead_desc)
                from_bases = 0
                for who in conf:
                    hit = next((b for b in left if who is not None and runners[b] == who), None)
                    if hit is not None:
                        left.remove(hit)
                        from_bases += 1
                batter_scored = batter is not None and batter in conf
                extra = max(0, rs - from_bases - (1 if batter_scored else 0))
                extra = min(extra, len(left))
                lead_bases = left[extra:]
            else:
                for who in predicted_scorers(runners, rs, batter):
                    scored.append(("pitch", gpid, who, True))
                lead_bases = lead_desc[rs:]
            if (p.outs_after or 0) >= 3:
                runners = {}
            else:
                new_on = _bases_set(p.bases_after)
                placed = {}
                bb = BATTER_REACH_BASE.get(p.ab_outcome)
                if bb in new_on:
                    placed[bb] = batter
                targets = new_on - set(placed)
                plan = place_runners(lead_bases, targets, bb if bb in new_on else None)
                if plan is not None:
                    for s, t in plan:
                        placed[t] = runners[s]
                else:
                    remaining = [runners[b] for b in lead_bases]
                    for b in sorted(targets, reverse=True):
                        placed[b] = remaining.pop(0) if remaining else None
                runners = placed
        apply_events(runners, p.pitch_sequence)
    return {"runners": runners, "scored": scored}


# ---------------------------------------------------------------------------
# Team-wide ledger (cached; invalidated on any Game Tracking save)
# ---------------------------------------------------------------------------
@cached("run_scorer_ledger", {"game_pitches", "game_runner_events", "game_forced_half_inning_ends",
                              "game_play_run_scorers", "games"})
def run_scorer_ledger(db):
    """[(game_id, identity, kind, ref_id, inferred)] for every run in every
    game. Loads only the columns the walk needs (egress)."""
    from models import GamePitch, GameRunnerEvent, GameForcedHalfInningEnd, GamePlayRunScorer
    cols = (GamePitch.game_pitch_id, GamePitch.game_id, GamePitch.pitch_sequence, GamePitch.inning,
            GamePitch.is_our_team_batting, GamePitch.batting_squad, GamePitch.bases_before,
            GamePitch.bases_after, GamePitch.outs_after, GamePitch.ends_plate_appearance,
            GamePitch.ab_outcome, GamePitch.runs_scored_on_play, GamePitch.our_player_id,
            GamePitch.opponent_our_player_id, GamePitch.opponent_player_id)
    by_game = defaultdict(list)
    for r in db.query(*cols).all():
        by_game[r.game_id].append(r)
    ev = defaultdict(list)
    for e in db.query(GameRunnerEvent).all():
        ev[e.game_id].append(e)
    fe = defaultdict(list)
    for f in db.query(GameForcedHalfInningEnd).all():
        fe[f.game_id].append(f)
    conf = load_confirmed(db)
    out = []
    for gid in set(by_game) | set(ev) | set(fe):
        res = walk_game(by_game.get(gid, []), ev.get(gid, []), fe.get(gid, []), conf)
        for kind, ref, who, inferred in res["scored"]:
            out.append((gid, who, kind, ref, inferred))
    return out


def load_confirmed(db, game_pitch_ids=None):
    """{game_pitch_id: [identity, ...]} in slot order."""
    from models import GamePlayRunScorer
    q = db.query(GamePlayRunScorer)
    if game_pitch_ids is not None:
        ids = list(game_pitch_ids)
        if not ids:
            return {}
        q = q.filter(GamePlayRunScorer.game_pitch_id.in_(ids))
    rows = sorted(q.all(), key=lambda r: (r.game_pitch_id, r.slot))
    out = defaultdict(list)
    for r in rows:
        out[r.game_pitch_id].append(identity_of(r.our_player_id, r.opponent_player_id))
    return dict(out)


# ---------------------------------------------------------------------------
# Per-player numbers
# ---------------------------------------------------------------------------
def rbi_on_play(p):
    if not p.ends_plate_appearance or p.ab_outcome in (None, "No Result") or p.ab_outcome in NO_RBI_OUTCOMES:
        return 0
    return p.runs_scored_on_play or 0


def runs_scored_for(db, identity, game_ids):
    game_ids = set(game_ids)
    if identity is None or not game_ids:
        return 0
    return sum(1 for gid, who, *_ in run_scorer_ledger(db) if gid in game_ids and who == identity)


def _runner_events(db, game_ids, event_types):
    from models import GameRunnerEvent
    game_ids = list(game_ids)
    if not game_ids:
        return []
    return db.query(GameRunnerEvent).filter(
        GameRunnerEvent.game_id.in_(game_ids),
        GameRunnerEvent.event_type.in_(event_types),
    ).all()


def running_line_for(db, player_id, pitches):
    """{"R", "RBI", "SB", "CS"} for one of our hitters, over the games in
    `pitches` (his batting pitches, already filtered by the caller)."""
    game_ids = {p.game_id for p in pitches}
    rbi = sum(rbi_on_play(p) for p in pitches)
    ident = ("our", player_id)
    sb = cs = 0
    for e in _runner_events(db, game_ids, (SB_EVENT, CS_EVENT)):
        if e.our_player_id == player_id:
            if e.event_type == SB_EVENT:
                sb += 1
            else:
                cs += 1
    return {"R": runs_scored_for(db, ident, game_ids), "RBI": rbi, "SB": sb, "CS": cs}


def sb_cs_allowed_for(db, pitches):
    """(SB, CS) with this pitcher on the mound: runner events anchored right
    after one of his pitches. Each runner counts (a double steal is 2 SB)."""
    his = {(p.game_id, p.pitch_sequence) for p in pitches}
    sb = cs = 0
    for e in _runner_events(db, {g for g, _s in his}, (SB_EVENT, CS_EVENT)):
        if (e.game_id, e.pitch_sequence_after) in his:
            if e.event_type == SB_EVENT:
                sb += 1
            else:
                cs += 1
    return sb, cs
