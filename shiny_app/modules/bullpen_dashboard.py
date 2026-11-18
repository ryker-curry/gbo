"""
GBO -- Bullpen Dashboard module (coach/staff-facing standalone page).

Direct port of pages/bullpen_dashboard.py -- an Overall Pitch Tracking
table (every one of a pitcher's Rapsodo sessions combined) sitting above
a single session's full drill-down (KPI cards, filters, pitch-type
summary, and the four core charts). All rendering is delegated to
bullpen_dashboard_display.register_bullpen_dashboard(), the same shared
helper modules/player_bullpens.py's inline "Bullpen Dashboard" section
already uses -- called TWICE here with distinct key_prefixes
("dash_overall" and "dash_session"), exactly as that file's own
docstring anticipated for a page that shows both sections at once.

Permissions mirror the original exactly: Players see only their own
sessions; coaches/staff see StaffPlayerAssignment-assigned players
unless can_view_all_players; Administrator/Head Coach/Coach/Sports
Scientist/Data Analyst are the allowed staff roles.

Reached two ways, same as the original's ?bullpen_id=<id> URL param:
  - Cross-page deep link: rapsodo_import.py's "Open full Bullpen
    Dashboard" button sets app_state.deep_link_bullpen_id and switches
    the navset to this page. The one-shot consume-effect below reads it
    into a LOCAL reactive.Value (_target_bullpen_id) and immediately
    clears the shared app_state field back to None (per state.py's
    documented consume-once contract) -- the local copy is what
    actually drives this page from then on, so a stale app_state value
    can't re-trigger the jump on a later visit.
  - In-page picker: pick a pitcher (Step 1, reveals that pitcher's
    Overall Pitch Tracking table), then pick one of their sessions and
    click "Open dashboard" (Step 2) -- the click handler sets the same
    local _target_bullpen_id, so both entry paths converge on identical
    downstream state.

Deliberate small addition over the original (which has no way back
short of editing the URL): a "Choose a different session" button once
a target is open, since Shiny's reactive.Value persists for the whole
session the way a Streamlit query param never did -- without it, a
coach who opened one pitcher's dashboard would be stuck on it for the
rest of their session with no in-app way back to the picker.

Sept 2026 addition: the session picker (_sessions_with_tracked_data)
now also lists sessions with command-tracking data (CommandPitch rows,
logged on the separate Command Tracker page), not just Rapsodo data --
previously a command-focused bullpen never showed up on this page at
all. Opening such a session shows a read-only Command Tracking
scorecard + chart (command_dashboard_display.py) below/instead of the
Rapsodo section, via the same register_*_dashboard(get_target)
convention; a session with both kinds of data shows both. "Overall
Pitch Tracking" stays Rapsodo-only for now -- a combined view across a
pitcher's command sessions is a deliberate not-yet, revisit once
there's more fall-ball command data to look at (intrasquads start the
week of Sep 7 2026).
"""

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, BullpenSession, RapsodoPitch, CommandPitch

import ui_helpers
import bullpen_dashboard_display
import command_dashboard_display

ALLOWED_STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")


def _allowed_player_ids(db, app_state):
    """Resolves who this session's user is allowed to see bullpen data
    for. Returns None if the user has no access at all (Player role
    with no linked player_id, or a staff role outside
    ALLOWED_STAFF_ROLES); otherwise a (possibly empty) list of
    player_ids -- same permission logic as the original page."""
    if app_state.role_name() == "Player":
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        return [me.player_id]
    if app_state.role_name() not in ALLOWED_STAFF_ROLES:
        return None
    q = db.query(Player).filter(Player.is_pitcher.is_(True))
    if not app_state.can_view_all_players():
        assigned_ids = [
            a.player_id for a in
            db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()
        ]
        q = q.filter(Player.player_id.in_(assigned_ids))
    return [p.player_id for p in q.all()]


