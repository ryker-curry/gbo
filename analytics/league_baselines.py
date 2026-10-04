"""
GBO -- League baselines (Oct 2026, Ryker: "lets adjust some of the
baselines for key stats to d2 averages ... compare to d2 baselines";
approved: show BOTH a D2 and an MIAA column, keep the team average, and
grade the up/down marks against D2 wherever a D2 number exists).

Source: spring 2026 season totals (all games) from 11 D2 conference stats
pages -- 136 teams, about half of D2: MIAA, GLVC, Lone Star, PSAC, Gulf
South, GAC, NSIC, Sunshine State, CCAA, RMAC, NE10. (Ryker picked 2026 over
2025; 2025 for reference: D2 .296/.397/.456, ERA 6.52, WHIP 1.71.) Pooled (sum of all teams'
counting stats, then the rate), so bigger samples weigh more. PA
approximated as AB + BB + HBP + SF (conference pages don't list sacrifice
bunts). Pitcher K% / BB% per batter faced = the league's hitter K% / BB%
(league-wide they're the same events).

Only stats published for D2 are here. Plate-discipline and pitch-level
numbers (chase, whiff, swing decisions, strike %, first-pitch strike %,
hit-the-spot, Stuff+) have no public D2 data and stay team-relative.

To update for a new season: replace the numbers below and SEASON.
"""

SEASON = "2026"
SOURCE = "2026 D2: 136 teams / 11 conferences; MIAA: 13 teams"

# Hitting (AVG/OBP/SLG as decimals, K%/BB% per plate appearance in percent)
HITTING = {
    "D2":   {"AVG": 0.300, "OBP": 0.406, "SLG": 0.457, "K%": 17.1, "BB%": 11.6},
    "MIAA": {"AVG": 0.303, "OBP": 0.418, "SLG": 0.482, "K%": 16.4, "BB%": 12.7},
}

# Pitching (k_pct/bb_pct per batter faced, percent -- same keys as
# player_report.stat_bundle)
PITCHING = {
    "D2":   {"era": 6.73, "whip": 1.75, "k_pct": 17.1, "bb_pct": 11.6, "k9": 7.6, "bb9": 5.0},
    "MIAA": {"era": 6.97, "whip": 1.77, "k_pct": 16.4, "bb_pct": 12.7, "k9": 7.3, "bb9": 5.3},
}

LEAGUES = ("D2", "MIAA")


def hitting(key, league="D2"):
    return HITTING.get(league, {}).get(key)


def pitching(key, league="D2"):
    return PITCHING.get(league, {}).get(key)


def fmt(key, v):
    """Display a baseline value the way GBO shows that stat."""
    if v is None:
        return "—"
    if key in ("AVG", "OBP", "SLG"):
        s = f"{v:.3f}"
        return s[1:] if s.startswith("0") else s
    if key in ("era", "whip"):
        return f"{v:.2f}"
    if key in ("k9", "bb9"):
        return f"{v:.1f}"
    return f"{v:.0f}%" if v >= 10 else f"{v:.1f}%"


def short(key, kind="hitting"):
    """'D2 .296 · MIAA .292' (empty string if no baseline)."""
    get = hitting if kind == "hitting" else pitching
    parts = [f"{lg} {fmt(key, get(key, lg))}" for lg in LEAGUES if get(key, lg) is not None]
    return " · ".join(parts)
