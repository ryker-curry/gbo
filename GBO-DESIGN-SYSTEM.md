# GBO Design System
*Gorilla Baseball Operations — v1, August 2026. Written to map 1:1 onto `shiny_app/theme.py` variables and `ui_helpers.py` components so implementation is mechanical.*

## 1. Principles

1. **View first, enter second.** Every page opens on what a coach wants to see. Data entry is a button that opens a panel, never the top of the page.
2. **Status is the headline.** Green / Amber / Red chips and bars tell a coach what matters before any number does. Status colors are reserved — never used for decoration or as chart series.
3. **Brand colors are rare.** Crimson is the one action color (primary buttons, active nav, links). Gold appears only on ratings, tiers, and the Show card. Everything else is neutral.
4. **One surface system.** Page ground → card → raised card. No gradients on content surfaces, no glowing borders.
5. **Numbers are typeset.** Tabular figures everywhere digits align; units in muted ink; display face for hero numbers.
6. **No emojis, no icons as decoration.** Icons only where they do a job (nav, status, actions).

## 2. Color tokens

Dark is the default. Light is a full second palette, not an inversion. Variable names keep Ryker's `--gbo-*` prefix.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--gbo-bg-page` | `#0F1216` | `#F3F4F6` | page ground |
| `--gbo-bg-card` | `#171B21` | `#FFFFFF` | cards, tables, panels |
| `--gbo-bg-raised` | `#1F242C` | `#F8F9FB` | hover rows, nested panels, inputs |
| `--gbo-border` | `#2A3039` | `#E1E4E9` | card/table borders |
| `--gbo-border-strong` | `#3A424D` | `#C9CED6` | inputs, focused cards |
| `--gbo-text` | `#E9ECF1` | `#151A21` | primary text |
| `--gbo-text-2` | `#AEB6C2` | `#4B5563` | secondary text, table body |
| `--gbo-text-muted` | `#7A8594` | `#6B7280` | captions, units, percentiles |
| `--gbo-crimson` | `#C8102E` | `#B3122B` | primary action, active nav, links |
| `--gbo-crimson-hover` | `#E01E3C` | `#9E0F26` | button hover |
| `--gbo-crimson-soft` | `rgba(200,16,46,.14)` | `rgba(179,18,43,.10)` | active nav background, selected row |
| `--gbo-gold` | `#F2B529` | `#B07D10` | ratings ≥90, Show card tier, rating ring |
| `--gbo-gold-soft` | `rgba(242,181,41,.16)` | `rgba(176,125,16,.12)` | gold chip background |
| `--gbo-status-good` | `#2E9C62` | `#1F7A4C` | Good |
| `--gbo-status-watch` | `#B58A22` | `#8A6514` | Attention |
| `--gbo-status-flag` | `#D94F3D` | `#B83C2C` | Priority |
| `--gbo-status-*-soft` | 14% alpha of each | 10% alpha | chip backgrounds |
| `--gbo-focus` | `#6FB1FF` | `#2563EB` | keyboard focus ring only |

Status colors always ship with a label ("Good / Attention / Priority") or an icon. Never color alone. Amber/red are weak for deutan viewers — the label is what carries it.

**Chart palettes** (validated, OKLCH band for dark):
- Pitch types, fixed order: Fastball `#3A8FE0` · Slider `#B08618` · Curveball `#2A9E7A` · Changeup `#B85FC4` · Cutter `#E0713F` · Sinker `#7F7EDB` · Other `#7A8594`. Same pitch always gets the same color on every chart.
- Sequential (heat maps): one hue, crimson, 5 steps from `--gbo-bg-raised` to `#C8102E`.
- Diverging (miss bias, +/-): blue `#3A8FE0` ← gray `#7A8594` → crimson `#C8102E`.
- Chart grid `--gbo-border`, axis text `--gbo-text-muted`, figure background transparent (inherits card).

## 3. Typography

| Role | Face | Fallback |
|---|---|---|
| Display (page titles, hero numbers, Show card) | **Barlow Condensed** 600/700, uppercase for titles | Arial Narrow, sans-serif |
| UI / body | **IBM Plex Sans** 400/500/600 | system-ui, sans-serif |
| Data (table numbers, KPIs, metric values) | **IBM Plex Mono** 500 or Plex Sans with `font-variant-numeric: tabular-nums` | monospace |

Scale (rem): 0.72 caption · 0.8 small · 0.875 body · 1 default · 1.125 card title · 1.5 section · 2 page title (display) · 2.75 hero number · 4.5 Show-card overall.

Rules: uppercase labels get `letter-spacing: .06em`; page titles `text-wrap: balance`; body line-height 1.5, data 1.2; max prose width 65ch.

Google Fonts link: `https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap`

## 4. Spacing, radius, elevation

- Spacing scale: 4 · 8 · 12 · 16 · 24 · 32 · 48 px. Card padding 20px; section gap 24px; page gutter 32px (16px on mobile).
- Radius: 6px inputs/chips · 10px cards · 999px pills. No 16px+ rounding.
- Elevation: borders, not shadows. Raised card = `--gbo-bg-raised` + border. One shadow only, on dropdowns/modals: `0 8px 24px rgba(0,0,0,.35)`.
- Dividers: 1px `--gbo-border`. No decorative underlines under headings.

## 5. Layout & navigation

**Shell:** fixed left sidebar 240px (collapses to 64px icon rail < 1200px, hidden behind a menu button < 768px) + top bar 56px + content area max 1440px, 12-col grid with 24px gutters.

**Sidebar groups (coach/admin):**
- Overview — Dashboard
- Roster — Players *(new roster table)*
- Development — Assessments, IDP, Training Routines, Player Assignments, Team Schedule, AT Appointments
- Pitching — Bullpen Dashboard, Bullpen Tracking, Bullpen Scripts, Import Rapsodo
- Hitting — Hitter Tracking
- Games — Game Tracking, Pitcher Game Report, Hitter Game Report, Player Stats
- Scouting — Opponent Teams
- Admin — User Management, Staff Assignments, Video Import

**Player role:** Overview (Dashboard) · Me (My Profile = same profile page as coaches see) · My Development, My Schedule, Training Routines.

**Top bar:** page breadcrumb (Roster › Jack Smith), global player search (⌘K), theme toggle, user chip (name + role pill), log out.

