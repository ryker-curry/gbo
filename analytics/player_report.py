"""
GBO -- Pitcher Meeting Report (Oct 2026).

Ryker: "build reports to where a player could sit down and go through it
like in a meeting style with a coach ... print off a sheet and be able to
see everything important and have a better understanding of what it all
means and how you as a pitcher performed and what you need to work on."
A separate, simpler one-page companion to Pitcher Game Report and
Pitcher Profile -- not a replacement for either.

Decisions agreed with Ryker (AskUserQuestion, Oct 2026):
  - Two versions: one GAME, one SEASON.
  - Staff can open anyone's; a Player only his own.
  - Coach notes are typed and saved (models.PlayerReportNote) and print
    on the sheet.
  - Compare every number to the TEAM average, his OWN average, and his
    goals (team goals + IDP goals).
  - Strictly one page.

This module is pure data -- no Shiny. It reuses analytics/
pitcher_game_report.py's own stat helpers (same definitions as the full
Game Report, so the two never disagree) over any list of one pitcher's
GamePitch rows, single game or many.

COMPARISONS
  Game report:   You (this game) | Your season (his other games this
                 season) | Team (staff, whole season) | Goal
  Season report: You (season)    | Last 3 games | Team (season) | Goal
  The colored mark compares him to the GOAL when there is one, else to
  the team average. A metric whose sample is too small (fewer than
  MIN_SAMPLE opportunities) gets no mark -- one walk in two hitters
  shouldn't read as a red flag.

WENT WELL / WORK ON
  Auto-written, plain-English, top 3 each, from (a) the key numbers that
  are clearly better/worse than the goal or team (by each metric's own
  SCALE), (b) his best and shakiest pitch, (c) a pitch that keeps missing
  the same way (Miss Map lean of LEAN_IN+ inches). Coaches add their own
  points in the saved notes.
"""

from collections import defaultdict

from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from models import Season, Game, GamePitch, PitchType, Player, RapsodoPitch, IDPGoal, IDPStatus, Assessment, AssessmentResult
from pitch_type_config import FASTBALL_TYPES
from analytics.pitcher_game_report import (
    _compute_header_stats, _fps_stat, _secondary_strike_stat, _pitcher_id,
    STRIKE_OUTCOMES, SWING_OUTCOMES, FPS_GOAL_PCT, SECONDARY_STRIKE_GOAL_PCT,
)
from analytics import command_metrics
from analytics.rapsodo_goal_metrics import rapsodo_field_for_test_name, average_rapsodo_metric

MIN_SAMPLE = 5
LEAN_IN = 3.0
MIN_PITCHES_FOR_PITCH_NOTE = 8

# key, label, higher_is_better, scale (what counts as "clearly" different),
# unit, what it means (plain English), denominator key, goal, tip when low
METRICS = [
    dict(key="strike_pct", label="Strike %", hib=True, scale=4.0, unit="%", n="pitches",
         means="Share of all pitches that were strikes (called, swinging, foul or put in play).",
         tip="Get ahead and stay in the zone -- make hitters earn it."),
    dict(key="fps_pct", label="First-pitch strike %", hib=True, scale=5.0, unit="%", n="fps_opportunities",
         goal=FPS_GOAL_PCT, means="How often you started a hitter 0-1. Hitters do far worse after 0-1 than 1-0.",
         tip="Attack 0-0 with your most reliable strike pitch."),
    dict(key="e_plus_a_pct", label="Early & ahead %", hib=True, scale=5.0, unit="%", n="bf",
         means="Hitters who put it in play in the first 3 pitches, or who you got to 2 strikes.",
         tip="Win the first 3 pitches -- early contact or 2 strikes, not deep counts."),
    dict(key="leadoff_out_pct", label="Leadoff out %", hib=True, scale=8.0, unit="%", n="leadoff_pas",
         means="Got the first hitter of the inning out. Innings go much better when he's out.",
         tip="Treat the leadoff hitter like the most important one of the inning."),
    dict(key="secondary_strike_pct", label="Off-speed strike %", hib=True, scale=5.0, unit="%", n="secondary_pitches",
         goal=SECONDARY_STRIKE_GOAL_PCT, means="Strikes with anything that isn't a fastball.",
         tip="Land off-speed for strikes so hitters can't sit fastball."),
    dict(key="whiff_pct", label="Whiff %", hib=True, scale=5.0, unit="%", n="swings",
         means="Swings that missed. Shows how hard your stuff is to hit.",
         tip="Finish pitches out of the zone with 2 strikes."),
    dict(key="k_pct", label="Strikeout %", hib=True, scale=5.0, unit="%", n="bf",
         means="Hitters faced who struck out.",
         tip="Use your put-away pitch once you're ahead."),
    dict(key="bb_pct", label="Walk %", hib=False, scale=3.0, unit="%", n="bf",
         means="Hitters faced who walked. Lower is better.",
         tip="Cut walks -- fill the zone in hitters' counts."),
    dict(key="execution_pct", label="Hit-the-spot %", hib=True, scale=6.0, unit="%", n="execution_reviewed",
         means="Pitches that landed in the zone the catcher called (needs video review).",
         tip="Pick a small target and finish to it."),
    dict(key="pitches_per_inning", label="Pitches per inning", hib=False, scale=2.0, unit="", n="outs",
         means="Efficiency. Around 15 or fewer lets you go deeper in games.",
         tip="Be efficient -- early contact saves pitches."),
]
METRIC_BY_KEY = {m["key"]: m for m in METRICS}


