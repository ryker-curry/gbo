"""
GBO — Player Management (Milestone: Aug 4-6).

Roster list + add/edit, filtered by role:
  - Coach sees only players assigned to them (via staff_player_assignments)
  - every other staff role sees the full active roster
  - all staff roles can add/edit players (per Ryker's decision)

Fields match Ryker's Master Player Profile Data Dictionary (Player
Information sheet): jersey number, throws/bats, class, graduation year,
dominant hand/leg, hometown, high school, height, weight, status.

Known MVP limitation: a newly-added player isn't automatically assigned
to the Coach who added them, so a Coach won't see a player they just
created until an assignment exists. Staff assignment management isn't
built yet -- flagged for a later milestone.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
import uuid
import csv
import io
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, Team, StaffPlayerAssignment, PlayerClass, PlayerStatus, Position, Assessment, IDPGoal, TrainingSession, PlayerAssignment, BullpenSession, User, PitchType, PlayerPitchArsenal
from supabase_client import get_supabase_admin_client

PHOTO_BUCKET = "player-photos"


def upload_player_photo(uploaded_file, player_identifier: str) -> str | None:
    """Uploads to the player-photos Supabase Storage bucket, returns the
    public URL. Returns None (with an on-screen error) if the bucket
    doesn't exist yet or the upload fails."""
    try:
        admin_client = get_supabase_admin_client()
        ext = uploaded_file.name.split(".")[-1].lower()
        path = f"{player_identifier}_{uuid.uuid4().hex[:8]}.{ext}"
        file_bytes = uploaded_file.getvalue()
        admin_client.storage.from_(PHOTO_BUCKET).upload(
            path, file_bytes, {"content-type": uploaded_file.type}
        )
        return admin_client.storage.from_(PHOTO_BUCKET).get_public_url(path)
    except Exception as e:
        st.error(
            f"Photo upload failed: {e}. "
            f"Make sure a public Storage bucket named '{PHOTO_BUCKET}' exists in your Supabase project "
            f"(Supabase dashboard -> Storage -> New bucket -> name it '{PHOTO_BUCKET}' -> make it Public)."
        )
        return None

