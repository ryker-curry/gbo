"""
GBO -- Shared UI components for consistent visual style across all
pages (KPI cards, profile headers, page header/footer, empty state).

Shiny port of the repo root's ui_components.py (the Streamlit version).
Unlike that version, this file does NOT inject a <style> block per
component call -- every class referenced here (.gbo-kpi-card,
.gbo-profile-card, etc.) is defined exactly once in theme.py's
GLOBAL_CSS, included a single time in the outer page shell
(shiny_app/app.py). See theme.py's module docstring for the full
styling rationale (the "Bold Athletic" direction, and why crimson is
never used as small body text in dark mode -- .gbo-kpi-accent below
gets a cream-plus-glow treatment there instead, and literal crimson in
light mode, via the --gbo-accent-ink token).
"""

from shiny import ui

import theme


def page_header(title: str, subtitle: str = None, actions=None):
    """Page title block (display face, uppercase). Optional subtitle
    line and a right-aligned actions slot (buttons) -- see
    GBO-DESIGN-SYSTEM.md section 5. Old one-arg calls keep working."""
    left = [ui.div(title, class_="gbo-page-header")]
    if subtitle:
        left.append(ui.div(subtitle, class_="gbo-page-sub"))
    children = [ui.div(*left)]
    if actions:
        children.append(ui.div(*(actions if isinstance(actions, (list, tuple)) else [actions]), class_="gbo-page-actions"))
    return ui.div(*children, class_="gbo-page-head")


def page_footer():
    """Small consistent wordmark at the bottom of every page."""
    return ui.div("Gorilla Baseball Operations", class_="gbo-footer")


def empty_state(message: str, icon: str = ""):
    """Friendlier empty-state message, used in place of a plain info box
    when a list/table has nothing to show yet. No emoji/icon by
    default, per the no-emojis rule -- pass icon= only with a plain
    text/symbol if a specific caller genuinely needs one."""
    children = []
    if icon:
        children.append(ui.div(icon, class_="icon"))
    children.append(message)
    return ui.div(*children, class_="gbo-empty-state")


# ---------------------------------------------------------------------
# v2 design-system components (GBO-DESIGN-SYSTEM.md section 6)
# ---------------------------------------------------------------------

STATUS_GOOD, STATUS_WATCH, STATUS_FLAG, STATUS_NEUTRAL = "good", "watch", "flag", "neutral"
_STATUS_LABEL = {"good": "Good", "watch": "Attention", "flag": "Priority", "neutral": "—", "gold": "Elite"}


def status_from_percentile(pct):
    """Default status rule (design doc section 7): >=60 good, 35-59
    attention, <35 priority, None -> neutral. Callers with a
    threshold-based rule (ROM) map their own red/yellow/green instead."""
    if pct is None:
        return STATUS_NEUTRAL
    if pct >= 60:
        return STATUS_GOOD
    if pct >= 35:
        return STATUS_WATCH
    return STATUS_FLAG


def status_from_color_word(word):
    """Maps the bucket system's 'green'/'yellow'/'orange'/'red' words
    onto the three design-system statuses."""
    return {"green": STATUS_GOOD, "yellow": STATUS_WATCH, "orange": STATUS_FLAG, "red": STATUS_FLAG}.get((word or "").lower(), STATUS_NEUTRAL)


def status_chip(status: str, label: str = None):
    """Pill with a dot + text label. status: good|watch|flag|neutral|gold|crimson."""
    return ui.span(label or _STATUS_LABEL.get(status, status), class_=f"gbo-chip gbo-chip-{status}")


def pill(text: str):
    return ui.span(text, class_="gbo-pill")


def card(*children, title: str = None, right=None, small: bool = False, class_: str = ""):
    """Quiet surface card with an optional header row (title left,
    anything -- text or a link -- right)."""
    head = None
    if title is not None or right is not None:
        head = ui.div(ui.h3(title or ""), ui.div(right, class_="right") if right is not None else None, class_="gbo-card-head")
    return ui.div(head, *children, class_=f"gbo-card {'sm' if small else ''} {class_}".strip())


def section_title(title: str, right=None):
    """In-page section heading with an optional right-aligned caption."""
    return ui.div(ui.div(title, class_="gbo-section-title"), ui.div(right, class_="right") if right is not None else None, class_="gbo-section-title-row")


