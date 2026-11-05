"""
GBO -- Throwing Workload charts (inline SVG, same approach as the Hitting
tab's trend chart). Data: analytics/throwing_workload.py rows.
"""

import html

from analytics import throwing_workload as tw

MUTED = "var(--gbo-text-muted,#8A8A8E)"
GRID = "var(--gbo-border,#333)"
COLORS = {"game": "#BF1E2D", "bullpen": "#E07A5F", "logged": "#5B8DEF", "sensor": "#2E9C62", "assumed": "#8A8A8E"}
LABELS = {"game": "Game", "bullpen": "Bullpen", "logged": "Logged throws", "sensor": "Sensor", "assumed": "Assumed (not logged)"}
ZONE_COLORS = {"In range": "#2E9C62", "Watch": "#B58A22", "Outside": "#D94F3D"}


def _e(s):
    return html.escape(str(s))


def _frame(W, H, label):
    return [f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg" style="max-width:900px">',
            f'<text x="44" y="11" font-size="10" font-weight="700" style="fill:{MUTED}">{_e(label)}</text>']


def _yaxis(out, ticks, y, L, W, R, fmt=str):
    for t in ticks:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" style="stroke:{GRID}" stroke-width="1"/>'
                   f'<text x="{L - 4}" y="{y(t) + 3:.1f}" font-size="9" text-anchor="end" style="fill:{MUTED}">{_e(fmt(t))}</text>')


def _xlabels(out, rows, x, H, every):
    for i, r in enumerate(rows):
        if i % every == 0 or i == len(rows) - 1:
            out.append(f'<text x="{x(i):.1f}" y="{H - 6}" font-size="9" text-anchor="middle" style="fill:{MUTED}">'
                       f'{r["date"]:%b %d}</text>')


def legend(keys, extra=()):
    items = [f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
             f'<span style="width:10px;height:10px;border-radius:2px;background:{COLORS[k]};'
             f'opacity:{0.45 if k == "assumed" else 1}"></span>{_e(LABELS[k])}</span>' for k in keys]
    items += [f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
              f'<span style="width:14px;height:0;border-top:2px {style} {c}"></span>{_e(t)}</span>' for t, c, style in extra]
    return f'<div class="small text-muted" style="margin:4px 0 0 40px">{"".join(items)}</div>'


