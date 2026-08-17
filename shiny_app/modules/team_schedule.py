"""
GBO -- Team Schedule module.

Direct port of pages/team_schedule.py -- team-wide calendar (lift days,
practice, games, other) with completion tracking. A "Lift" event can
optionally have a real Training Routine attached (EVENT_TYPE_TO_SESSION_TYPE
maps which event types have a matching routine library -- only "Lift" does
right now).

Creating/editing is restricted to Administrator, Head Coach, and Strength
Coach (CAN_EDIT_SCHEDULE); everyone else with Player Development access
gets read-only.

"Mark events as completed" has one expander+form per pending event, an
unknown-in-advance count -- same lazy-registered-per-row-button pattern
training_routines.py's per-exercise video-save buttons use
(_registered_complete_effects).

The original put the "Add event" type select OUTSIDE its st.form so the
routine dropdown below it could react to it live (st.form batches
everything inside it until submit, so it couldn't update there).
Shiny doesn't need that workaround -- everything is reactive by
default -- but the same split-into-two-output_ui-blocks shape as
elsewhere in this migration (avoid the "read an input from the same
block that defines it" hazard) does the same job here.
"""

from datetime import date, timedelta, datetime

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Team, TeamScheduleEvent, TeamEventType, TrainingRoutine, SessionType

import ui_helpers

EVENT_TYPE_TO_SESSION_TYPE = {"Lift": "Lifting"}
CAN_EDIT_SCHEDULE = ("Administrator", "Head Coach", "Strength Coach")


