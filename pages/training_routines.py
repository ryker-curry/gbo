"""
GBO — Training Routines.

A reusable content library: a coach builds a named routine once (e.g.
"Standard Post-Throw Recovery") with structured steps (exercise, sets,
reps), tied to a session type (Arm Care, Conditioning, etc.). Each
exercise can optionally have its own demo video, so a player knows
exactly what the movement looks like. Once built, routines can be
assigned to players repeatedly via Player Assignments instead of
retyping the same plan every time.

Creating/editing routines is restricted to edit-capable roles (same
can_edit_sessions permission used for Training Sessions and Player
Assignments); everyone else can view the library.
"""

import streamlit as st
import uuid
import pandas as pd

from database import get_session
from models import SessionType, TrainingRoutine, RoutineExercise
from ui_components import page_header, page_footer, empty_state
from supabase_client import get_supabase_admin_client

ROUTINE_VIDEO_BUCKET = "routine-videos"

# Which session types belong to which coaching specialty -- used to filter
# Training Routines so a Hitting Coach doesn't see pitcher-only routines
# and vice versa. Anything not listed here is shared (visible to both).
PITCHING_SESSION_TYPES = {"Arm Care", "Throwing", "Plyos", "Mechanical Work", "Bullpen"}
HITTING_SESSION_TYPES = {"Hitting Drills"}

page_header("Training Routines")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
coach_specialty = st.session_state.get("gbo_coach_specialty")
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()


def excluded_session_type_names():
    """Which session type names should be hidden from the current user,
    based on coaching specialty. Empty set for anyone not specialty-tagged."""
    if role_name != "Coach" or coach_specialty not in ("Pitching", "Hitting"):
        return set()
    return HITTING_SESSION_TYPES if coach_specialty == "Pitching" else PITCHING_SESSION_TYPES


def filter_session_types_for_specialty(all_types):
    """Filter a SessionType list by the current user's coaching specialty."""
    excluded = excluded_session_type_names()
    return [t for t in all_types if t.type_name not in excluded]


def upload_routine_video(uploaded_file, identifier: str):
    try:
        admin_client = get_supabase_admin_client()
        ext = uploaded_file.name.split(".")[-1].lower()
        path = f"{identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        file_bytes = uploaded_file.getvalue()
        admin_client.storage.from_(ROUTINE_VIDEO_BUCKET).upload(
            path, file_bytes, {"content-type": uploaded_file.type}
        )
        return admin_client.storage.from_(ROUTINE_VIDEO_BUCKET).get_public_url(path)
    except Exception as e:
        st.error(
            f"Video upload failed: {e}. "
            f"Make sure a public Storage bucket named '{ROUTINE_VIDEO_BUCKET}' exists in your Supabase project "
            f"(Supabase dashboard -> Storage -> New bucket -> name it '{ROUTINE_VIDEO_BUCKET}' -> make it Public)."
        )
        return None


def render_exercise_list(exercises):
    """Exercise list with an inline video player per exercise when one
    exists. Uses inline markdown/video rather than a nested st.expander,
    since Streamlit doesn't allow expanders inside expanders -- this
    function gets called from within the routine library's own expander."""
    for e in exercises:
        label = f"**{e.exercise_name}**"
        if e.sets or e.reps:
            label += f" — {e.sets or '—'} sets x {e.reps or '—'}"
        st.markdown(label)
        if e.video_url:
            st.video(e.video_url)
        if e.notes:
            st.caption(e.notes)


