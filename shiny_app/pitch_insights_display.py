"""
GBO -- HTML for the Pitcher Profile views built from Ryker's Oct 2026
reading list (analytics/pitch_insights.py does the math): Seam Shift,
Plane & Preference, Get Ahead / Miss Bats, Usage Split, Outs per XBH.
Plain HTML strings so the same blocks can go on reports later.
"""

import html
import math

from analytics import pitch_insights as pi
from pitch_type_config import get_pitch_color


def _e(s):
    return html.escape(str(s))


def _pct(v, d=0):
    return "—" if v is None else f"{v:.{d}f}%"


def _num(v, f="{:.1f}"):
    return "—" if v is None else f.format(v)


def _ops(v):
    return "—" if v is None else f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}"


def _sec(title, how, body):
    return (f'<div class="gbo-seq-sec"><h6 class="gbo-seq-h">{_e(title)}</h6>'
            f'<p class="text-muted small gbo-seq-how">{how}</p>{body}</div>')


def _lines(lines):
    if not lines:
        return ""
    return '<ul class="gbo-pi-lines">' + "".join(f"<li>{_e(x)}</li>" for x in lines) + "</ul>"


CSS = """
<style>
.gbo-pi-lines{margin:0 0 6px 18px;padding:0}.gbo-pi-lines li{margin:2px 0}
.gbo-pi-tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:.7rem;font-weight:700}
.gbo-pi-ssw{background:rgba(233,160,60,.25);color:#F2B45A}.gbo-pi-std{background:rgba(120,140,170,.2);color:#9AB}
.gbo-pi-bar{height:8px;border-radius:4px;background:#E9A03C}
.gbo-pi-track{background:rgba(255,255,255,.08);border-radius:4px;height:8px;width:100%;position:relative}
.gbo-pi-mark{position:absolute;top:-3px;width:2px;height:14px;background:rgba(255,255,255,.55)}
.gbo-pi-split{display:grid;grid-template-columns:1fr auto 1fr;gap:6px 10px;align-items:center;font-size:.85rem}
.gbo-pi-split .l{display:flex;justify-content:flex-end;align-items:center;gap:6px}
.gbo-pi-split .r{display:flex;align-items:center;gap:6px}
.gbo-pi-split .lbl{text-align:center;font-weight:700;min-width:110px}
.gbo-pi-tiles{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 10px}
.gbo-pi-tile{flex:1 1 130px;border:1px solid var(--gbo-border);border-radius:10px;padding:8px 10px;background:var(--gbo-bg-raised,#1D1D20)}
.gbo-pi-tile b{display:block;font-size:1.35rem}.gbo-pi-tile span{font-size:.72rem;color:var(--gbo-text-muted)}
.gbo-pi-vs{display:flex;gap:12px;flex-wrap:wrap}.gbo-pi-vs>div{flex:1 1 200px}
.gbo-pi-flag{color:#F2A65A;font-weight:700}
</style>
"""


# ---------------------------------------------------------------------------
# Seam shift
# ---------------------------------------------------------------------------

