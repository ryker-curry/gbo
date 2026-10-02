"""
GBO -- Arsenal Plan charts (Oct 2026). See analytics/arsenal_plan.py.

plan_movement_figure: pitcher's view movement map -- arm side always to
the right, IVB up. Each pitch: filled dot = current shape (median),
hollow ring = target, arrow current -> target; hollow diamond = a pitch
to ADD at its target shape.

progress_figure: inches from target by session for each pitch with a
target -- is the shape moving toward it?
"""

import plotly.graph_objects as go

from pitch_type_config import get_pitch_color
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM

EXTENT = 26


def plan_movement_figure(plan):
    fig = go.Figure()
    fig.add_hline(y=0, line=dict(color=GRID_GRAY, width=1.5))
    fig.add_vline(x=0, line=dict(color=GRID_GRAY, width=1.5))
    for r in plan["rows"]:
        c = get_pitch_color(r["label"])
        cur = r["cur"]
        fig.add_trace(go.Scatter(
            x=[cur["run"]], y=[cur["ivb"]], mode="markers+text", text=[r["label"]], textposition="top center",
            textfont=dict(color=TEXT_CREAM, size=10), name=f"{r['label']} (now)", showlegend=False,
            marker=dict(color=c, size=14, line=dict(width=1, color="#111")),
            hovertemplate=(f"{r['label']} now<br>{cur['ivb']:.1f}\" ride, {cur['run']:.1f}\" arm-side run"
                           + (f"<br>{cur['velo']:.1f} mph" if cur.get("velo") else "") + "<extra></extra>"),
        ))
        t = r.get("target")
        if t:
            fig.add_trace(go.Scatter(
                x=[t["run"]], y=[t["ivb"]], mode="markers", showlegend=False,
                marker=dict(color="rgba(0,0,0,0)", size=16, line=dict(width=2.5, color=c)),
                hovertemplate=(f"{r['label']} target ({'coach' if r.get('source') == 'coach' else 'rule'})"
                               f"<br>{t['ivb']:.1f}\" ride, {t['run']:.1f}\" run"
                               + (f"<br>{t['velo']:.1f} mph" if t.get("velo") else "") + "<extra></extra>"),
            ))
            if r["status"] == "tune":
                fig.add_annotation(x=t["run"], y=t["ivb"], ax=cur["run"], ay=cur["ivb"], xref="x", yref="y",
                                   axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.2,
                                   arrowwidth=1.8, arrowcolor=c, opacity=0.9, text="")
    for a in plan["adds"]:
        c = get_pitch_color(a["label"])
        t = a["target"]
        fig.add_trace(go.Scatter(
            x=[t["run"]], y=[t["ivb"]], mode="markers+text", text=[f"+ {a['label']}"], textposition="bottom center",
            textfont=dict(color=c, size=10), showlegend=False,
            marker=dict(symbol="diamond-open", color=c, size=16, line=dict(width=2.5, color=c)),
            hovertemplate=(f"ADD {a['label']} ({'core' if a['core'] else 'option'})<br>{t['ivb']:.1f}\" ride, "
                           f"{t['run']:.1f}\" run" + (f"<br>{t['velo']:.1f} mph" if t.get("velo") else "")
                           + "<extra></extra>"),
        ))
    fig.add_annotation(x=-EXTENT + 2, y=-EXTENT + 1.5, text="← glove side", showarrow=False, font=dict(color=TEXT_CREAM, size=10), xanchor="left")
    fig.add_annotation(x=EXTENT - 2, y=-EXTENT + 1.5, text="arm side →", showarrow=False, font=dict(color=TEXT_CREAM, size=10), xanchor="right")
    return apply_gbo_theme(
        fig, title="Arsenal plan -- pitcher's view (● now, ○ target, ◇ add)", height=520,
        x_title="Horizontal break, + = arm side (in)", y_title="Induced vertical break (in)",
        xaxis=dict(range=[-EXTENT, EXTENT], gridcolor=GRID_GRAY, zeroline=False, dtick=5, constrain="domain"),
        yaxis=dict(range=[-EXTENT, EXTENT], gridcolor=GRID_GRAY, zeroline=False, dtick=5, scaleanchor="x", scaleratio=1, constrain="domain"),
    )


def progress_figure(prog):
    if not prog:
        return None
    fig = go.Figure()
    for label, series in prog.items():
        fig.add_trace(go.Scatter(
            x=[d for d, _dist, _n in series], y=[dist for _d, dist, _n in series], mode="lines+markers", name=label,
            line=dict(color=get_pitch_color(label), width=2.5), marker=dict(size=8),
            customdata=[[n] for _d, _dist, n in series],
            hovertemplate=f"{label}<br>%{{x|%b %d}}: %{{y:.1f}}\" from target (%{{customdata[0]}} pitches)<extra></extra>",
        ))
    fig.add_hrect(y0=0, y1=3, fillcolor="rgba(30,138,76,0.15)", line_width=0)
    return apply_gbo_theme(fig, title="Distance from target shape by session (green band = keep range)", height=330,
                           x_title="Session", y_title="Inches from target", yaxis=dict(rangemode="tozero", gridcolor=GRID_GRAY))
