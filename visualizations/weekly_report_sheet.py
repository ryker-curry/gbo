"""
GBO -- Weekly Progress Report renderers (Oct 2026). See
analytics/weekly_report.py. render_sheet() -> the in-app page (light
"paper" card with its own scoped CSS, printable like the meeting
report); render_email() -> a short inline-styled email (highlights,
coach note, link to the full report) that survives Gmail/Outlook.
"""

from html import escape

from pitch_type_config import get_pitch_color
from analytics import league_baselines as lb

CSS = """
.gbo-wk{--ink:#1b1f24;--muted:#5d6670;--line:#d6dbe0;--soft:#f3f5f7;--brand:#7a1f2b;--good:#1e8a4c;--bad:#c0392b;--warn:#b7860b;
  background:#fff;color:var(--ink);max-width:8.5in;margin:0 auto;padding:.35in .45in;font-family:"Helvetica Neue",Arial,sans-serif;
  font-size:11px;line-height:1.35;box-shadow:0 2px 14px rgba(0,0,0,.35);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.gbo-wk *{box-sizing:border-box}
.gbo-wk .top{border-bottom:3px solid var(--ink);padding-bottom:6px;margin-bottom:10px}
.gbo-wk .kicker{font-size:9px;letter-spacing:2px;text-transform:uppercase;color:var(--brand);font-weight:700}
.gbo-wk h1{font-size:21px;margin:2px 0 0}
.gbo-wk .sub{color:var(--muted);font-size:11.5px;margin-top:2px}
.gbo-wk h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--brand);margin:12px 0 5px;border-bottom:2px solid var(--brand);padding-bottom:2px}
.gbo-wk table{width:100%;border-collapse:collapse;font-size:11px;color:var(--ink)}
.gbo-wk th{font-size:9px;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);text-align:right;font-weight:600;padding:3px 5px;border-bottom:1px solid var(--line)}
.gbo-wk th:first-child,.gbo-wk td:first-child{text-align:left}
.gbo-wk td{padding:4px 5px;border-bottom:1px solid var(--line);text-align:right;vertical-align:top}
.gbo-wk td b{font-size:12px}
.gbo-wk .d{font-size:9.5px;margin-left:3px}
.gbo-wk .up{color:var(--good)}.gbo-wk .down{color:var(--bad)}.gbo-wk .flat{color:var(--muted)}
.gbo-wk .muted{color:var(--muted)}
.gbo-wk .sw{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;vertical-align:middle}
.gbo-wk ul{margin:3px 0;padding-left:16px}.gbo-wk li{margin-bottom:3px}
.gbo-wk .hl{border-left:4px solid var(--good);padding:2px 0 2px 9px;margin:4px 0}
.gbo-wk .wt{border-left:4px solid var(--warn);padding:2px 0 2px 9px;margin:4px 0}
.gbo-wk .note{border:1px solid var(--line);border-radius:4px;padding:6px 9px;white-space:pre-wrap;background:var(--soft)}
.gbo-wk .foot{margin-top:10px;color:var(--muted);font-size:9px;border-top:1px solid var(--line);padding-top:4px}
@media print{.gbo-wk{box-shadow:none;padding:0}}
"""


def _e(s):
    return escape(str(s)) if s is not None else ""


def _num(v, d=1, suffix=""):
    return "—" if v is None else f"{v:.{d}f}{suffix}"


def _delta(this, last, d=1, higher_better=True, unit="", min_show=0.05):
    if this is None or last is None:
        return ""
    diff = this - last
    if abs(diff) < min_show:
        return '<span class="d flat">=</span>'
    good = diff > 0 if higher_better else diff < 0
    arrow = "&#9650;" if diff > 0 else "&#9660;"
    return f'<span class="d {"up" if good else "down"}">{arrow}{abs(diff):.{d}f}{unit}</span>'


def _activity(rep):
    bits = []
    if rep["bullpen_days"]:
        days = ", ".join(d.strftime("%a %b %d") for d in rep["bullpen_days"])
        bits.append(f"{len(rep['bullpen_days'])} bullpen{'s' if len(rep['bullpen_days']) != 1 else ''} ({days})")
    for g in rep["games"]:
        opp = g.opponent_team.team_name if getattr(g, "opponent_team", None) else (g.opponent_name or "game")
        bits.append(f"game vs {opp} ({g.game_date.strftime('%b %d')})")
    if rep["game_pitch_count"]:
        if rep.get("kind") == "hitter":
            pa = (rep.get("this") or {}).get("PA") or 0
            bits.append(f"{pa} plate appearance{'s' if pa != 1 else ''}, {rep['game_pitch_count']} pitches seen")
        else:
            bits.append(f"{rep['game_pitch_count']} game pitches")
    if rep["rapsodo_count"]:
        bits.append(f"{rep['rapsodo_count']} Rapsodo-tracked pitches")
    if not bits:
        return "No at-bats tracked this week." if rep.get("kind") == "hitter" else "No tracked throwing this week."
    return " · ".join(bits)


