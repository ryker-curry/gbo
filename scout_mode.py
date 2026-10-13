"""
GBO -- Scout login (Oct 2026, Ryker: "create a user login for potential
employers in mlb org ... able to be sent to anybody ... use our real data
but black out the names").

One shared login (SCOUT_EMAIL = guest@gbo.app / GBO_SCOUT_PASSWORD,
default "Password"; shown to the user as "Guest", never "Scout")
that opens the REAL Pittsburg State data with three protections:

  1. Names hidden. A Scout session reads through its own SQLAlchemy engine
     (scout_engine()). A "load" listener on every model rewrites names on
     objects loaded through that engine only: our players become
     "Pitcher 1..." / "Hitter 1..." (stable: numbered by player id),
     opponents "Opp. Player N", staff "Staff N"; jersey numbers, photos,
     emails, hometowns, schools, injury notes, free-text notes and video
     links are blanked. Real logins never touch this engine, and the
     query cache (gbo_cache) keys on the engine, so a masked result can
     never be served to a real login or the other way round.
  2. Read-only. The Scout engine refuses any SQL that isn't a read.
  3. Fewer pages. app.py shows only SCOUT_PAGES (no arm care, roster,
     player setup, IDP, compensation, game tracking, imports, admin).

Turn it off by setting GBO_SCOUT_PASSWORD to "off" on Posit; change the
password the same way.

The Scout session plugs into database.get_session() the same way the
guest demo does (database.use_guest_db), so uploads, email and the error
log -- which check database.in_guest_demo() -- stay off for Scouts too.
"""

import os
import threading

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

SCOUT_EMAIL = "guest@gbo.app"
SCOUT_TITLE = "Guest (view only)"

# Page keys a Scout can open (nav.build_nav_sections keys).
SCOUT_PAGES = [
    "dashboard", "how_to_read",
    "assessments",
    "pitcher_profile", "hitter_profile",
    "pitcher_game_report", "pitcher_meeting_report", "hitter_game_report", "hitter_meeting_report",
    "team_game_report", "analytics", "weekly_report",
    "pitching_leaderboard", "hitting_leaderboard",
    "bullpen_dashboard",
]

# Columns blanked on every model that has them (free text can name people).
BLANK_COLUMNS = {
    "notes", "overall_notes", "completed_notes", "note", "note_text", "injury_note", "plan_text",
    "video_url", "photo_url", "email", "hometown", "previous_school", "original_filename",
    "rapsodo_session_name",
}

_engine = None
_maker = None
_lock = threading.Lock()
_aliases = {"player": {}, "opp": {}, "user": {}}


def password():
    return os.environ.get("GBO_SCOUT_PASSWORD", "Password")


def enabled():
    return password().strip().lower() not in ("", "off", "disabled", "none")


def matches(email, pw):
    return enabled() and (email or "").strip().lower() == SCOUT_EMAIL and (pw or "") == password()


def _read_only_guard(conn, cursor, statement, parameters, context, executemany):
    head = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else ""
    if head not in ("SELECT", "WITH", "SHOW", "SET", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "PRAGMA"):
        raise PermissionError("Guest login is view only (read-only).")
    if head == "WITH" and any(w in statement.upper() for w in (" INSERT ", " UPDATE ", " DELETE ")):
        raise PermissionError("Guest login is view only (read-only).")


def use_engine(engine):
    """Make `engine` the Scout engine (read-only guard + masking). Tests and
    the local harness pass their own; production builds one in scout_engine()."""
    global _engine, _maker
    event.listen(engine, "before_cursor_execute", _read_only_guard)
    _engine = engine
    _maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    _install_masking()
    return engine


def scout_engine():
    """The Scout-only engine (created once, separate from database.engine)."""
    with _lock:
        if _engine is None:
            url = os.environ["DATABASE_URL"]
            kw = {"pool_pre_ping": True}
            if url.startswith("postgres"):
                kw.update(pool_size=2, max_overflow=1, pool_recycle=300, connect_args={"connect_timeout": 10})
            use_engine(create_engine(url, **kw))
        return _engine


def maker():
    scout_engine()
    return _maker


def refresh_aliases():
    """Number players / opponents / staff by id, so the same person always
    gets the same alias. Read through the Scout engine (a plain SELECT)."""
    eng = scout_engine()
    with eng.connect() as c:
        players = c.execute(text("SELECT player_id, is_pitcher FROM players ORDER BY player_id")).fetchall()
        opps = c.execute(text("SELECT opponent_player_id FROM opponent_players ORDER BY opponent_player_id")).fetchall()
        users = c.execute(text("SELECT user_id FROM users ORDER BY user_id")).fetchall()
    pa, n = {}, {"P": 0, "H": 0}
    for pid, is_p in players:
        k = "P" if is_p else "H"
        n[k] += 1
        pa[pid] = ("Pitcher" if is_p else "Hitter", str(n[k]))
    _aliases["player"] = pa
    _aliases["opp"] = {oid: i + 1 for i, (oid,) in enumerate(opps)}
    _aliases["user"] = {uid: i + 1 for i, (uid,) in enumerate(users)}


def _is_scout_session(session):
    return session is not None and _engine is not None and getattr(session, "bind", None) is _engine


def mask(obj):
    """Rewrite one loaded object in place (no change is ever written back)."""
    cls = type(obj).__name__
    cols = {c.key for c in obj.__mapper__.column_attrs}
    if cls == "Player":
        first, last = _aliases["player"].get(obj.player_id) or (
            "Pitcher" if getattr(obj, "is_pitcher", False) else "Player", str(obj.player_id))
        set_committed_value(obj, "first_name", first)
        set_committed_value(obj, "last_name", last)
        if "jersey_number" in cols:
            set_committed_value(obj, "jersey_number", None)
    elif cls == "OpponentPlayer":
        set_committed_value(obj, "player_name", f"Opp. Player {_aliases['opp'].get(obj.opponent_player_id, obj.opponent_player_id)}")
        set_committed_value(obj, "jersey_number", None)
    elif cls == "User":
        set_committed_value(obj, "first_name", "Staff")
        set_committed_value(obj, "last_name", str(_aliases["user"].get(obj.user_id, obj.user_id)))
    for c in BLANK_COLUMNS & cols:
        if getattr(obj, c, None) is not None:
            set_committed_value(obj, c, None)


def _on_load(target, context):
    if _is_scout_session(getattr(context, "session", None)):
        mask(target)


def _on_refresh(target, context, attrs):
    _on_load(target, context)


_installed = False


def _install_masking():
    global _installed
    if _installed:
        return
    from database import Base
    event.listen(Base, "load", _on_load, propagate=True)
    event.listen(Base, "refresh", _on_refresh, propagate=True)
    _installed = True


# ---- per-Shiny-session flag ----------------------------------------------
def _root(shiny_session):
    return shiny_session.root_scope() if hasattr(shiny_session, "root_scope") else shiny_session


def start(shiny_session):
    """Point this Shiny session at the Scout engine (masked + read-only)."""
    refresh_aliases()
    import database
    database.use_guest_db(shiny_session, maker())
    _root(shiny_session)._gbo_scout = True


def stop(shiny_session):
    import database
    root = _root(shiny_session)
    if getattr(root, "_gbo_scout", False):
        database.use_guest_db(shiny_session, None)
        root._gbo_scout = False


def is_scout(shiny_session=None):
    if shiny_session is None:
        try:
            from shiny.session import get_current_session
            shiny_session = get_current_session()
        except Exception:
            return False
    return bool(shiny_session is not None and getattr(_root(shiny_session), "_gbo_scout", False))
