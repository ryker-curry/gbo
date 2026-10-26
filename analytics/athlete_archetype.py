"""
GBO -- Athlete archetype, rebuilt on Georgia Southern's force-plate profile
report (Oct 2026, Ryker: "use the Georgia Southern template to build the
athlete archetypes" -- Hunter Lakey's GS player profile reports; GS uses Hawkin
Dynamics, GBO uses our VALD ForceDecks countermovement jump).

Everything comes from the CMJ, as team percentiles (players with that
metric on the active roster, MIN_POOL+).

RADAR -- 9 metrics, force-driven on one side, velocity-driven on the other:
  force-driven     Net Impulse, Force @ Bottom, Rel. Braking, Momentum
  velocity-driven  Jump Ht, Peak Velo, mRSI, Rel. Power, Peak Power
  FORCE SIDE %    = mean(Net Impulse, Force @ Bottom, Rel. Braking)
  VELOCITY SIDE % = mean(Peak Velo, mRSI, Jump Ht)
  (GS's sample: 19/32/73 -> 41st, 1/83/73 -> 53rd.)

FORCE-PLATE SIGNATURE -- 8 rows, every one a timing measure or per pound
of body weight, so a bigger or stronger athlete doesn't automatically read
muscular. Each row reads MUSCULAR when he sits on the muscular side of the
team (deeper dip, longer time to takeoff, more braking / push force per
pound, or less spring, speed, height, power per pound), ELASTIC on the
other side, NEUTRAL in the middle (40th-60th percentile).
  SPECTRUM INDEX = (elastic rows - muscular rows) / rows
  (GS's sample: 5 elastic, 2 muscular, 1 neutral -> +0.37.)
  Elastic at +ARCH_BAND or more, Muscular at -ARCH_BAND or less, Hybrid
  between (Ryker: +/-0.25 = a net 2 of 8 rows).

Substitutes (Ryker, Oct 2026 -- not in our VALD import yet):
  Force @ Bottom = CMJ concentric peak force
  Dip depth      = CMJ eccentric duration (a deeper dip takes longer)
Both are labeled as substitutes on the card.

OVERALL OUTPUT = his rank on the team by his average radar percentile.
SUPERPOWER / BIGGEST OPPORTUNITY = his highest / lowest radar percentile.
"""

from statistics import mean, median

ARCH_BAND = 0.25
MIN_POOL = 6
G = 9.81
LB_PER_KG = 2.2046226218

T_HEIGHT = "Countermovement Jump Height"
T_VELO = "CMJ Concentric Peak Velocity"
T_RSI = "Countermovement Jump RSI-Modified"
T_POWER = "CMJ Peak Power"
T_BW = "CMJ Bodyweight"
T_IMPULSE = "CMJ Concentric Impulse"
T_CPF = "CMJ Concentric Peak Force"
T_EPF = "CMJ Eccentric Peak Force"
T_ECC_DUR = "CMJ Eccentric Duration"
T_CON_DUR = "Countermovement Jump Concentric Duration"
NAMES = [T_HEIGHT, T_VELO, T_RSI, T_POWER, T_BW, T_IMPULSE, T_CPF, T_EPF, T_ECC_DUR, T_CON_DUR, "Body Weight"]

# key -> (label, side, unit, substitute note)
RADAR = {
    "jump_ht": ("Jump Ht", "velocity", "in", None),
    "peak_velo": ("Peak Velo", "velocity", "m/s", None),
    "mrsi": ("mRSI", "velocity", "", None),
    "rel_power": ("Rel. Power", "velocity", "W/kg", None),
    "peak_power": ("Peak Power", "velocity", "W", None),
    "momentum": ("Momentum", "force", "kg·m/s", None),
    "net_impulse": ("Net Impulse", "force", "N·s", None),
    "force_bottom": ("Force @ Bottom", "force", "N", "concentric peak force stands in until our VALD import has force at the bottom of the dip"),
    "rel_braking": ("Rel. Braking", "force", "%BW", None),
}
# radar order around the circle (GS: Jump Ht at the top, velocity side clockwise)
RADAR_ORDER = ["jump_ht", "peak_velo", "mrsi", "rel_power", "peak_power", "momentum", "net_impulse",
               "force_bottom", "rel_braking"]
FORCE_SIDE = ["net_impulse", "force_bottom", "rel_braking"]
VELO_SIDE = ["peak_velo", "mrsi", "jump_ht"]

# key -> (label, value key, "muscular" when the value is HIGH (True) or LOW (False), words high / low, substitute)
SIGNATURE = [
    ("dip", "Dip depth", "dip", True, ("deeper than", "shallower"), "eccentric duration stands in for dip depth"),
    ("ttt", "Time to takeoff", "ttt", True, ("longer than", "quicker"), None),
    ("brake", "Rel. braking force", "rel_braking", True, ("higher than", "lower"), None),
    ("push", "Rel. push force", "rel_push", True, ("higher than", "lower"), None),
    ("mrsi", "mRSI", "mrsi", False, ("higher than", "lower"), None),
    ("speed", "Takeoff speed", "peak_velo", False, ("higher than", "lower"), None),
    ("height", "Jump height", "jump_ht", False, ("higher than", "lower"), None),
    ("power", "Relative power", "rel_power", False, ("higher than", "lower"), None),
]
NEUTRAL_LO, NEUTRAL_HI = 40, 60

DESCRIPTION = {
    "Elastic": "Velocity-driven. Quick, stiff, springy; wins with the stretch-shortening cycle. Strength work has the most upside.",
    "Muscular": "Force-driven. Deeper, longer push; wins by putting a lot of force into the ground. Speed and reactive work has the most upside.",
    "Hybrid": "Balanced. No strong lean either way; uses both force and spring. Train both and let the retests show which side moves.",
}

# "In the box" -- adapted from Georgia Southern's hitting table (Ryker, Oct 2026)
IN_THE_BOX = {
    "rows": ["Gather · load", "Forward move", "Pelvis-torso transfer", "Barrel · contact", "Ball flight"],
    "Muscular": ["Strong rear-hip load and pressure. WATCH: over-depth or a slow gather that eats decision time.",
                 "Firm force acceptance at foot plant. WATCH: a heavy landing, long transfer or late organization.",
                 "Force and grounding. WATCH: pelvis and torso turn as one block -- early commitment, hard to change plans mid-swing.",
                 "High collision force and a stable barrel. WATCH: late barrel entry or slow acceleration if he stays deep and horizontal too long.",
                 "Elite exit velo and a stable launch when force is expressed quickly. WATCH: low attack angle and hard ground balls; late to velocity."],
    "Hybrid": ["Loads with force or with rhythm. WATCH: a slow gather or drift outside the back foot.",
               "Adequate acceptance at foot plant. WATCH: a heavy landing or early opening.",
               "Adequate separation. WATCH: one-block turn, or the pelvis escaping early.",
               "Enough force to drive it, enough twitch to adjust. WATCH: strength gains that stop showing up as bat speed.",
               "Consistent hard contact with adjustability. WATCH: lateness to velocity or rollovers, whichever leak shows up."],
    "Elastic": ["Rapid coil and separation. WATCH: drift outside the back foot, weak rear-hip capture, over-rotation.",
                "Quick transition into foot plant. WATCH: early opening or a soft front side -- spin-off, momentum he can't brake.",
                "Fast pelvis-to-torso sequencing. WATCH: pelvis leads, then outruns the torso and arms; the hands have to rescue contact.",
                "Late, fast barrel acceleration and adjustability. WATCH: variable collision quality if the base or block is unstable.",
                "Late adjustability and balls in the air when posture and braking hold. WATCH: pull-side rollovers, cut-across contact, a lower exit-velo floor."],
}
# "On the mound" -- GBO's pitching version of the same table. DRAFT wording
# for the staff to edit (Ryker, Oct 2026).
ON_THE_MOUND = {
    "rows": ["Gather · leg lift", "Stride · foot plant", "Pelvis-torso separation", "Arm action · release", "What shows up"],
    "Muscular": ["Strong back-leg load; pushes down the mound with force. WATCH: sinking too deep or a slow gather that drifts.",
                 "Firm lead-leg block at foot plant. WATCH: a heavy landing or a long stride that leaks energy.",
                 "Force and grounding. WATCH: pelvis and torso turn as one block -- early trunk rotation.",
                 "Strong, stable arm path. WATCH: the arm dragging behind a late-rotating trunk.",
                 "Heavy fastball; velo holds with intent. WATCH: velo that drops as the outing goes, less ride."],
    "Hybrid": ["Loads with rhythm and some force. WATCH: a slow gather or drift off the rubber.",
               "Adequate block at foot plant. WATCH: a heavy landing or opening early.",
               "Adequate separation. WATCH: one-block turn, or the pelvis opening early.",
               "Repeatable slot. WATCH: strength gains that stop showing up as arm speed.",
               "Solid mix of shape and command. WATCH: whichever side (velo or command) leaks first."],
    "Elastic": ["Quick, compact load; moves fast down the mound. WATCH: rushing, drifting off the rubber.",
                "Quick transition into foot plant. WATCH: a soft front side -- spins off instead of blocking.",
                "Fast pelvis-to-torso sequencing, big separation. WATCH: the pelvis opens early and the arm has to catch up.",
                "Fast, whippy arm speed. WATCH: an inconsistent slot and command when the base is unstable.",
                "Velo from speed and spring; good extension. WATCH: velo fade late, arm-side-high misses when tired."],
}