def seam_shift_html(mine, staff, name_of, pid):
    """mine: seam_shift_by_type for this pitcher; staff: seam_shift_staff()."""
    if not mine:
        return CSS + _sec("Seam shift", "Needs 10+ Rapsodo readings of a fastball or changeup with at least 4 in of break.",
                    "<p class='small text-muted'>Not enough Rapsodo readings yet.</p>")
    avg = staff["type_avg"]
    game = {r["type"]: r["game"] for r in staff["rows"] if r["pid"] == pid}
    rows = []
    for t, s in sorted(mine.items(), key=lambda kv: -kv[1]["abs_gap"]):
        g = game.get(t) or {}
        tag = ('<span class="gbo-pi-tag gbo-pi-ssw">Seam-shifted</span>' if s["ssw"]
               else '<span class="gbo-pi-tag gbo-pi-std">Spin explains it</span>')
        w = min(100, s["abs_gap"] / 120 * 100)
        mark = min(100, (avg.get(t) or 0) / 120 * 100)
        rows.append(
            f'<tr><th class="gbo-rc-pt">{_e(t)}<span>{s["n"]} readings</span></th>'
            f'<td style="min-width:150px"><div class="gbo-pi-track"><div class="gbo-pi-bar" style="width:{w:.0f}%"></div>'
            f'<div class="gbo-pi-mark" style="left:{mark:.0f}%" title="Staff {t}: {avg.get(t, 0):.0f} min"></div></div>'
            f'<div class="small" style="margin-top:3px">{s["abs_gap"]:.0f} min</div></td>'
            f'<td style="white-space:normal;text-align:left">{tag}<div class="small text-muted">{_e(s["words"])}</div></td>'
            f'<td title="{g.get("swings", 0)} swings">{_pct(g.get("whiff"))}</td>'
            f'<td title="{g.get("bip", 0)} balls in play">{_pct(g.get("gb"))}</td></tr>')
    head = "<tr><th>Pitch</th><th>Axis gap (white line = staff)</th><th>What the seams add</th><th>Whiff %</th><th>GB %</th></tr>"
    body = f'<div class="gbo-sg-wrap"><table class="gbo-rc"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
    s1 = _sec("Seam shift -- his pitches",
              "Axis gap = how far the ball's real movement direction sits from what its spin alone explains, in clock "
              "minutes (1 hour = 30°). Rapsodo measures both. A big gap means the seams are moving the ball "
              f"(seam-shifted wake). Tagged seam-shifted at {pi.SSW_MIN}+ min with {pi.SSW_MIN_IN:.0f}+ in of non-spin "
              "movement -- set from our staff's Rapsodo spread (Driveline's MLB cut is 50 min on Hawk-Eye, which "
              "measures the axis differently). Fastballs and changeups only: breaking balls are too gyro-heavy for "
              "Rapsodo's spin direction to mean much. Whiff and GB % come from charted games.", body)
    split_rows = []
    for fam, d in staff["split"].items():
        a, b = d["ssw"], d["trad"]
        if not (a["pitches"] or b["pitches"]):
            continue
        split_rows.append(
            f'<div><div class="small" style="font-weight:700;margin-bottom:4px">{_e(fam)}</div>'
            f'<div class="gbo-pi-tiles"><div class="gbo-pi-tile"><b>{_pct(a["whiff"], 1)}</b><span>Whiff · seam-shifted '
            f'({a["swings"]} swings)</span></div><div class="gbo-pi-tile"><b>{_pct(b["whiff"], 1)}</b><span>Whiff · '
            f'spin-only ({b["swings"]} swings)</span></div><div class="gbo-pi-tile"><b>{_pct(a["gb"], 1)}</b><span>GB · '
            f'seam-shifted ({a["bip"]} BIP)</span></div><div class="gbo-pi-tile"><b>{_pct(b["gb"], 1)}</b><span>GB · '
            f'spin-only ({b["bip"]} BIP)</span></div></div></div>')
    top = [r for r in staff["rows"][:8]]
    lb = "".join(f'<tr><td style="text-align:left">{i + 1}. {_e(name_of(r["pid"]))}</td><td>{_e(r["type"])}</td>'
                 f'<td>{r["abs_gap"]:.0f} min</td><td>{_pct(r["game"]["whiff"])}</td><td>{_pct(r["game"]["gb"])}</td></tr>'
                 for i, r in enumerate(top))
    s2 = _sec("Does it hold up on our staff?",
              "Every staff pitch type with 10+ readings, split seam-shifted vs spin-only, with game results. "
              "Small samples -- read the swing and ball-in-play counts.",
              "".join(split_rows) + (f'<details class="gbo-seq-details"><summary>Most seam-shifted pitches on staff'
                                     f'</summary><table class="gbo-rc"><thead><tr><th>Pitcher</th><th>Pitch</th><th>Gap'
                                     f'</th><th>Whiff</th><th>GB</th></tr></thead><tbody>{lb}</tbody></table></details>'
                                     if lb else ""))
    return CSS + s1 + s2


# ---------------------------------------------------------------------------
# Plane
# ---------------------------------------------------------------------------

