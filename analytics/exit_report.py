"""
GBO -- Fall Exit Report (Oct 2026, Ryker: "a report that coaches could go
through and do a deep dive on each player's performance this fall ... then
use it as a development tool so each guy knows what he needs to work on
before the season starts").

Decisions agreed with Ryker (AskUserQuestion, Oct 2026):
  - Pitchers AND hitters (shared Part 2 plan).
  - On screen + printable (2-3 pages).
  - GBO suggests the top 3 priorities, the coach edits them in the meeting.
  - Saving the plan creates (or updates) IDP goals.
  - Players see their report only after a coach saves it.
  - Default retest date: Jan 15, 2027.
  - "This fall" = GAMES ONLY (no bullpens), for results AND for stuff.

PART 1 -- how his fall went (pure data, built here):
  pitcher: key numbers (fall / early fall / late fall / team / D2 / goal),
           pitch mix + Stuff+ / Location+ from his game pitches' Rapsodo
           readings, pitcher type + attack-plan gaps, command by target
           lane, workload (outings, pitches, velo fade), body, goals.
  hitter:  key numbers with early / late, swing decisions, hot zones, by
           pitch type, how they pitch him, body, goals.
PART 2 -- the plan: suggest_priorities() ranks his biggest gaps into three
           measurable (or text) priorities; save_plan() stores the coach's
           version and turns each into an IDP goal.

No Shiny here. Reuses the Pitcher / Hitter Report builders
(analytics/player_report.py, analytics/hitter_report.py) so every number
matches those pages.
"""

from collections import defaultdict
from datetime import date, datetime

from sqlalchemy.orm import joinedload

from models import Player, Season, RapsodoPitch, Assessment, AssessmentResult, AssessmentTestType
from analytics import player_report, hitter_report, game_goals

RETEST_DEFAULT = date(2027, 1, 15)
MIN_TREND_GAMES = 4          # need 2+ games on each side to call early vs late
N_PRIORITIES = 3
GOAL_WINDOW = "last5"        # game-stat goals are judged on his last 5 games

# Pitcher Report metric key -> game_goals key (measurable in games)
P_GAME_KEY = {"strike_pct": "p_strike", "fps_pct": "p_fps", "whiff_pct": "p_whiff", "bb_pct": "p_bb",
              "execution_pct": "p_spot"}
# Hitter Report metric key -> game_goals key
H_GAME_KEY = {"Chase %": "h_chase", "Swing Decision %": "h_swing_dec", "Whiff %": "h_whiff", "K%": "h_k",
              "BB%": "h_bb", "Hard contact %": "h_hard", "QAB%": "h_qab"}

