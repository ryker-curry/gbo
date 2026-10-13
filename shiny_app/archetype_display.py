"""
GBO -- Athlete archetype card (analytics/athlete_archetype.py) and the
mobility -> stability -> strength ladder (analytics/training_stage.py).
Plain HTML strings.
"""

import html
import math

from analytics.athlete_archetype import _ord

FORCE_C, VELO_C, HYB_C = "#E07A3C", "#2BB3A3", "#8E7CC3"
KIND_C = {"Elastic": VELO_C, "Muscular": FORCE_C, "Hybrid": HYB_C}


def _e(s):
    return html.escape(str(s))


def _radar(metrics):
    n = len(metrics)
    if n < 3:
        return ""
    W = H = 280
    cx, cy, R = W / 2, H / 2, 92

    def pt(i, r):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * math.cos(a), cy + r * math.sin(a)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:300px" xmlns="http://www.w3.org/2000/svg">']
    for ring in (25, 50, 75, 100):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, R * ring / 100) for i in range(n)))
        dash = ' stroke-dasharray="3 3"' if ring == 50 else ""
        op = .25 if ring == 50 else .1
        parts.append(f'<polygon points="{pts}" fill="none" stroke="rgba(255,255,255,{op})"{dash}/>')
    for i in range(n):
        x, y = pt(i, R)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="rgba(255,255,255,.08)"/>')
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, R * max(m['pct'], 4) / 100) for i, m in enumerate(metrics)))
    parts.append(f'<polygon points="{pts}" fill="rgba(233,160,60,.28)" stroke="#E9A03C" stroke-width="2"/>')
    for i, m in enumerate(metrics):
        x, y = pt(i, R * max(m["pct"], 4) / 100)
        c = VELO_C if m["side"] == "velocity" else FORCE_C
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{c}"><title>{_e(m["label"])}: {m["pct"]}th</title></circle>')
        lx, ly = pt(i, R + 26)
        anchor = "middle" if abs(lx - cx) < 12 else ("start" if lx > cx else "end")
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="9" text-anchor="{anchor}" fill="#c9cfd8">{_e(m["label"])}</text>')
        parts.append(f'<text x="{lx:.1f}" y="{ly + 10:.1f}" font-size="9" font-weight="700" text-anchor="{anchor}" fill="{c}">'
                     f'{m["pct"]}</text>')
    parts.append("</svg>")
    return "".join(parts)


def archetype_card(prof):
    if prof is None:
        return ('<div class="gbo-seq-sec"><h6 class="gbo-seq-h">Athlete archetype</h6><p class="small text-muted">'
                "Needs at least one force test (CMJ mean force, impulse, mid-thigh pull...) and one speed/spring test "
                "(jump height, RSI-mod, hop RSI...), each taken by 6+ teammates.</p></div>")
    k = prof["kind"]
    c = KIND_C[k]
    pos = max(0, min(100, 50 + prof["index"] * 50))
    spectrum = (f'<div style="margin:6px 0 2px;display:flex;justify-content:space-between;font-size:.66rem;font-weight:700">'
                f'<span style="color:{FORCE_C}">MUSCULAR · FORCE-DRIVEN</span><span style="color:{HYB_C}">HYBRID</span>'
                f'<span style="color:{VELO_C}">ELASTIC · VELOCITY-DRIVEN</span></div>'
                f'<div style="position:relative;height:8px;border-radius:4px;background:linear-gradient(90deg,{FORCE_C},{HYB_C},{VELO_C})">'
                f'<div style="position:absolute;left:calc({pos:.0f}% - 8px);top:-5px;width:16px;height:16px;border-radius:50%;'
                f'background:#fff;border:3px solid {c}"></div></div>')
    sides = "".join(
        f'<div style="flex:1 1 180px"><div style="font-size:.7rem;font-weight:700;color:{col};border-bottom:2px solid {col};'
        f'margin-bottom:4px">{lbl} · {_ord(pct)} pct</div>'
        + "".join(f'<div style="display:flex;justify-content:space-between;font-size:.8rem"><span>{_e(m["label"])}</span>'
                  f'<b>{m["pct"]}</b></div><div style="height:5px;border-radius:3px;background:rgba(255,255,255,.08);'
                  f'margin-bottom:5px"><div style="height:5px;border-radius:3px;width:{max(m["pct"], 3)}%;background:{col}"></div></div>'
                  for m in prof["metrics"] if m["side"] == side) + "</div>"
        for side, lbl, col, pct in (("force", "FORCE SIDE", FORCE_C, prof["force"]),
                                    ("velocity", "VELOCITY SIDE", VELO_C, prof["velocity"])))
    lines = "".join(f"<li>{_e(x)}</li>" for x in prof["lines"])
    return (f'<div class="gbo-seq-sec"><h6 class="gbo-seq-h">Athlete archetype <span style="background:{c};color:#111;'
            f'padding:1px 8px;border-radius:6px;font-size:.75rem;margin-left:6px">{k.upper()}</span></h6>'
            f'<p class="text-muted small gbo-seq-how">How he produces power, from his jump and force tests as team '
            f'percentiles (Georgia Southern\'s archetype report). Force tests are per pound of body weight. Spectrum index '
            f'{prof["index"]:+.2f} · overall output {_ord(prof["output"])} percentile. Snapshot of his latest tests -- a '
            f'readiness trend needs regular jump testing.</p>'
            f'<div style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start"><div style="flex:0 1 300px">'
            f'{_radar(prof["metrics"])}</div><div style="flex:1 1 300px">{spectrum}'
            f'<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:12px">{sides}</div>'
            f'<ul class="small" style="margin:8px 0 0 18px;padding:0">{lines}</ul></div></div></div>')


STAGE_C = {"limiter": "#D64545", "ok": "#3FB27F", "untested": "#7A8594"}


def ladder_card(lad):
    """Mobility -> Stability -> Strength ladder (analytics/training_stage.py)."""
    if lad is None:
        return ""
    steps = []
    for i, st in enumerate(lad["stages"]):
        c = STAGE_C[st["status"]]
        label = {"limiter": "Start here" if st["name"] == lad["start"] else "Below staff",
                 "ok": "In place", "untested": "Not tested"}[st["status"]]
        ev = "".join(f"<li>{_e(x)}</li>" for x in st["evidence"])
        steps.append(
            f'<div style="flex:1 1 200px;border:1px solid {c};border-radius:10px;padding:8px 10px;'
            f'{"box-shadow:0 0 0 2px " + c + ";" if st["name"] == lad["start"] else ""}">'
            f'<div style="font-size:.7rem;color:var(--gbo-text-muted)">STEP {i + 1}</div>'
            f'<div style="font-weight:700">{_e(st["name"])} <span style="color:{c};font-size:.75rem">· {label}</span></div>'
            f'<div class="small text-muted">{_e(st["question"])}</div><ul class="small" style="margin:4px 0 0 16px;padding:0">{ev}</ul></div>')
    return (f'<div class="gbo-seq-sec"><h6 class="gbo-seq-h">Training order: mobility → stability → strength</h6>'
            f'<p class="text-muted small gbo-seq-how">Samuel Midgette\'s progression: each stage builds on the one before, '
            f'so the first one below staff (z ≤ -0.5) is where training should start. Stability here = lead-leg, '
            f'scapular and decel-side tests; a strength gain he can\'t control in his positions won\'t transfer.</p>'
            f'<div style="display:flex;gap:10px;flex-wrap:wrap">{"".join(steps)}</div>'
            f'<p class="small" style="margin:8px 0 0">{_e(lad["read"])}</p></div>')
