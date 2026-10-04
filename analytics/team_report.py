"""
GBO -- Team Game Report (Oct 2026, Ryker: "for both hitters and pitchers i
want the hitting and pitching coach as well as head coach to get game
reports for the entire team. be able to see a whole team page that shows
how we performed collectively as well as individual pages for each player
that the coaches can see." Answers: all coaches see both sides; in GBO +
email after each game; scope = game / series / season / any date range).

build(db, games) -> one dict with:
  record    -- W-L, runs for/against (Final, non-intrasquad games)
  pitching  -- team stat bundle (player_report.stat_bundle over every pitch
               our staff threw), pitch-type table, one row per pitcher
  hitting   -- team core numbers (hitter_insights.core_metrics over every
               pitch our hitters saw), swing decisions, by pitch type, one
               row per hitter
  standouts -- top pitchers / hitters for the email + page header
Intrasquads count both sides (our pitchers AND our hitters), same
convention every other GBO report uses.
"""

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import or_, and_
from sqlalchemy.orm import joinedload

from models import Game, GamePitch, Player, Season, PitchType
from analytics import hitter_insights as hi
from analytics.player_report import stat_bundle
from analytics.pitcher_game_report import _pitcher_id
from plate_discipline import SWING_OUTCOMES

STRIKES = {"Called Strike", "Swing and Miss", "Foul", "In Play"}
SERIES_GAP_DAYS = 2


def opponent_label(g):
    if g.is_intrasquad:
        return "Intrasquad"
    if getattr(g, "opponent_team", None) is not None:
        return g.opponent_team.team_name
    return g.opponent_name or "Opponent"


def game_label(g):
    opp = opponent_label(g)
    loc = "" if g.is_intrasquad else ("@ " if g.is_home is False else "vs ")
    score = ""
    if g.status == "Final" and not g.is_intrasquad:
        res = "W" if g.our_score > g.opponent_score else ("L" if g.our_score < g.opponent_score else "T")
        score = f"  {res} {g.our_score}-{g.opponent_score}"
    return f"{g.game_date.strftime('%b %d')}  {loc}{opp}{score}"


def tracked_games(db, season_id=None):
    ids = {gid for (gid,) in db.query(GamePitch.game_id).distinct().all()}
    if not ids:
        return []
    q = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id.in_(ids))
    if season_id is not None:
        q = q.filter(Game.season_id == season_id)
    return q.order_by(Game.game_date.desc(), Game.game_id.desc()).all()


def list_series(games):
    """Consecutive games vs the same opponent, no more than SERIES_GAP_DAYS
    apart -> [{"key", "label", "game_ids"}], newest first. Intrasquads are
    grouped the same way."""
    asc = sorted(games, key=lambda g: (g.game_date, g.game_id))
    groups = []
    for g in asc:
        opp = opponent_label(g)
        if groups and groups[-1]["opp"] == opp and (g.game_date - groups[-1]["last"]).days <= SERIES_GAP_DAYS:
            groups[-1]["games"].append(g)
            groups[-1]["last"] = g.game_date
        else:
            groups.append({"opp": opp, "games": [g], "last": g.game_date})
    out = []
    for grp in groups:
        gs = grp["games"]
        d0, d1 = gs[0].game_date, gs[-1].game_date
        dates = d0.strftime("%b %d") + ("" if d0 == d1 else f"–{d1.strftime('%b %d') if d1.month != d0.month else d1.strftime('%d')}")
        w = sum(1 for g in gs if g.status == "Final" and not g.is_intrasquad and g.our_score > g.opponent_score)
        l = sum(1 for g in gs if g.status == "Final" and not g.is_intrasquad and g.our_score < g.opponent_score)
        rec = f"  ({w}-{l})" if (w or l) else ""
        out.append({"key": f"{d0.isoformat()}|{grp['opp']}", "label": f"{grp['opp']} · {dates} · {len(gs)} game{'s' if len(gs) != 1 else ''}{rec}",
                    "game_ids": [g.game_id for g in gs]})
    return list(reversed(out))


# ---------------------------------------------------------------------------
# Pitch queries
# ---------------------------------------------------------------------------

def pitching_pitches(db, game_ids):
    if not game_ids:
        return []
    return (db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
            .filter(GamePitch.game_id.in_(game_ids))
            .filter(or_(GamePitch.is_our_team_batting.is_(False),
                        and_(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id.isnot(None))))
            .all())


def hitting_pitches(db, game_ids):
    if not game_ids:
        return []
    return (db.query(GamePitch).options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.game))
            .filter(GamePitch.game_id.in_(game_ids))
            .filter(or_(and_(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id.isnot(None)),
                        and_(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id.isnot(None))))
            .all())


def _batter_id(p):
    return p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id


def _pct(a, b):
    return round(100.0 * a / b, 1) if b else None


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def _record(games):
    fin = [g for g in games if g.status == "Final" and not g.is_intrasquad]
    w = sum(1 for g in fin if g.our_score > g.opponent_score)
    l = sum(1 for g in fin if g.our_score < g.opponent_score)
    t = len(fin) - w - l
    return {"games": len(games), "final": len(fin), "w": w, "l": l, "t": t,
            "rf": sum(g.our_score for g in fin), "ra": sum(g.opponent_score for g in fin),
            "intrasquads": sum(1 for g in games if g.is_intrasquad)}


