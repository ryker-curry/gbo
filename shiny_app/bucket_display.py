"""
GBO -- Shiny port of bucket_system_display.py (shared Bucket System /
Physical Testing rendering used by My Assessments, Dashboard, and
Analytics -- same sharing arrangement as the original, so those three
pages can't drift from each other).

Same math/labels/layout decisions as the Streamlit version -- only the
rendering mechanism changes, and the calling convention changes from
"render as a side effect, return True/False for whether anything was
shown" to "return a UI element, or None if there's nothing to show" (a
plain function can't both print itself to the page AND hand back a
bool the way Streamlit's model allows -- Shiny components have to
return what they build).

Every chart here is decorative (hoverinfo="skip"/"none" throughout,
no on_select/click handling anywhere in the original either), so
rendering them as static PNGs via fig.to_image() (kaleido) instead of
live plotly.js widgets loses no interactivity. That trade-off is what
lets a variable, data-dependent number of charts -- one ring per metric
that has data, one bar chart per sub-group that has data -- render
inside a single ui.HTML()-free tag tree without needing a fixed,
pre-declared Shiny output id per chart the way shinywidgets'
render_plotly would (bucket_system.py's own data determines the count,
which isn't known ahead of a render).

Deliberately never says "Bucket System" anywhere in the UI, same as the
original -- Ryker's explicit call. Always labeled "Physical Testing".

Mode-awareness: every build_* function below takes mode="dark"|"light"
and looks colors up via theme.chart_colors(mode) instead of hardcoded
hex. These charts are rendered server-side to static PNGs (see
_fig_to_img), so unlike the rest of the UI they can't pick up the
client-side dark-mode toggle through CSS alone -- callers pass
app_state.dark_mode() through explicitly (see modules/player_stats.py).
Bar marks use marker=dict(cornerradius=6) for a rounded data-end,
per the dataviz skill's mark-and-anatomy spec (flat baseline, rounded
tip) -- confirmed working with plotly 6.9.0 + kaleido v1 (see
requirements.txt's kaleido comment: v1 needs a real Chrome install on
the machine, found automatically or via a one-time `plotly_get_chrome`
-- it no longer bundles its own the way the old 0.2.1 pin did).
"""

import base64

import plotly.graph_objects as go
from shiny import ui

from bucket_system import BODY_COMP_METRICS

import theme

BODY_COMP_BAR_NAMES = {name for name, _ in BODY_COMP_METRICS}


def _fig_to_img(fig, width=None, height=None):
    """Render a plotly Figure to a static PNG and wrap it in an <img>
    tag -- see module docstring for why."""
    png_bytes = fig.to_image(format="png", width=width, height=height, scale=2)
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return ui.tags.img(src=f"data:image/png;base64,{b64}", style="max-width:100%; height:auto; display:block; margin:0 auto;")


def build_percentage_rings(metrics, key_prefix, show_ordinal=False, mode="dark"):
    """Generic full-circle percentage ring display -- metrics is a list
    of (label, value) tuples, value 0-100 or None. show_ordinal=True
    displays just the plain rounded number ("45") centered in the ring
    with the label underneath (percentile-style data); False (the
    default) shows a plain percentage ("45%") with the label as the
    in-ring sub-label (direct-percentage KPIs). Returns None (renders
    nothing) if every value is None -- same "show nothing" rule as the
    original's False return."""
    has_any_data = any(v is not None for _, v in metrics)
    if not has_any_data:
        return None

    c = theme.chart_colors(mode)
    col_width = max(1, 12 // len(metrics))
    cols = []
    for label, value in metrics:
        if value is None:
            cols.append(ui.div(ui.p(ui.strong(label)), ui.p("No data yet", class_="text-muted small")))
            continue

        fig = go.Figure(go.Pie(
            values=[value, 100 - value],
            hole=0.72,
            marker=dict(colors=[c["crimson"], c["track"]]),
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
                x=0.5, y=0.5, font=dict(size=26, color=c["text"]), showarrow=False,
            )],
            paper_bgcolor=c["surface"],
            margin=dict(t=10, b=10, l=10, r=10),
            height=200, width=200,
        )
        children = [_fig_to_img(fig, width=200, height=200)]
        if show_ordinal:
            children.append(ui.p(ui.strong(label), style="text-align:center; margin-top:-10px;"))
        cols.append(ui.div(*children))

    return ui.layout_columns(*cols, col_widths=[col_width] * len(cols))


def build_score_rings(bucket_data, key_prefix, mode="dark"):
    """Total/Body Comp/Power/Strength as full-circle percentage rings.
    Returns None (renders nothing) if there's no data yet for any of
    them."""
    specs = [
        ("Total", bucket_data["total_score"]),
        ("Body Comp", bucket_data["body_comp_score"]),
        ("Power", bucket_data["power_score"]),
        ("Strength", bucket_data["strength_score"]),
    ]
    return build_percentage_rings(specs, key_prefix, show_ordinal=True, mode=mode)


def build_metric_bars(metrics_dict, chart_key, mode="dark"):
    """Horizontal bar per metric -- bar length is the percentile
    (0-100), raw value + unit labeled at the end of the bar. Always
    returns something (a "no data" caption if metrics_dict is empty),
    matching the original's unconditional render."""
    if not metrics_dict:
        return ui.p("No data yet.", class_="text-muted small")

    c = theme.chart_colors(mode)
    names = list(metrics_dict.keys())
    percentiles = [d["percentile"] if d["percentile"] is not None else 0 for d in metrics_dict.values()]
    raw_labels = [f"{d['raw']:.2f}{d['unit'] or ''}" for d in metrics_dict.values()]
    fig = go.Figure(go.Bar(
        x=percentiles,
        y=names,
        orientation="h",
        text=raw_labels,
        textposition="outside",
        marker=dict(color=c["crimson"], cornerradius=6),
    ))
    chart_height = max(160, 70 * len(names))
    fig.update_layout(
        xaxis=dict(range=[0, 115], title="Percentile", tickcolor=c["text"], gridcolor=c["grid"]),
        yaxis=dict(autorange="reversed"),
        height=chart_height,
        margin=dict(l=10, r=60, t=10, b=40),
        paper_bgcolor=c["surface"],
        plot_bgcolor=c["surface"],
        font=dict(color=c["text"]),
    )
    return _fig_to_img(fig, width=700, height=chart_height)


def build_raw_metrics(metrics_dict):
    """Plain raw-value line, no percentile bar and no team comparison --
    for Body Comp fields that are reference-only. Returns None if
    empty."""
    if not metrics_dict:
        return None
    parts = [f"{name}: {d['raw']:.1f}{d['unit'] or ''}" for name, d in metrics_dict.items()]
    return ui.p("Reference only, not scored — " + "  •  ".join(parts), class_="text-muted small")