def metric_bar(name: str, value_text: str, pct, status: str = None, percentile_text: str = None, unit: str = None):
    """One metric row: name left, value right, status-colored 6px
    track, optional caption. pct is the fill 0-100 (None -> 0)."""
    st = status or status_from_percentile(pct)
    width = max(0, min(100, float(pct or 0)))
    raw = [value_text]
    if unit:
        raw.append(ui.span(unit, class_="unit"))
    return ui.div(
        ui.div(ui.span(name, class_="gbo-metric-bar-name"), ui.span(*raw, class_="gbo-metric-bar-raw"), class_="gbo-metric-bar-header"),
        ui.div(ui.div(class_=f"gbo-metric-bar-fill {st}", style=f"width:{width:.0f}%"), class_="gbo-metric-bar-track"),
        ui.div(percentile_text, class_="gbo-metric-bar-percentile") if percentile_text else None,
        class_="gbo-metric-bar-row",
    )


def score_ring(value, label: str, status: str = None, sublabel: str = None, size_px: int = 96):
    """Conic-gradient score ring, 0-100, colored by status (gold at
    >=90 by default)."""
    pct = max(0, min(100, float(value or 0)))
    st = status or ("gold" if pct >= 90 else status_from_percentile(pct))
    return ui.div(
        ui.div(
            ui.div(ui.div(f"{pct:.0f}", class_="gbo-ring-value"), ui.div(sublabel, class_="gbo-ring-sublabel") if sublabel else None, class_="gbo-ring-inner"),
            class_=f"gbo-ring {st}", style=f"--gbo-ring-pct:{pct:.0f}; width:{size_px}px; height:{size_px}px;",
        ),
        ui.div(label, class_="gbo-ring-label"),
        class_="gbo-ring-col",
    )


def kpi_tile(label: str, value, unit: str = None, delta: str = None, delta_positive=None, status: str = None):
    """Single KPI tile. delta_positive: True (green), False (red), None (muted)."""
    val = [ui.span(value if not isinstance(value, (int, float, str)) else str(value), class_="gbo-kpi-accent")]
    if unit:
        val.append(ui.tags.small(unit))
    parts = [ui.div(label, class_="gbo-kpi-label"), ui.div(*val, class_="gbo-kpi-value")]
    if delta:
        arrow = "▲ " if delta_positive is True else "▼ " if delta_positive is False else "— "
        cls = "positive" if delta_positive is True else "negative" if delta_positive is False else ""
        parts.append(ui.div(arrow + delta, class_=f"gbo-kpi-delta {cls}"))
    return ui.div(*parts, class_=f"gbo-kpi-card {status or ''}".strip())


def bucket_card(title: str, score, status: str, why, right=None):
    """Collapsed bucket summary row: score, title + one-line why, chip."""
    sc = "gold" if (score is not None and float(score) >= 90) else status
    return ui.div(
        ui.div(f"{float(score):.0f}" if score is not None else "—", class_=f"gbo-bucket-score {sc}"),
        ui.div(ui.div(title, class_="gbo-bucket-title"), ui.div(why, class_="gbo-bucket-why") if why else None),
        right if right is not None else status_chip(status),
        class_="gbo-bucket",
    )


def render_staff_profile_header(first_name: str, last_name: str, role_name: str, show_logo: bool = True, photo_url: str = None):
    """Same profile-card style as render_player_profile_header, for
    staff dashboards -- role name in place of jersey/position/class.

    The original Streamlit version base64-encoded the logo file on every
    call (st.markdown(unsafe_allow_html) needs a data URI, no static
    file serving). Shiny doesn't have that constraint -- app.py mounts
    assets/ as a real static route (theme.ASSETS_DIR), so this just
    points an <img> at theme.LOGO_URL instead."""
    children = []
    if photo_url:
        children.append(ui.tags.img(src=photo_url, class_="gbo-profile-photo"))
    children.append(
        ui.div(
            ui.p(f"{first_name} {last_name}", class_="gbo-profile-name"),
            ui.div(role_name, class_="gbo-profile-subtitle"),
        )
    )
    if show_logo:
        children.append(ui.tags.img(src=theme.LOGO_URL, class_="gbo-profile-logo", alt="GBO"))
    return ui.div(*children, class_="gbo-profile-card")


