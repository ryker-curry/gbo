"""
GBO -- My Assessments module (Player role only).

Direct port of pages/player_stats.py -- same score rings + development
profile at the top, "Goals in progress" section (baseline vs. current
for any metric tied to an active IDP goal), full Physical Testing
breakdown, and a category-filterable full history table at the bottom.
Read-only, same as the original (entering assessments stays staff-only
on Assessments -- not migrated yet).

Reuses bucket_system.compute_bucket_system (engine, unchanged) and
bucket_display.py (Shiny port of bucket_system_display.py) for the
rings/bars -- both shared with Dashboard and Analytics once those are
migrated too, same sharing bucket_system_display.py provided originally.

Reactive layout note: category select -> optional pitch-type select ->
history table is a chain of dependent choices, same as the original's
st.selectbox -> st.selectbox -> st.expander flow. Rather than building
the pitch-type select dynamically only when a Pitcher-Specific category
is chosen (which would require reading an input that might not exist
in the DOM yet -- a real ordering hazard with Shiny's reactive outputs),
BOTH selects are built together, once, in category_controls() below,
with the pitch-type select wrapped in ui.panel_conditional() so it's
always present (just hidden via CSS) until Pitcher-Specific is picked.
That sidesteps the ordering hazard entirely: history_section() can
always safely read input.pitch_type_filter() once category_controls()
has rendered at all.
"""

from datetime import date, timedelta

from shiny import module, ui, render, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, User, AssessmentCategory, Assessment, AssessmentResult,
    PitchType, IDPGoal, IDPStatus, BullpenPitch,
)
from bucket_system import compute_bucket_system

import ui_helpers
import bucket_display


@module.ui
def player_stats_ui():
    return ui.div(
        ui_helpers.page_header("My Assessments"),
        ui.output_ui("top_section"),
        ui.output_ui("category_controls"),
        ui.output_ui("history_section"),
        ui_helpers.page_footer(),
    )


@module.server
def player_stats_server(input, output, session, app_state):
    @render.ui
    def top_section():
        if not app_state.is_authenticated():
            return None

        db = get_session()
        try:
            me = db.query(User).filter(User.user_id == app_state.user_id()).first()
            if me is None or me.player_id is None:
                return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-muted")

            my_player = db.query(Player).filter(Player.player_id == me.player_id).first()
            bucket_data = compute_bucket_system(db, my_player.player_id)

            sections = []
            mode = app_state.dark_mode() or "dark"

            rings = bucket_display.build_score_rings(bucket_data, "myassess_top", mode=mode)
            if rings is not None:
                sections.append(rings)
                profile = bucket_display.build_development_profile(bucket_data, "myassess_top", mode=mode)
                if profile is not None:
                    sections.append(profile)
                sections.append(ui.hr())

            # --- Goals in progress: baseline vs. current for any metric
            # tied to an active IDP goal, same computation as the IDP page. ---
            open_goals = (
                db.query(IDPGoal)
                .join(IDPStatus)
                .options(joinedload(IDPGoal.category), joinedload(IDPGoal.target_test_type))
                .filter(
                    IDPGoal.player_id == my_player.player_id,
                    IDPGoal.target_test_type_id.isnot(None),
                    IDPStatus.status_name != "Completed",
                )
                .all()
            )
            if open_goals:
                sections.append(ui.h5("Goals in progress", class_="gbo-section-title"))
                sections.append(_goals_table_ui(db, open_goals))
                sections.append(ui.p("Full goal details (action steps, progress notes) are on My Development.", class_="text-muted small"))
                sections.append(ui.hr())

            # --- Bucket System: full breakdown by metric. ---
            sections.append(ui.h5("Physical Testing Breakdown", class_="gbo-section-title"))
            # A player can have real data in a reference-only section
            # (Mobility & ROM, Speed, etc.) before ever having Total/
            # Body Comp/Power/Strength data -- without also checking
            # mobility_rom_report here, that player would see "No
            # physical testing data yet." despite having real ROM
            # values on record (found via a screenshot of a player
            # whose ROM testing had just started, Aug 2026).
            has_any_data = (
                any(bucket_data[k] is not None for k in ("total_score", "body_comp_score", "power_score", "strength_score"))
                or bool(bucket_data.get("mobility_rom_report"))
            )
            if not has_any_data:
                sections.append(ui_helpers.empty_state("No physical testing data yet."))
            else:
                sections.append(bucket_display.build_full_breakdown(bucket_data, "myassess", mode=mode))
            sections.append(ui.hr())

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def category_controls():
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
            if not categories:
                return None
            cat_choices = {str(c.category_id): c.category_name for c in categories}
            pitcher_specific = next((c for c in categories if c.category_name == "Pitcher-Specific"), None)

            controls = [ui.input_select("category", "Category", choices=cat_choices)]

            if pitcher_specific is not None:
                me = db.query(User).filter(User.user_id == app_state.user_id()).first()
                pt_options = {"": "All pitch types"}
                if me and me.player_id:
                    used_pitch_types = (
                        db.query(PitchType)
                        .join(Assessment, Assessment.pitch_type_id == PitchType.pitch_type_id)
                        .filter(
                            Assessment.player_id == me.player_id,
                            Assessment.category_id == pitcher_specific.category_id,
                        )
                        .distinct()
                        .all()
                    )
                    for pt in used_pitch_types:
                        pt_options[str(pt.pitch_type_id)] = pt.type_name
                controls.append(
                    ui.panel_conditional(
                        f"input.category == '{pitcher_specific.category_id}'",
                        ui.input_select("pitch_type_filter", "Filter by pitch type", choices=pt_options),
                    )
                )
            return ui.div(*controls)
        finally:
            db.close()

    @render.ui
    def history_section():
        if not app_state.is_authenticated():
            return None
        category_id_str = input.category()
        req(category_id_str)  # wait until category_controls() has rendered
        category_id = int(category_id_str)

        db = get_session()
        try:
            me = db.query(User).filter(User.user_id == app_state.user_id()).first()
            if me is None or me.player_id is None:
                return None
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_id == category_id).first()
            if category is None:
                return None

            pitch_type_filter_id = None
            if category.category_name == "Pitcher-Specific":
                pt_filter_raw = input.pitch_type_filter() if "pitch_type_filter" in input else ""
                if pt_filter_raw:
                    pitch_type_filter_id = int(pt_filter_raw)

            history_query = (
                db.query(Assessment)
                .options(
                    joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                    joinedload(Assessment.pitch_type),
                )
                .filter(Assessment.player_id == me.player_id, Assessment.category_id == category_id)
                # Exclude entries auto-created by a Rapsodo import tied to
                # a Bullpen Tracking session -- that data already has a
                # proper home there (same exclusion as the original page).
                .filter(~Assessment.assessment_id.in_(
                    db.query(BullpenPitch.linked_assessment_id).filter(BullpenPitch.linked_assessment_id.isnot(None))
                ))
            )
            if pitch_type_filter_id is not None:
                history_query = history_query.filter(Assessment.pitch_type_id == pitch_type_filter_id)
            past_assessments = history_query.order_by(Assessment.assessment_date.desc()).limit(500).all()

            if not past_assessments:
                body = ui_helpers.empty_state("No entries to show.")
            else:
                content = []
                if len(past_assessments) == 500:
                    content.append(ui.p("Showing the most recent 500 entries.", class_="text-muted small"))
                content.append(_history_table_ui(past_assessments))
                body = ui.div(*content)

            return ui.accordion(
                ui.accordion_panel("Show full history (every individual entry)", body),
                open=False, id=None,
            )
        finally:
            db.close()


