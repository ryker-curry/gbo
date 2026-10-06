"""
GBO -- velo-by-pitch-number chart (Oct 2026, analytics/velo_fade.py).

Plain inline SVG, same look and CSS classes as progress_chart.py (reuses
.gbo-progress-svg so it follows the theme): fastball velo dots by pitch
number, the least-squares trend line, hover tooltip per dot.
Also a small per-outing season chart (mph change per 25 pitches by date).
"""

from html import escape

from visualizations.progress_chart import _nice_ticks

W, H = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 48, 24, 28, 40


def outing_svg(res):
    pts = res.get("points") or []
    if not pts:
        return ""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ticks = _nice_ticks(min(ys), max(ys))
    y0, y1 = ticks[0], ticks[-1]
    x0, x1 = 1, max(max(xs), 2)
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def X(x):
        return PAD_L + iw * (x - x0) / (x1 - x0)

    def Y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0))

    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Fastball velocity by pitch number">']
    for t in ticks:
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>')
        out.append(f'<text x="{PAD_L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="axis">{t:g}</text>')
    step = 5 if x1 <= 40 else (10 if x1 <= 90 else 20)
    for t in range(0, x1 + 1, step):
        if t >= x0:
            out.append(f'<text x="{X(t):.1f}" y="{H - 22}" text-anchor="middle" class="axis">{t}</text>')
    out.append(f'<text x="{(PAD_L + W - PAD_R) / 2:.0f}" y="{H - 4}" text-anchor="middle" class="axis">pitch # in the outing</text>')
    out.append(f'<text x="{PAD_L - 40}" y="12" class="axis">mph</text>')
    if res.get("ok"):
        a, b = res["intercept"], res["slope"]
        out.append(f'<line x1="{X(x0):.1f}" y1="{Y(a + b * x0):.1f}" x2="{X(xs[-1]):.1f}" y2="{Y(a + b * xs[-1]):.1f}" '
                   'class="avg" style="stroke-dasharray:none;stroke-width:2;stroke:var(--gbo-text)"/>')
    for x, v, s in pts:
        tip = escape(f"Pitch {x}: {v:.1f} mph" + (f", {s:,.0f} rpm" if s is not None else ""))
        out.append(f'<g class="pt"><title>{tip}</title><circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="10" class="hit"/>'
                   f'<circle cx="{X(x):.1f}" cy="{Y(v):.1f}" r="4" class="dot"/></g>')
    out.append("</svg>")
    return "".join(out)


def season_svg(outings):
    """outings: velo_fade.by_outing() rows with ok fades. Bars of mph per 25 by date."""
    rows = [o for o in outings if o["fade"].get("ok") and o["date"] is not None]
    if not rows:
        return ""
    vals = [o["fade"]["per"] for o in rows]
    lo, hi = min(min(vals), -2.0), max(max(vals), 0.5)
    ticks = _nice_ticks(lo, hi)
    y0, y1 = ticks[0], ticks[-1]
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    n = len(rows)
    bw = min(36, iw / n * 0.6)

    def X(i):
        return PAD_L + iw * (i + 0.5) / n

    def Y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0))

    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Velo fade per outing">']
    for t in ticks:
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>')
        out.append(f'<text x="{PAD_L - 8}" y="{Y(t) + 4:.1f}" text-anchor="end" class="axis">{t:+g}</text>')
    out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" style="stroke:var(--gbo-text-muted);stroke-width:1.5"/>')
    for i, o in enumerate(rows):
        v = o["fade"]["per"]
        top, bot = (Y(v), Y(0)) if v >= 0 else (Y(0), Y(v))
        color = ("var(--gbo-status-good)" if v >= -0.5 else
                 ("var(--gbo-status-watch)" if v >= -1.5 else "var(--gbo-status-flag)"))
        tip = escape(f"{o['date'].strftime('%b %-d')} ({o['kind']}): {v:+.1f} mph per 25 pitches, "
                     f"{o['fade']['n']} fastballs")
        out.append(f'<g class="pt"><title>{tip}</title><rect x="{X(i) - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                   f'height="{max(bot - top, 1.5):.1f}" rx="3" style="fill:{color}"/></g>')
        if n <= 12 or i % max(1, n // 8) == 0:
            out.append(f'<text x="{X(i):.1f}" y="{H - 12}" text-anchor="middle" class="axis">'
                       f'{o["date"].strftime("%b %-d")}</text>')
    out.append(f'<text x="{PAD_L - 40}" y="12" class="axis">mph per 25 pitches</text>')
    out.append("</svg>")
    return "".join(out)