def _pitch_table(rep):
    if not rep["pitches"]:
        return '<p class="muted">No Rapsodo readings this week.</p>'
    rows = []
    for r in rep["pitches"]:
        t, l, s = r["this"], r["last"] or {}, r["season"] or {}
        rows.append(
            f'<tr><td><span class="sw" style="background:{get_pitch_color(r["label"])}"></span>{_e(r["label"])} '
            f'<span class="muted">({t["n"]})</span></td>'
            f'<td><b>{_num(t["velo"])}</b>{_delta(t["velo"], l.get("velo"))}</td>'
            f'<td>{_num(t["max"])}</td>'
            f'<td>{_num(t["ivb"])}{_delta(t["ivb"], l.get("ivb"))}</td>'
            f'<td>{_num(t["run"])}{_delta(t["run"], l.get("run"))}</td>'
            f'<td>{_num(t["stuff"], 0)}{_delta(t["stuff"], l.get("stuff"), d=0, min_show=0.5)}</td>'
            f'<td class="muted">{_num(s.get("velo"))} / {_num(s.get("max"))}</td></tr>')
    return ('<table><tr><th>Pitch (#)</th><th>Velo</th><th>Top</th><th>Ride (in)</th><th>Arm-side run (in)</th>'
            '<th>Stuff+</th><th>Season avg / top</th></tr>' + "".join(rows) + "</table>"
            '<div class="muted" style="font-size:9.5px;margin-top:3px">Arrows compare to last week. Ride and run '
            'arrows just show direction -- whether that\'s good depends on the pitch (see Arsenal Plan below).</div>')


def _game_table(rep):
    g = rep["game"]
    if not g:
        return ""
    rows = []
    for key, label, hib in (("strike_pct", "Strike %", True), ("fps_pct", "First-pitch strike %", True),
                            ("whiff_pct", "Whiff % (per swing)", True), ("bb_pct", "Walk %", False),
                            ("execution_pct", "Hit-the-spot %", True)):
        t = g["this"].get(key)
        l = (g["last"] or {}).get(key)
        s = (g["season"] or {}).get(key)
        if t is None and l is None:
            continue
        d2 = lb.pitching(key)
        rows.append(f'<tr><td>{label}</td><td><b>{_num(t, 0, "%")}</b>{_delta(t, l, d=0, higher_better=hib, unit="")}</td>'
                    f'<td>{_num(l, 0, "%")}</td><td class="muted">{_num(s, 0, "%")}</td>'
                    f'<td class="muted">{_num(d2, 0, "%") if d2 is not None else "—"}</td></tr>')
    line = g["this"]
    head = (f'<div class="muted" style="margin-bottom:3px">{line["ip_display"]} IP · {line["bf"]} batters · '
            f'{line["hits"]} H · {line["bb"]} BB · {line["ks"]} K</div>')
    return ('<h2>In games</h2>' + head + '<table><tr><th>Stat</th><th>This week</th><th>Last week</th><th>Season</th>'
            '<th>D2 avg</th></tr>' + "".join(rows) + "</table>"
            '<div class="muted" style="font-size:9.5px;margin-top:3px">D2 avg = 2026 Division II average; no public D2 '
            'number exists for strike %, first-pitch strike %, whiff % or hit-the-spot %.</div>')


