"""
GBO -- SVG charts for Athlete vs Performance (Nov 2026, Ryker). Data:
analytics/athlete_performance.py. Plain SVG strings like release_graphics.py
(no kaleido / plotly.js), <title> hover text on every point.

  change_scatter_svg  team view: x = change in a physical test (% improved,
                      flipped for lower-is-better tests), y = change in a
                      fastball number; four labelled quadrants, OLS line.
  path_svg            one player: x = test value, y = fastball number, one
                      point per testing period, arrows oldest -> newest.
"""

from html import escape

from career_development_display import _ticks

TEXT = "var(--gbo-text)"
MUTED = "var(--gbo-text-muted)"
GRID = "var(--gbo-border)"
ACCENT = "var(--gbo-crimson)"
DOT = "var(--gbo-text-2)"
GOOD = "var(--gbo-status-good)"
FLAG = "var(--gbo-status-flag)"
WATCH = "var(--gbo-status-watch)"

QUAD_COLOR = {"Both up": GOOD, "Both down": FLAG, "Stronger, velo down": WATCH, "Test down, velo up": WATCH}


def _axes(x, y, xs, ys, x0, x1, y0, y1, xlabel, ylabel, h):
    p = []
    for v in ys:
        p.append(f'<line x1="{x0}" x2="{x1}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}"/>'
                 f'<text x="{x0 - 6}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="11" fill="{MUTED}">{v:g}</text>')
    for v in xs:
        p.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{y0}" y2="{y1}" stroke="{GRID}"/>'
                 f'<text x="{x(v):.1f}" y="{y0 + 16}" text-anchor="middle" font-size="11" fill="{MUTED}">{v:g}</text>')
    p.append(f'<text x="{x1}" y="{h - 4}" text-anchor="end" font-size="11" fill="{MUTED}">{escape(xlabel)}</text>'
             f'<text x="{x0 + 4}" y="{y1 + 12}" font-size="11" fill="{MUTED}">{escape(ylabel)}</text>')
    return "".join(p)


