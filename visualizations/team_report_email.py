"""
GBO -- Team Game Report email (Oct 2026). Short, inline-styled (survives
Gmail/Outlook): final score, team pitching + hitting lines, standouts, a
per-player mini table for each side, and a link to the full page.
See analytics/team_report.py.
"""

from html import escape

from analytics import team_report


def _e(s):
    return escape(str(s)) if s is not None else ""


def _a(v):
    if v is None:
        return "—"
    s = f"{v:.3f}"
    return s[1:] if s.startswith("0") else s


def _p(v):
    return "—" if v is None else f"{v:.0f}%"


TD = 'style="padding:3px 6px;border-bottom:1px solid #e3e6ea;text-align:right;font-size:12px"'
TDL = 'style="padding:3px 6px;border-bottom:1px solid #e3e6ea;text-align:left;font-size:12px"'
TH = 'style="padding:3px 6px;border-bottom:1px solid #c9ced6;text-align:right;font-size:10px;color:#5d6670;text-transform:uppercase"'
THL = 'style="padding:3px 6px;border-bottom:1px solid #c9ced6;text-align:left;font-size:10px;color:#5d6670;text-transform:uppercase"'


def _table(head, rows):
    h = "".join(f"<th {THL if i == 0 else TH}>{_e(c)}</th>" for i, c in enumerate(head))
    b = "".join("<tr>" + "".join(f"<td {TDL if i == 0 else TD}>{_e(c)}</td>" for i, c in enumerate(r)) + "</tr>" for r in rows)
    return f'<table style="border-collapse:collapse;width:100%;margin:4px 0 10px">{"<tr>" + h + "</tr>"}{b}</table>'


def subject(game):
    if game.status == "Final" and not game.is_intrasquad:
        res = "W" if game.our_score > game.opponent_score else ("L" if game.our_score < game.opponent_score else "T")
        return f"Team report: {res} {game.our_score}-{game.opponent_score} {team_report.opponent_label(game)} ({game.game_date.strftime('%b %d')})"
    return f"Team report: {team_report.opponent_label(game)} ({game.game_date.strftime('%b %d')})"


def render_email(rep, game, app_url=None):
    tp, th = rep["pitching"]["team"], rep["hitting"]["team"]
    head = _e(team_report.game_label(game))
    parts = [f'<div style="font-family:Arial,Helvetica,sans-serif;color:#1b1f24;max-width:640px">',
             '<p style="font-size:11px;letter-spacing:2px;text-transform:uppercase;color:#7a1f2b;font-weight:bold;margin:0">Team game report</p>',
             f'<h2 style="margin:4px 0 10px">{head}</h2>']
    so = rep["standouts"]
    if so["pitching"] or so["hitting"]:
        li = "".join(f'<li style="margin:0 0 4px">{_e(x)}</li>' for x in so["pitching"] + so["hitting"])
        parts.append(f'<p style="margin:0 0 4px;font-weight:bold">Standouts</p><ul style="margin:0 0 10px;padding-left:18px;font-size:13px">{li}</ul>')
    if tp:
        parts.append(f'<p style="margin:10px 0 2px;font-weight:bold">Pitching · {tp["ip_display"]} IP, {tp["hits"]} H, {tp["runs"]} R, '
                     f'{tp["bb"]} BB, {tp["ks"]} K</p><p style="margin:0;font-size:12px;color:#5d6670">Strike {_p(tp["strike_pct"])} · '
                     f'1st-pitch strike {_p(tp["fps_pct"])} · whiff {_p(tp["whiff_pct"])} · {tp["pitches"]} pitches</p>')
        parts.append(_table(["Pitcher", "IP", "P", "H", "R", "BB", "K", "Strike"],
                            [[r["name"], r["ip"], r["pitches"], r["h"], r["r"], r["bb"], r["k"], _p(r["strike_pct"])]
                             for r in rep["pitching"]["rows"]]))
    if th:
        sd = rep["hitting"]["sd"]
        parts.append(f'<p style="margin:10px 0 2px;font-weight:bold">Hitting · {th["H"]}-for-{th["AB"]}, {th["BB"]} BB, {th["K"]} K · '
                     f'{_a(th["AVG"])}/{_a(th["OBP"])}/{_a(th["SLG"])}</p><p style="margin:0;font-size:12px;color:#5d6670">'
                     f'Swing decisions {_p(th["Swing Decision %"])} · chase {_p(th["Chase %"])} · '
                     f'{sd["counts"]["Taken strike"]} hittable strikes taken · hard contact {_p(th["Hard contact %"])} · '
                     f'QAB {_p(th["QAB%"])}</p>')
        parts.append(_table(["Hitter", "PA", "AB", "H", "BB", "K", "QAB", "Swing dec."],
                            [[r["name"], r["pa"], r["ab"], r["h"], r["bb"], r["k"], f'{r["qab"]}/{r["pa"]}', _p(r["sd"])]
                             for r in rep["hitting"]["rows"]]))
    if app_url:
        parts.append(f'<p style="margin:16px 0"><a href="{_e(app_url)}" style="background:#7a1f2b;color:#fff;padding:10px 16px;'
                     f'text-decoration:none;border-radius:4px;font-weight:bold">Open the full team report in GBO</a></p>')
    parts.append('<p style="font-size:12px;color:#5d6670">In GBO: Analytics → Team Game Report. Pick any player there for his own report.</p></div>')
    return "".join(parts)