def _arsenal(rep):
    if not rep["arsenal"]:
        return ""
    rows = []
    for a in rep["arsenal"]:
        if a["last"] is not None:
            d = a["last"] - a["this"]
            trend = (f'<span class="up">&#9650; {d:.1f}" closer</span>' if d >= 0.5 else
                     f'<span class="down">&#9660; {-d:.1f}" further</span>' if d <= -0.5 else '<span class="flat">about the same</span>')
        else:
            trend = '<span class="muted">first week tracked</span>'
        status = '<span class="up">at target</span>' if a["this"] <= 3.0 else ""
        rows.append(f'<tr><td><span class="sw" style="background:{get_pitch_color(a["label"])}"></span>{_e(a["label"])} '
                    f'<span class="muted">→ {_e(a["target_name"])} target</span></td>'
                    f'<td><b>{a["this"]:.1f}"</b> {status}</td><td>{_num(a["last"], 1, chr(34))}</td><td>{trend}</td></tr>')
    return ('<h2>Arsenal Plan progress</h2><table><tr><th>Pitch</th><th>From target this week</th><th>Last week</th>'
            '<th>Trend</th></tr>' + "".join(rows) + '</table><div class="muted" style="font-size:9.5px;margin-top:3px">'
            'Inches between this week\'s shape (ride + run) and the target on Pitcher Profile → Arsenal Plan. 3" or less = at target.</div>')


_HIT_ROWS = (("AVG", "AVG", True, "avg"), ("OBP", "OBP", True, "avg"), ("SLG", "SLG", True, "avg"),
             ("Swing Decision %", "Swing decisions", True, "%"), ("Chase %", "Chase %", False, "%"),
             ("Zone Swing %", "Zone swing %", True, "%"), ("Whiff %", "Whiff % (per swing)", False, "%"),
             ("K%", "Strikeout %", False, "%"), ("BB%", "Walk %", True, "%"),
             ("Hard contact %", "Hard contact %", True, "%"), ("Pitches/PA", "Pitches per PA", True, "num"))


def _hv(kind, v):
    if v is None:
        return "—"
    if kind == "avg":
        x = f"{v:.3f}"
        return x[1:] if x.startswith("0") else x
    return f"{v:.0f}%" if kind == "%" else f"{v:.1f}"


def _hitter_body(rep):
    t, l, s = rep["this"], rep["last"] or {}, rep["season"] or {}
    head = (f'<div class="muted" style="margin-bottom:3px">{t["PA"]} PA · {t["H"]}-for-{t["AB"]} · {t["BB"]} BB · '
            f'{t["K"]} K</div>')
    rows = []
    for key, label, hib, kind in _HIT_ROWS:
        tv, lv, sv = t.get(key), l.get(key), s.get(key)
        if tv is None and lv is None:
            continue
        d = 3 if kind == "avg" else (1 if kind == "num" else 0)
        delta = _delta(tv, lv, d=d, higher_better=hib, min_show=(0.001 if kind == "avg" else 0.5 if kind == "%" else 0.05))
        if kind == "avg":
            delta = delta.replace("0.", ".")
        d2 = lb.hitting(key)
        rows.append(f'<tr><td>{label}</td><td><b>{_hv(kind, tv)}</b>{delta}</td><td>{_hv(kind, lv)}</td>'
                    f'<td class="muted">{_hv(kind, sv)}</td><td class="muted">{_hv(kind, d2)}</td></tr>')
    table = ('<h2>At the plate</h2>' + head + '<table><tr><th>Stat</th><th>This week</th><th>Last week</th><th>Season</th>'
             '<th>D2 avg</th></tr>' + "".join(rows) + "</table>")
    pt = ""
    if rep.get("pt"):
        prow = []
        for r in rep["pt"]["All"]:
            if not r["Seen"]:
                continue
            prow.append(f'<tr><td>{_e(r["Pitch"])}</td><td>{r["Seen"]}</td><td>{_hv("%", r["Swing %"])}</td>'
                        f'<td>{_hv("%", r["Whiff %"])}</td><td>{_hv("%", r["Chase %"])}</td><td>{_hv("avg", r["AVG"])}</td></tr>')
        if prow:
            pt = ('<h2>By pitch type this week</h2><table><tr><th>Pitch</th><th>Seen</th><th>Swing</th><th>Whiff</th>'
                  '<th>Chase</th><th>AVG</th></tr>' + "".join(prow) + "</table>")
    c = rep["sd"]["counts"]
    sd = (f'<h2>Swing decisions this week</h2><div>{c["Good swing"]} good swings · {c["Good take"]} good takes · '
          f'<span class="down">{c["Chase"]} chases</span> · <span class="down">{c["Taken strike"]} hittable strikes taken</span>'
          f'</div><div class="muted" style="font-size:9.5px;margin-top:3px">Swing at the heart of the plate, take pitches '
          f'off it, protect the edges with two strikes. Full chart: Hitter Profile → Swing Decisions.</div>')
    return table + sd + pt


