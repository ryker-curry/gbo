"""
GBO -- Training Routines module.

Direct port of pages/training_routines.py -- a reusable content library
of named routines (exercise name/sets/reps/notes, optional per-exercise
demo video), assignable to players repeatedly via Player Assignments.
Third and last of Task #11's three st.data_editor pages, and the only
one of the three where the grid is pre-loaded with EXISTING rows rather
than starting blank -- true add/edit/remove against real DB records,
not a pure bulk-insert form. Builds on the working-rows-in-a-
reactive.Value pattern opponent_teams.py/bullpen_scripts.py establish
(read those modules' docstrings for the full row-add/remove spike
writeup); the addition here is an "ID" column carried through the grid
so Save can diff against the database exactly like the original did:
a row whose ID matches an existing exercise updates it in place, a row
with no matching ID inserts a new exercise, and any existing ID that's
no longer present in the saved table (because its row was removed via
the "Remove selected" button before saving) gets deleted -- the Shiny
equivalent of the original's per-row trash icon, since render.data_frame
has no such built-in affordance (see opponent_teams.py's docstring).

The per-exercise "attach a demo video" section below the grid has an
unknown-in-advance number of Save-video buttons (one per exercise in
whichever routine is selected), so unlike the grid's own fixed Add/
Remove/Save buttons, those get the LAZY REGISTRATION treatment: each
exercise's click handler is registered the first time that exercise_id's
button appears in a render pass, not up front. This module is now the
canonical example of that pattern elsewhere in this migration (the
original example, video_import.py's now-removed "link an unlinked clip"
buttons, was dropped when that page was simplified to a pure upload
page -- see video_import.py's docstring).
"""

import pandas as pd

from shiny import module, ui, render, reactive, req

from database import get_session
from models import SessionType, TrainingRoutine, RoutineExercise
from r2_client import upload_video_to_r2

import ui_helpers

ROUTINE_VIDEO_SUBFOLDER = "routine-videos/"
EXERCISE_COLUMNS = ["ID", "Exercise Name", "Sets", "Reps", "Notes"]
BLANK_EXERCISE_ROW_COUNT = 3

# Which session types belong to which coaching specialty -- used to filter
# Training Routines so a Hitting Coach doesn't see pitcher-only routines
# and vice versa. Anything not listed here is shared (visible to both).
PITCHING_SESSION_TYPES = {"Arm Care", "Throwing", "Plyos", "Mechanical Work", "Bullpen"}
HITTING_SESSION_TYPES = {"Hitting Drills"}


class _ShinyFileAdapter:
    """Adapts one ui.input_file() entry to the .name/.getvalue()/.type
    shape upload_video_to_r2() expects -- same adapter as
    hitter_tracking.py's, duplicated here per that convention.
    (video_import.py used to carry a copy of this too, but that page
    was redesigned to store pasted Google Drive links instead of
    uploading files, so it no longer needs R2 or this adapter at all.)"""
    def __init__(self, file_info: dict):
        self.name = file_info["name"]
        self.type = file_info.get("type")
        self._datapath = file_info["datapath"]

    def getvalue(self) -> bytes:
        with open(self._datapath, "rb") as f:
            return f.read()


def _upload_routine_video(file_info: dict, identifier: str):
    try:
        return upload_video_to_r2(_ShinyFileAdapter(file_info), identifier, bucket_subfolder=ROUTINE_VIDEO_SUBFOLDER)
    except Exception as e:
        ui.notification_show(
            f"Video upload failed: {e}. Make sure Cloudflare R2 is configured "
            f"(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- "
            f"see r2_client.py's docstring for setup steps).",
            type="error", duration=12,
        )
        return None


def _blank_exercise_rows(n):
    return [{c: "" for c in EXERCISE_COLUMNS} for _ in range(n)]


def _exercise_rows_from_db(db, routine_id):
    routine = db.query(TrainingRoutine).filter(TrainingRoutine.routine_id == routine_id).first()
    if routine is None:
        return []
    existing = sorted(routine.exercises, key=lambda e: e.display_order)
    return [
        {
            "ID": str(e.exercise_id),
            "Exercise Name": e.exercise_name,
            "Sets": str(e.sets) if e.sets is not None else "",
            "Reps": e.reps or "",
            "Notes": e.notes or "",
        }
        for e in existing
    ]


