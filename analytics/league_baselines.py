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
    "D2":   {"AVG": 0.300, "OBP": 0.406, "SLG": 0.457, "K%": 17.1, "BB%": 11.6,
             "ISO": 0.156, "BABIP": 0.348, "wOBA": 0.382},
    "MIAA": {"AVG": 0.303, "OBP": 0.418, "SLG": 0.482, "K%": 16.4, "BB%": 12.7},
}

# Pitching (k_pct/bb_pct per batter faced, percent -- same keys as
# player_report.stat_bundle)
PITCHING = {
    "D2":   {"era": 6.73, "whip": 1.75, "k_pct": 17.1, "bb_pct": 11.6, "k9": 7.6, "bb9": 5.0,
             "fip": 6.73, "kbb_pct": 5.5},
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


# ---------------------------------------------------------------------------
# "+" stats vs D2 2026 (Oct 2026, Ryker: "can we base ops+, era+ etc off
# these 2026 d2 season stats?" -> OPS+, ERA+, FIP constant, wOBA+, plus
# AVG+/OBP+/SLG+/ISO+/K%+/BB%+/BABIP+ for hitters and WHIP+/K%+/BB%+/
# K-BB%+/FIP+ for pitchers; D2 only, no team-relative version).
# 100 = D2 average and HIGHER IS ALWAYS BETTER: stats where lower is
# better (hitter K%, ERA, WHIP, pitcher BB%, FIP) are flipped
# (100 x league / player), the rest are 100 x player / league.
# OPS+ uses the Baseball-Reference formula 100 x (OBP/lg + SLG/lg - 1).
# GBO's wOBA uses its own fixed weights (game_stats.WOBA_WEIGHTS); the D2
# wOBA above was computed from D2 totals with those same weights.
# D2 FIP = D2 ERA by construction (FIP_CONSTANT 4.72 in game_stats).
# ---------------------------------------------------------------------------

FIP_CONSTANT_D2 = 4.72


def _ratio(x, lg, flip=False):
    if x is None or not lg:
        return None
    if flip:
        return round(100 * lg / x) if x else None
    return round(100 * x / lg)


def hitting_plus(line):
    """line: a game_stats.compute_batting_line dict (AVG/OBP/SLG/ISO/wOBA,
    "K %"/"BB %" as percents, AB/H/HR/K/SF for BABIP). Returns
    {"OPS+", "wOBA+", "AVG+", "OBP+", "SLG+", "ISO+", "K%+", "BB%+", "BABIP+"}."""
    lg = HITTING["D2"]
    obp, slg = line.get("OBP"), line.get("SLG")
    out = {
        "OPS+": round(100 * (obp / lg["OBP"] + slg / lg["SLG"] - 1)) if obp is not None and slg is not None else None,
        "wOBA+": _ratio(line.get("wOBA"), lg["wOBA"]),
        "AVG+": _ratio(line.get("AVG"), lg["AVG"]),
        "OBP+": _ratio(obp, lg["OBP"]),
        "SLG+": _ratio(slg, lg["SLG"]),
        "ISO+": _ratio(line.get("ISO"), lg["ISO"]),
        "K%+": _ratio(line.get("K %"), lg["K%"], flip=True),
        "BB%+": _ratio(line.get("BB %"), lg["BB%"]),
    }
    ab, h, hr, k, sf = (line.get(x) for x in ("AB", "H", "HR", "K", "SF"))
    den = (ab or 0) - (k or 0) - (hr or 0) + (sf or 0)
    babip = ((h or 0) - (hr or 0)) / den if ab and den > 0 else None
    out["BABIP+"] = _ratio(babip, lg["BABIP"])
    return out


def pitching_plus(line):
    """line: a game_stats.compute_pitching_line dict ("ERA", "FIP", "WHIP",
    "K", "BB", "Batters Faced"). Returns {"ERA+", "FIP+", "WHIP+", "K%+",
    "BB%+", "K-BB%+"}."""
    lg = PITCHING["D2"]
    bf = line.get("Batters Faced") or 0
    k_pct = 100 * line["K"] / bf if bf and line.get("K") is not None else None
    bb_pct = 100 * line["BB"] / bf if bf and line.get("BB") is not None else None
    kbb = (k_pct - bb_pct) if k_pct is not None and bb_pct is not None else None
    return {
        "ERA+": _ratio(line.get("ERA"), lg["era"], flip=True),
        "FIP+": _ratio(line.get("FIP"), lg["fip"], flip=True),
        "WHIP+": _ratio(line.get("WHIP"), lg["whip"], flip=True),
        "K%+": _ratio(k_pct, lg["k_pct"]),
        "BB%+": _ratio(bb_pct, lg["bb_pct"], flip=True),
        "K-BB%+": round(100 * kbb / lg["kbb_pct"]) if kbb is not None else None,
    }


HITTING_PLUS_ORDER = ("OPS+", "wOBA+", "AVG+", "OBP+", "SLG+", "ISO+", "K%+", "BB%+", "BABIP+")
PITCHING_PLUS_ORDER = ("ERA+", "FIP+", "WHIP+", "K%+", "BB%+", "K-BB%+")
PLUS_HELP = ("100 = 2026 D2 average. Higher is better on every one -- e.g. 120 = 20% better than a D2-average "
             "player (for ERA, WHIP, K% for hitters and BB% for pitchers the math is flipped so better is still higher).")
