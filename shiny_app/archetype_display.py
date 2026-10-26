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
    """GS-style radar: Jump Ht at the top, velocity-driven metrics down the
    right, force-driven down the left; the team average (50th percentile)
    as a dashed ring, his shape on top, each point colored red (low) ->
    amber -> green (high)."""
    n = len(metrics)
    if n < 3:
        return ""
    W, H = 320, 300
    cx, cy, R = W / 2, 150, 100

    def pt(i, r):
        a = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * math.cos(a), cy + r * math.sin(a)

    def heat(p):
        return "#D64545" if p < 34 else ("#E9A03C" if p < 67 else "#3FB27F")

    parts = [f'<svg viewBox="-60 0 {W + 120} {H + 24}" width="100%" style="max-width:400px" xmlns="http://www.w3.org/2000/svg">',
             f'<path d="M{cx},{cy - R - 6} A{R + 6},{R + 6} 0 0,0 {cx},{cy + R + 6} Z" fill="{FORCE_C}" opacity=".07"/>',
             f'<path d="M{cx},{cy - R - 6} A{R + 6},{R + 6} 0 0,1 {cx},{cy + R + 6} Z" fill="{VELO_C}" opacity=".07"/>']
    for ring in (25, 50, 75, 100):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, R * ring / 100) for i in range(n)))
        dash = ' stroke-dasharray="4 3" stroke-width="1.5"' if ring == 50 else ""
        parts.append(f'<polygon points="{pts}" fill="none" style="stroke:var(--gbo-text-muted,#8A8A8E)" stroke-opacity="{.7 if ring == 50 else .25}"{dash}/>')
    for i in range(n):
        x, y = pt(i, R)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" style="stroke:var(--gbo-text-muted,#8A8A8E)" stroke-opacity=".2"/>')
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, R * max(m['pct'], 4) / 100) for i, m in enumerate(metrics)))
    parts.append(f'<polygon points="{pts}" fill="rgba(233,160,60,.25)" stroke="#E9A03C" stroke-width="2"/>')
    for i, m in enumerate(metrics):
        x, y = pt(i, R * max(m["pct"], 4) / 100)
        sub = " (substitute)" if m.get("substitute") else ""
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="{heat(m["pct"])}" stroke="#111" stroke-width="1">'
                     f'<title>{_e(m["label"])}{sub}: {_ord(m["pct"])} percentile</title></circle>')
        lx, ly = pt(i, R + 22)
        anchor = "middle" if abs(lx - cx) < 12 else ("start" if lx > cx else "end")
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="9.5" text-anchor="{anchor}" style="fill:var(--gbo-text-muted,#8A8A8E)">'
                     f'{_e(m["label"].upper())}{"*" if m.get("substitute") else ""}</text>')
        parts.append(f'<text x="{lx:.1f}" y="{ly + 11:.1f}" font-size="10" font-weight="700" text-anchor="{anchor}" '
                     f'fill="{heat(m["pct"])}">{_ord(m["pct"])}</text>')
    parts.append(f'<text x="-52" y="{H + 16}" font-size="10" font-weight="700" letter-spacing="1.5" fill="{FORCE_C}">FORCE-DRIVEN</text>')
    parts.append(f'<text x="{W + 52}" y="{H + 16}" font-size="10" font-weight="700" letter-spacing="1.5" text-anchor="end" '
                 f'fill="{VELO_C}">VELOCITY-DRIVEN</text>')
    parts.append("</svg>")
    return "".join(parts)


def _training(kind):
    from analytics.athlete_archetype import TRAINING
    t = TRAINING.get(kind)
    if not t:
        return ""
    items = "".join(f"<li>{_e(x)}</li>" for x in t["do"])
    return (f'<div style="margin-top:10px;border-left:3px solid {KIND_C[kind]};padding-left:10px">'
            f'<div style="font-size:.7rem;font-weight:700;letter-spacing:.06em">TRAINING FOCUS: {_e(t["focus"]).upper()}</div>'
            f'<ul class="small" style="margin:4px 0 0 18px;padding:0">{items}</ul>'
            f'<div class="small text-muted">Retest: {_e(t["retest"])}. General tendencies by type -- the strength '
            f'staff makes the call.</div></div>')


