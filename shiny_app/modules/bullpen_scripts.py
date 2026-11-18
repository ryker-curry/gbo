"""
GBO -- Bullpen Scripts module.

Direct port of pages/bullpen_scripts.py -- a reusable, pre-planned pitch
sequence, loaded on Bullpen Tracking to pre-create a whole planned
bullpen at once. Second of Task #11's three st.data_editor pages --
same "bulk add via a working-rows grid" pattern opponent_teams.py
establishes (see that module's docstring for the full rationale); this
page's only real difference is that Pitch Type and Intended Zone are
constrained-choice fields in the original (SelectboxColumn) rather than
free text, so this module validates both against the real lookup values
on save instead of relying on a dropdown at cell-edit time (Shiny's
editable data_frame has no per-column constrained cell editor as of
shiny 1.7 -- see opponent_teams.py's docstring for the full spike
writeup).
"""

import pandas as pd

from shiny import module, ui, render, reactive, req

from database import get_session
from models import BullpenType, BullpenScript, BullpenScriptPitch, PitchType

import ui_helpers

SCRIPT_PITCH_COLUMNS = ["Pitch Type", "Intended Zone", "Notes"]
ZONE_CHOICES = ["0 - Bury"] + [str(z) for z in range(1, 10)]
BLANK_SCRIPT_ROW_COUNT = 8

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")


def _blank_script_rows(n):
    return [{c: "" for c in SCRIPT_PITCH_COLUMNS} for _ in range(n)]


def _zone_text_to_int(text):
    """Accepts either the dropdown-style "0 - Bury" / "5" the original
    used, or a bare zone number typed directly -- returns None if it
    doesn't parse to 0-9."""
    text = (text or "").strip()
    if not text:
        return None
    first_token = text.split(" ")[0]
    try:
        z = int(first_token)
    except ValueError:
        return None
    return z if 0 <= z <= 9 else None


@module.ui
def bullpen_scripts_ui():
    return ui.div(
        ui_helpers.page_header("Bullpen Scripts"),
        ui.output_ui("script_library"),
        ui.output_ui("create_script_section"),
        ui.output_ui("script_picker"),
        ui.output_ui("script_grid_controls"),
        ui.output_data_frame("script_grid"),
        ui_helpers.page_footer(),
    )


