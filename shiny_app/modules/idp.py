"""
GBO -- Individual Development Plan (IDP) module.

Direct port of pages/idp.py -- flagged during the repo audit as a genuine
gap (registered in nav.py and the original app's page list, but never
assigned to a migration batch). Goals are typed by assessment category
and can link back to the assessment record or bullpen session that
motivated them; action steps and progress notes hang off each goal.

Edit permissions, unchanged from the original:
  - Administrator, Head Coach, Coach, Strength Coach: full edit
    (create goals, add action steps, add progress notes)
  - Athletic Trainer: progress notes only
  - Sports Scientist, Data Analyst: read-only
(Nav-level gating in nav.py already keeps the Player role off this page
entirely, same as Players/Assessments/Training Routines.)

Integrated Insights: Pitcher-Specific goals whose target metric has a
Rapsodo Bullpen Analytics equivalent (analytics/rapsodo_goal_metrics.py,
unchanged -- pure functions, no Streamlit) compute baseline/current live
from RapsodoPitch instead of AssessmentResult, optionally scoped to one
pitch type. The one unmapped Pitcher-Specific test (Spin Axis) and every
other category still use the AssessmentResult path -- see that module's
docstring for why (circular averaging, not implemented).

One deliberate simplification versus the original: the per-goal "Update
status" button showed only after you changed the dropdown away from the
current value (`if new_status != status_label: if st.button(...)`) --
that requires reading a select's live value in the same execution pass
that defines it, which only works in Streamlit's rerun-the-whole-script
model. Reading a just-defined input back out inside the very same
render.ui block it's declared in is the ordering hazard this migration
avoids throughout (see assessments.py's docstring for the fuller
rationale). Simplification here: the "Update status" button is just
always visible next to the dropdown; clicking it while the dropdown
already matches the current status is a harmless no-op re-save.

Reactive layout: player picker -> goals accordion (each goal panel is
fully self-contained: status update, action steps + add-step form, work
completed, progress notes + add-note form) -> new-goal category picker
-> new-goal metric picker (reads category) -> new-goal context inputs
(reads category+metric; branches Rapsodo lookback/pitch-type/bullpen vs.
legacy-assessment lookback vs. assessment-link picker) -> new-goal
baseline preview + final form + submit (reads all of the above). Same
"never read an input from the block that defines it" chain used
throughout this migration (see player_stats.py's/assessments.py's
docstrings for the fuller rationale).

Per-goal actions (status update, add action step, add progress note) are
an unbounded, data-dependent set -- however many goals a player has --
so they get the LAZY REGISTRATION treatment training_routines.py's
per-exercise video-save buttons establish (_registered_goal_ids /
_register_goal_handlers): each goal's three handlers are registered the
first time that goal_id appears in a render pass, not up front.

v2 REDESIGN (Aug 2026, Ryker: "I want to be able to see a player's
flags, priorities, lowest hanging fruit to decide what we need to
create a development plan for"): added a Flags/Priorities/Lowest-
hanging-fruit panel between the player picker and the goals accordion,
plus a full v2 visual pass over the rest of the page (this file's mtime
predated the "Apply v2 design system" commit, so it had never been
brought in line with Roster/Player Profile/Dashboard).

_priority_pool() below is deliberately a NEW function rather than a
reuse of player_profile._priorities() -- it walks the same bucket_data
(mobility_rom_report + body/speed/power/strength/capacity metrics,
same BODY_COMP_BAR_NAMES exclusion) but resolves each flagged metric to
its AssessmentCategory + AssessmentTestType (one query per distinct
metric name, cached in a dict) so a priority row can drive the
click-to-prefill flow below. player_profile._priorities()'s flat
(status, title, detail) tuples throw that linkage away, so extending it
in place would've broken its existing callers (the profile hero card's
own priorities panel, its flag calculation) for no reason -- easier and
safer to keep that function as-is and add a second one here with the
extra data this page specifically needs. category_name comes straight
from the DB (not a hand-maintained mapping of bucket-group -> category)
so it can't drift if a metric is ever recategorized.

Click-to-prefill wiring: clicking a priority/lowest-hanging-fruit row
sets a `priority_click` input (JSON {category, metric} via a
click-delegation <script>, same .gbo-*-link / Shiny.setInputValue
pattern Roster/Team Overview already use for player-name links). That
input's handler stores (category, metric) in `_pending_prefill` and
calls ui.update_select() on the ALREADY-RENDERED "new_goal_category"
select to change its value -- it does NOT rebuild that select (learned
the hard way on Roster's season picker earlier this session: a
render.ui that rebuilds itself in reaction to its own input's value
change races the client's value-change round trip and visibly
flip-flops). new_goal_metric_picker() reacts normally to the resulting
input.new_goal_category() change and, in that SAME render pass, reads
_pending_prefill() via reactive.isolate() (a non-reactive read -- it
must NOT be a tracked dependency of this function, or the metric select
would re-render a second time right after _pending_prefill.set() fires,
using the stale pre-update category and flashing the wrong metric list
before immediately correcting itself) to decide the new select's
`selected=` at construction time. Choices and selected are therefore
always computed together in the one render pass that's genuinely
triggered by the category change -- no separate update_select call is
needed (or safe) for the metric level. _pending_prefill is cleared on
player change and on goal creation so a stale click doesn't keep
re-applying itself if the coach returns to that category later in the
same session; leaving it un-cleared otherwise is a harmless "remembers
your last click in this category" nicety, not a bug.
"""

