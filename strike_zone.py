"""
GBO — Strike zone coordinate system (Game Tracking).

Replaces manual 1-9 zone-button entry with click-the-exact-spot
location, per Ryker's architecture doc.

Click capture uses Streamlit's own native st.plotly_chart(on_select=)
-- NOT the third-party streamlit-image-coordinates package, which
failed against a recent Streamlit release (ImportError on an internal
Streamlit class the package depended on, streamlit==1.61.1). Native
Plotly selection is first-party, documented Streamlit behavior
maintained by the Streamlit team itself, so it can't go stale against
future Streamlit releases the same way.

Coordinate convention (matches Statcast/Trackman): plate_x in feet,
0 = center of the plate; plate_z in feet, 0 = the ground.

The zone-derivation math (derive_old_zone, is_in_zone) is unchanged
from the original version -- verified with round-trip and zone-center
tests before this was wired into any page.
"""

import streamlit as st
import numpy as np
import plotly.graph_objects as go

X_MIN, X_MAX = -2.5, 2.5
Z_MIN, Z_MAX = 0.0, 5.0

# Generic average strike zone (17in plate width; knee-to-letters
# height). Not batter-specific -- GBO doesn't track individual batter
# heights/stances, so this is the same reasonable default everywhere,
# same as the old 1-9 grid was.
ZONE_HALF_WIDTH = 0.708  # ft, half of 17 inches
ZONE_BOTTOM, ZONE_TOP = 1.5, 3.5

GBO_CRIMSON = "#BF1E2D"
GBO_CREAM = "#FFFDE5"
BG_DARK = "#1E1E1E"
GRID_GRAY = "#3A3A3A"

# Click-grid resolution -- a dense invisible grid of selectable points
# spanning the view window. 30x30 gives roughly 2-inch click
# resolution, plenty precise for this use case.
_GRID_RES = 30
_GRID_X = np.linspace(X_MIN, X_MAX, _GRID_RES)
_GRID_Z = np.linspace(Z_MIN, Z_MAX, _GRID_RES)


def derive_old_zone(plate_x, plate_z):
    """Precise coordinates -> the old 1-9 grid + 0=Bury convention, so
    existing execution-accuracy calculations elsewhere in the app
    (game_stats.py, Bullpen/Hitter Tracking comparisons) keep working
    unchanged. Verified against all 9 zone centers + Bury + an
    outside-the-zone clamping case before use. Layout:
        1 2 3   (top third)
        4 5 6   (middle third)
        7 8 9   (bottom third)
    Meaningfully below the zone (more than ~2 inches under the bottom)
    -> 0 (Bury). Coordinates outside the zone horizontally or above it
    vertically are clamped to the nearest column/row rather than left
    unclassified -- there's no exact old-system equivalent for "how far
    outside," so nearest-zone is the most useful fallback."""
    if plate_x is None or plate_z is None:
        return None
    if plate_z < ZONE_BOTTOM - 0.15:
        return 0
    col_frac = (plate_x - (-ZONE_HALF_WIDTH)) / (2 * ZONE_HALF_WIDTH)
    col_frac = max(0.0, min(0.999, col_frac))
    col = int(col_frac * 3)
    row_frac = (ZONE_TOP - plate_z) / (ZONE_TOP - ZONE_BOTTOM)
    row_frac = max(0.0, min(0.999, row_frac))
    row = int(row_frac * 3)
    zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    return zone_layout[row][col]


def is_in_zone(plate_x, plate_z):
    """Simple in/out-of-zone check from precise coordinates -- used for
    a quick located/not-located indicator without needing the full
    heat-map classification work (Edge/Heart/Chase), which is a later
    phase."""
    if plate_x is None or plate_z is None:
        return None
    return (-ZONE_HALF_WIDTH <= plate_x <= ZONE_HALF_WIDTH) and (ZONE_BOTTOM <= plate_z <= ZONE_TOP)


def render_zone_selector(key, marker_x=None, marker_z=None):
    """Renders the clickable strike-zone graphic and returns whatever
    was clicked THIS run as (plate_x, plate_z), or (None, None) if
    nothing was clicked this run. marker_x/marker_z (a previously
    recorded click) are drawn as a small circle so the coach can see
    what's currently captured, not just a blank zone."""
    xs, zs = np.meshgrid(_GRID_X, _GRID_Z)
    xs, zs = xs.flatten(), zs.flatten()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=zs, mode="markers",
        marker=dict(size=16, opacity=0.001, color=GBO_CREAM),
        showlegend=False, hoverinfo="skip", name="grid",
    ))

    fig.add_shape(type="line", x0=X_MIN, x1=X_MAX, y0=0, y1=0, line=dict(color=GRID_GRAY, width=2))
    fig.add_shape(type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP, line=dict(color=GBO_CREAM, width=3))
    third_w = (2 * ZONE_HALF_WIDTH) / 3
    third_h = (ZONE_TOP - ZONE_BOTTOM) / 3
    for i in (1, 2):
        gx = -ZONE_HALF_WIDTH + third_w * i
        fig.add_shape(type="line", x0=gx, x1=gx, y0=ZONE_BOTTOM, y1=ZONE_TOP, line=dict(color=GBO_CREAM, width=1))
        gz = ZONE_BOTTOM + third_h * i
        fig.add_shape(type="line", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=gz, y1=gz, line=dict(color=GBO_CREAM, width=1))

    if marker_x is not None and marker_z is not None:
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[marker_z], mode="markers",
            marker=dict(size=18, color=GBO_CRIMSON, line=dict(color=GBO_CREAM, width=2)),
            showlegend=False, hoverinfo="skip", name="marker",
        ))

    fig.update_layout(
        xaxis=dict(range=[X_MIN, X_MAX], visible=False, fixedrange=True),
        yaxis=dict(range=[Z_MIN, Z_MAX], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_DARK,
        height=350, margin=dict(l=0, r=0, t=0, b=0),
        clickmode="event+select",
        dragmode=False,
    )

    result = st.plotly_chart(fig, on_select="rerun", key=key, config={"displayModeBar": False})

    # TEMPORARY DEBUG -- remove once click selection is confirmed working.
    # Shows exactly what Streamlit returns, so we can see the real
    # structure instead of continuing to guess at it.
    with st.expander("Debug: raw click result", expanded=False):
        st.write(result)

    if result:
        # Defensive: checking both "selection" and "select" since the
        # exact key couldn't be verified without live testing (no
        # network access to install/run plotly in the build sandbox).
        selection_data = result.get("selection") or result.get("select") or {}
        points = selection_data.get("points")
        if points:
            pt = points[0]
            return round(pt["x"], 3), round(pt["y"], 3)
    return None, None