**Page header:** title (display face) + optional subtitle + right-aligned actions (primary crimson button for the page's main entry action, e.g. "Log assessment").

## 6. Components

**Card** — `--gbo-bg-card`, 1px border, 10px radius, 20px padding. Optional header row: title (1.125rem, 600) left, action/link right. No colored borders or glows.

**KPI tile** — label (caption, uppercase, muted) · value (display face 2rem, tabular) · delta line (small, status-colored with ▲▼ and "vs last week"). 4–5 per row, equal width.

**Status chip** — pill, 0.72rem 600 uppercase, soft background + colored text + 6px dot. Variants: Good / Attention / Priority / Neutral (gray). Used in tables, metric rows, bucket summaries, roster.

**Metric bar** — name (body 500) left, value + unit (data face) right; 6px track `--gbo-bg-raised`; fill colored by **status**, not crimson; percentile in muted caption below. Optional sparkline (last 3 tests) at right, 64×20.

**Bucket card** — collapsed by default: bucket name, score (display 1.5rem), status chip, one-line "why" (worst metric). Expand → metric bars. Replaces the 60-bar wall.

**Score ring** — inline SVG, 88px, 8px stroke, track `--gbo-bg-raised`, fill by status (or gold ≥90), value in display face centered. No PNGs.

**Data table** — header caption uppercase muted, 12px vertical padding, row hover `--gbo-bg-raised`, zebra off, numbers right-aligned tabular, first column is a link in `--gbo-text` (not gold), sortable headers with ▲▼, sticky header, `overflow-x:auto` wrapper. Empty state inside the table body.

**Empty state** — centered, 40px padding: one sentence of what appears here + who adds it, and the action button if the user can add it.

**Buttons** — primary: crimson fill, white text, 6px radius, 36px height. Secondary: transparent, 1px `--gbo-border-strong`, text `--gbo-text`. Destructive: secondary style with `--gbo-status-flag` text; never a red filled button. Disabled 40% opacity.

**Inputs** — `--gbo-bg-raised` fill, 1px `--gbo-border-strong`, 36px height, label above in small 500. Focus: 2px `--gbo-focus` ring.

**Tabs** — underline style, active = crimson 2px underline + `--gbo-text`, inactive `--gbo-text-muted`. Used inside Player Profile.

**Entry panel** — the data-entry form from today's pages, placed in a right-side drawer (480px) or an accordion under the page header, opened by the page's primary button.

**Player card (MLB The Show style)** — see §8.

## 7. Assessment status rules

- Each metric gets a status from Ryker's existing logic (percentile / threshold / ROM classification): Good ≥ 60th percentile or within range · Attention 35–59th or near threshold · Priority < 35th, below threshold, or flagged.
- Bucket status = worst metric status unless bucket score ≥ 80 (then Attention max).
- Player overall chip = count of Priority metrics: 0 → Good, 1–2 → Attention, 3+ → Priority.
- Anthropometrics (height, weight, body comp raw) show **no status** — context only, rendered as plain values.
- Status shown as chip + colored bar; tooltips explain the rule in one sentence.

## 8. Player Profile & Show card

**Profile page layout:**
1. **Hero — Show card** (left, 360px) + **At-a-glance** (right): overall status chip, 3 priorities, last assessed date, upcoming items, quick links.
2. **Tabs:** Overview · Assessments · Pitching · Hitting · Games · Development · Video.
3. Overview tab = bucket cards grid + recent activity + active IDP goals.

**Show card spec:** 360×520, card background `--gbo-bg-raised` with a subtle crimson-to-transparent diagonal wash at top, 1px border, tier stripe on left edge. Top: overall (display 4.5rem) in tier color, position + bats/throws, class. Middle: player photo (4:5, object-fit cover, placeholder silhouette). Bottom: attribute rows — label, mini bar, value — 8 attributes from bucket scores (Body Comp, Mobility, Arm Health, Upper Str, Lower Str, Power, Rotation, Speed). Pitchers add Velo / Spin / Command / Movement from Rapsodo. Footer: team mark + "GBO" + season.

Tiers by overall: 90+ Gold (`--gbo-gold`) · 80–89 Crimson · 70–79 Silver (`#AEB6C2`) · <70 Slate (`#7A8594`). Tier colors the overall number, the left stripe, and the ring only.

## 9. Charts

- Plotly template `gbo_dark` / `gbo_light`: transparent paper/plot bg, grid `--gbo-border`, font Plex Sans 12px `--gbo-text-muted`, no title inside figure (card header carries it), legend horizontal above plot, modebar hidden, margins 8/8/32/40.
- Marks: 2px lines, 8px markers with 2px surface ring, bars with 2px gaps; strike-zone box in `--gbo-text-muted`; heat maps use the crimson sequential ramp.
- Every chart sits in a card with title + one-line caption; a table view toggle where data is tabular (pitch list).
- Hover tooltips on every mark.

## 10. Responsive

- ≥1200: sidebar 240 + 12-col. 768–1199: icon rail 64 + 8-col, KPI row wraps 2×2. <768: sidebar hidden, top bar with menu, single column, Show card full width, tables scroll horizontally inside cards.
- Touch targets ≥ 40px. `prefers-reduced-motion`: no transitions.

## 11. Motion

- 150ms ease on hover/active states; 200ms on drawer open; ring/bar fills animate once on first paint (600ms). Nothing else moves.

## 12. Implementation map (Phase 3)

| Design item | File |
|---|---|
| Tokens, global CSS, fonts | `shiny_app/theme.py` |
| page_header, kpi_cards, status_chip, metric_bar, bucket_card, svg_ring, data_table, empty_state, show_card | `shiny_app/ui_helpers.py` |
| Sidebar shell, top bar, search | `shiny_app/app.py`, `shiny_app/nav.py` |
| Roster page | `shiny_app/modules/roster.py` (new) |
| Player profile page | `shiny_app/modules/player_profile.py` (new; reuses bucket_display + bullpen_dashboard_display) |
| Plotly template | `visualizations/chart_theme.py` |
| SVG rings replacing kaleido PNGs | `shiny_app/bucket_display.py` |
