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


def render_bucket_gauges(bucket_data, key_prefix):
    """The 4 big gauges: Total, Body Comp, Power, Strength. Shows
    nothing at all (not 4 empty boxes) if there's no data yet for any
    of them. key_prefix keeps chart keys unique across pages/calls."""
    has_any_data = any(bucket_data[k] is not None for k in ("total_score", "body_comp_score", "power_score", "strength_score"))
    if not has_any_data:
        return False

    gauge_cols = st.columns(4)
    gauge_specs = [
        ("Total", "total_score", gauge_cols[0]),
        ("Body Comp", "body_comp_score", gauge_cols[1]),
        ("Power", "power_score", gauge_cols[2]),
        ("Strength", "strength_score", gauge_cols[3]),
    ]
    for label, key, col in gauge_specs:
        score = bucket_data[key]
        with col:
            if score is None:
                st.markdown(f"**{label}**")
                st.caption("No data yet")
                continue
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=score,
                number={"font": {"color": "#FFFDE5"}},
                title={"text": label, "font": {"color": "#FFFDE5", "size": 16}},
                gauge={
                    "axis": {"range": [0, 100], "tickcolor": "#FFFDE5"},
                    "bar": {"color": "#BF1E2D"},
                    "bgcolor": "#1E1E1E",
                    "borderwidth": 0,
                },
            ))
            fig.update_layout(height=200, margin=dict(t=40, b=10, l=20, r=20), paper_bgcolor="#1E1E1E", font=dict(color="#FFFDE5"))
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_gauge_{key}")
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