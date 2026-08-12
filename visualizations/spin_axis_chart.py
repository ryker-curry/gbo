"""
GBO — Rapsodo Bullpen Analytics: spin axis clock-face chart (Phase 3).

Spec Section 10: a circular clock-face dial, with an arrow pointing from
the center toward each pitch's spin-axis direction.

Convention (documented, not invented here -- see
rapsodo_conventions.spin_clock_to_degrees for the original conversion):
  - RapsodoPitch.spin_axis_degrees is 0-360, where 0 degrees = 12 o'clock
    and the value increases CLOCKWISE (matching Rapsodo's own clock-format
    "Spin Direction" column, e.g. "12:18").
  - To draw an actual clock face (12 at the top, increasing clockwise)
    with Plotly's polar chart -- which by default puts 0 degrees at 3
    o'clock and increases counter-clockwise -- the polar axis itself is
    configured with rotation=90 (shifts zero to the top) and
    direction="clockwise". No extra angle math is needed beyond that;
    spin_axis_degrees is used as-is as the theta value.

Two modes (spec requirement): individual pitch arrows, or one averaged
arrow per pitch type. Averaging spin-axis degrees correctly requires
circular (vector) averaging, not a plain arithmetic mean -- e.g. two
pitches at 5 degrees and 355 degrees should average to 0 degrees, not
180. Implemented with the standard sin/cos circular-mean method.
"""

import math

import plotly.graph_objects as go

from analytics.bullpen_metrics import pitch_type_label
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, BG_DARK
from visualizations.bullpen_charts import color_for_pitch_label


def _circular_mean_degrees(degrees_list):
    """Correct averaging for angular/clock data -- see module docstring.

    Symmetric inputs (e.g. 5 and 355 degrees, which straddle 0/12
    o'clock evenly) can produce a mean_angle that's an infinitesimally
    small negative float due to floating-point rounding in sin/cos --
    e.g. -4e-15 instead of exactly 0. `% 360` on a value that close to
    zero from the negative side rounds to exactly 360.0 at double
    precision, which is out of the intended [0, 360) range (harmless
    for the polar chart itself, which wraps, but wrong for anything
    that assumes a strict [0, 360) contract). Rounding before the
    final modulo clears that artifact.
    """
    if not degrees_list:
        return None
    radians = [math.radians(d) for d in degrees_list]
    mean_sin = sum(math.sin(r) for r in radians) / len(radians)
    mean_cos = sum(math.cos(r) for r in radians) / len(radians)
    mean_angle = math.degrees(math.atan2(mean_sin, mean_cos))
    return round(mean_angle % 360, 9) % 360


def _clock_label(degrees):
    """0-360 degrees (0 = 12 o'clock, clockwise) -> "H:MM" clock string,
    inverse of rapsodo_conventions.spin_clock_to_degrees, for hover text
    that matches the units coaches actually think in."""
    total_minutes = (degrees / 360) * 12 * 60
    hours = int(total_minutes // 60) % 12
    minutes = int(round(total_minutes % 60))
    if minutes == 60:
        minutes = 0
        hours = (hours + 1) % 12
    display_hour = 12 if hours == 0 else hours
    return f"{display_hour}:{minutes:02d}"


def _base_polar_figure(title):
    fig = go.Figure()
    apply_gbo_theme(
        fig, title=title, height=420,
        polar=dict(
            bgcolor=BG_DARK,
            radialaxis=dict(range=[0, 1], showticklabels=False, gridcolor=GRID_GRAY, ticks=""),
            angularaxis=dict(
                rotation=90, direction="clockwise",
                tickmode="array",
                tickvals=[0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330],
                ticktext=["12", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
                gridcolor=GRID_GRAY, linecolor=GRID_GRAY,
            ),
        ),
    )
    return fig


def individual_spin_axis_chart(pitches, pitch_type_filter=None):
    """One arrow per pitch. If pitch_type_filter is given (a display
    label from pitch_type_label), only that type's pitches are drawn --
    otherwise every pitch with a computed spin_axis_degrees is shown,
    which gets visually busy fast, so the page should default to a
    single selected type rather than "all" for this mode."""
    usable = [p for p in pitches if p.spin_axis_degrees is not None]
    if pitch_type_filter is not None:
        usable = [p for p in usable if pitch_type_label(p) == pitch_type_filter]

    fig = _base_polar_figure("Spin Axis — Individual Pitches")
    for p in usable:
        label = pitch_type_label(p)
        degrees = float(p.spin_axis_degrees)
        clock = _clock_label(degrees)
        fig.add_trace(go.Scatterpolar(
            r=[0, 1], theta=[degrees, degrees], mode="lines+markers",
            line=dict(color=color_for_pitch_label(label), width=2),
            marker=dict(size=[0, 8], color=color_for_pitch_label(label)),
            name=label,
            hovertemplate=f"Pitch #{p.pitch_number}<br>{label}<br>Spin Axis: {clock} ({degrees:.0f}°)<extra></extra>",
            showlegend=False,
        ))
    if not usable:
        fig.add_annotation(text="No spin axis data for this selection", showarrow=False,
                            font=dict(color=TEXT_CREAM), xref="paper", yref="paper", x=0.5, y=0.5)
    return fig


def average_spin_axis_chart(pitches):
    """One bold arrow per pitch type, at that type's circular-mean spin
    axis -- makes cross-pitch-type spin-axis separation (a key pitch-
    design signal) readable at a glance without a dozen overlapping
    individual arrows."""
    groups = {}
    for p in pitches:
        if p.spin_axis_degrees is None:
            continue
        groups.setdefault(pitch_type_label(p), []).append(float(p.spin_axis_degrees))

    fig = _base_polar_figure("Spin Axis — Average by Pitch Type")
    for label, degrees_list in groups.items():
        mean_degrees = _circular_mean_degrees(degrees_list)
        clock = _clock_label(mean_degrees)
        color = color_for_pitch_label(label)
        fig.add_trace(go.Scatterpolar(
            r=[0, 1], theta=[mean_degrees, mean_degrees], mode="lines+markers",
            line=dict(color=color, width=4),
            marker=dict(size=[0, 12], color=color),
            name=f"{label} ({len(degrees_list)} pitches)",
            hovertemplate=f"{label}<br>Average Spin Axis: {clock} ({mean_degrees:.0f}°)<br>n={len(degrees_list)}<extra></extra>",
        ))
    if not groups:
        fig.add_annotation(text="No spin axis data available", showarrow=False,
                            font=dict(color=TEXT_CREAM), xref="paper", yref="paper", x=0.5, y=0.5)
    return fig
