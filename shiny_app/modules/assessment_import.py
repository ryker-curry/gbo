"""
GBO -- Assessment Bulk Import module.

Lets a coach upload a filled-in GBO_Assessment_Import_Templates.xlsx sheet
(one category at a time, per Ryker's "one category per import" call) and
import every player's values in one shot instead of typing each one in by
hand on the Assessments page. UI-only, same split as rapsodo_import.py:
all the actual parsing/validation/writing lives in
services/assessment_import.py (framework-agnostic, already smoke-tested
against a real in-memory DB -- see that module's own docstring), this
module just drives it: pick a category -> upload the workbook -> pick
which tab to read (auto-matched to the category name when a tab by that
name exists) -> preview exactly what would happen, row by row -> confirm.

Role gating mirrors assessments.py, not rapsodo_import.py -- this touches
every category's data, not a pitching-only tool, so it's visible to
whoever can see Assessments (same ALLOWED_ROLES as nav.py's pd_pages
section) and gated on can_edit_assessments() the same way assessments.py's
own New/Edit sections are: a read-only role (Sports Scientist, Data
Analyst) can open this page and preview a sheet, same as browsing
Assessments, but the Import button itself is disabled without edit
permission.

assessment_import_spec.CATEGORY_SPECS only covers 8 of the 11 real
categories (Body Composition, Mobility & ROM, Arm Health, Upper Body
Strength, Lower Body Strength, Explosive Power, Rotational Power, Speed)
-- Anthropometrics was dropped (never measured), Baseball Performance has
no data yet, and Pitcher-Specific has its own per-pitch-type shape that
doesn't fit this generic sheet layout (it's still entered by hand on
Assessments). The category picker below only offers those 8; their
CATEGORY_SPECS dict order already matches AssessmentCategory.display_order
for exactly this subset, so no separate DB query/sort is needed just to
order the dropdown.
"""

import io

import pandas as pd
from shiny import module, ui, render, reactive, req

from database import get_session
from services.assessment_import import (
    preview_assessment_import, commit_assessment_import,
    AssessmentImportError, AssessmentValidationError, UnknownCategoryError,
)
from assessment_import_spec import CATEGORY_SPECS

import ui_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Strength Coach", "Athletic Trainer", "Sports Scientist", "Data Analyst")

_STATUS_LABELS = {
    "player_not_found": "Player not found",
    "no_date": "No date",
    "no_values": "Nothing to import",
}


