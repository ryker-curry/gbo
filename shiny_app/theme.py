"""
GBO -- centralized brand palette + Shiny/bslib theme + shared plotly
chart color sets, for both dark and light mode.

Single source of truth for styling. Before this file, colors were
hardcoded hex strings duplicated across ui_helpers.py, bucket_display.py,
and repeated inline <style> blocks re-injected on every single
component render (a pattern carried over from Streamlit, which has no
persistent app-wide stylesheet mechanism -- Shiny does, so GLOBAL_CSS
below is included exactly once, in the outer page shell, instead).

Style direction: "Bold Athletic" (Option A, chosen from three mocked-up
directions -- gbo-theme-preview.html) -- a crimson/crimson-dark
gradient navbar and profile card, gold as a genuine second accent
(section titles, badges, table row keys), cream text on the colored
surfaces. This is a more saturated, team-branded look than the
"Clean Professional" alternative; the tradeoff is more colored
surfaces to individually contrast-check, done below.

Accessibility notes (WCAG, computed -- see the dataviz skill's "run
the checks, don't eyeball them" rule; every ratio below was computed
with the standard sRGB-relative-luminance formula, not judged by eye):

- Crimson (#BF1E2D) as small TEXT directly on a dark card surface
  measures 2.73-2.90:1 -- fails even the 3:1 large-text minimum (this
  was true of the original Streamlit app's KPI numbers too, which
  colored the value text itself crimson). So in DARK mode, crimson
  never appears as text -- only as a background, border, or a
  text-shadow glow behind cream text (a glow doesn't affect the actual
  glyph fill color, so it costs nothing on contrast).
- In LIGHT mode, crimson-on-white/near-white measures 5.55-6.11:1 --
  comfortably passes -- so light mode CAN use literal crimson text for
  the same "accent" role dark mode fakes with a glow. --gbo-accent-ink
  below switches between the two per mode.
- Gold (#D4AF37) on a dark surface measures 7.93-8.76:1 -- passes
  easily, used as literal text in dark mode (section titles, table
  key column, role badge background paired with dark ink). But gold
  directly on the crimson gradient (profile card, navbar) measures
  only 2.90:1 (crimson) / 5.13:1 (crimson-dark) -- inconsistent across
  a gradient -- so gold is never used as TEXT on the crimson gradient;
  cream is (5.94:1 on crimson, 10.49:1 on crimson-dark, both pass).
  Gold's non-text uses (badge background, border) don't have this
  problem since ink-on-gold (#1A1A1A on #D4AF37) is 8.28:1 regardless
  of mode.
- Gold on a LIGHT surface fails outright (2.10:1 on white) -- same
  issue as before -- --gbo-gold-text (#8A6A1A, 4.59-5.05:1) is the
  darkened stand-in used anywhere gold would otherwise be light-mode
  text (e.g. the gold-family table/section accents).
"""

from pathlib import Path

from shiny import ui

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "assets"
LOGO_URL = "/assets/GBO_logo-06.png"

FONT_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"

# NOTE: this used to be a ui.Theme(preset="shiny").add_defaults(...)
# Sass theme, applied via App(..., theme=...). Dropped that approach --
# ui.Theme compiles Sass at runtime via the `libsass` package (a
# compiled C extension), and libsass-python has a long history of
# lagging behind new CPython releases with prebuilt wheels (see
# https://github.com/sass/libsass-python/issues/448), which is exactly
# what broke for Ryker on Python 3.14: no wheel, and building it from
# source needs a C toolchain most people don't have set up. Since
# almost every custom component here (KPI cards, profile cards,
# navbar, tables, page header) was ALREADY plain CSS in GLOBAL_CSS
# below rather than Sass, the only things the Sass theme was actually
# buying were native-Bootstrap component colors (buttons, form
# inputs) and the global border-radius/font -- all fully achievable
# with plain CSS overrides instead (see the "Native Bootstrap
# component overrides" section of GLOBAL_CSS below). Zero native
# dependencies, zero compile step, same visual result.
GBO_THEME = None

