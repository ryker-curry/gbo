"""
A small, fixed fake season for GBO's tests (Oct 2026). Pure SQLite in
memory -- never touches Supabase. Deterministic (fixed random seed).

What's in it:
  - 4 pitch types, 1 season, statuses, the "Baseball Performance" category
  - 3 of our pitchers (R, R, L) and 4 of our hitters (R, L, R, S)
  - an opponent team with named hitters (bats set) and two named pitchers
  - 6 external games (we pitch AND bat in each, opponent pitcher picked on
    our at-bats) + 1 intrasquad; every game Final with a score
  - Rapsodo readings with full shape data for every pitch our staff threw
    (enough per type to fit Stuff+ models), plus bullpen sessions
  - one inning that ends on a caught stealing mid at-bat
"""

import random
import datetime as dt

from models import (Base, Season, PitchType, Player, OpponentTeam, OpponentPlayer, Game, GamePitch,
                    RapsodoPitch, RapsodoImport, BullpenSession, BullpenType, IDPStatus, AssessmentCategory,
                    Organization, Role, User, GameRunnerEvent)
from strike_zone import derive_old_zone

TYPES = ["4-Seam Fastball", "Changeup", "Slider", "Curveball"]
SHAPE = {  # velo, ivb, hb, spin, axis, eff, gyro
    1: (87, 15, 9, 2200, 20, 92, 15), 2: (79, 6, 13, 1700, 60, 85, 25),
    3: (77, 1, -10, 2350, 270, 35, 65), 4: (73, -12, -7, 2450, 200, 70, 40),
}
GAME_DATES = [dt.date(2026, 9, d) for d in (5, 6, 12, 13, 19, 26)]


def _nullable(engine):
    for t in Base.metadata.tables.values():
        for c in t.columns:
            if not c.primary_key:
                c.nullable = True
    Base.metadata.create_all(engine)


