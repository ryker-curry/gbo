"""
GBO — Shared Plotly chart theming.

One place for the dark-theme styling every bullpen chart uses, per the
spec's "Use reusable GBO chart styling so future analytics pages
maintain the same visual identity" instruction (Section 24). This isn't
a new palette -- still Pittsburg State's crimson/gold -- just laid out
to sit inside the Bullpen Dashboard's Paradigm-inspired card panels (see
bullpen_dashboard_style.py) instead of drawing its own separate boxed
background: plot/paper backgrounds are transparent so a chart blends
into whatever card sits behind it, rather than stacking a second dark
rectangle inside the card's dark rectangle.

Do not hardcode plot_bgcolor/paper_bgcolor/font colors directly in a
chart function -- call apply_gbo_theme() on the figure instead.
"""

# Palette. BG_DARK is still used where a chart genuinely needs a filled
# background rather than a transparent one (e.g. spin_axis_chart.py's
# polar plot area) -- kept close to bullpen_dashboard_style.py's card
# color (#161010) so it reads as part of the same card, not a mismatched
# box.
BG_DARK = "#161010"
TEXT_CREAM = "#FFFDE5"
GRID_GRAY = "#3A2E2E"
GOLD = "#D4AF37"
CRIMSON = "#BF1E2D"
MUTED_GRAY = "#8A7A7A"


def apply_gbo_theme(fig, *, title=None, height=420, x_title=None, y_title=None, **layout_kwargs):
    """Applies the standard GBO dark chart theme in place and returns the
    figure (so calls can chain: `return apply_gbo_theme(fig, ...)`).

    plot_bgcolor/paper_bgcolor are transparent by default (see module
    docstring) -- pass either explicitly via layout_kwargs if a specific
    chart needs a filled background instead.

    Any Plotly layout keyword can be passed through via layout_kwargs for
    chart-specific needs (e.g. a second y-axis, a polar layout) --
    those are applied last, after the shared defaults, so a chart can
    override anything it genuinely needs to.
    """
    base_layout = dict(
        title=title,
        height=height,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TEXT_CREAM),
        margin=dict(t=50 if title else 20, b=40, l=50, r=30),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    if x_title is not None:
        base_layout["xaxis"] = dict(title=x_title, gridcolor=GRID_GRAY, zerolinecolor=GRID_GRAY)
    if y_title is not None:
        base_layout["yaxis"] = dict(title=y_title, gridcolor=GRID_GRAY, zerolinecolor=GRID_GRAY)

    fig.update_layout(**base_layout)
    if layout_kwargs:
        fig.update_layout(**layout_kwargs)
    return fig
