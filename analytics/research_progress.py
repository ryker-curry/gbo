"""
GBO -- data-collection progress for Ryker's research project (Oct 2026):
the relationship between strength & conditioning tests and fastball
velocity / spin rate in collegiate pitchers.

Counts only -- how many pitchers have each test and how many have fastball
velocity/spin on file this season. No names, no individual values, so it is
safe to show on the guest demo (Ryker's midterm progress report). The
correlations themselves run once collection is complete.
"""

import time

from sqlalchemy import func

import bucket_system as bs
from models import Assessment, AssessmentResult, AssessmentTestType, Player, PitchType, RapsodoPitch

FASTBALLS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball")

# (category, [tests]) -- the predictor battery, in page order. Only tests
# that are part of the scored / reference physical testing.
BATTERY = [
    ("Body Composition", [n for n, _ in bs.BODY_COMP_DISPLAY_METRICS if n not in ("Basal Metabolic Rate (BMR)", "Recommended Caloric Intake")]),
    ("Explosive Power", [n for sub, ms in bs.POWER_SUBGROUPS.items() if sub != "Med Ball Throw" for n, _ in ms]),
    ("Rotational Power", [n for n, _ in bs.POWER_SUBGROUPS.get("Med Ball Throw", [])] + [n for n, _ in bs.MED_BALL_THROW_REFERENCE_METRICS]),
    ("Lower Body Strength", [n for n, _ in bs.STRENGTH_SUBGROUPS.get("Lower Body Strength", [])]),
    ("Upper Body Strength", [n for n, _ in bs.STRENGTH_SUBGROUPS.get("Upper Body Strength", [])]),
    ("Speed", [n for n, _ in bs.SPEED_METRICS]),
]

_CACHE = {"at": 0.0, "data": None}
CACHE_SECONDS = 600


def progress(db, use_cache=True):
    """{"window", "n_pitchers", "velo", "spin", "both_any", "rows": [(category, test, n_tested)]}.
    Current season, active pitchers only."""
    if use_cache and _CACHE["data"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
        return _CACHE["data"]
    start, end = bs.season_date_range(bs.current_season_label())
    pitchers = {pid for (pid,) in db.query(Player.player_id).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).all()}

    q = (db.query(RapsodoPitch.player_id, func.count(RapsodoPitch.velocity), func.count(RapsodoPitch.total_spin))
         .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id)
         .filter(PitchType.type_name.in_(FASTBALLS)))
    if start is not None:
        q = q.filter(RapsodoPitch.pitch_date >= start)
    if end is not None:
        q = q.filter(RapsodoPitch.pitch_date < end)
    fb = {pid: (nv, ns) for pid, nv, ns in q.group_by(RapsodoPitch.player_id).all() if pid in pitchers}
    velo = {pid for pid, (nv, _) in fb.items() if nv}
    spin = {pid for pid, (_, ns) in fb.items() if ns}

    names = [t for _, tests in BATTERY for t in tests]
    tq = (db.query(AssessmentTestType.test_name, Assessment.player_id)
          .join(AssessmentResult, AssessmentResult.test_type_id == AssessmentTestType.test_type_id)
          .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
          .filter(AssessmentTestType.test_name.in_(names), AssessmentResult.value.isnot(None)))
    if start is not None:
        tq = tq.filter(Assessment.assessment_date >= start)
    if end is not None:
        tq = tq.filter(Assessment.assessment_date < end)
    tested = {}
    for name, pid in tq.distinct().all():
        if pid in pitchers:
            tested.setdefault(name, set()).add(pid)
    rows = [(cat, t, len(tested.get(t, ()))) for cat, tests in BATTERY for t in tests]
    any_test = set().union(*tested.values()) if tested else set()
    data = {
        "window": start, "n_pitchers": len(pitchers), "velo": len(velo), "spin": len(spin),
        "tested_any": len(any_test), "both_any": len(any_test & velo),
        "rows": rows,
    }
    _CACHE.update(at=time.time(), data=data)
    return data
