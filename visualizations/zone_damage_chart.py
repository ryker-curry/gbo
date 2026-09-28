"""
GBO -- Opposing-hitter "damage by zone" heat map chart (Sept 2026,
Ryker: "an opposing hitters heat map for each of my pitchers ... select
a pitch type from a drop down then see a strikezone that has red zones
for hot zones where the most damage gets done and blue for cold zones
... could be based on wOBA, contact quality in each zone, want your
opinion on which is best" -- answered in
analytics/pitcher_zone_damage.py's own docstring: run_value (RV), the
same number already driving the "RV/100" column in this exact Results
tab, re-sliced spatially instead of by pitch type. This file only
draws that data; see pitcher_zone_damage.compute_zone_damage for the
metric reasoning).

Draws the SAME 1-9 zone grid as everywhere else in GBO
(strike_zone.derive_old_zone), colored by each cell's average run
value, using a Plotly Heatmap with zmid=0 so the diverging color scale
is always centered on "break-even" regardless of how hot or cold the
actual data gets -- red = damage favors the hitter (positive RV),
blue = favors the pitcher (negative RV). Same reversed-RdBu convention
visualizations/pitch_location_heatmap.py already established for this
app (reversescale=True => low value blue, high value red), so a coach
reading both charts sees the same color language.

Cells with fewer than MIN_PITCHES_FOR_COLOR located pitches are muted
(gray, no color read) rather than shown at full saturation -- one or
two pitches at a location says nothing reliable about "hot" or "cold"
yet, same don't-oversell-thin-data judgment call
pitch_location_heatmap.py's own MIN_FOR_CONTOUR already makes for
density.

Bury (zone 0) has no fixed box the same way 1-9 do (strike_zone.
derive_old_zone's own docstring), so it isn't forced into a 10th grid
cell -- it's reported as a plain-language note under the chart title
instead, same as pitcher_zone_damage.py's own reasoning for keeping it
a separate summary rather than a cell.
"""

import plotly.graph_objects as go

from strike_zone import X_MIN, X_MAX, Z_MIN, Z_MAX, ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, MUTED_GRAY
from visualizations.hitter_graphic import home_plate_shape

# Below this many located pitches in a cell, mute it rather than color
# it -- matches pitch_location_heatmap.py's MIN_FOR_CONTOUR judgment
# (there for density, here for a reliable average).
MIN_PITCHES_FOR_COLOR = 3

_ZONE_WIDTH = 2 * ZONE_HALF_WIDTH
_ZONE_HEIGHT = ZONE_TOP - ZONE_BOTTOM

_CONTACT_QUALITY_ORDER = ("Barreled/Squared Up", "Solid", "Clipped", "Off the End", "Jammed", "Weak", "Bunt")


def _cell_bounds(zone):
    """Inverse of strike_zone.derive_old_zone's own column/row math --
    given a 1-9 zone number, returns (x0, x1, z0, z1) in the same feet
    coordinates that math derives zones FROM, so this chart's grid
    lines up exactly with how a pitch actually gets classified into
    that zone."""
    row, col = (zone - 1) // 3, (zone - 1) % 3
    x0 = -ZONE_HALF_WIDTH + (col / 3) * _ZONE_WIDTH
    x1 = -ZONE_HALF_WIDTH + ((col + 1) / 3) * _ZONE_WIDTH
    z1 = ZONE_TOP - (row / 3) * _ZONE_HEIGHT
    z0 = ZONE_TOP - ((row + 1) / 3) * _ZONE_HEIGHT
    return x0, x1, z0, z1


def _cell_center(zone):
    x0, x1, z0, z1 = _cell_bounds(zone)
    return (x0 + x1) / 2, (z0 + z1) / 2


