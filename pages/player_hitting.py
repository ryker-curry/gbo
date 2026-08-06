"""
GBO — My Hitting (Player role only).

Read-only view of the player's own Hitter Tracking sessions and their
own contact-quality-by-zone heatmap. Summary-only per session (no full
swing-by-swing table), same philosophy as My Bullpens -- video is
still browsable per swing.
"""

import streamlit as st
import plotly.graph_objects as go

from database import get_session
from models import Player, User, HitterTrackingSession, HitterSwing
from ui_components import page_header, page_footer, empty_state

page_header("My Hitting")

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

CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}


def compute_zone_scores(swings):
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def render_zone_heatmap(title, zone_scores, zone_counts, subtitle=None):
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_scores.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_scores[zid]:.1f}<br>({zone_counts[zid]})" if zid in zone_scores else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn", zmin=0, zmax=3, showscale=True,
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


session = get_session()
try:
    me = session.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        st.info("Your player profile isn't linked yet. Check with an administrator.")
        page_footer()
        st.stop()

    my_player = session.query(Player).filter(Player.player_id == me.player_id).first()

    sessions = (
        session.query(HitterTrackingSession)
        .filter(HitterTrackingSession.player_id == my_player.player_id)
        .order_by(HitterTrackingSession.session_date.desc())
        .all()
    )

    st.subheader("My sessions")
    if not sessions:
        empty_state("No hitting sessions recorded yet.")
    else:
        for s in sessions:
            type_name = s.session_type.type_name if s.session_type else "—"
            title = f"{s.session_date.strftime('%Y-%m-%d (%a)')} — {type_name}"
            if s.label:
                title += f": {s.label}"
            title += f" ({len(s.swings)} swings)"
            with st.expander(title):
                if s.overall_notes:
                    st.caption(s.overall_notes)
                if not s.swings:
                    st.caption("No swings recorded for this session.")
                else:
                    counts_by_quality = {}
                    counts_by_type = {}
                    for sw in s.swings:
                        if sw.contact_quality:
                            counts_by_quality[sw.contact_quality] = counts_by_quality.get(sw.contact_quality, 0) + 1
                        pt_name = sw.pitch_type.type_name if sw.pitch_type else "—"
                        counts_by_type[pt_name] = counts_by_type.get(pt_name, 0) + 1

                    st.markdown("**Contact quality**")
                    quality_line = " · ".join(f"{q}: {c}" for q, c in counts_by_quality.items())
                    st.write(quality_line or "—")

                    st.markdown("**By pitch type**")
                    type_line = " · ".join(f"{t}: {c}" for t, c in counts_by_type.items())
                    st.write(type_line or "—")

                    video_swings = [sw for sw in s.swings if sw.video_url]
                    if video_swings:
                        st.markdown(f"**Swing video** ({len(video_swings)} of {len(s.swings)} swings)")
                        video_swings_by_id = {sw.swing_id: sw for sw in video_swings}
                        chosen_id = st.selectbox(
                            "Watch",
                            options=list(video_swings_by_id.keys()),
                            format_func=lambda sid: f"Swing #{video_swings_by_id[sid].swing_number}"
                            + (f" ({video_swings_by_id[sid].pitch_type.type_name})" if video_swings_by_id[sid].pitch_type else "")
                            + (f" — {video_swings_by_id[sid].contact_quality}" if video_swings_by_id[sid].contact_quality else ""),
                            key=f"my_ht_video_choice_{s.session_id}",
                        )
                        st.video(video_swings_by_id[chosen_id].video_url)

    st.divider()
    st.subheader("My zone heatmap")
    all_swings = (
        session.query(HitterSwing)
        .join(HitterTrackingSession)
        .filter(HitterTrackingSession.player_id == my_player.player_id)
        .all()
    )
    hand_filter = st.radio("Filter by pitcher hand", ["All", "vs RHP", "vs LHP"], horizontal=True, key="my_ht_hand_filter")
    filtered_swings = all_swings
    if hand_filter == "vs RHP":
        filtered_swings = [sw for sw in all_swings if sw.pitcher_hand == "R"]
    elif hand_filter == "vs LHP":
        filtered_swings = [sw for sw in all_swings if sw.pitcher_hand == "L"]

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