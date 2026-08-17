"""
GBO -- My Development module (Player role only).

Direct port of pages/player_development.py -- read-only view of the
player's own IDP goals (creating/editing stays staff-only, on the IDP
page). Split out of the Dashboard originally; same split preserved here.
"""

from shiny import module, ui, render, reactive
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, IDPGoal, IDPActionStep

import ui_helpers


@module.ui
def player_development_ui():
    return ui.div(
        ui_helpers.page_header("My Development"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_development_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player":
            return ui.p("This page is only available to Player accounts.", class_="text-danger")

        db = get_session()
        try:
            me = db.query(User).filter(User.user_id == app_state.user_id()).first()
            if me is None or me.player_id is None:
                return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-muted")

            my_player = db.query(Player).filter(Player.player_id == me.player_id).first()

            sections = [ui.p(ui.strong(f"{my_player.first_name} {my_player.last_name}'s Development Plan"))]

            my_goals = (
                db.query(IDPGoal)
                .options(
                    joinedload(IDPGoal.category),
                    joinedload(IDPGoal.status),
                    joinedload(IDPGoal.target_test_type),
                    joinedload(IDPGoal.action_steps).joinedload(IDPActionStep.status),
                    joinedload(IDPGoal.progress_notes),
                )
                .filter(IDPGoal.player_id == my_player.player_id)
                .order_by(IDPGoal.created_at.desc())
                .all()
            )
            if not my_goals:
                sections.append(ui_helpers.empty_state("No development goals set yet -- check with your coach."))
            else:
                panels = []
                for goal in my_goals:
                    status_label = goal.status.status_name if goal.status else "—"
                    title = f"{goal.category.category_name if goal.category else '—'} — {goal.description[:60]}{'...' if len(goal.description) > 60 else ''} · {status_label}"

                    panel_children = [ui.p(goal.description)]
                    if goal.target_test_type:
                        unit = f" {goal.target_test_type.unit}" if goal.target_test_type.unit else ""
                        target_line = f"Target: {goal.target_test_type.test_name} — "
                        if goal.baseline_value is not None:
                            target_line += f"{float(goal.baseline_value):.2f}{unit} → "
                        if goal.target_value is not None:
                            target_line += f"{float(goal.target_value):.2f}{unit}"
                        if goal.target_date:
                            target_line += f" by {goal.target_date.strftime('%Y-%m-%d (%a)')}"
                        panel_children.append(ui.p(ui.strong(target_line)))

                    if goal.action_steps:
                        panel_children.append(ui.p(ui.strong("Action steps")))
                        panel_children.append(ui_helpers.render_dict_table([
                            {
                                "Description": a.description,
                                "Status": a.status.status_name if a.status else "—",
                                "Due date": a.due_date.strftime("%Y-%m-%d (%a)") if a.due_date else "—",
                            }
                            for a in goal.action_steps
                        ]))

                    if goal.progress_notes:
                        panel_children.append(ui.p(ui.strong("Progress notes")))
                        for note in sorted(goal.progress_notes, key=lambda n: n.created_at, reverse=True):
                            panel_children.append(ui.p(
                                ui.tags.span(note.created_at.strftime("%Y-%m-%d (%a)"), class_="text-muted small"),
                                ui.br(),
                                note.note_text,
                            ))

                    panels.append(ui.accordion_panel(title, ui.div(*panel_children)))
                sections.append(ui.accordion(*panels, open=False, id=None))

            return ui.div(*sections)
        finally:
            db.close()
