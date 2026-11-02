"""
GBO -- Arsenal Comparison (Nov 2026, Ryker: Past The Eye Test-style
pitcher similarity comps, PSU vs PSU only; also the "compare PSU pitchers
to each other to help decide who to go to next" idea from the Pearl
Player Development backlog).

Staff only. Pick two pitchers: overall similarity badge, a bar per
category (Release / Arsenal / Whiff / Command / Contact), both
catcher's-view release cards side by side, and a stat table with the
gap on every stat in staff standard deviations (1.0+ highlighted).
Below it: pitcher A's five closest teammates.

Data: analytics/release_comps.staff_pool -- game pitches only (no
bullpens), this page's date range and game scope. Categories with no
data yet are skipped, so it works with Release alone.
"""

from datetime import date

from shiny import module, ui, render, req, reactive

from database import get_session
from models import Player, StaffPlayerAssignment
from analytics import release_comps
from analytics.weekly_report import season_start
import release_graphics
import ui_helpers
import deep_link

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
TITLE = "Arsenal Comparison"


@module.ui
def arsenal_comparison_ui():
    return ui.div(
        ui_helpers.page_header(
            TITLE,
            "Compare two of our pitchers -- release, arsenal, whiffs, command and contact -- and find each "
            "pitcher's closest teammates. Game pitches only.",
        ),
        ui.output_ui("ac_filters"),
        ui.output_ui("ac_pickers"),
        ui.output_ui("ac_compare"),
        ui.output_ui("ac_comps"),
    )


@module.server
def arsenal_comparison_server(input, output, session, app_state):
    _dl = deep_link.Pending(app_state, TITLE, on_arrive=lambda p: [
        ui.update_select("ac_a", selected=str(p["pid"])) if "pid" in p else None,
        ui.update_select("ac_b", selected=str(p["pid_b"])) if "pid_b" in p else None,
    ])

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    def _visible_ids(db):
        if app_state.can_view_all_players():
            return None
        return {a.player_id for a in db.query(StaffPlayerAssignment)
                .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()}

    @reactive.calc
    def _summ():
        req("ac_scope" in input)
        db = get_session()
        try:
            summ = release_comps.staff_pool(db, input.ac_from(), input.ac_to(), input.ac_scope())
            vis = _visible_ids(db)
        finally:
            db.close()
        return summ, vis

    def _choices(summ, vis):
        pool = summ["pool"]
        ids = [int(i) for i in pool["player_id"]] if not pool.empty else []
        if vis is not None:
            ids = [i for i in ids if i in vis]
        players = [summ["players"][i] for i in ids if i in summ["players"]]
        players.sort(key=lambda p: (p.last_name, p.first_name))
        return {str(p.player_id): f"{p.last_name}, {p.first_name}" for p in players}

    @render.ui
    def ac_filters():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        return ui.layout_columns(
            ui.input_date("ac_from", "From", value=season_start()),
            ui.input_date("ac_to", "To", value=date.today()),
            ui.input_select("ac_scope", "Games",
                            choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[4, 4, 4],
        )

    @render.ui
    def ac_pickers():
        if not _ok():
            return None
        summ, vis = _summ()
        choices = _choices(summ, vis)
        if len(choices) < 2:
            return ui_helpers.empty_state(
                f"Needs at least two pitchers with {release_comps.MIN_COMP_GAME_PITCHES}+ charted game pitches "
                "in this date range.")
        with reactive.isolate():
            cur_a = input.ac_a() if "ac_a" in input else None
            cur_b = input.ac_b() if "ac_b" in input else None
        a = _dl.take("pid", choices) or (cur_a if cur_a in choices else next(iter(choices)))
        b = _dl.take("pid_b", choices) or (cur_b if cur_b in choices and cur_b != a else None)
        if b is None:
            comps = release_comps.closest_teammates(summ, int(a), n=5)
            b = next((str(p.player_id) for p, *_ in comps if str(p.player_id) in choices), None)
            b = b or next(k for k in choices if k != a)
        return ui.layout_columns(
            ui.input_select("ac_a", "Pitcher A", choices=choices, selected=a),
            ui.input_select("ac_b", "Pitcher B", choices=choices, selected=b),
            col_widths=[6, 6],
        )

    @render.ui
    def ac_compare():
        if not _ok():
            return None
        req("ac_a" in input and "ac_b" in input)
        a, b = int(input.ac_a()), int(input.ac_b())
        if a == b:
            return ui.p("Pick two different pitchers.", class_="text-muted small")
        summ, _vis = _summ()
        res = release_comps.compare(summ, a, b)
        if res is None:
            return None
        ra, rb, sim = res
        if sim.get("overall") is None:
            return ui.p("No stats in common yet for these two.", class_="text-muted small")
        pa, pb = summ["profiles"].get(a), summ["profiles"].get(b)
        # A pitcher with no release card still gets the numbers.
        pa = pa or _blank(summ["players"][a])
        pb = pb or _blank(summ["players"][b])
        html = release_graphics.comparison_html(pa, pb, ra, rb, sim)
        return ui.div(ui.HTML(html), class_="mt-2")

    @render.ui
    def ac_comps():
        if not _ok():
            return None
        req("ac_a" in input)
        summ, vis = _summ()
        a = int(input.ac_a())
        comps = release_comps.closest_teammates(summ, a, n=5)
        if not comps:
            return None
        rows = []
        for p, overall, cats in comps:
            if vis is not None and p.player_id not in vis:
                continue
            row = {"Teammate": f"{p.first_name} {p.last_name}", "Similarity": f"{overall:.0f}%"}
            for c in release_graphics.CATEGORY_FEATURES:
                row[c] = f"{cats[c]:.0f}%" if c in cats else "—"
            rows.append(row)
        if not rows:
            return None
        me = summ["players"].get(a)
        return ui_helpers.card(
            ui_helpers.render_dict_table(rows),
            ui.p("100% = identical. One standard deviation apart on every stat is about 61%. Categories with "
                 "no data yet are left out of the overall number.", class_="text-muted small", style="margin:6px 0 0;"),
            title=f"Closest teammates to {me.first_name} {me.last_name}" if me else "Closest teammates",
        )


def _blank(player):
    """Placeholder profile so comparison_html still renders the table when a
    pitcher has no release card (no Rapsodo fastball readings yet)."""
    return release_graphics.ReleaseProfile(
        name=f"{player.first_name} {player.last_name}", throws=player.throws or "R",
        release_height_ft=0.0, release_side_ft=0.0, extension_ft=0.0,
        height_in=float(player.height_in) if player.height_in is not None else None,
        subtitle="No release data yet", extra={"no_card": True},
    )
