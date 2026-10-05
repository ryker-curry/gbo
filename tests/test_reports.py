"""Every report builds and renders on the fake season without crashing."""

import datetime as dt

import pytest

from analytics import hitter_report, player_report, team_report, weekly_report, trends
from models import Game
from visualizations import (hitter_report_sheet, meeting_report_sheet, team_report_email, weekly_report_sheet)


def _games(db):
    return db.query(Game).filter(Game.is_intrasquad.is_(False)).order_by(Game.game_date).all()


@pytest.mark.parametrize("pid", [1, 2, 3])
def test_pitcher_meeting_report(db, pid):
    g = _games(db)[pid - 1]  # seed rotates starters 1, 2, 3
    for rep in (player_report.game_report(db, pid, g.game_id), player_report.season_report(db, pid, 1),
                player_report.range_report(db, pid, [x.game_id for x in _games(db)[:2]], "Series")):
        assert rep is not None
        assert "<" in meeting_report_sheet.render_sheet(rep)


@pytest.mark.parametrize("pid", [11, 12, 13, 14])
def test_hitter_meeting_report(db, pid):
    g = _games(db)[0]
    for rep in (hitter_report.game_report(db, pid, g.game_id), hitter_report.season_report(db, pid, 1),
                hitter_report.range_report(db, pid, [x.game_id for x in _games(db)[:2]], "Series")):
        assert rep is not None
        assert "<" in hitter_report_sheet.render_sheet(rep)


@pytest.mark.parametrize("pid", [1, 11])
def test_weekly_report(db, pid):
    rep = weekly_report.build_any(db, pid, dt.date(2026, 9, 7))
    assert rep is not None
    assert weekly_report_sheet.render_sheet(rep)
    assert weekly_report_sheet.render_email(rep)
    assert weekly_report_sheet.email_subject(rep)


def test_team_report_and_email(db):
    games = _games(db)
    for scope in ([games[0]], games[:2], games):
        rep = team_report.build(db, scope)
        team_report.standouts(rep)
    assert team_report_email.render_email(team_report.build(db, [games[0]]), games[0])


@pytest.mark.parametrize("pid,is_pitcher", [(1, True), (11, False)])
def test_trends(db, pid, is_pitcher):
    from models import GamePitch
    if is_pitcher:
        ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False), GamePitch.our_player_id == pid).all()
    else:
        ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == pid).all()
    team = trends.team_pitches_in_range(db, dt.date(2026, 9, 1), dt.date(2026, 9, 30), pitching=is_pitcher)
    for by in ("game", "week"):
        trends.build(db, ps, team, is_pitcher, by=by)
    if is_pitcher:
        trends.velo_stuff(db, pid, dt.date(2026, 9, 1), dt.date(2026, 9, 30))


@pytest.mark.parametrize("pid", [11, 12, 13, 14])
def test_hitter_insights(db, pid):
    from analytics import hitter_insights as hi, hitter_hot_zones
    from models import GamePitch
    ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == pid).all()
    hi.swing_decisions(ps)
    hi.attack_takeaways(hi.attack_profile(db, ps))
    hi.pitch_type_takeaways(hi.pitch_type_results(db, ps))
    hi.first_pitch_two_strike(ps)
    hi.count_table(db, ps)
    hi.location_grid(db, ps)
    hi.count_tendencies(db, ps)
    hitter_hot_zones.panels(db, ps)


def test_hitting_leaderboard(db):
    from analytics import hitting_leaderboard, hitter_insights, league_baselines
    from modules import hitting_leaderboard as page
    from models import GamePitch
    rows = hitting_leaderboard.rows(db)
    assert {r["player"].player_id for r in rows} == {11, 12, 13, 14}
    jake = next(r for r in rows if r["player"].player_id == 11)
    ps = db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(True), GamePitch.our_player_id == 11).all()
    ps += db.query(GamePitch).filter(GamePitch.is_our_team_batting.is_(False), GamePitch.opponent_our_player_id == 11).all()
    assert jake["Chase %"] == hitter_insights.core_metrics(ps)["Chase %"]
    assert jake["OPS+"] == league_baselines.hitting_plus({"OBP": jake["OBP"], "SLG": jake["SLG"]})["OPS+"]
    # every stat on the page exists on the rows
    assert all(k in jake for k, *_r in page.STAT_META)
    # min-PA: unqualified hitters sort last even with the best number
    fake = [{"Hitter": "a", "PA": 3, "AVG": .667}, {"Hitter": "b", "PA": 40, "AVG": .300}, {"Hitter": "c", "PA": 40, "AVG": None}]
    assert [r["Hitter"] for r in page.sort_rows(fake, "AVG", 10)] == ["b", "c", "a"]
    assert [r["Hitter"] for r in page.sort_rows(fake, "AVG", 0)] == ["a", "b", "c"]
    assert page.fmt_stat("AVG", .3) == ".300" and page.fmt_stat("OPS+", 89.0) == "89"
    # date range narrows it
    import datetime as dt
    assert all(r["PA"] <= jake["PA"] for r in hitting_leaderboard.rows(db, dt.date(2026, 9, 19), dt.date(2026, 9, 30)))
