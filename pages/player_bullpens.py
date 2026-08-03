"""
GBO — My Bullpens (Player role only).

Read-only view of the player's own bullpen sessions -- pitch log and
the same type-adaptive summary shown to coaches on Bullpen Tracking,
just without any editing/logging controls.
"""

import streamlit as st
import plotly.graph_objects as go
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, BullpenSession
from ui_components import page_header, page_footer, empty_state

page_header("My Bullpens")

# Same fixed generic strike-zone boundaries used on Bullpen Tracking.
ZONE_SIDE_BOUNDS = (-0.283, 0.283)
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)
BURY_HEIGHT_THRESHOLD = 1.5  # ft -- below this counts as "buried", regardless of target

PITCH_TYPE_COLORS = [
    "#BF1E2D", "#D4AF37", "#4C6EF5", "#37B24D", "#F76707", "#AE3EC9", "#0CA678", "#E64980",
]


def render_scatter_with_averages(title, x_label, y_label, data_by_type, x_key, y_key):
    """A scatter plot showing individual pitches (small, faded) plus a
    bold, labeled average marker per pitch type."""
    fig = go.Figure()
    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e[x_key] for e in entries if x_key in e and y_key in e]
        ys = [e[y_key] for e in entries if x_key in e and y_key in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=8, opacity=0.35),
            showlegend=False,
            hovertemplate=f"{pitch_type}<br>{x_label}: %{{x}}<br>{y_label}: %{{y}}<extra></extra>",
        ))
        avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
        fig.add_trace(go.Scatter(
            x=[avg_x], y=[avg_y], mode="markers+text", name=pitch_type,
            marker=dict(color=color, size=18, line=dict(color="#FFFDE5", width=2)),
            text=[pitch_type], textposition="top center",
            textfont=dict(color="#FFFDE5", size=12),
            hovertemplate=f"{pitch_type} average<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(
        title=title,
        xaxis_title=x_label, yaxis_title=y_label,
        showlegend=False, height=420,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        margin=dict(t=40, b=40, l=40, r=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def compute_actual_zone(plate_side_ft, plate_height_ft):
    if plate_height_ft < BURY_HEIGHT_THRESHOLD:
        return 0
    if plate_side_ft < ZONE_SIDE_BOUNDS[0]:
        col = 0
    elif plate_side_ft > ZONE_SIDE_BOUNDS[1]:
        col = 2
    else:
        col = 1
    if plate_height_ft > ZONE_HEIGHT_BOUNDS[1]:
        row = 0
    elif plate_height_ft < ZONE_HEIGHT_BOUNDS[0]:
        row = 2
    else:
        row = 1
    return row * 3 + col + 1


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

    sessions = (
        session.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.pitches))
        .filter(BullpenSession.player_id == my_player.player_id)
        .order_by(BullpenSession.session_date.desc())
        .all()
    )

    if not sessions:
        empty_state("No bullpen sessions recorded yet.")
        page_footer()
        st.stop()

    def _summarize(b):
        s_linked = 0
        s_hits = 0
        s_hits_by_type = {}
        s_counts_by_type = {}
        s_velos_by_type = {}
        s_movement_by_type = {}
        for p in b.pitches:
            pt_name = p.pitch_type.type_name if p.pitch_type else "—"
            s_counts_by_type[pt_name] = s_counts_by_type.get(pt_name, 0) + 1
            if p.linked_assessment:
                s_linked += 1
                results = {r.test_type.test_name: float(r.value) for r in p.linked_assessment.results}
                plate_side = results.get("Plate Side")
                plate_height = results.get("Plate Height")
                if plate_side is not None and plate_height is not None:
                    a_zone = compute_actual_zone(plate_side, plate_height)
                    if a_zone == p.target_zone:
                        s_hits += 1
                        s_hits_by_type[pt_name] = s_hits_by_type.get(pt_name, 0) + 1
                v = results.get("Velocity")
                if v is not None:
                    s_velos_by_type.setdefault(pt_name, []).append(v)
                s_movement_by_type.setdefault(pt_name, []).append(results)
        return {
            "linked": s_linked, "hits": s_hits, "hits_by_type": s_hits_by_type,
            "counts_by_type": s_counts_by_type, "velos_by_type": s_velos_by_type,
            "movement_by_type": s_movement_by_type, "total_pitches": len(b.pitches),
        }

    def _find_previous(idx):
        """First earlier session (later in this date-desc-sorted list)
        of the same bullpen type, for a fair comparison."""
        current_type_id = sessions[idx].bullpen_type_id
        for other in sessions[idx + 1:]:
            if other.bullpen_type_id == current_type_id:
                return other
        return None

    for idx, b in enumerate(sessions):
        bp_type_name = b.bullpen_type.type_name if b.bullpen_type else "—"
        date_label = b.session_date.strftime("%Y-%m-%d (%a)")
        with st.expander(f"{date_label} — {bp_type_name} ({len(b.pitches)} pitches)"):
            if b.overall_notes:
                st.caption(b.overall_notes)

            if not b.pitches:
                st.caption("No pitches recorded for this session.")
            else:
                current = _summarize(b)
                hits = current["hits"]
                linked_count = current["linked"]
                counts_by_type = current["counts_by_type"]
                hits_by_type = current["hits_by_type"]
                velos_by_type = current["velos_by_type"]
                movement_by_type = current["movement_by_type"]

                previous_session = _find_previous(idx)
                prev_summary = _summarize(previous_session) if previous_session else None
                prev_date_label = previous_session.session_date.strftime("%Y-%m-%d (%a)") if previous_session else None

                st.markdown("**Summary**")
                if bp_type_name == "High Intent Velo":
                    all_velos = [v for vs in velos_by_type.values() for v in vs]
                    if not all_velos:
                        st.caption("No velocity data linked yet for this session.")
                    else:
                        avg_velo = sum(all_velos) / len(all_velos)
                        max_velo = max(all_velos)
                        prev_avg_delta = prev_max_delta = None
                        if prev_summary and prev_summary["velos_by_type"]:
                            prev_all = [v for vs in prev_summary["velos_by_type"].values() for v in vs]
                            if prev_all:
                                prev_avg_delta = avg_velo - (sum(prev_all) / len(prev_all))
                                prev_max_delta = max_velo - max(prev_all)
                        c1, c2 = st.columns(2)
                        c1.metric("Max velocity", f"{max_velo:.1f} mph", f"{prev_max_delta:+.1f} vs {prev_date_label}" if prev_max_delta is not None else None)
                        c1.metric("Average velocity", f"{avg_velo:.1f} mph", f"{prev_avg_delta:+.1f} vs {prev_date_label}" if prev_avg_delta is not None else None)
                        by_type_lines = [f"{pt}: avg {sum(vs)/len(vs):.1f} mph, max {max(vs):.1f} mph" for pt, vs in velos_by_type.items()]
                        c2.markdown("\n\n".join(by_type_lines))
                elif bp_type_name == "Pitch Design":
                    if not movement_by_type:
                        st.caption("No movement data linked yet for this session.")
                    else:
                        def _avg_of(entries, key):
                            vals = [e[key] for e in entries if key in e]
                            return round(sum(vals) / len(vals), 1) if vals else None

                        summary_rows = []
                        for pt, entries in movement_by_type.items():
                            row = {"Pitch Type": pt, "Count": len(entries)}
                            prev_entries = prev_summary["movement_by_type"].get(pt) if prev_summary else None
                            for label, key in [
                                ("Avg Spin Rate (rpm)", "Spin Rate"),
                                ("Avg Horizontal Break (in)", "Horizontal Break"),
                                ("Avg Induced Vert. Break (in)", "Induced Vertical Break"),
                            ]:
                                cur_avg = _avg_of(entries, key)
                                row[label] = cur_avg if cur_avg is not None else "—"
                                if cur_avg is not None and prev_entries:
                                    prev_avg = _avg_of(prev_entries, key)
                                    if prev_avg is not None:
                                        row[f"{label} vs last"] = f"{round(cur_avg - prev_avg, 1):+.1f}"
                            summary_rows.append(row)
                        st.dataframe(summary_rows, use_container_width=True, hide_index=True)
                        if previous_session:
                            st.caption(f"\"vs last\" compares to the previous {bp_type_name} session on {prev_date_label}.")
                elif bp_type_name in ("Execution Focused", "Short Box"):
                    if linked_count == 0:
                        st.caption("No pitches linked to Rapsodo data yet for this session.")
                    else:
                        pct = round(100 * hits / linked_count)
                        delta_str = None
                        if prev_summary and prev_summary["linked"] > 0:
                            prev_pct = round(100 * prev_summary["hits"] / prev_summary["linked"])
                            delta_str = f"{pct - prev_pct:+d} pts vs {prev_date_label}"
                        c1, c2 = st.columns(2)
                        c1.metric("Overall execution", f"{hits}/{linked_count}", f"{pct}%")
                        if delta_str:
                            c1.caption(delta_str)
                        by_type_lines = [f"{pt}: {hits_by_type.get(pt, 0)}/{count}" for pt, count in counts_by_type.items()]
                        c2.markdown("\n\n".join(by_type_lines))
                else:
                    delta = len(b.pitches) - prev_summary["total_pitches"] if prev_summary else None
                    st.metric("Total pitches", len(b.pitches), f"{delta:+d} vs {prev_date_label}" if delta is not None else None)
                    by_type_lines = [f"{pt}: {count}" for pt, count in counts_by_type.items()]
                    st.markdown("\n\n".join(by_type_lines))

                # --- Charts (shared across all bullpen types) ---
                movement_data = current["movement_by_type"]
                has_movement = any("Horizontal Break" in e and "Induced Vertical Break" in e for entries in movement_data.values() for e in entries)
                has_release = any("Release Side" in e and "Release Height" in e for entries in movement_data.values() for e in entries)
                has_velocity = any(vs for vs in current["velos_by_type"].values())

                if has_movement or has_release or has_velocity:
                    st.markdown("**Charts**")
                    st.caption("Bold labeled markers are the average per pitch type; smaller dots are individual pitches.")
                    if has_movement:
                        render_scatter_with_averages(
                            "Movement Plot", "Horizontal Break (in)", "Induced Vertical Break (in)",
                            movement_data, "Horizontal Break", "Induced Vertical Break",
                        )
                    if has_release:
                        render_scatter_with_averages(
                            "Release Point (tunneling)", "Release Side (ft)", "Release Height (ft)",
                            movement_data, "Release Side", "Release Height",
                        )
                    if has_velocity:
                        velo_fig = go.Figure()
                        for i, (pt_name, vs) in enumerate(current["velos_by_type"].items()):
                            if not vs:
                                continue
                            color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
                            velo_fig.add_trace(go.Bar(x=[pt_name], y=[sum(vs) / len(vs)], marker_color=color, showlegend=False, name=pt_name))
                        velo_fig.update_layout(
                            title="Average Velocity by Pitch Type", yaxis_title="mph",
                            plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E", font=dict(color="#FFFDE5"),
                            yaxis=dict(gridcolor="#3A3A3A"), height=380, margin=dict(t=40, b=40, l=40, r=40),
                        )
                        st.plotly_chart(velo_fig, use_container_width=True)

                # --- Pitch video (release/mechanics review) -- video only,
                # not the full pitch-by-pitch data table (kept off this
                # page deliberately per Ryker's request for summary-only).
                video_pitches = [p for p in b.pitches if p.video_url]
                if video_pitches:
                    st.markdown(f"**Pitch video** ({len(video_pitches)} of {len(b.pitches)} pitches)")
                    video_pitches_by_id = {p.bullpen_pitch_id: p for p in video_pitches}
                    chosen_video_pitch_id = st.selectbox(
                        "Watch",
                        options=list(video_pitches_by_id.keys()),
                        format_func=lambda pid: f"Pitch #{video_pitches_by_id[pid].pitch_number}"
                        + (f" ({video_pitches_by_id[pid].pitch_type.type_name})" if video_pitches_by_id[pid].pitch_type else ""),
                        key=f"my_bp_video_choice_{b.bullpen_id}",
                    )
                    st.video(video_pitches_by_id[chosen_video_pitch_id].video_url)

finally:
    session.close()

page_footer()