def _hover_text(zone, cell):
    n = cell["n"]
    if n == 0:
        return f"Zone {zone}<br>No located pitches yet"
    lines = [f"Zone {zone}  (n={n})"]
    if cell["avg_rv"] is not None:
        lines.append(f"Avg RV: {cell['avg_rv']:+.3f}  (total {cell['total_rv']:+.2f})")
    else:
        lines.append("Avg RV: n/a")
    if cell["balls_in_play"]:
        cq_bits = [
            f"{cq} {cell['contact_quality_counts'].get(cq, 0)}"
            for cq in _CONTACT_QUALITY_ORDER
            if cell["contact_quality_counts"].get(cq, 0)
        ]
        lines.append(f"Contact ({cell['balls_in_play']} in play): " + ", ".join(cq_bits))
    if cell["hits_allowed"]:
        lines.append(f"Hits allowed: {cell['hits_allowed']}" + (f" ({cell['hr_allowed']} HR)" if cell["hr_allowed"] else ""))
    return "<br>".join(lines)


def zone_damage_heatmap(zone_damage, pitch_type_label):
    """zone_damage: analytics.pitcher_zone_damage.compute_zone_damage's
    return dict. pitch_type_label: display string for the chart title
    (a single pitch type's name, or "All Pitch Types"). Returns a
    plain Plotly Figure, or None if there's nothing located to draw
    yet (needs Video Review, same as every other zone-dependent chart
    in this app)."""
    cells = zone_damage["cells"]
    if zone_damage["n_located"] == 0:
        return None

    z_matrix, text_matrix, muted_zones = [], [], []
    for row in range(3):
        z_row, text_row = [], []
        for col in range(3):
            zone = row * 3 + col + 1
            cell = cells.get(zone) or {
                "n": 0, "avg_rv": None, "total_rv": None, "balls_in_play": 0,
                "contact_quality_counts": {}, "hits_allowed": 0, "hr_allowed": 0,
            }
            if cell["n"] < MIN_PITCHES_FOR_COLOR or cell["avg_rv"] is None:
                z_row.append(None)
                muted_zones.append(zone)
            else:
                z_row.append(cell["avg_rv"])
            text_row.append(_hover_text(zone, cell))
        z_matrix.append(z_row)
        text_matrix.append(text_row)

    x_centers = [_cell_center(z)[0] for z in (1, 2, 3)]
    y_centers = [_cell_center(z)[1] for z in (1, 4, 7)]  # top, middle, bottom row centers

    fig = go.Figure()

    fig.add_trace(
        go.Heatmap(
            x=x_centers, y=y_centers, z=z_matrix,
            zmid=0, colorscale="RdBu", reversescale=True,
            text=text_matrix, hovertemplate="%{text}<extra></extra>",
            colorbar=dict(title=dict(text="Avg RV", side="right"), tickfont=dict(color=TEXT_CREAM)),
            xgap=2, ygap=2,
        )
    )

    # Gray overlay for muted (too-thin-sample) cells, drawn above the
    # heatmap trace so an empty/NaN cell reads as deliberately muted
    # rather than as a rendering gap.
    for zone in muted_zones:
        x0, x1, z0, z1 = _cell_bounds(zone)
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=z0, y1=z1,
            line=dict(color=GRID_GRAY, width=1), fillcolor=MUTED_GRAY, opacity=0.55,
        )

    fig.add_shape(
        type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )
    fig.add_shape(
        type="line", x0=X_MIN, x1=X_MAX, y0=0, y1=0,
        line=dict(color=GRID_GRAY, width=1),
    )
    plate = {k: v for k, v in home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, ground_y=Z_MIN, view="catcher").items()
             if k not in ("xref", "yref")}
    fig.add_shape(**plate)

    fig.update_xaxes(range=[X_MIN, X_MAX], showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(range=[-0.4, Z_MAX], showticklabels=False, showgrid=False, zeroline=False,
                      scaleanchor="x", scaleratio=1)

    bury = zone_damage.get("bury")
    subtitle_bits = [f"n={zone_damage['n_located']} located"]
    if bury:
        subtitle_bits.append(f"{bury['n']} more buried (out of the zone low)")
    if muted_zones:
        subtitle_bits.append(f"gray = fewer than {MIN_PITCHES_FOR_COLOR} pitches")

    fig = apply_gbo_theme(fig, title=f"{pitch_type_label} — Damage by Zone", height=420)
    fig.add_annotation(
        text=" · ".join(subtitle_bits), xref="paper", yref="paper", x=0.5, y=1.09,
        showarrow=False, font=dict(color=TEXT_CREAM, size=11),
    )
    return fig
