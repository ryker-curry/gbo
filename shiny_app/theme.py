"""
GBO -- centralized design tokens + global CSS + shared plotly chart
colors, for both dark and light mode.

v2 (Aug 2026 redesign -- see GBO-DESIGN-SYSTEM.md at the repo root for
the full spec this file implements). Single source of truth for
styling: every --gbo-* token and every .gbo-* component class lives
here and is injected ONCE in the outer page shell (shiny_app/app.py).

What changed from v1 ("Bold Athletic") and why:
  - Crimson is now the ACTION color only (primary buttons, active nav,
    links). It no longer paints every KPI border, every progress bar,
    the navbar, or the profile card. Gold is reserved for ratings and
    tiers (>= 90, the player card). Everything else is a quiet neutral
    so the green/amber/red status system is the thing a coach's eye
    lands on first.
  - Status tokens (--gbo-status-good / -watch / -flag) are the new
    first-class citizens. The old --gbo-positive/--gbo-negative/
    --gbo-caution names are kept as aliases so existing pages keep
    working unchanged.
  - Typography: Barlow Condensed for page titles / big numbers, IBM
    Plex Sans for UI, IBM Plex Mono for tabular data. Loaded from
    Google Fonts with a system fallback stack.
  - Surfaces: page -> card -> raised. Borders, not shadows; no
    gradients or glows on content.
  - Layout: left sidebar shell (see app.py) replaces the top navbar.
    All old class names (.gbo-kpi-card, .gbo-section-title, .gbo-
    metric-bar-*, .gbo-ring*, .gbo-rom-*, ...) are retained and
    restyled, so no page module had to change for the new look.

Accessibility: every text/background pair below was chosen against
the WCAG formula (4.5:1 body, 3:1 large/UI). Gold and amber are
darkened for light mode (same approach v1 used). Status colors are
never the only carrier of meaning -- every chip/pill has a text label.
"""

from pathlib import Path

from shiny import ui

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
LOGO_URL = "/assets/GBO_logo-06.png"

FONT_STACK = "'IBM Plex Sans', system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
DISPLAY_STACK = "'Barlow Condensed', 'Arial Narrow', 'Helvetica Neue', Arial, sans-serif"
MONO_STACK = "'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

GOOGLE_FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700"
    "&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap"
)

# Kept for import-compatibility (app.py passes theme=GBO_THEME). Plain
# CSS overrides below do the work; no Sass/libsass needed.
GBO_THEME = None

# --- Chart color sets (plotly). Figures render inside cards, so paper/
# plot backgrounds are transparent and only ink colors differ by mode.
_CHART_COLORS = {
    "dark": dict(
        crimson="#C8102E", track="#1F242C", text="#E9ECF1", muted="#7A8594",
        surface="#171B21", grid="#2A3039", gold="#F2B529",
        good="#2E9C62", watch="#B58A22", flag="#D94F3D",
    ),
    "light": dict(
        crimson="#B3122B", track="#F8F9FB", text="#151A21", muted="#6B7280",
        surface="#FFFFFF", grid="#E1E4E9", gold="#B07D10",
        good="#1F7A4C", watch="#8A6514", flag="#B83C2C",
    ),
}

# Fixed pitch-type palette (same pitch -> same color on every chart).
# Validated for CVD separation against the dark surface.
PITCH_TYPE_COLORS = {
    "Fastball": "#3A8FE0", "4-Seam Fastball": "#3A8FE0", "2-Seam Fastball": "#7F7EDB",
    "Sinker": "#7F7EDB", "Slider": "#B08618", "Curveball": "#2A9E7A",
    "Changeup": "#B85FC4", "Cutter": "#E0713F", "Splitter": "#2A9E7A", "Other": "#7A8594",
}


def chart_colors(mode: str = "dark") -> dict:
    return _CHART_COLORS.get(mode, _CHART_COLORS["dark"])


