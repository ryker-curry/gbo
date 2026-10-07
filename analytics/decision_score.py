"""
GBO -- Decision Score (Oct 2026, from Liam Klein's BEAR series -- "Batter's
Eye Adjusted Rating"). One plate-discipline number per hitter, built from
stats GBO already charts (BEAR's swing-speed / blast inputs need bat
tracking, so they're left out):

  Swing Decision %   +      Decision RV/100   +
  Chase %            -      Zone Swing %      +
  Zone contact %     +      Whiff %           -
  BB%                +      K%                -

Each is z-scored across the hitters passed in (teammates with enough
PAs), signed so + is always good, averaged with equal weights (BEAR's
own weights were never published), and scaled 100 + 25 x z -- 100 = team
average, 25 = one SD (BEAR's scale). Inputs a hitter is missing drop out
of his average; he needs MIN_INPUTS of them.
"""

from statistics import mean, pstdev

COMPONENTS = [("Swing Decision %", 1), ("Decision RV/100", 1), ("Chase %", -1), ("Zone Swing %", 1),
              ("Zone contact %", 1), ("Whiff %", -1), ("BB%", 1), ("K%", -1)]
MIN_INPUTS = 5
MIN_HITTERS = 4


def scores(metrics_by_pid):
    """metrics_by_pid: {pid: core_metrics dict}. -> {pid: score}"""
    stats = {}
    for key, _sign in COMPONENTS:
        vals = [m.get(key) for m in metrics_by_pid.values() if m.get(key) is not None]
        if len(vals) >= MIN_HITTERS:
            sd = pstdev(vals)
            if sd > 0:
                stats[key] = (mean(vals), sd)
    out = {}
    for pid, m in metrics_by_pid.items():
        zs = [sign * (m[key] - stats[key][0]) / stats[key][1]
              for key, sign in COMPONENTS if key in stats and m.get(key) is not None]
        if len(zs) >= MIN_INPUTS:
            out[pid] = round(100 + 25 * mean(zs), 0)
    return out