def _goals_table_ui(db, open_goals):
    columns = ["Category", "Metric", "Baseline", "Current", "Target", "Target date"]
    rows = []
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

        rows.append({
            "Category": g.category.category_name,
            "Metric": g.target_test_type.test_name,
            "Baseline": f"{float(g.baseline_value):.2f}{unit}" if g.baseline_value is not None else "—",
            "Current": f"{current_value:.2f}{unit}" if current_value is not None else "—",
            "Target": f"{float(g.target_value):.2f}{unit}" if g.target_value is not None else "—",
            "Target date": g.target_date.strftime("%Y-%m-%d (%a)") if g.target_date else "—",
        })

    header = ui.tags.tr(*[ui.tags.th(c) for c in columns])
    body_rows = [ui.tags.tr(*[ui.tags.td(row[c]) for c in columns]) for row in rows]
    return ui.tags.table(ui.tags.thead(header), ui.tags.tbody(*body_rows), class_="table table-sm")


def _history_table_ui(assessments):
    """st.dataframe(list_of_dicts) auto-unions heterogeneous keys across
    rows (pandas fills the gaps); a plain HTML table has to do that
    explicitly -- columns is built as the union of every row's keys, in
    first-seen order, and missing cells render as "—"."""
    rows_data = []
    columns = []
    for a in assessments:
        row = {"Date": a.assessment_date.strftime("%Y-%m-%d (%a)")}
        if a.pitch_type:
            row["Pitch Type"] = a.pitch_type.type_name
        for r in a.results:
            unit_label = f" ({r.test_type.unit})" if r.test_type.unit else ""
            row[f"{r.test_type.test_name}{unit_label}"] = round(float(r.value), 2)
        rows_data.append(row)
        for key in row:
            if key not in columns:
                columns.append(key)

    header = ui.tags.tr(*[ui.tags.th(c) for c in columns])
    body_rows = [ui.tags.tr(*[ui.tags.td(row.get(c, "—")) for c in columns]) for row in rows_data]
    return ui.tags.table(ui.tags.thead(header), ui.tags.tbody(*body_rows), class_="table table-sm")