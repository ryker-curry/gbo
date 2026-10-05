"""
GBO -- Pitcher Meeting Report sheet renderer (Oct 2026).

Turns analytics/player_report.py's game_report()/season_report() dict
into ONE self-contained HTML block: a letter-size, light "paper" sheet
with its own scoped <style>, so it looks the same on screen as on paper.
The page's Print button copies just this block into a print window (see
shiny_app/modules/pitcher_meeting_report.py), so it prints as exactly one
page with none of the app around it.

Pure string building, no Shiny/DB -- easy to preview and test.

Marks print in color AND shape (triangle up / dot / triangle down) so
they still read on a black-and-white printer.
"""

from html import escape

from pitch_type_config import get_pitch_color
from strike_zone import ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP

SHEET_CSS = """
.gbo-sheet{--ink:#1b1f24;--muted:#5d6670;--line:#d6dbe0;--soft:#f3f5f7;--brand:#7a1f2b;--good:#1e8a4c;--ok:#b7860b;--bad:#c0392b;
  background:#fff;color:var(--ink);width:8.5in;max-width:100%;min-height:11in;box-sizing:border-box;padding:.4in .45in;
  margin:0 auto;font-family:"Helvetica Neue",Arial,sans-serif;font-size:10px;line-height:1.25;
  box-shadow:0 2px 14px rgba(0,0,0,.35);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.gbo-sheet *{box-sizing:border-box}
.gbo-sheet h1{font-size:22px;margin:0;letter-spacing:.3px}
.gbo-sheet h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--brand);margin:0 0 4px;
  border-bottom:2px solid var(--brand);padding-bottom:2px}
.gbo-sheet .top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:6px;margin-bottom:8px}
.gbo-sheet .kicker{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--brand);font-weight:700}
.gbo-sheet .sub{color:var(--muted);font-size:11px;margin-top:2px}
.gbo-sheet .line{display:flex;gap:4px}
.gbo-sheet .line div{border:1px solid var(--line);border-radius:4px;padding:3px 7px;text-align:center;min-width:42px;background:var(--soft)}
.gbo-sheet .line b{display:block;font-size:15px}
.gbo-sheet .line span{font-size:8.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.gbo-sheet table{width:100%;border-collapse:collapse;font-size:10px;color:var(--ink)}
.gbo-sheet th{font-size:8.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);text-align:right;font-weight:600;
  padding:2px 4px;border-bottom:1px solid var(--line)}
.gbo-sheet th:first-child,.gbo-sheet td:first-child{text-align:left}
.gbo-sheet td{padding:2px 4px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
.gbo-sheet td.you{font-weight:700;font-size:12px}
.gbo-sheet .means{display:block;color:var(--muted);font-size:8.5px;font-weight:400}
.gbo-sheet .mk{font-size:12px;text-align:center}
.gbo-sheet .good{color:var(--good)}.gbo-sheet .ok{color:var(--ok)}.gbo-sheet .bad{color:var(--bad)}.gbo-sheet .na{color:#99a;font-size:8.5px}
.gbo-sheet .sec{margin-bottom:6px}
.gbo-sheet .row{display:flex;gap:12px}
.gbo-sheet .row>*{flex:1;min-width:0}
.gbo-sheet .sw{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;vertical-align:middle}
.gbo-sheet ul{margin:2px 0 0;padding-left:15px}
.gbo-sheet li{margin-bottom:3px}
.gbo-sheet .well{border-left:4px solid var(--good);padding-left:8px}
.gbo-sheet .work{border-left:4px solid var(--bad);padding-left:8px}
.gbo-sheet .notes{border:1px solid var(--line);border-radius:4px;padding:5px 8px;min-height:60px;white-space:pre-wrap}
.gbo-sheet .ruled{height:16px;border-bottom:1px solid var(--line)}
.gbo-sheet .foot{margin-top:6px;color:var(--muted);font-size:8.5px;border-top:1px solid var(--line);padding-top:4px}
.gbo-sheet .small{font-size:9px;color:var(--muted)}
.gbo-sheet h1,.gbo-sheet h3,.gbo-sheet h4{color:var(--ink)}
@media screen and (max-width:700px){
  .gbo-sheet{padding:14px 12px;min-height:0;font-size:11px}
  .gbo-sheet .top{flex-direction:column;align-items:flex-start;gap:8px}
  .gbo-sheet .row{flex-direction:column;gap:10px}
  .gbo-sheet .line{flex-wrap:wrap}
  .gbo-sheet table{display:block;overflow-x:auto;white-space:nowrap}
  .gbo-sheet .means{white-space:normal}
}
@media print{.gbo-sheet{box-shadow:none;width:auto;min-height:0;padding:0;margin:0}}
"""

MARK = {"good": ("&#9650;", "good"), "ok": ("&#9679;", "ok"), "bad": ("&#9660;", "bad")}


def _e(s):
    return escape(str(s)) if s is not None else ""


def _f(m, v):
    if v is None:
        return "—"
    return f"{v:.0f}%" if m["unit"] == "%" else f"{v:.1f}"


def _pct(v):
    return "—" if v is None else f"{v:.0f}%"


def _num(v, d=1):
    return "—" if v is None else f"{v:.{d}f}"


def _fmt_goal_value(v):
    if v is None:
        return "—"
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def location_svg(points, width=230, height=232):
    """Pitcher's view (his view from the mound): plate_x is the catcher's-
    view coordinate, so it's flipped here. 1B side on the left."""
    x0, x1, z0, z1 = -2.0, 2.0, 0.6, 4.4
    pad_b = 18

    def sx(x):
        return (-x - x0) / (x1 - x0) * width

    def sz(z):
        return (z1 - z) / (z1 - z0) * (height - pad_b)

    zl, zr = sx(ZONE_HALF_WIDTH), sx(-ZONE_HALF_WIDTH)
    zt, zb = sz(ZONE_TOP), sz(ZONE_BOTTOM)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" xmlns="http://www.w3.org/2000/svg">',
             f'<rect x="0" y="0" width="{width}" height="{height - pad_b}" fill="#f7f8fa" stroke="#d6dbe0"/>']
    w3, h3 = (zr - zl) / 3, (zb - zt) / 3
    for i in (1, 2):
        parts.append(f'<line x1="{zl + w3 * i:.1f}" y1="{zt:.1f}" x2="{zl + w3 * i:.1f}" y2="{zb:.1f}" stroke="#c9ced4" stroke-width="0.8"/>')
        parts.append(f'<line x1="{zl:.1f}" y1="{zt + h3 * i:.1f}" x2="{zr:.1f}" y2="{zt + h3 * i:.1f}" stroke="#c9ced4" stroke-width="0.8"/>')
    parts.append(f'<rect x="{zl:.1f}" y="{zt:.1f}" width="{zr - zl:.1f}" height="{zb - zt:.1f}" fill="none" stroke="#1b1f24" stroke-width="1.6"/>')
    # Plate, pitcher's view: flat front edge nearest the viewer (bottom), point toward the zone.
    gy = sz(0.95)
    pw = zr - zl
    parts.append(
        f'<path d="M {zl:.1f} {gy + 10:.1f} L {zr:.1f} {gy + 10:.1f} L {zr:.1f} {gy + 4:.1f} '
        f'L {zl + pw / 2:.1f} {gy - 3:.1f} L {zl:.1f} {gy + 4:.1f} Z" fill="#ffffff" stroke="#1b1f24" stroke-width="1.2"/>')
    for x, z, label, _outcome in points:
        if not (x0 - 0.5 <= -x <= x1 + 0.5 and z0 - 0.5 <= z <= z1 + 0.5):
            continue
        cx = min(max(sx(x), 3), width - 3)
        cy = min(max(sz(z), 3), height - pad_b - 3)
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.6" fill="{get_pitch_color(label)}" '
                     f'fill-opacity="0.8" stroke="#ffffff" stroke-width="0.6"/>')
    parts.append(f'<text x="4" y="{height - 5}" font-size="9" fill="#5d6670">&#8592; 1B side</text>')
    parts.append(f'<text x="{width - 4}" y="{height - 5}" font-size="9" fill="#5d6670" text-anchor="end">3B side &#8594;</text>')
    parts.append(f'<text x="{width / 2}" y="{height - 5}" font-size="9" fill="#5d6670" text-anchor="middle">your view from the mound</text>')
    parts.append("</svg>")
    return "".join(parts)


def _line_strip(r):
    y = r["you"]
    cells = []
    if r["kind"] == "season":
        cells.append(("G", y["games"]))
    cells += [("IP", y["ip_display"]), ("Pitches", y["pitches"]), ("Batters", y["bf"]), ("H", y["hits"]),
              ("R", y["runs"]), ("BB", y["bb"]), ("K", y["ks"])]
    if y.get("hbp"):
        cells.append(("HBP", y["hbp"]))
    if r["kind"] == "season":
        cells.append(("ERA*", _num(y["era"], 2)))
    return '<div class="line">' + "".join(f"<div><b>{_e(v)}</b><span>{_e(k)}</span></div>" for k, v in cells) + "</div>"


def _league(m):
    d2, mi = m.get("d2"), m.get("miaa")
    if d2 is None and mi is None:
        return '<span class="na">—</span>'
    return f'{_f(m, d2)} / {_f(m, mi)}'


def _rate_line(r):
    """ERA / WHIP vs D2 and MIAA (Oct 2026) -- only once there are 3+ IP."""
    from analytics import league_baselines as lb
    y = r["you"]
    if (y.get("outs") or 0) < 9 or y.get("era") is None:
        return ""
    eplus = round(100 * lb.pitching("era") / y["era"]) if y["era"] else None
    bits = [f'ERA* <b>{y["era"]:.2f}</b> (D2 {lb.pitching("era"):.2f} · MIAA {lb.pitching("era", "MIAA"):.2f})'
            + (f' · ERA+ <b>{eplus}</b>' if eplus is not None else "")]
    if y.get("whip") is not None:
        bits.append(f'WHIP <b>{y["whip"]:.2f}</b> (D2 {lb.pitching("whip"):.2f} · MIAA {lb.pitching("whip", "MIAA"):.2f})')
    return f'<div class="small" style="margin-top:3px">{" &nbsp;·&nbsp; ".join(bits)} &nbsp;<span class="na">D2/MIAA = 2026 league ERA; ERA* here counts every run, so it reads a little high next to them</span></div>'


def _key_table(r):
    you_h = "This game" if r["kind"] == "game" else "Season"
    head = (f'<tr><th>Key numbers</th><th>{you_h}</th><th>{_e(r["mine_label"])}</th>'
            '<th>Team avg</th><th>D2 / MIAA</th><th>Goal</th><th style="text-align:center">vs goal / D2 / team</th></tr>')
    body = []
    for m in r["rows"]:
        if m["you"] is None and m["team"] is None:
            continue
        if m["mark"]:
            sym, cls = MARK[m["mark"]]
            mk = f'<span class="{cls}">{sym}</span>'
        else:
            mk = '<span class="na" title="Not enough chances to judge">small sample</span>' if m["you"] is not None else ""
        sample = f' <span class="small">({m["sample"]})</span>' if m["sample"] is not None and m["unit"] == "%" else ""
        goal = f'{m["goal"]:.0f}%' if m.get("goal") is not None else "—"
        body.append(
            f'<tr><td><b>{_e(m["label"])}</b><span class="means">{_e(m["means"])}</span></td>'
            f'<td class="you">{_f(m, m["you"])}{sample}</td><td>{_f(m, m["mine"])}</td><td>{_f(m, m["team"])}</td>'
            f'<td>{_league(m)}</td><td>{goal}</td><td class="mk">{mk}</td></tr>')
    return f'<table>{head}{"".join(body)}</table>{_rate_line(r)}'


def _mix_table(r):
    has_velo = any(p["velo"] is not None for p in r["mix"])
    head = ('<tr><th>Pitch</th><th>#</th><th>Use</th>' + ('<th>Velo</th>' if has_velo else '')
            + '<th>Strike</th><th>Whiff</th><th>Hit spot</th><th>Best zone</th><th>Misses toward</th></tr>')
    rows = []
    for p in r["mix"]:
        velo = ""
        if has_velo:
            velo = f'<td>{_num(p["velo"])}' + (f' <span class="small">({_num(p["velo_max"])})</span>' if p["velo_max"] else "") + "</td>"
        rows.append(
            f'<tr><td><span class="sw" style="background:{get_pitch_color(p["pitch"])}"></span>{_e(p["pitch"])}</td>'
            f'<td>{p["n"]}</td><td>{_pct(p["usage_pct"])}</td>{velo}<td>{_pct(p["strike_pct"])}</td>'
            f'<td>{_pct(p["whiff_pct"])}</td><td>{_pct(p["spot_pct"])}</td><td>{_pct(p.get("bz_pct"))}</td>'
            f'<td>{_e(p["lean"] or "—")}</td></tr>')
    note = ('<div class="small" style="margin-top:3px">Velo = average (top) from Rapsodo. Whiff = misses per swing. '
            'Hit spot = landed in the called zone. Best zone = landed where that pitch plays best. '
            'Misses toward = average miss from the called spot.</div>')
    return f'<table>{head}{"".join(rows)}</table>{note}'


def _stuff_why(r):
    lines = r.get("stuff_why") or []
    if not lines:
        return ""
    scope = f' <span class="small">({_e(r["stuff_why_scope"])})</span>' if r.get("stuff_why_scope") else ""
    return (f'<div class="sec"><h2>Why your stuff grades what it does{scope}</h2><ul>'
            + "".join(f"<li>{_e(t)}</li>" for t in lines)
            + '</ul><div class="small">Stuff+: 100 = team average for that pitch. Numbers in () are Stuff+ points '
              'each trait adds or costs.</div></div>')


def _goals_html(goals):
    if not goals:
        return '<div class="small">No active development goals in GBO. Set them on Development Plans.</div>'
    items = []
    for g in goals:
        bits = []
        if g["baseline"] is not None or g["target"] is not None or g["current"] is not None:
            bits.append(f'start {_fmt_goal_value(g["baseline"])} &#8594; now <b>{_fmt_goal_value(g["current"])}</b> '
                        f'&#8594; target {_fmt_goal_value(g["target"])}')
        if g["target_date"]:
            bits.append(f'by {g["target_date"].strftime("%b %d")}')
        what = " · ".join(x for x in (g["metric"], g["pitch"]) if x)
        items.append(f'<li><b>{_e(g["description"])}</b>' + (f' <span class="small">({_e(what)})</span>' if what else "")
                     + (f'<br><span class="small">{" · ".join(bits)}</span>' if bits else "") + "</li>")
    return f'<ul>{"".join(items)}</ul>'


def _game_log(r):
    if not r.get("game_log"):
        return ""
    rows = []
    for g in r["game_log"][:5]:
        game = g["game"]
        opp = game.opponent_team.team_name if getattr(game, "opponent_team", None) else (game.opponent_name or "—")
        rows.append(f'<tr><td>{game.game_date.strftime("%b %d")} &nbsp;{_e(opp)}</td><td>{_e(g["ip_display"])}</td>'
                    f'<td>{g["pitches"]}</td><td>{g["hits"]}</td><td>{g["runs"]}</td><td>{g["bb"]}</td><td>{g["ks"]}</td>'
                    f'<td>{_pct(g["strike_pct"])}</td><td>{_pct(g["fps_pct"])}</td></tr>')
    return ('<div class="sec"><h2>Recent outings</h2><table><tr><th>Game</th><th>IP</th><th>Pitches</th><th>H</th><th>R</th>'
            f'<th>BB</th><th>K</th><th>Strike</th><th>1st-pitch K</th></tr>{"".join(rows)}</table></div>')


def render_sheet(r, notes=None, team_name="Pitt State Baseball"):
    player = r["player"]
    name = f"{player.first_name} {player.last_name}"
    if r["kind"] == "game":
        g = r["game"]
        opp = g.opponent_team.team_name if getattr(g, "opponent_team", None) else (g.opponent_name or "opponent")
        loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs")
        sub = f'Game report · {g.game_date.strftime("%A, %b %d, %Y")} · {loc} {_e(opp)}'
    else:
        sub = f'Season report · {_e(r.get("season_name") or "")} · {r["you"]["games"]} games'
    hand = {"R": "RHP", "L": "LHP"}.get(player.throws, "P")

    if notes and notes.strip():
        notes_html = f'<div class="notes">{_e(notes.strip())}</div>'
    else:
        notes_html = '<div class="notes" style="padding-top:0">' + '<div class="ruled"></div>' * 4 + "</div>"

    goals_block = f'<div class="sec"><h2>Development goals</h2>{_goals_html(r["goals"])}</div>'
    log_block = _game_log(r)
    era_note = ' ERA* counts every run as earned.' if r["kind"] == "season" else ""

    return f"""
<div class="gbo-sheet" id="gbo-meeting-sheet"><style>{SHEET_CSS}</style>
  <div class="top">
    <div><div class="kicker">{_e(team_name)} · Pitcher report</div>
      <h1>{_e(name)} <span style="font-size:13px;color:#5d6670;font-weight:400">{hand}</span></h1>
      <div class="sub">{sub}</div></div>
    {_line_strip(r)}
  </div>
  <div class="sec">{_key_table(r)}</div>
  <div class="row sec">
    <div style="flex:1.55"><h2>Your pitches</h2>{_mix_table(r)}</div>
    <div style="flex:1"><h2>Where they went</h2>{location_svg(r["locations"]) if r["locations"] else '<div class="small">No pitch locations yet (added during video review).</div>'}</div>
  </div>
  <div class="row sec">
    <div class="well"><h2 style="color:#1e8a4c;border-color:#1e8a4c">What went well</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in r["good"])}</ul></div>
    <div class="work"><h2 style="color:#c0392b;border-color:#c0392b">What to work on</h2><ul>{"".join(f"<li>{_e(t)}</li>" for t in r["bad"])}</ul></div>
  </div>
  {_stuff_why(r)}
  {log_block}
  <div class="row">
    {goals_block}
    <div class="sec"><h2>Coach's focus</h2>{notes_html}</div>
  </div>
  <div class="foot"><span class="good">&#9650;</span> better than the goal (or the D2 average, or team average when neither exists) ·
    <span class="ok">&#9679;</span> about the same · <span class="bad">&#9660;</span> below it · "small sample" = too few chances to judge.
    Numbers in ( ) are how many chances.{era_note}</div>
</div>"""
