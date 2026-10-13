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


# Field colors -- the same look as the Game Tracking paper-chart field
# (game_tracking_step_display._FIELD_SVG / theme.py .gbo-field), so every
# field in the app reads as one field (Oct 2026, Ryker: "i want it to look
# like that everywhere the field is").
FIELD_GRASS = "#1E4D2B"
FIELD_DIRT = "#6B4A2E"
FIELD_DIRT_OPACITY = 0.55
FIELD_LINE = GBO_CREAM
FIELD_LABEL = "rgba(255,253,229,.55)"
FENCE_FT = 380          # fence arc (and foul-line length) on the full field
DIRT_FT = 150           # infield dirt arc
BASE_FT = 90


def _arc_points(radius, deg_from=-45, deg_to=45, step=1):
    pts = []
    d = deg_from
    while d <= deg_to + 1e-9:
        r = math.radians(d)
        pts.append((radius * math.sin(r), radius * math.cos(r)))
        d += step
    return pts


def _path(points, close=True):
    head, *rest = points
    out = f"M {head[0]:.1f},{head[1]:.1f} " + " ".join(f"L {x:.1f},{y:.1f}" for x, y in rest)
    return out + (" Z" if close else "")


def draw_field_diagram(fig, *, line_dist=FENCE_FT, arc_radius_ft=FENCE_FT, base_dist=BASE_FT, color=FIELD_LINE,
                       line_width=2.5, labels=True):
    """Draws the shared field background onto an existing figure, in place:
    grass fan to the fence, infield dirt arc, infield grass diamond, foul
    lines, fence, bases + home plate and LF/CF/RF labels -- the paper-chart
    field from Game Tracking. Everything is a layout shape on the "below"
    layer, so dots and click grids always sit on top. Same feet-from-home-
    plate convention as the rest of this module. arc_radius_ft trims the
    grass/fence (the infield slice chart passes 220); dirt and bases stay
    true scale."""
    R = arc_radius_ft
    below = dict(layer="below")
    fan = [(0, 0)] + _arc_points(R)
    fig.add_shape(type="path", path=_path(fan), fillcolor=FIELD_GRASS, line=dict(width=0), **below)
    dr = min(DIRT_FT, R)
    fig.add_shape(type="path", path=_path([(0, 0)] + _arc_points(dr)), fillcolor=FIELD_DIRT,
                  opacity=FIELD_DIRT_OPACITY, line=dict(width=0), **below)
    h = base_dist / math.sqrt(2)
    fig.add_shape(type="path", path=_path([(0, 0), (h, h), (0, 2 * h), (-h, h)]), fillcolor=FIELD_GRASS,
                  line=dict(width=0), **below)
    for sign in (-1, 1):
        end = line_dist * math.sin(math.radians(45))
        fig.add_shape(type="line", x0=0, y0=0, x1=sign * end, y1=end, line=dict(color=color, width=line_width), **below)
    fig.add_shape(type="path", path=_path(_arc_points(R), close=False), line=dict(color=color, width=line_width), **below)
    s = 6  # base half-size, feet
    for bx, by in ((h, h), (0, 2 * h), (-h, h)):
        fig.add_shape(type="rect", x0=bx - s, y0=by - s, x1=bx + s, y1=by + s, fillcolor=color, line=dict(width=0), **below)
    fig.add_shape(type="path", path=_path([(-7, 4), (7, 4), (7, -3), (0, -9)]), fillcolor=color, line=dict(width=0), **below)
    if labels:
        k = R / FENCE_FT
        for txt, x, y in (("LF", -203, 160), ("CF", 0, 300), ("RF", 203, 160)):
            fig.add_annotation(x=x * k, y=y * k, text=txt, showarrow=False,
                               font=dict(color=FIELD_LABEL, size=15, family="IBM Plex Sans, system-ui, sans-serif"))


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

    draw_field_diagram(fig)

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