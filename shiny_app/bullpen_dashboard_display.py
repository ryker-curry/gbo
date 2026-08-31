"""
GBO -- Shiny port of the repo root's bullpen_dashboard_render.py (shared
Rapsodo Bullpen Dashboard rendering -- session header/KPI cards,
filters, pitch-type summary, and the four core charts). Same sharing
arrangement as the original: this is meant to be called from both
modules/player_bullpens.py (My Bullpens' inline "Bullpen Dashboard"
section, live as of this migration) and, later, modules/bullpen_
dashboard.py once the standalone coach-facing page is migrated (Task
#10) -- so both never drift apart, same reason the original pulled this
out of pages/bullpen_dashboard.py in the first place.

Deliberately named "bullpen_dashboard_display", not
"bullpen_dashboard_render" -- both this file's directory (shiny_app/)
and the repo root are on sys.path at once (see app.py's own path-setup
comment), and a module of the same name in two sys.path directories is
fragile: whichever one Python's import system resolves first (order can
vary by how the process was launched -- plain `shiny run`, `--reload`'s
file-watcher subprocess, an IDE's own run configuration, etc.) is the
one every `import bullpen_dashboard_render` in this codebase would
silently bind to, and if it's ever the wrong one, you get an
AttributeError for a function that "should" exist. Same reason
ui_components.py (root) has no same-named counterpart in shiny_app/ --
it's ui_helpers.py there -- and bucket_system_display.py (root) is
bucket_display.py here. This file follows that same established
naming convention instead of relying on sys.path ordering to always
break the tie the same way.

Reuses every pure computation/chart-building function unchanged:
analytics.bullpen_metrics (session_summary/pitch_type_summary/
individual_pitch_rows/filter_pitches/pitch_type_label) and
visualizations.bullpen_charts / visualizations.spin_axis_chart (all
return plain Plotly Figure objects, no Streamlit calls) -- exactly the
"reusable as-is" analytics engine the migration plan identified. Only
the rendering mechanism changes: Streamlit's imperative st.* calls
become a `register_bullpen_dashboard()` call that wires up two chained
`@render.ui` outputs (see below), and every chart embeds as a static PNG
via chart_helpers.fig_to_img (same technique as bucket_display.py --
none of these charts have on_select/click handling in the original
either, so nothing is lost).

Calling convention -- different from a plain function call, because
Shiny's output IDs have to be bound once at module-server-setup time,
not created ad hoc mid-render the way a Streamlit page can just call a
function and have it print itself:

    register_bullpen_dashboard(input, output, session, key_prefix, get_target)

Call this ONCE, unconditionally, from the caller's @module.server body
(same "mount once, no-op until there's something to show" convention as
every *_server() in this app). It registers two @output(id=...)-bound
render.ui functions under "{key_prefix}_controls"/"{key_prefix}_results"
and returns a UI fragment (just ui.output_ui(f"{key_prefix}_controls"))
to place in the caller's own render.ui tree at the point the dashboard
should appear.

`key_prefix` must be unique per simultaneous instance on a page -- e.g.
player_bullpens.py uses a single "bp" prefix (only ever one instance:
either a single session or the combined view, never both at once, per
Ryker's request for a single picker there); a future bullpen_dashboard.py
page showing "Overall Pitch Tracking" above a single-session drill-down
simultaneously would need two distinct prefixes, e.g. "dash_overall" and
"dash_session" -- mirrors the original's per-target-id key suffixing,
just done once per logical section instead of once per bullpen_id (this
Shiny version only ever renders the currently-selected target, not every
possible one at once, so there's no need to suffix by bullpen_id itself).

`get_target(input)` is called by both registered outputs every render
pass to resolve what to show; it must return one of:
    {"kind": "session", "bullpen_id": int}
    {"kind": "combined", "player": Player, "bullpen_ids": [int, ...]}
    None  -- nothing selected yet / not applicable; both outputs render
             nothing (via req(), so this doesn't turn into a friendly
             "no data" state, which is what a caller wants for "this
             section isn't showing at all right now" versus a real
             empty-data case).
It should do its own req()-gating on whatever upstream selection input
it depends on (e.g. a "View" picker) -- same convention as every other
downstream render.ui in this codebase that reads an upstream select.
"""

from sqlalchemy.orm import joinedload

from shiny import ui, render, req, reactive

