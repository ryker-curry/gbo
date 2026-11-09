"""
Catcher framing for GBO, adapted from Adam Maloof's 3Z / IW approach
(SABR Tooth Tigers, 2025) for a small, single-park sample where the zone
IS known (per-batter ABS zone from analytics/strike_zone.py).

Headline number: STRIKES GAINED PER 100 CALLED PITCHES (vs. average).

Two views, both per 100 called pitches:

1. Model framing (headline, IW-style)
   A called-strike probability model is fit on every called pitch in the
   data (PSU catchers AND opposing catchers in SmartPark games, so the
   baseline is bigger than our own staff). For each pitch:
       influence = actual_call (1/0) - P(called strike)
   Summed per catcher and scaled per 100. A strike stolen on a pitch that
   is rarely a strike earns more than one down the middle.
   Instead of Maloof's pixel maps (he had 1.1M pitches), the probability
   is a smooth logistic model of distance from the zone edge, which edge,
   batter hand and count group, so it works on a few thousand pitches.
   When umpire_id is present, umpire intercepts are included (ridge-shrunk
   toward zero) so a catcher isn't credited for a generous umpire. Both
   teams' catchers see the same umpire, which is what makes this work.

2. Zone framing (3Z-style check, uses the known zone)
   strikes gained = called strikes on true balls (outside tolerance band)
   strikes lost   = balls on true strikes (outside tolerance band)
   Reported raw and vs. the average rate on the same opportunities.

Required columns (in addition to strike_zone.prepare_called_pitches):
  catcher_id  -- any hashable id; opposing catchers included
Optional:
  umpire_id
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analytics.strike_zone import GRADING_TOLERANCE_IN, prepare_called_pitches

EDGES = ("top", "bottom", "inside", "outside")
COUNT_GROUPS = ("even_or_pitcher_ahead", "hitter_ahead", "two_strike", "3-0")
DIST_CLIP_IN = 8.0          # beyond 8 in either way the call is ~certain
RIDGE_LAMBDA = 1.0          # general shrinkage for the logistic fit
UMPIRE_RIDGE_LAMBDA = 25.0  # stronger pull on umpire intercepts (few games each)
LOW_SAMPLE_CALLED = 250     # flag catchers with fewer called pitches than this


# ---------------------------------------------------------------- model ---
def _design_matrix(df: pd.DataFrame, umpire_levels=None):
    d = np.clip(df["dist_in"].to_numpy(dtype=float), -DIST_CLIP_IN, DIST_CLIP_IN)
    cols, names, penalties = [], [], []

    for e in EDGES:                       # edge-specific intercept + slope
        ind = (df["edge"].to_numpy() == e).astype(float)
        cols += [ind, ind * d]
        names += [f"edge_{e}", f"edge_{e}_x_dist"]
        penalties += [0.0, 0.0]

    lhb = (df["batter_hand"].to_numpy() == "L").astype(float)
    cols.append(lhb); names.append("lhb"); penalties.append(RIDGE_LAMBDA)

    cg = df["count_group"].to_numpy()
    for g in COUNT_GROUPS[1:]:            # first group is the baseline
        cols.append((cg == g).astype(float))
        names.append(f"count_{g}"); penalties.append(RIDGE_LAMBDA)

    if umpire_levels is not None:
        u = df["umpire_id"].to_numpy()
        for lvl in umpire_levels:
            cols.append((u == lvl).astype(float))
            names.append(f"ump_{lvl}"); penalties.append(UMPIRE_RIDGE_LAMBDA)

    X = np.column_stack(cols)
    return X, names, np.array(penalties)


def _fit_logistic(X, y, penalties, iters=50):
    """Ridge-penalized logistic regression via IRLS (numpy only)."""
    beta = np.zeros(X.shape[1])
    P = np.diag(penalties)
    for _ in range(iters):
        eta = np.clip(X @ beta, -30, 30)
        p = 1.0 / (1.0 + np.exp(-eta))
        w = np.maximum(p * (1 - p), 1e-6)
        grad = X.T @ (y - p) - P @ beta
        H = (X * w[:, None]).T @ X + P + 1e-8 * np.eye(len(beta))
        step = np.linalg.solve(H, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-7:
            break
    return beta


def fit_called_strike_model(called: pd.DataFrame, adjust_for_umpire=True):
    """Fit P(called strike). `called` = output of prepare_called_pitches."""
    use_ump = (adjust_for_umpire and "umpire_id" in called.columns
               and called["umpire_id"].notna().all())
    levels = sorted(called["umpire_id"].unique()) if use_ump else None
    X, names, pen = _design_matrix(called, levels)
    y = called["is_called_strike"].to_numpy(dtype=float)
    beta = _fit_logistic(X, y, pen)
    return {"beta": beta, "names": names, "umpire_levels": levels}


def predict_strike_prob(model, called: pd.DataFrame):
    X, _, _ = _design_matrix(called, model["umpire_levels"])
    eta = np.clip(X @ model["beta"], -30, 30)
    return 1.0 / (1.0 + np.exp(-eta))


# -------------------------------------------------------------- metrics ---
def framing_leaderboard(pitches: pd.DataFrame, adjust_for_umpire=True,
                        catcher_ids=None) -> pd.DataFrame:
    """Per-catcher framing table, best first.

    pitches: raw pitch rows (any pitch calls); filtered internally.
    catcher_ids: optional subset to report (e.g., PSU catchers only).
                 The model is still fit on everyone.
    """
    called = prepare_called_pitches(pitches)
    if called.empty:
        return pd.DataFrame()

    model = fit_called_strike_model(called, adjust_for_umpire)
    called = called.assign(p_strike=predict_strike_prob(model, called))
    called["influence"] = called["is_called_strike"].astype(float) - called["p_strike"]

    tol = GRADING_TOLERANCE_IN
    called["zone_gain"] = (called["dist_in"] > tol) & called["is_called_strike"]
    called["zone_loss"] = (called["dist_in"] < -tol) & ~called["is_called_strike"]
    called["opp_out"] = called["dist_in"] > tol
    called["opp_in"] = called["dist_in"] < -tol

    avg_gain_rate = called.loc[called["opp_out"], "zone_gain"].mean()
    avg_loss_rate = called.loc[called["opp_in"], "zone_loss"].mean()

    g = called.groupby("catcher_id")
    out = pd.DataFrame({
        "called_pitches": g.size(),
        "strikes_gained": g["influence"].sum(),
        "zone_strikes_gained": g["zone_gain"].sum(),
        "zone_strikes_lost": g["zone_loss"].sum(),
        "opp_out": g["opp_out"].sum(),
        "opp_in": g["opp_in"].sum(),
    })
    out["strikes_gained_per_100"] = 100 * out["strikes_gained"] / out["called_pitches"]
    out["zone_net_per_100"] = 100 * (out["zone_strikes_gained"]
                                     - out["zone_strikes_lost"]) / out["called_pitches"]
    expected_net = out["opp_out"] * avg_gain_rate - out["opp_in"] * avg_loss_rate
    out["zone_net_vs_avg_per_100"] = 100 * (
        (out["zone_strikes_gained"] - out["zone_strikes_lost"]) - expected_net
    ) / out["called_pitches"]
    out["low_sample"] = out["called_pitches"] < LOW_SAMPLE_CALLED

    # Edge breakdown: where each catcher gains or loses strikes (per 100 at that edge)
    by_edge = (called.groupby(["catcher_id", "edge"])["influence"]
               .agg(["sum", "size"]))
    by_edge = (100 * by_edge["sum"] / by_edge["size"]).unstack("edge")
    by_edge.columns = [f"per_100_{c}" for c in by_edge.columns]
    out = out.join(by_edge)

    out = out.drop(columns=["opp_out", "opp_in"]).round(2)
    if catcher_ids is not None:
        out = out[out.index.isin(catcher_ids)]
    return out.sort_values("strikes_gained_per_100", ascending=False)
