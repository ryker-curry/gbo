"""Nov 2026: runs scored / RBI / SB / CS (run_scorers.py)."""

from types import SimpleNamespace as NS

import run_scorers as rs


def _pa(seq, batter, ab, before, after, outs_after=0, runs=0, inning=1, gpid=None):
    return NS(game_pitch_id=gpid or seq, game_id=1, pitch_sequence=seq, inning=inning, is_our_team_batting=True,
              batting_squad=None, our_player_id=batter, opponent_our_player_id=None, opponent_player_id=None,
              ends_plate_appearance=True, ab_outcome=ab, bases_before=before, bases_after=after,
              outs_after=outs_after, runs_scored_on_play=runs)


def _ev(after, frm, to, typ="Stolen Base", out=False, pid=None, n=1):
    return NS(game_id=1, pitch_sequence_after=after, from_base=frm, to_base=to, is_out=out, our_player_id=pid,
              opponent_player_id=None, event_type=typ, created_at=n, runner_event_id=n)


def _who(res):
    return [w for _k, _r, w, _i in res["scored"]]


def test_single_scores_lead_runner():
    ps = [_pa(1, 11, "2B", "000", "010"), _pa(2, 12, "1B", "010", "100", runs=1)]
    assert _who(rs.walk_game(ps)) == [("our", 11)]


def test_home_run_scores_runners_then_batter():
    ps = [_pa(1, 11, "1B", "000", "100"), _pa(2, 12, "BB", "100", "110"), _pa(3, 13, "HR", "110", "000", runs=3)]
    assert _who(rs.walk_game(ps)) == [("our", 11), ("our", 12), ("our", 13)]


def test_runner_event_home_and_steal():
    ps = [_pa(1, 11, "3B", "000", "001")]
    res = rs.walk_game(ps, [_ev(1, 3, 4, typ="Wild Pitch")])
    assert _who(res) == [("our", 11)]


def test_confirmed_scorers_override_and_mismatch_falls_back():
    ps = [_pa(1, 11, "1B", "000", "100"), _pa(2, 12, "1B", "100", "110"),
          _pa(3, 13, "2B", "110", "011", runs=1, gpid=99)]
    assert _who(rs.walk_game(ps)) == [("our", 11)]          # guess: lead runner (11, on 2nd)
    # coach says the trail runner (12, from 1st) scored and 11 held at 3rd
    res = rs.walk_game(ps, confirmed={99: [("our", 12)]})
    assert _who(res) == [("our", 12)]
    assert res["runners"] == {3: ("our", 11), 2: ("our", 13)}
    # count no longer matches runs on the play -> ignored
    assert _who(rs.walk_game(ps, confirmed={99: [("our", 11), ("our", 12)]})) == [("our", 11)]


def test_forced_end_sweeps_runners():
    ps = [_pa(1, 11, "1B", "000", "100")]
    fe = NS(pitch_sequence_after=1, forced_end_id=5, runs_scored=1)
    assert _who(rs.walk_game(ps, forced_ends=[fe])) == [("our", 11)]
    fe.runs_scored = 0                                      # runners just left on
    assert _who(rs.walk_game(ps, forced_ends=[fe])) == []


def test_rbi_rule():
    assert rs.rbi_on_play(_pa(1, 1, "1B", "001", "100", runs=1)) == 1
    assert rs.rbi_on_play(_pa(1, 1, "BB", "111", "111", runs=1)) == 1
    assert rs.rbi_on_play(_pa(1, 1, "Sac Fly", "001", "000", outs_after=1, runs=1)) == 1
    assert rs.rbi_on_play(_pa(1, 1, "E", "001", "100", runs=1)) == 0
    assert rs.rbi_on_play(_pa(1, 1, "Double Play", "101", "000", outs_after=2, runs=1)) == 0


def test_seeded_lines(seeded):
    db, info = seeded
    from models import GamePitch, GameRunnerEvent
    import game_stats
    import stat_line
    import gbo_cache
    gbo_cache.clear()
    # every run in the ledger lines up with the runs recorded on plays/events/forced ends
    ledger = rs.run_scorer_ledger.uncached(db)
    play_runs = sum(p.runs_scored_on_play or 0 for p in db.query(GamePitch).all()
                    if p.ends_plate_appearance and p.ab_outcome not in (None, "No Result"))
    ev_runs = sum(1 for e in db.query(GameRunnerEvent).all() if not e.is_out and e.to_base == 4)
    assert len([r for r in ledger if r[2] in ("pitch", "event")]) == play_runs + ev_runs
    # every hitter's line has the new keys and the stat line has no dashes there
    hitters = {p.our_player_id for p in db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True)).all()}
    total_r = 0
    for pid in hitters:
        line = game_stats.batting_line_for(db, pid, game_stats.get_batting_pitches(db, pid))
        assert {"R", "RBI", "SB", "CS"} <= set(line)
        total_r += line["R"]
        rows, career, _ids = stat_line.batting_stat_rows(db, pid)
        assert career["R"] != stat_line.DASH and career["RBI"] != stat_line.DASH
    our_runs = sum(1 for r in ledger if r[1] and r[1][0] == "our")
    assert total_r <= our_runs
    cs_events = db.query(GameRunnerEvent).filter(GameRunnerEvent.event_type == "Caught Stealing").all()
    for e in cs_events:
        anchor = db.query(GamePitch).filter(GamePitch.game_id == e.game_id,
                                            GamePitch.pitch_sequence == e.pitch_sequence_after).first()
        if anchor is not None:
            pitcher = anchor.our_player_id if not anchor.is_our_team_batting else anchor.opponent_our_player_id
            line = game_stats.pitching_line_for(db, pitcher, game_stats.get_pitching_pitches(db, pitcher))
            assert line["CS Allowed"] >= 1
