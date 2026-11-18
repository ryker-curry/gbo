"""
GBO -- player-facing release view, rendering (Nov 2026, Ryker: release card +
detail + "Pitchers Like You", on Pitcher Deep Dive's Release Point view). Data: analytics/release_view.py.

Plain HTML/SVG strings (like release_graphics.py) -- render with ui.HTML().
Plots sit on the release card's own dark panel (INK) so they read the same in
light and dark mode; text around them uses the app's CSS variables.

    dashboard_card_html(profile, alert)         -- card + tiles (+ alert)
    window_html(types, throws)                  -- release window by pitch + table
    trend_html(outs)                            -- arm angle by outing
    takeaways_html(lines)                       -- "What this means"
    staff_fit_html(me_pid, points, comps, ...)  -- where he fits on the staff
    comps_html(comps, best)                     -- similar arm slots
"""

from html import escape

from release_graphics import CRIMSON, CREAM, INK, PANEL, MUTED, FONT, release_card_svg
from pitch_type_config import get_pitch_color

CRIMSON_TEXT = "#FF6B6F"   # readable red on INK (crimson itself is too dark for text)
COMP_BLUE = "#5AA9E6"
WATCH = "#F2A541"

CSS = """
<style>
.gbo-rv-tiles{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:10px 0}
.gbo-rv-tile{border:1px solid var(--gbo-border);border-radius:10px;padding:8px 4px;text-align:center;background:var(--gbo-bg-raised,#1D1D20)}
.gbo-rv-tile b{display:block;font-size:1.2rem}.gbo-rv-tile span{font-size:.72rem;color:var(--gbo-text-muted)}
.gbo-rv-alert{display:flex;gap:10px;align-items:center;border-radius:10px;padding:9px 12px;background:rgba(242,165,65,.14);font-size:.88rem;margin:4px 0 8px}
.gbo-rv-dot{width:9px;height:9px;border-radius:50%;flex:0 0 9px;display:inline-block}
.gbo-rv-tbl{width:100%;border-collapse:collapse;font-size:.86rem;margin-top:8px}
.gbo-rv-tbl th{font-size:.72rem;color:var(--gbo-text-muted);text-align:left;font-weight:600;padding:6px 4px;border-bottom:1px solid var(--gbo-border)}
.gbo-rv-tbl td{padding:8px 4px;border-bottom:1px solid var(--gbo-border)}
.gbo-rv-tbl tr.watch td{background:rgba(242,165,65,.12)}
.gbo-rv-lines{list-style:none;margin:0;padding:0}.gbo-rv-lines li{display:flex;gap:10px;align-items:flex-start;margin:0 0 10px;font-size:.92rem;line-height:1.45}
.gbo-rv-lines li .gbo-rv-dot{margin-top:6px}
.gbo-rv-comp{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--gbo-border);border-radius:12px;padding:10px 12px;margin-bottom:8px}
.gbo-rv-num{width:30px;height:30px;border-radius:50%;border:2px solid #5AA9E6;color:#5AA9E6;font-weight:700;display:flex;align-items:center;justify-content:center;flex:0 0 30px}
.gbo-rv-legend{display:flex;flex-wrap:wrap;gap:14px;font-size:.78rem;color:var(--gbo-text-muted);margin:6px 0}
.gbo-rv-legend span{display:flex;align-items:center;gap:6px}
.gbo-rv-wrap{max-width:560px}
</style>
"""

TONE_COLOR = {"watch": WATCH, "good": "#5BC08A", "note": "#80838E"}


def _e(s):
    return escape(str(s))


def _num(v, fmt="{:.1f}"):
    return "—" if v is None else fmt.format(v)