def _sessions_with_tracked_data(db, allowed_player_ids):
    """Every bullpen session with Rapsodo data, command-tracking data, or
    both -- the Bullpen Dashboard's session picker shows all of them
    (Sept 2026: previously Rapsodo-only via an inner join to
    RapsodoPitch, so a command-focused bullpen logged on the separate
    Command Tracker page -- CommandPitch rows, no RapsodoPitch -- never
    showed up here at all).

    Two separate queries rather than one OR-joined query, kept simple
    and matching this file's existing query style; merged below into
    one dict so a session with both kinds of data (the schema allows
    it -- BullpenType's "Command" value is a default, not a constraint)
    appears exactly once. Returns (sessions_by_id, rapsodo_bullpen_ids,
    command_bullpen_ids) -- callers use the two id sets to decide which
    of the Rapsodo/Command display fragments actually apply to the
    selected session."""
    rapsodo_sessions = (
        db.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .join(RapsodoPitch, RapsodoPitch.bullpen_id == BullpenSession.bullpen_id)
        .filter(BullpenSession.player_id.in_(allowed_player_ids))
        .distinct()
        .all()
    )
    command_sessions = (
        db.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .join(CommandPitch, CommandPitch.bullpen_id == BullpenSession.bullpen_id)
        .filter(BullpenSession.player_id.in_(allowed_player_ids))
        .distinct()
        .all()
    )
    rapsodo_ids = {b.bullpen_id for b in rapsodo_sessions}
    command_ids = {b.bullpen_id for b in command_sessions}
    merged = {b.bullpen_id: b for b in rapsodo_sessions}
    for b in command_sessions:
        merged.setdefault(b.bullpen_id, b)
    sessions_by_id = dict(sorted(merged.items(), key=lambda kv: kv[1].session_date, reverse=True))
    return sessions_by_id, rapsodo_ids, command_ids


@module.ui
def bullpen_dashboard_ui():
    return ui.div(
        ui_helpers.page_header("Bullpen Dashboard"),
        ui.output_ui("access_gate"),
        ui.output_ui("pitcher_picker"),
        ui.output_ui("session_picker"),
        ui.output_ui("dashboard_header"),
        ui.output_ui("dash_overall_controls_slot"),
        ui.output_ui("dash_session_controls_slot"),
        ui.output_ui("dash_command_controls_slot"),
        ui_helpers.page_footer(),
    )


