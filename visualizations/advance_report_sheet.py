"""
GBO -- Advance Scouting Report sheet (Oct 2026). Renders
analytics/advance_scouting.build() + the saved AdvanceReport (roles,
plan) as one printable HTML block with its own scoped CSS: page 1 =
staff + series plan, then one page per pitcher with enough pitches seen.
"""

from html import escape

from pitch_type_config import get_pitch_color
from analytics.advance_scouting import MIN_PLAN_PITCHES, STARTER_ROLES, COUNT_ROWS, MIN_HITTER_PAS

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
.gbo-adv .oneline{background:#fff7e0;border-left:4px solid #b7860b;padding:5px 8px;font-weight:600;font-size:11.5px;margin:0 0 8px}
.gbo-adv .ch td.thin{color:#9aa3ad}
.gbo-adv .ch td.hot{color:#c0392b;font-weight:700}
.gbo-adv .flag{color:#c0392b;font-weight:700}
.gbo-adv .hcards{display:grid;grid-template-columns:1fr 1fr;gap:12px 18px}
.gbo-adv .hcard{border:1px solid var(--line);border-radius:6px;padding:8px 10px;break-inside:avoid}
.gbo-adv .card-row td{vertical-align:top}
.gbo-adv .card-line{font-weight:600}
@media screen and (max-width:700px){.gbo-adv .hcards{grid-template-columns:1fr}}
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


def _short(name):
    return (name or "").replace("4-Seam Fastball", "FB").replace("2-Seam Fastball", "2S").replace("Fastball", "FB")


def _count_hand_table(prof):
    """Count x our-hitter-hand: the pitch he goes to and how often."""
    ch = prof.get("count_hand") or {}
    rows = []
    for key, label in COUNT_ROWS:
        tds = []
        for h in ("R", "L"):
            c = (ch.get(key) or {}).get(h)
            if not c:
                tds.append('<td class="thin">—</td>')
                continue
            cls = "thin" if c["thin"] else ("hot" if (c["top_pct"] or 0) >= 70 else "")
            tds.append(f'<td class="{cls}" title="{c["n"]} pitches · FB {_p(c["fb"])}">{_e(_short(c["top"]))} {_p(c["top_pct"])}'
                       f' <span class="small muted">({c["n"]})</span></td>')
        rows.append(f"<tr><td>{label}</td>{''.join(tds)}</tr>")
    return ('<table class="ch"><tr><th>Count</th><th>vs RHH</th><th>vs LHH</th></tr>' + "".join(rows) + "</table>"
            '<div class="small muted">Top pitch and how often · red = 70%+ (sit on it) · gray = under 10 pitches.</div>')


def _pitcher_page(p, damage=None):
    prof = p["profile"]
    rows = "".join(
        f'<tr><td><span class="sw" style="background:{get_pitch_color(a["pitch"])}"></span>{_e(a["pitch"])}</td>'
        f'<td>{a["n"]}</td><td><b>{_p(a["usage"])}</b></td><td>{_p(a["vs_r"])}</td><td>{_p(a["vs_l"])}</td>'
        f'<td>{_p(a["strike"])}</td><td>{_p(a["whiff"])}</td></tr>' for a in prof["arsenal"])
    f, t = prof["first"] or {}, prof["two_k"] or {}
    bars = (_count_hand_table(prof)
            + f'<div class="small muted" style="margin-top:4px">0-0 strikes {_p(f.get("strike"))} · '
              f'our 0-0 swings {_p(prof.get("first_swing"))} · 2-strike balls {_p(t.get("ball"))}</div>')
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
  {('<div class="oneline">Plan vs him: ' + _e(p.get("line")) + '</div>') if p.get("line") else ''}
  <div class="cols">
    <div style="flex:1.2"><h2>Arsenal</h2>
      <table><tr><th>Pitch</th><th>#</th><th>Use</th><th>vs RHH</th><th>vs LHH</th><th>Strike</th><th>Whiff</th></tr>{rows}</table>
      <h2 style="margin-top:10px">What he throws by count</h2>{bars}</div>
    <div style="flex:1"><h2>Fastball location</h2>
      <div style="display:flex;gap:22px">{_grid(prof['fb_grid'].get('R'), 'vs RHH')}{_grid(prof['fb_grid'].get('L'), 'vs LHH')}</div>
      <div class="small muted" style="margin-top:4px">% of his located fastballs by zone, catcher's view relative to the hitter.</div>
      <h2 style="margin-top:12px">Approach</h2><ol>{pts}</ol>{notes}</div>
  </div>{_approach_panel(prof, damage, p.get("hand"))}
</div>"""


def render_sheet(rep, report=None, team_name="Pitt State Baseball", hitters=None):
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
  {_hitters_pages(hitters) if hitters else ''}
  <div class="foot">Every number comes from pitches we charted against this team in Game Tracking -- small samples, especially vs pitchers we've seen once. Pitches thrown before GBO tracked which of their pitchers was in are grouped as "Unidentified".</div>
</div>"""



# ------------------------------------------------------------------ their hitters

def _avg(v):
    return "—" if v is None else (("%.3f" % v).lstrip("0") if v < 1 else "%.3f" % v)


def _hdamage(grid):
    cells = []
    for row in grid:
        for tb, n in row:
            if n < 2:
                cells.append('<div style="background:#e9edf1;color:#9aa3ad">·</div>')
                continue
            v = tb / n
            a = 0.12 + 0.88 * min(v, 1.0)
            cells.append(f'<div style="background:rgba(194,58,58,{a:.2f})" title="{tb} TB on {n} balls in play">{_avg(v)}</div>')
    return f'<div class="grid">{"".join(cells)}</div>'


def _hitters_lineup(hitters):
    rows = []
    for h in hitters:
        pr = h["profile"]
        line = '<span class="muted">small sample</span>' if h["small"] else _e(h["line"])
        rows.append(f'<tr><td>{h["order"] or ""}</td><td><b>{_e(h["name"])}</b> <span class="muted">{_e(h["bats"] or "?")}</span></td>'
                    f'<td>{pr["pa"]}</td><td>{_avg(pr["avg"])}/{_avg(pr["obp"])}/{_avg(pr["slg"])}</td>'
                    f'<td>{_p(pr["k_pct"])}</td><td>{_p(pr["bb_pct"])}</td><td>{_p(pr["first_swing"])}</td>'
                    f'<td>{_p(pr["chase"])}</td><td style="text-align:left;white-space:normal">{line}</td></tr>')
    return ('<table class="card-row"><tr><th>#</th><th>Hitter</th><th>PA</th><th>AVG/OBP/SLG</th><th>K</th><th>BB</th>'
            '<th>0-0 swing</th><th>Chase</th><th style="text-align:left">Plan</th></tr>' + "".join(rows) + "</table>")


def _hitter_card(h):
    pr = h["profile"]
    fam = "".join(f'<tr><td>{_e(f)}</td><td>{d["n"]}</td><td>{_p(d["whiff"])}</td><td>{_avg(d["slg_bip"])}</td>'
                  f'<td>{_p(d["hard"])}</td><td>{d["hits"]}</td></tr>' for f, d in pr["families"].items())
    note = f'<div class="notes small">{_e(h["notes"])}</div>' if h.get("notes") else ""
    return f"""<div class="hcard">
  <div style="display:flex;justify-content:space-between;align-items:baseline"><b>{_e(h['name'])}</b>
    <span class="small muted">bats {_e(h['bats'] or '?')} · {pr['pa']} PA · {_avg(pr['avg'])}/{_avg(pr['obp'])}/{_avg(pr['slg'])}</span></div>
  <div class="oneline" style="margin:4px 0 6px">{_e(h['line']) or 'No plan drafted yet.'}</div>
  <div class="cols"><div style="flex:1.4">
    <table><tr><th>vs</th><th>#</th><th>Whiff</th><th>SLG in play</th><th>Hard</th><th>Hits</th></tr>{fam}</table>
    <div class="small muted" style="margin-top:3px">0-0 swing {_p(pr['first_swing'])} · chase {_p(pr['chase'])} · 2-strike chase {_p(pr['two_chase'])}</div></div>
    <div><b class="small">Damage by zone</b>{_hdamage(pr['damage'])}<div class="small muted">SLG in play, from his side</div></div></div>{note}
</div>"""


def _hitters_pages(hitters):
    full = [h for h in hitters if not h["small"]]
    cards = "".join(_hitter_card(h) for h in full)
    return f"""
<div class="page">
  <h2>Their hitters -- what our pitchers have seen</h2>
  {_hitters_lineup(hitters)}
  <div class="small muted" style="margin-top:4px">From every pitch our staff threw them in Game Tracking; chase and zones use Rapsodo location. Hitters with fewer than {MIN_HITTER_PAS} PA get no plan yet.</div>
  {('<h2 style="margin-top:14px">Hitter by hitter</h2><div class="hcards">' + cards + '</div>') if cards else ''}
</div>"""


# ------------------------------------------------------------------ dugout card

def render_card(rep, report=None, hitters=None, team_name="Pitt State Baseball"):
    """One printable page for the dugout binder: their arms + their lineup."""
    team = rep["team"].team_name if rep["team"] else "Opponent"
    title = report.title if report else f"vs {team}"
    arms = []
    for p in rep["pitchers"] + rep["unidentified"]:
        if p["role"] == "Not expected":
            continue
        prof = p["profile"]
        mix = _e(_mixline(prof)) if prof else '<span class="muted">not seen</span>'
        arms.append(f'<tr><td>{_role(p["role"])}</td><td><b>{_e(p["name"])}</b> <span class="muted">{_e(p["hand"] or "?")}HP</span></td>'
                    f'<td style="text-align:left">{mix}</td><td class="card-line" style="text-align:left;white-space:normal">{_e(p.get("line"))}</td></tr>')
    lineup = []
    for h in hitters or []:
        pr = h["profile"]
        line = '<span class="muted">small sample</span>' if h["small"] else _e(h["line"])
        lineup.append(f'<tr><td>{h["order"] or ""}</td><td><b>{_e(h["name"])}</b> <span class="muted">{_e(h["bats"] or "?")}</span></td>'
                      f'<td>{_avg(pr["avg"])}</td><td>{_p(pr["k_pct"])}</td><td>{_p(pr["chase"])}</td>'
                      f'<td class="card-line" style="text-align:left;white-space:normal">{line}</td></tr>')
    plan = (report.plan_text if report and report.plan_text else "")
    return f"""
<div class="gbo-adv" id="gbo-advance-card"><style>{CSS}</style>
  <div class="top"><div><div class="kicker">{_e(team_name)} · Dugout card</div><h1>{_e(title)}</h1></div>
    <div class="small muted">{_e(team)}</div></div>
  <div class="cols">
    <div style="flex:1"><h2>Their arms -- plan for our hitters</h2>
      <table class="card-row"><tr><th></th><th>Pitcher</th><th style="text-align:left">Mix</th><th style="text-align:left">Plan</th></tr>{''.join(arms) or '<tr><td colspan="4" class="muted">No pitchers yet.</td></tr>'}</table>
      {('<h2 style="margin-top:10px">Series plan</h2><div class="planbox">' + _e(plan) + '</div>') if plan else ''}</div>
    <div style="flex:1"><h2>Their lineup -- plan for our pitchers</h2>
      <table class="card-row"><tr><th>#</th><th>Hitter</th><th>AVG</th><th>K</th><th>Chase</th><th style="text-align:left">Plan</th></tr>{''.join(lineup) or '<tr><td colspan="6" class="muted">No hitters charted yet.</td></tr>'}</table></div>
  </div>
</div>"""


# ------------------------------------------------------------------ self-scout

def render_self_scout(ss, team_name="Pitt State Baseball"):
    """Our pitcher, seen the way an opponent would see him."""
    prof = ss["profile"]
    spots = "".join(f'<li><span class="flag">{_e(sp["count"])} vs {sp["hand"]}HH: {_e(_short(sp["pitch"]))} {_p(sp["pct"])}</span>'
                    f' <span class="muted">({sp["n"]} pitches)</span></li>' for sp in ss["spots"])
    spots_html = (f'<ul>{spots}</ul>' if spots else
                  '<div class="small">Nothing a hitter could sit on -- no count where one pitch comes 70%+ of the time.</div>')
    page = _pitcher_page({"name": ss["name"], "hand": ss["hand"], "role": "", "points": ss["points"], "notes": None,
                          "profile": prof, "line": ss["line"]}).replace('<div class="page">', '<div>', 1)
    return f"""
<div class="gbo-adv" id="gbo-advance-self"><style>{CSS}</style>
  <div class="top"><div><div class="kicker">{_e(team_name)} · Self-scout</div><h1>{_e(ss['name'])}</h1>
    <div class="sub">How an opponent's advance report would read him -- every charted game, Rapsodo locations.</div></div></div>
  <h2>What a hitter could sit on</h2>{spots_html}
  <div style="margin-top:10px">{page}</div>
  <div class="foot">"Plan vs him" and the approach points are written the way an opposing hitting coach would use them.</div>
</div>"""


# ------------------------------------------------------------------ post-series check

def render_series_check(chk):
    if chk is None:
        return '<p class="muted">Set the series start date to check the series.</p>'
    if not chk["games"]:
        return '<p class="muted">No games against them charted in the series window yet.</p>'

    def mix(m):
        return " · ".join(f"{_e(_short(a))} {_p(b)}" for a, b in m) if m else "—"
    prow = []
    for p in chk["pitchers"]:
        pl, ac = p["planned"], p["actual"]
        prow.append(f'<tr><td><b>{_e(p["name"])}</b></td>'
                    f'<td>{_p(pl["fb0"]) if pl else "—"} → {_p(ac["fb0"])}</td>'
                    f'<td>{(_e(_short(pl["two_top"])) + " " + _p(pl["two_pct"])) if pl and pl["two_top"] else "—"} → '
                    f'{_e(_short(ac["two_top"])) if ac["two_top"] else "—"} {_p(ac["two_pct"])}</td>'
                    f'<td style="text-align:left">{mix(pl["mix"]) if pl else "<span class=muted>not seen before</span>"} → {mix(ac["mix"])}</td></tr>')
    h = chk["hitting"]
    b, d = h["before"], h["during"]
    hrow = (f'<tr><td>Swing at the 0-0 fastball</td><td>{_p(b["first_fb_swing"])} ({b["first_fb_n"]})</td><td>{_p(d["first_fb_swing"])} ({d["first_fb_n"]})</td></tr>'
            f'<tr><td>2-strike whiff rate</td><td>{_p(b["two_whiff"])} ({b["two_n"]})</td><td>{_p(d["two_whiff"])} ({d["two_n"]})</td></tr>')
    trow = "".join(f'<tr><td><b>{_e(t["name"])}</b></td><td>{_e(t["planned"] or "—")}</td><td>{t["pa"]}</td>'
                   f'<td>{t["finished_with_plan"]}</td><td>{t["outs_with_plan"]}</td><td>{t["hits"]}</td></tr>' for t in chk["their_hitters"])
    games = ", ".join(g.game_date.strftime("%b %d") for g in chk["games"])
    return f"""
<div class="gbo-adv" id="gbo-advance-check"><style>{CSS}</style>
  <div class="top"><div><div class="kicker">Post-series check</div><h1>Plan vs. what happened</h1>
    <div class="sub">Series games: {_e(games)} · "before" = everything charted before the series</div></div></div>
  <h2>Their pitchers -- did they pitch the way we planned?</h2>
  <table><tr><th>Pitcher</th><th>0-0 fastball %</th><th>2-strike pitch</th><th style="text-align:left">Top 3 mix</th></tr>{''.join(prow)}</table>
  <div class="cols" style="margin-top:12px">
    <div style="flex:1"><h2>Our hitters vs the plan</h2>
      <table><tr><th></th><th>Before</th><th>Series</th></tr>{hrow}</table>
      <div class="small muted">More 0-0 fastball swings = hunting it early; a lower 2-strike whiff rate = spitting on their put-away pitch.</div></div>
    <div style="flex:1"><h2>Their hitters vs our plan</h2>
      <table><tr><th>Hitter</th><th>Planned</th><th>PA</th><th>Finished with it</th><th>Outs with it</th><th>Hits</th></tr>{trow or '<tr><td colspan="6" class="muted">No identified hitters in the series.</td></tr>'}</table></div>
  </div>
</div>"""
