"""
GBO -- Hitting Leaderboard (Oct 2026, Ryker: "create a hitters
leaderboard just like pitching staff leaderboard"). Same layout as
pitching_leaderboard.py: pick columns, click a stat under the table to
sort best-to-worst (direction picked per stat), glossary, All /
Intrasquad / External games. Approved extras: a date range (season by
default) and an adjustable minimum PA (default 10) -- hitters under it
sort to the bottom, grayed out, so a 2-for-2 doesn't top the AVG list.
Coaches (Analytics) and players (My Development) both see it.
Data: analytics/hitting_leaderboard.py.
"""

from datetime import date

from shiny import module, ui, render, req, reactive

from database import get_session
from analytics import hitting_leaderboard
from analytics.weekly_report import season_start
import ui_helpers
import glossary_content

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
DEFAULT_MIN_PA = 10

# (key, label, higher_is_better, kind) -- kind: "avg" (.300), "pct" (45.2), "int", "num2", "plus"
STAT_META = [
    ("AVG", "AVG", True, "avg"), ("OBP", "OBP", True, "avg"), ("SLG", "SLG", True, "avg"),
    ("OPS", "OPS", True, "avg"), ("wOBA", "wOBA", True, "avg"), ("ISO", "ISO", True, "avg"),
    ("BABIP", "BABIP", True, "avg"),
    # "+" stats vs the 2026 D2 average -- 100 = D2 average, higher is always better
    ("OPS+", "OPS+", True, "int"), ("wOBA+", "wOBA+", True, "int"), ("AVG+", "AVG+", True, "int"),
    ("OBP+", "OBP+", True, "int"), ("SLG+", "SLG+", True, "int"), ("ISO+", "ISO+", True, "int"),
    ("K%+", "K%+", True, "int"), ("BB%+", "BB%+", True, "int"), ("BABIP+", "BABIP+", True, "int"),
    ("K %", "K%", False, "pct"), ("BB %", "BB%", True, "pct"), ("BB/K", "BB/K", True, "num2"),
    ("QAB %", "QAB%", True, "pct"),
    ("Swing Decision %", "Swing Dec%", True, "pct"), ("Chase %", "Chase%", False, "pct"),
    ("Zone Swing %", "Zone Swing%", True, "pct"), ("Whiff %", "Whiff%", False, "pct"),
    ("Hard contact %", "Hard Contact%", True, "pct"), ("Pitches/PA", "P/PA", True, "num2"),
    ("2-strike K %", "2-Strike K%", False, "pct"),
    # Oct 2026 (hitting article batch): run-valued decisions + BEAR-style summary
    ("Decision RV/100", "Decision RV/100", True, "num2"), ("Decision Score", "Decision Score", True, "int"),
    # Oct 2026 ("Gone Hunting"): % of right choices and how good it stays in slumps
    ("Decision Q %", "Decision Q%", True, "pct"), ("Decision Floor", "Decision Floor", True, "pct"),
    ("H", "H", True, "int"), ("2B", "2B", True, "int"), ("3B", "3B", True, "int"), ("HR", "HR", True, "int"),
    ("BB", "BB", True, "int"), ("K", "K", False, "int"),
]
STAT_LABELS = {k: lbl for k, lbl, *_r in STAT_META}
STAT_HIGHER_BETTER = {k: hib for k, _l, hib, _k in STAT_META}
STAT_KIND = {k: kind for k, _l, _h, kind in STAT_META}

DEFAULT_COLUMNS = ["AVG", "OBP", "SLG", "OPS", "OPS+", "wOBA", "K %", "BB %", "QAB %", "Chase %", "Hard contact %"]
DEFAULT_SORT = "OPS"


def fmt_stat(key, v):
    if v is None:
        return "—"
    kind = STAT_KIND.get(key, "pct")
    if kind == "avg":
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0.") else s
    if kind == "int":
        return str(int(round(v)))
    if kind == "num2":
        return f"{v:.2f}"
    return f"{v:.1f}"


def sort_rows(rows, key, min_pa):
    """Qualified hitters (PA >= min_pa) first, best to worst on `key`;
    missing values last; then the unqualified ones, same order."""
    hib = STAT_HIGHER_BETTER.get(key, True)

    def k(r):
        v = r.get(key)
        return (0 if (r.get("PA") or 0) >= min_pa else 1, 1 if v is None else 0,
                0 if v is None else (-v if hib else v))
    return sorted(rows, key=k)


