"""
GBO — Rapsodo Bullpen Analytics: core visualizations (Phase 3).

Movement plot, release-point consistency, and pitch-location heat map
(spec Sections 7, 8, 11). Spin axis has its own module
(spin_axis_chart.py) since a polar clock-face chart is visually
distinct enough from this scatter/line family to warrant separate
code.

The dual-axis Velocity and Spin Rate Trend chart (spec Section 9,
velocity_spin_trend_chart()) was removed per Ryker's call -- unclear
in practice what it was communicating -- and nothing else in GBO
depends on it.

Every function takes an already-loaded, already-filtered list of
RapsodoPitch ORM objects and returns a Plotly Figure -- no Streamlit
calls in this file (the page calls st.plotly_chart() on what these
return), and no database queries (the page/analytics layer already
did that). Pitch-type colors and display labels come from
pitch_type_config.py / analytics.bullpen_metrics.pitch_type_label --
never hardcoded or positionally assigned here, per spec Section 23.

Movement (IVB/HB) uses vb_spin/hb_spin (Rapsodo's spin-induced break
columns) -- matches the mapping already established in Phase 1's
importer and Phase 2's pitch-type summary table, not the trajectory-
fit or seam-shifted-wake break columns also preserved on RapsodoPitch.
"""

import plotly.graph_objects as go

from pitch_type_config import get_pitch_color
from analytics.bullpen_metrics import pitch_type_label
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, GOLD
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP


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


def color_for_pitch_label(label):
    """pitch_type_label() can return a canonical PitchType name, or a
    synthetic "Unclassified"/"X (unrecognized)" label for pitches with
    no recognized type (see analytics.bullpen_metrics.pitch_type_label).
    Only canonical names have an assigned color in pitch_type_config --
    anything else gets the default fallback color rather than a
    nonsensical lookup."""
    if label == "Unclassified" or "(unrecognized)" in label:
        return get_pitch_color(None)
    return get_pitch_color(label)


