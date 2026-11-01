"""
GBO -- Shiny rendering for the Baseball-Reference-style standard stat
line (Oct 2026). Shared by Season Stats (coach, analytics.py) and My
Stats (player, player_game_stats.py) so the two never drift apart. The
numbers themselves come from the root-level stat_line.py.
"""

from shiny import ui

import stat_line

_NOTE_PITCHING = (
    "* = practice/fall season, not official. Dashes are stats GBO doesn't track yet (W, L, SV, CG, SHO). "
    "BB includes intentional walks, like Baseball-Reference. ERA+ is vs the D2 average (100 = average)."
)
_NOTE_BATTING = (
    "* = practice/fall season, not official. Dashes are stats GBO doesn't track yet (R, RBI, SB, CS). "
    "BB includes intentional walks, like Baseball-Reference. OPS+ is vs the D2 average (100 = average)."
)


def stat_line_table(columns, rows, career, season_ids, selected_season_id):
    """One row per season, Career in the footer, the season picked in the
    page's dropdown highlighted."""
    def cells(row):
        out = []
        for c in columns:
            v = row.get(c, stat_line.DASH)
            out.append(ui.tags.td(v, class_="gbo-statline-na") if v == stat_line.DASH else ui.tags.td(v))
        return out
    head = ui.tags.tr(*[ui.tags.th(c, title=stat_line.COLUMN_HELP.get(c, "")) for c in columns])
    body = []
    for sid, row in zip(season_ids, rows):
        cls = "gbo-statline-selected" if selected_season_id is not None and sid == selected_season_id else None
        body.append(ui.tags.tr(*cells(row), class_=cls))
    table = ui.tags.table(
        ui.tags.thead(head), ui.tags.tbody(*body), ui.tags.tfoot(ui.tags.tr(*cells(career))),
        class_="table table-sm",
    )
    return ui.div(ui.div(table, class_="table-responsive"), class_="gbo-statline")


def stat_line_section(db, player, selected_season_id):
    """[title, table, note] for this player (pitching if he's a pitcher,
    batting otherwise), or [] if he has no Game Tracking data yet."""
    if player.is_pitcher:
        rows, career, ids = stat_line.pitching_stat_rows(db, player.player_id)
        cols, note, title = stat_line.PITCHING_COLUMNS, _NOTE_PITCHING, "Standard Pitching"
    else:
        rows, career, ids = stat_line.batting_stat_rows(db, player.player_id)
        cols, note, title = stat_line.BATTING_COLUMNS, _NOTE_BATTING, "Standard Batting"
    if not rows:
        return []
    return [
        ui.p(ui.strong(title)),
        stat_line_table(cols, rows, career, ids, selected_season_id),
        ui.p(note, class_="text-muted small"),
    ]
