"""Rolling in-zone whiff % line (analytics/zone_whiff.py). Inline SVG,
same .gbo-progress-svg classes as progress_chart.py."""

from html import escape

W, H, L, R, T, B = 640, 210, 44, 120, 14, 34


def svg(res, window):
    pts = res["points"]
    if not pts:
        return ""
    vals = [v for _i, v in pts] + [res["base"]]
    y0, y1 = 0.0, max(40.0, min(100.0, max(vals) + 10))
    x0, x1 = pts[0][0], max(pts[-1][0], pts[0][0] + 1)

    def X(i):
        return L + (W - L - R) * (i - x0) / (x1 - x0)

    def Y(v):
        return T + (H - T - B) * (1 - (v - y0) / (y1 - y0))
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Rolling in-zone whiff percent">']
    for t in range(0, int(y1) + 1, 10 if y1 <= 60 else 20):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(t) + 4:.1f}" text-anchor="end" class="axis">{t}%</text>')
    b = res["base"]
    out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(b):.1f}" y2="{Y(b):.1f}" class="avg"/>'
               f'<text x="{W - R + 6}" y="{Y(b) + 4:.1f}" class="avg-lbl">His normal {b:.0f}%</text>')
    flag = b + 10
    if flag < y1:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(flag):.1f}" y2="{Y(flag):.1f}" '
                   'style="stroke:var(--gbo-status-flag);stroke-width:1;stroke-dasharray:2 4"/>'
                   f'<text x="{W - R + 6}" y="{Y(flag) + 4:.1f}" class="avg-lbl" style="fill:var(--gbo-status-flag)">Flag line</text>')
    path = " ".join(f'{"M" if k == 0 else "L"}{X(i):.1f},{Y(v):.1f}' for k, (i, v) in enumerate(pts))
    out.append(f'<path d="{path}" class="line"/>')
    i, v = pts[-1]
    out.append(f'<g class="pt"><title>{escape(f"Last {window} zone swings: {v:.0f}% whiffs")}</title>'
               f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="4.5" class="dot"/></g>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 6}" text-anchor="middle" class="axis">in-zone swings this range '
               f'(each point = his last {window})</text>')
    out.append("</svg>")
    return "".join(out)