@module.ui
def hitting_leaderboard_ui():
    return ui.div(
        ui.div(
            ui.h4("Hitting Leaderboard", class_="gbo-section-title", style="margin-bottom:0;"),
            ui_helpers.glossary_link("hlb_glossary", "Stats Glossary"),
            style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
        ),
        ui.p("Every hitter with a charted plate appearance in this window, one row each. Pick which stats show "
             "below, then click a stat under the table to sort best-to-worst by it. Hitters under the minimum PA "
             "sort to the bottom (grayed out).", class_="text-muted small"),
        ui.output_ui("hlb_filters"),
        ui.output_ui("hlb_columns_picker"),
        ui.output_ui("hlb_table"),
        ui.output_ui("hlb_sort_picker"),
        ui.output_ui("hlb_lineup"),
    )


@module.server
def hitting_leaderboard_server(input, output, session, app_state):

    def _ok():
        if not app_state.is_authenticated():
            return False
        role = app_state.role_name()
        return role == "Player" or role in STAFF_ROLES

    @render.ui
    def hlb_filters():
        if not _ok():
            return None
        return ui.layout_columns(
            ui.input_date("hlb_from", "From", value=season_start()),
            ui.input_date("hlb_to", "To", value=date.today()),
            ui.input_select("hlb_game_scope", "Games",
                            choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            ui.input_numeric("hlb_min_pa", "Min PA", value=DEFAULT_MIN_PA, min=0, step=1),
            col_widths=[3, 3, 3, 3],
        )

    @render.ui
    def hlb_columns_picker():
        if not _ok():
            return None
        return ui.div(ui.input_checkbox_group("hlb_columns", "Columns to show", choices=STAT_LABELS,
                                              selected=DEFAULT_COLUMNS, inline=True), class_="mt-2")

    def _visible_columns():
        if "hlb_columns" in input and input.hlb_columns():
            selected = set(input.hlb_columns())
            return [k for k, *_r in STAT_META if k in selected]
        return list(DEFAULT_COLUMNS)

    @render.ui
    def hlb_sort_picker():
        if not _ok():
            return None
        cols = _visible_columns()
        if not cols:
            return None
        choices = {k: STAT_LABELS[k] for k in cols}
        current = input.hlb_sort_by() if "hlb_sort_by" in input else None
        selected = current if current in choices else (DEFAULT_SORT if DEFAULT_SORT in choices else cols[0])
        return ui.div(ui.input_radio_buttons("hlb_sort_by", "Sort by (best to worst)", choices=choices,
                                             selected=selected, inline=True), class_="mt-2")

    @reactive.calc
    def _rows():
        req(_ok() and "hlb_game_scope" in input and "hlb_from" in input and "hlb_to" in input)
        db = get_session()
        try:
            return hitting_leaderboard.rows(db, input.hlb_from(), input.hlb_to(), input.hlb_game_scope())
        finally:
            db.close()

    @render.ui
    def hlb_table():
        if not _ok():
            return None
        rows = _rows()
        if not rows:
            return ui_helpers.empty_state("No charted at-bats in this window yet.")
        cols = _visible_columns()
        sort_key = input.hlb_sort_by() if ("hlb_sort_by" in input and input.hlb_sort_by() in STAT_LABELS) else DEFAULT_SORT
        min_pa = input.hlb_min_pa() if "hlb_min_pa" in input and input.hlb_min_pa() is not None else DEFAULT_MIN_PA
        rows_sorted = sort_rows(rows, sort_key, min_pa)
        head = ui.tags.tr(ui.tags.th("#"), ui.tags.th("Hitter"), ui.tags.th("PA"),
                          *[ui.tags.th(STAT_LABELS[k], style="font-weight:800;" if k == sort_key else None) for k in cols])
        body, rank = [], 0
        for r in rows_sorted:
            qualified = (r.get("PA") or 0) >= min_pa
            if qualified:
                rank += 1
            body.append(ui.tags.tr(
                ui.tags.td(str(rank) if qualified else ""), ui.tags.td(ui.tags.b(r["Hitter"])), ui.tags.td(str(r["PA"])),
                *[ui.tags.td(fmt_stat(k, r.get(k)), style="font-weight:700;" if k == sort_key else None) for k in cols],
                style=None if qualified else "opacity:.45;",
            ))
        n_q = sum(1 for r in rows if (r.get("PA") or 0) >= min_pa)
        return ui.div(
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                   class_="table-responsive"),
            ui.p(f"Sorted by {STAT_LABELS[sort_key]}, best to worst. {n_q} of {len(rows)} hitters have {min_pa}+ PA.",
                 class_="text-muted small mt-1"),
        )

    @render.ui
    def hlb_lineup():
        """Lineup consistency (Oct 2026, from "Gone Hunting"): decision quality vs floor, staff only."""
        if not _ok() or app_state.role_name() not in STAFF_ROLES:
            return None
        from analytics import decision_floor
        rows = _rows()
        min_pa = input.hlb_min_pa() if "hlb_min_pa" in input and input.hlb_min_pa() is not None else DEFAULT_MIN_PA
        pts = [r for r in rows if (r.get("PA") or 0) >= min_pa and r.get("Decision Floor") is not None]
        head = ui.p(ui.strong("Lineup consistency: decision quality vs. floor"), "  ",
                    ui_helpers.how_to_link("decision_floor"), style="margin:18px 0 0;")
        if len(pts) < 3:
            return ui.div(head, ui.p(f"Needs 3+ hitters with {decision_floor.WINDOW}+ graded plate appearances "
                                     f"(and {min_pa}+ PA).", class_="text-muted small"))
        floors = sorted(r["Decision Floor"] for r in pts)
        qs = sorted(r["Decision Q %"] for r in pts)
        mf, mq = decision_floor._pctl(floors, 0.5), decision_floor._pctl(qs, 0.5)
        spread = decision_floor._pctl(floors, 0.75) - decision_floor._pctl(floors, 0.25)
        low = [r for r in pts if r["Decision Floor"] < mf - max(spread, 3.0)]
        line = (f"Middle half of the lineup's floors sit within {spread:.0f} points (median floor {mf:.0f}%). "
                + (f"Dragging it down: {', '.join(r['Hitter'] for r in sorted(low, key=lambda r: r['Decision Floor']))}."
                   if low else "Nobody is far below the pack -- a tight lineup."))
        return ui.div(
            head,
            ui.p("The Dodgers' lineup won back-to-back titles with floors packed tightly together: nobody's approach "
                 "fell apart in a slump. Each dot is a hitter: across = % of right swing/take choices, up = how good "
                 "that stays in his worst 10-PA stretches. Up and right is best; far below the floor line = his approach "
                 "slips when he struggles.", class_="text-muted small"),
            ui.p(ui.strong(line), class_="small"),
            ui.HTML(_lineup_svg(pts, mq, mf)),
        )

    @reactive.effect
    @reactive.event(input.hlb_glossary)
    def _show_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Hitting Stats Glossary", glossary_content.HITTING_LEADERBOARD))


