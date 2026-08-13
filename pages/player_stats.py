"""
GBO — My Assessments (Player role only).

The player's own assessment summary -- Max/Average/Min across all
history, for any category, including Rapsodo/Pitcher-Specific data.
Also shows a "Goals in progress" section: baseline vs. current for
any metric tied to an active IDP goal, reusing the same "current
value" logic as the IDP page rather than adding new tagging.
Read-only: entering assessments stays staff-only.
"""

import streamlit as st
from datetime import date, timedelta
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, AssessmentCategory, Assessment, AssessmentResult, AssessmentTestType, PitchType, IDPGoal, IDPStatus, BullpenPitch
from ui_components import page_header, page_footer, empty_state
from bucket_system import compute_bucket_system
from bucket_system_display import render_full_breakdown, render_score_rings, render_development_profile

page_header("My Assessments")

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

    # --- Overall/Strength/Power rings, right at the top of the page. ---
    top_bucket_data = compute_bucket_system(session, my_player.player_id)
    if render_score_rings(top_bucket_data, key_prefix="myassess_top"):
        render_development_profile(top_bucket_data, key_prefix="myassess_top")
        st.divider()

    # --- Goals in progress: baseline vs. current for any metric tied to
    # an active IDP goal, same computation as the IDP page. ---
    open_goals = (
        session.query(IDPGoal)
        .join(IDPStatus)
        .options(joinedload(IDPGoal.category), joinedload(IDPGoal.target_test_type))
        .filter(IDPGoal.player_id == my_player.player_id, IDPGoal.target_test_type_id.isnot(None), IDPStatus.status_name != "Completed")
        .all()
    )
    if open_goals:
        st.subheader("Goals in progress")
        goal_rows = []
        for g in open_goals:
            unit = f" {g.target_test_type.unit}" if g.target_test_type.unit else ""
            if g.category.category_name == "Pitcher-Specific":
                cutoff = date.today() - timedelta(days=30)
                recent_results = (
                    session.query(AssessmentResult)
                    .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
                    .filter(
                        Assessment.player_id == g.player_id,
                        Assessment.category_id == g.category_id,
                        Assessment.assessment_date >= cutoff,
                        AssessmentResult.test_type_id == g.target_test_type_id,
                    )
                    .all()
                )
                current_value = sum(float(r.value) for r in recent_results) / len(recent_results) if recent_results else None
            else:
                latest_pair = (
                    session.query(AssessmentResult, Assessment.assessment_date)
                    .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
                    .filter(Assessment.player_id == g.player_id, AssessmentResult.test_type_id == g.target_test_type_id)
                    .order_by(Assessment.assessment_date.desc())
                    .first()
                )
                current_value = float(latest_pair[0].value) if latest_pair else None

            goal_rows.append({
                "Category": g.category.category_name,
                "Metric": g.target_test_type.test_name,
                "Baseline": f"{float(g.baseline_value):.2f}{unit}" if g.baseline_value is not None else "—",
                "Current": f"{current_value:.2f}{unit}" if current_value is not None else "—",
                "Target": f"{float(g.target_value):.2f}{unit}" if g.target_value is not None else "—",
                "Target date": g.target_date.strftime("%Y-%m-%d (%a)") if g.target_date else "—",
            })
        st.dataframe(goal_rows, use_container_width=True, hide_index=True)
        st.caption("Full goal details (action steps, progress notes) are on My Development.")
        st.divider()

    # --- Bucket System: full breakdown by metric, horizontal bar per
    # test showing percentile (bar length) and raw value (label). The
    # big overall Total/Body Comp/Power/Strength numbers are on the
    # Dashboard -- this is the detail underneath them. ---
    st.subheader("Physical Testing Breakdown")
    has_any_data = any(top_bucket_data[k] is not None for k in ("total_score", "body_comp_score", "power_score", "strength_score"))
    if not has_any_data:
        empty_state("No physical testing data yet.")
    else:
        render_full_breakdown(top_bucket_data, key_prefix="myassess")

    st.divider()

    categories = session.query(AssessmentCategory).order_by(AssessmentCategory.display_order).all()
    categories_by_id = {c.category_id: c for c in categories}
    selected_category_id = st.selectbox(
        "Category",
        options=list(categories_by_id.keys()),
        format_func=lambda cid: categories_by_id[cid].category_name,
    )
    selected_category = categories_by_id[selected_category_id]

    pitch_type_filter_id = None
    if selected_category.category_name == "Pitcher-Specific":
        used_pitch_types = (
            session.query(PitchType)
            .join(Assessment, Assessment.pitch_type_id == PitchType.pitch_type_id)
            .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == selected_category_id)
            .distinct()
            .all()
        )
        if used_pitch_types:
            pt_options = {"All pitch types": None}
            pt_options.update({pt.type_name: pt.pitch_type_id for pt in used_pitch_types})
            pt_choice = st.selectbox("Filter by pitch type", list(pt_options.keys()))
            pitch_type_filter_id = pt_options[pt_choice]

    with st.expander("Show full history (every individual entry)"):
        history_query = (
            session.query(Assessment)
            .options(
                joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                joinedload(Assessment.pitch_type),
            )
            .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == selected_category_id)
            # Exclude entries that were auto-created by a Rapsodo import
            # tied to a Bullpen Tracking session -- that data already has
            # a proper home there, so it doesn't need to also clutter
            # this general browsing view (same as the coach-facing page).
            .filter(~Assessment.assessment_id.in_(
                session.query(BullpenPitch.linked_assessment_id).filter(BullpenPitch.linked_assessment_id.isnot(None))
            ))
        )
        if pitch_type_filter_id is not None:
            history_query = history_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
        past_assessments = history_query.order_by(Assessment.assessment_date.desc()).limit(500).all()

        if not past_assessments:
            empty_state("No entries to show.")
        else:
            if len(past_assessments) == 500:
                st.caption("Showing the most recent 500 entries.")
            rows = []
            for a in past_assessments:
                row = {"Date": a.assessment_date.strftime("%Y-%m-%d (%a)")}
                if a.pitch_type:
                    row["Pitch Type"] = a.pitch_type.type_name
                for r in a.results:
                    unit_label = f" ({r.test_type.unit})" if r.test_type.unit else ""
                    row[f"{r.test_type.test_name}{unit_label}"] = round(float(r.value), 2)
                rows.append(row)
            st.dataframe(rows, use_container_width=True, hide_index=True)

finally:
    session.close()

page_footer()