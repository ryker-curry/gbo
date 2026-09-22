"""
GBO -- Hitter Spray Chart / Infield Slice Chart (Sept 2026 addition,
Ryker: "i want a hit spray chart as well as an infield slice chart",
referencing Baseball Savant's own player-page Visuals for the concrete
look/behavior).

hit_spray_chart(pitches, title=None):
    Every ball in play that ended in a base hit (ab_outcome in
    HIT_AB_OUTCOMES: 1B/2B/3B/HR), plotted at its actual recorded
    batted_ball_x/batted_ball_y location (field_location.py's own
    feet-from-home-plate convention), colored by hit type -- matches
    Savant's own "BASE HITS" spray chart exactly (Ryker confirmed
    hits-only over also plotting outs). Reuses field_location.py's
    draw_field_diagram() for the field background, so this chart's
    foul lines/outfield arc/base dots are pixel-identical to the
    existing Field Location click-selector elsewhere in the app, not a
    second hand-drawn field.

infield_slice_chart(pitches, title=None):
    Baseball Savant's "Infield Slice Chart": the % share of ALL batted
    balls landing within INFIELD_SLICE_DISTANCE_FT (200 ft, Savant's
    own threshold -- "all batted balls with a projected distance of
    200 feet or less") that fall in each of 5 equal 18-degree wedges
    across the 90-degree fair-territory arc, left field line to right
    field line. A SEQUENTIAL encoding (one hue -- GBO crimson, opacity
    scaled by share), not a categorical one, since this is one measure
    (share of weak/short contact) varying by field position, not five
    unrelated categories -- see the dataviz skill's "sequential = one
    hue" rule. Wedges are raw field-side (not batter-relative Pull/
    Center/Oppo), matching Savant's own non-mirrored treatment -- same
    "raw Left/Center/Right" fallback field_location.classify_spray_
    direction() already uses when a batter's hand isn't being applied.
    Returns None if there are no qualifying (located, <=200ft) batted
    balls in `pitches`, same "nothing to show yet" convention every
    other chart builder in this app follows.
"""

import math

import plotly.graph_objects as go

from field_location import draw_field_diagram, distance_from_plate, X_MIN, X_MAX, Y_MIN, Y_MAX, BG_DARK, GBO_CREAM

# Fixed hue-per-hit-type order (never cycled/reassigned by filters --
# dataviz skill's categorical rule), validated colorblind-safe against
# GBO's dark chart surface (scripts/validate_palette.js --mode dark:
# lightness band, chroma floor, CVD separation, normal-vision floor,
# and surface contrast all PASS). Deliberately its own small palette,
# distinct from pitch_type_config.PITCH_TYPE_COLORS -- those hues
# already mean "pitch type" on every pitch-location/command chart in
# the app; reusing any of them here for "hit type" would read as the
# wrong dimension at a glance.
HIT_TYPE_COLORS = {
    "1B": "#D9722A",
    "2B": "#6C7FE0",
    "3B": "#B8860B",
    "HR": "#E0468C",
}
HIT_TYPE_LABELS = {"1B": "Single", "2B": "Double", "3B": "Triple", "HR": "Home Run"}
HIT_TYPE_ORDER = ("1B", "2B", "3B", "HR")  # legend/z-order, matches Savant's own listed order

INFIELD_SLICE_DISTANCE_FT = 200  # Savant's own threshold for this chart
INFIELD_SLICE_DISPLAY_RADIUS_FT = 220  # a little past the threshold, for visual breathing room
_SLICE_COUNT = 5
_SLICE_WIDTH_DEG = 90 / _SLICE_COUNT  # 18 degrees each, spanning the full 90-degree fair-territory arc


def hit_spray_chart(pitches, title=None):
    located_hits = [
        p for p in pitches
        if p.ab_outcome in HIT_TYPE_COLORS and p.batted_ball_x is not None and p.batted_ball_y is not None
    ]
    if not located_hits:
        return None

    fig = go.Figure()
    draw_field_diagram(fig)

    by_type = {t: [] for t in HIT_TYPE_ORDER}
    for p in located_hits:
        by_type[p.ab_outcome].append(p)

    for hit_type in HIT_TYPE_ORDER:
        group = by_type[hit_type]
        if not group:
            continue
        xs = [float(p.batted_ball_x) for p in group]
        ys = [float(p.batted_ball_y) for p in group]
        dists = [distance_from_plate(x, y) for x, y in zip(xs, ys)]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers",
            marker=dict(size=9, color=HIT_TYPE_COLORS[hit_type], opacity=0.85, line=dict(color=BG_DARK, width=0.5)),
            name=HIT_TYPE_LABELS[hit_type],
            legendgroup=hit_type,
            customdata=dists,
            hovertemplate=f"{HIT_TYPE_LABELS[hit_type]}<br>" + "%{customdata:.0f} ft from home<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15, color="#E9ECF1")) if title else None,
        xaxis=dict(range=[X_MIN, X_MAX], visible=False, fixedrange=True),
        yaxis=dict(range=[Y_MIN, Y_MAX], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_DARK,
        height=480, margin=dict(l=10, r=10, t=40 if title else 10, b=10),
        legend=dict(font=dict(color=GBO_CREAM), bgcolor="rgba(0,0,0,0)"),
        dragmode=False,
    )
    return fig


