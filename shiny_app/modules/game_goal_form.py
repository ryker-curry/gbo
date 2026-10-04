"""
GBO -- "New game-stat goal" form (Oct 2026). One small Shiny module used in
two places: the staff IDP page and the player's My Development page (Ryker:
players and coaches both set goals). Saves an IDPGoal with game_metric /
metric_window set; progress is computed live by analytics/game_goals.py.
"""

from datetime import date, datetime, timedelta

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, PitchType, IDPGoal, IDPStatus, AssessmentCategory
from analytics import game_goals

import ui_helpers


@module.ui
def game_goal_form_ui():
    return ui.output_ui("form")


@module.server
def game_goal_form_server(input, output, session, app_state, player_id_fn, can_create_fn, on_saved=None):

    def _player(db):
        pid = player_id_fn()
        return db.query(Player).filter(Player.player_id == pid).first() if pid else None

    @render.ui
    def form():
        if not can_create_fn():
            return None
        db = get_session()
        try:
            p = _player(db)
            if p is None:
                return None
            metrics = game_goals.metrics_for(p.is_pitcher)
            pts = db.query(PitchType).order_by(PitchType.display_order).all()
        finally:
            db.close()
        return ui_helpers.card(
            ui.p("Pick a game stat -- GBO keeps the progress up to date after every game.", class_="text-muted small"),
            ui.layout_columns(
                ui.input_select("metric", "Stat", {k: f"{v[0]} -- {v[4]}" for k, v in metrics.items()}),
                ui.input_select("window", "Measured over", {k: v[0] for k, v in game_goals.WINDOWS.items()}),
                col_widths=[7, 5],
            ),
            ui.output_ui("pitch_type_pick"),
            ui.output_ui("current_line"),
            ui.layout_columns(
                ui.output_ui("target_input"),
                ui.input_date("target_date", "Target date", value=date.today() + timedelta(days=42)),
                col_widths=[6, 6],
            ),
            ui.input_text("note", "Why / how (optional)", placeholder="e.g. lay off the slider away with 2 strikes"),
            ui.input_action_button("save", "Add goal", class_="btn-sm btn-primary"),
            title="New game-stat goal",
        )

    @render.ui
    def pitch_type_pick():
        req("metric" in input)
        if input.metric() != "p_velo":
            return None
        db = get_session()
        try:
            pts = db.query(PitchType).order_by(PitchType.display_order).all()
        finally:
            db.close()
        return ui.input_select("pitch_type", "Pitch type", {str(t.pitch_type_id): t.type_name for t in pts})

    def _pt_id():
        if input.metric() == "p_velo" and "pitch_type" in input and input.pitch_type():
            return int(input.pitch_type())
        return None

    @reactive.calc
    def _current():
        req("metric" in input and "window" in input)
        pid = player_id_fn()
        req(pid)
        db = get_session()
        try:
            return game_goals.current(db, pid, input.metric(), input.window(), _pt_id())
        finally:
            db.close()

    @render.ui
    def current_line():
        cur, n, _s = _current()
        key = input.metric()
        if n == 0:
            return ui.p("No games in this window yet -- the goal will start tracking from his next game.",
                        class_="text-muted small")
        return ui.p(f"Right now: {game_goals.fmt(key, cur)} over {n} game{'s' if n != 1 else ''}.", class_="small")

    @render.ui
    def target_input():
        cur, _n, _s = _current()
        key = input.metric()
        hib = game_goals.GAME_METRICS[key][2]
        sug = game_goals.suggest_target(key, cur)
        unit = game_goals.GAME_METRICS[key][3].strip()
        return ui.input_numeric("target", f"Target ({'at least' if hib else 'under'}{' ' + unit if unit else ''})",
                                value=sug if sug is not None else 0, step=0.5)

    @reactive.effect
    @reactive.event(input.save)
    def _save():
        if not can_create_fn():
            return
        pid = player_id_fn()
        key = input.metric()
        target = input.target()
        if pid is None or target is None:
            ui.notification_show("Pick a stat and a target.", type="warning")
            return
        label, _side, hib, _u, _d = game_goals.GAME_METRICS[key]
        cur, _n, _s = _current()
        db = get_session()
        try:
            cat = (db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Baseball Performance").first()
                   or db.query(AssessmentCategory).first())
            st = (db.query(IDPStatus).filter(IDPStatus.status_name == "In Progress").first()
                  or db.query(IDPStatus).first())
            pt_name = ""
            if _pt_id():
                t = db.query(PitchType).filter(PitchType.pitch_type_id == _pt_id()).first()
                pt_name = f" ({t.type_name})" if t else ""
            window_label = game_goals.WINDOWS[input.window()][0].lower()
            desc = f"{label}{pt_name} {'to' if hib else 'under'} {game_goals.fmt(key, target)} ({window_label})"
            note = (input.note() or "").strip()
            if note:
                desc += f" -- {note}"
            g = IDPGoal(player_id=pid, category_id=cat.category_id, status_id=st.status_id,
                        target_pitch_type_id=_pt_id(), baseline_value=cur, target_value=target,
                        target_date=input.target_date(), description=desc,
                        created_by_user_id=app_state.user_id(), created_at=datetime.utcnow(), updated_at=datetime.utcnow())
            g.game_metric = key
            g.metric_window = input.window()
            db.add(g)
            db.commit()
            ui.notification_show("Goal added -- it updates after every game.", type="message", duration=4)
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save -- has migrate_idp_game_goals been run? ({e})", type="error", duration=10)
            return
        finally:
            db.close()
        if on_saved:
            on_saved()
