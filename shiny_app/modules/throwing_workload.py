"""
GBO -- Throwing Workload (Nov 2026, Ryker). Every throw, not just charted
pitches: games + bullpens from GBO, catch play / long toss / plyos typed in,
sensor exports (PULSE / Motus, once GBO has them), and assumed warm-up and
catch-play throws for days nobody logged. Shows a 9-day vs 28-day ratio and
the weekly build vs pro benchmarks. Staff only, under Pitching.
Math: analytics/throwing_workload.py. Tables: throw_logs,
throwing_assumptions (python3 -m migrations.migrate_throwing_workload).
"""

from datetime import date, datetime, timedelta
from html import escape

from shiny import module, reactive, render, req, ui

from database import get_session
from models import Player, ThrowingAssumption, ThrowLog
from analytics import throwing_workload as tw
from analytics import throwing_workload_queries as twq
from services import throw_sensor_import as tsi

import ui_helpers
import throwing_workload_display as twd

VIEW_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Athletic Trainer",
              "Strength Coach")
EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Athletic Trainer", "Sports Scientist", "Strength Coach")
CATCH_DAYS = {"practice": "Team practice days (Team Schedule)", "weekdays": "Every day but Sunday",
              "daily": "Every day", "off": "Don't assume catch play"}
SOURCES = {"pulse": "PULSE", "motus": "Motus", "sensor": "Other sensor"}


def _pill(z):
    c = twd.ZONE_COLORS.get(z, "#7A8594")
    return (f'<span style="background:{c};color:#fff;border-radius:10px;padding:2px 10px;font-weight:700;'
            f'font-size:.8rem">{escape(z or "—")}</span>')


@module.ui
def throwing_workload_ui():
    return ui.div(
        ui_helpers.page_header("Throwing Workload",
                               "Every throw -- games, bullpens, catch play, warm-ups -- with the 9-day vs 28-day "
                               "ratio and the weekly build.", actions=ui_helpers.how_to_link("throwing_workload")),
        ui.output_ui("controls"),
        ui.output_ui("summary"),
        ui.output_ui("table"),
        ui.output_ui("detail"),
        ui.output_ui("editors"),
        ui.p("Counts: game and bullpen pitches come from GBO. Logged throws are typed in below. A sensor day (PULSE / "
             "Motus) uses the sensor's count for the whole day. Assumed throws (gray) fill in what nobody logged: a "
             "warm-up before each bullpen and outing, and catch play on throwing days -- log anything for a day, or "
             "'No throwing', and the assumed catch play goes away. Ratio = average throws a day over the last 9 days "
             "/ over the last 28. 0.8-1.2 in range, 0.7-0.8 or 1.2-1.3 watch, below 0.7 or above 1.3 outside. "
             "Hollow points = under 4 weeks of history, so the ratio is shaky. Benchmarks are pro numbers (Driveline "
             "2026 throwing volume, Jackson Sigman) -- reference lines, not targets for every pitcher. Guidance "
             "only: the trainer and coaches make the call.",
             class_="text-muted small", style="margin-top:14px;"),
    )