# ---------------------------------------------------------------------------
# Stat bundle over any list of one or many pitchers' pitches
# ---------------------------------------------------------------------------

def _completed_pas(pitches):
    """Group into PAs per (game, pitcher), in pitch order."""
    by_frame = defaultdict(list)
    for p in pitches:
        by_frame[(p.game_id, _pitcher_id(p))].append(p)
    out = []
    for key in sorted(by_frame, key=lambda k: (k[0], k[1] or 0)):
        cur = []
        for p in sorted(by_frame[key], key=lambda p: p.pitch_sequence):
            if p.pa_pitch_number == 1 and cur:
                out.append(cur)
                cur = []
            cur.append(p)
        if cur:
            out.append(cur)
    return [pa for pa in out if pa[-1].ends_plate_appearance and pa[-1].ab_outcome != "No Result"]


def _pct(a, b):
    return round(a / b * 100, 1) if b else None


def stat_bundle(pitches, pitch_types):
    """Every key number on the sheet, plus each one's sample size."""
    if not pitches:
        return None
    pitches = sorted(pitches, key=lambda p: (p.game_id, p.pitch_sequence))
    pas = _completed_pas(pitches)
    h = _compute_header_stats(pitches, pas)
    fps = _fps_stat(pas)
    sec = _secondary_strike_stat(pitches, pitch_types)
    swings = sum(1 for p in pitches if p.pitch_outcome in SWING_OUTCOMES)
    whiffs = sum(1 for p in pitches if p.pitch_outcome == "Swing and Miss")
    bf = h["bf"]
    outs = round((h["ip_decimal"] or 0) * 3)
    games = len({p.game_id for p in pitches})
    return {
        "games": games, "pitches": h["pitches"], "bf": bf, "ip_display": h["ip_display"], "outs": outs,
        "hits": h["hits"], "runs": h["runs"], "bb": h["bb"], "hbp": h["hbp"], "ks": h["ks"], "xbh": h["xbh"],
        "era": h["era"], "whip": h["whip"],
        "strike_pct": h["strike_pct"],
        "fps_pct": fps["fps_pct"], "fps_opportunities": fps["fps_opportunities"],
        "e_plus_a_pct": h["e_plus_a_pct"],
        "leadoff_out_pct": h["leadoff_out_pct"], "leadoff_pas": h["leadoff_pas"],
        "secondary_strike_pct": sec["secondary_strike_pct"], "secondary_pitches": sec["secondary_pitches"],
        "whiff_pct": _pct(whiffs, swings), "swings": swings,
        "k_pct": h["k_pct"], "bb_pct": _pct(h["bb"], bf),
        "execution_pct": h["execution_pct"], "execution_reviewed": h["execution_reviewed"],
        "pitches_per_inning": h["pitches_per_inning"],
    }


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def _pitcher_filter(player_id):
    return or_(
        and_(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == player_id),
        and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id == player_id),
    )


