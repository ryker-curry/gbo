"""
GBO -- WHOOP display pieces (Oct 2026 WHOOP pilot), shared by Player
Profile's Recovery tab and the Recovery Board page. Math lives in
analytics/whoop_metrics.py, charts in visualizations/whoop_charts.py.
Everyone, players included, can see this data (Ryker's call for the pilot).
"""

from datetime import datetime
from html import escape

from shiny import ui

import ui_helpers
from analytics import whoop_metrics as wm
from visualizations import whoop_charts as wc

ZONE_LABEL = {"green": "Green", "yellow": "Yellow", "red": "Red"}

EXPLAIN = (
    "HRV and resting heart rate are compared to HIS OWN normal (the 60 days before this week), never to teammates -- "
    "HRV varies a lot from person to person. 'Now' is his 7-day average; the shaded band is his normal range "
    "(average +/- half a standard deviation, the smallest change worth noticing). Ready = both inside or better than "
    "normal; Monitor = one is outside; Back off = clearly outside. It takes about 2-3 weeks of wearing it before the "
    "baseline means anything. WHOOP Strain is heart-rate load and does NOT count arm load from throwing -- use "
    "Arm Care & Availability for that. Guidance only: the trainer and coaches make the call."
)


def fmt(v, spec="{:.0f}", dash="—"):
    return dash if v is None else spec.format(v)


def synced_text(conn):
    if conn is None:
        return "Not connected"
    if conn.status == "error":
        return "Sync problem"
    if conn.last_synced_at:
        mins = (datetime.utcnow() - conn.last_synced_at).total_seconds() / 60
        if mins < 90:
            return f"Synced {int(mins)} min ago"
        if mins < 48 * 60:
            return f"Synced {int(mins // 60)} h ago"
        return f"Synced {conn.last_synced_at:%b %d}"
    return "Connected, waiting for first sync"


def readiness_chip(ready):
    return ui_helpers.status_chip(ready["status"], ready["label"])


def _vs_normal(ms, unit, spec):
    if ms["now"] is None:
        return ms["label"]
    base = f" vs normal {spec.format(ms['base_mean'])}" if ms["base_mean"] is not None else ""
    return f"7-day {spec.format(ms['now'])} {unit}{base} · {ms['label']}"


def kpi_row(ready):
    t = ready["today"] or {}
    zone = ready["zone"]
    hrv, rhr = ready["hrv"], ready["rhr"]
    need = t.get("sleep_need_hours")
    tiles = [
        ui_helpers.kpi_tile("Recovery today", fmt(t.get("recovery")), unit="%" if t.get("recovery") is not None else None,
                            delta=(ZONE_LABEL.get(zone, "") + (" (calibrating)" if t.get("calibrating") else "")) or "No score yet",
                            status=wm.ZONE_STATUS.get(zone)),
        ui_helpers.kpi_tile("HRV", fmt(t.get("hrv")), unit="ms" if t.get("hrv") is not None else None,
                            delta=_vs_normal(hrv, "ms", "{:.0f}"), status=hrv["status"] if hrv["status"] != "neutral" else None),
        ui_helpers.kpi_tile("Resting HR", fmt(t.get("rhr")), unit="bpm" if t.get("rhr") is not None else None,
                            delta=_vs_normal(rhr, "bpm", "{:.0f}"), status=rhr["status"] if rhr["status"] != "neutral" else None),
        ui_helpers.kpi_tile("Sleep last night", fmt(t.get("sleep_hours"), "{:.1f}"), unit="h" if t.get("sleep_hours") is not None else None,
                            delta=(f"needed {need:.1f} h" if need else "") + (f" · {t['sleep_performance']:.0f}% of need" if t.get("sleep_performance") is not None else ""),
                            status=("watch" if (t.get("sleep_hours") is not None and need and t["sleep_hours"] < need - 1) else None)),
        ui_helpers.kpi_tile("Sleep, 7-day avg", fmt(ready["sleep_avg_7d"], "{:.1f}"), unit="h" if ready["sleep_avg_7d"] is not None else None,
                            delta=(f"{ready['sleep_debt_7d']:+.1f} h short of need this week" if ready["sleep_debt_7d"] and ready["sleep_debt_7d"] > 0
                                   else ("met his need this week" if ready["sleep_debt_7d"] is not None else None))),
        ui_helpers.kpi_tile("Day strain", fmt(t.get("strain"), "{:.1f}"), delta="0-21 scale, heart-rate load"),
    ]
    return ui.div(*tiles, class_="gbo-kpi-row", style="margin-bottom:16px;")