from database import get_session
from models import BullpenSession, RapsodoPitch
from analytics.bullpen_metrics import (
    session_summary, pitch_type_summary, individual_pitch_rows, filter_pitches, pitch_type_label,
    release_trajectory_summary, fastball_trajectory_diagnostic, average_estimated_arm_angle,
)
from analytics.pitch_trajectory import calculate_estimated_arm_angle
from pitch_type_config import FASTBALL_TYPES
from visualizations.bullpen_charts import movement_chart, release_point_chart, location_chart, color_for_pitch_label
from visualizations.spin_axis_chart import individual_spin_axis_chart, average_spin_axis_chart
from visualizations.pitcher_graphic import pitcher_release_svg
from video_helpers import render_video_clip

import ui_helpers
import chart_helpers

GOLD = "#D4AF37"
TEXT_CREAM = "#FFFDE5"


def _pitch_type_legend(summary_rows, total_pitches):
    """Shiny port of bullpen_dashboard_style.py's pitch_type_legend --
    same colored-pill-per-pitch-type row, built as a plain <div> tree
    instead of an injected <style>/unsafe_allow_html markdown string."""
    if not summary_rows or not total_pitches:
        return None
    cells = []
    for row in summary_rows:
        label = row["Pitch Type"]
        usage_pct = round(100 * row["#"] / total_pitches, 0)
        avg_velo = f'{row["Avg Velo"]:.1f}' if row["Avg Velo"] is not None else "—"
        color = color_for_pitch_label(label)
        cells.append(ui.div(
            ui.div(style=f"width:28px; height:14px; border-radius:7px; background:{color}; margin:0 auto 6px auto;"),
            ui.div(label, style=f"color:{TEXT_CREAM}; font-weight:700; font-size:0.85rem;"),
            ui.div(f"{usage_pct:g}%", style=f"color:{GOLD}; font-size:0.8rem; margin-top:2px;"),
            ui.div(f"{avg_velo} mph", style="color:#B8B8B8; font-size:0.75rem;"),
            style="text-align:center; min-width:90px;",
        ))
    return ui.div(*cells, style="display:flex; justify-content:center; gap:22px; flex-wrap:wrap; margin:6px 0 14px 0;")


def _section_label(number, text):
    """Shiny port of bullpen_dashboard_style.py's section_label."""
    return ui.div(
        ui.div(style=f"width:32px; height:2px; background:{GOLD};"),
        ui.div(
            f"{number:02d} · {text}",
            style=f"color:{GOLD}; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em;",
        ),
        style="display:flex; align-items:center; gap:12px; margin: 8px 0 14px 0;",
    )


def _card(*children):
    """Bordered card panel -- Shiny equivalent of st.container(border=True)
    inside bullpen_dashboard_style.py's dark-card theme."""
    return ui.div(
        *children,
        style="background:#161010; border:1px solid rgba(212,175,55,0.28); border-radius:14px; padding:16px; margin-bottom:14px;",
    )


def _load_pitches(db, target):
    # joinedload(.player) added Aug 2026 (arm-angle/VAA feature): every
    # pitch in one target belongs to the same one pitcher, so eager-
    # loading it here means any downstream code can just read
    # pitches[0].player for that pitcher's height/throws with zero
    # extra queries -- cheaper than a second lookup, and avoids the
    # detached-object gotcha (touching a lazy relationship after
    # db.close(), a documented recurring bug class in this app).
    if target["kind"] == "session":
        return (
            db.query(RapsodoPitch)
            .options(joinedload(RapsodoPitch.pitch_type), joinedload(RapsodoPitch.player))
            .filter(RapsodoPitch.bullpen_id == target["bullpen_id"])
            .order_by(RapsodoPitch.pitch_number)
            .all()
        )
    return (
        db.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type), joinedload(RapsodoPitch.player))
        .filter(RapsodoPitch.bullpen_id.in_(target["bullpen_ids"]))
        .order_by(RapsodoPitch.pitch_date)
        .all()
    )