import json
from datetime import date, datetime, time, timedelta

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, StaffPlayerAssignment, AssessmentCategory, Assessment, AssessmentResult, AssessmentTestType,
    IDPGoal, IDPActionStep, IDPProgressNote, IDPStatus, BullpenSession, PitchType, RapsodoPitch,
    TrainingSession, PlayerAssignment,
)
from analytics.rapsodo_goal_metrics import rapsodo_field_for_test_name, average_rapsodo_metric
from bucket_system import compute_bucket_system
from modules.roster import _flag_for
import bucket_display

import ui_helpers

FULL_EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Strength Coach")


def _rapsodo_avg(db, player_id, rapsodo_field, pitch_type_id, days):
    cutoff = datetime.combine(date.today() - timedelta(days=days), time.min)
    q = db.query(RapsodoPitch).filter(RapsodoPitch.player_id == player_id, RapsodoPitch.pitch_date >= cutoff)
    if pitch_type_id:
        q = q.filter(RapsodoPitch.pitch_type_id == pitch_type_id)
    pitches = q.all()
    return average_rapsodo_metric(pitches, rapsodo_field), len(pitches)


def _pitcher_specific_avg(db, player_id, category_id, test_type_id, days):
    cutoff = date.today() - timedelta(days=days)
    results = (
        db.query(AssessmentResult)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
        .filter(
            Assessment.player_id == player_id,
            Assessment.category_id == category_id,
            Assessment.assessment_date >= cutoff,
            AssessmentResult.test_type_id == test_type_id,
        )
        .all()
    )
    if not results:
        return None, 0
    return sum(float(r.value) for r in results) / len(results), len(results)


def _latest_result(db, player_id, test_type_id):
    pair = (
        db.query(AssessmentResult, Assessment.assessment_date)
        .join(Assessment, AssessmentResult.assessment_id == Assessment.assessment_id)
        .filter(Assessment.player_id == player_id, AssessmentResult.test_type_id == test_type_id)
        .order_by(Assessment.assessment_date.desc())
        .first()
    )
    if not pair:
        return None, None
    return float(pair[0].value), pair[1]


def _target_metric_info(db, category, metric_choice):
    """Resolves the new-goal metric picker's current choice into
    (target_test_type or None, uses_rapsodo, rapsodo_field or None).
    Shared between the context-inputs block, the preview/submit block,
    and the save handler so the branch logic (Rapsodo-mapped vs. legacy
    Pitcher-Specific vs. every other category) is written once."""
    if not metric_choice or metric_choice == "-- No specific metric --":
        return None, False, None
    test_type = (
        db.query(AssessmentTestType)
        .filter(AssessmentTestType.category_id == category.category_id, AssessmentTestType.test_name == metric_choice)
        .first()
    )
    if test_type is None:
        return None, False, None
    is_pitcher_specific = category.category_name == "Pitcher-Specific"
    rapsodo_field = rapsodo_field_for_test_name(metric_choice) if is_pitcher_specific else None
    return test_type, rapsodo_field is not None, rapsodo_field


