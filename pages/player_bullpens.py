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
from models import Player, User, BullpenSession, HitterSwing
from ui_components import page_header, page_footer, empty_state

page_header("My Bullpens")

# Same fixed generic strike-zone boundaries used on Bullpen Tracking.
ZONE_SIDE_BOUNDS = (-0.283, 0.283)
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)
BURY_HEIGHT_THRESHOLD = 1.5  # ft -- below this counts as "buried", regardless of target

# Full strike zone rectangle bounds (feet) -- see Bullpen Tracking for the derivation comment.
_SIDE_THIRD = ZONE_SIDE_BOUNDS[1] - ZONE_SIDE_BOUNDS[0]
FULL_ZONE_SIDE = (ZONE_SIDE_BOUNDS[0] - _SIDE_THIRD, ZONE_SIDE_BOUNDS[1] + _SIDE_THIRD)
_HEIGHT_THIRD = ZONE_HEIGHT_BOUNDS[1] - ZONE_HEIGHT_BOUNDS[0]
FULL_ZONE_HEIGHT = (ZONE_HEIGHT_BOUNDS[0] - _HEIGHT_THIRD, ZONE_HEIGHT_BOUNDS[1] + _HEIGHT_THIRD)

PITCH_TYPE_COLORS = [
    "#BF1E2D", "#D4AF37", "#4C6EF5", "#37B24D", "#F76707", "#AE3EC9", "#0CA678", "#E64980",
]


def render_strike_zone_plot(title, data_by_type):
    """Actual pitch locations plotted against a drawn strike zone --
    matches the same chart on Bullpen Tracking."""
    fig = go.Figure()
    fig.add_shape(type="rect", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1],
                  line=dict(color="#FFFDE5", width=2), fillcolor="rgba(0,0,0,0)")
    for x in ZONE_SIDE_BOUNDS:
        fig.add_shape(type="line", x0=x, x1=x, y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1], line=dict(color="#5A5A5A", width=1, dash="dot"))
    for y in ZONE_HEIGHT_BOUNDS:
        fig.add_shape(type="line", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=y, y1=y, line=dict(color="#5A5A5A", width=1, dash="dot"))

    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e["Plate Side"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        ys = [e["Plate Height"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#1E1E1E", width=1)),
            hovertemplate=f"{pitch_type}<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Plate Side (ft)", yaxis_title="Plate Height (ft)",
        showlegend=True, height=480,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[FULL_ZONE_SIDE[0] - 1, FULL_ZONE_SIDE[1] + 1], scaleanchor="y", scaleratio=1),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[0, FULL_ZONE_HEIGHT[1] + 1.5]),
        margin=dict(t=40, b=40, l=40, r=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig, use_container_width=True)


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


CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}


def compute_zone_scores(swings):
    """Average contact-quality score and count per zone, from a list of
    HitterSwing objects."""
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def render_zone_heatmap(title, zone_scores, zone_counts, invert_colors=False, subtitle=None):
    """3x3 heatmap of average contact-quality score per zone."""
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


def compute_execution_accuracy(swings):
    """Hit-rate (0-100%) and attempt count per INTENDED zone -- how
    often, when this pitcher aimed for a given zone, did he actually
    land it, live, with a hitter in the box."""
    by_zone = {}
    for s in swings:
        if s.intended_zone is None or s.pitch_zone is None:
            continue
        by_zone.setdefault(s.intended_zone, []).append(1 if s.intended_zone == s.pitch_zone else 0)
    rates = {z: 100 * sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return rates, counts


def render_execution_heatmap(title, zone_rates, zone_counts, subtitle=None):
    """3x3 heatmap of hit-rate % per intended zone. Green = high
    accuracy, red = low."""
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_rates.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_rates[zid]:.0f}%<br>({zone_counts[zid]})" if zid in zone_rates else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn", zmin=0, zmax=100, showscale=True,
        colorbar=dict(title="Hit rate %", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
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

    if not my_player.is_pitcher:
        st.error("This page is only available to pitchers -- see My Hitting instead.")
        page_footer()
        st.stop()

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
                # Bullpen type names updated by migrate_rapsodo_bullpen.py --
                # see the matching comment in bullpen_tracking.py.
                if bp_type_name == "Velocity":
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
                elif bp_type_name == "Command":
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
                has_location = any("Plate Side" in e and "Plate Height" in e for entries in movement_data.values() for e in entries)
                has_velocity = any(vs for vs in current["velos_by_type"].values())

                if has_movement or has_release or has_location or has_velocity:
                    st.markdown("**Charts**")
                    if has_location:
                        render_strike_zone_plot("Actual Pitch Locations", movement_data)
                        st.caption("Where pitches actually crossed the plate -- from real Rapsodo Plate Side/Height, not the called intended zone.")
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

    # --- My zone heatmap: where opponents do damage against me, and my
    # own live execution accuracy -- same two heatmaps shown to coaches
    # on Bullpen Tracking (his own page), from Hitter Tracking swing
    # data logged against me by any hitter. ---
    st.divider()
    st.subheader("My zone heatmap")
    my_pitcher_swings = (
        session.query(HitterSwing)
        .filter(HitterSwing.pitcher_player_id == my_player.player_id)
        .all()
    )
    if not my_pitcher_swings:
        empty_state("No swings logged against you yet on Hitter Tracking.")
    else:
        my_zone_scores, my_zone_counts = compute_zone_scores(my_pitcher_swings)
        if not my_zone_scores:
            empty_state("No swings with both a zone and contact quality recorded against you yet.")
        else:
            render_zone_heatmap(
                "Opponent contact quality by zone", my_zone_scores, my_zone_counts, invert_colors=True,
                subtitle="Green = pitches hardest to hit here (good for you), red = hit hardest here. Number in parentheses is swing count.",
            )

        st.divider()
        st.caption("How well you execute to your intended locations with a hitter in the box (from Hitter Tracking).")
        my_exec_rates, my_exec_counts = compute_execution_accuracy(my_pitcher_swings)
        if not my_exec_rates:
            empty_state("No swings with both an intended and actual zone recorded for you yet.")
        else:
            render_execution_heatmap(
                "Live execution accuracy by intended zone", my_exec_rates, my_exec_counts,
                subtitle="Green = you hit your spot most often when you aim here, red = you miss most often. Number in parentheses is attempt count.",
            )

finally:
    session.close()

page_footer()