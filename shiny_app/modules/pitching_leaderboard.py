"""
GBO -- Pitching Staff Leaderboard (Sept 2026, Ryker: "create a pitching
staff leaderboard with both coaches and players can see. be able to
click a specific stat and it rearranges them best to worst. allow the
coach to pick what stats they want to see. have a glossary explaining
each stat. pull definitions for stats from trustworthy sources,
fangraphs, mlb.com, pitchprofiler.").

Roster-wide, one row per pitcher who has thrown a charted pitch in the
selected window -- combines game_stats.compute_pitching_line()'s
traditional box-score/rate stats with GBO's own team-relative pitch
grades (Stuff+/Location+/Pitching+/Command+/Arsenal/Results/
Performance), via analytics/profile_queries.py's
pitching_staff_leaderboard_rows() -- the same math pitcher_profile.py's
Overview tab computes for one pitcher, run once per roster pitcher
against baselines computed once (not re-fit per pitcher).

Visible to both coaches/staff (Analytics nav section) and the Player
role (My Development section, unconditionally -- see nav.py) -- one
shared page/module, no self-scoping needed the way Pitcher Profile
needs ("my own data only" doesn't apply to a roster-wide leaderboard).

Sort ("click a specific stat and it rearranges them best to worst"): a
row of stat chips below the table (ui.input_radio_buttons, inline) --
clicking one re-sorts by that stat, direction picked automatically per
STAT_META's higher_is_better flag (ERA ascending, K% descending, etc.)
so the table always reads best-to-worst, not a raw ascending/
descending toggle the way clicking a plain column header would.

Column picker ("allow the coach to pick what stats they want to see"):
a checkbox group toggling which of STAT_META's stats are shown as
columns -- session-only, resets to DEFAULT_COLUMNS next time the page
loads (Ryker's call -- no per-user persistence for V1). Pitcher/IP are
always shown, not toggleable -- a leaderboard needs at least a name and
a workload anchor regardless of which rate stats are picked.

Glossary: glossary_content.LEADERBOARD (Sept 2026 addition) -- the
traditional stats' definitions are sourced from FanGraphs' Sabermetrics
Library and MLB.com's own glossary (see that list's module-level note
for the specific pages used); the team-relative grades reuse GBO's own
existing OVERVIEW-tab wording verbatim (they're GBO's own invented
stats, not something FanGraphs/MLB.com define). Same glossary_link/
glossary_modal pattern every other page in this app already uses.
"""

from shiny import module, ui, render, req, reactive

from database import get_session
from analytics import profile_queries
import ui_helpers
import glossary_content

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

# (key, label, higher_is_better, decimals) -- key matches
# profile_queries.pitching_staff_leaderboard_rows()'s row dict keys
# exactly. decimals controls display formatting only; sorting always
# uses the row dict's raw numeric value, never the formatted string.
# Pitcher/IP aren't listed here -- always shown, never toggled off or
# offered as a sort choice (IP is workload context, not a "how good is
# this pitcher" stat -- Ryker asked for stats to rank best-to-worst,
# and a raw innings-thrown count doesn't have a "best" direction the
# way a rate stat does).
STAT_META = [
    ("ERA", "ERA", False, 2),
    ("WHIP", "WHIP", False, 2),
    ("FIP", "FIP", False, 2),
    ("K/9", "K/9", True, 2),
    ("BB/9", "BB/9", False, 2),
    ("HR/9", "HR/9", False, 2),
    ("K %", "K%", True, 1),
    ("BB %", "BB%", False, 1),
    ("K-BB %", "K-BB%", True, 1),
    ("K/BB", "K/BB", True, 2),
    ("OBA", "OBA (opp. AVG)", False, 3),
    ("Strike %", "Strike%", True, 1),
    ("FPS %", "FPS%", True, 1),
    ("CSW %", "CSW%", True, 1),
    ("Zone Execution %", "Zone Exec%", True, 1),
    ("BF", "BF", True, 0),
    ("K", "K", True, 0),
    ("BB", "BB", False, 0),
    ("Stuff+", "Stuff+", True, 1),
    ("Location+", "Location+", True, 1),
    ("Pitching+", "Pitching+", True, 1),
    ("Command+", "Command+", True, 1),
    ("Arsenal", "Arsenal", True, 1),
    ("Results", "Results", True, 1),
    ("Performance", "Performance", True, 1),
]
STAT_LABELS = {key: label for key, label, *_rest in STAT_META}
STAT_HIGHER_BETTER = {key: hib for key, _label, hib, _dec in STAT_META}
STAT_DECIMALS = {key: dec for key, _label, _hib, dec in STAT_META}