def _priority_pool(db, bd):
    """Every flagged/watch metric for this player's current bucket_data,
    resolved to its category + test name for goal-linking. Same source
    data player_profile._priorities() walks (mobility_rom_report,
    body_comp_metrics filtered to BODY_COMP_BAR_NAMES, speed_metrics,
    and the power/strength/capacity subgroup dicts flattened) -- see
    this module's docstring for why this is a separate function rather
    than a reuse of that one.

    Each item: {"scale": float 0-100 (LOWER = worse/farther from
    passing, same direction as a percentile), "status": "flag"|"watch",
    "title": str, "detail": str, "category_name": str|None,
    "metric_name": str|None}. category_name/metric_name are None only
    if a metric's name doesn't resolve to a real AssessmentTestType
    (shouldn't happen for anything bucket_system already scored, but
    the panel below just renders those rows non-clickable rather than
    assuming).

    ROM rows aren't percentile-based (see MOBILITY_ROM_THRESHOLDS in
    bucket_system.py -- pass/fail against a fixed floor, not a team
    ranking), so they get a synthetic 0-59 "scale" from how close raw
    is to its threshold (raw/threshold, clamped) when both are numbers,
    or a flat 10 (red) / 40 (yellow) fallback otherwise -- close enough
    to sit sensibly alongside percentile-based rows in one merged,
    ranked list without pretending ROM degrees and percentiles are the
    same unit.
    """
    items = []
    test_type_cache = {}

    def _category_for(test_name):
        if test_name not in test_type_cache:
            test_type_cache[test_name] = (
                db.query(AssessmentTestType)
                .options(joinedload(AssessmentTestType.category))
                .filter(AssessmentTestType.test_name == test_name)
                .first()
            )
        return test_type_cache[test_name]

    for row in bd.get("mobility_rom_report") or []:
        st = row.get("status")
        if st not in ("red", "yellow"):
            continue
        name = row.get("test_name") or row.get("name") or row.get("label") or "Mobility"
        raw, unit, thr = row.get("raw"), row.get("unit") or "", row.get("threshold")
        detail = row.get("explanation") or row.get("recommendation") or ""
        if not detail and raw is not None:
            detail = f"{raw:g}{unit}" + (f" · threshold {thr:g}{unit}" if thr is not None else "")
        if raw is not None and thr:
            scale = max(0.0, min(59.0, 59.0 * float(raw) / float(thr)))
        else:
            scale = 10.0 if st == "red" else 40.0
        tt = _category_for(name)
        items.append({
            "scale": scale,
            "status": ui_helpers.status_from_color_word(st),
            "title": name.replace(": ", " — "),
            "detail": detail.strip(),
            "category_name": tt.category.category_name if tt and tt.category else None,
            "metric_name": tt.test_name if tt else None,
        })

    groups = [("body_comp_metrics", None), ("speed_metrics", None), ("power_subgroup_metrics", "sub"), ("strength_subgroup_metrics", "sub"), ("capacity_subgroup_metrics", "sub")]
    for key, kind in groups:
        data = bd.get(key) or {}
        metrics = {}
        if kind == "sub":
            for sub, m in data.items():
                metrics.update(m)
        else:
            metrics = data
        if key == "body_comp_metrics":
            # Same BODY_COMP_BAR_NAMES split every other percentile-scoring
            # context in this app uses -- Body Fat Mass/% stay reference-only.
            metrics = {n: d for n, d in metrics.items() if n in bucket_display.BODY_COMP_BAR_NAMES}
        for name, d in metrics.items():
            pct = d.get("percentile")
            if pct is None:
                continue
            st = ui_helpers.status_from_percentile(pct)
            if st not in (ui_helpers.STATUS_FLAG, ui_helpers.STATUS_WATCH):
                continue
            tt = _category_for(name)
            items.append({
                "scale": float(pct),
                "status": st,
                "title": name,
                "detail": f"{d.get('raw')}{(' ' + d['unit']) if d.get('unit') else ''} · {bucket_display.ordinal(pct)} percentile on team",
                "category_name": tt.category.category_name if tt and tt.category else None,
                "metric_name": tt.test_name if tt else None,
            })
    return items


def _priorities_view(pool, limit=6):
    """Worst-first slice of the pool -- what to work on, most urgent."""
    return sorted(pool, key=lambda x: x["scale"])[:limit]


def _lowest_hanging_fruit_view(pool, limit=6):
    """Closest-to-passing-first slice -- prefers Attention-status metrics
    (already closer to Good than a Priority-status one) and, among
    those, the highest scale (nearest the threshold). Falls back to the
    whole pool sorted the same way if nothing is Attention-status, so
    it's never empty just because everything on file is a hard flag."""
    watch = [i for i in pool if i["status"] == ui_helpers.STATUS_WATCH]
    return sorted(watch or pool, key=lambda x: -x["scale"])[:limit]


@module.ui
def idp_ui():
    return ui.div(
        ui_helpers.page_header("Individual Development Plan", "Flags, priorities, and lowest-hanging fruit -- click a row below to start a goal for that metric."),
        ui.div(ui.output_ui("player_picker"), class_="gbo-filter"),
        ui.output_ui("player_flags_panel"),
        ui.output_ui("goals_section"),
        ui_helpers.card(
            ui.output_ui("new_goal_category_picker"),
            ui.output_ui("new_goal_metric_picker"),
            ui.output_ui("new_goal_context_inputs"),
            ui.output_ui("new_goal_form_and_submit"),
            title="New development goal",
            right="pick a category, or click a priority above to prefill",
        ),
        ui_helpers.page_footer(),
    )