def build(db, engine):
    _nullable(engine)
    rnd = random.Random(2026)
    db.add(Organization(organization_id=1, organization_name="Pitt State"))
    db.add(Season(season_id=1, season_name="2026-2027"))
    for i, n in enumerate(TYPES, 1):
        db.add(PitchType(pitch_type_id=i, type_name=n, display_order=i))
    for i, n in enumerate(["Not Started", "In Progress", "Completed", "On Hold"], 1):
        db.add(IDPStatus(status_id=i, status_name=n, display_order=i))
    db.add(AssessmentCategory(category_id=17, category_name="Baseball Performance"))
    db.add(Role(role_id=1, role_name="Head Coach"))
    db.add(User(user_id=1, organization_id=1, email="coach@example.com", first_name="Head", last_name="Coach",
                role_id=1, active=True))
    pitchers = [(1, "Shane", "Holman", "R"), (2, "Ryan", "Other", "R"), (3, "Lefty", "Lou", "L")]
    hitters = [(11, "Jake", "Smith", "R"), (12, "Cole", "Lee", "L"), (13, "Max", "Ruiz", "R"), (14, "Ty", "Ng", "S")]
    for pid, f, l, t in pitchers:
        db.add(Player(player_id=pid, first_name=f, last_name=l, throws=t, bats=t, is_pitcher=True, active=True))
    for pid, f, l, b in hitters:
        db.add(Player(player_id=pid, first_name=f, last_name=l, throws="R", bats=b, is_pitcher=False, active=True))
    db.add(OpponentTeam(team_id=1, team_name="Washburn"))
    opp_hitters = []
    for i in range(9):
        opp_hitters.append(100 + i)
        db.add(OpponentPlayer(opponent_player_id=100 + i, team_id=1, player_name=f"Opp Hitter {i}",
                              bats="L" if i % 3 == 0 else "R"))
    db.add(OpponentPlayer(opponent_player_id=200, team_id=1, player_name="Opp RHP", throws="R"))
    db.add(OpponentPlayer(opponent_player_id=201, team_id=1, player_name="Opp LHP", throws="L"))
    db.add(BullpenType(bullpen_type_id=1, type_name="Bullpen"))
    db.flush()

    ids = {"gp": 0, "rp": 0, "imp": 0}

    def add_pitch(gid, seq, inn, batting, our_pid, opp_pid, opp_our, n, b, s, outs, t, x, z, out, ends, ab,
                  runs=0, hand=None):
        ids["gp"] += 1
        quality = None
        bbt = None
        if out == "In Play":
            quality = rnd.choice(["Barreled/Squared Up", "Solid", "Weak", "Jammed", "Off the End"])
            bbt = rnd.choice(["Ground Ball", "Fly Ball", "Line Drive"])
        db.add(GamePitch(game_pitch_id=ids["gp"], game_id=gid, pitch_sequence=seq, inning=inn,
                         is_our_team_batting=batting, our_player_id=our_pid, opponent_player_id=opp_pid,
                         opponent_our_player_id=opp_our, opponent_hand=hand, pa_pitch_number=n,
                         balls_before=b, strikes_before=s, outs_before=outs, bases_before="000",
                         pitch_type_id=t, pitch_outcome=out, ends_plate_appearance=ends, ab_outcome=ab,
                         outs_after=(outs + (1 if ab in ("Groundout", "Flyout", "Lineout", "K", "K (Looking)") else 0)) if ends else None,
                         bases_after="000" if ends else None, runs_scored_on_play=runs, unearned_runs_on_play=0,
                         intended_plate_x=0.0, intended_plate_z=2.5, intended_zone=5,
                         actual_plate_x=x, actual_plate_z=z, pitch_zone=derive_old_zone(x, z), is_sword=False,
                         contact_quality=quality, batted_ball_type=bbt,
                         run_value=(0.05 if out == "Ball" else -0.06 if out in ("Called Strike", "Swing and Miss")
                                    else -0.02 if out == "Foul" else (0.45 if ab in ("1B", "2B", "HR") else -0.25))))
        return ids["gp"]

    def add_rapsodo(pid, gp_id, t, when, import_id=None, bullpen_id=None):
        ids["rp"] += 1
        v, ivb, hb, spin, axis, eff, gyro = SHAPE[t]
        bump = {1: 1.0, 2: -1.0, 3: 0.0}[pid]
        db.add(RapsodoPitch(rapsodo_pitch_id=ids["rp"], player_id=pid, game_pitch_id=gp_id, bullpen_id=bullpen_id,
                            import_id=import_id, pitch_type_id=t, pitch_date=when,
                            velocity=v + bump + rnd.gauss(0, 1.0), vb_trajectory=ivb + rnd.gauss(0, 2),
                            hb_trajectory=hb + rnd.gauss(0, 2), total_spin=spin + rnd.gauss(0, 100),
                            spin_axis_degrees=(axis + rnd.gauss(0, 12)) % 360,
                            spin_efficiency=max(10, min(100, eff + rnd.gauss(0, 6))),
                            gyro_degree=gyro + rnd.gauss(0, 8), release_height=5.7 + rnd.gauss(0, .1),
                            release_side=1.8 + rnd.gauss(0, .1)))

    def outcome(x, z):
        inz = abs(x) <= 0.83 and 1.5 <= z <= 3.5
        r = rnd.random()
        if inz:
            return "Called Strike" if r < .28 else "Swing and Miss" if r < .42 else "Foul" if r < .62 else "In Play"
        return "Ball" if r < .7 else "Swing and Miss" if r < .85 else "Foul"

    def half_inning(gid, seq, inn, batting, our_pids, opp_ids, opp_our_ids, hand, rap_when, imp, cs_inning=False):
        outs = 0
        order = 0
        while outs < 3:
            b = s = 0
            n = 0
            batter = order % 9
            order += 1
            while True:
                n += 1
                seq += 1
                b0, s0 = b, s  # count BEFORE this pitch
                t = rnd.choice([1, 1, 1, 2, 3, 4])
                x, z = rnd.gauss(0, 0.75), rnd.gauss(2.45, 0.8)
                out = outcome(x, z)
                ends, ab = False, None
                if out == "Ball":
                    b += 1
                elif out in ("Called Strike", "Swing and Miss"):
                    s += 1
                elif out == "Foul" and s < 2:
                    s += 1
                runs = 0
                if out == "In Play":
                    ends = True
                    ab = rnd.choice(["1B", "2B", "HR", "Groundout", "Flyout", "Lineout", "Groundout"])
                    runs = 1 if ab == "HR" else 0
                elif b == 4:
                    ends, ab = True, "BB"
                elif s == 3:
                    ends, ab = True, ("K" if out == "Swing and Miss" else "K (Looking)")
                if batting:
                    our_pid = our_pids[batter % len(our_pids)]
                    opp_pid = None if opp_our_ids else (200 if hand == "R" else 201)
                    opp_our = opp_our_ids[0] if opp_our_ids else None
                else:
                    our_pid = our_pids[0]
                    opp_pid = None if opp_our_ids else opp_ids[batter]
                    opp_our = opp_our_ids[batter % len(opp_our_ids)] if opp_our_ids else None
                gp = add_pitch(gid, seq, inn, batting, our_pid, opp_pid, opp_our, n, b0, s0, outs,
                               t, x, z, out, ends, ab, runs, hand)
                if not batting or opp_our_ids:
                    pitcher = our_pids[0] if not batting else opp_our_ids[0]
                    add_rapsodo(pitcher, gp, t, rap_when, import_id=imp)
                if cs_inning and outs == 2 and n == 2 and not ends:
                    db.add(GameRunnerEvent(game_id=gid, pitch_sequence_after=seq, is_our_team_batting=batting,
                                           event_type="Caught Stealing", from_base=1, to_base=2, is_out=True,
                                           created_at=dt.datetime(2026, 9, 1)))
                    return seq, True
                if ends:
                    if ab in ("Groundout", "Flyout", "Lineout", "K", "K (Looking)"):
                        outs += 1
                    break
        return seq, False

    gid = 0
    for gi, d in enumerate(GAME_DATES):
        gid += 1
        db.add(Game(game_id=gid, season_id=1, opponent_team_id=1, opponent_name="Washburn", is_intrasquad=False,
                    is_home=gi % 2 == 0, game_date=d, status="Final", our_score=rnd.randint(2, 9),
                    opponent_score=rnd.randint(1, 8)))
        ids["imp"] += 1
        db.add(RapsodoImport(import_id=ids["imp"], player_id=1, game_id=gid, original_filename="g.csv",
                             file_hash=str(gid), uploaded_by_user_id=1, row_count=0, status="success"))
        db.flush()
        seq = 0
        when = dt.datetime.combine(d, dt.time(18))
        starter = [1, 2, 3][gi % 3]
        for inn in range(1, 6):
            seq, _ = half_inning(gid, seq, inn, False, [starter if inn <= 3 else [2, 3, 1][gi % 3]], opp_hitters,
                                 None, None, when, ids["imp"])
            seq, _ = half_inning(gid, seq, inn, True, [11, 12, 13, 14], None, None, "R" if gi % 2 == 0 else "L",
                                 when, ids["imp"], cs_inning=(gi == 0 and inn == 2))
    # intrasquad: Holman pitching to our hitters
    gid += 1
    d = dt.date(2026, 9, 29)
    db.add(Game(game_id=gid, season_id=1, opponent_name="Squad B", is_intrasquad=True, game_date=d, status="Final",
                our_score=0, opponent_score=0))
    db.flush()
    seq = 0
    for inn in range(1, 3):
        seq, _ = half_inning(gid, seq, inn, False, [1], None, [11, 12, 13, 14], None,
                             dt.datetime.combine(d, dt.time(15)), None)
    # bullpens with Rapsodo for pitcher 1 (velo trend)
    for k, d in enumerate([dt.date(2026, 9, 8), dt.date(2026, 9, 15), dt.date(2026, 9, 22)]):
        db.add(BullpenSession(bullpen_id=k + 1, player_id=1, bullpen_type_id=1, session_date=d))
        db.flush()
        for _ in range(20):
            add_rapsodo(1, None, rnd.choice([1, 1, 2, 3]), dt.datetime.combine(d, dt.time(10)), bullpen_id=k + 1)
    db.commit()
    return {"pitchers": [p[0] for p in pitchers], "hitters": [h[0] for h in hitters], "games": gid}