def trend_cards(rows, ready):
    rolling = wm.rolling_hrv(rows)
    band = ready["hrv"].get("band")
    def chart(svg, empty):
        return ui.HTML(svg) if svg else ui_helpers.empty_state(empty)
    return ui.div(
        ui_helpers.card(chart(wc.hrv_svg(rows, rolling, band), "No HRV yet."), title="HRV",
                        right="dots = each morning · line = 7-day average · band = his normal"),
        ui_helpers.card(chart(wc.recovery_svg(rows), "No recovery scores yet."), title="Recovery",
                        right="WHOOP zones: green 67+ · yellow 34-66 · red 0-33"),
        ui_helpers.card(chart(wc.sleep_svg(rows), "No sleep yet."), title="Sleep",
                        right="bars = hours slept (gold = 30+ min short) · dashed = hours needed"),
        ui_helpers.card(chart(wc.strain_svg(rows), "No strain yet."), title="Day strain",
                        right="does not include arm load from throwing"),
    )


def _cell(v, spec="{:.0f}"):
    return ui.tags.td(fmt(v, spec), style="text-align:right;font-variant-numeric:tabular-nums")


def performance_section(games, is_pitcher):
    """Recovery vs performance: a dot per game + a table of every game."""
    if not games:
        return ui_helpers.card(ui_helpers.empty_state(
            "No charted games in this date range yet. Once he has games and WHOOP days, each game shows up here "
            "next to the recovery and sleep he had that morning."), title="Recovery vs performance")
    with_whoop = [g for g in games if g["has_whoop"]]
    if is_pitcher:
        y_key, y_label, y_fmt = "fb_velo", "FB velo (mph)", "{:.1f}"
    else:
        y_key, y_label, y_fmt = "woba", "wOBA", "{:.3f}"
    rel_rec = wm.relationship(with_whoop, "recovery", y_key)
    rel_sleep = wm.relationship(with_whoop, "sleep_hours", y_key)
    rel_hrv = wm.relationship(with_whoop, "hrv_z", y_key)
    scatter = wc.scatter_svg(with_whoop, "recovery", y_key, "Recovery % that morning", y_label, rel_rec, y_fmt)
    scatter2 = wc.scatter_svg(with_whoop, "sleep_hours", y_key, "Hours slept the night before", y_label, rel_sleep, y_fmt)

    if is_pitcher:
        head = ["Date", "Opponent", "Pitches", "FB velo", "FB max", "Strike %", "Zone Exec %", "Recovery", "HRV vs normal", "Sleep h", "Strain day before"]
    else:
        head = ["Date", "Opponent", "PA", "AVG", "wOBA", "K %", "Recovery", "HRV vs normal", "Sleep h", "Strain day before"]
    body = []
    for g in reversed(games):
        z = g.get("hrv_z")
        zt = "—" if z is None else ("low" if z <= -0.5 else ("high" if z >= 0.5 else "normal")) + f" ({z:+.1f})"
        zone = wm.recovery_zone(g.get("recovery"))
        rec_style = f"color:var(--gbo-status-{wm.ZONE_STATUS[zone]});font-weight:700" if zone else ""
        cells = [ui.tags.td(g["day"].strftime("%b %d")), ui.tags.td(g["opponent"])]
        if is_pitcher:
            cells += [_cell(g.get("pitches")), _cell(g.get("fb_velo"), "{:.1f}"), _cell(g.get("fb_max"), "{:.1f}"),
                      _cell(g.get("strike_pct"), "{:.1f}"), _cell(g.get("zone_exec_pct"), "{:.1f}")]
        else:
            cells += [_cell(g.get("pa")), _cell(g.get("avg"), "{:.3f}"), _cell(g.get("woba"), "{:.3f}"), _cell(g.get("k_pct"), "{:.1f}")]
        cells += [ui.tags.td(fmt(g.get("recovery")) + ("%" if g.get("recovery") is not None else ""), style="text-align:right;" + rec_style),
                  ui.tags.td(zt, style="text-align:right"), _cell(g.get("sleep_hours"), "{:.1f}"), _cell(g.get("prev_strain"), "{:.1f}")]
        body.append(ui.tags.tr(*cells))
    table = ui.div(ui.tags.table(ui.tags.thead(ui.tags.tr(*[ui.tags.th(h) for h in head])), ui.tags.tbody(*body),
                                 class_="table table-sm"), class_="table-responsive")
    reads = ui.tags.ul(
        ui.tags.li(ui.strong(f"Recovery vs {y_label}: "), rel_rec["read"]),
        ui.tags.li(ui.strong(f"Sleep vs {y_label}: "), rel_sleep["read"]),
        ui.tags.li(ui.strong(f"HRV vs normal vs {y_label}: "), rel_hrv["read"]),
        class_="small",
    )
    charts = ui.div(
        ui.div(ui.HTML(scatter) if scatter else ui_helpers.empty_state("No games with WHOOP data yet."), style="flex:1 1 300px;min-width:0"),
        ui.div(ui.HTML(scatter2) if scatter2 else None, style="flex:1 1 300px;min-width:0"),
        style="display:flex;gap:16px;flex-wrap:wrap;",
    )
    note = ("Each dot is one game: the recovery/sleep he had that morning against how he threw. These are his own games "
            "only, so the read gets more trustworthy as games pile up -- one bad night rarely explains one outing."
            if is_pitcher else
            "Each dot is one game. Single-game wOBA is noisy, so give this a lot of games before reading much into it.")
    return ui_helpers.card(charts, reads, ui.p(note, class_="text-muted small"), table, title="Recovery vs performance",
                           right=f"{len(with_whoop)} of {len(games)} games have WHOOP data")