def _text(x, y, s, color=MUTED, size=10, anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" fill="{color}" font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}" font-family="{FONT}">{s}</text>')


# ---------------------------------------------------------------- dashboard
def tiles_html(profile):
    t = [("{:.1f}".format(profile.release_height_ft), "ft", "Height"),
         ("{:.1f}".format(profile.release_side_ft), "ft", "Side"),
         (_num(profile.extension_ft or None), "ft", "Extension"),
         ("{:.0f}°".format(profile.arm_angle), "", "Arm angle" + (" est." if profile.arm_angle_is_estimate else ""))]
    cells = "".join(f'<div class="gbo-rv-tile"><b>{v}<small style="font-size:.7rem"> {u}</small></b><span>{l}</span></div>'
                    for v, u, l in t)
    return f'<div class="gbo-rv-tiles">{cells}</div>'


def dashboard_card_html(profile, alert=None):
    """Release card SVG + 4 tiles + optional alert line (the button is Shiny's)."""
    alert_html = (f'<div class="gbo-rv-alert"><span class="gbo-rv-dot" style="background:{WATCH}"></span>'
                  f'<span>{_e(alert)}</span></div>') if alert else ""
    return (CSS + '<div class="gbo-rv-wrap">'
            + f'<div style="max-width:440px">{release_card_svg(profile, show_header=False)}</div>'
            + tiles_html(profile) + alert_html + '</div>')


# ---------------------------------------------------------------- window
SHORT = {"4-Seam Fastball": "FB", "Fastball": "FB", "2-Seam Fastball": "2S", "Sinker": "SI", "Cutter": "CT",
         "Slider": "SL", "Sweeper": "SW", "Curveball": "CB", "Knuckle Curve": "KC", "Slurve": "SV",
         "Changeup": "CH", "Splitter": "SP"}


def short_name(t):
    return SHORT.get(t, t)


def window_svg(types, throws="R"):
    """Zoomed catcher's-view plot of each pitch type's average release around
    his fastball. 3-inch grid. Arm side is screen-left for a RHP."""
    fb = next((r for r in types if r["is_fb"]), None)
    if fb is None:
        return ""
    W, H = 342, 250
    cx, cy = W / 2, H / 2 - 4
    arm_dir = -1 if (throws or "R").upper() == "R" else 1
    # fit every pitch: px per inch, between 8 and 20
    span = max([abs(r["ds_in"] or 0) for r in types] + [abs(r["dh_in"] or 0) for r in types] + [3.0])
    ppi = max(8.0, min(20.0, 105.0 / span))
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" style="display:block;background:{INK};border-radius:12px;'
           f'max-width:520px" aria-label="Release point of each pitch type compared with the fastball">']
    step = 3 * ppi
    k = 0
    while cx + k * step < W:
        for x in {cx + k * step, cx - k * step}:
            out.append(f'<line x1="{x:.1f}" y1="10" x2="{x:.1f}" y2="{H-26}" stroke="{PANEL if k else "#3A3D46"}"/>')
        k += 1
    k = 0
    while cy + k * step < H - 26:
        for y in {cy + k * step, cy - k * step}:
            if 10 <= y <= H - 26:
                out.append(f'<line x1="10" y1="{y:.1f}" x2="{W-10}" y2="{y:.1f}" stroke="{PANEL if k else "#3A3D46"}"/>')
        k += 1
    left, right = ("3B", "1B")
    out.append(_text(14, 24, f"&#8592; {left}"))
    out.append(_text(W - 14, 24, f"{right} &#8594;", anchor="end"))
    out.append(_text(W / 2, H - 10, "Each line = 3 in · zoomed in around your fastball", anchor="middle"))
    pts = []
    for r in types:
        dx = 0.0 if r["is_fb"] else r["ds_in"] * ppi * arm_dir
        dy = 0.0 if r["is_fb"] else -r["dh_in"] * ppi
        pts.append((r, cx + dx, cy + dy))
    for r, x, y in pts:
        if r.get("tell"):
            out.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="{WATCH}" stroke-width="1.5" stroke-dasharray="3 3"/>')
    placed = []
    for r, x, y in sorted(pts, key=lambda t: not t[0]["is_fb"]):
        col = CREAM if r["is_fb"] else get_pitch_color(r["type"])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{col}" stroke="{INK}" stroke-width="1.5"/>')
        lab = short_name(r["type"])
        if r.get("tell"):
            lab += f" {r['offset_in']:.1f} in"
        # label on the side away from the fastball; FB label goes right
        go_left = (not r["is_fb"]) and x < cx
        anchor = "end" if go_left else "start"
        lx, ly = (x - 11 if go_left else x + 11), y + 4
        for _ in range(6):                      # nudge down past labels already placed
            if any(abs(ly - py) < 13 and (px < cx) == go_left for px, py in placed):
                ly += 13
        placed.append((lx, ly))
        out.append(_text(lx, ly, lab, color=col, size=11, anchor=anchor, weight=700))
    out.append("</svg>")
    return "".join(out)


def table_html(types):
    from analytics.release_view import offset_words
    rows = []
    for r in types:
        col = CREAM if r["is_fb"] else get_pitch_color(r["type"])
        vs = "Baseline" if r["is_fb"] else offset_words(r)
        style = f' style="color:{WATCH};font-weight:600"' if r.get("tell") else ' style="color:var(--gbo-text-muted)"'
        rows.append(f'<tr class="{"watch" if r.get("tell") else ""}"><td><span class="gbo-rv-dot" style="background:{col};'
                    f'margin-right:6px;border:1px solid var(--gbo-border)"></span><b>{_e(r["type"])}</b>'
                    f'<div style="font-size:.7rem;color:var(--gbo-text-muted)">{r["n"]} readings</div></td>'
                    f'<td>{r["height"]:.1f}</td><td>{r["side"]:.1f}</td><td>{_num(r["ext"])}</td>'
                    f'<td>{_num(r["arm_angle"], "{:.0f}°")}</td><td{style}>{_e(vs)}</td></tr>')
    return ('<table class="gbo-rv-tbl"><thead><tr><th>Pitch</th><th>Height</th><th>Side</th><th>Ext</th>'
            f'<th>Arm</th><th>vs FB</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'
            '<p class="text-muted small" style="margin-top:6px">Feet, catcher\'s view. Side = distance toward your '
            'arm side. Orange = 3+ in from your fastball release, which hitters can pick up.</p>')


