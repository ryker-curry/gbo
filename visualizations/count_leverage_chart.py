"""
GBO -- Count Leverage chart (Sept 2026, Pitcher Profile "Count Leverage"
view).

A "count tree" of pie charts -- 0-0 alone at the top, then every count
reachable by that many total pitches into the at-bat (balls+strikes
together) on its own row below, narrowing back down to 3-2 alone at
the bottom (row sizes 1/2/3/3/2/1 -- the standard shape, same one
Ryker asked for: "I want the pie charts to be in like a tree ...
similar to how other people have done it"). Left-to-right within a row
is strikes descending / balls ascending, so the pitcher-favorable side
of the tree (more strikes) is always on the left and the
hitter-favorable side (more balls) is always on the right -- matches
the row orderings Ryker gave directly ("0-2, 1-1, 2-0" / "1-2, 2-1,
3-0"). Each pie shows that count's own pitch-type mix. Reference is
Lance Brozdowski's "count leverage" framing (pitch selection should
shift with the count -- e.g. cutting a cutter's two-strike usage once
it's shown to get barreled there, leaning on a changeup instead once
the pitcher actually has leverage) and the Marlins' own dugout
pitch-calling system, which draws a similar line: best stuff
middle-middle in non-two-strike counts, maximum breaking-ball usage
once there are two strikes, hunting the whiff. Built entirely from
game_stats.compute_pitch_mix_by_count()'s rows.

Every pie shares the SAME fixed label order (every pitch type this
pitcher threw anywhere in the filtered window, most-used overall
first) and the same color mapping (pitch_type_config.get_pitch_color),
padded with 0-count slices for a type he didn't throw in that specific
count -- a 0-value slice draws no arc and doesn't show up in hover, so
this costs nothing visually, but it means all 12 pies can share ONE
legend (only the very first pie's showlegend=True) instead of each
subplot growing its own legend with whatever subset of types happened
to show up there.

Sept 2026, Ryker's follow-up ("is there a way we can see if what he
throws the majority of the time in those counts is successful?"): each
slice's hover also shows that (count, pitch type) combo's own RV/100
(game_stats.compute_pitch_mix_by_count's own column) -- run value, the
same ground-truth currency Location+/Pitching+/Command+ and the
Results tab already use, and what the FanGraphs primer this page's
whole grading system is adapted from treats as the standard measure of
pitch success, by count specifically. Passed through Plotly's
`customdata` -- NOT `{customdata}` in the hovertemplate string, which
prints the literal placeholder text instead of substituting (see
pitcher_game_report.py's own _attack_zones_figure for the same mistake
made and fixed once already this project -- %{customdata} is the
correct Plotly template syntax).
"""

from plotly.subplots import make_subplots
import plotly.graph_objects as go

from visualizations.chart_theme import apply_gbo_theme, MUTED_GRAY
from pitch_type_config import get_pitch_color

# The count-tree shape: row 0 is 0-0 alone, each row below is every
# (balls, strikes) reachable by that many total pitches into the count
# (a count can't reach 4 balls or 3 strikes and still be a "before"
# count -- that PA already ended), narrowing back to 3-2 alone at the
# bottom. Left-to-right within a row is strikes descending / balls
# ascending -- see module docstring.
TREE_ROWS = [
    [(0, 0)],
    [(0, 1), (1, 0)],
    [(0, 2), (1, 1), (2, 0)],
    [(1, 2), (2, 1), (3, 0)],
    [(2, 2), (3, 1)],
    [(3, 2)],
]

# 6 columns divides evenly by every row width this tree actually has
# (1, 2, 3), so every row's pies come out centered and evenly sized
# via colspan -- a lone pie spans all 6, a row of 2 spans 3 each, a
# row of 3 spans 2 each -- rather than hand-tuned fractional domains.
_GRID_COLS = 6


def _fmt_rv100(value):
    return f"{value:+.2f}" if value is not None else "n/a"


def count_leverage_chart(counts_by_state):
    """counts_by_state: game_stats.compute_pitch_mix_by_count()'s return
    value (a dict keyed by every (balls, strikes) TREE_ROWS/COUNT_STATES
    cover, always all 12 present). Returns a plotly Figure, or None if
    the pitcher had zero pitches across every count in this window."""
    all_states = [c for row in TREE_ROWS for c in row]
    if not any(counts_by_state[c]["Total"] for c in all_states):
        return None

    # Every pitch type thrown anywhere in this window, most-used overall
    # first -- the fixed label/color order every pie shares.
    overall_counts = {}
    for c in all_states:
        for t in counts_by_state[c]["Types"]:
            overall_counts[t["Pitch Type"]] = overall_counts.get(t["Pitch Type"], 0) + t["N"]
    label_order = sorted(overall_counts, key=lambda label: -overall_counts[label])
    colors = [get_pitch_color(label) for label in label_order]

    specs = []
    subplot_titles = []
    for row_states in TREE_ROWS:
        span = _GRID_COLS // len(row_states)
        row_spec = [None] * _GRID_COLS
        for i, c in enumerate(row_states):
            row_spec[i * span] = {"type": "domain", "colspan": span}
            subplot_titles.append(f"{c[0]}-{c[1]} ({counts_by_state[c]['Total']})")
        specs.append(row_spec)

    fig = make_subplots(
        rows=len(TREE_ROWS), cols=_GRID_COLS, specs=specs, subplot_titles=subplot_titles,
        horizontal_spacing=0.02, vertical_spacing=0.08,
    )

    is_first_pie = True
    for row_idx, row_states in enumerate(TREE_ROWS):
        span = _GRID_COLS // len(row_states)
        for i, c in enumerate(row_states):
            bucket = counts_by_state[c]
            by_label = {t["Pitch Type"]: t for t in bucket["Types"]}
            values = [by_label[label]["N"] if label in by_label else 0 for label in label_order]
            rv100_text = [_fmt_rv100(by_label[label]["RV/100"]) if label in by_label else "n/a" for label in label_order]
            fig.add_trace(
                go.Pie(
                    labels=label_order, values=values, marker=dict(colors=colors, line=dict(color="#1E1E1E", width=1)),
                    textinfo="percent", textposition="inside", insidetextorientation="radial",
                    textfont=dict(size=10, color="#fff"),
                    customdata=rv100_text,
                    hovertemplate="%{label}<br>%{value} pitch(es) (%{percent})<br>RV/100: %{customdata}<extra></extra>",
                    hole=0.25,
                    showlegend=is_first_pie,
                    sort=False,
                ),
                row=row_idx + 1, col=i * span + 1,
            )
            is_first_pie = False

    for annotation in fig.layout.annotations:
        annotation.font = dict(size=11, color=MUTED_GRAY)

    return apply_gbo_theme(
        fig, title="Count Leverage", height=920,
        legend=dict(orientation="h", yanchor="top", y=-0.02, xanchor="left", x=0),
        margin=dict(t=60, b=20, l=10, r=10),
    )
