"""
GBO -- Shared "render a Plotly Figure as a static PNG <img>" helper.

Extracted from bucket_display.py's original private `_fig_to_img` (see
that module's docstring for the full rationale: every chart this app
renders is decorative/hover-only, no on_select/click handling anywhere,
so a static image loses no real interactivity and sidesteps the
"variable, data-dependent number of charts" problem a fixed set of
shinywidgets render_plotly outputs would have -- callers here mirror the
same use case, e.g. player_hitting.py's zone heatmap and
bullpen_dashboard_display.py's whole chart section, both a data-dependent
number of charts inside a single ui.div tree.

Public (unlike bucket_display._fig_to_img, which stays private/internal
to that module) so any module can `import chart_helpers` instead of
reaching into bucket_display's private function or duplicating the
kaleido/base64 logic a third time.
"""

import base64


def fig_to_img(fig, width=None, height=None, scale=1):
    """Render a plotly Figure to a static PNG and wrap it in an <img> tag.

    scale defaults to 1 (standard resolution) rather than 2 (double/
    retina resolution) -- each Plotly-to-PNG export goes through
    kaleido, which has real per-image CPU cost, and that cost scales
    with pixel count (scale=2 renders 4x the pixels of scale=1). On
    Posit Connect Cloud's shared, limited CPU, a page rendering several
    charts at once at scale=2 was slow enough to occasionally trip the
    browser's websocket timeout ("Disconnected from the server") --
    most visible on Bullpen Dashboard, which renders up to 6 charts per
    section. Pass scale=2 explicitly for a specific chart if a caller
    ever needs retina-sharp output badly enough to accept the extra
    render time."""
    from shiny import ui

    png_bytes = fig.to_image(format="png", width=width, height=height, scale=scale)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return ui.tags.img(src=f"data:image/png;base64,{b64}", style="max-width:100%; height:auto; display:block; margin:0 auto;")