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
value, using a Plotly Heatmap so the diverging color scale is always
centered on "break-even" regardless of how hot or cold the actual data
gets -- red = damage favors the hitter (positive RV), blue = favors the
pitcher (negative RV). Same reversed-RdBu convention visualizations/
pitch_location_heatmap.py already established for this app
(reversescale=True => low value blue, high value red), so a coach
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

Sept 2026, Ryker: "add damage by zone for left and right hitters as
well" -- zone_damage_heatmap_by_hand() below draws All Batters/vs
RHH/vs LHH as small multiples side by side (same MAX_COLS-per-row,
skip-if-nothing-located convention pitch_location_heatmaps.py already
established for its own per-pitch-type panels), sharing ONE color
scale across all panels rather than each panel auto-ranging to its own
data -- a pitcher's damage zones can look equally "red" against both
lefties and righties on two separate scales even when one side is
clearly worse, and this chart's whole point is that comparison. Which
batter actually stood in the box is resolved via game_stats.
get_batter_hands (roster Player.bats/OpponentPlayer.bats, with the
switch-hitter fix), never GamePitch.opponent_hand directly -- that
column is unreliable for a three-squad intrasquad pitch specifically,
where it silently holds the PITCHER's own throwing hand instead of the
batter's (get_batter_hands' own docstring, and the real bug it fixed:
Ryker, Sept 2026, "Gavin Derr...only faced left handed hitters" /
"Webb Fern only faced right handed hitters" -- both artifacts of that
same column). Every other hand-split view in this app already goes
through get_batter_hands for this exact reason, so this chart does too
rather than reopening that bug.

Sept 2026, Ryker: "add the hitter graphic on their respective side"
-- the vs RHH/vs LHH panels each draw ONE batter silhouette
(visualizations/hitter_graphic.py) on that hand's real side (see
_draw_panel's own docstring for the hand-to-side mapping, same one
already established for the catcher-view Pitch Detail card), sized
with command_charts.py's own tuned HITTER_HEIGHT_FT (solved against
the SAME fixed ZONE_BOTTOM/TOP box this chart already draws, so the
zone lands at the anatomically correct spot on the silhouette). The
All Batters panel gets no silhouette -- there's no single hand to
draw one for.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from strike_zone import X_MIN, X_MAX, Z_MIN, Z_MAX, ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, MUTED_GRAY
from visualizations.hitter_graphic import home_plate_shape, hitter_images
# Reusing command_charts.py's own tuned batter-silhouette constants
# (Sept 2026, Ryker: "add the hitter graphic on their respective side"
# for the vs RHH/vs LHH panels) rather than a second set of magic
# numbers -- HITTER_HEIGHT_FT in particular isn't an arbitrary choice,
# it's solved against MLB ABS's height-based zone convention so THIS
# app's fixed strike_zone.ZONE_BOTTOM/TOP box (the same box this chart
# already draws) lands at the anatomically correct spot on the
# silhouette (see command_charts.py's own comment for the math).
from visualizations.command_charts import HITTER_HEIGHT_FT, HITTER_CENTER_X, CHART_X_EXTENT_FT

# Oct 2026, Ryker: the batter looked like he was standing in front of
# the plate, too close to the pitcher -- his feet sat on the plate's
# FRONT (pitcher-side) edge. This chart is drawn from the catcher's
# view, where the plate's point hangs down toward the viewer, so "back
# toward the catcher" means lower on screen: drop his feet this far
# below the ground line so he stands in the box. Set so the FRONT
# (higher-drawn, pitcher-side) foot sits exactly on the gray ground
# line: in assets/hitter_silhouette.png that foot's sole is 63px above
# the image bottom out of 818px, i.e. 63/818 * HITTER_HEIGHT_FT.
HITTER_FEET_BACK_FT = 63 / 818 * HITTER_HEIGHT_FT  # ~0.47 ft

# Below this many located pitches in a cell, mute it rather than color
# it -- matches pitch_location_heatmap.py's MIN_FOR_CONTOUR judgment
# (there for density, here for a reliable average).
MIN_PITCHES_FOR_COLOR = 3

# Floor for the shared color-scale half-range (see zone_damage_heatmap_by_hand)
# so a razor-thin, near-zero RV spread doesn't blow the scale up to
# something meaningless -- an RV/100-ish order of magnitude.
_MIN_SCALE_HALF_RANGE = 0.05

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


