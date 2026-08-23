"""
GBO -- Command Tracker: the command chart (Section 18).

One function, command_chart(pitches) -- plots every LOCATED pitch
(actual location recorded) as a point at its own (horizontal_miss,
vertical_miss) offset in inches, i.e. intended location is always the
origin regardless of where on the actual strike zone that pitch was
aimed. Concentric rings at command_config.TARGET_RADII_IN show the
Precise/Good/Competitive bands those miss-distance values are already
classified against everywhere else (command_config.classify_miss,
CommandPitch.within_*_target) -- unlike visualizations/bullpen_charts.py's
movement_chart (which deliberately walked AWAY from a ring design
because HB/IVB total distance isn't the metric coaches read off that
chart), here the ring boundaries ARE the metric: Section 10's whole
target-radius classification is a distance-from-target read, so rings
are the correct, non-misleading representation for this one.

Points are colored by pitch type (pitch_type_config.get_pitch_color),
matching the app-wide convention (Section 23) rather than by miss
classification, so a coach can see e.g. "the slider's misses cluster
glove-side" at a glance -- which band a point falls in is still fully
readable from which ring it's inside.

Pure figure builder, same shape as strike_zone.py/visualizations/
bullpen_charts.py: takes an already-loaded, already-filtered list of
CommandPitch ORM objects (joinedload(.pitch_type) is the caller's job)
and returns a plain Plotly Figure -- no Shiny/database calls here.
"""

import plotly.graph_objects as go

import command_config
from analytics.command_metrics import pitch_type_label
from pitch_type_config import get_pitch_color
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, GOLD, MUTED_GRAY

# Fixed axis extent (inches), same rationale as movement_chart's fixed
# MOVEMENT_EXTENT -- every command chart shows the same boundaries
# regardless of how tight or wide a given session's actual misses are,
# so charts are comparable session to session rather than each one
# auto-zooming to its own data. Twice the Competitive radius leaves
# room to see Major Miss pitches without them sitting on the frame edge
# in a typical bullpen.
CHART_EXTENT_IN = 2.0 * command_config.COMPETITIVE_TARGET_RADIUS_IN


def _group_by_type(pitches):
    groups = {}
    order = []
    for p in pitches:
        label = pitch_type_label(p)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)
    return order, groups


def command_chart(pitches):
    """pitches: any list of CommandPitch ORM objects (joinedload'd
    .pitch_type) -- pitches with no actual location yet are silently
    excluded (nothing to plot; same convention as
    command_metrics._located). Returns a plain Plotly Figure."""
    located = [p for p in pitches if p.horizontal_miss is not None and p.vertical_miss is not None]

    fig = go.Figure()

    # Concentric target rings, outer ring first so later (inner) rings
    # draw on top -- innermost (Precision) always visible even where
    # bands overlap in the legend/annotation.
    for radius_in, label in reversed(command_config.TARGET_RADII_IN):
        fig.add_shape(
            type="circle", xref="x", yref="y",
            x0=-radius_in, x1=radius_in, y0=-radius_in, y1=radius_in,
            line=dict(color=GRID_GRAY, width=1.5), fillcolor="rgba(0,0,0,0)", layer="below",
        )
        fig.add_annotation(
            x=0, y=radius_in, text=f'{label} ({radius_in:.0f}")', showarrow=False,
            yshift=10, font=dict(color=MUTED_GRAY, size=10),
        )

    # Bold crosshair at the origin -- the intended target every point
    # is measured against, same visual weight as movement_chart's own
    # origin reference lines.
    fig.add_shape(type="line", x0=0, x1=0, y0=-CHART_EXTENT_IN, y1=CHART_EXTENT_IN, line=dict(color=GOLD, width=2))
    fig.add_shape(type="line", x0=-CHART_EXTENT_IN, x1=CHART_EXTENT_IN, y0=0, y1=0, line=dict(color=GOLD, width=2))

    order, groups = _group_by_type(located)
    for label in order:
        group = groups[label]
        color = get_pitch_color(label) if label != "Unspecified" else MUTED_GRAY
        xs = [float(p.horizontal_miss) for p in group]
        ys = [float(p.vertical_miss) for p in group]
        customdata = [[p.pitch_number, float(p.miss_distance), p.miss_direction or "—"] for p in group]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=label,
            marker=dict(color=color, size=11, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            customdata=customdata,
            hovertemplate=(
                f"{label}<br>Pitch #%{{customdata[0]}}<br>"
                "Miss: %{customdata[1]:.1f} in (%{customdata[2]})<extra></extra>"
            ),
        ))

    apply_gbo_theme(
        fig, title="Command Chart -- Miss From Target", x_title="Horizontal miss (in)", y_title="Vertical miss (in)",
        xaxis=dict(range=[-CHART_EXTENT_IN, CHART_EXTENT_IN], gridcolor=GRID_GRAY, zeroline=False, dtick=3, constrain="domain"),
        yaxis=dict(range=[-CHART_EXTENT_IN, CHART_EXTENT_IN], gridcolor=GRID_GRAY, zeroline=False, dtick=3,
                    scaleanchor="x", scaleratio=1, constrain="domain"),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig
