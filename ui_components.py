"""
GBO — Shared UI components for consistent visual style across all
dashboard variants (general, Athletic Trainer, Strength Coach, Player,
and any future ones) -- built once, reused everywhere, so the KPI card
look stays consistent even though the underlying data differs per role.

Built as custom HTML/CSS via st.markdown rather than styling Streamlit's
built-in st.metric internals, since Streamlit's internal CSS class names
aren't a stable public API and can break between versions.

IMPORTANT: every line passed to st.markdown(..., unsafe_allow_html=True)
must have NO leading whitespace. Markdown treats any line indented 4+
spaces as a preformatted code block, so indented HTML/CSS gets shown as
literal text instead of being rendered -- this bit us once already.
"""

import streamlit as st

_KPI_STYLE = (
    "<style>"
    ".gbo-kpi-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 8px; }"
    ".gbo-kpi-card { background: #1E1E1E; border: 1px solid #3A3A3A; border-radius: 10px; "
    "padding: 16px 20px; flex: 1; min-width: 160px; }"
    ".gbo-kpi-label { color: #B8B8B8; font-size: 0.85rem; font-weight: 500; "
    "text-transform: uppercase; letter-spacing: 0.03em; margin-bottom: 6px; }"
    ".gbo-kpi-value { color: #FFFDE5; font-size: 2.1rem; font-weight: 800; line-height: 1.1; }"
    ".gbo-kpi-value span.accent { color: #BF1E2D; }"
    ".gbo-kpi-delta { font-size: 0.85rem; font-weight: 600; margin-top: 4px; }"
    ".gbo-kpi-delta.positive { color: #4CAF50; }"
    ".gbo-kpi-delta.negative { color: #E05252; }"
    "</style>"
)


def page_header(title: str):
    """Consistent page title with a crimson accent underline -- used in
    place of st.title() on every page for a unified look."""
    st.markdown(
        '<style>'
        '.gbo-page-header { font-size: 2.2rem; font-weight: 800; color: #FFFDE5; margin-bottom: 4px; }'
        '.gbo-page-header-underline { width: 60px; height: 4px; background: #BF1E2D; border-radius: 2px; margin-bottom: 20px; }'
        '</style>'
        f'<div class="gbo-page-header">{title}</div>'
        '<div class="gbo-page-header-underline"></div>',
        unsafe_allow_html=True,
    )


def page_footer():
    """Small consistent wordmark at the bottom of every page."""
    st.markdown(
        '<style>'
        '.gbo-footer { margin-top: 48px; padding-top: 16px; border-top: 1px solid #3A3A3A; '
        'color: #6B6B6B; font-size: 0.8rem; text-align: center; }'
        '</style>'
        '<div class="gbo-footer">Gorilla Baseball Operations</div>',
        unsafe_allow_html=True,
    )


def empty_state(message: str, icon: str = "📭"):
    """Friendlier empty-state message with an icon, used in place of a
    plain st.info() when a list/table has nothing to show yet."""
    st.markdown(
        '<style>'
        '.gbo-empty-state { text-align: center; padding: 24px 16px; color: #B8B8B8; }'
        '.gbo-empty-state .icon { font-size: 2rem; margin-bottom: 8px; }'
        '</style>'
        f'<div class="gbo-empty-state"><div class="icon">{icon}</div>{message}</div>',
        unsafe_allow_html=True,
    )


