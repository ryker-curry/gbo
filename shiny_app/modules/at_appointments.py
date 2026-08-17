"""
GBO -- Athletic Trainer Appointments module.

Direct port of pages/at_appointments.py -- real appointment scheduling
(date, time, player, which Athletic Trainer). Creating/editing
restricted to Administrator and Athletic Trainer (CAN_EDIT_APPOINTMENTS).

Privacy scoping, same as the original: full details (Athletic Trainer
name, Reason, Notes) go to Administrator/Athletic Trainer/Head Coach
(CAN_SEE_FULL_DETAILS); everyone else with Player Development access
sees date/time/player only. Sports Scientist doesn't get this page at
all -- nav.py already excludes it from their nav section entirely
(same as the original's page-level st.stop() gate), so this module's
own is_authenticated()-style checks don't need to re-block it, but see
the note on _blocked_for_role() below for why a defense-in-depth check
still lives here.

One real widget gap versus the original: Shiny for Python has no native
time-of-day input (st.time_input has no Shiny equivalent as of this
migration). ATAppointment.appointment_time is stored as a plain "HH:MM"
string either way (see the original's appt_time.strftime("%H:%M")), so
this uses a plain text field with the same format, validated on save --
a real, minor UX downgrade versus a native time picker, not a missed
translation.
"""

from datetime import date, timedelta
import re

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, Role, ATAppointment

import ui_helpers