def pitcher_pitches(db, player_id, season_id=None, game_id=None):
    q = (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
         .options(joinedload(GamePitch.pitch_type)).filter(_pitcher_filter(player_id)))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    if game_id is not None:
        q = q.filter(GamePitch.game_id == game_id)
    return q.all()


def team_pitches(db, season_id):
    """Every pitch thrown by one of OUR pitchers in this season (our side
    of real games; both sides of intrasquads)."""
    q = (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
         .options(joinedload(GamePitch.pitch_type))
         .filter(or_(GamePitch.is_our_team_batting.is_(False),
                     and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id.isnot(None)))))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    return q.all()


def pitcher_games(db, player_id, season_id=None):
    ids = {gid for (gid,) in db.query(GamePitch.game_id).filter(_pitcher_filter(player_id)).distinct().all()}
    if not ids:
        return []
    q = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id.in_(ids))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    return q.order_by(Game.game_date.desc(), Game.game_id.desc()).all()


def _velo_by_game_pitch(db, pitches):
    ids = [p.game_pitch_id for p in pitches]
    if not ids:
        return {}
    rows = db.query(RapsodoPitch.game_pitch_id, RapsodoPitch.velocity).filter(
        RapsodoPitch.game_pitch_id.in_(ids), RapsodoPitch.velocity.isnot(None)).all()
    return {gid: float(v) for gid, v in rows}


# ---------------------------------------------------------------------------
# Pitch mix
# ---------------------------------------------------------------------------

def _lean_text(h, v):
    parts = []
    if h is not None and abs(h) >= 1.5:
        parts.append(f'{abs(h):.0f}" {"arm side" if h > 0 else "glove side"}')
    if v is not None and abs(v) >= 1.5:
        parts.append(f'{abs(v):.0f}" {"high" if v > 0 else "low"}')
    return " & ".join(parts) if parts else "on target"


def pitch_mix(db, pitches, throws):
    total = len(pitches)
    velo = _velo_by_game_pitch(db, pitches)
    views = command_metrics.game_pitches_command_view(pitches, throws)
    view_by_type = defaultdict(list)
    for v in views:
        view_by_type[command_metrics.pitch_type_label(v)].append(v)
    by_type = defaultdict(list)
    for p in pitches:
        by_type[command_metrics.pitch_type_label(p)].append(p)
    rows = []
    for label, ps in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        n = len(ps)
        strikes = sum(1 for p in ps if p.pitch_outcome in STRIKE_OUTCOMES)
        swings = sum(1 for p in ps if p.pitch_outcome in SWING_OUTCOMES)
        whiffs = sum(1 for p in ps if p.pitch_outcome == "Swing and Miss")
        reviewed = [p for p in ps if p.intended_zone is not None and p.pitch_zone is not None]
        hit = sum(1 for p in reviewed if p.intended_zone == p.pitch_zone)
        vs = [velo[p.game_pitch_id] for p in ps if p.game_pitch_id in velo]
        located = [v for v in view_by_type.get(label, []) if v.horizontal_miss is not None]
        h_lean = v_lean = None
        if located:
            h_lean = sum(command_metrics.normalize_horizontal_to_arm_side(v.horizontal_miss, throws) for v in located) / len(located)
            v_lean = sum(float(v.vertical_miss) for v in located) / len(located)
        rows.append({
            "pitch": label, "n": n, "usage_pct": _pct(n, total),
            "velo": round(sum(vs) / len(vs), 1) if vs else None, "velo_max": round(max(vs), 1) if vs else None,
            "strike_pct": _pct(strikes, n), "swings": swings, "whiff_pct": _pct(whiffs, swings),
            "spot_pct": _pct(hit, len(reviewed)), "spot_n": len(reviewed),
            "located": len(located), "h_lean": h_lean, "v_lean": v_lean,
            "lean": _lean_text(h_lean, v_lean) if located else None,
            "is_fastball": label in FASTBALL_TYPES,
        })
    return rows


def locations(pitches):
    return [
        (float(p.actual_plate_x), float(p.actual_plate_z), command_metrics.pitch_type_label(p), p.pitch_outcome)
        for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None
    ]


