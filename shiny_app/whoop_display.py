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


def _day_label(d):
    return d.strftime("%a %b %d").replace(" 0", " ") if d else ""


def freshness_note(ready):
    """Warn when his band hasn't synced in a while."""
    sd = ready.get("stale_days")
    if sd is None or sd <= 1:
        return None
    return ui.div(ui_helpers.status_chip("watch", f"Last WHOOP data {sd} days ago"),
                  " Numbers below are from his latest synced day. He needs to wear the band and open the WHOOP app so it syncs.",
                  class_="small", style="margin:4px 0 10px;")


def kpi_row(ready):
    t = ready["today"] or {}
    zone = ready["zone"]
    hrv, rhr = ready["hrv"], ready["rhr"]
    need = t.get("sleep_need_hours")
    when = _day_label(t.get("day"))
    tiles = [
        ui_helpers.kpi_tile(f"Recovery · {when}" if when else "Recovery", fmt(t.get("recovery")), unit="%" if t.get("recovery") is not None else None,
                            delta=(ZONE_LABEL.get(zone, "") + (" (calibrating)" if t.get("calibrating") else "")) or "No score yet",
                            status=wm.ZONE_STATUS.get(zone)),
        ui_helpers.kpi_tile("HRV", fmt(t.get("hrv")), unit="ms" if t.get("hrv") is not None else None,
                            delta=_vs_normal(hrv, "ms", "{:.0f}"), status=hrv["status"] if hrv["status"] != "neutral" else None),
        ui_helpers.kpi_tile("Resting HR", fmt(t.get("rhr")), unit="bpm" if t.get("rhr") is not None else None,
                            delta=_vs_normal(rhr, "bpm", "{:.0f}"), status=rhr["status"] if rhr["status"] != "neutral" else None),
        ui_helpers.kpi_tile("Sleep", fmt(t.get("sleep_hours"), "{:.1f}"), unit="h" if t.get("sleep_hours") is not None else None,
                            delta=(f"needed {need:.1f} h" if need else "") + (f" · {t['sleep_performance']:.0f}% of need" if t.get("sleep_performance") is not None else ""),
                            status=("watch" if (t.get("sleep_hours") is not None and need and t["sleep_hours"] < need - 1) else None)),
        ui_helpers.kpi_tile("Sleep, 7-day avg", fmt(ready["sleep_avg_7d"], "{:.1f}"), unit="h" if ready["sleep_avg_7d"] is not None else None,
                            delta=(f"{ready['sleep_debt_7d']:.1f} h short of his need over 7 nights" if ready["sleep_debt_7d"] and ready["sleep_debt_7d"] > 0
                                   else ("met his need this week" if ready["sleep_debt_7d"] is not None else None))),
        ui_helpers.kpi_tile("Day strain", fmt(t.get("strain"), "{:.1f}"), delta="0-21 scale, heart-rate load"),
    ]
    return ui.div(*tiles, class_="gbo-kpi-row", style="margin-bottom:16px;")


def _hm(hours):
    if hours is None:
        return "—"
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h}h {m:02d}m"


def _clock(ts):
    return ts.strftime("%I:%M %p").lstrip("0") if ts else "—"