TRAINING = {
    "Elastic": {"focus": "Strength under the spring",
                "do": ["Heavy lower-body strength (trap bar, squat, split squat) 2-3x / week, 3-5 reps",
                       "Loaded jumps and slow eccentrics to build net impulse and braking",
                       "Keep one short plyo day so he doesn't lose his bounce"],
                "retest": "Net impulse, force @ bottom, rel. braking"},
    "Muscular": {"focus": "Speed and reactivity",
                 "do": ["Plyos with short ground contacts (pogos, hurdle hops, depth jumps)",
                        "Speed-strength: light jump squats, med-ball throws for speed, velocity-based lifting",
                        "Keep heavy strength in maintenance (1-2x / week)"],
                 "retest": "Peak velo, mRSI, jump height, time to takeoff"},
    "Hybrid": {"focus": "Both, by block",
               "do": ["Alternate 3-4 week blocks: heavy strength, then speed / reactive",
                      "Train his biggest opportunity metric first",
                      "Retest every block to see which side moves"],
               "retest": "His lowest-percentile metric"},
}

# IDP goal: radar metric -> (stored test, how the team-median target converts to that test)
GOAL_TEST = {
    "jump_ht": (T_HEIGHT, None), "peak_velo": (T_VELO, None), "mrsi": (T_RSI, None), "peak_power": (T_POWER, None),
    "net_impulse": (T_IMPULSE, None), "force_bottom": (T_CPF, None),
    "rel_power": (T_POWER, lambda m, bw: m * bw),
    "momentum": (T_VELO, lambda m, bw: m / bw),
    "rel_braking": (T_EPF, lambda m, bw: m / 100 * bw * G),
}


# ---------------------------------------------------------------------------

def _pct_rank(v, pool, higher=True):
    below = sum(1 for x in pool if (x < v if higher else x > v))
    equal = sum(1 for x in pool if x == v)
    return round(100.0 * (below + 0.5 * equal) / len(pool))


def _ord(n):
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def _bw_kg(raw, pid):
    bw = (raw.get(T_BW) or {}).get(pid)
    if bw:
        return float(bw)
    lb = (raw.get("Body Weight") or {}).get(pid)
    return float(lb) / LB_PER_KG if lb else None


def values(raw):
    """raw: {test: {pid: value}} -> {metric key: {pid: value}} for radar +
    signature metrics (relative ones per kg of CMJ body weight)."""
    pids = set()
    for d in raw.values():
        pids |= set(d)
    out = {k: {} for k in list(RADAR) + ["dip", "ttt", "rel_push"]}
    for pid in pids:
        g = lambda t: (float(raw[t][pid]) if raw.get(t, {}).get(pid) is not None else None)  # noqa: E731
        bw = _bw_kg(raw, pid)
        h, v, rsi, pw, imp, cpf, epf = g(T_HEIGHT), g(T_VELO), g(T_RSI), g(T_POWER), g(T_IMPULSE), g(T_CPF), g(T_EPF)
        ecc, con = g(T_ECC_DUR), g(T_CON_DUR)
        put = lambda k, x: out[k].__setitem__(pid, x) if x is not None else None  # noqa: E731
        put("jump_ht", h)
        put("peak_velo", v)
        put("mrsi", rsi)
        put("peak_power", pw)
        put("net_impulse", imp)
        put("force_bottom", cpf)
        if bw:
            put("rel_power", pw / bw if pw is not None else None)
            put("momentum", bw * v if v is not None else None)
            put("rel_braking", epf / (bw * G) * 100 if epf is not None else None)
            put("rel_push", cpf / (bw * G) * 100 if cpf is not None else None)
        put("dip", ecc)
        put("ttt", ecc + con if ecc is not None and con is not None else None)
    return {k: d for k, d in out.items() if d}


