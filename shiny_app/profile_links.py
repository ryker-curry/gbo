"""
GBO -- Player Profile as the coach's hub (Oct 2026, Ryker: "a coach goes
to a pitcher profile and from there clicks links that take them to game
reports, pitcher profile, etc.").

Two outputs on Player Profile (staff only):
  jump_bar      -- "Go to" buttons under the name: each opens that page
                   with this player (and his last game) already picked.
  recent_games  -- his last 5 games, one line each, with Breakdown /
                   Report links for that game.
Every jump sets app_state.back_to so the app shell shows "Back to <name>".
A button only shows when the coach's role can open that page.

Registered from player_profile_server (same pattern as
game_tracking_manage_display) so the ids live in that module's namespace.
"""

from datetime import date

from shiny import ui, render, reactive

import deep_link
import nav
import ui_helpers
from database import get_session
from format_helpers import game_label
from models import Player, BullpenSession
from game_stats import get_pitching_pitches, get_batting_pitches, pitching_line_for, compute_batting_line
from analytics import player_report, hitter_report, arm_care

N_RECENT = 5

# (button id, label, page title, what it needs) -- pitchers then hitters.
PITCHER_LINKS = [
    ("pl_profile", "Pitcher Profile", "Pitcher Profile", "pid"),
    ("pl_last", "Last outing", "Pitcher Game Breakdown", "game"),
    ("pl_report", "Pitcher Report", "Pitcher Report", "game"),
    ("pl_week", "Weekly Report", "Weekly Reports", "pid"),
    ("pl_pens", "Bullpens", "Bullpen Dashboard", "bullpen"),
    ("pl_plan", "Development plan", "IDP", "pid"),
    ("pl_arm", "Arm care", "Arm Care & Availability", None),
]
HITTER_LINKS = [
    ("pl_hprofile", "Hitter Profile", "Hitter Profile", "pid"),
    ("pl_hlast", "Last game", "Hitter Game Breakdown", "game"),
    ("pl_hreport", "Hitter Report", "Hitter Report", "game"),
    ("pl_hweek", "Weekly Report", "Weekly Reports", "pid"),
    ("pl_hplan", "Development plan", "IDP", "pid"),
]
ALL_LINKS = PITCHER_LINKS + HITTER_LINKS

ARM_CLASS = {"Available": "good", "Limited": "watch", "Down": "watch", "Hold": "flag"}


def _pct(v):
    return f"{v:.0f}%" if v is not None else "—"


def pitching_row(db, pid, g):
    line = pitching_line_for(db, pid, get_pitching_pitches(db, pid, game_id=g.game_id))
    return (f"{line.get('IP') or '0.0'} IP · {line.get('Pitches', 0)} P · {line.get('K', 0)} K · "
            f"{line.get('BB', 0)} BB · {line.get('H Allowed', 0)} H · {_pct(line.get('Strike %'))} strikes")


def batting_row(db, pid, g):
    line = compute_batting_line(get_batting_pitches(db, pid, game_id=g.game_id))
    bits = [f"{line.get('H', 0)}-{line.get('AB', 0)}"]
    for k in ("2B", "3B", "HR", "BB", "K"):
        if line.get(k):
            bits.append(f"{line[k]} {k}")
    return " · ".join(bits) + f" · {line.get('PA', 0)} PA"