GLOBAL_CSS = """
/* =========================================================
   1. TOKENS  (dark is the default; light is its own palette)
   ========================================================= */
:root[data-bs-theme="dark"] {
  --gbo-bg-page: #0A0A0B;
  --gbo-bg-card: #141415;
  --gbo-bg-raised: #1D1D20;
  --gbo-bg-card-grad: #141415;            /* alias, v1 gradient removed */
  --gbo-border: #272729;
  --gbo-border-strong: #3A3A3E;
  --gbo-border-input: #3A3A3E;            /* alias */
  --gbo-text: #F3F2EE;
  --gbo-text-2: #BDBCB6;
  --gbo-text-muted: #8A8A8E;
  --gbo-crimson: #CE1126;
  --gbo-crimson-hover: #E6223A;
  --gbo-crimson-dark: #8F0B21;
  --gbo-crimson-soft: rgba(200,16,46,.14);
  --gbo-gold: #FFC72C;
  --gbo-gold-text: #FFC72C;
  --gbo-gold-soft: rgba(255,199,44,.14);
  --gbo-accent-ink: var(--gbo-text);
  --gbo-text-on-crimson: #FFFFFF;
  --gbo-status-good: #2E9C62;
  --gbo-status-watch: #B58A22;
  --gbo-status-flag: #D94F3D;
  --gbo-status-good-soft: rgba(46,156,98,.14);
  --gbo-status-watch-soft: rgba(181,138,34,.14);
  --gbo-status-flag-soft: rgba(217,79,61,.14);
  --gbo-positive: var(--gbo-status-good);   /* v1 aliases */
  --gbo-negative: var(--gbo-status-flag);
  --gbo-caution: var(--gbo-status-watch);
  --gbo-orange: #D9782A;
  --gbo-silver: #BDBCB6;
  --gbo-focus: #6FB1FF;
  --gbo-shadow: 0 8px 24px rgba(0,0,0,.35);
}
:root[data-bs-theme="light"] {
  --gbo-bg-page: #F3F4F6;
  --gbo-bg-card: #FFFFFF;
  --gbo-bg-raised: #F8F9FB;
  --gbo-bg-card-grad: #FFFFFF;
  --gbo-border: #E1E4E9;
  --gbo-border-strong: #C9CED6;
  --gbo-border-input: #C9CED6;
  --gbo-text: #151A21;
  --gbo-text-2: #4B5563;
  --gbo-text-muted: #6B7280;
  --gbo-crimson: #B3122B;
  --gbo-crimson-hover: #9E0F26;
  --gbo-crimson-dark: #7A1420;
  --gbo-crimson-soft: rgba(179,18,43,.10);
  --gbo-gold: #B07D10;
  --gbo-gold-text: #8A6A1A;
  --gbo-gold-soft: rgba(176,125,16,.12);
  --gbo-accent-ink: var(--gbo-crimson);
  --gbo-text-on-crimson: #FFFFFF;
  --gbo-status-good: #1F7A4C;
  --gbo-status-watch: #8A6514;
  --gbo-status-flag: #B83C2C;
  --gbo-status-good-soft: rgba(31,122,76,.10);
  --gbo-status-watch-soft: rgba(138,101,20,.10);
  --gbo-status-flag-soft: rgba(184,60,44,.10);
  --gbo-positive: var(--gbo-status-good);
  --gbo-negative: var(--gbo-status-flag);
  --gbo-caution: var(--gbo-status-watch);
  --gbo-orange: #A3550F;
  --gbo-silver: #6B7280;
  --gbo-focus: #2563EB;
  --gbo-shadow: 0 8px 24px rgba(0,0,0,.12);
}
:root { --gbo-font: {FONT_STACK}; --gbo-display: {DISPLAY_STACK}; --gbo-mono: {MONO_STACK};
        --bs-border-radius: 6px; --bs-border-radius-sm: 4px; --bs-border-radius-lg: 10px; }

/* =========================================================
   2. BASE
   ========================================================= */
html, body { background: var(--gbo-bg-page); }
body { color: var(--gbo-text); font-family: var(--gbo-font); font-size: .875rem; line-height: 1.5; -webkit-font-smoothing: antialiased; }
a { color: var(--gbo-crimson); text-decoration: none; }
a:hover { color: var(--gbo-crimson-hover); text-decoration: underline; }
h1, h2, h3, h4, h5, h6 { color: var(--gbo-text); font-weight: 600; }
hr { border-color: var(--gbo-border); opacity: 1; }
.text-muted { color: var(--gbo-text-muted) !important; }
:focus-visible { outline: 2px solid var(--gbo-focus); outline-offset: 2px; }
.gbo-num, .gbo-mono { font-variant-numeric: tabular-nums; }
.gbo-mono { font-family: var(--gbo-mono); }
.gbo-cap { font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--gbo-text-muted); }

/* =========================================================
   3. NATIVE BOOTSTRAP OVERRIDES (buttons, inputs, cards, accordion, tables)
   ========================================================= */
.btn { font-weight: 600; border-radius: 6px; padding: .42rem .9rem; transition: background .15s, border-color .15s; }
.btn-primary {
  --bs-btn-bg: var(--gbo-crimson); --bs-btn-border-color: var(--gbo-crimson);
  --bs-btn-hover-bg: var(--gbo-crimson-hover); --bs-btn-hover-border-color: var(--gbo-crimson-hover);
  --bs-btn-active-bg: var(--gbo-crimson-dark); --bs-btn-active-border-color: var(--gbo-crimson-dark);
  --bs-btn-disabled-bg: var(--gbo-crimson); --bs-btn-disabled-border-color: var(--gbo-crimson);
  --bs-btn-color: #fff; --bs-btn-hover-color: #fff; --bs-btn-active-color: #fff;
  --bs-btn-focus-shadow-rgb: 200, 16, 46;
}
.btn-secondary, .btn-outline-light, .btn-outline-secondary, .btn-light {
  --bs-btn-bg: transparent; --bs-btn-color: var(--gbo-text); --bs-btn-border-color: var(--gbo-border-strong);
  --bs-btn-hover-bg: var(--gbo-bg-raised); --bs-btn-hover-color: var(--gbo-text); --bs-btn-hover-border-color: var(--gbo-border-strong);
  --bs-btn-active-bg: var(--gbo-bg-raised); --bs-btn-active-color: var(--gbo-text); --bs-btn-active-border-color: var(--gbo-border-strong);
}
.btn-danger, .btn-outline-danger {
  --bs-btn-bg: transparent; --bs-btn-color: var(--gbo-status-flag); --bs-btn-border-color: var(--gbo-border-strong);
  --bs-btn-hover-bg: var(--gbo-status-flag-soft); --bs-btn-hover-color: var(--gbo-status-flag); --bs-btn-hover-border-color: var(--gbo-status-flag);
  --bs-btn-active-bg: var(--gbo-status-flag-soft); --bs-btn-active-color: var(--gbo-status-flag);
}
.btn-success { --bs-btn-bg: var(--gbo-status-good); --bs-btn-border-color: var(--gbo-status-good); --bs-btn-hover-bg: var(--gbo-status-good); --bs-btn-hover-border-color: var(--gbo-status-good); --bs-btn-color: #fff; --bs-btn-hover-color:#fff; }

.form-label, label { color: var(--gbo-text-2); font-size: .8rem; font-weight: 500; margin-bottom: .25rem; }
.form-control, .form-select { background-color: var(--gbo-bg-raised); border-color: var(--gbo-border-strong); color: var(--gbo-text); border-radius: 6px; font-size: .875rem; }
.form-control::placeholder { color: var(--gbo-text-muted); }
.form-control:focus, .form-select:focus { background-color: var(--gbo-bg-raised); color: var(--gbo-text); border-color: var(--gbo-focus); box-shadow: 0 0 0 2px color-mix(in srgb, var(--gbo-focus) 30%, transparent); }
.form-select { background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%237A8594' stroke-width='1.5'/%3E%3C/svg%3E"); background-size: 10px; }
.form-check-input { background-color: var(--gbo-bg-raised); border-color: var(--gbo-border-strong); }
.form-check-input:checked { background-color: var(--gbo-crimson); border-color: var(--gbo-crimson); }
.form-range::-webkit-slider-thumb { background: var(--gbo-crimson); }
.form-range::-moz-range-thumb { background: var(--gbo-crimson); }
.irs--shiny .irs-bar { background: var(--gbo-crimson); border-color: var(--gbo-crimson); }
.irs--shiny .irs-from, .irs--shiny .irs-to, .irs--shiny .irs-single { background: var(--gbo-crimson); }
.irs--shiny .irs-handle { border-color: var(--gbo-crimson); background: var(--gbo-bg-card); }
.irs--shiny .irs-line { background: var(--gbo-bg-raised); border-color: var(--gbo-border); }
.irs--shiny .irs-min, .irs--shiny .irs-max, .irs--shiny .irs-grid-text { color: var(--gbo-text-muted); background: transparent; }

.card { background-color: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; }
.card-header { background: transparent; border-bottom-color: var(--gbo-border); font-weight: 600; }
.bslib-card .card-header { font-size: 1.05rem; }
.accordion { --bs-accordion-bg: var(--gbo-bg-card); --bs-accordion-border-color: var(--gbo-border); --bs-accordion-btn-color: var(--gbo-text); --bs-accordion-active-color: var(--gbo-text); --bs-accordion-active-bg: var(--gbo-bg-card); --bs-accordion-btn-focus-box-shadow: none; --bs-accordion-border-radius: 10px; }
.accordion-item, .accordion-button { background-color: var(--gbo-bg-card); color: var(--gbo-text); }
.accordion-button { font-weight: 600; font-size: .9rem; }
.accordion-button:not(.collapsed) { background-color: var(--gbo-bg-card); color: var(--gbo-text); box-shadow: inset 0 -1px 0 var(--gbo-border); }
.accordion-button::after { filter: grayscale(1) opacity(.6); }
.modal-content { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); box-shadow: var(--gbo-shadow); }
.dropdown-menu { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); box-shadow: var(--gbo-shadow); }
.dropdown-item { color: var(--gbo-text-2); } .dropdown-item:hover { background: var(--gbo-bg-raised); color: var(--gbo-text); }
.alert { border-radius: 8px; }
.nav-tabs { border-bottom: 1px solid var(--gbo-border); gap: 2px; }
.nav-tabs .nav-link { color: var(--gbo-text-muted); font-weight: 600; border: 0; border-bottom: 2px solid transparent; margin-bottom: -1px; padding: .55rem .9rem; }
.nav-tabs .nav-link:hover { color: var(--gbo-text); border-color: transparent; }
.nav-tabs .nav-link.active { color: var(--gbo-text); background: transparent; border-bottom-color: var(--gbo-crimson); }
.nav-pills .nav-link { color: var(--gbo-text-2); } .nav-pills .nav-link.active { background: var(--gbo-crimson-soft); color: var(--gbo-text); }

/* Tables */
.table { color: var(--gbo-text-2); --bs-table-bg: transparent; --bs-table-color: var(--gbo-text-2); --bs-table-striped-bg: transparent; --bs-table-hover-bg: var(--gbo-bg-raised); --bs-table-hover-color: var(--gbo-text); margin-bottom: 0; }
.table > :not(caption) > * > * { border-bottom-color: var(--gbo-border); padding: .65rem .75rem; vertical-align: middle; }
.table thead th { font-size: .7rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--gbo-text-muted); border-bottom: 1px solid var(--gbo-border); white-space: nowrap; }
.table tbody tr:hover > * { background: var(--gbo-bg-raised); }
.table tbody tr td:first-child { color: var(--gbo-text); font-weight: 600; }
.table td { font-variant-numeric: tabular-nums; }
.table-responsive { overflow-x: auto; }
.shiny-data-grid, .shiny-data-grid table { background: transparent; color: var(--gbo-text-2); }
.shiny-data-grid thead th { background: var(--gbo-bg-card); color: var(--gbo-text-muted); font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; border-bottom: 1px solid var(--gbo-border); }
.shiny-data-grid tbody tr:hover { background: var(--gbo-bg-raised); }
.shiny-data-grid tbody td { border-bottom: 1px solid var(--gbo-border); font-variant-numeric: tabular-nums; }

/* =========================================================
   4. SHELL: sidebar + top bar + content
   ========================================================= */
.gbo-app { display: grid; grid-template-columns: 240px 1fr; min-height: 100vh; }
.gbo-side { background: var(--gbo-bg-card); border-right: 1px solid var(--gbo-border); padding: 14px 12px; position: sticky; top: 0; height: 100vh; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.gbo-brand { display: flex; align-items: center; gap: 10px; padding: 6px 8px 14px; border-bottom: 1px solid var(--gbo-border); margin-bottom: 8px; }
.gbo-brand img { width: 30px; height: 36px; object-fit: contain; }
.gbo-brand-title { font-family: var(--gbo-display); font-weight: 700; font-size: 1.25rem; line-height: 1; letter-spacing: .02em; color: var(--gbo-gold-text); }
.gbo-brand-sub { font-size: .62rem; color: var(--gbo-text-muted); text-transform: uppercase; letter-spacing: .08em; margin-top: 2px; }
.gbo-side-group { padding: 12px 8px 4px; font-size: .68rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--gbo-gold-text); opacity: .85; }
.gbo-side-link { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 6px; color: var(--gbo-text-2); font-weight: 500; width: 100%; text-align: left; background: none; border: 0; font-size: .85rem; cursor: pointer; }
.gbo-side-link svg { width: 16px; height: 16px; stroke: currentColor; fill: none; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; flex: none; }
.gbo-side-link:hover { background: var(--gbo-bg-raised); color: var(--gbo-text); }
.gbo-side-link.active { background: var(--gbo-crimson-soft); color: var(--gbo-gold-text); box-shadow: inset 3px 0 0 var(--gbo-crimson); }
.gbo-side-me { margin-top: auto; border-top: 1px solid var(--gbo-border); padding: 12px 0 0 8px; display: flex; gap: 10px; align-items: center; }
.gbo-avatar { width: 32px; height: 32px; border-radius: 50%; background: var(--gbo-bg-raised); border: 1px solid var(--gbo-border-strong); display: grid; place-items: center; font-family: var(--gbo-display); font-weight: 700; color: var(--gbo-text-2); flex: none; object-fit: cover; }
.gbo-side-me-name { font-weight: 600; font-size: .82rem; color: var(--gbo-text); line-height: 1.2; }
.gbo-main { min-width: 0; display: flex; flex-direction: column; }
.gbo-top { border-top: 2px solid var(--gbo-crimson); height: 56px; display: flex; align-items: center; gap: 12px; padding: 0 32px; border-bottom: 1px solid var(--gbo-border); background: var(--gbo-bg-card); position: sticky; top: 0; z-index: 5; }
.gbo-crumb { color: var(--gbo-text-muted); font-weight: 500; }
.gbo-crumb b { color: var(--gbo-text); font-weight: 600; }
.gbo-top-right { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.gbo-top .btn { padding: .3rem .75rem; font-size: .8rem; }
.gbo-content { padding: 24px 32px 48px; max-width: 1440px; width: 100%; }
.gbo-mode-toggle { display: inline-flex; }
.gbo-mode-toggle .bslib-input-dark-mode, .gbo-mode-toggle bslib-input-dark-mode { --text-1: var(--gbo-text-2); }
.gbo-menu-btn { display: none; }
@media (max-width: 1200px) {
  .gbo-app { grid-template-columns: 64px 1fr; }
  .gbo-brand-title, .gbo-brand-sub, .gbo-side-group, .gbo-side-link span, .gbo-side-me > div { display: none; }
  .gbo-side-link { justify-content: center; padding: 10px; }
  .gbo-side-link.active { box-shadow: none; }
}
@media (max-width: 768px) {
  .gbo-app { grid-template-columns: 1fr; }
  .gbo-side { display: none; position: fixed; z-index: 50; width: 240px; }
  .gbo-side.open { display: flex; }
  .gbo-side.open .gbo-brand-title, .gbo-side.open .gbo-brand-sub, .gbo-side.open .gbo-side-group, .gbo-side.open .gbo-side-link span, .gbo-side.open .gbo-side-me > div { display: block; }
  .gbo-side.open .gbo-side-link { justify-content: flex-start; }
  .gbo-menu-btn { display: inline-flex; }
  .gbo-content, .gbo-top { padding-left: 16px; padding-right: 16px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }

/* Auth screens */
.gbo-auth-wrap { display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
.gbo-auth-card { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 12px; padding: 36px 40px; width: 100%; max-width: 420px; }
.gbo-auth-logo { height: 64px; width: auto; display: block; margin: 0 auto 14px; }
.gbo-auth-underline { width: 36px; height: 3px; background: var(--gbo-crimson); border-radius: 2px; margin: 0 auto 18px; }
.gbo-auth-card .gbo-page-header { text-align: center; font-size: 1.6rem; }

/* =========================================================
   5. PAGE STRUCTURE
   ========================================================= */
.gbo-page-header { font-family: var(--gbo-display); font-size: 2rem; font-weight: 700; text-transform: uppercase; letter-spacing: .02em; line-height: 1; color: var(--gbo-text); margin: 0 0 4px; }
.gbo-page-header-underline { display: none; }
.gbo-page-head > div:first-child { position: relative; padding-bottom: 8px; }
.gbo-page-head > div:first-child::after { content: ""; position: absolute; left: 0; bottom: 0; width: 48px; height: 3px; border-radius: 2px; background: linear-gradient(90deg, var(--gbo-crimson) 0 60%, var(--gbo-gold) 60%); }
.gbo-page-head { display: flex; align-items: flex-end; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }
.gbo-page-sub { color: var(--gbo-text-muted); margin: 4px 0 0; }
.gbo-page-actions { margin-left: auto; display: flex; gap: 8px; flex-wrap: wrap; }
.gbo-footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--gbo-border); color: var(--gbo-text-muted); font-size: .75rem; text-align: center; }
.gbo-empty-state { text-align: center; padding: 36px 20px; color: var(--gbo-text-muted); }
.gbo-empty-state .icon { display: none; }
.gbo-empty-state b { display: block; color: var(--gbo-text-2); font-weight: 600; margin-bottom: 4px; }

/* Section title (inside a page) -- quiet: text-color, no underline */
.gbo-section-title { color: var(--gbo-text); font-size: 1.05rem; font-weight: 600; text-transform: none; letter-spacing: 0; border: 0; display: block; padding: 0; margin: 0 0 12px; }
.gbo-section-title-row { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
.gbo-section-title-row .gbo-section-title { margin: 0; }
.gbo-section-title-row .right { margin-left: auto; color: var(--gbo-text-muted); font-size: .8rem; }
.gbo-category-title { color: var(--gbo-text); font-weight: 600; font-size: .95rem; border-left: 3px solid var(--gbo-border-strong); padding-left: 10px; margin: 18px 0 8px; }
.gbo-subgroup-label { color: var(--gbo-text-muted); font-style: normal; font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin: 12px 0 4px; }

/* Card (GBO component, distinct from Bootstrap .card) */
.gbo-card { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; padding: 20px; min-width: 0; }
.gbo-card.sm { padding: 16px 20px; }
.gbo-card-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.gbo-card-head h3 { margin: 0; font-size: 1.05rem; font-weight: 600; }
.gbo-card-head h3::before { content: ""; display: inline-block; width: 3px; height: .9em; background: var(--gbo-crimson); border-radius: 2px; margin-right: 10px; vertical-align: -2px; }
.gbo-card-head .right { margin-left: auto; color: var(--gbo-text-muted); font-size: .8rem; }
.gbo-grid { display: grid; gap: 20px; }
.gbo-grid-2 { grid-template-columns: minmax(0,1fr) minmax(0,1fr); } .gbo-grid-3 { grid-template-columns: repeat(3, minmax(0,1fr)); } .gbo-grid-21 { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); align-items: start; }
@media (max-width: 1000px) { .gbo-grid-2, .gbo-grid-3, .gbo-grid-21 { grid-template-columns: 1fr; } }

/* KPI tiles */
.gbo-kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin-bottom: 24px; }
.gbo-kpi-card { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; padding: 16px 20px; min-width: 0; }
.gbo-kpi-label { color: var(--gbo-gold-text); opacity: .8; font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
.gbo-kpi-value { color: var(--gbo-text); font-family: var(--gbo-display); font-size: 2rem; font-weight: 700; line-height: 1; display: flex; align-items: baseline; gap: 6px; font-variant-numeric: tabular-nums; }
.gbo-kpi-value .gbo-kpi-accent { color: var(--gbo-text); }
.gbo-kpi-value small { font-family: var(--gbo-font); font-weight: 500; font-size: .8rem; color: var(--gbo-text-muted); }
.gbo-kpi-delta { font-size: .78rem; font-weight: 600; margin-top: 6px; color: var(--gbo-text-muted); }
.gbo-kpi-delta.positive { color: var(--gbo-status-good); }
.gbo-kpi-delta.negative { color: var(--gbo-status-flag); }
.gbo-kpi-card.flag .gbo-kpi-value { color: var(--gbo-status-flag); }
.gbo-kpi-card.watch .gbo-kpi-value { color: var(--gbo-status-watch); }

/* Status chips */
.gbo-chip { display: inline-flex; align-items: center; gap: 6px; font-size: .68rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; padding: 3px 9px; border-radius: 999px; white-space: nowrap; line-height: 1.4; }
.gbo-chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.gbo-chip-good { background: var(--gbo-status-good-soft); color: var(--gbo-status-good); }
.gbo-chip-watch { background: var(--gbo-status-watch-soft); color: var(--gbo-status-watch); }
.gbo-chip-flag { background: var(--gbo-status-flag-soft); color: var(--gbo-status-flag); }
.gbo-chip-neutral { background: var(--gbo-bg-raised); color: var(--gbo-text-2); border: 1px solid var(--gbo-border); }
.gbo-chip-gold { background: var(--gbo-gold-soft); color: var(--gbo-gold); }
.gbo-chip-crimson { background: var(--gbo-crimson-soft); color: var(--gbo-crimson); }
.gbo-pill { display: inline-block; font-size: .66rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 2px 8px; border-radius: 999px; background: var(--gbo-bg-raised); border: 1px solid var(--gbo-border); color: var(--gbo-text-2); }
.gbo-role-badge { display: inline-block; background: var(--gbo-bg-raised); border: 1px solid var(--gbo-border); color: var(--gbo-text-2); font-size: .66rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; padding: 2px 8px; border-radius: 999px; }

/* Profile header (legacy card used by dashboards) -- quiet surface now */
.gbo-profile-card { position: relative; background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; display: flex; align-items: center; gap: 16px; overflow: hidden; }
.gbo-profile-card::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px; background: var(--gbo-crimson); }
.gbo-profile-photo { width: 56px; height: 56px; border-radius: 50%; object-fit: cover; border: 1px solid var(--gbo-border-strong); flex-shrink: 0; }
.gbo-profile-name { color: var(--gbo-text); font-family: var(--gbo-display); font-size: 1.6rem; font-weight: 700; line-height: 1; margin: 0; text-transform: uppercase; letter-spacing: .02em; }
.gbo-profile-subtitle { color: var(--gbo-text-muted); font-size: .78rem; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; margin-top: 4px; }
.gbo-profile-logo { position: absolute; right: 18px; top: 50%; transform: translateY(-50%); width: 36px; height: 36px; opacity: .25; object-fit: contain; }
.gbo-roster-thumb { width: 32px; height: 32px; border-radius: 6px; object-fit: cover; }

/* Metric bars -- fill is colored by STATUS (class on the fill), default neutral */
.gbo-metric-bar-group { display: flex; flex-direction: column; gap: 0; margin: 4px 0 10px; }
.gbo-metric-bar-row { width: 100%; padding: 9px 0; border-bottom: 1px solid var(--gbo-border); }
.gbo-metric-bar-row:last-child { border-bottom: 0; }
.gbo-metric-bar-header { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 6px; }
.gbo-metric-bar-name { color: var(--gbo-text); font-size: .85rem; font-weight: 500; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gbo-metric-bar-raw { color: var(--gbo-text); font-family: var(--gbo-mono); font-size: .82rem; font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; flex: none; }
.gbo-metric-bar-raw small, .gbo-metric-bar-raw .unit { color: var(--gbo-text-muted); font-family: var(--gbo-font); font-size: .74rem; margin-left: 3px; }
.gbo-metric-bar-track { background: var(--gbo-bg-raised); border-radius: 3px; height: 6px; overflow: hidden; }
.gbo-metric-bar-fill { background: var(--gbo-status-good); height: 100%; border-radius: 3px; transition: width .6s ease; }
.gbo-metric-bar-fill.good { background: var(--gbo-status-good); }
.gbo-metric-bar-fill.watch { background: var(--gbo-status-watch); }
.gbo-metric-bar-fill.flag { background: var(--gbo-status-flag); }
.gbo-metric-bar-fill.gold { background: var(--gbo-gold); }
.gbo-metric-bar-fill.neutral { background: var(--gbo-border-strong); }
.gbo-metric-bar-percentile { color: var(--gbo-text-muted); font-size: .72rem; margin: 4px 0 0; font-variant-numeric: tabular-nums; }

/* ROM rows (threshold-based) */
.gbo-rom-group { display: flex; flex-direction: column; gap: 0; margin: 4px 0 10px; }
.gbo-rom-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 9px 0; border-bottom: 1px solid var(--gbo-border); }
.gbo-rom-name { color: var(--gbo-text); font-size: .85rem; font-weight: 500; flex: 1 1 auto; min-width: 160px; }
.gbo-rom-raw { color: var(--gbo-text); font-family: var(--gbo-mono); font-size: .82rem; font-weight: 500; white-space: nowrap; font-variant-numeric: tabular-nums; }
.gbo-rom-status { display: inline-flex; align-items: center; gap: 6px; font-size: .68rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; padding: 3px 9px; border-radius: 999px; }
.gbo-rom-status::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.gbo-rom-status-green { color: var(--gbo-status-good); background: var(--gbo-status-good-soft); }
.gbo-rom-status-yellow { color: var(--gbo-status-watch); background: var(--gbo-status-watch-soft); }
.gbo-rom-status-red { color: var(--gbo-status-flag); background: var(--gbo-status-flag-soft); }
.gbo-rom-status-none { color: var(--gbo-text-muted); background: var(--gbo-bg-raised); }
.gbo-rom-compound-row { padding-bottom: 8px; border-bottom: 1px solid var(--gbo-border); }
.gbo-rom-compound-row .gbo-rom-row { border-bottom: none; padding-bottom: 2px; }
.gbo-rom-explanation { color: var(--gbo-text-muted); font-size: .78rem; margin: 2px 0 0; line-height: 1.45; }
.gbo-rom-recommendation { color: var(--gbo-text-2); font-size: .78rem; margin: 4px 0 0; line-height: 1.45; }

/* Score rings (conic) -- status-colored via --gbo-ring-color, default good */
.gbo-ring-col { text-align: center; }
.gbo-ring { --gbo-ring-color: var(--gbo-status-good); width: 96px; height: 96px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center; justify-content: center; background: conic-gradient(var(--gbo-ring-color) calc(var(--gbo-ring-pct) * 1%), var(--gbo-bg-raised) 0); }
.gbo-ring.good { --gbo-ring-color: var(--gbo-status-good); } .gbo-ring.watch { --gbo-ring-color: var(--gbo-status-watch); } .gbo-ring.flag { --gbo-ring-color: var(--gbo-status-flag); } .gbo-ring.gold { --gbo-ring-color: var(--gbo-gold); }
.gbo-ring-inner { width: 82%; height: 82%; border-radius: 50%; background: var(--gbo-bg-card); display: flex; flex-direction: column; align-items: center; justify-content: center; }
.gbo-ring-value { color: var(--gbo-text); font-family: var(--gbo-display); font-size: 1.75rem; font-weight: 700; line-height: 1; font-variant-numeric: tabular-nums; }
.gbo-ring-sublabel { color: var(--gbo-text-muted); font-size: .66rem; margin-top: 3px; text-align: center; padding: 0 8px; line-height: 1.2; }
.gbo-ring-label { color: var(--gbo-text-2); font-weight: 500; font-size: .8rem; text-align: center; margin: 8px 0 0; }
.gbo-ring--green { background: var(--gbo-status-good); } .gbo-ring--yellow { background: var(--gbo-status-watch); } .gbo-ring--orange { background: var(--gbo-orange); } .gbo-ring--red { background: var(--gbo-status-flag); }
.gbo-ring--green .gbo-ring-inner, .gbo-ring--yellow .gbo-ring-inner, .gbo-ring--orange .gbo-ring-inner, .gbo-ring--red .gbo-ring-inner { width: 100%; height: 100%; background: transparent; }
.gbo-ring--green .gbo-ring-value, .gbo-ring--yellow .gbo-ring-value, .gbo-ring--orange .gbo-ring-value, .gbo-ring--red .gbo-ring-value, .gbo-ring--green .gbo-ring-sublabel, .gbo-ring--yellow .gbo-ring-sublabel, .gbo-ring--orange .gbo-ring-sublabel, .gbo-ring--red .gbo-ring-sublabel { color: #fff; }

/* Bucket summary card (collapsible) */
.gbo-bucket { display: grid; grid-template-columns: 56px 1fr auto; gap: 16px; align-items: center; padding: 14px 20px; background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; cursor: pointer; margin-bottom: 10px; }
.gbo-bucket:hover { border-color: var(--gbo-border-strong); }
.gbo-bucket-score { font-family: var(--gbo-display); font-weight: 700; font-size: 1.75rem; line-height: 1; text-align: center; font-variant-numeric: tabular-nums; }
.gbo-bucket-score.good { color: var(--gbo-text); } .gbo-bucket-score.watch { color: var(--gbo-status-watch); } .gbo-bucket-score.flag { color: var(--gbo-status-flag); } .gbo-bucket-score.gold { color: var(--gbo-gold); }
.gbo-bucket-title { font-weight: 600; color: var(--gbo-text); }
.gbo-bucket-why { font-size: .78rem; color: var(--gbo-text-muted); margin-top: 2px; }
.gbo-bucket-why b { color: var(--gbo-text-2); font-weight: 500; }

/* Loading */
@keyframes gbo-spin { to { transform: rotate(360deg); } }
.gbo-loading-row { display: flex; align-items: center; gap: 10px; padding: 14px 0; color: var(--gbo-text-muted); font-size: .85rem; }
.gbo-loading-spinner { width: 18px; height: 18px; border-radius: 50%; border: 2.5px solid var(--gbo-border); border-top-color: var(--gbo-crimson); animation: gbo-spin .7s linear infinite; flex-shrink: 0; }

/* Balance bar */
.gbo-balance-bar { position: relative; height: 4px; background: var(--gbo-bg-raised); border-radius: 2px; margin: 22px 10px 8px; }
.gbo-balance-center { position: absolute; left: 50%; top: -8px; bottom: -8px; width: 2px; background: var(--gbo-border-strong); transform: translateX(-50%); }
.gbo-balance-marker { position: absolute; top: 50%; left: 50%; width: 16px; height: 16px; border-radius: 50%; background: var(--gbo-crimson); border: 2px solid var(--gbo-bg-card); transform: translate(-50%, -50%); }
.gbo-balance-labels { display: flex; justify-content: space-between; font-size: .72rem; color: var(--gbo-text-muted); margin: 0 10px 10px; }

/* Legacy navbar classes kept harmless (if any page still references them) */
.gbo-navbar-brand { display: flex; align-items: center; gap: 8px; font-weight: 700; color: var(--gbo-text); }
.gbo-navbar-logo { height: 26px; width: auto; }

/* Plotly figures sit on cards: make widget backgrounds transparent */
.js-plotly-plot .plotly .main-svg { background: transparent !important; }
.shiny-plot-output img, .gbo-chart-img { max-width: 100%; height: auto; }

/* =========================================================
   6. PLAYER PROFILE + SHOW CARD (modules/player_profile.py)
   ========================================================= */
.gbo-profile-hero { display: grid; grid-template-columns: 360px 1fr; gap: 20px; align-items: start; }
@media (max-width: 1100px) { .gbo-profile-hero { grid-template-columns: 1fr; } .gbo-show { width: 100%; } }
.gbo-show { width: 360px; background: linear-gradient(180deg, #1B1B1E, #121213); border: 1px solid var(--gbo-border-strong); border-radius: 12px; position: relative; overflow: hidden; padding: 20px 20px 16px 24px; display: flex; flex-direction: column; gap: 14px; }
.gbo-show::before { content: ""; position: absolute; inset: 0; background: linear-gradient(135deg, var(--gbo-crimson-soft) 0%, transparent 40%), linear-gradient(315deg, var(--gbo-gold-soft) 0%, transparent 35%); pointer-events: none; }
.gbo-show::after { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 5px; background: var(--tier); }
.gbo-show > * { position: relative; }
.gbo-show-hd { display: grid; grid-template-columns: auto 1fr; gap: 14px; align-items: start; }
.gbo-show-ovr { font-family: var(--gbo-display); font-weight: 700; font-size: 4.5rem; line-height: .85; color: var(--tier); font-variant-numeric: tabular-nums; }
.gbo-show-ovr small { display: block; font-size: .62rem; letter-spacing: .12em; font-family: var(--gbo-font); font-weight: 600; color: var(--gbo-text-muted); margin-top: 6px; text-transform: uppercase; }
.gbo-show-who { padding-top: 4px; min-width: 0; }
.gbo-show-nm { font-family: var(--gbo-display); font-weight: 700; font-size: 1.75rem; line-height: 1; text-transform: uppercase; color: var(--gbo-text); }
.gbo-show-ln { font-family: var(--gbo-display); font-weight: 500; font-size: 1.1rem; color: var(--gbo-text-2); line-height: 1.1; text-transform: uppercase; letter-spacing: .03em; }
.gbo-show-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.gbo-show-photo { aspect-ratio: 4 / 3; border-radius: 8px; background: linear-gradient(180deg, var(--gbo-bg-card), var(--gbo-bg-page)); border: 1px solid var(--gbo-border); display: grid; place-items: center; color: var(--gbo-text-muted); position: relative; overflow: hidden; }
.gbo-show-photo-img { width: 100%; height: 100%; object-fit: cover; }
.gbo-show-silhouette { width: 90px; height: 90px; opacity: .35; }
.gbo-show-num { position: absolute; right: 12px; bottom: 4px; font-family: var(--gbo-display); font-weight: 700; font-size: 3rem; color: var(--gbo-text); opacity: .18; line-height: 1; }
.gbo-show-attrs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; }
.gbo-at { display: grid; grid-template-columns: 40px 1fr 34px; gap: 8px; align-items: center; font-size: .72rem; }
.gbo-at .l { font-weight: 600; letter-spacing: .04em; color: var(--gbo-text-muted); }
.gbo-at .b { height: 5px; background: var(--gbo-bg-card); border-radius: 3px; overflow: hidden; }
.gbo-at .b > div { height: 100%; border-radius: 3px; background: var(--gbo-status-good); }
.gbo-at .b > .good { background: var(--gbo-status-good); } .gbo-at .b > .watch { background: var(--gbo-status-watch); } .gbo-at .b > .flag { background: var(--gbo-status-flag); } .gbo-at .b > .gold { background: var(--gbo-gold); } .gbo-at .b > .neutral { background: var(--gbo-border-strong); }
.gbo-at .v { text-align: right; font-family: var(--gbo-mono); font-size: .78rem; color: var(--gbo-text); font-variant-numeric: tabular-nums; }
.gbo-show-ft { display: flex; align-items: center; gap: 8px; border-top: 1px solid var(--gbo-border); padding-top: 10px; font-size: .64rem; letter-spacing: .08em; text-transform: uppercase; color: var(--gbo-text-muted); font-weight: 600; }
.gbo-show-ft img { width: 16px; height: 20px; object-fit: contain; }
.gbo-show-ft .rt { margin-left: auto; color: var(--tier); }
.gbo-pri { display: grid; grid-template-columns: auto 1fr; gap: 10px 12px; align-items: start; padding: 6px 0; }
.gbo-pri-i { width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center; font-family: var(--gbo-display); font-weight: 700; font-size: .9rem; }
.gbo-pri-i.flag { background: var(--gbo-status-flag-soft); color: var(--gbo-status-flag); } .gbo-pri-i.watch { background: var(--gbo-status-watch-soft); color: var(--gbo-status-watch); } .gbo-pri-i.good { background: var(--gbo-status-good-soft); color: var(--gbo-status-good); }
.gbo-pri b { display: block; color: var(--gbo-text); font-weight: 600; } .gbo-pri span { color: var(--gbo-text-muted); font-size: .8rem; }
.gbo-li { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; padding: 10px 0; border-bottom: 1px solid var(--gbo-border); color: var(--gbo-text-2); }
.gbo-li:last-child { border-bottom: 0; } .gbo-li b { color: var(--gbo-text); font-weight: 600; }
.gbo-li-dt { font-family: var(--gbo-mono); font-size: .75rem; color: var(--gbo-text-muted); width: 96px; flex: none; padding-top: 2px; }
.gbo-stack { display: flex; flex-direction: column; gap: 16px; }
.gbo-tab-body { padding-top: 20px; }
.gbo-rings-row { display: flex; gap: 12px; flex-wrap: wrap; justify-content: space-around; }
.gbo-bucket-accordion .accordion-item { border-radius: 10px !important; margin-bottom: 10px; border: 1px solid var(--gbo-border); overflow: hidden; }
.gbo-bucket-accordion .accordion-button { padding: 12px 16px; }
.gbo-bucket-accordion .accordion-button::after { margin-left: 12px; }
.gbo-bucket-head { display: grid; grid-template-columns: 56px 1fr auto; gap: 16px; align-items: center; width: 100%; }
.gbo-bucket-head .gbo-bucket-score { text-align: center; }
.gbo-stack-bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--gbo-bg-raised); gap: 2px; }
.gbo-stack-bar > div { height: 100%; }
.gbo-cols { display: flex; gap: 10px; align-items: stretch; height: 160px; padding-top: 6px; }
.gbo-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 0; }
.gbo-col-track { flex: 1; width: 100%; max-width: 36px; display: flex; align-items: flex-end; background: var(--gbo-bg-raised); border-radius: 4px; overflow: hidden; }
.gbo-col-track > div { width: 100%; border-radius: 4px 4px 0 0; transition: height .9s cubic-bezier(.2,.8,.2,1); }
.gbo-col-track > .good { background: var(--gbo-status-good); } .gbo-col-track > .watch { background: var(--gbo-status-watch); } .gbo-col-track > .flag { background: var(--gbo-status-flag); }
.gbo-col-val { font-family: var(--gbo-mono); font-size: .75rem; color: var(--gbo-text); }
.gbo-col-lab { font-size: .7rem; color: var(--gbo-text-muted); text-transform: uppercase; letter-spacing: .04em; }
.gbo-filter { min-width: 160px; }
.gbo-player-link { color: var(--gbo-text); font-weight: 600; white-space: nowrap; }
.gbo-player-link:hover { color: var(--gbo-crimson); text-decoration: none; }
.table td.gbo-nowrap, .table td:has(> .gbo-player-link) { white-space: nowrap; }
.gbo-filter .form-group, .gbo-filter .shiny-input-container { margin-bottom: 0; }

/* =========================================================
   7. MOTION (theme.MOTION_JS drives these; off under reduced-motion)
   ========================================================= */
.gbo-metric-bar-fill, .gbo-at .b > div { transition: width .9s cubic-bezier(.2,.8,.2,1); }
.gbo-anim-in { opacity: 0; transform: translateY(8px); }
.gbo-anim-in { transition: opacity .45s ease, transform .45s cubic-bezier(.2,.8,.2,1); }
.gbo-anim-in.gbo-anim-go { opacity: 1; transform: none; }
.gbo-side-link, .btn, .gbo-chip, .gbo-bucket, .gbo-card, .gbo-kpi-card { transition: background .15s, border-color .15s, color .15s, box-shadow .15s; }
.gbo-card:hover, .gbo-kpi-card:hover { border-color: var(--gbo-border-strong); }
.gbo-show { transition: transform .25s cubic-bezier(.2,.8,.2,1), box-shadow .25s; }
.gbo-show:hover { transform: translateY(-2px); box-shadow: var(--gbo-shadow); }
@media (prefers-reduced-motion: reduce) { .gbo-anim-in { opacity: 1; transform: none; } }
""".replace("{FONT_STACK}", FONT_STACK).replace("{DISPLAY_STACK}", DISPLAY_STACK).replace("{MONO_STACK}", MONO_STACK)


