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
import force_plate_standards

BODY_COMP_BAR_NAMES = {name for name, _ in BODY_COMP_METRICS}

MOBILITY_ROM_REGION_ORDER = ["Shoulder", "Elbow", "Hip", "Other"]


def _mobility_rom_region(test_name):
    """Which region heading a compute_mobility_rom_report row displays
    under. Total Arc rows ("Throwing Arm Total Arc"/"Non-Throwing Arm
    Total Arc") don't start with "Shoulder:" like the rest of that
    region's raw fields do, but they're derived from Shoulder ER/IR so
    they belong grouped there too."""
    if test_name.startswith("Shoulder:") or "Total Arc" in test_name:
        return "Shoulder"
    if test_name.startswith("Elbow:"):
        return "Elbow"
    if test_name.startswith("Hip:"):
        return "Hip"
    return "Other"


def build_mobility_rom_report(report):
    """Mobility & ROM section -- red/yellow/green rows, NOT percentile
    bars (see MOBILITY_ROM_THRESHOLDS/compute_mobility_rom_report in
    bucket_system.py for why this bucket doesn't rank ROM against the
    team like every other one on this page). Each row shows the raw
    value plus a colored status pill: green "Clear" if comfortably
    above the configured minimum, yellow "Caution" if it clears the
    minimum but only within MOBILITY_ROM_YELLOW_BUFFER degrees, red
    "Below threshold" if it doesn't clear the minimum at all, gray "No
    threshold set" if that metric has no configured MOBILITY_ROM_
    THRESHOLDS entry yet (still shows the raw value, just no status --
    see that dict for which fields still need a real number before
    they can be flagged).

    Grouped by body region (Shoulder, Elbow, Hip) via MOBILITY_ROM_
    REGION_ORDER, matching MOBILITY_ROM_THRESHOLDS' own definition
    order -- Total Arc rows are grouped under Shoulder since they're
    derived from Shoulder ER/IR, not their own measurement. Returns
    None if the report is empty (no ROM data on file for this player
    yet), same "show nothing" rule the rest of this module uses."""
    if not report:
        return None
    by_region = {}
    for row in report:
        by_region.setdefault(_mobility_rom_region(row["test_name"]), []).append(row)

    sections = []
    for region in MOBILITY_ROM_REGION_ORDER:
        rows = by_region.get(region)
        if not rows:
            continue
        sections.append(ui.p(region, class_="gbo-subgroup-label"))
        row_els = []
        for row in rows:
            unit = row["unit"] or ""
            display_name = row["test_name"]
            prefix = f"{region}: "
            if display_name.startswith(prefix):
                display_name = display_name[len(prefix):]

            # Rows from compute_shoulder_rom_profile (Total Arc Deficit,
            # GIRD, ERG, Flexion/Extension Difference -- Ryker's Aug
            # 2026 ROM redesign spec) carry an "explanation"/
            # "recommendation" pair the plain absolute-threshold rows
            # above don't have -- that key's presence is the signal to
            # render this row with the spec's own status wording
            # ("Good"/"Monitor"/"Red Flag — Priority Review") instead of
            # the simpler existing "Clear"/"Caution"/"Below threshold"
            # pill. The explanation/recommendation prose itself is
            # deliberately not rendered (Ryker's call, Aug 2026) -- only
            # the raw value and status pill show.
            if "explanation" in row:
                # signed by default (these are almost all differences/deficits/gains, direction
                # matters) -- a row can opt out via "signed": False for a plain magnitude (e.g.
                # Hip Drive/Plant Total Rotation, which is never negative and doesn't need a "+").
                fmt = "{:+.1f}" if row.get("signed", True) else "{:.1f}"
                raw_label = f"{fmt.format(row['raw'])}{unit}"
                status = row["status"]
                if status is None:
                    status_label, status_class = "Reference only", "gbo-rom-status-none"
                else:
                    status_label, status_class = row["status_label"], f"gbo-rom-status-{status}"

                row_els.append(ui.div(
                    ui.span(display_name, class_="gbo-rom-name"),
                    ui.span(raw_label, class_="gbo-rom-raw"),
                    ui.span(status_label, class_=f"gbo-rom-status {status_class}"),
                    class_="gbo-rom-row",
                ))
                continue

            raw_label = f"{row['raw']:.1f}{unit}"
            status = row["status"]
            if status is None:
                status_label, status_class = "No threshold set", "gbo-rom-status-none"
            else:
                threshold_label = f" (min {row['threshold']:.0f}{unit})"
                if status == "green":
                    status_label, status_class = f"Clear{threshold_label}", "gbo-rom-status-green"
                elif status == "yellow":
                    status_label, status_class = f"Caution{threshold_label}", "gbo-rom-status-yellow"
                else:
                    status_label, status_class = f"Below threshold{threshold_label}", "gbo-rom-status-red"

            row_els.append(ui.div(
                ui.span(display_name, class_="gbo-rom-name"),
                ui.span(raw_label, class_="gbo-rom-raw"),
                ui.span(status_label, class_=f"gbo-rom-status {status_class}"),
                class_="gbo-rom-row",
            ))
        sections.append(ui.div(*row_els, class_="gbo-rom-group"))
    return ui.div(*sections)


