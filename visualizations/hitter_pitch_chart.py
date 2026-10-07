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
from plate_discipline import SWING_OUTCOMES
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, MUTED_GRAY, TEXT_CREAM
from visualizations.hitter_graphic import hitter_images, home_plate_shape
from visualizations.command_charts import HITTER_HEIGHT_FT, HITTER_CENTER_X, CHART_X_EXTENT_FT


def at_bat_pitch_locations_chart(pa_pitches, batter_hand=None, title=None, zoom=False, show_intended=False):
    """zoom=True (Oct 2026, Ryker: "zoom in more on the strike zone so it
    is bigger"): frames the zone and the batter's lower body instead of
    the whole batter, widening only as far as needed to keep every
    located pitch on the chart."""
    fig = go.Figure()

    located = [p for p in pa_pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]

    # show_intended (Oct 2026, Pitcher Game Breakdown's At-Bat by At-Bat):
    # the catcher's called spot as a hollow ring in the pitch's color,
    # joined to where it actually went -- the plan vs the execution.
    # Replaces the pitch-order line (two sets of lines would be noise).
    if show_intended:
        for p in located:
            if p.intended_plate_x is None or p.intended_plate_z is None:
                continue
            label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
            color = get_pitch_color(label) if label != "Unspecified" else MUTED_GRAY
            fig.add_shape(type="line", xref="x", yref="y", x0=float(p.intended_plate_x), y0=float(p.intended_plate_z),
                          x1=float(p.actual_plate_x), y1=float(p.actual_plate_z),
                          line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below")
            fig.add_trace(go.Scatter(
                x=[float(p.intended_plate_x)], y=[float(p.intended_plate_z)], mode="markers",
                marker=dict(symbol="circle-open", color=color, size=20, line=dict(color=color, width=2)),
                showlegend=False, hovertemplate=f"Called spot for pitch #{p.pa_pitch_number}<extra></extra>",
            ))
    # Connecting line first (layer="below") so the numbered markers
    # always draw on top -- pitch-sequence order, not miss distance.
    if len(located) > 1 and not show_intended:
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
        cx = 1.75 if zoom else HITTER_CENTER_X     # a touch closer in when zoomed so the whole hitter fits
        center_x = -cx if batter_hand == "R" else cx
        facing = "right" if center_x > 0 else "left"
        for img in hitter_images(center_x=center_x, facing=facing, height_ft=HITTER_HEIGHT_FT, ground_y=-0.5, batter_hand=batter_hand):
            fig.add_layout_image(**img)
    fig.add_shape(**home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, view="catcher"))

    x_ext, y_lo, y_hi = CHART_X_EXTENT_FT, -0.6, HITTER_HEIGHT_FT + 0.4
    if zoom:
        xs = [abs(float(p.actual_plate_x)) for p in located]
        zs = [float(p.actual_plate_z) for p in located]
        if show_intended:
            xs += [abs(float(p.intended_plate_x)) for p in located if p.intended_plate_x is not None]
            zs += [float(p.intended_plate_z) for p in located if p.intended_plate_z is not None]
        x_ext = max([2.7] + [x + 0.35 for x in xs])
        y_lo = min([-0.35] + [z - 0.35 for z in zs])
        y_hi = max([6.0] + [z + 0.35 for z in zs])
    apply_gbo_theme(
        fig, title=title or "Pitch Locations", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=420,
        xaxis=dict(range=[-x_ext, x_ext], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[y_lo, y_hi], gridcolor=GRID_GRAY, zeroline=False),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


# Oct 2026, Ryker: Hitter Game Breakdown "Swing decisions" map -- every
# pitch he saw in the game. Filled = swung, hollow = took; green = good
# decision, red = bad, by analytics.decision_value's run credit (the same
# table as Decision Score). Gray = couldn't be graded (no count / location
# / a bunt or HBP).
GOOD_COLOR = "#3DBE6B"
BAD_COLOR = "#E0524A"


def swing_decision_chart(items, batter_hand=None, title=None):
    """items: [(pitch, credit_or_None, at_bat_no)] for located pitches."""
    fig = go.Figure()
    buckets = {}
    for p, cr, ab in items:
        swung = p.pitch_outcome in SWING_OUTCOMES
        if cr is None:
            key = "Not graded"
        else:
            key = ("Good " if cr > 0 else "Bad ") + ("swing" if swung else "take")
        buckets.setdefault(key, []).append((p, cr, ab, swung))
    styles = {
        "Good swing": dict(symbol="circle", color=GOOD_COLOR, line=dict(color="#1E1E1E", width=1)),
        "Bad swing": dict(symbol="circle", color=BAD_COLOR, line=dict(color="#1E1E1E", width=1)),
        "Good take": dict(symbol="circle-open", color=GOOD_COLOR, line=dict(color=GOOD_COLOR, width=3)),
        "Bad take": dict(symbol="circle-open", color=BAD_COLOR, line=dict(color=BAD_COLOR, width=3)),
        "Not graded": dict(symbol="circle-open", color=MUTED_GRAY, line=dict(color=MUTED_GRAY, width=2)),
    }
    for key in ("Good swing", "Bad swing", "Good take", "Bad take", "Not graded"):
        rows = buckets.get(key)
        if not rows:
            continue
        fig.add_trace(go.Scatter(
            x=[float(p.actual_plate_x) for p, *_ in rows],
            y=[float(p.actual_plate_z) for p, *_ in rows],
            mode="markers", name=key,
            marker=dict(size=18, opacity=0.95, **styles[key]),
            customdata=[[ab, p.pa_pitch_number or "—",
                         f"{p.balls_before}-{p.strikes_before}" if p.balls_before is not None else "—",
                         p.pitch_type.type_name if p.pitch_type else "Unspecified",
                         p.pitch_outcome or "—",
                         f"{cr:+.2f} runs" if cr is not None else "not graded"]
                        for p, cr, ab, _s in rows],
            hovertemplate=("At-bat %{customdata[0]}, pitch %{customdata[1]} · %{customdata[2]} count<br>"
                           "%{customdata[3]} · %{customdata[4]}<br>Decision: %{customdata[5]}<extra></extra>"),
        ))

    fig.add_shape(type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
                  line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)")
    zone_width, zone_height = 2 * ZONE_HALF_WIDTH, ZONE_TOP - ZONE_BOTTOM
    for i in (1, 2):
        gx = -ZONE_HALF_WIDTH + zone_width * i / 3
        fig.add_shape(type="line", xref="x", yref="y", x0=gx, x1=gx, y0=ZONE_BOTTOM, y1=ZONE_TOP,
                      line=dict(color=TEXT_CREAM, width=1, dash="dot"))
        gy = ZONE_BOTTOM + zone_height * i / 3
        fig.add_shape(type="line", xref="x", yref="y", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=gy, y1=gy,
                      line=dict(color=TEXT_CREAM, width=1, dash="dot"))
    if batter_hand in ("R", "L"):
        center_x = -1.75 if batter_hand == "R" else 1.75
        facing = "right" if center_x > 0 else "left"
        for img in hitter_images(center_x=center_x, facing=facing, height_ft=HITTER_HEIGHT_FT, ground_y=-0.5,
                                 batter_hand=batter_hand):
            fig.add_layout_image(**img)
    fig.add_shape(**home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, view="catcher"))

    xs = [abs(float(p.actual_plate_x)) for p, *_ in items]
    zs = [float(p.actual_plate_z) for p, *_ in items]
    x_ext = max([2.7] + [x + 0.35 for x in xs])
    y_lo = min([-0.35] + [z - 0.35 for z in zs])
    y_hi = max([6.0] + [z + 0.35 for z in zs])
    apply_gbo_theme(
        fig, title=title or "Swing Decisions", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=520,
        xaxis=dict(range=[-x_ext, x_ext], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1,
                   constrain="domain"),
        yaxis=dict(range=[y_lo, y_hi], gridcolor=GRID_GRAY, zeroline=False),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig
