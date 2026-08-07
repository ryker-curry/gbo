"""
GBO — My Video (Player role only).

Shows the right content automatically based on their own is_pitcher
flag -- no manual mode selection, since we already know which they
are (same flag that gates My Bullpens vs. My Hitting):
  - Pitcher: the player's own pitch-by-pitch video review -- Rapsodo
    numbers side-by-side with video, for their own Pitcher-Specific
    pitches.
  - Hitter (non-pitcher): the player's own hitting clips (no paired
    numeric data, same as Video Review's Hitter mode).
Read-only either way: uploading video stays staff-only (Video Review).
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, AssessmentCategory, Assessment, AssessmentResult, Video
from ui_components import page_header, page_footer, empty_state

page_header("My Video")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name != "Player":
    st.error("This page is only available to Player accounts.")
    page_footer()
    st.stop()

session = get_session()
try:
    me = session.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        st.info("Your player profile isn't linked yet. Check with an administrator.")
        page_footer()
        st.stop()

    my_player = session.query(Player).filter(Player.player_id == me.player_id).first()

    # No manual selection -- we already know from their roster record
    # whether they're a pitcher or a position player, same is_pitcher
    # flag that already gates My Bullpens vs. My Hitting.
    mode = "Pitcher" if my_player.is_pitcher else "Hitter"

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
            .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == category.category_id)
            .order_by(Assessment.assessment_date.desc())
            .limit(300)
            .all()
        )

        if not pitches:
            empty_state("No pitches recorded yet.")
        else:
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

            col1, col2 = st.columns(2)

            with col1:
                st.subheader("Rapsodo data")
                if not selected_pitch.results:
                    st.caption("No numeric values recorded for this pitch.")
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

            with col2:
                st.subheader("Video")
                if selected_pitch.videos:
                    for v in selected_pitch.videos:
                        st.video(v.video_url)
                        if v.description:
                            st.caption(v.description)
                else:
                    st.caption("No video linked to this pitch yet.")

    else:  # Hitter mode -- plain clips, no paired numeric data, matching Video Review's Hitter mode
        st.subheader("My clips")
        hitter_clips = (
            session.query(Video)
            .filter(Video.player_id == my_player.player_id, Video.assessment_id.is_(None))
            .order_by(Video.recorded_date.desc(), Video.created_at.desc())
            .all()
        )
        if not hitter_clips:
            empty_state("No video clips uploaded yet.")
        else:
            for v in hitter_clips:
                date_label = v.recorded_date.strftime("%Y-%m-%d (%a)") if v.recorded_date else "No date"
                with st.expander(f"{date_label}" + (f" — {v.description}" if v.description else "")):
                    st.video(v.video_url)

finally:
    session.close()

page_footer()