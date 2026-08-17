"""
GBO -- User Management module.

Direct port of pages/user_management.py -- Administrator-only. Replaces
the terminal scripts (create_admin_user.py, create_staff_user.py,
set_password.py) with a real in-app screen: view all users, create a
new user (any role, including Player -- linked to an existing roster
player), edit an existing user's role/status/photo, and reset a
password. Creating an account and resetting a password both call the
Supabase Admin API (service role key) -- same mechanism the terminal
scripts and the original page used.

Same CRUD conventions as players.py (the first module in this migration
to establish them): st.form -> plain input_*() fields read inside a
@reactive.effect + @reactive.event() click handler; st.rerun() ->
bumping _refresh_tick; st.file_uploader -> ui.input_file (a real temp
file per entry, read via open(...).read() instead of .getvalue()).

The original moved its Role selects OUTSIDE st.form so the
player-link/specialty picker below could react immediately (widgets
inside a Streamlit form don't rerun the app until submit). Shiny has no
such batching -- every input is always live -- so the real reason for
the split here is the usual ordering hazard instead: a render.ui block
can't read an input it just defined in the same block. Hence four
separate blocks for Create (role picker -> conditional fields) and
three for Edit (user picker -> role picker -> conditional fields),
mirroring player_stats.py's category -> pitch-type-filter chain.
"""

import uuid

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import User, Role, Organization, Player
from supabase_client import get_supabase_admin_client

import ui_helpers

STAFF_PHOTO_BUCKET = "staff-photos"
SPECIALTY_OPTIONS = ["Both", "Pitching", "Hitting"]


def _upload_staff_photo(file_info: dict, user_identifier: str):
    """Uploads to the staff-photos Supabase Storage bucket, returns the
    public URL, or None (with a toast) on failure -- same pattern as
    players.py's _upload_player_photo."""
    try:
        admin_client = get_supabase_admin_client()
        ext = file_info["name"].split(".")[-1].lower()
        path = f"{user_identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        with open(file_info["datapath"], "rb") as f:
            file_bytes = f.read()
        admin_client.storage.from_(STAFF_PHOTO_BUCKET).upload(
            path, file_bytes, {"content-type": file_info.get("type") or "application/octet-stream"}
        )
        return admin_client.storage.from_(STAFF_PHOTO_BUCKET).get_public_url(path)
    except Exception as e:
        ui.notification_show(
            f"Photo upload failed: {e}. Make sure a public Storage bucket named '{STAFF_PHOTO_BUCKET}' exists in "
            f"your Supabase project (Supabase dashboard -> Storage -> New bucket -> name it '{STAFF_PHOTO_BUCKET}' "
            f"-> make it Public).",
            type="error", duration=12,
        )
        return None


@module.ui
def user_management_ui():
    return ui.div(
        ui_helpers.page_header("User Management"),
        ui.output_ui("users_table"),
        ui.hr(),
        ui.h5("Create a new user", class_="gbo-section-title"),
        ui.output_ui("create_role_picker"),
        ui.output_ui("create_user_fields"),
        ui.hr(),
        ui.h5("Edit an existing user", class_="gbo-section-title"),
        ui.output_ui("edit_user_picker"),
        ui.output_ui("edit_role_picker"),
        ui.output_ui("edit_user_fields"),
        ui.output_ui("reset_password_section"),
        ui_helpers.page_footer(),
    )