@module.server
def throwing_workload_server(input, output, session, app_state):
    tick = reactive.Value(0)
    plan_v = reactive.Value(None)

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in VIEW_ROLES

    def _can_edit():
        return app_state.is_authenticated() and app_state.role_name() in EDIT_ROLES

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        return ui.input_date("as_of", "As of", value=date.today(), width="200px")

    @reactive.calc
    def _table():
        req(_ok() and "as_of" in input and input.as_of())
        tick()
        db = get_session()
        try:
            return twq.team_table(db, input.as_of())
        finally:
            db.close()

    @render.ui
    def summary():
        if not _ok():
            return None
        rows = _table()
        z = [r.get("zone") for r in rows]
        thin = sum(1 for r in rows if r.get("ratio") is not None and not r.get("full_history"))
        cards = [{"label": "In range", "value": str(z.count("In range"))},
                 {"label": "Watch", "value": str(z.count("Watch"))},
                 {"label": "Outside", "value": str(z.count("Outside")), "delta_positive": False if z.count("Outside") else None,
                  "delta": "check these first" if z.count("Outside") else None},
                 {"label": "Building history", "value": str(thin), "delta": "under 4 weeks tracked", "delta_positive": None}]
        return ui_helpers.render_kpi_cards(cards)

    @render.ui
    def table():
        if not _ok():
            return None
        rows = _table()
        if not rows:
            return ui_helpers.empty_state("No active pitchers.")
        head = ("<tr><th style='text-align:left'>Pitcher</th><th>Last 7 days</th>"
                "<th title='Average throws a day over the last 9 days, shown per week'>9-day pace / wk</th>"
                "<th title='Average throws a day over the last 28 days, shown per week'>28-day pace / wk</th>"
                "<th>Ratio</th><th>Zone</th>"
                "<th title='Share of the last 28 days of throws that GBO assumed (nobody logged them)'>Assumed</th>"
                "<th title='Days in the last 28 with a sensor count'>Sensor days</th></tr>")
        body = []
        for r in rows:
            p = r["player"]
            if r.get("last7") is None:
                body.append(f"<tr><td style='text-align:left'><b>{escape(p.last_name)}, {escape(p.first_name)}</b></td>"
                            "<td colspan='7' class='text-muted small'>No throwing tracked yet</td></tr>")
                continue
            ratio = "—" if r["ratio"] is None else f"{r['ratio']:.2f}" + ("" if r["full_history"] else " <span class='text-muted small'>(new)</span>")
            body.append(
                f"<tr><td style='text-align:left'><b>{escape(p.last_name)}, {escape(p.first_name)}</b></td>"
                f"<td>{r['last7']}</td><td>{r['acute_week'] if r['acute_week'] is not None else '—'}</td>"
                f"<td>{r['chronic_week'] if r['chronic_week'] is not None else '—'}</td>"
                f"<td>{ratio}</td><td>{_pill(r['zone']) if r['zone'] else '—'}</td>"
                f"<td>{'—' if r['assumed_pct'] is None else str(r['assumed_pct']) + '%'}</td>"
                f"<td>{r['sensor_days'] or '—'}</td></tr>")
        html = (f"<div class='table-responsive'><table class='table table-sm' style='text-align:center'>"
                f"{head}{''.join(body)}</table></div>")
        return ui_helpers.card(ui.HTML(html), title="Pitching staff", right=f"as of {input.as_of():%a %b %d}")

    @reactive.calc
    def _choices():
        """Active pitchers -- kept apart from tick() so saving a log doesn't
        reset the pickers."""
        req(_ok())
        db = get_session()
        try:
            ps = (db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
                  .order_by(Player.last_name, Player.first_name).all())
            return {str(p.player_id): f"{p.name_last_first}" for p in ps}
        finally:
            db.close()

    @render.ui
    def detail():
        if not _ok():
            return None
        ch = _choices()
        if not ch:
            return None
        return ui_helpers.card(
            ui.div(ui.input_select("pid", "Pitcher", ch, width="260px"),
                   ui.input_select("weeks", "Show", {"4": "Last 4 weeks", "8": "Last 8 weeks", "12": "Last 12 weeks",
                                                     "20": "Last 20 weeks"}, selected="8", width="180px"),
                   style="display:flex;gap:12px;flex-wrap:wrap;"),
            ui.output_ui("charts"),
            title="One pitcher")

    @reactive.calc
    def _rows():
        req(_ok() and "pid" in input and input.pid() and "weeks" in input)
        tick()
        as_of = input.as_of()
        d0 = as_of - timedelta(days=7 * int(input.weeks()) - 1)
        db = get_session()
        try:
            return twq.pitcher_rows(db, int(input.pid()), d0, as_of)
        finally:
            db.close()

    @render.ui
    def charts():
        rows = _rows()
        if not any(r["tracked"] for r in rows):
            return ui_helpers.empty_state("No throwing tracked for him in this window.")
        weeks = tw.weekly(rows)
        last = rows[-1]
        tiles = ui.div(
            ui_helpers.kpi_tile("Last 7 days", sum(r["total"] for r in rows[-7:] if r["tracked"])),
            ui_helpers.kpi_tile("9-day pace", f"{last['acute_week']}/wk" if last["acute_week"] is not None else "—"),
            ui_helpers.kpi_tile("28-day pace", f"{last['chronic_week']}/wk" if last["chronic_week"] is not None else "—"),
            ui_helpers.kpi_tile("Ratio", f"{last['ratio']:.2f}" if last["ratio"] is not None else "—",
                                delta=last["zone"] + ("" if last["full_history"] else " · building history") if last["zone"] else None,
                                delta_positive=None if last["zone"] is None else last["zone"] == "In range"),
            class_="gbo-kpi-row", style="margin:8px 0;")
        return ui.div(tiles, ui.HTML(twd.daily_svg(rows)), ui.HTML(twd.ratio_svg(rows)), ui.HTML(twd.weekly_svg(weeks)))

    # ---------------- editors ----------------
    @render.ui
    def editors():
        if not _can_edit():
            return None
        ch = _choices()
        if not ch:
            return None
        with reactive.isolate():
            db = get_session()
            try:
                a = twq.assumptions(db)
            finally:
                db.close()
            today = input.as_of() if "as_of" in input else date.today()
        return ui.div(
            ui.layout_columns(
                ui_helpers.card(
                    ui.input_select("lg_pid", "Pitcher", ch),
                    ui.input_date("lg_date", "Date", value=today),
                    ui.input_select("lg_type", "Type", {t: t for t in tw.LOG_TYPES}),
                    ui.input_numeric("lg_throws", "Throws", value=40, min=0, max=500),
                    ui.input_numeric("lg_high", "High-intent throws (optional)", value=None, min=0, max=500),
                    ui.input_text("lg_note", "Note", placeholder="optional"),
                    ui.input_action_button("lg_save", "Save throws", class_="btn-sm btn-primary"),
                    ui.output_ui("recent"),
                    title="Log throws (catch play, long toss, plyos ...)"),
                ui.div(
                    ui_helpers.card(
                        ui.p("Used only on days nobody logged throws or a sensor count.", class_="text-muted small"),
                        ui.layout_columns(
                            ui.input_numeric("as_pen", "Warm-up before a bullpen", value=a["pen_warmup"], min=0, max=200),
                            ui.input_numeric("as_game", "Warm-up before a game outing", value=a["game_warmup"], min=0, max=200),
                            ui.input_numeric("as_catch", "Catch play on a throwing day", value=a["catch_play"], min=0, max=300),
                            col_widths=[4, 4, 4]),
                        ui.input_select("as_days", "Throwing days for catch play", CATCH_DAYS, selected=a["catch_play_days"]),
                        ui.input_action_button("as_save", "Save assumptions", class_="btn-sm btn-primary"),
                        title="Assumed throws"),
                    ui_helpers.card(
                        ui.p("Upload a CSV export -- one row per athlete per day, or one row per throw. GBO finds the "
                             "date, athlete and throw columns by name. Re-uploading the same days replaces them.",
                             class_="text-muted small"),
                        ui.input_select("sn_src", "Sensor", SOURCES),
                        ui.input_file("sn_file", "Export file (.csv)", accept=[".csv"]),
                        ui.output_ui("sn_preview"),
                        title="Import sensor export (PULSE / Motus)"),
                ),
                col_widths=[5, 7]),
        )

    @render.ui
    def recent():
        req("lg_pid" in input and input.lg_pid())
        tick()
        db = get_session()
        try:
            logs = twq.recent_logs(db, int(input.lg_pid()))
            if not logs:
                return ui.p("Nothing logged for him yet.", class_="text-muted small", style="margin-top:8px;")
            ch = {str(l.throw_log_id): f"{l.log_date:%b %d} · {l.throw_type} · {l.throws}"
                  + (f" ({l.source.upper()})" if l.source != "manual" else "") for l in logs}
            return ui.div(ui.hr(), ui.input_select("lg_del", "Recent entries", ch),
                          ui.input_action_button("lg_remove", "Remove entry", class_="btn-sm btn-outline-light"),
                          style="margin-top:8px;")
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.lg_save)
    def _lg_save():
        if not _can_edit():
            return
        typ = input.lg_type()
        n = 0 if typ == "No throwing" else input.lg_throws()
        if n is None or n < 0:
            ui.notification_show("Enter the number of throws.", type="warning")
            return
        if input.lg_date() is None or input.lg_date() > date.today():
            ui.notification_show("Pick a date that isn't in the future.", type="warning")
            return
        hi = input.lg_high()
        db = get_session()
        try:
            db.add(ThrowLog(player_id=int(input.lg_pid()), log_date=input.lg_date(), throw_type=typ, throws=int(n),
                            high_intent=int(hi) if hi is not None and typ != "No throwing" else None, source="manual",
                            notes=(input.lg_note() or "").strip() or None, created_by_user_id=app_state.user_id(),
                            created_at=datetime.utcnow()))
            db.commit()
            ui.notification_show("Throws saved.", type="message", duration=3)
            tick.set(tick() + 1)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_throwing_workload been run? ({e})", type="error", duration=10)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.lg_remove)
    def _lg_remove():
        if not _can_edit() or not input.lg_del():
            return
        db = get_session()
        try:
            db.query(ThrowLog).filter(ThrowLog.throw_log_id == int(input.lg_del()),
                                      ThrowLog.player_id == int(input.lg_pid())).delete(synchronize_session=False)
            db.commit()
            ui.notification_show("Entry removed.", type="message", duration=3)
            tick.set(tick() + 1)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.as_save)
    def _as_save():
        if not _can_edit():
            return
        vals = [input.as_pen(), input.as_game(), input.as_catch()]
        if any(v is None or v < 0 for v in vals):
            ui.notification_show("Each assumption needs a number (0 is fine).", type="warning")
            return
        db = get_session()
        try:
            s = db.query(ThrowingAssumption).filter(ThrowingAssumption.setting_id == 1).first()
            if s is None:
                s = ThrowingAssumption(setting_id=1)
                db.add(s)
            s.pen_warmup, s.game_warmup, s.catch_play = (int(v) for v in vals)
            s.catch_play_days = input.as_days()
            s.updated_by_user_id = app_state.user_id()
            s.updated_at = datetime.utcnow()
            db.commit()
            ui.notification_show("Assumptions saved.", type="message", duration=3)
            tick.set(tick() + 1)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_throwing_workload been run? ({e})", type="error", duration=10)
        finally:
            db.close()

    @reactive.effect
    def _sn_read():
        f = input.sn_file() if "sn_file" in input else None
        if not f:
            plan_v.set(None)
            return
        with open(f[0]["datapath"], "rb") as fh:
            data = fh.read()
        db = get_session()
        try:
            plan_v.set(tsi.build_plan(db, data))
        except Exception as e:
            plan_v.set({"ok": False, "error": f"Couldn't read that file ({e})."})
        finally:
            db.close()

    @render.ui
    def sn_preview():
        plan = plan_v()
        if plan is None:
            return None
        if not plan["ok"]:
            return ui.p(plan["error"], class_="text-danger small")
        days = plan["days"]
        players = sorted({d["player"] for d in days})
        close = sorted({f"{d['sheet_name']} → {d['player']}" for d in days if d["how"] == "close"})
        lines = [f"{len(days)} player-days, {len(players)} pitchers, {sum(d['throws'] for d in days)} throws, "
                 f"{min(d['date'] for d in days):%b %d} – {max(d['date'] for d in days):%b %d}."
                 + (" One row per throw, counted." if plan["per_throw"] else "")]
        if close:
            lines.append("Close name matches (check): " + "; ".join(close))
        if plan["unmatched"]:
            lines.append("No GBO player, skipped: " + ", ".join(plan["unmatched"]))
        if plan["bad_rows"]:
            lines.append(f"{plan['bad_rows']} rows had no readable date / name / count and were skipped.")
        found = ", ".join(f"{k} = '{v}'" for k, v in plan["columns"].items())
        lines.append(f"Columns used: {found}.")
        return ui.div(*[ui.p(t, class_="small", style="margin:2px 0;") for t in lines],
                      ui.input_action_button("sn_go", "Import", class_="btn-sm btn-primary"), style="margin-top:6px;")

    @reactive.effect
    @reactive.event(input.sn_go)
    def _sn_go():
        plan = plan_v()
        if not _can_edit() or not plan or not plan.get("ok"):
            return
        db = get_session()
        try:
            n = tsi.commit_plan(db, plan, input.sn_src(), app_state.user_id())
            ui.notification_show(f"Imported {n} player-days.", type="message", duration=4)
            plan_v.set(None)
            tick.set(tick() + 1)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Import failed, nothing saved ({e}).", type="error", duration=10)
        finally:
            db.close()