def _pitch_type_table(pitches):
    by = defaultdict(list)
    for p in pitches:
        by[p.pitch_type.type_name if p.pitch_type else "Unspecified"].append(p)
    n = len(pitches)
    rows = []
    for label, ps in sorted(by.items(), key=lambda kv: -len(kv[1])):
        sw = [p for p in ps if p.pitch_outcome in SWING_OUTCOMES]
        bip = [p for p in ps if p.pitch_outcome == "In Play"]
        hits = sum(1 for p in bip if p.ab_outcome in ("1B", "2B", "3B", "HR"))
        rows.append({"Pitch": label, "Thrown": len(ps), "Usage %": _pct(len(ps), n),
                     "Strike %": _pct(sum(1 for p in ps if p.pitch_outcome in STRIKES), len(ps)),
                     "Whiff %": _pct(sum(1 for p in sw if p.pitch_outcome == "Swing and Miss"), len(sw)),
                     "In play": len(bip), "Hits": hits,
                     "Hard contact %": _pct(sum(1 for p in bip if p.contact_quality in hi.HARD_CONTACT), len(bip))})
    return rows


def build(db, games, names=None):
    game_ids = [g.game_id for g in games]
    names = names or {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    players = {p.player_id: p for p in db.query(Player).all()}

    # ---- pitching ----
    pp = pitching_pitches(db, game_ids)
    team_p = stat_bundle(pp, names) if pp else None
    by_pitcher = defaultdict(list)
    for p in pp:
        by_pitcher[_pitcher_id(p)].append(p)
    pitcher_rows = []
    for pid, ps in by_pitcher.items():
        if pid is None:
            continue
        b = stat_bundle(ps, names)
        pl = players.get(pid)
        pitcher_rows.append({"player_id": pid, "name": f"{pl.last_name}, {pl.first_name}" if pl else f"#{pid}",
                             "games": b["games"], "ip": b["ip_display"], "outs": b["outs"], "pitches": b["pitches"],
                             "bf": b["bf"], "h": b["hits"], "r": b["runs"], "bb": b["bb"], "k": b["ks"],
                             "strike_pct": b["strike_pct"], "fps_pct": b["fps_pct"], "whiff_pct": b["whiff_pct"],
                             "execution_pct": b["execution_pct"], "era": b["era"]})
    pitcher_rows.sort(key=lambda r: (-r["outs"], -r["pitches"]))

    # ---- hitting ----
    hp = hitting_pitches(db, game_ids)
    by_hitter = defaultdict(list)
    for p in hp:
        bid = _batter_id(p)
        if bid is not None:
            by_hitter[bid].append(p)
    team_h = hi.core_metrics(hp) if hp else None
    hitter_rows = []
    for bid, ps in by_hitter.items():
        m = hi.core_metrics(ps)
        pl = players.get(bid)
        pas = hi.plate_appearances(ps)
        ends = [pa[-1].ab_outcome for pa in pas if pa[-1].ends_plate_appearance]
        hitter_rows.append({"player_id": bid, "name": f"{pl.last_name}, {pl.first_name}" if pl else f"#{bid}",
                            "pa": m["PA"], "ab": m["AB"], "h": m["H"], "bb": m["BB"], "k": m["K"],
                            "2b": ends.count("2B"), "3b": ends.count("3B"), "hr": ends.count("HR"),
                            "avg": m["AVG"], "obp": m["OBP"], "slg": m["SLG"],
                            "sd": m["Swing Decision %"], "chase": m["Chase %"], "whiff": m["Whiff %"],
                            "hard": m["Hard contact %"], "ppa": m["Pitches/PA"],
                            "qab": m["QAB"], "qab_pct": m["QAB%"]})
    hitter_rows.sort(key=lambda r: (-r["pa"], r["name"]))
    if team_h is not None:
        ends = [pa[-1].ab_outcome for pa in hi.plate_appearances(hp) if pa[-1].ends_plate_appearance]
        team_h["2B"], team_h["3B"], team_h["HR"] = ends.count("2B"), ends.count("3B"), ends.count("HR")

    rep = {
        "games": games, "record": _record(games),
        "pitching": {"team": team_p, "rows": pitcher_rows, "types": _pitch_type_table(pp), "n": len(pp)},
        "hitting": {"team": team_h, "rows": hitter_rows, "n": len(hp),
                    "sd": hi.swing_decisions(hp) if hp else None,
                    "pt": hi.pitch_type_results(db, hp) if hp else None,
                    "fp": hi.first_pitch_two_strike(hp) if hp else None},
    }
    rep["standouts"] = standouts(rep)
    return rep


def standouts(rep):
    """A few plain lines: best pitching outings, best bats."""
    lines_p, lines_h = [], []
    for r in sorted(rep["pitching"]["rows"], key=lambda r: (-(r["k"] - r["bb"] - r["r"]), -r["outs"]))[:2]:
        if r["outs"] >= 3:
            lines_p.append(f"{r['name']}: {r['ip']} IP, {r['h']} H, {r['r']} R, {r['bb']} BB, {r['k']} K"
                           + (f", {r['strike_pct']:.0f}% strikes" if r["strike_pct"] is not None else ""))
    def _tb(r):
        return (r["h"] - r["2b"] - r["3b"] - r["hr"]) + 2 * r["2b"] + 3 * r["3b"] + 4 * r["hr"]
    for r in sorted(rep["hitting"]["rows"], key=lambda r: (-(_tb(r) + r["bb"]), -r["h"]))[:2]:
        if r["h"] or r["bb"]:
            xbh = ", ".join(x for x in ((f"{r['2b']} 2B" if r["2b"] else ""), (f"{r['3b']} 3B" if r["3b"] else ""),
                                        (f"{r['hr']} HR" if r["hr"] else "")) if x)
            lines_h.append(f"{r['name']}: {r['h']}-for-{r['ab']}" + (f", {xbh}" if xbh else "")
                           + (f", {r['bb']} BB" if r["bb"] else ""))
    return {"pitching": lines_p, "hitting": lines_h}
