"""
GBO -- Count-by-count value and PA length (Oct 2026, hitting article batch).

COUNT BY COUNT (Smitty, "Want to Get Called Up From AAA? Start Winning
These Counts"): hitters who got called up separated themselves in 2-0,
3-1, 2-1 and 1-1, most of all on offspeed. For each of the 12 counts:
pitches seen, swing %, and run value per 100 pitches (GamePitch.run_value,
batting side, + = good for the hitter) on fastballs vs everything else,
next to the team's RV/100 in that count. KEY_COUNTS are highlighted.

PA LENGTH + EARLY WIN (SABR Tooth Tigers, "Seeing More Pitches Rarely
Improves Batter Performance"): D1 data says long PAs don't help -- K rate
jumps after pitch 3. Results grouped by how many pitches the PA took, and
an alternate quality-AB rate:
  Early win  the PA reached a hitter's count (more balls than strikes at
             any point) OR he put pitch 1 or 2 in play with barreled /
             solid contact.
"""

from collections import defaultdict

from analytics.hitter_insights import plate_appearances, family, HARD_CONTACT, COUNTS
from plate_discipline import SWING_OUTCOMES

KEY_COUNTS = ("2-0", "3-1", "2-1", "1-1")
LENGTHS = (("1-2 pitches", 1, 2), ("3-6 pitches", 3, 6), ("7+ pitches", 7, 99))
REACH = {"1B", "2B", "3B", "HR", "BB", "HBP"}
NOT_PA = {None, "No Result"}


def _count(p):
    if p.balls_before is None or p.strikes_before is None:
        return None
    return f"{p.balls_before}-{p.strikes_before}"


def _rv100(ps):
    rv = [float(p.run_value) for p in ps if p.run_value is not None]
    return 100.0 * sum(rv) / len(ps) if ps and rv else None


def count_table(pitches, team_pitches=()):
    by = defaultdict(list)
    for p in pitches:
        c = _count(p)
        if c:
            by[c].append(p)
    team_by = defaultdict(list)
    for p in team_pitches:
        c = _count(p)
        if c:
            team_by[c].append(p)
    rows = []
    for c in COUNTS:
        ps = by.get(c, [])
        fb = [p for p in ps if family(p) == "Fastball"]
        other = [p for p in ps if family(p) in ("Breaking", "Offspeed")]
        sw = [p for p in ps if p.pitch_outcome in SWING_OUTCOMES]
        rows.append({"count": c, "key": c in KEY_COUNTS, "n": len(ps),
                     "swing": 100.0 * len(sw) / len(ps) if ps else None,
                     "rv": _rv100(ps), "fb_rv": _rv100(fb), "fb_n": len(fb),
                     "other_rv": _rv100(other), "other_n": len(other),
                     "team_rv": _rv100(team_by.get(c, []))})
    return rows


def _done(pa):
    return pa[-1].ends_plate_appearance and pa[-1].ab_outcome not in NOT_PA


def early_win(pa):
    for p in pa:
        if (p.balls_before or 0) > (p.strikes_before or 0):
            return True
        n = p.pa_pitch_number or 0
        if p.pitch_outcome == "In Play" and n <= 2 and (p.contact_quality or "") in HARD_CONTACT:
            return True
    return False


def pa_length(pitches):
    """[{label, pas, onbase, k, rv_pa}] + {"early": pct, "early_n", "done"}"""
    pas = [pa for pa in plate_appearances(pitches) if _done(pa)]
    rows = []
    for label, lo, hi in LENGTHS:
        grp = [pa for pa in pas if lo <= len(pa) <= hi]
        n = len(grp)
        rv = [float(p.run_value) for pa in grp for p in pa if p.run_value is not None]
        rows.append({
            "label": label, "pas": n,
            "onbase": 100.0 * sum(1 for pa in grp if pa[-1].ab_outcome in REACH) / n if n else None,
            "k": 100.0 * sum(1 for pa in grp if (pa[-1].ab_outcome or "").startswith("K")) / n if n else None,
            "rv_pa": sum(rv) / n if n and rv else None,
        })
    wins = sum(1 for pa in pas if early_win(pa))
    return {"rows": rows, "early": 100.0 * wins / len(pas) if pas else None, "early_n": wins, "done": len(pas)}