def register_bullpen_dashboard(input, output, session, key_prefix, get_target):
    controls_id = f"{key_prefix}_controls"
    results_id = f"{key_prefix}_results"

    type_filter_key = f"{key_prefix}_pitch_type_filter"
    range_key = f"{key_prefix}_pitch_range"
    shading_key = f"{key_prefix}_min_shading"
    location_mode_key = f"{key_prefix}_location_mode"
    spin_axis_mode_key = f"{key_prefix}_spin_axis_mode"
    show_charts_key = f"{key_prefix}_show_charts_btn"

    # Each of the four chart "slots" below is its OWN output id, not one
    # combined block -- Ryker's call, after "Show charts" still took ~30
    # seconds with nothing visible the whole time on Connect Cloud's
    # shared CPU. Splitting into independent outputs doesn't reduce the
    # total kaleido render time, but Shiny sends each output to the
    # browser as soon as THAT one finishes rather than waiting for every
    # chart to be done -- so charts stream in one at a time (movement
    # chart first, typically within a few seconds) instead of one long
    # blank wait followed by everything appearing at once.
    movement_chart_id = f"{key_prefix}_chart_movement"
    release_chart_id = f"{key_prefix}_chart_release"
    location_chart_id = f"{key_prefix}_chart_location"
    spin_chart_id = f"{key_prefix}_chart_spin"

    # The four charts below are real Plotly-to-PNG (kaleido) renders --
    # unlike bucket_display.py's rings/bars, these are genuine data
    # visualizations (scatter/heatmap positions), not something CSS can
    # fake, so they can't be converted away the way Assessments' charts
    # were. Rendering all four synchronously on every single pitcher/
    # session switch was slow enough to occasionally blow past the
    # browser's websocket timeout ("Disconnected from the server") when
    # switching targets in the live app. _charts_shown_for tracks which
    # target the charts were last explicitly requested for (via the
    # "Show charts" button below); switching to a different target
    # doesn't match, so _results() shows just the button again instead
    # of auto-rendering four fresh chart images before the page can
    # respond to anything else.
    _charts_shown_for = reactive.Value(None)
    # Backs chart_helpers.render_chart_async -- see that function's
    # docstring for the actual two-tick, no-threading mechanism (an
    # earlier version of this comment described a background-thread
    # approach; that was replaced before ship, this wasn't updated
    # until now). Whatever the mechanism, the effect is the same: a
    # placeholder reaches the browser immediately instead of the render
    # just silently blocking (Ryker's report: charts felt "frozen" for
    # ~30s with nothing visible in between).
    _chart_cache = reactive.Value({})
    # Separate cache for _controls() below (Aug 2026, same fix applied
    # one level up): picking a pitcher/session with a large pitch
    # history runs its own real DB query (_load_pitches) before any of
    # the KPI cards or "Show charts" button can appear -- previously
    # that query ran synchronously with nothing on screen in the
    # meantime, the same "frozen" complaint the charts themselves used
    # to have, just one step earlier in the flow. A distinct cache
    # (not reused from _chart_cache) since the keys are shaped
    # differently and there's no reason for a chart re-render to
    # invalidate the session header or vice versa. Still used as
    # render_chart_async's required cache arg even now that _controls
    # calls it with sync=True (see below) -- sync=True returns before
    # ever touching this cache, so it's just unused dead weight in that
    # path today, but left in place rather than restructuring the
    # signature, in case a future slow-session case brings the
    # placeholder back for this output specifically.
    _controls_cache = reactive.Value({})

    def _target_key(target):
        if target["kind"] == "session":
            return ("session", target["bullpen_id"])
        return ("combined", tuple(sorted(target["bullpen_ids"])))

    @reactive.effect
    @reactive.event(input[show_charts_key])
    def _on_show_charts():
        t, _ = _target_and_pitches()
        if t is not None:
            _charts_shown_for.set(_target_key(t))

    @reactive.calc
    def _target_and_pitches():
        """Both _controls and _results below need the same (target,
        pitches) pair -- previously each independently called
        get_target(input) and re-ran _load_pitches' database query, so
        picking a session cost that query twice. Memoized here so it
        only runs once per actual change to the target/upstream
        selection, same invalidation rule as everywhere else in this
        app that uses @reactive.calc for this pattern."""
        target = get_target(input)
        if target is None:
            return None, None
        db = get_session()
        try:
            return target, _load_pitches(db, target)
        finally:
            db.close()

    @reactive.calc
    def _filtered():
        """(target, filtered_pitches) -- shared by _results and all four
        chart outputs below, so the pitch-type/range filtering only
        happens once per actual change instead of once per output."""
        req(type_filter_key in input)
        req(range_key in input)
        target, all_pitches = _target_and_pitches()
        if target is None:
            return None, None
        selected_type = input[type_filter_key]()
        pitch_range = input[range_key]()
        filtered_pitches = filter_pitches(
            all_pitches,
            pitch_type_name=None if selected_type == "All Pitches" else selected_type,
            pitch_number_range=pitch_range,
        )
        return target, filtered_pitches

    def _charts_ready(target, filtered_pitches):
        return target is not None and filtered_pitches and _charts_shown_for() == _target_key(target)

    @output(id=controls_id)
    @render.ui
    def _controls():
        # get_target(input) alone is cheap (reads already-resolved
        # inputs, at most one single-row Player lookup) -- it's safe to
        # call directly on tick 1 just to know whether there's a target
        # at all and to build the cache key. The actual pitch-list load
        # (_target_and_pitches, which _load_pitches makes a real query
        # for -- worse the larger the session/combined view) is what
        # needs to be deferred to tick 2, inside _build below, so tick
        # 1 can return the loading placeholder immediately instead of
        # blocking on that query first.
        target = get_target(input)
        if target is None:
            return None

        def _build():
            _, pitches = _target_and_pitches()
            if pitches is None:
                return None
            return _build_controls(target, pitches)

        key = (controls_id, _target_key(target))
        # sync=True (Aug 2026, Ryker: this output was the one chart_
        # helpers.render_chart_async call site deliberately left on the
        # two-tick/invalidate_later path when the other 4 chart outputs
        # on this page got the same fix -- reasoning at the time was
        # that this one's builder does a real DB query
        # (_target_and_pitches -> _load_pitches), unlike the charts,
        # which by then were fast in-process plotly.js renders with
        # nothing left for the placeholder to usefully cover. Ryker
        # confirmed (screenshot) the "output is in an unexpected state"
        # warning was STILL showing up specifically on this output after
        # that first round -- i.e. the invalidate_later(0.1) timer race
        # described in render_chart_async's docstring was never actually
        # about kaleido/chart-render time, it's a race against Shiny's
        # own input-driven invalidation that any two-tick output can hit,
        # DB query or not. Since switching pitcher/session already
        # re-triggers this output through the normal reactive graph,
        # dropping the extra timer-based tick removes the race without
        # losing the "show something on pitcher switch" behavior. Trade-
        # off: a genuinely large pitch history's DB query now blocks
        # this output with no placeholder in between, same as the 4
        # chart outputs already accepted -- revisit with a real debounce
        # (not another invalidate_later) if that turns out to matter in
        # practice.
        return chart_helpers.render_chart_async(_controls_cache, key, _build, label="Loading session data…", sync=True)

    def _build_controls(target, pitches):
        db = get_session()
        try:
            summary = session_summary(pitches)
            type_options = ["All Pitches"] + summary["pitch_type_names"]
            max_pitch_number = max((p.pitch_number for p in pitches), default=1)

            header = []
            if target["kind"] == "session":
                active_bullpen = (
                    db.query(BullpenSession)
                    .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
                    .filter(BullpenSession.bullpen_id == target["bullpen_id"])
                    .first()
                )
                if active_bullpen is None:
                    return ui.p("That session either doesn't exist, has no Rapsodo data yet, or you don't have access to it.", class_="text-warning")
                player = active_bullpen.player
                player_name = f"{player.first_name} {player.last_name}" if player else "—"
                type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"
                header.append(ui.h5(f"{player_name} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}", style=f"color:{TEXT_CREAM};"))
                if active_bullpen.overall_notes:
                    header.append(ui.p(active_bullpen.overall_notes, class_="text-muted small"))
                if active_bullpen.video_url:
                    # Aug 2026 fix: this was a raw <video> tag, which can
                    # only ever play a direct file URL -- session video is
                    # now saved as a pasted Google Drive link (see Bullpen
                    # Tracking's "Session video" control), which needs
                    # Drive's iframe embed instead. render_video_clip()
                    # (shared with video_import.py/hitter_tracking.py)
                    # handles both correctly, so this silently worked for
                    # no one until now despite the field having a value.
                    header.append(ui.accordion(ui.accordion_panel("Session video", render_video_clip(active_bullpen.video_url)), open=False, id=None))
            else:
                player = target["player"]
                header.append(ui.h5(f"Overall Pitch Tracking — {player.first_name} {player.last_name}", style=f"color:{TEXT_CREAM};"))

            kpi_cards = [
                {"label": "Total Pitches", "value": str(summary["total_pitches"])},
                {"label": "Pitch Types", "value": str(len(summary["pitch_type_names"]))},
                {"label": "Avg Velocity", "value": f"{summary['avg_velocity']:.1f} mph" if summary["avg_velocity"] is not None else "—"},
                {"label": "Max Velocity", "value": f"{summary['max_velocity']:.1f} mph" if summary["max_velocity"] is not None else "—"} if target["kind"] == "session" else {"label": "Sessions", "value": str(len(target["bullpen_ids"]))},
                {"label": "Avg Spin Rate", "value": f"{summary['avg_spin_rate']:.0f} rpm" if summary["avg_spin_rate"] is not None else "—"},
            ]
            # Aug 2026 addition: Estimated Arm Angle KPI tile, geometric
            # estimate from this pitcher's existing Player.height_in (see
            # analytics/pitch_trajectory.py) -- never a new height input,
            # never asked for again. "N/A" (with the specific missing
            # piece) rather than a fabricated number when height/release
            # data isn't there yet, same as every other KPI's "—" for no
            # data, just with a more specific reason attached as a tooltip.
            if player is not None and pitches:
                arm_angle_summary = release_trajectory_summary(pitches, player)
                kpi_cards.append({"label": "Est. Arm Angle", "value": arm_angle_summary["Average Estimated Arm Angle"]})
            header.append(ui_helpers.render_kpi_cards(kpi_cards))
            if player is not None and player.height_in is None and pitches:
                # Specific reason for the "N/A" above -- a plain caption
                # rather than overloading render_kpi_cards' delta field
                # (which always prepends an up/down arrow, wrong here).
                header.append(ui.p("Estimated Arm Angle needs this pitcher's height — add it on the Players page.", class_="text-muted small"))

            return ui.div(
                *header,
                _section_label(1, "Filters"),
                ui.layout_columns(
                    ui.input_select(type_filter_key, "Pitch Type", choices=type_options),
                    ui.input_slider(range_key, "Pitch Number Range", min=1, max=max_pitch_number, value=(1, max_pitch_number)),
                    col_widths=[4, 8],
                ),
                ui.output_ui(results_id),
            )
        finally:
            db.close()

    @output(id=results_id)
    @render.ui
    def _results():
        target, filtered_pitches = _filtered()
        if target is None:
            return None
        if not filtered_pitches:
            return ui_helpers.empty_state("No pitches match the selected filters.")

        # player, Aug 2026 addition: every pitch in filtered_pitches
        # belongs to the same one pitcher, and RapsodoPitch.player is
        # eager-loaded by _load_pitches -- reading it off the first
        # pitch costs nothing extra and needs no signature changes to
        # _target_and_pitches/_filtered above.
        player = filtered_pitches[0].player if filtered_pitches else None

        summary_rows = pitch_type_summary(filtered_pitches, player=player)
        pitches_by_type = {}
        for p in filtered_pitches:
            pitches_by_type.setdefault(pitch_type_label(p), []).append(p)

        summary_section = _card(
            _section_label(2, "Pitch Summary"),
            ui_helpers.render_dict_table(summary_rows),
            ui.p("Expand a pitch type below to see every individual pitch. \"Est. VAA\"/\"Est. Arm Angle\" are geometric/trajectory ESTIMATES, not direct Rapsodo measurements — see the note below the charts.", class_="text-muted small"),
            ui.accordion(*[
                ui.accordion_panel(f"{row['Pitch Type']} ({row['#']} pitches)", ui_helpers.render_dict_table(individual_pitch_rows(pitches_by_type[row["Pitch Type"]], player=player)))
                for row in summary_rows
            ], open=False, id=None),
        )

        # Release / Trajectory Summary (spec Section 22) + one Fastball
        # Trajectory diagnostic card per fastball-family type actually
        # present (Section 18) -- both need `player` for Est. Arm Angle,
        # so both render nothing (not an empty card) when there's no
        # linked player.
        trajectory_cards = []
        if player is not None:
            rt_summary = release_trajectory_summary(filtered_pitches, player)
            per_type_rows = pitch_type_summary(filtered_pitches, player=player)
            angle_by_type_block = None
            if per_type_rows:
                # Aug 2026, Ryker: Release Angle shouldn't sit crammed
                # together with Est. Arm Angle here -- Release Angle now
                # lives in the pitch-type legend below the charts
                # (alongside usage % and avg velo, see _pitch_type_legend),
                # so this dedicated section stays Arm-Angle-only, per the
                # earlier "its own separate line showing that arm angle" ask.
                angle_by_type_block = ui.div(
                    ui.div(
                        "ESTIMATED ARM ANGLE BY PITCH TYPE",
                        style=f"color:{GOLD}; font-size:0.72rem; font-weight:700; text-transform:uppercase; letter-spacing:0.1em; margin:14px 0 6px 0;",
                    ),
                    *[
                        ui.div(
                            ui.div(style=f"width:10px; height:10px; border-radius:5px; background:{color_for_pitch_label(row['Pitch Type'])}; flex-shrink:0;"),
                            ui.div(row["Pitch Type"], style=f"color:{TEXT_CREAM}; font-weight:600; min-width:110px;"),
                            ui.div(f"Est. Arm Angle: {row['Est. Arm Angle']}" if row.get("Est. Arm Angle") else "Est. Arm Angle: N/A", class_="text-muted small"),
                            style="display:flex; align-items:center; gap:10px; padding:6px 0; border-top:1px solid rgba(212,175,55,0.12);",
                        )
                        for row in per_type_rows
                    ],
                )
            trajectory_cards.append(_card(
                _section_label(3, "Release / Trajectory Summary"),
                ui.div(*[
                    ui.div(ui.div(label, class_="text-muted small"), ui.div(value, style=f"color:{TEXT_CREAM}; font-weight:600;"))
                    for label, value in rt_summary.items()
                ], style="display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px;"),
                *([angle_by_type_block] if angle_by_type_block is not None else []),
                ui.p(
                    "Estimated Arm Angle is a geometric estimate from release point and estimated shoulder height "
                    "(70% of this pitcher's Body Comp/Players-page height) — not a direct biomechanical measurement. "
                    "Estimated VAA/HAA are calculated from release + actual plate-crossing data because Rapsodo's own "
                    "exported VAA/HAA columns are blank in these files — not a directly measured Rapsodo VAA/HAA.",
                    class_="text-muted small", style="margin-top:10px;",
                ),
            ))
            present_fastball_types = [t for t in FASTBALL_TYPES if any(pitch_type_label(p) == t for p in filtered_pitches)]
            for canonical_type in present_fastball_types:
                diag = fastball_trajectory_diagnostic(filtered_pitches, player, canonical_pitch_type=canonical_type)
                if diag is None:
                    continue
                trajectory_cards.append(_card(
                    ui.div(
                        ui.div(style=f"width:32px; height:2px; background:{GOLD};"),
                        ui.div(
                            f"FASTBALL TRAJECTORY · {canonical_type} (n={diag['n']})",
                            style=f"color:{GOLD}; font-size:0.8rem; font-weight:700; text-transform:uppercase; letter-spacing:0.14em;",
                        ),
                        style="display:flex; align-items:center; gap:12px; margin: 8px 0 14px 0;",
                    ),
                    ui.div(
                        ui.div(f"Velocity: {diag['Velocity']:.1f} mph" if diag["Velocity"] is not None else "Velocity: —"),
                        ui.div(f"VB: {diag['VB']:.1f}\"" if diag["VB"] is not None else "VB: —"),
                        ui.div(f"VAA: {diag['VAA']}"),
                        ui.div(f"Release Height: {diag['Release Height']:.2f} ft" if diag["Release Height"] is not None else "Release Height: —"),
                        ui.div(f"Extension: {diag['Extension']:.2f} ft" if diag["Extension"] is not None else "Extension: —"),
                        ui.div(f"Arm Angle: {diag['Arm Angle']}"),
                        style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; margin-bottom:10px;",
                    ),
                    ui.div(
                        "Trajectory: ",
                        ui.tags.b(diag["Trajectory"], style=f"color:{GOLD};"),
                        style=f"color:{TEXT_CREAM};",
                    ),
                ))

        if _charts_shown_for() != _target_key(target):
            return ui.div(
                summary_section,
                *trajectory_cards,
                ui.input_action_button(show_charts_key, "Show charts", class_="btn-outline-secondary mt-2"),
            )

        # Chart images themselves are NOT built here -- each is its own
        # output (registered below) so they can stream in independently
        # instead of this one output blocking until all four are done.
        charts_section = _card(
            _section_label(4, "Charts"),  # was 3 -- bumped to make room for section 3, Release / Trajectory Summary, above
            ui.input_slider(shading_key, "Minimum pitches to shade a pitch type's cluster", min=1, max=10, value=2),
            ui.output_ui(movement_chart_id),
            ui.p("Centered on release point; color-coded by pitch type.", class_="text-muted small"),
            ui.p("Left: every pitch's release point. Right: each pitch type's average release point, illustrated.", class_="text-muted small"),
            ui.output_ui(release_chart_id),
            ui.input_radio_buttons(location_mode_key, "Location view", ["Heat Map", "Individual Pitches"], inline=True),
            ui.output_ui(location_chart_id),
            ui.input_radio_buttons(spin_axis_mode_key, "Spin axis view", ["Average by Pitch Type", "Individual Pitches"], inline=True),
            ui.output_ui(spin_chart_id),
        )

        return ui.div(summary_section, *trajectory_cards, charts_section)

    @output(id=movement_chart_id)
    @render.ui
    def _chart_movement():
        target, filtered_pitches = _filtered()
        if not _charts_ready(target, filtered_pitches):
            return None
        min_shading = input[shading_key]() if shading_key in input else 2
        player = filtered_pitches[0].player if filtered_pitches else None
        throws = player.throws if player is not None else None

        # One Estimated Arm Angle ray per pitch type (Aug 2026, Ryker:
        # "i want one for each pitch [type]... color of the line to
        # match the color for that pitch in the charts") -- grouped and
        # colored the same way the Release Point silhouette's per-type
        # markers already group/color, so every panel agrees on both
        # the grouping and the color for a given type. Types with no
        # computable angle (e.g. no release-point data yet) are simply
        # left out rather than shown as a fabricated 0.
        type_groups = {}
        type_order = []
        for p in filtered_pitches:
            label = pitch_type_label(p)
            if label not in type_groups:
                type_groups[label] = []
                type_order.append(label)
            type_groups[label].append(p)

        per_type_angles = []  # (label, color, angle_degrees, n) -- for the caption
        for label in type_order:
            group = type_groups[label]
            angle, n = average_estimated_arm_angle(group, player)
            if angle is not None:
                per_type_angles.append((label, color_for_pitch_label(label), angle, n))

        arm_angles_by_type = [(label, color, angle) for label, color, angle, n in per_type_angles]

        def _build():
            movement_fig = movement_chart(
                filtered_pitches, min_pitches_for_shading=min_shading,
                arm_angles_by_type=arm_angles_by_type, throws=throws,
            )
            children = [chart_helpers.fig_to_img(movement_fig, width=700, height=420)]
            summary_rows = pitch_type_summary(filtered_pitches)
            legend = _pitch_type_legend(summary_rows, len(filtered_pitches))
            if legend is not None:
                children.append(legend)
            if per_type_angles:
                angle_items = [
                    ui.div(
                        ui.div(style=f"width:10px; height:10px; border-radius:5px; background:{color}; display:inline-block; margin-right:5px;"),
                        f"{label}: {round(angle)}° (n={n})",
                        style="display:inline-flex; align-items:center; color:#B8B8B8; font-size:0.78rem; margin:2px 8px;",
                    )
                    for label, color, angle, n in per_type_angles
                ]
                children.append(ui.div(*angle_items, style="display:flex; flex-wrap:wrap; justify-content:center; margin-top:6px;"))
            elif player is not None and player.height_in is None:
                children.append(ui.p("Estimated Arm Angle needs this pitcher's height — add it on the Players page.", class_="text-muted small", style="text-align:center;"))
            return ui.div(*children)

        key = (movement_chart_id, _target_key(target), min_shading, tuple(arm_angles_by_type), throws)
        return chart_helpers.render_chart_async(_chart_cache, key, _build, sync=True)

    @output(id=release_chart_id)
    @render.ui
    def _chart_release():
        target, filtered_pitches = _filtered()
        if not _charts_ready(target, filtered_pitches):
            return None
        player = filtered_pitches[0].player if filtered_pitches else None

        def _build():
            # One marker + "arm" line per PITCH TYPE (Aug 2026, second
            # revision -- Ryker: average release point per pitch type,
            # not one dot per individual pitch). Grouped and colored the
            # same way release_point_chart's own "average" mode already
            # groups/colors its dots, so the two panels always agree.
            type_groups = {}
            type_order = []
            for p in filtered_pitches:
                label = pitch_type_label(p)
                if label not in type_groups:
                    type_groups[label] = []
                    type_order.append(label)
                type_groups[label].append(p)

            releases = []
            for label in type_order:
                group = type_groups[label]
                heights = [float(p.release_height) for p in group if p.release_height is not None]
                sides = [float(p.release_side) for p in group if p.release_side is not None]
                if not heights or not sides:
                    continue
                avg_h = sum(heights) / len(heights)
                avg_s = sum(sides) / len(sides)
                releases.append({
                    "label": label,
                    "color": color_for_pitch_label(label),
                    # pitcher_release_svg wants catcher-view side_ft (+ =
                    # catcher's right); GBO's release_side is raw Rapsodo
                    # (pitcher-view, + = pitcher's own right/throwing
                    # side -- see rapsodo_conventions.py), so negate here,
                    # same sign flip already established for plate_x
                    # elsewhere (Aug 31 2026 convention fix).
                    "side_ft": -avg_s,
                    "height_ft": avg_h,
                    "count": len(group),
                })

            player_height_in = float(player.height_in) if player is not None and player.height_in is not None else None
            throws = player.throws if player is not None else None

            # New Aug 31 2026 (round 2) release-point graphic from
            # Ryker's web designer -- replaces the earlier hand-built
            # release_silhouette.py stick/solid-shaded illustration.
            # Its own legend (colored dot + label + usage %) is built
            # into the SVG, so no separate legend_items block is needed
            # here anymore.
            silhouette_children = [ui.HTML(pitcher_release_svg(releases, throws=throws or "R", height_in=player_height_in or 73))]
            if player is not None and player.height_in is None:
                silhouette_children.append(ui.p(
                    "Using an average height -- add this pitcher's real height on the Players page for a more accurate figure.",
                    class_="text-muted small", style="text-align:center;",
                ))
            silhouette_panel = ui.div(
                ui.p("Release Point", style=f"color:{TEXT_CREAM}; font-weight:700; text-align:center; margin-bottom:4px;"),
                *silhouette_children,
                style="display:flex; flex-direction:column; align-items:center; justify-content:flex-start; height:100%;",
            )

            return ui.layout_columns(
                chart_helpers.fig_to_img(release_point_chart(filtered_pitches, mode="individual"), width=450, height=420),
                silhouette_panel,
                col_widths=[6, 6],
            )

        key = (release_chart_id, _target_key(target))
        return chart_helpers.render_chart_async(_chart_cache, key, _build, sync=True)

    @output(id=location_chart_id)
    @render.ui
    def _chart_location():
        target, filtered_pitches = _filtered()
        if not _charts_ready(target, filtered_pitches):
            return None
        location_mode = input[location_mode_key]() if location_mode_key in input else "Heat Map"

        def _build():
            return chart_helpers.fig_to_img(
                location_chart(filtered_pitches, mode="heatmap" if location_mode == "Heat Map" else "individual"), width=700, height=480,
            )

        key = (location_chart_id, _target_key(target), location_mode)
        return chart_helpers.render_chart_async(_chart_cache, key, _build, sync=True)

    @output(id=spin_chart_id)
    @render.ui
    def _chart_spin():
        target, filtered_pitches = _filtered()
        if not _charts_ready(target, filtered_pitches):
            return None
        selected_type = input[type_filter_key]() if type_filter_key in input else "All Pitches"
        spin_axis_mode = input[spin_axis_mode_key]() if spin_axis_mode_key in input else "Average by Pitch Type"

        def _build():
            children = []
            if spin_axis_mode == "Average by Pitch Type":
                children.append(chart_helpers.fig_to_img(average_spin_axis_chart(filtered_pitches), width=500, height=420))
            else:
                individual_type_filter = None if selected_type == "All Pitches" else selected_type
                if selected_type == "All Pitches":
                    children.append(ui.p("Showing every pitch type at once gets busy -- filter to one type above for a cleaner view.", class_="text-muted small"))
                children.append(chart_helpers.fig_to_img(individual_spin_axis_chart(filtered_pitches, pitch_type_filter=individual_type_filter), width=500, height=420))
            return ui.div(*children)

        key = (spin_chart_id, _target_key(target), selected_type, spin_axis_mode)
        return chart_helpers.render_chart_async(_chart_cache, key, _build, sync=True)

    return ui.output_ui(controls_id)