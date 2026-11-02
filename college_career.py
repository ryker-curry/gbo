"""
GBO -- College Career (Nov 2026, Ryker): every college season a player had
before / outside GBO's own charting -- Pitt State spring seasons and the
schools he transferred from -- shown on Player Profile's "College Career"
tab, one row per season with its school, level and a link to where the
numbers came from. Fall ball stays GBO-charted only (Season Stats).

Many seasons were only published in part (a bio line, a news story), and a
blank stat means "not published", never zero. A row is "complete" when it
has the core counting stats (COMPLETE_*); only complete rows count toward
the Total row, so a half-known season can't drag a career line around.
Staff can add a season or fill in the gaps from the tab (e.g. from a JUCO
stat sheet a player sends).

Rows were first loaded from data/college_season_stats.csv by
scripts/import_college_season_stats.py.
"""

import csv
import re

DASH = "—"

# CSV header -> model column (shared by the importer and the edit form)
CSV_TO_COL = {
    "G": "g", "GS": "gs", "AB": "ab", "R": "r", "H": "h", "2B": "doubles", "3B": "triples", "HR": "hr",
    "RBI": "rbi", "BB": "bb", "HBP": "hbp", "SO": "so", "GDP": "gdp", "SF": "sf", "SH": "sh", "SB": "sb",
    "CS": "cs", "IBB": "ibb", "W": "w", "L": "l", "CG": "cg", "SHO": "sho", "SV": "sv", "ER": "er",
    "WP": "wp", "BK": "bk", "BF": "bf",
}
BATTING_FIELDS = ["G", "GS", "AB", "R", "H", "2B", "3B", "HR", "RBI", "BB", "HBP", "SO", "GDP", "SF", "SH", "SB", "CS", "IBB"]
PITCHING_FIELDS = ["W", "L", "G", "GS", "CG", "SHO", "SV", "IP", "H", "R", "ER", "BB", "SO", "HR", "WP", "HBP", "BK", "BF"]
COMPLETE_BATTING = ("g", "ab", "r", "h", "doubles", "triples", "hr", "rbi", "bb", "so")
COMPLETE_PITCHING = ("ip_outs", "h", "r", "er", "bb", "so")

BATTING_COLUMNS = ("Year", "School", "Level", "G", "GS", "PA", "AB", "R", "H", "2B", "3B", "HR", "RBI", "SB", "CS",
                   "BB", "SO", "BA", "OBP", "SLG", "OPS", "TB", "GDP", "HBP", "SH", "SF")
PITCHING_COLUMNS = ("Year", "School", "Level", "W", "L", "ERA", "G", "GS", "CG", "SHO", "SV", "IP", "H", "R", "ER",
                    "HR", "BB", "SO", "HBP", "BK", "WP", "BF", "WHIP", "H9", "BB9", "SO9", "SO/W")

# GBO roster name -> name the schools use (only where they differ)
NAME_ALIASES = {"robby lopez": "robert lopez iii", "jeff zachry": "jeff zachary", "miles burhle": "miles buhrle"}


# ---------------------------------------------------------------------------
# innings
# ---------------------------------------------------------------------------
def ip_to_outs(text):
    """'45.1' -> 136. None/'' -> None."""
    if text is None or str(text).strip() == "":
        return None
    whole, _, frac = str(text).strip().partition(".")
    frac = frac[:1] or "0"
    if frac not in ("0", "1", "2"):
        raise ValueError(f"innings must end in .0, .1 or .2: {text}")
    return int(whole or 0) * 3 + int(frac)


def outs_to_ip(outs):
    return None if outs is None else f"{outs // 3}.{outs % 3}"


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
def is_complete(row):
    need = COMPLETE_BATTING if row.side == "batting" else COMPLETE_PITCHING
    return all(getattr(row, c) is not None for c in need)


def _n(v):
    return DASH if v is None else str(v)


def _rate3(num, den):
    if num is None or not den:
        return DASH
    s = f"{num / den:.3f}"
    return s[1:] if s.startswith("0.") else s


def _f(v, d):
    return DASH if v is None else f"{v:.{d}f}"


def _all(*vals):
    return all(v is not None for v in vals)


def _batting_cells(s):
    """s: dict of model-column -> value (None = not published)."""
    g = s.get
    pa = g("ab") + g("bb") + g("hbp") + g("sf") + g("sh") if _all(g("ab"), g("bb"), g("hbp"), g("sf"), g("sh")) else None
    tb = (g("h") + g("doubles") + 2 * g("triples") + 3 * g("hr")) if _all(g("h"), g("doubles"), g("triples"), g("hr")) else None
    obp_den = (g("ab") + g("bb") + g("hbp") + g("sf")) if _all(g("ab"), g("bb"), g("hbp"), g("sf")) else None
    obp_num = (g("h") + g("bb") + g("hbp")) if _all(g("h"), g("bb"), g("hbp")) else None
    obp = obp_num / obp_den if obp_num is not None and obp_den else None
    slg = tb / g("ab") if tb is not None and g("ab") else None
    return {
        "G": _n(g("g")), "GS": _n(g("gs")), "PA": _n(pa), "AB": _n(g("ab")), "R": _n(g("r")), "H": _n(g("h")),
        "2B": _n(g("doubles")), "3B": _n(g("triples")), "HR": _n(g("hr")), "RBI": _n(g("rbi")),
        "SB": _n(g("sb")), "CS": _n(g("cs")), "BB": _n(g("bb")), "SO": _n(g("so")),
        "BA": _rate3(g("h"), g("ab")), "OBP": _rate3(obp, 1) if obp is not None else DASH,
        "SLG": _rate3(slg, 1) if slg is not None else DASH,
        "OPS": _rate3(obp + slg, 1) if obp is not None and slg is not None else DASH,
        "TB": _n(tb), "GDP": _n(g("gdp")), "HBP": _n(g("hbp")), "SH": _n(g("sh")), "SF": _n(g("sf")),
    }


