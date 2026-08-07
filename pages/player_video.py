"""
GBO — My Video (Player role only).

Unified video hub -- merges video from all three places it can come
from, into one session/date browser:
  1. Bullpen Tracking (BullpenPitch.video_url) -- per-pitch clips
     attached during an actual tracked bullpen session.
  2. Hitter Tracking (HitterSwing.video_url) -- per-swing clips
     attached during an actual tracked hitter session (Live ABs,
     Batting Practice, Intersquad, Scrimmage, Game).
  3. Video Review (the Video table) -- general clips not tied to a
     tracked session, uploaded through Video Review's Pitcher mode
     (linked to a specific Assessment/Rapsodo pitch) or Hitter mode
     (just player + date).

Which two of the three apply is decided automatically from the
player's own is_pitcher flag (same one gating My Bullpens vs. My
Hitting) -- no manual mode selection needed.

One combined "Session" picker, sorted by date, covering every source
-- e.g. "2026-08-05 (Wed) — Bullpen: Execution Focused", "2026-08-03
(Mon) — Live ABs", "2026-08-01 (Sat) — General clips".
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, User, AssessmentCategory, Assessment, AssessmentResult, Video,
    BullpenSession, BullpenPitch, HitterTrackingSession, HitterSwing,
)
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

    # Build one unified, chronologically-sorted list of "sessions" --
    # each entry knows its own kind, so we can render it correctly once
    # selected. No manual mode selection -- source set is auto-picked
    # from is_pitcher, same flag used elsewhere.
    sessions_list = []  # each: {"key", "sort_date", "display", "kind", ...kind-specific data}

    if my_player.is_pitcher:
        bullpen_sessions = (
            session.query(BullpenSession)
            .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.pitches))
            .filter(BullpenSession.player_id == my_player.player_id)
            .all()
        )
        for b in bullpen_sessions:
            video_pitches = [p for p in b.pitches if p.video_url]
            if video_pitches:
                type_name = b.bullpen_type.type_name if b.bullpen_type else "—"
                sessions_list.append({
                    "key": f"bullpen_{b.bullpen_id}",
                    "sort_date": b.session_date,
                    "display": f"{b.session_date.strftime('%Y-%m-%d (%a)')} — Bullpen: {type_name}",
                    "kind": "bullpen",
                    "pitches": video_pitches,
                })

        category = session.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
        general_pitches = []
        if category:
            general_pitches = (
                session.query(Assessment)
                .options(
                    joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                    joinedload(Assessment.pitch_type),
                    joinedload(Assessment.videos),
                )
                .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == category.category_id)
                .all()
            )
            general_pitches = [p for p in general_pitches if p.videos]
        general_dates = sorted({p.assessment_date for p in general_pitches}, reverse=True)
        for d in general_dates:
            sessions_list.append({
                "key": f"general_{d.isoformat()}",
                "sort_date": d,
                "display": f"{d.strftime('%Y-%m-%d (%a)')} — General clips",
                "kind": "general_pitcher",
                "pitches": [p for p in general_pitches if p.assessment_date == d],
            })

    else:
        hitter_sessions = (
            session.query(HitterTrackingSession)
            .options(joinedload(HitterTrackingSession.session_type), joinedload(HitterTrackingSession.swings))
            .filter(HitterTrackingSession.player_id == my_player.player_id)
            .all()
        )
        for hs in hitter_sessions:
            video_swings = [sw for sw in hs.swings if sw.video_url]
            if video_swings:
                type_name = hs.session_type.type_name if hs.session_type else "—"
                label = f"{hs.session_date.strftime('%Y-%m-%d (%a)')} — {type_name}"
                if hs.label:
                    label += f": {hs.label}"
                sessions_list.append({
                    "key": f"hitter_{hs.session_id}",
                    "sort_date": hs.session_date,
                    "display": label,
                    "kind": "hitter",
                    "swings": video_swings,
                })

        general_clips = (
            session.query(Video)
            .filter(Video.player_id == my_player.player_id, Video.assessment_id.is_(None))
            .all()
        )
        general_clip_dates = sorted({v.recorded_date for v in general_clips if v.recorded_date}, reverse=True)
        for d in general_clip_dates:
            sessions_list.append({
                "key": f"general_{d.isoformat()}",
                "sort_date": d,
                "display": f"{d.strftime('%Y-%m-%d (%a)')} — General clips",
                "kind": "general_hitter",
                "clips": [v for v in general_clips if v.recorded_date == d],
            })

    if not sessions_list:
        empty_state("No video available yet.")
        page_footer()
        st.stop()

    sessions_list.sort(key=lambda s: s["sort_date"], reverse=True)
    sessions_by_key = {s["key"]: s for s in sessions_list}

    selected_key = st.selectbox(
        "Session",
        options=list(sessions_by_key.keys()),
        format_func=lambda k: sessions_by_key[k]["display"],
    )
    selected = sessions_by_key[selected_key]

    st.divider()

    if selected["kind"] == "bullpen":
        pitches_by_id = {p.bullpen_pitch_id: p for p in selected["pitches"]}
        chosen_id = st.selectbox(
            "Pitch",
            options=list(pitches_by_id.keys()),
            format_func=lambda pid: f"Pitch #{pitches_by_id[pid].pitch_number}"
            + (f" ({pitches_by_id[pid].pitch_type.type_name})" if pitches_by_id[pid].pitch_type else ""),
        )
        st.video(pitches_by_id[chosen_id].video_url)
        if pitches_by_id[chosen_id].notes:
            st.caption(pitches_by_id[chosen_id].notes)

    elif selected["kind"] == "general_pitcher":
        pitches_by_id = {p.assessment_id: p for p in selected["pitches"]}

        def _label(aid):
            p = pitches_by_id[aid]
            pt = p.pitch_type.type_name if p.pitch_type else "Unknown type"
            velo = next((r.value for r in p.results if r.test_type.test_name == "Velocity"), None)
            return f"{pt}" + (f" — {float(velo):.1f} mph" if velo is not None else "")

        chosen_id = st.selectbox("Pitch", options=list(pitches_by_id.keys()), format_func=_label)
        selected_pitch = pitches_by_id[chosen_id]
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Rapsodo data")
            if not selected_pitch.results:
                st.caption("No numeric values recorded for this pitch.")
            else:
                st.dataframe(
                    [
                        {"Test": r.test_type.test_name, "Value": f"{float(r.value):.2f}" + (f" {r.test_type.unit}" if r.test_type.unit else "")}
                        for r in selected_pitch.results
                    ],
                    use_container_width=True, hide_index=True,
                )
        with col2:
            st.subheader("Video")
            for v in selected_pitch.videos:
                st.video(v.video_url)
                if v.description:
                    st.caption(v.description)

    elif selected["kind"] == "hitter":
        swings_by_id = {sw.swing_id: sw for sw in selected["swings"]}
        chosen_id = st.selectbox(
            "Swing",
            options=list(swings_by_id.keys()),
            format_func=lambda sid: f"Swing #{swings_by_id[sid].swing_number}"
            + (f" ({swings_by_id[sid].pitch_type.type_name})" if swings_by_id[sid].pitch_type else "")
            + (f" — {swings_by_id[sid].contact_quality}" if swings_by_id[sid].contact_quality else ""),
        )
        st.video(swings_by_id[chosen_id].video_url)
        if swings_by_id[chosen_id].notes:
            st.caption(swings_by_id[chosen_id].notes)

    else:  # general_hitter
        clips_by_id = {v.video_id: v for v in selected["clips"]}
        chosen_id = st.selectbox(
            "Clip",
            options=list(clips_by_id.keys()),
            format_func=lambda vid: clips_by_id[vid].description or f"Clip #{vid}",
        )
        st.video(clips_by_id[chosen_id].video_url)

finally:
    session.close()

page_footer()