"""SmartPark game import (services/smartpark_import.py), against a synthetic
TrackMan-style file -- no real SmartPark export existed when this was built."""

import csv
import datetime as dt
import io

import pytest

from models import (Game, GamePitch, GameRunnerEvent, GameForcedHalfInningEnd, PitchingChange,
                    OpponentPlayer, SmartParkImport, SmartParkPitch)
from services import smartpark_import as sp

HEADER = ["PitchNo", "Date", "Time", "GameID", "Inning", "Top/Bottom", "PAofInning", "PitchofPA", "Outs", "Balls",
          "Strikes", "Pitcher", "PitcherId", "PitcherThrows", "PitcherTeam", "Batter", "BatterId", "BatterSide",
          "BatterTeam", "TaggedPitchType", "AutoPitchType", "PitchCall", "KorBB", "TaggedHitType", "PlayResult",
          "OutsOnPlay", "RunsScored", "RelSpeed", "SpinRate", "InducedVertBreak", "HorzBreak", "PlateLocHeight",
          "PlateLocSide", "ExitSpeed", "Angle", "Direction", "Distance", "BatSpeed", "MysteryColumn"]

US = "PIT_GOR"
THEM = "WAS_ICH"


def _game_rows():
    """(inning, half, pitcher, batter, [(call, korbb, hit, result, oop, runs)...]) per PA.
    Outs/count/PA numbers are filled in by _build_csv from the results, like a real tracker."""
    P = lambda c, **k: (c, k.get("kor", "Undefined"), k.get("hit", "Undefined"), k.get("res", "Undefined"),  # noqa: E731
                        k.get("oop", 0), k.get("runs", 0))
    return [
        # Top 1 -- we bat (away)
        (1, "Top", ("Opp RHP", THEM, "Right"), ("Smith, Jake", US, "Right"),
         [P("BallCalled"), P("StrikeCalled"), P("InPlay", hit="GroundBall", res="Single")]),
        (1, "Top", ("Opp RHP", THEM, "Right"), ("Lee, Cole", US, "Left"),
         [P("StrikeSwinging"), P("FoulBall"), P("StrikeCalled", kor="Strikeout")]),
        (1, "Top", ("Opp RHP", THEM, "Right"), ("Ruiz, Max", US, "Right"),
         [P("InPlay", hit="GroundBall", res="Out", oop=2)]),
        # Bottom 1 -- Holman pitching, then Ryan Other
        (1, "Bottom", ("Holman, Shane", US, "Right"), ("Opp Hitter 0", THEM, "Left"),
         [P("BallCalled"), P("BallCalled"), P("BallCalled"), P("BallCalled", kor="Walk")]),
        (1, "Bottom", ("Holman, Shane", US, "Right"), ("Opp Hitter 1", THEM, "Right"),
         [P("InPlay", hit="FlyBall", res="HomeRun", runs=2)]),
        (1, "Bottom", ("Other, Ryan", US, "Right"), ("Opp Hitter 2", THEM, "Right"),
         [P("StrikeSwinging"), P("StrikeSwinging"), P("StrikeSwinging", kor="Strikeout")]),
        (1, "Bottom", ("Other, Ryan", US, "Right"), ("Brand New Guy", THEM, "Left"),
         [P("InPlay", hit="FlyBall", res="Out", oop=1)]),
        (1, "Bottom", ("Other, Ryan", US, "Right"), ("Opp Hitter 4", THEM, "Right"),
         [P("InPlay", hit="LineDrive", res="Single")]),
        # caught stealing ends the half mid at-bat
        (1, "Bottom", ("Other, Ryan", US, "Right"), ("Opp Hitter 5", THEM, "Right"),
         [P("BallCalled")]),
        # Top 2
        (2, "Top", ("Opp RHP", THEM, "Right"), ("Ng, Ty", US, "Left"),
         [P("HitByPitch")]),
        (2, "Top", ("Opp RHP", THEM, "Right"), ("Smith, Jake", US, "Right"),
         [P("InPlay", hit="LineDrive", res="Double")]),
        # run scores on a wild pitch mid at-bat, then a groundout
        (2, "Top", ("Opp RHP", THEM, "Right"), ("Lee, Cole", US, "Left"),
         [P("BallCalled", runs=1), P("InPlay", hit="GroundBall", res="Out", oop=1)]),
    ]


