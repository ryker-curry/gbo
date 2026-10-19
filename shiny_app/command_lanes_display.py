"""
GBO -- "Command by target lane" block (Oct 2026), shared by Pitcher
Profile's Command & Execution view and Pitcher Game Breakdown's. Data from
analytics/command_lanes.py.
"""

from shiny import ui

import ui_helpers
from analytics.command_lanes import H_LANES, V_LANES, takeaway

CSS = """
.gbo-lanes { border-collapse: separate; border-spacing: 4px; margin: 6px 0 4px; }
.gbo-lanes th { font-size: .7rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: var(--gbo-text-muted); text-align: center; padding: 2px 6px; }
.gbo-lanes td { width: 120px; height: 64px; text-align: center; vertical-align: middle; border-radius: 6px; border: 1px solid var(--gbo-border); background: var(--gbo-bg-card); font-size: .78rem; color: var(--gbo-text-muted); }
.gbo-lanes td b { display: block; font-size: 1.05rem; color: var(--gbo-text); }
.gbo-lanes td.good { background: var(--gbo-status-good-soft); } .gbo-lanes td.watch { background: var(--gbo-status-watch-soft); } .gbo-lanes td.flag { background: var(--gbo-status-flag-soft); }
"""


def _status(avg):
    """Same bands as Command Execution % scoring: within 8" = good, within 12" = watch."""
    if avg is None:
        return ""
    return "good" if avg <= 8 else ("watch" if avg <= 12 else "flag")


def lanes_block(res, min_n=1):
    """The grid + lane table + one-line takeaway, or an empty-state."""
    if not res or not res["overall"]:
        return ui_helpers.empty_state("No pitches with both a called spot and a location (and a known batter side) here yet.")
    head = ui.tags.tr(ui.tags.th(""), *[ui.tags.th(h) for h in H_LANES])
    body = []
    for v in V_LANES:
        cells = [ui.tags.th(v, style="text-align:right;")]
        for h in H_LANES:
            s = res["grid"].get((v, h))
            if not s or s["n"] < min_n:
                cells.append(ui.tags.td("--"))
                continue
            cells.append(ui.tags.td(
                ui.tags.b(f"{s['avg_miss']:.1f}\"" if s["avg_miss"] is not None else "--"),
                f"{s['hit_pct']}% hit · {s['n']}" if s["hit_pct"] is not None else f"{s['n']} pitches",
                class_=_status(s["avg_miss"]),
                title=f"{s['n']} pitches set up {v.lower()} / {h.lower()}" + (f" -- usually misses {s['lean'].lower()}" if s["lean"] else ""),
            ))
        body.append(ui.tags.tr(*cells))
    grid = ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="gbo-lanes")
    rows = [{
        "Catcher set up": label, "Pitches": s["n"],
        "Avg miss": f"{s['avg_miss']:.1f}\"" if s["avg_miss"] is not None else "--",
        "Zone Exec %": f"{s['hit_pct']}%" if s["hit_pct"] is not None else "--",
        "Usually misses": s["lean"] or "no clear lean",
    } for label, s in res["rows"].items()]
    o = res["overall"]
    msg = takeaway(res)
    return ui.div(
        ui.tags.style(CSS),
        ui.p(ui.strong(msg), class_="small") if msg else None,
        ui.div(
            ui.div(grid, ui.p("Rows = height of the target, columns = side, from the hitter's point of view (In = toward him). "
                              "Big number = average miss; green within 8\", yellow within 12\", red beyond.",
                              class_="text-muted small")),
            ui.div(ui_helpers.render_dict_table(rows),
                   ui.p(f"All lanes: {o['n']} pitches, {o['avg_miss']:.1f}\" average miss" if o["avg_miss"] is not None else "",
                        class_="text-muted small"),
                   ui.p(f"{res['skipped']} pitch(es) left out -- no called spot, no location, or batter side unknown."
                        if res["skipped"] else "", class_="text-muted small"),
                   style="margin-top:10px;"),
        ),
    )
