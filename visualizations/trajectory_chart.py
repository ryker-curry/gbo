"""
GBO — Rapsodo Bullpen Analytics: pitch flight-path chart (Phase 4).

Renders each pitch's cached trajectory_json (see pitch_trajectory.py)
as a flight-path line from release to the plate. Two views, matching
the two ways Michael Richmond's baseball-physics writeup visualizes a
trajectory (see pitch_trajectory.py's docstring for that source):

  - "side": height (y) vs. distance traveled from release (z) -- how
    much the ball rises/falls over its flight, viewed from the dugout.
  - "top": horizontal offset (x) vs. distance traveled (z) -- how much
    the ball breaks side to side, viewed from above.

Every pitch in the list gets its own line, colored by pitch type and
drawn at reduced opacity so a full session's worth of pitches reads as
a "corridor" per pitch type rather than a solid mass -- same shading
philosophy as movement_chart()'s cluster regions. Pitches with no
cached trajectory (trajectory_json is None -- missing a required
physics input, see pitch_trajectory.py) are silently skipped, not
treated as an error; a session can have a real mix of pitches with and
without a usable trajectory.
"""

import plotly.graph_objects as go

from analytics.bullpen_metrics import pitch_type_label
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, GOLD
from visualizations.bullpen_charts import color_for_pitch_label, _group_by_type

# Same fixed height range as release_point_chart's Y axis, for the same
# reason -- and so a coach reading both charts side by side isn't
# mentally rescaling between them.
HEIGHT_MIN, HEIGHT_MAX = 0.0, 8.0
# Same fixed horizontal range as release_point_chart's X axis.
SIDE_MIN, SIDE_MAX = -4.0, 4.0


def trajectory_chart(pitches, view="side"):
    """view="side" -> height vs. distance traveled. view="top" ->
    horizontal offset vs. distance traveled."""
    fig = go.Figure()

    usable = [p for p in pitches if getattr(p, "trajectory_json", None) is not None]
    order, groups = _group_by_type(usable)

    max_distance = 60.5  # sensible default if nothing usable is plotted
    if usable:
        max_distance = max(p.trajectory_json["flight_distance_ft"] for p in usable)

    if view == "top":
        # Center line at x=0 (mound centerline), same gold convention as
        # every other chart's reference line.
        fig.add_shape(type="line", x0=0, x1=max_distance, y0=0, y1=0, line=dict(color=GOLD, width=2.5))
        y_range = [SIDE_MIN, SIDE_MAX]
        y_title = "Horizontal Offset (ft)"
        title = "Pitch Trajectory — Top View"
    else:
        # Ground line at y=0.
        fig.add_shape(type="line", x0=0, x1=max_distance, y0=0, y1=0, line=dict(color=GOLD, width=2.5))
        y_range = [HEIGHT_MIN, HEIGHT_MAX]
        y_title = "Height (ft)"
        title = "Pitch Trajectory — Side View"

    for label in order:
        group = groups[label]
        color = color_for_pitch_label(label)
        first_in_group = True
        for p in group:
            samples = p.trajectory_json["samples"]
            zs = [s["z"] for s in samples]
            ys = [s["y"] if view != "top" else s["x"] for s in samples]
            fig.add_trace(go.Scatter(
                x=zs, y=ys, mode="lines", name=label,
                line=dict(color=color, width=1.5),
                opacity=0.45,
                showlegend=first_in_group,
                hovertemplate=f"{label}<br>Distance: %{{x:.1f}} ft<br>{y_title.split(' (')[0]}: %{{y:.2f}} ft<extra></extra>",
            ))
            first_in_group = False

    apply_gbo_theme(
        fig, title=title, x_title="Distance from Release (ft)", y_title=y_title,
        xaxis=dict(range=[0, max_distance], gridcolor=GRID_GRAY, zeroline=False),
        yaxis=dict(range=y_range, gridcolor=GRID_GRAY, zeroline=False),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.03, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
    )
    return fig