def window_html(types, throws="R"):
    if not types:
        return CSS + '<p class="text-muted small">Needs 5+ Rapsodo readings of a pitch type.</p>'
    return CSS + f'<div class="gbo-rv-wrap">{window_svg(types, throws)}{table_html(types)}</div>'


# ---------------------------------------------------------------- trend
def trend_html(outs):
    if len(outs) < 2:
        return CSS + '<p class="text-muted small">Needs 2+ outings with 5+ fastball readings each.</p>'
    W, H = 342, 140
    vals = [o["arm_angle"] for o in outs]
    avg = sum(vals) / len(vals)
    lo, hi = min(vals + [avg]) - 2, max(vals + [avg]) + 2
    x0, x1, y0, y1 = 34, W - 12, 16, H - 34

    def X(i):
        return x0 + (x1 - x0) * (i / (len(outs) - 1))

    def Y(v):
        return y1 - (y1 - y0) * (v - lo) / (hi - lo)

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" style="display:block;background:{INK};border-radius:12px;'
           f'max-width:520px" aria-label="Fastball arm angle by outing">']
    out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(avg):.1f}" y2="{Y(avg):.1f}" stroke="{MUTED}" stroke-dasharray="4 4"/>')
    out.append(_text(x0 - 6, Y(avg) + 3.5, f"{avg:.0f}°", anchor="end"))
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vals))
    out.append(f'<polyline points="{pts}" fill="none" stroke="{CRIMSON_TEXT}" stroke-width="2.5" stroke-linejoin="round"/>')
    for i, o in enumerate(outs):
        last = i == len(outs) - 1
        hollow = o["kind"] == "Bullpen"
        fill = INK if hollow else CRIMSON_TEXT
        out.append(f'<circle cx="{X(i):.1f}" cy="{Y(o["arm_angle"]):.1f}" r="{5 if last else 4}" fill="{fill}" '
                   f'stroke="{CREAM if last else CRIMSON_TEXT}" stroke-width="2"/>')
    first, last = outs[0], outs[-1]
    out.append(_text(x0, H - 12, first["date"].strftime("%b %d") if first["date"] else ""))
    out.append(_text(x1, H - 12, (last["date"].strftime("%b %d") if last["date"] else "") + f" · {last['arm_angle']:.0f}°",
                     anchor="end", color=CREAM, weight=700))
    out.append("</svg>")
    return (CSS + f'<div class="gbo-rv-wrap">{"".join(out)}</div>'
            '<p class="text-muted small" style="margin-top:6px">Fastball only, one point per outing. Filled = game, '
            'hollow = bullpen. Dashed line = average over these outings.</p>')


def takeaways_html(lines):
    items = "".join(f'<li><span class="gbo-rv-dot" style="background:{TONE_COLOR.get(t, MUTED)}"></span>'
                    f'<span{" class=text-muted" if t == "note" else ""}>{_e(s)}</span></li>' for t, s in lines)
    return CSS + f'<ul class="gbo-rv-lines">{items}</ul>'


