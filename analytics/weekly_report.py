"""
GBO -- Weekly Progress Report (Oct 2026).

Ryker: weekly progress reports for players, automated. Decisions
(AskUserQuestion, Oct 2026):
  - Pitchers now; hitters once Blast/HitTrax import exists.
  - Content: this week vs last week (and his season) + Arsenal Plan
    progress.
  - Delivered in GBO ("My Weekly Report") AND a short email with a link,
    every Monday (scripts/send_weekly_reports.py).
  - Coaches can add an optional note through Sunday night; it goes out
    Monday either way (models.WeeklyReportNote).

WEEK = Monday-Sunday. The report for "week of Mon X" covers X..X+6 and
is sent the following Monday. Computed live from the data (nothing is
snapshotted), so a late Rapsodo import still shows up if the page is
reopened.

SECTIONS
  pitches   -- per pitch type, from ALL Rapsodo readings (bullpens + games):
               avg/max velo, ride (IVB), arm-side run, Stuff+; this week,
               last week, season. Only pitch types he threw this week.
  game      -- strike %, first-pitch strike %, whiff %, hit-the-spot %
               from game pitches (player_report.stat_bundle), same three
               windows. Omitted when he didn't pitch in a game this week.
  arsenal   -- Arsenal Plan targets built from his season readings
               (analytics/arsenal_plan.py, coach overrides respected);
               inches from target this week vs last week.
  highlights-- up to 3 auto lines (biggest gains / moves toward target),
               plus 1 "watch" line when something dropped clearly.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import joinedload

from models import Player, RapsodoPitch, GamePitch, Game, PitchType
from analytics.bullpen_metrics import pitch_type_label
from analytics import arsenal_plan, player_report

VELO_MOVE = 1.0      # mph change worth calling out
SHAPE_MOVE = 1.5     # inches toward/away from target worth calling out
PCT_MOVE = 8.0       # percentage points worth calling out (game stats are small-sample)
MIN_TYPE_N = 3


def week_start_for(d):
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def last_completed_week(today=None):
    today = today or date.today()
    return week_start_for(today) - timedelta(days=7)


def _dt(d):
    return datetime.combine(d, datetime.min.time())


def season_start(today=None):
    try:
        from bucket_system import current_season_label, season_date_range
        start, _end = season_date_range(current_season_label())
        if start:
            return start
    except Exception:
        pass
    today = today or date.today()
    return date(today.year if today.month >= 8 else today.year - 1, 8, 1)


def _raps(db, pid, d0, d1):
    return (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.player_id == pid, RapsodoPitch.pitch_date >= _dt(d0), RapsodoPitch.pitch_date < _dt(d1))
            .all())


def _game_pitches(db, pid, d0, d1):
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type))
            .filter(player_report._pitcher_filter(pid), Game.game_date >= d0, Game.game_date < d1)
            .all())


def _f(v):
    return float(v) if v is not None else None


def _type_shape(ps, throws, stuff_models):
    from analytics.pitch_grading import stuff_plus
    velos = [_f(p.velocity) for p in ps if p.velocity is not None]
    s = arsenal_plan.shape(ps, throws) or {}
    stuff = []
    model = stuff_models.get(pitch_type_label(ps[0])) if ps and stuff_models else None
    if model is not None:
        for p in ps:
            try:
                v = stuff_plus(p, model)
            except Exception:
                v = None
            if v is not None:
                stuff.append(v)
    return {
        "n": len(ps), "velo": sum(velos) / len(velos) if velos else None, "max": max(velos) if velos else None,
        "ivb": s.get("ivb"), "run": s.get("run"),
        "stuff": sum(stuff) / len(stuff) if stuff else None,
    }


def _by_type(ps):
    g = defaultdict(list)
    for p in ps:
        g[pitch_type_label(p)].append(p)
    return g


def build(db, player_id, week_start, stuff_models=None):
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if player is None:
        return None
    throws = player.throws or "R"
    w0, w1 = week_start, week_start + timedelta(days=7)
    p0 = week_start - timedelta(days=7)
    s0 = min(season_start(), p0)

    if stuff_models is None:
        try:
            from analytics import profile_queries
            stuff_models = profile_queries.team_stuff_plus_baselines(db)
        except Exception:
            stuff_models = {}

    season_raps = _raps(db, player_id, s0, w1)
    this_raps = [p for p in season_raps if _dt(w0) <= p.pitch_date < _dt(w1)]
    prev_raps = [p for p in season_raps if _dt(p0) <= p.pitch_date < _dt(w0)]
    this_games = _game_pitches(db, player_id, w0, w1)
    prev_games = _game_pitches(db, player_id, p0, w0)
    season_games = _game_pitches(db, player_id, s0, w1)

    bullpen_days = sorted({p.pitch_date.date() for p in this_raps if p.bullpen_id is not None})
    game_ids = sorted({p.game_id for p in this_games})
    games = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id.in_(game_ids)).all() if game_ids else []

    # --- pitches (Rapsodo) ---
    tw, lw, se = _by_type(this_raps), _by_type(prev_raps), _by_type(season_raps)
    pitch_rows = []
    for label, ps in sorted(tw.items(), key=lambda kv: -len(kv[1])):
        if len(ps) < MIN_TYPE_N:
            continue
        pitch_rows.append({
            "label": label,
            "this": _type_shape(ps, throws, stuff_models),
            "last": _type_shape(lw[label], throws, stuff_models) if len(lw.get(label, [])) >= MIN_TYPE_N else None,
            "season": _type_shape(se[label], throws, stuff_models) if se.get(label) else None,
        })

    # --- game ---
    names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    game = None
    if this_games:
        game = {
            "this": player_report.stat_bundle(this_games, names),
            "last": player_report.stat_bundle(prev_games, names) if prev_games else None,
            "season": player_report.stat_bundle(season_games, names) if season_games else None,
        }

    # --- arsenal progress ---
    arsenal = []
    plan = None
    try:
        from models import ArsenalTarget
        overrides = {r.family: {"velo": _f(r.velo), "ivb": float(r.ivb), "run": float(r.run)}
                     for r in db.query(ArsenalTarget).filter(ArsenalTarget.player_id == player_id).all()}
    except Exception:
        db.rollback()
        overrides = {}
    try:
        from analytics.bullpen_metrics import average_estimated_arm_angle
        fb_like = [p for p in season_raps if pitch_type_label(p) in arsenal_plan.FASTBALLS]
        arm, _n = average_estimated_arm_angle(fb_like or season_raps, player)
        hts = [float(p.release_height) for p in (fb_like or season_raps) if p.release_height is not None]
        plan = arsenal_plan.build_plan(season_raps, throws, arm, sum(hts) / len(hts) if hts else None,
                                       overrides=overrides, label_of=pitch_type_label)
    except Exception:
        plan = None
    if plan:
        for r in plan["rows"]:
            t = r.get("target")
            if not t:
                continue
            cur = arsenal_plan.shape(tw.get(r["label"], []), throws) if len(tw.get(r["label"], [])) >= MIN_TYPE_N else None
            prv = arsenal_plan.shape(lw.get(r["label"], []), throws) if len(lw.get(r["label"], [])) >= MIN_TYPE_N else None
            if cur is None:
                continue
            arsenal.append({
                "label": r["label"], "target_name": arsenal_plan.NAMES.get(r["family"], r["family"]),
                "this": round(arsenal_plan._dist(cur, t), 1),
                "last": round(arsenal_plan._dist(prv, t), 1) if prv else None,
                "target": t,
            })

    rep = {
        "player": player, "week_start": w0, "week_end": w1 - timedelta(days=1),
        "bullpen_days": bullpen_days, "games": games, "game_pitch_count": len(this_games),
        "rapsodo_count": len(this_raps), "pitches": pitch_rows, "game": game, "arsenal": arsenal,
    }
    rep["highlights"], rep["watch"] = _highlights(rep)
    rep["active"] = bool(this_raps or this_games)
    return rep


def _highlights(rep):
    good, bad = [], []
    for r in rep["pitches"]:
        t, l = r["this"], r["last"]
        if l and t["velo"] is not None and l["velo"] is not None:
            d = t["velo"] - l["velo"]
            if d >= VELO_MOVE:
                good.append((d / VELO_MOVE, f"{r['label']} velo up {d:.1f} mph from last week ({t['velo']:.1f})."))
            elif d <= -VELO_MOVE * 1.5:
                bad.append((-d, f"{r['label']} velo down {-d:.1f} mph from last week -- worth checking in on."))
        if t["max"] is not None and r["season"] and r["season"]["max"] is not None and t["max"] >= r["season"]["max"] - 0.05 and r["season"]["n"] > t["n"]:
            good.append((1.5, f"New season high on the {r['label'].lower()}: {t['max']:.1f} mph."))
    for a in rep["arsenal"]:
        if a["last"] is not None:
            d = a["last"] - a["this"]
            if d >= SHAPE_MOVE:
                good.append((d / SHAPE_MOVE, f"{a['label']} moved {d:.1f}\" toward its {a['target_name'].lower()} target "
                                             f"({a['this']:.1f}\" away now)."))
            elif d <= -SHAPE_MOVE * 1.5:
                bad.append((-d, f"{a['label']} drifted {-d:.1f}\" further from its target ({a['this']:.1f}\" away)."))
        if a["this"] <= arsenal_plan.KEEP_IN and (a["last"] is None or a["last"] > arsenal_plan.KEEP_IN):
            good.append((2.0, f"{a['label']} reached its target shape this week."))
    g = rep["game"]
    if g and g["last"]:
        for key, label in (("strike_pct", "Game strike %"), ("fps_pct", "First-pitch strike %"), ("execution_pct", "Hit-the-spot %")):
            t, l = g["this"].get(key), g["last"].get(key)
            if t is not None and l is not None and t - l >= PCT_MOVE:
                good.append(((t - l) / PCT_MOVE, f"{label} up to {t:.0f}% (from {l:.0f}%)."))
            elif t is not None and l is not None and l - t >= PCT_MOVE * 1.5:
                bad.append(((l - t) / PCT_MOVE, f"{label} down to {t:.0f}% (from {l:.0f}%)."))
    good = [t for _s, t in sorted(good, key=lambda x: -x[0])][:3]
    bad = [t for _s, t in sorted(bad, key=lambda x: -x[0])][:1]
    return good, bad


# ---------------------------------------------------------------------------
# Hitters (Oct 2026, Ryker: "build 4-7" -> #6). Same week windows, same
# email/page; built from game at-bats (no Blast/HitTrax yet), using the
# hitter_insights math so every number matches Hitter Profile.
# ---------------------------------------------------------------------------

HIT_MOVES = {  # key: (label, higher_is_better, move worth calling out, kind)
    "AVG": ("AVG", True, 0.060, "avg"),
    "OBP": ("OBP", True, 0.060, "avg"),
    "SLG": ("SLG", True, 0.100, "avg"),
    "Swing Decision %": ("Swing decisions", True, 6.0, "%"),
    "Chase %": ("Chase %", False, 6.0, "%"),
    "Whiff %": ("Whiff %", False, 6.0, "%"),
    "K%": ("Strikeout %", False, 8.0, "%"),
    "Hard contact %": ("Hard contact %", True, 10.0, "%"),
}
HIT_MIN_PA = 3


def _batting_pitches(db, pid, d0, d1):
    from sqlalchemy import or_, and_
    return (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
            .options(joinedload(GamePitch.pitch_type))
            .filter(or_(and_(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == pid),
                        and_(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id == pid)),
                    Game.game_date >= d0, Game.game_date < d1)
            .order_by(Game.game_date, GamePitch.pitch_sequence).all())


def _hfmt(kind, v):
    if v is None:
        return "—"
    if kind == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0") else s
    return f"{v:.0f}%"


def build_hitter(db, player_id, week_start):
    from analytics import hitter_insights as hi
    player = db.query(Player).filter(Player.player_id == player_id).first()
    if player is None:
        return None
    w0, w1 = week_start, week_start + timedelta(days=7)
    p0 = week_start - timedelta(days=7)
    s0 = min(season_start(), p0)
    season = _batting_pitches(db, player_id, s0, w1)
    this = [p for p in season if w0 <= p.game.game_date < w1]
    prev = [p for p in season if p0 <= p.game.game_date < w0]
    game_ids = sorted({p.game_id for p in this})
    games = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id.in_(game_ids)).all() if game_ids else []
    t, l, s = hi.core_metrics(this), hi.core_metrics(prev) if prev else None, hi.core_metrics(season) if season else None
    good, bad = [], []
    if t["PA"] >= HIT_MIN_PA:
        if t["H"]:
            good.append((0.8, f"{t['H']}-for-{t['AB']} this week" + (f" with {t['BB']} walk{'s' if t['BB'] != 1 else ''}." if t["BB"] else ".")))
        if l and l["PA"] >= HIT_MIN_PA:
            for key, (label, hib, move, kind) in HIT_MOVES.items():
                tv, lv = t.get(key), l.get(key)
                if tv is None or lv is None:
                    continue
                d = (tv - lv) if hib else (lv - tv)
                if d >= move:
                    good.append((d / move, f"{label} {'up' if tv > lv else 'down'} to {_hfmt(kind, tv)} (from {_hfmt(kind, lv)})."))
                elif d <= -move * 1.5:
                    bad.append((-d / move, f"{label} {'up' if tv > lv else 'down'} to {_hfmt(kind, tv)} (from {_hfmt(kind, lv)})."))
        if s and t.get("Swing Decision %") is not None and s.get("Swing Decision %") is not None \
                and t["Swing Decision %"] >= s["Swing Decision %"] + 5:
            good.append((1.2, f"Best swing decisions in a while: {t['Swing Decision %']:.0f}% (season {s['Swing Decision %']:.0f}%)."))
    sd = hi.swing_decisions(this)
    rep = {
        "kind": "hitter", "player": player, "week_start": w0, "week_end": w1 - timedelta(days=1),
        "bullpen_days": [], "games": games, "game_pitch_count": len(this), "rapsodo_count": 0,
        "this": t, "last": l, "season": s, "sd": sd,
        "pt": hi.pitch_type_results(db, this) if this else None,
        "highlights": [x for _s, x in sorted(good, key=lambda z: -z[0])][:3],
        "watch": [x for _s, x in sorted(bad, key=lambda z: -z[0])][:1],
        "active": bool(this),
    }
    return rep


def build_any(db, player_id, week_start, stuff_models=None):
    """Pitchers -> build(); everyone else -> build_hitter()."""
    p = db.query(Player).filter(Player.player_id == player_id).first()
    if p is None:
        return None
    return build(db, player_id, week_start, stuff_models=stuff_models) if p.is_pitcher else build_hitter(db, player_id, week_start)
