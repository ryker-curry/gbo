"""
GBO -- Staff-to-Player Assignments module.

Direct port of pages/staff_assignments.py -- lets Administrators and
Head Coaches control which players a Coach (or other staff role) can
see, via a staff picker + a multiselect of assigned players. Restricted
to Administrator/Head Coach for the same reason as the original: a
general Coach assigning themselves players would bypass the whole
point of the "assigned players only" restriction.

Same ordering-hazard-safe split as everywhere else: the staff picker
lives in its own render.ui block, the multiselect (which needs to know
that staff member's current assignments) lives in a second block that
reads it via req("staff_select" in input).
"""

from shiny import module, ui, render, reactive, req

from database import get_session
from models import User, Player, StaffPlayerAssignment, Role

import ui_helpers


@module.ui
def staff_assignments_ui():
    return ui.div(
        ui_helpers.page_header("Staff Assignments"),
        ui.output_ui("staff_picker"),
        ui.output_ui("assignment_form"),
        ui_helpers.page_footer(),
    )


@module.server
def staff_assignments_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    @render.ui
    def staff_picker():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() not in ("Administrator", "Head Coach"):
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            staff_users = (
                db.query(User)
                .join(Role)
                .filter(Role.role_name != "Player", User.active.is_(True))
                .order_by(Role.role_name, User.last_name, User.first_name)
                .all()
            )
            players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()

            if not staff_users:
                return ui_helpers.empty_state("No staff accounts exist yet.")
            if not players:
                return ui_helpers.empty_state("No players exist yet -- add players first from the Players page.")

            choices = {str(u.user_id): f"{u.first_name} {u.last_name} ({u.role.role_name})" for u in staff_users}
            return ui.input_select("staff_select", "Select a staff member:", choices=choices)
        finally:
            db.close()

    @render.ui
    def assignment_form():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() not in ("Administrator", "Head Coach"):
            return None
        req("staff_select" in input)
        selected_staff_id = int(input.staff_select())

        db = get_session()
        try:
            staff_member = db.query(User).filter(User.user_id == selected_staff_id).first()
            if staff_member is None:
                return None
            players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
            player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}

            current_assignment_ids = {
                a.player_id for a in
                db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == selected_staff_id).all()
            }

            return ui.div(
                ui.p(f"{staff_member.first_name} {staff_member.last_name} currently has {len(current_assignment_ids)} player(s) assigned.", class_="text-muted small"),
                ui.input_selectize(
                    "assigned_players", "Assigned players:",
                    choices=player_choices, selected=[str(pid) for pid in current_assignment_ids], multiple=True,
                ),
                ui.input_action_button("save_assignments_btn", "Save assignments", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_assignments_btn)
    def _save_assignments():
        selected_staff_id = int(input.staff_select())
        new_ids = {int(pid) for pid in (input.assigned_players() or ())}

        db = get_session()
        try:
            staff_member = db.query(User).filter(User.user_id == selected_staff_id).first()
            current_assignment_ids = {
                a.player_id for a in
                db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == selected_staff_id).all()
            }
            to_remove = current_assignment_ids - new_ids
            to_add = new_ids - current_assignment_ids

            if to_remove:
                db.query(StaffPlayerAssignment).filter(
                    StaffPlayerAssignment.staff_user_id == selected_staff_id,
                    StaffPlayerAssignment.player_id.in_(to_remove),
                ).delete(synchronize_session=False)

            for pid in to_add:
                db.add(StaffPlayerAssignment(staff_user_id=selected_staff_id, player_id=pid))

            db.commit()
            ui.notification_show(
                f"Updated assignments for {staff_member.first_name} {staff_member.last_name}: "
                f"{len(to_add)} added, {len(to_remove)} removed.",
                type="message", duration=6,
            )
            _bump_refresh()
        finally:
            db.close()
