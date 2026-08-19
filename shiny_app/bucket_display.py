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

Deliberately never says "Bucket System" anywhere in the UI, same as the
original -- Ryker's explicit call. Always labeled "Physical Testing".

Every element on this page -- rings, metric bars, the development-
profile balance bar -- used to be a Plotly figure rendered server-side
to a static PNG via kaleido (fig.to_image()), one real image render
per element per page load. That was fine for interactivity (everything
here is decorative -- hoverinfo="skip"/"none" throughout, no
on_select/click handling anywhere), but kaleido has real per-image CPU
cost, and a single player's Physical Testing Breakdown could add up to
15-20+ of these on one load -- the direct cause of both "assessments
takes forever to load" and (via the same pattern in
bullpen_dashboard_display.py) the Bullpen Dashboard pitcher-switch
disconnect. Every element here is now plain HTML/CSS instead (see the
.gbo-ring-*/.gbo-metric-bar-*/.gbo-balance-* classes in theme.py's
GLOBAL_CSS) -- zero image renders, and as a bonus these now track the
live dark/light toggle automatically instead of needing mode=
threaded through from a server-side render. mode= stays on every
build_* signature below purely for call-site compatibility (nothing
here calls it anymore) so callers didn't need to change.
"""

from shiny import ui

from bucket_system import BODY_COMP_METRICS

BODY_COMP_BAR_NAMES = {name for name, _ in BODY_COMP_METRICS}


def build_percentage_rings(metrics, key_prefix, show_ordinal=False, mode="dark"):
    """Generic full-circle percentage ring display -- metrics is a list
    of (label, value) tuples, value 0-100 or None. show_ordinal=True
    displays just the plain rounded number ("45") centered in the ring
    with the label underneath (percentile-style data); False (the
    default) shows a plain percentage ("45%") with the label as the
    in-ring sub-label (direct-percentage KPIs). Returns None (renders
    nothing) if every value is None -- same "show nothing" rule as the
    original's False return.

    Each ring is a CSS conic-gradient circle (.gbo-ring in GLOBAL_CSS)
    -- var(--gbo-ring-pct) set inline per ring drives how much of the
    circle is filled -- with a same-color inner circle punched out
    (.gbo-ring-inner) to fake the donut hole a Plotly go.Pie(hole=0.72)
    used to give. No chart image involved."""
    has_any_data = any(v is not None for _, v in metrics)
    if not has_any_data:
        return None

    col_width = max(1, 12 // len(metrics))
    cols = []
    for label, value in metrics:
        if value is None:
            cols.append(ui.div(ui.p(ui.strong(label)), ui.p("No data yet", class_="text-muted small")))
            continue

        pct = max(0, min(100, value))
        if show_ordinal:
            inner_children = [ui.span(f"{round(value)}", class_="gbo-ring-value")]
        else:
            inner_children = [
                ui.span(f"{value:.0f}%", class_="gbo-ring-value"),
                ui.span(label, class_="gbo-ring-sublabel"),
            ]
        ring = ui.div(
            ui.div(*inner_children, class_="gbo-ring-inner"),
            class_="gbo-ring",
            style=f"--gbo-ring-pct: {pct};",
        )
        children = [ring]
        if show_ordinal:
            children.append(ui.p(ui.strong(label), class_="gbo-ring-label"))
        cols.append(ui.div(*children, class_="gbo-ring-col"))

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


def _ordinal(n):
    """11/12/13 stay "th" even though they end in 1/2/3 (11th, 12th,
    13th, not 11st/12nd/13rd) -- the usual English ordinal-suffix
    exception."""
    n = int(round(n))
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_metric_bars(metrics_dict, chart_key, mode="dark"):
    """One row per metric: name + raw value on a line, a thin colored
    progress bar underneath sized to the percentile (0-100), with the
    percentile itself labeled below the bar. Always returns something
    (a "no data" caption if metrics_dict is empty), matching the
    original's unconditional render.

    Rebuilt from a Plotly horizontal-bar-chart-rendered-as-an-image
    (see git history) to plain HTML/CSS -- Ryker's call, both because
    the old chart read as too visually "bulky" (70px-tall bar rows,
    wide chart margins) and because each one was a real kaleido image
    render on every player switch, the same per-image CPU cost that
    made Bullpen Dashboard disconnect on a pitcher switch. A page's
    full Physical Testing Breakdown can have a dozen-plus of these
    (one per sub-group) -- cutting all of them from "render a chart
    image" to "size a <div>" removes that many kaleido renders per
    page load, on top of looking slimmer. mode= is accepted for
    call-site compatibility with every other build_* function here,
    but isn't otherwise used -- unlike the rings/balance bar, these
    bars are real CSS (styled via GLOBAL_CSS's --gbo-* custom
    properties, see theme.py), so they already track the live
    dark/light toggle for free instead of needing a server-side
    re-render."""
    if not metrics_dict:
        return ui.p("No data yet.", class_="text-muted small")

    rows = []
    for name, d in metrics_dict.items():
        raw_percentile = d["percentile"]
        pct = raw_percentile if raw_percentile is not None else 0
        pct = max(0, min(100, pct))
        raw_label = f"{d['raw']:.2f}{d['unit'] or ''}"
        percentile_label = f"{_ordinal(raw_percentile)} percentile" if raw_percentile is not None else "No percentile data"
        rows.append(ui.div(
            ui.div(
                ui.span(name, class_="gbo-metric-bar-name"),
                ui.span(raw_label, class_="gbo-metric-bar-raw"),
                class_="gbo-metric-bar-header",
            ),
            ui.div(
                ui.div(class_="gbo-metric-bar-fill", style=f"width: {pct}%;"),
                class_="gbo-metric-bar-track",
            ),
            ui.p(percentile_label, class_="gbo-metric-bar-percentile"),
            class_="gbo-metric-bar-row",
        ))
    return ui.div(*rows, class_="gbo-metric-bar-group")


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
        # balance_pct, clamped to the display range. Plain CSS now
        # (.gbo-balance-* in GLOBAL_CSS) -- the marker's left% is just
        # display_pct remapped from a -50..50 range onto 0..100%.
        display_pct = max(-50, min(50, balance_pct))
        marker_left = display_pct + 50
        sections.append(ui.div(
            ui.div(class_="gbo-balance-track"),
            ui.div(class_="gbo-balance-center"),
            ui.div(class_="gbo-balance-marker", style=f"left: {marker_left}%;"),
            class_="gbo-balance-bar",
        ))
        sections.append(ui.div(
            ui.span("Capacity-Dominant"),
            ui.span("Output-Dominant"),
            class_="gbo-balance-labels",
        ))
        sections.append(ui.p(
            f"Balance: {balance_pct:+.1f}% (provisional bands -- not a validated threshold yet)",
            class_="text-muted small",
        ))

    return ui.div(*sections)