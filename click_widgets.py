"""
GBO -- Shared click-to-place widget helpers (Shiny/shinywidgets).

Extracted from shiny_app/modules/game_tracking.py (where this technique
was first built) so Command Tracker's intended/actual location widgets
can reuse the same click-capture code instead of a second copy-pasted
implementation, rather than because it was independently re-proven
working there -- see the pivot note below.

PIVOT (Aug 2026): the original approach used plotly.py's
go.FigureWidget.data[0].on_click(callback) -- a Python-side event
registration that relies on shinywidgets/anywidget to forward the
browser's click back to Python over the widget's comm channel, which
then calls ui.update_numeric() to write the clicked point into the
paired numeric inputs. Live debugging (with the coach actually clicking
the deployed app, not just a code read) proved this round-trip is
broken: the click reaches the browser's plotly.js layer correctly, the
comm message with the correct coordinates genuinely reaches the Python
process, the registered on_click callback fires with a valid point
index, and ui.update_numeric() runs without raising -- but the browser
never applies the update. This reproduces identically in
game_tracking.py's intended_location_widget/batted_ball_location_widget/
video_review_widget, so it isn't anything about Command Tracker's usage;
it's a framework-level regression tied to plotly 6.x's rewrite of
FigureWidget on top of anywidget (see e.g.
https://github.com/plotly/plotly.py/issues/4933 and
https://github.com/plotly/plotly.py/issues/4996 -- erratic FigureWidget
behavior and Shiny-specific breakage reported after that rewrite).

Fix: skip the Python-side on_click round-trip entirely. A click on the
chart is captured with a plain client-side 'plotly_click' listener
(plotly.js itself demonstrably fires this reliably -- confirmed live),
which writes the clicked point straight into the paired numeric
inputs' DOM elements and dispatches the same input/change events a
real keystroke + blur would produce. Those numeric inputs already have
a working Shiny binding (this is exactly how typing a coordinate by
hand has always reached the server -- confirmed live, including a full
save-a-pitch round trip with correct downstream math), so this is the
only step that needed replacing. No server-side click handling code is
needed at all any more -- the numeric inputs remain the single actual
source of truth, completely unchanged from before.

SECOND FIX (same day): the first version of CLICK_CAPTURE_JS below used
a childList-only MutationObserver, which reliably found the new
".gbo-click-target" wrapper divs but never actually bound their plotly
click handler -- live debugging (see bindClickTarget's comment) showed
the anywidget-based FigureWidget's container div lands in the DOM
*before* plotly.js finishes initializing it: the "js-plotly-plot" class
and the .on()/.once() event-emitter methods get attached by
Plotly.newPlot() as a later mutation on the SAME already-present node,
not as a fresh node insertion, so a childList-only observer never saw
it. Worse, the old bindClickTarget() set its "already bound" flag
*before* calling the not-yet-defined gd.on(), so the first failed
attempt permanently blocked every later, legitimate retry. Fixed by (a)
only marking a target bound once gd.on() is confirmed callable and the
listener registration actually happens, (b) also observing class
attribute mutations, and (c) a cheap periodic re-scan as a safety net
that doesn't care exactly which DOM mutation pattern anywidget uses.

Two pieces, used together as a pair:
  - build_clickable_widget -- wraps a plain plotly Figure into a
    go.FigureWidget (unchanged from before; rendering was never the
    problem, only the on_click round-trip was).
  - click_target -- wraps an output_widget(...) UI call so the shared
    CLICK_CAPTURE_JS (installed once, app-wide, by shiny_app/app.py)
    knows which two numeric inputs a click on that particular chart
    should write into.
"""

import plotly.graph_objects as go
from shiny import ui
from shiny.module import resolve_id


def build_clickable_widget(fig):
    """Wraps a plain plotly Figure (as returned by
    strike_zone.build_zone_selector_figure/
    field_location.build_field_selector_figure -- both pure,
    framework-agnostic figure builders, see those modules' docstrings)
    into a go.FigureWidget with the same mode-bar-hidden config the
    original Streamlit click-selector used
    (config={"displayModeBar": False} in strike_zone.render_zone_selector/
    field_location.render_field_selector). shinywidgets' render_plotly
    would auto-convert a plain go.Figure for us (see as_widget_plotly in
    the shinywidgets package), but only this explicit path lets us also
    set the widget's display config before it's returned."""
    widget = go.FigureWidget(fig.data, fig.layout)
    widget._config = {"displayModeBar": False}
    return widget


