"""
GBO -- Pitch Location Density Heatmaps (Sept 2026, Pitcher Profile
"Zone" tab).

Ryker's reference is mlbpitchprofiler.com's own "2026 PITCH LOCATIONS"
section: one density/contour heatmap per pitch type, side by side, each
over the same strike-zone box, so a coach can see at a glance where a
guy's fastball clusters versus where his slider clusters instead of
reading one blended "every pitch type at once" cloud.

This is deliberately a SEPARATE chart from visualizations/bullpen_charts.
py's existing location_chart(), not a generalization of it:
location_chart plots BullpenPitch rows (plate_x_ft/plate_z_ft, Rapsodo
bullpen/intrasquad capture) one pitch type at a time, picked from a
dropdown, for the Physical Profile tab's reused Bullpen Dashboard view.
This chart plots GamePitch rows (actual_plate_x/actual_plate_z, real
live-game charted locations -- the same field pp_zone_section's own
Attack Zone Distribution bar already reads) for every pitch type at
once, as small multiples, for the Zone tab. Different source field,
different pitch scope (real games only vs. bullpens too), different
"all at once" layout -- sharing the function would mean threading two
unrelated call shapes through one signature for no real reuse.

One shared Blues density colorscale across every subplot (not a
colorscale per pitch type) -- consistent with location_chart's own
"blue = low density, red = high" reasoning, and it keeps the panels
visually comparable to each other rather than each subplot fighting for
attention with its own hue. Low-sample pitch types (fewer than
MIN_FOR_CONTOUR located pitches -- a smoothed density surface over a
handful of points reads as more confident than the data supports, the
same caveat location_chart's own docstring already notes) fall back to
plain dots instead of a contour.

Skips any pitch type with zero located pitches (actual_plate_x/
actual_plate_z both set) in this window -- nothing to draw.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from strike_zone import X_MIN, X_MAX, Z_MIN, Z_MAX, ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM

MIN_FOR_CONTOUR = 5
MAX_COLS = 3


def _type_label(p):
    return p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"


def _group_by_type(pitches):
    order, groups = [], {}
    for p in pitches:
        label = _type_label(p)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)
    # Most-thrown first, same convention as compute_pitch_type_breakdown.
    order.sort(key=lambda label: len(groups[label]), reverse=True)
    return order, groups


def pitch_location_heatmaps(game_pitches):
    """game_pitches: any list of GamePitch ORM objects (joinedload'd
    .pitch_type) -- typically pp_zone_section's already-filtered
    profile_queries.get_pitcher_profile_pitches() result. Returns a
    plain Plotly Figure, or None if nothing here has a location yet."""
    order, groups = _group_by_type(game_pitches)
    panels = []
    for label in order:
        located = [
            p for p in groups[label]
            if p.actual_plate_x is not None and p.actual_plate_z is not None
        ]
        if located:
            panels.append((label, located))
    if not panels:
        return None

    n = len(panels)
    cols = min(MAX_COLS, n)
    rows = (n + cols - 1) // cols

    fig = make_subplots(
        rows=rows, cols=cols,
        subplot_titles=[f"{label}  (n={len(located)})" for label, located in panels],
        horizontal_spacing=0.06, vertical_spacing=0.14,
    )

    for i, (label, located) in enumerate(panels):
        r, c = (i // cols) + 1, (i % cols) + 1
        xs = [float(p.actual_plate_x) for p in located]
        zs = [float(p.actual_plate_z) for p in located]

        if len(located) >= MIN_FOR_CONTOUR:
            fig.add_trace(
                go.Histogram2dContour(
                    x=xs, y=zs, colorscale="Blues", reversescale=False,
                    contours=dict(coloring="heatmap"), line=dict(width=0),
                    showscale=False, hoverinfo="skip",
                ),
                row=r, col=c,
            )
            fig.add_trace(
                go.Scatter(
                    x=xs, y=zs, mode="markers",
                    marker=dict(color=TEXT_CREAM, size=3, opacity=0.35),
                    showlegend=False, hoverinfo="skip",
                ),
                row=r, col=c,
            )
        else:
            # Too few located pitches for a meaningful density surface
            # -- plain dots only, same "don't overstate a handful of
            # points" reasoning as location_chart's own docstring.
            fig.add_trace(
                go.Scatter(
                    x=xs, y=zs, mode="markers",
                    marker=dict(color=TEXT_CREAM, size=7, opacity=0.85,
                                line=dict(color=GRID_GRAY, width=1)),
                    showlegend=False, hoverinfo="skip",
                ),
                row=r, col=c,
            )

        fig.add_shape(
            type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
            line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
            row=r, col=c,
        )
        fig.add_shape(
            type="line", x0=X_MIN, x1=X_MAX, y0=0, y1=0,
            line=dict(color=GRID_GRAY, width=1), row=r, col=c,
        )

    fig.update_xaxes(range=[X_MIN, X_MAX], showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(range=[Z_MIN, Z_MAX], showticklabels=False, showgrid=False, zeroline=False,
                      scaleanchor="x", scaleratio=1)
    for annotation in fig.layout.annotations:
        annotation.font = dict(color=TEXT_CREAM, size=12)

    return apply_gbo_theme(fig, title="Pitch Locations", height=280 * rows + 40)