def _side_bars(prof):
    from analytics.athlete_archetype import FORCE_SIDE, VELO_SIDE
    by = {m["key"]: m for m in prof["metrics"]}
    cols = []
    for keys, lbl, col, pct in ((FORCE_SIDE, "FORCE SIDE", FORCE_C, prof["force"]),
                                (VELO_SIDE, "VELOCITY SIDE", VELO_C, prof["velocity"])):
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;font-size:.8rem"><span>{_e(by[k]["label"])}'
            f'{"*" if by[k].get("substitute") else ""}</span><b>{_ord(by[k]["pct"])}</b></div>'
            f'<div style="height:5px;border-radius:3px;background:rgba(255,255,255,.08);margin-bottom:6px">'
            f'<div style="height:5px;border-radius:3px;width:{max(by[k]["pct"], 3)}%;background:{col}"></div></div>'
            for k in keys if k in by)
        cols.append(f'<div style="flex:1 1 170px"><div style="display:flex;justify-content:space-between;font-size:.7rem;'
                    f'font-weight:700;color:{col};border-bottom:2px solid {col};margin-bottom:5px"><span>{lbl}</span>'
                    f'<span>{_ord(pct)} PCT</span></div>{rows}</div>')
    return f'<div style="display:flex;flex-wrap:wrap;gap:14px;margin-top:12px">{"".join(cols)}</div>'


def _spectrum(prof):
    c = KIND_C[prof["kind"]]
    pos = max(0, min(100, 50 + prof["index"] * 50))
    return (f'<div style="font-size:.7rem;font-weight:700;letter-spacing:.06em;margin-top:10px">WHERE HE SITS ON THE SPECTRUM</div>'
            f'<div style="margin:4px 0 2px;display:flex;justify-content:space-between;font-size:.64rem;font-weight:700">'
            f'<span style="color:{FORCE_C}">MUSCULAR · FORCE-DRIVEN</span><span style="color:{HYB_C}">HYBRID</span>'
            f'<span style="color:{VELO_C}">ELASTIC · VELOCITY-DRIVEN</span></div>'
            f'<div style="position:relative;height:8px;border-radius:4px;background:linear-gradient(90deg,{FORCE_C},{HYB_C},{VELO_C})">'
            f'<div title="team average" style="position:absolute;left:50%;top:-4px;width:2px;height:16px;background:rgba(255,255,255,.6)"></div>'
            f'<div style="position:absolute;left:calc({pos:.0f}% - 8px);top:-5px;width:16px;height:16px;border-radius:50%;'
            f'background:#fff;border:3px solid {c}"></div></div>'
            f'<div style="font-size:.64rem;color:var(--gbo-text-muted);text-align:center;margin-top:3px">team average</div>')


def _signature(prof):
    lean_c = {"muscular": FORCE_C, "elastic": VELO_C, "neutral": HYB_C}
    cells = []
    for s in prof["signature"]:
        # dot: left = muscular, right = elastic (s["m"] = how far toward muscular, 0-100)
        x = max(3, min(97, 100 - s["m"]))
        c = lean_c[s["lean"]]
        cells.append(
            f'<div style="display:flex;align-items:center;gap:8px;min-width:0">'
            f'<div style="width:110px;font-size:.78rem">{_e(s["label"])}{"*" if s.get("substitute") else ""}</div>'
            f'<div style="flex:1;min-width:90px"><div style="position:relative;height:8px;border-radius:4px;'
            f'background:linear-gradient(90deg,rgba(224,122,60,.35),rgba(255,255,255,.08),rgba(43,179,163,.35))">'
            f'<div style="position:absolute;left:50%;top:-3px;width:2px;height:14px;background:var(--gbo-text-muted,#8A8A8E)"></div>'
            f'<div style="position:absolute;left:calc({x:.0f}% - 5px);top:-2px;width:12px;height:12px;border-radius:50%;'
            f'background:{c};border:2px solid #fff"></div></div>'
            f'<div style="font-size:.64rem;color:var(--gbo-text-muted)">{_e(s["text"])}</div></div>'
            f'<div style="width:62px;font-size:.66rem;font-weight:700;color:{c}">{s["lean"].upper()}</div></div>')
    k = prof["counts"]
    return (f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:12px">'
            f'<div style="font-size:.7rem;font-weight:700;letter-spacing:.06em">FORCE-PLATE SIGNATURE</div>'
            f'<div class="small"><b style="color:{FORCE_C}">{k["muscular"]}</b> muscular · '
            f'<b style="color:{VELO_C}">{k["elastic"]}</b> elastic · {k["neutral"]} neutral</div></div>'
            f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:6px 18px;margin-top:6px">{"".join(cells)}</div>'
            f'<div class="small text-muted" style="margin-top:4px">Each row compares him to the team. Left of center points '
            f'muscular (deeper dip, longer time to takeoff, more braking and push force per pound); right of center points '
            f'elastic (more spring, speed, height and power per pound). Every row is a timing measure or per pound of body '
            f'weight, so a bigger or stronger athlete does not automatically read muscular.</div>')


