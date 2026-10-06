"""
GBO -- guest demo database (Oct 2026, Ryker: "update the continue as guest
view to match what it looks like now" -- for his midterm progress report;
his teacher clicks Continue as Guest and sees the real app).

Continue as Guest now runs the REAL GBO pages against a made-up team stored
in a private in-memory SQLite database -- never Supabase. Nothing here is a
real player: every name, number and game below is invented (names are
checked against nothing real; the generator is seeded so the demo looks the
same every time). Assessment values are drawn from team-wide averages and
spreads only (no individual's numbers), so the testing pages look realistic.

How it plugs in:
  - build_master() builds the demo team ONCE per process (a few seconds).
  - new_guest_db() copies that master into a fresh in-memory database for
    ONE guest browser session (SQLite backup API, milliseconds) and returns
    (sessionmaker, engine). Each guest gets a private copy, so anything a
    guest clicks or saves only changes their own copy and disappears when
    they leave.
  - database.get_session() hands out that guest's sessionmaker whenever the
    current Shiny session is a guest (see database.py).
"""

import contextlib
import datetime as dt
import io
import random
import sqlite3
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models as m
import seed_lookups as sl
import bucket_system as bs
from strike_zone import derive_old_zone

SEED = 20261006
DEMO_COACH_EMAIL = "guest.coach@demo.gbo"
DEMO_PLAYER_EMAIL = "guest.pitcher@demo.gbo"
DEMO_HITTER_EMAIL = "guest.hitter@demo.gbo"

# --- fictional roster -------------------------------------------------------
# (first, last, throws, height_in, weight_lb, class, arsenal, velo_offset, spin_offset, command_sd_ft)
PITCHERS = [
    ("Owen", "Hartwell", "R", 75, 205, "Senior", ["4-Seam Fastball", "Slider", "Changeup"], 2.5, 120, 0.30),
    ("Caleb", "Brandt", "R", 73, 190, "Junior", ["4-Seam Fastball", "Curveball", "Changeup"], 0.5, 60, 0.34),
    ("Mason", "Kerrigan", "L", 74, 195, "Sophomore", ["4-Seam Fastball", "Curveball", "Changeup"], -1.0, -40, 0.33),
    ("Dalton", "Pierce", "R", 76, 215, "Graduate", ["4-Seam Fastball", "Slider", "Cutter"], 3.5, 150, 0.38),
    ("Grant", "Whitlock", "R", 72, 185, "Freshman", ["4-Seam Fastball", "Slider"], -2.0, -80, 0.40),
    ("Reid", "Ashford", "L", 73, 188, "Junior", ["4-Seam Fastball", "Slider", "Changeup"], 0.0, 20, 0.31),
    ("Tanner", "Holcomb", "R", 74, 200, "Senior", ["4-Seam Fastball", "Changeup", "Curveball"], 1.0, -20, 0.29),
    ("Brody", "Callan", "R", 77, 225, "Redshirt Sophomore", ["4-Seam Fastball", "Slider"], 4.0, 90, 0.42),
    ("Wyatt", "Selby", "R", 71, 180, "Freshman", ["4-Seam Fastball", "Curveball"], -3.0, -110, 0.36),
    ("Jace", "Morrow", "L", 75, 198, "Sophomore", ["4-Seam Fastball", "Changeup", "Slider"], -0.5, 40, 0.35),
    ("Nolan", "Prewitt", "R", 73, 192, "Junior", ["4-Seam Fastball", "Cutter", "Changeup"], 1.5, 10, 0.32),
    ("Eli", "Garrison", "R", 74, 202, "Redshirt Freshman", ["4-Seam Fastball", "Slider", "Curveball"], 0.0, 70, 0.37),
]
# (first, last, bats, position, contact 0-1, power 0-1, eye 0-1)
HITTERS = [
    ("Luke", "Danforth", "R", "SS", .62, .40, .60),
    ("Cody", "Ferris", "L", "CF", .66, .35, .64),
    ("Ryan", "Maddox", "R", "C", .52, .55, .48),
    ("Zane", "Albright", "L", "1B", .55, .70, .52),
    ("Trent", "Ostrander", "R", "3B", .58, .58, .55),
    ("Hayes", "Kimbrell", "S", "2B", .64, .30, .66),
    ("Colt", "Rainey", "R", "LF", .54, .50, .45),
    ("Jaxon", "Delacroix", "L", "RF", .57, .48, .58),
    ("Bennett", "Sorrell", "R", "DH", .50, .66, .42),
    ("Parker", "Lindquist", "R", "C", .48, .38, .50),
    ("Drew", "Halvorsen", "L", "UTL", .56, .32, .57),
]
OPPONENTS = ["Prairie State", "Ozark Valley", "Missouri Bluffs", "Flint Hills Tech"]

