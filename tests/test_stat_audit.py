"""Oct 2026 stat audit: run charging (runner events, inherited runners),
one pitching line everywhere, standard Chase %, RV per PA, PA grouping."""

import datetime as dt

import game_stats as gs
from analytics import hitter_insights as hi, player_report as pr
from models import Game, GamePitch, GameRunnerEvent, PitchType


def _mk(db, gid, seq, inn, pid, bases_b, bases_a, ends=False, ab=None, runs=0, ue=0, outs_b=0, outs_a=None, n=1,
        outcome="Ball"):
    p = GamePitch(game_pitch_id=900000 + gid * 1000 + seq, game_id=gid, pitch_sequence=seq, inning=inn,
                  is_our_team_batting=False, our_player_id=pid, opponent_player_id=None, pa_pitch_number=n,
                  balls_before=0, strikes_before=0, outs_before=outs_b, bases_before=bases_b, pitch_type_id=1,
                  pitch_outcome=outcome, ends_plate_appearance=ends, ab_outcome=ab,
                  outs_after=outs_a if outs_a is not None else (outs_b if ends else None),
                  bases_after=bases_a if ends else None, runs_scored_on_play=runs, unearned_runs_on_play=ue)
    db.add(p)
    return p


def _game(db, gid):
    db.add(Game(game_id=gid, season_id=1, opponent_name="Audit", is_intrasquad=False,
                game_date=dt.date(2026, 10, 1), status="Final", our_score=0, opponent_score=3))


def test_runner_event_runs_and_inherited_runners(db):
    gid = 501
    _game(db, gid)
    # pitcher 1 walks two (runners on 1st, 2nd)
    _mk(db, gid, 1, 1, 1, "000", "100", ends=True, ab="BB", outcome="Ball")
    _mk(db, gid, 2, 1, 1, "100", "110", ends=True, ab="BB", outcome="Ball")
    # pitcher 2 comes in; a wild pitch moves both up (2nd, 3rd), a passed ball scores the lead runner
    _mk(db, gid, 3, 1, 2, "110", None)
    db.add(GameRunnerEvent(game_id=gid, pitch_sequence_after=3, is_our_team_batting=False, event_type="Wild Pitch",
                           from_base=2, to_base=3, is_out=False))
    db.add(GameRunnerEvent(game_id=gid, pitch_sequence_after=3, is_our_team_batting=False, event_type="Wild Pitch",
                           from_base=1, to_base=2, is_out=False))
    _mk(db, gid, 4, 1, 2, "011", None)
    db.add(GameRunnerEvent(game_id=gid, pitch_sequence_after=4, is_our_team_batting=False, event_type="Passed Ball",
                           from_base=3, to_base=4, is_out=False))
    # single scores the other inherited runner, batter on 1st (pitcher 2's own runner)
    _mk(db, gid, 5, 1, 2, "010", "100", ends=True, ab="1B", runs=1, outcome="In Play")
    db.commit()
    ch = gs.game_run_charges(db, [gid])
    assert ch[(gid, 1)]["runs"] == 2 and ch[(gid, 1)]["er"] == 1      # both inherited runners are his; PB run unearned
    assert ch[(gid, 2)]["runs"] == 0
    p1 = db.query(GamePitch).filter(GamePitch.game_id == gid, GamePitch.our_player_id == 1).all()
    p2 = db.query(GamePitch).filter(GamePitch.game_id == gid, GamePitch.our_player_id == 2).all()
    assert gs.pitching_line_for(db, 1, p1)["Runs Allowed"] == 2
    assert gs.pitching_line_for(db, 1, p1)["ER Allowed"] == 1
    assert gs.pitching_line_for(db, 2, p2)["Runs Allowed"] == 0       # the single's run moved off him


def test_every_page_uses_the_same_pitching_line(db):
    names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
    for pid in (1, 2, 3):
        ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == pid,
                                        GamePitch.game_id < 100).all()
        line = gs.pitching_line_for(db, pid, ps)
        b = pr.stat_bundle(ps, names, db)
        assert b["outs"] == round(line["IP (decimal)"] * 3)
        assert b["runs"] == line["Runs Allowed"] and b["era"] == line["ERA"] and b["whip"] == line["WHIP"]


def test_chase_is_standard_everywhere(db):
    import plate_discipline as pd
    ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == 11).all()
    assert hi.core_metrics(ps)["Chase %"] == pd.compute_hitter_discipline(ps)["Chase %"]


def test_rv_per_pa_divides_by_pa(db):
    ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == 12).all()
    line = gs.compute_batting_line(ps)
    assert abs(line["Avg RV/PA"] - line["Total RV"] / line["PA"]) < 0.002


def test_partial_pa_not_glued_to_next(db):
    from types import SimpleNamespace as P
    ps = [P(game_id=1, pitch_sequence=1, pa_pitch_number=1, ends_plate_appearance=False),   # inning ended on a CS
          P(game_id=1, pitch_sequence=9, pa_pitch_number=1, ends_plate_appearance=False),
          P(game_id=1, pitch_sequence=10, pa_pitch_number=2, ends_plate_appearance=True)]
    assert [len(pa) for pa in gs._group_into_plate_appearances(ps)] == [1, 2]
