"""
GBO — Opponent Teams.

Reusable opponent teams + rosters for Game Tracking -- create a team
once, pick it from a list for every future game against them, and
optionally build out their roster so pitch entry can select a real
named opposing player instead of just typing hand + batting order
each time. Roster is entirely optional -- Game Tracking works fine
with just hand/batting order typed in if a team's roster isn't built
out yet.
"""

import streamlit as st
import pandas as pd

from database import get_session
from models import OpponentTeam, OpponentPlayer, Game, GamePitch
from ui_components import page_header, page_footer, empty_state

page_header("Opponent Teams")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

session = get_session()
try:
    teams = session.query(OpponentTeam).order_by(OpponentTeam.team_name).all()

    st.subheader("Teams")
    if not teams:
        empty_state("No opponent teams created yet.")
    else:
        for t in teams:
            with st.expander(f"{t.team_name} ({len(t.roster)} roster player(s))"):
                if not t.roster:
                    st.caption("No roster players added yet.")
                else:
                    st.dataframe(
                        [
                            {
                                "Name": p.player_name,
                                "#": p.jersey_number or "",
                                "Bats": p.bats or "—",
                                "Throws": p.throws or "—",
                                "Position": p.position or "—",
                                "Notes": p.notes or "",
                            }
                            for p in t.roster
                        ],
                        use_container_width=True, hide_index=True,
                    )

    if not can_edit_sessions:
        st.info("Your role has read-only access to opponent teams.")
        page_footer()
        st.stop()

    st.divider()
    st.subheader("Create a new team")
    with st.form("new_team_form"):
        new_team_name = st.text_input("Team name")
        create_team_submitted = st.form_submit_button("Create team", type="primary")

    if create_team_submitted:
        if not new_team_name.strip():
            st.error("Team name is required.")
        else:
            existing = session.query(OpponentTeam).filter(OpponentTeam.team_name == new_team_name.strip()).first()
            if existing:
                st.error(f"A team named \"{new_team_name.strip()}\" already exists.")
            else:
                session.add(OpponentTeam(team_name=new_team_name.strip(), created_by_user_id=current_user_id))
                session.commit()
                st.success(f"Created {new_team_name.strip()}.")
                st.rerun()

    st.divider()
    st.subheader("Add roster players")
    if not teams:
        st.caption("Create a team above first.")
    else:
        teams_by_id = {t.team_id: t for t in teams}
        selected_team_id = st.selectbox(
            "Team",
            options=list(teams_by_id.keys()),
            format_func=lambda tid: teams_by_id[tid].team_name,
        )
        selected_team = teams_by_id[selected_team_id]

        st.caption(f"Type roster players for {selected_team.team_name} below -- add as many rows as you need, then save.")
        roster_table = st.data_editor(
            pd.DataFrame(columns=["Name", "Jersey #", "Bats", "Throws", "Position", "Notes"]),
            num_rows="dynamic",
            use_container_width=True,
            key=f"roster_table_{selected_team_id}",
            column_config={
                "Name": st.column_config.TextColumn(required=True),
                "Jersey #": st.column_config.TextColumn(),
                "Bats": st.column_config.SelectboxColumn(options=["R", "L", "S"]),
                "Throws": st.column_config.SelectboxColumn(options=["R", "L"]),
                "Position": st.column_config.TextColumn(),
                "Notes": st.column_config.TextColumn(),
            },
        )

        if st.button("Save roster players", type="primary"):
            valid_rows = roster_table[roster_table["Name"].notna() & (roster_table["Name"].str.strip() != "")]
            if valid_rows.empty:
                st.error("Add at least one player with a name before saving.")
            else:
                added = 0
                for _, row in valid_rows.iterrows():
                    session.add(OpponentPlayer(
                        team_id=selected_team_id,
                        player_name=str(row["Name"]).strip(),
                        jersey_number=str(row["Jersey #"]).strip() if pd.notna(row.get("Jersey #")) else None,
                        bats=row["Bats"] if pd.notna(row.get("Bats")) else None,
                        throws=row["Throws"] if pd.notna(row.get("Throws")) else None,
                        position=str(row["Position"]).strip() if pd.notna(row.get("Position")) else None,
                        notes=str(row["Notes"]).strip() if pd.notna(row.get("Notes")) else None,
                    ))
                    added += 1
                session.commit()
                st.success(f"Added {added} player(s) to {selected_team.team_name}.")
                st.rerun()

    st.divider()
    with st.expander("Delete a team"):
        if not teams:
            st.caption("No teams to delete.")
        else:
            delete_team_id = st.selectbox(
                "Which team?",
                options=list(teams_by_id.keys()),
                format_func=lambda tid: teams_by_id[tid].team_name,
                key="delete_team_choice",
            )
            st.warning("This permanently deletes the team and its entire roster. Games already logged against them keep their data (the team link just becomes empty) -- this can't be undone.")
            confirm_delete_team = st.checkbox("Yes, I want to permanently delete this team", key=f"confirm_delete_team_{delete_team_id}")
            if st.button("Delete team", key=f"delete_team_{delete_team_id}", disabled=not confirm_delete_team, type="primary"):
                team_to_delete = teams_by_id[delete_team_id]
                team_name = team_to_delete.team_name

                # Unlink (don't cascade-destroy) anything that points at
                # this team or its roster -- games and logged pitches
                # keep their actual data, they just lose the team/player
                # link. Same pattern as Player Assignments earlier.
                linked_games = session.query(Game).filter(Game.opponent_team_id == delete_team_id).all()
                for g in linked_games:
                    g.opponent_team_id = None

                roster_ids = [p.opponent_player_id for p in team_to_delete.roster]
                if roster_ids:
                    linked_pitches = session.query(GamePitch).filter(GamePitch.opponent_player_id.in_(roster_ids)).all()
                    for gp in linked_pitches:
                        gp.opponent_player_id = None

                session.delete(team_to_delete)
                session.commit()
                msg = f"Deleted {team_name}."
                if linked_games:
                    msg += f" Unlinked {len(linked_games)} game(s) that referenced it (their data is kept)."
                st.success(msg)
                st.rerun()

finally:
    session.close()

page_footer()