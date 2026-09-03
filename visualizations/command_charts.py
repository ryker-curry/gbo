"""
GBO -- Command Tracker charts: command_chart (Section 18) plus
pitch_locations_chart (Sept 2026 addition).

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

pitch_locations_chart (below command_chart in this file) is the
complementary view Ryker asked for: instead of every pitch normalized
to its own miss-from-target offset, it plots every pitch's INTENDED
and ACTUAL point on the real strike zone, each numbered, connected by
a line -- see its own docstring for the full reasoning.
"""

import plotly.graph_objects as go

import command_config
from analytics.command_metrics import pitch_type_label
from pitch_type_config import get_pitch_color
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, GOLD, MUTED_GRAY, TEXT_CREAM

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


def pitch_locations_chart(pitches):
    """Sept 2026 addition (Ryker): one chart showing every pitch's
    INTENDED location and ACTUAL location together, plotted on the real
    strike zone -- NOT command_chart's miss-from-target coordinate
    system above, since the point here is showing where on the actual
    zone each pitch was aimed and landed, not just how far off. Each
    pitch is numbered on BOTH its intended and actual point (pitch 1's
    intended dot and pitch 1's actual dot both show "1"), connected by
    a thin dotted line so the miss direction is visible at a glance
    instead of requiring the viewer to match numbers by eye across a
    busy chart.

    Color is by pitch type (Ryker: "if different pitch types are
    thrown change color of dot to be able to tell the difference"),
    same pitch_type_config.get_pitch_color convention as command_chart
    above -- intended and actual use the SAME color for a given pitch
    type (a same-colored pair threads together visually via color,
    number, AND the connecting line), distinguished from each other by
    marker shape instead: a hollow ring for intended, a filled dot for
    actual.

    Same real plate-coordinate system as visualizations/bullpen_charts.
    location_chart (feet, zone rectangle from strike_zone.py) -- one
    shared zone definition across the app, not a second independently
    drawn approximation.

    pitches: CommandPitch ORM objects (joinedload'd .pitch_type). A
    pitch with no actual location yet still gets its numbered intended
    point -- there's nothing to draw a line to or an actual dot for, an
    intent-only pitch has no "actual" side yet."""
    fig = go.Figure()

    order, groups = _group_by_type(pitches)

    # Connecting lines first (layer="below") so the numbered markers
    # always draw on top and stay legible even where a line crosses
    # through them.
    for p in pitches:
        if p.actual_x is None or p.actual_z is None:
            continue
        fig.add_shape(
            type="line", xref="x", yref="y",
            x0=float(p.intended_x), y0=float(p.intended_z),
            x1=float(p.actual_x), y1=float(p.actual_z),
            line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below",
        )

    label_font = dict(color="#FFFFFF", size=10, family="Arial Black, Arial, sans-serif")

    for label in order:
        group = groups[label]
        color = get_pitch_color(label) if label != "Unspecified" else MUTED_GRAY

        fig.add_trace(go.Scatter(
            x=[float(p.intended_x) for p in group],
            y=[float(p.intended_z) for p in group],
            mode="markers+text",
            text=[str(p.pitch_number) for p in group],
            textposition="middle center",
            textfont=label_font,
            marker=dict(symbol="circle-open", color=color, size=24, line=dict(color=color, width=3)),
            name=label, legendgroup=label, showlegend=True,
            hovertemplate=f"{label} — Intended<br>Pitch #%{{text}}<br>(%{{x:.2f}}, %{{y:.2f}}) ft<extra></extra>",
        ))

        located = [p for p in group if p.actual_x is not None and p.actual_z is not None]
        if located:
            customdata = [
                [p.pitch_number, float(p.miss_distance) if p.miss_distance is not None else None, p.miss_direction or "—"]
                for p in located
            ]
            fig.add_trace(go.Scatter(
                x=[float(p.actual_x) for p in located],
                y=[float(p.actual_z) for p in located],
                mode="markers+text",
                text=[str(p.pitch_number) for p in located],
                textposition="middle center",
                textfont=label_font,
                marker=dict(symbol="circle", color=color, size=24, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
                name=label, legendgroup=label, showlegend=False,
                customdata=customdata,
                hovertemplate=(
                    f"{label} — Actual<br>Pitch #%{{customdata[0]}}<br>(%{{x:.2f}}, %{{y:.2f}}) ft<br>"
                    "Miss: %{customdata[1]:.1f} in (%{customdata[2]})<extra></extra>"
                ),
            ))

    # Strike zone rectangle -- shared convention with strike_zone.py /
    # bullpen_charts.location_chart (one zone definition across the app).
    fig.add_shape(
        type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )

    apply_gbo_theme(
        fig, title="Pitch Locations — Intended vs. Actual", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=500,
        xaxis=dict(range=[-2.5, 2.5], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[0, 5], gridcolor=GRID_GRAY, zeroline=False),
        legend=dict(orientation="h", y=-0.12),
    )
    return fig
