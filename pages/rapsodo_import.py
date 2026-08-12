"""
GBO — Rapsodo Bullpen Analytics: Import.

Phase 1 of the Rapsodo Bullpen Analytics module (see
GBO_Rapsodo_Module_Architecture_Review.md). Replaces the old
pages/import_rapsodo.py as the primary Rapsodo upload path -- that page
still exists and still works (writes to Assessment/AssessmentResult, the
"Pitcher-Specific" assessment category), but new imports should come
through here, into the dedicated RapsodoImport/RapsodoPitch tables.

Workflow: pick a pitcher -> pick or start a bullpen session -> upload
the Rapsodo CSV -> preview validation -> import. All the actual parsing/
validation/insert logic lives in services/rapsodo_import.py, kept
separate from this page per the spec's "keep database operations
separate from UI code" instruction -- this file is UI only.

A plain results table shows immediately after a successful import (not
just a success message), plus a link into pages/bullpen_dashboard.py
(Phase 2) for the full pitch-type summary and filters. Charts are
Phase 3 -- not on the dashboard yet.
"""

import streamlit as st
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, BullpenSession, BullpenType, RapsodoPitch
from ui_components import page_header, page_footer, empty_state
from services.rapsodo_import import (
    import_rapsodo_file, validate_file_structure, read_csv_bytes,
    DuplicateImportError, RapsodoValidationError, RapsodoImportError,
)

page_header("Import Rapsodo Data")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

if role_name == "Coach" and st.session_state.get("gbo_coach_specialty") == "Hitting":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

if not can_edit_sessions:
    st.info("Your role has read-only access -- viewing is available once a session has been imported, but you can't upload new data here.")