def _plane_svg(pl):
    W = H = 300
    pad = 26
    lim = 24.0

    def X(h):
        return pad + (h + lim) / (2 * lim) * (W - 2 * pad)

    def Y(v):
        return pad + (lim - v) / (2 * lim) * (H - 2 * pad)

    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:340px" xmlns="http://www.w3.org/2000/svg">',
             f'<rect x="0" y="0" width="{W}" height="{H}" rx="10" fill="rgba(255,255,255,.03)"/>',
             f'<line x1="{X(-lim)}" y1="{Y(0)}" x2="{X(lim)}" y2="{Y(0)}" stroke="rgba(255,255,255,.18)"/>',
             f'<line x1="{X(0)}" y1="{Y(-lim)}" x2="{X(0)}" y2="{Y(lim)}" stroke="rgba(255,255,255,.18)"/>',
             f'<text x="{X(lim) - 4}" y="{Y(0) - 5}" font-size="9" text-anchor="end" fill="#8a93a3">arm side →</text>',
             f'<text x="{X(0) + 4}" y="{Y(lim) + 10}" font-size="9" fill="#8a93a3">ride ↑</text>']
    F, B = pl["shapes"][pl["fb"]], pl["shapes"][pl["bb"]]
    dh, dv = B["h"] - F["h"], B["v"] - F["v"]
    L = math.hypot(dh, dv) or 1
    ux, uy = dh / L, dv / L
    x1, y1 = F["h"] - ux * 40, F["v"] - uy * 40
    x2, y2 = F["h"] + ux * 60, F["v"] + uy * 60
    parts.append(f'<clipPath id="pclip"><rect x="{pad}" y="{pad}" width="{W - 2 * pad}" height="{H - 2 * pad}"/></clipPath>')
    parts.append(f'<line clip-path="url(#pclip)" x1="{X(x1):.1f}" y1="{Y(y1):.1f}" x2="{X(x2):.1f}" y2="{Y(y2):.1f}" '
                 f'stroke="#E9A03C" stroke-width="10" stroke-opacity=".18" stroke-linecap="round"/>')
    parts.append(f'<line clip-path="url(#pclip)" x1="{X(x1):.1f}" y1="{Y(y1):.1f}" x2="{X(x2):.1f}" y2="{Y(y2):.1f}" '
                 f'stroke="#E9A03C" stroke-dasharray="4 4"/>')
    off = {o["type"]: o["off"] for o in pl["off"]}
    for t, s in pl["shapes"].items():
        c = get_pitch_color(t) or "#ccc"
        hx, vy = max(-lim, min(lim, s["h"])), max(-lim, min(lim, s["v"]))
        ring = ' stroke="#F2A65A" stroke-width="2.5"' if off.get(t) else ' stroke="#111" stroke-width="1"'
        parts.append(f'<circle cx="{X(hx):.1f}" cy="{Y(vy):.1f}" r="7" fill="{c}"{ring}><title>{_e(t)}: '
                     f'{s["v"]:.1f} in ride, {s["h"]:.1f} in arm-side ({s["n"]})</title></circle>')
        parts.append(f'<text x="{X(hx) + 9:.1f}" y="{Y(vy) + 3:.1f}" font-size="9.5" fill="#d8dde6">{_e(t)}</text>')
    parts.append("</svg>")
    return "".join(parts)


def plane_html(pl):
    if pl is None:
        return CSS + _sec("Plane & preference", "",
                          "<p class='small text-muted'>Needs 10+ Rapsodo readings of a fastball and a breaking ball.</p>")
    word = {"vertical": "Vertical mover", "horizontal": "Horizontal mover", "diagonal": "In between"}[pl["kind"]]
    tiles = (f'<div class="gbo-pi-tiles"><div class="gbo-pi-tile"><b>{word}</b><span>from his {_e(pl["fb"])} → '
             f'{_e(pl["bb"])} line</span></div><div class="gbo-pi-tile"><b>{pl["angle"]:.0f}°</b><span>line angle '
             f'(90° = straight up/down)</span></div><div class="gbo-pi-tile"><b>{_e(pl["fb_says"].title())}</b>'
             f'<span>what the fastball alone says</span></div></div>')
    body = (f'<div class="gbo-pi-vs"><div style="flex:0 1 340px">{_plane_svg(pl)}</div><div>{tiles}'
            f'{_lines(pl["lines"])}</div></div>')
    s1 = _sec("Plane & preference",
              "Samuel Midgette's no-lab read: the line from his main fastball to his main breaking ball on the movement "
              "plot (his own throwing arm's view, arm side to the right) approximates the plane his arm works in. "
              f"Steeper than {pi.VERTICAL_DEG}° = vertical mover, flatter than {pi.HORIZONTAL_DEG}° = horizontal. "
              f"Orange-ringed pitches sit {pi.OFF_PLANE_IN:.0f}+ in off that line. It's an estimate: grip and seams also "
              "shape movement, so confirm on high-speed video before changing his arm path.", body)
    rows = "".join(
        f'<tr><th class="gbo-rc-pt">{_e(r["type"])}<span>{r["n"]} readings</span></th>'
        f'<td class="{"gbo-rc-worse" if r["tell"] else ""}">{"his FB" if r["offset"] is None else _num(r["offset"]) + " in"}</td>'
        f'<td class="{"gbo-rc-worse" if r["wander"] else ""}">{_num(r["sd"])} in</td></tr>' for r in pl["release"])
    s2 = _sec("Release window",
              f"Where each pitch leaves his hand. Offset = distance from his fastball's average release (red at "
              f"{pi.RELEASE_OFFSET_IN:.0f}+ in: hitters can pick it up). Spread = how much that pitch's release point "
              f"wanders (red at {pi.RELEASE_SD_IN:.0f}+ in).",
              f'<table class="gbo-rc"><thead><tr><th>Pitch</th><th>Offset from FB</th><th>Spread</th></tr></thead>'
              f'<tbody>{rows}</tbody></table>')
    return CSS + s1 + s2


