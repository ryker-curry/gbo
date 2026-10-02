"""
GBO -- Advance Scouting page (Oct 2026). See analytics/advance_scouting.py
for where the numbers come from and visualizations/advance_report_sheet.py
for the layout.

Staff: pick an opponent, open or create a report for a series, set each
of their pitchers' expected role, write scouting notes per pitcher
(saved on the opponent's roster so they carry over), edit the auto-
drafted series plan, and publish. Players (hitters): read-only list of
published reports.
"""

from datetime import date

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import OpponentTeam, OpponentPlayer, AdvanceReport
from analytics import advance_scouting as adv
from visualizations.advance_report_sheet import render_sheet

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Data Analyst", "Video Coordinator")
NEW = "__new__"

PRINT_JS = """
(function(){var el=document.getElementById('gbo-advance-sheet');if(!el){return;}
var w=window.open('','_blank');if(!w){alert('Allow pop-ups for this site to print the report.');return;}
w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Advance Report</title><style>@page{size:letter landscape;margin:.35in} body{margin:0;background:#fff}</style></head><body>'+el.outerHTML+'</body></html>');
w.document.close();w.focus();setTimeout(function(){w.print();},300);})();
"""


@module.ui
def advance_scouting_ui():
    return ui.div(
        ui_helpers.page_header("Advance Scouting", "Their staff from our own charting, plus your notes and a series plan."),
        ui.div(
            ui.output_ui("pickers"),
            ui.tags.button("Print / save as PDF", type="button", class_="btn btn-primary btn-sm", onclick=PRINT_JS,
                           style="align-self:flex-end;margin-bottom:16px;"),
            style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;",
        ),
        ui.output_ui("editor"),
        ui.output_ui("sheet"),
    )


