"""
GBO — Shared Plotly chart theming.

One place for the dark-theme styling every bullpen chart uses, per the
spec's "Use reusable GBO chart styling so future analytics pages
maintain the same visual identity" instruction (Section 24). Matches
the color palette already established in ui_components.py and the
existing bullpen charts in pages/bullpen_tracking.py -- this isn't a
new look, just the existing one centralized so it stops being retyped
into every chart function.

Do not hardcode plot_bgcolor/paper_bgcolor/font colors directly in a
chart function -- call apply_gbo_theme() on the figure instead.
"""

# Palette -- matches ui_components.py / strike_zone.py.
BG_DARK = "#1E1E1E"
TEXT_CREAM = "#FFFDE5"
GRID_GRAY = "#3A3A3A"
GOLD = "#D4AF37"
CRIMSON = "#BF1E2D"
MUTED_GRAY = "#6B6B6B"


def apply_gbo_theme(fig, *, title=None, height=420, x_title=None, y_title=None, **layout_kwargs):
    """Applies the standard GBO dark chart theme in place and returns the
    figure (so calls can chain: `return apply_gbo_theme(fig, ...)`).

    Any Plotly layout keyword can be passed through via layout_kwargs for
    chart-specific needs (e.g. a second y-axis, a polar layout) --
    those are applied last, after the shared defaults, so a chart can
    override anything it genuinely needs to.
    """
    base_layout = dict(
        title=title,
        height=height,
        plot_bgcolor=BG_DARK,
        paper_bgcolor=BG_DARK,
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
