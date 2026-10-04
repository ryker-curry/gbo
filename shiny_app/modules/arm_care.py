"""
GBO -- Arm Care & Availability board (Oct 2026, Ryker approved; staff only,
under Pitching). "Who can throw today?" -- one row per active pitcher with
last outing, rest, 7-day load, workload ratio and a status. Coaches can set
a Hold / Limited / Available override with a note and end date, and plan
outings (the board warns when he won't be rested by then). Math:
analytics/arm_care.py. Table: models.PitcherAvailability
(python3 -m migrations.migrate_pitcher_availability).
"""

from datetime import date, datetime, timedelta
from html import escape

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, PitcherAvailability
from analytics import arm_care

import ui_helpers

VIEW_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator",
              "Athletic Trainer", "Strength Coach")
EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Athletic Trainer")
STATUS_COLORS = {"Available": "#2E9C62", "Limited": "#B58A22", "Down": "#D94F3D", "Hold": "#7A4FB5"}


def _pill(status):
    c = STATUS_COLORS.get(status, "#7A8594")
    return (f'<span style="background:{c};color:#fff;border-radius:10px;padding:2px 10px;font-weight:700;'
            f'font-size:.8rem">{escape(status)}</span>')


@module.ui
def arm_care_ui():
    return ui.div(
        ui_helpers.page_header("Arm Care & Availability",
                               "Who can throw today -- rest, recent workload and coach holds in one place."),
        ui.output_ui("controls"),
        ui.output_ui("summary"),
        ui.output_ui("table"),
        ui.output_ui("editor"),
        ui.p("Rest chart (days off after an outing): 1-30 pitches 0 · 31-45 1 · 46-60 2 · 61-75 3 · 76+ 4. "
             "Workload ratio = last 7 days vs his normal week over the last 4 (0.8-1.3 normal, 1.3-1.5 caution, "
             "over 1.5 spike). Guidance only -- the trainer and coaches make the call.",
             class_="text-muted small", style="margin-top:14px;"),
    )


