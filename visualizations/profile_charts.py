"""
GBO -- Pitcher/Hitter Profile: the trend-over-time strip.

One function, trend_chart() -- a small chart of one metric's value over
time, one point per OUTING (Stuff+/Location+/Pitching+ by game, or any
other dated-value series a Profile page wants to show trending). Pure
figure builder, same shape as every other visualizations/*.py module in
this app (visualizations/bullpen_charts.py, visualizations/
command_charts.py): takes already-computed data, returns a plain
Plotly Figure, no Shiny/database calls here -- the calling module owns
grouping pitches by GAME (not just by date -- see pitcher_profile.py's
_aggregate_trend_by_game, which also keeps two games on the same date,
e.g. a doubleheader, as separate points) and computing each outing's
mean/lo/hi.

Sept 2026 (Ryker: raw pitch-by-pitch dots were too noisy to read as an
actual trend across outings -- "how is this useful?"): each point is
now one outing's AVERAGE grade, with an error bar spanning that
outing's own min-to-max pitch-level grade, so a viewer can tell a
locked-in start from a volatile one apart, not just see one line
jumping around pitch to pitch.

Deliberately minimal otherwise -- a single trace, no zone shading, no
target bands (unlike command_chart, there's no fixed reference band for
a mean-100 grade the way there is for miss-distance target radii) --
just the line plus a flat dashed reference at 100 so a viewer can read
"above/below average" at a glance.
"""

import plotly.graph_objects as go

from visualizations.chart_theme import apply_gbo_theme, GOLD, MUTED_GRAY


def trend_chart(points, y_label="Grade", color=GOLD):
    """points: list of (date, mean, lo, hi) tuples, one per outing,
    already sorted ascending by date (see the calling module's own
    aggregation, e.g. pitcher_profile.py's _aggregate_trend_by_game).
    mean may be None (a gap in the line -- Plotly handles None in y the
    same way as a missing point, per its own connectgaps default of
    False); lo/hi may equal mean (a single-pitch outing has no spread,
    so its error bar is simply zero-length). Returns None if there's no
    outing with a real mean value at all (nothing to plot)."""
    rows = [(d, m, lo, hi) for d, m, lo, hi in points if m is not None]
    if not rows:
        return None

    dates = [d for d, _, _, _ in rows]
    means = [m for _, m, _, _ in rows]
    los = [lo for _, _, lo, _ in rows]
    his = [hi for _, _, _, hi in rows]

    fig = go.Figure()
    fig.add_hline(y=100, line=dict(color=MUTED_GRAY, width=1, dash="dash"))
    fig.add_trace(go.Scatter(
        x=dates, y=means, mode="lines+markers",
        line=dict(color=color, width=2.5),
        marker=dict(color=color, size=7),
        error_y=dict(
            type="data", symmetric=False,
            array=[hi - m for m, hi in zip(means, his)],
            arrayminus=[m - lo for m, lo in zip(means, los)],
            color=color, thickness=1.5, width=4,
        ),
        hovertemplate="%{x}<br>" + y_label + ": %{y:.1f}<extra></extra>",
    ))
    return apply_gbo_theme(fig, height=260, y_title=y_label, showlegend=False)
