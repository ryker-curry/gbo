"""
GBO — Assessments (Milestone: Aug 7-10).

Data-driven by design: works for any assessment category as soon as its
test types are seeded (assessment_test_types), so adding the remaining
9 categories later needs no code changes here -- just seed data.

Currently only Anthropometrics and Body Composition have real test
types (from Ryker's Master Player Profile Data Dictionary). The other
9 categories show a "not defined yet" message until that protocol
detail is supplied.

Entry is manual (no device integration in the MVP). Assessments support
full history -- multiple dated entries per player per category, not
just a current snapshot.
"""

import streamlit as st
from ui_components import page_header, page_footer, empty_state
from datetime import date
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, AssessmentCategory, AssessmentTestType,
    Assessment, AssessmentResult, PitchType,
)

page_header("Assessments")

current_user_id = st.session_state.get("gbo_user_id")
can_view_all = st.session_state.get("gbo_can_view_all_players", False)
can_edit_assessments = st.session_state.get("gbo_can_edit_assessments", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

session = get_session()
try:
    # --- Visible players (same role-based filtering as Player Management) ---
    player_query = session.query(Player).options(joinedload(Player.team)).filter(Player.active.is_(True))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    players = player_query.order_by(Player.last_name, Player.first_name).all()

    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
        page_footer()
        st.stop()

    categories = session.query(AssessmentCategory).order_by(AssessmentCategory.display_order).all()

    players_by_id = {p.player_id: p for p in players}
    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
    )
    selected_player = players_by_id[selected_player_id]

    categories_by_id = {c.category_id: c for c in categories}
    selected_category_id = st.selectbox(
        "Category",
        options=list(categories_by_id.keys()),
        format_func=lambda cid: categories_by_id[cid].category_name,
    )
    selected_category = categories_by_id[selected_category_id]

    test_types = (
        session.query(AssessmentTestType)
        .filter(AssessmentTestType.category_id == selected_category_id)
        .order_by(AssessmentTestType.display_order)
        .all()
    )

    st.divider()

    # --- Summary stats (Max / Average / Min / Count per test) ---
    st.subheader(f"{selected_category.category_name} summary — {selected_player.first_name} {selected_player.last_name}")

    pitch_type_filter_id = None
    if selected_category.category_name == "Pitcher-Specific":
        used_pitch_types = (
            session.query(PitchType)
            .join(Assessment, Assessment.pitch_type_id == PitchType.pitch_type_id)
            .filter(Assessment.player_id == selected_player_id, Assessment.category_id == selected_category_id)
            .distinct()
            .all()
        )
        if used_pitch_types:
            pt_options = {"All pitch types": None}
            pt_options.update({pt.type_name: pt.pitch_type_id for pt in used_pitch_types})
            pt_choice = st.selectbox("Filter by pitch type", list(pt_options.keys()))
            pitch_type_filter_id = pt_options[pt_choice]

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
        .filter(Assessment.player_id == selected_player_id, Assessment.category_id == selected_category_id)
    )
    if pitch_type_filter_id is not None:
        summary_query = summary_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
    summary_query = summary_query.group_by(AssessmentTestType.test_type_id, AssessmentTestType.test_name, AssessmentTestType.unit, AssessmentTestType.display_order).order_by(AssessmentTestType.display_order)

    summary_rows = summary_query.all()

    if not summary_rows:
        st.info("No assessment history yet for this player and category.")
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

    # --- Full per-entry history (collapsed by default -- can be large after CSV imports) ---
    with st.expander("Show full history (every individual entry)"):
        history_query = (
            session.query(Assessment)
            .options(
                joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                joinedload(Assessment.pitch_type),
            )
            .filter(Assessment.player_id == selected_player_id, Assessment.category_id == selected_category_id)
        )
        if pitch_type_filter_id is not None:
            history_query = history_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
        past_assessments = history_query.order_by(Assessment.assessment_date.desc()).limit(500).all()

        if not past_assessments:
            st.info("No entries to show.")
        else:
            if len(past_assessments) == 500:
                st.caption("Showing the most recent 500 entries.")
            rows = []
            for a in past_assessments:
                row = {"Date": a.assessment_date.strftime("%Y-%m-%d (%a)")}
                if a.pitch_type:
                    row["Pitch Type"] = a.pitch_type.type_name
                row["Notes"] = a.notes or ""
                for r in a.results:
                    unit_label = f" ({r.test_type.unit})" if r.test_type.unit else ""
                    row[f"{r.test_type.test_name}{unit_label}"] = round(float(r.value), 2)
                rows.append(row)
            st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()

    # --- New assessment entry ---
    if not test_types:
        st.warning(
            f"No individual tests are defined yet for {selected_category.category_name}. "
            f"This category is waiting on the protocol details -- once those are added, "
            f"entry for this category will work automatically, same as Anthropometrics and Body Composition."
        )
    elif not can_edit_assessments:
        st.info("Your role has read-only access to assessments.")
    else:
        st.subheader(f"New {selected_category.category_name} assessment")

        pitch_types = []
        if selected_category.category_name == "Pitcher-Specific":
            pitch_types = session.query(PitchType).order_by(PitchType.display_order).all()

        with st.form("assessment_form"):
            assessment_date = st.date_input("Assessment date", value=date.today())
            pitch_type_choice = None
            if pitch_types:
                pitch_type_names = ["--"] + [pt.type_name for pt in pitch_types]
                pitch_type_choice = st.selectbox("Pitch Type", pitch_type_names)
            values = {}
            # Group fields by sub-category prefix (e.g. "Shoulder: Throwing Arm
            # External Rotation" -> group "Shoulder") for readability -- large
            # categories like Mobility & ROM (33 fields) and Arm Health (26
            # fields) are unusable as one flat list.
            groups = {}
            for t in test_types:
                if ": " in t.test_name:
                    group_name, field_label = t.test_name.split(": ", 1)
                else:
                    group_name, field_label = selected_category.category_name, t.test_name
                groups.setdefault(group_name, []).append((t, field_label))

            for group_name, fields in groups.items():
                if len(groups) > 1:
                    st.markdown(f"**{group_name}**")
                cols = st.columns(2)
                for i, (t, field_label) in enumerate(fields):
                    label = field_label + (f" ({t.unit})" if t.unit else "")
                    values[t.test_type_id] = cols[i % 2].number_input(label, value=0.0, step=0.1, format="%.2f", key=f"test_{t.test_type_id}")

            notes = st.text_area("Notes (optional)")
            submitted = st.form_submit_button("Save assessment", type="primary")

        if submitted:
            pitch_type_id = None
            if pitch_types and pitch_type_choice and pitch_type_choice != "--":
                pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_choice), None)

            new_assessment = Assessment(
                player_id=selected_player_id,
                category_id=selected_category_id,
                assessment_date=assessment_date,
                entered_by_user_id=current_user_id,
                pitch_type_id=pitch_type_id,
                notes=notes.strip() or None,
            )
            session.add(new_assessment)
            session.flush()  # get assessment_id before adding results

            entered_count = 0
            for test_type_id, value in values.items():
                if value:  # skip zero/blank entries -- treat 0.0 as "not entered"
                    session.add(AssessmentResult(
                        assessment_id=new_assessment.assessment_id,
                        test_type_id=test_type_id,
                        value=value,
                    ))
                    entered_count += 1

            if entered_count == 0:
                session.rollback()
                st.error("Enter at least one test value before saving.")
            else:
                session.commit()
                st.success(
                    f"Saved {selected_category.category_name} assessment for "
                    f"{selected_player.first_name} {selected_player.last_name} "
                    f"({entered_count} test value(s) recorded)."
                )
                st.rerun()

finally:
    session.close()

page_footer()