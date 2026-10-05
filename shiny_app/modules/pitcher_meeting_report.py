"""
GBO -- Pitcher Meeting Report page (Oct 2026).

Ryker: a simpler, one-page report a pitcher can sit down and go through
with a coach -- printable -- for a single GAME or a whole SEASON. A
separate page from Pitcher Game Report / Pitcher Profile (those stay the
full-detail tools). Data: analytics/player_report.py. Sheet HTML:
visualizations/meeting_report_sheet.py.

Access (Ryker's call): staff can open any pitcher's report; a Player
only his own (self-scoped, same pattern as Pitcher Game Report). Coach
notes ("Coach's focus") are typed and saved per report
(models.PlayerReportNote) by NOTE_EDIT_ROLES and print on the sheet;
players see them read-only.

Print: the Print button copies just the sheet (which carries its own
scoped CSS) into a new window and prints that, so the app's sidebar and
controls never end up on paper and the sheet prints as one page.
"""

from datetime import datetime

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Game, GamePitch, Season, User, PlayerReportNote
from analytics import player_report
from visualizations.meeting_report_sheet import render_sheet
from format_helpers import game_label

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
NOTE_EDIT_ROLES = ("Administrator", "Head Coach", "Coach")
ALL_GAMES = "all"

PRINT_JS = """
(function(){
  var el = document.getElementById('gbo-meeting-sheet');
  if(!el){ return; }
  var w = window.open('', '_blank');
  if(!w){ alert('Allow pop-ups for this site to print the report.'); return; }
  w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Pitcher Report</title>'
    + '<style>@page{size:letter;margin:.4in} body{margin:0;background:#fff}</style></head><body>'
    + el.outerHTML + '</body></html>');
  w.document.close();
  var s = w.document.getElementById('gbo-meeting-sheet');
  if(s){ var max = 10.15 * 96, h = s.scrollHeight; if(h > max){ s.style.zoom = (max / h).toFixed(3); } }
  w.focus();
  setTimeout(function(){ w.print(); }, 300);
})();
"""


@module.ui
def pitcher_meeting_report_ui():
    return ui.div(
        ui_helpers.page_header(
            "Pitcher Meeting Report",
            "One page to go through with a coach -- what happened, what it means, and what to work on.", actions=ui_helpers.how_to_link("meeting_report")),
        ui.div(
            ui.input_radio_buttons("kind", None, choices={"game": "Game", "season": "Season"}, selected="game", inline=True),
            ui.output_ui("pitcher_picker"),
            ui.output_ui("target_picker"),
            ui.tags.button("Print / save as PDF", type="button", class_="btn btn-primary btn-sm",
                           onclick=PRINT_JS, style="align-self:flex-end;margin-bottom:16px;"),
            style="display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start;",
        ),
        ui.output_ui("notes_editor"),
        ui.output_ui("sheet"),
    )


