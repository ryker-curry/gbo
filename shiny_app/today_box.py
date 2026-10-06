"""
GBO -- the "Today" box drawn at the top of every dashboard (Oct 2026,
Ryker approved Part 2). Data: analytics/today.py. Links jump straight to
the page through the sidebar's own `sidebar_go` input, and only show for
pages this role can open.
"""

import json

from shiny import ui

import nav
import ui_helpers

STATUS_COLORS = {"Available": "#2E9C62", "Limited": "#B58A22", "Down": "#D94F3D", "Hold": "#D94F3D",
                 "Met": "#2E9C62", "On track": "#2E9C62", "Making progress": "#B58A22", "Off track": "#D94F3D"}

CSS = """
.gbo-today { margin-bottom: 18px; }
.gbo-today-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.gbo-today-tile { background: var(--gbo-bg-raised, rgba(255,255,255,.03)); border: 1px solid var(--gbo-border);
  border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.gbo-today-tile .big { font-size: 1.25rem; font-weight: 700; line-height: 1.2; }
.gbo-today-tile .line { font-size: .86rem; }
.gbo-today-tile ul { margin: 2px 0 0; padding-left: 18px; font-size: .84rem; }
.gbo-today-tile .go { margin-top: auto; padding-top: 6px; font-size: .82rem; font-weight: 600; cursor: pointer; color: var(--gbo-accent, #E0573E); }
.gbo-today-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }
.gbo-today-stats { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: .86rem; }
.gbo-today-stats b { font-size: 1rem; }
"""


def allowed_titles(role_name, specialty, is_pitcher):
    try:
        return {p.title for s in nav.build_nav_sections(role_name, specialty, is_pitcher) for p in s.pages}
    except Exception:
        return set()


def _go(title, allowed, label=None):
    if title not in allowed:
        return None
    js = f"Shiny.setInputValue('sidebar_go', {json.dumps(title)}, {{priority: 'event'}})"
    return ui.tags.a(f"{label or 'Open ' + title} →", class_="go", onclick=js, role="button", tabindex="0")


def _dot(status):
    return ui.span(class_="gbo-today-dot", style=f"background:{STATUS_COLORS.get(status, '#888')};")


def _tile(cap, *children):
    return ui.div(ui.div(cap, class_="gbo-cap"), *[c for c in children if c is not None], class_="gbo-today-tile")


def _date(d):
    return d.strftime("%a %b %d").replace(" 0", " ") if d else ""


def _game_tile(g, cap, link):
    if not g:
        return _tile(cap, ui.div("No games charted yet.", class_="text-muted line"))
    head = f"{g['result']} vs {g['opponent']}" if g["result"] else f"vs {g['opponent']}"
    stats = None
    if g.get("stats"):
        stats = ui.div(*[ui.span(ui.tags.b("—" if v is None else (f"{v:.0f}%" if k.endswith("%") and isinstance(v, (int, float)) else str(v))),
                                 f" {k}") for k, v in g["stats"]], class_="gbo-today-stats")
    return _tile(cap, ui.div(head, class_="big"), ui.div(_date(g["date"]), class_="text-muted line"), stats, link)


