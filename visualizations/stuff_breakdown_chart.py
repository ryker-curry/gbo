"""
GBO -- Stuff+ Breakdown charts (Oct 2026, Kyle Bland-style, v2 layout
after Ryker's "graphs need to look better" pass):
  * trait_impact_figure -- diverging bars: Stuff+ points each trait adds
                           (green) or costs (red) vs the team's average
                           pitch of the SAME type
  * strip_figure        -- one compact strip per trait: every team pitch
                           of that type (grey) vs his (pitch color)
  * outcome_figure      -- runs saved per 100 by outcome vs the team on
                           the same pitch type, same diverging style
Titles live in the page (HTML), not in the figures, so the plotly
toolbar never sits on top of them. See analytics/stuff_breakdown.py.
"""

import random

import plotly.graph_objects as go

from pitch_type_config import get_pitch_color
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, MUTED_GRAY

UP = "#3FB27F"
DOWN = "#D64545"
NEUTRAL = "rgba(122,133,148,0.55)"
MAX_TRAITS = 6          # the rest fold into "Other traits"


def ordinal(n):
    if n is None:
        return "—"
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def fmt_value(f, v=None):
    v = f["value"] if v is None else v
    if v is None:
        return "—"
    sep = "" if f["unit"] in ("%", "°") else " "
    return f"{v:.{f['decimals']}f}{sep}{f['unit']}"


def _diverging(labels, values, hovers, height, x_title, faded=False, digits=1):
    colors = [NEUTRAL if faded else (UP if v >= 0 else DOWN) for v in values]
    fig = go.Figure(go.Bar(
        orientation="h", y=labels, x=values, marker=dict(color=colors, line=dict(width=0)),
        width=0.62, text=[(f"{v:+.{digits}f}" if abs(v) >= 0.5 * 10 ** -digits else "") for v in values], textposition="outside",
        textfont=dict(color=TEXT_CREAM, size=12), cliponaxis=False,
        hovertext=hovers, hoverinfo="text",
    ))
    m = max([abs(v) for v in values] + [1.0 if digits == 1 else 0.3]) * 1.35
    apply_gbo_theme(fig, height=height, showlegend=False, bargap=0.35,
                    margin=dict(t=8, b=44, l=8, r=24))
    fig.update_xaxes(range=[-m, m], zeroline=True, zerolinecolor=TEXT_CREAM, zerolinewidth=1.5,
                     gridcolor=GRID_GRAY, title=dict(text=x_title, font=dict(size=11, color=MUTED_GRAY)),
                     tickfont=dict(size=11), fixedrange=True)
    fig.update_yaxes(autorange="reversed", automargin=True, tickfont=dict(size=13, color="#E9ECF1"),
                     showgrid=False, fixedrange=True)
    return fig


def trait_impact_figure(entry):
    feats = entry["features"]
    if not feats:
        return None
    shown = feats[:MAX_TRAITS]
    rest = feats[MAX_TRAITS:]
    labels = [f["label"] for f in shown]
    values = [f["contrib"] for f in shown]
    hovers = [f"<b>{f['label']}</b><br>His avg: {fmt_value(f)} ({ordinal(f['pct'])} pct)"
              f"<br>Team avg: {fmt_value(f, f['team_avg'])}<br>Stuff+ points: {f['contrib']:+.1f}" for f in shown]
    if rest and abs(sum(f["contrib"] for f in rest)) >= 0.05:
        labels.append("Other traits")
        values.append(sum(f["contrib"] for f in rest))
        hovers.append("<br>".join(f"{f['label']}: {f['contrib']:+.1f}" for f in rest))
    return _diverging(labels, values, hovers, height=70 + 44 * len(labels),
                      x_title="Stuff+ points vs team average (100)")


def strip_figure(entry, feature_name, seed=7):
    f = next((x for x in entry["features"] if x["name"] == feature_name), None)
    team = entry["team_values"].get(feature_name) or []
    if f is None or not team:
        return None
    his = entry["his_values"].get(feature_name, [])
    rng = random.Random(seed)
    color = get_pitch_color(entry["label"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=team, y=[rng.uniform(-0.3, 0.3) for _ in team], mode="markers", name="Team",
        marker=dict(color="rgba(174,182,194,0.22)", size=6), hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=his, y=[rng.uniform(-0.3, 0.3) for _ in his], mode="markers", name="His",
        marker=dict(color=color, size=8, opacity=0.9, line=dict(color="#171B21", width=1)),
        hovertemplate=f"%{{x:.{f['decimals']}f}} {f['unit']}<extra>his pitch</extra>",
    ))
    fig.add_vline(x=f["team_avg"], line=dict(color=MUTED_GRAY, dash="dot", width=1.5))
    fig.add_annotation(x=f["team_avg"], y=0.62, text="team avg", showarrow=False, xshift=4,
                       font=dict(size=10, color=MUTED_GRAY), yanchor="bottom", xanchor="left")
    if f["value"] is not None:
        fig.add_vline(x=f["value"], line=dict(color=color, width=3))
        fig.add_annotation(x=f["value"], y=-0.62, text="his avg", showarrow=False, xshift=4,
                           font=dict(size=10, color=color), yanchor="top", xanchor="left")
    apply_gbo_theme(fig, height=170, showlegend=False, margin=dict(t=6, b=30, l=10, r=10))
    fig.update_yaxes(visible=False, range=[-0.95, 0.95], fixedrange=True)
    fig.update_xaxes(gridcolor=GRID_GRAY, tickfont=dict(size=11), fixedrange=True,
                     ticksuffix=("" if f["unit"] in ("%", "°") else " ") + f["unit"])
    return fig


def outcome_figure(label, o):
    if not o:
        return None
    rows = o["rows"]
    hovers = [f"<b>{r['bucket']}</b><br>His: {r['his_freq']:.0f}% of pitches · {r['his']:+.2f} runs/100"
              f"<br>Team: {r['team_freq']:.0f}% of pitches · {r['team']:+.2f} runs/100" for r in rows]
    return _diverging([r["bucket"] for r in rows], [r["gap"] for r in rows], hovers,
                      height=70 + 44 * len(rows), x_title="Runs saved per 100 pitches vs team (+ = better)",
                      faded=not o["enough"], digits=2)
