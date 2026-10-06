"""
GBO -- one-test progress chart for My Assessments (Oct 2026, Ryker: "make
the my assessments page better for player login"; approved: "pick any test
and see a line of every result over time").

Plain inline SVG (no plotly/kaleido render) so it's instant and follows the
dark/light toggle through CSS custom properties. One series: the player's
results, 2px line, 9px dots, the latest value labeled directly, every dot
has a hover tooltip. Optional dashed team-average reference line, labeled.
"""

import math
from html import escape

W, H = 640, 220
PAD_L, PAD_R, PAD_T, PAD_B = 52, 132, 18, 34


def _fmt(v, unit):
    if unit == "s":
        return f"{v:.2f}s"
    if unit == "kcal":
        return f"{v:,.0f} kcal"
    if unit in ("°", "%"):
        return f"{v:.1f}{unit}"
    return f"{v:.1f} {unit}".strip()


def _nice_ticks(lo, hi, n=4):
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + step * 0.001:
        ticks.append(round(t, 10))
        t += step
    if ticks[-1] < hi:
        ticks.append(ticks[-1] + step)
    return ticks


def render_svg(points, unit="", team_avg=None, name=""):
    """points: [(date, value)] oldest first. Returns an SVG string."""
    if not points:
        return ""
    vals = [v for _, v in points] + ([team_avg] if team_avg is not None else [])
    ticks = _nice_ticks(min(vals), max(vals))
    y0, y1 = ticks[0], ticks[-1]
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    days = [(d - points[0][0]).days for d, _ in points]
    span = max(days[-1], 1)

    def X(i):
        return PAD_L + (iw / 2 if len(points) == 1 else iw * days[i] / span)

    def Y(v):
        return PAD_T + ih * (1 - (v - y0) / (y1 - y0))

    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" '
           f'aria-label="{escape(name)} over time">']
    for t in ticks:
        y = Y(t)
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        lbl = f"{t:.2f}" if unit == "s" else (f"{t:,.0f}" if abs(t) >= 100 or float(t).is_integer() else f"{t:.1f}")
        out.append(f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" class="axis">{lbl}</text>')

    if team_avg is not None:
        y = Y(team_avg)
        out.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="avg"/>')
        out.append(f'<text x="{W - PAD_R + 6}" y="{y + 4:.1f}" class="avg-lbl">Team avg {_fmt(team_avg, unit)}</text>')

    # x labels: every point if few, else first / last and a few between
    idx = list(range(len(points)))
    if len(points) > 6:
        step = (len(points) - 1) / 5
        idx = sorted({round(k * step) for k in range(6)})
    for i in idx:
        out.append(f'<text x="{X(i):.1f}" y="{H - 10}" text-anchor="middle" class="axis">'
                   + points[i][0].strftime("%b %-d '%y") + '</text>')

    if len(points) > 1:
        path = " ".join(f'{"M" if i == 0 else "L"}{X(i):.1f},{Y(v):.1f}' for i, (_, v) in enumerate(points))
        out.append(f'<path d="{path}" class="line"/>')
    for i, (d, v) in enumerate(points):
        tip = escape(f'{d.strftime("%b %-d, %Y")}: {_fmt(v, unit)}')
        out.append(f'<g class="pt"><title>{tip}</title><circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="12" class="hit"/>'
                   f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4.5" class="dot"/></g>')
    lx, ly = X(len(points) - 1), Y(points[-1][1])
    out.append(f'<text x="{lx + 10:.1f}" y="{ly - 8:.1f}" class="last">{escape(_fmt(points[-1][1], unit))}</text>')
    out.append("</svg>")
    return "".join(out)


