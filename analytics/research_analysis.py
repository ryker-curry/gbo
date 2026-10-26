"""
GBO -- Research project analysis: strength & conditioning tests vs fastball
velocity and spin in our pitchers (Oct 2026, Ryker approved).

VARIABLES (Oct 2026 rebuild, Ryker: "all of this goes with research
project"): every column of the testing workbook (study_workbook_spec.py),
grouped by its tab, plus a "Calculated by GBO" group --
  - shoulder ER:IR and hip AD:AB ratios (max and average force),
  - asymmetries, (throw - glove) or (drive - plant) / the higher side x 100,
    the same formula for every bilateral test,
  - Dynamic Strength Index = CMJ concentric peak force / IMTP peak force.
Side-specific tests are read per pitcher from his throwing hand (throw /
glove, drive / plant), so "Shoulder: Throw External Rotation" is the right
shoulder for a RHP and the left for a LHP.

  dataset()        one record per active pitcher: his LATEST value on every
                   variable this season, his fastball outcomes, and any
                   import notes (why a value is missing)
  checklist()      what's collected / missing per pitcher and group
  correlations()   every variable vs one outcome: n, Pearson r, 95% CI
                   (Fisher z), p (two-sided t test), Spearman rho, plus
                   Bonferroni and Benjamini-Hochberg flags across variables
  to_csv()         the dataset as one row per pitcher (SPSS / R / Excel)

OUTCOMES -- from the study's own numbers (models.ResearchFBOutcome, the
workbook's FB VELO&SPIN tab: games only, spin confidence 0.8+) when they
exist, otherwise GBO's Rapsodo readings this season:
  avg_velo, peak_velo, avg_spin, peak_spin, bauer (avg spin / avg velo).

RELATIVE: force / power / impulse / strength variables can be divided by
body weight (per lb).

Pure Python statistics (no scipy on the server): the t distribution's
p-value comes from the regularized incomplete beta function.
"""

import csv
import io
import math
from collections import defaultdict
from statistics import mean

import bucket_system as bs
import study_workbook_spec as wspec
from analytics.research_progress import FASTBALLS

OUTCOMES = {"avg_velo": ("Average FB velo", "mph"), "peak_velo": ("Peak FB velo", "mph"),
            "avg_spin": ("Average FB spin", "rpm"), "peak_spin": ("Peak FB spin", "rpm"),
            "bauer": ("Bauer units (spin / velo)", "")}
MIN_N = 5
MIN_FB = 5
CALC_GROUP = "Calculated by GBO"
RELATIVE_UNITS = {"N", "W", "N s", "Ns", "lbs", "N/s"}


def _label(template):
    """Research label for a test-name template: sides as Throw / Glove /
    Drive / Plant instead of Right / Left."""
    if template is None or "{" not in template:
        return template
    return template.replace("{T}", "Throw").replace("{G}", "Glove").replace("{D}", "Drive").replace("{P}", "Plant")


def _build_vars():
    """[(group, [labels])] and {label: {"group", "unit", "template", "kind"}} from the workbook spec."""
    info, groups = {}, []
    for tab, t in wspec.TABS.items():
        if t.get("fb"):
            continue
        labels = []
        for c in t["cols"]:
            if c.kind == "height_cm":
                lab = "Height"
                info[lab] = {"group": t["group"], "unit": "in", "template": None, "kind": "height"}
            elif c.kind == "value":
                if "{R}" in (c.test or "") or "{L}" in (c.test or ""):
                    side = "Drive" if "{R}" in c.test else "Plant"
                    tmpl = c.test.replace("{R}", side).replace("{L}", side)
                    lab = tmpl
                else:
                    tmpl, lab = c.test, _label(c.test)
                info[lab] = {"group": t["group"], "unit": c.unit, "template": tmpl, "kind": "test"}
            else:
                continue
            if lab not in labels:
                labels.append(lab)
        groups.append((t["group"], labels))
    calc = []
    for lab, unit in DERIVED:
        info[lab] = {"group": CALC_GROUP, "unit": unit, "template": None, "kind": "derived"}
        calc.append(lab)
    groups.append((CALC_GROUP, calc))
    return groups, info


def _asym(a, b):
    if a is None or b is None or max(abs(a), abs(b)) == 0:
        return None
    return (a - b) / max(abs(a), abs(b)) * 100


def _ratio(a, b):
    return a / b if a is not None and b else None