_ROM_STATUS_SEVERITY = {"red": 2, "yellow": 1, "green": 0}

_MOVEMENT_FLAG_WORD = {"red": "RED", "orange": "ORANGE", "yellow": "YELLOW", "green": "GREEN"}


def build_movement_flag_ring(movement_flag, mobility_rom_report, key_prefix, mode="dark"):
    """Single merged Mobility & ROM ring -- one ring, colored/worded by
    Movement Flag (green/yellow/orange/red, see compute_movement_flag
    in bucket_system.py), with the 1-5 score shown inside it and a
    plain-English breakdown underneath.

    Originally this was two separate widgets: a ROM-report-only status
    ring (3 colors, no injury awareness) sitting next to a Movement
    Flag pill (4 colors, injury-aware). They could show conflicting
    reads -- e.g. a player with a current injury on file but a clean
    ROM report showed a green ring next to a red pill -- and even when
    they agreed, "2 Areas Need Attention" next to "1 ROM deficit" read
    as a contradiction rather than two views of the same data. Ryker's
    call (Aug 2026): collapse to one ring so there's a single answer
    at a glance, with Movement Flag as the source of truth for color
    (it's the one that accounts for the injury override) and the ROM
    report feeding the explanatory caption underneath.

    Returns None if there's nothing to show (movement_flag is None --
    compute_movement_flag already returns None when there's no ROM
    data at all and no injury on file)."""
    if movement_flag is None:
        return None
    color = movement_flag["color"]
    word = _MOVEMENT_FLAG_WORD[color]

    statused = [row for row in mobility_rom_report if row.get("status") in _ROM_STATUS_SEVERITY]
    yellow_count = sum(1 for row in statused if row["status"] == "yellow")
    red_count = sum(1 for row in statused if row["status"] == "red")

    ring = ui.div(
        ui.div(
            ui.span(word, class_="gbo-ring-value"),
            ui.span(f"Score: {movement_flag['score']}", class_="gbo-ring-sublabel"),
            class_="gbo-ring-inner",
        ),
        class_=f"gbo-ring gbo-ring--{color}",
    )
    children = [
        ring,
        ui.p(ui.strong(f"Movement Flag: {word}"), class_="gbo-ring-label"),
    ]

    # Explain the score: the ROM report's Caution count (Movement Flag's
    # own reason line below never mentions cautions, only true deficits)
    # plus that reason line itself, which already covers "N ROM
    # deficits", the "Poor Mover" suffix, and the injury note in the
    # injury-override case -- so together these two lines spell out
    # exactly what's driving the color without repeating each other.
    if yellow_count:
        children.append(ui.p(f"{yellow_count} Caution" + ("s" if yellow_count != 1 else ""), class_="text-muted small"))
    children.append(ui.p(movement_flag["reason"], class_="text-muted small"))

    return ui.div(*children, class_="gbo-ring-col")


