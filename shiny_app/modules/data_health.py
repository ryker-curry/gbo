"""
GBO -- Data Health page (Oct 2026, Ryker approved; staff only, under Game
Operations). Read-only: lists what's missing or inconsistent in each
game's charting so every report stays accurate, with a "Fix in Game
Tracking" button that opens that game. Checks: analytics/data_health.py.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req

from database import get_session
from analytics import data_health
from analytics.team_report import game_label

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
GRADE_COLORS = {"green": "#2E9C62", "yellow": "#B58A22", "red": "#D94F3D"}


@module.ui
def data_health_ui():
    return ui.div(
        ui_helpers.page_header("Data Health",
                               "What's missing in the charting -- fix these and every report stays accurate."),
        ui.output_ui("controls"),
        ui.output_ui("summary"),
        ui.output_ui("games"),
    )


@module.server
def data_health_server(input, output, session, app_state):

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        today = date.today()
        return ui.div(
            ui.input_date_range("range", "Games from / to", start=today - timedelta(days=14), end=today),
            ui.input_checkbox("only_problems", "Only show games with something to fix", value=True),
            style="display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;",
        )

    @reactive.calc
    def _results():
        req(_ok() and "range" in input and input.range())
        d0, d1 = input.range()
        req(d0 and d1)
        db = get_session()
        try:
            return data_health.check_range(db, d0, d1)
        finally:
            db.close()

    @render.ui
    def summary():
        if not _ok():
            return None
        res = _results()
        if not res:
            return ui_helpers.empty_state("No tracked games in this range.")
        avg = sum(r["score"] for r in res) / len(res)
        totals = {}
        for r in res:
            for c in r["checks"]:
                t = totals.setdefault(c["key"], [0, 0])
                t[0] += c["missing"]
                t[1] += c["total"]
        worst = sorted(((k, v) for k, v in totals.items() if v[0]), key=lambda kv: -kv[1][0] * data_health.CHECK_META[kv[0]][2])
        cards = [
            {"label": "Charting complete", "value": f"{avg:.0f}%", "delta": f"{len(res)} games", "delta_positive": avg >= data_health.GREEN},
            {"label": "Games to fix", "value": str(sum(1 for r in res if r["grade"] != "green")),
             "delta": f"{sum(1 for r in res if r['grade'] == 'red')} red"},
        ]
        trend = data_health.weekly_trend(res)
        trend_rows = [{"Week of": w.strftime("%b %d"), "Games": n, "Complete": f"{s:.0f}%"} for w, s, n in trend]
        top = [ui.tags.li(ui.strong(data_health.CHECK_META[k][0]), f": {v[0]} of {v[1]} -- ", data_health.CHECK_META[k][1])
               for k, v in worst[:4]]
        return ui.div(
            ui_helpers.render_kpi_cards(cards),
            ui.layout_columns(
                ui_helpers.card(ui.tags.ul(*top) if top else ui.p("Nothing missing in this range.", class_="text-muted"),
                                title="Biggest gaps (all games in range)"),
                ui_helpers.card(ui_helpers.render_dict_table(trend_rows), title="By week"),
                col_widths=[7, 5],
            ),
        )

    @render.ui
    def games():
        if not _ok():
            return None
        res = _results()
        if not res:
            return None
        only = input.only_problems() if "only_problems" in input else True
        blocks = []
        for r in res:
            g = r["game"]
            issues = [c for c in r["checks"] if c["missing"]]
            if only and not issues:
                continue
            color = GRADE_COLORS[r["grade"]]
            head = ui.div(
                ui.span(f"{r['score']:.0f}%", style=f"background:{color};color:#fff;font-weight:700;border-radius:10px;padding:2px 10px;margin-right:10px;"),
                ui.strong(game_label(g)),
                ui.span(f"  ·  {r['pitches']} pitches  ·  {g.status}", class_="text-muted small"),
                ui.input_action_button(f"fix_{g.game_id}", "Fix in Game Tracking", class_="btn-sm btn-outline-light",
                                       style="margin-left:auto;"),
                style="display:flex;align-items:center;gap:6px;",
            )
            rows = [{"Problem": c["label"], "Missing": f"{c['missing']} of {c['total']}" if c["key"] != "final" else "—",
                     "Why it matters": c["why"]} for c in issues]
            body = ui_helpers.render_dict_table(rows) if rows else ui.p("All checks pass.", class_="text-muted small")
            blocks.append(ui_helpers.card(head, ui.div(body, style="margin-top:8px;")))
        if not blocks:
            return ui.p("Every game in this range passes all checks.", class_="text-muted", style="margin-top:12px;")
        return ui.div(*blocks, style="margin-top:12px;display:flex;flex-direction:column;gap:12px;")

    # One observer for every "Fix" button (ids are per game).
    _seen = {}

    @reactive.effect
    def _fix_clicks():
        if not _ok():
            return
        res = _results()
        for r in res:
            gid = r["game"].game_id
            key = f"fix_{gid}"
            if key not in input:
                continue
            v = input[key]()
            if not v:
                _seen[key] = 0      # button re-rendered -> reset
                continue
            if v != _seen.get(key, 0):
                _seen[key] = v
                app_state.deep_link_game_id.set(gid)
                ui.update_navs("main_nav", selected="Game Tracking", session=session.root_scope())