DEFAULT_COLUMNS = ["ERA", "WHIP", "K/9", "BB/9", "K %", "FIP", "Command+", "Performance"]
DEFAULT_SORT = "ERA"


def _fmt_stat(key, value):
    if value is None:
        return "—"
    decimals = STAT_DECIMALS.get(key, 1)
    if decimals == 0:
        return str(int(value))
    return f"{value:.{decimals}f}"


@module.ui
def pitching_leaderboard_ui():
    return ui.div(
        ui.div(
            ui.h4("Pitching Staff Leaderboard", class_="gbo-section-title", style="margin-bottom:0;"),
            ui_helpers.glossary_link("lb_glossary", "Stats Glossary"),
            style="display:flex; justify-content:space-between; align-items:baseline; gap:10px;",
        ),
        ui.p(
            "Every pitcher who's thrown a charted pitch this window, one row each. Pick which stats show below, "
            "then click a stat under the table to sort the whole leaderboard best-to-worst by it.",
            class_="text-muted small",
        ),
        ui.output_ui("lb_filters"),
        ui.output_ui("lb_columns_picker"),
        ui.output_ui("lb_table"),
        ui.output_ui("lb_sort_picker"),
    )


@module.server
def pitching_leaderboard_server(input, output, session, app_state):
    @render.ui
    def lb_filters():
        if not app_state.is_authenticated():
            return None
        return ui.input_select(
            "lb_game_scope", "Games",
            choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"},
            width="220px",
        )

    @render.ui
    def lb_columns_picker():
        if not app_state.is_authenticated():
            return None
        return ui.div(
            ui.input_checkbox_group(
                "lb_columns", "Columns to show",
                choices=STAT_LABELS, selected=DEFAULT_COLUMNS, inline=True,
            ),
            class_="mt-2",
        )

    def _visible_columns():
        # Preserve STAT_META's own order, not whatever order the
        # checkbox group happens to report selections back in.
        if "lb_columns" in input and input.lb_columns():
            selected = set(input.lb_columns())
            return [key for key, *_rest in STAT_META if key in selected]
        return list(DEFAULT_COLUMNS)

    @render.ui
    def lb_sort_picker():
        if not app_state.is_authenticated():
            return None
        cols = _visible_columns()
        if not cols:
            return None
        choices = {key: STAT_LABELS[key] for key in cols}
        current = input.lb_sort_by() if "lb_sort_by" in input else None
        selected = current if current in choices else cols[0]
        return ui.div(
            ui.input_radio_buttons("lb_sort_by", "Sort by (best to worst)", choices=choices, selected=selected, inline=True),
            class_="mt-2",
        )

    @render.ui
    def lb_table():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        req("lb_game_scope" in input)
        game_scope = input.lb_game_scope()

        db = get_session()
        try:
            rows = profile_queries.pitching_staff_leaderboard_rows(db, game_scope=game_scope)
        finally:
            db.close()

        if not rows:
            return ui_helpers.empty_state("No charted pitches yet -- log some innings in Game Tracking.")

        cols = _visible_columns()
        sort_key = input.lb_sort_by() if ("lb_sort_by" in input and input.lb_sort_by() in STAT_LABELS) else DEFAULT_SORT
        higher_is_better = STAT_HIGHER_BETTER.get(sort_key, True)

        def _sort_value(row):
            v = row.get(sort_key)
            if v is None:
                return (1, 0)  # None always sorts last, whichever direction
            return (0, -v if higher_is_better else v)

        rows_sorted = sorted(rows, key=_sort_value)

        table_rows = []
        for r in rows_sorted:
            row_dict = {"Pitcher": r["Pitcher"], "IP": r["IP"]}
            for key in cols:
                row_dict[STAT_LABELS[key]] = _fmt_stat(key, r.get(key))
            table_rows.append(row_dict)

        return ui.div(
            ui_helpers.render_dict_table(table_rows),
            ui.p(f"Sorted by {STAT_LABELS[sort_key]}, best to worst.", class_="text-muted small mt-1"),
        )

    @reactive.effect
    @reactive.event(input.lb_glossary)
    def _lb_show_glossary():
        ui.modal_show(ui_helpers.glossary_modal("Pitching Stats Glossary", glossary_content.LEADERBOARD))
