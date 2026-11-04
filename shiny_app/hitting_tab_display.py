"""
GBO -- Player Profile "Hitting" tab (Nov 2026, Ryker). Position players
get this in place of the Pitching tab; a pitcher who also hits gets both.
Numbers from analytics/hitting_summary.py; every headline card shows the
position-player group's pooled number for the same season underneath.
"""

import html
from datetime import timedelta

from shiny import render, req, ui

import ui_helpers
from database import get_session
from analytics import hitting_summary as hs

TAB = "Hitting"


def _e(s):
    return html.escape(str(s))


def fmt(v, kind):
    if v is None:
        return "—"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0.") else s
    if kind == "rate":
        return f"{v:.2f}"
    return str(v)


def _tile(label, v, kind, team=None, higher=True, sub=None):
    delta, pos = sub, None
    if team is not None:
        delta = f"team {fmt(team, kind)}" + (f" · {sub}" if sub else "")
        if v is not None and v != team:
            pos = (v > team) == higher
    return ui_helpers.kpi_tile(label, fmt(v, kind), delta=delta, delta_positive=pos)


def _row(*tiles):
    return ui.div(*tiles, class_="gbo-kpi-row", style="margin-bottom:6px;")


def _note(text):
    return ui.p(text, class_="text-muted small", style="margin:4px 0 0;")


def trend_svg(rows, key, roll_key, lo, hi, team=None, kind="pct", label=""):
    """Per-game points (muted) + rolling line (crimson) + team dashed line."""
    if len(rows) < 2:
        return ""
    W, H, L, R, T, B = 520, 170, 40, 10, 14, 26
    n = len(rows)
    x = lambda i: L + (W - L - R) * i / (n - 1)  # noqa: E731
    y = lambda v: T + (H - T - B) * (1 - (min(max(v, lo), hi) - lo) / (hi - lo))  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:560px" xmlns="http://www.w3.org/2000/svg">',
           f'<text x="{L}" y="10" font-size="10" font-weight="700" style="fill:var(--gbo-text-muted,#8A8A8E)">{_e(label)}</text>']
    for t in (lo, (lo + hi) / 2, hi):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}" style="stroke:var(--gbo-border,#333)" stroke-width="1"/>'
                   f'<text x="{L - 4}" y="{y(t) + 3:.1f}" font-size="9" text-anchor="end" style="fill:var(--gbo-text-muted,#8A8A8E)">'
                   f'{_e(fmt(t, kind))}</text>')
    if team is not None:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(team):.1f}" y2="{y(team):.1f}" stroke="#E9C46A" stroke-dasharray="4 3" stroke-width="1.5">'
                   f'<title>Position players: {_e(fmt(team, kind))}</title></line>')
    pts = [(i, r[roll_key]) for i, r in enumerate(rows) if r[roll_key] is not None]
    if len(pts) >= 2:
        d = " ".join(f"{'M' if j == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for j, (i, v) in enumerate(pts))
        out.append(f'<path d="{d}" fill="none" style="stroke:var(--gbo-crimson,#BF1E2D)" stroke-width="2.5"/>')
    for i, r in enumerate(rows):
        if r[key] is None:
            continue
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(r[key]):.1f}" r="3.5" style="fill:var(--gbo-text-muted,#8A8A8E)" opacity=".7">'
                   f'<title>{r["date"]:%b %d}: {_e(fmt(r[key], kind))} ({r["PA"]} PA) · last {hs.ROLL} games '
                   f'{_e(fmt(r[roll_key], kind))}</title></circle>')
    first, last = rows[0]["date"], rows[-1]["date"]
    out.append(f'<text x="{L}" y="{H - 8}" font-size="9" style="fill:var(--gbo-text-muted,#8A8A8E)">{first:%b %d}</text>'
               f'<text x="{W - R}" y="{H - 8}" font-size="9" text-anchor="end" style="fill:var(--gbo-text-muted,#8A8A8E)">{last:%b %d}</text>')
    out.append("</svg>")
    return "".join(out)