_SH = ("Shoulder Strength: Throwing Arm {m} Peak Force", "Shoulder Strength: Non-Throwing Arm {m} Peak Force")
DERIVED_FNS = [
    ("Shoulder ER:IR ratio, max force (Throw)", "ratio", lambda v: _ratio(v.get(_SH[0].format(m="ER")), v.get(_SH[0].format(m="IR")))),
    ("Shoulder ER:IR ratio, max force (Glove)", "ratio", lambda v: _ratio(v.get(_SH[1].format(m="ER")), v.get(_SH[1].format(m="IR")))),
    ("Shoulder ER:IR ratio, avg force (Throw)", "ratio", lambda v: _ratio(v.get("Shoulder ER Avg Force (Throwing Arm)"), v.get("Shoulder IR Avg Force (Throwing Arm)"))),
    ("Shoulder ER:IR ratio, avg force (Glove)", "ratio", lambda v: _ratio(v.get("Shoulder ER Avg Force (Non-Throwing Arm)"), v.get("Shoulder IR Avg Force (Non-Throwing Arm)"))),
    ("Hip AD:AB ratio, max force (Drive)", "ratio", lambda v: _ratio(v.get("Hip Adduction Force (Drive Leg)"), v.get("Hip Abduction Force (Drive Leg)"))),
    ("Hip AD:AB ratio, max force (Plant)", "ratio", lambda v: _ratio(v.get("Hip Adduction Force (Plant Leg)"), v.get("Hip Abduction Force (Plant Leg)"))),
    ("Hip AD:AB ratio, avg force (Drive)", "ratio", lambda v: _ratio(v.get("Hip Adduction Avg Force (Drive Leg)"), v.get("Hip Abduction Avg Force (Drive Leg)"))),
    ("Hip AD:AB ratio, avg force (Plant)", "ratio", lambda v: _ratio(v.get("Hip Adduction Avg Force (Plant Leg)"), v.get("Hip Abduction Avg Force (Plant Leg)"))),
    ("Shoulder ER max force asymmetry (throw vs glove)", "%", lambda v: _asym(v.get(_SH[0].format(m="ER")), v.get(_SH[1].format(m="ER")))),
    ("Shoulder IR max force asymmetry (throw vs glove)", "%", lambda v: _asym(v.get(_SH[0].format(m="IR")), v.get(_SH[1].format(m="IR")))),
    ("Shoulder ER avg force asymmetry (throw vs glove)", "%", lambda v: _asym(v.get("Shoulder ER Avg Force (Throwing Arm)"), v.get("Shoulder ER Avg Force (Non-Throwing Arm)"))),
    ("Shoulder IR avg force asymmetry (throw vs glove)", "%", lambda v: _asym(v.get("Shoulder IR Avg Force (Throwing Arm)"), v.get("Shoulder IR Avg Force (Non-Throwing Arm)"))),
    ("Hip ABD max force asymmetry (drive vs plant)", "%", lambda v: _asym(v.get("Hip Abduction Force (Drive Leg)"), v.get("Hip Abduction Force (Plant Leg)"))),
    ("Hip ADD max force asymmetry (drive vs plant)", "%", lambda v: _asym(v.get("Hip Adduction Force (Drive Leg)"), v.get("Hip Adduction Force (Plant Leg)"))),
    ("Hip ABD avg force asymmetry (drive vs plant)", "%", lambda v: _asym(v.get("Hip Abduction Avg Force (Drive Leg)"), v.get("Hip Abduction Avg Force (Plant Leg)"))),
    ("Hip ADD avg force asymmetry (drive vs plant)", "%", lambda v: _asym(v.get("Hip Adduction Avg Force (Drive Leg)"), v.get("Hip Adduction Avg Force (Plant Leg)"))),
    ("IMTP net peak force asymmetry (drive vs plant)", "%", lambda v: _asym(v.get("IMTP Net Peak Vertical Force (Drive Leg)"), v.get("IMTP Net Peak Vertical Force (Plant Leg)"))),
] + [
    (f"Single-leg jump {name.lower()} asymmetry (drive vs plant)", "%",
     (lambda nm: lambda v: _asym(v.get(f"Single-Leg Jump {nm} (Drive Leg)"), v.get(f"Single-Leg Jump {nm} (Plant Leg)")))(name))
    for _h, name, _u, _c in wspec._SL
] + [
    ("Dynamic Strength Index (CMJ peak force / IMTP peak force)", "ratio",
     lambda v: _ratio(v.get("CMJ Concentric Peak Force"), v.get("Isometric Mid-Thigh Pull Peak Vertical Force"))),
]
DERIVED = [(lab, unit) for lab, unit, _f in DERIVED_FNS]
BATTERY, VAR_INFO = _build_vars()
CATEGORY_OF = {lab: g for g, labs in BATTERY for lab in labs}
TESTS = [lab for _g, labs in BATTERY for lab in labs]


def relative_ok(var):
    i = VAR_INFO.get(var) or {}
    return i.get("kind") == "test" and i.get("unit") in RELATIVE_UNITS and "Bodyweight" not in var


