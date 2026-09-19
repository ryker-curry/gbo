"""
GBO -- Pitch Results chart (Sept 2026, Pitcher Profile "Results" tab).

Ryker's reference is mlbpitchprofiler.com's own Results tab: per pitch
type, one stacked "quality of contact" bar (the outcome categories sum
to 100% of that type's balls in play) sitting next to three standalone
rate bars (Hard Hit %/Whiff %/Chase %, each its own percentage against
its own denominator -- NOT part of the contact-quality stack). Built
entirely from game_stats.compute_pitch_type_breakdown()'s rows, which
Sept 2026 already grew the "Weak %"/"Jammed %"/"Off the End %"/
"Clipped %"/"Solid Contact %"/"Barreled %"/"Hard Hit %" columns
specifically for this chart (GBO's own contact_quality vocabulary,
not Statcast's Topped/Under/Flare-Burner -- same six-bucket idea,
GBO's own labels).

Mixing a stacked group and several independently-positioned bars in
one Plotly figure needs a multi-category x-axis: every trace's x is a
list of (pitch type, sub-group) tuples. The 6 contact-quality traces
all use sub-group "Quality" for a given pitch type (so Plotly stacks
them there), while Hard Hit/Whiff/Chase each use their OWN sub-group
name ("Hard Hit"/"Whiff"/"Chase") so they land at their own slot next
to the stack instead of stacking into it -- Plotly's own multicategory
grouping does the rest (no subplot trickery needed).

Skips the "Total" row compute_pitch_type_breakdown always appends
(this is a per-pitch-type comparison chart, a "Total" bar isn't a real
pitch). A pitch type still shows here with zero balls in play as long
as it has any swings -- a whiff-only pitch type has nothing for the
contact-quality stack (those segments render as 0-height/blank, same
as any other None value here) but its Whiff bar is real and shouldn't
disappear just because nothing was ever put in play (Ryker, Sept 2026:
"it should show whiffs based on swing and miss. Don't need to click
swing and miss for contact quality because there was no contact").
"""

import plotly.graph_objects as go

from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, TEXT_CREAM
from pitch_type_config import get_pitch_color

# GBO's own six contact_quality buckets allowed on a ball in play,
# worst-for-the-pitcher-to-best-for-the-pitcher order (bottom of the
# stack up) -- matches hitter_tracking.CONTACT_QUALITY_SCORE's implied
# ordering (Weak/Jammed/Off the End/Clipped all score 1, Solid scores
# 2, Barreled/Squared Up scores 3), so the stack reads worst-contact-
# first the same way a reader would expect "weakest at the bottom."
_QUALITY_SEGMENTS = [
    ("Weak %", "Weak", "#4C5B6B"),
    ("Jammed %", "Jammed", "#6E7C8C"),
    ("Off the End %", "Off the End", "#8FA0B3"),
    ("Clipped %", "Clipped", "#C9A227"),
    ("Solid Contact %", "Solid", "#3E8E7E"),
    ("Barreled %", "Barreled/Squared Up", "#C8102E"),
]

_RATE_BARS = [
    ("Hard Hit %", "Hard Hit", "#C8102E"),
    ("Whiff %", "Whiff", "#2E86AB"),
    ("Chase %", "Chase", "#F2B529"),
]


def pitch_results_chart(rows):
    """rows: compute_pitch_type_breakdown()'s per-pitch-type list
    (Total row included is fine -- filtered out here). Returns a
    plotly Figure, or None if no pitch type here has any balls in
    play OR any swings yet (nothing meaningful to chart)."""
    type_rows = [
        r for r in rows
        if r.get("Pitch Type") != "Total" and ((r.get("Balls in Play") or 0) > 0 or (r.get("Total Swings") or 0) > 0)
    ]
    if not type_rows:
        return None

    fig = go.Figure()

    for col, seg_label, color in _QUALITY_SEGMENTS:
        fig.add_trace(go.Bar(
            x=[[r["Pitch Type"] for r in type_rows], ["Quality"] * len(type_rows)],
            y=[r.get(col) or 0 for r in type_rows],
            name=seg_label,
            marker_color=color,
            text=[f"{r[col]:.1f}" if r.get(col) is not None else "" for r in type_rows],
            textposition="inside",
            textfont=dict(size=10, color="#fff"),
            hovertemplate="%{x}: " + seg_label + " %{y:.1f}%<extra></extra>",
            offsetgroup="quality",
        ))

    for col, seg_label, color in _RATE_BARS:
        fig.add_trace(go.Bar(
            x=[[r["Pitch Type"] for r in type_rows], [seg_label] * len(type_rows)],
            y=[r.get(col) or 0 for r in type_rows],
            name=seg_label,
            marker_color=color,
            text=[f"{r[col]:.1f}" if r.get(col) is not None else "" for r in type_rows],
            textposition="outside",
            textfont=dict(size=10, color=TEXT_CREAM),
            hovertemplate="%{x}: " + seg_label + " %{y:.1f}%<extra></extra>",
            offsetgroup=seg_label,
            showlegend=False,
        ))

    fig.update_layout(barmode="stack")
    return apply_gbo_theme(
        fig, title="Pitch Results", height=440, y_title="%",
        yaxis=dict(range=[0, 108], gridcolor=GRID_GRAY, zerolinecolor=GRID_GRAY),
    )
