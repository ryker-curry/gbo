"""
Umpire scorecards for GBO, graded against the per-batter ABS zone
(analytics/strike_zone.py). Modeled on the Umpire Scorecards card.

Per game  -> game_scorecard():
  accuracy         correct calls / gradable called pitches. Pitches whose
                   ball edge is within GRADING_TOLERANCE_IN of the zone are
                   too close to grade (tracking error) and are excluded.
  expected acc.    what an average umpire in our data gets right on the same
                   pitch locations (binned by distance from the edge).
  relative acc.    correct calls above/below that expectation.
  consistency      share of calls consistent with the umpire's OWN zone
                   that game: balls called inside the convex hull of his
                   called strikes count as inconsistent.
  favor            run-expectancy swing of missed calls, net to each team.
  impactful misses the missed calls with the biggest run swing.

Across games -> umpire_tendencies():
  For each edge (top, bottom, inside, outside; inside/outside relative to
  the batter): how often he calls a strike just OFF the edge (expands) and
  just ON the edge (squeezes), vs. all umpires in our data. Rates are
  blended toward the all-umpire rate with TENDENCY_PRIOR_PITCHES pseudo-
  pitches, so one game can't make an umpire look extreme. The baseline is
  all OTHER umpires. tendency_notes() only reports edges that are large AND
  at least 2 standard errors from that baseline.

Required columns beyond strike_zone.prepare_called_pitches:
  umpire_id, game_id, batting_team, fielding_team,
  outs, on_1b, on_2b, on_3b (bools)
For favor you pass re_lookup(outs, on1, on2, on3, balls, strikes) ->
expected runs for the rest of the inning. Wire this to GBO's existing
RunExpectancy table.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.strike_zone import PLATE_HALF_WIDTH_IN, prepare_called_pitches

DIST_BINS_IN = [0, 1, 2, 3, 4, 6, 9, np.inf]   # |distance| bins for expected accuracy
TENDENCY_BAND_IN = 3.0       # "just off" / "just on" the edge = within 3 in
TENDENCY_PRIOR_PITCHES = 20  # blend weight toward the all-umpire rate (tunable)

# Standard zone used only for DRAWING (a 6'1" batter), so every pitch can be
# plotted on one box even though each batter had his own zone.
PLOT_HEIGHT_IN = 73
PLOT_BOT_FT = PLOT_HEIGHT_IN * 0.27 / 12
PLOT_TOP_FT = PLOT_HEIGHT_IN * 0.535 / 12


# ------------------------------------------------------------- helpers ---
def _normalized_xy(df):
    """x in plate half-widths (+/-1 = plate edges), z in zone heights (0..1)."""
    nx = df["plate_x"].to_numpy() * 12.0 / PLATE_HALF_WIDTH_IN
    nz = ((df["plate_z"] - df["sz_bot"]) / (df["sz_top"] - df["sz_bot"])).to_numpy()
    return nx, nz


def _convex_hull(points):
    """Monotone-chain convex hull. points: (n, 2) array. Returns CCW vertices."""
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def _strictly_inside_hull(hull, pts):
    if len(hull) < 3:
        return np.zeros(len(pts), dtype=bool)
    inside = np.ones(len(pts), dtype=bool)
    for i in range(len(hull)):
        a, b = hull[i], hull[(i + 1) % len(hull)]
        cr = (b[0] - a[0]) * (pts[:, 1] - a[1]) - (b[1] - a[1]) * (pts[:, 0] - a[0])
        inside &= cr > 1e-9
    return inside


def _after_call(call_strike, balls, strikes, outs, on1, on2, on3, re_lookup):
    """Expected runs (rest of inning) + runs scored right away, after a call."""
    if call_strike:
        if strikes == 2:
            new_outs = outs + 1
            return (0.0, 0) if new_outs >= 3 else (re_lookup(new_outs, on1, on2, on3, 0, 0), 0)
        return re_lookup(outs, on1, on2, on3, balls, strikes + 1), 0
    if balls == 3:  # walk: force runners
        runs = 1 if (on1 and on2 and on3) else 0
        n1, n2, n3 = True, on2 or on1, on3 or (on1 and on2)
        return re_lookup(outs, n1, n2, n3, 0, 0), runs
    return re_lookup(outs, on1, on2, on3, balls + 1, strikes), 0


def _run_swing_for_batting_team(row, re_lookup):
    """Batting team's run gain from the call made vs. the correct call."""
    args = (row.balls, row.strikes, row.outs, bool(row.on_1b), bool(row.on_2b),
            bool(row.on_3b), re_lookup)
    re_a, r_a = _after_call(row.is_called_strike, *args)
    re_c, r_c = _after_call(row.true_strike, *args)
    return (re_a + r_a) - (re_c + r_c)


