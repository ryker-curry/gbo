"""Oct 2026: compensation profile -- domains, velo model, flags, tracking."""

import random
from datetime import date, timedelta
from types import SimpleNamespace as NS

from analytics import compensation as comp


def test_derive_throwing_arm_and_per_lb():
    raw = {"Shoulder: Right External Rotation": 120.0, "Shoulder: Left External Rotation": 100.0,
           "Shoulder: Right Internal Rotation": 50.0, "Shoulder: Left Internal Rotation": 65.0,
           "Body Weight": 200.0, "Hex Bar Deadlift Max": 400.0}
    d = comp.derive(raw, "R")
    assert d[comp.ER_THROW] == 120 and d[comp.GIRD] == 15 and d[comp.TAD] == (100 + 65) - (120 + 50)
    assert comp.derive(raw, "L")[comp.ER_THROW] == 100
    v = comp.test_values(d)
    assert v["Hex Bar Deadlift Max"] == 2.0 and v["Body Weight"] == 200.0


def test_domains_read_and_flags():
    rng = random.Random(4)
    vals = {pid: {"Body Weight": 180 + rng.gauss(0, 10), "Hex Bar Deadlift Max": 2.0 + rng.gauss(0, 0.2),
                  "Acceleration: 10-Yard Sprint Time": 1.7 + rng.gauss(0, 0.05)} for pid in range(12)}
    vals[99] = {"Body Weight": 230.0, "Hex Bar Deadlift Max": 1.4, "Acceleration: 10-Yard Sprint Time": 1.55}
    stats = comp.staff_stats(vals)
    doms = comp.domains_for(vals[99], stats)
    assert doms["Size"]["z"] > 1 and doms["Lower-body strength"]["z"] < -1 and doms["Speed"]["z"] > 1   # fast = lower time
    strong, weak = comp.read(doms)
    assert "Size" in strong and weak == ["Lower-body strength"]
    derived = {"Shoulder Strength: Throwing Arm ER Peak Force": 30.0, "Shoulder Strength: Throwing Arm IR Peak Force": 50.0,
               comp.LEAD_HIP_IR: 18.0}
    names = {f["name"] for f in comp.flags(99, doms, derived, None, {99: 85.0})}
    assert {"ER:IR strength ratio", "Lead-hip internal rotation"} <= names


def test_velo_model_leave_one_out():
    doms, velo = {}, {}
    for pid in range(14):
        s, p, r = (pid % 5) - 2, ((pid * 3) % 5) - 2, ((pid * 2) % 5) - 2
        doms[pid] = {m: {"z": z} for m, z in zip(comp.MODEL_DOMAINS, (s, p, r))}
        velo[pid] = 84 + 1.0 * s + 0.5 * p + 0.8 * r
    velo[13] += 4                                    # throws way above his body
    m = comp.velo_model(doms, velo, predictors=list(comp.MODEL_DOMAINS))
    assert m["n"] == 14 and m["pred"][13][2] > 3 and abs(m["pred"][0][2]) < 1.5


def test_changes_effects_and_hold_days():
    d0 = date(2026, 6, 1)
    tl = [(d0, {"Hip mobility": -1.2}), (d0 + timedelta(days=60), {"Hip mobility": -0.4})]
    chg = comp.changes(tl, "Hip mobility")
    assert len(chg) == 1
    fb = [(d0 + timedelta(days=30 + i), 84.0) for i in range(10)] + [(d0 + timedelta(days=70 + i), 85.0) for i in range(10)]
    hold = [NS(kind="status", status="Hold", start_date=d0 + timedelta(days=40), end_date=d0 + timedelta(days=44))]
    e = comp.change_effects(chg, fb, hold)[0]
    assert e["dvelo"] == 1.0 and e["hold_before"] == 5 and e["hold_after"] == 0
    months = comp.monthly(fb, hold, [])
    assert any(m["hold"] == 5 for m in months)


def test_own_drivers_his_history():
    d0 = date(2026, 1, 5)
    seq, fb, state = [], [], {}
    for k in range(5):
        d = d0 + timedelta(days=30 * k)
        state = dict(state, **{"Hip: Plant Leg External Rotation": 30.0 + 5 * k, "Body Weight": 200.0 + (k % 2)})
        seq.append((d, dict(state), {"Hip: Plant Leg External Rotation", "Body Weight"}))
        fb += [(d + timedelta(days=i), 82.0 + k) for i in range(6)]
    rows = comp.own_drivers(seq, "R", fb)
    hip = next(r for r in rows if r["test"] == "Hip: Plant Leg External Rotation")
    assert hip["r"] > 0.95 and hip["n"] == 5 and hip["diff"] > 2 and rows[0]["test"] == hip["test"]


def test_tire_drift_and_delivery_flags():
    rows = [(("bp", 1), i, None, 90.0 - 0.1 * i, 6.0 - 0.005 * i, 1.8, 6.2 - 0.01 * i, 2300.0) for i in range(30)]
    drift = comp.tire_drift(rows)
    assert drift["velo"][0] < -1.5 and drift["ext"][0] < -2 and drift["side"][0] == 0
    staff = {"ext": (-0.5, 0.5), "velo": (-0.5, 0.5)}
    fl = comp.delivery_flags(drift, (None, None), staff, ["Lower-body power"])
    names = {f["name"] for f in fl}
    assert "Extension late in outings" in names and "lower half" in next(f["why"] for f in fl if f["name"].startswith("Extension"))
    assert comp.early_late([(date(2026, 3, 1), 4.0, i) for i in range(1, 80)]) == (4.0, 4.0)


def test_idp_spec_converts_per_lb():
    data = {"doms": {1: {"Lower-body strength": {"z": -1.0, "tests": [("Hex Bar Deadlift Max", 1.5, -1.2)]}}},
            "derived": {1: {"Hex Bar Deadlift Max": 300.0, "Body Weight": 200.0}},
            "stats": {"Hex Bar Deadlift Max": (2.0, 0.3, 20)}}
    sp = comp.idp_goal_spec(1, "Lower-body strength", data)
    assert sp["test"] == "Hex Bar Deadlift Max" and sp["baseline"] == 300 and sp["target"] == 400 and sp["per_lb"]


def test_pick_predictors_by_correlation():
    doms, velo = {}, {}
    for pid in range(15):
        doms[pid] = {"Speed": {"z": (pid % 5) - 2.0}, "Size": {"z": ((pid * 7) % 5) - 2.0}}
        velo[pid] = 84 + 1.5 * doms[pid]["Speed"]["z"]
    picked, screen = comp.pick_predictors(doms, velo)
    assert picked[0] == "Speed" and screen["Speed"][0] > 0.99
