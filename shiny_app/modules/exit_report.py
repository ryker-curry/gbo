"""
GBO -- Fall Exit Report page (Oct 2026, Ryker: exit meetings -- "a report
that coaches could go through and do a deep dive on each player's
performance this fall ... then use it as a development tool so each guy
knows what he needs to work on before the season starts").

Data: analytics/exit_report.py. Sheets: visualizations/exit_report_sheet.py.

Tabs:
  Fall review     -- pages 1-2 (how his fall went + deep dive)
  Offseason plan  -- the 3 priorities (GBO's suggestions pre-filled, the
                     coach edits), coach's notes, meeting date; "Save plan"
                     stores it (models.ExitReport) and creates / updates one
                     IDP goal per priority. Page 3 previews live below.
Print prints all three pages.

Access (Ryker's calls): staff open anyone's; Head Coach / Coach /
Administrator edit and save the plan; a Player sees only his own, and only
after a coach has saved it (read-only).
"""

from datetime import date

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, User, Season, Game
from analytics import exit_report as er
from visualizations.exit_report_sheet import render as render_sheets

import ui_helpers

VIEW_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator",
              "Strength Coach")
EDIT_ROLES = ("Administrator", "Head Coach", "Coach")
AREAS = ["Pitching", "Hitting", "Approach", "Body", "Arm care", "Other"]

PRINT_JS = """
(function(){
  var el = document.getElementById('gbo-exit-sheets');
  if(!el){ return; }
  var w = window.open('', '_blank');
  if(!w){ alert('Allow pop-ups for this site to print the report.'); return; }
  w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Fall Exit Report</title>'
    + '<style>@page{size:letter;margin:.4in} body{margin:0;background:#fff}'
    + '.gbo-exit .gbo-sheet{box-shadow:none;margin:0;min-height:0}</style></head><body>'
    + el.outerHTML + '</body></html>');
  w.document.close();
  w.focus();
  setTimeout(function(){ w.print(); }, 400);
})();
"""


@module.ui
def exit_report_ui():
    return ui.div(
        ui_helpers.page_header(
            "Fall Exit Report",
            "Go through his fall with him, then set the 3 things he works on before the season."),
        ui.div(
            ui.output_ui("pickers"),
            ui.tags.button("Print / save as PDF", type="button", class_="btn btn-primary btn-sm",
                           onclick=PRINT_JS, style="align-self:flex-end;margin-bottom:16px;"),
            style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;",
        ),
        ui.output_ui("status_line"),
        ui.output_ui("body"),
        # Full 3-page block, hidden -- the Print button copies it.
        ui.div(ui.output_ui("print_block"), style="display:none;"),
    )