def _needed_test_names():
    names = {"Body Weight"}
    for i in VAR_INFO.values():
        if i["template"]:
            for hand in ("R", "L"):
                n = wspec.resolve_test(i["template"], hand)
                if n:
                    names.add(n)
    from analytics import inflection
    names |= {n for n, _u, _s, src in inflection.METRICS if src == "test"}
    return sorted(names)


def _vals(rec):
    """Research values for one record: rec["vars"] (dataset()) or, for
    hand-built records, rec["tests"] keyed directly by variable."""
    return rec.get("vars") if rec.get("vars") is not None else rec["tests"]


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _season_label_for(day):
    for label, start, end in bs.list_seasons():
        if start is not None and day >= start and (end is None or day < end):
            return label
    return bs.current_season_label()


def dataset(db):
    """{pid: {"player", "tests": {gbo test: (value, date, unit)}, "vars": {variable: (value, date, unit)},
    "fb": {...}, "notes": [str]}} for active pitchers, this season."""
    from models import (Assessment, AssessmentResult, AssessmentTestType, Player, PitchType, RapsodoPitch,
                        ResearchFBOutcome)
    label = bs.current_season_label()
    start, end = bs.season_date_range(label)
    players = {p.player_id: p for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all()}
    out = {pid: {"player": p, "tests": {}, "vars": {}, "fb": {}, "notes": []} for pid, p in players.items()}
    if not players:
        return out
    q = (db.query(AssessmentTestType.test_name, AssessmentTestType.unit, Assessment.player_id, Assessment.assessment_date,
                  AssessmentResult.value)
         .join(AssessmentResult, AssessmentResult.test_type_id == AssessmentTestType.test_type_id)
         .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
         .filter(AssessmentTestType.test_name.in_(_needed_test_names()), AssessmentResult.value.isnot(None),
                 Assessment.player_id.in_(list(players))))
    nq = db.query(Assessment.player_id, Assessment.notes).filter(Assessment.player_id.in_(list(players)),
                                                                 Assessment.notes.isnot(None))
    if start is not None:
        q = q.filter(Assessment.assessment_date >= start)
        nq = nq.filter(Assessment.assessment_date >= start)
    if end is not None:
        q = q.filter(Assessment.assessment_date < end)
        nq = nq.filter(Assessment.assessment_date < end)
    for name, unit, pid, day, val in q.all():
        cur = out[pid]["tests"].get(name)
        if cur is None or day > cur[1]:
            out[pid]["tests"][name] = (float(val), day, unit or "")
    for pid, note in nq.all():
        for line in str(note).splitlines():
            if line.strip() and line.strip() not in out[pid]["notes"]:
                out[pid]["notes"].append(line.strip())

    # research variables, per pitcher's throwing hand
    for pid, rec in out.items():
        hand = rec["player"].throws
        for lab, i in VAR_INFO.items():
            if i["kind"] == "test":
                t = rec["tests"].get(wspec.resolve_test(i["template"], hand) or "")
                if t is not None:
                    rec["vars"][lab] = (t[0], t[1], i["unit"] or t[2])
            elif i["kind"] == "height" and rec["player"].height_in:
                rec["vars"][lab] = (float(rec["player"].height_in), None, "in")
        plain = {k: v[0] for k, v in rec["vars"].items()}
        for lab, unit, fn in DERIVED_FNS:
            try:
                v = fn(plain)
            except Exception:
                v = None
            if v is not None:
                rec["vars"][lab] = (v, None, unit)

    # fastball outcomes: the study's own numbers first, else Rapsodo
    study = {}
    try:
        for r in (db.query(ResearchFBOutcome).filter(ResearchFBOutcome.player_id.in_(list(players)),
                                                     ResearchFBOutcome.season_label == label).all()):
            study[r.player_id] = r
    except Exception:
        db.rollback()
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

    def _p90(xs):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(round(0.9 * (len(xs) - 1))))]

    for pid, rec in out.items():
        r = study.get(pid)
        if r is not None and (r.avg_velo is not None or r.avg_spin is not None):
            f = lambda x: float(x) if x is not None else None  # noqa: E731
            n = r.n_pitches
            fb = {"source": "study", "n_velo": n, "n_spin": n, "avg_velo": f(r.avg_velo), "peak_velo": f(r.peak_velo),
                  "avg_spin": f(r.avg_spin), "peak_spin": f(r.peak_spin), "note": r.note}
        else:
            vs, ss = velos.get(pid, []), spins.get(pid, [])
            fb = {"source": "rapsodo", "n_velo": len(vs), "n_spin": len(ss), "avg_velo": None, "peak_velo": None,
                  "avg_spin": None, "peak_spin": None, "note": None}
            if len(vs) >= MIN_FB:
                fb["avg_velo"], fb["peak_velo"] = mean(vs), _p90(vs)
            if len(ss) >= MIN_FB:
                fb["avg_spin"], fb["peak_spin"] = mean(ss), _p90(ss)
        fb["bauer"] = fb["avg_spin"] / fb["avg_velo"] if fb.get("avg_velo") and fb.get("avg_spin") else None
        rec["fb"] = fb
    return out


