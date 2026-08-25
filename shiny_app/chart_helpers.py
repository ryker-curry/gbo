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


def render_chart_async(cache, key, builder, label="Loading chart…", sync=False):
    """Render a chart's UI (via `builder`, a zero-arg callable) so a
    spinner + placeholder shows first, before the actual (still
    synchronous) render happens.

    `label` customizes the placeholder text for callers building
    something other than a literal chart (e.g. bullpen_dashboard_
    display.py's session header/KPI section, which also goes through
    this same two-tick pattern to avoid a blank gap while its own
    pitch-list query runs) -- defaults to "Loading chart…" for the
    common case.

    `sync=True` skips the placeholder/`invalidate_later` step entirely
    and just calls `builder()` immediately (Sept 2026, Ryker: client-
    side "output is in an unexpected state" warnings on Bullpen
    Dashboard). Root cause: the scheduled `invalidate_later(0.1)`
    below re-invalidates this specific output on a 100ms wall-clock
    timer, independent of Shiny's normal input-driven invalidation --
    when both fire close together (e.g. switching pitcher right as
    that timer is about to land), the client can receive two
    overlapping recalculation cycles for the same output id and its
    state tracker throws this warning. It's harmless (the content
    itself is always correct), but it was silent before because
    fig_to_img() used to go through kaleido, which took long enough
    that the two triggers rarely landed close together. Now that
    fig_to_img() renders live plotly.js (near-instant, no subprocess),
    the two-tick delay isn't buying anything for a plain chart build
    anymore -- it was only ever there to keep kaleido off the main
    thread (see below) -- so for that case it's simpler and safer to
    just skip the timer than to fight its timing. Left off by default
    so callers whose builder() is still a real, potentially-slow
    operation (e.g. this module's own DB-query-backed session header)
    keep the loading placeholder.

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

    if sync:
        return builder()

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