def render_sheet(rep, note=None, team_name="Pitt State Baseball"):
    p = rep["player"]
    if rep.get("kind") == "hitter":
        wk = f'{rep["week_start"].strftime("%b %d")} – {rep["week_end"].strftime("%b %d, %Y")}'
        hl = "".join(f'<div class="hl">{_e(t)}</div>' for t in rep["highlights"]) or '<div class="muted">No big moves this week.</div>'
        watch = "".join(f'<div class="wt">{_e(t)}</div>' for t in rep["watch"])
        note_html = f'<h2>Coach\'s note</h2><div class="note">{_e(note.strip())}</div>' if note and note.strip() else ""
        return f"""
<div class="gbo-wk" id="gbo-weekly-sheet"><style>{CSS}</style>
  <div class="top"><div class="kicker">{_e(team_name)} · Weekly progress report</div>
    <h1>{_e(p.first_name)} {_e(p.last_name)}</h1>
    <div class="sub">Week of {wk}</div>
    <div class="sub">{_e(_activity(rep))}</div></div>
  <h2>This week</h2>{hl}{watch}
  {note_html}
  {_hitter_body(rep)}
  <div class="foot">Built automatically from GBO every Monday from your charted game at-bats. Season = this season to date.</div>
</div>"""
    wk = f'{rep["week_start"].strftime("%b %d")} – {rep["week_end"].strftime("%b %d, %Y")}'
    hl = "".join(f'<div class="hl">{_e(t)}</div>' for t in rep["highlights"]) or '<div class="muted">No big moves this week.</div>'
    watch = "".join(f'<div class="wt">{_e(t)}</div>' for t in rep["watch"])
    note_html = f'<h2>Coach\'s note</h2><div class="note">{_e(note.strip())}</div>' if note and note.strip() else ""
    return f"""
<div class="gbo-wk" id="gbo-weekly-sheet"><style>{CSS}</style>
  <div class="top"><div class="kicker">{_e(team_name)} · Weekly progress report</div>
    <h1>{_e(p.first_name)} {_e(p.last_name)}</h1>
    <div class="sub">Week of {wk}</div>
    <div class="sub">{_e(_activity(rep))}</div></div>
  <h2>This week</h2>{hl}{watch}
  {note_html}
  <h2>Your pitches (Rapsodo, bullpens + games)</h2>{_pitch_table(rep)}
  {_game_table(rep)}
  {_arsenal(rep)}
  <div class="foot">Built automatically from GBO every Monday. Season = this season to date. Stuff+ 100 = team average for that pitch.</div>
</div>"""


def render_email(rep, note=None, app_url=None):
    p = rep["player"]
    wk = rep["week_start"].strftime("%b %d")
    li = "".join(f'<li style="margin:0 0 6px">{_e(t)}</li>' for t in rep["highlights"]) or \
        '<li style="margin:0 0 6px">No big moves this week -- see the full report for the numbers.</li>'
    watch = "".join(f'<p style="margin:8px 0;padding-left:10px;border-left:3px solid #b7860b">{_e(t)}</p>' for t in rep["watch"])
    note_html = (f'<p style="margin:12px 0 4px;font-weight:bold">Coach\'s note</p>'
                 f'<p style="margin:0;padding:8px 10px;background:#f3f5f7;white-space:pre-wrap">{_e(note.strip())}</p>'
                 if note and note.strip() else "")
    btn = (f'<p style="margin:18px 0"><a href="{_e(app_url)}" style="background:#7a1f2b;color:#fff;padding:10px 16px;'
           f'text-decoration:none;border-radius:4px;font-weight:bold">See your full weekly report in GBO</a></p>'
           f'<p style="font-size:12px;color:#5d6670">In GBO: My Development → My Weekly Report.</p>' if app_url else
           '<p style="font-size:12px;color:#5d6670">See the full report in GBO: My Development → My Weekly Report.</p>')
    return f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1b1f24;max-width:560px">
<p style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#7a1f2b;font-weight:bold;margin:0">Weekly progress report</p>
<h2 style="margin:4px 0 2px">{_e(p.first_name)}, here's your week of {wk}</h2>
<p style="color:#5d6670;margin:0 0 12px;font-size:13px">{_e(_activity(rep))}</p>
<ul style="padding-left:18px;margin:0">{li}</ul>{watch}{note_html}{btn}</div>"""


def email_subject(rep):
    return f"Your weekly report -- week of {rep['week_start'].strftime('%b %d')}"