def movement_chart(pitches, min_pitches_for_shading=2):
    """Horizontal Break (x) vs. Induced Vertical Break (y) -- a plain
    Cartesian grid with real tick labels on both axes, matching Rapsodo's
    own native movement plot rather than a Baseball-Savant-style radial
    (concentric ring) chart. Per Ryker's call: this is a coaching/
    development tool, not a broadcast graphic, and reading an exact HB/
    IVB number off the axes directly is more useful day-to-day than a
    single "distance from center" read -- plus it matches the movement
    plot pitchers already see in their own Rapsodo report, so there's no
    translation between tools.

    This replaces an earlier ring-based version (concentric 6"/12"/18"/
    24" distance rings) that was built first per a Statcast-style
    reference image Ryker provided, then explicitly walked back once it
    became clear the rings encode total movement magnitude
    (sqrt(HB^2+IVB^2)), not either axis individually -- a pitch can sit
    outside an inner ring on total distance even when neither of its raw
    HB or IVB numbers alone would suggest that, which is a legitimate but
    non-obvious way to read a chart. A plain grid with real ticks avoids
    that read entirely.

    Kept from the ring version: the soft shaded "cluster" region per
    pitch type (still a simple bounding circle around that type's own
    points, not a real density/KDE contour), and the bold gold reference
    lines through the origin (a standing, separate request of Ryker's,
    independent of the rings-vs-grid decision).

    min_pitches_for_shading: pitch types with fewer pitches than this
    still get their dots plotted, just no shaded cluster region (a shape
    drawn around 1-2 points isn't a meaningful "cluster," it's just
    noise).

    Deliberately still not included, same as before: an MLB/league-
    average reference overlay (no real external benchmark dataset to
    draw from) and an arm-angle/pitcher-silhouette indicator (needs the
    same physics review already deferred to Phase 4). The horizontal
    axis also still keeps its plain "Horizontal Break (in)" label rather
    than a hand-dependent "1B / 3B" label, pending Ryker confirming
    Rapsodo's HB sign convention -- unaffected by this rings-to-grid
    change.

    Axis range is fixed at -25"/+25" on both axes (see MOVEMENT_EXTENT)
    per Ryker's call -- every movement chart shows the same boundaries
    regardless of how tight or wide a given session's actual movement
    is, so charts are directly comparable session to session instead of
    each one auto-zooming to its own data.
    """
    fig = go.Figure()

    usable = [p for p in pitches if p.hb_spin is not None and p.vb_spin is not None]
    order, groups = _group_by_type(usable)

    # Axis extent: fixed at -25"/+25" on both axes per Ryker's call, not
    # sized to the session's actual data -- keeps every chart on the
    # same scale so they're comparable across sessions. Equal aspect
    # (scaleanchor/scaleratio below) so an inch of HB and an inch of IVB
    # are the same visual distance, same as Rapsodo's own plot.
    MOVEMENT_EXTENT = 25.0
    x_extent = MOVEMENT_EXTENT
    y_extent = MOVEMENT_EXTENT

    # Soft shaded cluster region per pitch type -- a simple bounding
    # circle around each type's own points (centered on its mean, sized
    # to its own spread), not a real density/KDE contour. An honest,
    # readable approximation rather than a statistically-fitted shape.
    for label in order:
        group = groups[label]
        if len(group) < min_pitches_for_shading:
            continue
        xs = [float(p.hb_spin) for p in group]
        ys = [float(p.vb_spin) for p in group]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        spread = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 + 1.5
        fig.add_shape(
            type="circle", xref="x", yref="y",
            x0=cx - spread, x1=cx + spread, y0=cy - spread, y1=cy + spread,
            line=dict(width=0), fillcolor=color_for_pitch_label(label), opacity=0.18, layer="below",
        )

    # Bold gold reference lines through the origin -- drawn after the
    # cluster shading (so they sit on top of it) but before the data
    # points, same layering as the ring version.
    fig.add_shape(type="line", x0=0, x1=0, y0=-y_extent, y1=y_extent, line=dict(color=GOLD, width=2.5))
    fig.add_shape(type="line", x0=-x_extent, x1=x_extent, y0=0, y1=0, line=dict(color=GOLD, width=2.5))

    for label in order:
        group = groups[label]
        color = color_for_pitch_label(label)
        xs = [float(p.hb_spin) for p in group]
        ys = [float(p.vb_spin) for p in group]
        customdata = [
            [p.pitch_number, float(p.velocity) if p.velocity is not None else None,
             float(p.total_spin) if p.total_spin is not None else None]
            for p in group
        ]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=label,
            marker=dict(color=color, size=10, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            customdata=customdata,
            hovertemplate=(
                f"{label}<br>Pitch #%{{customdata[0]}}<br>"
                "Velocity: %{customdata[1]:.1f} mph<br>"
                "Spin Rate: %{customdata[2]:.0f} rpm<br>"
                "IVB: %{y:.1f} in<br>HB: %{x:.1f} in<extra></extra>"
            ),
        ))

    apply_gbo_theme(
        fig, title="Pitch Movement", x_title="Horizontal Break (in)", y_title="Induced Vertical Break (in)",
        # Real gridlines and tick labels -- the whole point of the
        # switch away from the ring version -- with a fixed 5" tick
        # spacing so the grid reads as clean, evenly-spaced inches
        # rather than whatever irregular ticks autoscaling would pick.
        # constrain="domain" on both axes keeps the requested -25/+25
        # ranges exactly as specified -- without it, Plotly's equal-
        # aspect scaleanchor below stretches the x-axis range to fill
        # the (wider-than-tall) plot container instead of respecting
        # the range we set, which is what caused the x-axis to show
        # -65/65 instead of -25/25. With constrain="domain", the plot's
        # width shrinks to preserve the aspect ratio instead of the
        # range expanding.
        xaxis=dict(range=[-x_extent, x_extent], gridcolor=GRID_GRAY, zeroline=False, dtick=5,
                    constrain="domain"),
        yaxis=dict(range=[-y_extent, y_extent], gridcolor=GRID_GRAY, zeroline=False, dtick=5,
                    scaleanchor="x", scaleratio=1, constrain="domain"),
        showlegend=False,  # the pitch-type legend lives in the usage/velo table below the chart
    )
    return fig


