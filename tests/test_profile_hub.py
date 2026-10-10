"""Player Profile hub (profile_links / deep_link) and the simplified staff sidebar."""

from shiny import reactive

import deep_link
import nav
import profile_links

STAFF = [("Head Coach", None), ("Coach", "Pitching"), ("Coach", "Hitting"), ("Strength Coach", None),
         ("Athletic Trainer", None), ("Sports Scientist", None), ("Data Analyst", None), ("Video Coordinator", None)]


def _keys(role, spec=None):
    return [p.key for s in nav.build_nav_sections(role, spec, False) for p in s.pages]


def test_admin_and_players_keep_full_sidebar():
    assert nav.simple_sidebar_groups("Administrator") is None
    assert nav.simple_sidebar_groups("Player") is None


def test_every_other_staff_role_is_short():
    for role, spec in STAFF:
        core = nav.simple_sidebar_groups(role)
        assert core is not None, role
        allowed = set(_keys(role, spec))
        shown = {k for _g, keys in core for k in keys if k in allowed}
        assert "dashboard" in shown and 4 <= len(shown) <= 13, (role, shown)
        assert len(allowed - shown) > 0  # the rest goes to More tools, nothing lost


def test_coach_sidebar_matches_plan():
    core = dict(nav.simple_sidebar_groups("Coach"))
    assert "game_tracking" not in {k for keys in core.values() for k in keys}  # Ryker: More tools
    assert core["Players"] == ["roster", "player_profile", "arm_care"]


def test_profile_link_pages_exist_for_coaches():
    titles = {p.title for s in nav.build_nav_sections("Coach", "Pitching", False) for p in s.pages}
    for _bid, _label, title, _need in profile_links.ALL_LINKS:
        assert title in titles, title


def test_pending_take_only_matches_choices():
    p = deep_link.Pending.__new__(deep_link.Pending)
    p.values = {"pid": 7, "game_id": 23}
    p.tick = reactive.value(0)
    with reactive.isolate():
        assert p.take("pid", {"3": "a"}) is None      # not a choice yet -- kept
        assert p.take("pid", {"7": "b"}) == "7"       # taken
        assert p.take("pid", {"7": "b"}) is None      # only once
        assert p.take("game_id") == "23"
