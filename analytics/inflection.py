"""
GBO -- Inflection points: body comp vs fastball velo (Oct 2026, Ryker:
"see if there is a certain point at which this is the weight guys need to
get to to throw hard"). Research Project page, staff only, uncommitted
with the rest of the research tools until data collection is done.

For each body comp measure (plus SMM % and two per-inch-of-height
versions, the height check):

BREAKPOINT MODEL (hockey stick / segmented regression)
  y = a + b*x + c*max(0, x - k): one line that can bend once, at k. k is
  searched over a grid between the MIN_SIDE-th lowest and highest values
  (so each side has real pitchers). Slope before = b, after = b + c.
  Three honesty checks:
    vs line    does the bend beat a straight line? Residual-permutation
               test: shuffle the straight line's residuals back onto it
               (data that IS a straight line, same noise) and redo the
               whole search -- p = how often fake straight-line data shows
               a bend at least this much better.
    vs chance  does the best bent fit beat random data? Shuffle velos
               across pitchers and redo the whole search -- p = how often
               a random pairing fits as well. Catches "try every cutoff,
               one always looks good".
    range      bootstrap (resample pitchers with replacement, refit) ->
               middle 95% of the cutoffs = how sure the cutoff is.

VELO LINE (coach version)
  Pick a line (e.g. 85 mph). Find the cutoff that best splits pitchers at
  or above it from those below (Youden's J = hit rate above + miss rate
  below - 1), either direction. Counts on each side, plus a shuffle p for
  the same reason as above.

numpy, vectorized: every candidate cutoff x every shuffle at once.
"""

import numpy as np

MIN_N = 12
MIN_SIDE = 4
GRID = 40
N_PERM = 999
N_BOOT = 400
SEED = 2026

# (name, unit, step for the slope read, source)
METRICS = [
    ("Body Weight", "lb", 10, "test"),
    ("Skeletal Muscle Mass", "lb", 5, "test"),
    ("Skeletal Muscle Mass %", "% of body weight", 1, "smm_pct"),
    ("Body Fat Mass", "lb", 5, "test"),
    ("Percent Body Fat", "%", 1, "test"),
    ("Body Weight per inch of height", "lb/in", 0.1, "bw_in"),
    ("Skeletal Muscle Mass per inch of height", "lb/in", 0.1, "smm_in"),
]
HEIGHT_CHECK = {"Body Weight per inch of height", "Skeletal Muscle Mass per inch of height"}
DEFAULT_LINE = {"avg_velo": 85.0, "peak_velo": 87.0, "avg_spin": 2200.0, "bauer": 25.0}


def metric_value(rec, source, name):
    t = rec["tests"]
    bw = t.get("Body Weight", (None,))[0]
    smm = t.get("Skeletal Muscle Mass", (None,))[0]
    h = getattr(rec["player"], "height_in", None)
    h = float(h) if h else None
    if source == "test":
        v = t.get(name)
        return v[0] if v else None
    if source == "smm_pct":
        return 100.0 * smm / bw if smm and bw else None
    if source == "bw_in":
        return bw / h if bw and h else None
    if source == "smm_in":
        return smm / h if smm and h else None
    return None


def pairs(ds, metric, outcome, hand="all"):
    src = next(s for n, _u, _st, s in METRICS if n == metric)
    out = []
    for pid, rec in ds.items():
        if hand in ("R", "L") and rec["player"].throws != hand:
            continue
        x, y = metric_value(rec, src, metric), rec["fb"].get(outcome)
        if x is not None and y is not None:
            out.append((pid, float(x), float(y)))
    return out


# ---------------------------------------------------------------------------
# Model fitting (vectorized)
# ---------------------------------------------------------------------------

def _grid(xs):
    s = np.sort(xs)
    lo, hi = s[MIN_SIDE - 1], s[len(s) - MIN_SIDE]
    if hi <= lo:
        return None
    return np.linspace(lo, hi, GRID)


def _sse_line(x, Y):
    """x (n,), Y (n, m) -> SSE (m,) of the straight-line fit per column."""
    xc = x - x.mean()
    sxx = (xc * xc).sum()
    Yc = Y - Y.mean(axis=0)
    if sxx == 0:
        return (Yc * Yc).sum(axis=0)
    b = xc @ Yc / sxx
    r = Yc - np.outer(xc, b)
    return (r * r).sum(axis=0)