# Plain, coach-editable starting points for "how" -- one line each.
DRILLS = {
    "p_strike": ["Pens: 3 of 5 strikes to each called spot before moving on",
                 "Count-based pens (start 1-0 / 2-1) -- land the pitch you'd throw there"],
    "p_fps": ["Every pen opens with a 0-0 'strike one' round on his most reliable pitch",
              "Track first-pitch strikes in every intrasquad / live AB"],
    "p_whiff": ["Pitch design check on the best secondary (shape vs fastball, tunnel)",
                "Put-away round in pens: 2-strike pitch below the zone, chart chase"],
    "p_bb": ["Pens finishing every hitter in 4 pitches or fewer",
             "Fastball-command blocks: 10 to the glove side, 10 arm side"],
    "p_spot": ["Target pens with a 6-inch box -- chart hit / miss on every pitch",
               "Video review of misses: same release point on hits and misses?"],
    "e_plus_a_pct": ["Live ABs where the count resets at 3 pitches -- win them early"],
    "leadoff_out_pct": ["Treat the first hitter of every inning in live ABs as a 'must' AB"],
    "secondary_strike_pct": ["Off-speed for a strike in 1-0 and 2-1 counts in every pen",
                             "Shape check on the secondary -- one pitch he can land on demand"],
    "pitches_per_inning": ["Attack early: 3-pitch rule in live ABs (in play or 2 strikes by pitch 3)"],
    "h_chase": ["Pitch-recognition reps (spin / no-spin, ball / strike calls) 3x a week",
                "Live ABs with a 'two-strike zone' plan -- take anything off the plate"],
    "h_swing_dec": ["BP rounds swinging only at a called zone; take the rest",
                    "Machine / live rounds calling ball-strike out loud before the swing"],
    "h_whiff": ["Short-to-the-ball tee and front-toss work, then velo machine at game speed",
                "Two-strike approach rounds: choke, widen, put it in play"],
    "h_k": ["Two-strike approach rounds every BP: battle, foul off, put it in play",
            "Velo-machine rounds at game speed to cut late swings"],
    "h_bb": ["Live ABs: take until a strike -- learn the zone",
             "Track pitches seen per PA in scrimmages"],
    "h_hard": ["Intent rounds: bat speed / exit velo work on the tee",
               "Barrel-accuracy rounds (line drive net, center-field target)"],
    "h_qab": ["Every scrimmage AB graded for quality -- review weekly with a coach"],
}
GENERIC_DRILLS = ["Coach to set the weekly plan", "Retest on the date below"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def default_season(db):
    """Most recent season by its games (Fall 2026 today)."""
    from models import Game
    row = (db.query(Game.season_id).filter(Game.season_id.isnot(None))
           .order_by(Game.game_date.desc()).first())
    return row[0] if row else None


def _split(games_newest_first):
    """(early game ids, late game ids) by date, or (None, None) if too few."""
    games = sorted(games_newest_first, key=lambda g: (g.game_date, g.game_id))
    if len(games) < MIN_TREND_GAMES:
        return None, None
    half = len(games) // 2
    return {g.game_id for g in games[:half]}, {g.game_id for g in games[half:]}


def _trend(hib, scale, early, late):
    """'up' (better), 'down' (worse), 'flat' or None -- 'better' respects
    lower-is-better stats; a change under half the metric's scale is flat."""
    if early is None or late is None or not scale:
        return None
    d = (late - early) / scale
    if not hib:
        d = -d
    return "up" if d >= 0.5 else ("down" if d <= -0.5 else "flat")


def _type_name(p):
    return p.pitch_type.type_name if p.pitch_type is not None else None


def _linked_rapsodo(db, pitches):
    ids = [p.game_pitch_id for p in pitches]
    if not ids:
        return []
    return (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.game_pitch_id.in_(ids)).all())


# ---------------------------------------------------------------------------
# Body (both)
# ---------------------------------------------------------------------------

def _test_progress(db, pid, limit=8):
    """First vs latest result on each test he's done 2+ times (any date),
    biggest change first -- 'what changed since his first test'."""
    from analytics.research_progress import BATTERY
    from analytics.assessment_progress import direction_map
    names = [t for _c, tests in BATTERY for t in tests]
    rows = (db.query(AssessmentTestType.test_name, AssessmentTestType.unit, Assessment.assessment_date,
                     AssessmentResult.value)
            .join(AssessmentResult, AssessmentResult.test_type_id == AssessmentTestType.test_type_id)
            .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
            .filter(Assessment.player_id == pid, AssessmentTestType.test_name.in_(names),
                    AssessmentResult.value.isnot(None))
            .order_by(Assessment.assessment_date).all())
    by = defaultdict(list)
    units = {}
    for name, unit, day, val in rows:
        by[name].append((day, float(val)))
        units[name] = unit or ""
    dirs = direction_map()
    out = []
    for name, vals in by.items():
        if len(vals) < 2 or vals[0][1] == 0:
            continue
        (d0, v0), (d1, v1) = vals[0], vals[-1]
        if d0 == d1:
            continue
        chg = (v1 - v0) / abs(v0) * 100
        better = chg > 0 if dirs.get(name) != "lower" else chg < 0
        out.append({"test": name, "unit": units[name], "first": v0, "first_date": d0, "latest": v1,
                    "latest_date": d1, "pct": chg, "better": better if abs(chg) >= 1 else None})
    out.sort(key=lambda r: -abs(r["pct"]))
    return out[:limit]


def body(db, pid, is_pitcher):
    import bucket_system as bs
    from analytics import athlete_archetype as aa
    out = {"bucket": None, "arch": None, "arch_raw": None, "ladder": None, "progress": []}
    try:
        out["bucket"] = bs.compute_bucket_system(db, pid)
    except Exception:
        db.rollback()
    try:
        out["arch"], out["arch_raw"] = aa.load_full(db, pid)
    except Exception:
        db.rollback()
    if is_pitcher:
        try:
            from analytics import training_stage as ts
            data, raw, stab = ts.load(db)
            out["ladder"] = ts.ladder(pid, data, raw, stab)
        except Exception:
            db.rollback()
    try:
        out["progress"] = _test_progress(db, pid)
    except Exception:
        db.rollback()
    return out


# ---------------------------------------------------------------------------
# Pitchers
# ---------------------------------------------------------------------------