@module.server
def advance_scouting_server(input, output, session, app_state):
    tick = reactive.Value(0)
    selected_report = reactive.Value(None)

    def _role():
        return app_state.role_name() if app_state.is_authenticated() else None

    def _staff():
        return _role() in STAFF_ROLES

    def _can_edit():
        return _role() in EDIT_ROLES

    @render.ui
    def pickers():
        if not app_state.is_authenticated():
            return None
        tick()
        db = get_session()
        try:
            try:
                if _staff():
                    teams = db.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
                    if not teams:
                        return ui_helpers.empty_state("Add opponent teams on the Opponent Teams page first.")
                    team_sel = input.adv_team() if "adv_team" in input else str(teams[0].team_id)
                    reps = (db.query(AdvanceReport).filter(AdvanceReport.opponent_team_id == int(team_sel))
                            .order_by(AdvanceReport.updated_at.desc()).all())
                    rchoices = {str(r.report_id): r.title + ("" if r.published else " (draft)") for r in reps}
                    if _can_edit():
                        rchoices[NEW] = "+ New report"
                    cur = input.adv_report() if "adv_report" in input and input.adv_report() in rchoices else next(iter(rchoices), NEW)
                    if selected_report() and str(selected_report()) in rchoices:
                        cur = str(selected_report())
                    return ui.div(
                        ui.input_select("adv_team", "Opponent", {str(t.team_id): t.team_name for t in teams}, selected=team_sel),
                        ui.input_select("adv_report", "Report", rchoices, selected=cur) if rchoices else ui.p("No reports yet.", class_="text-muted"),
                        style="display:flex;gap:16px;flex-wrap:wrap;",
                    )
                reps = (db.query(AdvanceReport).options(joinedload(AdvanceReport.opponent_team))
                        .filter(AdvanceReport.published.is_(True)).order_by(AdvanceReport.updated_at.desc()).all())
            except Exception:
                db.rollback()
                return ui.p("Advance Scouting isn't set up yet -- run migrations.migrate_advance_reports.", class_="text-muted")
            if not reps:
                return ui_helpers.empty_state("No scouting reports have been published yet.")
            return ui.input_select("adv_report", "Report", {str(r.report_id): f"{r.title} ({r.opponent_team.team_name})" for r in reps})
        finally:
            db.close()

    def _report_id():
        req("adv_report" in input)
        v = input.adv_report()
        req(v and v != NEW)
        return int(v)

    @render.ui
    def editor():
        if not _can_edit():
            return None
        req("adv_team" in input and "adv_report" in input)
        team_id = int(input.adv_team())
        tick()
        db = get_session()
        try:
            if input.adv_report() == NEW:
                team = db.query(OpponentTeam).filter(OpponentTeam.team_id == team_id).first()
                return ui_helpers.card(
                    ui.layout_columns(
                        ui.input_text("adv_new_title", "Title", value=f"vs {team.team_name}" if team else ""),
                        ui.input_date("adv_new_date", "Series starts", value=date.today()),
                        col_widths=[8, 4],
                    ),
                    ui.input_action_button("adv_create", "Create report", class_="btn-sm btn-primary"),
                    title="New advance report",
                )
            rep_row = db.query(AdvanceReport).filter(AdvanceReport.report_id == _report_id()).first()
            if rep_row is None:
                return None
            data = adv.build(db, team_id, rep_row.roles or {})
            prow = []
            for p in data["pitchers"]:
                seen = f'{p["profile"]["n"]} pitches seen' if p["profile"] else "not seen yet"
                prow.append(ui.div(
                    ui.div(ui.strong(p["name"]), ui.span(f' {p["hand"] or "?"}HP · {seen}', class_="text-muted small"),
                           style="min-width:220px;"),
                    ui.input_select(f"role_{p['id']}", None, {r: (r or "Role") for r in adv.ROLES}, selected=p["role"], width="140px"),
                    ui.input_text_area(f"pnote_{p['id']}", None, value=p["notes"] or "", rows=1, width="100%",
                                       placeholder="Scouting notes (velo, tells, holds runners...) -- saved to his roster entry"),
                    style="display:flex;gap:10px;align-items:flex-start;border-bottom:1px solid rgba(255,255,255,.08);padding:6px 0;",
                ))
            plan = rep_row.plan_text if rep_row.plan_text else adv.draft_series_plan(data)
            return ui_helpers.card(
                ui.layout_columns(
                    ui.input_text("adv_title", "Title", value=rep_row.title),
                    ui.input_date("adv_date", "Series starts", value=rep_row.series_date),
                    ui.input_switch("adv_published", "Published (hitters can see it)", value=bool(rep_row.published)),
                    col_widths=[6, 3, 3],
                ),
                ui.p(ui.strong("Their pitchers"), class_="mb-1 mt-2"),
                *(prow or [ui.p("No pitchers on their roster yet -- add them on Opponent Teams, or they'll appear as we chart them.",
                               class_="text-muted small")]),
                ui.p(ui.strong("Series plan"), class_="mb-1 mt-3"),
                ui.input_text_area("adv_plan", None, value=plan, rows=6, width="100%"),
                ui.div(
                    ui.input_action_button("adv_save", "Save", class_="btn-sm btn-primary"),
                    ui.input_action_button("adv_redraft", "Redraft plan from the numbers", class_="btn-sm btn-outline-light",
                                           style="margin-left:8px;"),
                ),
                ui.p("The plan is drafted from the numbers and the roles you set (starters first) -- edit it before publishing. "
                     "Roles only change the report after Save.", class_="text-muted small", style="margin-top:6px;"),
                title="Edit report",
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.adv_create)
    def _create():
        if not _can_edit():
            return
        db = get_session()
        try:
            team_id = int(input.adv_team())
            data = adv.build(db, team_id, {})
            r = AdvanceReport(opponent_team_id=team_id, title=(input.adv_new_title() or "Advance report").strip(),
                              series_date=input.adv_new_date(), roles={}, plan_text=adv.draft_series_plan(data),
                              published=False, created_by_user_id=app_state.user_id())
            db.add(r)
            db.commit()
            selected_report.set(r.report_id)
            ui.notification_show("Report created -- set roles, edit the plan, then publish.", type="message", duration=6)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't create -- has migrate_advance_reports been run? ({e})", type="error", duration=10)
        finally:
            db.close()
        tick.set(tick() + 1)

    @reactive.effect
    @reactive.event(input.adv_save)
    def _save():
        if not _can_edit():
            return
        db = get_session()
        try:
            r = db.query(AdvanceReport).filter(AdvanceReport.report_id == _report_id()).first()
            if r is None:
                return
            roster = db.query(OpponentPlayer).filter(OpponentPlayer.team_id == r.opponent_team_id).all()
            roles = {}
            for op in roster:
                rid, nid = f"role_{op.opponent_player_id}", f"pnote_{op.opponent_player_id}"
                if rid in input and input[rid]():
                    roles[str(op.opponent_player_id)] = input[rid]()
                if nid in input:
                    op.notes = (input[nid]() or "").strip() or None
            r.roles = roles
            r.title = (input.adv_title() or r.title).strip()
            r.series_date = input.adv_date()
            r.plan_text = input.adv_plan()
            r.published = bool(input.adv_published())
            db.commit()
            selected_report.set(r.report_id)
            ui.notification_show("Saved." + (" Hitters can see it." if r.published else " (Draft -- not visible to hitters.)"),
                                 type="message", duration=5)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save ({e})", type="error", duration=10)
        finally:
            db.close()
        tick.set(tick() + 1)

    @reactive.effect
    @reactive.event(input.adv_redraft)
    def _redraft():
        if not _can_edit():
            return
        db = get_session()
        try:
            r = db.query(AdvanceReport).filter(AdvanceReport.report_id == _report_id()).first()
            if r is None:
                return
            roles = {}
            for op in db.query(OpponentPlayer).filter(OpponentPlayer.team_id == r.opponent_team_id).all():
                rid = f"role_{op.opponent_player_id}"
                if rid in input and input[rid]():
                    roles[op.opponent_player_id] = input[rid]()
            ui.update_text_area("adv_plan", value=adv.draft_series_plan(adv.build(db, r.opponent_team_id, roles)))
        finally:
            db.close()

    @render.ui
    def sheet():
        if not (_staff() or _role() == "Player"):
            return None
        rid = _report_id()
        tick()
        db = get_session()
        try:
            r = db.query(AdvanceReport).filter(AdvanceReport.report_id == rid).first()
            if r is None or (not _staff() and not r.published):
                return None
            data = adv.build(db, r.opponent_team_id, r.roles or {})
            return ui.div(ui.HTML(render_sheet(data, r)), style="padding:8px 0 24px;overflow-x:auto;")
        finally:
            db.close()
