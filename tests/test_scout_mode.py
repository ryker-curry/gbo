"""Scout login (Oct 2026): real data through a separate engine, names hidden,
read-only."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scout_mode
from models import Player, OpponentPlayer, User, GamePitch


@pytest.fixture(scope="module")
def dbs(tmp_path_factory):
    from tests import seed
    path = tmp_path_factory.mktemp("scout") / "gbo.db"
    real = create_engine(f"sqlite:///{path}")
    db = sessionmaker(bind=real)()
    seed.build(db, real)
    db.close()
    scout_mode.use_engine(create_engine(f"sqlite:///{path}"))
    scout_mode.refresh_aliases()
    return sessionmaker(bind=real), scout_mode.maker()


def test_names_hidden_only_for_scouts(dbs):
    real_maker, scout_maker = dbs
    real, scout = real_maker(), scout_maker()
    try:
        real_names = {f"{p.first_name} {p.last_name}" for p in real.query(Player).all()}
        masked = scout.query(Player).order_by(Player.player_id).all()
        assert all(p.first_name in ("Pitcher", "Hitter") and p.last_name.isdigit() for p in masked)
        assert not ({f"{p.first_name} {p.last_name}" for p in masked} & real_names)
        assert all(p.jersey_number is None and p.email is None for p in masked)
        assert all(o.player_name.startswith("Opp. Player") for o in scout.query(OpponentPlayer).all())
        assert all(u.first_name == "Staff" for u in scout.query(User).all())
        # joined-loaded players are masked too
        gp = scout.query(GamePitch).filter(GamePitch.our_player_id.isnot(None)).first()
        assert gp.our_player.first_name in ("Pitcher", "Hitter") and gp.notes is None
        # the real session still sees real names
        assert {f"{p.first_name} {p.last_name}" for p in real.query(Player).all()} == real_names
    finally:
        real.close()
        scout.close()


def test_aliases_are_stable(dbs):
    _real, scout_maker = dbs
    a = [(p.player_id, p.first_name, p.last_name) for p in scout_maker().query(Player).all()]
    scout_mode.refresh_aliases()
    b = [(p.player_id, p.first_name, p.last_name) for p in scout_maker().query(Player).all()]
    assert sorted(a) == sorted(b)


def test_read_only(dbs):
    _real, scout_maker = dbs
    s = scout_maker()
    try:
        p = s.query(Player).first()
        p.first_name = "Changed"
        with pytest.raises(Exception) as e:
            s.commit()
        assert "read-only" in str(e.value)
    finally:
        s.rollback()
        s.close()


def test_login_check(monkeypatch):
    assert scout_mode.matches("Guest@GBO.app ", "Password")
    assert not scout_mode.matches("guest@gbo.app", "password")
    monkeypatch.setenv("GBO_SCOUT_PASSWORD", "off")
    assert not scout_mode.matches("guest@gbo.app", "off")