def fonts_link():
    """<link> tag for the Google Fonts bundle. Include once in the page head."""
    return ui.tags.link(rel="stylesheet", href=GOOGLE_FONTS_URL)


def logo_img(css_class: str = "gbo-navbar-logo"):
    return ui.tags.img(src=LOGO_URL, class_=css_class, alt="GBO")


# Page-load motion: bars fill from 0, rings sweep to their value, KPI
# numbers count up, cards stagger in. Runs on every DOM insertion
# (Shiny re-renders outputs on navigation/tab change), so new content
# animates without any page module knowing about it. Skipped entirely
# when the OS asks for reduced motion.
MOTION_JS = r"""
(function(){
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return;
  var ease = function(t){ return 1 - Math.pow(1 - t, 3); };
  // Everything animates when it SCROLLS INTO VIEW (IntersectionObserver),
  // so bars far down a long page still fill in front of the user.
  var io = new IntersectionObserver(function(entries){
    entries.forEach(function(en){ if (en.isIntersecting) { io.unobserve(en.target); fire(en.target); } });
  }, { rootMargin: '0px 0px -5% 0px', threshold: 0.05 });
  function fire(el){
    if (el.__gboKind === 'bar') { var w = el.__gboW; el.style.transition = 'none'; el.style.width = '0%';
      requestAnimationFrame(function(){ requestAnimationFrame(function(){ el.style.transition = ''; el.style.width = w; }); }); }
    else if (el.__gboKind === 'col') { var h = el.__gboH; el.style.transition = 'none'; el.style.height = '3%';
      requestAnimationFrame(function(){ requestAnimationFrame(function(){ el.style.transition = ''; el.style.height = h; }); }); }
    else if (el.__gboKind === 'ring') { var target = el.__gboPct, t0 = null, dur = 900;
      function step(ts){ if (!t0) t0 = ts; var p = Math.min(1, (ts - t0) / dur); el.style.setProperty('--gbo-ring-pct', (target * ease(p)).toFixed(1)); if (p < 1) requestAnimationFrame(step); }
      requestAnimationFrame(step); }
    else if (el.__gboKind === 'num') { var node = el.__gboNode, txt = el.__gboTxt, m = el.__gboM, target = el.__gboTarget, t0n = null, durn = 800;
      var dec = (m[2].split('.')[1] || '').length, useComma = m[2].indexOf(',') >= 0;
      function fmt(v){ var s = v.toFixed(dec); if (useComma) s = s.replace(/\B(?=(\d{3})+(?!\d))/g, ','); return m[1] + s + m[3]; }
      function stepn(ts){ if (!t0n) t0n = ts; var p = Math.min(1, (ts - t0n) / durn); node.textContent = fmt(target * ease(p)); if (p < 1) requestAnimationFrame(stepn); else node.textContent = txt; }
      requestAnimationFrame(stepn); }
    else if (el.__gboKind === 'card') { el.classList.add('gbo-anim-go'); }
  }
  function prepBars(root){
    root.querySelectorAll('.gbo-metric-bar-fill:not([data-gbo-done]), .gbo-at .b > div:not([data-gbo-done]), .gbo-stack-bar > div:not([data-gbo-done])').forEach(function(el){
      el.setAttribute('data-gbo-done','1'); var w = el.style.width; if (!w) return;
      el.__gboKind = 'bar'; el.__gboW = w; el.style.transition = 'none'; el.style.width = '0%'; io.observe(el);
    });
    root.querySelectorAll('.gbo-col-track > div:not([data-gbo-done])').forEach(function(el){
      el.setAttribute('data-gbo-done','1'); var h = el.style.height; if (!h) return;
      el.__gboKind = 'col'; el.__gboH = h; el.style.transition = 'none'; el.style.height = '3%'; io.observe(el);
    });
  }
  function prepRings(root){
    root.querySelectorAll('.gbo-ring:not([data-gbo-done])').forEach(function(el){
      el.setAttribute('data-gbo-done','1');
      var target = parseFloat(getComputedStyle(el).getPropertyValue('--gbo-ring-pct')); if (isNaN(target)) return;
      el.__gboKind = 'ring'; el.__gboPct = target; el.style.setProperty('--gbo-ring-pct', '0'); io.observe(el);
    });
  }
  function prepNumbers(root){
    root.querySelectorAll('.gbo-kpi-accent:not([data-gbo-done]), .gbo-ring-value:not([data-gbo-done]), .gbo-show-ovr:not([data-gbo-done]), .gbo-bucket-score:not([data-gbo-done])').forEach(function(el){
      el.setAttribute('data-gbo-done','1');
      var node = null; for (var i = 0; i < el.childNodes.length; i++) { if (el.childNodes[i].nodeType === 3 && el.childNodes[i].textContent.trim()) { node = el.childNodes[i]; break; } }
      if (!node) return; var txt = node.textContent.trim(); var m = txt.match(/^([^0-9]*)([0-9][0-9,]*\.?[0-9]*)(.*)$/); if (!m) return;
      var target = parseFloat(m[2].replace(/,/g,'')); if (isNaN(target) || target === 0) return;
      el.__gboKind = 'num'; el.__gboNode = node; el.__gboTxt = txt; el.__gboM = m; el.__gboTarget = target;
      var dec = (m[2].split('.')[1] || '').length; node.textContent = m[1] + (0).toFixed(dec) + m[3]; io.observe(el);
    });
  }
  function prepCards(root){
    var cards = root.querySelectorAll('.gbo-card:not([data-gbo-done]), .gbo-kpi-card:not([data-gbo-done]), .gbo-show:not([data-gbo-done]), .gbo-bucket:not([data-gbo-done]), .accordion-item:not([data-gbo-done]), .gbo-profile-card:not([data-gbo-done])');
    cards.forEach(function(el, i){
      el.setAttribute('data-gbo-done','1'); el.classList.add('gbo-anim-in'); el.__gboKind = 'card';
      el.style.transitionDelay = (Math.min(i, 12) * 45) + 'ms'; io.observe(el);
    });
  }
  function run(root){ root = root || document; prepCards(root); prepBars(root); prepRings(root); prepNumbers(root); }
  window.__gboRun = run;
  var pending = null;
  var mo = new MutationObserver(function(){ if (pending) return; pending = setTimeout(function(){ pending = null; run(document); }, 30); });
  function start(){ run(document); mo.observe(document.body, {childList: true, subtree: true}); }
  if (document.readyState !== 'loading') start(); else document.addEventListener('DOMContentLoaded', start);
  document.addEventListener('shown.bs.tab', function(e){ var pane = document.querySelector(e.target.getAttribute('data-bs-target') || e.target.getAttribute('href') || ''); if (pane) { pane.querySelectorAll('[data-gbo-done]').forEach(function(x){ x.removeAttribute('data-gbo-done'); x.classList.remove('gbo-anim-in','gbo-anim-go'); x.style.transitionDelay=''; }); run(pane); } });
})();
"""