def sleep_breakdown(t):
    """Latest night: bed -> wake, a stage bar, and the sleep numbers."""
    if not t or t.get("sleep_hours") is None:
        return ui_helpers.card(ui_helpers.empty_state("No scored sleep yet."), title="Sleep breakdown")
    stages = [("Light", t.get("light_hours"), "var(--gbo-series-1)"), ("Deep (SWS)", t.get("deep_hours"), "#7A4FB5"),
              ("REM", t.get("rem_hours"), "#2E9C62"), ("Awake", t.get("awake_hours"), "var(--gbo-text-muted)")]
    total = sum(v for _, v, _ in stages if v) or 1
    segs, legend = [], []
    for name, v, color in stages:
        if not v:
            continue
        pct = 100 * v / total
        segs.append(ui.div(title=f"{name}: {_hm(v)} ({pct:.0f}%)",
                           style=f"width:{pct:.2f}%;background:{color};height:100%;"))
        legend.append(ui.span(ui.span(style=f"display:inline-block;width:10px;height:10px;border-radius:2px;background:{color};margin-right:5px;"),
                              f"{name} {_hm(v)} ({pct:.0f}%)", style="margin-right:14px;white-space:nowrap;"))
    bar = ui.div(*segs, style="display:flex;height:18px;border-radius:6px;overflow:hidden;margin:10px 0 6px;")
    need = t.get("sleep_need_hours")
    tiles = ui.div(
        ui_helpers.kpi_tile("Asleep", _hm(t.get("sleep_hours")), delta=f"needed {_hm(need)}" if need else None),
        ui_helpers.kpi_tile("Sleep performance", fmt(t.get("sleep_performance")), unit="%" if t.get("sleep_performance") is not None else None,
                            delta="hours slept vs hours needed"),
        ui_helpers.kpi_tile("Efficiency", fmt(t.get("sleep_efficiency")), unit="%" if t.get("sleep_efficiency") is not None else None,
                            delta="time asleep while in bed"),
        ui_helpers.kpi_tile("Consistency", fmt(t.get("sleep_consistency")), unit="%" if t.get("sleep_consistency") is not None else None,
                            delta="same bed/wake times as recent nights",
                            status=("watch" if (t.get("sleep_consistency") or 100) < 50 else None)),
        ui_helpers.kpi_tile("Wake-ups", fmt(t.get("disturbances")), delta="disturbances"),
        ui_helpers.kpi_tile("Breathing rate", fmt(t.get("resp_rate"), "{:.1f}"), unit="/min" if t.get("resp_rate") is not None else None),
        class_="gbo-kpi-row",
    )
    head = ui.p(ui.strong(f"{_clock(t.get('bedtime'))} to {_clock(t.get('wake_time'))}"),
                f" · in bed {_hm(t.get('in_bed_hours'))}", class_="small", style="margin:0;")
    return ui_helpers.card(head, bar, ui.div(*legend, class_="small text-muted", style="display:flex;flex-wrap:wrap;margin-bottom:12px;"),
                           tiles, title=f"Sleep breakdown · night before {_day_label(t.get('day'))}",
                           right="deep sleep = physical recovery · REM = mental recovery")


def health_card(ready):
    items = ready.get("health") or []
    if not any(i["value"] is not None for i in items):
        return ui_helpers.card(ui_helpers.empty_state("No health readings yet."), title="Health signals")
    tiles = []
    for i in items:
        if i["value"] is None:
            continue
        val = i["fmt"].format(i["value"])
        if i["base"] is not None:
            delta = f"normal {i['fmt'].format(i['base'])} · {i['diff']:+.1f} {i['unit']}"
        else:
            delta = f"building baseline ({i['n_base']}/{wm.HEALTH_MIN} days)"
        tiles.append(ui_helpers.kpi_tile(f"{i['label']} · {_day_label(i['day'])}", val, unit=i["unit"], delta=delta,
                                         status=i["status"] if i["status"] != "neutral" else None))
    flagged = [i["label"].lower() for i in items if i["status"] in ("watch", "flag")]
    note = (f"Worth a check-in: {', '.join(flagged)} outside his normal. Skin temp or breathing rate rising together "
            "is often the first sign of getting sick.") if flagged else "All inside his normal range."
    return ui_helpers.card(ui.div(*tiles, class_="gbo-kpi-row"), ui.p(note, class_="small text-muted", style="margin-top:8px;"),
                           title="Health signals vs his normal", right="compared to his previous 30 days")


_CELL_COLOR = {"good": "var(--gbo-status-good)", "watch": "var(--gbo-status-watch)", "flag": "var(--gbo-status-flag)"}


