"""
GBO — Batted-ball field location (Game Tracking).

Captures WHERE a ball in play landed, as raw coordinates -- not a
Pull/Straight/Oppo classification. That classification depends on
batter handedness, which varies by scenario (our batter, an intrasquad
opponent, an external roster player, or hand-only) and is better
computed later at analysis time than resolved live during entry --
same "store what happened, compute the derived stat later" principle
as everywhere else in this data model.

Click capture (in the Streamlit UI, via render_field_selector below)
uses Streamlit's own native st.plotly_chart(on_select=) -- NOT the
third-party streamlit-image-coordinates package, which failed against
a recent Streamlit release. See strike_zone.py for the full
explanation; same fix applied here for consistency.

Coordinate convention: feet from home plate. x = feet right of the
center-field line (negative = left field side, positive = right field
side); y = feet from home plate toward the outfield (0 = the plate).

Shiny for Python migration note: build_field_selector_figure() below is
the pure, framework-agnostic part (figure construction only, no
Streamlit import) -- the Shiny UI layer calls it directly and captures
clicks via shinywidgets' FigureWidget .on_click() instead of
st.plotly_chart(on_select=). render_field_selector() is kept as a thin
Streamlit-only wrapper around it so existing Streamlit pages keep
working unchanged until they're migrated.
"""

import math
import numpy as np
import plotly.graph_objects as go

X_MIN, X_MAX = -350, 350
Y_MIN, Y_MAX = -20, 420

GBO_CRIMSON = "#BF1E2D"
GBO_CREAM = "#FFFDE5"
BG_DARK = "#1E1E1E"

# Click-grid resolution -- a dense invisible grid of selectable points
# spanning the field. 35x35 gives roughly 20-foot resolution across
# the full outfield, plenty precise for charting purposes.
_GRID_RES = 35
_GRID_X = np.linspace(X_MIN, X_MAX, _GRID_RES)
_GRID_Y = np.linspace(Y_MIN, Y_MAX, _GRID_RES)


def distance_from_plate(x, y):
    """Straight-line feet from home plate -- useful later for a rough
    infield/outfield split without needing a batter-specific
    classification."""
    if x is None or y is None:
        return None
    return round(math.hypot(x, y), 1)


# Spray-angle Pull/Center/Oppo classification -- the analysis-time
# derivation this module's own docstring said belonged elsewhere
# ("better computed later at analysis time than resolved live during
# entry"). Standard sabermetric convention (matching Baseball Savant's
# own Pull%/Straight%/Oppo% split): the 90-degree fair-territory arc
# (45 degrees each side of the CF line) is divided into three equal
# 30-degree bands -- the middle 30 degrees (+-15 from dead center) is
# Center, the two outer 30-degree bands are Pull/Oppo depending on
# which side of the plate the batter stands on.
_SPRAY_HALF_ANGLE = 15  # degrees each side of dead-center = "Center"


def classify_spray_direction(x, y, bats=None):
    """x/y in this module's own feet-from-plate convention (see module
    docstring). bats is the hitter's Player.bats -- 'R' or 'L' gives a
    batter-relative Pull/Center/Oppo label; anything else (None, or 'S'
    for switch-hitters, since GBO doesn't record which side a switch-
    hitter actually batted from on a given PA) falls back to raw
    Left Field/Center/Right Field instead of guessing a side."""
    if x is None or y is None or y <= 0:
        return None
    angle = math.degrees(math.atan2(x, y))  # 0 = dead center, + = right field side, - = left field side
    if bats == "R":
        if angle < -_SPRAY_HALF_ANGLE:
            return "Pull"
        if angle > _SPRAY_HALF_ANGLE:
            return "Oppo"
        return "Center"
    if bats == "L":
        if angle > _SPRAY_HALF_ANGLE:
            return "Pull"
        if angle < -_SPRAY_HALF_ANGLE:
            return "Oppo"
        return "Center"
    if angle < -_SPRAY_HALF_ANGLE:
        return "Left Field"
    if angle > _SPRAY_HALF_ANGLE:
        return "Right Field"
    return "Center"