def _pitcher_type(db, player, pitches, raps, season):
    """pitcher_type.build() on GAME data only (Ryker: games only)."""
    from analytics import pitcher_type, sequencing, profile_queries, arsenal_plan
    from analytics.bullpen_metrics import average_estimated_arm_angle, pitch_type_label
    from game_stats import get_batter_hands
    fb_like = [r for r in raps if pitch_type_label(r) in arsenal_plan.FASTBALLS]
    arm, _n = average_estimated_arm_angle(fb_like or raps, player)
    hs = [float(r.release_height) for r in (fb_like or raps) if r.release_height is not None]
    hands = get_batter_hands(db, pitches)
    loc = sequencing.loc_map(profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches]))
    import bucket_system as bs
    d0, d1 = bs.season_date_range(bs.current_season_label())
    staff = pitcher_type.staff_fb_velos(db, d0, d1)
    return pitcher_type.build(pitches, raps, player.throws, arm, (sum(hs) / len(hs) if hs else None), hands, loc,
                              staff, label_of=pitch_type_label)


def _workload(db, pitches, raps):
    from analytics import velo_fade
    from analytics.bullpen_metrics import pitch_type_label
    by_game = defaultdict(int)
    for p in pitches:
        if getattr(p, "is_pitch", True) is not False:
            by_game[p.game_id] += 1
    outings = len(by_game)
    fades = [o for o in velo_fade.by_outing(raps, pitch_type_label) if o["fade"].get("ok")]
    per = [o["fade"]["per"] for o in fades]
    avg_per = sum(per) / len(per) if per else None
    return {"outings": outings, "pitches": sum(by_game.values()),
            "per_outing": round(sum(by_game.values()) / outings, 1) if outings else None,
            "max_outing": max(by_game.values()) if by_game else None,
            "fade_outings": len(fades), "fade_per": avg_per, "fade_read": velo_fade.read(avg_per) if per else None}


def pitcher_report(db, pid, season_id):
    base = player_report.season_report(db, pid, season_id)
    if base is None:
        return None
    player = base["player"]
    names = player_report._pitch_type_names(db)
    pitches = player_report.pitcher_pitches(db, pid, season_id=season_id)
    games = player_report.pitcher_games(db, pid, season_id=season_id)
    early_ids, late_ids = _split(games)
    early = late = None
    if early_ids:
        early = player_report.stat_bundle([p for p in pitches if p.game_id in early_ids], names, db)
        late = player_report.stat_bundle([p for p in pitches if p.game_id in late_ids], names, db)
    for r in base["rows"]:
        r["early"] = early.get(r["key"]) if early else None
        r["late"] = late.get(r["key"]) if late else None
        r["trend"] = _trend(r["hib"], r["scale"], r["early"], r["late"])

    raps = _linked_rapsodo(db, pitches)
    grades = {}
    try:
        from analytics import profile_queries
        bundle = profile_queries.compute_grading_bundle(db, pitches, raps)
        grades = {row["Pitch Type"]: row for row in bundle.get("arsenal_rows") or []}
        base["grades_overall"] = {k: bundle.get(k) for k in ("stuff_plus_value", "location_plus_value", "pitching_plus_value")}
    except Exception:
        db.rollback()
        base["grades_overall"] = {}
    for m in base["mix"]:
        g = grades.get(m["pitch"]) or {}
        m["stuff_plus"], m["location_plus"], m["pitching_plus"] = g.get("Stuff+"), g.get("Location+"), g.get("Pitching+")

    try:
        base["ptype"] = _pitcher_type(db, player, pitches, raps, season_id)
    except Exception:
        db.rollback()
        base["ptype"] = None
    try:
        from analytics import command_lanes
        from game_stats import get_batter_hands
        lanes = command_lanes.compute_lanes(pitches, get_batter_hands(db, pitches), player.throws)
        base["lanes"] = lanes
        base["lanes_takeaway"] = command_lanes.takeaway(lanes)
    except Exception:
        db.rollback()
        base["lanes"], base["lanes_takeaway"] = None, None
    base["workload"] = _workload(db, pitches, raps)
    base["body"] = body(db, pid, True)
    base["goals"] = player_report.idp_goals(db, pid, limit=6)
    base["side"] = "pitch"
    base["trend_ok"] = early_ids is not None
    return base


# ---------------------------------------------------------------------------
# Hitters
# ---------------------------------------------------------------------------

