"""
GBO -- Pitcher Game Report module.

Direct port of pages/pitcher_game_report.py -- single-game box score +
pitch-type breakdown (Usage/Strike/CSW/Whiff/Chase/Putaway/GB-FB-LD%,
overall and by opponent batter handedness) plus Command Precision and
Attack Zones, all from the exact same game_stats.py/pitch_location_stats.py
functions Analytics/My Stats use, just scoped to one game_id instead of
season/all-time aggregate.

Two-step picker (Game, then Pitcher) -- Game lives in its own render.ui
block; Pitcher (which needs to know who actually threw in that game)
lives in a second block reading it via req("game_select" in input); the
report body lives in a third block reading both. Same
ordering-hazard-safe chain as assessments.py's player/category/
pitch-type-filter sequence.

st.tabs(["All Batters", "vs RHH", "vs LHH"]) -> ui.navset_tab -- the one
new translation-table entry this batch introduces that hasn't come up
in an earlier module yet.
"""

from shiny import module, ui, render, reactive, req
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload
import plotly.graph_objects as go

from database import get_session
from models import Player, Game, GamePitch, RapsodoPitch, User, OpponentPlayer
from game_stats import (
    get_pitching_pitches, compute_pitching_line, compute_pitch_type_breakdown,
    get_forced_half_inning_end_runs, get_runner_event_outs, get_batter_hands,
)
from pitch_location_stats import compute_command_precision, compute_attack_zones
# Target-radius bands (Precision/Command/Competitive/Major Miss) and the
# concentric-ring chart, reused as-is from Command Tracker rather than a
# second implementation -- game_pitches_command_view() adapts a game
# pitcher's own GamePitch rows (intended_plate_x/z/actual_plate_x/z) into
# the same duck-typed shape session_command_scorecard/command_by_pitch_type
# and command_chart() already expect, with NO CommandPitch schema change
# or mirrored rows (see that function's own docstring for why). Existing
# Command Precision/Attack Zones above are untouched, computed the way
# they always have been -- this is a new, additional section, not a
# replacement.
from analytics import command_metrics, profile_queries
from analytics.pitcher_game_report import compute_staff_game_totals, FPS_GOAL_PCT, SECONDARY_STRIKE_GOAL_PCT
from analytics.pitch_grading import stuff_plus, arsenal_summary, location_plus, MIN_BASELINE_PITCHES
from analytics.bullpen_metrics import (
    average_estimated_arm_angle, pitch_type_label,
    _pitch_level_vaa, _pitch_level_haa, _avg_pitch_level,
)
import command_config
from visualizations import command_charts
from visualizations.bullpen_charts import movement_chart, color_for_pitch_label
from visualizations.pitcher_graphic import pitcher_release_svg
from visualizations.attack_zones_chart import attack_zones_figure as _attack_zones_figure
from visualizations.chart_theme import apply_gbo_theme, GRID_GRAY, MUTED_GRAY, TEXT_CREAM, GOLD, CRIMSON
from visualizations.hitter_graphic import home_plate_shape, hitter_images

import strike_zone
import chart_helpers
import ui_helpers
import format_helpers
from format_helpers import (
    format_pct as _fmt_pct,
    format_num as _fmt,
    opponent_display_name as _opponent_display_name,
    game_label as _game_label,
)


def _fmt_grade(value):
    return f"{value:.1f}" if value is not None else "—"


def _pitch_type_breakdown_with_stuff(pitches_subset, rap_by_gp, stuff_baselines):
    """compute_pitch_type_breakdown()'s rows, with a "Stuff+"/"Stuff+
    Reliable" column merged on by matching "Pitch Type" -- the Pitch
    Frequency by handedness panel from STUFF-LOCATION-PITCHING-PLUS-
    PLAN.md section 10, minus the Location+/Pitching+ half (Attack
    Zones below already covers location; Stuff+ is what's genuinely
    new here). rap_by_gp/stuff_baselines are precomputed once by the
    caller (analytics/profile_queries.py, same team-wide baseline
    Pitcher Profile's Arsenal table uses) and reused across all three
    tabs rather than requeried per tab.

    Reuses pitch_grading.arsenal_summary() for the per-type average +
    MIN_BASELINE_PITCHES reliability flag instead of a second rollup
    implementation -- same "n pitches of that type in THIS window"
    floor as the Arsenal table, which for a single outing will read
    "No" for most types (a start rarely throws 20+ of a given
    secondary pitch) -- shown anyway, not hidden, same small-sample
    philosophy as everywhere else this scale is used."""
    base_rows = compute_pitch_type_breakdown(pitches_subset)

    pitch_type_grades = {}
    for p in pitches_subset:
        if p.pitch_type is None:
            continue
        rap = rap_by_gp.get(p.game_pitch_id)
        if rap is None:
            continue
        label = p.pitch_type.type_name
        s_val = stuff_plus(rap, stuff_baselines.get(label))
        if s_val is None:
            continue
        pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
        pitch_type_grades[label]["n"] += 1
        pitch_type_grades[label]["stuff_plus"].append(s_val)

    stuff_by_label = {row["Pitch Type"]: (row["Stuff+"], row["Reliable"]) for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}
    all_stuff_vals = [v for g in pitch_type_grades.values() for v in g["stuff_plus"]]
    total_stuff = round(sum(all_stuff_vals) / len(all_stuff_vals), 1) if all_stuff_vals else None
    total_reliable = len(all_stuff_vals) >= MIN_BASELINE_PITCHES

    out_rows = []
    for row in base_rows:
        row = dict(row)
        if row["Pitch Type"] == "Total":
            s_val, reliable = total_stuff, total_reliable
        else:
            s_val, reliable = stuff_by_label.get(row["Pitch Type"], (None, False))
        row["Stuff+"] = _fmt_grade(s_val)
        row["Stuff+ Reliable"] = "Yes" if (s_val is not None and reliable) else "No"
        out_rows.append(row)
    return out_rows