CAN_EDIT_APPOINTMENTS = ("Administrator", "Athletic Trainer")
CAN_SEE_FULL_DETAILS = ("Administrator", "Athletic Trainer", "Head Coach")
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@module.ui
def at_appointments_ui():
    return ui.div(
        ui_helpers.page_header("Athletic Trainer Appointments"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def at_appointments_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _blocked_for_role():
        """Same page-level block the original applies before anything
        else -- Sports Scientist has no legitimate reason to see even
        the scoped-down version of this page. nav.py already keeps this
        page out of their nav entirely, so this is a defense-in-depth
        check (e.g. a stale bookmark/tab), not the primary gate."""
        return app_state.role_name() == "Sports Scientist"

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

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if _blocked_for_role():
            return ui.p("You don't have access to this page.", class_="text-danger")

        can_see_full_details = app_state.role_name() in CAN_SEE_FULL_DETAILS
        can_edit_appointments = app_state.role_name() in CAN_EDIT_APPOINTMENTS

        db = get_session()
        try:
            players = _visible_players(db)
            if not players:
                return ui_helpers.empty_state(
                    "No players to show yet." if app_state.can_view_all_players() else "No players are currently assigned to you."
                )
            player_ids = [p.player_id for p in players]
            player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}

            sections = [ui.hr(), ui.h5("Upcoming appointments", class_="gbo-section-title")]
            upcoming = (
                db.query(ATAppointment)
                .options(joinedload(ATAppointment.player), joinedload(ATAppointment.athletic_trainer))
                .filter(ATAppointment.player_id.in_(player_ids), ATAppointment.appointment_date >= date.today())
                .order_by(ATAppointment.appointment_date, ATAppointment.appointment_time)
                .all()
            )
            if not upcoming:
                sections.append(ui_helpers.empty_state("No upcoming appointments scheduled."))
            else:
                if not can_see_full_details:
                    sections.append(ui.p(
                        "Showing date/time only -- appointment details are restricted to Administrator, Athletic Trainer, and Head Coach.",
                        class_="text-muted small",
                    ))
                sections.append(ui_helpers.render_dict_table([
                    {
                        "Date": a.appointment_date.strftime("%Y-%m-%d (%a)"),
                        "Time": a.appointment_time or "—",
                        "Player": f"{a.player.first_name} {a.player.last_name}" if a.player else "—",
                        **({
                            "Athletic Trainer": f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "—",
                            "Reason": a.reason or "",
                        } if can_see_full_details else {}),
                    }
                    for a in upcoming
                ]))

            sections.append(ui.hr())
            sections.append(ui.h5("Check a specific player", class_="gbo-section-title"))
            sections.append(ui.input_select("at_check_player_choice", "Player", choices=player_choices))
            sections.append(ui.output_ui("player_appointments_section"))

            if not can_edit_appointments:
                sections.append(ui.p("Your role has read-only access to appointment scheduling.", class_="text-muted small"))
            else:
                sections.append(ui.hr())
                sections.append(ui.h5("Schedule an appointment", class_="gbo-section-title"))
                athletic_trainers = (
                    db.query(User)
                    .join(Role)
                    .filter(Role.role_name == "Athletic Trainer", User.active.is_(True))
                    .all()
                )
                if not athletic_trainers:
                    sections.append(ui.p("No Athletic Trainer accounts exist yet.", class_="text-warning"))
                else:
                    at_choices = {str(u.user_id): f"{u.first_name} {u.last_name}" for u in athletic_trainers}
                    sections.append(ui.div(
                        ui.input_select("appt_player_id", "Player", choices=player_choices),
                        ui.input_select("at_choice", "Athletic Trainer", choices=at_choices),
                        ui.input_date("appt_date", "Date", value=date.today() + timedelta(days=1)),
                        ui.input_text("appt_time", "Time (HH:MM, 24-hour)", placeholder="e.g. 14:30"),
                        ui.input_text("appt_reason", "Reason (optional)", placeholder="e.g. shoulder follow-up"),
                        ui.input_text_area("appt_notes", "Notes (optional)"),
                        ui.input_action_button("schedule_appt_btn", "Schedule appointment", class_="btn-primary mt-2"),
                    ))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def player_appointments_section():
        _refresh_tick()
        req("at_check_player_choice" in input)
        check_player_id = int(input.at_check_player_choice())
        can_see_full_details = app_state.role_name() in CAN_SEE_FULL_DETAILS

        db = get_session()
        try:
            check_player = db.query(Player).filter(Player.player_id == check_player_id).first()
            if check_player is None:
                return None

            status_label = check_player.status.status_name if check_player.status else "—"
            sections = [ui.p(ui.strong("Current status: "), status_label)]

            player_appointments = (
                db.query(ATAppointment)
                .options(joinedload(ATAppointment.athletic_trainer))
                .filter(ATAppointment.player_id == check_player_id)
                .order_by(ATAppointment.appointment_date.desc(), ATAppointment.appointment_time.desc())
                .all()
            )
            if not player_appointments:
                sections.append(ui_helpers.empty_state(f"No appointments on file for {check_player.first_name} {check_player.last_name}."))
            else:
                if not can_see_full_details:
                    sections.append(ui.p(
                        "Showing date/time only -- appointment details are restricted to Administrator, Athletic Trainer, and Head Coach.",
                        class_="text-muted small",
                    ))
                sections.append(ui_helpers.render_dict_table([
                    {
                        "Date": a.appointment_date.strftime("%Y-%m-%d (%a)"),
                        "Time": a.appointment_time or "—",
                        "Upcoming": "Yes" if a.appointment_date >= date.today() else "No",
                        **({
                            "Athletic Trainer": f"{a.athletic_trainer.first_name} {a.athletic_trainer.last_name}" if a.athletic_trainer else "—",
                            "Reason": a.reason or "",
                            "Notes": a.notes or "",
                        } if can_see_full_details else {}),
                    }
                    for a in player_appointments
                ]))
            return ui.div(*sections)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.schedule_appt_btn)
    def _schedule_appointment():
        appt_time_raw = (input.appt_time() or "").strip()
        if not _TIME_RE.match(appt_time_raw):
            ui.notification_show("Enter a valid time in 24-hour HH:MM format, e.g. 14:30.", type="error", duration=8)
            return

        db = get_session()
        try:
            appt_player_id = int(input.appt_player_id())
            player = db.query(Player).filter(Player.player_id == appt_player_id).first()
            db.add(ATAppointment(
                player_id=appt_player_id,
                athletic_trainer_user_id=int(input.at_choice()),
                appointment_date=input.appt_date(),
                appointment_time=appt_time_raw,
                reason=(input.appt_reason() or "").strip() or None,
                notes=(input.appt_notes() or "").strip() or None,
                created_by_user_id=app_state.user_id(),
            ))
            db.commit()
            ui.notification_show(f"Scheduled appointment for {player.first_name} {player.last_name}.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()
