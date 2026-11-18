"""
GBO -- small in-process cache for heavy team-wide lookups (Oct 2026,
Ryker approved: "10-minute caching of Stuff+ models, team baselines and
hands, invalidated on saves").

    @cached("stuff_models", tables={"rapsodo_pitches", "game_pitches"})
    def team_stuff_plus_baselines(db): ...

- Key = function name + every argument after `db`.
- Entries live TTL_SECONDS (10 min), so a save made by ANOTHER process
  (Posit Connect can run several) shows up within 10 minutes.
- A save in THIS process clears every entry that depends on a table the
  save touched, right after the commit (SQLAlchemy session events) -- so
  a coach who just charted a game sees it immediately.
- ORM rows are loaded in a private session and detached (expunge_all)
  before caching, so a later commit/close of the caller's session can't
  expire them. Only relationships that were eager-loaded are available
  on cached rows -- same as every caller already uses them.
- GBO_CACHE=0 turns caching off (debugging).
"""

import os
import time
import threading
from functools import wraps

from sqlalchemy import event
from sqlalchemy.orm import Session, sessionmaker

TTL_SECONDS = 600
_lock = threading.RLock()
_store = {}       # key -> (expires_at, tables, value)
_hits = {"hit": 0, "miss": 0}


def enabled():
    return os.environ.get("GBO_CACHE", "1") != "0"


def cached(name, tables):
    tables = frozenset(tables)

    def deco(fn):
        @wraps(fn)
        def wrapper(db, *args, **kwargs):
            if not enabled():
                return fn(db, *args, **kwargs)
            # id(bind): a guest's demo database and Supabase never share
            # an entry (Oct 2026, guest demo).
            key = (name, id(db.get_bind()), args, tuple(sorted(kwargs.items())))
            now = time.time()
            with _lock:
                hit = _store.get(key)
                if hit and hit[0] > now:
                    _hits["hit"] += 1
                    return hit[2]
            _hits["miss"] += 1
            private = sessionmaker(bind=db.get_bind())()
            try:
                value = fn(private, *args, **kwargs)
                private.expunge_all()
            finally:
                private.close()
            with _lock:
                _store[key] = (now + TTL_SECONDS, tables, value)
            return value
        wrapper.uncached = fn
        return wrapper
    return deco


def clear(tables=None):
    """Drop every entry (tables=None) or the ones depending on `tables`."""
    with _lock:
        if tables is None:
            _store.clear()
            return
        for k in [k for k, v in _store.items() if v[1] & tables]:
            del _store[k]


def stats():
    with _lock:
        return {"entries": len(_store), **_hits}


# ---- invalidate on saves ----------------------------------------------------
def _tables_of(objs):
    out = set()
    for o in objs:
        t = getattr(o, "__tablename__", None)
        if t:
            out.add(t)
    return out


@event.listens_for(Session, "after_flush")
def _after_flush(session, flush_context):
    touched = _tables_of(session.new) | _tables_of(session.dirty) | _tables_of(session.deleted)
    if touched:
        session.info.setdefault("gbo_touched", set()).update(touched)


@event.listens_for(Session, "do_orm_execute")
def _bulk_write(state):
    """query(...).update()/.delete() and update()/delete() statements skip
    the flush -- record their table too."""
    if state.is_update or state.is_delete or state.is_insert:
        m = state.bind_mapper
        t = getattr(m, "local_table", None) if m is not None else None
        if t is not None:
            state.session.info.setdefault("gbo_touched", set()).add(t.name)


@event.listens_for(Session, "after_commit")
def _after_commit(session):
    touched = session.info.pop("gbo_touched", None)
    if touched:
        clear(frozenset(touched))


@event.listens_for(Session, "after_rollback")
def _after_rollback(session):
    session.info.pop("gbo_touched", None)
