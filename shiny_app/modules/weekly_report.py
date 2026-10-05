"""
GBO -- Weekly Progress Report page (Oct 2026). See analytics/
weekly_report.py for what's in it and visualizations/weekly_report_sheet.py
for the layout. Staff: week picker, team overview (who threw, notes,
whether Monday's email went out), any pitcher's report, and an optional
coach note. Player: "My Weekly Report", own reports only.
Emails go out from scripts/send_weekly_reports.py (scheduled Mondays).
"""

from datetime import datetime, timedelta

from shiny import module, ui, render, reactive, req
from sqlalchemy import func

from database import get_session
from models import Player, User, GamePitch, Game, RapsodoPitch, WeeklyReportNote, WeeklyReportSend
from analytics import weekly_report
from visualizations.weekly_report_sheet import render_sheet

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
NOTE_ROLES = ("Administrator", "Head Coach", "Coach")
WEEKS_BACK = 10

PRINT_JS = """
(function(){var el=document.getElementById('gbo-weekly-sheet');if(!el){return;}
var w=window.open('','_blank');if(!w){alert('Allow pop-ups for this site to print the report.');return;}
w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Weekly Report</title><style>@page{size:letter;margin:.4in} body{margin:0;background:#fff}</style></head><body>'+el.outerHTML+'</body></html>');
w.document.close();w.focus();setTimeout(function(){w.print();},300);})();
"""


@module.ui
def weekly_report_ui():
    return ui.div(
        ui_helpers.page_header("Weekly Progress Report", "Every player's week -- pitchers: velo, shapes, game numbers, Arsenal Plan; hitters: at-bats, swing decisions, by pitch type.", actions=ui_helpers.how_to_link("weekly_report")),
        ui.div(
            ui.output_ui("week_picker"),
            ui.output_ui("pitcher_picker"),
            ui.tags.button("Print", type="button", class_="btn btn-outline-light btn-sm", onclick=PRINT_JS,
                           style="align-self:flex-end;margin-bottom:16px;"),
            style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;",
        ),
        ui.output_ui("overview"),
        ui.output_ui("note_editor"),
        ui.output_ui("sheet"),
    )