# --- pitch shapes (college-level, illustrative) ----------------------------
# velo, ivb, hb (arm side +), spin, axis, eff, gyro, release height
SHAPES = {
    "4-Seam Fastball": (87.0, 16.0, 8.0, 2180, 210, 90, 18, 5.8),
    "Cutter": (82.5, 8.0, -2.5, 2250, 190, 45, 55, 5.8),
    "Slider": (78.0, 1.0, -7.5, 2300, 260, 35, 62, 5.7),
    "Curveball": (73.5, -11.0, -6.0, 2400, 330, 65, 42, 5.9),
    "Changeup": (79.5, 7.0, 13.0, 1700, 235, 85, 25, 5.7),
}
USAGE = {"4-Seam Fastball": 5, "Slider": 3, "Curveball": 2.5, "Changeup": 2.5, "Cutter": 2.5}

# Team-wide (mean, sd) per test -- aggregate spreads only, no individual's
# numbers. Keeps the testing pages realistic.
TEST_DISTS = {
    "Body Weight": (194.9, 14.8), "Skeletal Muscle Mass": (95.4, 7.2), "Body Fat Mass": (29.0, 9.4),
    "Percent Body Fat": (14.8, 4.2), "Basal Metabolic Rate (BMR)": (1986, 125), "Recommended Caloric Intake": (3123, 253),
    "Medicine Ball Shot Put Distance": (50.0, 7.3), "Medicine Ball Shot Put Velocity": (28.4, 1.6),
    "Vertical Jump (Jump Mat)": (30.6, 3.4), "Broad Jump Distance": (102.0, 7.4),
    "Lateral Jump Distance (Drive Leg)": (78.1, 6.3), "Lateral Jump Distance (Plant Leg)": (77.9, 6.8),
    "Grip Strength (Seated, Throwing Hand)": (117.7, 15.1), "Neutral Grip Chin Up Max External Load": (260.9, 20.4),
    "Neutral Grip/DB Bench Press Max Load": (198.0, 29.0), "Front Squat Max": (258.6, 46.1), "Hex Bar Deadlift Max": (420.5, 63.0),
    "Acceleration: 10-Yard Sprint Time": (1.68, 0.06), "Top Speed: Flying 10 Sprint Time": (1.10, 0.05),
    "30-Yard Sprint Time": (3.95, 0.15),
    "Shoulder: Right External Rotation": (120.7, 7.6), "Shoulder: Left External Rotation": (111.6, 11.8),
    "Shoulder: Right Internal Rotation": (53.9, 12.3), "Shoulder: Left Internal Rotation": (61.2, 9.2),
    "Shoulder: Right Flexion": (173.2, 10.5), "Shoulder: Left Flexion": (174.7, 9.4),
    "Shoulder: Right Extension": (42.7, 10.5), "Shoulder: Left Extension": (48.4, 12.1),
    "Elbow: Right Flexion": (150.4, 11.3), "Elbow: Left Flexion": (146.9, 12.0),
    "Elbow: Right Extension": (15.2, 5.3), "Elbow: Left Extension": (17.5, 5.7),
    "Hip: Right Internal Rotation": (46.1, 9.7), "Hip: Left Internal Rotation": (46.4, 9.0),
    "Hip: Right External Rotation": (46.2, 10.9), "Hip: Left External Rotation": (45.3, 10.9),
    "Hip: Right Abduction": (60.5, 10.8), "Hip: Left Abduction": (58.2, 11.0),
    "Hip: Right Adduction": (47.6, 7.6), "Hip: Left Adduction": (48.7, 7.8),
    "Hip: Right Flexion": (130.7, 6.8), "Hip: Left Flexion": (130.7, 8.1),
    "Hip: Right Extension": (38.7, 8.3), "Hip: Left Extension": (39.1, 9.1),
}
ROM_PREFIXES = ("Shoulder:", "Elbow:", "Hip:")
TEST_DATES = [dt.date(2025, 8, 25), dt.date(2026, 8, 24)]   # last fall and this fall


