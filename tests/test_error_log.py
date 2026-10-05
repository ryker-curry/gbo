import sys
from datetime import date, datetime

import pytest
from sqlalchemy.orm import sessionmaker

import error_log
from models import AppError


@pytest.fixture
def logdb(db, monkeypatch):
    import database
    Session = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(database, "get_session", lambda: Session())
    from scripts import send_error_summary
    monkeypatch.setattr(send_error_summary, "get_session", lambda: Session())
    sent = []
    monkeypatch.setattr(error_log, "_send", lambda msg: sent.append(msg))
    monkeypatch.setattr(error_log.threading, "Thread",
                        lambda target, args=(), kwargs=None, daemon=None: type("T", (), {"start": lambda self: target(*args, **(kwargs or {}))})())
    db.query(AppError).delete()
    db.commit()
    return db, sent


def _boom():
    return {}["missing"]


def _fire(info=(11, "Player", "Hitter Profile")):
    try:
        _boom()
    except KeyError:
        return error_log.record(*sys.exc_info(), output_name="hp-overview", info=info)


def test_record_and_burst_alert(logdb):
    db, sent = logdb
    for _ in range(4):
        assert _fire() is not None
    assert not sent
    _fire()                                     # 5th in an hour -> one alert
    assert len(sent) == 1 and sent[0]["To"] == error_log.alert_email()
    _fire()                                     # 6th -> no second alert this hour
    assert len(sent) == 1
    rows = db.query(AppError).all()
    assert len(rows) == 6 and len({r.fingerprint for r in rows}) == 1
    r = rows[0]
    assert r.error_type == "KeyError" and r.page == "Hitter Profile" and "test_error_log.py" in r.location


def test_daily_summary(logdb):
    db, sent = logdb
    _fire()
    _fire(info=(12, "Player", "Trends"))
    from scripts import send_error_summary
    assert send_error_summary.run(datetime.utcnow().date(), dry_run=True) == 2
    msg = error_log.summary_email(db.query(AppError).all(), date.today())
    assert "2 errors" in msg["Subject"] and "2 users" in msg.get_content()
    assert send_error_summary.run(date(2020, 1, 1)) == 0      # clean day -> nothing sent
    assert not sent


def test_default_recipient_is_ryker(monkeypatch):
    monkeypatch.delenv("GBO_ALERT_EMAIL", raising=False)
    assert error_log.alert_email() == "rykercurry@gmail.com"


def test_shiny_hook_records_render_errors(logdb, monkeypatch):
    """Run a real Shiny output whose render function raises; the hook saves it."""
    db, _ = logdb
    error_log.install()
        # Shiny's own except-block calls traceback.print_exc(); emulate that call site
        # by invoking the hook from a frame whose code lives in the shiny package.
    import shiny.session._session as ss
    code = compile("def f(hook):\n    try:\n        {}['x']\n    except KeyError:\n        output_name = 'demo-out'\n        hook()\n",
                   ss.__file__, "exec")
    ns = {}
    exec(code, ns)
    ns["f"](error_log._print_exc_hook)
    row = db.query(AppError).order_by(AppError.error_id.desc()).first()
    assert row is not None and row.output_name == "demo-out" and row.error_type == "KeyError"