def build_full_breakdown(bucket_data, key_prefix, mode="dark"):
    """Sub-group score headers + a bar chart per sub-group, for Body
    Comp, Power, Strength, and (if present) Speed/Capacity/Mobility/
    Shoulder Health -- all reference-only sections shown exactly when
    the original showed them (same presence checks)."""
    sections = [ui.p(f"Body Comp — {bucket_data['body_comp_score'] if bucket_data['body_comp_score'] is not None else '—'}", class_="gbo-category-title")]
    body_comp_metrics = bucket_data["body_comp_metrics"]
    bar_metrics = {name: v for name, v in body_comp_metrics.items() if name in BODY_COMP_BAR_NAMES}
    raw_only_metrics = {name: v for name, v in body_comp_metrics.items() if name not in BODY_COMP_BAR_NAMES}
    sections.append(build_metric_bars(bar_metrics, f"{key_prefix}_body_comp", mode=mode))
    raw_ui = build_raw_metrics(raw_only_metrics)
    if raw_ui is not None:
        sections.append(raw_ui)

    sections.append(ui.p(f"Power — {bucket_data['power_score'] if bucket_data['power_score'] is not None else '—'}", class_="gbo-category-title"))
    for sub_name, sub_score in bucket_data["power_subgroup_scores"].items():
        metrics = bucket_data["power_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
        sections.append(build_metric_bars(metrics, f"{key_prefix}_power_{sub_name}", mode=mode))

    sections.append(ui.p(f"Strength — {bucket_data['strength_score'] if bucket_data['strength_score'] is not None else '—'}", class_="gbo-category-title"))
    for sub_name, sub_score in bucket_data["strength_subgroup_scores"].items():
        metrics = bucket_data["strength_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
        sections.append(build_metric_bars(metrics, f"{key_prefix}_strength_{sub_name}", mode=mode))

    if bucket_data["speed_metrics"]:
        sections.append(ui.p(f"Speed (reference only, not in Total) — {bucket_data['speed_score'] if bucket_data['speed_score'] is not None else '—'}", class_="gbo-category-title"))
        sections.append(build_metric_bars(bucket_data["speed_metrics"], f"{key_prefix}_speed", mode=mode))

    capacity_metrics_present = any(bucket_data.get("capacity_subgroup_metrics", {}).values())
    if capacity_metrics_present:
        sections.append(ui.p(f"Capacity (reference only, not in Total) — {bucket_data['capacity_score'] if bucket_data['capacity_score'] is not None else '—'}", class_="gbo-category-title"))
        for sub_name, sub_score in bucket_data["capacity_subgroup_scores"].items():
            metrics = bucket_data["capacity_subgroup_metrics"][sub_name]
            if not metrics:
                continue
            sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
            sections.append(build_metric_bars(metrics, f"{key_prefix}_capacity_{sub_name}", mode=mode))

    mobility_metrics_present = any(bucket_data.get("mobility_subgroup_metrics", {}).values())
    if mobility_metrics_present:
        sections.append(ui.p(f"Mobility (reference only, not in Total) — {bucket_data['mobility_score'] if bucket_data['mobility_score'] is not None else '—'}", class_="gbo-category-title"))
        for sub_name, sub_score in bucket_data["mobility_subgroup_scores"].items():
            metrics = bucket_data["mobility_subgroup_metrics"][sub_name]
            if not metrics:
                continue
            sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
            sections.append(build_metric_bars(metrics, f"{key_prefix}_mobility_{sub_name}", mode=mode))

    if bucket_data.get("shoulder_health_metrics"):
        sections.append(ui.p(f"Shoulder Health (reference only, not in Total) — {bucket_data['shoulder_health_score'] if bucket_data['shoulder_health_score'] is not None else '—'}", class_="gbo-category-title"))
        sections.append(build_metric_bars(bucket_data["shoulder_health_metrics"], f"{key_prefix}_shoulder_health", mode=mode))

    return ui.div(*sections)


def build_development_profile(bucket_data, key_prefix, mode="dark"):
    """Output vs. Capacity rings + a Balance bar. Returns None if
    there's not enough data to classify a profile yet (matches
    build_score_rings' same "show nothing" behavior)."""
    output_score = bucket_data.get("output_score")
    capacity_score = bucket_data.get("capacity_score")
    balance_pct = bucket_data.get("balance_pct")
    profile = bucket_data.get("development_profile")

    if output_score is None or capacity_score is None:
        return None

    c = theme.chart_colors(mode)
    sections = [ui.p(f"Development Profile: {profile or '—'}", class_="gbo-category-title")]
    rings = build_percentage_rings(
        [("Physical Output", output_score), ("Physical Capacity", capacity_score)],
        f"{key_prefix}_dev_profile", show_ordinal=True, mode=mode,
    )
    if rings is not None:
        sections.append(rings)

    if balance_pct is not None:
        # Horizontal balance bar: a fixed -50/+50 scale, a center
        # reference line at 0, and a marker at the athlete's actual
        # balance_pct, clamped to the display range.
        display_pct = max(-50, min(50, balance_pct))
        fig = go.Figure()
        fig.add_shape(type="line", x0=-50, x1=50, y0=0, y1=0, line=dict(color=c["track"], width=4))
        fig.add_shape(type="line", x0=0, x1=0, y0=-0.3, y1=0.3, line=dict(color=c["text"], width=2))
        fig.add_trace(go.Scatter(
            x=[display_pct], y=[0], mode="markers",
            marker=dict(size=22, color=c["crimson"], line=dict(color=c["text"], width=2)),
            showlegend=False, hoverinfo="skip",
        ))
        fig.update_layout(
            xaxis=dict(range=[-55, 55], visible=False, fixedrange=True),
            yaxis=dict(range=[-1, 1], visible=False, fixedrange=True),
            paper_bgcolor=c["surface"], plot_bgcolor=c["surface"],
            height=90, margin=dict(l=10, r=10, t=10, b=10),
            annotations=[
                dict(x=-50, y=-0.7, text="Capacity-Dominant", showarrow=False, font=dict(color=c["text"], size=12), xanchor="left"),
                dict(x=50, y=-0.7, text="Output-Dominant", showarrow=False, font=dict(color=c["text"], size=12), xanchor="right"),
            ],
        )
        sections.append(_fig_to_img(fig, width=700, height=90))
        sections.append(ui.p(
            f"Balance: {balance_pct:+.1f}% (provisional bands -- not a validated threshold yet)",
            class_="text-muted small",
        ))

    return ui.div(*sections)