@module.server
def arm_care_server(input, output, session, app_state):
    tick = reactive.Value(0)

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
    def _rows():
        req(_ok() and "as_of" in input and input.as_of())
        tick()
        db = get_session()
        try:
            return arm_care.board(db, input.as_of())
        finally:
            db.close()

    @render.ui
    def summary():
        if not _ok():
            return None
        rows = _rows()
        counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("Available", "Limited", "Down", "Hold")}
        warns = sum(1 for r in rows for p in r["plans"] if p["warn"])
        cards = [{"label": s, "value": str(n)} for s, n in counts.items()]
        if warns:
            cards.append({"label": "Planned outings at risk", "value": str(warns), "delta_positive": False,
                          "delta": "see the Plans column"})
        return ui_helpers.render_kpi_cards(cards)

    @render.ui
    def table():
        if not _ok():
            return None
        rows = _rows()
        if not rows:
            return ui_helpers.empty_state("No active pitchers.")
        as_of = input.as_of()
        head = ("<tr><th style='text-align:left'>Pitcher</th><th>Status</th><th style='text-align:left'>Why</th>"
                "<th>Last outing</th><th>Pitches</th><th>Days rest</th><th>Needs</th><th>Ready</th>"
                "<th>Last 7 days</th><th>Workload</th><th style='text-align:left'>Plans</th></tr>")
        body = []
        for r in rows:
            p = r["player"]
            last = "—" if r["last"] is None else (r["last"].strftime("%a %b %d") + (" (game)" if r["last_was_game"] else " (pen)"))
            ready = "now" if r["ready_on"] is None or r["ready_on"] <= as_of else r["ready_on"].strftime("%a %b %d")
            ratio = r["ratio_label"] + (f" ({r['ratio']:.2f})" if r["ratio"] is not None else "")
            rcolor = {"Spike": "#D94F3D", "Caution": "#B58A22", "Under-thrown": "#5B8DEF"}.get(r["ratio_label"], "inherit")
            plans = "<br>".join(
                f"{escape(pl['type'] or 'Outing')} {pl['date'].strftime('%a %b %d')}"
                + (f" <span style='color:#D94F3D'>⚠ {escape(pl['warn'])}</span>" if pl["warn"] else "")
                for pl in r["plans"]) or "—"
            src = " <span class='text-muted small'>(coach)</span>" if r["source"] == "coach" else ""
            body.append(
                f"<tr><td style='text-align:left'><b>{escape(p.last_name)}, {escape(p.first_name)}</b></td>"
                f"<td>{_pill(r['status'])}{src}</td><td style='text-align:left' class='small'>{escape(r['reason'])}</td>"
                f"<td>{last}</td><td>{r['last_pitches'] or '—'}</td>"
                f"<td>{'—' if r['days_rest'] is None else r['days_rest']}</td>"
                f"<td>{'—' if r['required_rest'] is None else r['required_rest']}</td><td>{ready}</td>"
                f"<td>{r['seven_day']}</td><td style='color:{rcolor}'>{escape(ratio)}</td>"
                f"<td style='text-align:left' class='small'>{plans}</td></tr>")
        html = (f"<div class='table-responsive'><table class='table table-sm' style='text-align:center'>"
                f"{head}{''.join(body)}</table></div>")
        return ui_helpers.card(ui.HTML(html), title="Pitching staff", right=f"as of {as_of.strftime('%a %b %d')}")

    # ---------------- editor ----------------
    @render.ui
    def editor():
        if not _can_edit():
            return None
        rows = _rows()
        if not rows:
            return None
        choices = {str(r["player"].player_id): f"{r['player'].last_name}, {r['player'].first_name}" for r in
                   sorted(rows, key=lambda r: r["player"].last_name)}
        today = input.as_of() if "as_of" in input else date.today()
        return ui.layout_columns(
            ui_helpers.card(
                ui.input_select("ed_pitcher", "Pitcher", choices),
                ui.input_radio_buttons("ed_status", "Set status", {"Hold": "Hold (can't throw)", "Limited": "Limited",
                                                                    "Available": "Available (clear rest flag)"},
                                       selected="Hold", inline=True),
                ui.input_date("ed_until", "Through (leave as-is for open-ended)", value=None),
                ui.input_text("ed_note", "Note", placeholder="e.g. back tightness, no pens till Thu"),
                ui.div(ui.input_action_button("ed_save", "Save status", class_="btn-sm btn-primary"),
                       ui.input_action_button("ed_clear", "Clear coach status", class_="btn-sm btn-outline-light"),
                       style="display:flex;gap:8px;"),
                title="Coach status (overrides the automatic one)",
            ),
            ui_helpers.card(
                ui.input_select("pl_pitcher", "Pitcher", choices),
                ui.input_radio_buttons("pl_type", "Outing", {"Start": "Start", "Relief": "Relief", "Bullpen": "Bullpen"},
                                       selected="Start", inline=True),
                ui.input_date("pl_date", "Date", value=today + timedelta(days=1)),
                ui.input_text("pl_note", "Note", placeholder="optional"),
                ui.div(ui.input_action_button("pl_save", "Add planned outing", class_="btn-sm btn-primary"),
                       style="display:flex;gap:8px;"),
                ui.output_ui("plan_list"),
                title="Planned outings",
            ),
            col_widths=[6, 6],
        )

    def _save(entry):
        db = get_session()
        try:
            db.add(entry)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_pitcher_availability been run? ({e})", type="error", duration=10)
            return False
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.ed_save)
    def _ed_save():
        if not _can_edit():
            return
        pid = int(input.ed_pitcher())
        until = input.ed_until()
        start = input.as_of() if "as_of" in input else date.today()
        if until is not None and until < start:
            ui.notification_show("'Through' date is before today.", type="warning")
            return
        ok = _save(PitcherAvailability(player_id=pid, kind="status", status=input.ed_status(), start_date=start,
                                       end_date=until, note=(input.ed_note() or "").strip() or None,
                                       created_by_user_id=app_state.user_id(), created_at=datetime.utcnow()))
        if ok:
            ui.notification_show("Status saved.", type="message", duration=3)
            tick.set(tick() + 1)

    @reactive.effect
    @reactive.event(input.ed_clear)
    def _ed_clear():
        if not _can_edit():
            return
        pid = int(input.ed_pitcher())
        db = get_session()
        try:
            n = (db.query(PitcherAvailability)
                 .filter(PitcherAvailability.player_id == pid, PitcherAvailability.kind == "status",
                         PitcherAvailability.cleared.is_(False)).update({"cleared": True}))
            db.commit()
            ui.notification_show(f"Cleared {n} coach status{'es' if n != 1 else ''}.", type="message", duration=3)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't clear ({e})", type="error", duration=8)
        finally:
            db.close()
        tick.set(tick() + 1)

    @reactive.effect
    @reactive.event(input.pl_save)
    def _pl_save():
        if not _can_edit():
            return
        d = input.pl_date()
        if d is None:
            return
        ok = _save(PitcherAvailability(player_id=int(input.pl_pitcher()), kind="plan", plan_type=input.pl_type(),
                                       planned_date=d, note=(input.pl_note() or "").strip() or None,
                                       created_by_user_id=app_state.user_id(), created_at=datetime.utcnow()))
        if ok:
            ui.notification_show("Planned outing added.", type="message", duration=3)
            tick.set(tick() + 1)

    @render.ui
    def plan_list():
        if not _can_edit():
            return None
        req("pl_pitcher" in input and input.pl_pitcher())
        pid = int(input.pl_pitcher())
        rows = [r for r in _rows() if r["player"].player_id == pid]
        plans = rows[0]["plans"] if rows else []
        if not plans:
            return ui.p("No upcoming outings planned for him.", class_="text-muted small", style="margin-top:8px;")
        choices = {str(p["id"]): f"{p['type']} {p['date'].strftime('%a %b %d')}" + (f" -- ⚠ {p['warn']}" if p["warn"] else "")
                   for p in plans}
        return ui.div(
            ui.input_select("pl_remove_pick", "Upcoming", choices),
            ui.input_action_button("pl_remove", "Remove", class_="btn-sm btn-outline-light"),
            style="margin-top:10px;",
        )

    @reactive.effect
    @reactive.event(input.pl_remove)
    def _pl_remove():
        if not _can_edit() or "pl_remove_pick" not in input:
            return
        db = get_session()
        try:
            db.query(PitcherAvailability).filter(PitcherAvailability.availability_id == int(input.pl_remove_pick())) \
              .update({"cleared": True})
            db.commit()
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't remove ({e})", type="error", duration=8)
        finally:
            db.close()
        tick.set(tick() + 1)
