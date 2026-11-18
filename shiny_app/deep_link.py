"""
GBO -- open a page with the player / game already picked (Oct 2026,
Ryker: "a coach goes to a pitcher profile and from there clicks links
that take them to game reports, etc.").

go() is called by the link (Player Profile's "Go to" buttons, Recent
games rows): it stores the request in app_state.deep_link_open, remembers
who to go back to, and switches the page. Each destination page owns a
Pending() which picks the request up once:

    _dl = deep_link.Pending(app_state, "Pitcher Game Breakdown",
                            on_arrive=lambda p: ui.update_select(...))
    ...
    sel = _dl.take("game_id", choices)   # inside the picker's render

take() covers a page whose picker hasn't rendered yet (it renders with the
right selection); on_arrive's update_select covers a page that already
has. A value is only taken once it's actually one of the choices, so a
second picker that depends on the first (pitcher after game) still gets
its value when it re-renders.
"""

from itertools import count

from shiny import reactive, ui

_n = count(1)


def go(app_state, session, title, back=None, **params):
    """Switch to page `title` with params (pid=, game_id=, ...). back =
    (pid, name) for the "Back to" bar; None leaves it as it is."""
    app_state.deep_link_open.set({"page": title, "n": next(_n), **params})
    if back is not None:
        app_state.back_to.set(back)
    ui.update_navs("main_nav", selected=title, session=session.root_scope())


class Pending:
    def __init__(self, app_state, title, on_arrive=None):
        self.values = {}
        self.tick = reactive.value(0)
        self._app_state = app_state

        @reactive.effect
        def _consume():
            req = app_state.deep_link_open()
            if not req or req.get("page") != title:
                return
            with reactive.isolate():
                app_state.deep_link_open.set(None)
                self.values = {k: v for k, v in req.items() if k not in ("page", "n") and v is not None}
                if on_arrive is not None:
                    on_arrive(dict(self.values))
                self.tick.set(self.tick() + 1)

    def take(self, key, choices=None):
        """The requested value for this key as a string, if it's one of
        `choices` (dict or list; None = accept anything). Removed once taken."""
        self.tick()  # re-render pickers when a new request lands
        v = self.values.get(key)
        if v is None:
            return None
        v = str(v)
        if choices is not None and v not in choices:
            return None
        self.values.pop(key, None)
        return v

    def peek(self, key):
        return self.values.get(key)
