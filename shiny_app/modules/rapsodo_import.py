"""
GBO -- Import Rapsodo Data module.

Direct port of pages/rapsodo_import.py -- pick a pitcher -> pick or
start a bullpen session -> upload the Rapsodo CSV -> preview validation
-> import. All parsing/validation/insert logic stays in
services/rapsodo_import.py (already framework-agnostic -- reused
unchanged, per the migration plan's engine-boundary rule); this module
is UI only, same as the original.

Role gating, same three checks as the original page-level st.stop()
calls: role must be one of Administrator/Head Coach/Coach/Sports
Scientist/Data Analyst, AND a Coach specifically tagged "Hitting" is
excluded (this is a pitching-side tool). can_edit_sessions further
gates whether upload is enabled at all -- someone without it can still
browse existing sessions.

Deep link: the "Open full Bullpen Dashboard for this session" button
mirrors the original's st.switch_page + st.query_params combo via
app_state.deep_link_bullpen_id (a one-shot, consume-once value -- see
state.py's docstring) plus ui.update_navs("main_nav", selected="Bullpen
Dashboard"). Note the session=session.root_scope() on that call: this
module's own `session` is namespaced to "rapsodo_import", but
"main_nav" is a top-level id defined in app.py outside any module, so
the update has to go out through the root (un-namespaced) session or it
would silently address a "rapsodo_import-main_nav" id that doesn't
exist.
"""

from datetime import date

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, BullpenSession, BullpenType, RapsodoPitch
from services.rapsodo_import import (
    import_rapsodo_file, validate_file_structure, read_csv_bytes,
    DuplicateImportError, RapsodoValidationError, RapsodoImportError,
)

import ui_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")