def league_accuracy_by_distance(called: pd.DataFrame) -> pd.Series:
    """All-umpire accuracy by |distance| bin, from gradable pitches."""
    g = called[called["gradable"]]
    bins = pd.cut(g["dist_in"].abs(), DIST_BINS_IN)
    return (g["is_called_strike"] == g["true_strike"]).groupby(bins, observed=False).mean()


# ------------------------------------------------------------ per game ---
def game_scorecard(pitches: pd.DataFrame, game_id, re_lookup,
                   league_called: pd.DataFrame | None = None, top_misses=3):
    """Scorecard dict for one game.

    league_called: prepared called pitches from ALL games (for expected
    accuracy). Defaults to this game only, which makes relative accuracy 0.
    """
    called = prepare_called_pitches(pitches[pitches["game_id"] == game_id])
    if called.empty:
        return None
    if league_called is None:
        league_called = called

    graded = called[called["gradable"]].copy()
    graded["correct"] = graded["is_called_strike"] == graded["true_strike"]
    n_graded, n_correct = len(graded), int(graded["correct"].sum())

    lg = league_accuracy_by_distance(league_called)
    bins = pd.cut(graded["dist_in"].abs(), DIST_BINS_IN)
    expected_correct = float(bins.map(lg).astype(float).fillna(lg.mean()).sum())

    # Consistency vs. his own zone (normalized coords)
    nx, nz = _normalized_xy(called)
    pts = np.column_stack([nx, nz])
    strikes = called["is_called_strike"].to_numpy()
    hull = _convex_hull(pts[strikes]) if strikes.sum() >= 3 else np.empty((0, 2))
    balls_inside_euz = int(_strictly_inside_hull(hull, pts[~strikes]).sum())

    # Favor (missed, gradable calls only)
    missed = graded[~graded["correct"]].copy()
    if not missed.empty:
        missed["batting_gain"] = missed.apply(_run_swing_for_batting_team, axis=1,
                                              re_lookup=re_lookup)
    else:
        missed["batting_gain"] = []
    teams = pd.unique(called[["batting_team", "fielding_team"]].to_numpy().ravel())
    favor = {
        t: round(float(missed.loc[missed["batting_team"] == t, "batting_gain"].sum()
                       - missed.loc[missed["fielding_team"] == t, "batting_gain"].sum()), 3)
        for t in teams
    }

    impact = missed.reindex(missed["batting_gain"].abs().sort_values(ascending=False).index)
    cols = [c for c in ("inning", "inning_half", "pitcher_name", "batter_name",
                        "outs", "on_1b", "on_2b", "on_3b", "balls", "strikes")
            if c in impact.columns]
    top = []
    for _, r in impact.head(top_misses).iterrows():
        item = {c: r[c] for c in cols}
        item["call"] = "strike called a ball" if r["true_strike"] else "ball called a strike"
        item["miss_in"] = round(abs(float(r["dist_in"])), 1)
        item["run_swing"] = round(float(r["batting_gain"]), 3)
        item["favored"] = r["batting_team"] if r["batting_gain"] > 0 else r["fielding_team"]
        top.append(item)

    return {
        "game_id": game_id,
        "umpire_id": called["umpire_id"].iloc[0],
        "called_pitches": len(called),
        "too_close_to_grade": int((~called["gradable"]).sum()),
        "graded": n_graded,
        "correct": n_correct,
        "accuracy": round(100 * n_correct / n_graded, 1) if n_graded else None,
        "expected_accuracy": round(100 * expected_correct / n_graded, 1) if n_graded else None,
        "correct_above_expected": round(n_correct - expected_correct, 1),
        "consistency": round(100 * (1 - balls_inside_euz / len(called)), 1),
        "balls_inside_own_zone": balls_inside_euz,
        "accuracy_on_true_balls": _pct(graded, ~graded["true_strike"]),
        "accuracy_on_true_strikes": _pct(graded, graded["true_strike"]),
        "favor_runs": favor,
        "impactful_misses": top,
        "_called": called,   # for the chart
    }


def _pct(graded, mask):
    sub = graded[mask]
    return round(100 * sub["correct"].mean(), 1) if len(sub) else None


