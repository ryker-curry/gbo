"""
GBO -- Hitter insight charts (Oct 2026). Catcher's view throughout, same
strike-zone box + plate as every other zone chart in GBO.
  swing_decision_chart  -- every located pitch colored by decision grade
  attack_location_chart -- where pitchers locate to him, one panel per
                           pitch family
  count_mix_chart       -- 100% stacked bars: pitch family by count
See analytics/hitter_insights.py.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from analytics.hitter_insights import DECISIONS, DECISION_COLORS, FAMILIES, COUNT_BUCKETS
from strike_zone import (ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP,
                         SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP)
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, MUTED_GRAY
from visualizations.hitter_graphic import home_plate_shape

FAMILY_COLORS = {"Fastball": "#3987E5", "Breaking": "#C98500", "Offspeed": "#D55181"}
X_RANGE = (-2.0, 2.0)
Z_RANGE = (0.0, 4.6)


def _zone_shapes(fig, xref="x", yref="y", tiers=True):
    if tiers:
        fig.add_shape(type="rect", x0=-SHADOW_HALF_WIDTH, y0=SHADOW_BOTTOM, x1=SHADOW_HALF_WIDTH, y1=SHADOW_TOP,
                      xref=xref, yref=yref, line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below")
        fig.add_shape(type="rect", x0=-HEART_HALF_WIDTH, y0=HEART_BOTTOM, x1=HEART_HALF_WIDTH, y1=HEART_TOP,
                      xref=xref, yref=yref, line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below")
    fig.add_shape(type="rect", x0=-ZONE_HALF_WIDTH, y0=ZONE_BOTTOM, x1=ZONE_HALF_WIDTH, y1=ZONE_TOP,
                  xref=xref, yref=yref, line=dict(color="#E9ECF1", width=2))
    plate = home_plate_shape(half_width_ft=ZONE_HALF_WIDTH, ground_y=0.35, view="catcher")
    if isinstance(plate, dict):
        fig.add_shape(**dict(plate, xref=xref, yref=yref))


def _axes(fig, row=None, col=None):
    kw = {} if row is None else dict(row=row, col=col)
    fig.update_xaxes(range=list(X_RANGE), visible=False, fixedrange=True, **kw)
    fig.update_yaxes(range=list(Z_RANGE), visible=False, fixedrange=True, scaleratio=1, **kw)


def swing_decision_chart(graded):
    if not graded:
        return None
    fig = go.Figure()
    _zone_shapes(fig)
    for d in DECISIONS:
        pts = [(p, float(p.actual_plate_x), float(p.actual_plate_z)) for p, dd in graded if dd == d]
        if not pts:
            continue
        fig.add_trace(go.Scatter(
            x=[x for _p, x, _z in pts], y=[z for _p, _x, z in pts], mode="markers", name=f"{d} ({len(pts)})",
            marker=dict(color=DECISION_COLORS[d], size=10 if d != "Borderline" else 8,
                        opacity=0.9 if d != "Borderline" else 0.5, line=dict(color="#171B21", width=1)),
            hovertext=[f"{d}<br>{p.pitch_type.type_name if p.pitch_type else ''} · {p.balls_before}-{p.strikes_before}"
                       f"<br>{p.pitch_outcome}" for p, _x, _z in pts],
            hoverinfo="text",
        ))
    fig.update_yaxes(scaleanchor="x")
    _axes(fig)
    apply_gbo_theme(fig, height=520, margin=dict(t=10, b=10, l=10, r=10),
                    legend=dict(orientation="v", x=1.0, xanchor="left", y=0.95, bgcolor="rgba(0,0,0,0)"))
    return fig


def attack_location_chart(by_family_loc):
    fams = [f for f in FAMILIES if by_family_loc.get(f)]
    if not fams:
        return None
    fig = make_subplots(rows=1, cols=len(fams), horizontal_spacing=0.03,
                        subplot_titles=[f"{f} ({len(by_family_loc[f])})" for f in fams])
    for i, f in enumerate(fams, start=1):
        xref = "x" if i == 1 else f"x{i}"
        yref = "y" if i == 1 else f"y{i}"
        pts = by_family_loc[f]
        if len(pts) >= 15:  # a density blob from a handful of pitches is noise
            fig.add_trace(go.Histogram2dContour(
                x=[x for _p, (x, _z) in pts], y=[z for _p, (_x, z) in pts], ncontours=8, showscale=False,
                colorscale=[[0, "rgba(0,0,0,0)"], [0.25, "rgba(57,135,229,0.15)"], [1, FAMILY_COLORS[f]]],
                contours=dict(coloring="fill", showlines=False), hoverinfo="skip",
            ), row=1, col=i)
        fig.add_trace(go.Scatter(
            x=[x for _p, (x, _z) in pts], y=[z for _p, (_x, z) in pts], mode="markers",
            marker=dict(color=FAMILY_COLORS[f], size=6, opacity=0.75, line=dict(color="#171B21", width=0.5)),
            hovertext=[f"{p.pitch_type.type_name if p.pitch_type else f} · {p.balls_before}-{p.strikes_before} · {p.pitch_outcome}"
                       for p, _xy in pts], hoverinfo="text", showlegend=False,
        ), row=1, col=i)
        _zone_shapes(fig, xref, yref, tiers=False)
        _axes(fig, 1, i)
        fig.update_yaxes(scaleanchor=xref, row=1, col=i)
    apply_gbo_theme(fig, height=440, showlegend=False, margin=dict(t=36, b=8, l=8, r=8))
    return fig


def count_mix_chart(mix):
    rows = [m for m in mix if m["Pitches"]]
    if not rows:
        return None
    fig = go.Figure()
    for f in FAMILIES:
        vals = [m.get(f) or 0 for m in rows]
        fig.add_trace(go.Bar(
            orientation="h", y=[f"{m['Count']} ({m['Pitches']})" for m in rows], x=vals, name=f,
            marker=dict(color=FAMILY_COLORS[f], line=dict(color="#171B21", width=2)),
            text=[f"{v:.0f}%" if v >= 8 else "" for v in vals], textposition="inside",
            insidetextanchor="middle", textfont=dict(color="#fff", size=12),
            hovertemplate=f"{f}: %{{x:.0f}}%<extra></extra>",
        ))
    apply_gbo_theme(fig, height=80 + 46 * len(rows), barmode="stack", bargap=0.3,
                    margin=dict(t=10, b=40, l=10, r=10),
                    legend=dict(orientation="h", y=-0.12, x=0, bgcolor="rgba(0,0,0,0)", traceorder="normal"))
    fig.update_xaxes(range=[0, 100], ticksuffix="%", gridcolor=GRID_GRAY, fixedrange=True)
    fig.update_yaxes(autorange="reversed", tickfont=dict(size=13, color="#E9ECF1"), fixedrange=True, automargin=True)
    return fig


def location_grid_figure(grid, title=None):
    """3x3 hitter's-side location grid (Oct 2026): columns In / Middle /
    Away from HIS side of the plate, rows Up / Middle / Down. Cell = share
    of located pitches (and the count)."""
    from analytics.hitter_insights import H_CELLS, V_CELLS
    if not grid or not grid["n"]:
        return None
    z, text = [], []
    for v in V_CELLS:
        z.append([grid["pct"][(v, h)] or 0 for h in H_CELLS])
        text.append([f"<b>{(grid['pct'][(v, h)] or 0):.0f}%</b><br>{grid['counts'][(v, h)]}" for h in H_CELLS])
    fig = go.Figure(go.Heatmap(
        z=z, x=list(H_CELLS), y=list(V_CELLS), text=text, texttemplate="%{text}", textfont=dict(size=14),
        colorscale=[[0, "#1E2530"], [0.35, "#5B6E8F"], [1, "#D64545"]], zmin=0, zmax=max(50, max(max(r) for r in z)),
        showscale=False, xgap=3, ygap=3, hovertemplate="%{y} / %{x}: %{z:.0f}%<extra></extra>",
    ))
    apply_gbo_theme(fig, title=title, height=340, margin=dict(t=40 if title else 10, b=40, l=70, r=10))
    fig.update_xaxes(side="bottom", title=dict(text="← inside      (his side of the plate)      away →",
                                               font=dict(size=11, color=MUTED_GRAY)), fixedrange=True)
    fig.update_yaxes(autorange="reversed", fixedrange=True)
    return fig