@module.server
def bullpen_dashboard_server(input, output, session, app_state):
    _target_bullpen_id = reactive.Value(None)

    # --- Consume the cross-page deep link exactly once ------------------
    @reactive.effect
    def _consume_deep_link():
        incoming = app_state.deep_link_bullpen_id()
        if incoming is not None:
            _target_bullpen_id.set(incoming)
            app_state.deep_link_bullpen_id.set(None)

    @reactive.effect
    @reactive.event(input.open_dashboard_btn)
    def _open_from_picker():
        req("session_select" in input)
        _target_bullpen_id.set(int(input.session_select()))

    @reactive.effect
    @reactive.event(input.change_session_btn)
    def _change_session():
        _target_bullpen_id.set(None)

    @reactive.calc
    def _resolved():
        """Shared resolution used by every block below: allowed player
        ids, the scoped session list, and whether the current
        _target_bullpen_id is actually valid for this user. Returns a
        dict; callers pick out what they need.

        This used to be a plain function (`_resolve(db)`) called fresh,
        with its own database queries, from SEVEN different places on
        this one page (access_gate, pitcher_picker, session_picker,
        dashboard_header, both chart-target resolvers, and the session
        controls slot) -- every one of them re-running the identical
        "which players can this user see, which of their bullpen
        sessions have Rapsodo data" queries on every page load.
        @reactive.calc makes this a single computation, memoized and
        shared by all of those callers, that only reruns when something
        it actually reads (role/user/view-all-players, or which
        session/pitcher is targeted) changes -- exactly the same
        invalidation rule Shiny already uses for a render.ui, just
        computed once instead of seven times."""
        db = get_session()
        try:
            allowed_player_ids = _allowed_player_ids(db, app_state)
            result = {
                "allowed_player_ids": allowed_player_ids,
                "sessions_by_id": {},
                "rapsodo_bullpen_ids": set(),
                "command_bullpen_ids": set(),
                "target_bullpen_id": None,
                "invalid_target": False,
            }
            if not allowed_player_ids:
                return result
            sessions_by_id, rapsodo_ids, command_ids = _sessions_with_tracked_data(db, allowed_player_ids)
            result["sessions_by_id"] = sessions_by_id
            result["rapsodo_bullpen_ids"] = rapsodo_ids
            result["command_bullpen_ids"] = command_ids

            raw_target = _target_bullpen_id()
            if raw_target is not None:
                if raw_target in result["sessions_by_id"]:
                    result["target_bullpen_id"] = raw_target
                else:
                    result["invalid_target"] = True
            return result
        finally:
            db.close()

    @render.ui
    def access_gate():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        resolved = _resolved()
        if resolved["allowed_player_ids"] is None:
            return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-warning") \
                if app_state.role_name() == "Player" else ui.p("You don't have access to this page.", class_="text-danger")
        if not resolved["allowed_player_ids"]:
            return ui_helpers.empty_state("No pitchers to show yet." if app_state.can_view_all_players() else "No pitchers are currently assigned to you.")
        if not resolved["sessions_by_id"]:
            return ui_helpers.empty_state("No bullpen sessions with tracked data yet. Import Rapsodo data, or log a session on the Command Tracker page, first.")
        return None

    @render.ui
    def pitcher_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None

        resolved = _resolved()
        if not resolved["allowed_player_ids"] or not resolved["sessions_by_id"]:
            return None
        if resolved["target_bullpen_id"] is not None:
            return None  # a target is already open -- no picker needed

        warning = None
        if resolved["invalid_target"]:
            warning = ui.p("That session either doesn't exist, has no tracked data yet, or you don't have access to it.", class_="text-warning")

        pitchers_by_id = {}
        for b in resolved["sessions_by_id"].values():
            if b.player and b.player_id not in pitchers_by_id:
                pitchers_by_id[b.player_id] = b.player
        sorted_ids = sorted(pitchers_by_id, key=lambda pid: (pitchers_by_id[pid].last_name, pitchers_by_id[pid].first_name))
        choices = {str(pid): f"{pitchers_by_id[pid].first_name} {pitchers_by_id[pid].last_name}" for pid in sorted_ids}

        children = [c for c in [warning] if c]
        children.append(ui.p(ui.strong("Select a pitcher")))
        children.append(ui.input_select("pitcher_select", None, choices=choices))
        return ui.div(*children)

    @render.ui
    def session_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None

        resolved = _resolved()
        if resolved["target_bullpen_id"] is not None or not resolved["sessions_by_id"]:
            return None
        req("pitcher_select" in input)
        target_player_id = int(input.pitcher_select())

        pitcher_sessions_by_id = {
            bid: b for bid, b in resolved["sessions_by_id"].items() if b.player_id == target_player_id
        }
        if not pitcher_sessions_by_id:
            return None

        def _label(bid):
            b = pitcher_sessions_by_id[bid]
            type_label = b.bullpen_type.type_name if b.bullpen_type else "—"
            return f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}"

        choices = {str(bid): _label(bid) for bid in pitcher_sessions_by_id}
        return ui.div(
            ui.p(ui.strong("Select a session")),
            ui.input_select("session_select", None, choices=choices),
            ui.input_action_button("open_dashboard_btn", "Open dashboard", class_="btn-primary"),
        )

    @render.ui
    def dashboard_header():
        resolved = _resolved()
        if resolved["target_bullpen_id"] is None:
            return None
        return ui.div(
            ui.input_action_button("change_session_btn", "Choose a different session", class_="btn-outline-secondary btn-sm mb-2"),
        )

    def _get_overall_target(input):
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None
        resolved = _resolved()
        if not resolved["allowed_player_ids"]:
            return None
        if resolved["target_bullpen_id"] is not None:
            target_player_id = resolved["sessions_by_id"][resolved["target_bullpen_id"]].player_id
        else:
            req("pitcher_select" in input)
            target_player_id = int(input.pitcher_select())
        db = get_session()
        try:
            target_player = db.query(Player).filter(Player.player_id == target_player_id).first()
        finally:
            db.close()
        if target_player is None:
            return None
        player_session_ids = [
            bid for bid, b in resolved["sessions_by_id"].items()
            if b.player_id == target_player_id and bid in resolved["rapsodo_bullpen_ids"]
        ]
        if not player_session_ids:
            return None
        return {"kind": "combined", "player": target_player, "bullpen_ids": player_session_ids}

    def _get_session_target(input):
        """Rapsodo dashboard target -- None (nothing to show) for a
        command-only session, so the Rapsodo display never has to
        handle a zero-RapsodoPitch session; see _get_command_session_
        target below for that session's actual data."""
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None
        resolved = _resolved()
        if resolved["target_bullpen_id"] is not None and resolved["target_bullpen_id"] in resolved["rapsodo_bullpen_ids"]:
            return {"kind": "session", "bullpen_id": resolved["target_bullpen_id"]}
        return None

    def _get_command_session_target(input):
        """Command Tracking target (Sept 2026 addition) -- mirrors
        _get_session_target exactly, just gated on command_bullpen_ids
        instead of rapsodo_bullpen_ids, so a command-focused bullpen
        (logged on the separate Command Tracker page) shows its
        scorecard/chart here even though it has no Rapsodo data at
        all. A session with both kinds of data resolves both targets
        at once -- dash_session_controls_slot/dash_command_controls_
        slot below render whichever fragment(s) actually apply."""
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None
        resolved = _resolved()
        if resolved["target_bullpen_id"] is not None and resolved["target_bullpen_id"] in resolved["command_bullpen_ids"]:
            return {"kind": "session", "bullpen_id": resolved["target_bullpen_id"]}
        return None

    _overall_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "dash_overall", _get_overall_target,
    )
    _session_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "dash_session", _get_session_target,
    )
    _command_fragment = command_dashboard_display.register_command_dashboard(
        input, output, session, "dash_command", _get_command_session_target,
    )

    @render.ui
    def dash_overall_controls_slot():
        if not app_state.is_authenticated():
            return None
        resolved = _resolved()
        if resolved["target_bullpen_id"] is not None:
            # A specific session is open below (dash_session_controls_
            # slot) -- if that's this pitcher's ONLY session with
            # Rapsodo data, "Overall Pitch Tracking" (which combines
            # every one of their sessions) would show byte-for-byte
            # identical numbers and charts to the single-session
            # drill-down beneath it, since there's only one session to
            # combine. Found via a real case (Aug 2026): a one-session
            # pitcher's dashboard rendered the entire page twice, which
            # reads as a bug even though it's actually two different
            # (currently identical) sections. Skip Overall here since it
            # adds no information in that case -- still shown normally
            # before a specific session is opened (Step 1's picker flow
            # needs it), and still shown once there are 2+ sessions to
            # actually aggregate.
            target_player_id = resolved["sessions_by_id"][resolved["target_bullpen_id"]].player_id
            session_count = sum(
                1 for bid, b in resolved["sessions_by_id"].items()
                if b.player_id == target_player_id and bid in resolved["rapsodo_bullpen_ids"]
            )
            if session_count <= 1:
                return None
        return _overall_fragment

    @render.ui
    def dash_session_controls_slot():
        if not app_state.is_authenticated():
            return None
        resolved = _resolved()
        if resolved["target_bullpen_id"] is None:
            return None
        return _session_fragment

    @render.ui
    def dash_command_controls_slot():
        if not app_state.is_authenticated():
            return None
        resolved = _resolved()
        if resolved["target_bullpen_id"] is None:
            return None
        return _command_fragment