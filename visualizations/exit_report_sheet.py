"""
GBO -- Fall Exit Report sheets (Oct 2026). Turns analytics/exit_report.py's
build() dict + the coach's plan into 3 letter-size "paper" pages (same
scoped SHEET_CSS as the Pitcher / Hitter Report, so screen = paper):

  1. How his fall went -- key numbers with early -> late fall, pitches
     (pitchers) or zones / swing decisions (hitters), went well / work on
  2. The deep dive -- pitcher type + plan gaps, command by target lane and
     workload (pitchers) or how they pitch him + game log (hitters); body
     (testing, athlete type, training stage, test progress); goals check
  3. Offseason plan -- the 3 priorities (measure, now -> target, retest
     date, how), coach's notes, sign-off lines

Pure string building -- no Shiny, no DB.
"""

from html import escape

from visualizations.meeting_report_sheet import (SHEET_CSS, MARK, location_svg, _goals_html,
                                                 _line_strip as p_line_strip, _rate_line)
from visualizations import hitter_report_sheet as hs
from pitch_type_config import get_pitch_color

EXIT_CSS = """
.gbo-exit .gbo-sheet{margin-bottom:18px}
.gbo-exit .page-break{page-break-before:always;break-before:page}
.gbo-sheet .tr-up{color:var(--good);font-weight:700}.gbo-sheet .tr-down{color:var(--bad);font-weight:700}
.gbo-sheet .tr-flat{color:var(--muted)}
.gbo-sheet .pri{border:1px solid var(--line);border-left:5px solid var(--brand);border-radius:4px;padding:6px 9px;margin-bottom:8px}
.gbo-sheet .pri h3{margin:0 0 2px;font-size:13px}
.gbo-sheet .pri .area{font-size:8.5px;letter-spacing:1px;text-transform:uppercase;color:var(--brand);font-weight:700}
.gbo-sheet .pri .meas{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}
.gbo-sheet .pri .meas div{border:1px solid var(--line);border-radius:4px;padding:2px 7px;background:var(--soft);font-size:9.5px}
.gbo-sheet .pri .meas b{font-size:11px}
.gbo-sheet .sign{display:flex;gap:30px;margin-top:14px}
.gbo-sheet .sign div{flex:1;border-top:1px solid var(--ink);padding-top:3px;font-size:9px;color:var(--muted)}
.gbo-sheet .lanes td{text-align:center}
.gbo-sheet .chip{display:inline-block;padding:0 6px;border-radius:8px;font-size:8.5px;font-weight:700;color:#fff}
.gbo-sheet .chip.match{background:var(--good)}.gbo-sheet .chip.partly{background:var(--ok)}.gbo-sheet .chip.gap{background:var(--bad)}
"""

TREND = {"up": ("&#9650; better", "tr-up"), "down": ("&#9660; worse", "tr-down"), "flat": ("&#8212; same", "tr-flat")}


def _e(s):
    return escape(str(s)) if s is not None else ""


def _v(r, v):
    """Format one key-number value for either side's row."""
    if v is None:
        return "—"
    kind = r.get("kind") or ("%" if r.get("unit") == "%" else "num")
    if kind == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0") else s
    if kind == "%":
        return f"{v:.0f}%"
    return f"{v:.1f}"


