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
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, AssessmentCategory, Assessment, AssessmentResult, AssessmentTestType, PitchType, IDPGoal, IDPStatus
from ui_components import page_header, page_footer, empty_state

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

    st.subheader(f"{selected_category.category_name} summary")

    summary_query = (
        session.query(
            AssessmentTestType.test_name,
            AssessmentTestType.unit,
            func.count(AssessmentResult.value).label("count"),
            func.max(AssessmentResult.value).label("max"),
            func.avg(AssessmentResult.value).label("avg"),
            func.min(AssessmentResult.value).label("min"),
        )
        .join(Assessment, Assessment.assessment_id == AssessmentResult.assessment_id)
        .join(AssessmentTestType, AssessmentTestType.test_type_id == AssessmentResult.test_type_id)
        .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == selected_category_id)
    )
    if pitch_type_filter_id is not None:
        summary_query = summary_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
    summary_query = summary_query.group_by(
        AssessmentTestType.test_type_id, AssessmentTestType.test_name, AssessmentTestType.unit, AssessmentTestType.display_order
    ).order_by(AssessmentTestType.display_order)

    summary_rows = summary_query.all()

    if not summary_rows:
        empty_state("No assessment history yet for this category.")
    else:
        st.dataframe(
            [
                {
                    "Test": f"{r.test_name}" + (f" ({r.unit})" if r.unit else ""),
                    "Count": r.count,
                    "Average": round(float(r.avg), 2),
                    "Max": round(float(r.max), 2),
                    "Min": round(float(r.min), 2),
                }
                for r in summary_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("Show full history (every individual entry)"):
        history_query = (
            session.query(Assessment)
            .options(
                joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                joinedload(Assessment.pitch_type),
            )
            .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == selected_category_id)
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