def _pitching_cells(s):
    g = s.get
    outs = g("ip_outs")
    ip = outs / 3 if outs else None

    def per9(x):
        return _f(x * 9 / ip, 1) if x is not None and ip else DASH
    return {
        "W": _n(g("w")), "L": _n(g("l")), "ERA": _f(g("er") * 9 / ip, 2) if g("er") is not None and ip else DASH,
        "G": _n(g("g")), "GS": _n(g("gs")), "CG": _n(g("cg")), "SHO": _n(g("sho")), "SV": _n(g("sv")),
        "IP": outs_to_ip(outs) or DASH, "H": _n(g("h")), "R": _n(g("r")), "ER": _n(g("er")), "HR": _n(g("hr")),
        "BB": _n(g("bb")), "SO": _n(g("so")), "HBP": _n(g("hbp")), "BK": _n(g("bk")), "WP": _n(g("wp")),
        "BF": _n(g("bf")),
        "WHIP": _f((g("bb") + g("h")) / ip, 2) if _all(g("bb"), g("h")) and ip else DASH,
        "H9": per9(g("h")), "BB9": per9(g("bb")), "SO9": per9(g("so")),
        "SO/W": _f(g("so") / g("bb"), 2) if _all(g("so"), g("bb")) and g("bb") else DASH,
    }


STAT_COLS = list(dict.fromkeys(list(CSV_TO_COL.values()) + ["ip_outs"]))


def _stats(row):
    return {c: getattr(row, c) for c in STAT_COLS}


def career_rows(rows, side):
    """(season_rows, total_row, partial_count) for one side. Each season
    row is a dict of column -> display text plus "_partial", "_source",
    "_id". The Total row sums complete rows only; a stat that's blank on
    any of them shows a dash."""
    rows = sorted([r for r in rows if r.side == side], key=lambda r: (r.season_year, r.school))
    cells = _batting_cells if side == "batting" else _pitching_cells
    out = []
    for r in rows:
        d = cells(_stats(r))
        d.update({"Year": str(r.season_year), "School": r.school, "Level": r.level or DASH,
                  "_partial": not is_complete(r), "_source": r.source_url, "_id": r.college_season_stat_id})
        out.append(d)
    full = [r for r in rows if is_complete(r)]
    total = None
    if full:
        summed = {}
        for c in STAT_COLS:
            vals = [getattr(r, c) for r in full]
            summed[c] = None if any(v is None for v in vals) else sum(vals)
        total = cells(summed)
        n_schools = len({r.school for r in full})
        total.update({"Year": f"{len(full)} season{'s' if len(full) != 1 else ''}",
                      "School": "Total" + (f" ({n_schools} schools)" if n_schools > 1 else ""), "Level": ""})
    return out, total, sum(1 for r in rows if not is_complete(r))


# ---------------------------------------------------------------------------
# CSV import
# ---------------------------------------------------------------------------
def _norm(name):
    return re.sub(r"[^a-z ]", "", (name or "").lower()).strip()


def match_player(name, players):
    """players: iterable of Player rows. Exact full name (with aliases),
    else unique last-name + first-initial match. Returns Player or None."""
    target = _norm(name)
    by_full = {}
    for p in players:
        full = _norm(f"{p.first_name} {p.last_name}")
        by_full[NAME_ALIASES.get(full, full)] = p
        by_full.setdefault(full, p)
    if target in by_full:
        return by_full[target]
    parts = target.split()
    if len(parts) < 2:
        return None
    last = parts[-1] if parts[-1] not in ("ii", "iii", "iv", "jr") else parts[-2]
    cands = [p for p in players if _norm(p.last_name) == last and _norm(p.first_name)[:1] == parts[0][:1]]
    return cands[0] if len(cands) == 1 else None


def parse_csv_row(rec):
    """CSV dict -> (side, year, school, level, {column: value}, source_url)."""
    vals = {}
    for k, col in CSV_TO_COL.items():
        raw = (rec.get(k) or "").strip()
        vals[col] = int(raw) if raw != "" else None
    vals["ip_outs"] = ip_to_outs(rec.get("IP"))
    side = rec["side"].strip().lower()
    if side not in ("batting", "pitching"):
        raise ValueError(f"side must be batting or pitching: {side}")
    return side, int(rec["year"]), rec["school"].strip(), (rec.get("level") or "").strip() or None, vals, (rec.get("source_url") or "").strip() or None


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))