def build_percentage_rings(metrics, key_prefix, show_ordinal=False, mode="dark", status_fn=None):
    """Generic full-circle percentage ring display -- metrics is a list
    of (label, value) tuples, value 0-100 or None. show_ordinal=True
    displays just the plain rounded number ("45") centered in the ring
    with the label underneath (percentile-style data); False (the
    default) shows a plain percentage ("45%") with the label as the
    in-ring sub-label (direct-percentage KPIs). Returns None (renders
    nothing) if every value is None -- same "show nothing" rule as the
    original's False return.

    status_fn: optional callable(label, value) -> a CSS class name (any
    of "good"/"watch"/"flag"/"gold"/"diamond"/"silver"/"bronze"/
    "common") or None, applied as a class on the ring so it tints
    accordingly instead of the flat default green every ring used to
    render (.gbo-ring's base --gbo-ring-color, see theme.py). None (the
    default) keeps that old always-green look -- only callers that
    pass status_fn opt into coloring, so this stays a no-op everywhere
    that hasn't asked for it (Aug 2026, Ryker: added for build_score_
    rings' composite scores; see _score_ring_status/_composite_score_
    status/_tier_for_total below).

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
        status = status_fn(label, value) if status_fn else None
        ring = ui.div(
            ui.div(*inner_children, class_="gbo-ring-inner"),
            class_=f"gbo-ring {status}" if status else "gbo-ring",
            style=f"--gbo-ring-pct: {pct};",
        )
        children = [ring]
        if show_ordinal:
            children.append(ui.p(ui.strong(label), class_="gbo-ring-label"))
        cols.append(ui.div(*children, class_="gbo-ring-col"))

    return ui.layout_columns(*cols, col_widths=[col_width] * len(cols))


def _composite_score_status(value):
    """Color rule for build_score_rings' Body Comp/Power/Strength rings
    -- NOT the app-wide status_from_percentile 35/60 split used for
    individual metric percentiles elsewhere (ui_helpers.status_from_
    percentile), and NOT the Total ring, which uses _tier_for_total
    instead (Ryker's call, Aug 2026, split from an earlier version that
    used this same rule for Total too). Ryker's call (Aug 2026): the
    roster's composite scores cluster tightly (e.g. nobody under 60),
    so the 35/60 split rendered everyone green/gold and didn't
    actually separate anyone -- these cut points are tuned to that
    real spread instead: below 80 flag (red), 80-84 watch (yellow),
    85+ good (green). Revisit if the roster's score distribution
    shifts."""
    if value is None:
        return None
    if value >= 85:
        return "good"
    if value >= 80:
        return "watch"
    return "flag"


def _individual_metric_status(pct):
    """Color rule for build_metric_bars' individual metric bars (Body
    Comp/Power/Strength/Speed rows in the Physical Testing Breakdown)
    -- a separate, stricter cut than _composite_score_status' 80/85
    (which is itself already stricter than the app-wide status_from_
    percentile 35/60 default -- see that function's docstring for why
    35/60 doesn't work on this roster). Ryker's call (Sept 1 2026),
    reported after noticing every one of these bars rendered green
    regardless of percentile -- turned out to be two separate things:
    build_metric_bars never applied ANY status class before this (pure
    bug, independent of where the cutoff sits -- the CSS's base
    .gbo-metric-bar-fill rule defaults to green), and on top of that
    the percentile itself (value vs. team leader, not a true rank)
    clusters high the same way composite scores do. 90+ good, 80-89
    watch, <80 flag; no percentile data yet stays neutral (muted gray,
    same class score_ring/metric_bar already use for "not scored" --
    missing data isn't the same claim as "performed poorly", so it
    shouldn't render as a flag). Revisit alongside _composite_score_
    status if the roster's spread changes."""
    if pct is None:
        return "neutral"
    if pct >= 90:
        return "good"
    if pct >= 80:
        return "watch"
    return "flag"


def _tier_for_total(value):
    """Total ring color = the same Diamond/Gold/Silver/Bronze/Common
    tiers as the player card's Overall rating (show_card in ui_helpers.
    py) -- Ryker's call (Aug 2026): Total should read as the identical
    tier everywhere it appears, not a separate red/yellow/green scale
    just for this one ring. Keep these cut points in sync with
    show_card's tier= line if either one changes."""
    if value is None:
        return None
    if value >= 90:
        return "diamond"
    if value >= 85:
        return "gold"
    if value >= 80:
        return "silver"
    if value >= 75:
        return "bronze"
    return "common"


def _score_ring_status(label, value):
    """build_score_rings' status_fn -- Total gets the player-card tier
    scale (_tier_for_total), Body Comp/Power/Strength keep the red/
    yellow/green scale (_composite_score_status). See each function's
    docstring."""
    return _tier_for_total(value) if label == "Total" else _composite_score_status(value)


def build_score_rings(bucket_data, key_prefix, mode="dark"):
    """Total/Body Comp/Power/Strength as full-circle percentage rings.
    Returns None (renders nothing) if there's no data yet for any of
    them. Colored via _score_ring_status: Total uses the player card's
    Diamond/Gold/Silver/Bronze/Common tiers, the other three use red/
    yellow/green (see _tier_for_total / _composite_score_status)."""
    specs = [
        ("Total", bucket_data["total_score"]),
        ("Body Comp", bucket_data["body_comp_score"]),
        ("Power", bucket_data["power_score"]),
        ("Strength", bucket_data["strength_score"]),
    ]
    return build_percentage_rings(specs, key_prefix, show_ordinal=True, mode=mode, status_fn=_score_ring_status)


def ordinal(n):
    """11/12/13 stay "th" even though they end in 1/2/3 (11th, 12th,
    13th, not 11st/12nd/13rd) -- the usual English ordinal-suffix
    exception. Public (Aug 2026 -- was _ordinal, private/internal to
    this module only): player_profile.py's own percentile captions
    (Development priorities, Overview tab's "Lowest" line and metric
    bars) were still hardcoding "{pct:.0f}th" everywhere, reading as
    "72th"/"71th" instead of "72nd"/"71st" -- Ryker's call to fix.
    Rather than a second copy of this logic there, this one function is
    now the single source of truth every percentile caption in the app
    goes through."""
    n = int(round(n))
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def build_metric_bars(metrics_dict, chart_key, mode="dark", is_pitcher=None):
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
    re-render.

    is_pitcher: when not None, each row is also checked against
    force_plate_standards.FORCE_PLATE_STANDARDS -- a metric covered
    there (currently just mRSI and the multi-rebound Avg RSI) gets a
    small tier badge appended to its header (e.g. "MLB tier: Good").
    Purely additive/display-only -- doesn't touch the percentile bar
    or this function's "no data" behavior. Left None by any caller
    that doesn't know the player's position (or is rendering a
    section, like Body Comp, where neither covered metric ever
    appears), which just means no badges render -- same as today."""
    if not metrics_dict:
        return ui.p("No data yet.", class_="text-muted small")

    rows = []
    for name, d in metrics_dict.items():
        raw_percentile = d["percentile"]
        pct = raw_percentile if raw_percentile is not None else 0
        pct = max(0, min(100, pct))
        raw_label = f"{d['raw']:.2f}{d['unit'] or ''}"
        percentile_label = f"{ordinal(raw_percentile)} percentile" if raw_percentile is not None else "No percentile data"
        header_children = [
            ui.span(name, class_="gbo-metric-bar-name"),
            ui.span(raw_label, class_="gbo-metric-bar-raw"),
        ]
        tier = force_plate_standards.classify(name, d["raw"], is_pitcher) if is_pitcher is not None else None
        if tier is not None:
            header_children.append(ui.span(
                f"{tier['badge_source']} tier: {tier['tier_label']}",
                class_=f"gbo-tier-badge {tier['status']}",
            ))
        status = _individual_metric_status(raw_percentile)
        rows.append(ui.div(
            ui.div(*header_children, class_="gbo-metric-bar-header"),
            ui.div(
                ui.div(class_=f"gbo-metric-bar-fill {status}", style=f"width: {pct}%;"),
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
    is_pitcher = bucket_data.get("is_pitcher")  # None for any pre-Aug-2026 caller's bucket_data that predates this key -- build_metric_bars treats None as "skip badges", same as before this feature existed
    sections = [ui.p(f"Body Comp — {bucket_data['body_comp_score'] if bucket_data['body_comp_score'] is not None else '—'}", class_="gbo-category-title")]
    body_comp_metrics = bucket_data["body_comp_metrics"]
    bar_metrics = {name: v for name, v in body_comp_metrics.items() if name in BODY_COMP_BAR_NAMES}
    raw_only_metrics = {name: v for name, v in body_comp_metrics.items() if name not in BODY_COMP_BAR_NAMES}
    sections.append(build_metric_bars(bar_metrics, f"{key_prefix}_body_comp", mode=mode, is_pitcher=is_pitcher))
    raw_ui = build_raw_metrics(raw_only_metrics)
    if raw_ui is not None:
        sections.append(raw_ui)

    sections.append(ui.p(f"Power — {bucket_data['power_score'] if bucket_data['power_score'] is not None else '—'}", class_="gbo-category-title"))
    for sub_name, sub_score in bucket_data["power_subgroup_scores"].items():
        metrics = bucket_data["power_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
        sections.append(build_metric_bars(metrics, f"{key_prefix}_power_{sub_name}", mode=mode, is_pitcher=is_pitcher))

    sections.append(ui.p(f"Strength — {bucket_data['strength_score'] if bucket_data['strength_score'] is not None else '—'}", class_="gbo-category-title"))
    for sub_name, sub_score in bucket_data["strength_subgroup_scores"].items():
        metrics = bucket_data["strength_subgroup_metrics"][sub_name]
        if not metrics:
            continue
        sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
        sections.append(build_metric_bars(metrics, f"{key_prefix}_strength_{sub_name}", mode=mode, is_pitcher=is_pitcher))

    if bucket_data["speed_metrics"]:
        sections.append(ui.p(f"Speed (reference only, not in Total) — {bucket_data['speed_score'] if bucket_data['speed_score'] is not None else '—'}", class_="gbo-category-title"))
        sections.append(build_metric_bars(bucket_data["speed_metrics"], f"{key_prefix}_speed", mode=mode, is_pitcher=is_pitcher))

    capacity_metrics_present = any(bucket_data.get("capacity_subgroup_metrics", {}).values())
    if capacity_metrics_present:
        sections.append(ui.p(f"Capacity (reference only, not in Total) — {bucket_data['capacity_score'] if bucket_data['capacity_score'] is not None else '—'}", class_="gbo-category-title"))
        for sub_name, sub_score in bucket_data["capacity_subgroup_scores"].items():
            metrics = bucket_data["capacity_subgroup_metrics"][sub_name]
            if not metrics:
                continue
            sections.append(ui.p(f"{sub_name} — {sub_score if sub_score is not None else '—'}", class_="gbo-subgroup-label"))
            sections.append(build_metric_bars(metrics, f"{key_prefix}_capacity_{sub_name}", mode=mode, is_pitcher=is_pitcher))

    mobility_rom_report = bucket_data.get("mobility_rom_report", [])
    mobility_rom_ui = build_mobility_rom_report(mobility_rom_report)
    movement_ring = build_movement_flag_ring(
        bucket_data.get("movement_flag"), mobility_rom_report, f"{key_prefix}_movement_flag", mode=mode
    )
    # A player can have a current_injury flag on file before ever having
    # real ROM data entered -- compute_movement_flag's injury override
    # applies independent of the ROM report, so the header/ring show
    # whenever EITHER has something to say, not gated on ROM rows
    # existing (mirrors the earlier "No physical testing data yet." fix's
    # same lesson: don't gate one section on another unrelated section's
    # data).
    if movement_ring is not None or mobility_rom_ui is not None:
        sections.append(ui.p("Mobility & ROM (reference only, not in Total)", class_="gbo-category-title"))
        if movement_ring is not None:
            sections.append(movement_ring)
        if mobility_rom_ui is not None:
            sections.append(mobility_rom_ui)

    if bucket_data.get("shoulder_health_metrics"):
        sections.append(ui.p(f"Shoulder Health (reference only, not in Total) — {bucket_data['shoulder_health_score'] if bucket_data['shoulder_health_score'] is not None else '—'}", class_="gbo-category-title"))
        sections.append(build_metric_bars(bucket_data["shoulder_health_metrics"], f"{key_prefix}_shoulder_health", mode=mode, is_pitcher=is_pitcher))

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