# --- Chart color sets (plotly figures render server-side as static
# PNGs -- see bucket_display.py -- so they can't respond to the
# client-side dark-mode toggle via CSS the way the rest of the UI does;
# callers read AppState.dark_mode() and pass "dark"/"light" through). ---
_CHART_COLORS = {
    "dark": dict(
        crimson="#BF1E2D", track="#3A3A3A", text="#FFFDE5", muted="#B8B8B8",
        surface="#1E1E1E", grid="#3A3A3A", gold="#D4AF37",
    ),
    "light": dict(
        crimson="#BF1E2D", track="#E3E1DC", text="#1A1A1A", muted="#6B6B6B",
        surface="#FFFFFF", grid="#E3E1DC", gold="#8A6A1A",
    ),
}


def chart_colors(mode: str = "dark") -> dict:
    return _CHART_COLORS.get(mode, _CHART_COLORS["dark"])


# --- GLOBAL_CSS: GBO's own component classes (not native Bootstrap
# components), as CSS custom properties keyed off Bootstrap 5.3's
# [data-bs-theme] attribute -- ui.input_dark_mode() toggles that
# attribute, so every --gbo-* token below updates automatically with
# no Python-side re-render needed. Included ONCE, in the outer page
# shell (shiny_app/app.py), not per-component. -----------------------------
GLOBAL_CSS = """
:root[data-bs-theme="dark"] {
  --gbo-bg-page: #141414;
  --gbo-bg-card: #1E1E1E;
  --gbo-bg-card-grad: #241414;
  --gbo-border: #3A3A3A;
  --gbo-border-input: #4A4A4A;
  --gbo-text: #FFFDE5;
  --gbo-text-muted: #B8B8B8;
  --gbo-crimson: #BF1E2D;
  --gbo-crimson-dark: #7A1420;
  --gbo-gold: #D4AF37;
  /* Gold reads as literal TEXT in dark mode (7.93-8.76:1 on dark
     surfaces) -- see module docstring. */
  --gbo-gold-text: #D4AF37;
  /* Crimson fails as text on a dark surface (2.7-2.9:1) -- the "bold
     accent" value color is cream instead, paired with a crimson glow
     (see .gbo-kpi-accent below) so the bold/saturated look survives
     without failing contrast. */
  --gbo-accent-ink: var(--gbo-text);
  --gbo-text-on-crimson: #FFFDE5;
  --gbo-positive: #4CAF50;
  --gbo-negative: #E05252;
  --gbo-caution: #E0A526;
  /* Movement Flag's 4-tier scale (Green/Yellow/Orange/Red) needs a 4th
     hue distinct from both caution-amber and negative-red -- see
     build_movement_flag_ring in bucket_display.py. */
  --gbo-orange: #E0791E;
}
:root[data-bs-theme="light"] {
  --gbo-bg-page: #F5F4F1;
  --gbo-bg-card: #FFFFFF;
  --gbo-bg-card-grad: #FFFFFF;
  --gbo-border: #E3E1DC;
  --gbo-border-input: #C9C6C0;
  --gbo-text: #1A1A1A;
  --gbo-text-muted: #6B6B6B;
  --gbo-crimson: #BF1E2D;
  --gbo-crimson-dark: #7A1420;
  --gbo-gold: #D4AF37;
  /* Gold fails as text on a light surface (2.10:1) -- darkened
     variant, 4.59-5.05:1, passes. */
  --gbo-gold-text: #8A6A1A;
  /* Crimson-on-white/near-white passes (5.55-6.11:1) in light mode,
     so the accent value color CAN be literal crimson here -- no glow
     trick needed. */
  --gbo-accent-ink: var(--gbo-crimson);
  --gbo-text-on-crimson: #FFFDE5;
  --gbo-positive: #2E7D32;
  --gbo-negative: #C62828;
  /* Amber fails as text on a light surface at the dark-mode value
     (#E0A526 -> ~2.0:1) -- darkened variant, same contrast fix
     --gbo-gold-text already applies for the same reason. */
  --gbo-caution: #96690C;
  /* Same contrast fix as --gbo-caution/--gbo-negative above, darkened
     so orange text/badges pass on a light surface. */
  --gbo-orange: #A3550F;
}

body { background: var(--gbo-bg-page); color: var(--gbo-text); font-family: {FONT_STACK}; }
a { color: var(--gbo-crimson); }

/* --- Native Bootstrap component overrides (plain CSS, no Sass/libsass
   build step -- see GBO_THEME's comment above for why). Bootstrap 5.3
   bakes each component's own colors into LOCAL --bs-btn-*/--bs-*
   custom properties at its own Sass-compile time (not references to a
   global --bs-primary), so a global "--bs-primary: crimson" override
   would NOT reach .btn-primary -- these override each component's
   local variables directly instead, which does work purely in CSS. */
:root { --bs-border-radius: 0.65rem; --bs-border-radius-sm: 0.5rem; --bs-border-radius-lg: 0.85rem; }

.btn-primary {
  --bs-btn-bg: var(--gbo-crimson);
  --bs-btn-border-color: var(--gbo-crimson);
  --bs-btn-hover-bg: var(--gbo-crimson-dark);
  --bs-btn-hover-border-color: var(--gbo-crimson-dark);
  --bs-btn-active-bg: var(--gbo-crimson-dark);
  --bs-btn-active-border-color: var(--gbo-crimson-dark);
  --bs-btn-disabled-bg: var(--gbo-crimson);
  --bs-btn-disabled-border-color: var(--gbo-crimson);
  --bs-btn-color: var(--gbo-text-on-crimson);
  --bs-btn-hover-color: var(--gbo-text-on-crimson);
  --bs-btn-active-color: var(--gbo-text-on-crimson);
  --bs-btn-focus-shadow-rgb: 191, 30, 45;
}
.btn-outline-light { --bs-btn-color: var(--gbo-text); --bs-btn-border-color: var(--gbo-border-input); --bs-btn-hover-bg: var(--gbo-crimson); --bs-btn-hover-border-color: var(--gbo-crimson); }

.form-control, .form-select {
  background-color: var(--gbo-bg-card);
  border-color: var(--gbo-border-input);
  color: var(--gbo-text);
}
.form-control:focus, .form-select:focus {
  background-color: var(--gbo-bg-card);
  color: var(--gbo-text);
  border-color: var(--gbo-crimson);
  box-shadow: 0 0 0 0.25rem rgba(191, 30, 45, 0.25);
}
.form-check-input:checked { background-color: var(--gbo-crimson); border-color: var(--gbo-crimson); }

.card { background-color: var(--gbo-bg-card); border-color: var(--gbo-border); }
.accordion-item, .accordion-button { background-color: var(--gbo-bg-card); color: var(--gbo-text); }
.accordion-button:not(.collapsed) { background-color: var(--gbo-bg-card); color: var(--gbo-crimson); }

/* Dark-mode toggle, fixed corner, present on every screen (login,
   guest, authenticated app alike) -- see app.py's outer shell. */
.gbo-mode-toggle { position: fixed; top: 10px; right: 14px; z-index: 1050; }

/* Auth screens (login/guest-continue) -- centered branded card,
   consistent with the rest of the "Bold Athletic" system instead of a
   plain unstyled Bootstrap form. */
.gbo-auth-wrap { display: flex; justify-content: center; align-items: center; min-height: 80vh; padding: 20px; }
.gbo-auth-card { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-top: 4px solid var(--gbo-crimson); border-radius: var(--bs-border-radius-lg); padding: 32px 36px; width: 100%; max-width: 420px; }
.gbo-auth-logo { height: 56px; width: auto; display: block; margin: 0 auto 14px; }
.gbo-auth-underline { width: 42px; height: 3px; background: var(--gbo-crimson); border-radius: 2px; margin: 0 auto 18px; }

/* Page header -- "Bold Athletic": gold, uppercase, letter-spaced,
   crimson underline -- replaces a plain <h1>/st.title() on every page. */
.gbo-page-header { font-size: 1.5rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; color: var(--gbo-gold-text); margin-bottom: 6px; }
.gbo-page-header-underline { width: 42px; height: 3px; background: var(--gbo-crimson); border-radius: 2px; margin-bottom: 18px; }

/* Footer wordmark. */
.gbo-footer { margin-top: 40px; padding-top: 14px; border-top: 1px solid var(--gbo-border); color: var(--gbo-text-muted); font-size: 0.78rem; text-align: center; }

/* Empty state. */
.gbo-empty-state { text-align: center; padding: 22px 16px; color: var(--gbo-text-muted); }
.gbo-empty-state .icon { font-size: 1.4rem; margin-bottom: 6px; }

/* KPI row -- Bold Athletic: gradient card with a crimson border, gold
   uppercase label, cream value. The value's "accent" span (see
   ui_helpers.render_kpi_cards) carries the bold look: cream text with
   a crimson glow in dark mode, literal crimson in light mode (see
   --gbo-accent-ink above for why the split). */
.gbo-kpi-row { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 8px; }
.gbo-kpi-card { background: linear-gradient(160deg, var(--gbo-bg-card-grad) 0%, var(--gbo-bg-card) 100%); border: 1px solid var(--gbo-crimson); border-radius: 10px; padding: 14px 18px; flex: 1; min-width: 150px; }
.gbo-kpi-label { color: var(--gbo-gold-text); font-size: 0.72rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 6px; }
.gbo-kpi-value { color: var(--gbo-text); font-size: 1.8rem; font-weight: 800; line-height: 1.1; display: flex; align-items: center; gap: 8px; }
.gbo-kpi-value .gbo-kpi-accent { color: var(--gbo-accent-ink); }
:root[data-bs-theme="dark"] .gbo-kpi-value .gbo-kpi-accent { text-shadow: 0 0 18px rgba(191, 30, 45, 0.55); }
.gbo-kpi-delta { font-size: 0.8rem; font-weight: 600; margin-top: 4px; }
.gbo-kpi-delta.positive { color: var(--gbo-positive); }
.gbo-kpi-delta.negative { color: var(--gbo-negative); }

/* Profile header -- full crimson-to-crimson-dark gradient card with a
   gold border, same in both modes (it's a colored surface, not the
   page background, so it doesn't need to flip with the mode). Name +
   subtitle are cream (passes on both crimson and crimson-dark; gold
   text here would NOT -- see module docstring), gold is reserved for
   the border/frame, not the text. */
.gbo-profile-card { position: relative; background: linear-gradient(135deg, var(--gbo-crimson) 0%, var(--gbo-crimson-dark) 100%); border: 2px solid var(--gbo-gold); border-radius: 14px; padding: 18px 22px; margin-bottom: 8px; display: flex; align-items: center; gap: 18px; overflow: hidden; }
.gbo-profile-photo { width: 64px; height: 64px; border-radius: 50%; object-fit: cover; border: 3px solid var(--gbo-gold); flex-shrink: 0; }
.gbo-profile-name { color: var(--gbo-text-on-crimson); font-size: 1.45rem; font-weight: 800; line-height: 1.15; margin: 0; }
.gbo-profile-subtitle { color: var(--gbo-text-on-crimson); opacity: 0.85; font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; margin-top: 3px; }
.gbo-profile-logo { position: absolute; right: 18px; top: 50%; transform: translateY(-50%); width: 46px; height: 46px; opacity: 0.18; object-fit: contain; }

/* Small roster-table headshot thumbnail (Players page) -- distinct
   from .gbo-profile-photo (that one's a large circular profile-header
   photo on a crimson card; this is a compact square-ish cell image on
   a plain table row). */
.gbo-roster-thumb { width: 32px; height: 32px; border-radius: 6px; object-fit: cover; }

/* Navbar: gradient background (overrides bslib's flat navbar_dark_bg
   so the gradient survives regardless of Bootstrap version), cream
   nav-links, a translucent-white highlight on the active link, gold
   role badge. */
.navbar { background: linear-gradient(135deg, var(--gbo-crimson) 0%, var(--gbo-crimson-dark) 100%) !important; }
.navbar .nav-link { color: var(--gbo-text-on-crimson) !important; opacity: 0.88; }
.navbar .nav-link.active, .navbar .nav-link:hover { opacity: 1; background: rgba(255, 255, 255, 0.16); border-radius: 8px; }
.navbar .navbar-text { color: var(--gbo-text-on-crimson) !important; }
.gbo-navbar-brand { display: flex; align-items: center; gap: 8px; font-weight: 800; color: var(--gbo-text-on-crimson); }
.gbo-navbar-logo { height: 26px; width: auto; }
.gbo-role-badge { display: inline-block; background: var(--gbo-gold); color: #1A1A1A; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; padding: 3px 10px; border-radius: 20px; }

/* Section title -- for a sub-heading WITHIN a page (e.g. "Team
   Snapshot" above a KPI row), smaller/lower-emphasis than
   .gbo-page-header. Gold, uppercase, crimson underline rule. */
.gbo-section-title { color: var(--gbo-gold-text); font-size: 0.95rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.03em; border-bottom: 2px solid var(--gbo-crimson); display: inline-block; padding-bottom: 4px; margin: 0 0 14px; }

/* Category title -- one step down from .gbo-section-title, for a
   labeled sub-block WITHIN a section (e.g. "Body Comp — 60" inside the
   "Physical Testing Breakdown" section). Gold text carries the accent
   without the uppercase/underline treatment, so it doesn't visually
   compete with the section title above it; a thin crimson left-border
   (echoing .gbo-profile-card's accent stripe) marks it as a labeled
   block rather than a plain heading. */
.gbo-category-title { color: var(--gbo-gold-text); font-weight: 700; font-size: 0.92rem; border-left: 3px solid var(--gbo-crimson); padding-left: 10px; margin: 18px 0 8px; }

/* Subgroup label -- one step down from .gbo-category-title, for the
   finest-grained grouping (e.g. "Jumps — 82" under Power). Muted and
   italic, same as a plain <em> would look, but tokenized so it tracks
   dark/light mode instead of relying on default browser italic-gray. */
.gbo-subgroup-label { color: var(--gbo-text-muted); font-style: italic; font-size: 0.85rem; margin: 10px 0 4px; }

/* Metric progress bars (Physical Testing Breakdown -- Assessments, My
   Assessments, Dashboard all share this). Replaced a Plotly
   horizontal-bar-chart-rendered-as-an-image (bulky rows, plus a real
   per-chart kaleido render cost) with plain HTML/CSS: name + raw
   value on one line, a thin colored track underneath sized to the
   percentile. "Comfortable" density -- slimmer than the old chart,
   still easy to scan. Being real CSS (not a server-rendered image),
   these track the live dark/light toggle automatically. */
.gbo-metric-bar-group { display: flex; flex-direction: column; gap: 14px; margin: 4px 0 10px; }
.gbo-metric-bar-row { width: 100%; }
.gbo-metric-bar-header { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; margin-bottom: 5px; }
.gbo-metric-bar-name { color: var(--gbo-text); font-size: 0.85rem; font-weight: 600; }
.gbo-metric-bar-raw { color: var(--gbo-text-muted); font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.gbo-metric-bar-track { background: var(--gbo-border); border-radius: 5px; height: 10px; overflow: hidden; }
.gbo-metric-bar-fill { background: var(--gbo-crimson); height: 100%; border-radius: 5px; transition: width 0.3s ease; }
.gbo-metric-bar-percentile { color: var(--gbo-text-muted); font-size: 0.75rem; margin: 4px 0 0; }

/* Mobility & ROM pass/fail report (build_mobility_rom_report in
   bucket_display.py) -- NOT a percentile bar like .gbo-metric-bar-*
   above, since Mobility & ROM is checked against a fixed threshold
   instead of ranked against the team (see MOBILITY_ROM_THRESHOLDS in
   bucket_system.py). Each row is a name + raw value + a colored
   status pill instead of a track/fill bar. */
.gbo-rom-group { display: flex; flex-direction: column; gap: 8px; margin: 4px 0 10px; }
.gbo-rom-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; padding: 6px 0; border-bottom: 1px solid var(--gbo-border); }
.gbo-rom-name { color: var(--gbo-text); font-size: 0.85rem; font-weight: 600; flex: 1 1 auto; min-width: 160px; }
.gbo-rom-raw { color: var(--gbo-text-muted); font-size: 0.8rem; font-weight: 600; white-space: nowrap; }
.gbo-rom-status { font-size: 0.75rem; font-weight: 700; white-space: nowrap; padding: 2px 9px; border-radius: 10px; }
.gbo-rom-status-green { color: var(--gbo-positive); background: color-mix(in srgb, var(--gbo-positive) 15%, transparent); }
.gbo-rom-status-yellow { color: var(--gbo-caution); background: color-mix(in srgb, var(--gbo-caution) 15%, transparent); }
.gbo-rom-status-red { color: var(--gbo-negative); background: color-mix(in srgb, var(--gbo-negative) 15%, transparent); }
.gbo-rom-status-none { color: var(--gbo-text-muted); background: color-mix(in srgb, var(--gbo-text-muted) 12%, transparent); }

/* Compound Shoulder ROM rows (Total Arc Deficit, GIRD, ERG, Flexion/
   Extension Difference -- Ryker's Aug 2026 ROM redesign spec). Same
   .gbo-rom-row for the name/value/pill line, plus an explanation
   ("why this matters") and, for yellow/red only, a recommendation
   line underneath -- see build_mobility_rom_report and compute_
   shoulder_rom_profile/​_shoulder_rom_explanation in bucket_system.py. */
.gbo-rom-compound-row { padding-bottom: 6px; border-bottom: 1px solid var(--gbo-border); }
.gbo-rom-compound-row .gbo-rom-row { border-bottom: none; padding-bottom: 2px; }
.gbo-rom-explanation { color: var(--gbo-text-muted); font-size: 0.8rem; margin: 2px 0 0; line-height: 1.4; }
.gbo-rom-recommendation { color: var(--gbo-text); font-size: 0.8rem; margin: 4px 0 0; line-height: 1.4; }

/* Score/percentile rings (Total/Body Comp/Power/Strength, Development
   Profile's Output/Capacity) -- a CSS conic-gradient circle instead of
   a rendered Plotly donut-chart image: --gbo-ring-pct (set inline per
   ring, 0-100) drives how much of the circle fills with crimson before
   falling back to the track color. .gbo-ring-inner is a same-background
   circle sized to punch out the donut hole (72%, matching the old
   Plotly hole=0.72) and centers the value/label text. Real CSS, so
   (like the metric bars) these track the live dark/light toggle
   automatically instead of needing a server-side re-render. */
.gbo-ring-col { text-align: center; }
.gbo-ring { width: 130px; height: 130px; border-radius: 50%; margin: 0 auto; display: flex; align-items: center; justify-content: center; background: conic-gradient(var(--gbo-crimson) calc(var(--gbo-ring-pct) * 1%), var(--gbo-border) 0); }
.gbo-ring-inner { width: 74%; height: 74%; border-radius: 50%; background: var(--gbo-bg-card); display: flex; flex-direction: column; align-items: center; justify-content: center; }
.gbo-ring-value { color: var(--gbo-text); font-size: 1.55rem; font-weight: 800; line-height: 1; }
.gbo-ring-sublabel { color: var(--gbo-text); font-size: 0.7rem; margin-top: 4px; text-align: center; padding: 0 10px; line-height: 1.2; }
.gbo-ring-label { color: var(--gbo-text); font-weight: 700; text-align: center; margin: 8px 0 0; }

/* Movement Flag ring (build_movement_flag_ring) -- a fully-filled
   solid-color circle showing the flag's STATUS WORD (GREEN/YELLOW/
   ORANGE/RED) plus its 1-5 score, not a percentage, since Mobility &
   ROM doesn't have a percentile score to plot (see that function's
   docstring). Same .gbo-ring/.gbo-ring-inner shell as the percentage
   rings above, just with a flat color instead of a conic-gradient fill
   -- these modifier classes override the default crimson background.
   The status word is always shown as TEXT alongside the color (never
   color alone), per Ryker's explicit colorblind-accessibility
   requirement. Originally this was two separate widgets -- a 3-color
   (green/yellow/red) ROM-only ring plus a 4-color Movement Flag pill
   sitting next to it -- collapsed into one ring (Ryker's call, Aug
   2026) since the two could show conflicting reads and even when they
   agreed, showing two different "problem counts" side by side read as
   contradictory. This ring's color/word now comes from Movement Flag
   (compute_movement_flag in bucket_system.py), which is why it needs
   all 4 hues, not just the 3 the ROM-only version used. */
.gbo-ring--green { background: var(--gbo-positive); }
.gbo-ring--yellow { background: var(--gbo-caution); }
.gbo-ring--orange { background: var(--gbo-orange); }
.gbo-ring--red { background: var(--gbo-negative); }

/* Loading placeholder (chart_helpers.render_chart_async) -- a small
   spinner + label shown while a chart image or other slow, DB-backed
   section is still rendering (kaleido PNG export, or a big pitch-list
   query on Bullpen Dashboard). Ryker's report (Aug 2026): the old
   plain-text "Loading chart..." placeholder was too easy to miss
   against the dark theme, read as inert text rather than something
   actively working -- a rotating ring reads as "in progress" the way
   text alone doesn't, regardless of theme/color. */
@keyframes gbo-spin { to { transform: rotate(360deg); } }
.gbo-loading-row { display: flex; align-items: center; gap: 10px; padding: 14px 0; color: var(--gbo-text-muted); font-size: 0.85rem; }
.gbo-loading-spinner { width: 18px; height: 18px; border-radius: 50%; border: 2.5px solid var(--gbo-border); border-top-color: var(--gbo-crimson); animation: gbo-spin 0.7s linear infinite; flex-shrink: 0; }

/* Development Profile's Output-vs-Capacity balance bar -- was a
   Plotly shapes+scatter-marker chart image, now a plain CSS track
   with a positioned marker dot (marker's left% is the athlete's
   -50..50 balance_pct remapped onto 0..100%, see build_development_
   profile in bucket_display.py). */
.gbo-balance-bar { position: relative; height: 4px; background: var(--gbo-border); border-radius: 2px; margin: 22px 10px 8px; }
.gbo-balance-center { position: absolute; left: 50%; top: -8px; bottom: -8px; width: 2px; background: var(--gbo-text); transform: translateX(-50%); }
.gbo-balance-marker { position: absolute; top: 50%; left: 50%; width: 20px; height: 20px; border-radius: 50%; background: var(--gbo-crimson); border: 2px solid var(--gbo-text); transform: translate(-50%, -50%); }
.gbo-balance-labels { display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--gbo-text-muted); margin: 0 10px 10px; }

/* Plain data tables (read-only listings -- ui.tags.table built pages).
   First column (the "key" -- date, name, category) gets the gold
   accent treatment; the rest stay normal text color. */
.table { color: var(--gbo-text); }
.table > :not(caption) > * > * { border-bottom-color: var(--gbo-border); }
.table tbody tr td:first-child { color: var(--gbo-gold-text); font-weight: 700; }
""".replace("{FONT_STACK}", FONT_STACK)


def logo_img(css_class: str = "gbo-navbar-logo"):
    return ui.tags.img(src=LOGO_URL, class_=css_class, alt="GBO")