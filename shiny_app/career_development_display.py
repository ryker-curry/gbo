"""
GBO -- Player Profile "Career Development" tab (Nov 2026, Ryker): how a
pitcher's Rapsodo metrics and game numbers changed season to season at Pitt
State. Data and math: career_development.py (root).

Who sees what: staff see every pitcher; a player sees only his own profile
(player_profile's profile_pid already resolves that). The spring 2026
staff comparison is staff only.

Charts are plain SVG strings (like release_graphics.py) -- no kaleido, no
plotly.js -- with <title> hover text on every mark.
"""

from html import escape

from shiny import ui, render, reactive, req

from database import get_session
import career_development as cd
import ui_helpers
from pitch_type_config import get_pitch_color

TAB = "Career Development"
TO_COLOR = "var(--gbo-crimson)"
FROM_COLOR = "var(--gbo-gold)"
MUTED = "var(--gbo-text-muted)"
GRID = "var(--gbo-border)"
TEXT = "var(--gbo-text)"
_VERDICT_STYLE = {
    "Better": "color:var(--gbo-status-good);border-color:var(--gbo-status-good);",
    "Worse": "color:var(--gbo-status-flag);border-color:var(--gbo-status-flag);",
    "Higher": "color:var(--gbo-status-watch);border-color:var(--gbo-status-watch);",
    "Lower": "color:var(--gbo-status-watch);border-color:var(--gbo-status-watch);",
    "Above staff": "color:var(--gbo-status-good);border-color:var(--gbo-status-good);",
    "Below staff": "color:var(--gbo-status-flag);border-color:var(--gbo-status-flag);",
}


def _chip(text):
    return ui.span(text, style="display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;"
                               "border:1px solid var(--gbo-border);color:var(--gbo-text-muted);" + _VERDICT_STYLE.get(text, ""))


def _fmt(v, dp, sign=False):
    if v is None:
        return "—"
    s = f"{v:+.{dp}f}" if sign else f"{v:.{dp}f}"
    return s.replace("-", "−")


def _table(headers, rows, num_from=1):
    head = ui.tags.tr(*[ui.tags.th(h, style="text-align:right;" if i >= num_from else "") for i, h in enumerate(headers)])
    body = [ui.tags.tr(*[ui.tags.td(c, style="text-align:right;" if i >= num_from and not hasattr(c, "tagify") else "")
                         for i, c in enumerate(r)]) for r in rows]
    return ui.div(ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                         class_="table-responsive"), class_="gbo-statline")


def _note(text):
    return ui.p(text, class_="text-muted small")


# ---------------------------------------------------------------- SVG
def _ticks(lo, hi, n=5):
    import math
    span = hi - lo or 1
    step = 10 ** math.floor(math.log10(span / n))
    for m in (1, 2, 2.5, 5, 10):
        if span / (step * m) <= n:
            step *= m
            break
    t = math.ceil(lo / step) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 6))
        t += step
    return out


def _axes(x, y, xs, ys, x0, x1, y0, y1, xlabel, ylabel, w, h):
    parts = []
    for v in ys:
        parts.append(f'<line x1="{x0}" x2="{x1}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}" stroke-width="1"/>'
                     f'<text x="{x0 - 6}" y="{y(v) + 4:.1f}" text-anchor="end" font-size="11" fill="{MUTED}">{v:g}</text>')
    for v in xs:
        parts.append(f'<line x1="{x(v):.1f}" x2="{x(v):.1f}" y1="{y0}" y2="{y1}" stroke="{GRID}" stroke-width="1"/>'
                     f'<text x="{x(v):.1f}" y="{y0 + 16}" text-anchor="middle" font-size="11" fill="{MUTED}">{v:g}</text>')
    parts.append(f'<text x="{x1}" y="{h - 4}" text-anchor="end" font-size="11" fill="{MUTED}">{escape(xlabel)}</text>')
    parts.append(f'<text x="{x0 + 4}" y="{y1 + 12}" font-size="11" fill="{MUTED}">{escape(ylabel)}</text>')
    return "".join(parts)