# ---------------------------------------------------------------- comps
def staff_fit_html(me_pid, points, comps, throws="R", slot=None, angle=None):
    """Every pool pitcher's fastball release (unnamed), him highlighted, his
    comps numbered. Side is absolute, drawn on his own arm side."""
    me = next((p for p in points if p[0] == me_pid), None)
    if me is None or len(points) < 3:
        return CSS + '<p class="text-muted small">Not enough teammates with game data yet.</p>'
    W, H = 342, 262
    sides = [p[1] for p in points]
    hts = [p[2] for p in points]
    smin, smax = min(sides) - 0.3, max(sides) + 0.3
    hmin, hmax = min(hts) - 0.3, max(hts) + 0.3
    x0, x1, y0, y1 = 44, W - 12, 34, H - 40
    arm_dir = -1 if (throws or "R").upper() == "R" else 1

    def X(s):
        frac = (s - smin) / (smax - smin)          # 0 = least arm side
        return (x1 - frac * (x1 - x0)) if arm_dir == -1 else (x0 + frac * (x1 - x0))

    def Y(h):
        return y1 - (y1 - y0) * (h - hmin) / (hmax - hmin)

    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" style="display:block;background:{INK};border-radius:12px;'
           f'max-width:520px" aria-label="Where your release fits among teammates">']
    for ft in range(int(hmin) + 1, int(hmax) + 1):
        out.append(f'<line x1="{x0}" x2="{x1}" y1="{Y(ft):.1f}" y2="{Y(ft):.1f}" stroke="{PANEL}"/>')
        out.append(_text(x0 - 6, Y(ft) + 3.5, f"{ft} ft", anchor="end"))
    for ft in range(int(smin) + 1, int(smax) + 1):
        out.append(f'<line x1="{X(ft):.1f}" x2="{X(ft):.1f}" y1="{y0}" y2="{y1}" stroke="{PANEL}"/>')
        out.append(_text(X(ft), y1 + 14, f"{ft} ft side", anchor="middle"))
    arm_lbl = "&#8592; more arm side" if arm_dir == -1 else "more arm side &#8594;"
    out.append(_text(x0 if arm_dir == -1 else x1, H - 8, arm_lbl, anchor="start" if arm_dir == -1 else "end"))
    out.append(_text(x1, 22, "higher release", anchor="end"))
    comp_ids = {pl.player_id: i + 1 for i, (pl, _s, _p) in enumerate(comps)}
    for pid, s, h, _a in points:
        if pid != me_pid and pid not in comp_ids:
            out.append(f'<circle cx="{X(s):.1f}" cy="{Y(h):.1f}" r="6" fill="{MUTED}" fill-opacity=".5"/>')
    for pid, s, h, _a in points:
        if pid in comp_ids:
            out.append(f'<circle cx="{X(s):.1f}" cy="{Y(h):.1f}" r="9" fill="{INK}" stroke="{COMP_BLUE}" stroke-width="2"/>')
            out.append(_text(X(s), Y(h) + 3.5, str(comp_ids[pid]), color=COMP_BLUE, size=10, anchor="middle", weight=700))
    out.append(f'<circle cx="{X(me[1]):.1f}" cy="{Y(me[2]):.1f}" r="9" fill="{CRIMSON}" stroke="{CREAM}" stroke-width="3"/>')
    out.append(_text(X(me[1]) + 14, Y(me[2]) + 18, "You", color=CREAM, size=12, weight=700))
    out.append("</svg>")
    legend = ('<div class="gbo-rv-legend">'
              f'<span><i class="gbo-rv-dot" style="background:{CRIMSON};border:2px solid {CREAM}"></i>You</span>'
              f'<span><i class="gbo-rv-dot" style="border:2px solid {COMP_BLUE}"></i>Closest matches</span>'
              f'<span><i class="gbo-rv-dot" style="background:{MUTED};opacity:.5"></i>Other teammates</span></div>')
    angles = [p[3] for p in points]
    line = ""
    if slot and angle is not None:
        line = (f'<p style="margin:4px 0 0">You\'re a <b>{_e(slot)}</b> pitcher on this staff: {angle:.0f}° arm angle, '
                f'staff range {min(angles):.0f}° to {max(angles):.0f}°.</p>')
    return CSS + f'<div class="gbo-rv-wrap">{"".join(out)}{legend}{line}</div>'


def comps_html(comps, best):
    """comps: [(Player, sim, ReleaseProfile)], best: {pid: (type, whiff) or None}."""
    if not comps:
        return CSS + '<p class="text-muted small">Not enough teammates with game data yet.</p>'
    cards = []
    for i, (pl, sim, prof) in enumerate(comps):
        b = best.get(pl.player_id)
        best_line = (f'<div style="font-size:.88rem">Best pitch: <b>{_e(b[0])}</b>, {b[1]:.0f}% whiff</div>'
                     if b else '<div class="text-muted small">Best pitch: not enough swings yet</div>')
        tag = ('<span style="font-size:.72rem;font-weight:600;color:#5AA9E6">Closest match</span>' if i == 0 else "")
        cards.append(
            f'<div class="gbo-rv-comp"><div class="gbo-rv-num">{i + 1}</div><div style="flex:1">'
            f'<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">'
            f'<b>{_e(pl.first_name)} {_e(pl.last_name)}</b>{tag}</div>'
            f'<div class="text-muted small">{prof.arm_angle:.0f}° · {prof.release_height_ft:.1f} ft high · '
            f'{prof.release_side_ft:.1f} ft side · {sim:.0f}% similar release</div>{best_line}</div></div>')
    return CSS + f'<div class="gbo-rv-wrap">{"".join(cards)}</div>'