def click_target(widget_ui, x_input_id, y_input_id, round_ndigits=2):
    """Wrap an output_widget(...) call (built from a
    build_clickable_widget()-wrapped figure, which always carries the
    invisible dense click-grid from strike_zone.py/field_location.py at
    trace index 0 -- see those modules' build_*_selector_figure
    docstrings) so that clicking the rendered chart writes the clicked
    grid point's coordinates into the two given ui.input_numeric()
    fields -- exactly as if the coach had typed them.

    Call this from a module's *_ui() function (or from inside a
    @render.ui that builds a nested UI, e.g. game_tracking.py's
    live_tracking_body/video review section) wherever output_widget(...)
    used to be called directly:

        click_widgets.click_target(
            output_widget("cmd_intended_location_widget"),
            "cmd_intended_x_input", "cmd_intended_z_input",
        )

    resolve_id() namespaces the two input ids the same way Shiny
    already namespaces the ui.input_numeric() calls that define them,
    so this works correctly inside a module without any extra wiring;
    the shared CLICK_CAPTURE_JS (installed once app-wide by
    shiny_app/app.py) reads the already-namespaced ids straight off
    this wrapper's data attributes at click time via
    document.getElementById(), so it never needs to know about Shiny
    modules at all.

    No matching server-side registration call is needed any more --
    unlike the old register_click_to_numeric(), this fully replaces it;
    delete any leftover call to the old function at the call site."""
    return ui.div(
        widget_ui,
        class_="gbo-click-target",
        **{
            "data-click-x-input": resolve_id(x_input_id),
            "data-click-y-input": resolve_id(y_input_id),
            "data-click-round": str(round_ndigits),
        },
    )


# Installed once, app-wide, by shiny_app/app.py (same pattern as that
# file's own _NO_WHEEL_SCROLL_JS) -- NOT per-widget, so this stays a
# single shared listener no matter how many click_target()-wrapped
# charts exist on a page. A MutationObserver (rather than a fixed list
# of ids) is required because every widget rebuilt via build_
# clickable_widget() is a brand-new FigureWidget/DOM node on every
# re-render (typing in the paired numeric inputs, changing pitch type,
# switching sessions, etc. all cause a fresh render) -- a one-time
# querySelectorAll at page load would miss every chart that (re)appears
# after that.
CLICK_CAPTURE_JS = r"""
(function () {
  function round(value, digits) {
    var mult = Math.pow(10, digits);
    return Math.round(value * mult) / mult;
  }

  function fireInputChange(el, value) {
    if (!el) return;
    el.value = value;
    el.dispatchEvent(new Event("input", {bubbles: true}));
    el.dispatchEvent(new Event("change", {bubbles: true}));
  }

  function bindClickTarget(gd) {
    // Guard on gd.on actually existing (not just the node existing): the
    // anywidget-based FigureWidget inserts its container div into the DOM
    // before plotly.js has finished initializing it (the "js-plotly-plot"
    // class and the .on()/.once() event-emitter methods get attached by
    // Plotly.newPlot() asynchronously, as a later mutation on the SAME
    // already-present node rather than as a fresh node insertion). A plain
    // childList-only MutationObserver never sees that second step, so a
    // bind attempt that fires on the first (empty-container) insertion
    // would previously call the not-yet-defined gd.on() and throw -- and
    // because the __gboClickBound flag was set *before* that call, the
    // failure was permanent (the guard above would then skip every later,
    // legitimate retry). Only set the flag once binding actually succeeds,
    // and skip silently (retry-able) if gd.on isn't callable yet.
    if (gd.__gboClickBound) return;
    if (typeof gd.on !== "function") return;
    gd.__gboClickBound = true;
    gd.on("plotly_click", function (evt) {
      if (!evt || !evt.points || !evt.points.length) return;
      var pt = evt.points[0];
      var wrapper = gd.closest(".gbo-click-target");
      if (!wrapper) return;
      var digits = parseInt(wrapper.getAttribute("data-click-round"), 10);
      if (isNaN(digits)) digits = 2;
      fireInputChange(document.getElementById(wrapper.getAttribute("data-click-x-input")), round(pt.x, digits));
      fireInputChange(document.getElementById(wrapper.getAttribute("data-click-y-input")), round(pt.y, digits));
    });
  }

  function scan(root) {
    if (!root || root.nodeType !== 1) return;
    if (root.matches && root.matches(".gbo-click-target .js-plotly-plot, .gbo-click-target .plotly-graph-div")) {
      bindClickTarget(root);
    }
    if (root.querySelectorAll) {
      var found = root.querySelectorAll(".gbo-click-target .js-plotly-plot, .gbo-click-target .plotly-graph-div");
      for (var i = 0; i < found.length; i++) bindClickTarget(found[i]);
    }
  }

  function scanWholePage() {
    scan(document.body);
  }

  // childList/subtree catches the common case (a whole new plot container
  // appearing). attributes/attributeFilter:['class'] catches the case
  // above -- an existing, already-observed node gaining the
  // "js-plotly-plot" class (and, by then, its .on method) after the fact.
  var observer = new MutationObserver(function (mutations) {
    for (var i = 0; i < mutations.length; i++) {
      var m = mutations[i];
      if (m.type === "childList") {
        for (var j = 0; j < m.addedNodes.length; j++) scan(m.addedNodes[j]);
      } else if (m.type === "attributes") {
        scan(m.target);
      }
    }
  });
  observer.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["class"],
  });
  scanWholePage();

  // Belt-and-suspenders safety net: bindClickTarget() is idempotent (it
  // no-ops once a div is genuinely bound, and no-ops harmlessly if gd.on
  // still isn't ready), so a cheap periodic re-scan guarantees every
  // click target eventually gets bound even if some future plotly/anywidget
  // version mutates the DOM in a way neither observer branch above
  // anticipates.
  setInterval(scanWholePage, 800);
})();
"""