def release_svg(rows, s_from, s_to, shoulder):
    """Behind-the-pitcher release plot, equal feet scale on both axes, lefties
    mirrored. Lines from the estimated shoulder to each season's average
    release; the line's angle is the estimated arm angle."""
    pts = [r for r in rows if r["season"] in (s_from, s_to) and r["rel_height"] is not None and r["rel_side"] is not None]
    if not pts:
        return None
    w, h, ml, mr, mt, mb = 520, 340, 44, 16, 14, 36
    xmax = max(4.0, max(r["rel_side"] for r in pts)) + 0.3
    ymin = min(shoulder - 0.4, min(r["rel_height"] for r in pts)) - 0.2
    ymax = max(7.0, max(r["rel_height"] for r in pts)) + 0.2
    ft = max(xmax / (w - ml - mr), (ymax - ymin) / (h - mt - mb))
    x = lambda v: ml + v / ft
    y = lambda v: mt + (ymax - v) / ft
    y0 = y(ymin)
    out = [_axes(x, y, _ticks(0, xmax), _ticks(ymin, ymax), ml, x(xmax), y0, mt,
                 "Release side, arm side (ft)", "Release height (ft)", w, h)]
    for r in pts:
        later = r["season"] == s_to
        c = TO_COLOR if later else FROM_COLOR
        out.append(f'<circle cx="{x(r["rel_side"]):.1f}" cy="{y(r["rel_height"]):.1f}" r="3.5" stroke="{c}" '
                   f'fill="{c if later else "none"}" fill-opacity="0.5" stroke-opacity="0.8"><title>{r["date"]} · {r["season"]}\n'
                   f'Height {r["rel_height"]:.2f} ft, side {r["rel_side"]:.2f} ft\nArm angle {r["arm_angle"]:.1f}° (est.)</title></circle>')
    out.append(f'<circle cx="{x(0):.1f}" cy="{y(shoulder):.1f}" r="5" fill="{MUTED}"/>'
               f'<text x="{x(0) + 8:.1f}" y="{y(shoulder) + 16:.1f}" font-size="11" fill="{MUTED}">Shoulder (est.)</text>')
    import math
    for i, s in enumerate(dict.fromkeys([s_from, s_to])):
        sr = [r for r in pts if r["season"] == s]
        if not sr:
            continue
        cx = sum(r["rel_side"] for r in sr) / len(sr)
        cy = sum(r["rel_height"] for r in sr) / len(sr)
        ang = math.degrees(math.atan2(cy - shoulder, cx))
        c = TO_COLOR if s == s_to else FROM_COLOR
        dash = "" if s == s_to else ' stroke-dasharray="6 4"'
        dy = -10 if (s == s_to or s_from == s_to) else 18
        out.append(f'<line x1="{x(0):.1f}" y1="{y(shoulder):.1f}" x2="{x(cx):.1f}" y2="{y(cy):.1f}" stroke="{c}" '
                   f'stroke-width="3" stroke-linecap="round"{dash}/>'
                   f'<circle cx="{x(cx):.1f}" cy="{y(cy):.1f}" r="6" fill="{c if s == s_to else "var(--gbo-bg-card)"}" stroke="{c}" stroke-width="2"/>'
                   f'<text x="{x(cx) - 10:.1f}" y="{y(cy) + dy:.1f}" text-anchor="end" font-size="12" font-weight="600" fill="{TEXT}">{s}: {ang:.0f}°</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Release point by season">{"".join(out)}</svg>'


def movement_svg(rows, s_from, s_to):
    pts = [r for r in rows if r["season"] in (s_from, s_to) and r["ivb"] is not None and r["hb"] is not None]
    if not pts:
        return None
    w, h, ml, mr, mt, mb = 520, 340, 40, 12, 14, 36
    lo_x, hi_x = min(-5, min(r["hb"] for r in pts) - 2), max(5, max(r["hb"] for r in pts) + 2)
    lo_y, hi_y = min(-5, min(r["ivb"] for r in pts) - 2), max(5, max(r["ivb"] for r in pts) + 2)
    x = lambda v: ml + (v - lo_x) / (hi_x - lo_x) * (w - ml - mr)
    y = lambda v: h - mb - (v - lo_y) / (hi_y - lo_y) * (h - mt - mb)
    out = [_axes(x, y, _ticks(lo_x, hi_x, 6), _ticks(lo_y, hi_y, 6), ml, w - mr, h - mb, mt,
                 "Horizontal break, arm side (in)", "Induced vertical break (in)", w, h),
           f'<line x1="{x(0):.1f}" x2="{x(0):.1f}" y1="{mt}" y2="{h - mb}" stroke="{MUTED}" stroke-opacity="0.6"/>'
           f'<line x1="{ml}" x2="{w - mr}" y1="{y(0):.1f}" y2="{y(0):.1f}" stroke="{MUTED}" stroke-opacity="0.6"/>']
    for r in pts:
        later = r["season"] == s_to
        c = get_pitch_color(r["pitch"])
        out.append(f'<circle cx="{x(r["hb"]):.1f}" cy="{y(r["ivb"]):.1f}" r="3.2" stroke="{c}" fill="{c if later else "none"}" '
                   f'fill-opacity="0.5" stroke-opacity="{0.9 if later else 0.5}"><title>{r["date"]} · {escape(r["pitch"])}\n'
                   f'HB {r["hb"]:.1f} in, IVB {r["ivb"]:.1f} in\n{r["velo"]:.1f} mph</title></circle>')
    if s_from != s_to:
        for t in sorted({r["pitch"] for r in pts}):
            a = [r for r in pts if r["pitch"] == t and r["season"] == s_from]
            b = [r for r in pts if r["pitch"] == t and r["season"] == s_to]
            if a and b:
                c = get_pitch_color(t)
                ax, ay = sum(r["hb"] for r in a) / len(a), sum(r["ivb"] for r in a) / len(a)
                bx, by = sum(r["hb"] for r in b) / len(b), sum(r["ivb"] for r in b) / len(b)
                mid = "".join(ch for ch in t if ch.isalnum())
                out.append(f'<defs><marker id="cd-arr-{mid}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto">'
                           f'<path d="M0,0L10,5L0,10z" fill="{c}"/></marker></defs>'
                           f'<line x1="{x(ax):.1f}" y1="{y(ay):.1f}" x2="{x(bx):.1f}" y2="{y(by):.1f}" stroke="{c}" stroke-width="2.5" '
                           f'stroke-linecap="round" marker-end="url(#cd-arr-{mid})"/>')
    legend = "".join(f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;">'
                     f'<span style="width:10px;height:10px;border-radius:50%;background:{get_pitch_color(t)};display:inline-block;"></span>{escape(t)}</span>'
                     for t in sorted({r["pitch"] for r in pts}))
    return (f'<div class="text-muted small" style="margin-bottom:4px;">{legend}</div>'
            f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Pitch movement by season">{"".join(out)}</svg>')


def mini_svg(points, s_from, s_to, dp, unit):
    """One metric across seasons: mean dot, +/- 1 SD bar, compared seasons
    highlighted. points = [(season, n, value, sd)]."""
    w, h, ml, mr, mt, mb = 260, 150, 44, 10, 14, 24
    lo = min(v - (sd or 0) for _s, _n, v, sd in points)
    hi = max(v + (sd or 0) for _s, _n, v, sd in points)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    k = len(points)
    x = lambda i: ml + (i + 0.5) * (w - ml - mr) / k
    y = lambda v: h - mb - (v - lo) / (hi - lo) * (h - mt - mb)
    out = []
    for t in _ticks(lo, hi, 4):
        out.append(f'<line x1="{ml}" x2="{w - mr}" y1="{y(t):.1f}" y2="{y(t):.1f}" stroke="{GRID}"/>'
                   f'<text x="{ml - 6}" y="{y(t) + 4:.1f}" text-anchor="end" font-size="10" fill="{MUTED}">{t:g}</text>')
    if k > 1:
        d = " ".join(f'{"M" if i == 0 else "L"}{x(i):.1f},{y(v):.1f}' for i, (_s, _n, v, _sd) in enumerate(points))
        out.append(f'<path d="{d}" fill="none" stroke="{MUTED}" stroke-width="1.5"/>')
    for i, (s, n, v, sd) in enumerate(points):
        c = TO_COLOR if s == s_to else FROM_COLOR if s == s_from else MUTED
        if sd is not None:
            out.append(f'<line x1="{x(i):.1f}" x2="{x(i):.1f}" y1="{y(v - sd):.1f}" y2="{y(v + sd):.1f}" stroke="{c}" stroke-width="2" opacity="0.6"/>')
        tip = f"{s}: {v:.{dp}f} {unit}" + (f" ± {sd:.{dp}f}" if sd is not None else "") + f" ({n} pitches)"
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{5 if s in (s_from, s_to) else 3.5}" fill="{c}"><title>{escape(tip)}</title></circle>'
                   f'<text x="{x(i):.1f}" y="{h - 6}" text-anchor="middle" font-size="10" fill="{MUTED}">{s[2:]}</text>')
    return f'<svg viewBox="0 0 {w} {h}" width="100%">{"".join(out)}</svg>'


# ---------------------------------------------------------------- server
def register(input, output, session, app_state, profile_pid):
    """Call from player_profile_server. profile_pid(db) -> shown player id."""

    def _staff():
        return app_state.is_authenticated() and app_state.role_name() != "Player"

    def _open():
        return "profile_tabs" in input and input.profile_tabs() == TAB

    @reactive.calc
    def _data():
        db = get_session()
        try:
            pid = profile_pid(db)
            if pid is None:
                return None
            d = cd.load_pitches(db, pid)
            d["pid"] = pid
            d["games"] = cd.game_terms(db, pid, d["rows"])
            d["staff"] = cd.staff_compare(db, pid) if _staff() else (None, 0, [])
            return d
        finally:
            db.close()

    @render.ui
    def career_dev_tab():
        if not app_state.is_authenticated():
            return None
        req(_open())
        d = _data()
        if d is None:
            return ui_helpers.card(ui_helpers.empty_state("No player selected."))
        rows = d["rows"]
        intro = _note("How this pitcher's Rapsodo numbers and game results changed season to season. "
                      "Seasons run August to July. A change counts only when it's at least half a standard "
                      "deviation of his pitch-to-pitch spread and both seasons have 8 or more pitches.")
        if not rows:
            return ui.div(ui_helpers.card(intro, ui_helpers.empty_state("No Rapsodo pitches on file yet."), title=TAB),
                          ui.output_ui("cd_games"))
        pitch, s_from, s_to = cd.default_view(rows)
        ss = cd.seasons(rows)
        controls = ui.div(
            ui.input_select("cd_pitch", "Pitch", choices=dict(cd.pitch_options(rows)), selected=pitch),
            ui.input_select("cd_mode", "Sessions", choices=cd.MODES, selected="standard"),
            ui.input_select("cd_from", "Compare season", choices=ss, selected=s_from),
            ui.input_select("cd_to", "to", choices=ss, selected=s_to),
            style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;",
        )
        return ui.div(ui_helpers.card(intro, controls, title=TAB), ui.output_ui("cd_body"), ui.output_ui("cd_games"))

    def _sel():
        d = _data()
        req(d is not None and d["rows"])
        req("cd_pitch" in input and "cd_from" in input and "cd_to" in input and "cd_mode" in input)
        return d, input.cd_pitch(), input.cd_mode(), input.cd_from(), input.cd_to()

    @render.ui
    def cd_body():
        req(_open())
        d, pitch, mode, s_from, s_to = _sel()
        rows = [r for r in d["rows"] if cd.keep_mode(mode)(r)]
        prow = [r for r in rows if cd.pitch_match(pitch)(r)]
        summ = cd.season_summary(d["rows"], pitch, mode)
        cmp = cd.compare(summ, s_from, s_to)
        cnt = cd.verdict_counts(cmp)

        if s_from == s_to or not cmp:
            take = _note("Pick two different seasons to compare. With only one season of Rapsodo data so far, "
                         "the charts below show that season.")
            cmp_card = None
        else:
            take = ui.p(ui.strong(pitch), f", {s_from} to {s_to}: ", ui.strong(str(cnt["better"])), " better, ",
                        ui.strong(str(cnt["worse"])), " worse, ", ui.strong(str(cnt["changed"])),
                        " changed with no clear good or bad direction, ", ui.strong(str(cnt["same"])), " about the same.")
            table = _table(["Metric", s_from, s_to, "Change", "Pitches", "Verdict"],
                           [[r["label"], _fmt(r["v1"], r["dp"]), _fmt(r["v2"], r["dp"]),
                             _fmt(r["change"], r["dp"], sign=True), r["n"], _chip(r["verdict"])] for r in cmp])
            cmp_card = ui_helpers.card(
                _note("Velocity, extension and Rapsodo in-zone % have a better direction; release spreads are better "
                      "when smaller; the rest are marked higher or lower because the right direction depends on the pitch."),
                table, title="What changed")

        rel = release_svg(prow, s_from, s_to, d["shoulder_ft"])
        mov = movement_svg(rows, s_from, s_to)
        charts = ui.div(
            ui_helpers.card(_note("Behind the pitcher, drawn to scale in feet (lefties mirrored, arm side to the right). "
                                  "Lines run from an estimated shoulder to each season's average release; the angle is the "
                                  "estimated arm angle." + ("" if d["height_known"] else " No height on file, so 6'1\" is assumed.")),
                            ui.HTML(rel) if rel else ui_helpers.empty_state("No release data for these seasons."),
                            title="Release point and arm angle"),
            ui_helpers.card(_note("Every pitch type. Hollow = earlier season, filled = later; arrows run between season averages."),
                            ui.HTML(mov) if mov else ui_helpers.empty_state("No movement data for these seasons."),
                            title="Pitch movement"),
            style="display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(min(100%,22rem),1fr));",
        )

        seasons_sorted = sorted(summ)
        minis = []
        for mid, label, unit, dp, _dir, _spin, _kind in cd.METRICS:
            pts = [(s, *summ[s][mid]) for s in seasons_sorted if summ[s][mid][0] and summ[s][mid][1] is not None]
            if pts:
                minis.append(ui.div(ui.p(ui.strong(f"{label} ({unit})"), style="margin:0 0 4px;font-size:13px;"),
                                    ui.HTML(mini_svg(pts, s_from, s_to, dp, unit)),
                                    style="border:1px solid var(--gbo-border);border-radius:8px;padding:10px;min-width:0;"))
        multiples = ui_helpers.card(
            _note("Season average with a bar for one standard deviation either side. Compared seasons are highlighted."),
            ui.div(*minis, style="display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(min(100%,15rem),1fr));"),
            title="Season by season") if minis else None

        sess = cd.sessions(d["rows"])
        log = ui_helpers.card(
            ui.div(_table(["Date", "Season", "Type", "Pitches", "FB avg mph", "FB max mph", "FB avg spin"],
                          [[s["date"].strftime("%b %d, %Y"), s["season"], s["type"], s["pitches"],
                            _fmt(s["fb_velo"], 1), _fmt(s["fb_max"], 1), _fmt(s["fb_spin"], 0)] for s in sess], num_from=3),
                   style="max-height:420px;overflow:auto;"),
            title="Session log")
        return ui.div(ui_helpers.card(take), cmp_card, charts, multiples, log,
                      style="display:grid;gap:16px;margin-top:16px;")

    @render.ui
    def cd_games():
        req(_open())
        d = _data()
        if d is None:
            return None
        games = d["games"]
        parts = []
        if games:
            parts.append(ui_helpers.card(
                _note("Spring 2026 from the staff game-tracking workbook; fall terms from GBO intrasquad pitches that have a "
                      "Rapsodo reading. Whiff % is whiffs over swings; CSW % is called strikes plus whiffs over pitches; "
                      "runs saved per 100 pitches is higher when better."),
                _table(["Term", "Pitch", "Pitches", "Strike %", "Called %", "Whiff %", "CSW %", "Runs saved /100"],
                       [[g["term"], g["pitch"], g["pitches"], _fmt(g["strike_pct"], 1), _fmt(g["called_pct"], 1),
                         _fmt(g["whiff_pct"], 1), _fmt(g["csw_pct"], 1), _fmt(g["rs100"], 2, sign=True)] for g in games], num_from=2),
                title="Game numbers by pitch"))
        line, n_staff, srows = d["staff"]
        if _staff() and line is not None:
            ip = float(line.ip) if line.ip is not None else 0
            parts.append(ui_helpers.card(
                _note(f"Spring 2026 game numbers next to the median of the {n_staff} other staff pitchers with "
                      f"{cd.QUALIFIED_IP}+ innings. Percentile = share of them he did better than. "
                      f"He threw {ip:g} innings and {line.pitches or 0} pitches"
                      + (" -- under 10 innings one outing moves these a lot." if ip < cd.QUALIFIED_IP else ".")),
                _table(["Metric", "Pitcher", "Staff median", "Percentile", "Read"],
                       [[r["label"], _fmt(r["mine"], r["dp"]), _fmt(r["median"], r["dp"]),
                         "—" if r["pct"] is None else str(r["pct"]), _chip(r["read"])] for r in srows]),
                title="Spring 2026 against the staff", right="staff only"))
        if not parts:
            return None
        return ui.div(*parts, style="display:grid;gap:16px;margin-top:16px;")
