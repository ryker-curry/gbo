"""
GBO -- Player Management module.

Direct port of pages/players.py -- roster list with search/filter/sort +
CSV export, add/edit form (all staff roles can add/edit, per Ryker's
decision), pitch arsenal management for pitchers, and a guarded delete
(blocked if the player has any real data attached -- assessments, IDP
goals, sessions, assignments, bullpens, or a linked user account --
same related-record check as the original).

Role gating: Coach sees only players assigned to them (via
staff_player_assignments, same app_state.can_view_all_players() flag
used everywhere else); every other staff role sees the full active
roster. Same MVP limitation as the original -- a newly-added player
isn't auto-assigned to the Coach who added them.

Streamlit -> Shiny translation notes (this is the first module in the
migration with real write operations, so these patterns are new here
and get reused by every CRUD page after this one):
  - st.form + st.form_submit_button -> plain ui.input_*() fields plus a
    ui.input_action_button, read only inside a
    @reactive.effect + @reactive.event(input.save_player_btn) handler
    -- same "batch until submit" behavior as st.form, just wired
    explicitly instead of implicitly.
  - st.rerun() after a save/delete -> bumping the module-local
    `_refresh_tick` reactive.Value, which every data-loading render.ui
    below depends on (calls `_refresh_tick()` first thing, purely for
    the reactive dependency) -- this forces the roster table, the
    player picker, and the delete section to all recompute from the
    database, the same "whole page recomputes" effect Streamlit gives
    for free.
  - The "select a player to edit" -> "render that player's form"
    sequence has the same ordering hazard player_stats.py's category
    select -> pitch-type select chain has: reading an input from the
    same output_ui block that defines it doesn't work reliably. Same
    fix -- split into two output_ui blocks (picker, then fields/
    arsenal/delete-confirm) so the second can safely read the first's
    current value.
  - st.column_config.ImageColumn (roster table's Photo column) has no
    render_dict_table equivalent (that helper renders plain text
    cells), so this module builds its own small table with a real
    <img> thumbnail cell instead.
  - st.download_button -> @render.download + ui.download_button,
    re-deriving the same filtered/sorted list the on-screen table used
    (no shared reactive.calc for it -- see _filtered_sorted_players()).
  - st.file_uploader -> ui.input_file; Shiny hands back a list of
    {"name", "size", "type", "datapath"} dicts (a path to a real temp
    file) instead of an in-memory UploadedFile, so the Supabase upload
    helper reads bytes from that path instead of calling .getvalue().
  - st.success/st.error/st.warning (which persist inline until the
    next rerun in Streamlit) -> ui.notification_show() toasts here --
    Shiny has no persistent inline flash-message primitive, so this is
    an intentional, minor UX difference, not a missed translation.
"""

import csv
import io
import uuid
from datetime import date

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, Team, StaffPlayerAssignment, PlayerClass, PlayerStatus, Position,
    Assessment, IDPGoal, TrainingSession, PlayerAssignment, BullpenSession,
    User, PitchType, PlayerPitchArsenal,
)
from supabase_client import get_supabase_admin_client

import ui_helpers

PHOTO_BUCKET = "player-photos"

# Display-only position grouping for the roster table, CSV export, and the
# Position filter -- Ryker wants position players shown as INF/OF rather
# than each specific spot (1B/2B/3B/SS -> INF, LF/CF/RF -> OF), while
# pitchers (RHP/LHP) and C stay as-is. This is purely a display transform:
# the underlying Position row (and position_id FK) a player is actually
# assigned stays exactly as specific as it's always been -- nothing else
# in the app (lineup slots, game tracking's position-exclusion logic,
# etc.) reads through this grouping, so nothing else changes behavior.
# DH and UTL aren't part of the ask and pass through unchanged.
_POSITION_DISPLAY_GROUPS = {
    "1B": "INF", "2B": "INF", "3B": "INF", "SS": "INF",
    "LF": "OF", "CF": "OF", "RF": "OF",
}