def _lineup_svg(pts, mq, mf):
    from html import escape
    W, H, L, R, T, B = 640, 320, 50, 20, 16, 44
    xs = [r["Decision Q %"] for r in pts]
    ys = [r["Decision Floor"] for r in pts]
    x0, x1 = min(xs) - 3, max(xs) + 3
    y0, y1 = min(ys) - 3, max(ys) + 3

    def X(v):
        return L + (W - L - R) * (v - x0) / ((x1 - x0) or 1)

    def Y(v):
        return T + (H - T - B) * (1 - (v - y0) / ((y1 - y0) or 1))
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Lineup consistency">']
    for k in range(4):
        yv, xv = y0 + (y1 - y0) * k / 3, x0 + (x1 - x0) * k / 3
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end" class="axis">{yv:.0f}%</text>'
                   f'<text x="{X(xv):.1f}" y="{H - 24}" text-anchor="middle" class="axis">{xv:.0f}%</text>')
    out.append(f'<line x1="{X(mq):.1f}" x2="{X(mq):.1f}" y1="{T}" y2="{H - B}" class="avg"/>'
               f'<line x1="{L}" x2="{W - R}" y1="{Y(mf):.1f}" y2="{Y(mf):.1f}" class="avg"/>')
    for r in pts:
        x, y = X(r["Decision Q %"]), Y(r["Decision Floor"])
        last = r["Hitter"].split()[-1]
        out.append(f'<g class="pt"><title>{escape(r["Hitter"])}: {r["Decision Q %"]:.0f}% right, floor '
                   f'{r["Decision Floor"]:.0f}%</title><circle cx="{x:.1f}" cy="{y:.1f}" r="10" class="hit"/>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="dot"/>'
                   f'<text x="{x + 7:.1f}" y="{y - 6:.1f}" class="axis">{escape(last)}</text></g>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 6}" text-anchor="middle" class="axis">decision quality '
               '(% of right swing/take choices)</text>')
    out.append(f'<text x="12" y="{(T + H - B) / 2:.0f}" text-anchor="middle" class="axis" '
               f'transform="rotate(-90 12 {(T + H - B) / 2:.0f})">floor (worst 10-PA stretches)</text>')
    out.append("</svg>")
    return "".join(out)
