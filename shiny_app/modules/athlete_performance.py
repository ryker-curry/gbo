"""
GBO -- Athlete vs Performance (Nov 2026, Ryker): does a change in a physical
test line up with a change on the mound? Staff only.

  - Change-vs-change scatter: each pitcher's change in one test (force
    plates, ForceFrame, med ball, body comp) between two testing periods
    against his Rapsodo fastball change over the matching +/-30-day windows.
    Four quadrants (both up / both down / stronger but velo down / test down
    but velo up), OLS line with r, p and n.
  - Decline watch: velo down 1.5+ mph and/or a key force plate test 5%+
    worse -- "Both down" first.
  - Full change table for the picked test.

Math and the agreed rules: analytics/athlete_performance.py. Each pitcher's
own development path is on Player Profile -> Career Development.
"""

from shiny import module, ui, render, req, reactive

from database import get_session
from models import StaffPlayerAssignment
from analytics import athlete_performance as ap
import athlete_performance_display as apd
from gbo_cache import cached
import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Strength Coach", "Athletic Trainer",
               "Sports Scientist", "Data Analyst", "Video Coordinator")
TITLE = "Athlete vs Performance"
_TABLES = {"assessments", "assessment_results", "assessment_test_types", "rapsodo_pitches",
           "rapsodo_history", "game_pitches", "players"}

_team = cached("athlete_perf_changes", tables=_TABLES)(ap.team_changes)


@cached("athlete_perf_periods", tables=_TABLES)
def _periods(db):
    tests, _meta = ap.load_tests(db)
    pers = ap.periods(tests)
    counts = {p: sum(1 for t in tests.values() if p in t) for p in pers}
    return pers, counts


def _fmt(v, dp, sign=False):
    if v is None:
        return "—"
    return (f"{v:+.{dp}f}" if sign else f"{v:.{dp}f}").replace("-", "−")


def _chip(text):
    col = {"Both down": "var(--gbo-status-flag)", "Velo down": "var(--gbo-status-watch)",
           "Test down": "var(--gbo-status-watch)", "Both up": "var(--gbo-status-good)",
           "Stronger, velo down": "var(--gbo-status-watch)", "Test down, velo up": "var(--gbo-status-watch)"}.get(text)
    style = "display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;border:1px solid var(--gbo-border);"
    style += f"color:{col};border-color:{col};" if col else "color:var(--gbo-text-muted);"
    return ui.span(text, style=style)


def _table(headers, rows, num_from=1):
    head = ui.tags.tr(*[ui.tags.th(h, style="text-align:right;" if i >= num_from else "") for i, h in enumerate(headers)])
    body = [ui.tags.tr(*[ui.tags.td(c, style="text-align:right;" if i >= num_from and isinstance(c, str) else "")
                         for i, c in enumerate(r)]) for r in rows]
    return ui.div(ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                         class_="table-responsive"), class_="gbo-statline")


def _note(text):
    return ui.p(text, class_="text-muted small")


@module.ui
def athlete_performance_ui():
    return ui.div(
        ui_helpers.page_header(
            TITLE,
            "Did the pitchers who got stronger, faster or more powerful also gain on the mound -- and who is "
            "trending down on both? Change between two testing periods vs Rapsodo fastballs within 30 days of each.",
        ),
        ui.output_ui("ap_controls"),
        ui.output_ui("ap_body"),
    )