def render_tab(player, season_label, mine, team, trend):
    if mine is None:
        return ui_helpers.card(ui_helpers.empty_state(f"No charted plate appearances for {season_label} yet."))
    from game_stats import ops_plus
    ln, d, b, x = mine["line"], mine["disc"], mine["batted"], mine["extra"]

    def tv(src, key):
        return hs.value(team, src, key) if team else None

    head = _row(*[_tile(lbl, hs.value(mine, src, key), kind, tv(src, key), hib) for lbl, src, key, hib, kind in hs.HEADLINE])
    top = ui_helpers.card(head, _note(f"{ln['PA']} plate appearances. Under each number: all position players pooled, "
                                      "same season. Hard-Hit % is the charter's contact call (barreled or solid), "
                                      "not exit velocity."),
                          title="Hitting", right=season_label)

    opsp = ops_plus(ln["OBP"], ln["SLG"])
    results = ui_helpers.card(
        _row(*[ui_helpers.kpi_tile(k, ln[k]) for k in ("PA", "AB", "H", "2B", "3B", "HR", "RBI")]
             + [ui_helpers.kpi_tile(k, ln.get(k) if ln.get(k) is not None else "—") for k in ("R", "SB")]),
        _row(_tile("AVG", ln["AVG"], "avg", tv("line", "AVG")), _tile("OBP", ln["OBP"], "avg", tv("line", "OBP")),
             _tile("SLG", ln["SLG"], "avg", tv("line", "SLG")), _tile("OPS", ln["OPS"], "avg", tv("line", "OPS")),
             ui_helpers.kpi_tile("OPS+", opsp if opsp is not None else "—", delta="100 = D2 average"),
             _tile("ISO", ln["ISO"], "avg", tv("line", "ISO")), _tile("BB/K", ln["BB/K"], "rate", tv("line", "BB/K"))),
        title="Results")

    approach = ui_helpers.card(
        _row(_tile("Pitches / PA", x["Pitches / PA"], "rate", tv("extra", "Pitches / PA")),
             _tile("1st-pitch swing %", d["First-Pitch Swing %"], "pct", tv("disc", "First-Pitch Swing %"), higher=True),
             _tile("Zone swing %", d["Zone Swing %"], "pct", tv("disc", "Zone Swing %")),
             _tile("Chase %", d["Chase %"], "pct", tv("disc", "Chase %"), higher=False),
             _tile("Whiff %", d["Whiff %"], "pct", tv("disc", "Whiff %"), higher=False)),
        _note("Zone swing high and chase low is the goal: swinging at strikes, taking balls. "
              "First-pitch swing has no right answer -- green just means more aggressive than the group."),
        title="Approach")

    spray_keys = ["Pull %", "Center %", "Oppo %"] if "Pull %" in b else ["Left Field %", "Center %", "Right Field %"]
    contact = ui_helpers.card(
        _row(_tile("Barrel %", b["Barrel %"], "pct", tv("batted", "Barrel %")),
             _tile("Hard-hit %", b["Hard Contact %"], "pct", tv("batted", "Hard Contact %")),
             _tile("Line drive %", b["Line Drive %"], "pct", tv("batted", "Line Drive %")),
             _tile("Ground ball %", b["Ground Ball %"], "pct", tv("batted", "Ground Ball %"), higher=False),
             _tile("Fly ball %", b["Fly Ball %"], "pct", tv("batted", "Fly Ball %")),
             _tile("Pop-up %", b["Pop Up %"], "pct", tv("batted", "Pop Up %"), higher=False)),
        _row(*[ui_helpers.kpi_tile(k.replace(" %", ""), fmt(b.get(k), "pct")) for k in spray_keys]) if b["Located"] else None,
        _note(f"{b['Balls in Play']} balls in play ({b['Located']} with a spray location)."
              + (" Switch hitter or no batting side on file, so spray is left / center / right field." if "Pull %" not in b else "")),
        title="Quality of contact")

    sit = ui_helpers.card(
        _row(_tile("2-strike AVG", ln["2-Strike AVG"], "avg", tv("line", "2-Strike AVG"), sub=f"{ln['2-Strike PA']} PA"),
             _tile("RISP AVG", ln["RISP AVG"], "avg", tv("line", "RISP AVG"), sub=f"{ln['RISP PA']} PA"),
             _tile("Leadoff OBP", x["Leadoff OBP"], "avg", tv("extra", "Leadoff OBP"), sub=f"{x['Leadoff PA']} PA"),
             _tile("Productive out %", x["Productive Out %"], "pct", tv("extra", "Productive Out %"),
                   sub=f"{x['Productive Outs']} of {x['Productive Out Opps']}")),
        _row(*[_tile(f"{s} OPS", x[f"{s} OPS"], "avg", tv("extra", f"{s} OPS"), sub=f"{ln[f'{s} PA']} PA")
               for s in ("Ahead", "Even", "Behind")]),
        _note("Ahead / even / behind use the count when the at-bat ended. Productive out % = of his outs made with a "
              "runner on base, how many moved a runner up or scored one (sac bunts and sac flies count; strikeouts "
              "and double plays don't). Small samples swing hard -- check the PA count."),
        title="Situations")

    if len(trend) >= 2:
        tq = tv("line", "QAB %")
        to = tv("line", "OPS")
        hi_ops = max(1.2, max((r["OPS"] or 0) for r in trend))
        charts = ui.div(
            ui.HTML(trend_svg(trend, "QAB %", "roll_qab", 0, 100, tq, "pct", "QAB % BY GAME")),
            ui.HTML(trend_svg(trend, "OPS", "roll_ops", 0, round(hi_ops + 0.05, 1), to, "avg", "OPS BY GAME")),
            style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;")
        tr = ui_helpers.card(charts, _note(f"Dots = each game. Red line = his last {hs.ROLL} games pooled together. "
                                           "Gold dashed line = position players this season."),
                             title="Trend: heating up or cooling off", right=f"{len(trend)} games")
    else:
        tr = ui_helpers.card(ui_helpers.empty_state("The game-by-game trend starts after his second charted game."),
                             title="Trend: heating up or cooling off")
    return ui.div(top, results, approach, contact, sit, tr)


def register(input, output, session, app_state, profile_pid, season_label_fn):
    """Call from player_profile_server. profile_pid(db) -> shown player id;
    season_label_fn() -> the page's selected season label."""
    from bucket_system import season_date_range
    from models import Player

    def _open():
        return "profile_tabs" in input and input.profile_tabs() == TAB

    @render.ui
    def hitting_tab():
        if not app_state.is_authenticated():
            return None
        req(_open())
        label = season_label_fn()
        start, end = season_date_range(label)
        db = get_session()
        try:
            pid = profile_pid(db)
            player = db.query(Player).filter(Player.player_id == pid).first() if pid else None
            if player is None:
                return ui_helpers.card(ui_helpers.empty_state("No player selected."))
            mine, team, trend, _p = hs.load(db, player, date_from=start, date_to=(end - timedelta(days=1)) if end else None)
            return render_tab(player, label, mine, team, trend)
        finally:
            db.close()
