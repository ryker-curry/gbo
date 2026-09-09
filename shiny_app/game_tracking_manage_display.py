"""
GBO -- Game Tracking's "Manage Game" section, extracted out of
game_tracking.py's single ~4850-line game_tracking_server (Tier 2 of the
2026-09 architecture review; see /docs or the review doc Claude produced
for the full rationale). This is the first and lowest-risk of that split's
9 groups: manage_game_body/game_status_controls/game_delete_section only
ever read _active_game_id/_refresh_tick and call _bump_refresh/_access_ok/
_can_edit -- none of the larger live-tracking/pitch-entry state.

Registration pattern follows bullpen_dashboard_display.register_bullpen_dashboard
exactly (called once, synchronously, from inside game_tracking_server's own
body, so it runs inside that module's already-namespaced session context).
Unlike register_bullpen_dashboard, this is only ever instantiated once (no
key_prefix/dynamic ids needed) -- output ids are the plain function names
below, matched by the ui.output_ui("manage_game_body") /
ui.output_ui("game_delete_section") calls already in game_tracking_ui,
exactly as they were when these functions lived directly in
game_tracking_server (Shiny's implicit output auto-registration binds by
function name regardless of which function actually executes the
@render.ui-decorated def, as long as it happens inside the module's
session context -- see shiny/render/renderer/_renderer.py's
Renderer._auto_register).
"""

from shiny import ui, render, reactive

from database import get_session
from models import Game


def register_game_tracking_manage(input, output, session, _refresh_tick, _active_game_id, _bump_refresh, _access_ok, _can_edit):
    @render.ui
    def manage_game_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        if not _can_edit():
            return ui.p("Game management is only available to edit-enabled roles.", class_="text-muted")
        return ui.div(
            ui.output_ui("game_status_controls"),
            ui.output_ui("game_delete_section"),
        )

    @render.ui
    def game_status_controls():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            if game.status in ("Final", "Cancelled"):
                # Reopen exists purely as an undo for a mis-click -- Mark
                # Final/Cancel Game are one click with no confirmation, and
                # before this there was truly no way back short of deleting
                # the whole game (see Ryker's 2026-08-23 accidental-Final
                # report). Nothing else in the app branches on status ==
                # "Final"/"Cancelled" (game_stats.py's get_pitching_pitches/
                # get_batting_pitches and every report just query by
                # game_id), so putting a game back to In Progress is fully
                # safe -- Live Tracking, Video Review, and the Pitch Log all
                # just start working again.
                return ui.div(
                    ui.p(f"Status: {game.status} (no further status changes available).", class_="text-muted small"),
                    ui.p(
                        "Marked this Final or Cancelled by mistake? Reopening puts it back In Progress so Live "
                        "Tracking, Video Review, and the Pitch Log all work again.",
                        class_="text-muted small",
                    ),
                    ui.input_action_button("reopen_game_btn", "Reopen game", class_="btn-outline-primary btn-sm"),
                )
            row = []
            if game.status == "Scheduled":
                row.append(ui.input_action_button("start_game_btn", "Start game", class_="btn-primary"))
            if game.status == "In Progress":
                row.append(ui.input_action_button("pause_game_btn", "Pause game", class_="btn-outline-secondary"))
                row.append(ui.input_action_button("mark_final_btn", "Mark game Final", class_="btn-primary"))
            if game.status == "Paused":
                row.append(ui.input_action_button("resume_game_btn", "Resume game", class_="btn-primary"))
                row.append(ui.input_action_button("mark_final_btn", "Mark game Final", class_="btn-outline-secondary"))
            row.append(ui.input_action_button("cancel_game_btn", "Cancel game", class_="btn-outline-danger"))
            return ui.div(ui.p(f"Status: {game.status}", class_="text-muted small"), ui.layout_columns(*row))
        finally:
            db.close()

    def _set_game_status(new_status, message):
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return
            game.status = new_status
            db.commit()
            ui.notification_show(message, type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.start_game_btn)
    def _start_game():
        _set_game_status("In Progress", "Game started.")

    @reactive.effect
    @reactive.event(input.pause_game_btn)
    def _pause_game():
        _set_game_status("Paused", "Game paused.")

    @reactive.effect
    @reactive.event(input.resume_game_btn)
    def _resume_game():
        _set_game_status("In Progress", "Game resumed.")

    @reactive.effect
    @reactive.event(input.mark_final_btn)
    def _mark_final():
        _set_game_status("Final", "Game marked Final.")

    @reactive.effect
    @reactive.event(input.cancel_game_btn)
    def _cancel_game():
        _set_game_status("Cancelled", "Game cancelled.")

    @reactive.effect
    @reactive.event(input.reopen_game_btn)
    def _reopen_game():
        _set_game_status("In Progress", "Game reopened -- back In Progress.")

    @render.ui
    def game_delete_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            pitch_count = len(game.pitches)
            return ui.accordion(
                ui.accordion_panel(
                    "Delete this game",
                    ui.p(f"This permanently deletes this game and all {pitch_count} pitch(es) logged in it. This can't be undone.", class_="text-warning small"),
                    ui.input_checkbox("confirm_delete_game", "Yes, I want to permanently delete this game", value=False),
                    ui.input_action_button("delete_game_btn", "Delete game", class_="btn-danger btn-sm"),
                ),
                open=False, id=None,
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_game_btn)
    def _delete_game():
        if not (input.confirm_delete_game() if "confirm_delete_game" in input else False):
            return
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return
            deleted_id = game.game_id
            db.delete(game)
            db.commit()
            _active_game_id.set(None)
            ui.notification_show(f"Deleted game #{deleted_id}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()