@module.ui
def rapsodo_import_ui():
    return ui.div(
        ui_helpers.page_header("Import Rapsodo Data"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def rapsodo_import_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _last_import = reactive.Value(None)  # (import_record, target_bullpen) after a successful import

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _blocked_for_role():
        role_name = app_state.role_name()
        if role_name not in ALLOWED_ROLES:
            return True
        if role_name == "Coach" and app_state.coach_specialty() == "Hitting":
            return True
        return False

    def _visible_pitchers(db):
        query = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()
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

        can_edit_sessions = app_state.can_edit_sessions()
        db = get_session()
        try:
            pitchers = _visible_pitchers(db)
            if not pitchers:
                return ui_helpers.empty_state(
                    "No pitchers to show yet." if app_state.can_view_all_players() else "No pitchers are currently assigned to you."
                )
            pitcher_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitchers}

            sections = []
            if not can_edit_sessions:
                sections.append(ui.p(
                    "Your role has read-only access -- viewing is available once a session has been imported, "
                    "but you can't upload new data here.",
                    class_="text-muted small",
                ))

            sections.extend([
                ui.input_select("selected_pitcher_id", "Pitcher", choices=pitcher_choices),
                ui.hr(),
                ui.h5("Bullpen session", class_="gbo-section-title"),
                ui.output_ui("session_picker"),
                ui.hr(),
                ui.h5("Upload file", class_="gbo-section-title"),
                ui.output_ui("upload_section"),
            ])
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def session_picker():
        _refresh_tick()
        req("selected_pitcher_id" in input)
        selected_pitcher_id = int(input.selected_pitcher_id())
        can_edit_sessions = app_state.can_edit_sessions()

        db = get_session()
        try:
            existing_sessions = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.player_id == selected_pitcher_id)
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            choices = {"": "-- Start a new bullpen session --"}
            for b in existing_sessions:
                pitch_count = db.query(RapsodoPitch).filter(RapsodoPitch.bullpen_id == b.bullpen_id).count()
                choices[str(b.bullpen_id)] = f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {b.bullpen_type.type_name if b.bullpen_type else '—'} ({pitch_count} Rapsodo pitch(es))"

            fields = [ui.input_select("target_bullpen_choice", "Session to import into", choices=choices)]
            fields.append(ui.output_ui("new_session_fields"))
            return ui.div(*fields)
        finally:
            db.close()

    @render.ui
    def new_session_fields():
        req("target_bullpen_choice" in input)
        target_bullpen_id = input.target_bullpen_choice()
        can_edit_sessions = app_state.can_edit_sessions()

        if target_bullpen_id:
            return None  # importing into an existing session -- nothing new to configure
        if not can_edit_sessions:
            return ui.p("Your role can't start a new session. Ask a coach to start one, or select an existing session above.", class_="text-muted small")

        db = get_session()
        try:
            bullpen_types = db.query(BullpenType).order_by(BullpenType.display_order).all()
            if not bullpen_types:
                return ui.p("No bullpen types set up yet -- run the migration/seed script first.", class_="text-warning")
            type_choices = {str(t.bullpen_type_id): t.type_name for t in bullpen_types}
            return ui.div(
                ui.layout_columns(
                    ui.input_select("new_bullpen_type", "Bullpen type", choices=type_choices),
                    ui.input_date("new_bullpen_date", "Session date", value=date.today()),
                ),
                ui.input_text("new_bullpen_notes", "Session notes (optional)"),
            )
        finally:
            db.close()

    @render.ui
    def upload_section():
        req("selected_pitcher_id" in input)
        req("target_bullpen_choice" in input)
        can_edit_sessions = app_state.can_edit_sessions()

        if not can_edit_sessions:
            return ui.p("Read-only access -- upload is disabled for your role.", class_="text-muted small")

        return ui.div(
            ui.input_file("rapsodo_file", "Rapsodo CSV export", accept=[".csv"]),
            ui.output_ui("upload_preview_and_import"),
        )

    @render.ui
    def upload_preview_and_import():
        req("rapsodo_file" in input)
        files = input.rapsodo_file()
        if not files:
            return ui.p("Upload a Rapsodo CSV export to continue.", class_="text-muted small")

        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()

        try:
            preview_df = read_csv_bytes(file_bytes)
            field_to_column, unmapped_columns = validate_file_structure(preview_df)
        except RapsodoValidationError as e:
            return ui.p(str(e), class_="text-danger")

        target_bullpen_id = input.target_bullpen_choice()
        new_bullpen_type_id = input.new_bullpen_type() if "new_bullpen_type" in input else None

        sections = [
            ui.p(f"Read {len(preview_df)} row(s) from the file.", class_="text-success"),
            ui.accordion(
                ui.accordion_panel(
                    f"Column mapping preview ({len(field_to_column)} recognized field(s), {len(unmapped_columns)} unmapped)",
                    ui.p(ui.strong("Recognized fields: "), ", ".join(sorted(field_to_column.keys()))),
                    ui.p(
                        "These columns weren't recognized by name but will still be preserved in each pitch's raw data "
                        "(not displayed on charts, but not discarded either): " + ", ".join(unmapped_columns),
                        class_="text-muted small",
                    ) if unmapped_columns else None,
                ),
                open=False, id=None,
            ),
        ]

        if not target_bullpen_id and not new_bullpen_type_id:
            sections.append(ui.p("Choose a bullpen type above before importing (needed to start a new session).", class_="text-warning"))
            return ui.div(*sections)

        sections.append(ui.input_action_button("do_import_btn", "Import", class_="btn-primary mt-2"))
        sections.append(ui.output_ui("import_result_section"))
        return ui.div(*sections)

    @reactive.effect
    @reactive.event(input.do_import_btn)
    def _do_import():
        selected_pitcher_id = int(input.selected_pitcher_id())
        target_bullpen_id = input.target_bullpen_choice()
        files = input.rapsodo_file()
        if not files:
            return
        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()

        db = get_session()
        try:
            if target_bullpen_id:
                target_bullpen = db.query(BullpenSession).filter(BullpenSession.bullpen_id == int(target_bullpen_id)).first()
            else:
                new_bullpen_type_id = int(input.new_bullpen_type())
                new_bullpen_date = input.new_bullpen_date()
                new_bullpen_notes = (input.new_bullpen_notes() or "").strip() if "new_bullpen_notes" in input else ""
                target_bullpen = BullpenSession(
                    player_id=selected_pitcher_id,
                    bullpen_type_id=new_bullpen_type_id,
                    session_date=new_bullpen_date,
                    overall_notes=new_bullpen_notes or None,
                    created_by_user_id=app_state.user_id(),
                )
                db.add(target_bullpen)
                db.flush()  # assigns bullpen_id

            try:
                import_record = import_rapsodo_file(
                    db,
                    file_bytes=file_bytes,
                    original_filename=files[0]["name"],
                    player_id=selected_pitcher_id,
                    bullpen_id=target_bullpen.bullpen_id,
                    uploaded_by_user_id=app_state.user_id(),
                )
            except DuplicateImportError as e:
                db.rollback()
                ui.notification_show(str(e), type="error", duration=12)
                return
            except RapsodoValidationError as e:
                db.rollback()
                ui.notification_show(f"This file couldn't be imported: {e}", type="error", duration=12)
                return
            except RapsodoImportError as e:
                db.rollback()
                ui.notification_show(str(e), type="error", duration=12)
                return

            db.commit()
            _last_import.set((import_record.import_id, target_bullpen.bullpen_id, target_bullpen.session_date))

            summary_msg = f"Imported {import_record.imported_row_count} pitch(es) into the {target_bullpen.session_date.strftime('%Y-%m-%d (%a)')} session."
            if import_record.rejected_row_count:
                summary_msg += f" {import_record.rejected_row_count} row(s) were skipped -- see details below."
            ui.notification_show(summary_msg, type="message", duration=10)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def import_result_section():
        _refresh_tick()
        last = _last_import()
        if last is None:
            return None
        import_id, bullpen_id, session_date = last

        db = get_session()
        try:
            from models import RapsodoImport
            import_record = db.query(RapsodoImport).filter(RapsodoImport.import_id == import_id).first()
            sections = []
            if import_record and import_record.error_summary:
                sections.append(ui.accordion(
                    ui.accordion_panel(
                        f"Skipped rows ({import_record.rejected_row_count})",
                        *[ui.p(line, class_="text-muted small") for line in import_record.error_summary.split("; ")],
                    ),
                    open=False, id=None,
                ))

            imported_pitches = (
                db.query(RapsodoPitch)
                .options(joinedload(RapsodoPitch.pitch_type))
                .filter(RapsodoPitch.import_id == import_id)
                .order_by(RapsodoPitch.pitch_number)
                .all()
            )
            if imported_pitches:
                sections.append(ui.h5("Imported pitches", class_="gbo-section-title"))
                sections.append(ui_helpers.render_dict_table([
                    {
                        "#": p.pitch_number,
                        "Time": p.pitch_date.strftime("%I:%M:%S %p") if p.pitch_date else "—",
                        "Pitch Type": p.pitch_type.type_name if p.pitch_type else (p.raw_pitch_type or "—"),
                        "Velocity (mph)": float(p.velocity) if p.velocity is not None else "—",
                        "Total Spin (rpm)": float(p.total_spin) if p.total_spin is not None else "—",
                        "IVB (in)": float(p.vb_spin) if p.vb_spin is not None else "—",
                        "HB (in)": float(p.hb_spin) if p.hb_spin is not None else "—",
                        "Extension (ft)": float(p.release_extension) if p.release_extension is not None else "—",
                        "Strike": "Y" if p.is_strike else ("N" if p.is_strike is False else "—"),
                    }
                    for p in imported_pitches
                ]))

            sections.append(ui.hr())
            sections.append(ui.input_action_button(
                "open_bullpen_dashboard_btn",
                f"Open full Bullpen Dashboard ({session_date.strftime('%Y-%m-%d (%a)')} session)",
                class_="btn-outline-primary",
            ))
            return ui.div(*sections)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.open_bullpen_dashboard_btn)
    def _open_bullpen_dashboard():
        last = _last_import()
        if last is None:
            return
        _, bullpen_id, _ = last
        app_state.deep_link_bullpen_id.set(bullpen_id)
        ui.update_navs("main_nav", selected="Bullpen Dashboard", session=session.root_scope())
