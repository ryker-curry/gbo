"""
GBO -- Shared value-formatting and game-label helpers, extracted out of
several page modules that each carried their own copy.

format_pct/format_num: analytics.py, hitter_game_report.py,
hitter_profile.py, pitcher_game_report.py, pitcher_profile.py, and
player_game_stats.py each defined their own `_fmt_pct`/`_fmt` with the
identical "%.<N>f" + em-dash-for-None body, differing only in which
decimals default each page happened to pick (0 vs 1 for percentages,
2 vs 3 for plain numbers). Rather than force one default on every
call site (which would silently change what's displayed on whichever
pages don't already pass decimals explicitly), each module keeps its
own `_fmt_pct`/`_fmt` name and default, now as a one-line call into the
shared implementation here -- so the formatting logic has one source
of truth, and every page's displayed output is unchanged.

opponent_display_name: identical across game_tracking.py,
hitter_game_report.py, and pitcher_game_report.py.

game_label: hitter_game_report.py and pitcher_game_report.py had an
identical short "date -- vs/at opponent (status)" version.
game_tracking.py has its own longer version (adds a season prefix and
the score) that is NOT a duplicate of this one -- it stays local to
that module.
"""


def format_pct(value, decimals=1):
    return f"{value:.{decimals}f}%" if value is not None else "—"


def format_num(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


def opponent_display_name(g):
    if g.opponent_team:
        return g.opponent_team.team_name
    return g.opponent_name or "Unknown opponent"


def game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
    return f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {opponent_display_name(g)} ({g.status})"
