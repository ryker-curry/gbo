"""
GBO -- Player Assignments module.

Direct port of pages/player_assignments.py -- prescribed, forward-looking
tasks for a specific player, assigned ahead of time by a coach/Strength
Coach/Athletic Trainer, with completion tracking. Reuses the SessionType
lookup so assignment types match logged session types; a "Bullpen" type
assignment can attach a BullpenType + optional BullpenScript instead of
a TrainingRoutine, and any assignment can optionally link to an open IDP
goal. Editing gated by app_state.can_edit_sessions().

Same shapes as team_schedule.py, reused here:
  - a "type" select outside any form so a routine/bullpen-type/script
    picker beneath it can react to it live (bulk assign AND the
    single-player add-assignment form each have their own copy of this
    chain)
  - one expander+form per pending assignment for "mark as completed",
    lazily-registered per-row handlers since the row count isn't known
    until query time (_registered_complete_effects)
  - delete-with-confirmation-checkbox for a past/upcoming assignment,
    including the original's "unlink rather than cascade-delete" rule:
    a BullpenSession pointing at a deleted assignment via
    source_assignment_id gets that FK cleared, not its pitch data
    deleted, since the tracked session is worth keeping even without
    its source prescription.
"""

from datetime import date, datetime

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, StaffPlayerAssignment, SessionType, PlayerAssignment, TrainingRoutine, IDPGoal, BullpenType, BullpenScript, BullpenSession

import ui_helpers