# ---------------------------------------------------------------------------
# Get ahead, then miss bats
# ---------------------------------------------------------------------------

def get_ahead_html(g, staff, pid):
    avg = staff[None]
    f = g["first"]

    def rk(getter, higher=True):
        r = pi.rank_of(staff, pid, getter, higher)
        return f"{r[0]} of {r[1]} on staff" if r else "not ranked yet"

    tiles = [
        (_pct(f["strike"]), "0-0 strike %", f"staff {_pct(avg['first']['strike'])} · {rk(lambda x: x['first']['strike'])}"),
        (_pct(f["zone"]), "0-0 in zone", f"staff {_pct(avg['first']['zone'])} · {f['located']} located"),
        (_num(f["whiff100"]), "whiffs / 100 first pitches",
         f"staff {_num(avg['first']['whiff100'])} · {rk(lambda x: x['first']['whiff100'])}"),
        (("—" if g["gap"] is None else f"{g['gap']:+.0f}"), "K% swing, 0-1 vs 1-0",
         f"staff {('—' if avg['gap'] is None else format(avg['gap'], '+.0f'))} · {rk(lambda x: x['gap'])}"),
    ]
    t = "".join(f'<div class="gbo-pi-tile"><b>{v}</b><span>{_e(lbl)}<br>{_e(sub)}</span></div>' for v, lbl, sub in tiles)
    a, b = g["ahead"], g["behind"]
    table = (f'<table class="gbo-rc"><thead><tr><th>After</th><th>PA</th><th>K%</th><th>BB%</th><th>OPS against</th></tr></thead>'
             f'<tbody><tr><th class="gbo-rc-pt">0-1 (won it)</th><td>{a["pa"]}</td><td>{_pct(a["k"])}</td><td>{_pct(a["bb"])}</td>'
             f'<td>{_ops(a["ops"])}</td></tr><tr><th class="gbo-rc-pt">1-0 (lost it)</th><td>{b["pa"]}</td><td>{_pct(b["k"])}</td>'
             f'<td>{_pct(b["bb"])}</td><td>{_ops(b["ops"])}</td></tr></tbody></table>')
    how = ("From \"Get Ahead, Then Miss Bats\" (Skubal). Step 1: win 0-0. Step 2: turn 0-1 into strikeouts. Skubal "
           "strikes out 41% of hitters after getting ahead and 23% after falling behind, the biggest gap in MLB. "
           f"Charted games, date range above. Pitchers are ranked once they have {pi.MIN_FIRST}+ first pitches.")
    return CSS + _sec("Get ahead, then miss bats", how,
                      f'<div class="gbo-pi-tiles">{t}</div>{_lines(pi.get_ahead_lines(g, avg))}{table}')


def get_ahead_game_line(g):
    """One-line summary for a single game (game report)."""
    f = g["first"]
    bits = []
    if f["n"]:
        bits.append(f"Won 0-0 on {round((f['strike'] or 0) * f['n'] / 100)} of {f['n']} ({_pct(f['strike'])})")
    if g["ahead"]["pa"]:
        bits.append(f"after 0-1: {g['ahead']['pa']} PA, {_pct(g['ahead']['k'])} K")
    if g["behind"]["pa"]:
        bits.append(f"after 1-0: {g['behind']['pa']} PA, {_pct(g['behind']['k'])} K")
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Usage split
# ---------------------------------------------------------------------------

def usage_split_html(sp, label_a, label_b):
    if not sp["rows"]:
        return CSS + _sec("Usage split", "", "<p class='small text-muted'>No pitches in one of the periods.</p>")
    mx = max(max(r["a"], r["b"]) for r in sp["rows"]) or 1
    rows = []
    for r in sp["rows"]:
        wa, wb = r["a"] / mx * 100, r["b"] / mx * 100
        c = get_pitch_color(r["type"]) or "#9aa"
        st = ""
        if r["stuff"]:
            s = r["stuff"]
            st = (f'<div class="small {"gbo-pi-flag" if s["changed"] else "text-muted"}">'
                  f'{s["dvelo"]:+.1f} mph · {s["dmove"]:.1f} in moved</div>')
        rows.append(
            f'<div class="l"><span class="small">{r["a"]:.0f}%</span><div class="gbo-pi-track" style="max-width:220px;'
            f'transform:scaleX(-1)"><div class="gbo-pi-bar" style="width:{wa:.0f}%;background:#7d8796"></div></div></div>'
            f'<div class="lbl">{_e(r["type"])}{st}</div>'
            f'<div class="r"><div class="gbo-pi-track" style="max-width:220px"><div class="gbo-pi-bar" style="width:{wb:.0f}%;'
            f'background:{c}"></div></div><span class="small{" gbo-pi-flag" if r["shift"] else ""}">{r["b"]:.0f}%'
            f'{" (" + format(r["d"], "+.0f") + ")" if r["shift"] else ""}</span></div>')
    head = (f'<div class="gbo-pi-split" style="margin-bottom:6px"><div class="l small text-muted">{_e(label_a)} · '
            f'{sp["a"]["n"]} pitches</div><div></div><div class="r small text-muted">{_e(label_b)} · {sp["b"]["n"]} pitches</div></div>')
    a, b = sp["a"], sp["b"]
    res = (f'<table class="gbo-rc" style="margin-top:10px"><thead><tr><th></th><th>PA</th><th>K%</th><th>BB%</th><th>Whiff %</th>'
           f'<th>OPS against</th><th>RV/100</th></tr></thead><tbody>'
           + "".join(f'<tr><th class="gbo-rc-pt">{_e(lbl)}</th><td>{x["pa"]}</td><td>{_pct(x["k"])}</td><td>{_pct(x["bb"])}</td>'
                     f'<td>{_pct(x["whiff"])}</td><td>{_ops(x["ops"])}</td><td>{_num(x["rv100"], "{:+.2f}")}</td></tr>'
                     for lbl, x in ((label_a, a), (label_b, b)))
           + "</tbody></table>")
    how = ("From Samuel Midgette's Yoendrys Gómez posts: same arsenal and delivery, new usage, very different results. "
           f"Left = before, right = after. Highlighted usage moved {pi.USAGE_SHIFT:.0f}+ points. Under each pitch: "
           f"the change in Rapsodo velo and movement, highlighted when the stuff itself changed ({pi.VELO_SHIFT} mph or "
           f"{pi.MOVE_SHIFT} in).")
    return CSS + _sec("Usage split", how, head + f'<div class="gbo-pi-split">{"".join(rows)}</div>' + _lines(sp["lines"]) + res)


# ---------------------------------------------------------------------------
# Outs per XBH
# ---------------------------------------------------------------------------

def outs_xbh_html(rows, title, how):
    if not rows:
        return ""
    best = max([r["ratio"] for r in rows if r["ratio"] is not None] or [1])
    trs = []
    for r in rows:
        w = 100 if r["ratio"] is None else r["ratio"] / best * 100
        val = "no XBH" if r["ratio"] is None else f"{r['ratio']:.1f}"
        trs.append(f'<tr><th class="gbo-rc-pt">{_e(r["type"])}</th><td>{r["pitches"]}</td><td>{r["outs"]}</td><td>{r["xbh"]}</td>'
                   f'<td style="min-width:140px"><div style="display:flex;gap:8px;align-items:center"><div class="gbo-pi-track">'
                   f'<div class="gbo-pi-bar" style="width:{w:.0f}%"></div></div><b>{val}</b></div></td></tr>')
    return CSS + _sec(title, how, '<table class="gbo-rc"><thead><tr><th>Pitch</th><th>Pitches</th><th>Outs</th><th>XBH</th>'
                      f'<th>Outs / XBH</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')
