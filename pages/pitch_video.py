"""
GBO — Video Review.

Two modes, since pitcher and hitter video work differently right now:
  - Pitcher: side-by-side view of a specific pitch's Rapsodo numbers
    alongside video of that same pitch. Supports single-clip upload
    (linked to a pitch immediately) AND bulk upload (many clips at
    once, uploaded unlinked, then matched to specific pitches
    afterward -- same "upload now, link later with safeguards" pattern
    already proven on Bullpen Tracking's Rapsodo linking, since
    matching many clips to many pitches has the same challenge).
  - Hitter: plain video clips (no paired numeric data yet -- there's no
    hitting-metrics tracking system built). Supports single and bulk
    upload, no linking step needed since there's nothing to match
    against.

Both modes reuse the same Video table (assessment_id left empty for
hitter clips and not-yet-linked pitcher clips) -- no schema change
needed for any of this.

Note: video files are much larger than photos. Supabase's free tier
gives 1GB of total storage -- worth watching closely once bulk uploads
are in regular use.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
import uuid
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, AssessmentCategory, Assessment, AssessmentResult, Video
from supabase_client import get_supabase_admin_client

VIDEO_BUCKET = "pitch-videos"

page_header("Video Review")

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

    mode = st.radio("Mode", ["Pitcher", "Hitter"], horizontal=True, key="video_review_mode")

    players_by_id = {p.player_id: p for p in players}
    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )
    selected_player = players_by_id[selected_player_id]

    st.divider()

    if mode == "Pitcher":
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
            empty_state("No Pitcher-Specific pitches recorded yet for this player.")
        else:
            pitches_by_id = {p.assessment_id: p for p in pitches}

            def pitch_label(aid):
                p = pitches_by_id[aid]
                pt = p.pitch_type.type_name if p.pitch_type else "Unknown type"
                velo = next((r.value for r in p.results if r.test_type.test_name == "Velocity"), None)
                velo_label = f" — {float(velo):.1f} mph" if velo is not None else ""
                has_video = " (video)" if p.videos else ""
                return f"{p.assessment_date.strftime('%Y-%m-%d (%a)')} — {pt}{velo_label}{has_video}"

            selected_pitch_id = st.selectbox(
                "Select a pitch",
                options=list(pitches_by_id.keys()),
                format_func=pitch_label,
            )
            selected_pitch = pitches_by_id[selected_pitch_id]

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

        # --- Bulk upload: many clips at once, unlinked -- match to pitches below ---
        if can_edit_assessments:
            st.divider()
            with st.expander("Bulk upload clips"):
                st.caption(
                    f"For uploading many clips at once (e.g. every pitch from a session) for "
                    f"{selected_player.first_name} {selected_player.last_name}. They'll upload unlinked -- "
                    f"match each one to its actual pitch in the section below once they're in."
                )
                with st.form("bulk_pitcher_video_upload"):
                    bulk_files = st.file_uploader(
                        "Video files", type=["mp4", "mov", "m4v"], accept_multiple_files=True, key="bulk_pitcher_files"
                    )
                    bulk_date = st.date_input("Date these were recorded", value=date.today(), key="bulk_pitcher_date")
                    bulk_submitted = st.form_submit_button("Upload all", type="primary")

                if bulk_submitted:
                    if not bulk_files:
                        st.error("Choose at least one video file first.")
                    else:
                        progress = st.progress(0.0, text="Uploading...")
                        uploaded_count = 0
                        for i, f in enumerate(bulk_files):
                            identifier = f"pitcher-bulk-{selected_player_id}-{bulk_date.isoformat()}-{i}"
                            url = upload_pitch_video(f, identifier)
                            if url:
                                session.add(Video(
                                    player_id=selected_player_id,
                                    assessment_id=None,
                                    video_url=url,
                                    description=f.name,
                                    recorded_date=bulk_date,
                                ))
                                uploaded_count += 1
                            progress.progress((i + 1) / len(bulk_files), text=f"Uploading... {i + 1}/{len(bulk_files)}")
                        session.commit()
                        progress.empty()
                        st.success(f"Uploaded {uploaded_count} clip(s). Match them to pitches below.")
                        st.rerun()

            # --- Link unlinked clips to their actual pitches ---
            unlinked_videos = (
                session.query(Video)
                .filter(Video.player_id == selected_player_id, Video.assessment_id.is_(None))
                .order_by(Video.recorded_date.desc(), Video.created_at)
                .all()
            )
            if unlinked_videos:
                with st.expander(f"Link uploaded clips to pitches ({len(unlinked_videos)} not yet linked)"):
                    # Group by date, since matching only makes sense within the same session/date.
                    dates_with_unlinked = sorted({v.recorded_date for v in unlinked_videos if v.recorded_date}, reverse=True)
                    for d in dates_with_unlinked:
                        videos_this_date = [v for v in unlinked_videos if v.recorded_date == d]
                        candidate_pitches = (
                            session.query(Assessment)
                            .options(joinedload(Assessment.pitch_type))
                            .filter(Assessment.player_id == selected_player_id, Assessment.category_id == category.category_id, Assessment.assessment_date == d)
                            .order_by(Assessment.assessment_id)
                            .all()
                        )
                        st.markdown(f"**{d.strftime('%Y-%m-%d (%a)')}** — {len(videos_this_date)} clip(s), {len(candidate_pitches)} pitch(es) recorded that day")
                        if not candidate_pitches:
                            st.caption("No pitches recorded for this date yet -- import that day's Rapsodo data first, or these clips may be from a session with no Rapsodo data.")
                            continue

                        candidates_by_id = {p.assessment_id: p for p in candidate_pitches}

                        def _pitch_option_label(aid):
                            p = candidates_by_id[aid]
                            pt = p.pitch_type.type_name if p.pitch_type else "Unknown type"
                            return f"{pt} (#{aid})"

                        for idx, v in enumerate(videos_this_date):
                            suggested_aid = candidate_pitches[idx].assessment_id if idx < len(candidate_pitches) else None
                            options = list(candidates_by_id.keys())
                            default_index = options.index(suggested_aid) if suggested_aid in options else 0
                            col1, col2, col3 = st.columns([2, 3, 1])
                            col1.markdown(f"{v.description or 'Clip'}")
                            link_choice = col2.selectbox(
                                " ", options=options, index=default_index,
                                format_func=_pitch_option_label,
                                key=f"link_video_{v.video_id}", label_visibility="collapsed",
                            )
                            if col3.button("Link", key=f"link_video_btn_{v.video_id}"):
                                v.assessment_id = link_choice
                                session.commit()
                                st.success(f"Linked {v.description or 'clip'}.")
                                st.rerun()

    else:  # Hitter mode -- plain clips, no paired numeric data (no hitting-metrics system built yet)
        st.subheader(f"{selected_player.first_name} {selected_player.last_name}'s clips")

        hitter_clips = (
            session.query(Video)
            .filter(Video.player_id == selected_player_id, Video.assessment_id.is_(None))
            .order_by(Video.recorded_date.desc(), Video.created_at.desc())
            .all()
        )

        if not hitter_clips:
            empty_state("No video clips uploaded yet for this player.")
        else:
            for v in hitter_clips:
                date_label = v.recorded_date.strftime("%Y-%m-%d (%a)") if v.recorded_date else "No date"
                with st.expander(f"{date_label}" + (f" — {v.description}" if v.description else "")):
                    st.video(v.video_url)

        if can_edit_assessments:
            st.divider()
            st.subheader("Upload a clip")
            with st.form("hitter_video_upload"):
                video_file = st.file_uploader("Video file", type=["mp4", "mov", "m4v"])
                video_date = st.date_input("Date", value=date.today())
                video_desc = st.text_input("Description (optional)", placeholder="e.g. BP, live at-bat, side view")
                upload_submitted = st.form_submit_button("Upload", type="primary")

            if upload_submitted:
                if video_file is None:
                    st.error("Choose a video file first.")
                else:
                    identifier = f"hitter-{selected_player_id}-{video_date.isoformat()}"
                    url = upload_pitch_video(video_file, identifier)
                    if url:
                        session.add(Video(
                            player_id=selected_player_id,
                            assessment_id=None,
                            video_url=url,
                            description=video_desc.strip() or None,
                            recorded_date=video_date,
                        ))
                        session.commit()
                        st.success("Video uploaded.")
                        st.rerun()

            with st.expander("Bulk upload clips"):
                st.caption(f"For uploading many clips at once for {selected_player.first_name} {selected_player.last_name} -- e.g. a full BP round or practice.")
                with st.form("bulk_hitter_video_upload"):
                    bulk_files = st.file_uploader(
                        "Video files", type=["mp4", "mov", "m4v"], accept_multiple_files=True, key="bulk_hitter_files"
                    )
                    bulk_date = st.date_input("Date these were recorded", value=date.today(), key="bulk_hitter_date")
                    bulk_desc = st.text_input("Shared description (optional)", placeholder="e.g. BP round 1", key="bulk_hitter_desc")
                    bulk_submitted = st.form_submit_button("Upload all", type="primary")

                if bulk_submitted:
                    if not bulk_files:
                        st.error("Choose at least one video file first.")
                    else:
                        progress = st.progress(0.0, text="Uploading...")
                        uploaded_count = 0
                        for i, f in enumerate(bulk_files):
                            identifier = f"hitter-bulk-{selected_player_id}-{bulk_date.isoformat()}-{i}"
                            url = upload_pitch_video(f, identifier)
                            if url:
                                description = f"{bulk_desc.strip()} — {f.name}" if bulk_desc.strip() else f.name
                                session.add(Video(
                                    player_id=selected_player_id,
                                    assessment_id=None,
                                    video_url=url,
                                    description=description,
                                    recorded_date=bulk_date,
                                ))
                                uploaded_count += 1
                            progress.progress((i + 1) / len(bulk_files), text=f"Uploading... {i + 1}/{len(bulk_files)}")
                        session.commit()
                        progress.empty()
                        st.success(f"Uploaded {uploaded_count} clip(s).")
                        st.rerun()

finally:
    session.close()

page_footer()