def render_staff_profile_header(first_name: str, last_name: str, role_name: str, logo_base64: str = None):
    """Same bold crimson/gold card style as render_player_profile_header,
    for staff dashboards -- role name in place of jersey/position/class,
    no photo (staff don't have profile photos)."""
    logo_html = ""
    if logo_base64:
        logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="gbo-profile-logo" />'

    st.markdown(
        '<style>'
        '.gbo-profile-card { position: relative; background: linear-gradient(135deg, #BF1E2D 0%, #7A1420 100%); '
        'border: 2px solid #D4AF37; border-radius: 14px; padding: 24px 28px; margin-bottom: 8px; '
        'display: flex; align-items: center; gap: 20px; overflow: hidden; }'
        '.gbo-profile-name { color: #FFFDE5; font-size: 2.4rem; font-weight: 900; line-height: 1.1; '
        'letter-spacing: 0.01em; margin: 0; }'
        '.gbo-profile-subtitle { color: #D4AF37; font-size: 1.1rem; font-weight: 700; '
        'text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }'
        '.gbo-profile-logo { position: absolute; right: 20px; top: 50%; transform: translateY(-50%); '
        'width: 70px; height: 70px; opacity: 0.25; object-fit: contain; }'
        '</style>'
        f'<div class="gbo-profile-card">'
        f'<div><div class="gbo-profile-name">{first_name} {last_name}</div>'
        f'<div class="gbo-profile-subtitle">{role_name}</div></div>'
        f'{logo_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_player_profile_header(player, logo_base64: str = None):
    """A bold, card-style player profile header for the Player dashboard --
    big name, crimson/gold styling, jersey/position/class, optional photo
    and GBO logo watermark. Replaces a plain 'Good morning, [Name]'
    greeting with something that actually looks like a player profile."""
    position_label = player.player_position.position_name if player.player_position else ""
    class_label = player.player_class.class_name if player.player_class else ""
    jersey_label = f"#{player.jersey_number}" if player.jersey_number else ""
    subtitle_parts = [p for p in [jersey_label, position_label, class_label] if p]
    subtitle = " · ".join(subtitle_parts)

    photo_html = ""
    if player.photo_url:
        photo_html = f'<img src="{player.photo_url}" class="gbo-profile-photo" />'

    logo_html = ""
    if logo_base64:
        logo_html = f'<img src="data:image/png;base64,{logo_base64}" class="gbo-profile-logo" />'

    st.markdown(
        '<style>'
        '.gbo-profile-card { position: relative; background: linear-gradient(135deg, #BF1E2D 0%, #7A1420 100%); '
        'border: 2px solid #D4AF37; border-radius: 14px; padding: 24px 28px; margin-bottom: 8px; '
        'display: flex; align-items: center; gap: 20px; overflow: hidden; }'
        '.gbo-profile-photo { width: 84px; height: 84px; border-radius: 50%; object-fit: cover; '
        'border: 3px solid #D4AF37; flex-shrink: 0; }'
        '.gbo-profile-name { color: #FFFDE5; font-size: 2.4rem; font-weight: 900; line-height: 1.1; '
        'letter-spacing: 0.01em; margin: 0; }'
        '.gbo-profile-subtitle { color: #D4AF37; font-size: 1.1rem; font-weight: 700; '
        'text-transform: uppercase; letter-spacing: 0.05em; margin-top: 4px; }'
        '.gbo-profile-logo { position: absolute; right: 20px; top: 50%; transform: translateY(-50%); '
        'width: 70px; height: 70px; opacity: 0.25; object-fit: contain; }'
        '</style>'
        f'<div class="gbo-profile-card">'
        f'{photo_html}'
        f'<div><div class="gbo-profile-name">{player.first_name} {player.last_name}</div>'
        f'<div class="gbo-profile-subtitle">{subtitle}</div></div>'
        f'{logo_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def render_kpi_cards(cards: list[dict]):
    """Render a row of bordered KPI cards, bold crimson numbers, optional
    trend delta with an up/down arrow (green = positive, red = negative).

    Each card dict: {"label": str, "value": str, "delta": str | None,
    "delta_positive": bool} -- delta and delta_positive are optional.
    """
    st.markdown(_KPI_STYLE, unsafe_allow_html=True)

    card_htmls = []
    for c in cards:
        delta_html = ""
        if c.get("delta"):
            arrow = "▲" if c.get("delta_positive", True) else "▼"
            css_class = "positive" if c.get("delta_positive", True) else "negative"
            delta_html = f'<div class="gbo-kpi-delta {css_class}">{arrow} {c["delta"]}</div>'
        card_htmls.append(
            '<div class="gbo-kpi-card">'
            f'<div class="gbo-kpi-label">{c["label"]}</div>'
            f'<div class="gbo-kpi-value"><span class="accent">{c["value"]}</span></div>'
            f'{delta_html}'
            '</div>'
        )

    row_html = '<div class="gbo-kpi-row">' + "".join(card_htmls) + '</div>'
    st.markdown(row_html, unsafe_allow_html=True)