def _sse_hinge(x, Y, ks):
    """x (n,), Y (n, m), ks (K,) -> SSE (K, m) and betas (K, 3, m).
    Candidates without MIN_SIDE points on each side get SSE = inf."""
    n = len(x)
    X = np.stack([np.ones((len(ks), n)), np.broadcast_to(x, (len(ks), n)),
                  np.maximum(0.0, x[None, :] - ks[:, None])], axis=2)          # (K, n, 3)
    XtX = np.einsum("kni,knj->kij", X, X) + 1e-9 * np.eye(3)
    XtY = np.einsum("kni,nm->kim", X, Y)
    beta = np.linalg.solve(XtX, XtY)                                            # (K, 3, m)
    fit = np.einsum("kni,kim->knm", X, beta)
    sse = ((Y[None, :, :] - fit) ** 2).sum(axis=1)                              # (K, m)
    below = (x[None, :] < ks[:, None]).sum(axis=1)
    bad = (below < MIN_SIDE) | (n - below < MIN_SIDE)
    sse[bad, :] = np.inf
    return sse, beta


def _best(x, Y, ks):
    sse, beta = _sse_hinge(x, Y, ks)
    i = np.argmin(sse, axis=0)
    m = np.arange(Y.shape[1])
    return sse[i, m], ks[i], beta[i, :, m]          # (m,), (m,), (m, 3)


def breakpoint_fit(xs, ys, seed=SEED):
    """-> dict or None when there aren't enough pitchers."""
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    n = len(x)
    if n < MIN_N or len(np.unique(x)) < 2 * MIN_SIDE:
        return None
    ks = _grid(x)
    if ks is None:
        return None
    rng = np.random.default_rng(seed)
    Y = y[:, None]
    sse_bp, k, beta = _best(x, Y, ks)
    sse_bp, k, beta = float(sse_bp[0]), float(k[0]), beta[0]
    sse_ln = float(_sse_line(x, Y)[0])
    sst = float(((y - y.mean()) ** 2).sum())
    if sst == 0:
        return None
    gain = (sse_ln - sse_bp) / sse_bp if sse_bp > 0 else 0.0

    # vs line: straight-line data with these residuals, full search each time
    xc = x - x.mean()
    b_ln = (xc @ (y - y.mean())) / (xc @ xc)
    yhat = y.mean() + b_ln * xc
    res = y - yhat
    Yl = yhat[:, None] + np.stack([rng.permutation(res) for _ in range(N_PERM)], axis=1)
    s_bp, _k, _b = _best(x, Yl, ks)
    s_ln = _sse_line(x, Yl)
    g = (s_ln - s_bp) / np.where(s_bp > 0, s_bp, np.inf)
    p_line = (1 + int((g >= gain - 1e-12).sum())) / (N_PERM + 1)

    # vs chance: shuffle velos across pitchers
    Ys = np.stack([rng.permutation(y) for _ in range(N_PERM)], axis=1)
    s_bp2, _k2, _b2 = _best(x, Ys, ks)
    p_chance = (1 + int((s_bp2 <= sse_bp + 1e-12).sum())) / (N_PERM + 1)

    # bootstrap range for the cutoff
    idx = rng.integers(0, n, size=(N_BOOT, n))
    kb = []
    for row in idx:
        xb, yb = x[row], y[row]
        if len(np.unique(xb)) < 2 * MIN_SIDE:
            continue
        sb, kk, _bb = _best(xb, yb[:, None], ks)
        if np.isfinite(sb[0]):
            kb.append(float(kk[0]))
    lo, hi = (float(np.percentile(kb, 2.5)), float(np.percentile(kb, 97.5))) if len(kb) >= 50 else (None, None)

    return {"n": n, "k": k, "lo": lo, "hi": hi, "a": float(beta[0]), "b1": float(beta[1]),
            "b2": float(beta[1] + beta[2]), "slope_line": float(b_ln), "r2_line": 1 - sse_ln / sst,
            "r2_bp": 1 - sse_bp / sst, "p_line": p_line, "p_chance": p_chance, "x_min": float(x.min()),
            "n_below": int((x < k).sum()), "n_above": int((x >= k).sum()),
            "x_max": float(x.max())}


OUTCOME_WORD = {"avg_velo": "velo", "peak_velo": "peak velo", "avg_spin": "spin", "bauer": "Bauer units"}


def _dir(slope, flat):
    """'up' / 'down' / 'flat' for one side of the bend. flat = the slope size
    that counts as level (a third of the steeper side)."""
    if abs(slope) <= flat:
        return "flat"
    return "up" if slope > 0 else "down"


_SHAPE = {   # (before, after) -> (code, words)
    ("up", "flat"): ("plateau", "rises, then levels off past the cutoff"),
    ("up", "down"): ("bend", "rises to the cutoff, then drops"),
    ("up", "up"): ("bend", "climbs the whole way, at a different rate past the cutoff"),
    ("flat", "up"): ("takeoff", "flat below the cutoff, then climbs"),
    ("flat", "down"): ("bend", "flat below the cutoff, then drops"),
    ("down", "flat"): ("plateau", "drops, then levels off past the cutoff"),
    ("down", "up"): ("bend", "drops to the cutoff, then climbs"),
    ("down", "down"): ("bend", "drops the whole way, at a different rate past the cutoff"),
    ("flat", "flat"): ("bend", "bends at the cutoff"),
}