def _build_csv(pas, file_outs_override=None):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(HEADER)
    n = 0
    outs = 0
    half = None
    pa_of_inning = 0
    for inning, tb, (pname, pteam, pthrows), (bname, bteam, bside), pitches in pas:
        if (inning, tb) != half:
            half, outs, pa_of_inning = (inning, tb), 0, 0
        pa_of_inning += 1
        balls = strikes = 0
        for k, (call, kor, hit, res, oop, runs) in enumerate(pitches, 1):
            n += 1
            w.writerow([n, "2026-10-30", f"18:{n:02d}:00", "G1", inning, tb, pa_of_inning, k, outs, balls, strikes,
                        pname, f"id-{pname}", pthrows, pteam, bname, f"id-{bname}", bside, bteam,
                        "Fastball" if k % 2 else "Slider", "Four-Seam", call, kor, hit, res, oop, runs,
                        90.1, 2250, 17.5, -8.2, 2.5, 0.3, 95 if call == "InPlay" else "", 12 if call == "InPlay" else "",
                        -20 if call == "InPlay" else "", 250 if call == "InPlay" else "", 70, "x"])
            if call in ("BallCalled",):
                balls += 1
            elif call in ("StrikeCalled", "StrikeSwinging") or (call == "FoulBall" and strikes < 2):
                strikes += 1
            outs += oop if call == "InPlay" else 0
            if kor == "Strikeout":
                outs += 1
    return out.getvalue().encode()


@pytest.fixture()
def game(db):
    g = Game(game_id=900, season_id=1, opponent_team_id=1, opponent_name="Washburn", is_intrasquad=False,
             is_home=False, game_date=dt.date(2026, 10, 30), status="Scheduled", created_by_user_id=1)
    db.add(g)
    db.flush()
    yield g
    db.rollback()


def test_column_check_and_parse():
    info = sp.check_file(_build_csv(_game_rows()))
    assert info["unmapped"] == ["MysteryColumn"]
    assert info["game_uid"] == "G1"
    assert info["dates"] == [dt.date(2026, 10, 30)]
    assert info["rows"][0]["raw_extra"] == {"MysteryColumn": "x"}


def test_missing_required_column_is_explained():
    with pytest.raises(sp.SmartParkValidationError, match="PitchCall|pitch_call"):
        sp.check_file(b"Inning,Top/Bottom,Balls,Strikes,Outs,Pitcher,Batter\n1,Top,0,0,0,A,B\n")


def test_name_key():
    assert sp.name_key("Curry, Ryker") == sp.name_key("Ryker Curry") == sp.name_key("ryker curry jr.") == "ryker curry"


def test_full_game_import(db, game):
    data = _build_csv(_game_rows())
    info, g, plan = sp.preview(db, data, game.game_id)
    assert plan["unmatched"] == {}
    assert "brand new guy" in plan["new_opponents"]

    imp = sp.import_game(db, data, "g1.csv", game.game_id, user_id=1)
    pitches = db.query(GamePitch).filter(GamePitch.game_id == game.game_id).order_by(GamePitch.pitch_sequence).all()
    rows = info["rows"]
    assert len(pitches) == len(rows) == imp.pitch_count

    # every pitch's count/outs match the file, and the half-inning chain agrees with the app's replay
    for p, r in zip(pitches, rows):
        assert (p.balls_before, p.strikes_before, p.outs_before) == (r["balls"], r["strikes"], r["outs"]), r
    assert not any("different half-inning" in w for w in plan["warnings"])

    first = pitches[0]
    assert first.is_our_team_batting and first.our_player_id == 11 and first.opponent_player_id == 200
    assert first.opponent_hand == "R" and first.pitch_type_id is not None
    assert pitches[2].ab_outcome == "1B" and pitches[2].batted_ball_type == "Ground Ball"
    assert pitches[5].ab_outcome == "K (Looking)"
    assert pitches[6].ab_outcome == "Double Play" and pitches[6].outs_after == 3

    holman = [p for p in pitches if not p.is_our_team_batting and p.our_player_id == 1]
    assert holman[3].ab_outcome == "BB" and holman[4].ab_outcome == "HR" and holman[4].runs_scored_on_play == 2
    new_guy = db.query(OpponentPlayer).filter(OpponentPlayer.player_name == "Brand New Guy").one()
    assert any(p.opponent_player_id == new_guy.opponent_player_id for p in pitches)

    assert db.query(PitchingChange).filter(PitchingChange.game_id == game.game_id, PitchingChange.player_id == 2).count() == 1
    assert game.starting_pitcher_id == 1
    events = db.query(GameRunnerEvent).filter(GameRunnerEvent.game_id == game.game_id).all()
    assert sorted((e.event_type, e.is_out) for e in events) == [("Out on Bases", True), ("Wild Pitch", False)]
    assert (game.our_score, game.opponent_score, game.status) == (1, 2, "Final")

    sps = db.query(SmartParkPitch).filter(SmartParkPitch.import_id == imp.import_id).all()
    assert len(sps) == len(rows) and all(s.game_pitch_id for s in sps)
    assert sps[0].rel_speed == 90.1 and sps[0].bat_speed == 70 and sps[0].pitcher_player_id is None
    assert sps[0].batter_player_id == 11

    with pytest.raises(sp.DuplicateSmartParkFile):
        sp.import_game(db, data, "g1.csv", game.game_id, user_id=1)

    sp.delete_import(db, imp.import_id)
    assert db.query(GamePitch).filter(GamePitch.game_id == game.game_id).count() == 0
    assert db.query(SmartParkImport).filter(SmartParkImport.import_id == imp.import_id).count() == 0
    assert game.status == "Scheduled"


