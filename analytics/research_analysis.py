"""
GBO -- Research project analysis (Oct 2026, Ryker approved): strength &
conditioning tests vs fastball velocity and spin in our pitchers.

Staff-only tools on the Research Project page (the guest demo keeps the
counts-only page from research_progress.py):

  dataset()        one record per active pitcher: his LATEST result on
                   every battery test this season, plus his fastball
                   numbers this season (Ryker's pairing call: season to
                   season)
  checklist()      what's collected / missing per pitcher and category
  correlations()   every test vs one outcome: n, Pearson r, 95% CI
                   (Fisher z), p (two-sided t test), Spearman rho, plus
                   Bonferroni and Benjamini-Hochberg flags across tests
  to_csv()         the dataset as one row per pitcher (SPSS / R / Excel)

OUTCOMES (Ryker picked all four) -- fastballs = 4-seam, 2-seam, "Fastball":
  avg_velo   mean velocity of his Rapsodo fastball readings
  peak_velo  90th percentile of those (top-end velo)
  avg_spin   mean total spin
  bauer      avg spin / avg velo (Bauer units -- spin independent of velo)

RELATIVE: strength tests (Lower / Upper Body Strength) and any force or
impulse measure can be divided by body weight (per lb) -- relative
strength often tracks velo better than raw numbers.

Pure Python statistics (no scipy on the server): the t distribution's
p-value comes from the regularized incomplete beta function.
"""

import csv
import io
import math
from collections import defaultdict
from statistics import mean

import bucket_system as bs
from analytics.research_progress import BATTERY, FASTBALLS

OUTCOMES = {"avg_velo": ("Average FB velo", "mph"), "peak_velo": ("Peak FB velo (90th pct)", "mph"),
            "avg_spin": ("Average FB spin", "rpm"), "bauer": ("Bauer units (spin / velo)", "")}
MIN_N = 5
MIN_FB = 5
CATEGORY_OF = {t: c for c, tests in BATTERY for t in tests}
TESTS = [t for _c, tests in BATTERY for t in tests]


def relative_ok(test):
    c = CATEGORY_OF.get(test, "")
    return c in ("Lower Body Strength", "Upper Body Strength") or "Force" in test or "Impulse" in test


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def dataset(db):
    """{pid: {"player", "tests": {name: (value, date, unit)}, "fb": {...}}} for active pitchers."""
    from models import Assessment, AssessmentResult, AssessmentTestType, Player, PitchType, RapsodoPitch
    start, end = bs.season_date_range(bs.current_season_label())
    players = {p.player_id: p for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all()}
    out = {pid: {"player": p, "tests": {}, "fb": {}} for pid, p in players.items()}
    if not players:
        return out
    q = (db.query(AssessmentTestType.test_name, AssessmentTestType.unit, Assessment.player_id, Assessment.assessment_date,
                  AssessmentResult.value)
         .join(AssessmentResult, AssessmentResult.test_type_id == AssessmentTestType.test_type_id)
         .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
         .filter(AssessmentTestType.test_name.in_(TESTS + ["Body Weight"]), AssessmentResult.value.isnot(None),
                 Assessment.player_id.in_(list(players))))
    if start is not None:
        q = q.filter(Assessment.assessment_date >= start)
    if end is not None:
        q = q.filter(Assessment.assessment_date < end)
    for name, unit, pid, day, val in q.all():
        cur = out[pid]["tests"].get(name)
        if cur is None or day > cur[1]:
            out[pid]["tests"][name] = (float(val), day, unit or "")
    rq = (db.query(RapsodoPitch.player_id, RapsodoPitch.velocity, RapsodoPitch.total_spin)
          .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id)
          .filter(PitchType.type_name.in_(FASTBALLS), RapsodoPitch.player_id.in_(list(players))))
    if start is not None:
        rq = rq.filter(RapsodoPitch.pitch_date >= start)
    if end is not None:
        rq = rq.filter(RapsodoPitch.pitch_date < end)
    velos, spins = defaultdict(list), defaultdict(list)
    for pid, v, sp in rq.all():
        if v is not None:
            velos[pid].append(float(v))
        if sp is not None:
            spins[pid].append(float(sp))
    for pid, rec in out.items():
        vs, ss = sorted(velos.get(pid, [])), spins.get(pid, [])
        fb = {"n_velo": len(vs), "n_spin": len(ss), "avg_velo": None, "peak_velo": None, "avg_spin": None, "bauer": None}
        if len(vs) >= MIN_FB:
            fb["avg_velo"] = mean(vs)
            fb["peak_velo"] = vs[min(len(vs) - 1, int(round(0.9 * (len(vs) - 1))))]
        if len(ss) >= MIN_FB:
            fb["avg_spin"] = mean(ss)
        if fb["avg_velo"] and fb["avg_spin"]:
            fb["bauer"] = fb["avg_spin"] / fb["avg_velo"]
        rec["fb"] = fb
    return out


