"""
GBO -- WHOOP charts (Oct 2026 WHOOP pilot). Plain inline SVG using the same
.gbo-progress-svg classes as progress_chart.py / velo_fade_chart.py, so they
follow the light/dark theme. Data: analytics/whoop_metrics.py.

  hrv_svg       daily HRV dots, 7-day line, his normal band shaded
  recovery_svg  daily recovery bars in WHOOP's green / yellow / red
  sleep_svg     hours slept bars vs hours needed (dashed line)
  strain_svg    day strain line (0-21)
  scatter_svg   one WHOOP number vs one performance number, a dot per game
"""

from html import escape

from visualizations.progress_chart import _nice_ticks

W, H = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 48, 20, 22, 36
ZONE_FILL = {"green": "var(--gbo-status-good)", "yellow": "var(--gbo-status-watch)", "red": "var(--gbo-status-flag)"}


def _frame(days, lo, hi, label, unit_lbl):
    """Shared axes. Returns (parts, X(day), Y(v), bar width)."""
    ticks = _nice_ticks(lo, hi)
    y0, y1 = ticks[0], ticks[-1]
    d0, d1 = days[0], days[-1]
    span = max((d1 - d0).days, 1)
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def X(d):
        return PAD_L + iw * ((d - d0).days / span) if span else PAD_L + iw / 2

    def Y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0))

    parts = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="{escape(label)}">']
    for t in ticks:
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="axis">{t:g}</text>')
    n_lbl = min(6, len(days))
    step = max(1, (len(days) - 1) // max(n_lbl - 1, 1))
    for d in days[::step]:
        parts.append(f'<text x="{X(d):.1f}" y="{H - 14}" text-anchor="middle" class="axis">{d.strftime("%b %d").replace(" 0", " ")}</text>')
    parts.append(f'<text x="4" y="12" class="axis">{escape(unit_lbl)}</text>')
    bw = max(2.0, min(14.0, iw / max(span + 1, 1) * 0.7))
    return parts, X, Y, bw, (y0, y1)


def _tip(text):
    return f"<title>{escape(text)}</title>"


def hrv_svg(rows, rolling, band=None):
    pts = [(r["day"], r["hrv"]) for r in rows if r.get("hrv")]
    if not pts:
        return ""
    vals = [v for _, v in pts] + ([band[0], band[1]] if band else [])
    days = [r["day"] for r in rows]
    parts, X, Y, _bw, (y0, y1) = _frame(days, min(vals) * 0.95, max(vals) * 1.05, "HRV trend", "HRV (ms)")
    if band:
        lo, hi = max(band[0], y0), min(band[1], y1)
        parts.append(f'<rect x="{PAD_L}" y="{Y(hi):.1f}" width="{W - PAD_L - PAD_R}" height="{max(Y(lo) - Y(hi), 0):.1f}" '
                     f'style="fill:var(--gbo-status-good-soft)">{_tip(f"His normal: {band[0]:.0f}-{band[1]:.0f} ms")}</rect>')
    line = [(d, v) for d, v in rolling if v is not None]
    if len(line) >= 2:
        path = " ".join(f'{"M" if i == 0 else "L"}{X(d):.1f},{Y(v):.1f}' for i, (d, v) in enumerate(line))
        parts.append(f'<path d="{path}" class="line"/>')
    for d, v in pts:
        parts.append(f'<g class="pt">{_tip(f"{d:%b %d}: {v:.0f} ms")}<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="9" class="hit"/>'
                     f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="3" class="dot" style="opacity:.55"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def recovery_svg(rows):
    pts = [(r["day"], r["recovery"]) for r in rows if r.get("recovery") is not None]
    if not pts:
        return ""
    days = [r["day"] for r in rows]
    parts, X, Y, bw, _ = _frame(days, 0, 100, "Recovery by day", "Recovery %")
    for cut in (34, 67):
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(cut):.1f}" y2="{Y(cut):.1f}" class="avg"/>')
    for d, v in pts:
        zone = "green" if v >= 67 else ("yellow" if v >= 34 else "red")
        parts.append(f'<rect x="{X(d) - bw / 2:.1f}" y="{Y(v):.1f}" width="{bw:.1f}" height="{Y(0) - Y(v):.1f}" rx="2" '
                     f'style="fill:{ZONE_FILL[zone]}">{_tip(f"{d:%b %d}: {v:.0f}% recovery")}</rect>')
    parts.append("</svg>")
    return "".join(parts)


def sleep_svg(rows):
    pts = [(r["day"], r["sleep_hours"], r.get("sleep_need_hours")) for r in rows if r.get("sleep_hours") is not None]
    if not pts:
        return ""
    days = [r["day"] for r in rows]
    hi = max([h for _, h, _ in pts] + [n for _, _, n in pts if n] + [9])
    parts, X, Y, bw, _ = _frame(days, 0, hi, "Sleep by night", "Hours")
    for d, h, n in pts:
        short = n is not None and h < n - 0.5
        tip = f"{d:%b %d}: slept {h:.1f} h" + (f", needed {n:.1f} h" if n else "")
        parts.append(f'<rect x="{X(d) - bw / 2:.1f}" y="{Y(h):.1f}" width="{bw:.1f}" height="{Y(0) - Y(h):.1f}" rx="2" '
                     f'style="fill:{"var(--gbo-status-watch)" if short else "var(--gbo-series-1)"}">{_tip(tip)}</rect>')
    need = [(d, n) for d, _, n in pts if n]
    if len(need) >= 2:
        path = " ".join(f'{"M" if i == 0 else "L"}{X(d):.1f},{Y(n):.1f}' for i, (d, n) in enumerate(need))
        parts.append(f'<path d="{path}" class="avg" style="fill:none"/>')
    parts.append("</svg>")
    return "".join(parts)


def strain_svg(rows):
    pts = [(r["day"], r["strain"]) for r in rows if r.get("strain") is not None]
    if not pts:
        return ""
    days = [r["day"] for r in rows]
    parts, X, Y, _bw, _ = _frame(days, 0, 21, "Day strain", "Strain")
    if len(pts) >= 2:
        path = " ".join(f'{"M" if i == 0 else "L"}{X(d):.1f},{Y(v):.1f}' for i, (d, v) in enumerate(pts))
        parts.append(f'<path d="{path}" class="line"/>')
    for d, v in pts:
        parts.append(f'<g class="pt">{_tip(f"{d:%b %d}: strain {v:.1f}")}<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="9" class="hit"/>'
                     f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="3" class="dot"/></g>')
    parts.append("</svg>")
    return "".join(parts)


def scatter_svg(games, x_key, y_key, x_label, y_label, rel=None, fmt_y="{:.1f}"):
    pts = [g for g in games if g.get(x_key) is not None and g.get(y_key) is not None]
    if not pts:
        return ""
    xs = [float(g[x_key]) for g in pts]
    ys = [float(g[y_key]) for g in pts]
    xt, yt = _nice_ticks(min(xs), max(xs)), _nice_ticks(min(ys), max(ys))
    x0, x1, y0, y1 = xt[0], xt[-1], yt[0], yt[-1]
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def X(v):
        return PAD_L + iw * (v - x0) / (x1 - x0)

    def Y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0))

    parts = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="{escape(y_label)} vs {escape(x_label)}">']
    for t in yt:
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="axis">{t:g}</text>')
    for t in xt:
        parts.append(f'<text x="{X(t):.1f}" y="{H - 18}" text-anchor="middle" class="axis">{t:g}</text>')
    parts.append(f'<text x="{(PAD_L + W - PAD_R) / 2:.0f}" y="{H - 2}" text-anchor="middle" class="axis">{escape(x_label)}</text>')
    parts.append(f'<text x="4" y="12" class="axis">{escape(y_label)}</text>')
    if rel and rel.get("slope") is not None:
        a, b = rel["intercept"], rel["slope"]
        ya, yb = a + b * x0, a + b * x1
        parts.append(f'<line x1="{X(x0):.1f}" y1="{Y(min(max(ya, y0), y1)):.1f}" x2="{X(x1):.1f}" y2="{Y(min(max(yb, y0), y1)):.1f}" class="avg"/>')
    for g in pts:
        x, y = float(g[x_key]), float(g[y_key])
        tip = f"{g['day']:%b %d} {g.get('opponent') or ''}: {x_label} {x:.0f}, {y_label} {fmt_y.format(y)}"
        parts.append(f'<g class="pt">{_tip(tip)}<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="10" class="hit"/>'
                     f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="5" class="dot"/></g>')
    parts.append("</svg>")
    return "".join(parts)