def hitter_report_data(db, pid, season_id):
    from analytics import hitter_insights as hi
    base = hitter_report.season_report(db, pid, season_id)
    if base is None:
        return None
    pitches = hitter_report.hitter_pitches(db, pid, season_id=season_id)
    games = hitter_report.hitter_games(db, pid, season_id=season_id)
    early_ids, late_ids = _split(games)
    early = late = None
    if early_ids:
        early = hi.core_metrics([p for p in pitches if p.game_id in early_ids])
        late = hi.core_metrics([p for p in pitches if p.game_id in late_ids])
    scale = {k: (hib, sc) for k, _l, _m, hib, sc, _kind in hitter_report.METRICS}
    for r in base["rows"]:
        hib, sc = scale[r["key"]]
        r["hib"], r["scale"] = hib, sc
        r["early"] = early.get(r["key"]) if early else None
        r["late"] = late.get(r["key"]) if late else None
        r["trend"] = _trend(hib, sc, r["early"], r["late"])
    base["body"] = body(db, pid, False)
    base["goals"] = player_report.idp_goals(db, pid, limit=6)
    base["side"] = "hit"
    base["trend_ok"] = early_ids is not None
    return base


def build(db, pid, season_id):
    """The whole Part 1 for one player, or None if he has no fall games."""
    player = db.query(Player).filter(Player.player_id == pid).first()
    if player is None:
        return None
    rep = pitcher_report(db, pid, season_id) if player.is_pitcher else hitter_report_data(db, pid, season_id)
    if rep is None:
        return None
    season = db.query(Season).filter(Season.season_id == season_id).first() if season_id else None
    rep["season_name"] = season.season_name if season else "This fall"
    rep["priorities_suggested"] = suggest_priorities(db, rep)
    return rep


# ---------------------------------------------------------------------------
# Part 2 -- priorities
# ---------------------------------------------------------------------------

def _fmt(v, unit):
    if v is None:
        return "—"
    if unit == "%":
        return f"{v:.0f}%"
    if unit == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0") else s
    return f"{v:.1f}"


def _perf_candidates(rep):
    """(score, priority) from the key numbers that are clearly below the
    goal / D2 / team (mark == 'bad'), worst first."""
    out = []
    pitch = rep["side"] == "pitch"
    for r in rep["rows"]:
        if r.get("diff") is None or r.get("mark") not in ("bad", "ok") or (r["mark"] == "ok" and r["diff"] >= 0):
            continue
        # clearly below = full weight; slightly below ("ok" but under the
        # reference) only fills in when there aren't 3 clear gaps
        weight = abs(r["diff"]) if r["mark"] == "bad" else abs(r["diff"]) * 0.3
        if pitch:
            unit = r["unit"]
            ref = (f"the {r['goal']:.0f}% goal" if r.get("goal") is not None else
                   f"D2 {_fmt(r['d2'], unit)}" if r.get("d2") is not None else f"team {_fmt(r['team'], unit)}")
            key = P_GAME_KEY.get(r["key"])
            label, you = r["label"], _fmt(r["you"], unit)
            tip = r.get("tip") or ""
            drills = DRILLS.get(key or r["key"], GENERIC_DRILLS)
        else:
            kind = r["kind"]
            ref = f"D2 {_fmt(r['d2'], kind)}" if r.get("d2") is not None else f"team {_fmt(r['team'], kind)}"
            key = H_GAME_KEY.get(r["key"])
            label, you = r["label"], _fmt(r["you"], kind)
            tip = ""
            drills = DRILLS.get(key, GENERIC_DRILLS)
        trend = {"up": " It got better as the fall went on -- keep that going.",
                 "down": " It slipped late in the fall."}.get(r.get("trend"), "")
        target = None
        if key:
            target = game_goals.suggest_target(key, r["you"])
        out.append((weight, {
            "area": "Pitching" if pitch else "Hitting",
            "title": f"{'Raise' if (r.get('hib', True)) else 'Lower'} {label}",
            "why": f"{label} was {you} this fall vs {ref}.{trend} {tip}".strip(),
            "measure": f"g:{key}" if key else "", "target": target, "retest": RETEST_DEFAULT.isoformat(),
            "drills": "\n".join(drills), "goal_id": None,
        }))
    return out


