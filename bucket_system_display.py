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

from bucket_system import BODY_COMP_METRICS

# Body Comp fields that get a percentile bar (the same 2 that feed
# body_comp_score). Body Fat Mass / Percent Body Fat are reference-only
# (see BODY_COMP_DISPLAY_METRICS in bucket_system.py) -- Ryker's call,
# after the "lower is better" percentile ratio produced a confusing-
# looking result (16% body fat showing as "42nd percentile") that was
# really just one lean teammate's value dominating the min/value ratio.
# Beyond the math being unintuitive here, ranking players against each
# other on body fat specifically -- even implicitly via a bar chart --
# isn't something this system should do. Raw value only for those two,
# no team comparison at all.
BODY_COMP_BAR_NAMES = {name for name, _ in BODY_COMP_METRICS}


def render_percentage_rings(metrics, key_prefix, show_ordinal=False):
    """Generic full-circle percentage ring display -- metrics is a list
    of (label, value) tuples, value 0-100 or None. show_ordinal=True
    displays just the plain rounded number ("45") centered in the ring
    with no sub-label inside it -- the metric's own label is rendered
    underneath the ring instead (see the block below the chart) -- for
    percentile-style data (Physical Testing), per Ryker's call to drop
    both the ordinal suffix ("45th") and the word "Percentile" entirely
    and just show the number; False (the default) displays it as a
    plain percentage ("45%") with the metric's own label as the
    in-ring sub-label, for direct-percentage KPIs (pitching command,
    etc.) -- unaffected by that change. Returns False (renders nothing)
    if every value is None."""
    has_any_data = any(v is not None for _, v in metrics)
    if not has_any_data:
        return False

    cols = st.columns(len(metrics))
    for (label, value), col in zip(metrics, cols):
        with col:
            if value is None:
                st.markdown(f"**{label}**")
                st.caption("No data yet")
                continue
            fig = go.Figure(go.Pie(
                values=[value, 100 - value],
                hole=0.72,
                marker=dict(colors=["#BF1E2D", "#3A3A3A"]),
                direction="clockwise",
                rotation=0,
                sort=False,
                textinfo="none",
                hoverinfo="skip",
            ))
            if show_ordinal:
                annotation_text = f"<b>{round(value)}</b>"
            else:
                annotation_text = f"<b>{value:.0f}%</b><br><span style='font-size:13px'>{label}</span>"
            fig.update_layout(
                showlegend=False,
                annotations=[dict(
                    text=annotation_text,
                    x=0.5, y=0.5, font=dict(size=26, color="#FFFDE5"), showarrow=False,
                )],
                paper_bgcolor="#1E1E1E",
                margin=dict(t=10, b=10, l=10, r=10),
                height=200,
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_ring_{label}")
            if show_ordinal:
                st.markdown(f"<p style='text-align:center; margin-top:-10px;'><b>{label}</b></p>", unsafe_allow_html=True)
    return True


def render_score_rings(bucket_data, key_prefix):
    """Total/Body Comp/Power/Strength as full-circle percentage rings,
    matching Ryker's reference screenshot's style -- not Plotly's
    default semicircle gauge, which doesn't produce a true full ring.
    Shows nothing at all if there's no data yet for any of them."""
    specs = [
        ("Total", bucket_data["total_score"]),
        ("Body Comp", bucket_data["body_comp_score"]),
        ("Power", bucket_data["power_score"]),
        ("Strength", bucket_data["strength_score"]),
    ]
    return render_percentage_rings(specs, key_prefix, show_ordinal=True)


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


def render_raw_metrics(metrics_dict):
    """Plain raw-value line, no percentile bar and no team comparison
    -- for Body Comp fields that are reference-only (Body Fat Mass,
    Percent Body Fat). Ignores the "percentile" key entirely, even
    though it's present in the dict (bucket_system.py still computes
    it) -- deliberately never shown, see BODY_COMP_BAR_NAMES above for
    why. Renders nothing if empty."""
    if not metrics_dict:
        return
    parts = [f"{name}: {d['raw']:.1f}{d['unit'] or ''}" for name, d in metrics_dict.items()]
    st.caption("Reference only, not scored — " + "  •  ".join(parts))


def render_full_breakdown(bucket_data, key_prefix):
    """Sub-group score headers + a bar chart per sub-group, for Body
    Comp, Power, Strength, and Speed (reference only)."""
    st.markdown(f"**Body Comp** — {bucket_data['body_comp_score'] if bucket_data['body_comp_score'] is not None else '—'}")
    body_comp_metrics = bucket_data["body_comp_metrics"]
    bar_metrics = {name: v for name, v in body_comp_metrics.items() if name in BODY_COMP_BAR_NAMES}
    raw_only_metrics = {name: v for name, v in body_comp_metrics.items() if name not in BODY_COMP_BAR_NAMES}
    render_metric_bars(bar_metrics, f"{key_prefix}_body_comp")
    render_raw_metrics(raw_only_metrics)

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

    capacity_metrics_present = any(bucket_data.get("capacity_subgroup_metrics", {}).values())
    if capacity_metrics_present:
        st.markdown(f"**Capacity** (reference only, not in Total) — {bucket_data['capacity_score'] if bucket_data['capacity_score'] is not None else '—'}")
        for sub_name, sub_score in bucket_data["capacity_subgroup_scores"].items():
            metrics = bucket_data["capacity_subgroup_metrics"][sub_name]
            if not metrics:
                continue
            st.markdown(f"*{sub_name}* — {sub_score if sub_score is not None else '—'}")
            render_metric_bars(metrics, f"{key_prefix}_capacity_{sub_name}")


def render_development_profile(bucket_data, key_prefix):
    """Output vs. Capacity rings + a Balance bar, per the Physical
    Assessment & IDP design brief -- deliberately its own section, not
    folded into the Physical Testing rings above (Total/Body Comp/
    Power/Strength), since Output/Capacity/Balance answer a different
    question (development profile, not overall physical testing
    standing) and mixing them into one row of rings would blur that.
    Renders nothing if there's not enough data to classify a profile
    yet (matches render_score_rings' same "show nothing" behavior)."""
    output_score = bucket_data.get("output_score")
    capacity_score = bucket_data.get("capacity_score")
    balance_pct = bucket_data.get("balance_pct")
    profile = bucket_data.get("development_profile")

    if output_score is None or capacity_score is None:
        return False

    st.markdown(f"**Development Profile: {profile or '—'}**")
    render_percentage_rings(
        [("Physical Output", output_score), ("Physical Capacity", capacity_score)],
        f"{key_prefix}_dev_profile", show_ordinal=True,
    )

    if balance_pct is not None:
        # Horizontal balance bar: a fixed -50/+50 scale (well past any
        # realistic balance_pct), a center reference line at 0, and a
        # marker at the athlete's actual balance_pct, clamped to the
        # display range so an extreme outlier doesn't fly off the
        # chart. Capacity-dominant reads left, Output-dominant reads
        # right, matching the "Output <-> Capacity" sketch in the brief.
        display_pct = max(-50, min(50, balance_pct))
        fig = go.Figure()
        fig.add_shape(type="line", x0=-50, x1=50, y0=0, y1=0, line=dict(color="#3A3A3A", width=4))
        fig.add_shape(type="line", x0=0, x1=0, y0=-0.3, y1=0.3, line=dict(color="#FFFDE5", width=2))
        fig.add_trace(go.Scatter(
            x=[display_pct], y=[0], mode="markers",
            marker=dict(size=22, color="#BF1E2D", line=dict(color="#FFFDE5", width=2)),
            showlegend=False, hoverinfo="skip",
        ))
        fig.update_layout(
            xaxis=dict(range=[-55, 55], visible=False, fixedrange=True),
            yaxis=dict(range=[-1, 1], visible=False, fixedrange=True),
            paper_bgcolor="#1E1E1E", plot_bgcolor="#1E1E1E",
            height=90, margin=dict(l=10, r=10, t=10, b=10),
            annotations=[
                dict(x=-50, y=-0.7, text="Capacity-Dominant", showarrow=False, font=dict(color="#FFFDE5", size=12), xanchor="left"),
                dict(x=50, y=-0.7, text="Output-Dominant", showarrow=False, font=dict(color="#FFFDE5", size=12), xanchor="right"),
            ],
        )
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_balance_bar")
        st.caption(f"Balance: {balance_pct:+.1f}% (provisional bands -- not a validated threshold yet)")
    return True