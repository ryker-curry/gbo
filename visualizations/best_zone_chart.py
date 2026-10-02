"""
GBO -- Best Zone chart (Oct 2026). One small panel per pitch type for one
batter hand: the pitch's best area shaded blue, every pitch colored by
how far it landed from that area (blue inside -> red 12"+), Paradigm-style.
Catcher's view (same as the Zone tab's heat maps), plate drawn on top.
See analytics/best_zone.py for how the areas are built.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analytics import best_zone as bz
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, TEXT_CREAM, GRID_GRAY
from visualizations.hitter_graphic import home_plate_shape

BAND_COLORS = {"Inside": "#3D7BFF", "0-3\"": "#5B8DEF", "3-6\"": "#A9C4F5", "6-12\"": "#F2A65A", "12\"+": "#D64545"}
X_RANGE = (-2.2, 2.2)
Z_RANGE = (0.2, 4.8)
MAX_COLS = 3


def best_zone_figure(scored, maps, throws, bat_hand):
    rows = [r for r in scored if r["matchup"] == bz.matchup(throws, bat_hand)]
    if not rows:
        return None
    by_type = {}
    for r in rows:
        by_type.setdefault(r["label"], []).append(r)
    order = sorted(by_type, key=lambda k: -len(by_type[k]))
    n = len(order)
    cols = min(MAX_COLS, n)
    nrows = (n + cols - 1) // cols
    titles = []
    for label in order:
        rs = by_type[label]
        inside = sum(1 for r in rs if r["band"] == "Inside")
        titles.append(f"{label} (n={len(rs)}) · {round(inside / len(rs) * 100)}% in best zone")
    fig = make_subplots(rows=nrows, cols=cols, subplot_titles=titles, horizontal_spacing=0.05, vertical_spacing=0.12)
    shown_bands = set()
    for i, label in enumerate(order):
        r_, c_ = i // cols + 1, i % cols + 1
        rs = by_type[label]
        key = (rs[0]["family"], rs[0]["matchup"])
        for lo_a, hi_a, lo_z, hi_z in maps[key]["rects"]:
            x0, x1 = sorted((bz.to_plate_x(lo_a, throws), bz.to_plate_x(hi_a, throws)))
            fig.add_shape(type="rect", x0=x0, x1=x1, y0=lo_z, y1=hi_z, line=dict(width=1.2, color="rgba(140,175,245,0.9)", dash="dot"),
                          fillcolor="rgba(91,141,239,0.18)", layer="below", row=r_, col=c_)
        fig.add_shape(type="rect", x0=-ZONE_HALF_WIDTH, x1=ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, y1=ZONE_TOP,
                      line=dict(color=TEXT_CREAM, width=1.5), fillcolor="rgba(0,0,0,0)", row=r_, col=c_)
        plate = {k: v for k, v in home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, ground_y=0.75, view="catcher").items()
                 if k not in ("xref", "yref")}
        plate["layer"] = "above"
        fig.add_shape(row=r_, col=c_, **plate)
        for band, _lo, _hi in bz.BANDS:
            pts = [r for r in rs if r["band"] == band]
            if not pts:
                continue
            fig.add_trace(go.Scatter(
                x=[float(r["pitch"].actual_plate_x) for r in pts], y=[float(r["pitch"].actual_plate_z) for r in pts],
                mode="markers", name=f"{band} best zone" if band == "Inside" else f"{band} away",
                legendgroup=band, showlegend=band not in shown_bands,
                marker=dict(color=BAND_COLORS[band], size=8, opacity=0.9, line=dict(width=0.6, color="#111")),
                customdata=[[round(r["dist"], 1)] for r in pts],
                hovertemplate=f"{label}<br>%{{customdata[0]}}\" from best zone<extra></extra>",
            ), row=r_, col=c_)
            shown_bands.add(band)
    fig.update_xaxes(range=list(X_RANGE), showticklabels=False, showgrid=False, zeroline=False)
    fig.update_yaxes(range=list(Z_RANGE), showticklabels=False, showgrid=False, zeroline=False)
    for k in range(1, nrows * cols + 1):
        sfx = "" if k == 1 else str(k)
        fig.layout[f"yaxis{sfx}"].scaleanchor = f"x{sfx}"
    for a in fig.layout.annotations:
        a.font = dict(color=TEXT_CREAM, size=11)
    hand_word = "RHH" if bat_hand == "R" else "LHH"
    fig = apply_gbo_theme(fig, title=f"Best zone vs {hand_word} (shaded) -- catcher's view", height=330 * nrows + 90)
    fig.update_layout(legend=dict(orientation="h", y=-0.04), margin=dict(t=80))
    return fig