def change_scatter_svg(pts, line, xlabel, ylabel, neutral=False, highlight=None, y_unit="mph"):
    if not pts:
        return None
    w, h, ml, mr, mt, mb = 640, 420, 48, 16, 16, 38
    xa = max(5.0, max(abs(p["x"]) for p in pts) * 1.15)
    ya = max(1.0, max(abs(p["y"]) for p in pts) * 1.15)
    x = lambda v: ml + (v + xa) / (2 * xa) * (w - ml - mr)
    y = lambda v: h - mb - (v + ya) / (2 * ya) * (h - mt - mb)
    out = [_axes(x, y, _ticks(-xa, xa, 6), _ticks(-ya, ya, 6), ml, w - mr, h - mb, mt, xlabel, ylabel, h)]
    # quadrant tint + labels
    q = ([("Test up, velo up", w - mr - 6, mt + 28, "end", None), ("Test down, velo up", ml + 6, mt + 28, "start", None),
          ("Test down, velo down", ml + 6, h - mb - 8, "start", None), ("Test up, velo down", w - mr - 6, h - mb - 8, "end", None)]
         if neutral else
         [("Both up", w - mr - 6, mt + 28, "end", GOOD), ("Test down, velo up", ml + 6, mt + 28, "start", WATCH),
          ("Both down", ml + 6, h - mb - 8, "start", FLAG), ("Stronger, velo down", w - mr - 6, h - mb - 8, "end", WATCH)])
    if not neutral:
        out.append(f'<rect x="{ml}" y="{y(0):.1f}" width="{x(0) - ml:.1f}" height="{h - mb - y(0):.1f}" fill="{FLAG}" opacity="0.07"/>'
                   f'<rect x="{x(0):.1f}" y="{mt}" width="{w - mr - x(0):.1f}" height="{y(0) - mt:.1f}" fill="{GOOD}" opacity="0.07"/>')
    for label, tx, ty, anchor, col in q:
        out.append(f'<text x="{tx}" y="{ty}" text-anchor="{anchor}" font-size="12" font-weight="600" fill="{col or MUTED}">{label}</text>')
    out.append(f'<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{mt}" y2="{h - mb}" stroke="{MUTED}"/>'
               f'<line x1="{ml}" x2="{w - mr}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{MUTED}"/>')
    if line:
        x1, x2 = -xa, xa
        y1, y2 = line["intercept"] + line["slope"] * x1, line["intercept"] + line["slope"] * x2
        y1, y2 = max(-ya, min(ya, y1)), max(-ya, min(ya, y2))
        xx1 = (y1 - line["intercept"]) / line["slope"] if line["slope"] else x1
        xx2 = (y2 - line["intercept"]) / line["slope"] if line["slope"] else x2
        out.append(f'<line x1="{x(max(-xa, xx1)):.1f}" y1="{y(y1):.1f}" x2="{x(min(xa, xx2)):.1f}" y2="{y(y2):.1f}" '
                   f'stroke="{TEXT}" stroke-opacity="0.45" stroke-width="2" stroke-dasharray="6 4"/>')
    for p in sorted(pts, key=lambda p: p["pid"] == highlight):
        hi = p["pid"] == highlight
        c = ACCENT if hi else QUAD_COLOR.get(p["quad"], DOT)
        t = p["test"]
        tip = (f'{p["name"]} -- {p["quad"]}\nTest: {t["v1"]:.2f} -> {t["v2"]:.2f} ({p["x"]:+.1f}%)\n'
               f'{ylabel}: {p["perf"]["v1"]:.1f} -> {p["perf"]["v2"]:.1f} ({p["y"]:+.1f} {y_unit})')
        weight = ' font-weight="600"' if hi else ""
        out.append(f'<circle cx="{x(p["x"]):.1f}" cy="{y(p["y"]):.1f}" r="{7 if hi else 5}" fill="{c}" fill-opacity="0.85" '
                   f'stroke="var(--gbo-bg-card)" stroke-width="1.5"><title>{escape(tip)}</title></circle>'
                   f'<text x="{x(p["x"]) + 8:.1f}" y="{y(p["y"]) + 4:.1f}" font-size="11" fill="{TEXT if hi else MUTED}"'
                   f'{weight}>{escape(p["last"])}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Change in test vs change on the mound">{"".join(out)}</svg>'


def path_svg(points, xlabel, ylabel, x_dp=2, y_dp=1):
    """points: [(period, x, y)] oldest first."""
    pts = [p for p in points if p[1] is not None and p[2] is not None]
    if not pts:
        return None
    w, h, ml, mr, mt, mb = 520, 300, 48, 20, 16, 38
    xs, ys = [p[1] for p in pts], [p[2] for p in pts]
    px = (max(xs) - min(xs)) * 0.2 or abs(xs[0]) * 0.05 or 1
    py = (max(ys) - min(ys)) * 0.2 or 1
    lo_x, hi_x, lo_y, hi_y = min(xs) - px, max(xs) + px, min(ys) - py, max(ys) + py
    x = lambda v: ml + (v - lo_x) / (hi_x - lo_x) * (w - ml - mr)
    y = lambda v: h - mb - (v - lo_y) / (hi_y - lo_y) * (h - mt - mb)
    out = [_axes(x, y, _ticks(lo_x, hi_x, 5), _ticks(lo_y, hi_y, 5), ml, w - mr, h - mb, mt, xlabel, ylabel, h),
           f'<defs><marker id="ap-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
           f'<path d="M0,0L10,5L0,10z" fill="{ACCENT}"/></marker></defs>']
    for (p1, x1, y1), (p2, x2, y2) in zip(pts, pts[1:]):
        out.append(f'<line x1="{x(x1):.1f}" y1="{y(y1):.1f}" x2="{x(x2):.1f}" y2="{y(y2):.1f}" stroke="{ACCENT}" '
                   f'stroke-width="2.5" stroke-linecap="round" marker-end="url(#ap-arr)"/>')
    for i, (per, xv, yv) in enumerate(pts):
        last = i == len(pts) - 1
        out.append(f'<circle cx="{x(xv):.1f}" cy="{y(yv):.1f}" r="6" fill="{ACCENT if last else "var(--gbo-bg-card)"}" '
                   f'stroke="{ACCENT}" stroke-width="2"><title>{escape(per)}: {xv:.{x_dp}f} / {yv:.{y_dp}f}</title></circle>'
                   f'<text x="{x(xv):.1f}" y="{y(yv) - 10:.1f}" text-anchor="middle" font-size="11" font-weight="600" fill="{TEXT}">{escape(per)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Development path">{"".join(out)}</svg>'
