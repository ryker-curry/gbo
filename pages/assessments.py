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
import plotly.graph_objects as go
from ui_components import page_header, page_footer, empty_state
from datetime import date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, AssessmentCategory, AssessmentTestType,
    Assessment, AssessmentResult, PitchType, IDPGoal, IDPStatus,
)
from bucket_system import compute_bucket_system, BUCKET_RELEVANT_CATEGORIES, get_bucket_test_names_for_category

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
    # --- Visible players (same role-based filtering as Player Management)
    # --- NOT filtered to active-only, unlike every other roster-facing
    # picker in GBO (Game Tracking lineups, Analytics, Bucket System
    # comparisons) -- Ryker wants to keep entering assessment data for
    # last year's players even after marking them inactive so they don't
    # show up on the current roster anywhere else. ---
    player_query = session.query(Player).options(joinedload(Player.team))
    if not can_view_all:
        assigned_ids = [
            a.player_id for a in
            session.query(StaffPlayerAssignment)
            .filter(StaffPlayerAssignment.staff_user_id == current_user_id)
            .all()
        ]
        player_query = player_query.filter(Player.player_id.in_(assigned_ids))
    players = player_query.order_by(Player.active.desc(), Player.last_name, Player.first_name).all()

    if not players:
        empty_state("No players to show yet." if can_view_all else "No players are currently assigned to you.")
        page_footer()
        st.stop()

    categories = session.query(AssessmentCategory).order_by(AssessmentCategory.display_order).all()

    players_by_id = {p.player_id: p for p in players}
    selected_player_id = st.selectbox(
        "Player",
        options=list(players_by_id.keys()),
        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" + ("" if players_by_id[pid].active else " (Inactive / prior roster)"),
    )
    selected_player = players_by_id[selected_player_id]

    # --- Goals in progress: baseline vs. current for any metric tied to
    # an active IDP goal, reusing the same "current value" computation
    # as the IDP page (rolling 30-day average for Pitcher-Specific,
    # most recent single value for other categories) -- no new tagging
    # needed, just surfacing data that's already tracked. ---
    open_goals = (
        session.query(IDPGoal)
        .join(IDPStatus)
        .options(joinedload(IDPGoal.category), joinedload(IDPGoal.target_test_type))
        .filter(IDPGoal.player_id == selected_player_id, IDPGoal.target_test_type_id.isnot(None), IDPStatus.status_name != "Completed")
        .all()
    )
    if open_goals:
        st.subheader(f"Goals in progress — {selected_player.first_name} {selected_player.last_name}")
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
        st.caption("Full goal details (action steps, progress notes) are on the IDP page.")
        st.divider()

    # --- Bucket System: composite physical testing score (body comp,
    # power, strength percentiles vs the team, rolled up into one
    # Total). Speed is shown for reference but excluded from the Total,
    # per Ryker's professor's methodology -- see bucket_system.py for
    # the full formula/rollup, verified directly against his real
    # spreadsheet data before building this. ---
    st.subheader("Bucket System")
    bucket_data = compute_bucket_system(session, selected_player_id)
    if bucket_data["total_score"] is None and bucket_data["body_comp_score"] is None and bucket_data["power_score"] is None and bucket_data["strength_score"] is None:
        empty_state("No bucket-system data yet for this player -- needs at least one result for a Body Comp, Power, or Strength test.")
    else:
        gauge_cols = st.columns(4)
        gauge_specs = [
            ("Total", bucket_data["total_score"], gauge_cols[0]),
            ("Body Comp", bucket_data["body_comp_score"], gauge_cols[1]),
            ("Power", bucket_data["power_score"], gauge_cols[2]),
            ("Strength", bucket_data["strength_score"], gauge_cols[3]),
        ]
        for label, score, col in gauge_specs:
            with col:
                if score is None:
                    st.markdown(f"**{label}**")
                    st.caption("No data yet")
                    continue
                fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=score,
                    number={"font": {"color": "#FFFDE5"}},
                    title={"text": label, "font": {"color": "#FFFDE5", "size": 16}},
                    gauge={
                        "axis": {"range": [0, 100], "tickcolor": "#FFFDE5"},
                        "bar": {"color": "#BF1E2D"},
                        "bgcolor": "#1E1E1E",
                        "borderwidth": 0,
                    },
                ))
                fig.update_layout(height=220, margin=dict(t=40, b=10, l=20, r=20), paper_bgcolor="#1E1E1E", font=dict(color="#FFFDE5"))
                st.plotly_chart(fig, use_container_width=True)
        if bucket_data["speed_score"] is not None:
            st.caption(f"Speed (reference only, not in Total): {bucket_data['speed_score']}")

        with st.expander("Bucket System detail"):
            st.markdown("**Body Comp**")
            if bucket_data["body_comp_metrics"]:
                st.dataframe(
                    [{"Metric": name, "Value": f"{d['raw']:.2f}{d['unit'] or ''}", "Percentile": d["percentile"]} for name, d in bucket_data["body_comp_metrics"].items()],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No data yet.")

            st.markdown("**Power**")
            for sub_name, sub_score in bucket_data["power_subgroup_scores"].items():
                metrics = bucket_data["power_subgroup_metrics"][sub_name]
                if not metrics:
                    continue
                st.markdown(f"*{sub_name}* — {sub_score if sub_score is not None else '—'}")
                st.dataframe(
                    [{"Metric": name, "Value": f"{d['raw']:.2f}{d['unit'] or ''}", "Percentile": d["percentile"]} for name, d in metrics.items()],
                    use_container_width=True, hide_index=True,
                )

            st.markdown("**Strength**")
            for sub_name, sub_score in bucket_data["strength_subgroup_scores"].items():
                metrics = bucket_data["strength_subgroup_metrics"][sub_name]
                if not metrics:
                    continue
                st.markdown(f"*{sub_name}* — {sub_score if sub_score is not None else '—'}")
                st.dataframe(
                    [{"Metric": name, "Value": f"{d['raw']:.2f}{d['unit'] or ''}", "Percentile": d["percentile"]} for name, d in metrics.items()],
                    use_container_width=True, hide_index=True,
                )

            if bucket_data["speed_metrics"]:
                st.markdown("**Speed** (reference only)")
                st.dataframe(
                    [{"Metric": name, "Value": f"{d['raw']:.2f}{d['unit'] or ''}", "Percentile": d["percentile"]} for name, d in bucket_data["speed_metrics"].items()],
                    use_container_width=True, hide_index=True,
                )
    st.divider()

    categories_by_id = {c.category_id: c for c in categories}
    selected_category_id = st.selectbox(
        "Category",
        options=list(categories_by_id.keys()),
        format_func=lambda cid: categories_by_id[cid].category_name,
    )
    selected_category = categories_by_id[selected_category_id]

    pitch_types = []
    if selected_category.category_name == "Pitcher-Specific":
        pitch_types = session.query(PitchType).order_by(PitchType.display_order).all()

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
        empty_state("No assessment history yet for this player and category.")
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
            empty_state("No entries to show.")
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

    # --- Edit or delete a past entry -- fixing a typo, or removing a bad
    # entry entirely. Shows whatever fields actually exist on that
    # specific assessment record, regardless of the current bucket-
    # system entry scoping above -- an older entry might have values
    # for fields no longer shown on the New assessment form, and this
    # should still let a coach fix those. ---
    if can_edit_assessments:
        with st.expander("Edit or delete a past entry"):
            edit_query = (
                session.query(Assessment)
                .options(
                    joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                    joinedload(Assessment.pitch_type),
                )
                .filter(Assessment.player_id == selected_player_id, Assessment.category_id == selected_category_id)
            )
            if pitch_type_filter_id is not None:
                edit_query = edit_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
            editable_assessments = edit_query.order_by(Assessment.assessment_date.desc()).limit(500).all()

            if not editable_assessments:
                st.caption("No entries to edit yet.")
            else:
                assessments_by_id = {a.assessment_id: a for a in editable_assessments}

                def _entry_label(aid):
                    a = assessments_by_id[aid]
                    label = a.assessment_date.strftime("%Y-%m-%d (%a)")
                    if a.pitch_type:
                        label += f" — {a.pitch_type.type_name}"
                    if a.notes:
                        label += f" — {a.notes[:40]}"
                    return label

                edit_assessment_id = st.selectbox(
                    "Which entry?",
                    options=list(assessments_by_id.keys()),
                    format_func=_entry_label,
                    key=f"edit_entry_choice_{selected_category_id}",
                )
                editing_assessment = assessments_by_id[edit_assessment_id]

                with st.form(f"edit_assessment_form_{edit_assessment_id}"):
                    edit_date = st.date_input("Assessment date", value=editing_assessment.assessment_date)
                    edit_pitch_type_choice = None
                    if pitch_types:
                        pitch_type_names = ["--"] + [pt.type_name for pt in pitch_types]
                        current_pt_name = editing_assessment.pitch_type.type_name if editing_assessment.pitch_type else "--"
                        edit_pitch_type_choice = st.selectbox("Pitch Type", pitch_type_names, index=pitch_type_names.index(current_pt_name) if current_pt_name in pitch_type_names else 0)

                    edit_groups = {}
                    for r in editing_assessment.results:
                        t = r.test_type
                        if ": " in t.test_name:
                            group_name, field_label = t.test_name.split(": ", 1)
                        else:
                            group_name, field_label = selected_category.category_name, t.test_name
                        edit_groups.setdefault(group_name, []).append((t, field_label, r))

                    edit_values = {}
                    for group_name, fields in edit_groups.items():
                        if len(edit_groups) > 1:
                            st.markdown(f"**{group_name}**")
                        cols = st.columns(2)
                        for i, (t, field_label, r) in enumerate(fields):
                            label = field_label + (f" ({t.unit})" if t.unit else "")
                            edit_values[r.result_id] = cols[i % 2].number_input(label, value=float(r.value), step=0.1, format="%.2f", key=f"edit_result_{r.result_id}")

                    edit_notes = st.text_area("Notes (optional)", value=editing_assessment.notes or "")
                    edit_submitted = st.form_submit_button("Save changes", type="primary")

                if edit_submitted:
                    editing_assessment.assessment_date = edit_date
                    editing_assessment.notes = edit_notes.strip() or None
                    if pitch_types:
                        editing_assessment.pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == edit_pitch_type_choice), None) if edit_pitch_type_choice != "--" else None
                    for result_id, new_value in edit_values.items():
                        result = next(r for r in editing_assessment.results if r.result_id == result_id)
                        result.value = new_value
                    session.commit()
                    st.success("Saved changes.")
                    st.rerun()

                st.divider()
                st.warning("Deleting an entry removes it and all its test values permanently -- this can't be undone.")
                confirm_delete_entry = st.checkbox("Yes, I want to permanently delete this entry", key=f"confirm_delete_entry_{edit_assessment_id}")
                if st.button("Delete this entry", key=f"delete_entry_{edit_assessment_id}", disabled=not confirm_delete_entry, type="primary"):
                    session.delete(editing_assessment)
                    session.commit()
                    st.success("Deleted.")
                    st.rerun()

    st.divider()

    # --- New assessment entry ---
    # For bucket-relevant categories, entry is scoped to ONLY the fields
    # that are actually in the bucket spreadsheet (Ryker's explicit
    # rule) -- e.g. Body Composition entry shows just Body Weight, Body
    # Fat Mass, Skeletal Muscle Mass, Percent Body Fat, not the other 15
    # InBody770 fields GBO also tracks. Doesn't affect the summary/
    # history views above, which still show whatever data exists.
    entry_test_types = test_types
    if selected_category.category_name in BUCKET_RELEVANT_CATEGORIES:
        allowed_names = get_bucket_test_names_for_category(selected_category.category_name)
        entry_test_types = [t for t in test_types if t.test_name in allowed_names]

    if not entry_test_types:
        st.warning(
            f"No individual tests are defined yet for {selected_category.category_name}. "
            f"This category is waiting on the protocol details -- once those are added, "
            f"entry for this category will work automatically, same as Anthropometrics and Body Composition."
        )
    elif not can_edit_assessments:
        st.info("Your role has read-only access to assessments.")
    else:
        st.subheader(f"New {selected_category.category_name} assessment")

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
            for t in entry_test_types:
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