"""
GBO -- Assessments module.

Direct port of pages/assessments.py -- data-driven by design: works for
any assessment category as soon as its test types are seeded, so the
remaining categories beyond Anthropometrics/Body Composition need no
code changes here, just seed data. Entry is manual, and every category
supports full history (multiple dated entries per player), not just a
current snapshot.

Layout, top to bottom, same order as the original:
  1. Player picker (not active-only -- Ryker wants to keep entering
     data for prior-roster players)
  2. Physical testing score rings/breakdown for that player (reuses
     bucket_display.py, same as Dashboard/My Assessments)
  3. Goals in progress (baseline vs. current for any metric tied to an
     open IDP goal)
  4. Category picker, optional pitch-type filter (Pitcher-Specific only)
  5. Full history (collapsed, excludes Rapsodo-import-linked entries --
     those live on Bullpen Tracking instead)
  6. Edit or delete a past entry (can_edit_assessments only)
  7. New assessment entry, one ui.input_numeric per test type, grouped
     by "Group: Field" test-name prefixes (can_edit_assessments only)

Same ordering-hazard pattern as player_stats.py's category -> pitch-type
chain: player/category/pitch-type-filter/edit-entry selects each get
their own output_ui, and everything downstream reads them via
`req("<id>" in input)` (which -- per Shiny's Inputs.__contains__ --
waits for the client to have actually sent a value, not just for the
key to exist) before touching the value.

New pattern versus players.py (first data-driven dynamic form in this
migration): the New/Edit assessment forms don't have a fixed field
list -- one ui.input_numeric per AssessmentTestType row, keyed
"test_{test_type_id}"/"edit_result_{result_id}". Reading them back in
the save handlers uses input[key]() (Shiny's Inputs supports bracket
access for dynamically-named inputs, same as input.name() for a static
one) instead of a fixed list of input.<name>() calls.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, AssessmentCategory, AssessmentTestType,
    Assessment, AssessmentResult, PitchType, IDPGoal, IDPStatus, BullpenPitch,
)
from bucket_system import BUCKET_RELEVANT_CATEGORIES, get_bucket_test_names_for_category, compute_bucket_system

import ui_helpers
import bucket_display


@module.ui
def assessments_ui():
    return ui.div(
        ui_helpers.page_header("Assessments"),
        ui.output_ui("player_picker"),
        ui.output_ui("top_section"),
        ui.output_ui("category_picker"),
        ui.output_ui("pitch_type_filter_section"),
        ui.output_ui("history_section"),
        ui.output_ui("edit_section"),
        ui.output_ui("new_entry_section"),
        ui_helpers.page_footer(),
    )


@module.server
def assessments_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _visible_players(db):
        """NOT active-only, unlike Player Management's browsing table --
        Ryker wants to keep entering assessment data for prior-roster
        players after marking them inactive."""
        query = db.query(Player).options(joinedload(Player.team))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment)
                .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id())
                .all()
            ]
            query = query.filter(Player.player_id.in_(assigned_ids))
        return query.order_by(Player.active.desc(), Player.last_name, Player.first_name).all()

    def _group_test_fields(items, category_name):
        """items: list of (test_type, field_label-source-object) pairs
        sharing the same ": " split-by-prefix grouping logic the
        original uses for both the entry form and the edit form."""
        groups = {}
        for t in items:
            if ": " in t.test_name:
                group_name, field_label = t.test_name.split(": ", 1)
            else:
                group_name, field_label = category_name, t.test_name
            groups.setdefault(group_name, []).append((t, field_label))
        return groups

    # -------------------------------------------------------------------
    # 1. Player picker
    # -------------------------------------------------------------------

    @render.ui
    def player_picker():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            players = _visible_players(db)
            if not players:
                return ui_helpers.empty_state(
                    "No players to show yet." if app_state.can_view_all_players() else "No players are currently assigned to you."
                )
            choices = {
                str(p.player_id): f"{p.first_name} {p.last_name}" + ("" if p.active else " (Inactive / prior roster)")
                for p in players
            }
            return ui.input_select("player_select", "Player", choices=choices)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # 2 & 3. Score rings/breakdown + goals in progress, for the selected player
    # -------------------------------------------------------------------

    @render.ui
    def top_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_player_id = int(input.player_select())
        mode = app_state.dark_mode() or "dark"

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            if selected_player is None:
                return None

            sections = []
            bucket_data = compute_bucket_system(db, selected_player_id)
            rings = bucket_display.build_score_rings(bucket_data, "assess", mode=mode)
            if rings is not None:
                sections.append(rings)
                profile = bucket_display.build_development_profile(bucket_data, "assess", mode=mode)
                if profile is not None:
                    sections.append(profile)
                sections.append(ui.h5("Physical Testing Breakdown", class_="gbo-section-title"))
                sections.append(bucket_display.build_full_breakdown(bucket_data, "assess_detail", mode=mode))
                sections.append(ui.hr())

            open_goals = (
                db.query(IDPGoal)
                .join(IDPStatus)
                .options(joinedload(IDPGoal.category), joinedload(IDPGoal.target_test_type))
                .filter(IDPGoal.player_id == selected_player_id, IDPGoal.target_test_type_id.isnot(None), IDPStatus.status_name != "Completed")
                .all()
            )
            if open_goals:
                sections.append(ui.h5(f"Goals in progress — {selected_player.first_name} {selected_player.last_name}", class_="gbo-section-title"))
                goal_rows = []
                for g in open_goals:
                    unit = f" {g.target_test_type.unit}" if g.target_test_type.unit else ""
                    if g.category.category_name == "Pitcher-Specific":
                        cutoff = date.today() - timedelta(days=30)
                        recent_results = (
                            db.query(AssessmentResult)
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
                            db.query(AssessmentResult, Assessment.assessment_date)
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
                sections.append(ui_helpers.render_dict_table(goal_rows))
                sections.append(ui.p("Full goal details (action steps, progress notes) are on the IDP page.", class_="text-muted small"))
                sections.append(ui.hr())

            return ui.div(*sections)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # 4. Category picker + pitch-type filter
    # -------------------------------------------------------------------

    @render.ui
    def category_picker():
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            categories = (
                db.query(AssessmentCategory)
                .filter(AssessmentCategory.category_name != "Anthropometrics")
                .order_by(AssessmentCategory.display_order)
                .all()
            )
            choices = {str(c.category_id): c.category_name for c in categories}
            return ui.div(ui.hr(), ui.input_select("category_select", "Category", choices=choices))
        finally:
            db.close()

    @render.ui
    def pitch_type_filter_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        req("category_select" in input)
        selected_player_id = int(input.player_select())
        selected_category_id = int(input.category_select())

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == selected_category_id).first()
            if category is None or category.category_name != "Pitcher-Specific":
                return None
            used_pitch_types = (
                db.query(PitchType)
                .join(Assessment, Assessment.pitch_type_id == PitchType.pitch_type_id)
                .filter(Assessment.player_id == selected_player_id, Assessment.category_id == selected_category_id)
                .distinct()
                .all()
            )
            if not used_pitch_types:
                return None
            choices = {"": "All pitch types"}
            choices.update({str(pt.pitch_type_id): pt.type_name for pt in used_pitch_types})
            return ui.input_select("pitch_type_filter", "Filter by pitch type", choices=choices)
        finally:
            db.close()

    def _pitch_type_filter_id():
        """Safe to call from any render.ui downstream of both selects --
        the filter select doesn't always exist (only for Pitcher-Specific
        with used pitch types), so this treats "not set yet" the same as
        "All pitch types" rather than blocking."""
        if "pitch_type_filter" in input:
            raw = input.pitch_type_filter()
            return int(raw) if raw else None
        return None

    # -------------------------------------------------------------------
    # 5. Full history
    # -------------------------------------------------------------------

    def _history_query(db, player_id, category_id):
        q = (
            db.query(Assessment)
            .options(
                joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                joinedload(Assessment.pitch_type),
            )
            .filter(Assessment.player_id == player_id, Assessment.category_id == category_id)
            # Same Rapsodo-import exclusion as My Assessments -- that
            # data already has a home on Bullpen Tracking.
            .filter(~Assessment.assessment_id.in_(
                db.query(BullpenPitch.linked_assessment_id).filter(BullpenPitch.linked_assessment_id.isnot(None))
            ))
        )
        pt_filter_id = _pitch_type_filter_id()
        if pt_filter_id is not None:
            q = q.filter(Assessment.pitch_type_id == pt_filter_id)
        return q.order_by(Assessment.assessment_date.desc()).limit(500)

    @render.ui
    def history_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        req("category_select" in input)
        selected_player_id = int(input.player_select())
        selected_category_id = int(input.category_select())

        db = get_session()
        try:
            past_assessments = _history_query(db, selected_player_id, selected_category_id).all()
            if not past_assessments:
                body = ui_helpers.empty_state("No entries to show.")
            else:
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
                content = []
                if len(past_assessments) == 500:
                    content.append(ui.p("Showing the most recent 500 entries.", class_="text-muted small"))
                content.append(ui_helpers.render_dict_table(rows))
                body = ui.div(*content)

            return ui.accordion(
                ui.accordion_panel("Show full history (every individual entry)", body),
                open=False, id=None,
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # 6. Edit or delete a past entry
    # -------------------------------------------------------------------

    @render.ui
    def edit_section():
        _refresh_tick()
        if not app_state.is_authenticated() or not app_state.can_edit_assessments():
            return None
        req("player_select" in input)
        req("category_select" in input)
        selected_player_id = int(input.player_select())
        selected_category_id = int(input.category_select())

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == selected_category_id).first()
            editable_assessments = _history_query(db, selected_player_id, selected_category_id).all()

            if not editable_assessments:
                body = ui.p("No entries to edit yet.", class_="text-muted small")
            else:
                choices = {}
                for a in editable_assessments:
                    label = a.assessment_date.strftime("%Y-%m-%d (%a)")
                    if a.pitch_type:
                        label += f" — {a.pitch_type.type_name}"
                    if a.notes:
                        label += f" — {a.notes[:40]}"
                    choices[str(a.assessment_id)] = label
                body = ui.div(
                    ui.input_select("edit_entry_select", "Which entry?", choices=choices),
                    ui.output_ui("edit_entry_form"),
                )
            return ui.accordion(ui.accordion_panel("Edit or delete a past entry", body), open=False, id=None)
        finally:
            db.close()

    @render.ui
    def edit_entry_form():
        if not app_state.is_authenticated() or not app_state.can_edit_assessments():
            return None
        req("edit_entry_select" in input)
        edit_assessment_id = int(input.edit_entry_select())

        db = get_session()
        try:
            editing_assessment = (
                db.query(Assessment)
                .options(joinedload(Assessment.results).joinedload(AssessmentResult.test_type), joinedload(Assessment.pitch_type))
                .filter(Assessment.assessment_id == edit_assessment_id)
                .first()
            )
            if editing_assessment is None:
                return None
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == editing_assessment.category_id).first()

            pitch_type_block = []
            if category and category.category_name == "Pitcher-Specific":
                pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()
                pitch_type_names = ["--"] + [pt.type_name for pt in pitch_types]
                current_pt_name = editing_assessment.pitch_type.type_name if editing_assessment.pitch_type else "--"
                pitch_type_block = [ui.input_select("edit_pitch_type_choice", "Pitch Type", choices=pitch_type_names, selected=current_pt_name)]

            groups = _group_test_fields([r.test_type for r in editing_assessment.results], category.category_name if category else "")
            result_by_test_type_id = {r.test_type_id: r for r in editing_assessment.results}

            field_blocks = []
            for group_name, fields in groups.items():
                if len(groups) > 1:
                    field_blocks.append(ui.markdown(f"**{group_name}**"))
                inputs = []
                for t, field_label in fields:
                    r = result_by_test_type_id[t.test_type_id]
                    label = field_label + (f" ({t.unit})" if t.unit else "")
                    inputs.append(ui.input_numeric(f"edit_result_{r.result_id}", label, value=float(r.value), step=0.1))
                field_blocks.append(ui.layout_columns(*inputs))

            return ui.div(
                ui.input_date("edit_date", "Assessment date", value=editing_assessment.assessment_date),
                *pitch_type_block,
                *field_blocks,
                ui.input_text_area("edit_notes", "Notes (optional)", value=editing_assessment.notes or ""),
                ui.input_action_button("save_edit_btn", "Save changes", class_="btn-primary mt-2"),
                ui.hr(),
                ui.p("Deleting an entry removes it and all its test values permanently -- this can't be undone.", class_="text-warning small"),
                ui.input_checkbox("confirm_delete_entry", "Yes, I want to permanently delete this entry", value=False),
                ui.input_action_button("delete_entry_btn", "Delete this entry", class_="btn-danger mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_edit_btn)
    def _save_edit():
        edit_assessment_id = int(input.edit_entry_select())
        db = get_session()
        try:
            editing_assessment = (
                db.query(Assessment)
                .options(joinedload(Assessment.results))
                .filter(Assessment.assessment_id == edit_assessment_id)
                .first()
            )
            if editing_assessment is None:
                return

            editing_assessment.assessment_date = input.edit_date()
            editing_assessment.notes = (input.edit_notes() or "").strip() or None
            if "edit_pitch_type_choice" in input:
                choice = input.edit_pitch_type_choice()
                if choice and choice != "--":
                    pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()
                    editing_assessment.pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == choice), None)
                else:
                    editing_assessment.pitch_type_id = None

            for r in editing_assessment.results:
                key = f"edit_result_{r.result_id}"
                if key in input:
                    r.value = input[key]()

            db.commit()
            ui.notification_show("Saved changes.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_entry_btn)
    def _delete_entry():
        if not (input.confirm_delete_entry() if "confirm_delete_entry" in input else False):
            return
        edit_assessment_id = int(input.edit_entry_select())
        db = get_session()
        try:
            editing_assessment = db.query(Assessment).filter(Assessment.assessment_id == edit_assessment_id).first()
            if editing_assessment is None:
                return
            db.delete(editing_assessment)
            db.commit()
            ui.notification_show("Deleted.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # 7. New assessment entry
    # -------------------------------------------------------------------

    @render.ui
    def new_entry_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("category_select" in input)
        selected_category_id = int(input.category_select())

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == selected_category_id).first()
            if category is None:
                return None

            pitch_types = []
            if category.category_name == "Pitcher-Specific":
                pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()

            test_types = (
                db.query(AssessmentTestType)
                .filter(AssessmentTestType.category_id == selected_category_id)
                .order_by(AssessmentTestType.display_order)
                .all()
            )
            entry_test_types = test_types
            if category.category_name in BUCKET_RELEVANT_CATEGORIES:
                allowed_names = get_bucket_test_names_for_category(category.category_name)
                entry_test_types = [t for t in test_types if t.test_name in allowed_names]

            if not entry_test_types:
                return ui.p(
                    f"No individual tests are defined yet for {category.category_name}. "
                    f"This category is waiting on the protocol details -- once those are added, "
                    f"entry for this category will work automatically, same as Anthropometrics and Body Composition.",
                    class_="text-warning",
                )
            if not app_state.can_edit_assessments():
                return ui.p("Your role has read-only access to assessments.", class_="text-muted")

            pitch_type_block = []
            if pitch_types:
                pitch_type_block = [ui.input_select("pitch_type_choice", "Pitch Type", choices=["--"] + [pt.type_name for pt in pitch_types])]

            groups = _group_test_fields(entry_test_types, category.category_name)
            field_blocks = []
            for group_name, fields in groups.items():
                if len(groups) > 1:
                    field_blocks.append(ui.markdown(f"**{group_name}**"))
                inputs = []
                for t, field_label in fields:
                    label = field_label + (f" ({t.unit})" if t.unit else "")
                    inputs.append(ui.input_numeric(f"test_{t.test_type_id}", label, value=0.0, step=0.1))
                field_blocks.append(ui.layout_columns(*inputs))

            return ui.div(
                ui.h5(f"New {category.category_name} assessment", class_="gbo-section-title"),
                ui.input_date("assessment_date", "Assessment date", value=date.today()),
                *pitch_type_block,
                *field_blocks,
                ui.input_text_area("assessment_notes", "Notes (optional)"),
                ui.input_action_button("save_assessment_btn", "Save assessment", class_="btn-primary mt-2"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.save_assessment_btn)
    def _save_assessment():
        selected_player_id = int(input.player_select())
        selected_category_id = int(input.category_select())

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == selected_category_id).first()
            if category is None:
                return
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()

            pitch_types = []
            if category.category_name == "Pitcher-Specific":
                pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()
            pitch_type_id = None
            if pitch_types and "pitch_type_choice" in input:
                choice = input.pitch_type_choice()
                if choice and choice != "--":
                    pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == choice), None)

            test_types = (
                db.query(AssessmentTestType)
                .filter(AssessmentTestType.category_id == selected_category_id)
                .order_by(AssessmentTestType.display_order)
                .all()
            )
            entry_test_types = test_types
            if category.category_name in BUCKET_RELEVANT_CATEGORIES:
                allowed_names = get_bucket_test_names_for_category(category.category_name)
                entry_test_types = [t for t in test_types if t.test_name in allowed_names]

            new_assessment = Assessment(
                player_id=selected_player_id,
                category_id=selected_category_id,
                assessment_date=input.assessment_date(),
                entered_by_user_id=app_state.user_id(),
                pitch_type_id=pitch_type_id,
                notes=(input.assessment_notes() or "").strip() or None,
            )
            db.add(new_assessment)
            db.flush()

            entered_count = 0
            for t in entry_test_types:
                key = f"test_{t.test_type_id}"
                value = input[key]() if key in input else None
                if value:  # skip zero/blank entries -- treat 0.0 as "not entered", same as the original
                    db.add(AssessmentResult(assessment_id=new_assessment.assessment_id, test_type_id=t.test_type_id, value=value))
                    entered_count += 1

            if entered_count == 0:
                db.rollback()
                ui.notification_show("Enter at least one test value before saving.", type="error", duration=8)
            else:
                db.commit()
                ui.notification_show(
                    f"Saved {category.category_name} assessment for "
                    f"{selected_player.first_name} {selected_player.last_name} "
                    f"({entered_count} test value(s) recorded).",
                    type="message", duration=6,
                )
                _bump_refresh()
        finally:
            db.close()