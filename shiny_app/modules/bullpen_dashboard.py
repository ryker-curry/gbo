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
"""

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, User, BullpenSession, RapsodoPitch

import ui_helpers
import bullpen_dashboard_display

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


def _sessions_with_rapsodo_data(db, allowed_player_ids):
    return (
        db.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .join(RapsodoPitch, RapsodoPitch.bullpen_id == BullpenSession.bullpen_id)
        .filter(BullpenSession.player_id.in_(allowed_player_ids))
        .distinct()
        .order_by(BullpenSession.session_date.desc())
        .all()
    )


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

    def _resolve(db):
        """Shared resolution used by every block below: allowed player
        ids, the scoped session list, and whether the current
        _target_bullpen_id is actually valid for this user. Returns a
        dict; callers pick out what they need."""
        allowed_player_ids = _allowed_player_ids(db, app_state)
        result = {
            "allowed_player_ids": allowed_player_ids,
            "sessions_by_id": {},
            "target_bullpen_id": None,
            "invalid_target": False,
        }
        if not allowed_player_ids:
            return result
        sessions = _sessions_with_rapsodo_data(db, allowed_player_ids)
        result["sessions_by_id"] = {b.bullpen_id: b for b in sessions}

        raw_target = _target_bullpen_id()
        if raw_target is not None:
            if raw_target in result["sessions_by_id"]:
                result["target_bullpen_id"] = raw_target
            else:
                result["invalid_target"] = True
        return result

    @render.ui
    def access_gate():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            allowed_player_ids = _allowed_player_ids(db, app_state)
            if allowed_player_ids is None:
                return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-warning") \
                    if app_state.role_name() == "Player" else ui.p("You don't have access to this page.", class_="text-danger")
            if not allowed_player_ids:
                return ui_helpers.empty_state("No pitchers to show yet." if app_state.can_view_all_players() else "No pitchers are currently assigned to you.")
            sessions = _sessions_with_rapsodo_data(db, allowed_player_ids)
            if not sessions:
                return ui_helpers.empty_state("No bullpen sessions with imported Rapsodo data yet. Upload one from the \"Import Rapsodo Data\" page first.")
            return None
        finally:
            db.close()

    @render.ui
    def pitcher_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None

        db = get_session()
        try:
            resolved = _resolve(db)
            if not resolved["allowed_player_ids"] or not resolved["sessions_by_id"]:
                return None
            if resolved["target_bullpen_id"] is not None:
                return None  # a target is already open -- no picker needed

            warning = None
            if resolved["invalid_target"]:
                warning = ui.p("That session either doesn't exist, has no Rapsodo data yet, or you don't have access to it.", class_="text-warning")

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
        finally:
            db.close()

    @render.ui
    def session_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None

        db = get_session()
        try:
            resolved = _resolve(db)
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
        finally:
            db.close()

    @render.ui
    def dashboard_header():
        db = get_session()
        try:
            resolved = _resolve(db)
            if resolved["target_bullpen_id"] is None:
                return None
            return ui.div(
                ui.input_action_button("change_session_btn", "Choose a different session", class_="btn-outline-secondary btn-sm mb-2"),
            )
        finally:
            db.close()

    def _get_overall_target(input):
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None
        db = get_session()
        try:
            resolved = _resolve(db)
            if not resolved["allowed_player_ids"]:
                return None
            if resolved["target_bullpen_id"] is not None:
                target_player_id = resolved["sessions_by_id"][resolved["target_bullpen_id"]].player_id
            else:
                req("pitcher_select" in input)
                target_player_id = int(input.pitcher_select())
            target_player = db.query(Player).filter(Player.player_id == target_player_id).first()
            if target_player is None:
                return None
            player_session_ids = [
                bid for bid, b in resolved["sessions_by_id"].items() if b.player_id == target_player_id
            ]
            if not player_session_ids:
                return None
            return {"kind": "combined", "player": target_player, "bullpen_ids": player_session_ids}
        finally:
            db.close()

    def _get_session_target(input):
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player" and app_state.role_name() not in ALLOWED_STAFF_ROLES:
            return None
        db = get_session()
        try:
            resolved = _resolve(db)
            if resolved["target_bullpen_id"] is not None:
                return {"kind": "session", "bullpen_id": resolved["target_bullpen_id"]}
            return None
        finally:
            db.close()

    _overall_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "dash_overall", _get_overall_target,
    )
    _session_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "dash_session", _get_session_target,
    )

    @render.ui
    def dash_overall_controls_slot():
        if not app_state.is_authenticated():
            return None
        return _overall_fragment

    @render.ui
    def dash_session_controls_slot():
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            resolved = _resolve(db)
            if resolved["target_bullpen_id"] is None:
                return None
            return _session_fragment
        finally:
            db.close()