def _key_table(rep):
    pitch = rep["side"] == "pitch"
    head = ('<tr><th>Key numbers</th><th>Fall</th><th>Early fall &#8594; late fall</th><th>Team avg</th>'
            '<th>D2 / MIAA</th>' + ('<th>Goal</th>' if pitch else '') + '<th style="text-align:center">vs goal / D2 / team</th></tr>')
    body = []
    for r in rep["rows"]:
        if r.get("you") is None and r.get("team") is None:
            continue
        mk = ""
        if r.get("mark"):
            sym, cls = MARK[r["mark"]]
            mk = f'<span class="{cls}">{sym}</span>'
        elif r.get("you") is not None:
            mk = '<span class="na">small sample</span>'
        if r.get("early") is not None and r.get("late") is not None:
            t_sym, t_cls = TREND.get(r.get("trend"), ("", ""))
            trend = f'{_v(r, r["early"])} &#8594; {_v(r, r["late"])} <span class="{t_cls}">{t_sym}</span>'
        else:
            trend = '<span class="na">—</span>'
        lg = (f'{_v(r, r.get("d2"))} / {_v(r, r.get("miaa"))}' if r.get("d2") is not None else '<span class="na">—</span>')
        goal = (f'<td>{r["goal"]:.0f}%</td>' if r.get("goal") is not None else "<td>—</td>") if pitch else ""
        body.append(f'<tr><td><b>{_e(r["label"])}</b><span class="means">{_e(r.get("means", ""))}</span></td>'
                    f'<td class="you">{_v(r, r["you"])}</td><td>{trend}</td><td>{_v(r, r.get("team"))}</td>'
                    f'<td>{lg}</td>{goal}<td class="mk">{mk}</td></tr>')
    note = ("" if rep.get("trend_ok") else
            '<div class="small">Early &#8594; late needs 4+ games -- not enough this fall to split.</div>')
    rate = _rate_line(rep) if pitch else ""
    return f'<table>{head}{"".join(body)}</table>{rate}{note}'


def _g(v):
    return "—" if v is None else f"{v:.0f}"


def _mix_table(rep):
    head = ('<tr><th>Pitch</th><th>#</th><th>Use</th><th>Velo</th><th>Strike</th><th>Whiff</th><th>Stuff+</th>'
            '<th>Location+</th><th>Pitching+</th><th>Misses toward</th></tr>')
    rows = []
    for p in rep["mix"]:
        velo = "—" if p["velo"] is None else f'{p["velo"]:.1f}' + (f' <span class="small">({p["velo_max"]:.1f})</span>' if p.get("velo_max") else "")
        rows.append(f'<tr><td><span class="sw" style="background:{get_pitch_color(p["pitch"])}"></span>{_e(p["pitch"])}</td>'
                    f'<td>{p["n"]}</td><td>{_g(p["usage_pct"])}%</td><td>{velo}</td><td>{_g(p["strike_pct"])}%</td>'
                    f'<td>{_g(p["whiff_pct"]) + "%" if p["whiff_pct"] is not None else "—"}</td>'
                    f'<td>{_g(p.get("stuff_plus"))}</td><td>{_g(p.get("location_plus"))}</td><td>{_g(p.get("pitching_plus"))}</td>'
                    f'<td>{_e(p.get("lean") or "—")}</td></tr>')
    g = rep.get("grades_overall") or {}
    tot = ""
    if g.get("stuff_plus_value") is not None:
        tot = (f'<div class="small" style="margin-top:3px">Overall: Stuff+ <b>{_g(g["stuff_plus_value"])}</b> · '
               f'Location+ <b>{_g(g.get("location_plus_value"))}</b> · Pitching+ <b>{_g(g.get("pitching_plus_value"))}</b> '
               '(100 = team average). Game pitches only.</div>')
    return f'<table>{head}{"".join(rows)}</table>{tot}'


def _went_work(rep):
    return (f'<div class="row sec"><div class="went"><h2 style="color:#1e8a4c;border-color:#1e8a4c">What went well</h2>'
            f'<ul>{"".join(f"<li>{_e(t)}</li>" for t in rep["good"])}</ul></div>'
            f'<div class="work"><h2 style="color:#c0392b;border-color:#c0392b">What to work on</h2>'
            f'<ul>{"".join(f"<li>{_e(t)}</li>" for t in rep["bad"])}</ul></div></div>')


def _header(rep, page_title, team_name):
    p = rep["player"]
    if rep["side"] == "pitch":
        tag = {"R": "RHP", "L": "LHP"}.get(p.throws, "P")
        strip = p_line_strip(rep)
    else:
        tag = {"R": "Bats R", "L": "Bats L", "S": "Switch"}.get(getattr(p, "bats", None), "")
        strip = hs._line_strip(rep)
    return (f'<div class="top"><div><div class="kicker">Fall exit report · {_e(page_title)}</div>'
            f'<h1>{_e(p.first_name)} {_e(p.last_name)} <span style="font-size:13px;color:#5d6670;font-weight:400">{_e(tag)}</span></h1>'
            f'<div class="sub">{_e(rep.get("season_name") or "")} · games only</div></div>{strip}</div>')