# ---------------------------------------------------------------------------
# IDP goals
# ---------------------------------------------------------------------------

def idp_goals(db, player_id, limit=3):
    goals = (
        db.query(IDPGoal).options(joinedload(IDPGoal.status), joinedload(IDPGoal.target_test_type),
                                  joinedload(IDPGoal.target_pitch_type))
        .filter(IDPGoal.player_id == player_id).order_by(IDPGoal.created_at.desc()).all()
    )
    out = []
    for g in goals:
        status = g.status.status_name if g.status else ""
        if status.lower() in ("completed", "complete", "achieved", "cancelled", "canceled"):
            continue
        current = None
        if g.target_test_type is not None:
            field = rapsodo_field_for_test_name(g.target_test_type.test_name)
            if field:
                q = db.query(RapsodoPitch).filter(RapsodoPitch.player_id == player_id)
                if g.target_pitch_type_id:
                    q = q.filter(RapsodoPitch.pitch_type_id == g.target_pitch_type_id)
                recent = q.order_by(RapsodoPitch.pitch_date.desc()).limit(60).all()
                current = average_rapsodo_metric(recent, field)
            else:
                r = (db.query(AssessmentResult).join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
                     .filter(Assessment.player_id == player_id, AssessmentResult.test_type_id == g.target_test_type_id)
                     .order_by(Assessment.assessment_date.desc()).first())
                current = float(r.value) if r else None
        out.append({
            "description": g.description, "status": status,
            "metric": g.target_test_type.test_name if g.target_test_type else None,
            "pitch": g.target_pitch_type.type_name if g.target_pitch_type else None,
            "baseline": float(g.baseline_value) if g.baseline_value is not None else None,
            "target": float(g.target_value) if g.target_value is not None else None,
            "current": round(current, 1) if current is not None else None,
            "target_date": g.target_date,
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Comparison rows + went well / work on
# ---------------------------------------------------------------------------

def _mark(m, you, n, team):
    """('good'|'ok'|'bad'|None, diff in scale units vs goal-or-team)."""
    if you is None or n is None or n < MIN_SAMPLE:
        return None, None
    ref = m.get("goal") if m.get("goal") is not None else team
    if ref is None:
        return None, None
    diff = (you - ref) / m["scale"]
    if not m["hib"]:
        diff = -diff
    return ("good" if diff >= 1 else "bad" if diff <= -1 else "ok"), diff


def key_rows(you, mine, team):
    rows = []
    for m in METRICS:
        y = you.get(m["key"]) if you else None
        n = you.get(m["n"]) if you else None
        t = team.get(m["key"]) if team else None
        mark, diff = _mark(m, y, n, t)
        rows.append({**m, "you": y, "sample": n, "mine": mine.get(m["key"]) if mine else None,
                     "team": t, "mark": mark, "diff": diff})
    return rows


def _fmt(m, v):
    if v is None:
        return "—"
    return f"{v:.0f}{m['unit']}" if m["unit"] == "%" else f"{v:.1f}"


def takeaways(rows, mix, total_pitches):
    good, bad = [], []
    for r in rows:
        if r["diff"] is None:
            continue
        ref_name = f"the {r['goal']:.0f}% goal" if r.get("goal") is not None else f"the team ({_fmt(r, r['team'])})"
        if r["mark"] == "good":
            good.append((r["diff"], f"{r['label']}: {_fmt(r, r['you'])}, better than {ref_name}."))
        elif r["mark"] == "bad":
            bad.append((-r["diff"], f"{r['label']}: {_fmt(r, r['you'])}, below {ref_name}. {r['tip']}"))

    enough = [p for p in mix if p["n"] >= MIN_PITCHES_FOR_PITCH_NOTE and p["pitch"] != "Unspecified"]
    whiffy = [p for p in enough if p["swings"] >= 5 and p["whiff_pct"] is not None]
    if whiffy:
        best = max(whiffy, key=lambda p: p["whiff_pct"])
        if best["whiff_pct"] >= 25:
            good.append((best["whiff_pct"] / 25, f"Your {best['pitch'].lower()} got swings and misses "
                                                  f"({best['whiff_pct']:.0f}% of swings) -- trust it."))
    if enough:
        best_s = max(enough, key=lambda p: p["strike_pct"] or 0)
        if (best_s["strike_pct"] or 0) >= 68:
            good.append((1.2, f"You threw your {best_s['pitch'].lower()} for strikes "
                              f"({best_s['strike_pct']:.0f}% of {best_s['n']})."))
        worst = min(enough, key=lambda p: p["strike_pct"] or 0)
        if (worst["strike_pct"] or 0) < 55:
            bad.append((1.5 + (55 - worst["strike_pct"]) / 10,
                        f"Your {worst['pitch'].lower()} was a strike only {worst['strike_pct']:.0f}% of the time "
                        f"({worst['n']} thrown). Make it a pitch you can land when you need to."))
    for p in mix:
        if p["located"] >= 6 and p["h_lean"] is not None:
            big = max(abs(p["h_lean"]), abs(p["v_lean"]))
            if big >= LEAN_IN:
                bad.append((big / LEAN_IN, f"Your {p['pitch'].lower()} missed {p['lean']} of the target on average. "
                                           f"Adjust your aim or finish to correct it."))

    good = [t for _s, t in sorted(good, key=lambda x: -x[0])][:3]
    bad = [t for _s, t in sorted(bad, key=lambda x: -x[0])][:3]
    if not good:
        good = ["Nothing jumped out above the goal or team average -- a steady outing to build on."] if total_pitches else []
    if not bad:
        bad = ["Nothing stood out as a problem in the numbers -- keep doing what you're doing."] if total_pitches else []
    return good, bad


# ---------------------------------------------------------------------------
# Whole reports
# ---------------------------------------------------------------------------

def _pitch_type_names(db):
    return {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}


def game_report(db, player_id, game_id):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == game_id).first()
    if player is None or game is None:
        return None
    names = _pitch_type_names(db)
    mine_game = pitcher_pitches(db, player_id, game_id=game_id)
    if not mine_game:
        return None
    you = stat_bundle(mine_game, names)
    season_pitches = [p for p in pitcher_pitches(db, player_id, season_id=game.season_id) if p.game_id != game_id] \
        if game.season_id is not None else []
    mine = stat_bundle(season_pitches, names) if season_pitches else None
    team = stat_bundle(team_pitches(db, game.season_id), names)
    mix = pitch_mix(db, mine_game, player.throws)
    rows = key_rows(you, mine, team)
    good, bad = takeaways(rows, mix, you["pitches"])
    return {
        "kind": "game", "player": player, "game": game, "season_id": game.season_id,
        "you": you, "mine": mine, "team": team, "mine_label": "Your season", "rows": rows,
        "mix": mix, "locations": locations(mine_game), "good": good, "bad": bad,
        "goals": idp_goals(db, player_id), "game_log": None,
    }


def season_report(db, player_id, season_id):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if player is None:
        return None
    names = _pitch_type_names(db)
    pitches = pitcher_pitches(db, player_id, season_id=season_id)
    if not pitches:
        return None
    you = stat_bundle(pitches, names)
    games = pitcher_games(db, player_id, season_id=season_id)
    last3_ids = {g.game_id for g in games[:3]}
    last3 = stat_bundle([p for p in pitches if p.game_id in last3_ids], names) if len(games) > 3 else None
    team = stat_bundle(team_pitches(db, season_id), names)
    mix = pitch_mix(db, pitches, player.throws)
    rows = key_rows(you, last3, team)
    good, bad = takeaways(rows, mix, you["pitches"])
    by_game = defaultdict(list)
    for p in pitches:
        by_game[p.game_id].append(p)
    log = []
    for g in games[:6]:
        b = stat_bundle(by_game[g.game_id], names)
        log.append({"game": g, **b})
    season = db.query(Season).filter(Season.season_id == season_id).first() if season_id is not None else None
    return {
        "kind": "season", "player": player, "game": None, "season_id": season_id,
        "season_name": season.season_name if season else "All games",
        "you": you, "mine": last3, "team": team, "mine_label": "Last 3 games", "rows": rows,
        "mix": mix, "locations": locations(pitches), "good": good, "bad": bad,
        "goals": idp_goals(db, player_id), "game_log": log,
    }
