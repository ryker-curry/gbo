"""
GBO -- Pitcher/Hitter Profile: the trend-over-time strip.

One function, trend_chart() -- a small sparkline-style line chart of one
metric's value over time (Stuff+/Location+/Pitching+ by date, or any
other dated-value series a Profile page wants to show trending). Pure
figure builder, same shape as every other visualizations/*.py module in
this app (visualizations/bullpen_charts.py, visualizations/
command_charts.py): takes already-computed data, returns a plain
Plotly Figure, no Shiny/database calls here -- the calling module owns
grouping pitches by date and computing each date's value.

Deliberately minimal -- a single trace, no zone shading, no target
bands (unlike command_chart, there's no fixed reference band for a
mean-100 grade the way there is for miss-distance target radii) --
just the line plus a flat dashed reference at 100 so a viewer can read
"above/below average" at a glance.
"""

import plotly.graph_objects as go

from visualizations.chart_theme import apply_gbo_theme, GOLD, MUTED_GRAY


def trend_chart(dated_values, y_label="Grade", color=GOLD):
    """dated_values: list of (date, value) tuples, already sorted
    ascending, value may be None (a gap in the line -- Plotly handles
    None in y the same way as a missing point, per its own connectgaps
    default of False). Returns None if there's no data with a real
    value at all (nothing to plot)."""
    points = [(d, v) for d, v in dated_values if v is not None]
    if not points:
        return None

    dates = [d for d, _ in points]
    values = [v for _, v in points]

    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=MUTED_GRAY, width=1, dash="dash"))
    fig.add_trace(go.Scatter(
        x=dates, y=values, mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(color=color, size=7),
        hovertemplate="%{x}<br>" + y_label + ": %{y:.1f}<extra></extra>",
    ))
    return apply_gbo_theme(fig, height=260, y_title=y_label, showlegend=False)
