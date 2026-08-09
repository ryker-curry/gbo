"""
GBO — shared Bucket System / Physical Testing rendering, used by the
Player Dashboard (big gauges only), My Assessments (gauges + full
breakdown, player-facing), and Analytics (gauges + full breakdown,
coach-facing). One place for this so the three pages can't drift.

Deliberately never says "Bucket System" anywhere in the UI -- Ryker's
explicit call. Always labeled "Physical Testing" instead.
"""

import streamlit as st
import plotly.graph_objects as go


def _ordinal(n):
    """45 -> '45th', 82 -> '82nd', 21 -> '21st', 13 -> '13th'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def render_score_rings(bucket_data, key_prefix):
    """Total/Body Comp/Power/Strength as full-circle percentage rings (a
    donut chart with 2 slices: filled + remainder), matching Ryker's
    reference screenshot's style -- not Plotly's default semicircle
    gauge, which doesn't produce a true full ring. Shows nothing at all
    if there's no data yet for any of them."""
    specs = [
        ("Total", "total_score"),
        ("Body Comp", "body_comp_score"),
        ("Power", "power_score"),
        ("Strength", "strength_score"),
    ]
    has_any_data = any(bucket_data[key] is not None for _, key in specs)
    if not has_any_data:
        return False

    cols = st.columns(4)
    for (label, key), col in zip(specs, cols):
        score = bucket_data[key]
        with col:
            if score is None:
                st.markdown(f"**{label}**")
                st.caption("No data yet")
                continue
            fig = go.Figure(go.Pie(
                values=[score, 100 - score],
                hole=0.72,
                marker=dict(colors=["#BF1E2D", "#3A3A3A"]),
                direction="clockwise",
                rotation=0,
                sort=False,
                textinfo="none",
                hoverinfo="skip",
            ))
            fig.update_layout(
                showlegend=False,
                annotations=[dict(
                    text=f"<b>{_ordinal(score)}</b><br><span style='font-size:13px'>Percentile</span>",
                    x=0.5, y=0.5, font=dict(size=26, color="#FFFDE5"), showarrow=False,
                )],
                paper_bgcolor="#1E1E1E",
                margin=dict(t=10, b=10, l=10, r=10),
                height=200,
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_ring_{key}")
            st.markdown(f"<p style='text-align:center; margin-top:-10px;'><b>{label}</b></p>", unsafe_allow_html=True)
    return True


def render_metric_bars(metrics_dict, chart_key):
    """Horizontal bar per metric -- bar length is the percentile
    (0-100), raw value + unit labeled at the end of the bar."""
    if not metrics_dict:
        st.caption("No data yet.")
        return
    names = list(metrics_dict.keys())
    percentiles = [d["percentile"] if d["percentile"] is not None else 0 for d in metrics_dict.values()]
    raw_labels = [f"{d['raw']:.2f}{d['unit'] or ''}" for d in metrics_dict.values()]
    fig = go.Figure(go.Bar(
        x=percentiles,
        y=names,
        orientation="h",
        text=raw_labels,
        textposition="outside",
        marker=dict(color="#BF1E2D"),
    ))
    fig.update_layout(
        xaxis=dict(range=[0, 115], title="Percentile", tickcolor="#FFFDE5", gridcolor="#3A3A3A"),
        yaxis=dict(autorange="reversed"),
        height=max(160, 70 * len(names)),
        margin=dict(l=10, r=60, t=10, b=40),
        paper_bgcolor="#1E1E1E",
        plot_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
    )
    st.plotly_chart(fig, use_container_width=True, key=chart_key)


def render_full_breakdown(bucket_data, key_prefix):
    """Sub-group score headers + a bar chart per sub-group, for Body
    Comp, Power, Strength, and Speed (reference only)."""
    st.markdown(f"**Body Comp** — {bucket_data['body_comp_score'] if bucket_data['body_comp_score'] is not None else '—'}")
    render_metric_bars(bucket_data["body_comp_metrics"], f"{key_prefix}_body_comp")

    st.markdown(f"**Power** — {bucket_data['power_score'] if bucket_data['power_score'] is not None else '—'}")
    for sub_name, sub_score in bucket_data["power_subgroup_scores"].items():
        metrics = bucket_data["power_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        st.markdown(f"*{sub_name}* — {sub_score if sub_score is not None else '—'}")
        render_metric_bars(metrics, f"{key_prefix}_power_{sub_name}")

    st.markdown(f"**Strength** — {bucket_data['strength_score'] if bucket_data['strength_score'] is not None else '—'}")
    for sub_name, sub_score in bucket_data["strength_subgroup_scores"].items():
        metrics = bucket_data["strength_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        st.markdown(f"*{sub_name}* — {sub_score if sub_score is not None else '—'}")
        render_metric_bars(metrics, f"{key_prefix}_strength_{sub_name}")

    if bucket_data["speed_metrics"]:
        st.markdown(f"**Speed** (reference only, not in Total) — {bucket_data['speed_score'] if bucket_data['speed_score'] is not None else '—'}")
        render_metric_bars(bucket_data["speed_metrics"], f"{key_prefix}_speed")