@module.server
def idp_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _registered_goal_ids = set()

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _can_create_goals():
        return app_state.role_name() in FULL_EDIT_ROLES

    def _can_add_progress_notes():
        return app_state.role_name() in FULL_EDIT_ROLES + ("Athletic Trainer",)

    def _visible_players(db):
        query = db.query(Player).filter(Player.active.is_(True))
        if not app_state.can_view_all_players():
            assigned_ids = [
                a.player_id for a in
                db.query(StaffPlayerAssignment)
                .filter(StaffPlayerAssignment.staff_user_id == app_state.user_id())
                .all()
            ]
            query = query.filter(Player.player_id.in_(assigned_ids))
        return query.order_by(Player.last_name, Player.first_name).all()

    # -------------------------------------------------------------------
    # Player picker
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
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}
            return ui.input_select("player_select", "Player", choices=choices)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Flags / Priorities / Lowest-hanging-fruit panel
    # -------------------------------------------------------------------

    _pending_prefill = reactive.Value(None)  # (category_name, metric_name) or None -- see module docstring

    @render.ui
    def player_flags_panel():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_player_id = int(input.player_select())
        can_click = _can_create_goals()

        db = get_session()
        try:
            bd = compute_bucket_system(db, selected_player_id) or {}
            flag, why = _flag_for(bd)
            pool = _priority_pool(db, bd)
            pris = _priorities_view(pool)
            fruit = _lowest_hanging_fruit_view(pool)

            def row(item, idx):
                inner = ui.div(
                    ui.div(str(idx), class_=f"gbo-pri-i {item['status']}"),
                    ui.div(ui.tags.b(item["title"]), ui.span(item["detail"])),
                )
                if can_click and item["category_name"] and item["metric_name"]:
                    return ui.tags.a(
                        inner, href="#", class_="gbo-pri gbo-idp-pri-link",
                        **{"data-category": item["category_name"], "data-metric": item["metric_name"]},
                    )
                return ui.div(inner, class_="gbo-pri")

            pri_rows = [row(it, i) for i, it in enumerate(pris, 1)] or [ui_helpers.empty_state("No flagged metrics right now.")]
            fruit_rows = [row(it, i) for i, it in enumerate(fruit, 1)] or [ui_helpers.empty_state("Nothing close to passing right now.")]

            flag_tile = ui.div(
                ui_helpers.kpi_tile("Overall flag", ui_helpers.status_chip(flag), delta=why or "No flags"),
                ui_helpers.kpi_tile("Priorities", str(len(pool)), delta=f"{sum(1 for i in pool if i['status'] == 'flag')} flag · {sum(1 for i in pool if i['status'] == 'watch')} attention" if pool else "None on file"),
                class_="gbo-kpi-row", style="margin-bottom:16px;",
            )
            panel = ui.div(
                flag_tile,
                ui.div(
                    ui_helpers.card(*pri_rows, title="Priorities", right="worst metrics first"),
                    ui_helpers.card(*fruit_rows, title="Lowest-hanging fruit", right="closest to passing first"),
                    class_="gbo-grid gbo-grid-2",
                ),
                id=session.ns("flags_panel"),
                style="margin-bottom:24px;",
            )
            js = ui.tags.script(f"""
            (function(){{
              var root = document.getElementById('{session.ns("flags_panel")}');
              if (!root || root.__gboBound) return; root.__gboBound = true;
              root.addEventListener('click', function(e){{
                var a = e.target.closest ? e.target.closest('.gbo-idp-pri-link') : null;
                if (!a) return; e.preventDefault();
                Shiny.setInputValue('{session.ns("priority_click")}', JSON.stringify({{category: a.getAttribute('data-category'), metric: a.getAttribute('data-metric')}}), {{priority:'event'}});
              }});
            }})();""")
            return ui.div(panel, js)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.priority_click)
    def _consume_priority_click():
        try:
            payload = json.loads(input.priority_click())
        except (TypeError, ValueError):
            return
        category, metric = payload.get("category"), payload.get("metric")
        if not category:
            return
        _pending_prefill.set((category, metric))
        ui.update_select("new_goal_category", selected=category)
        ui.notification_show(f"Prefilled a new goal for {metric} ({category}) -- see New development goal below.", type="message", duration=6)

    # -------------------------------------------------------------------
    # Goals accordion for the selected player
    # -------------------------------------------------------------------

    @render.ui
    def goals_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_player_id = int(input.player_select())
        can_create_goals = _can_create_goals()
        can_add_progress_notes = _can_add_progress_notes()

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            if selected_player is None:
                return None

            statuses = db.query(IDPStatus).order_by(IDPStatus.display_order).all()
            status_names = [s.status_name for s in statuses]

            goals = (
                db.query(IDPGoal)
                .options(
                    joinedload(IDPGoal.category),
                    joinedload(IDPGoal.status),
                    joinedload(IDPGoal.source_assessment),
                    joinedload(IDPGoal.target_test_type),
                    joinedload(IDPGoal.target_pitch_type),
                    joinedload(IDPGoal.source_bullpen).joinedload(BullpenSession.bullpen_type),
                    joinedload(IDPGoal.action_steps).joinedload(IDPActionStep.status),
                    joinedload(IDPGoal.progress_notes),
                    joinedload(IDPGoal.linked_sessions).joinedload(TrainingSession.session_type),
                    joinedload(IDPGoal.linked_assignments).joinedload(PlayerAssignment.session_type),
                )
                .filter(IDPGoal.player_id == selected_player_id)
                .order_by(IDPGoal.created_at.desc())
                .all()
            )

            header = [ui_helpers.section_title(f"Goals — {selected_player.first_name} {selected_player.last_name}", right=f"{len(goals)} goal(s)" if goals else None)]
            if not goals:
                return ui.div(*header, ui_helpers.empty_state("No development goals yet for this player."))

            panels = []
            for goal in goals:
                status_label = goal.status.status_name if goal.status else "—"
                truncated = goal.description[:60] + ("..." if len(goal.description) > 60 else "")
                title = ui.div(
                    ui.span(f"{goal.category.category_name} — {truncated}", class_="gbo-accordion-title-text"),
                    ui_helpers.status_chip("good" if status_label == "Completed" else "neutral", status_label),
                    style="display:flex; align-items:center; justify-content:space-between; gap:12px; width:100%;",
                )

                body = [ui.p(goal.description)]

                if goal.target_test_type:
                    unit = f" {goal.target_test_type.unit}" if goal.target_test_type.unit else ""
                    pitch_type_suffix = f" ({goal.target_pitch_type.type_name})" if goal.target_pitch_type else ""
                    target_line = f"**Target: {goal.target_test_type.test_name}{pitch_type_suffix}** — "
                    if goal.baseline_value is not None:
                        target_line += f"{float(goal.baseline_value):.2f}{unit} → "
                    if goal.target_value is not None:
                        target_line += f"{float(goal.target_value):.2f}{unit}"
                    if goal.target_date:
                        target_line += f" by {goal.target_date.strftime('%Y-%m-%d (%a)')}"
                    body.append(ui.markdown(target_line))

                    if goal.category.category_name == "Pitcher-Specific":
                        rapsodo_field = rapsodo_field_for_test_name(goal.target_test_type.test_name)
                        if rapsodo_field:
                            avg, count = _rapsodo_avg(db, goal.player_id, rapsodo_field, goal.target_pitch_type_id, 30)
                            if avg is not None:
                                pitch_note = f" of {goal.target_pitch_type.type_name}" if goal.target_pitch_type else ""
                                body.append(ui.p(f"Current: {avg:.2f}{unit} (avg{pitch_note}, {count} pitch(es), last 30 days)", class_="text-muted small"))
                            else:
                                body.append(ui.p("Current: no Rapsodo pitches matching this metric/pitch type in the last 30 days.", class_="text-muted small"))
                        else:
                            avg, count = _pitcher_specific_avg(db, goal.player_id, goal.category_id, goal.target_test_type_id, 30)
                            if avg is not None:
                                body.append(ui.p(f"Current: {avg:.2f}{unit} (avg of {count} pitches, last 30 days)", class_="text-muted small"))
                            else:
                                body.append(ui.p("Current: no pitches with this metric in the last 30 days.", class_="text-muted small"))
                    else:
                        val, dt = _latest_result(db, goal.player_id, goal.target_test_type_id)
                        if val is not None:
                            body.append(ui.p(f"Current: {val:.2f}{unit} (most recent, {dt.strftime('%Y-%m-%d (%a)')})", class_="text-muted small"))
                        else:
                            body.append(ui.p("Current: no assessments recorded for this metric yet.", class_="text-muted small"))

                if goal.source_assessment:
                    body.append(ui.p(f"Linked to assessment dated {goal.source_assessment.assessment_date.strftime('%Y-%m-%d (%a)')}", class_="text-muted small"))
                if goal.source_bullpen:
                    bp_type = goal.source_bullpen.bullpen_type.type_name if goal.source_bullpen.bullpen_type else "—"
                    body.append(ui.p(f"Linked to bullpen session dated {goal.source_bullpen.session_date.strftime('%Y-%m-%d (%a)')} ({bp_type})", class_="text-muted small"))

                if can_create_goals:
                    body.append(ui.layout_columns(
                        ui.input_select(f"goal_status_{goal.goal_id}", "Status", choices=status_names, selected=status_label if status_label in status_names else None),
                        ui.div(ui.input_action_button(f"update_status_btn_{goal.goal_id}", "Update status", class_="btn-primary btn-sm"), class_="d-flex align-items-end"),
                        col_widths=[8, 4],
                    ))

                body.append(ui.p(ui.strong("Action steps")))
                if not goal.action_steps:
                    body.append(ui.p("No action steps yet.", class_="text-muted small"))
                else:
                    body.append(ui_helpers.render_dict_table([
                        {
                            "Description": a.description,
                            "Status": a.status.status_name if a.status else "—",
                            "Due date": a.due_date.strftime("%Y-%m-%d (%a)") if a.due_date else "—",
                        }
                        for a in goal.action_steps
                    ]))
                if can_create_goals:
                    body.append(ui.input_text(f"step_desc_{goal.goal_id}", "New action step"))
                    body.append(ui.input_date(f"step_due_{goal.goal_id}", "Due date", value=date.today()))
                    body.append(ui.input_select(f"step_status_{goal.goal_id}", "Status", choices=status_names))
                    body.append(ui.input_action_button(f"add_step_btn_{goal.goal_id}", "Add action step", class_="btn-primary btn-sm mt-1"))

                body.append(ui.p(ui.strong("Work completed toward this goal")))
                completed_assignments = [a for a in goal.linked_assignments if a.completed]
                if not completed_assignments and not goal.linked_sessions:
                    body.append(ui.p(
                        "No completed work logged toward this goal yet -- assign one from Player Assignments and mark it completed once it's done.",
                        class_="text-muted small",
                    ))
                else:
                    rows = [
                        {
                            "Date": a.scheduled_date.strftime("%Y-%m-%d (%a)"),
                            "Type": a.session_type.type_name if a.session_type else "—",
                            "What happened": a.completed_notes or "",
                        }
                        for a in sorted(completed_assignments, key=lambda a: a.scheduled_date, reverse=True)
                    ]
                    rows += [
                        {
                            "Date": s.session_date.strftime("%Y-%m-%d (%a)"),
                            "Type": s.session_type.type_name if s.session_type else "—",
                            "What happened": s.notes or "",
                        }
                        for s in sorted(goal.linked_sessions, key=lambda s: s.session_date, reverse=True)
                    ]
                    body.append(ui_helpers.render_dict_table(rows))

                body.append(ui.p(ui.strong("Progress notes")))
                if not goal.progress_notes:
                    body.append(ui.p("No progress notes yet.", class_="text-muted small"))
                else:
                    for note in sorted(goal.progress_notes, key=lambda n: n.created_at, reverse=True):
                        body.append(ui.p(ui.strong(note.created_at.strftime("%Y-%m-%d (%a)"))))
                        body.append(ui.p(note.note_text))
                if can_add_progress_notes:
                    body.append(ui.input_text_area(f"note_text_{goal.goal_id}", "New progress note"))
                    body.append(ui.input_action_button(f"add_note_btn_{goal.goal_id}", "Add progress note", class_="btn-primary btn-sm mt-1"))

                if goal.goal_id not in _registered_goal_ids:
                    _registered_goal_ids.add(goal.goal_id)
                    _register_goal_handlers(goal.goal_id)

                panels.append(ui.accordion_panel(title, *body))

            return ui.div(*header, ui.accordion(*panels, open=False, id=None))
        finally:
            db.close()

    def _register_goal_handlers(goal_id):
        @reactive.effect
        @reactive.event(input[f"update_status_btn_{goal_id}"])
        def _update_status():
            key = f"goal_status_{goal_id}"
            if key not in input:
                return
            db = get_session()
            try:
                goal = db.query(IDPGoal).filter(IDPGoal.goal_id == goal_id).first()
                if goal is None:
                    return
                status = db.query(IDPStatus).filter(IDPStatus.status_name == input[key]()).first()
                if status is None:
                    return
                goal.status_id = status.status_id
                db.commit()
                ui.notification_show("Status updated.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[f"add_step_btn_{goal_id}"])
        def _add_step():
            desc_key, due_key, status_key = f"step_desc_{goal_id}", f"step_due_{goal_id}", f"step_status_{goal_id}"
            if desc_key not in input:
                return
            desc = (input[desc_key]() or "").strip()
            if not desc:
                ui.notification_show("Enter a description for the action step.", type="error", duration=8)
                return
            db = get_session()
            try:
                status = db.query(IDPStatus).filter(IDPStatus.status_name == input[status_key]()).first() if status_key in input else None
                db.add(IDPActionStep(
                    goal_id=goal_id,
                    description=desc,
                    status_id=status.status_id if status else db.query(IDPStatus).order_by(IDPStatus.display_order).first().status_id,
                    due_date=input[due_key]() if due_key in input else None,
                ))
                db.commit()
                ui.notification_show("Action step added.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[f"add_note_btn_{goal_id}"])
        def _add_note():
            note_key = f"note_text_{goal_id}"
            if note_key not in input:
                return
            text = (input[note_key]() or "").strip()
            if not text:
                ui.notification_show("Enter a progress note first.", type="error", duration=8)
                return
            db = get_session()
            try:
                db.add(IDPProgressNote(goal_id=goal_id, note_text=text, created_by_user_id=app_state.user_id()))
                db.commit()
                ui.notification_show("Progress note added.", type="message", duration=6)
                _bump_refresh()
            finally:
                db.close()

    # -------------------------------------------------------------------
    # New development goal
    # -------------------------------------------------------------------

    @render.ui
    def new_goal_category_picker():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        if not _can_create_goals():
            if _can_add_progress_notes():
                return ui.p("Your role can add progress notes to existing goals, but not create new goals.", class_="text-muted")
            return ui.p("Your role has read-only access to IDP.", class_="text-muted")

        db = get_session()
        try:
            categories = db.query(AssessmentCategory).filter(AssessmentCategory.category_name != "Anthropometrics").order_by(AssessmentCategory.display_order).all()
            if not categories:
                return None
            choices = {c.category_name: c.category_name for c in categories}
            return ui.input_select("new_goal_category", "Category", choices=choices)
        finally:
            db.close()

    @render.ui
    def new_goal_metric_picker():
        _refresh_tick()
        if not (app_state.is_authenticated() and _can_create_goals()):
            return None
        req("new_goal_category" in input)
        category_choice = input.new_goal_category()

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == category_choice).first()
            if category is None:
                return None
            test_types = db.query(AssessmentTestType).filter(AssessmentTestType.category_id == category.category_id).order_by(AssessmentTestType.display_order).all()
            if not test_types:
                return ui.p("No specific tests defined yet for this category -- target metric isn't available until they are.", class_="text-muted small")
            choices = ["-- No specific metric --"] + [t.test_name for t in test_types]
            # Non-reactive read -- must NOT become a tracked dependency of
            # this function (see module docstring's click-to-prefill
            # section for the race that creates if it is).
            with reactive.isolate():
                pending = _pending_prefill()
            pending_metric = pending[1] if pending and pending[0] == category_choice and pending[1] in choices else None
            return ui.input_select("new_goal_target_metric", "Target metric (optional)", choices=choices, selected=pending_metric)
        finally:
            db.close()

    @render.ui
    def new_goal_context_inputs():
        _refresh_tick()
        if not (app_state.is_authenticated() and _can_create_goals()):
            return None
        req("player_select" in input)
        req("new_goal_category" in input)
        selected_player_id = int(input.player_select())
        category_choice = input.new_goal_category()
        metric_choice = input.new_goal_target_metric() if "new_goal_target_metric" in input else None

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == category_choice).first()
            if category is None:
                return None
            is_pitcher_specific = category.category_name == "Pitcher-Specific"
            target_test_type, uses_rapsodo, _ = _target_metric_info(db, category, metric_choice)

            if uses_rapsodo:
                all_pitch_types = db.query(PitchType).order_by(PitchType.display_order).all()
                player_rapsodo_bullpens = (
                    db.query(BullpenSession)
                    .join(RapsodoPitch, RapsodoPitch.bullpen_id == BullpenSession.bullpen_id)
                    .filter(BullpenSession.player_id == selected_player_id)
                    .distinct()
                    .order_by(BullpenSession.session_date.desc())
                    .all()
                )
                bullpen_choices = {"": "-- Not linked to a specific bullpen session --"}
                bullpen_choices.update({str(b.bullpen_id): f"{b.session_date.strftime('%Y-%m-%d (%a)')} (#{b.bullpen_id})" for b in player_rapsodo_bullpens})
                pitch_type_choices = {"": "All Pitch Types"}
                pitch_type_choices.update({str(pt.pitch_type_id): pt.type_name for pt in all_pitch_types})
                return ui.div(
                    ui.p(
                        "This metric comes from Rapsodo Bullpen Analytics -- the baseline is an average over a "
                        "recent window of actual pitches, optionally scoped to one pitch type.",
                        class_="text-muted small",
                    ),
                    ui.input_numeric("new_goal_lookback", "Lookback window (days)", value=30, min=1, max=365, step=1),
                    ui.input_select("new_goal_pitch_type", "Pitch type (optional)", choices=pitch_type_choices),
                    ui.input_select("new_goal_bullpen", "Link to bullpen session (optional)", choices=bullpen_choices),
                )
            elif is_pitcher_specific:
                return ui.div(
                    ui.p(
                        "This metric doesn't have a Rapsodo equivalent yet, so it still uses the older "
                        "assessment-based baseline -- continuous, per-pitch averaging over a recent window.",
                        class_="text-muted small",
                    ),
                    ui.input_numeric("new_goal_lookback", "Lookback window (days)", value=30, min=1, max=365, step=1),
                )
            else:
                player_assessments = (
                    db.query(Assessment)
                    .filter(Assessment.player_id == selected_player_id, Assessment.category_id == category.category_id)
                    .order_by(Assessment.assessment_date.desc())
                    .limit(50)
                    .all()
                )
                choices = {"": "-- Not linked to a specific assessment --"}
                choices.update({str(a.assessment_id): f"{a.assessment_date.strftime('%Y-%m-%d (%a)')} (#{a.assessment_id})" for a in player_assessments})
                return ui.input_select("new_goal_assessment", "Link to assessment (optional)", choices=choices)
        finally:
            db.close()

    @render.ui
    def new_goal_form_and_submit():
        _refresh_tick()
        if not (app_state.is_authenticated() and _can_create_goals()):
            return None
        req("player_select" in input)
        req("new_goal_category" in input)
        selected_player_id = int(input.player_select())
        category_choice = input.new_goal_category()
        metric_choice = input.new_goal_target_metric() if "new_goal_target_metric" in input else None

        db = get_session()
        try:
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == category_choice).first()
            if category is None:
                return None
            statuses = db.query(IDPStatus).order_by(IDPStatus.display_order).all()
            target_test_type, uses_rapsodo, rapsodo_field = _target_metric_info(db, category, metric_choice)

            preview = []
            baseline_value = None
            if target_test_type is not None:
                unit = target_test_type.unit or ""
                if uses_rapsodo:
                    lookback_days = input.new_goal_lookback() if "new_goal_lookback" in input else 30
                    pitch_type_raw = input.new_goal_pitch_type() if "new_goal_pitch_type" in input else ""
                    pitch_type_id = int(pitch_type_raw) if pitch_type_raw else None
                    avg, count = _rapsodo_avg(db, selected_player_id, rapsodo_field, pitch_type_id, lookback_days)
                    baseline_value = avg
                    if avg is not None:
                        pitch_note = " of the selected pitch type" if pitch_type_id else ""
                        preview.append(ui.p(f"Baseline auto-filled: average{pitch_note} of {count} pitch(es) over the last {lookback_days} days = {avg:.2f} {unit}", class_="text-muted small"))
                    else:
                        preview.append(ui.p(f"No Rapsodo pitches match this metric/pitch type in the last {lookback_days} days -- enter a baseline manually below, or widen the lookback window.", class_="text-muted small"))
                elif category.category_name == "Pitcher-Specific":
                    lookback_days = input.new_goal_lookback() if "new_goal_lookback" in input else 30
                    avg, count = _pitcher_specific_avg(db, selected_player_id, category.category_id, target_test_type.test_type_id, lookback_days)
                    baseline_value = avg
                    if avg is not None:
                        preview.append(ui.p(f"Baseline auto-filled: average of {count} pitches over the last {lookback_days} days = {avg:.2f} {unit}", class_="text-muted small"))
                    else:
                        preview.append(ui.p(f"No pitches with this metric in the last {lookback_days} days -- enter a baseline manually below, or widen the lookback window.", class_="text-muted small"))
                else:
                    assessment_raw = input.new_goal_assessment() if "new_goal_assessment" in input else ""
                    if assessment_raw:
                        matching_result = (
                            db.query(AssessmentResult)
                            .filter(AssessmentResult.assessment_id == int(assessment_raw), AssessmentResult.test_type_id == target_test_type.test_type_id)
                            .first()
                        )
                        if matching_result:
                            baseline_value = float(matching_result.value)
                            preview.append(ui.p(f"Baseline auto-filled from the linked assessment: {baseline_value} {unit}", class_="text-muted small"))

            fields = list(preview)
            if target_test_type is not None:
                fields.append(ui.input_numeric("new_goal_baseline_value", f"Baseline value{f' ({unit})' if unit else ''}", value=baseline_value if baseline_value is not None else 0.0, step=0.1))
                fields.append(ui.input_numeric("new_goal_target_value", f"Target value{f' ({unit})' if unit else ''}", value=0.0, step=0.1))
                fields.append(ui.input_date("new_goal_target_date", "Target date", value=date.today() + timedelta(days=60)))
            fields.append(ui.input_text_area("new_goal_description", "Goal description"))
            fields.append(ui.input_select("new_goal_status", "Initial status", choices=[s.status_name for s in statuses]))
            fields.append(ui.input_action_button("create_goal_btn", "Create goal", class_="btn-primary mt-2"))

            return ui.div(*fields)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.create_goal_btn)
    def _create_goal():
        selected_player_id = int(input.player_select())
        category_choice = input.new_goal_category()
        metric_choice = input.new_goal_target_metric() if "new_goal_target_metric" in input else None
        description = (input.new_goal_description() or "").strip()
        if not description:
            ui.notification_show("Goal description is required.", type="error", duration=8)
            return

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == category_choice).first()
            if category is None:
                return
            statuses = db.query(IDPStatus).order_by(IDPStatus.display_order).all()
            target_test_type, uses_rapsodo, rapsodo_field = _target_metric_info(db, category, metric_choice)

            source_assessment_id = None
            source_bullpen_id = None
            target_pitch_type_id = None

            if target_test_type is not None and uses_rapsodo:
                pitch_type_raw = input.new_goal_pitch_type() if "new_goal_pitch_type" in input else ""
                target_pitch_type_id = int(pitch_type_raw) if pitch_type_raw else None
                bullpen_raw = input.new_goal_bullpen() if "new_goal_bullpen" in input else ""
                source_bullpen_id = int(bullpen_raw) if bullpen_raw else None
            elif target_test_type is not None and category.category_name != "Pitcher-Specific":
                assessment_raw = input.new_goal_assessment() if "new_goal_assessment" in input else ""
                source_assessment_id = int(assessment_raw) if assessment_raw else None
            elif target_test_type is None and category.category_name != "Pitcher-Specific":
                assessment_raw = input.new_goal_assessment() if "new_goal_assessment" in input else ""
                source_assessment_id = int(assessment_raw) if assessment_raw else None

            new_goal = IDPGoal(
                player_id=selected_player_id,
                category_id=category.category_id,
                source_assessment_id=source_assessment_id,
                source_bullpen_id=source_bullpen_id,
                target_test_type_id=target_test_type.test_type_id if target_test_type else None,
                target_pitch_type_id=target_pitch_type_id if target_test_type else None,
                baseline_value=input.new_goal_baseline_value() if target_test_type is not None else None,
                target_value=input.new_goal_target_value() if target_test_type is not None else None,
                target_date=input.new_goal_target_date() if target_test_type is not None else None,
                description=description,
                status_id=next(s.status_id for s in statuses if s.status_name == input.new_goal_status()),
                created_by_user_id=app_state.user_id(),
            )
            db.add(new_goal)
            db.commit()
            ui.notification_show(f"Created goal for {selected_player.first_name} {selected_player.last_name}.", type="message", duration=8)
            _pending_prefill.set(None)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.player_select)
    def _on_player_change():
        _pending_prefill.set(None)