def _pitch_shape_rows(pitches, rap_by_gp, stuff_baselines, pitcher):
    """Physical pitch-shape table for the Pitch Shape (Rapsodo) section
    (Ryker's Pitch Profiler-style reference, Sept 2026): Velocity/Spin
    Rate/IVB/HB/VAA/HAA/vRel/hRel/Ext/Arm deg, plus Stuff+ and Whiff %,
    one row per pitch type actually thrown -- grouped by the coach's own
    charted GamePitch.pitch_type (not Rapsodo's independent auto-
    classification), same convention as _pitch_type_breakdown_with_stuff
    above, since Usage %/Whiff % are GamePitch-outcome facts that need
    to agree with the rest of the page. Physical columns only average
    the subset of that type's pitches with a Rapsodo reading linked
    (rap_by_gp) -- a charted type with no Rapsodo match yet shows
    Usage %/Whiff % from the charted count and "--" for every physical
    column, same "shown anyway" philosophy as elsewhere, rather than
    being dropped from the table.

    No separate Barrel % column -- GBO doesn't track batted-ball
    exit velocity/launch angle, so there's no GBO equivalent to
    substitute (Ryker's own call: substitute a real GBO equivalent
    where one exists, skip what doesn't rather than fabricating it).

    Stuff+ reuses pitch_grading.stuff_plus/arsenal_summary against the
    same team-wide baseline as the Arsenal table and Pitch Type
    Breakdown above -- not a second Stuff+ computation. Small-sample
    reality: MIN_BASELINE_PITCHES is 20, and a single outing rarely
    throws 20+ of a secondary pitch, so most Stuff+ values here will be
    on a thin sample -- shown anyway rather than hidden, with a caption
    below the table flagging the floor, same convention as
    _pitch_type_breakdown_with_stuff's own "Reliable" column."""
    base_rows = {row["Pitch Type"]: row for row in compute_pitch_type_breakdown(pitches) if row["Pitch Type"] != "Total"}

    type_order = []
    rapsodo_groups = {}
    for p in pitches:
        if p.pitch_type is None:
            continue
        label = p.pitch_type.type_name
        if label not in rapsodo_groups:
            rapsodo_groups[label] = []
            type_order.append(label)
        rap = rap_by_gp.get(p.game_pitch_id)
        if rap is not None:
            rapsodo_groups[label].append(rap)

    pitch_type_grades = {}
    for label, raps in rapsodo_groups.items():
        for rap in raps:
            s_val = stuff_plus(rap, stuff_baselines.get(label))
            if s_val is None:
                continue
            grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
            grp["n"] += 1
            grp["stuff_plus"].append(s_val)
    stuff_by_label = {row["Pitch Type"]: row["Stuff+"] for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}

    def _avg_field(raps, field, decimals=1):
        vals = [float(getattr(r, field)) for r in raps if getattr(r, field) is not None]
        return round(sum(vals) / len(vals), decimals) if vals else None

    def _d(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "—"

    rows = []
    for label in type_order:
        raps = rapsodo_groups[label]
        base = base_rows.get(label, {})
        arm_angle, _n = average_estimated_arm_angle(raps, pitcher)
        rows.append({
            "Pitch Type": label,
            "% Thrown": _d(base.get("Pitch Usage %"), "%"),
            "Velocity": _d(_avg_field(raps, "velocity"), " mph"),
            "Spin Rate": _d(_avg_field(raps, "total_spin", 0), " rpm"),
            "IVB": _d(_avg_field(raps, "vb_spin"), '"'),
            "HB": _d(_avg_field(raps, "hb_trajectory"), '"'),
            "VAA": _d(_avg_pitch_level([_pitch_level_vaa(r)["value_degrees"] for r in raps])[0], "° (est.)"),
            "HAA": _d(_avg_pitch_level([_pitch_level_haa(r)["value_degrees"] for r in raps])[0], "° (est.)"),
            "vRel": _d(_avg_field(raps, "release_height"), "'"),
            "hRel": _d(_avg_field(raps, "release_side"), "'"),
            "Ext": _d(_avg_field(raps, "release_extension"), "'"),
            "Arm°": _d(round(arm_angle) if arm_angle is not None else None, "°"),
            "Stuff+": _d(stuff_by_label.get(label)),
            "Whiff %": _d(base.get("Whiff %"), "%"),
            "SwStr %": _d(base.get("SwStr %"), "%"),
        })
    return rows


def _pitch_location_figure(intended_x, intended_z, actual_x, actual_z, color, batter_hand=None):
    """Compact single-pitch intended-vs-actual location figure for the
    Pitch-by-Pitch detail card (Ryker, Sept 2026: "add like how we
    have in [Command Tracking] where we can see intended location and
    then actual location and it shows the distance between with a
    line"). Mirrors visualizations/command_charts.pitch_locations_chart's
    established styling -- dotted gray connecting line drawn first
    (layer="below"), hollow-ring marker for intended, filled marker
    for actual, both colored by pitch type -- but scaled down to a
    single pitch and a small fixed-size image (this renders via
    chart_helpers.fig_to_img, same static-PNG pattern as the rest of
    this per-selection card) rather than the full multi-pitch chart
    with its batter silhouettes and legend, which wouldn't read at
    280x280.

    intended_x/z and actual_x/z are floats already, in the same
    plate-coordinate feet used by strike_zone.py's zone constants;
    actual_x/z may be None if the pitch has no recorded location yet,
    in which case only the intended point is drawn.

    Home plate drawn view="catcher" (Sept 2026, Ryker: this card's
    intended-vs-actual view is from behind the plate looking out at
    the pitcher, same viewpoint as Command Tracker's location pickers
    -- corrected from an initial view="pitcher" guess, which Ryker
    caught as backwards for this particular chart). Note this diverges
    from pitch_locations_chart's own view="pitcher" convention on
    Command Tracking's dashboard -- the two charts share styling
    (markers, connecting line, colors) but not viewpoint.

    batter_hand ('R'/'L'/None, Sept 2026, Ryker: "have a batter graphic
    based on the hitter that was up... visually see a batter in the
    box") -- draws ONE hitter_graphic.hitter_images() silhouette (not
    the decorative pair command_charts.py draws on both sides), on the
    side matching this pitch's actual batter, resolved by the caller
    via game_stats.get_batter_hands() rather than trusted from the raw
    GamePitch.opponent_hand column (see that function's own docstring
    for why -- three-squad intrasquad games in particular). Catcher-view
    convention (this card's view="catcher" above) puts a RIGHT-handed
    batter on the LEFT/negative-x side of the plate -- the box closer
    to 3B -- and a LEFT-handed batter on the RIGHT/positive-x side --
    closer to 1B -- same side Statcast's own pitch-location graphics
    draw them on. (The SIDE was right from the start; the POSE
    initially wasn't -- see the facing= comment where this is called,
    a couple lines below, for that fix.) None (hand couldn't be
    resolved) skips the silhouette entirely rather than guessing a
    side. This is why the card grew
    from a fixed 280x280 to 450x450 (see pitch_detail_card) -- this
    function originally stayed silhouette-free specifically because a
    batter "wouldn't read" at the old smaller size; superseded now that
    Ryker's asked for one and confirmed the larger size."""
    fig = go.Figure()

    # Zone box + intended/actual markers all shifted down by the same
    # -0.5ft as the batter silhouette below (Sept 2026, Ryker: "the
    # strike zone needs to be adjusted, moved down to match the batter
    # moving down"). Shifting this whole group together keeps the zone
    # box and the markers positioned correctly relative to EACH OTHER
    # -- it's still the same real pitch data, just rendered 0.5ft lower
    # -- while re-aligning them visually against the batter, whose feet
    # were moved down (ground_y=-0.5) to sit at the plate instead of
    # floating above it. Home plate stays at ground_y=0.0 below -- it's
    # the one true anchor everything else here is positioned relative
    # to, so it does NOT get this shift.
    ZONE_Y_SHIFT = -0.5

    if actual_x is not None and actual_z is not None:
        fig.add_shape(
            type="line", xref="x", yref="y",
            x0=intended_x, y0=intended_z + ZONE_Y_SHIFT, x1=actual_x, y1=actual_z + ZONE_Y_SHIFT,
            line=dict(color=MUTED_GRAY, width=1, dash="dot"), layer="below",
        )

    fig.add_trace(go.Scatter(
        x=[intended_x], y=[intended_z + ZONE_Y_SHIFT], mode="markers",
        marker=dict(symbol="circle-open", color=color, size=22, line=dict(color=color, width=3)),
        name="Intended", showlegend=True, hoverinfo="skip",
    ))
    if actual_x is not None and actual_z is not None:
        fig.add_trace(go.Scatter(
            x=[actual_x], y=[actual_z + ZONE_Y_SHIFT], mode="markers",
            marker=dict(symbol="circle", color=color, size=22, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
            name="Actual", showlegend=True, hoverinfo="skip",
        ))

    fig.add_shape(
        type="rect", x0=-strike_zone.ZONE_HALF_WIDTH, x1=strike_zone.ZONE_HALF_WIDTH,
        y0=strike_zone.ZONE_BOTTOM + ZONE_Y_SHIFT, y1=strike_zone.ZONE_TOP + ZONE_Y_SHIFT,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )
    # Batter silhouette -- see this function's own docstring for the
    # hand-to-side convention. Reuses command_charts.py's own tuned
    # HITTER_HEIGHT_FT/HITTER_CENTER_X/CHART_X_EXTENT_FT constants below
    # rather than a second set of magic numbers, so a batter drawn here
    # matches the one on Command Tracking's chart in scale.
    if batter_hand in ("R", "L"):
        # Sept 2026 -- settled by actually rendering all four
        # combinations (center_x sign x facing) and looking at the
        # pixels, after two rounds of guessing wrong from the docstring
        # alone. The one thing that has to be true regardless of hand:
        # the batter faces the strike zone (front foot/shoulder toward
        # it, bat cocked back over the AWAY-from-zone shoulder) rather
        # than facing out of the picture -- anything else reads as
        # backwards ("looks like the catcher is throwing the pitch").
        # That happens exactly when facing is paired with center_x's
        # sign the same way command_charts.py already pairs them
        # (facing="right" with +x, facing="left" with -x) -- i.e. no
        # hand-specific override needed at all; center_x alone (from
        # the R/L-to-side mapping below) determines facing. The earlier
        # "swap facing per hand" fix was wrong -- it made both hands
        # face outward, away from the zone.
        center_x = -command_charts.HITTER_CENTER_X if batter_hand == "R" else command_charts.HITTER_CENTER_X
        facing = "right" if center_x > 0 else "left"
        # ground_y=-0.5 (Sept 2026, Ryker: "it looks like the hitter is
        # standing way in front of the plate") -- the plate's own ground
        # line already sits exactly at the batter's un-shifted feet
        # (both nominally ground_y=0), so there's no real math mismatch;
        # the plate is just a small, thin shape (its own depth_ft=0.22
        # exaggerated to *1.7 for the point) sitting well off to the
        # side under the zone, so a batter whose feet only just touch
        # its topmost edge reads as standing forward of it rather than
        # at it. Confirmed by rendering a few offsets and having Ryker
        # pick -- shifting the batter down (not raising the plate,
        # which barely moved the needle at this scale) closes the gap.
        for img in hitter_images(center_x=center_x, facing=facing, height_ft=command_charts.HITTER_HEIGHT_FT, ground_y=-0.5):
            fig.add_layout_image(**img)

    fig.add_shape(**home_plate_shape(half_width_ft=strike_zone.ZONE_HALF_WIDTH, ground_y=0.0, view="catcher"))

    apply_gbo_theme(
        fig, height=450, margin=dict(l=0, r=0, t=0, b=0),
        # Widened from the original +/-2.0/4.5 (see docstring) to fit the
        # batter silhouette -- same extents as command_charts.py's own
        # chart so the zone/markers end up at roughly the same on-screen
        # scale as before despite the bigger canvas (450px over a wider
        # range works out to nearly the same ft-per-pixel density as
        # 280px over the old, narrower one).
        xaxis=dict(range=[-command_charts.CHART_X_EXTENT_FT, command_charts.CHART_X_EXTENT_FT], visible=False, fixedrange=True),
        # Lower bound dropped to -0.9 (was -0.4) so the batter's feet
        # -- now anchored at ground_y=-0.5, not 0 (see the ground_y=-0.5
        # comment above) -- have room below them instead of clipping.
        yaxis=dict(range=[-0.9, command_charts.HITTER_HEIGHT_FT + 0.4], visible=False, fixedrange=True, scaleanchor="x", scaleratio=1),
        legend=dict(orientation="h", y=-0.05, font=dict(size=10)),
    )
    return fig


def _all_pitch_locations_figure(pitches, color_by, baseline, own_idx_map=None):
    """All-pitches location scatter for the Pitch Locations view (Ryker,
    Sept 2026: "looking at pitch location for all pitches of a certain
    pitch type vs LHH, RHH ... an option to see all each different
    pitch with all of their locations" plus "is there also something
    we could create to see if the locations that we are throwing to
    is getting good results for the pitcher or poor results?"). Caller
    has already filtered `pitches` by pitch type / batter hand (this
    page's loc_pitch_type/loc_batter_hand inputs) -- this just draws
    whatever it's handed.

    color_by == "type": one trace per pitch type, using the same
    app-wide pitch-type color convention (pitch_type_config via
    color_for_pitch_label) as bullpen_charts.location_chart's own
    mode="individual" -- lets a coach see e.g. "the slider's locations
    cluster down-and-away" whether one type or every type is shown.

    color_by == "result": every pitch in one trace, colored by its
    Location+ grade (analytics.pitch_grading.location_plus against
    `baseline` -- analytics.profile_queries.team_location_plus_baseline)
    -- same 100-average/10-points-per-standard-deviation scale as
    Stuff+/Command+ elsewhere on this page, so green reads as "this
    location has actually worked out well for the pitcher" and red as
    the opposite, using this team's own run-value history, not a
    league benchmark. A pitch whose (attack zone, pitch type) cell has
    no stable team-wide baseline yet (or has no run_value at all --
    e.g. Video Review not done, or an unusual count RunExpectancy has
    no entry for) gets its own muted-gray trace instead of being
    silently dropped -- same "shown anyway, not hidden" small-sample
    philosophy as every other grading feature on this page.

    Same real plate-coordinate feet and view="catcher" home plate as
    this page's own _pitch_location_figure above (same actual_plate_x/z
    fields, same catcher's-eye-view Ryker corrected there).

    own_idx_map: optional {game_pitch_id: pitcher-specific pitch number}
    (see _own_pitch_index_map) -- when given, hover text shows this
    pitcher's own pitch count for the game instead of the game-wide
    pitch_sequence (Ryker, Sept 2026: same "specific to that pitcher"
    request as Pitch Detail's numbering)."""
    fig = go.Figure()

    if color_by == "result":
        graded_x, graded_y, graded_vals, graded_custom = [], [], [], []
        ungraded_x, ungraded_y, ungraded_custom = [], [], []
        for p in pitches:
            label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
            lp = location_plus(p, baseline)
            base_custom = [
                own_idx_map.get(p.game_pitch_id, p.pitch_sequence) if own_idx_map else p.pitch_sequence,
                label, p.pitch_outcome or "—",
                p.ab_outcome if (p.ends_plate_appearance and p.ab_outcome) else "—",
            ]
            if lp is None:
                ungraded_x.append(float(p.actual_plate_x))
                ungraded_y.append(float(p.actual_plate_z))
                ungraded_custom.append(base_custom)
            else:
                graded_x.append(float(p.actual_plate_x))
                graded_y.append(float(p.actual_plate_z))
                graded_vals.append(lp)
                graded_custom.append(base_custom + [lp])

        if ungraded_x:
            fig.add_trace(go.Scatter(
                x=ungraded_x, y=ungraded_y, mode="markers", name="Not enough team data yet",
                marker=dict(color=MUTED_GRAY, size=11, opacity=0.6, line=dict(color="#1E1E1E", width=1)),
                customdata=ungraded_custom,
                hovertemplate=(
                    "%{customdata[1]}<br>Pitch #%{customdata[0]}<br>Result: %{customdata[2]}<br>"
                    "AB Outcome: %{customdata[3]}<br>No Location+ grade yet<extra></extra>"
                ),
            ))
        if graded_x:
            fig.add_trace(go.Scatter(
                x=graded_x, y=graded_y, mode="markers", name="Location+",
                marker=dict(
                    color=graded_vals, colorscale="RdYlGn", cmid=100, size=13, opacity=0.9,
                    line=dict(color="#1E1E1E", width=1),
                    colorbar=dict(title="Location+", tickfont=dict(color=TEXT_CREAM), title_font=dict(color=TEXT_CREAM)),
                ),
                customdata=graded_custom,
                hovertemplate=(
                    "%{customdata[1]}<br>Pitch #%{customdata[0]}<br>Result: %{customdata[2]}<br>"
                    "AB Outcome: %{customdata[3]}<br>Location+: %{customdata[4]:.0f}<extra></extra>"
                ),
            ))
    else:
        order, groups = [], {}
        for p in pitches:
            label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
            if label not in groups:
                groups[label] = []
                order.append(label)
            groups[label].append(p)
        for label in order:
            group = groups[label]
            color = color_for_pitch_label(label) if label != "Unspecified" else MUTED_GRAY
            fig.add_trace(go.Scatter(
                x=[float(p.actual_plate_x) for p in group],
                y=[float(p.actual_plate_z) for p in group],
                mode="markers", name=label,
                marker=dict(color=color, size=12, opacity=0.9, line=dict(color="#1E1E1E", width=1)),
                customdata=[
                    [own_idx_map.get(p.game_pitch_id, p.pitch_sequence) if own_idx_map else p.pitch_sequence,
                     p.pitch_outcome or "—",
                     p.ab_outcome if (p.ends_plate_appearance and p.ab_outcome) else "—"]
                    for p in group
                ],
                hovertemplate=(
                    f"{label}<br>Pitch #%{{customdata[0]}}<br>Result: %{{customdata[1]}}<br>"
                    "AB Outcome: %{customdata[2]}<extra></extra>"
                ),
            ))

    fig.add_shape(
        type="rect", x0=-strike_zone.ZONE_HALF_WIDTH, x1=strike_zone.ZONE_HALF_WIDTH,
        y0=strike_zone.ZONE_BOTTOM, y1=strike_zone.ZONE_TOP,
        line=dict(color=TEXT_CREAM, width=2), fillcolor="rgba(0,0,0,0)",
    )
    fig.add_shape(**home_plate_shape(half_width_ft=strike_zone.ZONE_HALF_WIDTH, ground_y=0.0, view="catcher"))

    apply_gbo_theme(
        fig, title="Pitch Locations", x_title="Plate Side (ft)", y_title="Plate Height (ft)", height=480,
        xaxis=dict(range=[-2.5, 2.5], gridcolor=GRID_GRAY, zeroline=False, scaleanchor="y", scaleratio=1),
        yaxis=dict(range=[-0.4, 5], gridcolor=GRID_GRAY, zeroline=False),
        legend=dict(orientation="h", y=-0.15),
    )
    return fig


@module.ui
def pitcher_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Game Report"),
        ui.output_ui("game_picker"),
        ui.output_ui("staff_totals_section"),
        ui.output_ui("pitcher_picker"),
        ui.output_ui("report_body"),
        # Everything below is one of the "View" dropdown's sections --
        # each of these render.ui functions gates itself on
        # input.report_section() and returns None when not selected, so
        # only the chosen section actually queries the DB/builds charts
        # (see report_section_picker below). All five stay statically
        # listed here (Shiny needs a placeholder in the DOM for each
        # output id), same as report_body/command_target_section/
        # rapsodo_shape_section always were -- the change is what each
        # function does internally, not whether it's wired up.
        ui.output_ui("report_section_picker"),
        ui.output_ui("pitch_type_breakdown_section"),
        ui.output_ui("command_execution_section"),
        ui.output_ui("command_target_section"),
        ui.output_ui("pitch_locations_section"),
        ui.output_ui("rapsodo_shape_section"),
        ui.output_ui("pitch_by_pitch_section"),
        ui_helpers.page_footer(),
    )


@module.server
def pitcher_game_report_server(input, output, session, app_state):
    # "Player" added Sept 2026 (Ryker: players should be able to see game
    # reports for themselves) -- self-scoped, same pattern pitcher_profile.py
    # already established: a Player sees no game/pitcher pickers pointed at
    # the whole roster, just their own outings, and every other gated
    # section below (report_body, command_execution_section, etc.) stays
    # completely unchanged -- they all just read game_select/pitcher_select,
    # which game_picker/pitcher_picker below already restrict to this
    # player's own data, so the rest of the page needs no per-section
    # Player-specific logic. Nav only links this page for a pitcher-flagged
    # Player (see nav.py's is_pitcher_player) -- the is_pitcher check here
    # is defense-in-depth, not the only gate.
    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator", "Player")

    def _my_pitcher(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        player = db.query(Player).filter(Player.player_id == me.player_id).first()
        return player if (player is not None and player.is_pitcher) else None

    @render.ui
    def game_picker():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role not in ALLOWED_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            if role == "Player":
                me = _my_pitcher(db)
                if me is None:
                    return ui.p("You don't have access to this page.", class_="text-danger")
                # Same our_player_id/opponent_our_player_id dual lookup as
                # pitcher_picker below (intrasquad games record "the other
                # squad's" pitcher under opponent_our_player_id), just
                # narrowed to this one player instead of every pitcher.
                own_game_ids = {
                    gid for (gid,) in db.query(GamePitch.game_id)
                    .filter(GamePitch.our_player_id == me.player_id, GamePitch.is_our_team_batting.is_(False))
                    .distinct().all()
                } | {
                    gid for (gid,) in db.query(GamePitch.game_id)
                    .filter(GamePitch.opponent_our_player_id == me.player_id, GamePitch.is_our_team_batting.is_(True))
                    .distinct().all()
                }
                if not own_game_ids:
                    return ui_helpers.empty_state("No games recorded for you as a pitcher yet.")
                games = (
                    db.query(Game).options(joinedload(Game.opponent_team))
                    .filter(Game.game_id.in_(own_game_ids))
                    .order_by(Game.game_date.desc()).all()
                )
            else:
                games = db.query(Game).options(joinedload(Game.opponent_team)).order_by(Game.game_date.desc()).all()
            if not games:
                return ui_helpers.empty_state("No games tracked yet. Start one on Game Tracking first.")
            choices = {str(g.game_id): _game_label(g) for g in games}
            return ui.input_select("game_select", "Game", choices=choices)
        finally:
            db.close()

    @render.ui
    def staff_totals_section():
        """Whole-game, whole-staff totals for the five "team pitching
        goals" stats (Ryker, Sept 2026 -- see compute_staff_game_totals's
        own docstring for the full request and each stat's definition).
        Independent of the Pitcher picker below -- shows as soon as a
        game is selected, since it's a staff-wide view, not one
        pitcher's. Two goal-tracked stats (First Pitch Strike %,
        Secondary Strike %) get a green/red tile against Ryker's own
        targets; the other three (AB<=4-pitches %, Leadoff Out %,
        Shutdown Inning %) show plainly with no goal yet, per his call."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        selected_game_id = int(input.game_select())

        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == selected_game_id).first()
            if game is None:
                return None
            totals = compute_staff_game_totals(db, selected_game_id)
            if totals is None:
                return ui_helpers.card(ui_helpers.empty_state("No pitches recorded for our staff in this game yet."), title="Staff Totals", right=_game_label(game))
            staff = totals["staff_total"]

            def _goal_tile(label, pct, goal):
                if pct is None:
                    return ui_helpers.kpi_tile(label, "—", delta="No pitches yet")
                met = pct >= goal
                return ui_helpers.kpi_tile(
                    label, _fmt_pct(pct),
                    delta=f"Goal {goal:.0f}%+", delta_positive=met,
                    status="good" if met else "flag",
                )

            goal_tiles = ui.div(
                _goal_tile("First Pitch Strike %", staff["fps_pct"], FPS_GOAL_PCT),
                _goal_tile("Secondary Strike %", staff["secondary_strike_pct"], SECONDARY_STRIKE_GOAL_PCT),
                class_="gbo-kpi-row",
            )
            plain_tiles = ui.div(
                ui_helpers.kpi_tile("AB ≤ 4 Pitches %", _fmt_pct(staff["ab4_pct"])),
                ui_helpers.kpi_tile("Leadoff Out %", _fmt_pct(staff["leadoff_out_pct"])),
                ui_helpers.kpi_tile(
                    "Shutdown Inning %", _fmt_pct(staff["shutdown_pct"]),
                    delta=f"{staff['shutdown_converted']}/{staff['shutdown_opportunities']} opportunities" if staff["shutdown_opportunities"] else "No opportunities yet",
                ),
                class_="gbo-kpi-row", style="margin-top:8px;",
            )

            by_inning_rows = [
                {
                    "Inning": r["inning"], "FPS %": _fmt_pct(r["fps_pct"]), "AB≤4 Pitches %": _fmt_pct(r["ab4_pct"]),
                    "Leadoff Out %": _fmt_pct(r["leadoff_out_pct"]), "Secondary Strike %": _fmt_pct(r["secondary_strike_pct"]),
                    "Shutdown": ("Yes" if r["shutdown"] else "No") if r["shutdown_opportunity"] else "—",
                }
                for r in totals["by_inning"]
            ]
            by_pitcher_rows = [
                {
                    "Pitcher": r["player_name"], "FPS %": _fmt_pct(r["fps_pct"]), "AB≤4 Pitches %": _fmt_pct(r["ab4_pct"]),
                    "Leadoff Out %": _fmt_pct(r["leadoff_out_pct"]), "Secondary Strike %": _fmt_pct(r["secondary_strike_pct"]),
                    "Shutdown": f"{r['shutdown_converted']}/{r['shutdown_opportunities']}" if r["shutdown_opportunities"] else "—",
                }
                for r in totals["by_pitcher"]
            ]

            return ui_helpers.card(
                goal_tiles,
                plain_tiles,
                ui.h6("By inning", class_="mt-3"),
                ui_helpers.render_dict_table(by_inning_rows, empty_message="No innings pitched yet."),
                ui.h6("By pitcher", class_="mt-3"),
                ui_helpers.render_dict_table(by_pitcher_rows, empty_message="No pitchers recorded yet."),
                title="Staff Totals", right=_game_label(game),
            )
        finally:
            db.close()

    @render.ui
    def pitcher_picker():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        selected_game_id = int(input.game_select())

        db = get_session()
        try:
            if app_state.role_name() == "Player":
                me = _my_pitcher(db)
                if me is None:
                    return ui.p("You don't have access to this page.", class_="text-danger")
                # No picker needed -- game_picker above already restricted
                # game_select to games this player pitched in, so there's
                # exactly one pitcher to show: themselves. Still a real
                # input_select (not skipped) so every downstream section
                # keeps reading input.pitcher_select() unchanged.
                return ui.input_select("pitcher_select", "Pitcher", choices={str(me.player_id): f"{me.first_name} {me.last_name}"})

            our_pitcher_ids = {
                pid for (pid,) in db.query(GamePitch.our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(False))
                .distinct().all()
                if pid is not None
            }
            # Intrasquad games: the "other side" is also our own roster (Squad B),
            # recorded as opponent_our_player_id while we're batting -- include
            # those pitchers too so BOTH squads' pitchers show up here, since in
            # an intrasquad game every pitcher belongs to our own team either way.
            other_squad_pitcher_ids = {
                pid for (pid,) in db.query(GamePitch.opponent_our_player_id)
                .filter(GamePitch.game_id == selected_game_id, GamePitch.is_our_team_batting.is_(True))
                .distinct().all()
                if pid is not None
            }
            pitcher_ids = our_pitcher_ids | other_squad_pitcher_ids
            if not pitcher_ids:
                return ui_helpers.empty_state("No pitches recorded for any of our pitchers in this game yet.")
            pitchers = db.query(Player).filter(Player.player_id.in_(pitcher_ids)).order_by(Player.last_name, Player.first_name).all()
            choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitchers}
            return ui.input_select("pitcher_select", "Pitcher", choices=choices)
        finally:
            db.close()

    @render.ui
    def report_body():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())

        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == selected_game_id).first()
            pitcher = db.query(Player).filter(Player.player_id == selected_pitcher_id).first()
            if game is None or pitcher is None:
                return None

            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return ui_helpers.empty_state("No pitches for this pitcher in this game.")

            # Runners swept home by an "End half-inning early" override
            # (see models.GameForcedHalfInningEnd) count as this
            # pitcher's earned runs even though they never landed on a
            # GamePitch row -- fold them into Runs Allowed/ERA here too.
            extra_earned_runs = get_forced_half_inning_end_runs(db, selected_pitcher_id, game_id=selected_game_id)
            extra_outs = get_runner_event_outs(db, selected_pitcher_id, game_id=selected_game_id)
            line = compute_pitching_line(pitches, extra_earned_runs=extra_earned_runs, extra_outs=extra_outs)
            # Sept 2026, Ryker: wants Command Execution % (the graded
            # 0/1/2 distance-from-called-target score, see Command &
            # Execution section / analytics/command_metrics.py) in the
            # Line row instead of Zone Execution % (the binary same-
            # zone match this "line" dict itself computes -- see
            # game_stats.compute_pitching_line). Reuses the exact same
            # game_pitches_command_view()/session_command_scorecard()
            # pair the Command & Execution section below builds off of,
            # not a second implementation -- see that section's own
            # module comment (command_target_section/_selected_pitcher_
            # view_pitches) for why. Zone Execution % isn't removed
            # anywhere else on the page, just no longer duplicated here.
            cmd_view_pitches = command_metrics.game_pitches_command_view(pitches, pitcher.throws)
            cmd_scorecard = command_metrics.session_command_scorecard(cmd_view_pitches)
            sections = [ui.h5(f"{pitcher.first_name} {pitcher.last_name} — {_game_label(game)}", class_="gbo-section-title")]

            sections.append(ui.p(ui.strong("Line")))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "IP", "value": str(line["IP"])},
                {"label": "Pitches", "value": str(line["Pitches"])},
                {"label": "K", "value": str(line["K"])},
                {"label": "BB", "value": str(line["BB"])},
                {"label": "H", "value": str(line["H Allowed"])},
                {"label": "R", "value": str(line["Runs Allowed"])},
            ]))
            sections.append(ui_helpers.render_kpi_cards([
                {"label": "WHIP", "value": _fmt(line["WHIP"])},
                {"label": "K/BB", "value": _fmt(line["K/BB"])},
                {"label": "K %", "value": _fmt_pct(line["K %"])},
                {"label": "ERA", "value": _fmt(line["ERA"])},
                {"label": "FIP", "value": _fmt(line["FIP"])},
                {"label": "Command Execution %", "value": _cmd_fmt(cmd_scorecard["execution_pct"], "%")},
            ]))
            # Count Control/Situational/Against tucked behind one
            # collapsed-by-default accordion panel -- Sept 2026, Ryker:
            # "too much information ... want to track all of it but
            # don't need to always see all of it." Line above stays
            # always visible (the first thing anyone wants), everything
            # still computes/renders exactly as before, just not open
            # by default. Same ui.accordion(..., open=False, id=None)
            # pattern already used for collapsed-by-default panels
            # elsewhere in the app (assessments.py, bullpen_tracking.py,
            # game_tracking.py, idp.py, opponent_teams.py).
            more_children = [
                ui.p(ui.strong("Count Control")),
                ui_helpers.render_kpi_cards([
                    {"label": "Strike %", "value": _fmt_pct(line["Strike %"])},
                    {"label": "Early", "value": str(line["Early"])},
                    {"label": "Ahead", "value": str(line["Ahead (PA)"])},
                    {"label": "E+A %", "value": _fmt_pct(line["E+A %"])},
                ]),
                ui.p(f"Pitches/Inning: {_fmt(line['Pitches/Inning'], 1)} · Balls: {line['Balls']} ({_fmt_pct(line['Ball %'])})", class_="text-muted small"),

                ui.p(ui.strong("Situational")),
                ui_helpers.render_kpi_cards([
                    {"label": "Leadoff Out %", "value": _fmt_pct(line["Leadoff Out %"])},
                    {"label": "Leadoff BB", "value": str(line["Leadoff BB"])},
                    {"label": "2 Out BB", "value": str(line["2 Out BB"])},
                    {"label": "XBH Allowed", "value": str(line["XBH"])},
                ]),
                ui.p(
                    f"0-2 Hits: {line['0-2 Hits']} · 0-2 Barrel: {line['0-2 Barrel']} · 1-2 Barrel: {line['1-2 Barrel']} · "
                    "\"Score\" versions (did that specific walked runner score) aren't computable yet -- "
                    "GBO tracks base occupancy, not individual runner identity.",
                    class_="text-muted small",
                ),

                ui.p(ui.strong("Against")),
                ui_helpers.render_kpi_cards([
                    {"label": "OBA", "value": _fmt(line["OBA (opponent AVG)"], 3)},
                    {"label": "wOBA*", "value": _fmt(line["wOBA"], 3)},
                    {"label": "AB", "value": str(line["AB"])},
                ]),
                ui.p("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.", class_="text-muted small"),
            ]
            sections.append(ui.accordion(
                ui.accordion_panel("More: Count Control, Situational, Against", *more_children),
                open=False, id=None,
            ))

            # Pitch Type Breakdown / Command Precision / Attack Zones /
            # Command Target Zones / Pitch Shape (Rapsodo) used to all be
            # appended here too, making this one continuously-scrolling
            # page. They're now each their own gated section, chosen via
            # the "View" dropdown (report_section_picker) below, so only
            # one renders (and queries the DB) at a time -- Ryker's Sept
            # 2026 report request. See pitch_type_breakdown_section/
            # command_execution_section/command_target_section/
            # rapsodo_shape_section/pitch_by_pitch_section.
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def report_section_picker():
        """The "View" dropdown driving which of the five sections below
        actually renders. Default (first dict entry, Python preserves
        insertion order) is Pitch Type Breakdown -- each gated section
        function checks input.report_section() itself and returns None
        immediately when not selected, before doing any query, so
        switching this dropdown is what stops the DB work for the other
        four, not CSS visibility."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.input_select(
                    "report_section", "View",
                    choices={
                        "pitch_type_breakdown": "Pitch Type Breakdown",
                        "command_execution": "Command & Execution",
                        "pitch_locations": "Pitch Locations",
                        "pitch_shape": "Pitch Shape / Rapsodo",
                        "pitch_by_pitch": "Pitch-by-Pitch",
                    },
                ),
            )
        finally:
            db.close()

    @render.ui
    def pitch_type_breakdown_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_type_breakdown":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return None
            hands = get_batter_hands(db, pitches)
            vs_rhh = [p for p in pitches if hands.get(p.game_pitch_id) == "R"]
            vs_lhh = [p for p in pitches if hands.get(p.game_pitch_id) == "L"]
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            return ui.div(
                ui.p(ui.strong("Pitch Type Breakdown")),
                ui.p(
                    f"Stuff+ is team-relative (100 = your staff's average, 10 points = 1 SD) and only populates for "
                    f"pitches with a Rapsodo reading linked to this outing. 'Reliable' needs at least "
                    f"{MIN_BASELINE_PITCHES} pitches of that type in this game -- shown either way, just flagged below "
                    f"that floor.",
                    class_="text-muted small",
                ),
                ui.navset_tab(
                    ui.nav_panel("All Batters", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(pitches, rap_by_gp, stuff_baselines))),
                    ui.nav_panel("vs RHH", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(vs_rhh, rap_by_gp, stuff_baselines)) if vs_rhh else ui.p("No pitches recorded against a right-handed batter yet.", class_="text-muted small")),
                    ui.nav_panel("vs LHH", ui_helpers.render_dict_table(_pitch_type_breakdown_with_stuff(vs_lhh, rap_by_gp, stuff_baselines)) if vs_lhh else ui.p("No pitches recorded against a left-handed batter yet.", class_="text-muted small")),
                ),
            )
        finally:
            db.close()

    @render.ui
    def command_execution_section():
        """Command Precision + Attack Zones -- unchanged computation,
        just moved out of report_body into their own gated section
        (paired under the same "Command & Execution" dropdown value as
        command_target_section below, which stays a separate function
        since it also owns a render_plotly chart -- see that function's
        own comment for why that split has to stay a separate output)."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "command_execution":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitcher = db.query(Player).filter(Player.player_id == selected_pitcher_id).first()
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches or pitcher is None:
                return None

            sections = [ui.p(ui.strong("Command Precision"))]
            sections.append(ui.p(
                "Real distance between where he aimed and where it actually crossed the plate -- only counts "
                "pitches reviewed in Video Review (both an intended and an actual location on file).",
                class_="text-muted small",
            ))
            cp_overall, cp_by_type = compute_command_precision(pitches, throws=pitcher.throws)
            if cp_overall["Reviewed"] == 0:
                sections.append(ui.p("No reviewed pitches yet (needs Video Review).", class_="text-muted small"))
            else:
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Avg Miss", "value": f"{cp_overall['Avg Miss (in)']}\""},
                    {"label": "Reviewed", "value": str(cp_overall["Reviewed"])},
                    {"label": "Horizontal Bias", "value": f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}"},
                    {"label": "Vertical Bias", "value": f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}"},
                ]))
                if pitcher.throws not in ("R", "L"):
                    sections.append(ui.p("Pitcher's throwing hand isn't on file, so horizontal bias shows raw 3B-side/1B-side instead of Arm-side/Glove-side.", class_="text-muted small"))
                sections.append(ui_helpers.render_dict_table(cp_by_type))

            sections.append(ui.p(ui.strong("Attack Zones")))
            sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near. GBO approximation of Statcast's own tiers.", class_="text-muted small"))
            az_overall, az_by_type = compute_attack_zones(pitches)
            if az_overall["Located"] == 0:
                sections.append(ui.p("No located pitches yet.", class_="text-muted small"))
            else:
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Heart %", "value": _fmt_pct(az_overall["Heart %"])},
                    {"label": "Shadow %", "value": _fmt_pct(az_overall["Shadow %"])},
                    {"label": "Chase Zone %", "value": _fmt_pct(az_overall["Chase Zone %"])},
                    {"label": "Waste %", "value": _fmt_pct(az_overall["Waste %"])},
                ]))
                sections.append(ui_helpers.render_dict_table(az_by_type))
                sections.append(output_widget("attack_zones_chart"))

            return ui.div(*sections)
        finally:
            db.close()

    @render_plotly
    def attack_zones_chart():
        """Chart half of Attack Zones -- see _attack_zones_figure's own
        docstring. Separate registered function/output_widget than the
        KPI cards/table above (command_execution_section, a render.ui),
        same split every other render_plotly chart on this page needs
        (a render_plotly output can't be nested inside a render.ui
        function's own return value)."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "command_execution":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
            if not located:
                return None
            return _attack_zones_figure(located)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Command Target Zones -- Command Tracker's own scorecard/table/chart
    # (analytics/command_metrics.py's session_command_scorecard/
    # command_by_pitch_type/miss_bias + visualizations/command_charts.
    # command_chart()), fed this game's own GamePitch rows adapted through
    # command_metrics.game_pitches_command_view() instead of a second,
    # parallel bullpen-only implementation. A new, additional section
    # placed AFTER Attack Zones -- Command Precision/Attack Zones above
    # (pitch_location_stats.py) are completely untouched. Only pitches
    # with an intended location count here (game_pitches_command_view()
    # excludes any without one -- i.e. a real external opponent's
    # pitches, whose intent GBO never captures; see game_tracking.py's
    # show_intended), so for a real-opponent game this section stays
    # empty even though Command Precision above (which only needs
    # intended+actual together anyway) would too. Same three-block
    # render.ui-wrapper / render_plotly / render.ui-table split as
    # hitter_game_report.py's Contact Quality by Zone / Pitch Type
    # section, for the same reason: a render_plotly output needs its own
    # registered function, not one nested inside report_body's render.ui.
    # -------------------------------------------------------------------

    def _selected_pitcher_view_pitches(db):
        if "game_select" not in input or "pitcher_select" not in input:
            return None, None
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None, None
        pitcher = db.query(Player).filter(Player.player_id == int(pitcher_id_raw)).first()
        if pitcher is None:
            return None, None
        pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
        if not pitches:
            return None, None
        return command_metrics.game_pitches_command_view(pitches, pitcher.throws), pitcher.throws

    def _team_command_plus_baselines(db):
        """Every located pitch, across every game (intrasquad and real
        opponents alike -- fall scrimmages and the spring season both),
        from our own pitchers -- Ryker's 2026-08-23 call on what counts
        as "the team" for Command+: games only, not bullpen sessions,
        and not scoped to just intrasquad. A real-opponent game's DOES
        count for our own pitcher's outings in it -- only the opposing
        pitcher's pitches are excluded, and that's already handled
        automatically by the DB filter below: intended_plate_x is only
        ever set for our own pitcher in the first place (see
        game_tracking.py's show_intended), never for an opponent's.
        Not scoped to a season/date range yet -- all-time across every
        game currently in the system; worth revisiting once "all-time"
        and "this season" start to meaningfully diverge.

        throws=None is safe here even though these pitches span many
        different pitchers' hands -- danger_adjusted_miss doesn't depend
        on throws at all (only the miss_direction/within_*_target labels
        do, neither of which this baseline needs).

        Returns command_metrics.team_command_plus_baselines()'s
        {"pooled": (mean, stdev, n), "by_type": {...}} -- Sept 2026,
        widened from just the pooled (mean, stdev, n) so
        session_command_plus() below can grade each pitch against its
        own pitch type (see that function's module comment for why)."""
        all_pitches = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
        view_pitches = command_metrics.game_pitches_command_view(all_pitches, None)
        return command_metrics.team_command_plus_baselines(view_pitches)

    def _cmd_fmt(value, suffix=""):
        return f"{value}{suffix}" if value is not None else "—"

    def _cmd_bias_label(bias):
        parts = []
        if bias["horizontal_bias_in"] is not None:
            parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
        if bias["vertical_bias_in"] is not None:
            parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
        return " / ".join(parts) if parts else "—"

    @render.ui
    def command_target_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "command_execution":
            return None
        db = get_session()
        try:
            view_pitches, _throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Command Target Zones")),
                ui.p(
                    "Same 5-tier target-radius bands (4\"/8\"/12\"/16\"/20\") and concentric-ring chart Command "
                    "Tracker uses -- built from this game's own intended-vs-actual pitch locations, no separate "
                    "math. Only pitches with a logged intended location count (a real opponent's pitcher never has "
                    "one on file).",
                    class_="text-muted small",
                ),
                ui.output_ui("command_target_table"),
                output_widget("command_target_chart"),
                ui.output_ui("pitch_targeting_plan_section"),
                output_widget("pitch_targeting_plan_chart"),
            )
        finally:
            db.close()

    @render.ui
    def command_target_table():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None

            scorecard = command_metrics.session_command_scorecard(view_pitches)
            if scorecard["located_pitches"] == 0:
                return ui.p("No pitches have an actual location recorded yet -- needs Video Review.", class_="text-muted small")

            baselines = _team_command_plus_baselines(db)
            _pooled_mean, _pooled_stdev, baseline_n = baselines["pooled"]
            command_plus_value = None
            if baseline_n >= command_metrics.MIN_BASELINE_PITCHES:
                command_plus_value = command_metrics.session_command_plus(view_pitches, baselines)

            tier_cards = [
                {"label": f'{label} Hit% (\u2264{radius:.0f}")', "value": _cmd_fmt(scorecard["tier_pcts"].get(label), "%")}
                for radius, label in command_config.TARGET_RADII_IN
            ]
            children = [ui_helpers.render_kpi_cards([
                {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
                {"label": "Command+", "value": _cmd_fmt(command_plus_value)},
                {"label": "Avg Miss", "value": _cmd_fmt(scorecard["avg_miss_distance"], " in")},
                {"label": "Danger-Adj. Miss", "value": _cmd_fmt(scorecard["avg_danger_adjusted_miss"], " in")},
                {"label": "Median Miss", "value": _cmd_fmt(scorecard["median_miss_distance"], " in")},
                {"label": "Command Execution %", "value": _cmd_fmt(scorecard["execution_pct"], "%")},
                *tier_cards,
                {"label": "Major Miss %", "value": _cmd_fmt(scorecard["major_miss_pct"], "%")},
            ])]
            if command_plus_value is not None:
                children.append(ui.p(
                    "Command+: 100 = your own team's average -- graded pitch type by pitch type (a called slider "
                    "compares to the team's own slider misses, a called fastball to fastball misses), falling back "
                    "to the whole-team average only for a pitch type still too thin to trust on its own. Not an MLB "
                    "comparison -- GBO doesn't have access to league-wide pitch data. Above 100 is better than your "
                    "team's own average, below is worse.",
                    class_="text-muted small",
                ))
            else:
                children.append(ui.p(
                    f"Command+ needs at least {command_metrics.MIN_BASELINE_PITCHES} located pitches across all your "
                    f"team's games (any pitcher, any game) to form a stable baseline -- {baseline_n} so far. 100 will "
                    "mean your own team's average, not an MLB comparison -- GBO doesn't have access to league-wide "
                    "pitch data.",
                    class_="text-muted small",
                ))

            bias = command_metrics.miss_bias(view_pitches, throws)
            children.append(ui.p(f"Average miss bias: {_cmd_bias_label(bias)}", class_="text-muted small mt-2"))

            by_type = command_metrics.command_by_pitch_type(view_pitches, throws)
            if len(by_type) > 1:
                rows = []
                for row in by_type:
                    tier_cols = {
                        f'{label} % (\u2264{radius:.0f}")': (row["Tier Pcts"].get(label) if row["Tier Pcts"].get(label) is not None else "—")
                        for radius, label in command_config.TARGET_RADII_IN
                    }
                    rows.append({
                        "Pitch Type": row["Pitch Type"],
                        "Pitches": row["Pitches"],
                        "Avg Miss (in)": row["Avg Miss"] if row["Avg Miss"] is not None else "—",
                        "Danger-Adj. Miss (in)": row["Danger-Adj. Miss"] if row["Danger-Adj. Miss"] is not None else "—",
                        "Command Execution %": row["Command Execution %"] if row["Command Execution %"] is not None else "—",
                        **tier_cols,
                        "Major Miss %": row["Major Miss %"] if row["Major Miss %"] is not None else "—",
                        "Miss Bias": _cmd_bias_label(row["Miss Bias"]),
                    })
                children.append(ui.h6("By pitch type", class_="mt-3"))
                children.append(ui_helpers.render_dict_table(rows))

            # Miss by call (Ryker, Sept 2026: replaced the old raw
            # per-pitch "Miss direction by pitch" list and the
            # by-pitch-type-only "Miss direction by pitch type" grid --
            # "I just want to see where they typically missed based on
            # pitch call. like if the pitch call is low and glove side
            # where do they tend to miss") -- one row per pitch type +
            # call combo (e.g. "Slider" / "Low + Glove Side"), the
            # ACTUAL pattern being asked for, aggregated instead of
            # scanned by eye across every pitch. Pitch Type is its own
            # column because the same call can miss differently by pitch
            # (Ryker, same day, follow-up: "for miss by call i need to
            # know pitc type, not just locaiton"). See
            # command_metrics.miss_by_call/call_location_label for the
            # call->label collapsing and miss_bias for the tendency math
            # (same function "Average miss bias" above already uses,
            # just scoped per pitch-type/call here). Command Target
            # Zones' own chart (command_target_chart, registered
            # separately below) is untouched -- Ryker: "keep the command
            # chart miss from target".
            call_rows = command_metrics.miss_by_call(view_pitches, throws)
            if call_rows:
                children.append(ui.h6("Miss by call", class_="mt-3"))
                children.append(ui.p(
                    "For pitches called to each location, by pitch type, how they actually missed on average -- "
                    "scan for a pitch/call combo that consistently misses the same way.",
                    class_="text-muted small",
                ))
                children.append(ui_helpers.render_dict_table([
                    {
                        "Pitch Type": row["Pitch Type"],
                        "Called": row["Called"],
                        "Pitches": row["Pitches"],
                        "Typical Miss": _cmd_bias_label(row["Miss Bias"]),
                    }
                    for row in call_rows
                ]))

            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def command_target_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, _throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            located = [p for p in view_pitches if p.horizontal_miss is not None]
            if not located:
                return None
            return command_charts.command_chart(view_pitches)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch Targeting Plan -- Sept 2026, Ryker: forward-looking companion
    # to the Command Target Zones table/chart above (which grades what
    # already happened). One recommended aim point per pitch type,
    # shifted opposite this pitcher's own measured miss bias for that
    # type (analytics.command_metrics.pitch_targeting_plan/miss_bias),
    # so the recommendation is specific to how HE actually misses, not
    # a generic tip. Same render.ui-text / render_plotly-chart split as
    # command_target_section/command_target_chart above, for the same
    # reason (a render_plotly output needs its own registered function).
    # -------------------------------------------------------------------

    @render.ui
    def pitch_targeting_plan_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            plan = command_metrics.pitch_targeting_plan(view_pitches, throws)
            if not plan:
                return ui.p(
                    f"Pitch Targeting Plan needs at least {command_metrics.MIN_TARGETING_PITCHES} located pitches "
                    "of a given pitch type in this game to recommend an aim point -- none qualify yet.",
                    class_="text-muted small mt-3",
                )
            return ui.div(
                ui.h6("Pitch Targeting Plan", class_="mt-3"),
                ui.p(
                    "Recommended aim point per pitch type -- shifted opposite this pitcher's own average miss "
                    "bias for that pitch, so if he tends to miss glove side on his slider, the recommendation "
                    "aims a bit arm side of the true target instead. \"Bias\" is the average miss this "
                    "recommendation is correcting for.",
                    class_="text-muted small",
                ),
                ui_helpers.render_dict_table([
                    {
                        "Pitch Type": row["Pitch Type"],
                        "Located": row["Located"],
                        "Bias": row["Bias"],
                        "Recommended Aim Shift": f'{row["recommended_aim_horizontal_in"]:+.1f}" horiz / {row["recommended_aim_vertical_in"]:+.1f}" vert',
                    } for row in plan
                ]),
            )
        finally:
            db.close()

    @render_plotly
    def pitch_targeting_plan_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            view_pitches, throws = _selected_pitcher_view_pitches(db)
            if not view_pitches:
                return None
            plan = command_metrics.pitch_targeting_plan(view_pitches, throws)
            if not plan:
                return None
            return command_charts.pitch_targeting_chart(plan)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch Locations -- Sept 2026, Ryker: "looking at pitch location for
    # all pitches of a certain pitch type vs left handed hitters (LHH),
    # right handed hitters (RHH), and then just an option to see all
    # each different pitch with all of their locations" plus "is there
    # also something we could create to see if the locations that we
    # are throwing to is getting good results for the pitcher or poor
    # results?" Two independent filters (Pitch Type, Batters) plus a
    # Color By toggle answering the second question: "Pitch Type"
    # colors each dot by pitch type (see all types' locations at once,
    # or one type on its own); "Result (Location+)" colors every dot
    # by analytics.pitch_grading.location_plus instead, this team's own
    # run-value-based grade of whether that location has actually
    # helped or hurt the pitcher, regardless of which pitch type filter
    # is active. See _all_pitch_locations_figure's own docstring above
    # pitcher_game_report_ui for exactly how each mode is drawn.
    # -------------------------------------------------------------------

    def _own_pitch_index_map(db, pitcher_id, game_id):
        """{game_pitch_id: pitcher-specific pitch number} for every pitch
        this pitcher threw in this game, numbered in pitch_sequence order
        (Ryker, Sept 2026: pitch_sequence is the game-wide count across
        both pitchers -- e.g. the 52nd pitch of the game could be this
        pitcher's 5th -- and Pitch Locations' hover text should show the
        latter, same as Pitch Detail)."""
        all_pitches = sorted(get_pitching_pitches(db, pitcher_id, game_id=game_id), key=lambda p: p.pitch_sequence)
        return {p.game_pitch_id: idx for idx, p in enumerate(all_pitches, start=1)}

    def _selected_pitcher_located_pitches(db):
        if "game_select" not in input or "pitcher_select" not in input:
            return None
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
        located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
        return located or None

    @render.ui
    def pitch_locations_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_locations":
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_located_pitches(db)
            if not pitches:
                return ui.div(
                    ui.hr(),
                    ui.p(ui.strong("Pitch Locations")),
                    ui.p("No located pitches yet -- needs Video Review.", class_="text-muted small"),
                )

            type_counts = {}
            type_order = []
            for p in pitches:
                label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
                if label not in type_counts:
                    type_counts[label] = 0
                    type_order.append(label)
                type_counts[label] += 1
            type_order.sort(key=lambda label: type_counts[label], reverse=True)
            type_choices = {"all": "All Pitch Types"}
            for label in type_order:
                type_choices[label] = f"{label} ({type_counts[label]})"

            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Pitch Locations")),
                ui.p(
                    "Every located pitch from this outing, plotted on the real strike zone. Filter by pitch "
                    "type and/or batter handedness, and switch Color By to \"Result (Location+)\" to see whether "
                    "these locations have actually been getting good or poor results for this pitcher, graded "
                    "against your own team's history -- not an MLB comparison.",
                    class_="text-muted small",
                ),
                ui.layout_columns(
                    ui.input_select("loc_pitch_type", "Pitch Type", choices=type_choices),
                    ui.input_select("loc_batter_hand", "Batters", choices={"all": "All Batters", "R": "vs RHH", "L": "vs LHH"}),
                    ui.input_radio_buttons("loc_color_by", "Color By", choices={"type": "Pitch Type", "result": "Result (Location+)"}, inline=True),
                    col_widths=[4, 4, 4],
                ),
                output_widget("pitch_locations_chart"),
            )
        finally:
            db.close()

    @render_plotly
    def pitch_locations_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_locations":
            return None
        req("loc_pitch_type" in input)
        req("loc_batter_hand" in input)
        req("loc_color_by" in input)
        db = get_session()
        try:
            pitches = _selected_pitcher_located_pitches(db)
            if not pitches:
                return None

            pitch_type_choice = input.loc_pitch_type()
            hand_choice = input.loc_batter_hand()
            color_by = input.loc_color_by()

            if pitch_type_choice != "all":
                pitches = [
                    p for p in pitches
                    if (p.pitch_type.type_name if p.pitch_type is not None else "Unspecified") == pitch_type_choice
                ]
            if hand_choice != "all":
                hands = get_batter_hands(db, pitches)
                pitches = [p for p in pitches if hands.get(p.game_pitch_id) == hand_choice]
            if not pitches:
                return None

            baseline = profile_queries.team_location_plus_baseline(db) if color_by == "result" else None
            own_idx_map = _own_pitch_index_map(db, int(input.pitcher_select()), int(input.game_select()))
            return _all_pitch_locations_figure(pitches, color_by, baseline, own_idx_map)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch Shape (Rapsodo) -- Sept 2026, restyled after Ryker's Pitch
    # Profiler reference image: Release Point (silhouette), Movement
    # Profile (with per-pitch-type Estimated Arm Angle rays), and Pitch
    # Frequency by batter handedness side by side, then a full physical
    # breakdown table below. Reuses the same pure chart/analytics
    # functions the Bullpen Dashboard and the Pitch Type Breakdown tabs
    # above already use (visualizations/bullpen_charts.py,
    # visualizations/pitcher_graphic.py, analytics/bullpen_metrics.py,
    # analytics/pitch_grading.py) -- no second implementation of any of
    # this math, just fed this game's own Rapsodo-linked pitches.
    #
    # Deliberately still lean on controls, per Ryker's own call: no
    # pitch-type/date filters, no individual-vs-average toggle -- fixed
    # defaults only. The Bullpen Dashboard's full interactive version
    # (arm-angle filters, mode toggles, etc.) stays the place a coach
    # digs deeper for bullpen sessions; the equivalent for intrasquad
    # games (season-wide, not just one outing) is planned for Pitcher
    # Profile, not built yet as of this section.
    #
    # No Barrel % column anywhere here -- GBO doesn't track batted-ball
    # exit velocity/launch angle, so there's no real GBO equivalent to
    # substitute (Ryker's own call on the metric gap: substitute a real
    # equivalent where one exists, skip what doesn't).
    # -------------------------------------------------------------------

    def _selected_pitcher_rapsodo_game_pitches(db):
        if "game_select" not in input or "pitcher_select" not in input:
            return None
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        pitches = (
            db.query(RapsodoPitch)
            .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
            .options(joinedload(RapsodoPitch.pitch_type), joinedload(RapsodoPitch.player))
            .filter(GamePitch.game_id == int(game_id_raw), RapsodoPitch.player_id == int(pitcher_id_raw))
            .order_by(RapsodoPitch.pitch_number)
            .all()
        )
        return pitches or None

    def _rapsodo_arm_angles_by_type(pitches, player):
        """[(label, color, angle_degrees), ...] for every pitch type with
        a computable Estimated Arm Angle -- same grouping/coloring
        bullpen_dashboard_display.py's own movement-chart panel uses, so
        the ray colors always agree with the dots they're drawn against."""
        type_groups = {}
        type_order = []
        for p in pitches:
            label = pitch_type_label(p)
            if label not in type_groups:
                type_groups[label] = []
                type_order.append(label)
            type_groups[label].append(p)
        out = []
        for label in type_order:
            angle, _n = average_estimated_arm_angle(type_groups[label], player)
            if angle is not None:
                out.append((label, color_for_pitch_label(label), angle))
        return out

    @render.ui
    def rapsodo_shape_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_shape":
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Pitch Shape (Rapsodo)")),
                ui.p(
                    "Release point, movement, and pitch mix by batter handedness for this outing, from this "
                    "game's Rapsodo-linked pitches.",
                    class_="text-muted small",
                ),
                ui.layout_columns(
                    ui.div(
                        ui.p("Release Point", style="font-weight:700; text-align:center;"),
                        ui.output_ui("rapsodo_release_point"),
                    ),
                    output_widget("rapsodo_movement_chart"),
                    col_widths=[5, 7],
                ),
                # Its own full-width row rather than a third equal column --
                # it's a horizontal bar chart with a label past the tip of
                # every bar, so a ~1/3-width column left it visibly cramped
                # (labels overlapping/squeezed even after fixing the hard
                # clipping). Full width gives every bar's label room.
                output_widget("rapsodo_pitch_frequency_chart"),
                ui.output_ui("rapsodo_pitch_shape_table"),
            )
        finally:
            db.close()

    @render.ui
    def rapsodo_release_point():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            type_groups = {}
            type_order = []
            for p in pitches:
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
                releases.append({
                    "label": label,
                    "color": color_for_pitch_label(label),
                    "side_ft": sum(sides) / len(sides),
                    "height_ft": sum(heights) / len(heights),
                    "count": len(group),
                })

            player = pitches[0].player
            player_height_in = float(player.height_in) if player is not None and player.height_in is not None else None
            throws = player.throws if player is not None else None
            children = [ui.HTML(pitcher_release_svg(releases, throws=throws or "R", height_in=player_height_in or 73))]
            if player is not None and player.height_in is None:
                children.append(ui.p(
                    "Using an average height -- add this pitcher's real height on the Players page for a more accurate figure.",
                    class_="text-muted small", style="text-align:center;",
                ))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def rapsodo_movement_chart():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        db = get_session()
        try:
            pitches = _selected_pitcher_rapsodo_game_pitches(db)
            if not pitches:
                return None
            player = pitches[0].player
            throws = player.throws if player is not None else None
            arm_angles_by_type = _rapsodo_arm_angles_by_type(pitches, player)
            return movement_chart(pitches, arm_angles_by_type=arm_angles_by_type, throws=throws)
        finally:
            db.close()

    @render_plotly
    def rapsodo_pitch_frequency_chart():
        """Pitch mix vs RHH/vs LHH, tornado-style -- same vs_rhh/vs_lhh
        split and Stuff+ baseline the Pitch Type Breakdown tabs above
        already compute (GamePitch.opponent_hand, profile_queries'
        team-wide Stuff+ baseline), just as one combined chart instead
        of separate tabs. Stuff+ shown per pitch type overall (not
        re-split by handedness) -- splitting the baseline further would
        shrink an already-thin single-outing sample per type into
        something too small to mean anything."""
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches:
                return None
            hands = get_batter_hands(db, pitches)
            vs_rhh = [p for p in pitches if hands.get(p.game_pitch_id) == "R"]
            vs_lhh = [p for p in pitches if hands.get(p.game_pitch_id) == "L"]
            if not vs_rhh and not vs_lhh:
                return None

            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            pitch_type_grades = {}
            for p in pitches:
                if p.pitch_type is None:
                    continue
                rap = rap_by_gp.get(p.game_pitch_id)
                if rap is None:
                    continue
                label = p.pitch_type.type_name
                s_val = stuff_plus(rap, stuff_baselines.get(label))
                if s_val is None:
                    continue
                grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": []})
                grp["n"] += 1
                grp["stuff_plus"].append(s_val)
            stuff_by_label = {row["Pitch Type"]: row["Stuff+"] for row in arsenal_summary(pitch_type_grades)} if pitch_type_grades else {}

            def _counts_by_type(subset):
                counts, order = {}, []
                for p in subset:
                    if p.pitch_type is None:
                        continue
                    label = p.pitch_type.type_name
                    if label not in counts:
                        counts[label] = 0
                        order.append(label)
                    counts[label] += 1
                return counts, order

            rhh_counts, rhh_order = _counts_by_type(vs_rhh)
            lhh_counts, lhh_order = _counts_by_type(vs_lhh)
            labels = list(dict.fromkeys(rhh_order + lhh_order))
            if not labels:
                return None
            rhh_vals = [rhh_counts.get(l, 0) for l in labels]
            lhh_vals = [lhh_counts.get(l, 0) for l in labels]
            colors = [color_for_pitch_label(l) for l in labels]

            def _bar_text(label, count):
                # A 0-length bar (this pitch type never thrown to that
                # handedness) still sits at x=0 -- giving it a label too
                # would overlap the other side's label right at the
                # zero line, especially for low counts. Skip it.
                if not count:
                    return ""
                stuff = stuff_by_label.get(label)
                return f"Count: {count}" + (f"  ({round(stuff)} Stuff+)" if stuff is not None else "")

            fig = go.Figure()
            # cliponaxis=False: "outside" bar text is positioned in data
            # units, not pixels, so with three narrow side-by-side charts
            # the longer "Count: N  (NNN Stuff+)" labels were getting hard
            # -clipped at the axis range boundary before this. Letting the
            # text draw past the axis (into the figure's own margin) fixes
            # the truncation regardless of window width.
            fig.add_trace(go.Bar(
                y=labels, x=[-v for v in lhh_vals], orientation="h", name="LHH",
                marker_color=colors, text=[_bar_text(l, v) for l, v in zip(labels, lhh_vals)],
                textposition="outside", hoverinfo="text", cliponaxis=False,
            ))
            fig.add_trace(go.Bar(
                y=labels, x=rhh_vals, orientation="h", name="RHH",
                marker_color=colors, text=[_bar_text(l, v) for l, v in zip(labels, rhh_vals)],
                textposition="outside", hoverinfo="text", cliponaxis=False,
            ))
            max_val = max(rhh_vals + lhh_vals + [1])
            fig.update_xaxes(range=[-max_val * 1.8, max_val * 1.8], zeroline=True, zerolinewidth=2, showticklabels=False)
            fig.add_annotation(text="← LHH", x=0, xref="paper", xanchor="left", y=1.08, yref="paper", showarrow=False)
            fig.add_annotation(text="RHH →", x=1, xref="paper", xanchor="right", y=1.08, yref="paper", showarrow=False)
            return apply_gbo_theme(fig, title="Pitch Frequency", height=420, showlegend=False, barmode="overlay")
        finally:
            db.close()

    @render.ui
    def rapsodo_pitch_shape_table():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        game_id_raw, pitcher_id_raw = input.game_select(), input.pitcher_select()
        if not game_id_raw or not pitcher_id_raw:
            return None
        db = get_session()
        try:
            pitcher = db.query(Player).filter(Player.player_id == int(pitcher_id_raw)).first()
            pitches = get_pitching_pitches(db, int(pitcher_id_raw), game_id=int(game_id_raw))
            if not pitches or pitcher is None:
                return None
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            rows = _pitch_shape_rows(pitches, rap_by_gp, stuff_baselines, pitcher)
            if not rows:
                return None
            return ui.div(
                ui_helpers.render_dict_table(rows),
                ui.p(
                    "VAA/HAA are estimated from release point, release angle, extension, and actual plate-crossing "
                    "location (not a direct Rapsodo measurement -- Rapsodo's own exported VAA/HAA columns are blank "
                    "in these files), same approach as the Bullpen Dashboard's arm-angle/VAA/HAA estimates.",
                    class_="text-muted small",
                ),
                ui.p(
                    f"Stuff+ needs at least {MIN_BASELINE_PITCHES} pitches of that type (team-wide) to be a stable "
                    "read -- a single outing rarely reaches that for a secondary pitch, shown anyway rather than hidden.",
                    class_="text-muted small",
                ),
            )
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch-by-Pitch -- Ryker's Sept 2026 report request: a per-pitch
    # list for this outing (not a per-type average like the sections
    # above), with a picker to drill into one pitch's Rapsodo numbers,
    # its actual location on the zone, its estimated arm angle (reusing
    # average_estimated_arm_angle on a one-pitch list rather than a new
    # single-pitch helper), and its charted result. The zone plot is
    # rendered as a static PNG via chart_helpers.fig_to_img (same
    # pattern Bullpen Dashboard uses) rather than a registered
    # render_plotly/output_widget, since it's a small, non-interactive,
    # per-selection image -- simpler than managing another widget id.
    # -------------------------------------------------------------------

    @render.ui
    def pitch_by_pitch_section():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_by_pitch":
            return None
        selected_game_id = int(input.game_select())
        selected_pitcher_id = int(input.pitcher_select())
        db = get_session()
        try:
            pitches = get_pitching_pitches(db, selected_pitcher_id, game_id=selected_game_id)
            if not pitches:
                return None
            pitches = sorted(pitches, key=lambda p: p.pitch_sequence)
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, [p.game_pitch_id for p in pitches])

            rows = []
            choices = {}
            # Per-pitcher pitch number (Ryker, Sept 2026: "I want the pitch
            # number to be specific to that specific pitcher" -- pitch_sequence
            # is the game-wide count across both pitchers, e.g. the 52nd pitch
            # of the game could be this pitcher's 5th). `pitches` here is
            # already filtered to this one pitcher+game and sorted above, so
            # the pitcher-specific number is just its position in this list.
            for own_idx, p in enumerate(pitches, start=1):
                label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"
                rap = rap_by_gp.get(p.game_pitch_id)
                rows.append({
                    "#": own_idx,
                    "Pitch Type": label,
                    "Velo": f"{float(rap.velocity):.1f} mph" if rap is not None and rap.velocity is not None else "—",
                    "Result": p.pitch_outcome or "—",
                    "AB Outcome": p.ab_outcome if (p.ends_plate_appearance and p.ab_outcome) else "—",
                })
                choices[str(p.game_pitch_id)] = f"Pitch {own_idx} — {label} — {p.pitch_outcome or 'unknown result'}"

            return ui.div(
                ui.p(ui.strong("Pitch-by-Pitch")),
                ui.p(
                    "Every pitch in this outing, in order. Pick one below to see its Rapsodo numbers, actual "
                    "location, and estimated arm angle.",
                    class_="text-muted small",
                ),
                ui_helpers.render_dict_table(rows),
                ui.input_select("selected_pitch_id", "Pitch detail", choices=choices),
                ui.output_ui("pitch_detail_card"),
            )
        finally:
            db.close()

    @render.ui
    def pitch_detail_card():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("game_select" in input)
        req("pitcher_select" in input)
        req("report_section" in input)
        if input.report_section() != "pitch_by_pitch":
            return None
        req("selected_pitch_id" in input)
        selected_raw = input.selected_pitch_id()
        if not selected_raw:
            return None
        db = get_session()
        try:
            p = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type))
                .filter(GamePitch.game_pitch_id == int(selected_raw))
                .first()
            )
            if p is None:
                return None
            # Same per-pitcher numbering as pitch_by_pitch_section's own_idx
            # above, recomputed here since this card is a separate render
            # keyed only on the selected game_pitch_id (falls back to the
            # game-wide pitch_sequence in the unexpected case this pitch
            # isn't found in the pitcher's own list).
            own_pitches = sorted(
                get_pitching_pitches(db, int(input.pitcher_select()), game_id=int(input.game_select())),
                key=lambda gp: gp.pitch_sequence,
            )
            own_idx = next(
                (i for i, gp in enumerate(own_pitches, start=1) if gp.game_pitch_id == p.game_pitch_id),
                p.pitch_sequence,
            )
            pitcher = db.query(Player).filter(Player.player_id == int(input.pitcher_select())).first()
            rap = db.query(RapsodoPitch).filter(RapsodoPitch.game_pitch_id == p.game_pitch_id).first()
            label = p.pitch_type.type_name if p.pitch_type is not None else "Unspecified"

            has_intended = p.intended_plate_x is not None and p.intended_plate_z is not None
            has_actual = p.actual_plate_x is not None and p.actual_plate_z is not None

            # Batter for this specific pitch (Sept 2026, Ryker: "have a
            # batter graphic based on the hitter that was up"). Hand comes
            # from game_stats.get_batter_hands() -- the same canonical
            # resolution the vs-RHH/vs-LHH splits elsewhere on this page
            # already use, NOT the raw GamePitch.opponent_hand column
            # (wrong for three-squad intrasquad pitches, see that
            # function's own docstring). Name resolution mirrors its
            # same batter_id convention (our_player_id is the batter when
            # is_our_team_batting is True -- reachable here for a
            # two-squad intrasquad game where THIS pitcher is tracked as
            # the "opponent" side while our own roster batted;
            # opponent_our_player_id otherwise, else a named
            # external-opponent OpponentPlayer row) so the name and hand
            # always describe the same person; falls back to hand-only
            # when no name is on file (a real opponent tracked by hand
            # alone, per OpponentPlayer's own docstring).
            batter_hand = get_batter_hands(db, [p]).get(p.game_pitch_id)
            batter_id = p.our_player_id if p.is_our_team_batting else p.opponent_our_player_id
            batter_name = None
            if batter_id is not None:
                batter_player = db.query(Player).filter(Player.player_id == batter_id).first()
                if batter_player is not None:
                    batter_name = f"{batter_player.first_name} {batter_player.last_name}"
            elif p.opponent_player_id is not None:
                opp_player = db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id == p.opponent_player_id).first()
                if opp_player is not None:
                    batter_name = opp_player.player_name
            if batter_name and batter_hand:
                batter_caption = f"vs. {batter_name} ({batter_hand})"
            elif batter_name:
                batter_caption = f"vs. {batter_name}"
            elif batter_hand:
                batter_caption = f"vs. {batter_hand}HH"
            else:
                batter_caption = None

            if has_intended:
                location_fig = _pitch_location_figure(
                    intended_x=float(p.intended_plate_x), intended_z=float(p.intended_plate_z),
                    actual_x=float(p.actual_plate_x) if has_actual else None,
                    actual_z=float(p.actual_plate_z) if has_actual else None,
                    color=color_for_pitch_label(label),
                    batter_hand=batter_hand,
                )
                location_block = ui.div(
                    ui.p("Location", style="font-weight:700; text-align:center;"),
                    chart_helpers.fig_to_img(location_fig, width=450, height=450),
                    ui.p(batter_caption, class_="text-muted small", style="text-align:center;") if batter_caption else None,
                )
            else:
                location_block = ui.div(
                    ui.p("Location", style="font-weight:700; text-align:center;"),
                    ui.p("Not located yet.", class_="text-muted small", style="text-align:center;"),
                    ui.p(batter_caption, class_="text-muted small", style="text-align:center;") if batter_caption else None,
                )

            # Trimmed from the full Rapsodo readout down to Velocity plus
            # command/outcome context (Ryker, Sept 2026: "instead of
            # showing all the rapsodo data i just want it to show
            # velocity, miss distance, ball or strike") -- Spin Rate/IVB/
            # HB/VAA/HAA/Arm Angle are still available in aggregate on
            # this same page's Pitch Shape (Rapsodo) section, just not
            # repeated per-pitch here. Added on top of Ryker's three:
            # Count (the balls-strikes this pitch was thrown in -- context
            # for why it was a take/swing) and Miss Direction alongside
            # Miss Distance (same intended-vs-actual numbers already
            # needed for the distance, showing which way it missed too,
            # not just how far), reusing pitch_location_stats.py's own
            # inches-and-direction convention (Arm-side/Glove-side when
            # throws is known, else raw 3B-side/1B-side).
            if has_intended and has_actual:
                # Zone-based miss (Ryker, Sept 2026): measured from the
                # called Level-Zone cell's nearest edge, not the exact
                # intended point -- see analytics/command_metrics.compute_miss
                # for the full reasoning. Reuses the same compute_miss/
                # classify_miss_direction the Command Target Zones
                # section below already calls, instead of a third inline
                # calc with its own point-to-point math and its own
                # Arm-side/Glove-side labeling.
                throws = pitcher.throws if pitcher is not None else None
                dx, dz, miss_distance = command_metrics.compute_miss(
                    p.intended_plate_x, p.intended_plate_z, p.actual_plate_x, p.actual_plate_z,
                )
                miss_direction = command_metrics.classify_miss_direction(dx, dz, throws)
            else:
                miss_distance = None
                miss_direction = None

            count_str = (
                f"{p.balls_before}-{p.strikes_before}"
                if p.balls_before is not None and p.strikes_before is not None
                else None
            )

            summary_block = ui.div(
                ui.p("Summary", style="font-weight:700;"),
                ui_helpers.render_kpi_cards([
                    {"label": "Velocity", "value": f"{float(rap.velocity):.1f} mph" if (rap is not None and rap.velocity is not None) else "—"},
                    {"label": "Count", "value": count_str or "—"},
                    {"label": "Result", "value": p.pitch_outcome or "—"},
                    {"label": "Miss Distance", "value": f'{miss_distance:.1f}"' if miss_distance is not None else "—"},
                    {"label": "Miss Direction", "value": miss_direction or "—"},
                ]),
            )
            if rap is None:
                summary_block = ui.div(summary_block, ui.p("No Rapsodo reading linked to this pitch -- Velocity above is unavailable.", class_="text-muted small"))

            result_bits = []
            if p.contact_quality:
                result_bits.append(f"Contact Quality: {p.contact_quality}")
            if p.batted_ball_type:
                result_bits.append(f"Batted Ball: {p.batted_ball_type}")
            if p.ends_plate_appearance and p.ab_outcome:
                result_bits.append(f"AB Outcome: {p.ab_outcome}")

            return ui.div(
                ui.hr(),
                ui.p(ui.strong(f"Pitch {own_idx} — {label}")),
                ui.layout_columns(
                    location_block,
                    ui.div(
                        summary_block,
                        ui.p(" · ".join(result_bits), class_="text-muted small", style="margin-top:12px;"),
                    ),
                    col_widths=[5, 7],
                ),
            )
        finally:
            db.close()
