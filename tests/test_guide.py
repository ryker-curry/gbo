"""How to Read GBO: every link points at a real section, every section's pages exist in the nav."""

import os
import re

import guide_content
import nav

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROLES = [("Head Coach", None, False), ("Coach", "Pitching", False), ("Coach", "Hitting", False),
         ("Athletic Trainer", None, False), ("Player", None, True), ("Player", None, False)]


def _all_titles():
    return {p.title for r in ROLES for s in nav.build_nav_sections(*r) for p in s.pages}


def test_sections_complete():
    keys = [s["key"] for s in guide_content.GUIDE]
    assert len(keys) == len(set(keys))
    for s in guide_content.GUIDE:
        assert s["who"] in guide_content.WHO_LABELS
        assert s["shows"] and s["use"] and s["good"]


def test_section_pages_exist():
    titles = _all_titles()
    for s in guide_content.GUIDE:
        for t in s["pages"]:
            assert t in titles, (s["key"], t)


def test_every_how_to_link_has_a_section():
    used = set()
    for d, _dirs, files in os.walk(os.path.join(ROOT, "shiny_app")):
        for f in files:
            if f.endswith(".py"):
                used |= set(re.findall(r'how_to_link\("([a-z_]+)"', open(os.path.join(d, f)).read()))
    assert used, "no how_to_link calls found"
    assert used <= set(guide_content.BY_KEY), used - set(guide_content.BY_KEY)


def test_guide_page_in_every_role_nav():
    for r in ROLES:
        assert "How to Read GBO" in {p.title for s in nav.build_nav_sections(*r) for p in s.pages}


def test_modal_builds():
    from modules import how_to_read
    for s in guide_content.GUIDE:
        assert how_to_read.modal(s["key"], _all_titles()) is not None