def connection_card(conn, open_link, can_manage, ns_make, ns_sync, allow_sync=True):
    """Connection status + the Connect / Sync buttons. ns_make/ns_sync are the
    (namespaced inside the module) input ids for the two buttons."""
    if conn is None:
        msg = ui.p("No WHOOP connected for this player yet. Make a Connect WHOOP link and text it to him -- he opens "
                   "it on his phone, signs into WHOOP, and taps Allow. His last 90 days come in right away, then it "
                   "updates every morning and afternoon.")
    elif conn.status == "error":
        msg = ui.div(ui.p(ui_helpers.status_chip("flag", "Sync problem"), " ", escape(conn.last_error or "")),
                     ui.p("If he removed GBO in the WHOOP app or it's been a long time, make a new link and have him connect again.",
                          class_="small text-muted"))
    else:
        who = f" as {conn.whoop_name}" if conn.whoop_name else ""
        msg = ui.p(ui_helpers.status_chip("good", "Connected"), f" WHOOP account{who} · {synced_text(conn)}.")
    btns = []
    if can_manage:
        btns.append(ui.input_action_button(ns_make, "Make Connect WHOOP link" if conn is None else "Make a new connect link",
                                           class_="btn-primary" if conn is None else "btn-outline-light"))
    if conn is not None and allow_sync:
        btns.append(ui.input_action_button(ns_sync, "Sync now", class_="btn-outline-light"))
    link_block = None
    if open_link:
        url, exp = open_link
        link_block = ui.div(
            ui.p(ui.strong("Connect link"), f" (one-time, expires {exp:%b %d}). Copy it and text it to him:", class_="small", style="margin:10px 0 4px"),
            ui.tags.input(type="text", value=url, readonly=True, onclick="this.select()",
                          class_="form-control form-control-sm", style="font-family:monospace;"),
        )
    return ui_helpers.card(msg, ui.div(*btns, style="display:flex;gap:8px;flex-wrap:wrap;") if btns else None, link_block,
                           title="WHOOP", right=ui_helpers.how_to_link("whoop"))
