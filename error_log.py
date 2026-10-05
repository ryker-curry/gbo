"""
GBO -- error alerts (Oct 2026, Ryker approved: "just mine for the email").

Every unhandled error a user hits in the app (a chart/table that shows the
red error box, or a broken button) is saved to app_errors with who hit it,
what page they were on, and the traceback. Then:
  - Burst alert: the same error BURST_COUNT (5) times within an hour sends
    an email right away (at most one per error per hour).
  - Daily summary: scripts/send_error_summary.py (error_summary_job.ipynb
    on Posit Connect, every morning) emails yesterday's errors grouped by
    bug. Nothing is sent on a day with no errors.

Email goes only to GBO_ALERT_EMAIL (falls back to Ryker's address), via
the same SMTP_* env vars as the weekly reports.

How errors are caught: Shiny prints every render/effect error with
traceback.print_exc() before showing the error box -- install() wraps that
one function so GBO also records it. Nothing about Shiny's own handling
changes, and a failure to record never raises.
"""

import hashlib
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta

DEFAULT_ALERT_EMAIL = "rykercurry@gmail.com"
BURST_COUNT = 5
BURST_WINDOW = timedelta(hours=1)
ROOT = os.path.dirname(os.path.abspath(__file__))

_sessions = {}           # root session id -> callable returning (user_id, role, page)
_installed = False
_orig_print_exc = traceback.print_exc


def alert_email():
    return os.environ.get("GBO_ALERT_EMAIL") or DEFAULT_ALERT_EMAIL


# ---- who / where ------------------------------------------------------------
def register_session(session, info_fn):
    """app.py: info_fn() -> (user_id, role_name, page) for this browser session."""
    _sessions[session.id] = info_fn
    try:
        session.on_ended(lambda: _sessions.pop(session.id, None))
    except Exception:
        pass


def _session_info():
    try:
        from shiny.session import get_current_session
        s = get_current_session()
        if s is None:
            return None, None, None
        root = getattr(s, "_root_session", None) or s
        fn = _sessions.get(root.id)
        if fn is None:
            return None, None, None
        from shiny import reactive
        with reactive.isolate():
            return fn()
    except Exception:
        return None, None, None


def _gbo_frame(tb):
    """Deepest traceback frame inside the GBO repo (not site-packages)."""
    best = None
    for fs in traceback.extract_tb(tb):
        f = os.path.abspath(fs.filename)
        if f.startswith(ROOT) and "site-packages" not in f and os.sep + "ven" + os.sep not in f:
            best = fs
    return best


def fingerprint(exc_type, frame):
    loc = f"{os.path.relpath(frame.filename, ROOT)}:{frame.name}:{frame.lineno}" if frame else "?"
    return hashlib.sha1(f"{exc_type.__name__}|{loc}".encode()).hexdigest()[:16], loc


# ---- record -------------------------------------------------------------------
def record(exc_type, exc, tb, output_name=None, info=None):
    """Save one error; never raises. Returns the AppError id or None."""
    try:
        from database import get_session
        from models import AppError
        frame = _gbo_frame(tb)
        fp, loc = fingerprint(exc_type, frame)
        user_id, role, page = info if info is not None else _session_info()
        tb_text = "".join(traceback.format_exception(exc_type, exc, tb))[-8000:]
        db = get_session()
        try:
            row = AppError(fingerprint=fp, error_type=exc_type.__name__, message=str(exc)[:1000], location=loc[:255],
                           output_name=(output_name or "")[:255] or None, page=(page or None), user_id=user_id,
                           role_name=role, traceback_text=tb_text)
            db.add(row)
            db.commit()
            _maybe_burst_alert(db, row)
            return row.error_id
        finally:
            db.close()
    except Exception:
        return None


def _maybe_burst_alert(db, row):
    from models import AppError
    since = datetime.utcnow() - BURST_WINDOW
    q = db.query(AppError).filter(AppError.fingerprint == row.fingerprint, AppError.created_at >= since)
    if q.count() < BURST_COUNT or q.filter(AppError.alert_sent.is_(True)).count():
        return
    row.alert_sent = True
    db.commit()
    recent = q.order_by(AppError.created_at.desc()).all()
    msg = burst_email(row, recent)
    threading.Thread(target=_send, args=(msg,), daemon=True).start()


