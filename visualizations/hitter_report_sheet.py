"""
GBO -- Hitter Meeting Report sheet (Oct 2026). The hitting twin of
visualizations/meeting_report_sheet.py: one letter-size light sheet,
same scoped SHEET_CSS (so it prints the same way), built from
analytics/hitter_report.py's game_report()/season_report() dict.
Zone pictures are catcher's view, like the rest of GBO.
"""

from html import escape

from analytics.hitter_hot_zones import OUTER, MIN_BIP
from analytics.hitter_insights import DECISION_COLORS
from strike_zone import (ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP, HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP,
                         SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP)
from visualizations.meeting_report_sheet import SHEET_CSS, MARK, _goals_html

EXTRA_CSS = """
.gbo-sheet .zpic{display:block;margin:0 auto}
.gbo-sheet .legend span{display:inline-block;margin-right:8px;font-size:8.5px;color:var(--muted)}
.gbo-sheet .legend i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:3px;vertical-align:middle}
.gbo-sheet .kv{display:flex;gap:6px;flex-wrap:wrap;margin:3px 0}
.gbo-sheet .kv div{border:1px solid var(--line);border-radius:4px;padding:2px 6px;background:var(--soft);font-size:9px}
.gbo-sheet .kv b{font-size:11px}
"""


def _e(s):
    return escape(str(s)) if s is not None else ""


def _avg(v):
    if v is None:
        return "—"
    s = f"{v:.3f}"
    return s[1:] if s.startswith("0") else s


def _pct(v):
    return "—" if v is None else f"{v:.0f}%"


def _fmtv(kind, v):
    return _avg(v) if kind == "avg" else (_pct(v) if kind == "%" else ("—" if v is None else f"{v:.1f}"))


# ---------- zone pictures (catcher's view) ----------
PAD = 0.55
X0, X1 = -ZONE_HALF_WIDTH - PAD - 0.05, ZONE_HALF_WIDTH + PAD + 0.05
Z0, Z1 = ZONE_BOTTOM - PAD - 0.05, ZONE_TOP + PAD + 0.05


def _mapper(w, h):
    sx = lambda x: (x - X0) / (X1 - X0) * w
    sz = lambda z: h - (z - Z0) / (Z1 - Z0) * h
    return sx, sz


def _heat(v):
    """.150 blue -> .300 neutral -> .450 red."""
    if v is None:
        return "#e6e8eb"
    t = max(0.0, min(1.0, (v - 0.150) / 0.300))
    if t < 0.5:
        a = t / 0.5
        c0, c1 = (47, 111, 208), (233, 228, 218)
    else:
        a = (t - 0.5) / 0.5
        c0, c1 = (233, 228, 218), (208, 52, 44)
    r, g, b = (round(c0[i] + (c1[i] - c0[i]) * a) for i in range(3))
    return f"rgb({r},{g},{b})"


def hot_zone_svg(cells, w=190, h=210):
    sx, sz = _mapper(w, h)
    mid = (ZONE_BOTTOM + ZONE_TOP) / 2
    parts = [f'<svg class="zpic" width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">']
    for key in OUTER:
        c = cells[key]
        left, up = key.endswith("L"), key.startswith("OU")
        x0, x1 = (-ZONE_HALF_WIDTH - PAD, 0) if left else (0, ZONE_HALF_WIDTH + PAD)
        z0, z1 = (mid, ZONE_TOP + PAD) if up else (ZONE_BOTTOM - PAD, mid)
        fill = _heat(c["avg"]) if c["bip"] >= MIN_BIP else "#eef0f2"
        parts.append(f'<rect x="{sx(x0):.1f}" y="{sz(z1):.1f}" width="{sx(x1)-sx(x0):.1f}" height="{sz(z0)-sz(z1):.1f}" '
                     f'fill="{fill}" stroke="#fff" stroke-width="2"/>')
        lx = sx(-ZONE_HALF_WIDTH - PAD / 2) if left else sx(ZONE_HALF_WIDTH + PAD / 2)
        lz = sz(ZONE_TOP + PAD / 2) if up else sz(ZONE_BOTTOM - PAD / 2)
        t = _avg(c["avg"]) if c["bip"] >= MIN_BIP else (str(c["bip"]) if c["bip"] else "")
        parts.append(f'<text x="{lx:.1f}" y="{lz+3:.1f}" font-size="8" text-anchor="middle" fill="#333">{t}</text>')
    cw = 2 * ZONE_HALF_WIDTH / 3
    ch = (ZONE_TOP - ZONE_BOTTOM) / 3
    for z in range(1, 10):
        c = cells[z]
        row, col = (z - 1) // 3, (z - 1) % 3
        x0 = -ZONE_HALF_WIDTH + col * cw
        ztop = ZONE_TOP - row * ch
        fill = _heat(c["avg"]) if c["bip"] >= MIN_BIP else "#dfe2e6"
        parts.append(f'<rect x="{sx(x0):.1f}" y="{sz(ztop):.1f}" width="{sx(x0+cw)-sx(x0):.1f}" '
                     f'height="{sz(ztop-ch)-sz(ztop):.1f}" fill="{fill}" stroke="#fff" stroke-width="2"/>')
        cx, cz = sx(x0 + cw / 2), sz(ztop - ch / 2)
        if c["bip"] >= MIN_BIP:
            parts.append(f'<text x="{cx:.1f}" y="{cz+1:.1f}" font-size="10" font-weight="700" text-anchor="middle" fill="#111">{_avg(c["avg"])}</text>')
            parts.append(f'<text x="{cx:.1f}" y="{cz+10:.1f}" font-size="6.5" text-anchor="middle" fill="#333">{c["bip"]} BIP</text>')
        elif c["bip"]:
            parts.append(f'<text x="{cx:.1f}" y="{cz+3:.1f}" font-size="7" text-anchor="middle" fill="#666">{c["bip"]}</text>')
    parts.append(f'<rect x="{sx(-ZONE_HALF_WIDTH):.1f}" y="{sz(ZONE_TOP):.1f}" width="{sx(ZONE_HALF_WIDTH)-sx(-ZONE_HALF_WIDTH):.1f}" '
                 f'height="{sz(ZONE_BOTTOM)-sz(ZONE_TOP):.1f}" fill="none" stroke="#1b1f24" stroke-width="1.6"/>')
    parts.append("</svg>")
    return "".join(parts)


def decisions_svg(graded, w=190, h=210):
    sx, sz = _mapper(w, h)
    parts = [f'<svg class="zpic" width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">',
             f'<rect x="0" y="0" width="{w}" height="{h}" fill="#f6f7f9"/>']
    for hw, b, t in ((SHADOW_HALF_WIDTH, SHADOW_BOTTOM, SHADOW_TOP), (HEART_HALF_WIDTH, HEART_BOTTOM, HEART_TOP)):
        parts.append(f'<rect x="{sx(-hw):.1f}" y="{sz(t):.1f}" width="{sx(hw)-sx(-hw):.1f}" height="{sz(b)-sz(t):.1f}" '
                     f'fill="none" stroke="#aab" stroke-dasharray="3,2"/>')
    parts.append(f'<rect x="{sx(-ZONE_HALF_WIDTH):.1f}" y="{sz(ZONE_TOP):.1f}" width="{sx(ZONE_HALF_WIDTH)-sx(-ZONE_HALF_WIDTH):.1f}" '
                 f'height="{sz(ZONE_BOTTOM)-sz(ZONE_TOP):.1f}" fill="none" stroke="#1b1f24" stroke-width="1.6"/>')
    order = ("Borderline", "Good take", "Good swing", "Taken strike", "Chase")
    for d in order:
        for p, dd in graded:
            if dd != d:
                continue
            x = max(X0, min(X1, float(p.actual_plate_x)))
            z = max(Z0, min(Z1, float(p.actual_plate_z)))
            r = 2.4 if d == "Borderline" else 3.4
            op = 0.5 if d == "Borderline" else 0.95
            parts.append(f'<circle cx="{sx(x):.1f}" cy="{sz(z):.1f}" r="{r}" fill="{DECISION_COLORS[d]}" '
                         f'fill-opacity="{op}" stroke="#fff" stroke-width=".6"/>')
    parts.append("</svg>")
    return "".join(parts)


# ---------- blocks ----------
def _line_strip(r):
    y = r["you"]
    cells = [("PA", y["PA"]), ("AB", y["AB"]), ("H", y["H"]), ("BB", y["BB"]), ("K", y["K"]),
             ("AVG", _avg(y["AVG"])), ("OBP", _avg(y["OBP"])), ("SLG", _avg(y["SLG"]))]
    from game_stats import ops_plus
    op = ops_plus(y["OBP"], y["SLG"])
    if op is not None:
        cells.append(("OPS+ vs D2", op))
    if r["kind"] == "season":
        cells.insert(0, ("G", r.get("games")))
    return '<div class="line">' + "".join(f"<div><b>{_e(v if v is not None else '—')}</b><span>{k}</span></div>" for k, v in cells) + "</div>"


def _key_table(r):
    head = (f'<tr><th>Key numbers</th><th>{"This game" if r["kind"] == "game" else "Season"}</th>'
            f'<th>{_e(r["ref_label"])}</th><th>Team avg</th><th>D2 / MIAA</th><th>vs D2 / team</th></tr>')
    body = []
    for row in r["rows"]:
        mk = ""
        if row["mark"]:
            sym, cls = MARK[row["mark"]]
            mk = f'<span class="{cls}">{sym}</span>'
        elif row["you"] is not None:
            mk = '<span class="na">small sample</span>'
        body.append(f'<tr><td><b>{_e(row["label"])}</b><span class="means">{_e(row["means"])}</span></td>'
                    f'<td class="you">{_fmtv(row["kind"], row["you"])}</td><td>{_fmtv(row["kind"], row["ref"])}</td>'
                    f'<td>{_fmtv(row["kind"], row["team"])}</td>'
                    f'<td>{(_fmtv(row["kind"], row.get("d2")) + " / " + _fmtv(row["kind"], row.get("miaa"))) if row.get("d2") is not None else "<span class=na>—</span>"}</td>'
                    f'<td class="mk">{mk}</td></tr>')
    return f'<table>{head}{"".join(body)}</table>'


def _pt_table(r):
    rows = r["pt"]["All"]
    head = "<tr><th>Pitch type</th><th>Seen</th><th>Swing</th><th>Whiff</th><th>Chase</th><th>AVG</th><th>SLG</th></tr>"
    body = "".join(f'<tr><td>{_e(x["Pitch"])}</td><td>{x["Seen"]}</td><td>{_pct(x["Swing %"])}</td><td>{_pct(x["Whiff %"])}</td>'
                   f'<td>{_pct(x["Chase %"])}</td><td>{_avg(x["AVG"])}</td><td>{_avg(x["SLG"])}</td></tr>' for x in rows)
    split = []
    for s in ("vs RHP", "vs LHP"):
        w = [x for x in r["pt"][s] if x["Seen"] >= 5]
        if w:
            worst = max(w, key=lambda x: x["Whiff %"] or 0)
            split.append(f'{s}: most misses on {worst["Pitch"].lower()} ({_pct(worst["Whiff %"])})')
    note = f'<div class="small" style="margin-top:2px">{_e(" · ".join(split))}</div>' if split else ""
    return f'<table>{head}{body}</table>{note}'


def _attack_block(r):
    f, t = r["fp"]["first"], r["fp"]["two"]
    kv = (f'<div class="kv"><div>1st-pitch swing <b>{_pct(f["Swing %"])}</b></div>'
          f'<div>Strike one seen <b>{_pct(f["Strike seen %"])}</b></div>'
          f'<div>2-strike K <b>{_pct(t["K %"])}</b></div><div>2-strike chase <b>{_pct(t["Chase %"])}</b></div>'
          f'<div>Foul-offs/PA <b>{t["Foul-offs per PA"] if t["Foul-offs per PA"] is not None else "—"}</b></div></div>')
    lines = r["attack_lines"] or ["Not enough pitches yet to see a pattern."]
    return kv + "<ul>" + "".join(f"<li>{_e(l)}</li>" for l in lines) + "</ul>"


def _pa_log(r):
    if not r.get("pa_log"):
        return ""
    rows = "".join(f'<tr><td>{x["inning"]}</td><td>{_e({"R": "RHP", "L": "LHP"}.get(x["hand"], "?"))}</td>'
                   f'<td>{_e(x["count"])}</td><td>{x["pitches"]}</td><td style="text-align:left;font-family:monospace">{_e(x["seq"])}</td>'
                   f'<td><b>{_e(x["result"])}</b>{(" · " + _e(x["quality"])) if x["quality"] else ""}</td></tr>' for x in r["pa_log"])
    return ('<div class="sec"><h2>At-bat by at-bat</h2><table><tr><th>Inn</th><th>vs</th><th>Final count</th><th>#</th>'
            '<th style="text-align:left">Pitches (FB fastball, SL slider, CB curve, CH change… + b ball · k called strike · s whiff · f foul · x in play)</th><th>Result</th></tr>'
            f'{rows}</table></div>')


def _game_log(r):
    if not r.get("game_log"):
        return ""
    rows = []
    for g in r["game_log"][:5]:
        game = g["game"]
        opp = game.opponent_team.team_name if getattr(game, "opponent_team", None) else (game.opponent_name or "—")
        rows.append(f'<tr><td>{game.game_date.strftime("%b %d")} &nbsp;{_e(opp)}</td><td>{g["PA"]}</td><td>{g["H"]}</td>'
                    f'<td>{g["BB"]}</td><td>{g["K"]}</td><td>{_avg(g["AVG"])}</td><td>{_pct(g["Swing Decision %"])}</td>'
                    f'<td>{_pct(g["Chase %"])}</td></tr>')
    return ('<div class="sec"><h2>Recent games</h2><table><tr><th>Game</th><th>PA</th><th>H</th><th>BB</th><th>K</th>'
            f'<th>AVG</th><th>Swing dec.</th><th>Chase</th></tr>{"".join(rows)}</table></div>')


def render_sheet(r, notes=None, team_name="Pitt State Baseball"):
    player = r["player"]
    name = f"{player.first_name} {player.last_name}"
    if r["kind"] == "game":
        g = r["game"]
        opp = g.opponent_team.team_name if getattr(g, "opponent_team", None) else (g.opponent_name or "opponent")
        loc = "@" if g.is_home is False else "vs"
        sub = f'Game report · {g.game_date.strftime("%A, %b %d, %Y")} · {loc} {_e(opp)}'
    else:
        sub = f'Season report · {_e(r.get("season_name") or "")}'
    bats = {"R": "Bats R", "L": "Bats L", "S": "Switch"}.get(getattr(player, "bats", None), "")
    if notes and notes.strip():
        notes_html = f'<div class="notes">{_e(notes.strip())}</div>'
    else:
        notes_html = '<div class="notes" style="padding-top:0">' + '<div class="ruled"></div>' * 4 + "</div>"
    sd = r["sd"]
    c = sd["counts"]
    zl = f' <span class="small">({_e(r["zones_label"])})</span>' if r.get("zones_label") else ""
    legend = '<div class="legend">' + "".join(
        f'<span><i style="background:{DECISION_COLORS[d]}"></i>{d} {c[d]}</span>'
        for d in ("Good swing", "Good take", "Chase", "Taken strike")) + "</div>"
    return f"""
<div class="gbo-sheet" id="gbo-meeting-sheet"><style>{SHEET_CSS}{EXTRA_CSS}</style>
  <div class="top">
    <div><div class="kicker">{_e(team_name)} · Hitter report</div>
      <h1>{_e(name)} <span style="font-size:13px;color:#5d6670;font-weight:400">{_e(bats)}</span></h1>
      <div class="sub">{sub}</div></div>
    {_line_strip(r)}
  </div>
  <div class="sec">{_key_table(r)}</div>
  <div class="row sec">
    <div><h2>Hot zones{zl}</h2>{hot_zone_svg(r["zones"])}
      <div class="small" style="text-align:center">AVG on balls in play · red = hot · catcher's view</div></div>
    <div><h2>Swing decisions · {_pct(sd["score"])}</h2>{decisions_svg(sd["graded"])}{legend}</div>
    <div style="flex:1.3"><h2>By pitch type</h2>{_pt_table(r)}
      <h2 style="margin-top:8px">How they pitch you</h2>{_attack_block(r)}</div>
  </div>
  <div class="row sec">
    <div class="well"><h2 style="color:#1e8a4c;border-color:#1e8a4c">What went well</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in r["good"])}</ul></div>
    <div class="work"><h2 style="color:#c0392b;border-color:#c0392b">What to work on</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in r["bad"])}</ul></div>
  </div>
  {_pa_log(r)}{_game_log(r)}
  <div class="row">
    <div class="sec"><h2>Development goals</h2>{_goals_html(r["goals"])}</div>
    <div class="sec"><h2>Coach's focus</h2>{notes_html}</div>
  </div>
  <div class="foot"><span class="good">&#9650;</span> better than the D2 average (team average where there's no D2 number) · <span class="ok">&#9679;</span> about the same ·
    <span class="bad">&#9660;</span> below it · "small sample" = fewer than 4 plate appearances. Swing decisions: swing at
    the heart, take pitches off the plate, protect the edges with two strikes.</div>
</div>"""