def _radar_pcts(pid, vals):
    out = {}
    for k in RADAR_ORDER:
        pool = vals.get(k) or {}
        if pid in pool and len(pool) >= MIN_POOL:
            out[k] = _pct_rank(pool[pid], list(pool.values()))
    return out


def profile(pid, vals):
    """-> None (not enough data) or {"kind", "index", "output", "force", "velocity", "metrics", "signature",
    "counts", "best", "worst", "lines", "how", "substitutes"}"""
    pcts = _radar_pcts(pid, vals)
    f_side = [pcts[k] for k in FORCE_SIDE if k in pcts]
    v_side = [pcts[k] for k in VELO_SIDE if k in pcts]
    sig = []
    for key, label, vk, musc_high, words, sub in SIGNATURE:
        pool = vals.get(vk) or {}
        if pid not in pool or len(pool) < MIN_POOL:
            continue
        pct = _pct_rank(pool[pid], list(pool.values()))
        m = pct if musc_high else 100 - pct            # how far toward muscular
        lean = "muscular" if m >= NEUTRAL_HI else ("elastic" if m <= NEUTRAL_LO else "neutral")
        sig.append({"key": key, "label": label, "pct": pct, "m": m, "lean": lean,
                    "text": f"{words[0]} {pct}% of team", "substitute": sub})
    if not f_side or not v_side or len(sig) < 3:
        return None
    counts = {k: sum(1 for s in sig if s["lean"] == k) for k in ("muscular", "elastic", "neutral")}
    idx = (counts["elastic"] - counts["muscular"]) / len(sig)
    kind = "Elastic" if idx >= ARCH_BAND else ("Muscular" if idx <= -ARCH_BAND else "Hybrid")
    metrics = [{"key": k, "test": k, "label": RADAR[k][0], "side": RADAR[k][1], "pct": pcts[k],
                "value": vals[k][pid], "unit": RADAR[k][2], "pool": len(vals[k]), "substitute": RADAR[k][3]}
               for k in RADAR_ORDER if k in pcts]
    # overall output: his rank on the team by average radar percentile
    means = {}
    for other in set().union(*[set(vals.get(k, {})) for k in RADAR_ORDER]):
        op = _radar_pcts(other, vals)
        if len(op) >= max(3, len(pcts) - 2):
            means[other] = mean(op.values())
    mine = mean(pcts.values())
    output = _pct_rank(mine, list(means.values())) if len(means) >= MIN_POOL else round(mine)
    best = max(metrics, key=lambda m: m["pct"])
    worst = min(metrics, key=lambda m: m["pct"])
    lines = [DESCRIPTION[kind], f"Superpower: {best['label']} ({_ord(best['pct'])} percentile on the team)."]
    if worst["pct"] < 40:
        lines.append(f"Biggest opportunity: {worst['label']} ({_ord(worst['pct'])}).")
    return {"kind": kind, "index": idx, "output": output, "force": round(mean(f_side)), "velocity": round(mean(v_side)),
            "metrics": metrics, "signature": sig, "counts": counts, "best": best, "worst": worst, "lines": lines,
            "how": how_he_moves(sig, kind),
            "substitutes": [s for s in [RADAR[m["key"]][3] for m in metrics] + [s["substitute"] for s in sig] if s]}


def how_he_moves(sig, kind):
    """A plain 'on the plates' sentence from the signature rows."""
    by = {s["key"]: s for s in sig}
    bits = []
    if "dip" in by:
        bits.append({"elastic": "loads shallow", "muscular": "loads deep", "neutral": "loads to a normal depth"}[by["dip"]["lean"]])
    if "ttt" in by:
        bits.append({"elastic": "gets off the ground quickly", "muscular": "takes a longer push to get off the ground",
                     "neutral": "gets off the ground in a normal time"}[by["ttt"]["lean"]])
    if "height" in by or "mrsi" in by:
        s = by.get("height") or by["mrsi"]
        bits.append({"elastic": "produces good height and spring", "muscular": "gets less height and spring than his force suggests",
                     "neutral": "produces average height"}[s["lean"]])
    forces = [by[k] for k in ("brake", "push") if k in by]
    if forces:
        lean = "muscular" if any(f["lean"] == "muscular" for f in forces) else (
            "elastic" if all(f["lean"] == "elastic" for f in forces) else "neutral")
        bits.append({"muscular": "puts a lot of braking and push force into the ground per pound",
                     "elastic": "runs lighter on braking and push force per pound",
                     "neutral": "has average braking and push force per pound"}[lean])
    if not bits:
        return ""
    tail = {"Elastic": " He produces relative to his body weight rather than through size.",
            "Muscular": " He produces through force and mass more than spring.",
            "Hybrid": " He uses a mix of force and spring."}[kind]
    return "On the plates he " + ", ".join(bits[:-1]) + (", and " if len(bits) > 1 else "") + bits[-1] + "." + tail


