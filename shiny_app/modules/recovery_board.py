"""
GBO -- Recovery Board (Oct 2026 WHOOP pilot). One row per player with a
connected WHOOP: today's readiness, recovery, HRV and resting HR vs his own
normal, last night's sleep, and when it last synced. Click a name to open
his Player Profile on the Recovery tab. Everyone can see it, players
included (Ryker's call for the pilot). Math: analytics/whoop_metrics.py.
"""

from datetime import date

from shiny import module, ui, render, reactive, req

from database import get_session
from analytics import whoop_metrics as wm

import ui_helpers
import whoop_display as wd


@module.ui
def recovery_board_ui():
    return ui.div(
        ui_helpers.page_header("Recovery Board",
                               "WHOOP sleep, HRV and recovery for every connected player, each compared to his own normal.",
                               actions=ui_helpers.how_to_link("whoop")),
        ui.output_ui("controls"),
        ui.output_ui("summary"),
        ui.output_ui("table"),
        ui.p(wd.EXPLAIN, class_="text-muted small", style="margin-top:14px;"),
    )


@module.server
def recovery_board_server(input, output, session, app_state):

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        return ui.input_date("as_of", "As of", value=date.today(), width="200px")

    @reactive.calc
    def _board():
        req(app_state.is_authenticated() and "as_of" in input and input.as_of())
        db = get_session()
        try:
            return wm.team_board(db, input.as_of())
        finally:
            db.close()

    @render.ui
    def summary():
        rows = _board()
        if not rows:
            return ui_helpers.card(ui_helpers.empty_state(
                "No players have a WHOOP connected yet. Open a player's profile, go to the Recovery tab, and make a "
                "Connect WHOOP link for him."))
        counts = {s: sum(1 for r in rows if r["ready"]["status"] == s) for s in (wm.GOOD, wm.WATCH, wm.FLAG, wm.NEUTRAL)}
        return ui.div(
            ui_helpers.kpi_tile("Connected", str(len(rows))),
            ui_helpers.kpi_tile("Ready", str(counts[wm.GOOD]), status="good" if counts[wm.GOOD] else None),
            ui_helpers.kpi_tile("Monitor", str(counts[wm.WATCH]), status="watch" if counts[wm.WATCH] else None),
            ui_helpers.kpi_tile("Back off", str(counts[wm.FLAG]), status="flag" if counts[wm.FLAG] else None),
            ui_helpers.kpi_tile("Building baseline", str(counts[wm.NEUTRAL])),
            class_="gbo-kpi-row", style="margin-bottom:16px;",
        )

    @render.ui
    def table():
        rows = _board()
        if not rows:
            return None
        head = ["Player", "Readiness", "Recovery", "HRV (7-day vs normal)", "Resting HR (7-day vs normal)",
                "Sleep last night", "Sleep 7-day avg", "Sync"]
        body = []
        for r in rows:
            p, rd, c = r["player"], r["ready"], r["connection"]
            t = rd["today"] or {}
            zone = rd["zone"]
            rec = (f"{t['recovery']:.0f}%" if t.get("recovery") is not None else "—")
            rec_style = f"color:var(--gbo-status-{wm.ZONE_STATUS[zone]});font-weight:700" if zone else ""
            def vs(ms, spec="{:.0f}"):
                if ms["now"] is None or ms["base_mean"] is None:
                    return ms["label"]
                return f"{spec.format(ms['now'])} vs {spec.format(ms['base_mean'])}"
            js = f"Shiny.setInputValue('{session.ns('open')}', {p.player_id}, {{priority: 'event'}})"
            label = f"{p.last_name}, {p.first_name}"
            # Players see the whole board but can only open their own profile.
            name = (ui.tags.span(label, style="font-weight:600") if app_state.role_name() == "Player"
                    else ui.tags.a(label, onclick=js, role="button", style="cursor:pointer;font-weight:600"))
            sleep = (f"{t['sleep_hours']:.1f} h" if t.get("sleep_hours") is not None else "—") + \
                    (f" / {t['sleep_need_hours']:.1f}" if t.get("sleep_need_hours") else "")
            body.append(ui.tags.tr(
                ui.tags.td(name), ui.tags.td(wd.readiness_chip(rd)),
                ui.tags.td(rec, style=rec_style), ui.tags.td(vs(rd["hrv"])), ui.tags.td(vs(rd["rhr"])),
                ui.tags.td(sleep), ui.tags.td(wd.fmt(rd["sleep_avg_7d"], "{:.1f} h")),
                ui.tags.td(wd.synced_text(c), class_="text-muted small"),
            ))
        return ui_helpers.card(ui.div(ui.tags.table(ui.tags.thead(ui.tags.tr(*[ui.tags.th(h) for h in head])),
                                                    ui.tags.tbody(*body), class_="table table-sm"),
                                      class_="table-responsive"), title="Today")

    @reactive.effect
    @reactive.event(input.open)
    def _open():
        app_state.deep_link_player_id.set((int(input.open()), "Recovery"))
        target = "My Profile" if app_state.role_name() == "Player" else "Player Profile"
        ui.update_navs("main_nav", selected=target, session=session.root_scope())