@module.server
def bullpen_scripts_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _script_rows = reactive.Value(_blank_script_rows(BLANK_SCRIPT_ROW_COUNT))
    _script_rows_script_id = reactive.Value(None)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _access_ok():
        if not app_state.is_authenticated():
            return False
        if app_state.role_name() not in ALLOWED_ROLES:
            return False
        if app_state.role_name() == "Coach" and app_state.coach_specialty() == "Hitting":
            return False
        return True

    @render.ui
    def script_library():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if not _access_ok():
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            scripts = db.query(BullpenScript).order_by(BullpenScript.script_name).all()
            sections = [ui.p(ui.strong("Script library"))]
            if not scripts:
                sections.append(ui_helpers.empty_state("No bullpen scripts saved yet."))
            else:
                sections.append(ui.accordion(*[
                    ui.accordion_panel(
                        f"{s.script_name} ({s.bullpen_type.type_name if s.bullpen_type else '—'}) — {len(s.pitches)} pitch(es)",
                        ui_helpers.render_dict_table([
                            {
                                "#": p.pitch_number,
                                "Pitch Type": p.pitch_type.type_name if p.pitch_type else "—",
                                "Intended Zone": "Bury" if p.target_zone == 0 else p.target_zone,
                                "Notes": p.notes or "",
                            }
                            for p in s.pitches
                        ], empty_message="No pitches added to this script yet."),
                    )
                    for s in scripts
                ], open=False, id=None))
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def create_script_section():
        _refresh_tick()
        if not _access_ok():
            return None
        if not app_state.can_edit_sessions():
            return ui.p("Your role has read-only access to bullpen scripts.", class_="text-muted small")
        db = get_session()
        try:
            bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all()
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Create a new script")),
                ui.input_text("new_script_name", "Script name", placeholder="e.g. 25-pitch Execution Ladder"),
                ui.input_select("new_script_type", "Bullpen type", choices=[t.type_name for t in bullpen_types]),
                ui.input_action_button("create_script_btn", "Create script", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.create_script_btn)
    def _create_script():
        name = (input.new_script_name() or "").strip()
        if not name:
            ui.notification_show("Script name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all()
            type_choice = input.new_script_type()
            type_id = next((t.bullpen_type_id for t in bullpen_types if t.type_name == type_choice), None)
            if type_id is None:
                ui.notification_show("Select a bullpen type.", type="error", duration=8)
                return
            db.add(BullpenScript(script_name=name, bullpen_type_id=type_id, created_by_user_id=app_state.user_id()))
            db.commit()
            ui.notification_show(f"Created script: {name}", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Planned-pitch grid (bulk add)
    # -------------------------------------------------------------------

    @render.ui
    def script_picker():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        db = get_session()
        try:
            scripts = db.query(BullpenScript).order_by(BullpenScript.script_name).all()
            if not scripts:
                return ui.div(ui.hr(), ui.p(ui.strong("Add planned pitches to a script")), ui.p("Create a script above first.", class_="text-muted small"))
            choices = {str(s.script_id): s.script_name for s in scripts}
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Add planned pitches to a script")),
                ui.input_select("script_select", "Script", choices=choices),
            )
        finally:
            db.close()

    @reactive.effect
    def _reset_script_rows_on_script_change():
        req("script_select" in input)
        sid = int(input.script_select())
        if sid != _script_rows_script_id():
            _script_rows_script_id.set(sid)
            _script_rows.set(_blank_script_rows(BLANK_SCRIPT_ROW_COUNT))

    @render.data_frame
    def script_grid():
        req("script_select" in input)
        df = pd.DataFrame(_script_rows(), columns=SCRIPT_PITCH_COLUMNS, dtype="string").fillna("")
        return render.DataGrid(df, editable=True, selection_mode="rows", width="100%")

    @render.ui
    def script_grid_controls():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("script_select" in input)
        db = get_session()
        try:
            pitch_type_names = [pt.type_name for pt in db.query(PitchType).order_by(PitchType.pitch_type_id).all()]
        finally:
            db.close()
        return ui.div(
            ui.p(
                f"Type the planned sequence below -- add as many rows as you need, then save. "
                f"Pitch Type must match one of: {', '.join(pitch_type_names)}. "
                f"Intended Zone should be 0-9 (0 = Bury).",
                class_="text-muted small",
            ),
            ui.input_action_button("add_script_rows_btn", f"+ Add {BLANK_SCRIPT_ROW_COUNT} rows", class_="btn-outline-secondary btn-sm"),
            ui.input_action_button("remove_script_rows_btn", "Remove selected", class_="btn-outline-secondary btn-sm ms-1"),
            ui.input_action_button("save_script_pitches_btn", "Save planned pitches", class_="btn-primary btn-sm ms-1"),
        )

    @reactive.effect
    @reactive.event(input.add_script_rows_btn)
    def _add_script_rows():
        current = script_grid.data_view().to_dict("records")
        _script_rows.set(current + _blank_script_rows(BLANK_SCRIPT_ROW_COUNT))

    @reactive.effect
    @reactive.event(input.remove_script_rows_btn)
    def _remove_script_rows():
        current = script_grid.data_view().to_dict("records")
        selected = script_grid.data_view(selected=True).to_dict("records")
        _script_rows.set(ui_helpers.remove_selected_grid_rows(current, selected))

    @reactive.effect
    @reactive.event(input.save_script_pitches_btn)
    def _save_script_pitches():
        req("script_select" in input)
        selected_script_id = int(input.script_select())
        rows = script_grid.data_view().to_dict("records")
        valid_rows = [r for r in rows if (r.get("Pitch Type") or "").strip() and (r.get("Intended Zone") or "").strip()]
        if not valid_rows:
            ui.notification_show("Add at least one planned pitch (pitch type + intended zone) before saving.", type="error", duration=8)
            return

        db = get_session()
        try:
            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            pitch_types_by_name = {pt.type_name: pt.pitch_type_id for pt in pitch_types}

            errors = []
            parsed_rows = []
            for i, r in enumerate(valid_rows, start=1):
                pt_name = (r.get("Pitch Type") or "").strip()
                zone = _zone_text_to_int(r.get("Intended Zone"))
                if pt_name not in pitch_types_by_name:
                    errors.append(f"Row {i}: Pitch Type \"{pt_name}\" doesn't match any known pitch type.")
                    continue
                if zone is None:
                    errors.append(f"Row {i}: Intended Zone \"{r.get('Intended Zone')}\" isn't 0-9.")
                    continue
                parsed_rows.append((pt_name, zone, (r.get("Notes") or "").strip() or None))
            if errors:
                for e in errors:
                    ui.notification_show(e, type="error", duration=12)
                return

            selected_script = db.query(BullpenScript).filter(BullpenScript.script_id == selected_script_id).first()
            if selected_script is None:
                return
            next_number = len(selected_script.pitches) + 1
            for pt_name, zone, notes in parsed_rows:
                db.add(BullpenScriptPitch(
                    script_id=selected_script_id,
                    pitch_number=next_number,
                    pitch_type_id=pitch_types_by_name[pt_name],
                    target_zone=zone,
                    notes=notes,
                ))
                next_number += 1
            db.commit()
            ui.notification_show(f"Added {len(parsed_rows)} planned pitch(es).", type="message", duration=8)
            _script_rows.set(_blank_script_rows(BLANK_SCRIPT_ROW_COUNT))
            _bump_refresh()
        finally:
            db.close()