# ---------------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------------

def load(db, pid):
    import bucket_system as bs
    raw, _units = bs._batch_fetch_latest_values(db, NAMES, include_player_id=pid)
    return profile(pid, values(raw))


def load_full(db, pid):
    """(profile, raw) -- raw is needed to build an IDP goal."""
    import bucket_system as bs
    raw, _units = bs._batch_fetch_latest_values(db, NAMES, include_player_id=pid)
    return profile(pid, values(raw)), raw


def team(db):
    """[(Player, profile)] for every active player with a profile, Elastic -> Muscular."""
    import bucket_system as bs
    from models import Player
    raw, _units = bs._batch_fetch_latest_values(db, NAMES)
    vals = values(raw)
    out = []
    for p in db.query(Player).filter(Player.active.is_(True)).all():
        prof = profile(p.player_id, vals)
        if prof:
            out.append((p, prof))
    out.sort(key=lambda t: -t[1]["index"])
    return out


def goal_spec(pid, raw, prof):
    """IDP goal for his biggest opportunity: raise that radar metric to the
    team median, written on the CMJ test it comes from (relative metrics
    converted with his own body weight). None if it can't be built."""
    if not prof or prof["worst"]["pct"] >= 50:
        return None
    key = prof["worst"]["key"]
    test, conv = GOAL_TEST[key]
    vals = values(raw)
    pool = vals.get(key) or {}
    base_raw = (raw.get(test) or {}).get(pid)
    if not pool or base_raw is None:
        return None
    m = median(pool.values())
    if conv is None:
        target = m
    else:
        bw = _bw_kg(raw, pid)
        if not bw:
            return None
        target = conv(m, bw)
    base = float(base_raw)
    if target <= base:
        return None
    return {"test": test, "label": prof["worst"]["label"], "baseline": base, "target": target, "kind": prof["kind"]}


def open_goal(db, pid, test):
    """The player's existing not-Completed IDP goal on this test, or None --
    so the one-click "Make goal" button can't create the same goal twice."""
    from models import AssessmentTestType, IDPGoal, IDPStatus
    return (db.query(IDPGoal)
            .join(AssessmentTestType, AssessmentTestType.test_type_id == IDPGoal.target_test_type_id)
            .outerjoin(IDPStatus, IDPStatus.status_id == IDPGoal.status_id)
            .filter(IDPGoal.player_id == pid, AssessmentTestType.test_name == test,
                    (IDPStatus.status_name.is_(None)) | (IDPStatus.status_name != "Completed"))
            .first())


def create_goal(db, pid, sp, user_id):
    """Create the archetype IDP goal from goal_spec(). -> (created, message).
    Refuses (no write) if an open goal on the same test already exists."""
    from datetime import date, timedelta
    from models import AssessmentTestType, IDPGoal, IDPStatus
    if open_goal(db, pid, sp["test"]) is not None:
        return False, f"He already has an open IDP goal on {sp['test']} -- no new goal made."
    tt = db.query(AssessmentTestType).filter(AssessmentTestType.test_name == sp["test"]).first()
    st = db.query(IDPStatus).order_by(IDPStatus.display_order, IDPStatus.status_id).first()
    if tt is None or st is None:
        return False, "Couldn't make the goal -- test type or IDP statuses missing."
    db.add(IDPGoal(
        player_id=pid, category_id=tt.category_id, target_test_type_id=tt.test_type_id,
        baseline_value=round(sp["baseline"], 3), target_value=round(sp["target"], 3),
        target_date=date.today() + timedelta(weeks=8), status_id=st.status_id,
        description=(f"Athlete archetype ({sp['kind']}): biggest opportunity is {sp['label'].lower()}. "
                     f"Raise {sp['test']} from {sp['baseline']:.2f} to the team middle ({sp['target']:.2f})."),
        created_by_user_id=user_id,
    ))
    db.commit()
    return True, f"Goal created: {sp['test']}."
