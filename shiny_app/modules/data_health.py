"""
GBO -- Data Health page (Oct 2026, Ryker approved; staff only, under Game
Operations). Read-only: lists what's missing or inconsistent in each
game's charting so every report stays accurate, with a "Fix in Game
Tracking" button that opens that game. Checks: analytics/data_health.py.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req

from database import get_session
from analytics import data_health, box_score
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
        ui.output_ui("box_card"),
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

    _saved = reactive.value(0)

    @reactive.calc
    def _results():
        _saved()
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
            blocks.append(ui_helpers.card(head, ui.div(body, style="margin-top:8px;"), _box_line(r)))
        if not blocks:
            return ui.p("Every game in this range passes all checks.", class_="text-muted", style="margin-top:12px;")
        return ui.div(*blocks, style="margin-top:12px;display:flex;flex-direction:column;gap:12px;")

    # ---- Box score check ------------------------------------------------
    def _box_line(r):
        if r["game"].is_intrasquad:
            return None
        if not r["has_box"]:
            return ui.p("No official box score entered yet -- add it in Box score check above.",
                        class_="text-muted small", style="margin:6px 0 0;")
        bad = [x for x in r["box_rows"] if not x["ok"]]
        if not bad:
            return ui.p("✓ Charting matches the official box score.", class_="small",
                        style="margin:6px 0 0;color:#2E9C62;")
        txt = ", ".join(f"{'Pitt State' if x['side'] == 'our' else 'Opponent'} {x['label']} "
                        f"charted {x['charted']} vs official {x['official']}" for x in bad)
        return ui.p("Box score off: " + txt, class_="small", style="margin:6px 0 0;color:#D94F3D;")

    def _box_games():
        return [r for r in _results() if not r["game"].is_intrasquad]

    @render.ui
    def box_card():
        if not _ok():
            return None
        res = _box_games()
        if not res:
            return None
        choices = {str(r["game"].game_id): ("✓ " if r["has_box"] else "") + game_label(r["game"]) for r in res}
        sel = input.box_game() if "box_game" in input and input.box_game() in choices else next(iter(choices))
        head = ui.tags.tr(ui.tags.th(""), *[ui.tags.th(box_score.LABELS[k], style="text-align:center;") for k in box_score.STATS])
        # Re-renders whenever the game changes (reads input.box_game above),
        # so the boxes always show that game's saved line.
        cur = next(r for r in res if str(r["game"].game_id) == sel)
        saved = {(x["side"], x["stat"]): x["official"] for x in cur["box_rows"]}

        def row(side, name):
            return ui.tags.tr(ui.tags.td(ui.strong(name)), *[
                ui.tags.td(ui.input_numeric(f"box_{side}_{k}", None, value=saved.get((side, k)), min=0, step=1,
                                            width="70px"))
                for k in box_score.STATS])
        form = ui.tags.table(head, row("our", "Pitt State"), row("opp", "Opponent"), class_="gbo-box-form")
        return ui_helpers.card(
            ui.p("Type the official line (R / H / E / BB / K) from the final box score. E = errors that team made "
                 "in the field. GBO checks it against what the charting adds up to.", class_="text-muted small"),
            ui.layout_columns(
                ui.div(ui.input_select("box_game", "Game", choices=choices, selected=sel), form,
                       ui.input_action_button("box_save", "Save box score", class_="btn-sm btn-primary",
                                              style="margin-top:6px;")),
                ui.output_ui("box_compare"),
                col_widths=[6, 6],
            ),
            ui.tags.style(".gbo-box-form td{padding:2px 6px;vertical-align:middle}.gbo-box-form .form-group{margin:0}"),
            title="Box score check",
        )

    @reactive.effect
    @reactive.event(input.box_save)
    def _save_box():
        if not _ok() or "box_game" not in input:
            return
        vals = {}
        for side in box_score.SIDES:
            for k in box_score.STATS:
                v = input[f"box_{side}_{k}"]()
                vals[f"{side}_{k}"] = int(v) if v not in (None, "") else None
        if all(v is None for v in vals.values()):
            ui.notification_show("Type at least one number first.", type="warning")
            return
        db = get_session()
        try:
            box_score.save(db, int(input.box_game()), vals, app_state.user_id())
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save the box score: {e}", type="error")
            return
        finally:
            db.close()
        ui.notification_show("Box score saved.", type="message")
        _saved.set(_saved() + 1)

    @render.ui
    def box_compare():
        if not _ok() or "box_game" not in input or not input.box_game():
            return None
        gid = int(input.box_game())
        r = next((x for x in _box_games() if x["game"].game_id == gid), None)
        if r is None:
            return None
        db = get_session()
        try:
            charted = box_score.charted_line(db, gid)
        finally:
            db.close()
        if not r["has_box"]:
            rows = [{"": "Pitt State" if s == "our" else "Opponent",
                     **{box_score.LABELS[k]: charted[s][k] for k in box_score.STATS}} for s in box_score.SIDES]
            return ui.div(ui.strong("What the charting adds up to"), ui_helpers.render_dict_table(rows),
                          ui.p("Save the official line to compare.", class_="text-muted small"))
        cells = {(x["side"], x["stat"]): x for x in r["box_rows"]}

        def td(side, k):
            x = cells.get((side, k))
            if x is None:
                return ui.tags.td(str(charted[side][k]), style="text-align:center;color:#888;")
            if x["ok"]:
                return ui.tags.td(f"{x['charted']} ✓", style="text-align:center;color:#2E9C62;")
            return ui.tags.td(f"{x['charted']} (box {x['official']})",
                              style="text-align:center;color:#D94F3D;font-weight:700;")
        head = ui.tags.tr(ui.tags.th("Charted"), *[ui.tags.th(box_score.LABELS[k], style="text-align:center;")
                                                   for k in box_score.STATS])
        body = [ui.tags.tr(ui.tags.td(ui.strong("Pitt State" if s == "our" else "Opponent")),
                           *[td(s, k) for k in box_score.STATS]) for s in box_score.SIDES]
        bad = sum(1 for x in r["box_rows"] if not x["ok"])
        msg = (ui.p("Everything matches.", style="color:#2E9C62;margin-top:6px;") if not bad else
               ui.p(f"{bad} number{'s' if bad != 1 else ''} off -- open the game in Game Tracking and look for a "
                    "missing PA, a wrong result, or a run that didn't get credited.", class_="small",
                    style="color:#D94F3D;margin-top:6px;"))
        return ui.div(ui.tags.table(head, *body, class_="table table-sm"), msg)

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
