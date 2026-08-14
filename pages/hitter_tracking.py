"""
GBO — Hitter Tracking.

Live swing-by-swing tracking sheet, same spirit as Bullpen Tracking but
for hitters: pitch type, location (same 3x3 zone grid + Bury), pitcher
hand (always capturable, even for a BP arm/machine/opponent that isn't
on our roster), an optional link to a specific roster pitcher (so a
pitcher's own heatmap can be built on Bullpen Tracking from this same
data), a simple contact-quality grade (Barrel/Solid/Weak/Miss -- no
exit velo/launch angle tracking exists yet), and where the ball was hit.

Produces a hitter heatmap here: for the selected hitter, contact
quality by zone across all their logged swings, filterable by pitcher
hand -- "where do they hit the ball best, what do they struggle with."
The mirror-opposite view -- a pitcher's own zone heatmap, showing where
opponents do damage against him -- lives on his own page (Bullpen
Tracking) instead, not here, since a hitter should only see his own
heatmap on this page.

Restricted the mirror-opposite way from Bullpen Tracking: hidden from
Pitching-specialty coaches, visible to Hitting-specialty coaches (plus
Administrator/Head Coach, same as Bullpen Tracking's pattern).
"""

import streamlit as st
import plotly.graph_objects as go
import uuid
from datetime import date, datetime

from database import get_session
from models import Player, StaffPlayerAssignment, PitchType, HitterTrackingSession, HitterSwing, HitterSessionType
from ui_components import page_header, page_footer, empty_state
from r2_client import upload_video_to_r2

page_header("Hitter Tracking")

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

if role_name == "Coach" and st.session_state.get("gbo_coach_specialty") == "Pitching":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

PITCH_VIDEO_SUBFOLDER = "pitch-videos/"  # reuses the same R2 folder Bullpen Tracking/Pitch Video Review already use


def upload_swing_video(uploaded_file, identifier: str):
    try:
        return upload_video_to_r2(uploaded_file, identifier, bucket_subfolder=PITCH_VIDEO_SUBFOLDER)
    except Exception as e:
        st.error(
            f"Video upload failed: {e}. "
            f"Make sure Cloudflare R2 is configured (R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/"
            f"R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- see r2_client.py's docstring for setup steps)."
        )
        return None


ZONE_LABELS = {
    0: "Bury (in the dirt)",
    1: "Up-Left", 2: "Up-Middle", 3: "Up-Right",
    4: "Middle-Left", 5: "Middle-Middle", 6: "Middle-Right",
    7: "Down-Left", 8: "Down-Middle", 9: "Down-Right",
}
CONTACT_QUALITY_OPTIONS = ["Barrel", "Solid", "Weak", "Miss"]
CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}
HIT_LOCATION_OPTIONS = ["Left Field", "Left-Center", "Center Field", "Right-Center", "Right Field", "Infield"]


def render_zone_heatmap(title, zone_scores, zone_counts, invert_colors=False, subtitle=None):
    """3x3 heatmap of average contact-quality score per zone. Green =
    good, red = poor -- inverted for the pitcher view, where a LOW
    opponent contact-quality score is what's good for the pitcher."""
    # z rows top-to-bottom must be given bottom-to-top for go.Heatmap's
    # default y-axis orientation, so row order here is Down/Middle/Up.
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_scores.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_scores[zid]:.1f}<br>({zone_counts[zid]})" if zid in zone_scores else "—" for zid in row] for row in zone_grid]

    colorscale = "RdYlGn_r" if invert_colors else "RdYlGn"
    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale=colorscale, zmin=0, zmax=3, showscale=True,
        colorbar=dict(title="Avg score", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)
    if subtitle:
        st.caption(subtitle)