def register_profile_links(input, output, session, app_state, _selected):
    def _allowed_titles():
        return {p.title for s in nav.build_nav_sections(app_state.role_name(), app_state.coach_specialty(),
                                                         app_state.is_pitcher()) for p in s.pages}

    def _staff():
        return app_state.is_authenticated() and app_state.role_name() != "Player"

    def _player(db):
        pid = _selected()
        return db.query(Player).filter(Player.player_id == pid).first() if pid else None

    def _games(db, p):
        return (player_report.pitcher_games(db, p.player_id) if p.is_pitcher
                else hitter_report.hitter_games(db, p.player_id))

    @render.ui
    def jump_bar():
        if not _staff():
            return None
        db = get_session()
        try:
            p = _player(db)
            if p is None:
                return None
            allowed = _allowed_titles()
            links = PITCHER_LINKS if p.is_pitcher else HITTER_LINKS
            has_game = bool(_games(db, p))
            has_pen = p.is_pitcher and db.query(BullpenSession.bullpen_id).filter(BullpenSession.player_id == p.player_id).first() is not None
            arm = None
            if p.is_pitcher and "Arm Care & Availability" in allowed:
                try:
                    arm = arm_care.pitcher_row(db, p, date.today())
                except Exception:
                    arm = None
            buttons = []
            for bid, label, title, need in links:
                if title not in allowed:
                    continue
                if (need == "game" and not has_game) or (need == "bullpen" and not has_pen):
                    continue
                if bid == "pl_arm" and arm:
                    label = f"Arm care: {arm['status']}"
                buttons.append(ui.input_action_button(
                    bid, label, class_="btn-sm gbo-jump-btn" + (f" gbo-jump-{ARM_CLASS.get(arm['status'], '')}" if bid == "pl_arm" and arm else ""),
                    title=(arm.get("reason") or "") if bid == "pl_arm" and arm else None))
            if not buttons:
                return None
            return ui.div(ui.span("Go to", class_="gbo-jump-lbl"), *buttons, class_="gbo-jump")
        finally:
            db.close()

    def _jump(bid):
        db = get_session()
        try:
            p = _player(db)
            if p is None:
                return
            spec = next(x for x in ALL_LINKS if x[0] == bid)
            _id, _label, title, need = spec
            back = (p.player_id, f"{p.first_name} {p.last_name}")
            if title == "Pitcher Profile":
                app_state.back_to.set(back)
                app_state.deep_link_pitcher.set((p.player_id, "overview"))
                ui.update_navs("main_nav", selected=title, session=session.root_scope())
                return
            if need == "bullpen":
                bp = (db.query(BullpenSession).filter(BullpenSession.player_id == p.player_id)
                      .order_by(BullpenSession.session_date.desc(), BullpenSession.bullpen_id.desc()).first())
                app_state.back_to.set(back)
                if bp is not None:
                    app_state.deep_link_bullpen_id.set(bp.bullpen_id)
                ui.update_navs("main_nav", selected=title, session=session.root_scope())
                return
            params = {"pid": p.player_id}
            if need == "game":
                games = _games(db, p)
                if games:
                    params["game_id"] = games[0].game_id
        finally:
            db.close()
        deep_link.go(app_state, session, title, back=back, **params)

    for _bid, *_rest in ALL_LINKS:
        def _make(bid):
            @reactive.effect
            @reactive.event(input[bid])
            def _on_click():
                _jump(bid)
        _make(_bid)

    @render.ui
    def recent_games():
        if not _staff():
            return None
        db = get_session()
        try:
            p = _player(db)
            if p is None:
                return None
            allowed = _allowed_titles()
            games = _games(db, p)[:N_RECENT]
            if not games:
                return None
            if p.is_pitcher:
                pages = ("Pitcher Game Breakdown", "Pitcher Report")
                row_fn = pitching_row
            else:
                pages = ("Hitter Game Breakdown", "Hitter Report")
                row_fn = batting_row
            go_id = session.ns("open_game")
            rows = []
            for g in games:
                try:
                    line = row_fn(db, p.player_id, g)
                except Exception:
                    line = ""
                acts = []
                for title, label in zip(pages, ("Breakdown", "Report")):
                    if title in allowed:
                        acts.append(ui.tags.a(label, href="#", class_="gbo-recent-link",
                                              onclick=(f"Shiny.setInputValue('{go_id}', "
                                                       f"{{page: '{title}', game: {g.game_id}, t: Date.now()}}, "
                                                       f"{{priority: 'event'}}); return false;")))
                rows.append(ui.div(
                    ui.div(game_label(g), class_="gbo-recent-game"),
                    ui.div(line, class_="gbo-recent-line"),
                    ui.div(*acts, class_="gbo-recent-acts"),
                    class_="gbo-recent-row",
                ))
            title = "Recent outings" if p.is_pitcher else "Recent games"
            return ui.div(ui_helpers.card(*rows, title=title, right=f"last {len(games)}"), style="margin-bottom:16px;")
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.open_game)
    def _open_game():
        req_ = input.open_game() or {}
        db = get_session()
        try:
            p = _player(db)
            if p is None or req_.get("page") not in _allowed_titles():
                return
            back = (p.player_id, f"{p.first_name} {p.last_name}")
        finally:
            db.close()
        deep_link.go(app_state, session, req_["page"], back=back, pid=back[0], game_id=int(req_["game"]))
