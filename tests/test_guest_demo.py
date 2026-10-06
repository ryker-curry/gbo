"""Guest demo (Oct 2026): the real app on a private, made-up team."""

import database
import demo_db
import models as m


def test_demo_db_is_private_copy():
    mk1, e1 = demo_db.new_guest_db()
    mk2, e2 = demo_db.new_guest_db()
    a, b = mk1(), mk2()
    try:
        assert a.query(m.Player).count() == len(demo_db.PITCHERS) + len(demo_db.HITTERS)
        assert a.query(m.GamePitch).count() > 1000 and a.query(m.RapsodoPitch).count() > 1000
        assert a.query(m.AssessmentResult).count() > 500
        for email in (demo_db.DEMO_COACH_EMAIL, demo_db.DEMO_PLAYER_EMAIL, demo_db.DEMO_HITTER_EMAIL):
            assert a.query(m.User).filter_by(email=email).one()
        # one guest's edit never shows up in another guest's copy
        a.query(m.Player).filter_by(player_id=1).update({"first_name": "Changed"})
        a.commit()
        assert b.query(m.Player).filter_by(player_id=1).one().first_name != "Changed"
    finally:
        a.close(); b.close(); e1.dispose(); e2.dispose()


def test_real_sessions_outside_guest():
    assert database.in_guest_demo() is False


def test_cache_keys_split_by_database():
    import gbo_cache
    calls = []

    @gbo_cache.cached("t_demo_split", tables={"players"})
    def f(db):
        calls.append(1)
        return db.query(m.Player).count()

    mk1, e1 = demo_db.new_guest_db()
    mk2, e2 = demo_db.new_guest_db()
    s1, s2 = mk1(), mk2()
    try:
        f(s1); f(s2)
        assert len(calls) == 2           # different databases never share a cached value
    finally:
        s1.close(); s2.close(); e1.dispose(); e2.dispose()