def _plan_candidates(rep):
    out = []
    pt = rep.get("ptype")
    if pt and pt.get("gaps"):
        gaps = [r for r in pt["rows"] if r["status"] == "gap"]
        if gaps:
            g = gaps[0]
            out.append((1.2, {
                "area": "Pitching", "title": f"Attack plan: {g['stage_lbl'].split(' (')[0].lower()} vs {g['side_lbl'].lower()}",
                "why": (f"As a {pt['type']}, the plan there is {g['plan']}; in games he threw {g['actual'].split(' of ')[0]}. "
                        f"{len(gaps)} count / hitter-hand spot{'s' if len(gaps) > 1 else ''} didn't match his type."),
                "measure": "", "target": None, "retest": RETEST_DEFAULT.isoformat(),
                "drills": "Script live ABs by count: throw the plan pitch in that count and side\n"
                          "Go through his Pitcher Type card with the pitching coach before each scrimmage",
                "goal_id": None}))
    lanes = rep.get("lanes")
    if lanes and rep.get("lanes_takeaway") and "costing the zone" in rep["lanes_takeaway"]:
        out.append((1.1, {
            "area": "Pitching", "title": "Command on the corners",
            "why": rep["lanes_takeaway"], "measure": "g:p_spot",
            "target": game_goals.suggest_target("p_spot", rep["you"].get("execution_pct")),
            "retest": RETEST_DEFAULT.isoformat(),
            "drills": "Target pens alternating middle and corner setups -- chart the miss on each\n"
                      "Corner pens: 10 to each edge, track hit-the-spot %",
            "goal_id": None}))
    return out


def _body_candidates(rep):
    from analytics import athlete_archetype as aa
    out = []
    b = rep.get("body") or {}
    arch, raw = b.get("arch"), b.get("arch_raw")
    pid = rep["player"].player_id
    if arch and raw:
        spec = aa.goal_spec(pid, raw, arch)
        if spec:
            focus = aa.TRAINING.get(arch["kind"], {})
            out.append((1.0 + (50 - arch["worst"]["pct"]) / 25, {
                "area": "Body",
                "title": f"{'Lower' if spec['target'] < spec['baseline'] else 'Raise'} {spec['label'].lower()}",
                "why": (f"{arch['kind']} athlete; his biggest opportunity is {spec['label'].lower()} "
                        f"({arch['worst']['pct']}th percentile on the team). Target = the team middle."),
                "measure": f"t:{spec['test']}", "target": round(spec["target"], 2), "retest": RETEST_DEFAULT.isoformat(),
                "drills": "\n".join(focus.get("do", GENERIC_DRILLS)[:2]), "goal_id": None}))
    lad = b.get("ladder")
    if lad and lad.get("start") in ("Mobility", "Stability"):
        out.append((1.3, {
            "area": "Body", "title": f"{lad['start']} first",
            "why": lad["read"], "measure": "", "target": None, "retest": RETEST_DEFAULT.isoformat(),
            "drills": ("Daily mobility block for the limited joint (shoulder / hip) -- retest range\n"
                       "Strength staff sets the program around it" if lad["start"] == "Mobility" else
                       "Lead-leg block and landing / decel work 2-3x a week\n"
                       "Single-leg stability work; retest jump / decel tests"),
            "goal_id": None}))
    return out


def suggest_priorities(db, rep, n=N_PRIORITIES):
    """Top n distinct priorities: his biggest performance gap, his biggest
    body gap (when he has one), then the next biggest of anything."""
    perf = sorted(_perf_candidates(rep) + _plan_candidates(rep), key=lambda t: -t[0])
    bod = sorted(_body_candidates(rep), key=lambda t: -t[0])
    picked, seen = [], set()

    def take(c):
        key = (c["measure"] or c["title"])
        if key in seen or len(picked) >= n:
            return
        seen.add(key)
        picked.append(c)
    if perf:
        take(perf[0][1])
    if bod:
        take(bod[0][1])
    for _s, c in sorted(perf[1:] + bod[1:], key=lambda t: -t[0]):
        take(c)
    while len(picked) < n:
        picked.append(blank_priority())
    return picked


def blank_priority():
    return {"area": "", "title": "", "why": "", "measure": "", "target": None, "retest": RETEST_DEFAULT.isoformat(),
            "drills": "", "goal_id": None}


def measure_choices(is_pitcher):
    """{value: label} for the priority 'how it's measured' picker."""
    from analytics.research_progress import BATTERY
    out = {"": "No number -- coach checks it"}
    for k, (label, _side, hib, _u, _d) in game_goals.metrics_for(is_pitcher).items():
        if k == "p_velo":
            continue
        out[f"g:{k}"] = f"Games: {label} ({'higher' if hib else 'lower'} is better)"
    for _cat, tests in BATTERY:
        for t in tests:
            out[f"t:{t}"] = f"Test: {t}"
    return out