def daily_table(rows):
    """Every day, every number, newest first. Colored vs his own normal."""
    if not rows:
        return None
    flags = wm.day_flags(rows)
    cols = [("Recovery", "recovery", "{:.0f}%"), ("HRV", "hrv", "{:.0f}"), ("RHR", "rhr", "{:.0f}"),
            ("Slept", "sleep_hours", None), ("Needed", "sleep_need_hours", None), ("Sleep %", "sleep_performance", "{:.0f}"),
            ("Effic. %", "sleep_efficiency", "{:.0f}"), ("Consist. %", "sleep_consistency", "{:.0f}"),
            ("Deep", "deep_hours", None), ("REM", "rem_hours", None), ("Wake-ups", "disturbances", "{:.0f}"),
            ("Bed", "bedtime", "clock"), ("Wake", "wake_time", "clock"),
            ("Strain", "strain", "{:.1f}"), ("SpO2", "spo2", "{:.1f}"), ("Skin \u00b0C", "skin_temp", "{:.1f}"),
            ("Breaths", "resp_rate", "{:.1f}")]
    head = ui.tags.tr(ui.tags.th("Day"), *[ui.tags.th(c, style="text-align:right;white-space:nowrap;") for c, _, _ in cols])
    body = []
    for r in reversed(rows):
        f = flags.get(r["day"], {})
        cells = [ui.tags.td(_day_label(r["day"]), style="white-space:nowrap;")]
        for _, key, spec in cols:
            v = r.get(key)
            if v is None:
                text = "—"
            elif spec is None:
                text = _hm(v)
            elif spec == "clock":
                text = _clock(v)
            else:
                text = spec.format(v)
            style = "text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;"
            color = None
            if key == "recovery" and v is not None:
                color = _CELL_COLOR.get(wm.ZONE_STATUS.get(wm.recovery_zone(v)))
            elif key in f and f[key]:
                color = _CELL_COLOR.get(f[key])
            if color:
                style += f"color:{color};font-weight:700;"
            cells.append(ui.tags.td(text, style=style))
        body.append(ui.tags.tr(*cells))
    table = ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm",
                                 style="font-size:.82rem;"),
                   class_="table-responsive", style="max-height:520px;overflow:auto;")
    return ui_helpers.card(table, ui.p("Colored vs his own normal: recovery uses WHOOP's zones; HRV, resting HR, SpO2, skin temp "
                                       "and breathing rate are green/gold/red when clearly better / off / well off his previous "
                                       "30-60 days. Blank days = band not worn or not synced.", class_="small text-muted"),
                           title="Day by day", right=f"{len(rows)} days")


def workouts_table(workouts):
    if not workouts:
        return ui_helpers.card(ui_helpers.empty_state("No WHOOP-tracked workouts in this range."), title="Workouts")
    head = ui.tags.tr(*[ui.tags.th(h, style="white-space:nowrap;") for h in
                        ["Day", "Start", "Activity", "Length", "Strain", "Avg HR", "Max HR", "Heart-rate zones"]])
    zone_colors = ["#8A8A8E", "#3E8EDE", "#2E9C62", "#B58A22", "#D9782A", "#D94F3D"]
    body = []
    for w in workouts:
        z = w["zones"]
        tot = sum(z.values()) or 1
        bar = ui.div(*[ui.div(title=f"{lbl}: {mins:.0f} min", style=f"width:{100 * mins / tot:.2f}%;background:{zone_colors[k]};height:100%;")
                       for k, (lbl, mins) in enumerate(z.items()) if mins],
                     style="display:flex;height:12px;min-width:140px;border-radius:4px;overflow:hidden;")
        body.append(ui.tags.tr(
            ui.tags.td(_day_label(w["day"]), style="white-space:nowrap;"), ui.tags.td(_clock(w["start"])),
            ui.tags.td(w["sport"]), ui.tags.td(f"{w['minutes']:.0f} min" if w["minutes"] else "—"),
            ui.tags.td(fmt(w["strain"], "{:.1f}")), ui.tags.td(fmt(w["avg_hr"])), ui.tags.td(fmt(w["max_hr"])),
            ui.tags.td(bar),
        ))
    legend = ui.p(*[ui.span(ui.span(style=f"display:inline-block;width:9px;height:9px;background:{c};margin:0 4px 0 10px;"), lbl)
                    for c, lbl in zip(zone_colors, ["Z0 rest", "Z1", "Z2", "Z3", "Z4", "Z5 max"])], class_="small text-muted")
    return ui_helpers.card(ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                                  class_="table-responsive", style="max-height:420px;overflow-y:auto;"),
                           legend, ui.p("Heart-rate load only -- throwing stress on the arm isn't captured here; see Arm Care.",
                                        class_="small text-muted"),
                           title="Workouts", right=f"{len(workouts)} sessions")


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


