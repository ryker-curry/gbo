"""
GBO -- Hitter Hot Zones chart (Oct 2026). Three panels side by side:
All pitchers / vs RHP / vs LHP. 13 zones (9 strike-zone cells + 4
outside corners), catcher's view, colored blue (cold) -> red (hot) by
AVG or SLG on balls in play. Cells under MIN_BIP balls in play are
muted gray with just the count. See analytics/hitter_hot_zones.py.
"""

import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from analytics.hitter_hot_zones import MIN_BIP, OUTER
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
from visualizations.chart_theme import apply_gbo_theme, TEXT_CREAM
from visualizations.hitter_graphic import home_plate_shape

SCALE = [[0.0, "#2F6FD0"], [0.5, "#E9E4DA"], [1.0, "#D0342C"]]
RANGES = {"avg": (0.150, 0.450), "slg": (0.200, 0.800)}
PAD = 0.55               # outside ring thickness, ft
MUTED = "#2E333B"


def _fmt(v):
    return f"{v:.3f}".lstrip("0") if v is not None else "—"


def _inner_bounds(zone):
    w = 2 * ZONE_HALF_WIDTH / 3
    h = (ZONE_TOP - ZONE_BOTTOM) / 3
    row, col = (zone - 1) // 3, (zone - 1) % 3
    x0 = -ZONE_HALF_WIDTH + col * w
    z1 = ZONE_TOP - row * h
    return x0, z1 - h, x0 + w, z1


def _outer_bounds(key):
    mid = (ZONE_BOTTOM + ZONE_TOP) / 2
    left = key.endswith("L")
    up = key.startswith("OU")
    x0, x1 = (-ZONE_HALF_WIDTH - PAD, 0.0) if left else (0.0, ZONE_HALF_WIDTH + PAD)
    z0, z1 = (mid, ZONE_TOP + PAD) if up else (ZONE_BOTTOM - PAD, mid)
    return x0, z0, x1, z1


def _outer_label_pos(key):
    left = key.endswith("L")
    up = key.startswith("OU")
    x = (-ZONE_HALF_WIDTH - PAD / 2) if left else (ZONE_HALF_WIDTH + PAD / 2)
    z = (ZONE_TOP + PAD / 2) if up else (ZONE_BOTTOM - PAD / 2)
    return x, z


def _color(value, metric):
    lo, hi = RANGES[metric]
    t = max(0.0, min(1.0, (value - lo) / (hi - lo)))
    return sample_colorscale(SCALE, [t])[0]


def hot_zone_figure(panels, metric="avg", stacked=False):
    """stacked=True (phones, Oct 2026): one panel per row instead of side by side."""
    n = len(panels)
    fig = make_subplots(rows=n if stacked else 1, cols=1 if stacked else n,
                        horizontal_spacing=0.04, vertical_spacing=0.06 if stacked else 0.3,
                        subplot_titles=[f"{label}  ·  {t['bip']} BIP  ·  {metric.upper()} {_fmt(t[metric])}"
                                        for label, _c, t in panels])
    mname = metric.upper()
    for i, (label, cells, _t) in enumerate(panels, start=1):
        xref = "x" if i == 1 else f"x{i}"
        yref = "y" if i == 1 else f"y{i}"
        hx, hy, htxt = [], [], []
        # outside corners first, inner cells drawn on top
        for key in OUTER:
            c = cells[key]
            x0, z0, x1, z1 = _outer_bounds(key)
            fill = _color(c[metric], metric) if c["bip"] >= MIN_BIP else MUTED
            fig.add_shape(type="rect", x0=x0, y0=z0, x1=x1, y1=z1, xref=xref, yref=yref,
                          fillcolor=fill, line=dict(color="#171B21", width=2), layer="below")
            lx, lz = _outer_label_pos(key)
            txt = _fmt(c[metric]) if c["bip"] >= MIN_BIP else (f"{c['bip']}" if c["bip"] else "")
            fig.add_annotation(x=lx, y=lz, xref=xref, yref=yref, text=txt, showarrow=False,
                               font=dict(size=11, color="#111" if c["bip"] >= MIN_BIP else TEXT_CREAM))
            hx.append(lx); hy.append(lz)
            htxt.append(f"Outside ({'up' if key.startswith('OU') else 'down'}-{'left' if key.endswith('L') else 'right'})"
                        f"<br>{mname} {_fmt(c[metric])} · {c['hits']} H / {c['bip']} BIP")
        for z in range(1, 10):
            c = cells[z]
            x0, z0, x1, z1 = _inner_bounds(z)
            fill = _color(c[metric], metric) if c["bip"] >= MIN_BIP else "#3A404A"
            fig.add_shape(type="rect", x0=x0, y0=z0, x1=x1, y1=z1, xref=xref, yref=yref,
                          fillcolor=fill, line=dict(color="#171B21", width=2))
            cx, cz = (x0 + x1) / 2, (z0 + z1) / 2
            if c["bip"] >= MIN_BIP:
                txt = f"<b>{_fmt(c[metric])}</b><br><span style='font-size:9px'>{c['bip']} BIP</span>"
                col = "#111"
            else:
                txt = f"<span style='font-size:9px'>{c['bip']} BIP</span>" if c["bip"] else ""
                col = TEXT_CREAM
            fig.add_annotation(x=cx, y=cz, xref=xref, yref=yref, text=txt, showarrow=False,
                               font=dict(size=13, color=col))
            hx.append(cx); hy.append(cz)
            htxt.append(f"Zone {z}<br>AVG {_fmt(c['avg'])} · SLG {_fmt(c['slg'])}<br>{c['hits']} H / {c['bip']} BIP")
        fig.add_shape(type="rect", x0=-ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, x1=ZONE_HALF_WIDTH, y1=ZONE_TOP,
                      xref=xref, yref=yref, line=dict(color="#E9ECF1", width=2.5), fillcolor="rgba(0,0,0,0)")
        plate = home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, ground_y=ZONE_BOTTOM - PAD - 0.25, view="catcher")
        if isinstance(plate, dict):
            plate = dict(plate, xref=xref, yref=yref)
            fig.add_shape(**plate)
        fig.add_trace(go.Scatter(x=hx, y=hy, mode="markers", marker=dict(size=28, opacity=0),
                                 hovertext=htxt, hoverinfo="text", showlegend=False),
                      row=i if stacked else 1, col=1 if stacked else i)
        rc = dict(row=i, col=1) if stacked else dict(row=1, col=i)
        fig.update_xaxes(range=[-ZONE_HALF_WIDTH - PAD - 0.1, ZONE_HALF_WIDTH + PAD + 0.1], visible=False,
                         fixedrange=True, **rc)
        fig.update_yaxes(range=[ZONE_BOTTOM - PAD - 0.6, ZONE_TOP + PAD + 0.1], visible=False, fixedrange=True,
                         scaleanchor=xref, scaleratio=1, **rc)
    apply_gbo_theme(fig, height=(380 * n) if stacked else 430, showlegend=False, margin=dict(t=40, b=10, l=10, r=10))
    fig.update_annotations(selector=dict(xref="paper"), font=dict(size=12, color="#E9ECF1"))
    return fig