def render_player_profile_header(player, show_logo: bool = True):
    """A card-style player profile header for the Player dashboard --
    name, crimson accent stripe, jersey/position/class, optional photo
    and GBO logo watermark (see render_staff_profile_header's docstring
    for why this is a static asset src now instead of base64)."""
    position_label = player.player_position.position_name if player.player_position else ""
    class_label = player.player_class.class_name if player.player_class else ""
    jersey_label = f"#{player.jersey_number}" if player.jersey_number else ""
    subtitle_parts = [p for p in [jersey_label, position_label, class_label] if p]
    subtitle = " · ".join(subtitle_parts)

    children = []
    if player.photo_url:
        children.append(ui.tags.img(src=player.photo_url, class_="gbo-profile-photo"))
    children.append(
        ui.div(
            ui.p(f"{player.first_name} {player.last_name}", class_="gbo-profile-name"),
            ui.div(subtitle, class_="gbo-profile-subtitle"),
        )
    )
    if show_logo:
        children.append(ui.tags.img(src=theme.LOGO_URL, class_="gbo-profile-logo", alt="GBO"))
    return ui.div(*children, class_="gbo-profile-card")


def render_dict_table(rows: list, empty_message: str = None):
    """Shiny equivalent of the original's very common
    st.dataframe(list_of_dicts, use_container_width=True, hide_index=True)
    pattern (dozens of call sites across the app -- dashboard, players,
    assessments, idp, and nearly every other page). Columns are the
    union of every row's keys, in first-seen order, same as
    player_stats.py's/player_schedule.py's hand-built table helpers
    (pandas' auto-union behavior, made explicit since a plain HTML
    table has no equivalent auto-fill).

    Returns empty_state(empty_message) if rows is empty and a message
    was given, otherwise a styled <table>. Every cell value is passed
    through ui.tags.td() as plain text, so it's auto-escaped the same
    way every other value in this app is -- callers should pre-format
    (dates, rounding, "—" for None) before building the row dicts, same
    as every other table-building call site in this codebase.
    """
    if not rows:
        if empty_message:
            return empty_state(empty_message)
        return None

    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    header = ui.tags.tr(*[ui.tags.th(c) for c in columns])
    body_rows = [ui.tags.tr(*[ui.tags.td(row.get(c, "—")) for c in columns]) for row in rows]
    return ui.tags.table(ui.tags.thead(header), ui.tags.tbody(*body_rows), class_="table table-sm")


def render_kpi_cards(cards: list):
    """Render a row of bordered, gradient-backed KPI cards. The value is
    wrapped in a .gbo-kpi-accent span -- theme.py gives it a
    cream-plus-crimson-glow look in dark mode and literal crimson in
    light mode (crimson text alone fails contrast on the dark card
    surface -- see theme.py's module docstring), so it reads as the
    "bold" accent color in both modes without ever failing contrast.
    Optional trend delta with an up/down arrow (green = positive,
    red = negative).

    Each card dict: {"label": str, "value": str, "delta": str | None,
    "delta_positive": bool} -- delta and delta_positive are optional.
    """
    card_divs = []
    for c in cards:
        value_children = [ui.span(c["value"], class_="gbo-kpi-accent")]
        parts = [
            ui.div(c["label"], class_="gbo-kpi-label"),
            ui.div(*value_children, class_="gbo-kpi-value"),
        ]
        if c.get("delta"):
            arrow = "▲" if c.get("delta_positive", True) else "▼"
            css_class = "positive" if c.get("delta_positive", True) else "negative"
            parts.append(ui.div(f"{arrow} {c['delta']}", class_=f"gbo-kpi-delta {css_class}"))
        card_divs.append(ui.div(*parts, class_="gbo-kpi-card"))

    return ui.div(*card_divs, class_="gbo-kpi-row")


def remove_selected_grid_rows(rows: list, selected_records: list) -> list:
    """Removes rows matching selected_records (by exact dict equality)
    from `rows`, consuming one match per selected record so duplicate
    rows are handled correctly -- removes exactly as many rows as were
    selected, not every row that happens to match a selected row's
    content (which matters here since several blank/identical scratch
    rows are common in these grids).

    Part of the Task #11 "editable grid" pattern used by
    opponent_teams.py, bullpen_scripts.py, and training_routines.py:
    Shiny's render.data_frame widget (as of shiny 1.7) has no built-in
    per-row delete affordance or "add a blank row" button the way
    Streamlit's st.data_editor(num_rows="dynamic") does, so those pages
    hold their working rows in a plain Python list (a module-local
    reactive.Value), rebuild a pandas DataFrame from it on every
    render, and implement "+Add row(s)"/"Remove selected"/"Save" as
    ordinary buttons: Add appends blank dict(s) to the list; Remove
    reads <grid>.data_view(selected=True) and calls this function;
    Save reads <grid>.data_view() (the full current data, patches
    included) and persists it. Row selection (and therefore "remove")
    is enabled via DataGrid(..., selection_mode="rows")."""
    remaining = list(rows)
    for rec in selected_records:
        for i, row in enumerate(remaining):
            if row == rec:
                del remaining[i]
                break
    return remaining