# --------------------------------------------------------- across games ---
def umpire_tendencies(pitches: pd.DataFrame, umpire_id) -> pd.DataFrame:
    """Where this umpire gives or takes away strikes vs. all umpires.

    Returns one row per edge with:
      expands_rate   strike rate on pitches 0-3 in OFF that edge
      squeezes_rate  ball rate on pitches 0-3 in ON that edge
      *_vs_avg       difference from all umpires, after blending
      n_off / n_on   pitches behind each number
    """
    called = prepare_called_pitches(pitches)
    near = called[called["dist_in"].abs() <= TENDENCY_BAND_IN]
    off = near[near["dist_in"] > 0]
    on = near[near["dist_in"] <= 0]
    k = TENDENCY_PRIOR_PITCHES

    rows = []
    for edge in ("top", "bottom", "inside", "outside"):
        # Baseline = every OTHER umpire, so an extreme umpire can't drag the
        # average toward himself.
        o_off = off[(off["edge"] == edge) & (off["umpire_id"] != umpire_id)]
        o_on = on[(on["edge"] == edge) & (on["umpire_id"] != umpire_id)]
        lg_off = o_off["is_called_strike"].mean() if len(o_off) else np.nan
        lg_on = (~o_on["is_called_strike"]).mean() if len(o_on) else np.nan
        u_off = off[(off["edge"] == edge) & (off["umpire_id"] == umpire_id)]
        u_on = on[(on["edge"] == edge) & (on["umpire_id"] == umpire_id)]
        exp = (u_off["is_called_strike"].sum() + k * lg_off) / (len(u_off) + k)
        sq = ((~u_on["is_called_strike"]).sum() + k * lg_on) / (len(u_on) + k)
        rows.append({
            "edge": edge,
            "expands_rate": round(100 * exp, 1),
            "expands_vs_avg": round(100 * (exp - lg_off), 1),
            "expands_z": _z(u_off["is_called_strike"].sum(), len(u_off), lg_off),
            "n_off": len(u_off),
            "squeezes_rate": round(100 * sq, 1),
            "squeezes_vs_avg": round(100 * (sq - lg_on), 1),
            "squeezes_z": _z((~u_on["is_called_strike"]).sum(), len(u_on), lg_on),
            "n_on": len(u_on),
        })
    return pd.DataFrame(rows).set_index("edge")


def _z(successes, n, base_rate):
    """How many standard errors his raw rate sits from the baseline."""
    if n == 0 or not (0 < base_rate < 1):
        return 0.0
    se = np.sqrt(base_rate * (1 - base_rate) / n)
    return round(float((successes / n - base_rate) / se), 2)


def tendency_notes(tend: pd.DataFrame, min_diff=8.0, min_z=2.0):
    """Plain-language takeaways for a pregame card.

    Only edges that are both big (min_diff points, after blending) and
    unlikely to be noise (min_z standard errors) make the card.
    """
    notes = []
    for edge, r in tend.iterrows():
        if r["expands_vs_avg"] >= min_diff and r["expands_z"] >= min_z:
            notes.append(f"Gives the {edge} strike off the plate "
                         f"({r['expands_rate']:.0f}% vs avg, +{r['expands_vs_avg']:.0f}).")
        if r["squeezes_vs_avg"] >= min_diff and r["squeezes_z"] >= min_z:
            notes.append(f"Squeezes the {edge} edge "
                         f"({r['squeezes_rate']:.0f}% balls on edge strikes, "
                         f"+{r['squeezes_vs_avg']:.0f}).")
    return notes or ["No edge stands out from the other umpires yet."]


# ---------------------------------------------------------------- chart ---
def missed_calls_figure(card, crimson="#BF1E2D", green="#4E9A5B"):
    """Plotly chart of missed calls on a standard zone (catcher's view)."""
    import plotly.graph_objects as go

    called = card["_called"]
    nx, nz = _normalized_xy(called)
    px = nx * PLATE_HALF_WIDTH_IN / 12.0
    pz = PLOT_BOT_FT + nz * (PLOT_TOP_FT - PLOT_BOT_FT)
    called = called.assign(px=px, pz=pz)
    miss = called[called["gradable"] & (called["is_called_strike"] != called["true_strike"])]

    fig = go.Figure()
    fig.add_shape(type="rect", x0=-PLATE_HALF_WIDTH_IN / 12, x1=PLATE_HALF_WIDTH_IN / 12,
                  y0=PLOT_BOT_FT, y1=PLOT_TOP_FT, line=dict(color="black", width=2))
    for is_k, color, label in ((True, crimson, "Ball called strike"),
                               (False, green, "Strike called ball")):
        m = miss[miss["is_called_strike"] == is_k]
        fig.add_trace(go.Scatter(x=m["px"], y=m["pz"], mode="markers", name=label,
                                 marker=dict(size=16, color=color, opacity=0.8,
                                             line=dict(color="black", width=1))))
    fig.update_layout(
        xaxis=dict(range=[-1.8, 1.8], visible=False, scaleanchor="y"),
        yaxis=dict(range=[0.6, 4.4], visible=False),
        height=420, margin=dict(l=10, r=10, t=30, b=10),
        legend=dict(orientation="h", y=-0.02), plot_bgcolor="white",
        title="Missed calls (catcher's view)",
    )
    return fig