# ---------------------------------------------------------------------------
# WHOOP vs performance explorer (Oct 2026) -- analytics/whoop_performance.py
# ---------------------------------------------------------------------------
_ZONE_TXT = {"green": "Green (67+)", "yellow": "Yellow (34-66)", "red": "Red (0-33)"}


def explorer_controls(outcome_id, predictor_id, outcomes, sel_outcome=None, sel_predictor=None):
    from analytics import whoop_performance as wp
    preds = {k: v[0] for k, v in wp.PREDICTORS.items()}
    so = sel_outcome if sel_outcome in outcomes else next(iter(outcomes), None)
    sp = sel_predictor if sel_predictor in preds else "recovery"
    return ui.div(
        ui.input_select(outcome_id, "Performance", outcomes, selected=so, width="320px"),
        ui.input_select(predictor_id, "Compared with (WHOOP)", preds, selected=sp, width="300px"),
        style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-end;",
    )


def _zone_bars(zones, fmt_v, diff=False, raw=None):
    """Bars = difference vs his own average (so tiny raw gaps aren't
    exaggerated); text shows the raw average too when `raw` is given."""
    vals = [m for m, n in zones.values() if m is not None]
    if not vals:
        return ui.p("No sessions on scored WHOOP mornings yet.", class_="small text-muted")
    lo, hi = min(vals + ([0] if diff else [])), max(vals + ([0] if diff else []))
    span = (hi - lo) or 1
    rows = []
    for z in ("green", "yellow", "red"):
        m, n = zones.get(z, (None, 0))
        color = _CELL_COLOR[wm.ZONE_STATUS[z]]
        if m is None:
            bar, txt = None, "no sessions"
        else:
            w = 15 + 85 * (m - lo) / span if not diff else 10 + 90 * abs(m) / (max(abs(lo), abs(hi)) or 1)
            bar = ui.div(style=f"width:{w:.0f}%;height:14px;border-radius:4px;background:{color};")
            raw_txt = f"{fmt_v.format(raw[z][0])} · " if raw and raw.get(z, (None,))[0] is not None else ""
            txt = raw_txt + (f"{m:+.2f} vs his avg" if diff else fmt_v.format(m)) + f" · {n} session{'s' if n != 1 else ''}"
        rows.append(ui.div(ui.div(_ZONE_TXT[z], style="width:120px;flex:none;", class_="small"),
                           ui.div(bar, style="flex:1;min-width:80px;"),
                           ui.div(txt, class_="small", style="width:250px;flex:none;text-align:right;font-variant-numeric:tabular-nums;"),
                           style="display:flex;gap:10px;align-items:center;margin:6px 0;"))
    rows.append(ui.p("Bar length = how far from his own average (longer = bigger difference).", class_="small text-muted", style="margin:2px 0 0;"))
    return ui.div(*rows)


def _value_fmt(outcome_key):
    return "{:.1f} mph" if outcome_key.startswith("fb_") else "{:.2f}"