@module.ui
def assessment_import_ui():
    return ui.div(
        ui_helpers.page_header(
            "Import Assessments",
            "Upload a filled-in template sheet to bring in a whole category's testing data at once, instead of "
            "typing each value in on Assessments.",
        ),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def assessment_import_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    # Same reset trick as rapsodo_import.py's _upload_key: Shiny's
    # ui.input_file has no built-in way to clear a previously-selected
    # file, so a dynamic id keyed off this counter forces a brand-new
    # (empty) widget whenever the category changes or an import succeeds
    # -- otherwise the last file stays "selected" and a stray re-click
    # would re-import it under a category it was never previewed against.
    _upload_key = reactive.Value(0)
    _last_result = reactive.Value(None)  # (category_name, commit result dict) after a successful import

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _upload_input_id():
        return f"assessment_file_{_upload_key()}"

    @reactive.effect
    @reactive.event(input.import_category_select)
    def _reset_upload_on_category_change():
        _upload_key.set(_upload_key() + 1)
        _last_result.set(None)

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() not in ALLOWED_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        category_choices = {name: name for name in CATEGORY_SPECS.keys()}
        # Preserve whatever category was already picked across every
        # re-render (this re-renders on _bump_refresh(), i.e. after every
        # import) -- same selected= preservation pattern used throughout
        # rapsodo_import.py/assessments.py, for the same reason: without
        # it, ui.input_select silently bounces back to the first choice.
        current = input.import_category_select() if "import_category_select" in input else None
        selected = current if current in category_choices else None

        sections = []
        if not app_state.can_edit_assessments():
            sections.append(ui.p(
                "Your role has read-only access -- you can preview what a sheet would do, but importing is disabled.",
                class_="text-muted small",
            ))
        sections.extend([
            ui.input_select("import_category_select", "Category", choices=category_choices, selected=selected),
            ui.p(
                "Use the matching tab from the template workbook you were given for this category -- column "
                "headers have to match exactly for a value to be recognized.",
                class_="text-muted small",
            ),
            ui.output_ui("upload_section"),
        ])
        return ui.div(*sections)

    @render.ui
    def upload_section():
        req("import_category_select" in input)
        return ui.div(
            ui.input_file(_upload_input_id(), "Filled-in template (.xlsx)", accept=[".xlsx"]),
            ui.output_ui("sheet_picker_section"),
        )

    @render.ui
    def sheet_picker_section():
        """A workbook can hold every category's sheet as its own tab (Ryker
        confirmed tabs-in-one-workbook is fine) -- this lists the actual
        tabs in whatever file was just uploaded and defaults to the one
        matching the selected category's name, but lets a coach pick a
        different tab if theirs is named slightly differently."""
        upload_id = _upload_input_id()
        req(upload_id in input)
        files = input[upload_id]()
        if not files:
            return ui.p("Upload a workbook to continue.", class_="text-muted small")

        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()

        try:
            sheet_names = pd.ExcelFile(io.BytesIO(file_bytes), engine="openpyxl").sheet_names
        except Exception as e:
            return ui.p(f"Couldn't read this file as an Excel workbook. Underlying error: {e}", class_="text-danger")
        if not sheet_names:
            return ui.p("This workbook has no sheets.", class_="text-danger")

        category_name = input.import_category_select()
        default_sheet = category_name if category_name in sheet_names else sheet_names[0]
        current = input.import_sheet_select() if "import_sheet_select" in input else None
        selected = current if current in sheet_names else default_sheet

        return ui.div(
            ui.input_select("import_sheet_select", "Sheet (tab)", choices=sheet_names, selected=selected),
            ui.output_ui("preview_section"),
        )

    @render.ui
    def preview_section():
        req("import_sheet_select" in input)
        upload_id = _upload_input_id()
        req(upload_id in input)
        files = input[upload_id]()
        if not files:
            return None

        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()
        category_name = input.import_category_select()
        sheet_name = input.import_sheet_select()

        db = get_session()
        try:
            try:
                preview = preview_assessment_import(
                    db, file_bytes=file_bytes, sheet_name=sheet_name, category_name=category_name,
                )
            except (AssessmentValidationError, UnknownCategoryError) as e:
                return ui.p(str(e), class_="text-danger")
        finally:
            db.close()

        sections = [ui.p(
            f"Read {len(preview['rows'])} row(s) from \"{sheet_name}\" -- "
            f"{preview['ok_row_count']} ready to import, {preview['skipped_row_count']} skipped.",
            class_="text-success" if preview["ok_row_count"] else "text-warning",
        )]

        if preview["unrecognized_columns"]:
            sections.append(ui.p(
                ui.strong("Unrecognized column(s): "), ", ".join(preview["unrecognized_columns"]),
                " -- these don't match this category's expected headers (a typo, or an extra column someone "
                "added) and won't be imported.",
                class_="text-warning small",
            ))
        if preview["unmapped_new_columns"]:
            sections.append(ui.p(
                ui.strong("Recognized but not importable yet: "), ", ".join(preview["unmapped_new_columns"]),
                " -- real, known columns that have no home in the schema yet. Their values are read but not "
                "stored -- nothing is lost, but nothing lands in the database for them either.",
                class_="text-muted small",
            ))

        row_dicts = []
        for r in preview["rows"]:
            if r["status"] == "ok":
                status_label = "Adds to existing entry" if r["existing_assessment_id"] else "New entry"
                detail = f"{len(r['values'])} value(s)"
                if r["duplicate_test_names"]:
                    detail += f", {len(r['duplicate_test_names'])} already recorded (skipped)"
                if r["player_updates"]:
                    detail += f", updates player profile ({', '.join(r['player_updates'].keys())})"
            else:
                status_label = _STATUS_LABELS.get(r["status"], r["status"])
                detail = r["reason"]
            row_dicts.append({
                "Row": r["file_row_num"],
                "Player": f"{r['first_name'] or '—'} {r['last_name'] or ''}".strip(),
                "Date": r["assessment_date"].strftime("%Y-%m-%d") if r["assessment_date"] else "—",
                "Status": status_label,
                "Detail": detail,
            })
        sections.append(ui.h5("Row-by-row preview", class_="gbo-section-title"))
        sections.append(ui_helpers.render_dict_table(row_dicts))

        if preview["ok_row_count"] == 0:
            sections.append(ui.p("Nothing here is ready to import.", class_="text-muted small"))
        elif not app_state.can_edit_assessments():
            sections.append(ui.p("Your role can't import -- ask a coach or admin to run this.", class_="text-muted small"))
        else:
            sections.append(ui.input_action_button(
                "do_import_assessments_btn", f"Import {preview['ok_row_count']} row(s)", class_="btn-primary mt-2",
            ))

        sections.append(ui.output_ui("import_result_section"))
        return ui.div(*sections)

    @reactive.effect
    @reactive.event(input.do_import_assessments_btn)
    def _do_import():
        if not app_state.can_edit_assessments():
            return
        upload_id = _upload_input_id()
        files = input[upload_id]() if upload_id in input else None
        if not files:
            return
        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()
        category_name = input.import_category_select()
        sheet_name = input.import_sheet_select()

        db = get_session()
        try:
            try:
                # Re-run preview fresh right before committing, rather than
                # reusing whatever preview_section last rendered -- guards
                # against acting on a stale preview if the underlying data
                # (another coach's import, a roster change) shifted between
                # when the preview was drawn and this click.
                preview = preview_assessment_import(
                    db, file_bytes=file_bytes, sheet_name=sheet_name, category_name=category_name,
                )
            except (AssessmentValidationError, UnknownCategoryError) as e:
                ui.notification_show(str(e), type="error", duration=12)
                return
            try:
                result = commit_assessment_import(db, preview, entered_by_user_id=app_state.user_id())
            except AssessmentImportError as e:
                ui.notification_show(str(e), type="error", duration=12)
                return
        finally:
            db.close()

        _last_result.set((category_name, result))
        _upload_key.set(_upload_key() + 1)  # clear the file widget, same trick as rapsodo_import.py

        entry_word = "entry" if result["assessments_created"] == 1 else "entries"
        reused_word = "entry" if result["assessments_reused"] == 1 else "entries"
        summary = (
            f"Imported {category_name}: {result['assessments_created']} new {entry_word}, "
            f"{result['assessments_reused']} existing {reused_word} added to, "
            f"{result['results_created']} value(s) recorded"
        )
        if result["players_updated"]:
            summary += f", {result['players_updated']} player profile(s) updated (throwing arm and/or height)"
        summary += "."
        ui.notification_show(summary, type="message", duration=10)
        _bump_refresh()

    @render.ui
    def import_result_section():
        """Deliberately reads _last_result() directly rather than anything
        upload-widget-related, so it keeps showing the last import's
        summary even after _upload_key resets the file input above it and
        preview_section (which embeds this) freezes on its last render --
        same req()-freeze behavior rapsodo_import.py's own
        import_result_section relies on after a successful import."""
        _refresh_tick()
        last = _last_result()
        if last is None:
            return None
        category_name, result = last
        return ui.div(
            ui.hr(),
            ui.p(
                f"Last import ({category_name}): {result['assessments_created']} new, "
                f"{result['assessments_reused']} reused, {result['results_created']} value(s), "
                f"{result['players_updated']} player profile update(s).",
                class_="text-success",
            ),
        )