def _round(v, unit):
    if unit == "s":
        return round(v, 2)
    if unit in ("N", "kcal", "ms", "°"):
        return round(v)
    return round(v, 1)


def _populate(db):
    rnd = random.Random(SEED)
    with contextlib.redirect_stdout(io.StringIO()):      # seed_lookups prints progress
        for f in (sl.seed_roles, sl.seed_assessment_categories_and_tests, sl.seed_pitch_types, sl.seed_idp_statuses,
                  sl.seed_session_types, sl.seed_player_statuses, sl.seed_player_classes, sl.seed_positions,
                  sl.seed_team_event_types, sl.seed_bullpen_types, sl.seed_hitter_session_types):
            f(db)
    from migrations.migrate_run_expectancy import RE_DATA
    for outs, bases, count, re_value in RE_DATA:
        db.add(m.RunExpectancy(outs=outs, bases=bases, count=count, re_value=re_value))

    roles = {r.role_name: r.role_id for r in db.query(m.Role).all()}
    ptype = {p.type_name: p.pitch_type_id for p in db.query(m.PitchType).all()}
    pos = {p.position_name: p.position_id for p in db.query(m.Position).all()}
    cls = {c.class_name: c.class_id for c in db.query(m.PlayerClass).all()}
    active_status = db.query(m.PlayerStatus).filter_by(status_name="Active").one().status_id

    db.add(m.Organization(organization_id=1, organization_name="Demo University"))
    db.add(m.Team(team_id=1, organization_id=1, team_name="Demo Gorillas", season_year=2026))
    db.flush()
    coach = m.User(user_id=1, organization_id=1, email=DEMO_COACH_EMAIL, first_name="Demo", last_name="Coach",
                   role_id=roles["Administrator"], active=True)   # full access, so a guest can try data entry too
    db.add(coach)
    db.add(m.Season(season_id=1, season_name="Fall 2026", is_official=False, start_date=dt.date(2026, 8, 1),
                    created_by_user_id=1))

    # --- players ---
    players = []
    pid = 0
    grad = {"Freshman": 2030, "Redshirt Freshman": 2030, "Sophomore": 2029, "Redshirt Sophomore": 2029,
            "Junior": 2028, "Senior": 2027, "Graduate": 2027}
    for i, (f, l, t, h, w, c, ars, vo, so, cmd) in enumerate(PITCHERS):
        pid += 1
        p = m.Player(player_id=pid, team_id=1, first_name=f, last_name=l, is_pitcher=True, throws=t, bats=t,
                     position_id=pos["RHP" if t == "R" else "LHP"], jersey_number=10 + i * 3, class_id=cls[c],
                     graduation_year=grad.get(c, 2028), height_in=h, weight_lb=w, status_id=active_status,
                     hometown="Demo Town, KS", active=True)
        p._demo = dict(arsenal=ars, velo=vo, spin=so, cmd=cmd)
        players.append(p)
    hitter_ids = []
    for i, (f, l, b, ps, con, pw, eye) in enumerate(HITTERS):
        pid += 1
        p = m.Player(player_id=pid, team_id=1, first_name=f, last_name=l, is_pitcher=False, throws="R", bats=b,
                     position_id=pos[ps], jersey_number=2 + i * 2, class_id=cls[rnd.choice(list(grad))],
                     graduation_year=2028, height_in=rnd.randint(70, 75), weight_lb=rnd.randint(175, 215),
                     status_id=active_status, hometown="Demo Town, KS", active=True)
        p._demo = dict(con=con, pw=pw, eye=eye)
        players.append(p)
        hitter_ids.append(pid)
    for p in players:
        demo = p._demo
        del p._demo
        db.add(p)
        p.demo = demo
    db.flush()
    pitchers = [p for p in players if p.is_pitcher]
    hitters = [p for p in players if not p.is_pitcher]
    db.add(m.User(user_id=2, organization_id=1, email=DEMO_PLAYER_EMAIL, first_name=pitchers[0].first_name,
                  last_name=pitchers[0].last_name, role_id=roles["Player"], player_id=pitchers[0].player_id, active=True))
    db.add(m.User(user_id=3, organization_id=1, email=DEMO_HITTER_EMAIL, first_name=hitters[0].first_name,
                  last_name=hitters[0].last_name, role_id=roles["Player"], player_id=hitters[0].player_id, active=True))
    for p in pitchers:
        for k, name in enumerate(p.demo["arsenal"]):
            db.add(m.PlayerPitchArsenal(player_id=p.player_id, pitch_type_id=ptype[name], active=True, is_primary=k == 0))

    # --- assessments: last fall + this fall, everyone ---
    cats = {c.category_name: c.category_id for c in db.query(m.AssessmentCategory).all()}
    tests = {t.test_name: t for t in db.query(m.AssessmentTestType).all()}
    dirs = {}
    for lst in [bs.BODY_COMP_DISPLAY_METRICS, bs.MED_BALL_THROW_REFERENCE_METRICS, bs.SPEED_METRICS] + \
            list(bs.POWER_SUBGROUPS.values()) + list(bs.STRENGTH_SUBGROUPS.values()):
        for n, d in lst:
            dirs[n] = d
    for p in players:
        talent = rnd.gauss(0, 0.8)                 # one athleticism factor per player
        base = {}
        for name, (mu, sd) in TEST_DISTS.items():
            if name not in tests:
                continue
            if name.startswith(ROM_PREFIXES):
                if not p.is_pitcher:
                    continue
                base[name] = rnd.gauss(mu, sd * 0.9)
            else:
                d = dirs.get(name, "higher")
                sign = -1 if d == "lower" else 1
                base[name] = mu + sd * (0.6 * sign * talent + rnd.gauss(0, 0.75))
        for k, day in enumerate(TEST_DATES):
            if k == 0 and rnd.random() < 0.2:
                continue                           # a few newcomers have only this fall
            by_cat = {}
            for name, v0 in base.items():
                t = tests[name]
                if name.startswith(ROM_PREFIXES) and k == 0:
                    continue                       # ROM screening started this fall
                d = dirs.get(name)
                gain = 0.0
                if k == 1 and d and not name.startswith(ROM_PREFIXES):
                    gain = (0.35 if d == "higher" else -0.35) * TEST_DISTS[name][1] * rnd.uniform(-0.6, 1.4)
                v = v0 + gain + rnd.gauss(0, TEST_DISTS[name][1] * 0.12)
                by_cat.setdefault(t.category_id, []).append((t.test_type_id, _round(v, t.unit)))
            for cat_id, vals in by_cat.items():
                a = m.Assessment(player_id=p.player_id, category_id=cat_id, assessment_date=day, entered_by_user_id=1)
                db.add(a)
                db.flush()
                for tid, v in vals:
                    db.add(m.AssessmentResult(assessment_id=a.assessment_id, test_type_id=tid, value=v))
    db.flush()

    # --- Rapsodo helper ---
    ids = {"rp": 0, "imp": 0, "gp": 0}

    def rapsodo(p, pitch_name, when, game_pitch_id=None, bullpen_id=None, import_id=None, n=1, fatigue=0.0):
        v, ivb, hb, spin, axis, eff, gyro, rh = SHAPES[pitch_name]
        side = 1 if p.throws == "R" else -1
        ids["rp"] += 1
        vel = v + p.demo["velo"] * (1 if pitch_name == "4-Seam Fastball" else 0.8) + rnd.gauss(0, 0.9) - fatigue
        db.add(m.RapsodoPitch(
            rapsodo_pitch_id=ids["rp"], player_id=p.player_id, import_id=import_id, pitch_number=n,
            game_pitch_id=game_pitch_id, bullpen_id=bullpen_id, pitch_type_id=ptype[pitch_name], pitch_date=when,
            raw_pitch_type=pitch_name, velocity=round(vel, 1),
            total_spin=round(spin + p.demo["spin"] + rnd.gauss(0, 70)), spin_efficiency=round(max(10, min(100, eff + rnd.gauss(0, 5))), 1),
            spin_axis_degrees=round((axis * (1 if side > 0 else -1) + rnd.gauss(0, 10)) % 360, 1),
            vb_trajectory=round(ivb + p.demo["spin"] / 120 + rnd.gauss(0, 1.4), 1),
            hb_trajectory=round(side * (hb + rnd.gauss(0, 1.5)), 1),
            gyro_degree=round(gyro + rnd.gauss(0, 6), 1), release_height=round(rh + (p.height_in - 74) * 0.04 + rnd.gauss(0, .08), 2),
            release_side=round(side * (1.7 + rnd.gauss(0, .1)), 2), release_extension=round(6.1 + rnd.gauss(0, .2), 2),
            release_angle=round(-1.5 + rnd.gauss(0, .6), 2), horizontal_angle=round(rnd.gauss(0, 1.2), 2)))

    # --- bullpens (3 per pitcher) ---
    bp_id = 0
    for p in pitchers:
        for k, day in enumerate([dt.date(2026, 9, 2), dt.date(2026, 9, 16), dt.date(2026, 9, 30)]):
            bp_id += 1
            db.add(m.BullpenSession(bullpen_id=bp_id, player_id=p.player_id, bullpen_type_id=1, session_date=day,
                                    created_by_user_id=1))
            ids["imp"] += 1
            db.add(m.RapsodoImport(import_id=ids["imp"], player_id=p.player_id, bullpen_id=bp_id, original_filename="demo.csv",
                                   file_hash=f"demo-bp-{bp_id}", uploaded_by_user_id=1, row_count=25, status="success"))
            db.flush()
            when = dt.datetime.combine(day, dt.time(15))
            for n in range(1, 26):
                name = rnd.choices(p.demo["arsenal"], weights=[USAGE[a] for a in p.demo["arsenal"]])[0]
                db.add(m.BullpenPitch(bullpen_id=bp_id, pitch_number=n, pitch_type_id=ptype[name], target_zone=rnd.randint(1, 9)))
                rapsodo(p, name, when, bullpen_id=bp_id, import_id=ids["imp"], n=n)
    db.flush()

    # --- games ---
    re_lookup = {(o, b, c): v for o, b, c, v in RE_DATA}

    def re_at(outs, bases, b, s):
        return re_lookup.get((outs, bases, f"{b}-{s}"))

    opp_ids = []
    for k, name in enumerate(OPPONENTS):
        db.add(m.OpponentTeam(team_id=k + 1, team_name=name, created_by_user_id=1))
    db.flush()
    opp_pid = 100
    opp_rosters = {}
    opp_pitchers = {}
    for k, name in enumerate(OPPONENTS):
        roster = []
        for j in range(9):
            opp_pid += 1
            db.add(m.OpponentPlayer(opponent_player_id=opp_pid, team_id=k + 1, player_name=f"{name.split()[0]} Hitter {j + 1}",
                                    jersey_number=j + 1, bats=rnd.choice("RRRL"), position=["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH"][j]))
            roster.append(opp_pid)
        opp_rosters[k + 1] = roster
        ps = []
        for j, hand in enumerate("RL"):
            opp_pid += 1
            db.add(m.OpponentPlayer(opponent_player_id=opp_pid, team_id=k + 1, player_name=f"{name.split()[0]} Pitcher {j + 1}",
                                    throws=hand, position="P"))
            ps.append((opp_pid, hand))
        opp_pitchers[k + 1] = ps
    db.flush()

    def zone_target(name, hand):
        side = 1 if hand == "R" else -1
        if name == "4-Seam Fastball":
            return rnd.choice([-1, 1]) * rnd.uniform(0.3, 0.8), rnd.uniform(2.2, 3.5)
        if name in ("Slider", "Cutter"):
            return -side * rnd.uniform(0.3, 0.9), rnd.uniform(1.4, 2.3)
        if name == "Curveball":
            return rnd.uniform(-0.5, 0.5), rnd.uniform(1.2, 2.0)
        return side * rnd.uniform(0.0, 0.6), rnd.uniform(1.3, 2.1)

    def pitch_event(x, z, b, s, quality, eye, con):
        inz = abs(x) <= 0.83 and 1.5 <= z <= 3.5
        r = rnd.random()
        if inz:
            swing = 0.68 + 0.12 * (s == 2)
            if r > swing:
                return "Called Strike"
            miss = 0.20 + 0.10 * quality - 0.10 * (con - .55)
            r2 = rnd.random()
            return "Swing and Miss" if r2 < miss else ("Foul" if r2 < miss + 0.38 else "In Play")
        chase = 0.30 + 0.10 * (s == 2) - 0.25 * (eye - .55)
        if r > chase:
            return "Ball"
        r2 = rnd.random()
        return "Swing and Miss" if r2 < 0.45 + 0.1 * quality else ("Foul" if r2 < 0.8 else "In Play")

    def in_play(pw, con, quality):
        r = rnd.random()
        hit_p = 0.30 + 0.25 * (con - .55) - 0.08 * quality
        if r < hit_p:
            r2 = rnd.random()
            if r2 < 0.05 + 0.10 * pw:
                return "HR", "Barreled/Squared Up", "Fly Ball"
            if r2 < 0.25 + 0.15 * pw:
                return "2B", "Solid", rnd.choice(["Line Drive", "Fly Ball"])
            return "1B", rnd.choice(["Solid", "Barreled/Squared Up", "Weak"]), rnd.choice(["Ground Ball", "Line Drive"])
        if r < hit_p + 0.03:
            return "E", "Weak", "Ground Ball"
        r2 = rnd.random()
        if r2 < 0.48:
            return "Groundout", rnd.choice(["Weak", "Jammed", "Off the End", "Solid"]), "Ground Ball"
        if r2 < 0.85:
            return "Flyout", rnd.choice(["Weak", "Off the End", "Solid"]), "Fly Ball"
        return "Lineout", "Solid", "Line Drive"

    def advance(bases, ab):
        b = [int(c) for c in bases]
        outs = runs = 0
        if ab in ("K", "K (Looking)", "Groundout", "Flyout", "Lineout"):
            outs = 1
            if ab == "Flyout" and b[2] and rnd.random() < 0.4:
                runs, b[2] = 1, 0
        elif ab in ("BB", "HBP"):
            if b[0]:
                if b[1]:
                    runs += b[2]
                    b[2] = 1
                b[1] = 1
            b[0] = 1
        elif ab in ("1B", "E"):
            runs += b[2] + (b[1] if rnd.random() < 0.6 else 0)
            b = [1, b[0], 0 if runs > b[2] else b[1]]
        elif ab == "2B":
            runs += b[1] + b[2] + (b[0] if rnd.random() < 0.4 else 0)
            b = [0, 1, 0 if runs >= b[0] + b[1] + b[2] else 1]
        elif ab == "HR":
            runs += sum(b) + 1
            b = [0, 0, 0]
        return outs, runs, "".join(str(x) for x in b)

    def spray(ab, bbt):
        if ab == "HR":
            return rnd.uniform(-60, 60), rnd.uniform(330, 390)
        depth = {"Ground Ball": (60, 130), "Line Drive": (150, 250), "Fly Ball": (220, 320)}.get(bbt, (100, 200))
        return rnd.uniform(-130, 130), rnd.uniform(*depth)

    game_days = [dt.date(2026, 9, d) for d in (5, 12, 13, 19, 20, 26, 27)] + [dt.date(2026, 10, 3)]
    rotation = list(range(len(pitchers)))
    for gi, day in enumerate(game_days):
        gid = gi + 1
        opp = gi % len(OPPONENTS) + 1
        starter = pitchers[rotation[(gi * 2) % len(pitchers)]]
        relievers = [pitchers[rotation[(gi * 2 + j) % len(pitchers)]] for j in (1, 3, 5)]
        game = m.Game(game_id=gid, season_id=1, opponent_team_id=opp, opponent_name=OPPONENTS[opp - 1], is_intrasquad=False,
                      game_date=day, is_home=gi % 2 == 0, status="Final", starting_pitcher_id=starter.player_id,
                      opponent_starting_pitcher_id=opp_pitchers[opp][gi % 2][0], created_by_user_id=1)
        db.add(game)
        lineup = rnd.sample(hitters, 9)
        for k, h in enumerate(lineup):
            db.add(m.GameLineupSlot(game_id=gid, squad="A", batting_order=k + 1, player_id=h.player_id,
                                    starting_position_id=h.position_id))
        db.flush()
        imports = {}
        seq = 0
        when = dt.datetime.combine(day, dt.time(13))
        score = {True: 0, False: 0}
        pitcher_now = starter
        pitch_count = 0
        changes = 0
        order = {True: 0, False: 0}
        for inning in range(1, 8):
            for batting in (False, True):
                if not batting and inning > 1 and (pitch_count > 70 or (inning >= 5 and changes == 0)) and changes < len(relievers):
                    pitcher_now = relievers[changes]
                    changes += 1
                    pitch_count = 0
                    db.add(m.PitchingChange(game_id=gid, player_id=pitcher_now.player_id, inning=inning, outs_at_entry=0,
                                            pitch_sequence_at_entry=seq + 1))
                outs, bases = 0, "000"
                opp_hand_p = opp_pitchers[opp][(gi + (inning > 4)) % 2]
                while outs < 3:
                    if batting:
                        h = lineup[order[True] % 9]
                        con, pw, eye = h.demo["con"], h.demo["pw"], h.demo["eye"]
                        quality = 0.0
                        arsenal = ["4-Seam Fastball", "Slider", "Changeup"]
                        thrower_hand = opp_hand_p[1]
                        cmd = 0.38
                    else:
                        opp_batter = opp_rosters[opp][order[False] % 9]
                        con, pw, eye = rnd.uniform(.45, .62), rnd.uniform(.3, .6), rnd.uniform(.42, .6)
                        quality = (pitcher_now.demo["velo"] / 4 + pitcher_now.demo["spin"] / 300) / 2
                        arsenal = pitcher_now.demo["arsenal"]
                        thrower_hand = pitcher_now.throws
                        cmd = pitcher_now.demo["cmd"]
                    order[batting] += 1
                    b = s = 0
                    n = 0
                    while True:
                        n += 1
                        seq += 1
                        name = rnd.choices(arsenal, weights=[USAGE[a] for a in arsenal])[0]
                        ix, iz = zone_target(name, thrower_hand)
                        fat = max(0.0, (pitch_count - 60) / 40) if not batting else 0.0
                        x, z = ix + rnd.gauss(0, cmd * 1.6), iz + rnd.gauss(0, cmd * 1.6)
                        ev = pitch_event(x, z, b, s, quality, eye, con)
                        b0, s0 = b, s
                        ends, ab, cq, bbt, bx, by = False, None, None, None, None, None
                        if ev == "Ball":
                            b += 1
                            if b == 4:
                                ends, ab = True, "BB"
                        elif ev in ("Called Strike", "Swing and Miss"):
                            s += 1
                            if s == 3:
                                ends, ab = True, "K" if ev == "Swing and Miss" else "K (Looking)"
                        elif ev == "Foul":
                            s = min(2, s + 1)
                        else:
                            ends = True
                            ab, cq, bbt = in_play(pw, con, quality)
                            bx, by = spray(ab, bbt)
                        if not ends and n >= 10:
                            ends, ev, ab, cq, bbt = True, "In Play", "Groundout", "Weak", "Ground Ball"
                            bx, by = spray(ab, bbt)
                        o_rec, runs, new_bases = advance(bases, ab) if ends else (0, 0, bases)
                        outs_after = outs + o_rec
                        if ends:
                            re_after = 0.0 if outs_after >= 3 else re_at(outs_after, new_bases, 0, 0)
                        else:
                            re_after = re_at(outs, bases, b, s)
                        re_before = re_at(outs, bases, b0, s0)
                        rv = round(re_after + runs - re_before, 3) if re_before is not None and re_after is not None else None
                        ids["gp"] += 1
                        gp = m.GamePitch(
                            game_pitch_id=ids["gp"], game_id=gid, pitch_sequence=seq, inning=inning, is_our_team_batting=batting,
                            our_player_id=h.player_id if batting else pitcher_now.player_id,
                            opponent_player_id=opp_hand_p[0] if batting else opp_batter,
                            opponent_hand=thrower_hand if batting else None,
                            batting_slot_id=None, pa_pitch_number=n, balls_before=b0, strikes_before=s0, outs_before=outs,
                            bases_before=bases, pitch_type_id=ptype[name],
                            intended_plate_x=round(ix, 3), intended_plate_z=round(iz, 3),
                            intended_zone=derive_old_zone(ix, iz), actual_plate_x=round(x, 3), actual_plate_z=round(z, 3),
                            pitch_zone=derive_old_zone(x, z), pitch_outcome=ev, contact_quality=cq, batted_ball_type=bbt,
                            batted_ball_x=round(bx, 1) if bx is not None else None, batted_ball_y=round(by, 1) if by is not None else None,
                            is_sword=False, ends_plate_appearance=ends, ab_outcome=ab,
                            outs_after=outs_after if ends else None, bases_after=new_bases if ends else None,
                            runs_scored_on_play=runs if ends else 0, unearned_runs_on_play=runs if ends and ab == "E" else 0,
                            re_before=re_before, re_after=re_after, run_value=rv)
                        db.add(gp)
                        if not batting:
                            pitch_count += 1
                            key = pitcher_now.player_id
                            if key not in imports:
                                ids["imp"] += 1
                                imports[key] = ids["imp"]
                                db.add(m.RapsodoImport(import_id=ids["imp"], player_id=key, game_id=gid, original_filename="demo.csv",
                                                       file_hash=f"demo-g{gid}-{key}", uploaded_by_user_id=1, row_count=0, status="success"))
                                db.flush()
                            rapsodo(pitcher_now, name, when, game_pitch_id=ids["gp"], import_id=imports[key], n=pitch_count, fatigue=fat)
                        if ends:
                            score[batting] += runs
                            outs, bases = outs_after, new_bases
                            break
        game.our_score, game.opponent_score = score[True], score[False]
        db.flush()

    # --- schedule, goals, availability (light touch so those pages aren't empty) ---
    etypes = {e.type_name: e.event_type_id for e in db.query(m.TeamEventType).all()}
    if etypes:
        first_type = next(iter(etypes.values()))
        for k in range(10):
            day = dt.date(2026, 10, 6) + dt.timedelta(days=k)
            title = ["Team lift", "Practice", "Bullpen day", "Practice", "Intrasquad"][k % 5]
            db.add(m.TeamScheduleEvent(team_id=1, event_type_id=etypes.get(title.split()[0], first_type), scheduled_date=day,
                                       title=title, created_by_user_id=1))
    statuses = {s.status_name: s.status_id for s in db.query(m.IDPStatus).all()}
    vj = tests.get("Vertical Jump (Jump Mat)")
    sprint = tests.get("30-Yard Sprint Time")
    for k, p in enumerate(players[:6]):
        t = vj if k % 2 == 0 else sprint
        if t is None:
            continue
        db.add(m.IDPGoal(player_id=p.player_id, category_id=t.category_id, target_test_type_id=t.test_type_id,
                         baseline_value=TEST_DISTS[t.test_name][0], target_value=TEST_DISTS[t.test_name][0] * (1.05 if t is vj else 0.97),
                         target_date=dt.date(2026, 12, 1), description=f"Improve {t.test_name.lower()} this fall",
                         status_id=statuses["In Progress"], created_by_user_id=1))
    db.commit()


_lock = threading.Lock()
_master = None


def _master_conn():
    global _master
    with _lock:
        if _master is None:
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            eng = create_engine("sqlite://", poolclass=StaticPool, creator=lambda: conn)
            m.Base.metadata.create_all(eng)
            db = sessionmaker(bind=eng, autoflush=False)()
            try:
                _populate(db)
            finally:
                db.close()
            _master = conn
        return _master


def build_master():
    """Build the demo team now (otherwise built on the first guest click)."""
    _master_conn()


def new_guest_db():
    """A private copy of the demo team for one guest: (sessionmaker, engine)."""
    src = _master_conn()
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    with _lock:
        src.backup(conn)
    eng = create_engine("sqlite://", poolclass=StaticPool, creator=lambda: conn)
    return sessionmaker(bind=eng, autoflush=False, autocommit=False), eng