def build_field_selector_figure(marker_x=None, marker_y=None):
    """Pure figure builder -- foul lines, outfield arc, infield
    reference dots, invisible dense click-grid, and (if given) a marker
    at the currently-recorded click. No Streamlit/UI-framework
    dependency: returns a plain plotly Figure that any UI layer can
    render and attach click-capture to on its own terms."""
    xs, ys = np.meshgrid(_GRID_X, _GRID_Y)
    xs, ys = xs.flatten(), ys.flatten()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers",
        marker=dict(size=14, opacity=0.001, color=GBO_CREAM),
        showlegend=False, hoverinfo="none", name="grid",
    ))

    line_dist = 400
    for sign in (-1, 1):
        end_x = sign * line_dist * math.sin(math.radians(45))
        end_y = line_dist * math.cos(math.radians(45))
        fig.add_shape(type="line", x0=0, y0=0, x1=end_x, y1=end_y, line=dict(color=GBO_CREAM, width=2))

    # Outfield arc, drawn as a dense path of small line segments (Plotly
    # shapes don't support a true arc primitive like PIL does)
    radius_ft = 350
    arc_x, arc_y = [], []
    for deg in range(-45, 46):
        rad = math.radians(deg)
        arc_x.append(radius_ft * math.sin(rad))
        arc_y.append(radius_ft * math.cos(rad))
    fig.add_trace(go.Scatter(x=arc_x, y=arc_y, mode="lines", line=dict(color=GBO_CREAM, width=2), showlegend=False, hoverinfo="skip", name="arc"))

    base_dist = 90
    base_x, base_y = [], []
    for angle in (45, 135, 225, 315):
        base_x.append(base_dist * math.sin(math.radians(angle)))
        base_y.append(base_dist * math.cos(math.radians(angle)))
    fig.add_trace(go.Scatter(x=base_x, y=base_y, mode="markers", marker=dict(size=6, color=GBO_CREAM), showlegend=False, hoverinfo="skip", name="bases"))

    if marker_x is not None and marker_y is not None:
        fig.add_trace(go.Scatter(
            x=[marker_x], y=[marker_y], mode="markers",
            marker=dict(size=18, color=GBO_CRIMSON, line=dict(color=GBO_CREAM, width=2)),
            showlegend=False, hoverinfo="skip", name="marker",
        ))

    fig.update_layout(
        xaxis=dict(range=[X_MIN, X_MAX], visible=False, fixedrange=True),
        yaxis=dict(range=[Y_MIN, Y_MAX], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_DARK,
        height=370, margin=dict(l=0, r=0, t=0, b=0),
        # "event" only, not "event+select" -- the active Shiny click
        # capture (click_widgets.py) only ever listens for the plain
        # plotly_click event and writes coordinates manually; native
        # Plotly "select" mode was only needed by the old Streamlit
        # on_select="rerun" path below (frozen/reference-only), and its
        # default click-dims-the-point selection styling was causing a
        # dead-looking click in Command Tracker (Aug 2026, Ryker report:
        # "click one and the dot goes dim and nothing happens").
        clickmode="event",
        dragmode=False,
    )
    return fig


def render_field_selector(key, marker_x=None, marker_y=None):
    """Streamlit-only wrapper: renders the field figure via
    st.plotly_chart(on_select=) and returns whatever was clicked THIS
    run as (x, y), or (None, None) if nothing was clicked this run.
    Kept as-is for existing Streamlit pages -- the Shiny UI layer
    should call build_field_selector_figure() directly instead and
    implement its own click capture (see module docstring)."""
    import streamlit as st

    fig = build_field_selector_figure(marker_x=marker_x, marker_y=marker_y)
    result = st.plotly_chart(fig, on_select="rerun", key=key, config={"displayModeBar": False})

    # TEMPORARY DEBUG -- remove once click selection is confirmed working
    # live (was previously never actually confirmed, since the build
    # sandbox has no browser to click-test against -- kept in for one
    # more round after fixing the hoverinfo bug below, so a screenshot
    # of this can confirm the fix if anything's still off).
    with st.expander("Debug: raw click result", expanded=False):
        st.write(result)

    if result:
        # Confirmed against Streamlit's official st.plotly_chart docs
        # (PlotlyState/PlotlySelectionState schema): the selection dict
        # is always under "selection" -> "points", never "select".
        selection_data = result.get("selection") or {}
        points = selection_data.get("points")
        if points:
            pt = points[0]
            return round(pt["x"], 1), round(pt["y"], 1)
    return None, None