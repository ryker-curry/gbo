"""
GBO -- Player Profile "VALD Testing" tab (Nov 2026, Ryker: put every VALD
test on the website -- "don't use it for assessment").

Raw VALD numbers only. Nothing here is scored, ranked against the team or
colored good/bad, and none of it feeds Assessments, percentiles or the
Bucket System. Tiles show the latest test with a neutral change vs the
previous one; a table under each test shows every date.

Who sees it: staff see every player; a player sees only his own (the tab
follows Player Profile's own profile_pid resolution).

Data: vald_tests (services/vald_import.py). ForceFrame sides are shown as
throwing / non-throwing arm (shoulder) and drive / plant leg (hip), from
Player.throws -- the research convention (Nov 2026). With no throwing hand
on file it falls back to L / R.
"""

from shiny import ui, render, req

from database import get_session
from models import Player, ValdTest
import ui_helpers

DASH = "—"

# ForceDecks IMTP: (VALD column, label, unit, decimals)
IMTP_METRICS = [
    ("Peak Vertical Force [N]", "Peak force", "N", 0),
    ("Peak Vertical Force / BM [N/kg]", "Relative peak force", "N/kg", 2),
    ("Net Peak Vertical Force [N]", "Net peak force", "N", 0),
    ("RFD - 100ms [N/s]", "RFD 0-100 ms", "N/s", 0),
    ("RFD - 200ms [N/s]", "RFD 0-200 ms", "N/s", 0),
    ("Net Force at 100ms [N]", "Net force at 100 ms", "N", 0),
    ("Impulse (Net of BW) - 200ms [N s]", "Net impulse 0-200 ms", "N s", 1),
]
IMTP_TILES = ["Peak Vertical Force [N]", "Peak Vertical Force / BM [N/kg]", "RFD - 100ms [N/s]", "RFD - 200ms [N/s]"]


def _fmt(v, dec=0):
    if v is None:
        return DASH
    try:
        return f"{float(v):,.{dec}f}"
    except (TypeError, ValueError):
        return str(v)


def _delta(cur, prev, unit, dec, prev_date):
    if cur is None or prev is None:
        return None
    d = float(cur) - float(prev)
    return f"{'+' if d >= 0 else ''}{d:,.{dec}f} {unit} vs {prev_date:%b %d, %Y}"


def _table(columns, rows):
    head = ui.tags.tr(*[ui.tags.th(c) for c in columns])
    body = [ui.tags.tr(*[ui.tags.td(v, class_="gbo-statline-na") if v == DASH else ui.tags.td(v) for v in r]) for r in rows]
    return ui.div(ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                         class_="table-responsive"), class_="gbo-statline")


def _side_names(test_type, throws):
    """-> {"L": label, "R": label} and the order to show them in."""
    throws = (throws or "").upper()[:1]
    hip = (test_type or "").lower().startswith("hip")
    if throws not in ("L", "R"):
        return {"L": "Left", "R": "Right"}, ["L", "R"]
    other = "L" if throws == "R" else "R"
    if hip:
        names = {throws: f"Drive leg ({throws})", other: f"Plant leg ({other})"}
    else:
        names = {throws: f"Throwing arm ({throws})", other: f"Non-throwing arm ({other})"}
    return names, [throws, other]


def _asym_text(asym, is_pitcher, throws):
    if not asym:
        return DASH
    val, side = asym.get("value"), asym.get("side")
    txt = f"{val:g}%" + (f" {side}" if side else "")
    t = (throws or "").upper()[:1]
    if is_pitcher and side and t in ("L", "R"):
        txt += " (drive)" if side == t else " (plant)"
    return txt


# ---------------------------------------------------------------- ForceDecks

def _forcedecks_section(test_type, tests, player):
    tests = sorted(tests, key=lambda t: t.tested_at, reverse=True)
    latest, prev = tests[0], (tests[1] if len(tests) > 1 else None)
    vals = (latest.metrics or {}).get("values", {})
    pvals = ((prev.metrics or {}).get("values", {}) if prev else {})
    asym = (latest.metrics or {}).get("asym", {})
    asym_key = next(iter(asym), None)

    if test_type.upper() == "IMTP":
        spec = {k: (lab, unit, dec) for k, lab, unit, dec in IMTP_METRICS}
        tiles = []
        for k in IMTP_TILES:
            lab, unit, dec = spec[k]
            tiles.append(ui_helpers.kpi_tile(lab, _fmt(vals.get(k), dec), unit=unit,
                                             delta=_delta(vals.get(k), pvals.get(k), unit, dec, prev.test_date) if prev else None))
        if asym_key:
            tiles.append(ui_helpers.kpi_tile("Asymmetry (net peak force)", _asym_text(asym[asym_key], player.is_pitcher, player.throws)))
        metric_rows = IMTP_METRICS
    else:
        # Any other ForceDecks test: show what the export had, in its own order.
        keys = list(vals.keys())[:10]
        metric_rows = [(k, k, "", 2) for k in keys]
        tiles = [ui_helpers.kpi_tile(k, _fmt(vals.get(k), 2)) for k in keys[:4]]

    cols = ["Date", "Body weight"] + [f"{lab} ({unit})" if unit else lab for _, lab, unit, _ in metric_rows]
    if asym_key:
        cols.append("Asymmetry")
    rows = []
    for t in tests:
        v = (t.metrics or {}).get("values", {})
        a = (t.metrics or {}).get("asym", {})
        bw = f"{float(t.body_weight_kg):.1f} kg ({float(t.body_weight_kg) * 2.20462:.0f} lb)" if t.body_weight_kg else DASH
        r = [f"{t.tested_at:%b %d, %Y}", bw] + [_fmt(v.get(k), dec) for k, _, _, dec in metric_rows]
        if asym_key:
            r.append(_asym_text(a.get(asym_key), player.is_pitcher, player.throws))
        rows.append(r)
    return ui_helpers.card(
        ui.div(*tiles, class_="gbo-kpi-row", style="margin-bottom:12px;"),
        _table(cols, rows),
        title=f"ForceDecks · {test_type}",
        right=f"Latest {latest.tested_at:%b %d, %Y} · {len(tests)} test{'s' if len(tests) != 1 else ''}",
    )