# ---------------------------------------------------------------------------
# Page 2 pieces
# ---------------------------------------------------------------------------

def _ptype(rep):
    t = rep.get("ptype")
    if not t:
        return '<div class="sec"><h2>Pitcher type</h2><div class="small">Needs more charted game pitches.</div></div>'
    rows = []
    for r in t["rows"]:
        chip = f'<span class="chip {r["status"]}">{ {"match": "matches", "partly": "partly", "gap": "gap"}[r["status"]] }</span>' \
            if r["status"] else '<span class="na">—</span>'
        rows.append(f'<tr><td>{_e(r["stage_lbl"])}<span class="means">{_e(r["side_lbl"])}</span></td>'
                    f'<td style="text-align:left">{_e(r["plan"])}</td><td style="text-align:left">{_e(r["actual"])}'
                    f'<span class="means">{_e(r["detail"])}</span></td><td style="text-align:center">{chip}</td></tr>')
    power = " · power" if t.get("power") else ""
    return (f'<div class="sec"><h2>Pitcher type: {_e(t["type"])}{power}</h2>'
            f'<div class="small" style="margin-bottom:3px">{_e(t["why_type"])} · {t["strike_pct"]:.0f}% strikes'
            + (f' · best swing-and-miss pitch in games: {_e(t["whiff"])}' if t.get("whiff") else "") + '</div>'
            '<table><tr><th>Count</th><th style="text-align:left">How his type should attack</th>'
            f'<th style="text-align:left">What he did in games</th><th style="text-align:center">Plan</th></tr>{"".join(rows)}</table></div>')