def coach_box(data, allowed):
    tiles = []
    arm = data.get("arm")
    if arm is not None:
        c = arm["counts"]
        lines = [ui.tags.li(_dot(r["status"]), ui.tags.b(r["name"]), f" -- {r['status']}",
                            f" until {_date(r['ready_on'])}" if r.get("ready_on") and r["status"] == "Down" else "")
                 for r in arm["not_available"][:6]]
        more = len(arm["not_available"]) - 6
        if more > 0:
            lines.append(ui.tags.li(f"+{more} more"))
        tiles.append(_tile("Who can throw today",
                           ui.div(f"{c['Available']} of {arm['total']} available", class_="big"),
                           ui.div(f"{c['Limited']} limited · {c['Down'] + c['Hold']} down or on hold", class_="text-muted line"),
                           ui.tags.ul(*lines) if lines else ui.div("Everyone is good to go.", class_="line"),
                           _go("Arm Care & Availability", allowed)))
    tiles.append(_game_tile(data.get("last_game"), "Last game", _go("Team Game Report", allowed, "Team Game Report")))
    h = data.get("health")
    if h is not None:
        bits = []
        if h["to_fix"]:
            bits.append(ui.tags.li(f"{h['to_fix']} game{'s' if h['to_fix'] != 1 else ''} with charting to fix"))
        if h["box_off"]:
            bits.append(ui.tags.li(f"{h['box_off']} box score{'s' if h['box_off'] != 1 else ''} don't match the charting"))
        if h["no_box"]:
            bits.append(ui.tags.li(f"{h['no_box']} game{'s' if h['no_box'] != 1 else ''} with no official box score typed in"))
        tiles.append(_tile("Charting (last 2 weeks)",
                           ui.div(f"{h['avg']}% complete", class_="big"),
                           ui.tags.ul(*bits) if bits else ui.div("Nothing to fix.", class_="line"),
                           _go("Data Health", allowed)))
    goals = data.get("goals_off") or []
    if goals:
        tiles.append(_tile("Goals off track",
                           ui.div(f"{len(goals)} player goal{'s' if len(goals) != 1 else ''}", class_="big"),
                           ui.tags.ul(*[ui.tags.li(ui.tags.b(g["name"]), f" -- {g['label']}: {g['current']} "
                                                   f"(target {'over' if g['higher_better'] else 'under'} {g['target']})")
                                        for g in goals[:5]]),
                           _go("IDP", allowed, "Open IDP")))
    return _wrap(data["today"], tiles)


def player_box(data, allowed):
    tiles = []
    arm = data.get("arm")
    if arm is not None:
        st = arm["status"]
        detail = arm.get("reason") or ""
        if st != "Available" and arm.get("ready_on"):
            detail = f"Rested on {_date(arm['ready_on'])}" + (f" · {detail}" if detail else "")
        last = f"Last threw {_date(arm['last'])} ({arm['last_pitches']} pitches)" if arm.get("last") else None
        tiles.append(_tile("My arm today", ui.div(_dot(st), st, class_="big"),
                           ui.div(detail, class_="line") if detail else None,
                           ui.div(last, class_="text-muted line") if last else None))
    tiles.append(_game_tile(data.get("last_game"), "My last game", _go("Pitcher Report" if "Pitcher Report" in allowed else "Hitter Report", allowed, "Open my report")))
    goals = data.get("goals") or []
    if goals:
        items = []
        for g in goals:
            st = (g.get("status") or "").split(" · ")[-1]
            cur = g.get("current")
            items.append(ui.tags.li(_dot(st) if st in STATUS_COLORS else None, ui.tags.b(g.get("metric") or g.get("description") or "Goal"),
                                    f": {cur} now" if cur is not None else "",
                                    f" -> {g['target']:g}" if isinstance(g.get("target"), (int, float)) else ""))
        tiles.append(_tile("My goals", ui.tags.ul(*items), _go("My Development", allowed)))
    else:
        tiles.append(_tile("My goals", ui.div("No open goals yet -- set one with your coach.", class_="text-muted line"),
                           _go("My Development", allowed)))
    if data.get("week"):
        tiles.append(_tile("My weekly report", ui.div(f"Week of {_date(data['week'])}", class_="big"),
                           ui.div("Your week in one page: what changed and what to work on.", class_="text-muted line"),
                           _go("My Weekly Report", allowed, "Open my weekly report")))
    return _wrap(data["today"], tiles)


def _wrap(today, tiles):
    return ui.div(
        ui.tags.style(CSS),
        ui.div(ui.div("Today", class_="gbo-section-title"),
               ui.div(_date(today), "  ·  ", ui_helpers.how_to_link("today", "What's this?"), class_="right text-muted"),
               class_="gbo-section-title-row"),
        ui.div(*tiles, class_="gbo-today-grid"),
        class_="gbo-today",
    )