@module.server
def exit_report_server(input, output, session, app_state):
    tick = reactive.Value(0)          # bumps after a save
    reset = reactive.Value(0)         # bumps on "Use GBO suggestions"

    def _role():
        return app_state.role_name() if app_state.is_authenticated() else None

    def _allowed():
        return _role() in VIEW_ROLES or _role() == "Player"

    def _can_edit():
        return _role() in EDIT_ROLES

    def _my_player_id(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        return me.player_id if me is not None else None

    # ---------------- pickers ----------------
    @render.ui
    def pickers():
        if not _allowed():
            return ui.p("You don't have access to this page.", class_="text-danger") if app_state.is_authenticated() else None
        tick()
        db = get_session()
        try:
            season_ids = [sid for (sid,) in db.query(Game.season_id).filter(Game.season_id.isnot(None)).distinct()]
            seasons = db.query(Season).filter(Season.season_id.in_(season_ids)).all() if season_ids else []
            if not seasons:
                return ui_helpers.empty_state("No games tracked yet.")
            default = er.default_season(db)
            s_choices = {str(s.season_id): s.season_name for s in seasons}
            season_sel = ui.input_select("season", "Season", choices=s_choices,
                                         selected=str(default) if default else None)
            if _role() == "Player":
                pid = _my_player_id(db)
                p = db.query(Player).filter(Player.player_id == pid).first() if pid else None
                if p is None:
                    return ui.p("Your account isn't linked to a player yet.", class_="text-muted")
                return ui.div(ui.div(ui.input_select("player", "Player", choices={str(p.player_id): f"{p.first_name} {p.last_name}"}),
                                     style="display:none;"), season_sel)
            players = (db.query(Player).filter(Player.active.is_(True))
                       .order_by(Player.last_name, Player.first_name).all())
            saved = set()
            try:
                from models import ExitReport
                saved = {pid for (pid,) in db.query(ExitReport.player_id).filter(
                    ExitReport.status == "saved", ExitReport.season_id == default)}
            except Exception:
                db.rollback()
            groups = {"Pitchers": {}, "Hitters": {}}
            for p in players:
                mark = "  ✓ plan saved" if p.player_id in saved else ""
                groups["Pitchers" if p.is_pitcher else "Hitters"][str(p.player_id)] = f"{p.last_name}, {p.first_name}{mark}"
            with reactive.isolate():
                keep = input.player() if "player" in input else None
            return ui.div(
                ui.input_select("player", "Player", choices=groups,
                                selected=keep if keep and any(keep in g for g in groups.values()) else None),
                season_sel, style="display:flex;gap:16px;flex-wrap:wrap;")
        finally:
            db.close()

    def _pid():
        req("player" in input)
        v = input.player()
        req(v)
        return int(v)

    def _sid():
        req("season" in input)
        v = input.season()
        req(v)
        return int(v)

    # ---------------- data ----------------
    @reactive.calc
    def _rep():
        pid, sid = _pid(), _sid()
        db = get_session()
        try:
            if _role() == "Player" and _my_player_id(db) != pid:
                return None
            return er.build(db, pid, sid)
        finally:
            db.close()

    @reactive.calc
    def _plan_row():
        """Saved plan as plain values (or None)."""
        pid, sid = _pid(), _sid()
        tick()
        db = get_session()
        try:
            try:
                r = er.load_plan(db, pid, sid)
            except Exception:
                db.rollback()
                return {"missing_table": True}
            if r is None:
                return None
            return {"status": r.status, "priorities": list(r.priorities or []), "notes": r.coach_notes or "",
                    "met_on": r.met_on, "saved_at": r.saved_at}
        finally:
            db.close()

    def _player_blocked():
        """Players only see a saved plan."""
        if _role() != "Player":
            return False
        pr = _plan_row()
        return not (pr and pr.get("status") == "saved")

    @render.ui
    def status_line():
        if not _allowed():
            return None
        pr = _plan_row()
        if pr and pr.get("missing_table"):
            return ui.div("Saving plans needs one setup step: run  python3 -m migrations.migrate_exit_reports",
                          class_="alert alert-warning small")
        if pr and pr.get("status") == "saved":
            when = pr["saved_at"].strftime("%b %d") if pr.get("saved_at") else ""
            return ui.p(f"Plan saved {when}" + (f" · met {pr['met_on'].strftime('%b %d')}" if pr.get("met_on") else "")
                        + (" -- he can see it in My Development." if _role() != "Player" else ""), class_="text-muted small")
        if _role() != "Player":
            return ui.p("No plan saved yet -- the Offseason plan tab starts from GBO's suggestions.", class_="text-muted small")
        return None

    # ---------------- plan inputs <-> dicts ----------------
    def _start_priorities():
        """Saved plan if there is one (unless the coach asked for the
        suggestions again), else GBO's suggestions."""
        rep = _rep()
        pr = _plan_row()
        with reactive.isolate():
            want_suggest = reset() > 0
        if pr and pr.get("priorities") and not want_suggest:
            items = pr["priorities"]
        else:
            items = rep["priorities_suggested"] if rep else []
            if pr and pr.get("priorities"):
                # keep the goal links so re-saving updates, not duplicates
                for i, p in enumerate(items):
                    if i < len(pr["priorities"]):
                        p = dict(p)
                        p["goal_id"] = pr["priorities"][i].get("goal_id")
                        items[i] = p
        items = [{**er.blank_priority(), **p} for p in items][:er.N_PRIORITIES]
        while len(items) < er.N_PRIORITIES:
            items.append(er.blank_priority())
        return items

    _goal_ids = reactive.Value([None] * er.N_PRIORITIES)

    def _read_inputs():
        out = []
        gids = _goal_ids.get()
        for i in range(er.N_PRIORITIES):
            if f"p{i}_title" not in input:
                return None
            tgt = input[f"p{i}_target"]()
            rt = input[f"p{i}_retest"]()
            out.append({
                "area": input[f"p{i}_area"](), "title": (input[f"p{i}_title"]() or "").strip(),
                "why": (input[f"p{i}_why"]() or "").strip(), "measure": input[f"p{i}_measure"]() or "",
                "target": tgt if tgt not in ("", None) else None,
                "retest": rt.isoformat() if rt else None, "drills": input[f"p{i}_drills"]() or "",
                "goal_id": gids[i] if i < len(gids) else None,
            })
        return out

    def _measure_label(m, choices):
        return choices.get(m, "").replace("Games: ", "").replace("Test: ", "") if m else ""

    # ---------------- body ----------------
    @render.ui
    def body():
        if not _allowed():
            return None
        if _player_blocked():
            return ui_helpers.empty_state("Your exit report shows up here after your meeting with a coach.")
        rep = _rep()
        if rep is None:
            return ui_helpers.empty_state("No games tracked for him this season yet.")
        part1 = ui.HTML(render_sheets(rep, None, pages=(1, 2), wrapper_id=None))
        tabs = [ui.nav_panel("Fall review", ui.div(part1, style="padding:10px 0 24px;overflow-x:auto;"))]
        if _can_edit():
            tabs.append(ui.nav_panel("Offseason plan", ui.div(ui.output_ui("editor"), ui.output_ui("plan_preview"),
                                                              style="padding-top:10px;")))
        else:
            tabs.append(ui.nav_panel("Offseason plan", ui.div(ui.output_ui("plan_preview"), style="padding-top:10px;")))
        return ui.navset_tab(*tabs, id="xr_tab")

    @render.ui
    def editor():
        if not _can_edit():
            return None
        rep = _rep()
        if rep is None:
            return None
        reset()
        items = _start_priorities()
        pr = _plan_row() or {}
        _goal_ids.set([p.get("goal_id") for p in items])
        choices = er.measure_choices(rep["player"].is_pitcher)
        boxes = []
        for i, p in enumerate(items):
            meas = p["measure"] if p["measure"] in choices else ""
            try:
                rt = date.fromisoformat(p["retest"]) if p.get("retest") else er.RETEST_DEFAULT
            except ValueError:
                rt = er.RETEST_DEFAULT
            area = p.get("area") if p.get("area") in AREAS else ("Pitching" if rep["side"] == "pitch" else "Hitting")
            boxes.append(ui_helpers.card(
                ui.layout_columns(
                    ui.input_text(f"p{i}_title", "Priority", value=p.get("title") or "", width="100%",
                                  placeholder="e.g. Raise first-pitch strike %"),
                    ui.input_select(f"p{i}_area", "Area", choices=AREAS, selected=area),
                    col_widths=[9, 3]),
                ui.input_text_area(f"p{i}_why", "Why (what the fall showed)", value=p.get("why") or "", rows=2, width="100%"),
                ui.layout_columns(
                    ui.input_select(f"p{i}_measure", "Measured by", choices=choices, selected=meas),
                    ui.div(ui.tags.label("Now", class_="form-label"), ui.output_text(f"p{i}_now")),
                    ui.input_numeric(f"p{i}_target", "Target", value=p.get("target")),
                    ui.input_date(f"p{i}_retest", "Retest by", value=rt),
                    col_widths=[5, 2, 2, 3]),
                ui.input_text_area(f"p{i}_drills", "How (one per line)", value=p.get("drills") or "", rows=3, width="100%"),
                title=f"Priority {i + 1}", right=("linked to an IDP goal" if p.get("goal_id") else None),
            ))
        met = pr.get("met_on") or date.today()
        return ui.div(
            ui.p("GBO filled these in from his biggest gaps -- keep, rewrite or replace any of them. Leave a priority's "
                 "title blank to skip it. Saving creates (or updates) one IDP goal per priority; a priority 'Measured by' "
                 "a game stat or test tracks itself.", class_="text-muted small"),
            *boxes,
            ui_helpers.card(
                ui.input_text_area("notes", None, value=pr.get("notes") or "", rows=4, width="100%",
                                   placeholder="Anything else from the meeting -- prints on page 3."),
                ui.input_date("met_on", "Meeting date", value=met),
                title="Coach's notes"),
            ui.div(ui.input_action_button("save", "Save plan & update IDP goals", class_="btn-primary"),
                   ui.input_action_button("suggest", "Start over from GBO's suggestions", class_="btn-sm btn-outline-light"),
                   style="display:flex;gap:10px;align-items:center;margin:6px 0 18px;"),
        )

    def _now_text(i):
        req(f"p{i}_measure" in input)
        m = input[f"p{i}_measure"]()
        if not m:
            return "—"
        db = get_session()
        try:
            return er.measure_now(db, _pid(), m, _sid())[1]
        finally:
            db.close()

    @render.text
    def p0_now():
        return _now_text(0)

    @render.text
    def p1_now():
        return _now_text(1)

    @render.text
    def p2_now():
        return _now_text(2)

    @reactive.effect
    @reactive.event(input.suggest)
    def _suggest():
        reset.set(reset() + 1)

    @reactive.effect
    @reactive.event(input.save)
    def _save():
        if not _can_edit():
            return
        items = _read_inputs()
        if items is None:
            return
        rep = _rep()
        db = get_session()
        try:
            _row, msgs = er.save_plan(db, _pid(), _sid(), rep.get("season_name") if rep else "Fall", items,
                                      input.notes() if "notes" in input else "", input.met_on() if "met_on" in input else None,
                                      app_state.user_id())
            ui.notification_show("Plan saved." + (f" {len(msgs)} new IDP goal(s)." if msgs else " IDP goals updated."),
                                 type="message", duration=5)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save the plan -- has migrate_exit_reports been run? ({e})", type="error", duration=10)
            return
        finally:
            db.close()
        reset.set(0)
        tick.set(tick() + 1)

    @reactive.calc
    def _sheet_plan():
        return _plan_for_sheet(_rep())

    def _plan_for_sheet(rep):
        """Live inputs for a coach (unsaved edits preview), else the saved plan."""
        if rep is None:
            return None
        choices = er.measure_choices(rep["player"].is_pitcher)
        items, notes, met = None, "", None
        if _can_edit():
            items = _read_inputs()
            notes = input.notes() if "notes" in input else ""
            met = input.met_on() if "met_on" in input else None
        if items is None:
            pr = _plan_row() or {}
            items = pr.get("priorities") or []
            notes, met = pr.get("notes") or "", pr.get("met_on")
        out = []
        db = get_session()
        try:
            for p in items:
                if not (p.get("title") or "").strip():
                    continue
                _v, now = er.measure_now(db, rep["player"].player_id, p.get("measure"), _sid()) if p.get("measure") else (None, "")
                tgt = p.get("target")
                key = (p.get("measure") or "").partition(":")[2]
                if tgt in (None, ""):
                    tdisp = ""
                elif (p.get("measure") or "").startswith("g:") and key in er.game_goals.GAME_METRICS:
                    tdisp = er.game_goals.fmt(key, float(tgt))
                else:
                    tdisp = f"{float(tgt):g}"
                try:
                    rdisp = date.fromisoformat(p["retest"]).strftime("%b %d, %Y") if p.get("retest") else ""
                except ValueError:
                    rdisp = ""
                out.append({**p, "measure_label": _measure_label(p.get("measure"), choices), "now_disp": now,
                            "target_disp": tdisp, "retest_disp": rdisp})
        finally:
            db.close()
        return {"priorities": out, "notes": notes, "met_on": met}

    @render.ui
    def plan_preview():
        if not _allowed() or _player_blocked():
            return None
        rep = _rep()
        if rep is None:
            return None
        html = render_sheets(rep, _sheet_plan(), pages=(3,), wrapper_id=None)
        title = "Page 3 preview -- updates as you type" if _can_edit() else "His offseason plan"
        return ui.div(ui.h6(title, class_="gbo-section-title"), ui.HTML(html),
                      style="overflow-x:auto;padding-bottom:24px;")

    @render.ui
    def print_block():
        if not _allowed() or _player_blocked():
            return None
        rep = _rep()
        if rep is None:
            return None
        return ui.HTML(render_sheets(rep, _sheet_plan()))
