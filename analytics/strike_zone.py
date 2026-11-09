"""
Per-batter ABS-style strike zone for GBO.

Shared foundation for catcher framing (analytics/catcher_framing.py) and
umpire scorecards (analytics/umpire_scorecard.py).

Zone definition (MLB ABS, 2026):
  - top    = 53.5% of the batter's standing height
  - bottom = 27%   of the batter's standing height
  - width  = 17 in (home plate), measured at the MIDPOINT of the plate
  - a pitch is a strike if any part of the ball touches the zone, so the
    box is grown by one ball radius on every side before grading.

Coordinate convention (catcher's view, feet):
  plate_x : horizontal, 0 = middle of plate, + = catcher's right
  plate_z : height above the ground
CONFIRM against the SmartPark/Yakkertech export once it exists: which sign
is "catcher's right", and whether plate location is reported at the front
of the plate or the midpoint. If it is the front edge, a small vertical
correction may be needed for pitches with steep descent.

Pure numpy/pandas, no DB access, so it can be tested on synthetic data.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# --- Zone constants -------------------------------------------------------
ABS_TOP_PCT = 0.535
ABS_BOTTOM_PCT = 0.27
PLATE_HALF_WIDTH_IN = 8.5
BALL_RADIUS_IN = 1.47            # ~2.94 in diameter / 2

# Pitches whose ball-edge is within this many inches of the zone edge are
# "too close to grade" for umpire accuracy (tracking error band).
GRADING_TOLERANCE_IN = 1.0

# Called pitches only. Map SmartPark pitch-call labels to these two values
# in the importer; everything else (swings, HBP, fouls) is excluded.
CALLED_STRIKE = "called_strike"
BALL = "ball"
CALLED_PITCH_VALUES = (CALLED_STRIKE, BALL)


def abs_zone_ft(height_in):
    """Return (bottom_ft, top_ft) of the ABS zone for a batter height in inches.

    Works on scalars or arrays. Does NOT include the ball radius.
    """
    h = np.asarray(height_in, dtype=float)
    return h * ABS_BOTTOM_PCT / 12.0, h * ABS_TOP_PCT / 12.0


def signed_distance_in(plate_x_ft, plate_z_ft, sz_bot_ft, sz_top_ft):
    """Signed distance (inches) from the ball's CENTER to the strike boundary.

    The boundary is the ABS box grown by one ball radius, so:
      distance <= 0  -> some part of the ball touched the zone (true strike)
      distance  > 0  -> true ball, by that many inches
    Inside the box the value is minus the distance to the nearest edge.
    """
    x = np.asarray(plate_x_ft, dtype=float) * 12.0
    z = np.asarray(plate_z_ft, dtype=float) * 12.0
    bot = np.asarray(sz_bot_ft, dtype=float) * 12.0 - BALL_RADIUS_IN
    top = np.asarray(sz_top_ft, dtype=float) * 12.0 + BALL_RADIUS_IN
    half_w = PLATE_HALF_WIDTH_IN + BALL_RADIUS_IN

    # How far outside each axis (0 if within that axis' range)
    dx_out = np.maximum(np.abs(x) - half_w, 0.0)
    dz_out = np.maximum(np.maximum(bot - z, z - top), 0.0)
    outside = np.hypot(dx_out, dz_out)

    # Inside: distance to nearest edge (negative)
    dx_in = half_w - np.abs(x)
    dz_in = np.minimum(z - bot, top - z)
    inside = -np.minimum(dx_in, dz_in)

    is_out = (dx_out > 0) | (dz_out > 0)
    return np.where(is_out, outside, inside)


def nearest_edge(plate_x_ft, plate_z_ft, sz_bot_ft, sz_top_ft, batter_hand):
    """Label the zone edge each pitch is closest to: top, bottom, inside, outside.

    inside/outside are relative to the batter (R batter stands on the
    catcher's left in catcher's view, so catcher's-left = inside for RHB).
    """
    x = np.asarray(plate_x_ft, dtype=float) * 12.0
    z = np.asarray(plate_z_ft, dtype=float) * 12.0
    bot = np.asarray(sz_bot_ft, dtype=float) * 12.0
    top = np.asarray(sz_top_ft, dtype=float) * 12.0
    mid_z = (bot + top) / 2.0
    half_h = (top - bot) / 2.0

    # Compare normalized offsets so tall/short zones are treated alike
    nx = np.abs(x) / PLATE_HALF_WIDTH_IN
    nz = np.abs(z - mid_z) / half_h
    vertical = nz >= nx

    hand = np.asarray(batter_hand).astype(str)
    catcher_left = x < 0
    inside_side = np.where(hand == "R", catcher_left, ~catcher_left)

    return np.where(
        vertical,
        np.where(z >= mid_z, "top", "bottom"),
        np.where(inside_side, "inside", "outside"),
    )


def count_group(balls, strikes):
    """Group counts the way called-strike rates actually differ."""
    b = np.asarray(balls)
    s = np.asarray(strikes)
    return np.select(
        [(b == 3) & (s == 0), s == 2, b > s],
        ["3-0", "two_strike", "hitter_ahead"],
        default="even_or_pitcher_ahead",
    )


def prepare_called_pitches(df: pd.DataFrame) -> pd.DataFrame:
    """Filter to called pitches and add zone columns.

    Required columns:
      plate_x, plate_z (ft), batter_height_in, batter_hand ('R'/'L'),
      pitch_call, balls, strikes
    Adds:
      sz_bot, sz_top, dist_in, true_strike, is_called_strike,
      gradable, edge, count_group
    """
    need = {"plate_x", "plate_z", "batter_height_in", "batter_hand",
            "pitch_call", "balls", "strikes"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"prepare_called_pitches missing columns: {sorted(missing)}")

    out = df[df["pitch_call"].isin(CALLED_PITCH_VALUES)].copy()
    out = out.dropna(subset=["plate_x", "plate_z", "batter_height_in"])
    if out.empty:
        return out

    out["sz_bot"], out["sz_top"] = abs_zone_ft(out["batter_height_in"].to_numpy())
    out["dist_in"] = signed_distance_in(out["plate_x"], out["plate_z"],
                                        out["sz_bot"], out["sz_top"])
    out["true_strike"] = out["dist_in"] <= 0
    out["is_called_strike"] = out["pitch_call"] == CALLED_STRIKE
    out["gradable"] = out["dist_in"].abs() > GRADING_TOLERANCE_IN
    out["edge"] = nearest_edge(out["plate_x"], out["plate_z"], out["sz_bot"],
                               out["sz_top"], out["batter_hand"])
    out["count_group"] = count_group(out["balls"], out["strikes"])
    return out
