"""
GBO -- Hitter game card HTML (Oct 2026). Renders
analytics.hitter_game_card.build()'s dict: five tiles, every pitch with his
decision, where he swung (heat), and Heart / Edges / Chase panels.
Catcher's view, like the rest of GBO. Plain HTML + inline SVG on the app's
CSS variables, so it reads in dark and light mode.
"""

import math
from html import escape

from strike_zone import (ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP,
                         SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP, CHASE_HALF_WIDTH, CHASE_BOTTOM, CHASE_TOP)

GOOD, POOR, NEUTRAL, GOLD = "#2E9C62", "#D94F3D", "#9AA0A6", "#FFC72C"
AREA_C = {"heart": "#2E9C62", "edges": "#C9A227", "chase": "#D94F3D"}
DEC_C = {"good": GOOD, "poor": POOR, "neutral": NEUTRAL, None: None}
MUTED = "var(--gbo-text-muted,#8A8A8E)"
LINE = "var(--gbo-text-2,#BDBCB6)"
X_EXT, Z_LO, Z_HI = 2.1, 0.45, 4.6


def _e(s):
    return escape(str(s)) if s is not None else ""


def _fmt(kind, v, signed=False):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.0f}%"
    return f"{v:+.1f}" if signed or kind == "pts" else f"{v:.1f}"


class _Plot:
    """ft -> px for one zone picture (catcher's view)."""

    def __init__(self, w, h, x_ext=X_EXT, z_lo=Z_LO, z_hi=Z_HI, pad=8):
        self.w, self.h, self.pad = w, h, pad
        self.s = min((w - 2 * pad) / (2 * x_ext), (h - 2 * pad) / (z_hi - z_lo))
        self.x_ext, self.z_lo, self.z_hi = x_ext, z_lo, z_hi
        self.cx = w / 2
        self.base = pad + (z_hi - z_lo) * self.s   # px of z_lo

    def x(self, ft):
        ft = max(-self.x_ext + 0.12, min(self.x_ext - 0.12, ft))
        return self.cx + ft * self.s

    def z(self, ft):
        ft = max(self.z_lo + 0.12, min(self.z_hi - 0.12, ft))
        return self.base - (ft - self.z_lo) * self.s

    def rect(self, hw, lo, hi, **attrs):
        a = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        return (f'<rect x="{self.cx - hw * self.s:.1f}" y="{self.base - (hi - self.z_lo) * self.s:.1f}" '
                f'width="{2 * hw * self.s:.1f}" height="{(hi - lo) * self.s:.1f}" {a}/>')

    def plate(self):
        hw = ZONE_HALF_WIDTH * self.s
        y = self.base - (min(0.3, (ZONE_BOTTOM - self.z_lo) / 3)) * self.s - 12
        cx = self.cx
        return (f'<path d="M{cx - hw:.1f},{y:.1f} L{cx + hw:.1f},{y:.1f} L{cx + hw:.1f},{y + 6:.1f} '
                f'L{cx:.1f},{y + 14:.1f} L{cx - hw:.1f},{y + 6:.1f} Z" fill="none" stroke="{MUTED}" stroke-width="1.2"/>')

    def frame(self, shadow=True):
        out = []
        if shadow:
            out.append(self.rect(SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP, fill="none", stroke=MUTED,
                                 stroke_width="1", stroke_dasharray="4 3"))
        out.append(self.rect(ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, fill="none", style=f"stroke:{LINE}",
                             stroke_width="2"))
        out.append(self.plate())
        return "".join(out)