def _zone_damage_pieces(zone_damage):
    """Pure data prep shared by every panel (single or small-multiples):
    returns (x_centers, y_centers, z_matrix, text_matrix, muted_zones)
    for one compute_zone_damage() dict."""
    cells = zone_damage["cells"]
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
    return x_centers, y_centers, z_matrix, text_matrix, muted_zones


def _draw_panel(fig, pieces, *, row, col, showscale, zmin, zmax, hand=None):
    """Adds one zone-damage panel's heatmap trace + shapes onto `fig`
    at the given subplot (row, col) -- fig must come from
    make_subplots (even a 1x1 grid), so row/col are always valid.

    hand ('R'/'L'/None, Sept 2026, Ryker: "add the hitter graphic on
    their respective side"): draws ONE batter silhouette on the side
    that hand actually stands on, same hand-to-side mapping already
    established for the catcher-view Pitch Detail card (pitcher_game_
    report.py's own docstring on that function) -- a RIGHT-handed
    batter stands on the LEFT/negative-x side of the plate (the box
    closer to 3B) and a LEFT-handed batter on the RIGHT/positive-x
    side (closer to 1B), same side Statcast's own graphics use. None
    (the "All Batters" panel, or a hand that couldn't be resolved)
    skips the silhouette entirely rather than guessing a side."""
    x_centers, y_centers, z_matrix, text_matrix, muted_zones = pieces

    fig.add_trace(
        go.Heatmap(
            x=x_centers, y=y_centers, z=z_matrix,
            zmin=zmin, zmax=zmax, zmid=0, colorscale="RdBu", reversescale=True,
            text=text_matrix, hovertemplate="%{text}<extra></extra>",
            showscale=showscale,
            colorbar=dict(title=dict(text="Avg RV", side="right"), tickfont=dict(color=TEXT_CREAM)),
            xgap=2, ygap=2,
        ),
        row=row, col=col,
    )

    # Gray overlay for muted (too-thin-sample) cells, drawn above the
    # heatmap trace so an empty/NaN cell reads as deliberately muted
    # rather than as a rendering gap.
    for zone in muted_zones:
        x0, x1, z0, z1 = _cell_bounds(zone)
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=z0, y1=z1,
            line=dict(color=GRID_GRAY, width=1), fillcolor=MUTED_GRAY, opacity=0.55,
            row=row, col=col,
        )

    fig.add_shape(
        type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
        row=row, col=col,
    )
    fig.add_shape(
        type="line", x0=X_MIN, x1=X_MAX, y0=0, y1=0,
        line=dict(color=GRID_GRAY, width=1),
        row=row, col=col,
    )
    if hand in ("R", "L"):
        # Same center_x-decides-facing logic as the Pitch Detail card
        # (batter always faces the zone, bat cocked back over the
        # away-from-zone shoulder -- anything else reads as backwards)
        # -- no hand-specific facing override, center_x's sign alone
        # determines it.
        center_x = -HITTER_CENTER_X if hand == "R" else HITTER_CENTER_X
        facing = "right" if center_x > 0 else "left"
        for img in hitter_images(center_x=center_x, facing=facing, height_ft=HITTER_HEIGHT_FT, ground_y=Z_MIN - HITTER_FEET_BACK_FT):
            fig.add_layout_image(**img, row=row, col=col)
    plate = {k: v for k, v in home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, ground_y=Z_MIN, view="catcher").items()
             if k not in ("xref", "yref")}
    fig.add_shape(row=row, col=col, **plate)


def _panel_title(label, zone_damage):
    bits = [f"n={zone_damage['n_located']}"]
    bury = zone_damage.get("bury")
    if bury:
        bits.append(f"{bury['n']} buried")
    return f"{label}  ({', '.join(bits)})"


def _shared_scale(panels):
    """One symmetric zmin/zmax across every panel's colorable cells, so
    red/blue mean the same thing in every panel -- see module
    docstring for why (comparing hand splits on independent scales
    would defeat the point)."""
    values = [
        cell["avg_rv"]
        for _, zone_damage, _ in panels
        for cell in zone_damage["cells"].values()
        if cell["avg_rv"] is not None and cell["n"] >= MIN_PITCHES_FOR_COLOR
    ]
    half_range = max(_MIN_SCALE_HALF_RANGE, max((abs(v) for v in values), default=_MIN_SCALE_HALF_RANGE))
    return -half_range, half_range