@module.server
def weekly_report_server(input, output, session, app_state):
    tick = reactive.Value(0)

    def _role():
        return app_state.role_name() if app_state.is_authenticated() else None

    def _staff():
        return _role() in STAFF_ROLES

    def _my_pid(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        return me.player_id if me else None

    @render.ui
    def week_picker():
        if not (_staff() or _role() == "Player"):
            return None
        last = weekly_report.last_completed_week()
        weeks = [last - timedelta(days=7 * i) for i in range(WEEKS_BACK)]
        this_week = weekly_report.week_start_for(last + timedelta(days=7))
        choices = {this_week.isoformat(): f"This week so far ({this_week.strftime('%b %d')})"}
        choices.update({w.isoformat(): f"Week of {w.strftime('%b %d')} – {(w + timedelta(days=6)).strftime('%b %d')}" for w in weeks})
        return ui.input_select("week", "Week", choices=choices, selected=last.isoformat())

    def _week():
        req("week" in input)
        return datetime.fromisoformat(input.week()).date()

    @render.ui
    def pitcher_picker():
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            if _role() == "Player":
                pid = _my_pid(db)
                p = db.query(Player).filter(Player.player_id == pid).first() if pid else None
                if p is None:
                    return ui.p("Your account isn't linked to a player yet.", class_="text-muted")
                return ui.div(ui.input_select("pitcher", "Pitcher", {str(p.player_id): f"{p.first_name} {p.last_name}"}),
                              style="display:none;")
            if not _staff():
                return ui.p("You don't have access to this page.", class_="text-danger")
            ps = (db.query(Player).filter(Player.active.is_(True))
                  .order_by(Player.last_name, Player.first_name).all())
            # Oct 2026: hitters too (grouped so the dropdown stays easy to scan).
            groups = {
                "Pitchers": {str(p.player_id): f"{p.last_name}, {p.first_name}" for p in ps if p.is_pitcher},
                "Hitters": {str(p.player_id): f"{p.last_name}, {p.first_name}" for p in ps if not p.is_pitcher},
            }
            return ui.input_select("pitcher", "Player", {k: v for k, v in groups.items() if v})
        finally:
            db.close()

    def _pid():
        req("pitcher" in input)
        req(input.pitcher())
        return int(input.pitcher())

    @render.ui
    def overview():
        if not _staff():
            return None
        w0 = _week()
        w1 = w0 + timedelta(days=7)
        tick()
        db = get_session()
        try:
            ps = db.query(Player).filter(Player.is_pitcher.is_(True), Player.active.is_(True)).order_by(Player.last_name).all()
            raps = dict(db.query(RapsodoPitch.player_id, func.count(RapsodoPitch.rapsodo_pitch_id))
                        .filter(RapsodoPitch.pitch_date >= datetime.combine(w0, datetime.min.time()),
                                RapsodoPitch.pitch_date < datetime.combine(w1, datetime.min.time()))
                        .group_by(RapsodoPitch.player_id).all())
            gp = dict(db.query(GamePitch.our_player_id, func.count(GamePitch.game_pitch_id))
                      .join(Game, GamePitch.game_id == Game.game_id)
                      .filter(GamePitch.is_our_team_batting.is_(False), Game.game_date >= w0, Game.game_date < w1)
                      .group_by(GamePitch.our_player_id).all())
            try:
                notes = {n.player_id for n in db.query(WeeklyReportNote).filter(WeeklyReportNote.week_start == w0) if n.note}
                sends = {s.player_id: s for s in db.query(WeeklyReportSend).filter(WeeklyReportSend.week_start == w0)}
            except Exception:
                db.rollback()
                notes, sends = set(), {}
            rows = []
            for p in ps:
                s = sends.get(p.player_id)
                rows.append({
                    "Pitcher": f"{p.last_name}, {p.first_name}",
                    "Rapsodo pitches": raps.get(p.player_id, 0), "Game pitches": gp.get(p.player_id, 0),
                    "Coach note": "✓" if p.player_id in notes else "—",
                    "Email": (s.status if s else ("not yet" if (raps.get(p.player_id) or gp.get(p.player_id)) else "no activity")),
                })
            # Hitters (Oct 2026): plate appearances this week.
            from analytics.hitter_insights import plate_appearances
            hs = db.query(Player).filter(Player.is_pitcher.is_(False), Player.active.is_(True)).order_by(Player.last_name).all()
            bat = {}
            for gp_row in (db.query(GamePitch).join(Game, GamePitch.game_id == Game.game_id)
                           .filter(Game.game_date >= w0, Game.game_date < w1).all()):
                bid = gp_row.our_player_id if gp_row.is_our_team_batting else gp_row.opponent_our_player_id
                if bid is not None:
                    bat.setdefault(bid, []).append(gp_row)
            hrows = []
            for p in hs:
                s = sends.get(p.player_id)
                pa = len(plate_appearances(bat.get(p.player_id, [])))
                hrows.append({
                    "Hitter": f"{p.last_name}, {p.first_name}", "Plate appearances": pa,
                    "Coach note": "✓" if p.player_id in notes else "—",
                    "Email": (s.status if s else ("not yet" if pa else "no activity")),
                })
            return ui_helpers.card(
                ui.navset_tab(ui.nav_panel("Pitchers", ui_helpers.render_dict_table(rows)),
                              ui.nav_panel("Hitters", ui_helpers.render_dict_table(hrows))),
                title="Team this week", right="players with nothing tracked this week don't get an email")
        finally:
            db.close()

    def _note(db, pid, w0):
        try:
            n = db.query(WeeklyReportNote).filter(WeeklyReportNote.player_id == pid, WeeklyReportNote.week_start == w0).first()
            return n.note if n else ""
        except Exception:
            db.rollback()
            return ""

    @render.ui
    def note_editor():
        if _role() not in NOTE_ROLES:
            return None
        pid, w0 = _pid(), _week()
        tick()
        db = get_session()
        try:
            text = _note(db, pid, w0)
        finally:
            db.close()
        return ui_helpers.card(
            ui.input_text_area("note", None, value=text, rows=2, width="100%",
                               placeholder="Optional -- goes out with Monday's report. Leave blank to send without a note."),
            ui.input_action_button("save_note", "Save note", class_="btn-sm btn-primary"),
            title="Coach's note",
        )

    @reactive.effect
    @reactive.event(input.save_note)
    def _save():
        if _role() not in NOTE_ROLES:
            return
        pid, w0 = _pid(), _week()
        db = get_session()
        try:
            n = db.query(WeeklyReportNote).filter(WeeklyReportNote.player_id == pid, WeeklyReportNote.week_start == w0).first()
            if n is None:
                n = WeeklyReportNote(player_id=pid, week_start=w0)
                db.add(n)
            n.note = (input.note() or "").strip() or None
            n.updated_by_user_id = app_state.user_id()
            db.commit()
            ui.notification_show("Note saved.", type="message", duration=4)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_weekly_reports been run? ({e})", type="error", duration=10)
        finally:
            db.close()
        tick.set(tick() + 1)

    @render.ui
    def sheet():
        if not (_staff() or _role() == "Player"):
            return None
        pid, w0 = _pid(), _week()
        tick()
        db = get_session()
        try:
            if _role() == "Player" and _my_pid(db) != pid:
                return None
            rep = weekly_report.build_any(db, pid, w0)
            if rep is None:
                return None
            if not rep["active"]:
                return ui_helpers.empty_state(
                    "No at-bats tracked this week." if rep.get("kind") == "hitter"
                    else "No tracked throwing this week (no Rapsodo readings or game pitches).")
            return ui.div(ui.HTML(render_sheet(rep, _note(db, pid, w0))), style="padding:8px 0 24px;overflow-x:auto;")
        finally:
            db.close()
