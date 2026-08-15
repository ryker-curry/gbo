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


def render_staff_profile_header(first_name: str, last_name: str, role_name: str, logo_base64: str = None, photo_url: str = None):
    """Same profile-card style as render_player_profile_header, for
    staff dashboards -- role name in place of jersey/position/class."""
    children = []
    if photo_url:
        children.append(ui.tags.img(src=photo_url, class_="gbo-profile-photo"))
    children.append(
        ui.div(
            ui.p(f"{first_name} {last_name}", class_="gbo-profile-name"),
            ui.div(role_name, class_="gbo-profile-subtitle"),
        )
    )
    if logo_base64:
        children.append(ui.tags.img(src=f"data:image/png;base64,{logo_base64}", class_="gbo-profile-logo"))
    return ui.div(*children, class_="gbo-profile-card")


def render_player_profile_header(player, logo_base64: str = None):
    """A card-style player profile header for the Player dashboard --
    name, crimson accent stripe, jersey/position/class, optional photo
    and GBO logo watermark."""
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
    if logo_base64:
        children.append(ui.tags.img(src=f"data:image/png;base64,{logo_base64}", class_="gbo-profile-logo"))
    return ui.div(*children, class_="gbo-profile-card")


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