def measure_now(db, pid, measure, season_id=None):
    """His current value for a measure: game metric over this fall's games,
    or his latest test result. -> (value, display) or (None, '—')."""
    if not measure:
        return None, "—"
    kind, _, name = measure.partition(":")
    if kind == "g" and name in game_goals.GAME_METRICS:
        side = game_goals.GAME_METRICS[name][1]
        if side == "hit":
            pitches = hitter_report.hitter_pitches(db, pid, season_id=season_id)
        else:
            pitches = player_report.pitcher_pitches(db, pid, season_id=season_id)
        v = game_goals.value(db, name, pitches)
        return v, game_goals.fmt(name, v)
    if kind == "t":
        r = (db.query(AssessmentResult.value, AssessmentTestType.unit)
             .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
             .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
             .filter(Assessment.player_id == pid, AssessmentTestType.test_name == name, AssessmentResult.value.isnot(None))
             .order_by(Assessment.assessment_date.desc()).first())
        if r is None:
            return None, "not tested yet"
        return float(r[0]), f"{float(r[0]):.2f} {r[1] or ''}".strip()
    return None, "—"


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

def load_plan(db, pid, season_id):
    from models import ExitReport
    return (db.query(ExitReport).filter(ExitReport.player_id == pid, ExitReport.season_id == season_id).first())


def _goal_description(p, season_name):
    text = (p.get("title") or "").strip()
    if p.get("why"):
        text += f" -- {p['why'].strip()}"
    return f"Exit plan ({season_name}): {text}"[:2000]


def save_plan(db, pid, season_id, season_name, priorities, notes, met_on, user_id):
    """Store the coach's plan and create / update one IDP goal per filled-in
    priority. -> (ExitReport, [messages]). Commits."""
    from models import ExitReport, IDPGoal, IDPStatus, AssessmentCategory
    msgs = []
    rep = load_plan(db, pid, season_id)
    if rep is None:
        rep = ExitReport(player_id=pid, season_id=season_id)
        db.add(rep)
    st = (db.query(IDPStatus).filter(IDPStatus.status_name == "In Progress").first()
          or db.query(IDPStatus).order_by(IDPStatus.display_order).first())
    perf_cat = (db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Baseball Performance").first()
                or db.query(AssessmentCategory).first())
    out = []
    for p in priorities:
        p = {**blank_priority(), **p}
        if not (p.get("title") or "").strip():
            out.append(p)
            continue
        kind, _, name = (p.get("measure") or "").partition(":")
        baseline, _disp = measure_now(db, pid, p.get("measure"), season_id)
        tt = None
        if kind == "t":
            tt = db.query(AssessmentTestType).filter(AssessmentTestType.test_name == name).first()
        cat_id = tt.category_id if tt is not None else perf_cat.category_id
        retest = None
        try:
            retest = date.fromisoformat(p["retest"]) if p.get("retest") else None
        except ValueError:
            retest = None
        goal = db.query(IDPGoal).filter(IDPGoal.goal_id == p["goal_id"], IDPGoal.player_id == pid).first() \
            if p.get("goal_id") else None
        if goal is None:
            goal = IDPGoal(player_id=pid, status_id=st.status_id, created_by_user_id=user_id,
                           created_at=datetime.utcnow(), description="")
            db.add(goal)
            msgs.append(f"New IDP goal: {p['title']}")
        goal.category_id = cat_id
        goal.description = _goal_description(p, season_name)
        goal.target_test_type_id = tt.test_type_id if tt is not None else None
        goal.baseline_value = round(baseline, 3) if baseline is not None else None
        goal.target_value = float(p["target"]) if p.get("target") not in (None, "") else None
        goal.target_date = retest
        goal.updated_at = datetime.utcnow()
        if kind == "g" and name in game_goals.GAME_METRICS:
            goal.game_metric = name
            goal.metric_window = GOAL_WINDOW
        elif goal.goal_id is not None or kind != "g":
            # only touch the deferred columns when they can matter (avoids a
            # needless error before migrate_idp_game_goals has run)
            if getattr(goal, "game_metric", None):
                goal.game_metric = None
                goal.metric_window = None
        db.flush()
        p["goal_id"] = goal.goal_id
        out.append(p)
    rep.priorities = out
    rep.coach_notes = (notes or "").strip() or None
    rep.met_on = met_on
    rep.status = "saved"
    rep.saved_by_user_id = user_id
    rep.saved_at = datetime.utcnow()
    rep.updated_at = datetime.utcnow()
    db.commit()
    return rep, msgs