session = get_session()
try:
    session_types = session.query(SessionType).order_by(SessionType.display_order).all()
    session_types = filter_session_types_for_specialty(session_types)

    st.subheader("Routine library")
    type_filter = st.selectbox("Filter by type", ["All"] + [t.type_name for t in session_types])

    routines_query = session.query(TrainingRoutine).join(SessionType)
    excluded_types = excluded_session_type_names()
    if excluded_types:
        routines_query = routines_query.filter(SessionType.type_name.notin_(excluded_types))
    if type_filter != "All":
        routines_query = routines_query.filter(SessionType.type_name == type_filter)
    routines = routines_query.order_by(TrainingRoutine.routine_name).all()

    if not routines:
        empty_state("No routines saved yet." if type_filter == "All" else f"No {type_filter} routines saved yet.")
    else:
        for r in routines:
            with st.expander(f"**{r.routine_name}** ({r.session_type.type_name if r.session_type else '—'})"):
                if r.description:
                    st.write(r.description)
                if not r.exercises:
                    st.caption("No exercises added to this routine yet.")
                else:
                    render_exercise_list(r.exercises)

    if not can_edit_sessions:
        st.info("Your role has read-only access to the routine library.")
        page_footer()
        st.stop()

    st.divider()
    st.subheader("Create a new routine")

    with st.form("new_routine_form"):
        routine_name = st.text_input("Routine name", placeholder="e.g. Standard Post-Throw Recovery")
        session_type_choice = st.selectbox("Type", [t.type_name for t in session_types])
        description = st.text_area("Description (optional)", placeholder="Brief overview of when/why to use this routine")
        create_submitted = st.form_submit_button("Create routine", type="primary")

    if create_submitted:
        if not routine_name.strip():
            st.error("Routine name is required.")
        else:
            session_type_id = next(t.session_type_id for t in session_types if t.type_name == session_type_choice)
            session.add(TrainingRoutine(
                session_type_id=session_type_id,
                routine_name=routine_name.strip(),
                description=description.strip() or None,
                created_by_user_id=current_user_id,
            ))
            session.commit()
            st.success(f"Created routine: {routine_name.strip()}")
            st.rerun()

    st.divider()
    st.subheader("Edit a routine")

    if not routines:
        st.caption("Create a routine above first.")
    else:
        routines_by_id = {r.routine_id: r for r in routines}
        selected_routine_id = st.selectbox(
            "Routine",
            options=list(routines_by_id.keys()),
            format_func=lambda rid: routines_by_id[rid].routine_name,
        )
        selected_routine = routines_by_id[selected_routine_id]

        with st.form(f"rename_routine_{selected_routine_id}"):
            new_name = st.text_input("Routine name", value=selected_routine.routine_name)
            new_description = st.text_area("Description (optional)", value=selected_routine.description or "")
            rename_submitted = st.form_submit_button("Save name/description", type="primary")

        if rename_submitted:
            if not new_name.strip():
                st.error("Routine name is required.")
            else:
                selected_routine.routine_name = new_name.strip()
                selected_routine.description = new_description.strip() or None
                session.commit()
                st.success("Saved.")
                st.rerun()

        st.caption(
            f"Edit exercises for {selected_routine.routine_name} below -- change values in place, use the trash "
            f"icon on a row to remove it, or add new rows at the bottom. Existing videos are kept unless you "
            f"remove that row entirely."
        )
        existing_exercises = sorted(selected_routine.exercises, key=lambda e: e.display_order)
        existing_ids = [e.exercise_id for e in existing_exercises]
        exercise_df = pd.DataFrame({
            "ID": pd.array([e.exercise_id for e in existing_exercises], dtype="Int64"),
            "Exercise Name": pd.array([e.exercise_name for e in existing_exercises], dtype="string"),
            "Sets": pd.array([e.sets for e in existing_exercises], dtype="Int64"),
            "Reps": pd.array([e.reps for e in existing_exercises], dtype="string"),
            "Notes": pd.array([e.notes for e in existing_exercises], dtype="string"),
        })
        exercise_table = st.data_editor(
            exercise_df,
            num_rows="dynamic",
            use_container_width=True,
            key=f"exercise_table_{selected_routine_id}",
            column_config={
                "ID": st.column_config.NumberColumn(disabled=True, help="Existing exercises keep their ID (and video) automatically -- leave blank for new rows."),
                "Exercise Name": st.column_config.TextColumn(required=True),
                "Sets": st.column_config.NumberColumn(min_value=0, max_value=20, step=1),
                "Reps": st.column_config.TextColumn(help='e.g. "10", "AMRAP", "30 sec"'),
                "Notes": st.column_config.TextColumn(),
            },
        )

        if st.button("Save exercises", type="primary"):
            valid_rows = exercise_table[exercise_table["Exercise Name"].notna() & (exercise_table["Exercise Name"].str.strip() != "")]
            if valid_rows.empty:
                st.error("Add at least one exercise with a name before saving.")
            else:
                exercises_by_id = {e.exercise_id: e for e in existing_exercises}
                kept_ids = set()
                order = 1
                added = 0
                updated = 0
                for _, row in valid_rows.iterrows():
                    sets_val = row.get("Sets")
                    row_id = row.get("ID")
                    name = str(row["Exercise Name"]).strip()
                    sets = int(sets_val) if pd.notna(sets_val) else None
                    reps = str(row["Reps"]).strip() if pd.notna(row.get("Reps")) else None
                    notes = str(row["Notes"]).strip() if pd.notna(row.get("Notes")) else None

                    if pd.notna(row_id) and int(row_id) in exercises_by_id:
                        # Existing exercise -- update in place, video_url untouched.
                        ex = exercises_by_id[int(row_id)]
                        ex.exercise_name = name
                        ex.sets = sets
                        ex.reps = reps
                        ex.notes = notes
                        ex.display_order = order
                        kept_ids.add(ex.exercise_id)
                        updated += 1
                    else:
                        # New row -- no ID, or an ID that no longer matches anything.
                        session.add(RoutineExercise(
                            routine_id=selected_routine_id,
                            exercise_name=name,
                            sets=sets,
                            reps=reps,
                            notes=notes,
                            display_order=order,
                        ))
                        added += 1
                    order += 1

                # Any existing exercise whose row was removed from the table entirely.
                removed_ids = set(existing_ids) - kept_ids
                removed = 0
                for rid in removed_ids:
                    session.delete(exercises_by_id[rid])
                    removed += 1

                session.commit()
                st.success(f"Saved -- {updated} updated, {added} added, {removed} removed.")
                st.rerun()

        # Refresh exercises after any save, and offer video attachment per exercise
        session.refresh(selected_routine)
        if selected_routine.exercises:
            st.divider()
            st.caption(f"Attach a demo video to any exercise in {selected_routine.routine_name}:")
            for e in selected_routine.exercises:
                ex_label = e.exercise_name
                if e.sets or e.reps:
                    ex_label += f" ({e.sets or '—'} sets x {e.reps or '—'})"
                st.markdown(f"**{ex_label}**")
                if e.video_url:
                    st.video(e.video_url)
                    st.caption("Uploading a new video below will replace this one.")
                video_file = st.file_uploader(
                    f"Video for {e.exercise_name}", type=["mp4", "mov", "m4v"], key=f"video_upload_{e.exercise_id}"
                )
                if video_file is not None and st.button(f"Save video for {e.exercise_name}", key=f"save_video_{e.exercise_id}", type="primary"):
                    identifier = f"routine-{selected_routine_id}-exercise-{e.exercise_id}"
                    url = upload_routine_video(video_file, identifier)
                    if url:
                        e.video_url = url
                        session.commit()
                        st.success(f"Video saved for {e.exercise_name}.")
                        st.rerun()

finally:
    session.close()

page_footer()