def test_unmatched_player_blocks_until_linked(db, game):
    pas = _game_rows()
    pas[0] = (1, "Top", pas[0][2], ("Smyth, J.", US, "Right"), pas[0][4])
    data = _build_csv(pas)
    _, _, plan = sp.preview(db, data, game.game_id)
    assert [u["name"] for u in plan["unmatched"].values()] == ["Smyth, J."]
    with pytest.raises(sp.SmartParkError, match="Smyth"):
        sp.import_game(db, data, "g.csv", game.game_id, user_id=1)
    key, u = next(iter(plan["unmatched"].items()))
    sp.save_links(db, {key: (u["name"], 11)})
    _, _, plan = sp.preview(db, data, game.game_id)
    assert plan["unmatched"] == {}


def test_home_game_flips_sides(db, game):
    game.is_home = True  # PSU home -> the file's Bottom halves are ours
    _, _, plan = sp.preview(db, _build_csv(_game_rows()), game.game_id)
    assert any("Home/Away" in w for w in plan["warnings"])


def test_intrasquad_short_halves(db):
    g = Game(game_id=901, season_id=1, opponent_name="Squad B", is_intrasquad=True, game_date=dt.date(2026, 10, 30),
             status="Scheduled", created_by_user_id=1)
    db.add(g)
    db.flush()
    pas = [
        (1, "Top", ("Holman, Shane", US, "Right"), ("Smith, Jake", US, "Right"), [("InPlay", "Undefined", "GroundBall", "Single", 0, 0)]),
        # half ends after one batter (intrasquad rule)
        (1, "Bottom", ("Other, Ryan", US, "Right"), ("Lee, Cole", US, "Left"), [("StrikeCalled", "Undefined", "Undefined", "Undefined", 0, 0),
                                                                              ("InPlay", "Undefined", "FlyBall", "Out", 1, 0)]),
        (2, "Top", ("Holman, Shane", US, "Right"), ("Ruiz, Max", US, "Right"), [("InPlay", "Undefined", "LineDrive", "Double", 0, 0)]),
    ]
    data = _build_csv(pas)
    sp.import_game(db, data, "intra.csv", g.game_id, user_id=1)
    ps = db.query(GamePitch).filter(GamePitch.game_id == g.game_id).order_by(GamePitch.pitch_sequence).all()
    assert ps[0].is_our_team_batting and ps[0].our_player_id == 11 and ps[0].opponent_our_player_id == 1
    assert not ps[1].is_our_team_batting and ps[1].our_player_id == 2 and ps[1].opponent_our_player_id == 12
    assert [p.inning for p in ps] == [1, 2, 2, 3]
    assert db.query(GameForcedHalfInningEnd).filter(GameForcedHalfInningEnd.game_id == g.game_id).count() == 2
    assert g.squad_b_starting_pitcher_id == 1 and g.starting_pitcher_id == 2
    db.rollback()