def release_point_chart(pitches, mode="individual"):
    """Spec Section 8: release-point consistency. X = Release Side (ft),
    Y = Release Height (ft). Two modes, meant to be shown side by side
    per Ryker's reference image:

      - mode="individual": every pitch plotted as its own dot, colored
        by pitch type.
      - mode="average": one bold dot per pitch type, at that type's
        average release side/height -- makes cross-type tunneling
        (tight clustering across types = harder to read out of the
        hand) visible at a glance without the individual-pitch noise.

    Axis range is fixed at Release Side [-4, 4] ft and Release Height
    [0, 8] ft on both modes, matching Ryker's reference image exactly,
    rather than the earlier version's dynamic zoom-to-data-plus-padding
    formula -- a fixed range also makes the two side-by-side panels
    directly comparable at a glance (same scale in both), and makes a
    session's real inches of arm-slot variation read as a small,
    honest fraction of a consistent frame instead of shifting frame to
    frame. Bold gold crosshair at (0, 0), same visual convention as the
    movement chart's origin lines, drawn behind the data.

    In-plot horizontal legend at the top (colored dot + pitch type
    name) per the reference image, unlike movement_chart's legend
    (which lives in the separate below-chart pitch_type_legend()
    component instead) -- this chart has no matching below-chart
    table to borrow a legend from, so Plotly's own legend is used
    directly here."""
    fig = go.Figure()

    usable = [p for p in pitches if p.release_side is not None and p.release_height is not None]
    order, groups = _group_by_type(usable)

    X_MIN, X_MAX = -4.0, 4.0
    Y_MIN, Y_MAX = 0.0, 8.0

    # Bold gold crosshair at (0, 0) -- drawn first so it sits behind
    # the data points.
    fig.add_shape(type="line", x0=0, x1=0, y0=Y_MIN, y1=Y_MAX, line=dict(color=GOLD, width=2.5))
    fig.add_shape(type="line", x0=X_MIN, x1=X_MAX, y0=0, y1=0, line=dict(color=GOLD, width=2.5))

    if mode == "average":
        for label in order:
            group = groups[label]
            color = color_for_pitch_label(label)
            xs = [float(p.release_side) for p in group]
            ys = [float(p.release_height) for p in group]
            avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
            fig.add_trace(go.Scatter(
                x=[avg_x], y=[avg_y], mode="markers", name=label,
                marker=dict(color=color, size=20, line=dict(color="#1E1E1E", width=1.5)),
                hovertemplate=f"{label} average ({len(group)} pitches)<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
            ))
        title = "Release Point — Average by Pitch Type"
    else:
        for label in order:
            group = groups[label]
            color = color_for_pitch_label(label)
            xs = [float(p.release_side) for p in group]
            ys = [float(p.release_height) for p in group]
            customdata = [[p.pitch_number, float(p.velocity) if p.velocity is not None else None] for p in group]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", name=label,
                marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#1E1E1E", width=1)),
                customdata=customdata,
                hovertemplate=f"{label}<br>Pitch #%{{customdata[0]}}<br>Velocity: %{{customdata[1]:.1f}} mph<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
            ))
        title = "Release Point — All Pitches"

    apply_gbo_theme(
        fig, title=title, x_title="Release Side (ft)", y_title="Release Height (ft)",
        # zeroline off on both axes -- the bold gold crosshair drawn
        # above replaces Plotly's default thin zeroline.
        xaxis=dict(range=[X_MIN, X_MAX], gridcolor=GRID_GRAY, zeroline=False, dtick=1),
        yaxis=dict(range=[Y_MIN, Y_MAX], gridcolor=GRID_GRAY, zeroline=False, dtick=1),
        showlegend=True,
        # y=1.03 sat right on top of the title text -- confirmed via a
        # real screenshot Ryker sent. Push the legend further up and
        # widen the top margin so the two don't compete for the same
        # cramped default space.
        legend=dict(orientation="h", yanchor="bottom", y=1.15, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(t=90, b=40, l=50, r=30),
    )
    return fig


def location_chart(pitches, mode="heatmap"):
    """Spec Section 11: pitch location relative to the strike zone.
    mode="heatmap" -> density heat map (blue = low density, red = high).
    mode="individual" -> one dot per pitch, colored by pitch type.

    Uses plate_x_ft/plate_z_ft (converted from Rapsodo's Strike Zone
    Side/Height at import time -- see rapsodo_conventions.py for the
    documented conversion and its open sign-convention caveat) and the
    same strike-zone rectangle constants as strike_zone.py (Game
    Tracking) -- one shared zone definition across the app, not a
    second independently-drawn approximation."""
    fig = go.Figure()

    usable = [p for p in pitches if p.plate_x_ft is not None and p.plate_z_ft is not None]

    if mode == "individual":
        order, groups = _group_by_type(usable)
        for label in order:
            group = groups[label]
            color = color_for_pitch_label(label)
            xs = [float(p.plate_x_ft) for p in group]
            ys = [float(p.plate_z_ft) for p in group]
            customdata = [[p.pitch_number, float(p.velocity) if p.velocity is not None else None] for p in group]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", name=label,
                marker=dict(color=color, size=10, opacity=0.8, line=dict(color="#1E1E1E", width=1)),
                customdata=customdata,
                hovertemplate=f"{label}<br>Pitch #%{{customdata[0]}}<br>Velocity: %{{customdata[1]:.1f}} mph<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
            ))
    else:
        xs = [float(p.plate_x_ft) for p in usable]
        ys = [float(p.plate_z_ft) for p in usable]
        if xs and ys:
            fig.add_trace(go.Histogram2dContour(
                x=xs, y=ys, colorscale="Blues", reversescale=False,
                contours=dict(coloring="heatmap"),
                showscale=True,
                colorbar=dict(title="Density", tickfont=dict(color=TEXT_CREAM), title_font=dict(color=TEXT_CREAM)),
                line=dict(width=0),
            ))
            # Overlay actual pitch locations as faint points so the heat
            # map isn't the only thing on screen -- helps at low pitch
            # counts, where a smoothed density surface alone can look
            # more confident than the data supports.
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers",
                marker=dict(color=TEXT_CREAM, size=4, opacity=0.4),
                showlegend=False, hoverinfo="skip",
            ))

    # Strike zone rectangle -- shared convention with strike_zone.py.
    fig.add_shape(
        type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )

    apply_gbo_theme(
        fig, title="Pitch Location", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=480,
        xaxis=dict(range=[-2.5, 2.5], gridcolor=GRID_GRAY, zerolinecolor=GRID_GRAY, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[0, 5], gridcolor=GRID_GRAY, zerolinecolor=GRID_GRAY),
    )
    return fig