def show_card(player, bucket_data, pitch_summary=None, flag="neutral"):
    """MLB-The-Show-style player card (design doc section 8). Reads
    only what the bucket system already computes:
      Overall  = total_score
      BODY/PWR/STR/SPD/ARM = bucket scores (percentile-based, 0-100)
      ROM      = share of Mobility & ROM rows that are green (0-100)
      Pitchers also get VELO/SPIN from the latest Rapsodo session
      (shown as the raw mph/rpm, bar scaled 70-100 mph / 1500-2800 rpm).
    Tier by overall: 90+ gold, 80-89 crimson, 70-79 silver, else slate.
    Positions never get pitching rows; nothing is invented when data is
    missing -- the row shows a dash."""
    bd = bucket_data or {}
    overall = bd.get("total_score")
    tier = "gold" if (overall or 0) >= 90 else "crimson" if (overall or 0) >= 80 else "silver" if (overall or 0) >= 70 else "slate"
    tier_color = {"gold": "var(--gbo-gold)", "crimson": "var(--gbo-crimson)", "silver": "var(--gbo-silver)", "slate": "var(--gbo-text-muted)"}[tier]
    rom = bd.get("mobility_rom_report") or []
    statused = [r for r in rom if r.get("status") in ("red", "yellow", "green")]
    rom_score = round(100 * sum(1 for r in statused if r["status"] == "green") / len(statused)) if statused else None

    def bar(label, value, display=None, lo=0, hi=100, status=None):
        if value is None:
            return ui.div(ui.span(label, class_="l"), ui.div(ui.div(class_="neutral", style="width:0"), class_="b"), ui.span("—", class_="v"), class_="gbo-at")
        pct = max(0, min(100, (float(value) - lo) / (hi - lo) * 100))
        st = status or ("gold" if pct >= 90 else status_from_percentile(pct))
        return ui.div(ui.span(label, class_="l"), ui.div(ui.div(class_=st, style=f"width:{pct:.0f}%"), class_="b"), ui.span(display if display is not None else f"{float(value):.0f}", class_="v"), class_="gbo-at")

    attrs = [
        bar("BODY", bd.get("body_comp_score")), bar("PWR", bd.get("power_score")),
        bar("STR", bd.get("strength_score")), bar("SPD", bd.get("speed_score")),
        bar("ARM", bd.get("capacity_score")), bar("ROM", rom_score),
    ]
    if getattr(player, "is_pitcher", False):
        ps = pitch_summary or {}
        v, sp = ps.get("avg_velocity"), ps.get("avg_spin_rate")
        attrs += [bar("VELO", v, f"{v:.1f}" if v else None, 70, 100), bar("SPIN", sp, f"{sp:,.0f}" if sp else None, 1500, 2800)]

    pos = player.player_position.position_name if getattr(player, "player_position", None) else None
    cls = player.player_class.class_name if getattr(player, "player_class", None) else None
    cls_short = (cls or "").replace("Redshirt ", "RS ").replace("Freshman", "FR").replace("Sophomore", "SO").replace("Junior", "JR").replace("Senior", "SR").replace("Graduate", "GR")
    meta = [pill(x) for x in [pos, f"{player.bats or '-'} / {player.throws or '-'}", cls_short] if x]
    if flag and flag != "neutral":
        meta.append(status_chip(flag))
    photo = ui.tags.img(src=player.photo_url, class_="gbo-show-photo-img", alt="") if getattr(player, "photo_url", None) else ui.HTML('<svg viewBox="0 0 24 24" fill="currentColor" class="gbo-show-silhouette"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0116 0z"/></svg>')
    return ui.div(
        ui.div(
            ui.div(f"{overall:.0f}" if overall is not None else "—", ui.tags.small("Overall"), class_="gbo-show-ovr"),
            ui.div(ui.div(player.first_name, class_="gbo-show-nm"), ui.div(player.last_name, class_="gbo-show-ln"), ui.div(*meta, class_="gbo-show-meta"), class_="gbo-show-who"),
            class_="gbo-show-hd",
        ),
        ui.div(photo, ui.div(str(player.jersey_number) if player.jersey_number else "", class_="gbo-show-num"), class_="gbo-show-photo"),
        ui.div(*attrs, class_="gbo-show-attrs"),
        ui.div(ui.tags.img(src=theme.LOGO_URL, alt=""), ui.span("Pitt State"), ui.span(f"{tier} tier", class_="rt"), class_="gbo-show-ft"),
        class_="gbo-show", style=f"--tier:{tier_color}",
    )
