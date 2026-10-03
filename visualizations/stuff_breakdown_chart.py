"""
GBO -- Stuff+ Breakdown charts (Oct 2026). Kyle Bland-style:
  * waterfall_figure   -- how each trait pushes this pitch's Stuff+ up or
                          down from the team average (100)
  * percentile_figure  -- where his pitches sit vs every team pitch of
                          the same type on the traits that matter most
  * outcome_figure     -- runs saved per 100 by outcome vs the team
See analytics/stuff_breakdown.py for the math.
"""

import random

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pitch_type_config import get_pitch_color
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM, MUTED_GRAY

UP = "#3FB27F"
DOWN = "#D64545"


def _ordinal(n):
    if n is None:
        return ""
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _val(f):
    if f["value"] is None:
        return "—"
    return f"{f['value']:.{f['decimals']}f}{'' if f['unit'] in ('%', '°') else ' '}{f['unit']}"


def waterfall_figure(entry):
    feats = [f for f in entry["features"]]
    if not feats:
        return None
    # biggest movers at the top -> plotly draws h-waterfall top-down when
    # the y axis is reversed
    labels = [f"{f['label']}  <span style='color:{MUTED_GRAY}'>{_val(f)} · {_ordinal(f['pct'])} pct</span>" for f in feats]
    fig = go.Figure(go.Waterfall(
        orientation="h",
        measure=["absolute"] + ["relative"] * len(feats) + ["total"],
        y=["Team average"] + labels + [f"<b>{entry['label']} Stuff+</b>"],
        x=[entry["base"]] + [f["contrib"] for f in feats] + [0],
        text=[f"{entry['base']:.0f}"] + [(f"{f['contrib']:+.1f}" if abs(f["contrib"]) >= 0.05 else "") for f in feats] + [f"{entry['stuff_plus']:.0f}"],
        textposition="outside",
        increasing=dict(marker=dict(color=UP)),
        decreasing=dict(marker=dict(color=DOWN)),
        totals=dict(marker=dict(color=get_pitch_color(entry["label"]))),
        connector=dict(line=dict(color=GRID_GRAY, width=1)),
        hovertemplate="%{y}<br>%{text}<extra></extra>",
    ))
    lo = min([entry["base"], entry["stuff_plus"]] + [entry["base"] + sum(f["contrib"] for f in feats[:i + 1]) for i in range(len(feats))])
    hi = max([entry["base"], entry["stuff_plus"]] + [entry["base"] + sum(f["contrib"] for f in feats[:i + 1]) for i in range(len(feats))])
    pad = max(6.0, (hi - lo) * 0.25)
    apply_gbo_theme(
        fig, title=f"Why his {entry['label'].lower()} grades {entry['stuff_plus']:.0f} (n={entry['n']})",
        height=90 + 34 * (len(feats) + 2), x_title="Stuff+",
        yaxis=dict(autorange="reversed", gridcolor="rgba(0,0,0,0)"),
        margin=dict(t=50, b=40, l=10, r=30), showlegend=False,
    )
    fig.update_xaxes(range=[lo - pad, hi + pad], gridcolor=GRID_GRAY)
    fig.update_yaxes(automargin=True)
    return fig


def percentile_figure(entry, top=3, seed=7):
    feats = [f for f in entry["features"] if entry["team_values"].get(f["name"])][:top]
    if not feats:
        return None
    rng = random.Random(seed)
    color = get_pitch_color(entry["label"])
    fig = make_subplots(rows=len(feats), cols=1, vertical_spacing=0.22 if len(feats) > 1 else 0.1,
                        subplot_titles=[f"{f['label']} — {_ordinal(f['pct'])} percentile on the team"
                                        if f["pct"] is not None else f["label"] for f in feats])
    for i, f in enumerate(feats, start=1):
        team = entry["team_values"][f["name"]]
        his = entry["his_values"].get(f["name"], [])
        fig.add_trace(go.Scatter(
            x=team, y=[rng.uniform(-0.35, 0.35) for _ in team], mode="markers",
            marker=dict(color="rgba(174,182,194,0.28)", size=6), name="Team pitches",
            showlegend=(i == 1), hovertemplate=f"Team: %{{x:.{f['decimals']}f}} {f['unit']}<extra></extra>",
        ), row=i, col=1)
        fig.add_trace(go.Scatter(
            x=his, y=[rng.uniform(-0.35, 0.35) for _ in his], mode="markers",
            marker=dict(color=color, size=8, line=dict(color="#111", width=0.5)), name="His pitches",
            showlegend=(i == 1), hovertemplate=f"His: %{{x:.{f['decimals']}f}} {f['unit']}<extra></extra>",
        ), row=i, col=1)
        fig.add_vline(x=f["team_avg"], line=dict(color=MUTED_GRAY, dash="dash", width=1), row=i, col=1)
        if f["value"] is not None:
            fig.add_vline(x=f["value"], line=dict(color=color, width=3), row=i, col=1)
        fig.update_yaxes(visible=False, range=[-0.6, 0.6], row=i, col=1)
        fig.update_xaxes(title_text=f["unit"], gridcolor=GRID_GRAY, row=i, col=1)
    apply_gbo_theme(fig, height=130 + 150 * len(feats), margin=dict(t=40, b=40, l=20, r=20))
    fig.update_annotations(font=dict(size=12, color=TEXT_CREAM), x=0, xanchor="left")
    return fig


def outcome_figure(label, o):
    if not o:
        return None
    rows = o["rows"]
    faded = not o["enough"]
    colors = [(UP if r["gap"] >= 0 else DOWN) for r in rows]
    if faded:
        colors = ["rgba(122,133,148,0.6)"] * len(rows)
    fig = go.Figure(go.Bar(
        orientation="h", y=[r["bucket"] for r in rows], x=[r["gap"] for r in rows],
        marker=dict(color=colors),
        text=[f"{r['gap']:+.2f}" for r in rows], textposition="outside",
        customdata=[[r["his_freq"], r["team_freq"], r["his"], r["team"]] for r in rows],
        hovertemplate=("%{y}<br>His: %{customdata[0]:.0f}% of pitches, %{customdata[2]:+.2f} runs/100"
                       "<br>Team: %{customdata[1]:.0f}% of pitches, %{customdata[3]:+.2f} runs/100<extra></extra>"),
    ))
    m = max([abs(r["gap"]) for r in rows] + [0.5]) * 1.4
    title = f"{label}: runs saved per 100 vs team, by outcome (n={o['n']})"
    if faded:
        title += " — small sample"
    apply_gbo_theme(fig, title=title, height=300, x_title="Runs saved per 100 pitches vs team (+ = better)",
                    yaxis=dict(autorange="reversed"), showlegend=False)
    fig.update_xaxes(range=[-m, m], zeroline=True, zerolinecolor=TEXT_CREAM, gridcolor=GRID_GRAY)
    return fig
