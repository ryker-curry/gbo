"""
GBO -- Trend charts (Oct 2026). See analytics/trends.py.
metrics_figure: small multiples, one per metric -- faint dots per game/week,
a bold rolling line, and flat reference lines for his own average (dotted),
the team (dashed gray) and D2 (dashed gold, where it exists).
velo_stuff_figure: avg velo and Stuff+ per pitch type over time (Rapsodo,
bullpens and games).
"""

import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pitch_type_config import get_pitch_color
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, MUTED_GRAY, GOLD, TEXT_CREAM

LINE = "#E8EDF3"
ROLL = "#D64545"


def _fmt(unit, v):
    if v is None:
        return "—"
    return f"{v:.0f}%" if unit == "%" else f"{v:.0f}"


def _arrow(s, unit, hib):
    if not s:
        return ""
    ch = s["change"]
    if abs(ch) < (1 if unit == "%" else 3):
        return f"  ·  steady since {s['since']}"
    good = (ch > 0) == hib
    sym = "▲" if ch > 0 else "▼"
    col = "#3FB27F" if good else "#D64545"
    amt = f"{abs(ch):.0f}{'%' if unit == '%' else ''}"
    return f"  <span style='color:{col}'>{sym} {amt}</span> <span style='color:{MUTED_GRAY}'>(last {s['n']} vs first {s['n']})</span>"


def metrics_figure(trend):
    keys = list(trend["series"].keys())
    if not trend["groups"] or not keys:
        return None
    cols = 2
    rows = math.ceil(len(keys) / cols)
    titles = []
    for k in keys:
        s = trend["series"][k]
        titles.append(f"<b>{s['label']}</b>{_arrow(s['summary'], s['unit'], s['hib'])}")
    fig = make_subplots(rows=rows, cols=cols, subplot_titles=titles, vertical_spacing=0.14 if rows > 1 else 0.1,
                        horizontal_spacing=0.08)
    xs = [lab for _k, lab in trend["groups"]]
    roll_name = f"Rolling {trend['rolling']}" if trend["by"] == "game" else "Rolling"
    for i, k in enumerate(keys):
        r, c = i // cols + 1, i % cols + 1
        s = trend["series"][k]
        ys = [v for _l, v in s["points"]]
        rs = [v for _l, v in s["rolling"]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", marker=dict(size=7, color="rgba(232,237,243,0.45)"),
                                 name="Each game" if trend["by"] == "game" else "Each week", showlegend=(i == 0),
                                 hovertemplate="%{x}: %{y:.0f}<extra></extra>"), row=r, col=c)
        fig.add_trace(go.Scatter(x=xs, y=rs, mode="lines", line=dict(color=ROLL, width=3), name=roll_name,
                                 showlegend=(i == 0), connectgaps=True,
                                 hovertemplate="%{x}: %{y:.0f} rolling<extra></extra>"), row=r, col=c)
        bench = s.get("bench")
        refs = ((s["mine"], "His average", "dot", LINE), (s["team"], "Team", "dash", MUTED_GRAY),
                (s["d2"], "D2 average", "dash", GOLD),
                (bench[0] if bench else None, bench[1] if bench else "", "dashdot", "#3FB27F"))
        for val, name, dash, color in refs:
            if val is None:
                continue
            first_d2 = name == "D2 average" and not any(trend["series"][kk]["d2"] is not None for kk in keys[:i])
            fig.add_trace(go.Scatter(x=[xs[0], xs[-1]], y=[val, val], mode="lines",
                                     line=dict(color=color, dash=dash, width=1.5), name=name,
                                     showlegend=(name in ("His average", "Team") and i == 0) or first_d2
                                     or (bench is not None and name == bench[1]),
                                     hovertemplate=f"{name}: {_fmt(s['unit'], val)}<extra></extra>"), row=r, col=c)
        fig.update_xaxes(showticklabels=len(xs) <= 14, tickangle=-35, tickfont=dict(size=9), gridcolor=GRID_GRAY,
                         row=r, col=c)
        fig.update_yaxes(gridcolor=GRID_GRAY, ticksuffix="%" if s["unit"] == "%" else "", row=r, col=c)
    apply_gbo_theme(fig, height=260 * rows + 110, margin=dict(t=90, b=60, l=40, r=20),
                    legend=dict(orientation="h", yref="container", y=0.99, yanchor="top", x=0, bgcolor="rgba(0,0,0,0)"))
    fig.update_annotations(font=dict(size=12, color=TEXT_CREAM))
    for i, a in enumerate(fig.layout.annotations):
        ax = fig.layout["xaxis" if i == 0 else f"xaxis{i + 1}"]
        a.update(xanchor="left", x=ax.domain[0])
    return fig


def velo_stuff_figure(vs):
    if not vs:
        return None
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.08,
                        subplot_titles=["<b>Average velo</b> (dot size = pitches; open = bullpen)",
                                        "<b>Stuff+</b> (100 = team average for that pitch)",
                                        "<b>Bauer units</b> (spin / velo -- up = spinning it better, not just throwing harder)"])
    for label, rows in sorted(vs.items(), key=lambda kv: -sum(r["n"] for r in kv[1])):
        col = get_pitch_color(label)
        xs = [r["date"] for r in rows]
        fig.add_trace(go.Scatter(
            x=xs, y=[r["velo"] for r in rows], mode="lines+markers", name=label, legendgroup=label,
            line=dict(color=col, width=2),
            marker=dict(size=[min(14, 5 + r["n"] / 4) for r in rows], color=col,
                        symbol=["circle-open" if r["bullpen"] else "circle" for r in rows]),
            customdata=[[r["n"], r["top"] or 0] for r in rows],
            hovertemplate=f"{label} %{{x|%b %d}}: %{{y:.1f}} mph avg, top %{{customdata[1]:.1f}} (%{{customdata[0]}} pitches)<extra></extra>",
        ), row=1, col=1)
        if any(r["stuff"] is not None for r in rows):
            fig.add_trace(go.Scatter(
                x=xs, y=[r["stuff"] for r in rows], mode="lines+markers", name=label, legendgroup=label,
                showlegend=False, line=dict(color=col, width=2), marker=dict(color=col, size=6), connectgaps=True,
                hovertemplate=f"{label} %{{x|%b %d}}: Stuff+ %{{y:.0f}}<extra></extra>",
            ), row=2, col=1)
        if any(r.get("bu") is not None for r in rows):
            fig.add_trace(go.Scatter(
                x=xs, y=[r.get("bu") for r in rows], mode="lines+markers", name=label, legendgroup=label,
                showlegend=False, line=dict(color=col, width=2), marker=dict(color=col, size=6), connectgaps=True,
                hovertemplate=f"{label} %{{x|%b %d}}: %{{y:.1f}} Bauer units<extra></extra>",
            ), row=3, col=1)
    fig.add_hline(y=100, line=dict(color=MUTED_GRAY, dash="dash", width=1), row=2, col=1)
    apply_gbo_theme(fig, height=760, margin=dict(t=40, b=40, l=50, r=20),
                    legend=dict(orientation="h", y=-0.08, x=0, bgcolor="rgba(0,0,0,0)"))
    fig.update_yaxes(gridcolor=GRID_GRAY)
    fig.update_xaxes(gridcolor=GRID_GRAY)
    fig.update_yaxes(ticksuffix=" mph", row=1, col=1)
    fig.update_annotations(font=dict(size=12, color=TEXT_CREAM), x=0, xanchor="left")
    return fig