# Fixed display order for the grouped Position filter dropdown -- built
# once here rather than derived from the (still-granular) positions
# table, since several specific positions now collapse onto one entry.
_POSITION_FILTER_CHOICES = ["RHP", "LHP", "C", "INF", "OF", "DH", "UTL"]


def _display_position(position_name):
    """Specific position name -> grouped display label. None/"" -> None
    so callers can fall back to their own placeholder (e.g. "—")."""
    if not position_name:
        return None
    return _POSITION_DISPLAY_GROUPS.get(position_name, position_name)


def _upload_player_photo(file_info: dict, player_identifier: str):
    """Uploads to the player-photos Supabase Storage bucket, returns the
    public URL, or None (with a toast) on failure. file_info is one
    entry from ui.input_file()'s list -- {"name", "size", "type",
    "datapath"} -- datapath is a real temp file Shiny already wrote the
    upload to, unlike Streamlit's in-memory UploadedFile."""
    try:
        admin_client = get_supabase_admin_client()
        ext = file_info["name"].split(".")[-1].lower()
        path = f"{player_identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        with open(file_info["datapath"], "rb") as f:
            file_bytes = f.read()
        admin_client.storage.from_(PHOTO_BUCKET).upload(
            path, file_bytes, {"content-type": file_info.get("type") or "application/octet-stream"}
        )
        return admin_client.storage.from_(PHOTO_BUCKET).get_public_url(path)
    except Exception as e:
        ui.notification_show(
            f"Photo upload failed: {e}. Make sure a public Storage bucket named '{PHOTO_BUCKET}' exists in "
            f"your Supabase project (Supabase dashboard -> Storage -> New bucket -> name it '{PHOTO_BUCKET}' "
            f"-> make it Public).",
            type="error", duration=12,
        )
        return None


@module.ui
def players_ui():
    return ui.div(
        ui_helpers.page_header("Players"),
        ui.output_ui("roster_section"),
        ui.hr(),
        ui.h5("Add or edit a player", class_="gbo-section-title"),
        ui.output_ui("player_picker"),
        ui.output_ui("player_form_fields"),
        ui.output_ui("arsenal_section"),
        ui.hr(),
        ui.output_ui("delete_section"),
        ui_helpers.page_footer(),
    )


