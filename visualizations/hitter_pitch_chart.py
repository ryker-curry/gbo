"""
GBO -- Hitter Pitch Locations chart (Sept 2026 addition, Ryker: "for
hitters hitter game report show charts of pitch locations from each of
their at-bats").

One function, at_bat_pitch_locations_chart(pa_pitches, batter_hand=None,
title=None): plots every pitch of ONE plate appearance at its own
ACTUAL location (GamePitch.actual_plate_x/z) on the real strike zone,
numbered by pa_pitch_number, colored by pitch type -- same
pitch_type_config.get_pitch_color convention every other pitch-location
chart in this app already uses (visualizations/command_charts.
pitch_locations_chart, shiny_app/modules/pitcher_game_report.py's own
_pitch_location_figure).

Deliberately ACTUAL-location-only, not intended-vs-actual:
GamePitch.intended_plate_x/z is only ever populated for pitches WE
threw (is_our_team_batting=False). Every pitch this chart draws is an
is_our_team_batting=True row (our own batters, or -- in a 2-squad
intrasquad game -- the "opponent" squad's batters, who are also our own
roster), so intended is always None there -- there is no second point
to plot or connect, unlike the pitcher-side charts this one otherwise
mirrors.

A thin dotted line connects consecutive LOCATED pitches in
pitch-sequence order (not intended-to-actual -- there's no intended
point here) so the at-bat's own path (ball away, ball in, called
strike middle-middle, foul back...) reads at a glance instead of
requiring the viewer to match numbers by eye. Same "read the sequence"
motivation as command_charts.pitch_locations_chart's own connecting
line, just carrying a different meaning here (pitch order, not miss
distance).

Batter silhouette: same hand-to-side convention pitcher_game_report.py's
_pitch_location_figure settled on by rendering all four combinations
(Sept 2026) -- center_x negative/facing="right" for a RIGHT-handed
batter, center_x positive/facing="left" for a LEFT-handed batter, using
command_charts.py's own tuned HITTER_HEIGHT_FT/HITTER_CENTER_X so a
batter drawn here matches the one on every other pitch-location chart
in scale. batter_hand=None (switch-hitter, or no hand on file) skips
the silhouette rather than guessing a side.

pa_pitches: one plate appearance's-worth of GamePitch ORM objects
(joinedload'd .pitch_type), already pitch_sequence-sorted -- the
caller's job (report_body groups via game_stats.
_group_into_plate_appearances, which already returns sorted groups).
A pitch missing a location is still numbered in the hover-free legend
sense -- actually it's simply skipped from the plotted markers/line,
same "don't guess a location" rule as every other chart here.
"""

import plotly.graph_objects as go

from pitch_type_config import get_pitch_color
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, MUTED_GRAY, TEXT_CREAM
from visualizations.hitter_graphic import hitter_images, home_plate_shape
from visualizations.command_charts import HITTER_HEIGHT_FT, HITTER_CENTER_X, CHART_X_EXTENT_FT


def at_bat_pitch_locations_chart(pa_pitches, batter_hand=None, title=None):
    fig = go.Figure()

    located = [p for p in pa_pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]

    # Connecting line first (layer="below") so the numbered markers
    # always draw on top -- pitch-sequence order, not miss distance.
    if len(located) > 1:
        ordered = sorted(located, key=lambda p: p.pa_pitch_number or 0)
        fig.add_trace(go.Scatter(
            x=[float(p.actual_plate_x) for p in ordered],
            y=[float(p.actual_plate_z) for p in ordered],
            mode="lines",
            line=dict(color=MUTED_GRAY, width=1, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

    # One trace per pitch type (for color-keyed legend entries), same
    # grouping convention as command_charts.pitch_locations_chart.
    order, groups = [], {}
    for p in located:
        label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
        if label not in groups:
            order.append(label)
            groups[label] = []
        groups[label].append(p)

    label_font = dict(color="#FFFFFF", size=11, family="Arial Black, Arial, sans-serif")
    for label in order:
        group = groups[label]
        color = get_pitch_color(label) if label != "Unspecified" else MUTED_GRAY
        customdata = [
            [p.pitch_outcome or "—", p.contact_quality or "—", p.ab_outcome if p.ends_plate_appearance else None]
            for p in group
        ]
        fig.add_trace(go.Scatter(
            x=[float(p.actual_plate_x) for p in group],
            y=[float(p.actual_plate_z) for p in group],
            mode="markers+text",
            text=[str(p.pa_pitch_number) for p in group],
            textposition="middle center",
            textfont=label_font,
            marker=dict(symbol="circle", color=color, size=26, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            name=label, legendgroup=label, showlegend=True,
            customdata=customdata,
            hovertemplate=(
                label + " — Pitch #%{text}<br>(%{x:.2f}, %{y:.2f}) ft<br>"
                "Outcome: %{customdata[0]}<br>Contact: %{customdata[1]}"
                "<extra></extra>"
            ),
        ))

    fig.add_shape(
        type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )
    zone_width, zone_height = 2 * ZONE_HALF_WIDTH, ZONE_TOP - ZONE_BOTTOM
    for i in (1, 2):
        grid_x = -ZONE_HALF_WIDTH + zone_width * i / 3
        fig.add_shape(
            type="line", xref="x", yref="y", x0=grid_x, x1=grid_x, y0=ZONE_BOTTOM, y1=ZONE_TOP,
            line=dict(color=TEXT_CREAM, width=1, dash="dot"),
        )
        grid_y = ZONE_BOTTOM + zone_height * i / 3
        fig.add_shape(
            type="line", xref="x", yref="y", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=grid_y, y1=grid_y,
            line=dict(color=TEXT_CREAM, width=1, dash="dot"),
        )

    if batter_hand in ("R", "L"):
        center_x = -HITTER_CENTER_X if batter_hand == "R" else HITTER_CENTER_X
        facing = "right" if center_x > 0 else "left"
        for img in hitter_images(center_x=center_x, facing=facing, height_ft=HITTER_HEIGHT_FT, ground_y=-0.5):
            fig.add_layout_image(**img)
    fig.add_shape(**home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, view="catcher"))

    apply_gbo_theme(
        fig, title=title or "Pitch Locations", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=420,
        xaxis=dict(range=[-CHART_X_EXTENT_FT, CHART_X_EXTENT_FT], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[-0.6, HITTER_HEIGHT_FT + 0.4], gridcolor=GRID_GRAY, zeroline=False),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig
