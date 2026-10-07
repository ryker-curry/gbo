"""
GBO -- Advance Scouting Report sheet (Oct 2026). Renders
analytics/advance_scouting.build() + the saved AdvanceReport (roles,
plan) as one printable HTML block with its own scoped CSS: page 1 =
staff + series plan, then one page per pitcher with enough pitches seen.
"""

from html import escape

from pitch_type_config import get_pitch_color
from analytics.advance_scouting import MIN_PLAN_PITCHES, STARTER_ROLES

CSS = """
.gbo-adv{--ink:#1b1f24;--muted:#5d6670;--line:#d6dbe0;--soft:#f3f5f7;--brand:#7a1f2b;--blue:#2f6fd6;
  background:#fff;color:var(--ink);max-width:11in;margin:0 auto;padding:.35in .4in;font-family:"Helvetica Neue",Arial,sans-serif;
  font-size:10.5px;line-height:1.35;box-shadow:0 2px 14px rgba(0,0,0,.35);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.gbo-adv *{box-sizing:border-box}
.gbo-adv .top{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:3px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.gbo-adv .kicker{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--brand);font-weight:700}
.gbo-adv h1{font-size:21px;margin:2px 0 0}.gbo-adv .sub{color:var(--muted);font-size:11px}
.gbo-adv h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--brand);margin:0 0 6px;border-bottom:2px solid var(--brand);padding-bottom:2px}
.gbo-adv h3{font-size:16px;margin:0}
.gbo-adv .cols{display:flex;gap:16px}.gbo-adv .cols>*{min-width:0}
.gbo-adv .staff{flex:1.3}.gbo-adv .plan{flex:1}
.gbo-adv .p{border-bottom:1px solid var(--line);padding:6px 0}
.gbo-adv .role{display:inline-block;min-width:44px;text-align:center;font-size:8.5px;font-weight:700;letter-spacing:.5px;
  border:1px solid var(--ink);border-radius:3px;padding:1px 4px;margin-right:6px;text-transform:uppercase}
.gbo-adv .role.st{background:var(--ink);color:#fff}
.gbo-adv .muted{color:var(--muted)}.gbo-adv .small{font-size:9px}
.gbo-adv .planbox{white-space:pre-wrap;border-left:4px solid var(--brand);padding:4px 0 4px 10px;font-size:11.5px;line-height:1.5}
.gbo-adv table{width:100%;border-collapse:collapse;font-size:10.5px;color:var(--ink)}
.gbo-adv th{font-size:8.5px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);text-align:right;font-weight:600;padding:3px 5px;border-bottom:1px solid var(--line)}
.gbo-adv th:first-child,.gbo-adv td:first-child{text-align:left}
.gbo-adv td{padding:3px 5px;border-bottom:1px solid var(--line);text-align:right}
.gbo-adv .sw{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:middle}
.gbo-adv .page{break-before:page;page-break-before:always;margin-top:22px;padding-top:12px;border-top:3px solid var(--ink)}
.gbo-adv .bar{display:flex;align-items:center;gap:8px;margin:3px 0}
.gbo-adv .bar .l{width:150px}.gbo-adv .bar .t{flex:1;height:10px;background:var(--soft);border-radius:2px;position:relative}
.gbo-adv .bar .f{position:absolute;left:0;top:0;bottom:0;background:var(--blue);border-radius:2px}
.gbo-adv .bar .v{width:38px;text-align:right;font-weight:700}
.gbo-adv .grid{display:grid;grid-template-columns:repeat(3,34px);gap:2px;margin-top:3px}
.gbo-adv .grid div{height:30px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:10px;color:#fff;border-radius:2px}
.gbo-adv ol{margin:4px 0;padding-left:18px}.gbo-adv li{margin-bottom:4px}
.gbo-adv .notes{background:var(--soft);border-radius:4px;padding:6px 8px;white-space:pre-wrap;margin-top:6px}
.gbo-adv .foot{margin-top:10px;color:var(--muted);font-size:8.5px;border-top:1px solid var(--line);padding-top:4px}
.gbo-adv h1,.gbo-adv h3,.gbo-adv h4{color:var(--ink)}
@media screen and (max-width:700px){
  .gbo-adv{padding:14px 12px}
  .gbo-adv .cols{flex-direction:column}
  .gbo-adv .bar .l{width:110px}
  .gbo-adv table{display:block;overflow-x:auto;white-space:nowrap}
}
@media print{.gbo-adv{box-shadow:none;padding:0;max-width:none}}
"""


def _e(s):
    return escape(str(s)) if s is not None else ""


def _p(v):
    return "—" if v is None else f"{v:.0f}%"


def _mixline(prof):
    return " · ".join(f"{a['pitch'].replace(' Fastball', '').replace('4-Seam', '4S').replace('2-Seam', '2S')} {a['usage']:.0f}%"
                      for a in prof["arsenal"][:4] if a["usage"] is not None)


def _role(r):
    if not r:
        return '<span class="role muted" style="border-color:#c9ced4">—</span>'
    return f'<span class="role{" st" if r in STARTER_ROLES else ""}">{_e(r)}</span>'


def _staff(rep):
    items = []
    for p in rep["pitchers"] + rep["unidentified"]:
        if p["role"] == "Not expected":
            continue
        prof = p["profile"]
        stat = (f'{prof["n"]} pitches seen in {len(prof["games"])} game{"s" if len(prof["games"]) != 1 else ""} · '
                f'K {_p(prof["k_pct"])} · BB {_p(prof["bb_pct"])}' if prof else "Not seen by us yet")
        mix = f'<div class="small">{_e(_mixline(prof))}</div>' if prof else ""
        note = f'<div class="small muted">{_e((p["notes"] or "")[:160])}</div>' if p["notes"] else ""
        hand = f' <span class="muted">{_e(p["hand"])}HP</span>' if p["hand"] else ""
        items.append(f'<div class="p">{_role(p["role"])}<b>{_e(p["name"])}</b>{hand}'
                     f'<div class="small muted">{stat}</div>{mix}{note}</div>')
    return "".join(items) or '<p class="muted">No pitchers on file yet.</p>'


def _bar(label, v, note=""):
    w = max(0, min(100, v or 0))
    return (f'<div class="bar"><div class="l">{_e(label)}</div><div class="t"><div class="f" style="width:{w}%"></div></div>'
            f'<div class="v">{_p(v)}</div><div class="small muted" style="width:120px">{_e(note)}</div></div>')


def _grid(g, title):
    if not g:
        return f'<div><b>{title}</b><div class="small muted">No located fastballs.</div></div>'
    cells = []
    for row in g["pct"]:
        for v in row:
            a = 0.12 + 0.88 * min(v, 40) / 40
            cells.append(f'<div style="background:rgba(47,111,214,{a:.2f})">{v}</div>')
    return (f'<div><b>{title}</b> <span class="small muted">({g["n"]} located)</span>'
            f'<div class="small muted">in · mid · away / up→down</div><div class="grid">{"".join(cells)}</div></div>')


def _whiff_grid(g, title):
    """Whiff % of swings by hitter-relative cell (Approach panel, Oct 2026)."""
    cells = []
    for row in g["cells"]:
        for wh, sw in row:
            if sw < 2:
                cells.append('<div style="background:#e9edf1;color:#9aa3ad">·</div>')
                continue
            v = round(100 * wh / sw)
            a = 0.12 + 0.88 * min(v, 60) / 60
            cells.append(f'<div style="background:rgba(194,58,58,{a:.2f})" title="{wh} of {sw} swings">{v}</div>')
    chase = f' · chase {_p(g["chase"])}' if g.get("chase") is not None else ""
    return (f'<div><b>{title}</b> <span class="small muted">({g["n"]}{chase})</span>'
            f'<div class="grid">{"".join(cells)}</div></div>')


def _damage_grid(d, hand):
    if not d:
        return ""
    cells = []
    for row in d:
        for tb, n in row:
            if n < 2:
                cells.append('<div style="background:#e9edf1;color:#9aa3ad">·</div>')
                continue
            v = tb / n
            a = 0.12 + 0.88 * min(v, 1.0)
            cells.append(f'<div style="background:rgba(46,156,98,{a:.2f})" title="{tb} TB on {n} balls in play">'
                         f'{("%.3f" % v).lstrip("0") if v < 1 else "%.2f" % v}</div>')
    return (f'<div><b>Our damage vs {hand}HP</b> <span class="small muted">(SLG in play)</span>'
            f'<div class="grid">{"".join(cells)}</div></div>')


def _approach_panel(prof, damage, hand):
    wg = prof.get("whiff_grids") or {}
    names = {"Fastball": "Fastball", "Breaking": "Breaking", "Offspeed": "Offspeed"}
    grids = "".join(_whiff_grid(wg[f], names[f]) for f in ("Fastball", "Breaking", "Offspeed") if f in wg)
    dmg = _damage_grid((damage or {}).get(hand), hand) if hand in ("R", "L") else ""
    tto = prof.get("tto") or []
    trows = "".join(f'<tr><td>{"1st" if t["tto"] == 1 else "2nd" if t["tto"] == 2 else "3rd+"}</td><td>{t["n"]}</td>'
                    f'<td>{_p(t["fb"])}</td><td>{_e(t["top"])} {_p(t["top_pct"])}</td><td>{_p(t["strike"])}</td></tr>'
                    for t in tto)
    ttable = (f'<table><tr><th>Time through</th><th>#</th><th>FB%</th><th>Top pitch</th><th>Strike</th></tr>{trows}</table>'
              if trows else '<div class="small muted">Not enough at-bats yet.</div>')
    return f"""
  <div class="cols" style="margin-top:10px">
    <div style="flex:1.4"><h2>Where he wins: swing-and-miss % by zone</h2>
      <div style="display:flex;gap:18px;flex-wrap:wrap">{grids}{dmg}</div>
      <div class="small muted" style="margin-top:4px">Whiffs per swing in each zone (in · mid · away, up→down, from the hitter's side), both sides of the plate. Green = how hard we hit balls in play there against {_e(hand or '?')}HP (all our at-bats). Red where he wins + pale green where we don't = lay off it.</div></div>
    <div style="flex:1"><h2>Times through the order</h2>{ttable}</div>
  </div>"""


def _pitcher_page(p, damage=None):
    prof = p["profile"]
    rows = "".join(
        f'<tr><td><span class="sw" style="background:{get_pitch_color(a["pitch"])}"></span>{_e(a["pitch"])}</td>'
        f'<td>{a["n"]}</td><td><b>{_p(a["usage"])}</b></td><td>{_p(a["vs_r"])}</td><td>{_p(a["vs_l"])}</td>'
        f'<td>{_p(a["strike"])}</td><td>{_p(a["whiff"])}</td></tr>' for a in prof["arsenal"])
    f, b, t = prof["first"] or {}, prof["behind"] or {}, prof["two_k"] or {}
    bars = (_bar("0-0 fastball", f.get("fb"), f"{f.get('n', 0)} first pitches")
            + _bar("0-0 strike rate", f.get("strike"))
            + _bar("Our 0-0 swing rate", prof.get("first_swing"))
            + _bar("Behind in count: fastball", b.get("fb"), f"{b.get('n', 0)} pitches")
            + _bar(f"2 strikes: {t.get('top', '—')}", t.get("top_pct"), f"{t.get('n', 0)} pitches")
            + _bar("2 strikes: ball rate", t.get("ball")))
    pts = "".join(f"<li>{_e(x)}</li>" for x in p["points"]) or '<li class="muted">Not enough pitches seen to draft an approach.</li>'
    notes = f'<div class="notes"><b>Notes:</b> {_e(p["notes"])}</div>' if p["notes"] else ""
    games = ", ".join(g.game_date.strftime("%b %d") for g in prof["games"])
    role = f"{_e(p['role'])} · " if p["role"] else ""
    return f"""
<div class="page">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:8px">
    <h3>{_e(p['name'])} <span class="muted" style="font-size:12px;font-weight:400">{role}{_e(p['hand'] or '?')}HP</span></h3>
    <div class="small muted">{prof['n']} pitches · {prof['bf']} batters · {prof['innings']} inn. seen ({_e(games)}) · AVG vs us {('%.3f' % prof['avg']).lstrip('0') if prof['avg'] is not None else '—'} · K {_p(prof['k_pct'])} · BB {_p(prof['bb_pct'])}</div>
  </div>
  <div class="cols">
    <div style="flex:1.2"><h2>Arsenal</h2>
      <table><tr><th>Pitch</th><th>#</th><th>Use</th><th>vs RHH</th><th>vs LHH</th><th>Strike</th><th>Whiff</th></tr>{rows}</table>
      <h2 style="margin-top:10px">Count tendencies</h2>{bars}</div>
    <div style="flex:1"><h2>Fastball location</h2>
      <div style="display:flex;gap:22px">{_grid(prof['fb_grid'].get('R'), 'vs RHH')}{_grid(prof['fb_grid'].get('L'), 'vs LHH')}</div>
      <div class="small muted" style="margin-top:4px">% of his located fastballs by zone, catcher's view relative to the hitter.</div>
      <h2 style="margin-top:12px">Approach</h2><ol>{pts}</ol>{notes}</div>
  </div>{_approach_panel(prof, damage, p.get("hand"))}
</div>"""


def render_sheet(rep, report=None, team_name="Pitt State Baseball"):
    team = rep["team"].team_name if rep["team"] else "Opponent"
    title = report.title if report else f"vs {team}"
    when = report.series_date.strftime("%A, %b %d, %Y") if report and report.series_date else ""
    games = ", ".join(g.game_date.strftime("%b %d") for g in rep["games"]) or "none yet"
    plan = (report.plan_text if report and report.plan_text else "") or "No series plan written yet."
    pages = "".join(_pitcher_page(p, rep.get("damage")) for p in rep["pitchers"] + rep["unidentified"]
                    if p["profile"] and p["profile"]["n"] >= MIN_PLAN_PITCHES and p["role"] != "Not expected")
    status = "" if (report is None or report.published) else ' <span class="role" style="border-color:#b7860b;color:#b7860b">draft</span>'
    return f"""
<div class="gbo-adv" id="gbo-advance-sheet"><style>{CSS}</style>
  <div class="top"><div><div class="kicker">{_e(team_name)} · Advance report{status}</div>
    <h1>{_e(title)}</h1><div class="sub">{_e(team)}{(' · ' + _e(when)) if when else ''}</div></div>
    <div class="small muted" style="text-align:right">From our charting: {rep['n']} pitches their staff threw us<br>Games: {_e(games)}</div></div>
  <div class="cols">
    <div class="staff"><h2>Staff -- probables and arms we may see</h2>{_staff(rep)}</div>
    <div class="plan"><h2>Series plan</h2><div class="planbox">{_e(plan)}</div></div>
  </div>
  {pages}
  <div class="foot">Every number comes from pitches we charted against this team in Game Tracking -- small samples, especially vs pitchers we've seen once. Pitches thrown before GBO tracked which of their pitchers was in are grouped as "Unidentified".</div>
</div>"""
