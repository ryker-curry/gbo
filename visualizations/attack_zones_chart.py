"""
GBO -- Attack Zones chart: Heart/Shadow/Chase/Waste nested-tier strike
zone with each located pitch plotted on top, colored by pitch type.

Extracted Sept 2026 from shiny_app/modules/pitcher_game_report.py (where
it was originally built, Aug/Sept 2026, per Ryker: attached an example
from a third-party pitch-profiling app and asked for the same idea
restyled into GBO's own dark theme, then a follow-up asking for the four
zone tiers to each get their own color and label) into its own
visualizations module so Pitcher Profile's Command & Execution tab
(Ryker, Sept 2026: "add: attack zones with attack zone chart") can reuse
the exact same chart instead of a second, differently-styled copy --
same "pure viz function, caller wraps it" split every other chart in
visualizations/ already follows. pitcher_game_report.py now imports this
function too (as _attack_zones_figure, its own established internal
name) rather than keeping its own copy.

Only pitches with actual_plate_x/z on file plot (same "located"
convention pitch_location_stats.compute_attack_zones itself uses) --
caller filters."""

import plotly.graph_objects as go

import strike_zone
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, MUTED_GRAY, TEXT_CREAM, GOLD, CRIMSON
from visualizations.bullpen_charts import color_for_pitch_label
from visualizations.hitter_graphic import home_plate_shape


def attack_zones_figure(pitches):
    """Visual companion to compute_attack_zones' Heart/Shadow/Chase/
    Waste percentages (Ryker, Sept 2026: attached an example from a
    third-party pitch-profiling app and asked "would like to add this
    to pitcher game report under command and execution... right now we
    have labels of percentages of these but now this would also show a
    visual", then a follow-up: "the colors of the strike zone should be
    heart, shadow, chase zone, and waste. the different zones should be
    labeled") -- same idea (nested zone tiers behind the actual pitch
    locations) restyled into GBO's own dark theme/palette rather than
    that app's light one, and using this app's own tier geometry
    (strike_zone.classify_attack_zone's HEART_*/SHADOW_*/CHASE_*
    constants -- a GBO approximation of Savant's tiers, not identical
    numbers, see pitch_location_stats.py's module docstring) instead of
    guessing at the reference image's own boundaries.

    Four tiers, each its own color (not one hue at different opacities
    -- Ryker's own correction above) stepping from GOLD (Heart, brand
    accent = the one spot you actually want to live) through CRIMSON
    (Shadow) to the neutral MUTED_GRAY/GRID_GRAY grays (Chase/Waste --
    the two tiers that matter least), each a real filled rect layered
    Waste-below-Chase-below-Shadow-below-Heart so all four are visible
    at once. Labeled via dummy legend-only traces (x=[None]) rather
    than text annotations drawn over the zone -- avoids fighting for
    space with actual pitch markers, which can land anywhere in any
    tier, and puts the zone labels in the same legend row as the
    pitch-type legend below instead of a second, separate one. The
    true strike zone (not a tier boundary -- it straddles Heart and
    Shadow) gets its own dashed-line legend entry the same way, same
    as the reference image's own "Strike Zone" entry.

    Only pitches with actual_plate_x/z on file plot (same "located"
    convention compute_attack_zones itself uses) -- caller filters."""
    fig = go.Figure()

    # Kept as locals (not the shared apply_gbo_theme call's own inline
    # dicts below) so the Waste tier's background rect can reuse the
    # exact same bounds as the axis range instead of a second, easy-to-
    # drift-out-of-sync pair of magic numbers.
    x_extent, y_range = 2.5, (-0.4, 5.0)

    # (half_width, bottom, top, legend name, fill color, legend swatch opacity, fill opacity)
    tiers = [
        (x_extent, y_range[0], y_range[1], "Waste", GRID_GRAY, 0.6, 0.55),
        (strike_zone.CHASE_HALF_WIDTH, strike_zone.CHASE_BOTTOM, strike_zone.CHASE_TOP, "Chase Zone", MUTED_GRAY, 0.7, 0.35),
        (strike_zone.SHADOW_HALF_WIDTH, strike_zone.SHADOW_BOTTOM, strike_zone.SHADOW_TOP, "Shadow", CRIMSON, 0.75, 0.30),
        (strike_zone.HEART_HALF_WIDTH, strike_zone.HEART_BOTTOM, strike_zone.HEART_TOP, "Heart", GOLD, 0.85, 0.38),
    ]
    for half_width, bottom, top, name, color, legend_opacity, fill_opacity in tiers:
        fig.add_shape(
            type="rect", x0=-half_width, x1=half_width, y0=bottom, y1=top,
            line=dict(width=0), fillcolor=color, opacity=fill_opacity, layer="below",
        )
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(symbol="square", size=14, color=color, opacity=legend_opacity),
            name=name, showlegend=True, hoverinfo="skip", legend="legend",
        ))
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines", line=dict(color=TEXT_CREAM, width=2, dash="dash"),
        name="Strike Zone", showlegend=True, hoverinfo="skip", legend="legend",
    ))

    order, groups = [], {}
    for p in pitches:
        label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)
    for label in order:
        group = groups[label]
        color = color_for_pitch_label(label) if label != "Unspecified" else MUTED_GRAY
        fig.add_trace(go.Scatter(
            x=[float(p.actual_plate_x) for p in group],
            y=[float(p.actual_plate_z) for p in group],
            mode="markers", name=label,
            marker=dict(color=color, size=12, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            hovertemplate=f"{label}<br>Attack Zone: %{{customdata}}<extra></extra>",
            customdata=[strike_zone.classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z)) for p in group],
            legend="legend2",
        ))

    fig.add_shape(
        type="rect", x0=-strike_zone.ZONE_HALF_WIDTH, x1=strike_zone.ZONE_HALF_WIDTH,
        y0=strike_zone.ZONE_BOTTOM, y1=strike_zone.ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2, dash="dash"), fillcolor="rgba(0,0,0,0)",
    )
    fig.add_shape(**home_plate_shape(half_width_ft=strike_zone.ZONE_HALF_WIDTH, ground_y=0.0, view="catcher"))

    apply_gbo_theme(
        fig, title="Attack Zones", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=520,
        xaxis=dict(range=[-x_extent, x_extent], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=list(y_range), gridcolor=GRID_GRAY, zeroline=False),
        # Two separate legend boxes (Ryker: "one side should be the
        # pitches and the other should be the strike zone labels") --
        # `legend` (the zone tiers + Strike Zone, tagged above) sits
        # bottom-left, `legend2` (the pitch types, tagged above) sits
        # bottom-right, each its own vertical list so neither has to
        # wrap awkwardly the way one shared horizontal legend did.
        legend=dict(orientation="v", x=0, xanchor="left", y=-0.08, yanchor="top"),
        legend2=dict(orientation="v", x=1, xanchor="right", y=-0.08, yanchor="top", bgcolor="rgba(0,0,0,0)"),
    )
    return fig