def zone_damage_heatmap(zone_damage, pitch_type_label):
    """zone_damage: analytics.pitcher_zone_damage.compute_zone_damage's
    return dict. pitch_type_label: display string for the chart title
    (a single pitch type's name, or "All Pitch Types"). Returns a
    plain Plotly Figure, or None if there's nothing located to draw
    yet (needs Video Review, same as every other zone-dependent chart
    in this app)."""
    if zone_damage["n_located"] == 0:
        return None
    return zone_damage_heatmap_by_hand([("", zone_damage, None)], pitch_type_label, _single_title=True)


def zone_damage_heatmap_by_hand(panels, pitch_type_label, _single_title=False):
    """panels: an ordered list of (label, zone_damage, hand) tuples --
    e.g. [("All Batters", dmg_all, None), ("vs RHH", dmg_r, "R"),
    ("vs LHH", dmg_l, "L")] (Sept 2026, Ryker: "add damage by zone for
    left and right hitters as well"). hand is 'R'/'L'/None -- None
    (e.g. the All Batters panel) draws no batter silhouette; 'R'/'L'
    draws one on that hand's real side (Ryker: "add the hitter graphic
    on their respective side" -- see _draw_panel's own docstring for
    the hand-to-side mapping). Any panel whose zone_damage has nothing
    located yet is dropped (same "skip if nothing to draw" convention
    pitch_location_heatmaps.py uses per pitch type), so a hand this
    pitcher hasn't faced yet simply doesn't get an empty frame. Returns
    a single Plotly Figure with one small-multiple per remaining panel,
    or None if none of them have anything located."""
    panels = [(label, zd, hand) for label, zd, hand in panels if zd["n_located"] > 0]
    if not panels:
        return None

    zmin, zmax = _shared_scale(panels)
    n = len(panels)
    fig = make_subplots(
        rows=1, cols=n,
        subplot_titles=None if _single_title else [_panel_title(label, zd) for label, zd, _ in panels],
        horizontal_spacing=0.08,
    )
    for i, (label, zone_damage, hand) in enumerate(panels):
        pieces = _zone_damage_pieces(zone_damage)
        _draw_panel(fig, pieces, row=1, col=i + 1, showscale=(i == n - 1), zmin=zmin, zmax=zmax, hand=hand)

    # Widened axis extents (Ryker's own tuned command_charts.py
    # constants) whenever ANY panel in this figure draws a batter
    # silhouette -- applied to every panel uniformly, including a
    # hand-less "All Batters" one sharing the row. A per-panel version
    # of this (tight range only where a batter is drawn) was tried and
    # rendered -- Plotly's scaleanchor recomputes each subplot's actual
    # displayed range against its own pixel domain at render time
    # regardless of the narrower range requested here, so the zone
    # ended up the same visual size either way; keeping one shared
    # range is simpler and keeps every panel's zone at an identical,
    # directly comparable scale, which matters more than avoiding the
    # extra whitespace beside the hand-less panel.
    has_hitter = any(hand in ("R", "L") for _, _, hand in panels)
    x_range = [-CHART_X_EXTENT_FT, CHART_X_EXTENT_FT] if has_hitter else [X_MIN, X_MAX]
    y_range = [-0.6, HITTER_HEIGHT_FT + 0.1] if has_hitter else [-0.4, Z_MAX]
    fig.update_xaxes(range=x_range, showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(range=y_range, showticklabels=False, showgrid=False, zeroline=False,
                      scaleanchor="x", scaleratio=1)
    for annotation in fig.layout.annotations:
        annotation.font = dict(color=TEXT_CREAM, size=11)

    any_muted = any(cell["n"] < MIN_PITCHES_FOR_COLOR or cell["avg_rv"] is None
                     for _, zd, _ in panels for cell in zd["cells"].values() if cell["n"] > 0)

    fig = apply_gbo_theme(fig, title=f"{pitch_type_label} — Damage by Zone", height=420)

    if _single_title:
        subtitle_bits = [f"n={panels[0][1]['n_located']} located"]
        bury = panels[0][1].get("bury")
        if bury:
            subtitle_bits.append(f"{bury['n']} more buried (out of the zone low)")
        if any_muted:
            subtitle_bits.append(f"gray = fewer than {MIN_PITCHES_FOR_COLOR} pitches")
        fig.add_annotation(
            text=" · ".join(subtitle_bits), xref="paper", yref="paper", x=0.5, y=1.14,
            showarrow=False, font=dict(color=TEXT_CREAM, size=11),
        )
    elif any_muted:
        fig.add_annotation(
            text=f"gray = fewer than {MIN_PITCHES_FOR_COLOR} pitches", xref="paper", yref="paper", x=0.5, y=1.16,
            showarrow=False, font=dict(color=TEXT_CREAM, size=11),
        )
    return fig