def player_explorer(paired, n_sessions, outcome_key, outcome_label, predictor):
    from analytics import whoop_performance as wp
    pred_label, pred_fmt = wp.PREDICTORS[predictor]
    fmt_v = _value_fmt(outcome_key)
    if n_sessions == 0:
        return ui_helpers.empty_state(f"No {outcome_label} sessions on record for him yet.")
    if not paired:
        return ui_helpers.empty_state(f"He has {n_sessions} {outcome_label} session{'s' if n_sessions != 1 else ''}, but none on a day "
                                      "he has WHOOP data. They'll pair up once both are being collected.")
    read = wp.player_read(paired, predictor)
    svg = wc.scatter_svg(paired, predictor, "value", pred_label, outcome_label, read, fmt_v.replace(" mph", ""))
    recent = sorted(paired, key=lambda p: p["day"], reverse=True)[:12]
    head = ui.tags.tr(*[ui.tags.th(h) for h in ["Day", outcome_label, "vs his avg", "Recovery", "HRV vs normal", "Slept", "Strain day before"]])
    body = [ui.tags.tr(
        ui.tags.td(_day_label(p["day"])), ui.tags.td(fmt_v.format(p["value"])), ui.tags.td(f"{p['diff']:+.2f}"),
        ui.tags.td(fmt(p.get("recovery")) + ("%" if p.get("recovery") is not None else ""),
                   style=(f"color:{_CELL_COLOR[wm.ZONE_STATUS[p['zone']]]};font-weight:700;" if p.get("zone") else "")),
        ui.tags.td(fmt(p.get("hrv_z"), "{:+.1f}")), ui.tags.td(_hm(p.get("sleep_hours"))), ui.tags.td(fmt(p.get("prev_strain"), "{:.1f}")),
    ) for p in recent]
    return ui.div(
        ui.p(ui.strong(f"{outcome_label} by recovery zone that morning"), class_="small", style="margin:8px 0 2px;"),
        _zone_bars(wp.zone_summary(paired, "diff"), fmt_v, diff=True, raw=wp.zone_summary(paired)),
        ui.div(ui.HTML(svg) if svg else ui.p(f"No sessions with {pred_label.lower()} yet.", class_="small text-muted"), style="margin-top:12px;"),
        ui.p(ui.strong(f"{pred_label} vs {outcome_label}: "), read["read"], class_="small"),
        ui.p(f"{len(paired)} of his {n_sessions} sessions fall on a WHOOP day. One session rarely means much -- look for the pattern "
             f"over {wp.MIN_SESSIONS}+.", class_="small text-muted"),
        ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm", style="font-size:.85rem;"),
               class_="table-responsive"),
    )


def team_explorer(res, outcome_key, outcome_label, predictor):
    from analytics import whoop_performance as wp
    pred_label = wp.PREDICTORS[predictor][0]
    if not res["players"]:
        return ui_helpers.empty_state("No players with WHOOP connected yet.")
    fmt_v = "{:+.2f}"
    head = ui.tags.tr(ui.tags.th("Player"), ui.tags.th("Paired sessions"), ui.tags.th("His own r"))
    body = [ui.tags.tr(ui.tags.td(p["name"]), ui.tags.td(str(p["n"])),
                       ui.tags.td("—" if p["r"] is None else f"{p['r']:+.2f}" + ("" if p["n"] >= wp.MIN_SESSIONS else " (early)")))
            for p in sorted(res["players"], key=lambda p: -p["n"])]
    return ui.div(
        ui.p(ui.strong(f"{outcome_label}, vs each player's own average, by recovery zone"), class_="small", style="margin:8px 0 2px;"),
        _zone_bars(res["zones"], fmt_v, diff=True),
        ui.p(ui.strong(f"{pred_label} vs {outcome_label}: "), res["read"], class_="small", style="margin-top:10px;"),
        ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm", style="font-size:.85rem;"),
               class_="table-responsive"),
        ui.p("Each player is compared with himself first (his sessions vs his own average, his WHOOP vs his own normal), then pooled "
             "-- a repeated-measures correlation -- so differences BETWEEN players (a 92 vs an 84 mph arm) don't fake a relationship. "
             "Guidance for spotting patterns, not proof of cause.", class_="small text-muted"),
    )