@module.ui
def player_assignments_ui():
    return ui.div(
        ui_helpers.page_header("Player Assignments"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_assignments_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _registered_complete_effects = set()

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _visible_players(db):
        query = db.query(Player).filter(Player.active.is_(True))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment)
                .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id())
                .all()
            ]
            query = query.filter(Player.player_id.in_(assigned_ids))
        return query.order_by(Player.last_name, Player.first_name).all()

    def _type_dependent_fields(db, type_choice, bullpen_type_id_input_key):
        """Shared by bulk-assign and add-assignment -- given a session
        type name, returns (session_type_id, matching_routines,
        is_bullpen, bullpen_types). The caller reads the actual bullpen
        type/script selections separately since those need their own
        reactive inputs."""
        session_types = db.query(SessionType).order_by(SessionType.display_order).all()
        type_id = next(t.session_type_id for t in session_types if t.type_name == type_choice)
        matching_routines = (
            db.query(TrainingRoutine)
            .filter(TrainingRoutine.session_type_id == type_id)
            .order_by(TrainingRoutine.routine_name)
            .all()
        )
        is_bullpen = type_choice == "Bullpen"
        bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all() if is_bullpen else []
        return type_id, matching_routines, is_bullpen, bullpen_types

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            players = _visible_players(db)
            if not players:
                return ui_helpers.empty_state(
                    "No players to show yet." if app_state.can_view_all_players() else "No players are currently assigned to you."
                )
            session_types = db.query(SessionType).order_by(SessionType.display_order).all()
            player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}

            sections = []
            if not app_state.can_edit_sessions():
                sections.append(ui.p("Your role has read-only access to player assignments.", class_="text-muted small"))
            else:
                sections.extend([
                    ui.h5("Bulk assign to multiple players", class_="gbo-section-title"),
                    ui.p("Assign the same thing (e.g. conditioning, arm care) to several players at once, instead of one at a time.", class_="text-muted small"),
                    ui.input_select("bulk_type_choice", "Type", choices=[t.type_name for t in session_types]),
                    ui.output_ui("bulk_type_dependent_fields"),
                    ui.input_selectize("bulk_players", "Players", choices=player_choices, multiple=True),
                    ui.output_ui("bulk_assign_form"),
                ])

            sections.extend([
                ui.hr(),
                ui.h5("Manage a single player's assignments", class_="gbo-section-title"),
                ui.input_select("single_player_choice", "Player", choices=player_choices),
                ui.output_ui("single_player_section"),
            ])
            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Bulk assign
    # -------------------------------------------------------------------

    @render.ui
    def bulk_type_dependent_fields():
        if not app_state.can_edit_sessions():
            return None
        req("bulk_type_choice" in input)
        type_choice = input.bulk_type_choice()

        db = get_session()
        try:
            _, matching_routines, is_bullpen, bullpen_types = _type_dependent_fields(db, type_choice, "bulk_bullpen_type_choice")
            if is_bullpen and bullpen_types:
                choices = {str(bt.bullpen_type_id): bt.type_name for bt in bullpen_types}
                return ui.input_select("bulk_bullpen_type_choice", "Bullpen type", choices=choices)
            return None
        finally:
            db.close()

    @render.ui
    def bulk_assign_form():
        if not app_state.can_edit_sessions():
            return None
        req("bulk_type_choice" in input)
        type_choice = input.bulk_type_choice()

        db = get_session()
        try:
            _, matching_routines, is_bullpen, bullpen_types = _type_dependent_fields(db, type_choice, "bulk_bullpen_type_choice")

            extra_block = []
            if is_bullpen:
                bullpen_type_choice = input.bulk_bullpen_type_choice() if "bulk_bullpen_type_choice" in input else None
                if bullpen_type_choice:
                    matching_scripts = (
                        db.query(BullpenScript)
                        .filter(BullpenScript.bullpen_type_id == int(bullpen_type_choice))
                        .order_by(BullpenScript.script_name)
                        .all()
                    )
                    if matching_scripts:
                        choices = {"": "-- No script, just notes --"}
                        choices.update({str(s.script_id): s.script_name for s in matching_scripts})
                        extra_block = [ui.input_select("bulk_script_choice", "Attach a script (optional)", choices=choices)]
                    else:
                        extra_block = [ui.p("No scripts saved yet for this bullpen type -- build one on Bullpen Scripts first if you want to attach a planned sequence.", class_="text-muted small")]
            elif matching_routines:
                choices = {"": "-- No routine, just notes --"}
                choices.update({str(r.routine_id): r.routine_name for r in matching_routines})
                extra_block = [ui.input_select("bulk_routine_choice", "Use a saved routine (optional)", choices=choices)]

            return ui.div(
                ui.input_date("bulk_date", "Date", value=date.today()),
                *extra_block,
                ui.input_text_area("bulk_notes", "Notes (optional, applies to everyone selected)"),
                ui.input_action_button("bulk_assign_btn", "Assign to selected players", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.bulk_assign_btn)
    def _bulk_assign():
        selected_player_ids = [int(pid) for pid in (input.bulk_players() or ())]
        if not selected_player_ids:
            ui.notification_show("Select at least one player.", type="error", duration=8)
            return

        db = get_session()
        try:
            type_choice = input.bulk_type_choice()
            type_id, _, is_bullpen, _ = _type_dependent_fields(db, type_choice, "bulk_bullpen_type_choice")
            bullpen_type_id = int(input.bulk_bullpen_type_choice()) if is_bullpen and "bulk_bullpen_type_choice" in input and input.bulk_bullpen_type_choice() else None
            script_id = int(input.bulk_script_choice()) if "bulk_script_choice" in input and input.bulk_script_choice() else None
            routine_id = int(input.bulk_routine_choice()) if "bulk_routine_choice" in input and input.bulk_routine_choice() else None
            bulk_date = input.bulk_date()
            notes = (input.bulk_notes() or "").strip() or None

            players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(selected_player_ids)).all()}

            for pid in selected_player_ids:
                db.add(PlayerAssignment(
                    player_id=pid,
                    session_type_id=type_id,
                    routine_id=routine_id,
                    bullpen_type_id=bullpen_type_id,
                    bullpen_script_id=script_id,
                    scheduled_date=bulk_date,
                    notes=notes,
                    assigned_by_user_id=app_state.user_id(),
                ))
            db.commit()
            names = ", ".join(f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in selected_player_ids if pid in players_by_id)
            ui.notification_show(f"Assigned {type_choice} to {len(selected_player_ids)} player(s): {names}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Single-player management
    # -------------------------------------------------------------------

    @render.ui
    def single_player_section():
        _refresh_tick()
        req("single_player_choice" in input)
        selected_player_id = int(input.single_player_choice())

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            if selected_player is None:
                return None

            sections = [
                ui.hr(),
                ui.h5(f"Upcoming assignments — {selected_player.first_name} {selected_player.last_name}", class_="gbo-section-title"),
            ]
            upcoming = (
                db.query(PlayerAssignment)
                .filter(PlayerAssignment.player_id == selected_player_id, PlayerAssignment.scheduled_date >= date.today())
                .order_by(PlayerAssignment.scheduled_date)
                .all()
            )
            if not upcoming:
                sections.append(ui_helpers.empty_state("No upcoming assignments for this player."))
            else:
                sections.append(ui_helpers.render_dict_table([
                    {
                        "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                        "Type": a.session_type.type_name if a.session_type else "—",
                        "Routine": a.routine.routine_name if a.routine else (a.bullpen_script.script_name if a.bullpen_script else (a.bullpen_type.type_name if a.bullpen_type else "—")),
                        "Notes": a.notes or "",
                    }
                    for a in upcoming
                ]))

            if app_state.can_edit_sessions():
                all_assignments = (
                    db.query(PlayerAssignment)
                    .filter(PlayerAssignment.player_id == selected_player_id)
                    .order_by(PlayerAssignment.scheduled_date.desc())
                    .limit(200)
                    .all()
                )
                if all_assignments:
                    choices = {}
                    for a in all_assignments:
                        label = f"{a.scheduled_date.strftime('%Y-%m-%d (%a)')} — {a.session_type.type_name if a.session_type else '—'}"
                        if a.bullpen_script:
                            label += f": {a.bullpen_script.script_name}"
                        elif a.routine:
                            label += f": {a.routine.routine_name}"
                        if a.completed:
                            label += " (completed)"
                        choices[str(a.assignment_id)] = label
                    sections.append(ui.accordion(
                        ui.accordion_panel(
                            "Delete an assignment (past or upcoming)",
                            ui.input_select("delete_assignment_select", "Which assignment?", choices=choices),
                            ui.output_ui("delete_assignment_confirm"),
                        ),
                        open=False, id=None,
                    ))

            sections.append(ui.hr())
            sections.append(ui.h5("Mark assignments as completed", class_="gbo-section-title"))
            sections.append(ui.output_ui("pending_assignments_section"))

            sections.append(ui.accordion(
                ui.accordion_panel("Recently completed", ui.output_ui("completed_assignments_table")),
                open=False, id=None,
            ))

            if not app_state.can_edit_sessions():
                sections.append(ui.p("Your role has read-only access to player assignments.", class_="text-muted small"))
            else:
                sections.append(ui.hr())
                sections.append(ui.h5("Add an assignment", class_="gbo-section-title"))
                sections.append(ui.input_select("assignment_type_choice", "Type", choices=[t.type_name for t in db.query(SessionType).order_by(SessionType.display_order).all()]))
                sections.append(ui.output_ui("add_assignment_type_dependent_fields"))
                sections.append(ui.output_ui("add_assignment_form"))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def delete_assignment_confirm():
        req("delete_assignment_select" in input)
        delete_target_id = int(input.delete_assignment_select())
        return ui.div(
            ui.input_checkbox("confirm_delete_assignment", "Yes, permanently delete this assignment", value=False),
            ui.input_action_button("delete_assignment_btn", "Delete assignment", class_="btn-danger mt-2"),
        )

    @reactive.effect
    @reactive.event(input.delete_assignment_btn)
    def _delete_assignment():
        if not (input.confirm_delete_assignment() if "confirm_delete_assignment" in input else False):
            return
        delete_target_id = int(input.delete_assignment_select())

        db = get_session()
        try:
            target = db.query(PlayerAssignment).filter(PlayerAssignment.assignment_id == delete_target_id).first()
            if target is None:
                return
            linked_sessions = db.query(BullpenSession).filter(BullpenSession.source_assignment_id == delete_target_id).all()
            for bs in linked_sessions:
                bs.source_assignment_id = None
            db.delete(target)
            db.commit()
            msg = "Deleted the assignment."
            if linked_sessions:
                msg += f" Unlinked it from {len(linked_sessions)} bullpen session(s) that were tracking it (those sessions and their pitches are kept)."
            ui.notification_show(msg, type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def pending_assignments_section():
        _refresh_tick()
        req("single_player_choice" in input)
        selected_player_id = int(input.single_player_choice())

        db = get_session()
        try:
            pending = (
                db.query(PlayerAssignment)
                .filter(
                    PlayerAssignment.player_id == selected_player_id,
                    PlayerAssignment.scheduled_date <= date.today(),
                    PlayerAssignment.completed.is_(False),
                )
                .order_by(PlayerAssignment.scheduled_date.desc())
                .all()
            )
            if not pending:
                return ui.p("No pending assignments (today or earlier) to mark complete.", class_="text-muted small")
            if not app_state.can_edit_sessions():
                return ui.p("Your role has read-only access to player assignments.", class_="text-muted small")

            panels = []
            for a in pending:
                type_label = a.session_type.type_name if a.session_type else "—"
                date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
                title = f"{date_label} — {type_label}"
                if a.routine:
                    title += f": {a.routine.routine_name}"
                elif a.bullpen_type:
                    title += f": {a.bullpen_type.type_name}"

                notes_id = f"complete_notes_{a.assignment_id}"
                feedback_id = f"complete_feedback_{a.assignment_id}"
                btn_id = f"complete_assignment_btn_{a.assignment_id}"

                if btn_id not in _registered_complete_effects:
                    _registered_complete_effects.add(btn_id)
                    _register_complete_handler(btn_id, notes_id, feedback_id, a.assignment_id)

                panels.append(ui.accordion_panel(
                    title,
                    ui.input_text_area(notes_id, "What actually happened (optional)"),
                    ui.input_text_area(feedback_id, "Player feedback (optional)"),
                    ui.input_action_button(btn_id, "Mark as completed", class_="btn-primary mt-2"),
                ))
            return ui.accordion(*panels, open=False, id=None)
        finally:
            db.close()

    def _register_complete_handler(btn_id, notes_id, feedback_id, assignment_id):
        @reactive.effect
        @reactive.event(input[btn_id])
        def _handler():
            db = get_session()
            try:
                a = db.query(PlayerAssignment).filter(PlayerAssignment.assignment_id == assignment_id).first()
                if a is None:
                    return
                type_label = a.session_type.type_name if a.session_type else "—"
                date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
                a.completed = True
                a.completed_notes = (input[notes_id]() or "").strip() or None
                a.player_feedback = (input[feedback_id]() or "").strip() or None
                a.completed_at = datetime.utcnow()
                db.commit()
                ui.notification_show(f"Marked {type_label} on {date_label} as completed.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

    @render.ui
    def completed_assignments_table():
        _refresh_tick()
        req("single_player_choice" in input)
        selected_player_id = int(input.single_player_choice())

        db = get_session()
        try:
            completed = (
                db.query(PlayerAssignment)
                .filter(PlayerAssignment.player_id == selected_player_id, PlayerAssignment.completed.is_(True))
                .order_by(PlayerAssignment.scheduled_date.desc())
                .limit(20)
                .all()
            )
            if not completed:
                return ui.p("No completed assignments yet.", class_="text-muted small")
            return ui_helpers.render_dict_table([
                {
                    "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                    "Type": a.session_type.type_name if a.session_type else "—",
                    "What happened": a.completed_notes or "",
                    "Player feedback": a.player_feedback or "",
                }
                for a in completed
            ])
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Add an assignment (single player)
    # -------------------------------------------------------------------

    @render.ui
    def add_assignment_type_dependent_fields():
        if not app_state.can_edit_sessions():
            return None
        req("assignment_type_choice" in input)
        type_choice = input.assignment_type_choice()

        db = get_session()
        try:
            _, _, is_bullpen, bullpen_types = _type_dependent_fields(db, type_choice, "single_bullpen_type_choice")
            if is_bullpen and bullpen_types:
                choices = {str(bt.bullpen_type_id): bt.type_name for bt in bullpen_types}
                return ui.input_select("single_bullpen_type_choice", "Bullpen type", choices=choices)
            return None
        finally:
            db.close()

    @render.ui
    def add_assignment_form():
        if not app_state.can_edit_sessions():
            return None
        req("assignment_type_choice" in input)
        req("single_player_choice" in input)
        type_choice = input.assignment_type_choice()
        selected_player_id = int(input.single_player_choice())

        db = get_session()
        try:
            _, matching_routines, is_bullpen, _ = _type_dependent_fields(db, type_choice, "single_bullpen_type_choice")

            extra_block = []
            if is_bullpen:
                bullpen_type_choice = input.single_bullpen_type_choice() if "single_bullpen_type_choice" in input else None
                if bullpen_type_choice:
                    matching_scripts = (
                        db.query(BullpenScript)
                        .filter(BullpenScript.bullpen_type_id == int(bullpen_type_choice))
                        .order_by(BullpenScript.script_name)
                        .all()
                    )
                    if matching_scripts:
                        choices = {"": "-- No script, just notes --"}
                        choices.update({str(s.script_id): s.script_name for s in matching_scripts})
                        extra_block = [ui.input_select("script_choice", "Attach a script (optional)", choices=choices)]
                    else:
                        extra_block = [ui.p("No scripts saved yet for this bullpen type -- build one on Bullpen Scripts first if you want to attach a planned sequence.", class_="text-muted small")]
            elif matching_routines:
                choices = {"": "-- No routine, just notes --"}
                choices.update({str(r.routine_id): r.routine_name for r in matching_routines})
                extra_block = [ui.input_select("routine_choice", "Use a saved routine (optional)", choices=choices)]

            player_goals = (
                db.query(IDPGoal)
                .filter(IDPGoal.player_id == selected_player_id)
                .order_by(IDPGoal.created_at.desc())
                .all()
            )
            goal_block = []
            if player_goals:
                choices = {"": "-- Not linked to a goal --"}
                choices.update({str(g.goal_id): g.description[:50] for g in player_goals})
                goal_block = [ui.input_select("goal_choice", "Prescribed toward IDP goal (optional)", choices=choices)]

            return ui.div(
                ui.input_date("assignment_date", "Date", value=date.today()),
                *extra_block,
                *goal_block,
                ui.input_text_area("assignment_notes", "Notes (optional)", placeholder="e.g. specific throwing program details"),
                ui.input_action_button("add_assignment_btn", "Add assignment", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.add_assignment_btn)
    def _add_assignment():
        selected_player_id = int(input.single_player_choice())
        type_choice = input.assignment_type_choice()

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            type_id, _, is_bullpen, _ = _type_dependent_fields(db, type_choice, "single_bullpen_type_choice")

            bullpen_type_id = int(input.single_bullpen_type_choice()) if is_bullpen and "single_bullpen_type_choice" in input and input.single_bullpen_type_choice() else None
            script_id = int(input.script_choice()) if "script_choice" in input and input.script_choice() else None
            routine_id = int(input.routine_choice()) if "routine_choice" in input and input.routine_choice() else None
            goal_id = int(input.goal_choice()) if "goal_choice" in input and input.goal_choice() else None
            scheduled_date = input.assignment_date()

            db.add(PlayerAssignment(
                player_id=selected_player_id,
                session_type_id=type_id,
                routine_id=routine_id,
                bullpen_type_id=bullpen_type_id,
                bullpen_script_id=script_id,
                goal_id=goal_id,
                scheduled_date=scheduled_date,
                notes=(input.assignment_notes() or "").strip() or None,
                assigned_by_user_id=app_state.user_id(),
            ))
            db.commit()
            ui.notification_show(
                f"Added {type_choice} assignment for {selected_player.first_name} {selected_player.last_name} on {scheduled_date.strftime('%Y-%m-%d (%a)')}.",
                type="message", duration=8,
            )
            _bump_refresh()
        finally:
            db.close()