def pattern(fit, alpha=0.05, outcome="avg_velo"):
    """Plain read of a fit: (code, words). Shape comes from the slope on each
    side of the cutoff -- a side is "flat" when its slope is under a third of
    the steeper side's, so a V (down then up) reads as down-then-up, not as
    flat-then-climbs."""
    what = OUTCOME_WORD.get(outcome, "velo")
    if fit is None:
        return "thin", "not enough pitchers yet"
    if fit["p_chance"] > alpha:
        return "none", "no clear pattern -- random pairings fit about as well"
    if fit["p_line"] > alpha:
        return "line", (f"steady: more goes with more {what}, no clear bend" if fit["slope_line"] > 0 else
                        f"steady: more goes with less {what}, no clear bend")
    b1, b2 = fit["b1"], fit["b2"]
    flat = max(abs(b1), abs(b2)) / 3
    return _SHAPE[(_dir(b1, flat), _dir(b2, flat))]


# ---------------------------------------------------------------------------
# Velo line (coach version)
# ---------------------------------------------------------------------------

def _best_split(x, F):
    """x (n,), F (n, m) booleans -> (J (m,), t (m,), higher (m,) bool)."""
    s = np.unique(x)
    if len(s) < 2:
        return None
    ts = (s[:-1] + s[1:]) / 2                                       # (T,)
    above = x[None, :] >= ts[:, None]                               # (T, n)
    nf = F.sum(axis=0).astype(float)                                # (m,)
    ns = (~F).sum(axis=0).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sens = above.astype(float) @ F.astype(float) / nf           # (T, m) share of fast above
        fpr = above.astype(float) @ (~F).astype(float) / ns         # share of slow above
    J = sens - fpr                                                  # >0: higher x = faster
    Jabs = np.nan_to_num(np.abs(J), nan=-1.0)
    i = np.argmax(Jabs, axis=0)
    m = np.arange(F.shape[1])
    return Jabs[i, m], ts[i], J[i, m] > 0


def velo_line_split(xs, ys, line, seed=SEED):
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    if len(x) < MIN_N:
        return None
    fast = y >= line
    if fast.all() or not fast.any():
        return {"n": len(x), "line": line, "degenerate": True, "n_fast": int(fast.sum())}
    res = _best_split(x, fast[:, None])
    if res is None:
        return None
    J, t, higher = float(res[0][0]), float(res[1][0]), bool(res[2][0])
    rng = np.random.default_rng(seed)
    Fs = np.stack([rng.permutation(fast) for _ in range(N_PERM)], axis=1)
    Jp = _best_split(x, Fs)[0]
    p = (1 + int((Jp >= J - 1e-12).sum())) / (N_PERM + 1)
    side = x >= t if higher else x < t
    return {"n": len(x), "line": line, "degenerate": False, "cutoff": t, "higher": higher, "J": J, "p": p,
            "in_fast": int((side & fast).sum()), "in_n": int(side.sum()),
            "out_fast": int((~side & fast).sum()), "out_n": int((~side).sum())}


def run(ds, outcome, hand="all", line=None, split=True):
    """[{metric, unit, step, height, n, fit, read, split}] in METRICS order.
    split=False skips the velo-line split (row["split"] = None) -- the page
    caches the slow breakpoint fits and adds splits with add_splits(), so
    typing a new line doesn't redo every shuffle / bootstrap."""
    rows = []
    for name, unit, step, _src in METRICS:
        pr = pairs(ds, name, outcome, hand)
        xs, ys = [x for _p, x, _y in pr], [y for _p, _x, y in pr]
        fit = breakpoint_fit(xs, ys) if len(pr) >= MIN_N else None
        code, words = pattern(fit, outcome=outcome)
        if fit is None and len(pr) >= MIN_N:
            # enough pitchers, but too few distinct values to place a cutoff
            code, words = "thin", "too little spread in this measure to look for a cutoff"
        rows.append({"metric": name, "unit": unit, "step": step, "height": name in HEIGHT_CHECK, "n": len(pr),
                     "fit": fit, "code": code, "read": words, "split": None})
    return add_splits(rows, ds, outcome, hand, line) if split else rows


def add_splits(rows, ds, outcome, hand="all", line=None):
    """Copy of run() rows with the velo-line split filled in for `line`."""
    line = DEFAULT_LINE.get(outcome, 85.0) if line is None else line
    out = []
    for r in rows:
        pr = pairs(ds, r["metric"], outcome, hand)
        xs, ys = [x for _p, x, _y in pr], [y for _p, _x, y in pr]
        out.append({**r, "split": velo_line_split(xs, ys, line) if len(pr) >= MIN_N else None})
    return out