def checklist(ds):
    """[{player, cats: {group: {"done", "total", "missing", "last"}}, "fb", "fb_ok", "complete", "notes"}] by name.
    The calculated group isn't a collection item, so it's left out."""
    rows = []
    for rec in ds.values():
        vals = _vals(rec)
        cats = {}
        for cat, labs in BATTERY:
            if cat == CALC_GROUP:
                continue
            done = [t for t in labs if t in vals]
            dates = [vals[t][1] for t in done if vals[t][1] is not None]
            cats[cat] = {"done": len(done), "total": len(labs), "missing": [t for t in labs if t not in vals],
                         "last": max(dates) if dates else None}
        fb_ok = rec["fb"].get("avg_velo") is not None and rec["fb"].get("avg_spin") is not None
        complete = fb_ok and all(c["done"] == c["total"] for c in cats.values())
        rows.append({"player": rec["player"], "cats": cats, "fb": rec["fb"], "fb_ok": fb_ok, "complete": complete,
                     "notes": rec.get("notes", [])})
    rows.sort(key=lambda r: ((r["player"].last_name or ""), (r["player"].first_name or "")))
    return rows


def category_completion(rows):
    """{group: % of (pitcher, variable) cells filled}, plus "Fastball data"."""
    out = {}
    for cat, labs in BATTERY:
        if cat == CALC_GROUP:
            continue
        tot = len(rows) * len(labs)
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
    """[(pid, x, y)] pitchers with both the variable and the outcome."""
    out = []
    for pid, rec in ds.items():
        if hand in ("R", "L") and rec["player"].throws != hand:
            continue
        t = _vals(rec).get(test)
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


def _direction(test, dirs):
    i = VAR_INFO.get(test) or {}
    if i.get("template"):
        return dirs.get(wspec.resolve_test(i["template"], "R")) or dirs.get(test)
    return dirs.get(test)


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
                     "direction": _direction(test, dirs), "relative": relative and relative_ok(test)})
    m = sum(1 for r in rows if r["p"] is not None)
    bh = bh_flags([r["p"] for r in rows])
    for i, r in enumerate(rows):
        r["bonf"] = r["p"] is not None and m > 0 and r["p"] <= 0.05 / m
        r["bh"] = i in bh
    return rows, m


def meaning(row, outcome):
    """Plain read: which way the variable goes with the outcome."""
    r = row["r"]
    if r is None:
        return "not enough pitchers yet"
    if abs(r) < 0.1:
        return "no real relationship"
    better = (r > 0) if row["direction"] != "lower" else (r < 0)
    word = "more" if outcome != "bauer" else "higher"
    what = {"avg_velo": "FB velo", "peak_velo": "peak FB velo", "avg_spin": "FB spin", "peak_spin": "peak FB spin",
            "bauer": "Bauer units"}[outcome]
    if row["direction"] is None:
        return f"{row['strength']}: {'higher' if r > 0 else 'lower'} value goes with {word if r > 0 else 'less'} {what}"
    return f"{row['strength']}: a better result goes with {word if better else 'less'} {what}"


def to_csv(ds):
    """One row per pitcher: every variable (GBO units), body weight, the
    fastball outcomes and where they came from."""
    extra = [] if "Body Weight" in TESTS else ["Body Weight"]
    fb_keys = ["source", "n_velo", "avg_velo", "peak_velo", "n_spin", "avg_spin", "peak_spin", "bauer"]
    cols = ["player_id", "name", "throws"] + TESTS + extra + [f"fb_{k}" for k in fb_keys] + ["notes"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for pid, rec in sorted(ds.items(), key=lambda kv: ((kv[1]["player"].last_name or ""), (kv[1]["player"].first_name or ""))):
        p = rec["player"]
        vals = _vals(rec)
        row = [pid, f"{p.first_name} {p.last_name}", p.throws or ""]
        for t in TESTS:
            v = vals.get(t)
            row.append("" if v is None else round(v[0], 4))
        for t in extra:
            v = rec["tests"].get(t)
            row.append("" if v is None else round(v[0], 4))
        fb = rec["fb"]
        for k in fb_keys:
            v = fb.get(k)
            row.append("" if v is None else (round(v, 3) if isinstance(v, float) else v))
        row.append(" | ".join(rec.get("notes") or []))
        w.writerow(row)
    return buf.getvalue()