def compute_zone_scores(swings):
    """Average contact-quality score and count per zone, from a list of
    HitterSwing objects. Miss counts toward the average (score 0) but
    has no hit_location."""
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


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
    player_ids_list = list(players_by_id.keys())
    default_hitter_id = st.session_state.get("ht_selected_hitter_id")
    hitter_index = player_ids_list.index(default_hitter_id) if default_hitter_id in player_ids_list else 0
    selected_hitter_id = st.selectbox(
        "Hitter",
        options=player_ids_list,
        index=hitter_index,
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
        key="ht_selected_hitter_id",
    )
    selected_hitter = players_by_id[selected_hitter_id]

    # Roster pitchers, for the optional per-swing pitcher link
    roster_pitchers = session.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).order_by(Player.last_name, Player.first_name).all()
    roster_pitchers_by_id = {p.player_id: p for p in roster_pitchers}

    pitch_types = session.query(PitchType).order_by(PitchType.pitch_type_id).all()

    st.divider()
    st.subheader(f"Sessions — {selected_hitter.first_name} {selected_hitter.last_name}")

    existing_sessions = (
        session.query(HitterTrackingSession)
        .filter(HitterTrackingSession.player_id == selected_hitter_id)
        .order_by(HitterTrackingSession.session_date.desc())
        .all()
    )
    sessions_by_id = {s.session_id: s for s in existing_sessions}

    def _session_label(sid):
        if sid is None:
            return "-- Start a new session --"
        s = sessions_by_id[sid]
        label = f"{s.session_date.strftime('%Y-%m-%d (%a)')} — {s.session_type.type_name if s.session_type else '—'}"
        if s.label:
            label += f": {s.label}"
        label += f" ({len(s.swings)} swings)"
        return label

    def _set_active_session(session_id):
        if session_id is None:
            st.query_params.pop("hitter_session_id", None)
        else:
            st.query_params["hitter_session_id"] = str(session_id)
        st.session_state.active_hitter_session_id = session_id

    query_session_id_raw = st.query_params.get("hitter_session_id")
    try:
        default_session_id = int(query_session_id_raw) if query_session_id_raw is not None else None
    except ValueError:
        default_session_id = None
    if default_session_id not in sessions_by_id:
        default_session_id = None

    session_option_ids = [None] + list(sessions_by_id.keys())
    session_index = session_option_ids.index(default_session_id) if default_session_id in session_option_ids else 0
    active_session_id = st.selectbox(
        "Session",
        options=session_option_ids,
        index=session_index,
        format_func=_session_label,
        key="ht_session_selectbox",
    )
    if active_session_id != default_session_id:
        _set_active_session(active_session_id)

    active_session = sessions_by_id[active_session_id] if active_session_id is not None else None

    if active_session_id is None and can_edit_sessions:
        hitter_session_types = session.query(HitterSessionType).order_by(HitterSessionType.display_order).all()
        with st.form("new_hitter_session_form"):
            new_date = st.date_input("Date", value=date.today())
            new_type_choice = st.selectbox("Type", [t.type_name for t in hitter_session_types])
            new_label = st.text_input("Additional detail (optional)", placeholder="e.g. Round 2")
            overall_notes = st.text_area("Session notes (optional)")
            new_session_submitted = st.form_submit_button("Start session", type="primary")

        if new_session_submitted:
            new_type_id = next(t.session_type_id for t in hitter_session_types if t.type_name == new_type_choice)
            new_ht_session = HitterTrackingSession(
                player_id=selected_hitter_id,
                session_type_id=new_type_id,
                session_date=new_date,
                label=new_label.strip() or None,
                overall_notes=overall_notes.strip() or None,
                created_by_user_id=current_user_id,
            )
            session.add(new_ht_session)
            session.commit()
            _set_active_session(new_ht_session.session_id)
            st.success(f"Started {new_type_choice} session for {selected_hitter.first_name} on {new_date.strftime('%Y-%m-%d (%a)')}.")
            st.rerun()
    elif active_session_id is None:
        st.info("Your role has read-only access to hitter tracking.")

    if active_session:
        st.divider()
        title = f"{active_session.session_date.strftime('%Y-%m-%d (%a)')} — {active_session.session_type.type_name if active_session.session_type else '—'}"
        if active_session.label:
            title += f": {active_session.label}"
        st.markdown(f"### {title}")
        if active_session.overall_notes:
            st.caption(active_session.overall_notes)

        if can_edit_sessions:
            with st.expander("Delete this session"):
                st.warning(f"This permanently deletes this session and all {len(active_session.swings)} swing(s) logged in it. This can't be undone.")
                confirm_delete = st.checkbox("Yes, I want to permanently delete this session", key=f"confirm_delete_ht_{active_session.session_id}")
                if st.button("Delete session", key=f"delete_ht_{active_session.session_id}", disabled=not confirm_delete, type="primary"):
                    deleted_id = active_session.session_id
                    session.delete(active_session)
                    session.commit()
                    _set_active_session(None)
                    st.success(f"Deleted session #{deleted_id}.")
                    st.rerun()

        if can_edit_sessions:
            st.subheader(f"Swing #{len(active_session.swings) + 1}")

            if st.session_state.get("ht_reset_pending"):
                st.session_state.ht_pitch_type = "4-Seam Fastball"
                st.session_state.ht_target_zone = 5
                st.session_state.ht_intended_zone = 5
                st.session_state.ht_pitcher_hand = "R"
                st.session_state.ht_roster_pitcher = None
                st.session_state.ht_reset_pending = False

            pitch_type_choice = st.selectbox("Pitch type", [pt.type_name for pt in pitch_types], key="ht_pitch_type")

            if "ht_pitcher_hand" not in st.session_state:
                st.session_state.ht_pitcher_hand = "R"
            pitcher_hand_choice = st.radio("Pitcher hand", ["R", "L"], horizontal=True, key="ht_pitcher_hand")

            roster_pitcher_choice = st.selectbox(
                "Link to a roster pitcher? (optional)",
                options=[None] + list(roster_pitchers_by_id.keys()),
                format_func=lambda pid: "-- Not a roster pitcher (BP/machine/opponent) --" if pid is None else f"{roster_pitchers_by_id[pid].first_name} {roster_pitchers_by_id[pid].last_name}",
                key="ht_roster_pitcher",
            )

            intended_zone_choice = None
            if roster_pitcher_choice is not None:
                st.caption("Intended zone (what he was aiming for)")
                if "ht_intended_zone" not in st.session_state:
                    st.session_state.ht_intended_zone = 5
                zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
                for row in zone_layout:
                    cols = st.columns(3)
                    for i, zone in enumerate(row):
                        is_selected = st.session_state.ht_intended_zone == zone
                        label = f"● {zone}" if is_selected else str(zone)
                        if cols[i].button(label, key=f"ht_intended_zone_btn_{zone}", use_container_width=True):
                            st.session_state.ht_intended_zone = zone
                            st.rerun()
                bury_intended_selected = st.session_state.ht_intended_zone == 0
                bury_intended_label = "● Bury (in the dirt)" if bury_intended_selected else "Bury (in the dirt)"
                if st.button(bury_intended_label, key="ht_intended_zone_btn_bury", use_container_width=True):
                    st.session_state.ht_intended_zone = 0
                    st.rerun()
                st.caption(f"Selected: {st.session_state.ht_intended_zone} ({ZONE_LABELS[st.session_state.ht_intended_zone]})")
                intended_zone_choice = st.session_state.ht_intended_zone

            st.caption("Actual location (where it ended up)")
            if "ht_target_zone" not in st.session_state:
                st.session_state.ht_target_zone = 5
            zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
            for row in zone_layout:
                cols = st.columns(3)
                for i, zone in enumerate(row):
                    is_selected = st.session_state.ht_target_zone == zone
                    label = f"● {zone}" if is_selected else str(zone)
                    if cols[i].button(label, key=f"ht_zone_btn_{zone}", use_container_width=True):
                        st.session_state.ht_target_zone = zone
                        st.rerun()
            bury_selected = st.session_state.ht_target_zone == 0
            bury_label = "● Bury (in the dirt)" if bury_selected else "Bury (in the dirt)"
            if st.button(bury_label, key="ht_zone_btn_bury", use_container_width=True):
                st.session_state.ht_target_zone = 0
                st.rerun()
            st.caption(f"Selected: {st.session_state.ht_target_zone} ({ZONE_LABELS[st.session_state.ht_target_zone]})")

            with st.form("hitter_swing_form"):
                contact_quality_choice = st.selectbox("Contact quality", ["-- Select --"] + CONTACT_QUALITY_OPTIONS)
                hit_location_choice = None
                if contact_quality_choice != "Miss":
                    hit_location_choice = st.selectbox("Where was it hit? (optional)", ["-- Not specified --"] + HIT_LOCATION_OPTIONS)
                swing_notes = st.text_input("Notes (optional)")
                log_swing_submitted = st.form_submit_button("Record swing", type="primary")

            if log_swing_submitted:
                if contact_quality_choice == "-- Select --":
                    st.error("Select a contact quality before recording the swing.")
                else:
                    pitch_type_id = next(pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_choice)
                    session.add(HitterSwing(
                        session_id=active_session.session_id,
                        swing_number=len(active_session.swings) + 1,
                        pitch_type_id=pitch_type_id,
                        intended_zone=intended_zone_choice,
                        pitch_zone=st.session_state.ht_target_zone,
                        pitcher_hand=pitcher_hand_choice,
                        pitcher_player_id=roster_pitcher_choice,
                        contact_quality=contact_quality_choice,
                        hit_location=hit_location_choice if hit_location_choice and hit_location_choice != "-- Not specified --" else None,
                        notes=swing_notes.strip() or None,
                    ))
                    session.commit()
                    st.session_state.ht_reset_pending = True
                    st.success(f"Recorded swing #{len(active_session.swings) + 1}.")
                    st.rerun()

        st.divider()
        st.subheader("Swing log")
        if not active_session.swings:
            empty_state("No swings logged yet for this session.")
        else:
            st.dataframe(
                [
                    {
                        "#": s.swing_number,
                        "Pitch Type": s.pitch_type.type_name if s.pitch_type else "—",
                        "Intended": f"{s.intended_zone} ({ZONE_LABELS.get(s.intended_zone, '—')})" if s.intended_zone is not None else "—",
                        "Actual": f"{s.pitch_zone} ({ZONE_LABELS.get(s.pitch_zone, '—')})" if s.pitch_zone is not None else "—",
                        "Located": "Yes" if (s.intended_zone is not None and s.pitch_zone is not None and s.intended_zone == s.pitch_zone) else ("No" if s.intended_zone is not None and s.pitch_zone is not None else "—"),
                        "Pitcher Hand": s.pitcher_hand or "—",
                        "Roster Pitcher": f"{s.pitcher_player.first_name} {s.pitcher_player.last_name}" if s.pitcher_player else "—",
                        "Contact": s.contact_quality or "—",
                        "Hit Location": s.hit_location or "—",
                        "Notes": s.notes or "",
                    }
                    for s in active_session.swings
                ],
                use_container_width=True,
                hide_index=True,
            )

            with st.expander(f"Swing video ({sum(1 for s in active_session.swings if s.video_url)} of {len(active_session.swings)} swings have video)"):
                video_swings_by_id = {s.swing_id: s for s in active_session.swings}
                video_swing_id = st.selectbox(
                    "Swing",
                    options=list(video_swings_by_id.keys()),
                    format_func=lambda sid: f"Swing #{video_swings_by_id[sid].swing_number}"
                    + (f" ({video_swings_by_id[sid].pitch_type.type_name})" if video_swings_by_id[sid].pitch_type else "")
                    + (f" — {video_swings_by_id[sid].contact_quality}" if video_swings_by_id[sid].contact_quality else "")
                    + (" (video)" if video_swings_by_id[sid].video_url else ""),
                    key="ht_video_swing_choice",
                )
                selected_video_swing = video_swings_by_id[video_swing_id]

                if selected_video_swing.video_url:
                    st.video(selected_video_swing.video_url)

                if can_edit_sessions:
                    upload_label = "Replace video" if selected_video_swing.video_url else "Upload video"
                    swing_video_file = st.file_uploader(upload_label, type=["mp4", "mov", "m4v"], key=f"ht_video_upload_{selected_video_swing.swing_id}")
                    if swing_video_file is not None and st.button("Save video", key=f"ht_video_save_{selected_video_swing.swing_id}", type="primary"):
                        identifier = f"hitter-swing-{active_session.session_id}-{selected_video_swing.swing_number}"
                        url = upload_swing_video(swing_video_file, identifier)
                        if url:
                            selected_video_swing.video_url = url
                            session.commit()
                            st.success(f"Saved video for swing #{selected_video_swing.swing_number}.")
                            st.rerun()

    # --- Hitter heatmap: this hitter's contact quality by zone, across ALL their sessions ---
    st.divider()
    st.subheader(f"{selected_hitter.first_name} {selected_hitter.last_name}'s zone heatmap")
    all_hitter_swings = (
        session.query(HitterSwing)
        .join(HitterTrackingSession)
        .filter(HitterTrackingSession.player_id == selected_hitter_id)
        .all()
    )
    hand_filter = st.radio("Filter by pitcher hand", ["All", "vs RHP", "vs LHP"], horizontal=True, key="ht_heatmap_hand_filter")
    filtered_swings = all_hitter_swings
    if hand_filter == "vs RHP":
        filtered_swings = [s for s in all_hitter_swings if s.pitcher_hand == "R"]
    elif hand_filter == "vs LHP":
        filtered_swings = [s for s in all_hitter_swings if s.pitcher_hand == "L"]

    if not filtered_swings:
        empty_state("No swings logged yet to build a heatmap from.")
    else:
        zone_scores, zone_counts = compute_zone_scores(filtered_swings)
        if not zone_scores:
            empty_state("No swings with both a zone and contact quality recorded yet.")
        else:
            render_zone_heatmap(
                f"Contact quality by zone ({hand_filter})", zone_scores, zone_counts,
                subtitle="Green = best contact (Barrel/Solid), red = weakest (Weak/Miss). Number in parentheses is swing count.",
            )

finally:
    session.close()

page_footer()