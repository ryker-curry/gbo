"""
GBO — Bullpen Dashboard page chrome, styled after Paradigm Player
Development's report layout (paradigmpds.com): a near-black background,
bordered card panels, and small-caps letter-spaced section labels
prefixed with a number and a thin rule (their "— 03 / WHAT COACHES SAY"
pattern). Colors are Pittsburg State's own crimson/gold, not Paradigm's
green -- this borrows their layout language, not their brand.

Deliberately scoped to pages/bullpen_dashboard.py only, not folded into
ui_components.py's shared page_header/render_kpi_cards -- those run on
every page in GBO, and restyling them would change the whole app's look,
not just this one dashboard. If this look is wanted elsewhere later,
promote it into ui_components.py then; don't import this module from
any other page in the meantime.

Same technique ui_components.py already uses everywhere (page_header,
render_kpi_cards, etc.): inject a <style> block via st.markdown. Because
Streamlit tears down and rebuilds a page's whole element tree on
navigation, this style block -- and its effect on .stApp -- only exists
while this page is the active one; it doesn't leak onto other pages.

One rule is a deliberate best-effort exception:
[data-testid="stVerticalBlockBorderWrapper"] / [data-testid="stExpander"]
recolor Streamlit's own bordered-container and expander chrome, which
Streamlit doesn't officially guarantee as a stable styling hook. If a
future Streamlit upgrade renames that testid, the rule just silently
stops matching -- st.container(border=True) still renders its own
default border, nothing breaks, it just reverts to plain gray there
until this is revisited.
"""

import streamlit as st

# Matches visualizations/chart_theme.py -- kept here too (not imported)
# since this module intentionally has no dependency on the chart-only
# visualizations package.
GOLD = "#D4AF37"
CRIMSON = "#BF1E2D"
TEXT_CREAM = "#FFFDE5"


def inject_dashboard_theme():
    """Call once near the top of pages/bullpen_dashboard.py, after
    page_header(). Sets the near-black background and cards/expanders
    tint for this page only."""
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(ellipse 1400px 700px at 50% -10%, rgba(191,30,45,0.12) 0%, rgba(10,8,8,0) 60%),
                #0C0909;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: #161010;
            border: 1px solid rgba(212,175,55,0.28) !important;
            border-radius: 14px !important;
        }
        [data-testid="stExpander"] {
            background: #161010;
            border: 1px solid rgba(212,175,55,0.22) !important;
            border-radius: 10px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def pitch_type_legend(summary_rows, total_pitches, color_for_label):
    """Colored-pill legend row per pitch type -- Pitch Type / Usage% /
    Avg MPH -- replacing the movement chart's in-plot Plotly legend
    (turned off in movement_chart() itself) with the below-chart table
    style from Ryker's reference image. Takes summary_rows in the same
    shape analytics.bullpen_metrics.pitch_type_summary() already
    returns (needs "Pitch Type", "#", "Avg Velo") -- no separate
    usage/velo computation here, just formatting what's already
    computed elsewhere for the Pitch Summary table above it.

    color_for_label is passed in rather than imported, so this module
    (page chrome, not a chart builder) doesn't need to depend on
    visualizations/bullpen_charts.py."""
    if not summary_rows or not total_pitches:
        return
    cells = []
    for row in summary_rows:
        label = row["Pitch Type"]
        usage_pct = round(100 * row["#"] / total_pitches, 0)
        avg_velo = f'{row["Avg Velo"]:.1f}' if row["Avg Velo"] is not None else "—"
        color = color_for_label(label)
        cells.append(
            '<div style="text-align:center; min-width:90px;">'
            f'<div style="width:28px; height:14px; border-radius:7px; background:{color}; margin:0 auto 6px auto;"></div>'
            f'<div style="color:{TEXT_CREAM}; font-weight:700; font-size:0.85rem;">{label}</div>'
            f'<div style="color:{GOLD}; font-size:0.8rem; margin-top:2px;">{usage_pct:g}%</div>'
            f'<div style="color:#B8B8B8; font-size:0.75rem;">{avg_velo} mph</div>'
            '</div>'
        )
    st.markdown(
        '<div style="display:flex; justify-content:center; gap:22px; flex-wrap:wrap; margin:6px 0 14px 0;">'
        + "".join(cells) + '</div>',
        unsafe_allow_html=True,
    )


def section_label(number, text):
    """Renders a Paradigm-style numbered section label: a short rule,
    then "01 · TEXT" in small-caps gold letter-spacing. Use in place of
    st.subheader() for this page's three structural sections (Filters,
    Pitch Summary, Charts) -- not a general-purpose replacement for
    st.subheader() elsewhere in GBO."""
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:12px; margin: 8px 0 14px 0;">
            <div style="width:32px; height:2px; background:{GOLD};"></div>
            <div style="color:{GOLD}; font-size:0.8rem; font-weight:700;
                        text-transform:uppercase; letter-spacing:0.14em;">
                {number:02d} &middot; {text}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