def _wedge_path(angle_start_deg, angle_end_deg, radius, n_points=16):
    """Home plate -> an arc of `n_points` segments from angle_start to
    angle_end -> back to home plate -- a closed polygon Plotly can fill
    as one pie-style wedge. Same angle convention as field_location.py
    (0 = dead center, - = left field side, + = right field side)."""
    xs, ys = [0.0], [0.0]
    for i in range(n_points + 1):
        deg = angle_start_deg + (angle_end_deg - angle_start_deg) * i / n_points
        rad = math.radians(deg)
        xs.append(radius * math.sin(rad))
        ys.append(radius * math.cos(rad))
    xs.append(0.0)
    ys.append(0.0)
    return xs, ys


def infield_slice_chart(pitches, title=None):
    weak_contact = []
    for p in pitches:
        if p.pitch_outcome != "In Play" or p.batted_ball_x is None or p.batted_ball_y is None:
            continue
        x, y = float(p.batted_ball_x), float(p.batted_ball_y)
        dist = distance_from_plate(x, y)
        if dist is not None and dist <= INFIELD_SLICE_DISTANCE_FT:
            weak_contact.append((x, y, dist))
    total = len(weak_contact)
    if total == 0:
        return None

    bounds = [-45 + i * _SLICE_WIDTH_DEG for i in range(_SLICE_COUNT + 1)]  # -45, -27, -9, 9, 27, 45
    counts = [0] * _SLICE_COUNT
    for x, y, _dist in weak_contact:
        angle = math.degrees(math.atan2(x, y))
        angle = max(-45.0, min(45.0, angle))  # clamp floating-point edge cases right at the foul lines
        idx = min(int((angle - bounds[0]) / _SLICE_WIDTH_DEG), _SLICE_COUNT - 1)
        counts[idx] += 1

    max_count = max(counts) or 1
    fig = go.Figure()
    draw_field_diagram(fig, line_dist=INFIELD_SLICE_DISPLAY_RADIUS_FT, arc_radius_ft=INFIELD_SLICE_DISPLAY_RADIUS_FT)

    label_x, label_y, label_text = [], [], []
    for i in range(_SLICE_COUNT):
        pct = round(100 * counts[i] / total)
        opacity = 0.25 + 0.60 * (counts[i] / max_count)
        wx, wy = _wedge_path(bounds[i], bounds[i + 1], INFIELD_SLICE_DISPLAY_RADIUS_FT)
        fig.add_trace(go.Scatter(
            x=wx, y=wy, mode="lines", fill="toself",
            fillcolor=f"rgba(191,30,45,{opacity:.2f})",  # GBO_CRIMSON at scaled opacity
            line=dict(color=GBO_CREAM, width=1),
            showlegend=False,
            name=f"Slice {i + 1}",
            hovertemplate=f"{pct}% of weak/short contact ({counts[i]} of {total})<extra></extra>",
        ))
        mid_deg = (bounds[i] + bounds[i + 1]) / 2
        rad = math.radians(mid_deg)
        label_radius = INFIELD_SLICE_DISPLAY_RADIUS_FT * 1.08
        label_x.append(label_radius * math.sin(rad))
        label_y.append(label_radius * math.cos(rad))
        label_text.append(f"{pct}%")

    fig.add_trace(go.Scatter(
        x=label_x, y=label_y, mode="text", text=label_text,
        textfont=dict(color=GBO_CREAM, size=14, family="IBM Plex Sans, system-ui, sans-serif"),
        showlegend=False, hoverinfo="skip",
    ))

    display_max = INFIELD_SLICE_DISPLAY_RADIUS_FT * 1.2
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=15, color="#E9ECF1")) if title else None,
        xaxis=dict(range=[-display_max, display_max], visible=False, fixedrange=True),
        yaxis=dict(range=[-20, display_max], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        paper_bgcolor=BG_DARK, plot_bgcolor=BG_DARK,
        height=420, margin=dict(l=10, r=10, t=40 if title else 10, b=10),
        showlegend=False,
        dragmode=False,
    )
    return fig