page_header("Players")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    # --- Build the visible roster based on role ---
    query = session.query(Player).options(
        joinedload(Player.player_position),
        joinedload(Player.player_secondary_position),
        joinedload(Player.player_class),
        joinedload(Player.status),
        joinedload(Player.team),
    ).filter(Player.active.is_(True))

    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        query = query.filter(Player.player_id.in_(assigned_ids))

    players = query.order_by(Player.last_name, Player.first_name).all()
    teams = session.query(Team).all()
    classes = session.query(PlayerClass).order_by(PlayerClass.display_order).all()
    statuses = session.query(PlayerStatus).order_by(PlayerStatus.display_order).all()
    positions = session.query(Position).order_by(Position.display_order).all()

    # --- Search / filter ---
    if players:
        search_col, pos_col, class_col, status_col = st.columns([2, 1, 1, 1])
        search_text = search_col.text_input("Search by name", placeholder="Type a name...")
        position_filter = pos_col.selectbox("Position", ["All"] + [p.position_name for p in positions])
        class_filter = class_col.selectbox("Class", ["All"] + [c.class_name for c in classes])
        status_filter = status_col.selectbox("Status", ["All"] + [s.status_name for s in statuses])

        filtered_players = players
        if search_text.strip():
            needle = search_text.strip().lower()
            filtered_players = [
                p for p in filtered_players
                if needle in f"{p.first_name} {p.last_name}".lower()
            ]
        if position_filter != "All":
            filtered_players = [
                p for p in filtered_players
                if p.player_position and p.player_position.position_name == position_filter
            ]
        if class_filter != "All":
            filtered_players = [
                p for p in filtered_players
                if p.player_class and p.player_class.class_name == class_filter
            ]
        if status_filter != "All":
            filtered_players = [
                p for p in filtered_players
                if p.status and p.status.status_name == status_filter
            ]

        sort_col, _ = st.columns([1, 3])
        sort_choice = sort_col.selectbox(
            "Sort by",
            ["Last Name", "Jersey #", "Position", "Class"],
        )
        if sort_choice == "Last Name":
            filtered_players = sorted(filtered_players, key=lambda p: (p.last_name, p.first_name))
        elif sort_choice == "Jersey #":
            filtered_players = sorted(filtered_players, key=lambda p: (p.jersey_number is None, p.jersey_number or 0))
        elif sort_choice == "Position":
            filtered_players = sorted(
                filtered_players,
                key=lambda p: (p.player_position.display_order if p.player_position else 999, p.last_name),
            )
        elif sort_choice == "Class":
            filtered_players = sorted(
                filtered_players,
                key=lambda p: (p.player_class.display_order if p.player_class else 999, p.last_name),
            )
    else:
        filtered_players = players

    # --- Roster table ---
    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
    elif not filtered_players:
        empty_state("No players match the current search/filters.")
    else:
        st.caption(f"Showing {len(filtered_players)} of {len(players)} player(s).")
        st.dataframe(
            [
                {
                    "Photo": p.photo_url or "",
                    "Name": f"{p.first_name} {p.last_name}",
                    "#": p.jersey_number or "—",
                    "Position": p.player_position.position_name if p.player_position else "—",
                    "Class": p.player_class.class_name if p.player_class else "—",
                    "Status": p.status.status_name if p.status else "—",
                    "Pitcher": "Yes" if p.is_pitcher else "No",
                    "Team": p.team.team_name if p.team else "—",
                }
                for p in filtered_players
            ],
            use_container_width=True,
            hide_index=True,
            column_config={"Photo": st.column_config.ImageColumn("Photo")},
        )

        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["First Name", "Last Name", "Jersey #", "Position", "Secondary Position", "Class", "Status", "Pitcher", "Team", "Height (in)", "Weight (lb)", "Hometown", "Previous School"])
        for p in filtered_players:
            writer.writerow([
                p.first_name, p.last_name, p.jersey_number or "",
                p.player_position.position_name if p.player_position else "",
                p.player_secondary_position.position_name if p.player_secondary_position else "",
                p.player_class.class_name if p.player_class else "",
                p.status.status_name if p.status else "",
                "Yes" if p.is_pitcher else "No",
                p.team.team_name if p.team else "",
                p.height_in or "", p.weight_lb or "",
                p.hometown or "", p.previous_school or "",
            ])
        st.download_button(
            "Download roster as CSV",
            data=csv_buffer.getvalue(),
            file_name="gbo_roster.csv",
            mime="text/csv",
        )

    st.divider()

    # --- Add / Edit (all staff roles can do this per Ryker's decision) ---
    st.subheader("Add or edit a player")

    if not teams:
        st.warning("No teams exist yet. Run create_admin_user.py first to create a starter team.")
        page_footer()
        st.stop()

    players_by_id = {p.player_id: p for p in players}
    selected_id = st.selectbox(
        "Select a player to edit, or add a new one:",
        options=[None] + list(players_by_id.keys()),
        format_func=lambda pid: "-- Add new player --" if pid is None else f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )
    # Re-fetch by plain ID (not a live object) so we never hand a stale,
    # session-detached Player across Streamlit reruns.
    editing_player = players_by_id.get(selected_id) if selected_id is not None else None

    with st.form("player_form"):
        st.markdown("**Photo**")
        remove_photo = False
        if editing_player and editing_player.photo_url:
            st.image(editing_player.photo_url, width=150)
            remove_photo = st.checkbox("Remove current photo")
        photo_file = st.file_uploader("Upload a photo (optional)", type=["jpg", "jpeg", "png", "webp"])

        st.markdown("**Identity**")
        c1, c2 = st.columns(2)
        first_name = c1.text_input("First name", value=editing_player.first_name if editing_player else "")
        last_name = c2.text_input("Last name", value=editing_player.last_name if editing_player else "")

        team_names = [t.team_name for t in teams]
        default_team_idx = team_names.index(editing_player.team.team_name) if editing_player and editing_player.team else 0
        team_choice = st.selectbox("Team", team_names, index=default_team_idx)

        st.markdown("**Baseball info**")
        c1, c2, c3 = st.columns(3)
        position_names = ["--"] + [p.position_name for p in positions]
        default_pos_idx = position_names.index(editing_player.player_position.position_name) if editing_player and editing_player.player_position else 0
        position_choice = c1.selectbox("Primary position", position_names, index=default_pos_idx)
        default_sec_pos_idx = position_names.index(editing_player.player_secondary_position.position_name) if editing_player and editing_player.player_secondary_position else 0
        secondary_position_choice = c2.selectbox("Secondary position", position_names, index=default_sec_pos_idx)
        jersey_number = c3.number_input("Jersey #", min_value=0, max_value=99, step=1, value=editing_player.jersey_number if editing_player and editing_player.jersey_number else 0)

        c1, c2, c3 = st.columns(3)
        throws = c1.selectbox("Throws", ["", "R", "L"], index=["", "R", "L"].index(editing_player.throws) if editing_player and editing_player.throws in ("R", "L") else 0)
        bats = c2.selectbox("Bats", ["", "R", "L", "S"], index=["", "R", "L", "S"].index(editing_player.bats) if editing_player and editing_player.bats in ("R", "L", "S") else 0)
        is_pitcher = c3.checkbox("Pitcher", value=editing_player.is_pitcher if editing_player else False)

        class_names = ["--"] + [c.class_name for c in classes]
        default_class_idx = class_names.index(editing_player.player_class.class_name) if editing_player and editing_player.player_class else 0
        class_choice = st.selectbox("Class", class_names, index=default_class_idx)
        graduation_year = st.number_input("Graduation year", min_value=2024, max_value=2035, step=1, value=editing_player.graduation_year if editing_player and editing_player.graduation_year else 2026)

        st.markdown("**Physical**")
        c1, c2, c3, c4 = st.columns(4)
        height_in = c1.number_input("Height (in)", min_value=0.0, max_value=90.0, step=0.5, value=float(editing_player.height_in) if editing_player and editing_player.height_in else 0.0)
        weight_lb = c2.number_input("Weight (lb)", min_value=0.0, max_value=400.0, step=1.0, value=float(editing_player.weight_lb) if editing_player and editing_player.weight_lb else 0.0)
        dominant_hand = c3.selectbox("Dominant hand", ["", "R", "L"], index=["", "R", "L"].index(editing_player.dominant_hand) if editing_player and editing_player.dominant_hand in ("R", "L") else 0)
        dominant_leg = c4.selectbox("Dominant leg", ["", "R", "L"], index=["", "R", "L"].index(editing_player.dominant_leg) if editing_player and editing_player.dominant_leg in ("R", "L") else 0)

        st.markdown("**Background**")
        c1, c2 = st.columns(2)
        hometown = c1.text_input("Hometown", value=(editing_player.hometown if editing_player else "") or "")
        previous_school = c2.text_input("Previous school", value=(editing_player.previous_school if editing_player else "") or "", placeholder="High school, or JUCO/transfer school if applicable")

        dob = st.date_input(
            "Date of birth",
            value=editing_player.date_of_birth if editing_player and editing_player.date_of_birth else date(2005, 1, 1),
        )
        email = st.text_input("Email", value=(editing_player.email if editing_player else "") or "")

        st.markdown("**Status**")
        status_names = ["--"] + [s.status_name for s in statuses]
        default_status_idx = status_names.index(editing_player.status.status_name) if editing_player and editing_player.status else (status_names.index("Active") if "Active" in status_names else 0)
        status_choice = st.selectbox("Status", status_names, index=default_status_idx)
        active = st.checkbox("Active in system (unchecking soft-deletes/hides them)", value=editing_player.active if editing_player else True)
        confirm_deactivate = False
        if editing_player and editing_player.active:
            confirm_deactivate = st.checkbox(
                f"Confirm hiding {editing_player.first_name} {editing_player.last_name} from the roster "
                f"(only needed if you unchecked Active above)"
            )

        submitted = st.form_submit_button("Save player", type="primary")

    if submitted:
        validation_errors = []

        if not first_name.strip() or not last_name.strip():
            validation_errors.append("First and last name are required.")

        # Duplicate jersey number on the same team (excluding this player if editing)
        if jersey_number and jersey_number > 0:
            team_id_for_check = next((t.team_id for t in teams if t.team_name == team_choice), None)
            conflict = next(
                (
                    p for p in players
                    if p.team_id == team_id_for_check
                    and p.jersey_number == int(jersey_number)
                    and (not editing_player or p.player_id != editing_player.player_id)
                ),
                None,
            )
            if conflict:
                validation_errors.append(
                    f"Jersey #{int(jersey_number)} is already used by {conflict.first_name} {conflict.last_name} on this team."
                )

        # Deactivating an active player requires the confirmation checkbox
        if editing_player and editing_player.active and not active and not confirm_deactivate:
            validation_errors.append(
                f"Check the confirmation box to hide {editing_player.first_name} {editing_player.last_name} from the roster."
            )

        if validation_errors:
            for err in validation_errors:
                st.error(err)
        else:
            # Soft warnings -- don't block saving, just flag for a second look
            if height_in and not (48 <= height_in <= 84):
                st.warning(f"Height of {height_in}\" is unusual for a player -- double check this before saving again if it's a typo.")
            if weight_lb and not (100 <= weight_lb <= 350):
                st.warning(f"Weight of {weight_lb} lb is unusual for a player -- double check this before saving again if it's a typo.")
            duplicate_name = next(
                (
                    p for p in players
                    if p.first_name.strip().lower() == first_name.strip().lower()
                    and p.last_name.strip().lower() == last_name.strip().lower()
                    and (not editing_player or p.player_id != editing_player.player_id)
                ),
                None,
            )
            if duplicate_name:
                st.warning(f"Another player named {first_name} {last_name} already exists on the roster -- make sure this isn't a duplicate entry.")

            # Graduation year vs. class sanity check (soft warning)
            EXPECTED_YEARS_TO_GRAD = {"Freshman": 4, "Sophomore": 3, "Junior": 2, "Senior": 1, "Graduate": 1}
            if class_choice in EXPECTED_YEARS_TO_GRAD and graduation_year:
                expected = date.today().year + EXPECTED_YEARS_TO_GRAD[class_choice]
                if abs(int(graduation_year) - expected) > 1:
                    st.warning(
                        f"Graduation year {int(graduation_year)} looks off for class '{class_choice}' "
                        f"(expected around {expected}) -- double check before saving again if it's a typo."
                    )

            team_id = next(t.team_id for t in teams if t.team_name == team_choice)
            class_id = next((c.class_id for c in classes if c.class_name == class_choice), None)
            status_id = next((s.status_id for s in statuses if s.status_name == status_choice), None)
            position_id = next((p.position_id for p in positions if p.position_name == position_choice), None)
            secondary_position_id = next((p.position_id for p in positions if p.position_name == secondary_position_choice), None)

            photo_url = editing_player.photo_url if editing_player else None
            if remove_photo:
                photo_url = None
            if photo_file is not None:
                identifier = f"player-{editing_player.player_id}" if editing_player else f"player-new-{last_name.strip()}"
                uploaded_url = upload_player_photo(photo_file, identifier)
                if uploaded_url:
                    photo_url = uploaded_url

            field_values = dict(
                team_id=team_id,
                first_name=first_name.strip(),
                last_name=last_name.strip(),
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
                hometown=hometown.strip() or None,
                previous_school=previous_school.strip() or None,
                date_of_birth=dob,
                email=email.strip() or None,
                status_id=status_id,
                active=active,
            )

            if editing_player:
                for field, value in field_values.items():
                    setattr(editing_player, field, value)
                session.commit()
                st.success(f"Updated {first_name} {last_name}.")
            else:
                new_player = Player(**field_values)
                session.add(new_player)
                session.commit()
                st.success(f"Added {first_name} {last_name} to the roster.")
            st.rerun()

    if editing_player is not None and editing_player.is_pitcher:
        st.divider()
        st.subheader(f"Pitch arsenal — {editing_player.first_name} {editing_player.last_name}")
        st.caption("Which pitches he actually throws -- filters the pitch-type dropdown to his real arsenal during live tracking (Game Tracking, Bullpen Tracking). Leave empty and every pitch type stays available, so this never blocks data entry.")

        pitch_types = session.query(PitchType).order_by(PitchType.pitch_type_id).all()
        existing_arsenal = session.query(PlayerPitchArsenal).filter(PlayerPitchArsenal.player_id == editing_player.player_id, PlayerPitchArsenal.active.is_(True)).all()
        existing_type_ids = {a.pitch_type_id for a in existing_arsenal}

        with st.form(f"arsenal_form_{editing_player.player_id}"):
            selected_type_ids = st.multiselect(
                "Pitch types thrown",
                options=[pt.pitch_type_id for pt in pitch_types],
                default=list(existing_type_ids),
                format_func=lambda tid: next(pt.type_name for pt in pitch_types if pt.pitch_type_id == tid),
            )
            arsenal_submitted = st.form_submit_button("Save arsenal", type="primary")

        if arsenal_submitted:
            for a in existing_arsenal:
                session.delete(a)
            for tid in selected_type_ids:
                session.add(PlayerPitchArsenal(player_id=editing_player.player_id, pitch_type_id=tid, active=True))
            session.commit()
            st.success(f"Saved arsenal for {editing_player.first_name} {editing_player.last_name}.")
            st.rerun()

    st.divider()
    with st.expander("Delete a player"):
        st.caption(
            "For real players with any history (assessments, IDP goals, training sessions, etc.), "
            "deactivate them above instead -- that preserves their record. This is meant for cleaning "
            "up accidental duplicates or test entries with nothing attached to them yet."
        )
        delete_player_id = st.selectbox(
            "Which player?",
            options=list(players_by_id.keys()),
            format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" + ("" if players_by_id[pid].active else " (inactive)"),
            key="delete_player_choice",
        )
        target_player = players_by_id[delete_player_id]

        # Check for any related records before allowing a real delete --
        # a player with real history shouldn't be silently destroyable.
        related_counts = {
            "assessments": session.query(Assessment).filter(Assessment.player_id == delete_player_id).count(),
            "IDP goals": session.query(IDPGoal).filter(IDPGoal.player_id == delete_player_id).count(),
            "training sessions": session.query(TrainingSession).filter(TrainingSession.player_id == delete_player_id).count(),
            "player assignments": session.query(PlayerAssignment).filter(PlayerAssignment.player_id == delete_player_id).count(),
            "bullpen sessions": session.query(BullpenSession).filter(BullpenSession.player_id == delete_player_id).count(),
            "linked user accounts": session.query(User).filter(User.player_id == delete_player_id).count(),
        }
        has_related_data = any(count > 0 for count in related_counts.values())

        if has_related_data:
            present = ", ".join(f"{count} {label}" for label, count in related_counts.items() if count > 0)
            st.error(f"{target_player.first_name} {target_player.last_name} has real data attached ({present}) -- deactivate them above instead of deleting.")
        else:
            st.caption(f"{target_player.first_name} {target_player.last_name} has no assessments, goals, sessions, assignments, bullpens, or linked accounts -- safe to delete.")
            confirm_delete_player = st.checkbox("Yes, permanently delete this player", key=f"confirm_delete_player_{delete_player_id}")
            if st.button("Delete player", key=f"delete_player_{delete_player_id}", disabled=not confirm_delete_player, type="primary"):
                session.delete(target_player)
                session.commit()
                st.success(f"Deleted {target_player.first_name} {target_player.last_name}.")
                st.rerun()

finally:
    session.close()

page_footer()