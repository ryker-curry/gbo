"""
GBO -- Shared strike-zone/movement chart builders for the two pages that
track bullpen pitches by hand-entered dot location: bullpen_tracking.py
(coach entry) and player_bullpens.py (player-facing view of the same
session data).

Extracted because ZONE_SIDE_BOUNDS/ZONE_HEIGHT_BOUNDS/FULL_ZONE_SIDE/
FULL_ZONE_HEIGHT/PITCH_TYPE_COLORS and the render_strike_zone_plot()/
render_scatter_with_averages() functions built from them were defined
independently in both modules -- confirmed byte-for-byte identical
(module constants and add_shape/add_trace/update_layout calls all
match; the only differences were incidental line-wrapping) rather than
two things that happened to converge on the same design. Behavior is
unchanged: both call sites still get exactly the same Figure back.

BURY_HEIGHT_THRESHOLD was a third identical constant duplicated the
same way, folded in here too.

ZONE_SIDE_BOUNDS/ZONE_HEIGHT_BOUNDS are the actual rulebook strike zone
in feet (side: umpire's-eye plate-side bounds; height: this app's
fixed generic zone, not a per-batter dynamic zone). FULL_ZONE_SIDE/
FULL_ZONE_HEIGHT extend that by one more "zone-width" in each
direction so the plotted axis range shows a third zone-width of
buffer outside the shadow zone on every side, matching the original
two modules' own chart framing.
"""

import plotly.graph_objects as go

import chart_helpers
from visualizations.hitter_graphic import home_plate_shape

ZONE_SIDE_BOUNDS = (-0.283, 0.283)
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)
BURY_HEIGHT_THRESHOLD = 1.5  # ft -- below this counts as "buried", regardless of target

_SIDE_THIRD = ZONE_SIDE_BOUNDS[1] - ZONE_SIDE_BOUNDS[0]
FULL_ZONE_SIDE = (ZONE_SIDE_BOUNDS[0] - _SIDE_THIRD, ZONE_SIDE_BOUNDS[1] + _SIDE_THIRD)
_HEIGHT_THIRD = ZONE_HEIGHT_BOUNDS[1] - ZONE_HEIGHT_BOUNDS[0]
FULL_ZONE_HEIGHT = (ZONE_HEIGHT_BOUNDS[0] - _HEIGHT_THIRD, ZONE_HEIGHT_BOUNDS[1] + _HEIGHT_THIRD)

PITCH_TYPE_COLORS = [
    "#3A8FE0", "#B08618", "#2A9E7A", "#B85FC4", "#E0713F", "#7F7EDB", "#D94F3D", "#7A8594",
]


def render_strike_zone_plot(title, data_by_type, view="pitcher"):
    """view (Sept 2026, Ryker: "add a home plate to everything that
    has a strike zone... face the correct way based on the view")
    matches bullpen_tracking.py's existing "Grid perspective" toggle
    (bp_zone_view, default "Pitcher's view") -- pass view="catcher"
    when that toggle reads "Catcher's view" so the plate under this
    chart agrees with the zone-tap button grid the coach is looking
    at. player_bullpens.py has no such toggle (player-facing,
    read-only) and just takes the default. Note this only flips the
    plate's own point-vs-flat orientation, not the plotted dots'
    left-right axis -- Plate Side here keeps its one fixed real-world
    sign convention regardless of view, same as everywhere else Rapsodo
    data is plotted."""
    fig = go.Figure()
    fig.add_shape(type="rect", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1],
                  line=dict(color="#AEB6C2", width=2), fillcolor="rgba(0,0,0,0)")
    fig.add_shape(**home_plate_shape(half_width_ft=ZONE_SIDE_BOUNDS[1], depth_ft=0.1, ground_y=FULL_ZONE_HEIGHT[0], view=view))
    for x in ZONE_SIDE_BOUNDS:
        fig.add_shape(type="line", x0=x, x1=x, y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1], line=dict(color="#5A5A5A", width=1, dash="dot"))
    for y in ZONE_HEIGHT_BOUNDS:
        fig.add_shape(type="line", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=y, y1=y, line=dict(color="#5A5A5A", width=1, dash="dot"))

    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e["Plate Side"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        ys = [e["Plate Height"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#171B21", width=1)),
            hovertemplate=f"{pitch_type}<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
        ))

    fig.update_layout(
        title=title, xaxis_title="Plate Side (ft)", yaxis_title="Plate Height (ft)",
        showlegend=True, height=480,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB6C2"),
        xaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039", range=[FULL_ZONE_SIDE[0] - 1, FULL_ZONE_SIDE[1] + 1], scaleanchor="y", scaleratio=1),
        # Lower bound extended below FULL_ZONE_HEIGHT[0] so the plate
        # (anchored there, partly below it) isn't clipped.
        yaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039", range=[FULL_ZONE_HEIGHT[0] - 0.2, FULL_ZONE_HEIGHT[1] + 1.5]),
        margin=dict(t=40, b=40, l=40, r=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=480)


def render_scatter_with_averages(title, x_label, y_label, data_by_type, x_key, y_key):
    fig = go.Figure()
    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e[x_key] for e in entries if x_key in e and y_key in e]
        ys = [e[y_key] for e in entries if x_key in e and y_key in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=8, opacity=0.35),
            showlegend=False,
            hovertemplate=f"{pitch_type}<br>{x_label}: %{{x}}<br>{y_label}: %{{y}}<extra></extra>",
        ))
        avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
        fig.add_trace(go.Scatter(
            x=[avg_x], y=[avg_y], mode="markers+text", name=pitch_type,
            marker=dict(color=color, size=18, line=dict(color="#AEB6C2", width=2)),
            text=[pitch_type], textposition="top center",
            textfont=dict(color="#AEB6C2", size=12),
            hovertemplate=f"{pitch_type} average<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(
        title=title, xaxis_title=x_label, yaxis_title=y_label,
        showlegend=False, height=420,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color="#AEB6C2"),
        xaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039"),
        yaxis=dict(gridcolor="#2A3039", zerolinecolor="#2A3039"),
        margin=dict(t=40, b=40, l=40, r=40),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=420)