def checklist(ds):
    """[{player, cats: {cat: {"done", "total", "missing", "last"}}, "fb": {...}, "complete"}] by name."""
    rows = []
    for rec in ds.values():
        cats = {}
        for cat, tests in BATTERY:
            done = [t for t in tests if t in rec["tests"]]
            dates = [rec["tests"][t][1] for t in done]
            cats[cat] = {"done": len(done), "total": len(tests), "missing": [t for t in tests if t not in rec["tests"]],
                         "last": max(dates) if dates else None}
        fb_ok = rec["fb"].get("avg_velo") is not None and rec["fb"].get("avg_spin") is not None
        complete = fb_ok and all(c["done"] == c["total"] for c in cats.values())
        rows.append({"player": rec["player"], "cats": cats, "fb": rec["fb"], "fb_ok": fb_ok, "complete": complete})
    rows.sort(key=lambda r: (r["player"].last_name, r["player"].first_name))
    return rows


def category_completion(rows):
    """{cat: % of (pitcher, test) cells filled}, plus "Fastball data"."""
    out = {}
    for cat, tests in BATTERY:
        tot = len(rows) * len(tests)
        out[cat] = 100.0 * sum(r["cats"][cat]["done"] for r in rows) / tot if tot else 0.0
    out["Fastball data"] = 100.0 * sum(1 for r in rows if r["fb_ok"]) / len(rows) if rows else 0.0
    return out


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _ranks(vals):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(xs, ys):
    return pearson(_ranks(xs), _ranks(ys))


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (Numerical Recipes)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
    h = d
    for m in range(1, 200):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > 1e-30 else 1e-30)
        c = 1.0 + aa / c
        c = c if abs(c) > 1e-30 else 1e-30
        de = d * c
        h *= de
        if abs(de - 1.0) < 3e-12:
            break
    return h


def betainc(a, b, x):
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbeta) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbeta) * _betacf(b, a, 1 - x) / b


def p_value(r, n):
    """Two-sided p for Pearson r with n pairs (t test, df = n - 2)."""
    if r is None or n < 3:
        return None
    if abs(r) >= 1:
        return 0.0
    df = n - 2
    t = r * math.sqrt(df / (1 - r * r))
    return betainc(df / 2, 0.5, df / (df + t * t))


def fisher_ci(r, n, z=1.96):
    if r is None or n < 4 or abs(r) >= 1:
        return None, None
    f = math.atanh(r)
    se = 1 / math.sqrt(n - 3)
    return math.tanh(f - z * se), math.tanh(f + z * se)


def strength(r):
    if r is None:
        return "—"
    a = abs(r)
    return "negligible" if a < 0.1 else ("small" if a < 0.3 else ("moderate" if a < 0.5 else "large"))