# ---------------------------------------------------------------- ForceFrame

def _dir_force(t, direction, side):
    d = ((t.metrics or {}).get("directions", {}).get(direction) or {}).get(side)
    return (d or {}).get("max_force")


def _ratio(num, den):
    if num is None or den in (None, 0):
        return None
    return float(num) / float(den)


def _forceframe_section(test_type, position, tests, player):
    tests = sorted(tests, key=lambda t: t.tested_at, reverse=True)
    latest, prev = tests[0], (tests[1] if len(tests) > 1 else None)
    names, order = _side_names(test_type, player.throws)
    directions = []
    for t in tests:
        for d in (t.metrics or {}).get("directions", {}):
            if d not in directions:
                directions.append(d)
    # Shoulder: ER then IR (ER:IR is the ratio people read); hip: AB then AD.
    pref = {"ER": 0, "IR": 1, "AB": 0, "AD": 1}
    directions.sort(key=lambda d: pref.get(d, 9))
    ratio_pair = ("ER", "IR") if {"ER", "IR"} <= set(directions) else ("AB", "AD") if {"AB", "AD"} <= set(directions) else None

    # Tiles: first side (throwing arm / drive leg) for each direction + ratio.
    first = order[0]
    tiles = []
    for d in directions:
        cur = _dir_force(latest, d, first)
        pv = _dir_force(prev, d, first) if prev else None
        tiles.append(ui_helpers.kpi_tile(f"{d} · {names[first]}", _fmt(cur), unit="N",
                                         delta=_delta(cur, pv, "N", 0, prev.test_date) if prev else None))
    if ratio_pair:
        for s in order:
            r = _ratio(_dir_force(latest, ratio_pair[0], s), _dir_force(latest, ratio_pair[1], s))
            tiles.append(ui_helpers.kpi_tile(f"{ratio_pair[0]}:{ratio_pair[1]} · {names[s]}", _fmt(r, 2)))

    cols = ["Date"]
    for s in order:
        cols += [f"{d} {names[s]} (N)" for d in directions]
        if ratio_pair:
            cols.append(f"{ratio_pair[0]}:{ratio_pair[1]} {names[s]}")
    rows = []
    for t in tests:
        r = [f"{t.tested_at:%b %d, %Y}"]
        for s in order:
            r += [_fmt(_dir_force(t, d, s)) for d in directions]
            if ratio_pair:
                r.append(_fmt(_ratio(_dir_force(t, ratio_pair[0], s), _dir_force(t, ratio_pair[1], s)), 2))
        rows.append(r)
    note = "Max force, best rep. A dash means that side wasn't tested that day."
    if (player.throws or "").upper()[:1] not in ("L", "R"):
        note += " No throwing hand on file, so sides show as left / right."
    return ui_helpers.card(
        ui.div(*tiles, class_="gbo-kpi-row", style="margin-bottom:12px;"),
        _table(cols, rows),
        ui.p(note, class_="text-muted small"),
        title=f"ForceFrame · {test_type}",
        right=(position + " · " if position else "") + f"Latest {latest.tested_at:%b %d, %Y}",
    )


# ---------------------------------------------------------------- tab

def build_vald_tab(db, pid):
    p = db.query(Player).filter(Player.player_id == pid).first()
    if p is None:
        return ui_helpers.card(ui_helpers.empty_state("No player selected."))
    tests = db.query(ValdTest).filter(ValdTest.player_id == pid).order_by(ValdTest.tested_at.desc()).all()
    intro = ui.p("Raw results from VALD ForceDecks and ForceFrame. Shown for reference only -- these numbers "
                 "aren't scored and don't feed Assessments or percentiles.", class_="text-muted small")
    if not tests:
        return ui.div(intro, ui_helpers.card(ui_helpers.empty_state("No VALD tests on file yet. Staff bring them in on Import VALD.")))
    groups = {}
    for t in tests:
        key = (t.system, t.test_type, t.position if t.system == "ForceFrame" else None)
        groups.setdefault(key, []).append(t)
    # ForceDecks first, then ForceFrame; newest group first within each.
    ordered = sorted(groups.items(), key=lambda kv: (kv[0][0] != "ForceDecks", -max(t.tested_at for t in kv[1]).timestamp()))
    sections = []
    for (system, test_type, position), ts in ordered:
        if system == "ForceFrame":
            sections.append(_forceframe_section(test_type, position, ts, p))
        else:
            sections.append(_forcedecks_section(test_type, ts, p))
    return ui.div(intro, *sections)


def register(input, output, session, app_state, profile_pid):
    """Call from player_profile_server. profile_pid(db) -> shown player id."""

    @render.ui
    def vald_tab():
        if not app_state.is_authenticated():
            return None
        req("profile_tabs" in input and input.profile_tabs() == "VALD Testing")
        db = get_session()
        try:
            pid = profile_pid(db)
            if pid is None:
                return ui_helpers.card(ui_helpers.empty_state("No player selected."))
            return build_vald_tab(db, pid)
        finally:
            db.close()
