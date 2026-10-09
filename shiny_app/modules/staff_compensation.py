"""
GBO -- Staff Compensation (Oct 2026, Ryker): every active pitcher's
compensation profile at a glance -- domain scores vs the staff, velo vs
his body, and his risk / delivery flags. Click a name for his Player
Profile -> Compensation tab. Staff only. Data: analytics/compensation.py.
"""

from html import escape

from shiny import module, ui, render, reactive

from database import get_session
from analytics import compensation as comp
import ui_helpers

SHORT = {"Size": "Size", "Lower-body strength": "LB str", "Lower-body power": "LB pwr", "Rotational power": "Rot pwr",
         "Speed": "Speed", "Upper-body strength": "UB str", "Shoulder strength": "Shldr str",
         "Forearm & grip": "Forearm", "Shoulder mobility": "Shldr mob", "Hip mobility": "Hip mob"}

CSS = """
.gbo-sc td.z { text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.gbo-sc td.z.s { background: var(--gbo-status-good-soft); color: var(--gbo-status-good); }
.gbo-sc td.z.w { background: var(--gbo-status-flag-soft); color: var(--gbo-status-flag); }
.gbo-sc td.z.na { color: var(--gbo-text-muted); font-weight: 400; }
.gbo-sc th.z { text-align: center; white-space: nowrap; font-size: .72rem; }
.gbo-sc a.nm { cursor: pointer; font-weight: 700; }
"""


@module.ui
def staff_compensation_ui():
    return ui.div(
        ui.tags.style(CSS),
        ui_helpers.page_header("Staff Compensation",
                               "What each pitcher leans on, what he lacks, and whether the pattern is a known arm-stress "
                               "risk. Click a name for the full profile."),
        ui.output_ui("grid"),
        class_="gbo-sc",
    )


@module.server
def staff_compensation_server(input, output, session, app_state):
    def _ok():
        return app_state.is_authenticated() and app_state.role_name() != "Player"

    @render.ui
    def grid():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        db = get_session()
        try:
            data = comp.load(db)
            dl = comp.load_delivery(db, data)
            try:   # Oct 2026 (Paradigm, "The Angle Advantage"): staff angle standouts
                from analytics import approach_angles as aa
                angle_x = aa.staff_extremes(aa.staff_profiles(db))
            except Exception:
                angle_x = {}
        finally:
            db.close()
        if not data["players"]:
            return ui_helpers.card(ui_helpers.empty_state("No active pitchers."))
        head = ui.tags.tr(ui.tags.th("Pitcher"), ui.tags.th("Flags"), ui.tags.th("Velo vs body", class_="z"),
                          ui.tags.th("Angle standouts"),
                          *[ui.tags.th(SHORT[d], class_="z", title=d) for d in comp.DOMAIN_NAMES])
        body = []
        counts = {"tested": 0, "flags": 0}
        open_js = session.ns("open")
        for pid, p in sorted(data["players"].items(), key=lambda kv: (kv[1].last_name, kv[1].first_name)):
            doms = data["doms"].get(pid, {})
            _s, weak = comp.read(doms)
            fl = comp.flags(pid, doms, data["derived"][pid], data["model"], data["velo"])
            fl += comp.delivery_flags(dl["drifts"].get(pid, {}), dl["el"].get(pid, (None, None)), dl["staff"], weak)
            counts["tested"] += bool(doms)
            counts["flags"] += bool(fl)
            cells = []
            for d in comp.DOMAIN_NAMES:
                v = doms.get(d)
                if v is None:
                    cells.append(ui.tags.td("·", class_="z na", title=f"{d}: not tested"))
                    continue
                z = v["z"]
                cls = "z s" if z >= comp.STRONG else ("z w" if z <= comp.WEAK else "z")
                cells.append(ui.tags.td(f"{z:+.1f}", class_=cls, title=f"{d} {z:+.2f} SD"))
            pr = (data["model"] or {}).get("pred", {}).get(pid)
            vtxt = f"{pr[2]:+.1f}" if pr else "—"
            vcls = "z" + ((" s" if pr[2] >= data["model"]["rmse"] else " w" if pr[2] <= -data["model"]["rmse"] else "")
                          if pr else " na")
            chips = [ui_helpers.status_chip("flag" if f["level"] == "high" else "watch", f["name"]) for f in fl]
            body.append(ui.tags.tr(
                ui.tags.td(ui.tags.a(f"{p.last_name}, {p.first_name}", class_="nm",
                                     onclick=f"Shiny.setInputValue('{open_js}', {pid}, {{priority: 'event'}})"),
                           style="white-space:nowrap;"),
                ui.tags.td(ui.div(*chips, style="display:flex;gap:4px;flex-wrap:wrap;min-width:180px;") if chips else "—"),
                ui.tags.td(ui.div(*[ui.span(_angle_short(e), title=e["text"], class_="small", style="white-space:nowrap;")
                                    for e in angle_x.get(pid, [])], style="display:flex;flex-direction:column;min-width:150px;")
                           if angle_x.get(pid) else "—"),
                ui.tags.td(vtxt, class_=vcls, title="mph above (+) or below (-) what his body predicts"),
                *cells,
            ))
        n = len(data["players"])
        return ui.div(
            ui.p(f"{counts['tested']} of {n} pitchers have tests this season · {counts['flags']} with at least one flag. "
                 "Cells = SD vs the staff (green strength, red limiter, · not tested). Velo vs body = mph above or below "
                 "what the team model predicts from his tests. Flags are research-based watch items, not diagnoses. "
                 "Many cells stay empty until this season's testing is in.", class_="text-muted small"),
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                   class_="table-responsive"),
        )

    @reactive.effect
    @reactive.event(input.open)
    def _open():
        if not _ok():
            return
        app_state.deep_link_player_id.set((int(input.open()), "Compensation"))
        ui.update_navs("main_nav", selected="Player Profile", session=session.root_scope())


def _angle_short(e):
    word = {"flat": "flattest", "steep": "steepest", "arm": "arm-side", "glove": "glove-side"}[e["kind"]]
    return f"{e['label']}: {word} ({e['value']:+.1f}°)"
