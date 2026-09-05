"""
GBO -- Shared, read-only Command Tracker display: renders a single
session's already-saved command-tracking data (scorecard + two charts)
given nothing but a bullpen_id. Reused by
shiny_app/modules/bullpen_dashboard.py so a coach OR the player who
threw the bullpen can view a command-focused session's results from
the same Bullpen Dashboard picker used for Rapsodo sessions, without
touching the entry workflow.

Command Tracker itself (shiny_app/modules/command_tracker.py) stays
the only place pitches get click-to-place ENTERED, EDITED, or DELETED
-- this module is read-only, reusing its exact aggregate math
(analytics/command_metrics.py) and its exact charts
(visualizations/command_charts.py) so the two views can never disagree
about the same session's numbers. Lifted from that module's
cmd_scorecard_section/cmd_chart_section -- the underlying computation
was already pure (query by bullpen_id, then plain functions); only the
reactive coupling (_refresh_tick/_active_bullpen_id/_access_ok)
changes, swapped for bullpen_dashboard_display.
register_bullpen_dashboard's get_target(input) convention so both can
be registered side by side on the same page.

Written for BOTH a coach and the player who threw the bullpen (Command
Tracker's own entry workflow is coach/staff-only; this view isn't) --
Sept 2026, Ryker: command data needs to be understandable to a player
reading it alone, not just a coach who already knows the vocabulary.
So every jargon term (Danger-Adj. Miss, the miss-pattern line, the four
target bands) gets one plain-language line near it, and the band
thresholds are pulled live from command_config.py rather than restated
as a bare "3/6/9" so this can never drift out of sync with the actual
classification.

Sept 2026 addition: a Pitch Type filter plus a "Pitches to Show"
multi-select, same two-output controls/results split as
bullpen_dashboard_display.py's own filters -- added because the
pitch-locations chart (visualizations/command_charts.
pitch_locations_chart) gets crowded once a session has more than a
handful of pitches. Ryker specifically wanted to pick exactly which
pitches show (not just a contiguous range), so pitch selection is a
multi-select of individual pitch numbers -- every pitch is selected by
default, and unchecking/removing one drops it from the scorecard,
table, AND both charts at once.

Calling convention -- same shape as bullpen_dashboard_display.
register_bullpen_dashboard, so both can sit on the same page:

    register_command_dashboard(input, output, session, key_prefix, get_target)

Call once, unconditionally, from the caller's @module.server body.
get_target(input) must return {"kind": "session", "bullpen_id": int}
or None (no "combined" kind yet -- an Overall Command view aggregating
a pitcher's command sessions is a deliberate not-yet, same call Ryker
made for the Rapsodo Overall Pitch Tracking section when this shipped;
revisit once there's more fall-ball command data to look at). Returns
a ui.output_ui fragment for the caller's own render.ui tree.
"""

from shiny import ui, render, reactive, req
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload

from database import get_session
from models import BullpenSession, CommandPitch
from analytics import command_metrics
import command_config
from visualizations import command_charts

import ui_helpers

TEXT_CREAM = "#FFFDE5"


def _fmt(value, suffix=""):
    return f"{value}{suffix}" if value is not None else "—"


def _bias_label(bias):
    parts = []
    if bias["horizontal_bias_in"] is not None:
        parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
    if bias["vertical_bias_in"] is not None:
        parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
    return " / ".join(parts) if parts else "—"


def _band_legend():
    """Plain-language line for the four target-radius bands, built from
    command_config.py's actual configured radii (rather than a
    hardcoded "3/6/9") so this line can never say a threshold the real
    Precise/Good/Competitive/Major Miss classification doesn't use."""
    parts = [f'{label} ≤{radius:.0f}"' for radius, label in command_config.TARGET_RADII_IN]
    parts.append(f'{command_config.MAJOR_MISS_LABEL} beyond {command_config.COMPETITIVE_TARGET_RADIUS_IN:.0f}"')
    return "Bands: " + " · ".join(parts) + " from the target."


