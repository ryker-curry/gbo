"""
GBO — Pitch Video Review.

Side-by-side view: a specific pitch's Rapsodo numbers alongside video of
that same pitch, so the numbers and the eye test can be compared
directly. Videos are optionally linked to a specific Assessment record
(Pitcher-Specific category -- one pitch = one assessment).

Note: video files are much larger than photos. Supabase's free tier
gives 1GB of total storage -- fine for a handful of test clips, but
worth watching if this gets used heavily before upgrading the plan.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
import uuid
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, AssessmentCategory, Assessment, AssessmentResult, Video
from supabase_client import get_supabase_admin_client

VIDEO_BUCKET = "pitch-videos"

page_header("Pitch Video Review")

current_user_id = st.session_state.get("gbo_user_id")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)
can_edit_assessments = st.session_state.get("gbo_can_edit_assessments", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()


def upload_pitch_video(uploaded_file, identifier: str):
    try:
        admin_client = get_supabase_admin_client()
        ext = uploaded_file.name.split(".")[-1].lower()
        path = f"{identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        file_bytes = uploaded_file.getvalue()
        admin_client.storage.from_(VIDEO_BUCKET).upload(
            path, file_bytes, {"content-type": uploaded_file.type}
        )
        return admin_client.storage.from_(VIDEO_BUCKET).get_public_url(path)
    except Exception as e:
        st.error(
            f"Video upload failed: {e}. "
            f"Make sure a public Storage bucket named '{VIDEO_BUCKET}' exists in your Supabase project "
            f"(Supabase dashboard -> Storage -> New bucket -> name it '{VIDEO_BUCKET}' -> make it Public)."
        )
        return None


session = get_session()
try:
    player_query = session.query(Player).filter(Player.active.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    players = player_query.order_by(Player.last_name, Player.first_name).all()

    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
        page_footer()
        st.stop()

    players_by_id = {p.player_id: p for p in players}
    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )

    category = session.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
    if category is None:
        st.error("Pitcher-Specific category not found.")
        page_footer()
        st.stop()

    pitches = (
        session.query(Assessment)
        .options(
            joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
            joinedload(Assessment.pitch_type),
            joinedload(Assessment.videos),
        )
        .filter(Assessment.player_id == selected_player_id, Assessment.category_id == category.category_id)
        .order_by(Assessment.assessment_date.desc())
        .limit(300)
        .all()
    )

    if not pitches:
        st.info("No Pitcher-Specific pitches recorded yet for this player.")
        page_footer()
        st.stop()

    pitches_by_id = {p.assessment_id: p for p in pitches}

    def pitch_label(aid):
        p = pitches_by_id[aid]
        pt = p.pitch_type.type_name if p.pitch_type else "Unknown type"
        velo = next((r.value for r in p.results if r.test_type.test_name == "Velocity"), None)
        velo_label = f" — {float(velo):.1f} mph" if velo is not None else ""
        has_video = " 🎥" if p.videos else ""
        return f"{p.assessment_date.strftime('%Y-%m-%d (%a)')} — {pt}{velo_label}{has_video}"

    selected_pitch_id = st.selectbox(
        "Select a pitch",
        options=list(pitches_by_id.keys()),
        format_func=pitch_label,
    )
    selected_pitch = pitches_by_id[selected_pitch_id]

    st.divider()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Rapsodo data")
        if not selected_pitch.results:
            st.info("No numeric values recorded for this pitch.")
        else:
            st.dataframe(
                [
                    {
                        "Test": r.test_type.test_name,
                        "Value": f"{float(r.value):.2f}" + (f" {r.test_type.unit}" if r.test_type.unit else ""),
                    }
                    for r in selected_pitch.results
                ],
                use_container_width=True,
                hide_index=True,
            )
        if selected_pitch.notes:
            st.caption(selected_pitch.notes)

    with col2:
        st.subheader("Video")
        if selected_pitch.videos:
            for v in selected_pitch.videos:
                st.video(v.video_url)
                if v.description:
                    st.caption(v.description)
        else:
            st.info("No video linked to this pitch yet.")

        if can_edit_assessments:
            with st.form(f"video_upload_{selected_pitch_id}"):
                video_file = st.file_uploader("Upload video for this pitch", type=["mp4", "mov", "m4v"])
                video_desc = st.text_input("Description (optional)")
                upload_submitted = st.form_submit_button("Upload", type="primary")

            if upload_submitted:
                if video_file is None:
                    st.error("Choose a video file first.")
                else:
                    identifier = f"pitch-{selected_pitch_id}"
                    url = upload_pitch_video(video_file, identifier)
                    if url:
                        session.add(Video(
                            player_id=selected_player_id,
                            assessment_id=selected_pitch_id,
                            video_url=url,
                            description=video_desc.strip() or None,
                            recorded_date=selected_pitch.assessment_date,
                        ))
                        session.commit()
                        st.success("Video uploaded and linked to this pitch.")
                        st.rerun()

finally:
    session.close()

page_footer()