def _lanes(rep):
    from analytics.command_lanes import H_LANES, V_LANES
    res = rep.get("lanes")
    if not res or not res.get("overall"):
        return ('<div class="sec"><h2>Command by target lane</h2><div class="small">Needs pitches with a called spot and '
                'a location (video review).</div></div>')
    head = "<tr><th></th>" + "".join(f"<th style='text-align:center'>{h}</th>" for h in H_LANES) + "</tr>"
    body = []
    for v in V_LANES:
        cells = [f"<td><b>{v}</b></td>"]
        for h in H_LANES:
            s = res["grid"].get((v, h))
            if not s or s["avg_miss"] is None:
                cells.append("<td>—</td>")
                continue
            cls = "good" if s["avg_miss"] <= 8 else ("ok" if s["avg_miss"] <= 12 else "bad")
            cells.append(f'<td><b class="{cls}">{s["avg_miss"]:.1f}"</b> <span class="small">({s["n"]})</span></td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    take = rep.get("lanes_takeaway")
    o = res["overall"]
    allx = f' All lanes: {o["n"]} pitches, {o["avg_miss"]:.1f}" average miss.' if o.get("avg_miss") is not None else ""
    return ('<div class="sec"><h2>Command by target lane</h2>'
            + (f'<div style="margin-bottom:3px"><b>{_e(take)}</b></div>' if take else "")
            + f'<table class="lanes">{head}{"".join(body)}</table>'
            + '<div class="small">Average miss (inches) by where the catcher set up -- from the hitter\'s side '
              f'(In = toward him).{allx}</div></div>')


def _workload(rep):
    w = rep.get("workload") or {}
    if not w.get("outings"):
        return ""
    fade = (f' · velo within an outing: <b>{_e(w["fade_read"])}</b> ({w["fade_per"]:+.1f} mph per 25 pitches, '
            f'{w["fade_outings"]} outings)' if w.get("fade_read") else "")
    return (f'<div class="sec"><h2>Workload</h2><div>{w["outings"]} outings · {w["pitches"]} pitches · '
            f'{_e(w["per_outing"])} per outing (most {w["max_outing"]}){fade}</div></div>')


def _body(rep):
    b = rep.get("body") or {}
    parts = []
    bk = b.get("bucket") or {}
    scores = [("Total", bk.get("total_score")), ("Body comp", bk.get("body_comp_score")), ("Power", bk.get("power_score")),
              ("Strength", bk.get("strength_score")), ("Speed", bk.get("speed_score"))]
    scores = [(k, v) for k, v in scores if v is not None]
    if scores:
        parts.append('<div class="kv">' + "".join(f"<div>{k} <b>{v:.0f}</b></div>" for k, v in scores) + '</div>'
                     '<div class="small">Physical testing scores, 0-100 vs the team\'s best (Bucket System).</div>')
    a = b.get("arch")
    if a:
        parts.append(f'<div style="margin-top:4px"><b>{_e(a["kind"])} athlete</b> -- '
                     f'superpower: {_e(a["best"]["label"])} ({a["best"]["pct"]}th pct) · '
                     f'biggest opportunity: {_e(a["worst"]["label"])} ({a["worst"]["pct"]}th pct)</div>')
    lad = b.get("ladder")
    if lad:
        st = " · ".join(f'{s["name"]}: {"limiter" if s["status"] == "limiter" else ("ok" if s["status"] == "ok" else "not tested")}'
                        for s in lad["stages"])
        parts.append(f'<div style="margin-top:4px"><b>Training stage</b> -- {_e(st)}<br><span class="small">{_e(lad["read"])}</span></div>')
    prog = b.get("progress") or []
    if prog:
        rows = "".join(
            f'<tr><td>{_e(r["test"])}</td><td>{r["first"]:.1f} <span class="small">{r["first_date"].strftime("%-m/%-d/%y")}</span></td>'
            f'<td>{r["latest"]:.1f} <span class="small">{r["latest_date"].strftime("%-m/%-d/%y")}</span></td>'
            f'<td class="{"good" if r["better"] else ("bad" if r["better"] is False else "")}">{r["pct"]:+.0f}%</td></tr>'
            for r in prog[:6])
        parts.append('<table style="margin-top:4px"><tr><th>Test</th><th>First</th><th>Latest</th><th>Change</th></tr>'
                     f'{rows}</table>')
    if not parts:
        parts.append('<div class="small">No physical testing on file yet.</div>')
    return f'<div class="sec"><h2>The body</h2>{"".join(parts)}</div>'


def _goals(rep):
    return f'<div class="sec"><h2>Goals check (current IDP goals)</h2>{_goals_html(rep.get("goals") or [])}</div>'


# ---------------------------------------------------------------------------
# Page 3 -- the plan
# ---------------------------------------------------------------------------

def _plan(plan):
    pri = [p for p in (plan.get("priorities") or []) if (p.get("title") or "").strip()]
    if not pri:
        boxes = ('<div class="small">No priorities saved yet -- set them with the coach in the meeting.</div>'
                 + "".join('<div class="pri"><div class="ruled"></div><div class="ruled"></div><div class="ruled"></div></div>'
                           for _ in range(3)))
    else:
        out = []
        for i, p in enumerate(pri, 1):
            meas = []
            if p.get("measure_label"):
                meas.append(f'<div>Measured by <b>{_e(p["measure_label"])}</b></div>')
            if p.get("now_disp") and p["now_disp"] != "—":
                meas.append(f'<div>Now <b>{_e(p["now_disp"])}</b></div>')
            if p.get("target_disp"):
                meas.append(f'<div>Target <b>{_e(p["target_disp"])}</b></div>')
            if p.get("retest_disp"):
                meas.append(f'<div>Retest by <b>{_e(p["retest_disp"])}</b></div>')
            drills = [d.strip(" -•") for d in (p.get("drills") or "").splitlines() if d.strip()]
            out.append(f'<div class="pri"><div class="area">Priority {i}{(" · " + _e(p["area"])) if p.get("area") else ""}</div>'
                       f'<h3>{_e(p["title"])}</h3>'
                       + (f'<div>{_e(p["why"])}</div>' if p.get("why") else "")
                       + (f'<div class="meas">{"".join(meas)}</div>' if meas else "")
                       + (f'<div><b>How:</b><ul>{"".join(f"<li>{_e(d)}</li>" for d in drills)}</ul></div>' if drills else "")
                       + '</div>')
        boxes = "".join(out)
    notes = (plan.get("notes") or "").strip()
    notes_html = (f'<div class="notes">{_e(notes)}</div>' if notes else
                  '<div class="notes" style="padding-top:0">' + '<div class="ruled"></div>' * 5 + "</div>")
    met = plan.get("met_on")
    return (f'<div class="sec"><h2>Before the season: what to work on</h2>{boxes}</div>'
            f'<div class="sec"><h2>Coach\'s notes</h2>{notes_html}</div>'
            f'<div class="small">Each priority with a number is an IDP goal in GBO -- it shows on Development Plans and '
            f'My Development and updates as new games and tests come in.</div>'
            f'<div class="sign"><div>Player</div><div>Coach</div><div>Date{(": " + met.strftime("%b %d, %Y")) if met else ""}</div></div>')


def render(rep, plan, team_name="Pitt State Baseball", pages=(1, 2, 3), wrapper_id="gbo-exit-sheets"):
    """The requested pages in one block. The full 3-page block carries id
    gbo-exit-sheets, which the page's Print button copies."""
    plan = plan or {"priorities": [], "notes": "", "met_on": None}
    pitch = rep["side"] == "pitch"
    css = f"<style>{SHEET_CSS}{hs.EXTRA_CSS}{EXIT_CSS}</style>"
    if pitch:
        p1_mid = (f'<div class="row sec"><div style="flex:1.8"><h2>His pitches (fall games)</h2>{_mix_table(rep)}</div>'
                  f'<div style="flex:1"><h2>Where they went</h2>'
                  f'{location_svg(rep["locations"]) if rep.get("locations") else "<div class=small>No locations yet.</div>"}</div></div>')
        p2 = _ptype(rep) + '<div class="row">' + f'<div>{_lanes(rep)}{_workload(rep)}</div><div>{_body(rep)}</div></div>' + _goals(rep)
    else:
        sd = rep["sd"]
        c = sd["counts"]
        legend = '<div class="legend">' + "".join(
            f'<span><i style="background:{hs.DECISION_COLORS[d]}"></i>{d} {c[d]}</span>'
            for d in ("Good swing", "Good take", "Chase", "Taken strike")) + "</div>"
        p1_mid = (f'<div class="row sec"><div><h2>Hot zones</h2>{hs.hot_zone_svg(rep["zones"])}'
                  '<div class="small" style="text-align:center">AVG on balls in play · catcher\'s view</div></div>'
                  f'<div><h2>Swing decisions · {hs._pct(sd["score"])}</h2>{hs.decisions_svg(sd["graded"])}{legend}</div>'
                  f'<div style="flex:1.3"><h2>By pitch type</h2>{hs._pt_table(rep)}</div></div>')
        p2 = (f'<div class="row"><div><div class="sec"><h2>How they pitch him</h2>{hs._attack_block(rep)}</div>'
              f'{hs._game_log(rep)}</div><div>{_body(rep)}</div></div>' + _goals(rep))
    built = {
        1: lambda: (f'<div class="sec"><h2>Fall at a glance</h2>{_key_table(rep)}</div>{p1_mid}{_went_work(rep)}',
                    "1 · How his fall went"),
        2: lambda: (p2, "2 · Deep dive"),
        3: lambda: (_plan(plan), "3 · Offseason plan"),
    }
    out = []
    for i, n in enumerate(pages):
        inner, title = built[n]()
        out.append(f'<div class="gbo-sheet{" page-break" if i else ""}">{_header(rep, title, team_name)}{inner}</div>')
    wid = f' id="{wrapper_id}"' if wrapper_id else ""
    return f'<div class="gbo-exit"{wid}>{css}{"".join(out)}</div>'
