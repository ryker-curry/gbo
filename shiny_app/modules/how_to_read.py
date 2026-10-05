"""
GBO -- "How to Read GBO" guide page (Oct 2026, Ryker approved Part 2).
Plain-English help for every main page; content in guide_content.py.
The same sections open as a pop-up from the "How to read this" links
on key pages (ui_helpers.how_to_link + app.py's _show_how_to).
"""

import json

from shiny import module, ui, render

import guide_content
import nav
import ui_helpers

CSS = """
.gbo-guide-sec h4 { font-size: 1rem; margin: 0 0 4px; }
.gbo-guide-sec .who { font-size: .68rem; text-transform: uppercase; letter-spacing: .08em; color: var(--gbo-text-muted); }
.gbo-guide-sec .lbl { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; margin: 10px 0 2px; color: var(--gbo-text-2); }
.gbo-guide-sec ul { margin: 0; padding-left: 18px; }
.gbo-guide-sec li { margin-bottom: 4px; }
.gbo-guide-sec .go { font-size: .82rem; font-weight: 600; cursor: pointer; color: var(--gbo-accent, #E0573E); }
"""


def section_body(sec, allowed=None):
    """The inside of one guide section (used on the page and in pop-ups)."""
    go = None
    if allowed:
        title = next((t for t in sec["pages"] if t in allowed), None)
        if title:
            js = f"Shiny.setInputValue('sidebar_go', {json.dumps(title)}, {{priority: 'event'}})"
            go = ui.tags.a(f"Open {title} →", class_="go", onclick=js, role="button", tabindex="0")
    return ui.div(
        ui.p(sec["shows"]),
        ui.div("How to use it", class_="lbl"), ui.tags.ul(*[ui.tags.li(x) for x in sec["use"]]),
        ui.div("What good looks like", class_="lbl"), ui.tags.ul(*[ui.tags.li(x) for x in sec["good"]]),
        ui.div(go, style="margin-top:8px;") if go is not None else None,
        class_="gbo-guide-sec",
    )


def modal(key, allowed=None):
    sec = guide_content.BY_KEY.get(key)
    if sec is None:
        return None
    return ui.modal(ui.tags.style(CSS), section_body(sec, allowed), title=f"How to read: {sec['title']}",
                    easy_close=True, footer=ui.modal_button("Got it"), size="l")


def _order_for(role, is_pitcher):
    if role == "Player":
        mine = "pitchers" if is_pitcher else "hitters"
        rank = {"all": 0, mine: 1}
        secs = [s for s in guide_content.GUIDE if s["who"] in ("all", mine)]
    else:
        rank = {"all": 0, "staff": 1, "pitchers": 2, "hitters": 2}
        secs = list(guide_content.GUIDE)
    return sorted(secs, key=lambda s: rank.get(s["who"], 3))


@module.ui
def how_to_read_ui():
    return ui.div(
        ui.tags.style(CSS),
        ui_helpers.page_header("How to Read GBO", "What every page shows, how to use it, and what good looks like."),
        ui.input_text("q", None, placeholder="Search -- e.g. chase, Stuff+, QAB, rest", width="100%"),
        ui.output_ui("sections"),
    )


@module.server
def how_to_read_server(input, output, session, app_state):

    @render.ui
    def sections():
        if not app_state.is_authenticated():
            return None
        role, spec, isp = app_state.role_name(), app_state.coach_specialty(), app_state.is_pitcher()
        allowed = {p.title for s in nav.build_nav_sections(role, spec, isp) for p in s.pages}
        secs = _order_for(role, isp)
        q = (input.q() or "").strip().lower()
        if q:
            secs = [s for s in secs if q in " ".join([s["title"], s["shows"], *s["use"], *s["good"]]).lower()]
        if not secs:
            return ui_helpers.empty_state("Nothing matches that search.")
        panels = [ui.accordion_panel(
            ui.span(s["title"], ui.span(f"  ·  {guide_content.WHO_LABELS[s['who']]}", class_="text-muted small")),
            section_body(s, allowed), value=s["key"]) for s in secs]
        return ui.accordion(*panels, id="guide_acc", open=[secs[0]["key"]] if not q else [s["key"] for s in secs],
                            multiple=True)