def register_command_dashboard(input, output, session, key_prefix, get_target):
    controls_id = f"{key_prefix}_controls"
    results_id = f"{key_prefix}_results"
    locations_widget_id = f"{key_prefix}_pitch_locations_chart"
    chart_widget_id = f"{key_prefix}_command_chart"

    type_filter_key = f"{key_prefix}_pitch_type_filter"
    select_key = f"{key_prefix}_pitch_select"

    @reactive.calc
    def _target_and_pitches():
        """Every pitch for the target session, unfiltered -- shared by
        _controls (to build the filter choices/range) and _filtered
        below, so picking a session only queries CommandPitch once per
        actual change, same reasoning as bullpen_dashboard_display.py's
        own _target_and_pitches @reactive.calc."""
        target = get_target(input)
        if target is None:
            return None, None
        db = get_session()
        try:
            pitches = (
                db.query(CommandPitch)
                .options(joinedload(CommandPitch.pitch_type))
                .filter(CommandPitch.bullpen_id == target["bullpen_id"])
                .order_by(CommandPitch.pitch_number)
                .all()
            )
            return target, pitches
        finally:
            db.close()

    @reactive.calc
    def _filtered():
        """(target, filtered_pitches) -- shared by _results and both
        chart widgets below, so the pitch-type/selection filtering only
        happens once per actual change instead of once per output.
        Local filtering rather than a shared helper -- CommandPitch
        has nothing in common with RapsodoPitch's
        analytics.bullpen_metrics.filter_pitches (no velocity/spin
        filters, different model entirely). Pitch selection is exact
        membership (a multi-select of individual pitch numbers), not a
        lo/hi range -- Ryker wanted to be able to pick specific pitches
        (e.g. 1, 4, 9), not just a contiguous stretch."""
        req(type_filter_key in input)
        req(select_key in input)
        target, all_pitches = _target_and_pitches()
        if target is None:
            return None, None
        selected_type = input[type_filter_key]()
        selected_numbers = {int(v) for v in input[select_key]()}
        filtered_pitches = [
            p for p in all_pitches
            if (selected_type == "All Pitches" or command_metrics.pitch_type_label(p) == selected_type)
            and p.pitch_number in selected_numbers
        ]
        return target, filtered_pitches

    @output(id=controls_id)
    @render.ui
    def _controls():
        target, pitches = _target_and_pitches()
        if target is None:
            return None
        if not pitches:
            # The Bullpen Dashboard's session picker only lists sessions
            # that actually have >=1 CommandPitch row, so this shouldn't
            # happen in practice -- guarded anyway rather than assumed.
            return None

        db = get_session()
        try:
            active_bullpen = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.player), joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.bullpen_id == target["bullpen_id"])
                .first()
            )
        finally:
            db.close()
        if active_bullpen is None:
            return None

        player = active_bullpen.player
        player_name = f"{player.first_name} {player.last_name}" if player else "—"
        type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"

        type_options = ["All Pitches"]
        for p in pitches:
            label = command_metrics.pitch_type_label(p)
            if label not in type_options:
                type_options.append(label)
        pitch_number_choices = {str(p.pitch_number): f"#{p.pitch_number}" for p in pitches}

        return ui.div(
            ui.hr(),
            ui.h5(
                f"Command Tracking — {player_name} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}",
                style=f"color:{TEXT_CREAM};",
            ),
            ui.p(
                "Compares where each pitch was aimed to where it actually landed. A smaller miss means better command.",
                class_="text-muted small",
            ),
            ui.p(_band_legend(), class_="text-muted small"),
            ui.layout_columns(
                ui.input_select(type_filter_key, "Pitch Type", choices=type_options),
                ui.input_selectize(
                    select_key, "Pitches to Show",
                    choices=pitch_number_choices, selected=list(pitch_number_choices.keys()), multiple=True,
                    options={"plugins": ["remove_button"], "placeholder": "Select pitches..."},
                ),
                col_widths=[4, 8],
            ),
            ui.p(
                "Remove a pitch's chip (or clear the box and pick specific ones) to show only the pitches you choose.",
                class_="text-muted small",
            ),
            ui.output_ui(results_id),
        )

    @output(id=results_id)
    @render.ui
    def _results():
        target, pitches = _filtered()
        if target is None:
            return None
        if not pitches:
            return ui_helpers.empty_state("No pitches match the selected filters.")

        db = get_session()
        try:
            active_bullpen = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.player))
                .filter(BullpenSession.bullpen_id == target["bullpen_id"])
                .first()
            )
        finally:
            db.close()
        throws = active_bullpen.player.throws if active_bullpen and active_bullpen.player else None

        children = []

        scorecard = command_metrics.session_command_scorecard(pitches)
        if scorecard["located_pitches"] == 0:
            children.append(ui_helpers.empty_state("No pitches have an actual location recorded yet — this fills in once at least one does."))
            return ui.div(*children)

        children.append(ui_helpers.render_kpi_cards([
            {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
            {"label": "Avg Miss", "value": _fmt(scorecard["avg_miss_distance"], " in")},
            {"label": "Median Miss", "value": _fmt(scorecard["median_miss_distance"], " in")},
            {"label": "Danger-Adj. Miss", "value": _fmt(scorecard["avg_danger_adjusted_miss"], " in")},
            {"label": "Execution %", "value": _fmt(scorecard["execution_pct"], "%")},
            {"label": "Precision %", "value": _fmt(scorecard["precision_pct"], "%")},
            {"label": "Command Target %", "value": _fmt(scorecard["command_target_pct"], "%")},
            {"label": "Competitive %", "value": _fmt(scorecard["competitive_pct"], "%")},
            {"label": "Major Miss %", "value": _fmt(scorecard["major_miss_pct"], "%")},
        ]))
        children.append(ui.p(
            "Danger-Adj. Miss counts a miss toward the middle of the plate as worse than the same-size miss away from it — a pitch that drifts toward the heart of the plate is easier to hit.",
            class_="text-muted small",
        ))

        bias = command_metrics.miss_bias(pitches, throws)
        children.append(ui.p(
            f"Miss pattern: {_bias_label(bias)} — the direction this pitcher tends to miss on average, not any one pitch.",
            class_="text-muted small mt-2",
        ))

        by_type = command_metrics.command_by_pitch_type(pitches, throws)
        if len(by_type) > 1:
            rows = [{
                "Pitch Type": row["Pitch Type"],
                "Pitches": row["Pitches"],
                "Avg Miss (in)": row["Avg Miss"] if row["Avg Miss"] is not None else "—",
                "Danger-Adj. Miss (in)": row["Danger-Adj. Miss"] if row["Danger-Adj. Miss"] is not None else "—",
                "Execution %": row["Execution %"] if row["Execution %"] is not None else "—",
                "Precision %": row["Precision %"] if row["Precision %"] is not None else "—",
                "Command %": row["Command Target %"] if row["Command Target %"] is not None else "—",
                "Major Miss %": row["Major Miss %"] if row["Major Miss %"] is not None else "—",
                "Miss Pattern": _bias_label(row["Miss Bias"]),
            } for row in by_type]
            children.append(ui.h6("By pitch type", class_="mt-3"))
            children.append(ui_helpers.render_dict_table(rows))

        children.append(ui.h6("Pitch locations", class_="mt-3"))
        children.append(ui.p(
            "Every pitch, numbered, plotted on the real strike zone (the batters and home plate are just for "
            "visual reference). The hollow ring is where it was aimed, the filled dot is where it landed, and "
            "the dotted line connects the two — color shows pitch type. Use the filters above to narrow this "
            "down if it's crowded.",
            class_="text-muted small",
        ))
        children.append(output_widget(locations_widget_id))

        children.append(ui.h6("Command chart", class_="mt-3"))
        children.append(ui.p(
            "Each dot is one pitch, plotted by how far off target it landed — the crosshair marks the target itself, and the rings mark the Precise, Good, and Competitive bands.",
            class_="text-muted small",
        ))
        children.append(output_widget(chart_widget_id))

        return ui.div(*children)

    @output(id=locations_widget_id)
    @render_plotly
    def _pitch_locations_chart():
        target, pitches = _filtered()
        if target is None or not pitches:
            return None
        return command_charts.pitch_locations_chart(pitches)

    @output(id=chart_widget_id)
    @render_plotly
    def _command_chart():
        target, pitches = _filtered()
        if target is None or not pitches:
            return None
        return command_charts.command_chart(pitches)

    return ui.output_ui(controls_id)
