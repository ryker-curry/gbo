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

Delete an import (Aug 2026, Ryker's request -- "I accidentally put the
wrong one for somebody"): services/rapsodo_import.py already has a
delete_rapsodo_import() function (removes the RapsodoPitch rows +
RapsodoImport audit record for one import, leaves the parent
BullpenSession alone) -- this module just adds the UI to call it, in
two places: a quick "undo" right after a fresh upload
(import_result_section), and a general "past imports" list+delete for
an existing session (existing_imports_section, under session_picker),
since a wrong-pitcher upload might not be noticed until later.

Intrasquad-game imports (Aug 2026, plan doc section 9 -- getting
Rapsodo's ball-flight metrics linked to the pitch result/run value
Game Tracking already records, ahead of intrasquads starting the week
of Sep 7): a second target-type mode alongside the original
bullpen-session flow, picked via the new "Import into" radio
(target_type). Choosing "Intrasquad Game" swaps session_picker for
game_picker (a game picker scoped to Game.is_intrasquad games only --
real external games have no equivalent UI yet) and routes the upload
through _do_game_import instead of the original bullpen path in
_do_import. The parsing/validation/insert logic in
services/rapsodo_import.py is unchanged and shared by both modes
(import_rapsodo_file now takes either bullpen_id or game_id, never
both); what's new for the game path is the auto-match pass right after
import (auto_match_rapsodo_to_game_pitches), which links each Rapsodo
reading to the specific charted GamePitch it came from when the two
pitch counts agree, and populates that GamePitch's actual location
from Rapsodo's raw coordinates (never from Rapsodo's own strike/ball
call -- see rapsodo_conventions.py and strike_zone.py, and the "video
review is the correction step" design in the plan doc). When the
counts don't match, game_import_result_section shows a warning instead
of a clean-match message, and manual_match_table takes over: one row
per Rapsodo pitch, each pre-matched by order to the game pitch in the
same position (a starting point, not a claim it's already correct) and
freely reassignable, applied via apply_manual_rapsodo_game_pitch_matches.
Kept as a separate reactive.Value (_last_game_import) and separate
render outputs from the original bullpen-session result section rather
than widening that flow's state shape -- see _last_game_import's inline
comment.
"""

from datetime import date

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, BullpenSession, BullpenType, RapsodoPitch, RapsodoImport, Game
from services.rapsodo_import import (
    import_rapsodo_file, validate_file_structure, read_csv_bytes, delete_rapsodo_import,
    auto_match_rapsodo_to_game_pitches, apply_manual_rapsodo_game_pitch_matches,
    DuplicateImportError, RapsodoValidationError, RapsodoImportError, RapsodoImportNotFoundError,
)
from game_stats import get_pitching_pitches

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
    # Bug fix (Aug 2026, Ryker: "previous pitcher's data is still there"):
    # Shiny's ui.input_file has no built-in way to clear a previously
    # selected file, and _last_import above wasn't being reset when the
    # pitcher changed -- so switching from Pitcher A to Pitcher B left
    # Pitcher A's file still "selected" in the widget AND Pitcher A's
    # "Imported pitches" summary still on screen. Worse: if someone
    # switched pitchers and clicked Import again without deliberately
    # re-choosing a file, Pitcher A's already-selected file would get
    # imported and attributed to Pitcher B. Fix: give the file input a
    # dynamic id keyed off this counter -- bumping it forces Shiny to
    # mount a brand-new (empty) file widget, the standard reset trick
    # since there's no ui.update_file(). Bumped whenever the pitcher
    # changes (_reset_upload_on_pitcher_change below) and after every
    # successful import (_do_import), so the next upload always starts
    # from a clean slate.
    _upload_key = reactive.Value(0)
    # (import_id, game_id, match_result) after a successful import linked
    # to an intrasquad-game outing -- kept as a separate reactive.Value
    # from _last_import rather than widening that tuple's shape, since
    # _last_import's (import_id, bullpen_id, session_date) shape is relied
    # on unchanged by the existing bullpen-session flow below.
    _last_game_import = reactive.Value(None)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _upload_input_id():
        return f"rapsodo_file_{_upload_key()}"

    @reactive.effect
    @reactive.event(input.selected_pitcher_id)
    def _reset_upload_on_pitcher_change():
        _upload_key.set(_upload_key() + 1)
        _last_import.set(None)
        _last_game_import.set(None)

    @reactive.effect
    @reactive.event(input.target_type)
    def _reset_upload_on_target_type_change():
        # Switching between "Bullpen Session" and "Intrasquad Game" is the
        # same kind of context change as switching pitchers (Aug 2026 bug
        # fix above) -- reset the file widget and any leftover result from
        # the other mode so a stray leftover file/result can't get
        # attributed to the wrong target.
        _upload_key.set(_upload_key() + 1)
        _last_import.set(None)
        _last_game_import.set(None)

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
                ui.input_radio_buttons(
                    "target_type", "Import into",
                    choices={"bullpen": "Bullpen Session", "game": "Intrasquad Game"},
                    selected="bullpen", inline=True,
                ),
                ui.output_ui("target_picker"),
                ui.hr(),
                ui.h5("Upload file", class_="gbo-section-title"),
                ui.output_ui("upload_section"),
            ])
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def target_picker():
        req("target_type" in input)
        if input.target_type() == "game":
            return ui.div(
                ui.h5("Intrasquad game", class_="gbo-section-title"),
                ui.output_ui("game_picker"),
            )
        return ui.div(
            ui.h5("Bullpen session", class_="gbo-section-title"),
            ui.output_ui("session_picker"),
        )

    @render.ui
    def game_picker():
        """Aug 2026: lets a coach import a Rapsodo export for a pitcher's
        outing in an intrasquad game instead of a bullpen session (plan
        doc section 9). Deliberately scoped to Game.is_intrasquad games
        only, matching the decision that this whole feature starts
        intrasquad-only -- a real external game has no equivalent UI yet.
        The pitcher is whichever one is already selected above; matching
        this file's pitches to that pitcher's specific charted stint in
        the chosen game is handled after import (see
        auto_match_rapsodo_to_game_pitches / manual_match_table below)."""
        _refresh_tick()
        db = get_session()
        try:
            games = (
                db.query(Game)
                .filter(Game.is_intrasquad.is_(True))
                .order_by(Game.game_date.desc())
                .all()
            )
            if not games:
                return ui_helpers.empty_state("No intrasquad games logged yet -- create one in Game Tracking first.")
            game_choices = {
                str(g.game_id): f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {g.opponent_name or 'Intrasquad'}"
                for g in games
            }
            return ui.input_select("target_game_id", "Game", choices=game_choices)
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
            if can_edit_sessions:
                fields.append(ui.output_ui("existing_imports_section"))
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
    def existing_imports_section():
        """Lists every Rapsodo import tied to the currently-selected
        EXISTING bullpen session (does nothing for "-- Start a new
        bullpen session --", since there's nothing imported into it
        yet), each with the option to delete it -- covers a mistake
        found later, not just right after uploading (see
        import_result_section's own quick-delete for that immediate
        case). A session can hold more than one import (e.g. two
        Rapsodo files from the same outing), so this is a picker +
        single delete action, same pattern as players.py's player_select
        + confirm-checkbox + save flow, rather than one button per row."""
        _refresh_tick()
        req("target_bullpen_choice" in input)
        target_bullpen_id = input.target_bullpen_choice()
        if not target_bullpen_id:
            return None

        db = get_session()
        try:
            imports = (
                db.query(RapsodoImport)
                .filter(RapsodoImport.bullpen_id == int(target_bullpen_id))
                .order_by(RapsodoImport.uploaded_at.desc())
                .all()
            )
            if not imports:
                return None

            import_choices = {
                str(imp.import_id): (
                    f"{imp.original_filename} — uploaded {imp.uploaded_at.strftime('%Y-%m-%d %I:%M %p')} "
                    f"({imp.imported_row_count} pitch(es) imported"
                    + (f", {imp.rejected_row_count} skipped" if imp.rejected_row_count else "")
                    + ")"
                )
                for imp in imports
            }
            return ui.div(
                ui.markdown("**Imports on this session**"),
                ui.input_select("import_to_delete", "Delete an import", choices=import_choices),
                ui.input_checkbox(
                    "confirm_delete_import_existing",
                    "Yes, permanently delete this import and every pitch it added (this can't be undone)",
                    value=False,
                ),
                ui.input_action_button("delete_existing_import_btn", "Delete selected import", class_="btn-outline-danger btn-sm mt-2"),
                class_="mt-3 mb-2",
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_existing_import_btn)
    def _delete_existing_import():
        if not input.confirm_delete_import_existing():
            ui.notification_show("Check the confirmation box before deleting an import.", type="warning", duration=8)
            return
        import_id = int(input.import_to_delete())
        db = get_session()
        try:
            try:
                summary = delete_rapsodo_import(db, import_id)
            except RapsodoImportNotFoundError as e:
                ui.notification_show(str(e), type="error", duration=10)
                return
            except RapsodoImportError as e:
                ui.notification_show(str(e), type="error", duration=10)
                return
            ui.notification_show(
                f"Deleted \"{summary['original_filename']}\" -- removed {summary['deleted_pitch_count']} pitch(es).",
                type="message", duration=8,
            )
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def upload_section():
        req("selected_pitcher_id" in input)
        target_type = input.target_type() if "target_type" in input else "bullpen"
        if target_type == "game":
            req("target_game_id" in input)
        else:
            req("target_bullpen_choice" in input)
        can_edit_sessions = app_state.can_edit_sessions()

        if not can_edit_sessions:
            return ui.p("Read-only access -- upload is disabled for your role.", class_="text-muted small")

        return ui.div(
            ui.input_file(_upload_input_id(), "Rapsodo CSV export", accept=[".csv"]),
            ui.output_ui("upload_preview_and_import"),
        )

    @render.ui
    def upload_preview_and_import():
        upload_id = _upload_input_id()
        req(upload_id in input)
        files = input[upload_id]()
        if not files:
            return ui.p("Upload a Rapsodo CSV export to continue.", class_="text-muted small")

        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()

        try:
            preview_df = read_csv_bytes(file_bytes)
            field_to_column, unmapped_columns = validate_file_structure(preview_df)
        except RapsodoValidationError as e:
            return ui.p(str(e), class_="text-danger")

        target_type = input.target_type() if "target_type" in input else "bullpen"

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

        if target_type == "game":
            if "target_game_id" not in input or not input.target_game_id():
                sections.append(ui.p("Choose a game above before importing.", class_="text-warning"))
                return ui.div(*sections)
            sections.append(ui.input_action_button("do_import_btn", "Import", class_="btn-primary mt-2"))
            sections.append(ui.output_ui("game_import_result_section"))
            return ui.div(*sections)

        target_bullpen_id = input.target_bullpen_choice()
        new_bullpen_type_id = input.new_bullpen_type() if "new_bullpen_type" in input else None
        if not target_bullpen_id and not new_bullpen_type_id:
            sections.append(ui.p("Choose a bullpen type above before importing (needed to start a new session).", class_="text-warning"))
            return ui.div(*sections)

        sections.append(ui.input_action_button("do_import_btn", "Import", class_="btn-primary mt-2"))
        sections.append(ui.output_ui("import_result_section"))
        return ui.div(*sections)

    def _do_game_import(selected_pitcher_id, files, file_bytes):
        """The intrasquad-game counterpart of _do_import's bullpen path
        below -- pulled into its own function (rather than another branch
        inline) since the post-import step differs in kind, not just
        detail: a bullpen import is done once it's saved, but a
        game-linked import always needs the auto-match pass run right
        after (plan doc section 9), and its result (clean match vs. a
        count mismatch needing manual reconciliation) has to reach
        game_import_result_section instead of import_result_section."""
        target_game_id = int(input.target_game_id())
        db = get_session()
        try:
            try:
                import_record = import_rapsodo_file(
                    db,
                    file_bytes=file_bytes,
                    original_filename=files[0]["name"],
                    player_id=selected_pitcher_id,
                    uploaded_by_user_id=app_state.user_id(),
                    game_id=target_game_id,
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

            try:
                match_result = auto_match_rapsodo_to_game_pitches(db, import_record.import_id, target_game_id)
            except RapsodoImportNotFoundError as e:
                match_result = {"status": "error", "error": str(e)}
            except RapsodoImportError as e:
                match_result = {"status": "error", "error": str(e)}

            _last_game_import.set((import_record.import_id, target_game_id, match_result))
            _upload_key.set(_upload_key() + 1)

            summary_msg = f"Imported {import_record.imported_row_count} pitch(es) for this outing."
            if import_record.rejected_row_count:
                summary_msg += f" {import_record.rejected_row_count} row(s) were skipped -- see details below."
            status = match_result.get("status") if match_result else None
            if status == "matched":
                summary_msg += f" Matched all {match_result['matched_count']} pitch(es) to the charted game pitches."
            elif status == "count_mismatch":
                summary_msg += (
                    f" This file has {match_result['rapsodo_pitch_count']} pitch(es) but the charted stint has "
                    f"{match_result['game_pitch_count']} -- match them by hand below."
                )
            elif status == "no_pitches":
                summary_msg += " Nothing to auto-match yet -- see details below."
            ui.notification_show(summary_msg, type="message", duration=10)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.do_import_btn)
    def _do_import():
        selected_pitcher_id = int(input.selected_pitcher_id())
        target_type = input.target_type() if "target_type" in input else "bullpen"
        upload_id = _upload_input_id()
        files = input[upload_id]() if upload_id in input else None
        if not files:
            return
        with open(files[0]["datapath"], "rb") as f:
            file_bytes = f.read()

        if target_type == "game":
            _do_game_import(selected_pitcher_id, files, file_bytes)
            return

        target_bullpen_id = input.target_bullpen_choice()
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
            # Clear the file widget after every successful import (same
            # reset trick as the pitcher-change handler above) -- without
            # this, the just-imported file stays "selected," and a stray
            # second click on Import would try to re-import the exact
            # same file (caught by DuplicateImportError, but confusing).
            _upload_key.set(_upload_key() + 1)

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
            import_record = db.query(RapsodoImport).filter(RapsodoImport.import_id == import_id).first()
            if import_record is None:
                # Already deleted (e.g. via the quick-undo button below, or
                # the existing_imports_section picker further up the page)
                # -- nothing left to show for it.
                _last_import.set(None)
                return None
            sections = []
            if import_record.error_summary:
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

            # Quick undo -- imported the wrong file, or into the wrong
            # pitcher, and noticed immediately. existing_imports_section
            # above (under session_picker) covers the same delete for a
            # mistake noticed later, after leaving this page.
            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Made a mistake? "), "Wrong pitcher, wrong file, or a bad export.", class_="text-muted small"))
            sections.append(ui.input_checkbox("confirm_delete_import", "Yes, permanently delete this import and every pitch it added", value=False))
            sections.append(ui.input_action_button("delete_import_btn", "Delete this import", class_="btn-outline-danger btn-sm"))
            return ui.div(*sections)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_import_btn)
    def _delete_just_imported():
        if not input.confirm_delete_import():
            ui.notification_show("Check the confirmation box before deleting this import.", type="warning", duration=8)
            return
        last = _last_import()
        if last is None:
            return
        import_id, _, _ = last
        db = get_session()
        try:
            try:
                summary = delete_rapsodo_import(db, import_id)
            except RapsodoImportNotFoundError as e:
                ui.notification_show(str(e), type="error", duration=10)
                _last_import.set(None)
                return
            except RapsodoImportError as e:
                ui.notification_show(str(e), type="error", duration=10)
                return
            ui.notification_show(
                f"Deleted \"{summary['original_filename']}\" -- removed {summary['deleted_pitch_count']} pitch(es).",
                type="message", duration=8,
            )
            _last_import.set(None)
            _bump_refresh()
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

    @render.ui
    def game_import_result_section():
        """Intrasquad-game counterpart of import_result_section above --
        separate output/reactive.Value (see _last_game_import's comment)
        since the content differs: a match-result banner (and, on a
        count mismatch, the manual reconciliation table) instead of the
        "open Bullpen Dashboard" deep link, which doesn't apply here."""
        _refresh_tick()
        last = _last_game_import()
        if last is None:
            return None
        import_id, game_id, match_result = last

        db = get_session()
        try:
            import_record = db.query(RapsodoImport).filter(RapsodoImport.import_id == import_id).first()
            if import_record is None:
                # Already deleted (e.g. via the delete button below).
                _last_game_import.set(None)
                return None
            sections = []
            if import_record.error_summary:
                sections.append(ui.accordion(
                    ui.accordion_panel(
                        f"Skipped rows ({import_record.rejected_row_count})",
                        *[ui.p(line, class_="text-muted small") for line in import_record.error_summary.split("; ")],
                    ),
                    open=False, id=None,
                ))

            status = match_result.get("status") if match_result else None
            if status == "matched":
                sections.append(ui.p(
                    f"Matched all {match_result['matched_count']} Rapsodo pitch(es) to this outing's charted "
                    f"pitches -- actual location and physical pitch data are now linked on those game pitches.",
                    class_="text-success",
                ))
            elif status == "count_mismatch":
                sections.append(ui.p(
                    f"This file has {match_result['rapsodo_pitch_count']} pitch(es), but the charted stint for "
                    f"this pitcher in this game has {match_result['game_pitch_count']}. A pitch count can differ "
                    f"in a live game (a foul tip double-read, a swing that blocked the radar, a warm-up throw that "
                    f"leaked into the export) -- match them up by hand below before they'll link to actual "
                    f"location / physical pitch data.",
                    class_="text-warning",
                ))
                sections.append(ui.output_ui("manual_match_table"))
            elif status == "no_pitches":
                sections.append(ui.p(
                    "Nothing to match yet -- either this file or the charted stint for this pitcher in this game "
                    "has no pitches on record.",
                    class_="text-muted small",
                ))
            elif status == "error":
                sections.append(ui.p(f"Matching couldn't run: {match_result.get('error')}", class_="text-danger"))

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
                        "Matched to game pitch": "Yes" if p.game_pitch_id else "No",
                    }
                    for p in imported_pitches
                ]))

            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Made a mistake? "), "Wrong pitcher, wrong file, or a bad export.", class_="text-muted small"))
            sections.append(ui.input_checkbox("confirm_delete_game_import", "Yes, permanently delete this import and every pitch it added", value=False))
            sections.append(ui.input_action_button("delete_game_import_btn", "Delete this import", class_="btn-outline-danger btn-sm"))
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def manual_match_table():
        """Pitch-by-pitch reconciliation for a count-mismatched game
        import (plan doc section 9: "charted pitches on one side, Rapsodo
        readings on the other, pre-matched by order... adjustable by
        hand"). Pre-selects each Rapsodo pitch against the game pitch at
        the same position (same starting point the automatic path would
        have used), so a coach is only correcting the pitches that are
        actually off rather than re-building the whole match from
        scratch -- this is a starting point, not a claim those positional
        guesses are correct, which is exactly why it's editable."""
        last = _last_game_import()
        if last is None:
            return None
        import_id, game_id, match_result = last
        if not match_result or match_result.get("status") != "count_mismatch":
            return None
        req("selected_pitcher_id" in input)
        selected_pitcher_id = int(input.selected_pitcher_id())

        db = get_session()
        try:
            rapsodo_pitches = sorted(
                db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
                .filter(RapsodoPitch.import_id == import_id).all(),
                key=lambda p: p.pitch_number,
            )
            game_pitches = sorted(
                get_pitching_pitches(db, selected_pitcher_id, game_id=game_id),
                key=lambda p: p.pitch_sequence,
            )
            game_pitch_choices = {"": "-- unmatched --"}
            for gp in game_pitches:
                game_pitch_choices[str(gp.game_pitch_id)] = f"#{gp.pitch_sequence} — {gp.pitch_outcome or '—'}"

            rows = []
            for i, rp in enumerate(rapsodo_pitches):
                default_match = str(game_pitches[i].game_pitch_id) if i < len(game_pitches) else ""
                pitch_type_label = rp.pitch_type.type_name if rp.pitch_type else (rp.raw_pitch_type or "—")
                velo_label = f", {float(rp.velocity):.1f} mph" if rp.velocity is not None else ""
                rows.append(
                    ui.layout_columns(
                        ui.p(f"Rapsodo #{rp.pitch_number} — {pitch_type_label}{velo_label}", class_="mb-1"),
                        ui.input_select(f"manual_match_{rp.rapsodo_pitch_id}", None, choices=game_pitch_choices, selected=default_match),
                        col_widths=[7, 5],
                    )
                )
            return ui.div(
                ui.markdown("**Match each Rapsodo reading to the charted pitch it came from**"),
                *rows,
                ui.input_action_button("apply_manual_matches_btn", "Apply matches", class_="btn-primary btn-sm mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.apply_manual_matches_btn)
    def _apply_manual_matches():
        last = _last_game_import()
        if last is None:
            return
        import_id, game_id, _match_result = last
        db = get_session()
        try:
            rapsodo_pitches = db.query(RapsodoPitch).filter(RapsodoPitch.import_id == import_id).all()
            matches = {}
            for rp in rapsodo_pitches:
                field_id = f"manual_match_{rp.rapsodo_pitch_id}"
                if field_id in input and input[field_id]():
                    matches[rp.rapsodo_pitch_id] = int(input[field_id]())
            try:
                result = apply_manual_rapsodo_game_pitch_matches(db, import_id, matches)
            except RapsodoImportError as e:
                ui.notification_show(str(e), type="error", duration=12)
                return
            ui.notification_show(f"Matched {result['matched_count']} pitch(es) by hand.", type="message", duration=8)
            # Replace the mismatch banner/table with a plain "matched"
            # result now that this has been reconciled by hand --
            # re-running auto-match would just report the same count
            # mismatch again, since the underlying counts haven't changed.
            _last_game_import.set((import_id, game_id, {"status": "matched", "matched_count": result["matched_count"]}))
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_game_import_btn)
    def _delete_game_import():
        if not input.confirm_delete_game_import():
            ui.notification_show("Check the confirmation box before deleting this import.", type="warning", duration=8)
            return
        last = _last_game_import()
        if last is None:
            return
        import_id, _, _ = last
        db = get_session()
        try:
            try:
                summary = delete_rapsodo_import(db, import_id)
            except RapsodoImportNotFoundError as e:
                ui.notification_show(str(e), type="error", duration=10)
                _last_game_import.set(None)
                return
            except RapsodoImportError as e:
                ui.notification_show(str(e), type="error", duration=10)
                return
            ui.notification_show(
                f"Deleted \"{summary['original_filename']}\" -- removed {summary['deleted_pitch_count']} pitch(es).",
                type="message", duration=8,
            )
            _last_game_import.set(None)
            _bump_refresh()
        finally:
            db.close()