def _marker(x, y, action, color, r=7):
    fill = color or "none"
    stroke = "#111" if color else MUTED
    if action == "whiff":
        c = color or NEUTRAL
        return (f'<path d="M{x - r:.1f},{y - r:.1f} L{x + r:.1f},{y + r:.1f} M{x - r:.1f},{y + r:.1f} '
                f'L{x + r:.1f},{y - r:.1f}" stroke="{c}" stroke-width="3.2" stroke-linecap="round"/>')
    if action == "foul":
        return (f'<path d="M{x:.1f},{y - r - 1:.1f} L{x + r + 1:.1f},{y + r - 1:.1f} L{x - r - 1:.1f},{y + r - 1:.1f} Z" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
    if action == "take":
        return (f'<path d="M{x:.1f},{y - r - 1:.1f} L{x + r + 1:.1f},{y:.1f} L{x:.1f},{y + r + 1:.1f} L{x - r - 1:.1f},{y:.1f} Z" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'


def decisions_svg(items, hand=None, w=300, h=310):
    P = _Plot(w, h)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" xmlns="http://www.w3.org/2000/svg">',
             P.frame()]
    if hand in ("R", "L"):
        # catcher's view: a right-handed hitter stands on the left
        x = 14 if hand == "R" else w - 14
        parts.append(f'<text x="{x}" y="{P.z(3.0):.0f}" font-size="10" font-weight="700" '
                     f'text-anchor="{"start" if hand == "R" else "end"}" style="fill:{MUTED}">{hand}HH</text>')
    for it in items:
        x, y = P.x(it["x"]), P.z(it["z"])
        if it["two_three"]:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="12" fill="none" stroke="{GOLD}" stroke-width="2.2"/>')
        tip = (f'At-bat {it["ab"] or "—"} · {it["count"]} · {it["pitch"]} · {it["result"]}'
               + (f' · decision {it["pts"]:+.1f} pts' if it["pts"] is not None else " · not graded"))
        parts.append(f'<g><title>{_e(tip)}</title>{_marker(x, y, it["action"], DEC_C[it["decision"]])}</g>')
    parts.append("</svg>")
    return "".join(parts)


def _heat_color(t):
    # pale yellow -> orange -> red
    stops = [(0.0, (255, 236, 150)), (0.5, (245, 150, 40)), (1.0, (205, 40, 30))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            f = (t - a) / (b - a) if b > a else 0
            return "rgb({},{},{})".format(*(round(ca[i] + (cb[i] - ca[i]) * f) for i in range(3)))
    return "rgb(205,40,30)"


def swing_heat_svg(swings, w=300, h=310, sigma=0.32, cell=0.1):
    P = _Plot(w, h)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" xmlns="http://www.w3.org/2000/svg">',
             '<defs><filter id="hgcblur" x="-10%" y="-10%" width="120%" height="120%">'
             '<feGaussianBlur stdDeviation="3"/></filter></defs>']
    if swings:
        nx, nz = int(2 * X_EXT / cell), int((Z_HI - Z_LO) / cell)
        grid, top = [], 0.0
        for i in range(nx):
            gx = -X_EXT + (i + 0.5) * cell
            for j in range(nz):
                gz = Z_LO + (j + 0.5) * cell
                d = sum(math.exp(-((gx - x) ** 2 + (gz - z) ** 2) / (2 * sigma * sigma)) for x, z in swings)
                grid.append((gx, gz, d))
                top = max(top, d)
        parts.append('<g filter="url(#hgcblur)">')
        sz = cell * P.s + 0.6
        for gx, gz, d in grid:
            t = d / top if top else 0
            if t < 0.12:
                continue
            parts.append(f'<rect x="{P.cx + (gx - cell / 2) * P.s:.1f}" y="{P.base - (gz + cell / 2 - Z_LO) * P.s:.1f}" '
                         f'width="{sz:.1f}" height="{sz:.1f}" fill="{_heat_color(t)}" opacity="{0.25 + 0.7 * t:.2f}"/>')
        parts.append("</g>")
    parts.append(P.frame())
    for x, z in swings:
        parts.append(f'<circle cx="{P.x(x):.1f}" cy="{P.z(z):.1f}" r="2.6" fill="#7A1010" opacity=".8"/>')
    if not swings:
        parts.append(f'<text x="{w / 2}" y="{h / 2}" font-size="12" text-anchor="middle" style="fill:{MUTED}">No swings</text>')
    parts.append("</svg>")
    return "".join(parts)


def area_svg(key, items, w=120, h=130):
    P = _Plot(w, h, x_ext=CHASE_HALF_WIDTH + 0.15, z_lo=CHASE_BOTTOM - 0.15, z_hi=CHASE_TOP + 0.15, pad=4)
    c = AREA_C[key]
    parts = [f'<svg viewBox="0 0 {w} {h}" width="{w}" xmlns="http://www.w3.org/2000/svg">']
    if key == "chase":
        parts.append(P.rect(CHASE_HALF_WIDTH, CHASE_BOTTOM, CHASE_TOP, fill=c, fill_opacity=".18"))
        parts.append(P.rect(SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP, style="fill:var(--gbo-bg-card,#141415)"))
    elif key == "edges":
        parts.append(P.rect(SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP, fill=c, fill_opacity=".25"))
        parts.append(P.rect(HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP, style="fill:var(--gbo-bg-card,#141415)"))
    else:
        parts.append(P.rect(HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP, fill=c, fill_opacity=".3"))
    parts.append(P.rect(SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP, fill="none", stroke=MUTED, stroke_width=".8",
                        stroke_dasharray="3 2"))
    parts.append(P.rect(ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, fill="none", style=f"stroke:{LINE}", stroke_width="1.4"))
    for it in items:
        col = DEC_C[it["decision"]] or NEUTRAL
        swung = it["action"] in ("swing", "whiff", "foul")
        parts.append(f'<circle cx="{P.x(it["x"]):.1f}" cy="{P.z(it["z"]):.1f}" r="3.6" '
                     + (f'fill="{col}" stroke="#111" stroke-width=".8"/>' if swung
                        else f'fill="none" stroke="{col}" stroke-width="1.6"/>'))
    parts.append("</svg>")
    return "".join(parts)


def _tile(t):
    col = {"good": GOOD, "poor": POOR}.get(t["mark"], "var(--gbo-text,#F3F2EE)")
    signed = t["kind"] == "pts"
    team = (f'TEAM · game {_fmt(t["kind"], t["game"], signed)} · season {_fmt(t["kind"], t["season"], signed)}')
    return (f'<div style="flex:1 1 150px;border:1px solid var(--gbo-border,#272729);border-radius:8px;overflow:hidden;'
            f'background:var(--gbo-bg-raised,#1D1D20);text-align:center">'
            f'<div style="background:{GOLD};color:#151A21;font-size:.66rem;font-weight:800;letter-spacing:.06em;'
            f'padding:3px 4px">{_e(t["label"].upper())}</div>'
            f'<div style="font-size:1.7rem;font-weight:800;color:{col};line-height:1.25;margin-top:6px">'
            f'{_fmt(t["kind"], t["you"])}</div>'
            f'<div style="font-size:.68rem;color:{MUTED}">{_e(t["sub"])}</div>'
            f'<div style="font-size:.64rem;font-weight:700;color:{MUTED};margin:4px 0 7px">{team}</div></div>')


def _bar(pct, team_game, team_season, color):
    def tick(v, dash):
        if v is None:
            return ""
        return (f'<div title="team {"game" if dash else "season"} {v:.0f}%" style="position:absolute;left:calc({v:.1f}% - 1px);'
                f'top:-4px;width:2px;height:18px;background:{"transparent" if dash else "var(--gbo-text,#F3F2EE)"};'
                f'{"border-left:2px dotted var(--gbo-text,#F3F2EE);" if dash else ""}"></div>')
    w = 0 if pct is None else pct
    return (f'<div style="position:relative;height:10px;border-radius:3px;background:var(--gbo-border,#272729);margin:6px 0 3px">'
            f'<div style="width:{w:.1f}%;height:100%;border-radius:3px;background:{color}"></div>'
            f'{tick(team_season, False)}{tick(team_game, True)}</div>')


def _area_panel(a, items):
    c = AREA_C[a["key"]]
    pts = a["pts"]
    pts_c = GOOD if (pts or 0) > 0.05 else POOR if (pts or 0) < -0.05 else "var(--gbo-text,#F3F2EE)"
    pct = a["swing_pct"]
    tg = "—" if a["team_game"] is None else f'{a["team_game"]:.0f}%'
    ts = "—" if a["team_season"] is None else f'{a["team_season"]:.0f}%'
    lab = 'style="font-size:.6rem;font-weight:700;letter-spacing:.08em;color:%s"' % MUTED
    return (f'<div style="flex:1 1 260px;border:1px solid var(--gbo-border,#272729);border-radius:8px;overflow:hidden;background:var(--gbo-bg-card,#141415)">'
            f'<div style="background:{c};color:#fff;display:flex;justify-content:space-between;align-items:center;'
            f'padding:5px 10px"><b style="letter-spacing:.06em">{_e(a["label"].upper())}</b>'
            f'<i style="font-size:.7rem">{_e(a["hint"])}</i></div>'
            f'<div style="display:flex;gap:10px;padding:10px;align-items:center">'
            f'<div>{area_svg(a["key"], [i for i in items if i["area"] == a["key"]])}</div>'
            f'<div style="flex:1;min-width:0"><div {lab}>SWUNG AT</div>'
            f'<div style="font-size:1.35rem;font-weight:800">{a["swings"]} of {a["n"]}</div>'
            f'{_bar(pct, a["team_game"], a["team_season"], c)}'
            f'<div style="font-size:.66rem;color:{MUTED}">{_fmt("pct", pct)} · team game {tg} · season {ts}</div>'
            f'<div {lab} class="mt-2">DECISION PTS</div>'
            f'<div style="font-size:1.25rem;font-weight:800;color:{pts_c}">{_fmt("pts", pts)}</div>'
            f'<div style="font-size:.66rem;color:{MUTED}">{_fmt("pct", a["share"])} of your swings</div>'
            f'</div></div></div>')


def _legend():
    def sw(action, color, label):
        return (f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px">'
                f'<svg width="18" height="18" viewBox="0 0 18 18">{_marker(9, 9, action, color, r=5)}</svg>{label}</span>')
    ring = (f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px"><svg width="18" height="18">'
            f'<circle cx="9" cy="9" r="7" fill="none" stroke="{GOLD}" stroke-width="2"/></svg>2 strikes or 3 balls</span>')
    dots = "".join(f'<span style="margin-right:10px"><i style="display:inline-block;width:9px;height:9px;border-radius:50%;'
                   f'background:{c};margin-right:4px"></i>{t}</span>'
                   for c, t in ((GOOD, "good decision"), (NEUTRAL, "neutral"), (POOR, "poor")))
    return (f'<div style="font-size:.7rem;color:{MUTED};margin-top:4px">{sw("swing", NEUTRAL, "in play")}'
            f'{sw("whiff", NEUTRAL, "whiff")}{sw("foul", NEUTRAL, "foul")}{sw("take", NEUTRAL, "take")}{ring}</div>'
            f'<div style="font-size:.68rem;color:{MUTED}">{dots}</div>')


def _head(t):
    return (f'<div style="display:flex;align-items:center;gap:8px;margin:14px 0 6px">'
            f'<span style="width:4px;height:16px;background:{GOLD};display:inline-block"></span>'
            f'<b style="font-size:.8rem;letter-spacing:.08em">{_e(t)}</b></div>')


def card_html(card, hand=None):
    me = card["me"]
    summary = (f'{me["pitches"]} pitches seen · {me["swings"]} swings · '
               f'{card["pa"] if card["pa"] is not None else "—"} plate appearances · {me["bip"]} balls in play')
    tiles = "".join(_tile(t) for t in card["tiles"])
    items = card["pitches"]
    return (
        '<div class="gbo-hitter-game-card">'
        f'<div style="display:flex;gap:10px;flex-wrap:wrap">{tiles}</div>'
        f'<div style="text-align:center;font-size:.72rem;color:{MUTED};margin-top:6px">{_e(summary)}</div>'
        '<div style="display:flex;gap:18px;flex-wrap:wrap">'
        f'<div style="flex:1 1 300px">{_head("EVERY PITCH — YOUR DECISIONS")}{decisions_svg(items, hand)}{_legend()}</div>'
        f'<div style="flex:1 1 300px">{_head("WHERE YOU SWUNG")}{swing_heat_svg(card["swings"])}'
        f'<div style="font-size:.7rem;color:{MUTED}">hotter = more of your swings there</div></div></div>'
        f'{_head("DECISIONS BY AREA")}'
        f'<div style="display:flex;gap:10px;flex-wrap:wrap">{"".join(_area_panel(a, items) for a in card["areas"])}</div>'
        f'<div style="font-size:.7rem;color:{MUTED};margin-top:6px">Catcher\'s view. Heart = middle of the zone, Edges = '
        f'the shadow band around the zone\'s edge, Chase = everything off it. Decision points come from GBO\'s decision '
        f'values (10 points = 1 run): what he did vs the other choice in that spot and count, from our own charted '
        f'games. Bar = his swing rate; solid tick = team season, dotted tick = team this game. Team = active position '
        f'players, every pitch pooled.</div>'
        '</div>')