@module.server
def athlete_performance_server(input, output, session, app_state):

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    def _visible(db):
        if app_state.can_view_all_players():
            return None
        return tuple(sorted(a.player_id for a in db.query(StaffPlayerAssignment)
                            .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()))

    @render.ui
    def ap_controls():
        if not _ok():
            return ui_helpers.card(ui_helpers.empty_state("Staff only."))
        db = get_session()
        try:
            pers, counts = _periods(db)
        finally:
            db.close()
        if len(pers) < 2:
            return ui_helpers.card(ui_helpers.empty_state("Needs at least two testing periods of assessments."))
        pairs = [(a, b) for i, a in enumerate(pers) for b in pers[i + 1:]]
        default = pairs[-1]
        return ui_helpers.card(ui.div(
            ui.input_select("ap_from", "From period", choices=pers, selected=default[0]),
            ui.input_select("ap_to", "To period", choices=pers, selected=default[1]),
            ui.input_select("ap_perf", "On the mound",
                            choices={k: f"{v[0]} ({v[1]})" for k, v in ap.PERF_METRICS.items()}, selected="velo"),
            ui.output_ui("ap_test_ui"),
            style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;",
        ), _note("Periods with tests: " + ", ".join(f"{p} ({counts[p]} players)" for p in pers) + "."))

    @reactive.calc
    def _changes():
        req(_ok() and "ap_from" in input and "ap_to" in input)
        a, b = input.ap_from(), input.ap_to()
        req(a and b and a != b)
        db = get_session()
        try:
            return _team(db, a, b, _visible(db))
        finally:
            db.close()

    @render.ui
    def ap_test_ui():
        changes, meta = _changes()
        opts = ap.test_options(changes, meta)
        if not opts:
            return None
        labels = {k: f"{k} ({meta.get(k, ('', ''))[0] or ''})".replace(" ()", "") for k in opts}
        return ui.input_select("ap_test", "Physical test", choices=labels, selected=opts[0])

    @render.ui
    def ap_body():
        if not _ok():
            return None
        if "ap_from" in input and "ap_to" in input and input.ap_from() == input.ap_to():
            return ui_helpers.card(ui_helpers.empty_state("Pick two different periods."))
        changes, meta = _changes()
        if not changes:
            return ui_helpers.card(ui_helpers.empty_state(
                f"No pitcher has tests in both {input.ap_from()} and {input.ap_to()} yet."))
        req("ap_test" in input and "ap_perf" in input)
        test, perf = input.ap_test(), input.ap_perf()
        unit = (meta.get(test) or ("", ""))[0] or ""
        p_label, p_unit, p_dp = ap.PERF_METRICS[perf]
        pts = ap.scatter_points(changes, test, perf)
        neutral = bool(pts) and pts[0]["test"]["dir"] == 0
        line = ap.fit(pts)
        flipped = bool(pts) and pts[0]["test"]["dir"] == -1
        xlab = f"{test}: change (%)" + (" -- flipped, right = faster/better" if flipped else
                                        "" if neutral else ", right = improved")
        svg = apd.change_scatter_svg(pts, line, xlab, f"{p_label} change ({p_unit})", neutral=neutral, y_unit=p_unit)
        if line:
            r = line["r"]
            strength = "negligible" if abs(r) < 0.1 else "small" if abs(r) < 0.3 else "moderate" if abs(r) < 0.5 else "large"
            pv = f", p = {line['p']:.2f}" if line.get("p") is not None else ""
            stats = (f"r = {r:+.2f} ({strength}){pv}, n = {line['n']} pitchers. "
                     + ("Early signal only -- under 15 pitchers a correlation can look strong by chance. "
                        if line["n"] < 15 else "")
                     + "Shows things that moved together, not cause and effect.")
        else:
            stats = "Needs 3+ pitchers with both a test change and Rapsodo fastballs in both windows."
        scatter = ui_helpers.card(
            _note(f"{input.ap_from()} to {input.ap_to()}. Each dot is a pitcher. Hover a dot for his numbers. "
                  "Fastball numbers use his Rapsodo 4-seam and 2-seam pitches within 30 days of each test "
                  "(bullpens and games, no rehab or low-intent sessions)."),
            ui.HTML(svg) if svg else ui_helpers.empty_state("No pitcher has this test and Rapsodo fastballs in both windows."),
            _note(stats), title="Change vs change")

        watch = ap.decline_watch(changes)
        watch_rows = []
        for r in watch:
            drops = ", ".join(f"{k} {v:+.1f}%".replace("-", "−") for k, v in r["drops"]) or "—"
            watch_rows.append([r["name"], _chip(r["level"]), _fmt(r["velo_change"], 1, sign=True), drops,
                               str((r["perf_b"] or {}).get("n", 0))])
        watch_card = ui_helpers.card(
            _note(f"Fastball velo down {ap.VELO_DROP} mph or more from {input.ap_from()}, and/or a key force plate test "
                  f"({', '.join(ap.KEY_DECLINE)}) {ap.TEST_DROP_PCT:g}%+ worse. Both at once is the strongest flag -- "
                  "it points to fatigue, injury, weight loss or detraining rather than mechanics."),
            _table(["Pitcher", "Flag", "Velo change (mph)", "Force plate drops", "Pitches (later window)"], watch_rows, num_from=2)
            if watch_rows else ui_helpers.empty_state("Nobody crosses the decline thresholds for these periods."),
            title="Decline watch")

        rows = []
        for p in sorted(pts, key=lambda p: (p["quad"] != "Both down", p["last"])):
            t = p["test"]
            rows.append([p["name"], _fmt(t["v1"], 2), _fmt(t["v2"], 2), _fmt(t["pct"], 1, sign=True),
                         _fmt(p["perf"]["v1"], p_dp), _fmt(p["perf"]["v2"], p_dp), _fmt(p["y"], p_dp, sign=True),
                         _chip(p["quad"])])
        table = ui_helpers.card(
            _table(["Pitcher", f"{input.ap_from()} ({unit})", f"{input.ap_to()} ({unit})", "Test change %",
                    f"{p_label} before", f"{p_label} after", "Change", "Quadrant"], rows),
            title=f"{test} vs {p_label}") if rows else None

        return ui.div(scatter, watch_card, table, style="display:grid;gap:16px;margin-top:16px;")
