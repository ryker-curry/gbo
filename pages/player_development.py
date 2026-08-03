"""
GBO — My Development (Player role only).

Split out of the Dashboard -- shows the player's own IDP goals,
read-only (creating/editing goals stays staff-only).
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, IDPGoal, IDPActionStep
from ui_components import page_header, page_footer, empty_state

page_header("My Development")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name != "Player":
    st.error("This page is only available to Player accounts.")
    page_footer()
    st.stop()

session = get_session()
try:
    me = session.query(User).filter(User.user_id == current_user_id).first()
    if me is None or me.player_id is None:
        st.info("Your player profile isn't linked yet. Check with an administrator.")
        page_footer()
        st.stop()

    my_player = session.query(Player).filter(Player.player_id == me.player_id).first()

    st.markdown(f"**{my_player.first_name} {my_player.last_name}'s Development Plan**")

    my_goals = (
        session.query(IDPGoal)
        .options(
            joinedload(IDPGoal.category),
            joinedload(IDPGoal.status),
            joinedload(IDPGoal.target_test_type),
            joinedload(IDPGoal.action_steps).joinedload(IDPActionStep.status),
            joinedload(IDPGoal.progress_notes),
        )
        .filter(IDPGoal.player_id == my_player.player_id)
        .order_by(IDPGoal.created_at.desc())
        .all()
    )
    if not my_goals:
        empty_state("No development goals set yet -- check with your coach.")
    else:
        for goal in my_goals:
            status_label = goal.status.status_name if goal.status else "—"
            title = f"{goal.category.category_name if goal.category else '—'} — {goal.description[:60]}{'...' if len(goal.description) > 60 else ''} · {status_label}"
            with st.expander(title):
                st.write(goal.description)
                if goal.target_test_type:
                    unit = f" {goal.target_test_type.unit}" if goal.target_test_type.unit else ""
                    target_line = f"**Target: {goal.target_test_type.test_name}** — "
                    if goal.baseline_value is not None:
                        target_line += f"{float(goal.baseline_value):.2f}{unit} → "
                    if goal.target_value is not None:
                        target_line += f"{float(goal.target_value):.2f}{unit}"
                    if goal.target_date:
                        target_line += f" by {goal.target_date.strftime('%Y-%m-%d (%a)')}"
                    st.markdown(target_line)

                if goal.action_steps:
                    st.markdown("**Action steps**")
                    st.dataframe(
                        [
                            {
                                "Description": a.description,
                                "Status": a.status.status_name if a.status else "—",
                                "Due date": a.due_date.strftime("%Y-%m-%d (%a)") if a.due_date else "—",
                            }
                            for a in goal.action_steps
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

                if goal.progress_notes:
                    st.markdown("**Progress notes**")
                    for note in sorted(goal.progress_notes, key=lambda n: n.created_at, reverse=True):
                        st.caption(note.created_at.strftime("%Y-%m-%d (%a)"))
                        st.write(note.note_text)

finally:
    session.close()

page_footer()