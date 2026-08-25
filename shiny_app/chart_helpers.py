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


def render_chart_async(cache, key, builder, label="Loading chart…"):
    """Render a chart's UI (via `builder`, a zero-arg callable) so a
    spinner + placeholder shows first, before the actual (still
    synchronous) render happens.

    `label` customizes the placeholder text for callers building
    something other than a literal chart (e.g. bullpen_dashboard_
    display.py's session header/KPI section, which also goes through
    this same two-tick pattern to avoid a blank gap while its own
    pitch-list query runs) -- defaults to "Loading chart…" for the
    common case.

    This deliberately does NOT use a background thread. An earlier
    version offloaded `builder()` to a ThreadPoolExecutor so the main
    reactive thread stayed free to flush a "Loading..." message while
    the chart rendered in the background -- but that means kaleido's
    `fig.to_image()` (which the builders here call) would be invoked
    off the main thread, and kaleido's thread-safety under genuinely
    concurrent calls isn't confirmed for this app's pinned version
    (kaleido v1 talks to a real Chrome install over an internal
    asyncio-based Chrome DevTools Protocol connection -- not something
    to gamble on in production without being able to test it live).

    Instead this uses a "two-tick" pattern with `reactive.invalidate_later`
    and no threading at all:
      - Tick 1 (key not seen yet): mark it "pending", schedule a
        re-invalidation of *this specific output* a moment from now via
        `reactive.invalidate_later`, and return the "Loading chart..."
        placeholder. Shiny flushes that placeholder to the browser.
      - Tick 2 (the timer fires): this function runs again for the same
        output, sees the key is "pending", and *now* calls `builder()`
        for real -- still synchronously, still on the main thread, so
        kaleido is never called from anywhere but the main thread.

    The tradeoff vs. the threaded version: no parallel rendering speedup
    (charts still render one at a time, same total time as before) --
    but genuinely zero thread-safety risk, and the user still sees a
    "Loading chart..." placeholder instead of a blank gap while it
    renders.

    `cache` is a reactive.Value(dict) the caller owns (one per group of
    related chart outputs is fine -- it's fine for multiple chart
    outputs to share one cache; a .set() from one output will cause
    the others to re-run too, but they'll just re-return their own
    already-resolved entry, which is harmless, just a little extra
    churn). `key` must uniquely identify this specific chart + its
    current inputs (target, filters, etc.) -- changing any input that
    should trigger a fresh render just means passing a different key;
    a stale entry under an old key is simply never looked up again.

    Call this from inside a @render.ui function bound to a single
    output id."""
    from shiny import reactive, ui

    state = cache()
    entry = state.get(key)

    if entry is None:
        cache.set({**state, key: "pending"})
        reactive.invalidate_later(0.1)
        return ui.div(
            ui.div(class_="gbo-loading-spinner"),
            ui.span(label),
            class_="gbo-loading-row",
        )

    if entry == "pending":
        result = builder()
        cache.set({**cache(), key: result})
        return result

    return entry


PLOTLY_JS_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"


def plotly_js_dep():
    """<script> tag for plotly.js -- include once in the page head
    (shiny_app/app.py). Charts rendered by fig_to_img() rely on it."""
    from shiny import ui
    return ui.tags.script(src=PLOTLY_JS_URL, charset="utf-8")


def fig_to_img(fig, width=None, height=None, scale=1):
    """v2: render a plotly Figure as a LIVE, responsive plotly.js chart
    (hover tooltips, zoom) instead of a kaleido PNG.

    Why the change: kaleido v1 needs a Chrome install on the server.
    Posit Connect Cloud doesn't have one, so every chart on the Bullpen
    Dashboard rendered as an empty box in production (the "blank
    charts" bug). Inlining the figure JSON and letting the browser draw
    it needs no Chrome, costs the server nothing, and every mark gets a
    hover tooltip for free.

    Kept the name and signature so the 20+ existing call sites don't
    change. width is ignored (charts fill their card); height is
    honored. Paper/plot backgrounds are forced transparent so the card
    surface shows through in both themes."""
    from shiny import ui
    import json
    import uuid
    import plotly.io as pio

    h = int(height or (fig.layout.height or 420))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", autosize=True, width=None, height=h)
    div_id = f"gbo-plot-{uuid.uuid4().hex[:10]}"
    spec = json.loads(pio.to_json(fig, validate=False))
    config = {"displayModeBar": False, "responsive": True, "displaylogo": False, "scrollZoom": False}
    js = (
        "(function(){var run=function(){var el=document.getElementById(%s);if(!el||!window.Plotly){return setTimeout(run,60);}"
        "Plotly.newPlot(el,%s,%s,%s);};run();})();"
    ) % (json.dumps(div_id), json.dumps(spec["data"]), json.dumps(spec["layout"]), json.dumps(config))
    return ui.div(
        ui.div(id=div_id, class_="gbo-plot", style=f"width:100%; height:{h}px;"),
        ui.tags.script(js),
        class_="gbo-plot-wrap",
    )