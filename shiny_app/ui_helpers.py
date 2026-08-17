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


def page_header(title: str):
    """Consistent page title with a crimson accent underline -- used in
    place of a plain <h1> on every page for a unified look."""
    return ui.div(
        ui.div(title, class_="gbo-page-header"),
        ui.div(class_="gbo-page-header-underline"),
    )


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