session = get_session()
try:
    player_query = session.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == current_user_id).all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    pitchers = player_query.order_by(Player.last_name, Player.first_name).all()

    if not pitchers:
        empty_state("No pitchers to show yet." if can_view_all else "No pitchers are currently assigned to you.")
        page_footer()
        st.stop()

    pitchers_by_id = {p.player_id: p for p in pitchers}
    selected_pitcher_id = st.selectbox(
        "Pitcher",
        options=list(pitchers_by_id.keys()),
        format_func=lambda pid: f"{pitchers_by_id[pid].first_name} {pitchers_by_id[pid].last_name}",
        key="rapsodo_selected_pitcher_id",
    )
    selected_pitcher = pitchers_by_id[selected_pitcher_id]

    st.divider()
    st.subheader("Bullpen session")

    existing_sessions = (
        session.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type))
        .filter(BullpenSession.player_id == selected_pitcher_id)
        .order_by(BullpenSession.session_date.desc())
        .all()
    )
    sessions_by_id = {b.bullpen_id: b for b in existing_sessions}

    def _session_label(bullpen_id):
        if bullpen_id is None:
            return "-- Start a new bullpen session --"
        b = sessions_by_id[bullpen_id]
        pitch_count = session.query(RapsodoPitch).filter(RapsodoPitch.bullpen_id == b.bullpen_id).count()
        return f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {b.bullpen_type.type_name if b.bullpen_type else '—'} ({pitch_count} Rapsodo pitch(es))"

    session_option_ids = [None] + list(sessions_by_id.keys())
    target_bullpen_id = st.selectbox(
        "Session to import into",
        options=session_option_ids,
        format_func=_session_label,
        key="rapsodo_target_bullpen_choice",
    )

    new_bullpen_type_id = None
    new_bullpen_date = None
    new_bullpen_notes = None
    if target_bullpen_id is None and can_edit_sessions:
        bullpen_types = session.query(BullpenType).order_by(BullpenType.display_order).all()
        if not bullpen_types:
            st.warning("No bullpen types set up yet -- run the migration/seed script first.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                new_bullpen_type_id = st.selectbox(
                    "Bullpen type", options=[t.bullpen_type_id for t in bullpen_types],
                    format_func=lambda tid: next(t.type_name for t in bullpen_types if t.bullpen_type_id == tid),
                    key="rapsodo_new_bullpen_type",
                )
            with col2:
                new_bullpen_date = st.date_input("Session date", value=date.today(), key="rapsodo_new_bullpen_date")
            new_bullpen_notes = st.text_input("Session notes (optional)", key="rapsodo_new_bullpen_notes")
    elif target_bullpen_id is None:
        st.info("Your role can't start a new session. Ask a coach to start one, or select an existing session above.")

    st.divider()
    st.subheader("Upload file")

    if not can_edit_sessions:
        st.caption("Read-only access -- upload is disabled for your role.")
        page_footer()
        st.stop()

    uploaded_file = st.file_uploader("Rapsodo CSV export", type=["csv"], key="rapsodo_file_uploader")

    if uploaded_file is None:
        st.info("Upload a Rapsodo CSV export to continue.")
        page_footer()
        st.stop()

    file_bytes = uploaded_file.getvalue()

    try:
        preview_df = read_csv_bytes(file_bytes)
        field_to_column, unmapped_columns = validate_file_structure(preview_df)
    except RapsodoValidationError as e:
        st.error(str(e))
        page_footer()
        st.stop()

    st.success(f"Read {len(preview_df)} row(s) from the file.")
    mapped_count = len(field_to_column)
    with st.expander(f"Column mapping preview ({mapped_count} recognized field(s), {len(unmapped_columns)} unmapped)"):
        st.write("**Recognized fields:**", ", ".join(sorted(field_to_column.keys())))
        if unmapped_columns:
            st.caption(
                "These columns weren't recognized by name but will still be preserved in each pitch's raw data "
                "(not displayed on charts, but not discarded either): " + ", ".join(unmapped_columns)
            )

    if target_bullpen_id is None and new_bullpen_type_id is None:
        st.warning("Choose a bullpen type above before importing (needed to start a new session).")
        page_footer()
        st.stop()

    if st.button("Import", type="primary"):
        target_bullpen = None
        if target_bullpen_id is not None:
            target_bullpen = sessions_by_id[target_bullpen_id]
        else:
            target_bullpen = BullpenSession(
                player_id=selected_pitcher_id,
                bullpen_type_id=new_bullpen_type_id,
                session_date=new_bullpen_date,
                overall_notes=new_bullpen_notes.strip() if new_bullpen_notes else None,
                created_by_user_id=current_user_id,
            )
            session.add(target_bullpen)
            session.flush()  # assigns bullpen_id

        try:
            import_record = import_rapsodo_file(
                session,
                file_bytes=file_bytes,
                original_filename=uploaded_file.name,
                player_id=selected_pitcher_id,
                bullpen_id=target_bullpen.bullpen_id,
                uploaded_by_user_id=current_user_id,
            )
        except DuplicateImportError as e:
            session.rollback()
            st.error(str(e))
            page_footer()
            st.stop()
        except RapsodoValidationError as e:
            session.rollback()
            st.error(f"This file couldn't be imported: {e}")
            page_footer()
            st.stop()
        except RapsodoImportError as e:
            session.rollback()
            st.error(str(e))
            page_footer()
            st.stop()

        session.commit()

        summary_msg = (
            f"Imported {import_record.imported_row_count} pitch(es) into the "
            f"{target_bullpen.session_date.strftime('%Y-%m-%d (%a)')} session."
        )
        if import_record.rejected_row_count:
            summary_msg += f" {import_record.rejected_row_count} row(s) were skipped -- see details below."
        st.success(summary_msg)

        if import_record.error_summary:
            with st.expander(f"Skipped rows ({import_record.rejected_row_count})"):
                for line in import_record.error_summary.split("; "):
                    st.caption(line)

        imported_pitches = (
            session.query(RapsodoPitch)
            .options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.import_id == import_record.import_id)
            .order_by(RapsodoPitch.pitch_number)
            .all()
        )
        if imported_pitches:
            st.subheader("Imported pitches")
            st.dataframe(
                [
                    {
                        "#": p.pitch_number,
                        "Time": p.pitch_date.strftime("%I:%M:%S %p") if p.pitch_date else "—",
                        "Pitch Type": p.pitch_type.type_name if p.pitch_type else (p.raw_pitch_type or "—"),
                        "Velocity (mph)": float(p.velocity) if p.velocity is not None else None,
                        "Total Spin (rpm)": float(p.total_spin) if p.total_spin is not None else None,
                        "IVB (in)": float(p.vb_spin) if p.vb_spin is not None else None,
                        "HB (in)": float(p.hb_spin) if p.hb_spin is not None else None,
                        "Extension (ft)": float(p.release_extension) if p.release_extension is not None else None,
                        "Strike": "Y" if p.is_strike else ("N" if p.is_strike is False else "—"),
                    }
                    for p in imported_pitches
                ],
                use_container_width=True,
                hide_index=True,
            )
        st.divider()
        if st.button("Open full Bullpen Dashboard for this session", type="primary", key="rapsodo_import_open_dashboard"):
            st.query_params["bullpen_id"] = str(target_bullpen.bullpen_id)
            st.switch_page("pages/bullpen_dashboard.py")
        st.caption("The dashboard includes movement, release point, velocity/spin trend, location, and spin-axis charts.")

finally:
    session.close()

page_footer()