def daily_svg(rows):
    """Stacked daily throws + acute (9-day) and chronic (28-day) average lines."""
    if not rows:
        return ""
    W, H, L, R, T, B = 900, 230, 44, 10, 18, 22
    n = len(rows)
    top = max([r["total"] for r in rows] + [r["acute"] or 0 for r in rows] + [r["chronic"] or 0 for r in rows] + [50])
    top = int((top * 1.1 + 24) // 25 * 25)
    bw = max(2.0, (W - L - R) / n * 0.72)
    x = lambda i: L + (W - L - R) * (i + 0.5) / n  # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - v / top)  # noqa: E731
    out = _frame(W, H, "THROWS PER DAY")
    _yaxis(out, [0, top // 2, top], y, L, W, R)
    for i, r in enumerate(rows):
        if not r["tracked"]:
            continue
        base = 0
        tip = [f'{r["date"]:%a %b %d}: {r["total"]} throws']
        for k in tw.PARTS:
            v = r[k]
            if not v:
                continue
            tip.append(f"{LABELS[k]} {v}")
            op = 0.45 if k == "assumed" else 0.95
            out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y(base + v):.1f}" width="{bw:.1f}" '
                       f'height="{y(base) - y(base + v):.1f}" fill="{COLORS[k]}" opacity="{op}"/>')
            base += v
        if r["acute"] is not None:
            tip.append(f"9-day avg {r['acute']}/day · 28-day avg {r['chronic']}/day")
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{T}" width="{bw:.1f}" height="{H - T - B}" fill="transparent">'
                   f'<title>{_e(" · ".join(tip))}</title></rect>')
    for key, color, dash in (("chronic", "#9AA5B1", "5 3"), ("acute", "#E9C46A", "")):
        pts = [(i, r[key]) for i, r in enumerate(rows) if r[key] is not None]
        if len(pts) >= 2:
            d = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for j, (i, v) in enumerate(pts))
            out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2"'
                       + (f' stroke-dasharray="{dash}"' if dash else "") + '/>')
    _xlabels(out, rows, x, H, max(1, n // 8))
    out.append("</svg>")
    return "".join(out) + legend(tw.PARTS, [("9-day avg / day", "#E9C46A", "solid"),
                                            ("28-day avg / day", "#9AA5B1", "dashed")])


def ratio_svg(rows):
    """Acute:chronic ratio over the bands. Hollow points = under 4 weeks of history."""
    pts = [(i, r) for i, r in enumerate(rows) if r["ratio"] is not None]
    if len(pts) < 2:
        return ""
    W, H, L, R, T, B = 900, 190, 44, 10, 18, 22
    lo, hi = 0.4, 1.8
    n = len(rows)
    x = lambda i: L + (W - L - R) * (i + 0.5) / n  # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - (min(max(v, lo), hi) - lo) / (hi - lo))  # noqa: E731
    out = _frame(W, H, "ACUTE : CHRONIC (9-DAY vs 28-DAY)")
    for a, b, c, op in ((lo, 0.7, "#D94F3D", .10), (0.7, 0.8, "#B58A22", .16), (0.8, 1.2, "#2E9C62", .16),
                        (1.2, 1.3, "#B58A22", .16), (1.3, hi, "#D94F3D", .10)):
        out.append(f'<rect x="{L}" y="{y(b):.1f}" width="{W - L - R}" height="{y(a) - y(b):.1f}" fill="{c}" opacity="{op}"/>')
    _yaxis(out, [0.4, 0.8, 1.0, 1.2, 1.8], y, L, W, R, fmt=lambda t: f"{t:.1f}")
    d = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(r['ratio']):.1f}" for j, (i, r) in enumerate(pts))
    out.append(f'<path d="{d}" fill="none" style="stroke:var(--gbo-text,#ddd)" stroke-width="1.8"/>')
    for i, r in pts:
        c = ZONE_COLORS.get(r["zone"], "#8A8A8E")
        fill = c if r["full_history"] else "none"
        note = "" if r["full_history"] else " (building history -- under 4 weeks)"
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(r["ratio"]):.1f}" r="3.2" fill="{fill}" stroke="{c}" stroke-width="1.5">'
                   f'<title>{r["date"]:%a %b %d}: {r["ratio"]:.2f} {_e(r["zone"])}{_e(note)}</title></circle>')
    _xlabels(out, rows, x, H, max(1, n // 8))
    out.append("</svg>")
    return "".join(out)


def weekly_svg(weeks):
    """Weekly totals vs the 500-700 range and the pro starter / reliever medians."""
    if not weeks:
        return ""
    W, H, L, R, T, B = 900, 210, 44, 120, 18, 22
    n = len(weeks)
    top = max([w["total"] for w in weeks] + [tw.BENCH_WEEK_RANGE[1] + 50])
    top = int((top * 1.05 + 99) // 100 * 100)
    bw = (W - L - R) / n * 0.6
    x = lambda i: L + (W - L - R) * (i + 0.5) / n  # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - v / top)  # noqa: E731
    out = _frame(W, H, "THROWS PER WEEK (MON-SUN)")
    a, b = tw.BENCH_WEEK_RANGE
    out.append(f'<rect x="{L}" y="{y(b):.1f}" width="{W - L - R}" height="{y(a) - y(b):.1f}" fill="#2E9C62" opacity=".12"/>')
    step = 250 if top > 600 else 100
    _yaxis(out, list(range(0, top + 1, step)), y, L, W, R)
    for i, w in enumerate(weeks):
        real = w["total"] - w["assumed"]
        partial = w["days"] < 7
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y(real):.1f}" width="{bw:.1f}" height="{y(0) - y(real):.1f}" '
                   f'fill="#5B8DEF" opacity="{0.55 if partial else 0.95}"/>')
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{y(w["total"]):.1f}" width="{bw:.1f}" '
                   f'height="{y(real) - y(w["total"]):.1f}" fill="#8A8A8E" opacity=".45"/>')
        tip = (f'Week of {w["week_start"]:%b %d}: {w["total"]} throws ({w["assumed"]} assumed)'
               + (f" -- only {w['days']} days so far" if partial else ""))
        out.append(f'<rect x="{x(i) - bw / 2:.1f}" y="{T}" width="{bw:.1f}" height="{H - T - B}" fill="transparent">'
                   f'<title>{_e(tip)}</title></rect>'
                   f'<text x="{x(i):.1f}" y="{H - 6}" font-size="9" text-anchor="middle" style="fill:{MUTED}">'
                   f'{w["week_start"]:%b %d}</text>')
    for v, lab, c in ((tw.BENCH_SP_WEEK["MLB"], "MLB SP median 665", "#BF1E2D"),
                      (tw.BENCH_SP_WEEK["A"], "A-ball SP median 595", "#E07A5F"),
                      (tw.BENCH_RP_WEEK, "Pro RP median ~490", "#9AA5B1")):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{c}" stroke-dasharray="5 3" '
                   f'stroke-width="1.4"/><text x="{W - R + 4}" y="{y(v) + 3:.1f}" font-size="9" style="fill:{c}">{_e(lab)}</text>')
    out.append(f'<text x="{L + 4}" y="{y(a) - 4:.1f}" font-size="9" style="fill:#2E9C62">500-700 a week once built up (Sigman)</text>')
    out.append("</svg>")
    key = ('<div class="small text-muted" style="margin:4px 0 0 40px">'
           '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:#5B8DEF;margin-right:4px"></span>'
           'Counted (pitches, logs, sensor)<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
           'background:#8A8A8E;opacity:.45;margin:0 4px 0 12px"></span>Assumed · lighter bar = week still in progress</div>')
    return "".join(out) + key