@module.server
def user_management_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _access_ok():
        return app_state.is_authenticated() and app_state.role_name() == "Administrator"

    @render.ui
    def users_table():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if not _access_ok():
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            users = (
                db.query(User)
                .options(joinedload(User.role), joinedload(User.player))
                .order_by(User.active.desc(), User.last_name, User.first_name)
                .all()
            )
            return ui.div(
                ui.p(ui.strong("All users")),
                ui_helpers.render_dict_table([
                    {
                        "Name": f"{u.first_name} {u.last_name}",
                        "Email": u.email,
                        "Role": u.role.role_name if u.role else "—",
                        "Specialty": u.coach_specialty or "—",
                        "Linked Player": f"{u.player.first_name} {u.player.last_name}" if u.player else "—",
                        "Active": "Yes" if u.active else "No",
                    }
                    for u in users
                ], empty_message="No users to show yet."),
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Create a new user
    # -------------------------------------------------------------------

    @render.ui
    def create_role_picker():
        if not _access_ok():
            return None
        db = get_session()
        try:
            roles = db.query(Role).order_by(Role.role_id).all()
            return ui.input_select("create_user_role", "Role", choices=[r.role_name for r in roles])
        finally:
            db.close()

    @render.ui
    def create_user_fields():
        if not _access_ok():
            return None
        req("create_user_role" in input)
        role_choice = input.create_user_role()

        db = get_session()
        try:
            conditional_block = []
            if role_choice == "Player":
                eligible_players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                if eligible_players:
                    player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in eligible_players}
                    conditional_block.append(ui.input_select("create_linked_player", "Which player is this account for?", choices=player_choices))
                else:
                    conditional_block.append(ui.p("No players exist on the roster yet -- add one first from the Players page.", class_="text-warning"))
            elif role_choice == "Coach":
                conditional_block.append(ui.input_select(
                    "create_specialty", "Specialty", choices=SPECIALTY_OPTIONS,
                ))
                conditional_block.append(ui.p(
                    "Filters which Training Routines this coach sees -- Pitching coaches won't see hitting-only "
                    "routines and vice versa. Shared categories (Lifting, Conditioning, Mobility, Med Ball, "
                    "General) are visible either way.",
                    class_="text-muted small",
                ))

            return ui.div(
                *conditional_block,
                ui.layout_columns(
                    ui.input_text("create_first_name", "First name"),
                    ui.input_text("create_last_name", "Last name"),
                ),
                ui.input_text("create_email", "Email (their GBO login)"),
                ui.input_password("create_password", "Initial password (min 6 characters)"),
                ui.input_action_button("create_user_btn", "Create user", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.create_user_btn)
    def _create_user():
        role_choice = input.create_user_role()
        first_name = (input.create_first_name() or "").strip()
        last_name = (input.create_last_name() or "").strip()
        email = (input.create_email() or "").strip()
        password = input.create_password() or ""
        linked_player_id = int(input.create_linked_player()) if role_choice == "Player" and "create_linked_player" in input and input.create_linked_player() else None
        coach_specialty_choice = input.create_specialty() if role_choice == "Coach" and "create_specialty" in input else None

        db = get_session()
        try:
            roles = db.query(Role).order_by(Role.role_id).all()
            org = db.query(Organization).first()

            if not (first_name and last_name and email and len(password) >= 6):
                ui.notification_show("First name, last name, email, and a password of at least 6 characters are required.", type="error", duration=10)
                return
            if org is None:
                ui.notification_show("No organization exists yet.", type="error", duration=10)
                return
            if role_choice == "Player" and linked_player_id is None:
                ui.notification_show("Select which player this account is for.", type="error", duration=10)
                return
            if db.query(User).filter(User.email == email).first():
                ui.notification_show(f"A user with email {email} already exists.", type="error", duration=10)
                return

            try:
                admin_client = get_supabase_admin_client()
                auth_result = admin_client.auth.admin.create_user(
                    {"email": email, "password": password, "email_confirm": True}
                )
                role = next(r for r in roles if r.role_name == role_choice)
                new_user = User(
                    organization_id=org.organization_id,
                    auth_subject_id=auth_result.user.id,
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    role_id=role.role_id,
                    player_id=linked_player_id,
                    coach_specialty=coach_specialty_choice,
                    active=True,
                )
                db.add(new_user)
                db.commit()
                ui.notification_show(f"Created {role_choice} account for {first_name} {last_name}.", type="message", duration=8)
                _bump_refresh()
            except Exception as e:
                ui.notification_show(f"Failed to create account: {e}", type="error", duration=12)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Edit an existing user
    # -------------------------------------------------------------------

    @render.ui
    def edit_user_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        db = get_session()
        try:
            users = db.query(User).order_by(User.active.desc(), User.last_name, User.first_name).all()
            if not users:
                return ui_helpers.empty_state("No users to edit yet.")
            choices = {str(u.user_id): f"{u.first_name} {u.last_name} ({u.email})" for u in users}
            return ui.input_select("edit_user_select", "Select a user", choices=choices)
        finally:
            db.close()

    @render.ui
    def edit_role_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        req("edit_user_select" in input)
        db = get_session()
        try:
            editing_user = db.query(User).options(joinedload(User.role)).filter(User.user_id == int(input.edit_user_select())).first()
            if editing_user is None:
                return None
            roles = db.query(Role).order_by(Role.role_id).all()
            role_names = [r.role_name for r in roles]
            current_role = editing_user.role.role_name if editing_user.role else role_names[0]
            return ui.input_select("edit_role_choice", "Role", choices=role_names, selected=current_role)
        finally:
            db.close()

    @render.ui
    def edit_user_fields():
        _refresh_tick()
        if not _access_ok():
            return None
        req("edit_user_select" in input)
        req("edit_role_choice" in input)

        db = get_session()
        try:
            editing_user = db.query(User).filter(User.user_id == int(input.edit_user_select())).first()
            if editing_user is None:
                return None
            new_role_choice = input.edit_role_choice()

            conditional_block = []
            if new_role_choice == "Player":
                all_players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                if not all_players:
                    conditional_block.append(ui.p("No players exist on the roster yet -- add one first from the Players page.", class_="text-warning"))
                else:
                    player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in all_players}
                    default_player = str(editing_user.player_id) if editing_user.player_id in {p.player_id for p in all_players} else str(all_players[0].player_id)
                    conditional_block.append(ui.input_select("edit_linked_player", "Which player is this account for?", choices=player_choices, selected=default_player))
            elif new_role_choice == "Coach":
                default_specialty = editing_user.coach_specialty if editing_user.coach_specialty in SPECIALTY_OPTIONS else SPECIALTY_OPTIONS[0]
                conditional_block.append(ui.input_select("edit_specialty", "Specialty", choices=SPECIALTY_OPTIONS, selected=default_specialty))
                conditional_block.append(ui.p(
                    "Filters which Training Routines this coach sees -- Pitching coaches won't see hitting-only "
                    "routines and vice versa. Shared categories (Lifting, Conditioning, Mobility, Med Ball, "
                    "General) are visible either way.",
                    class_="text-muted small",
                ))

            photo_block = []
            if editing_user.photo_url:
                photo_block = [
                    ui.tags.img(src=editing_user.photo_url, style="width:150px; border-radius:6px;"),
                    ui.input_checkbox("edit_remove_photo", "Remove current photo", value=False),
                ]

            return ui.div(
                *conditional_block,
                ui.markdown("**Photo**"),
                *photo_block,
                ui.input_file("edit_photo_file", "Upload a photo (optional)", accept=[".jpg", ".jpeg", ".png", ".webp"]),
                ui.layout_columns(
                    ui.input_text("edit_first_name", "First name", value=editing_user.first_name),
                    ui.input_text("edit_last_name", "Last name", value=editing_user.last_name),
                ),
                ui.input_text("edit_email", "Email", value=editing_user.email),
                ui.input_checkbox("edit_active", "Active", value=editing_user.active),
                ui.input_action_button("save_user_btn", "Save changes", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_user_btn)
    def _save_user():
        db = get_session()
        try:
            editing_user = db.query(User).filter(User.user_id == int(input.edit_user_select())).first()
            if editing_user is None:
                return
            roles = db.query(Role).order_by(Role.role_id).all()
            new_role_choice = input.edit_role_choice()

            new_first_name = (input.edit_first_name() or "").strip()
            new_last_name = (input.edit_last_name() or "").strip()
            new_email = (input.edit_email() or "").strip()
            active_choice = input.edit_active()
            remove_photo = input.edit_remove_photo() if "edit_remove_photo" in input else False
            new_player_id = int(input.edit_linked_player()) if new_role_choice == "Player" and "edit_linked_player" in input and input.edit_linked_player() else None
            new_coach_specialty = input.edit_specialty() if new_role_choice == "Coach" and "edit_specialty" in input else None

            if not (new_first_name and new_last_name and new_email):
                ui.notification_show("First name, last name, and email are required.", type="error", duration=10)
                return

            email_changed = new_email != editing_user.email
            if email_changed and db.query(User).filter(User.email == new_email, User.user_id != editing_user.user_id).first():
                ui.notification_show(f"Another user already has the email {new_email}.", type="error", duration=10)
                return

            if email_changed and editing_user.auth_subject_id:
                try:
                    admin_client = get_supabase_admin_client()
                    admin_client.auth.admin.update_user_by_id(editing_user.auth_subject_id, {"email": new_email})
                except Exception as e:
                    ui.notification_show(f"Failed to update login email in Supabase: {e}", type="error", duration=12)
                    return

            new_role = next(r for r in roles if r.role_name == new_role_choice)
            editing_user.first_name = new_first_name
            editing_user.last_name = new_last_name
            editing_user.email = new_email
            editing_user.role_id = new_role.role_id
            # Clear the player link if the role isn't Player anymore;
            # otherwise save whichever player was selected above. Same
            # for specialty -- only meaningful for Coach.
            editing_user.player_id = new_player_id if new_role_choice == "Player" else None
            editing_user.coach_specialty = new_coach_specialty if new_role_choice == "Coach" else None
            editing_user.active = active_choice

            photo_upload_failed = False
            if remove_photo:
                editing_user.photo_url = None
            else:
                uploaded_files = input.edit_photo_file()
                if uploaded_files:
                    identifier = f"staff-{editing_user.user_id}"
                    uploaded_url = _upload_staff_photo(uploaded_files[0], identifier)
                    if uploaded_url:
                        editing_user.photo_url = uploaded_url
                    else:
                        # _upload_staff_photo already showed the real error --
                        # stop here instead of continuing on to commit, which
                        # would imply the photo saved when it didn't.
                        photo_upload_failed = True

            if not photo_upload_failed:
                db.commit()
                ui.notification_show(f"Updated {editing_user.first_name} {editing_user.last_name}.", type="message", duration=8)
                _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Reset password
    # -------------------------------------------------------------------

    @render.ui
    def reset_password_section():
        if not _access_ok():
            return None
        req("edit_user_select" in input)
        return ui.div(
            ui.markdown("**Reset password**"),
            ui.input_password("reset_pw", "New password (min 6 characters)"),
            ui.input_password("reset_pw_confirm", "Confirm new password"),
            ui.input_action_button("reset_password_btn", "Reset password", class_="btn-primary mt-2"),
        )

    @reactive.effect
    @reactive.event(input.reset_password_btn)
    def _reset_password():
        new_password = input.reset_pw() or ""
        confirm_password = input.reset_pw_confirm() or ""

        if len(new_password) < 6:
            ui.notification_show("Password must be at least 6 characters.", type="error", duration=10)
            return
        if new_password != confirm_password:
            ui.notification_show("Passwords do not match.", type="error", duration=10)
            return

        db = get_session()
        try:
            editing_user = db.query(User).filter(User.user_id == int(input.edit_user_select())).first()
            if editing_user is None:
                return
            try:
                admin_client = get_supabase_admin_client()
                auth_users = admin_client.auth.admin.list_users()
                match = next((u for u in auth_users if u.email == editing_user.email), None)
                if match is None:
                    ui.notification_show(f"No Supabase Auth account found for {editing_user.email}.", type="error", duration=10)
                else:
                    admin_client.auth.admin.update_user_by_id(match.id, {"password": new_password})
                    ui.notification_show(f"Password updated for {editing_user.first_name} {editing_user.last_name}.", type="message", duration=8)
            except Exception as e:
                ui.notification_show(f"Failed to reset password: {e}", type="error", duration=12)
        finally:
            db.close()