@module.server
def pitcher_meeting_report_server(input, output, session, app_state):
    notes_tick = reactive.Value(0)

    def _role():
        return app_state.role_name() if app_state.is_authenticated() else None

    def _allowed():
        role = _role()
        return role in STAFF_ROLES or role == "Player"

    def _my_player_id(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        return me.player_id if me is not None else None

    @render.ui
    def pitcher_picker():
        if not _allowed():
            return ui.p("You don't have access to this page.", class_="text-danger") if app_state.is_authenticated() else None
        db = get_session()
        try:
            if _role() == "Player":
                pid = _my_player_id(db)
                p = db.query(Player).filter(Player.player_id == pid).first() if pid else None
                if p is None:
                    return ui.p("Your account isn't linked to a player yet.", class_="text-muted")
                return ui.div(ui.input_select("pitcher", "Pitcher", choices={str(p.player_id): f"{p.first_name} {p.last_name}"}),
                              style="display:none;")
            ids = {pid for (pid,) in db.query(GamePitch.our_player_id).filter(GamePitch.is_our_team_batting.is_(False)).distinct()}
            ids |= {pid for (pid,) in db.query(GamePitch.opponent_our_player_id)
                    .filter(GamePitch.is_our_team_batting.is_(True), GamePitch.opponent_our_player_id.isnot(None)).distinct()}
            ids.discard(None)
            if not ids:
                return ui_helpers.empty_state("No pitchers with tracked games yet.")
            players = db.query(Player).filter(Player.player_id.in_(ids)).order_by(Player.last_name, Player.first_name).all()
            return ui.input_select("pitcher", "Pitcher", choices={str(p.player_id): f"{p.last_name}, {p.first_name}" for p in players})
        finally:
            db.close()

    def _pid():
        req("pitcher" in input)
        v = input.pitcher()
        req(v)
        return int(v)

    @render.ui
    def target_picker():
        if not _allowed():
            return None
        pid = _pid()
        db = get_session()
        try:
            if input.kind() == "game":
                games = player_report.pitcher_games(db, pid)
                if not games:
                    return ui.p("No games tracked for this pitcher yet.", class_="text-muted")
                return ui.input_select("game", "Game", choices={str(g.game_id): game_label(g) for g in games})
            games = player_report.pitcher_games(db, pid)
            season_ids = [g.season_id for g in games if g.season_id is not None]
            seasons = db.query(Season).filter(Season.season_id.in_(set(season_ids))).all() if season_ids else []
            order = {sid: i for i, sid in enumerate(dict.fromkeys(season_ids))}  # most recent game first
            seasons.sort(key=lambda s: order.get(s.season_id, 99))
            choices = {str(s.season_id): s.season_name for s in seasons}
            choices[ALL_GAMES] = "All games"
            return ui.input_select("season", "Season", choices=choices)
        finally:
            db.close()

    def _target():
        """(kind, game_id, season_id) for the current selection."""
        kind = input.kind()
        if kind == "game":
            req("game" in input)
            req(input.game())
            return "game", int(input.game()), None
        req("season" in input)
        req(input.season())
        v = input.season()
        return "season", None, (None if v == ALL_GAMES else int(v))

    def _load_note(db, pid, kind, game_id, season_id):
        q = db.query(PlayerReportNote).filter(PlayerReportNote.player_id == pid, PlayerReportNote.report_kind == kind)
        q = q.filter(PlayerReportNote.game_id == game_id) if game_id is not None else q.filter(PlayerReportNote.game_id.is_(None))
        q = q.filter(PlayerReportNote.season_id == season_id) if season_id is not None else q.filter(PlayerReportNote.season_id.is_(None))
        return q.order_by(PlayerReportNote.updated_at.desc()).first()

    def _note_text(db, pid, kind, game_id, season_id):
        try:
            n = _load_note(db, pid, kind, game_id, season_id)
            return n.notes if n else ""
        except Exception:
            # Table not created yet (migration not run) -- the sheet still works.
            db.rollback()
            return ""

    @render.ui
    def notes_editor():
        if _role() not in NOTE_EDIT_ROLES:
            return None
        pid = _pid()
        kind, game_id, season_id = _target()
        notes_tick()
        db = get_session()
        try:
            text = _note_text(db, pid, kind, game_id, season_id)
        finally:
            db.close()
        return ui_helpers.card(
            ui.input_text_area("notes", None, value=text, rows=3, width="100%",
                               placeholder="1-3 things to focus on before his next outing. These print under \"Coach's focus\"."),
            ui.input_action_button("save_notes", "Save notes", class_="btn-sm btn-primary"),
            title="Coach's focus (prints on the sheet)",
        )

    @reactive.effect
    @reactive.event(input.save_notes)
    def _save_notes():
        if _role() not in NOTE_EDIT_ROLES:
            return
        pid = _pid()
        kind, game_id, season_id = _target()
        text = (input.notes() or "").strip()
        db = get_session()
        try:
            n = _load_note(db, pid, kind, game_id, season_id)
            if n is None:
                n = PlayerReportNote(player_id=pid, report_kind=kind, game_id=game_id, season_id=season_id)
                db.add(n)
            n.notes = text or None
            n.updated_by_user_id = app_state.user_id()
            n.updated_at = datetime.utcnow()
            db.commit()
            ui.notification_show("Notes saved.", type="message", duration=4)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save notes -- has migrate_player_report_notes been run? ({e})",
                                 type="error", duration=10)
        finally:
            db.close()
        notes_tick.set(notes_tick() + 1)

    @render.ui
    def sheet():
        if not _allowed():
            return None
        pid = _pid()
        kind, game_id, season_id = _target()
        notes_tick()
        db = get_session()
        try:
            if _role() == "Player" and _my_player_id(db) != pid:
                return None
            if kind == "game":
                rep = player_report.game_report(db, pid, game_id)
            else:
                rep = player_report.season_report(db, pid, season_id)
            if rep is None:
                return ui_helpers.empty_state("No pitches recorded for this selection yet.")
            notes = _note_text(db, pid, kind, game_id, season_id)
            return ui.div(ui.HTML(render_sheet(rep, notes)), style="padding:8px 0 24px;overflow-x:auto;")
        finally:
            db.close()