@module.ui
def team_schedule_ui():
    return ui.div(
        ui_helpers.page_header("Team Schedule"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def team_schedule_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _registered_complete_effects = set()

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _can_edit():
        return app_state.role_name() in CAN_EDIT_SCHEDULE

    def _event_row(s, include_completed_notes=False):
        row = {
            "Date": s.scheduled_date.strftime("%Y-%m-%d (%a)"),
            "Type": s.event_type.type_name if s.event_type else "—",
            "Title": s.title,
            "Audience": "Pitchers Only" if s.pitchers_only is True else ("Position Players Only" if s.pitchers_only is False else "Whole Team"),
            "Routine": s.routine.routine_name if s.routine else "—",
            "Completed": "Yes" if s.completed else "No",
        }
        if include_completed_notes:
            row["What happened"] = s.completed_notes or ""
        row["Notes"] = s.notes or ""
        return row

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            teams = db.query(Team).all()
            if not teams:
                return ui.p("No teams exist yet.", class_="text-warning")
            team = teams[0]  # single-team MVP
            event_types = db.query(TeamEventType).order_by(TeamEventType.display_order).all()

            sections = [
                ui.input_select("type_filter", "Filter by type", choices=["All"] + [t.type_name for t in event_types]),
                ui.hr(),
                ui.h5("Upcoming events", class_="gbo-section-title"),
                ui.output_ui("upcoming_events_table"),
                ui.hr(),
                ui.h5("Mark events as completed", class_="gbo-section-title"),
                ui.output_ui("pending_events_section"),
                ui.hr(),
                ui.accordion(ui.accordion_panel("Past events", ui.output_ui("past_events_table")), open=False, id=None),
            ]

            if _can_edit():
                sections.append(ui.hr())
                sections.append(ui.h5("Add a scheduled event", class_="gbo-section-title"))
                sections.append(ui.input_select("new_event_type", "Type", choices=[t.type_name for t in event_types]))
                sections.append(ui.output_ui("add_event_form_fields"))
            else:
                sections.append(ui.p("Your role has read-only access to the team schedule.", class_="text-muted small"))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def upcoming_events_table():
        _refresh_tick()
        req("type_filter" in input)
        type_filter = input.type_filter()

        db = get_session()
        try:
            teams = db.query(Team).all()
            if not teams:
                return None
            team = teams[0]
            q = (
                db.query(TeamScheduleEvent)
                .options(joinedload(TeamScheduleEvent.event_type), joinedload(TeamScheduleEvent.routine))
                .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date >= date.today())
            )
            if type_filter != "All":
                q = q.join(TeamEventType).filter(TeamEventType.type_name == type_filter)
            upcoming = q.order_by(TeamScheduleEvent.scheduled_date).all()
            if not upcoming:
                return ui_helpers.empty_state("No upcoming events scheduled.")
            return ui_helpers.render_dict_table([_event_row(s) for s in upcoming])
        finally:
            db.close()

    @render.ui
    def past_events_table():
        _refresh_tick()
        req("type_filter" in input)
        type_filter = input.type_filter()

        db = get_session()
        try:
            teams = db.query(Team).all()
            if not teams:
                return None
            team = teams[0]
            q = (
                db.query(TeamScheduleEvent)
                .options(joinedload(TeamScheduleEvent.event_type), joinedload(TeamScheduleEvent.routine))
                .filter(TeamScheduleEvent.team_id == team.team_id, TeamScheduleEvent.scheduled_date < date.today())
            )
            if type_filter != "All":
                q = q.join(TeamEventType).filter(TeamEventType.type_name == type_filter)
            past = q.order_by(TeamScheduleEvent.scheduled_date.desc()).limit(50).all()
            if not past:
                return ui.p("No past entries.", class_="text-muted small")
            return ui_helpers.render_dict_table([_event_row(s, include_completed_notes=True) for s in past])
        finally:
            db.close()

    @render.ui
    def pending_events_section():
        _refresh_tick()
        db = get_session()
        try:
            teams = db.query(Team).all()
            if not teams:
                return None
            team = teams[0]
            pending_events = (
                db.query(TeamScheduleEvent)
                .options(joinedload(TeamScheduleEvent.event_type))
                .filter(
                    TeamScheduleEvent.team_id == team.team_id,
                    TeamScheduleEvent.scheduled_date <= date.today(),
                    TeamScheduleEvent.completed.is_(False),
                )
                .order_by(TeamScheduleEvent.scheduled_date.desc())
                .all()
            )
            if not pending_events:
                return ui.p("No pending events (today or earlier) to mark complete.", class_="text-muted small")
            if not _can_edit():
                return ui.p("Your role has read-only access to the team schedule.", class_="text-muted small")

            panels = []
            for s in pending_events:
                date_label = s.scheduled_date.strftime("%Y-%m-%d (%a)")
                type_label = s.event_type.type_name if s.event_type else "—"
                notes_id = f"complete_notes_{s.schedule_id}"
                btn_id = f"complete_btn_{s.schedule_id}"

                if btn_id not in _registered_complete_effects:
                    _registered_complete_effects.add(btn_id)
                    _register_complete_handler(btn_id, notes_id, s.schedule_id)

                panels.append(ui.accordion_panel(
                    f"{date_label} — {type_label}: {s.title}",
                    ui.input_text_area(notes_id, "What actually happened (optional)"),
                    ui.input_action_button(btn_id, "Mark as completed", class_="btn-primary mt-2"),
                ))
            return ui.accordion(*panels, open=False, id=None)
        finally:
            db.close()

    def _register_complete_handler(btn_id, notes_id, schedule_id):
        @reactive.effect
        @reactive.event(input[btn_id])
        def _handler():
            db = get_session()
            try:
                s = db.query(TeamScheduleEvent).filter(TeamScheduleEvent.schedule_id == schedule_id).first()
                if s is None:
                    return
                s.completed = True
                s.completed_notes = (input[notes_id]() or "").strip() or None
                s.completed_at = datetime.utcnow()
                db.commit()
                ui.notification_show(f"Marked {s.title} on {s.scheduled_date.strftime('%Y-%m-%d (%a)')} as completed.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

    @render.ui
    def add_event_form_fields():
        if not _can_edit():
            return None
        req("new_event_type" in input)
        event_type_choice = input.new_event_type()

        db = get_session()
        try:
            event_types = db.query(TeamEventType).order_by(TeamEventType.display_order).all()
            event_type = next((t for t in event_types if t.type_name == event_type_choice), None)
            if event_type is None:
                return None

            matching_routines = []
            mapped_session_type = EVENT_TYPE_TO_SESSION_TYPE.get(event_type_choice)
            if mapped_session_type:
                matching_routines = (
                    db.query(TrainingRoutine)
                    .join(SessionType)
                    .filter(SessionType.type_name == mapped_session_type)
                    .order_by(TrainingRoutine.routine_name)
                    .all()
                )

            routine_block = []
            if matching_routines:
                choices = {"": "-- No routine, just a title --"}
                choices.update({str(r.routine_id): r.routine_name for r in matching_routines})
                routine_block = [ui.input_select("routine_choice", "Attach a routine (optional)", choices=choices)]
            elif mapped_session_type:
                routine_block = [ui.p(
                    f"No {mapped_session_type} routines saved yet -- build one on Training Routines first if you want to attach real workout content.",
                    class_="text-muted small",
                )]

            return ui.div(
                ui.input_date("scheduled_date", "Date", value=date.today() + timedelta(days=1)),
                ui.input_text("event_title", "Title", placeholder="e.g. Squat Day, Team Practice"),
                ui.input_select("audience_choice", "Who is this for?", choices=["Whole Team", "Pitchers Only", "Position Players Only"]),
                *routine_block,
                ui.input_text_area("event_notes", "Notes (optional)"),
                ui.input_action_button("add_event_btn", "Add to schedule", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.add_event_btn)
    def _add_event():
        title = (input.event_title() or "").strip()
        if not title:
            ui.notification_show("Title is required.", type="error", duration=8)
            return

        db = get_session()
        try:
            teams = db.query(Team).all()
            if not teams:
                return
            team = teams[0]
            event_types = db.query(TeamEventType).order_by(TeamEventType.display_order).all()
            event_type_choice = input.new_event_type()
            event_type_id = next(t.event_type_id for t in event_types if t.type_name == event_type_choice)

            routine_id = None
            if "routine_choice" in input:
                raw = input.routine_choice()
                routine_id = int(raw) if raw else None

            audience_choice = input.audience_choice()
            pitchers_only = {"Whole Team": None, "Pitchers Only": True, "Position Players Only": False}[audience_choice]
            scheduled_date = input.scheduled_date()

            db.add(TeamScheduleEvent(
                team_id=team.team_id,
                event_type_id=event_type_id,
                routine_id=routine_id,
                pitchers_only=pitchers_only,
                scheduled_date=scheduled_date,
                title=title,
                notes=(input.event_notes() or "").strip() or None,
                created_by_user_id=app_state.user_id(),
            ))
            db.commit()
            ui.notification_show(f"Added {title} on {scheduled_date.strftime('%Y-%m-%d (%a)')}.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()