# ---- email -------------------------------------------------------------------
def _send(msg):
    try:
        from scripts.send_weekly_reports import _smtp
        s = _smtp()
        try:
            s.send_message(msg)
        finally:
            s.quit()
    except Exception as e:      # never let an alert failure hurt the app
        print(f"[GBO] error alert not sent: {e}", file=sys.stderr)


def _base_msg(subject):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER") or alert_email()
    msg["To"] = alert_email()
    return msg


def _who(rows):
    users = {(r.user_id, r.role_name) for r in rows if r.user_id}
    pages = sorted({r.page for r in rows if r.page})
    return (f"{len(users)} user{'s' if len(users) != 1 else ''}" if users else "no signed-in user"), pages


def burst_email(row, recent):
    who, pages = _who(recent)
    msg = _base_msg(f"GBO alert: {row.error_type} hit {len(recent)}x in the last hour")
    msg.set_content(
        f"The same error has happened {len(recent)} times in the last hour ({who}).\n\n"
        f"Error:  {row.error_type}: {row.message}\n"
        f"Where:  {row.location}\n"
        f"Output: {row.output_name or '-'}\n"
        f"Pages:  {', '.join(pages) or '-'}\n\n"
        f"Latest traceback:\n{row.traceback_text}\n\n"
        "You'll get at most one alert per error per hour; everything is also in tomorrow's daily summary.\n")
    return msg


def group_errors(rows):
    """[{fingerprint, count, first, last, sample, users, pages}] most frequent first."""
    groups = {}
    for r in rows:
        g = groups.setdefault(r.fingerprint, {"fingerprint": r.fingerprint, "rows": []})
        g["rows"].append(r)
    out = []
    for g in groups.values():
        rs = sorted(g["rows"], key=lambda r: r.created_at)
        who, pages = _who(rs)
        out.append({"fingerprint": g["fingerprint"], "count": len(rs), "first": rs[0].created_at,
                    "last": rs[-1].created_at, "sample": rs[-1], "users": who, "pages": pages})
    return sorted(out, key=lambda g: -g["count"])


def summary_email(rows, day):
    groups = group_errors(rows)
    msg = _base_msg(f"GBO daily errors {day.strftime('%a %b %d')}: {len(rows)} error"
                    f"{'s' if len(rows) != 1 else ''}, {len(groups)} different")
    parts = [f"{len(rows)} errors on {day.strftime('%A %b %d')} ({len(groups)} different bugs), most frequent first.\n"]
    for i, g in enumerate(groups, 1):
        s = g["sample"]
        tail = "\n".join(s.traceback_text.strip().splitlines()[-6:]) if s.traceback_text else ""
        parts.append(
            f"{i}. {s.error_type}: {s.message}\n"
            f"   {g['count']}x  ·  {g['users']}  ·  {g['first'].strftime('%H:%M')}-{g['last'].strftime('%H:%M')} UTC\n"
            f"   Where: {s.location}   Output: {s.output_name or '-'}   Pages: {', '.join(g['pages']) or '-'}\n"
            f"{tail}\n")
    msg.set_content("\n".join(parts))
    return msg


# ---- hook into Shiny ----------------------------------------------------------
def _print_exc_hook(*args, **kwargs):
    _orig_print_exc(*args, **kwargs)
    try:
        exc_type, exc, tb = sys.exc_info()
        if exc_type is None:
            return
        caller = sys._getframe(1)
        if not os.path.abspath(caller.f_code.co_filename).startswith(_shiny_dir()):
            return                      # only errors Shiny itself reports to a user (not GBO's own handled ones)
        output_name = caller.f_locals.get("output_name")
        info = _session_info()          # needs the Shiny session context -> read it now
        # The database write happens off the request path, so a slow or
        # down database never makes the app slower on top of the error.
        threading.Thread(target=record, args=(exc_type, exc, tb),
                         kwargs={"output_name": str(output_name) if output_name else None, "info": info},
                         daemon=True).start()
    except Exception:
        pass


def _shiny_dir():
    import shiny
    return os.path.dirname(os.path.abspath(shiny.__file__)) + os.sep


def install():
    global _installed
    if _installed or os.environ.get("GBO_ERROR_LOG", "1") == "0":
        return
    traceback.print_exc = _print_exc_hook
    _installed = True
