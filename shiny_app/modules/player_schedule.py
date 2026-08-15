"""
GBO -- My Schedule module (Player role only).

Direct port of pages/player_schedule.py -- same three sections (team
schedule, my assignments, my Athletic Trainer appointments), same 7-day
window, same queries, same fields. Role gating (Player-only) is handled
at the nav level -- build_nav_sections() in shiny_app/nav.py only
includes "My Schedule" for role_name == "Player", so unlike the original
page this module doesn't need its own st.stop()-style role check. It
still checks app_state.is_authenticated() before querying, same as
every other module (see shiny_app/app.py's module docstring for why
every module is mounted unconditionally at startup).

Streamlit's st.expander -> Shiny's ui.accordion/ui.accordion_panel.
Streamlit's st.dataframe (for the read-only appointments table) ->
plain ui.tags.table built from real tag objects (not a raw HTML
string), so cell values -- which come straight from the database --
get the same automatic escaping ui.p()/ui.strong() give the other
sections, rather than needing manual escaping.
"""

from datetime import date, timedelta

from shiny import module, ui, render
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, TeamScheduleEvent, PlayerAssignment, ATAppointment, TrainingRoutine

import ui_helpers


@module.ui
def player_schedule_ui():
    return ui.div(
        ui_helpers.page_header("My Schedule"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_schedule_server(input, output, session, app_state):
    @render.ui
    def body():
        if not app_state.is_authenticated():
            return None

        db = get_session()
        try:
            me = db.query(User).filter(User.user_id == app_state.user_id()).first()
            if me is None or me.player_id is None:
                return ui.p(
                    "Your player profile isn't linked yet. Check with an administrator.",
                    class_="text-muted",
                )

            my_player = db.query(Player).filter(Player.player_id == me.player_id).first()
            today = date.today()
            week_ahead = today + timedelta(days=7)

            team_events = (
                db.query(TeamScheduleEvent)
                .options(
                    joinedload(TeamScheduleEvent.event_type),
                    joinedload(TeamScheduleEvent.routine).joinedload(TrainingRoutine.exercises),
                )
                .filter(
                    TeamScheduleEvent.team_id == my_player.team_id,
                    TeamScheduleEvent.scheduled_date >= today,
                    TeamScheduleEvent.scheduled_date <= week_ahead,
                    or_(
                        TeamScheduleEvent.pitchers_only.is_(None),
                        TeamScheduleEvent.pitchers_only == my_player.is_pitcher,
                    ),
                )
                .order_by(TeamScheduleEvent.scheduled_date)
                .all()
            )

            my_assignments = (
                db.query(PlayerAssignment)
                .options(
                    joinedload(PlayerAssignment.session_type),
                    joinedload(PlayerAssignment.routine).joinedload(TrainingRoutine.exercises),
                    joinedload(PlayerAssignment.bullpen_type),
                    joinedload(PlayerAssignment.bullpen_script),
                )
                .filter(
                    PlayerAssignment.player_id == my_player.player_id,
                    PlayerAssignment.scheduled_date >= today,
                    PlayerAssignment.scheduled_date <= week_ahead,
                )
                .order_by(PlayerAssignment.scheduled_date)
                .all()
            )

            my_appointments = (
                db.query(ATAppointment)
                .options(joinedload(ATAppointment.athletic_trainer))
                .filter(
                    ATAppointment.player_id == my_player.player_id,
                    ATAppointment.appointment_date >= today,
                )
                .order_by(ATAppointment.appointment_date, ATAppointment.appointment_time)
                .all()
            )

            return ui.div(
                ui.h5("Team schedule (next 7 days)", class_="gbo-section-title"),
                _team_events_ui(team_events),
                ui.hr(),
                ui.h5("My assignments (next 7 days)", class_="gbo-section-title"),
                _assignments_ui(my_assignments),
                ui.hr(),
                ui.h5("My Athletic Trainer appointments", class_="gbo-section-title"),
                _appointments_ui(my_appointments),
            )
        finally:
            db.close()


def _routine_exercise_ui(ex):
    """One exercise's block within a routine -- name, sets x reps,
    optional video, optional notes. Shared by both the team-event and
    assignment routine renderers below (same shape in the original)."""
    ex_label = ex.exercise_name
    if ex.sets or ex.reps:
        ex_label += f" — {ex.sets or '—'} sets x {ex.reps or '—'}"
    parts = [ui.p(ui.strong(ex_label), class_="mb-1")]
    if ex.video_url:
        parts.append(
            ui.tags.video(
                ui.tags.source(src=ex.video_url),
                controls=True,
                style="max-width:100%; margin-bottom: 8px;",
            )
        )
    if ex.notes:
        parts.append(ui.p(ex.notes, class_="text-muted small"))
    return parts


def _team_events_ui(events):
    if not events:
        return ui_helpers.empty_state("No team events scheduled this week.")

    panels = []
    for e in events:
        date_label = e.scheduled_date.strftime("%Y-%m-%d (%a)")
        type_label = e.event_type.type_name if e.event_type else "Team"
        title = f"{date_label} — {type_label}: {e.title}"
        if e.routine:
            title += f" ({e.routine.routine_name})"

        content = []
        if e.routine:
            if e.routine.description:
                content.append(ui.p(e.routine.description))
            for ex in e.routine.exercises:
                content.extend(_routine_exercise_ui(ex))
        if e.notes:
            content.append(ui.p(e.notes, class_="text-muted small"))
        if not e.routine and not e.notes:
            content.append(ui.p("No additional details provided.", class_="text-muted small"))

        panels.append(ui.accordion_panel(title, *content))
    return ui.accordion(*panels, open=False, id=None)


def _assignments_ui(assignments):
    if not assignments:
        return ui_helpers.empty_state("No assignments scheduled this week.")

    panels = []
    for a in assignments:
        type_label = a.session_type.type_name if a.session_type else "—"
        date_label = a.scheduled_date.strftime("%Y-%m-%d (%a)")
        title = f"{date_label} — {type_label}"
        if a.routine:
            title += f": {a.routine.routine_name}"
        elif a.bullpen_type:
            title += f": {a.bullpen_type.type_name}"
            if a.bullpen_script:
                title += f" ({a.bullpen_script.script_name})"

        content = []
        if a.routine:
            if a.routine.description:
                content.append(ui.p(a.routine.description))
            for ex in a.routine.exercises or []:
                content.extend(_routine_exercise_ui(ex))
        elif a.bullpen_type:
            caption = f"{a.bullpen_type.type_name} bullpen"
            if a.bullpen_script:
                caption += f": {a.bullpen_script.script_name}"
            content.append(ui.p(f"{caption} — logged in Bullpen Tracking once thrown.", class_="text-muted small"))
        if a.notes:
            content.append(ui.p(a.notes, class_="text-muted small"))
        if not a.routine and not a.bullpen_type and not a.notes:
            content.append(ui.p("No additional details provided.", class_="text-muted small"))

        panels.append(ui.accordion_panel(title, *content))
    return ui.accordion(*panels, open=False, id=None)


def _appointments_ui(appointments):
    if not appointments:
        return ui_helpers.empty_state("No upcoming Athletic Trainer appointments.")

    rows = [
        ui.tags.tr(
            ui.tags.td(a.appointment_date.strftime("%Y-%m-%d (%a)")),
            ui.tags.td(a.appointment_time or "—"),
            ui.tags.td(
                f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}"
                if a.athletic_trainer
                else "—"
            ),
            ui.tags.td(a.reason or ""),
        )
        for a in appointments
    ]
    return ui.tags.table(
        ui.tags.thead(
            ui.tags.tr(
                ui.tags.th("Date"), ui.tags.th("Time"), ui.tags.th("Athletic Trainer"), ui.tags.th("Reason")
            )
        ),
        ui.tags.tbody(*rows),
        class_="table table-sm",
    )