@module.ui
def training_routines_ui():
    return ui.div(
        ui_helpers.page_header("Training Routines"),
        ui.output_ui("routine_library_filter"),
        ui.output_ui("routine_library"),
        ui.output_ui("create_routine_section"),
        ui.output_ui("routine_picker"),
        ui.output_ui("rename_routine_section"),
        ui.output_ui("exercise_grid_controls"),
        ui.output_data_frame("exercise_grid"),
        ui.output_ui("exercise_video_section"),
        ui_helpers.page_footer(),
    )


@module.server
def training_routines_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _exercise_rows = reactive.Value([])
    _exercise_rows_routine_id = reactive.Value(None)
    _registered_video_save_handlers = set()

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _excluded_session_type_names():
        if app_state.role_name() != "Coach" or app_state.coach_specialty() not in ("Pitching", "Hitting"):
            return set()
        return HITTING_SESSION_TYPES if app_state.coach_specialty() == "Pitching" else PITCHING_SESSION_TYPES

    def _visible_session_types(db):
        all_types = db.query(SessionType).order_by(SessionType.display_order).all()
        excluded = _excluded_session_type_names()
        return [t for t in all_types if t.type_name not in excluded]

    # -------------------------------------------------------------------
    # Routine library (read-only browse)
    # -------------------------------------------------------------------

    @render.ui
    def routine_library_filter():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            session_types = _visible_session_types(db)
            return ui.div(
                ui.p(ui.strong("Routine library")),
                ui.input_select("routine_type_filter", "Filter by type", choices=["All"] + [t.type_name for t in session_types]),
            )
        finally:
            db.close()

    @render.ui
    def routine_library():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("routine_type_filter" in input)
        type_filter = input.routine_type_filter()

        db = get_session()
        try:
            excluded_types = _excluded_session_type_names()
            routines_query = db.query(TrainingRoutine).join(SessionType)
            if excluded_types:
                routines_query = routines_query.filter(SessionType.type_name.notin_(excluded_types))
            if type_filter != "All":
                routines_query = routines_query.filter(SessionType.type_name == type_filter)
            routines = routines_query.order_by(TrainingRoutine.routine_name).all()

            if not routines:
                return ui_helpers.empty_state("No routines saved yet." if type_filter == "All" else f"No {type_filter} routines saved yet.")

            panels = []
            for r in routines:
                children = []
                if r.description:
                    children.append(ui.p(r.description))
                if not r.exercises:
                    children.append(ui.p("No exercises added to this routine yet.", class_="text-muted small"))
                else:
                    for e in r.exercises:
                        label = e.exercise_name
                        if e.sets or e.reps:
                            label += f" — {e.sets or '—'} sets x {e.reps or '—'}"
                        children.append(ui.p(ui.strong(label)))
                        if e.video_url:
                            children.append(ui.tags.video(ui.tags.source(src=e.video_url), controls=True, style="max-width:100%;"))
                        if e.notes:
                            children.append(ui.p(e.notes, class_="text-muted small"))
                panels.append(ui.accordion_panel(f"{r.routine_name} ({r.session_type.type_name if r.session_type else '—'})", *children))
            return ui.accordion(*panels, open=False, id=None)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Create a routine
    # -------------------------------------------------------------------

    @render.ui
    def create_routine_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if not app_state.can_edit_sessions():
            return ui.p("Your role has read-only access to the routine library.", class_="text-muted small")
        db = get_session()
        try:
            session_types = _visible_session_types(db)
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Create a new routine")),
                ui.input_text("new_routine_name", "Routine name", placeholder="e.g. Standard Post-Throw Recovery"),
                ui.input_select("new_routine_type", "Type", choices=[t.type_name for t in session_types]),
                ui.input_text_area("new_routine_description", "Description (optional)", placeholder="Brief overview of when/why to use this routine"),
                ui.input_action_button("create_routine_btn", "Create routine", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.create_routine_btn)
    def _create_routine():
        name = (input.new_routine_name() or "").strip()
        if not name:
            ui.notification_show("Routine name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            session_types = _visible_session_types(db)
            type_choice = input.new_routine_type()
            type_id = next((t.session_type_id for t in session_types if t.type_name == type_choice), None)
            if type_id is None:
                ui.notification_show("Select a type.", type="error", duration=8)
                return
            db.add(TrainingRoutine(
                session_type_id=type_id,
                routine_name=name,
                description=(input.new_routine_description() or "").strip() or None,
                created_by_user_id=app_state.user_id(),
            ))
            db.commit()
            ui.notification_show(f"Created routine: {name}", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Edit a routine: picker -> rename -> exercise grid -> videos
    # -------------------------------------------------------------------

    @render.ui
    def routine_picker():
        _refresh_tick()
        if not app_state.is_authenticated() or not app_state.can_edit_sessions():
            return None
        db = get_session()
        try:
            excluded_types = _excluded_session_type_names()
            routines_query = db.query(TrainingRoutine).join(SessionType)
            if excluded_types:
                routines_query = routines_query.filter(SessionType.type_name.notin_(excluded_types))
            routines = routines_query.order_by(TrainingRoutine.routine_name).all()
            if not routines:
                return ui.div(ui.hr(), ui.p(ui.strong("Edit a routine")), ui.p("Create a routine above first.", class_="text-muted small"))
            choices = {str(r.routine_id): r.routine_name for r in routines}
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Edit a routine")),
                ui.input_select("routine_select", "Routine", choices=choices),
            )
        finally:
            db.close()

    @reactive.effect
    def _reset_exercise_rows_on_routine_change():
        req("routine_select" in input)
        rid = int(input.routine_select())
        if rid != _exercise_rows_routine_id():
            _exercise_rows_routine_id.set(rid)
            db = get_session()
            try:
                _exercise_rows.set(_exercise_rows_from_db(db, rid))
            finally:
                db.close()

    @render.ui
    def rename_routine_section():
        _refresh_tick()
        if not app_state.is_authenticated() or not app_state.can_edit_sessions():
            return None
        req("routine_select" in input)
        db = get_session()
        try:
            routine = db.query(TrainingRoutine).filter(TrainingRoutine.routine_id == int(input.routine_select())).first()
            if routine is None:
                return None
            return ui.div(
                ui.input_text("edit_routine_name", "Routine name", value=routine.routine_name),
                ui.input_text_area("edit_routine_description", "Description (optional)", value=routine.description or ""),
                ui.input_action_button("save_routine_name_btn", "Save name/description", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_routine_name_btn)
    def _save_routine_name():
        req("routine_select" in input)
        new_name = (input.edit_routine_name() or "").strip()
        if not new_name:
            ui.notification_show("Routine name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            routine = db.query(TrainingRoutine).filter(TrainingRoutine.routine_id == int(input.routine_select())).first()
            if routine is None:
                return
            routine.routine_name = new_name
            routine.description = (input.edit_routine_description() or "").strip() or None
            db.commit()
            ui.notification_show("Saved.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    @render.data_frame
    def exercise_grid():
        req("routine_select" in input)
        df = pd.DataFrame(_exercise_rows(), columns=EXERCISE_COLUMNS, dtype="string").fillna("")
        return render.DataGrid(df, editable=True, selection_mode="rows", width="100%")

    @render.ui
    def exercise_grid_controls():
        _refresh_tick()
        if not app_state.is_authenticated() or not app_state.can_edit_sessions():
            return None
        req("routine_select" in input)
        return ui.div(
            ui.p(
                "Edit exercises below -- change values in place, select a row and use \"Remove selected\" to drop "
                "it, or add new rows at the bottom, then save. Leave ID blank on new rows -- existing exercises "
                "keep their ID (and video) automatically. Existing videos are kept unless you remove that row "
                "entirely.",
                class_="text-muted small",
            ),
            ui.input_action_button("add_exercise_rows_btn", f"+ Add {BLANK_EXERCISE_ROW_COUNT} rows", class_="btn-outline-secondary btn-sm"),
            ui.input_action_button("remove_exercise_rows_btn", "Remove selected", class_="btn-outline-secondary btn-sm ms-1"),
            ui.input_action_button("save_exercises_btn", "Save exercises", class_="btn-primary btn-sm ms-1"),
        )

    @reactive.effect
    @reactive.event(input.add_exercise_rows_btn)
    def _add_exercise_rows():
        current = exercise_grid.data_view().to_dict("records")
        _exercise_rows.set(current + _blank_exercise_rows(BLANK_EXERCISE_ROW_COUNT))

    @reactive.effect
    @reactive.event(input.remove_exercise_rows_btn)
    def _remove_exercise_rows():
        current = exercise_grid.data_view().to_dict("records")
        selected = exercise_grid.data_view(selected=True).to_dict("records")
        _exercise_rows.set(ui_helpers.remove_selected_grid_rows(current, selected))

    @reactive.effect
    @reactive.event(input.save_exercises_btn)
    def _save_exercises():
        req("routine_select" in input)
        selected_routine_id = int(input.routine_select())
        rows = exercise_grid.data_view().to_dict("records")
        valid_rows = [r for r in rows if (r.get("Exercise Name") or "").strip()]
        if not valid_rows:
            ui.notification_show("Add at least one exercise with a name before saving.", type="error", duration=8)
            return

        db = get_session()
        try:
            existing_exercises = db.query(RoutineExercise).filter(RoutineExercise.routine_id == selected_routine_id).all()
            exercises_by_id = {e.exercise_id: e for e in existing_exercises}
            existing_ids = set(exercises_by_id.keys())
            kept_ids = set()
            order = 1
            added = 0
            updated = 0
            sets_warnings = []
            for r in valid_rows:
                name = (r.get("Exercise Name") or "").strip()
                sets_raw = (r.get("Sets") or "").strip()
                sets = None
                if sets_raw:
                    try:
                        sets = int(sets_raw)
                    except ValueError:
                        sets_warnings.append(f"\"{sets_raw}\" for {name} isn't a whole number -- saved with Sets blank.")
                reps = (r.get("Reps") or "").strip() or None
                notes = (r.get("Notes") or "").strip() or None
                id_raw = (r.get("ID") or "").strip()
                row_id = int(id_raw) if id_raw.isdigit() else None

                if row_id is not None and row_id in exercises_by_id:
                    ex = exercises_by_id[row_id]
                    ex.exercise_name = name
                    ex.sets = sets
                    ex.reps = reps
                    ex.notes = notes
                    ex.display_order = order
                    kept_ids.add(row_id)
                    updated += 1
                else:
                    db.add(RoutineExercise(
                        routine_id=selected_routine_id,
                        exercise_name=name, sets=sets, reps=reps, notes=notes,
                        display_order=order,
                    ))
                    added += 1
                order += 1

            removed_ids = existing_ids - kept_ids
            for rid in removed_ids:
                db.delete(exercises_by_id[rid])

            db.commit()
            for w in sets_warnings:
                ui.notification_show(w, type="warning", duration=10)
            ui.notification_show(f"Saved -- {updated} updated, {added} added, {len(removed_ids)} removed.", type="message", duration=8)
            _exercise_rows.set(_exercise_rows_from_db(db, selected_routine_id))
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Per-exercise demo video
    # -------------------------------------------------------------------

    @render.ui
    def exercise_video_section():
        _refresh_tick()
        if not app_state.is_authenticated() or not app_state.can_edit_sessions():
            return None
        req("routine_select" in input)
        db = get_session()
        try:
            routine = db.query(TrainingRoutine).filter(TrainingRoutine.routine_id == int(input.routine_select())).first()
            if routine is None or not routine.exercises:
                return None

            blocks = [ui.hr(), ui.p(ui.strong(f"Attach a demo video to any exercise in {routine.routine_name}:"))]
            for e in routine.exercises:
                ex_label = e.exercise_name
                if e.sets or e.reps:
                    ex_label += f" ({e.sets or '—'} sets x {e.reps or '—'})"
                upload_id = f"video_upload_{e.exercise_id}"
                save_id = f"save_video_{e.exercise_id}"

                if save_id not in _registered_video_save_handlers:
                    _registered_video_save_handlers.add(save_id)
                    _register_video_save_handler(save_id, upload_id, e.exercise_id, e.exercise_name)

                exercise_children = [ui.p(ui.strong(ex_label))]
                if e.video_url:
                    exercise_children.append(ui.tags.video(ui.tags.source(src=e.video_url), controls=True, style="max-width:100%;"))
                    exercise_children.append(ui.p("Uploading a new video below will replace this one.", class_="text-muted small"))
                exercise_children.append(ui.input_file(upload_id, f"Video for {e.exercise_name}", accept=[".mp4", ".mov", ".m4v"]))
                exercise_children.append(ui.input_action_button(save_id, f"Save video for {e.exercise_name}", class_="btn-primary btn-sm mt-1"))
                blocks.append(ui.div(*exercise_children, class_="mb-3"))
            return ui.div(*blocks)
        finally:
            db.close()

    def _register_video_save_handler(save_id, upload_id, exercise_id, exercise_name):
        @reactive.effect
        @reactive.event(input[save_id])
        def _handler():
            files = input[upload_id]()
            if not files:
                return
            db = get_session()
            try:
                ex = db.query(RoutineExercise).filter(RoutineExercise.exercise_id == exercise_id).first()
                if ex is None:
                    return
                identifier = f"routine-{ex.routine_id}-exercise-{exercise_id}"
                url = _upload_routine_video(files[0], identifier)
                if url:
                    ex.video_url = url
                    db.commit()
                    ui.notification_show(f"Video saved for {exercise_name}.", type="message", duration=8)
                    _bump_refresh()
            finally:
                db.close()