def _table(kind, is_pitcher):
    from analytics.athlete_archetype import IN_THE_BOX, ON_THE_MOUND
    t = ON_THE_MOUND if is_pitcher else IN_THE_BOX
    title = "On the mound: how each archetype pitches" if is_pitcher else "In the box: how each archetype hits"
    head = "".join(f'<th style="color:{KIND_C[k]};{"background:rgba(255,255,255,.06);" if k == kind else ""}">{k.upper()}</th>'
                   for k in ("Muscular", "Hybrid", "Elastic"))
    rows = []
    for i, r in enumerate(t["rows"]):
        cells = "".join(f'<td style="font-size:.74rem;vertical-align:top;'
                        f'{"background:rgba(255,255,255,.06);" if k == kind else "opacity:.75;"}">{_e(t[k][i])}</td>'
                        for k in ("Muscular", "Hybrid", "Elastic"))
        rows.append(f'<tr><th style="font-size:.7rem;white-space:nowrap;vertical-align:top">{_e(r.upper())}</th>{cells}</tr>')
    note = ("GBO's pitching version of Georgia Southern's table -- draft wording for the staff to edit."
            if is_pitcher else "Adapted from Georgia Southern's hitting table.")
    return (f'<details style="margin-top:12px" open><summary style="font-size:.75rem;font-weight:700;letter-spacing:.05em">'
            f'{_e(title.upper())}</summary><div style="overflow-x:auto"><table class="table table-sm" style="margin-top:6px">'
            f'<thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
            f'<div class="small text-muted">{_e(note)} The traits are what his archetype typically shows -- confirm them '
            f'on video{"" if is_pitcher else " and bat-sensor data"}.</div></details>')


def archetype_card(prof, is_pitcher=None):
    """Georgia Southern-style archetype card (Oct 2026): radar, archetype +
    spectrum, force / velocity side, how he moves, force-plate signature,
    the mound (pitchers) or box (hitters) table, training focus."""
    if prof is None:
        return ('<div class="gbo-seq-sec"><h6 class="gbo-seq-h">Athlete archetype</h6><p class="small text-muted">'
                "Needs a countermovement jump (VALD) with height, mRSI, peak velocity, power, impulse and force -- "
                "and at least 6 teammates tested -- to place him on the spectrum.</p></div>")
    from analytics.athlete_archetype import DESCRIPTION
    k = prof["kind"]
    c = KIND_C[k]
    lines = "".join(f"<li>{_e(x)}</li>" for x in prof["lines"][1:])
    subs = ('<div class="small text-muted" style="margin-top:6px">* Substitute until our VALD import has it: '
            + _e("; ".join(sorted(set(prof.get("substitutes") or [])))) + ".</div>") if prof.get("substitutes") else ""
    panel = (f'<div style="border-left:4px solid {c};background:rgba(255,255,255,.03);padding:8px 12px;border-radius:6px">'
             f'<div style="display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap">'
             f'<div><div style="font-size:.66rem;font-weight:700;letter-spacing:.08em">ARCHETYPE</div>'
             f'<div style="font-size:1.5rem;font-weight:800;color:{c};line-height:1.1">{k.upper()}</div></div>'
             f'<div class="small" style="flex:1 1 200px">{_e(DESCRIPTION[k])}</div></div>'
             f'<div class="small" style="margin-top:6px;border-top:1px solid rgba(255,255,255,.1);padding-top:5px">'
             f'Spectrum index <b>{prof["index"]:+.2f}</b> &nbsp;·&nbsp; Overall output <b>{_ord(prof["output"])} pct</b></div></div>')
    how = (f'<div style="font-size:.7rem;font-weight:700;letter-spacing:.06em;margin-top:12px">HOW HE MOVES</div>'
           f'<div class="small">{_e(prof["how"])}</div>') if prof.get("how") else ""
    return (f'<div class="gbo-seq-sec"><h6 class="gbo-seq-h">Athlete archetype <span style="background:{c};color:#111;'
            f'padding:1px 8px;border-radius:6px;font-size:.75rem;margin-left:6px">{k.upper()}</span></h6>'
            f'<p class="text-muted small gbo-seq-how">Georgia Southern&#39;s force-plate archetype from his countermovement jump: '
            f'every metric is a team percentile (red at the center, green at the edge; dashed ring = team average). '
            f'Snapshot of his latest jump -- a trend needs regular jump testing.</p>'
            f'<div style="display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start">'
            f'<div style="flex:0 1 340px">{_radar(prof["metrics"])}'
            f'<ul class="small" style="margin:6px 0 0 18px;padding:0">{lines}</ul></div>'
            f'<div style="flex:1 1 320px">{panel}{_spectrum(prof)}{_side_bars(prof)}{how}</div></div>'
            f'{_signature(prof)}'
            f'{_table(k, True if is_pitcher is None else is_pitcher)}'
            f'{_training(k)}{subs}</div>')


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