@module.server
def players_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _reference_data(db):
        return dict(
            teams=db.query(Team).all(),
            classes=db.query(PlayerClass).order_by(PlayerClass.display_order).all(),
            statuses=db.query(PlayerStatus).order_by(PlayerStatus.display_order).all(),
            positions=db.query(Position).order_by(Position.display_order).all(),
        )

    def _visible_players(db):
        """Active-only roster, scoped by role -- what the browsing table
        shows. Returns (players, assigned_ids | None)."""
        query = db.query(Player).options(
            joinedload(Player.player_position),
            joinedload(Player.player_secondary_position),
            joinedload(Player.player_class),
            joinedload(Player.status),
            joinedload(Player.team),
        ).filter(Player.active.is_(True))

        assigned_ids = None
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment)
                .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id())
                .all()
            ]
            query = query.filter(Player.player_id.in_(assigned_ids))

        return query.order_by(Player.last_name, Player.first_name).all(), assigned_ids

    def _manageable_players(db, assigned_ids):
        """Same scoping, but including inactive players -- used only by
        the add/edit and delete sections, same as the original."""
        query = db.query(Player).options(
            joinedload(Player.player_position),
            joinedload(Player.player_secondary_position),
            joinedload(Player.player_class),
            joinedload(Player.status),
            joinedload(Player.team),
        )
        if assigned_ids is not None:
            query = query.filter(Player.player_id.in_(assigned_ids))
        return query.order_by(Player.active.desc(), Player.last_name, Player.first_name).all()

    def _filtered_sorted_players(players, ref):
        needle = (input.search_text() or "").strip().lower()
        position_filter = input.position_filter() if "position_filter" in input else "All"
        class_filter = input.class_filter() if "class_filter" in input else "All"
        status_filter = input.status_filter() if "status_filter" in input else "All"
        sort_choice = input.sort_by() if "sort_by" in input else "Last Name"

        filtered = players
        if needle:
            filtered = [p for p in filtered if needle in f"{p.first_name} {p.last_name}".lower()]
        if position_filter and position_filter != "All":
            filtered = [p for p in filtered if p.player_position and _display_position(p.player_position.position_name) == position_filter]
        if class_filter and class_filter != "All":
            filtered = [p for p in filtered if p.player_class and p.player_class.class_name == class_filter]
        if status_filter and status_filter != "All":
            filtered = [p for p in filtered if p.status and p.status.status_name == status_filter]

        if sort_choice == "Jersey #":
            filtered = sorted(filtered, key=lambda p: (p.jersey_number is None, p.jersey_number or 0))
        elif sort_choice == "Position":
            filtered = sorted(filtered, key=lambda p: (p.player_position.display_order if p.player_position else 999, p.last_name))
        elif sort_choice == "Class":
            filtered = sorted(filtered, key=lambda p: (p.player_class.display_order if p.player_class else 999, p.last_name))
        else:
            filtered = sorted(filtered, key=lambda p: (p.last_name, p.first_name))
        return filtered

    def _roster_table_ui(filtered_players):
        rows = []
        for p in filtered_players:
            photo_cell = ui.tags.img(src=p.photo_url, class_="gbo-roster-thumb") if p.photo_url else "—"
            rows.append(ui.tags.tr(
                ui.tags.td(photo_cell),
                ui.tags.td(f"{p.first_name} {p.last_name}"),
                ui.tags.td(str(p.jersey_number) if p.jersey_number else "—"),
                ui.tags.td(_display_position(p.player_position.position_name if p.player_position else None) or "—"),
                ui.tags.td(p.player_class.class_name if p.player_class else "—"),
                ui.tags.td(p.status.status_name if p.status else "—"),
                ui.tags.td("Yes" if p.is_pitcher else "No"),
                ui.tags.td(p.team.team_name if p.team else "—"),
            ))
        header = ui.tags.tr(*[ui.tags.th(c) for c in ("Photo", "Name", "#", "Position", "Class", "Status", "Pitcher", "Team")])
        return ui.tags.table(ui.tags.thead(header), ui.tags.tbody(*rows), class_="table table-sm")

    # -------------------------------------------------------------------
    # Roster: search/filter/sort + table + CSV export
    # -------------------------------------------------------------------

    @render.ui
    def roster_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None

        db = get_session()
        try:
            players, assigned_ids = _visible_players(db)
            ref = _reference_data(db)

            if not players:
                return ui_helpers.empty_state(
                    "No players to show yet." if app_state.can_view_all_players() else "No players are currently assigned to you."
                )

            controls = ui.layout_columns(
                ui.input_text("search_text", "Search by name", placeholder="Type a name..."),
                ui.input_select("position_filter", "Position", choices=["All"] + _POSITION_FILTER_CHOICES),
                ui.input_select("class_filter", "Class", choices=["All"] + [c.class_name for c in ref["classes"]]),
                ui.input_select("status_filter", "Status", choices=["All"] + [s.status_name for s in ref["statuses"]]),
                col_widths=[4, 3, 3, 2],
            )
            sort_control = ui.input_select("sort_by", "Sort by", choices=["Last Name", "Jersey #", "Position", "Class"])

            filtered = _filtered_sorted_players(players, ref)

            if not filtered:
                return ui.div(controls, sort_control, ui_helpers.empty_state("No players match the current search/filters."))

            return ui.div(
                controls,
                sort_control,
                ui.p(f"Showing {len(filtered)} of {len(players)} player(s).", class_="text-muted small"),
                _roster_table_ui(filtered),
                ui.download_button("download_roster", "Download roster as CSV", class_="btn-outline-secondary btn-sm mt-2"),
            )
        finally:
            db.close()

    @render.download(filename="gbo_roster.csv")
    def download_roster():
        db = get_session()
        try:
            players, _ = _visible_players(db)
            ref = _reference_data(db)
            filtered = _filtered_sorted_players(players, ref)

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(["First Name", "Last Name", "Jersey #", "Position", "Secondary Position", "Class", "Status", "Pitcher", "Team", "Height (in)", "Weight (lb)", "Hometown", "Previous School"])
            for p in filtered:
                writer.writerow([
                    p.first_name, p.last_name, p.jersey_number or "",
                    _display_position(p.player_position.position_name if p.player_position else None) or "",
                    _display_position(p.player_secondary_position.position_name if p.player_secondary_position else None) or "",
                    p.player_class.class_name if p.player_class else "",
                    p.status.status_name if p.status else "",
                    "Yes" if p.is_pitcher else "No",
                    p.team.team_name if p.team else "",
                    p.height_in or "", p.weight_lb or "",
                    p.hometown or "", p.previous_school or "",
                ])
            yield buf.getvalue()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Add / edit
    # -------------------------------------------------------------------

    @render.ui
    def player_picker():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            _, assigned_ids = _visible_players(db)
            manageable = _manageable_players(db, assigned_ids)
            ref = _reference_data(db)
            if not ref["teams"]:
                return ui.p("No teams exist yet. Run create_admin_user.py first to create a starter team.", class_="text-warning")

            choices = {"": "-- Add new player --"}
            for p in manageable:
                choices[str(p.player_id)] = f"{p.first_name} {p.last_name}" + ("" if p.active else " (Inactive)")
            return ui.input_select("player_select", "Select a player to edit, or add a new one:", choices=choices)
        finally:
            db.close()

    @render.ui
    def player_form_fields():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_id = input.player_select()

        db = get_session()
        try:
            _, assigned_ids = _visible_players(db)
            manageable = _manageable_players(db, assigned_ids)
            ref = _reference_data(db)
            if not ref["teams"]:
                return None
            players_by_id = {p.player_id: p for p in manageable}
            editing_player = players_by_id.get(int(selected_id)) if selected_id else None

            photo_block = []
            if editing_player and editing_player.photo_url:
                photo_block = [
                    ui.tags.img(src=editing_player.photo_url, style="width:150px; border-radius:6px;"),
                    ui.input_checkbox("remove_photo", "Remove current photo", value=False),
                ]

            team_names = [t.team_name for t in ref["teams"]]
            # Primary/Secondary Position now only offer the grouped set
            # (RHP/LHP/C/INF/OF/DH/UTL) -- picking a specific infield/
            # outfield spot for a player's profile is no longer a thing,
            # per Ryker's ask. Game Tracking's lineup-slot position picker
            # is unaffected -- it explicitly excludes INF/OF and still
            # offers the full granular list (see game_tracking.py).
            position_names = ["--"] + _POSITION_FILTER_CHOICES
            class_names = ["--"] + [c.class_name for c in ref["classes"]]
            status_names = ["--"] + [s.status_name for s in ref["statuses"]]

            default_team = editing_player.team.team_name if editing_player and editing_player.team else team_names[0]
            default_pos = editing_player.player_position.position_name if editing_player and editing_player.player_position else "--"
            default_sec_pos = editing_player.player_secondary_position.position_name if editing_player and editing_player.player_secondary_position else "--"
            default_class = editing_player.player_class.class_name if editing_player and editing_player.player_class else "--"
            default_status = (editing_player.status.status_name if editing_player and editing_player.status else ("Active" if "Active" in status_names else status_names[0]))

            confirm_deactivate_block = []
            if editing_player and editing_player.active:
                confirm_deactivate_block = [
                    ui.input_checkbox(
                        "confirm_deactivate",
                        f"Confirm hiding {editing_player.first_name} {editing_player.last_name} from the roster "
                        f"(only needed if you unchecked Active above)",
                        value=False,
                    )
                ]

            return ui.div(
                ui.markdown("**Photo**"),
                *photo_block,
                ui.input_file("photo_file", "Upload a photo (optional)", accept=[".jpg", ".jpeg", ".png", ".webp"]),

                ui.markdown("**Identity**"),
                ui.layout_columns(
                    ui.input_text("first_name", "First name", value=editing_player.first_name if editing_player else ""),
                    ui.input_text("last_name", "Last name", value=editing_player.last_name if editing_player else ""),
                ),
                ui.input_select("team_choice", "Team", choices=team_names, selected=default_team),

                ui.markdown("**Baseball info**"),
                ui.layout_columns(
                    ui.input_select("position_choice", "Primary position", choices=position_names, selected=default_pos),
                    ui.input_select("secondary_position_choice", "Secondary position", choices=position_names, selected=default_sec_pos),
                    ui.input_numeric("jersey_number", "Jersey #", value=editing_player.jersey_number if editing_player and editing_player.jersey_number else 0, min=0, max=99, step=1),
                ),
                ui.layout_columns(
                    ui.input_select("throws", "Throws", choices=["", "R", "L"], selected=editing_player.throws if editing_player and editing_player.throws in ("R", "L") else ""),
                    ui.input_select("bats", "Bats", choices=["", "R", "L", "S"], selected=editing_player.bats if editing_player and editing_player.bats in ("R", "L", "S") else ""),
                    ui.input_checkbox("is_pitcher", "Pitcher", value=editing_player.is_pitcher if editing_player else False),
                ),
                ui.input_select("class_choice", "Class", choices=class_names, selected=default_class),
                ui.input_numeric("graduation_year", "Graduation year", value=editing_player.graduation_year if editing_player and editing_player.graduation_year else 2026, min=2024, max=2035, step=1),

                ui.markdown("**Physical**"),
                ui.layout_columns(
                    ui.input_numeric("height_in", "Height (in)", value=float(editing_player.height_in) if editing_player and editing_player.height_in else 0.0, min=0.0, max=90.0, step=0.5),
                    ui.input_numeric("weight_lb", "Weight (lb)", value=float(editing_player.weight_lb) if editing_player and editing_player.weight_lb else 0.0, min=0.0, max=400.0, step=1.0),
                    ui.input_select("dominant_hand", "Dominant hand", choices=["", "R", "L"], selected=editing_player.dominant_hand if editing_player and editing_player.dominant_hand in ("R", "L") else ""),
                    ui.input_select("dominant_leg", "Dominant leg", choices=["", "R", "L"], selected=editing_player.dominant_leg if editing_player and editing_player.dominant_leg in ("R", "L") else ""),
                ),

                ui.markdown("**Background**"),
                ui.layout_columns(
                    ui.input_text("hometown", "Hometown", value=(editing_player.hometown if editing_player else "") or ""),
                    ui.input_text("previous_school", "Previous school", value=(editing_player.previous_school if editing_player else "") or "", placeholder="High school, or JUCO/transfer school if applicable"),
                ),
                ui.input_date("dob", "Date of birth", value=editing_player.date_of_birth if editing_player and editing_player.date_of_birth else date(2005, 1, 1)),
                ui.input_text("email", "Email", value=(editing_player.email if editing_player else "") or ""),

                ui.markdown("**Movement Flag**"),
                ui.p(
                    "These two feed the Movement Flag on the player's Physical Testing "
                    "breakdown, alongside their ROM deficit count -- see Assessments/My "
                    "Assessments for how the flag itself is calculated.",
                    class_="text-muted small",
                ),
                ui.input_checkbox("poor_mover", "Poor Mover", value=editing_player.poor_mover if editing_player else False),
                ui.input_checkbox(
                    "current_injury", "Current injury / surgical recovery",
                    value=editing_player.current_injury if editing_player else False,
                ),
                ui.input_text_area(
                    "injury_note", "Injury note (optional)",
                    value=(editing_player.injury_note if editing_player else "") or "",
                    placeholder="e.g. \"UCL reconstruction, 4 months post-op\" -- shown as the flag's reason when checked above.",
                    rows=2,
                ),

                ui.markdown("**Status**"),
                ui.input_select("status_choice", "Status", choices=status_names, selected=default_status),
                ui.input_checkbox("active", "Active in system (unchecking soft-deletes/hides them)", value=editing_player.active if editing_player else True),
                *confirm_deactivate_block,

                ui.input_action_button("save_player_btn", "Save player", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_player_btn)
    def _save_player():
        db = get_session()
        try:
            _, assigned_ids = _visible_players(db)
            active_players, _ = _visible_players(db)
            manageable = _manageable_players(db, assigned_ids)
            ref = _reference_data(db)
            players_by_id = {p.player_id: p for p in manageable}
            selected_id = input.player_select()
            editing_player = players_by_id.get(int(selected_id)) if selected_id else None

            first_name = input.first_name()
            last_name = input.last_name()
            team_choice = input.team_choice()
            position_choice = input.position_choice()
            secondary_position_choice = input.secondary_position_choice()
            jersey_number = input.jersey_number()
            throws = input.throws()
            bats = input.bats()
            is_pitcher = input.is_pitcher()
            class_choice = input.class_choice()
            graduation_year = input.graduation_year()
            height_in = input.height_in()
            weight_lb = input.weight_lb()
            dominant_hand = input.dominant_hand()
            dominant_leg = input.dominant_leg()
            hometown = input.hometown()
            previous_school = input.previous_school()
            dob = input.dob()
            email = input.email()
            poor_mover = input.poor_mover()
            current_injury = input.current_injury()
            injury_note = input.injury_note()
            status_choice = input.status_choice()
            active = input.active()
            confirm_deactivate = input.confirm_deactivate() if "confirm_deactivate" in input else False
            remove_photo = input.remove_photo() if "remove_photo" in input else False

            validation_errors = []
            if not (first_name or "").strip() or not (last_name or "").strip():
                validation_errors.append("First and last name are required.")

            if jersey_number and jersey_number > 0:
                team_id_for_check = next((t.team_id for t in ref["teams"] if t.team_name == team_choice), None)
                conflict = next(
                    (
                        p for p in active_players
                        if p.team_id == team_id_for_check
                        and p.jersey_number == int(jersey_number)
                        and (not editing_player or p.player_id != editing_player.player_id)
                    ),
                    None,
                )
                if conflict:
                    validation_errors.append(f"Jersey #{int(jersey_number)} is already used by {conflict.first_name} {conflict.last_name} on this team.")

            if editing_player and editing_player.active and not active and not confirm_deactivate:
                validation_errors.append(f"Check the confirmation box to hide {editing_player.first_name} {editing_player.last_name} from the roster.")

            if validation_errors:
                for err in validation_errors:
                    ui.notification_show(err, type="error", duration=10)
                return

            if height_in and not (48 <= height_in <= 84):
                ui.notification_show(f"Height of {height_in}\" is unusual for a player -- double check this before saving again if it's a typo.", type="warning", duration=10)
            if weight_lb and not (100 <= weight_lb <= 350):
                ui.notification_show(f"Weight of {weight_lb} lb is unusual for a player -- double check this before saving again if it's a typo.", type="warning", duration=10)
            duplicate_name = next(
                (
                    p for p in active_players
                    if p.first_name.strip().lower() == (first_name or "").strip().lower()
                    and p.last_name.strip().lower() == (last_name or "").strip().lower()
                    and (not editing_player or p.player_id != editing_player.player_id)
                ),
                None,
            )
            if duplicate_name:
                ui.notification_show(f"Another player named {first_name} {last_name} already exists on the roster -- make sure this isn't a duplicate entry.", type="warning", duration=10)

            EXPECTED_YEARS_TO_GRAD = {"Freshman": 4, "Sophomore": 3, "Junior": 2, "Senior": 1, "Graduate": 1}
            if class_choice in EXPECTED_YEARS_TO_GRAD and graduation_year:
                expected = date.today().year + EXPECTED_YEARS_TO_GRAD[class_choice]
                if abs(int(graduation_year) - expected) > 1:
                    ui.notification_show(
                        f"Graduation year {int(graduation_year)} looks off for class '{class_choice}' "
                        f"(expected around {expected}) -- double check before saving again if it's a typo.",
                        type="warning", duration=10,
                    )

            team_id = next(t.team_id for t in ref["teams"] if t.team_name == team_choice)
            class_id = next((c.class_id for c in ref["classes"] if c.class_name == class_choice), None)
            status_id = next((s.status_id for s in ref["statuses"] if s.status_name == status_choice), None)
            position_id = next((p.position_id for p in ref["positions"] if p.position_name == position_choice), None)
            secondary_position_id = next((p.position_id for p in ref["positions"] if p.position_name == secondary_position_choice), None)

            photo_url = editing_player.photo_url if editing_player else None
            if remove_photo:
                photo_url = None
            uploaded_files = input.photo_file()
            if uploaded_files:
                identifier = f"player-{editing_player.player_id}" if editing_player else f"player-new-{(last_name or '').strip()}"
                uploaded_url = _upload_player_photo(uploaded_files[0], identifier)
                if uploaded_url:
                    photo_url = uploaded_url

            field_values = dict(
                team_id=team_id,
                first_name=(first_name or "").strip(),
                last_name=(last_name or "").strip(),
                position_id=position_id,
                secondary_position_id=secondary_position_id,
                photo_url=photo_url,
                jersey_number=int(jersey_number) or None,
                throws=throws or None,
                bats=bats or None,
                is_pitcher=is_pitcher,
                class_id=class_id,
                graduation_year=int(graduation_year) or None,
                height_in=height_in or None,
                weight_lb=weight_lb or None,
                dominant_hand=dominant_hand or None,
                dominant_leg=dominant_leg or None,
                hometown=(hometown or "").strip() or None,
                previous_school=(previous_school or "").strip() or None,
                date_of_birth=dob,
                email=(email or "").strip() or None,
                poor_mover=poor_mover,
                current_injury=current_injury,
                injury_note=(injury_note or "").strip() or None,
                status_id=status_id,
                active=active,
            )

            if editing_player:
                for field, value in field_values.items():
                    setattr(editing_player, field, value)
                db.commit()
                ui.notification_show(f"Updated {first_name} {last_name}.", type="message", duration=6)
            else:
                new_player = Player(**field_values)
                db.add(new_player)
                db.commit()
                ui.notification_show(f"Added {first_name} {last_name} to the roster.", type="message", duration=6)

            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch arsenal
    # -------------------------------------------------------------------

    @render.ui
    def arsenal_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_id = input.player_select()
        if not selected_id:
            return None

        db = get_session()
        try:
            _, assigned_ids = _visible_players(db)
            manageable = _manageable_players(db, assigned_ids)
            players_by_id = {p.player_id: p for p in manageable}
            editing_player = players_by_id.get(int(selected_id))
            if editing_player is None or not editing_player.is_pitcher:
                return None

            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            existing_arsenal = db.query(PlayerPitchArsenal).filter(PlayerPitchArsenal.player_id == editing_player.player_id).all()
            existing_type_ids = {a.pitch_type_id for a in existing_arsenal}

            return ui.div(
                ui.hr(),
                ui.h5(f"Pitch arsenal — {editing_player.first_name} {editing_player.last_name}", class_="gbo-section-title"),
                ui.p(
                    "Which pitches he actually throws -- filters the pitch-type dropdown to his real arsenal during "
                    "live tracking (Game Tracking, Bullpen Tracking). Leave empty and every pitch type stays "
                    "available, so this never blocks data entry.",
                    class_="text-muted small",
                ),
                ui.input_selectize(
                    "arsenal_types", "Pitch types thrown",
                    choices={str(pt.pitch_type_id): pt.type_name for pt in pitch_types},
                    selected=[str(tid) for tid in existing_type_ids],
                    multiple=True,
                ),
                ui.input_action_button("save_arsenal_btn", "Save arsenal", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_arsenal_btn)
    def _save_arsenal():
        selected_id = input.player_select()
        if not selected_id:
            return
        selected_type_ids = [int(tid) for tid in (input.arsenal_types() or ())]

        db = get_session()
        try:
            player_id = int(selected_id)
            player = db.query(Player).filter(Player.player_id == player_id).first()
            if player is None:
                return
            existing_arsenal = db.query(PlayerPitchArsenal).filter(PlayerPitchArsenal.player_id == player_id).all()
            for a in existing_arsenal:
                db.delete(a)
            for tid in selected_type_ids:
                db.add(PlayerPitchArsenal(player_id=player_id, pitch_type_id=tid, active=True))
            db.commit()
            ui.notification_show(f"Saved arsenal for {player.first_name} {player.last_name}.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Delete
    # -------------------------------------------------------------------

    @render.ui
    def delete_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            _, assigned_ids = _visible_players(db)
            manageable = _manageable_players(db, assigned_ids)
            if not manageable:
                return None
            choices = {
                str(p.player_id): f"{p.first_name} {p.last_name}" + ("" if p.active else " (inactive)")
                for p in manageable
            }
            return ui.accordion(
                ui.accordion_panel(
                    "Delete a player",
                    ui.p(
                        "For real players with any history (assessments, IDP goals, training sessions, etc.), "
                        "deactivate them above instead -- that preserves their record. This is meant for cleaning "
                        "up accidental duplicates or test entries with nothing attached to them yet.",
                        class_="text-muted small",
                    ),
                    ui.input_select("delete_player_select", "Which player?", choices=choices),
                    ui.output_ui("delete_confirm_area"),
                ),
                open=False, id=None,
            )
        finally:
            db.close()

    @render.ui
    def delete_confirm_area():
        req("delete_player_select" in input)
        delete_player_id = input.delete_player_select()
        if not delete_player_id:
            return None
        delete_player_id = int(delete_player_id)

        db = get_session()
        try:
            target_player = db.query(Player).filter(Player.player_id == delete_player_id).first()
            if target_player is None:
                return None

            related_counts = {
                "assessments": db.query(Assessment).filter(Assessment.player_id == delete_player_id).count(),
                "IDP goals": db.query(IDPGoal).filter(IDPGoal.player_id == delete_player_id).count(),
                "training sessions": db.query(TrainingSession).filter(TrainingSession.player_id == delete_player_id).count(),
                "player assignments": db.query(PlayerAssignment).filter(PlayerAssignment.player_id == delete_player_id).count(),
                "bullpen sessions": db.query(BullpenSession).filter(BullpenSession.player_id == delete_player_id).count(),
                "linked user accounts": db.query(User).filter(User.player_id == delete_player_id).count(),
            }
            has_related_data = any(count > 0 for count in related_counts.values())

            if has_related_data:
                present = ", ".join(f"{count} {label}" for label, count in related_counts.items() if count > 0)
                return ui.p(
                    f"{target_player.first_name} {target_player.last_name} has real data attached ({present}) -- "
                    f"deactivate them above instead of deleting.",
                    class_="text-danger",
                )

            return ui.div(
                ui.p(
                    f"{target_player.first_name} {target_player.last_name} has no assessments, goals, sessions, "
                    f"assignments, bullpens, or linked accounts -- safe to delete.",
                    class_="text-muted small",
                ),
                ui.input_checkbox("confirm_delete_player", "Yes, permanently delete this player", value=False),
                ui.input_action_button("delete_player_btn", "Delete player", class_="btn-danger mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_player_btn)
    def _delete_player():
        if not (input.confirm_delete_player() if "confirm_delete_player" in input else False):
            return
        delete_player_id = input.delete_player_select()
        if not delete_player_id:
            return
        delete_player_id = int(delete_player_id)

        db = get_session()
        try:
            target_player = db.query(Player).filter(Player.player_id == delete_player_id).first()
            if target_player is None:
                return
            name = f"{target_player.first_name} {target_player.last_name}"
            db.delete(target_player)
            db.commit()
            ui.notification_show(f"Deleted {name}.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()