def bh_flags(ps, q=0.05):
    """Benjamini-Hochberg: indices (into ps, Nones skipped) that pass at FDR q."""
    idx = sorted((p, i) for i, p in enumerate(ps) if p is not None)
    m = len(idx)
    passed = set()
    k_max = 0
    for k, (p, _i) in enumerate(idx, start=1):
        if p <= q * k / m:
            k_max = k
    for k, (_p, i) in enumerate(idx, start=1):
        if k <= k_max:
            passed.add(i)
    return passed


def pairs(ds, test, outcome, hand="all", relative=False):
    """[(pid, x, y)] pitchers with both the test and the outcome."""
    out = []
    for pid, rec in ds.items():
        if hand in ("R", "L") and rec["player"].throws != hand:
            continue
        t = rec["tests"].get(test)
        y = rec["fb"].get(outcome)
        if t is None or y is None:
            continue
        x = t[0]
        if relative and relative_ok(test):
            bw = rec["tests"].get("Body Weight")
            if not bw or not bw[0]:
                continue
            x = x / bw[0]
        out.append((pid, x, y))
    return out


def correlations(ds, outcome, hand="all", relative=False):
    """[{test, category, n, r, lo, hi, p, rho, strength, bonf, bh, direction}] in battery order."""
    from analytics.assessment_progress import direction_map
    dirs = direction_map()
    rows = []
    for test in TESTS:
        pr = pairs(ds, test, outcome, hand, relative)
        n = len(pr)
        xs, ys = [x for _p, x, _y in pr], [y for _p, _x, y in pr]
        r = pearson(xs, ys) if n >= MIN_N else None
        lo, hi = fisher_ci(r, n)
        rows.append({"test": test, "category": CATEGORY_OF[test], "n": n, "r": r, "lo": lo, "hi": hi,
                     "p": p_value(r, n) if r is not None else None,
                     "rho": spearman(xs, ys) if n >= MIN_N else None, "strength": strength(r),
                     "direction": dirs.get(test), "relative": relative and relative_ok(test)})
    m = sum(1 for r in rows if r["p"] is not None)
    bh = bh_flags([r["p"] for r in rows])
    for i, r in enumerate(rows):
        r["bonf"] = r["p"] is not None and m > 0 and r["p"] <= 0.05 / m
        r["bh"] = i in bh
    return rows, m


def meaning(row, outcome):
    """Plain read: which way the test goes with the outcome."""
    r = row["r"]
    if r is None:
        return "not enough pitchers yet"
    if abs(r) < 0.1:
        return "no real relationship"
    better = (r > 0) if row["direction"] != "lower" else (r < 0)
    word = "more" if outcome != "bauer" else "higher"
    what = {"avg_velo": "FB velo", "peak_velo": "peak FB velo", "avg_spin": "FB spin", "bauer": "Bauer units"}[outcome]
    if row["direction"] is None:
        return f"{row['strength']}: {'higher' if r > 0 else 'lower'} test value goes with {word if r > 0 else 'less'} {what}"
    return f"{row['strength']}: a better result goes with {word if better else 'less'} {what}"


def to_csv(ds):
    extra = [] if "Body Weight" in TESTS else ["Body Weight"]
    cols = ["player_id", "name", "throws"] + TESTS + extra + ["fb_n_velo", "fb_avg_velo", "fb_peak_velo",
                                                       "fb_n_spin", "fb_avg_spin", "fb_bauer"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for pid, rec in sorted(ds.items(), key=lambda kv: (kv[1]["player"].last_name, kv[1]["player"].first_name)):
        p = rec["player"]
        row = [pid, f"{p.first_name} {p.last_name}", p.throws or ""]
        for t in TESTS + extra:
            v = rec["tests"].get(t)
            row.append("" if v is None else round(v[0], 4))
        fb = rec["fb"]
        for k in ("n_velo", "avg_velo", "peak_velo", "n_spin", "avg_spin", "bauer"):
            v = fb.get(k)
            row.append("" if v is None else (round(v, 3) if isinstance(v, float) else v))
        w.writerow(row)
    return buf.getvalue()
