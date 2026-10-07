"""
GBO -- Bauer units (Oct 2026, Ryker approved): total spin / velocity
(rpm per mph). Spin climbs when a pitcher throws harder, so dividing by
velo isolates his natural spin ability -- fairly stable and hard to train.
Most telling on breaking balls (high Bauer units = a natural spinner);
on fastballs it says nothing about how much of the spin moves the ball
(spin efficiency / IVB over expected do that).

Per reading first (spin / velo), then averaged. TYPICAL band: within
+/- TYPICAL of the team average for that pitch type reads "typical".
"""

from collections import defaultdict

TYPICAL = 1.0
_cache = {"key": None, "avg": None}


def bu(p):
    if p.total_spin is None or p.velocity is None or float(p.velocity) <= 0:
        return None
    return float(p.total_spin) / float(p.velocity)


def avg(pitches):
    vals = [v for v in (bu(p) for p in pitches) if v is not None]
    return sum(vals) / len(vals) if vals else None


def team_by_type(db):
    """{pitch type: team average Bauer units}, cached until readings change."""
    from sqlalchemy import func
    from models import RapsodoPitch, PitchType
    key = (id(db.get_bind()), db.query(func.count(RapsodoPitch.rapsodo_pitch_id)).scalar(),
           db.query(func.max(RapsodoPitch.rapsodo_pitch_id)).scalar())
    if _cache["key"] == key and _cache["avg"] is not None:
        return _cache["avg"]
    sums = defaultdict(lambda: [0.0, 0])
    for name, spin, velo in (db.query(PitchType.type_name, RapsodoPitch.total_spin, RapsodoPitch.velocity)
                             .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id)
                             .filter(RapsodoPitch.total_spin.isnot(None), RapsodoPitch.velocity.isnot(None)).all()):
        if float(velo) > 0:
            sums[name][0] += float(spin) / float(velo)
            sums[name][1] += 1
    out = {k: s / n for k, (s, n) in sums.items() if n}
    _cache.update(key=key, avg=out)
    return out


def vs_team(mine, team):
    if mine is None or team is None:
        return "—"
    d = mine - team
    if abs(d) < TYPICAL:
        return f"{d:+.1f} (typical)"
    return f"{d:+.1f} ({'above' if d > 0 else 'below'})"
