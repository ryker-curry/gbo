"""
GBO -- My Bullpens module (Player role only).

Direct port of pages/player_bullpens.py -- read-only view of the
player's own bullpen sessions: a type-adaptive per-session summary
(pitch count/velocity/movement/execution, depending on bullpen type),
shared charts, pitch video, plus (for sessions with imported Rapsodo
data) an inline "Bullpen Dashboard" section reusing the same rendering
as the future coach-facing standalone page -- see
bullpen_dashboard_display.py's module docstring for the shared-module
rationale. (Named "display", not "render", specifically so it can't
collide on import with the repo root's own bullpen_dashboard_render.py
-- see that module's docstring for why the name has to differ, not just
live in a different directory.)

Charts here (movement/release-point/velocity-by-type bar, all fixed
dark theme, no on_select handling in the original) render as static
PNGs via chart_helpers.fig_to_img, same technique used throughout this
migration for decorative Plotly output.

Per-session accordions and per-session video pickers use dynamic,
session-scoped input/output IDs, same lazy-registration idiom as
player_hitting.py/training_routines.py elsewhere in this migration.
"""

from shiny import module, ui, render, reactive, req
import plotly.graph_objects as go
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, User, BullpenSession, HitterSwing, RapsodoPitch, BullpenPitch, Assessment, AssessmentResult

import ui_helpers
import chart_helpers
import bullpen_dashboard_display

# Same fixed generic strike-zone boundaries used on Bullpen Tracking.
ZONE_SIDE_BOUNDS = (-0.283, 0.283)
ZONE_HEIGHT_BOUNDS = (2.167, 2.833)
BURY_HEIGHT_THRESHOLD = 1.5  # ft -- below this counts as "buried", regardless of target

_SIDE_THIRD = ZONE_SIDE_BOUNDS[1] - ZONE_SIDE_BOUNDS[0]
FULL_ZONE_SIDE = (ZONE_SIDE_BOUNDS[0] - _SIDE_THIRD, ZONE_SIDE_BOUNDS[1] + _SIDE_THIRD)
_HEIGHT_THIRD = ZONE_HEIGHT_BOUNDS[1] - ZONE_HEIGHT_BOUNDS[0]
FULL_ZONE_HEIGHT = (ZONE_HEIGHT_BOUNDS[0] - _HEIGHT_THIRD, ZONE_HEIGHT_BOUNDS[1] + _HEIGHT_THIRD)

PITCH_TYPE_COLORS = [
    "#BF1E2D", "#D4AF37", "#4C6EF5", "#37B24D", "#F76707", "#AE3EC9", "#0CA678", "#E64980",
]

CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}


def _render_strike_zone_plot(title, data_by_type):
    fig = go.Figure()
    fig.add_shape(type="rect", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1],
                  line=dict(color="#FFFDE5", width=2), fillcolor="rgba(0,0,0,0)")
    for x in ZONE_SIDE_BOUNDS:
        fig.add_shape(type="line", x0=x, x1=x, y0=FULL_ZONE_HEIGHT[0], y1=FULL_ZONE_HEIGHT[1], line=dict(color="#5A5A5A", width=1, dash="dot"))
    for y in ZONE_HEIGHT_BOUNDS:
        fig.add_shape(type="line", x0=FULL_ZONE_SIDE[0], x1=FULL_ZONE_SIDE[1], y0=y, y1=y, line=dict(color="#5A5A5A", width=1, dash="dot"))

    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e["Plate Side"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        ys = [e["Plate Height"] for e in entries if "Plate Side" in e and "Plate Height" in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=10, opacity=0.75, line=dict(color="#1E1E1E", width=1)),
            hovertemplate=f"{pitch_type}<br>Side: %{{x:.2f}} ft<br>Height: %{{y:.2f}} ft<extra></extra>",
        ))

    fig.update_layout(
        title=title,
        xaxis_title="Plate Side (ft)", yaxis_title="Plate Height (ft)",
        showlegend=True, height=480,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[FULL_ZONE_SIDE[0] - 1, FULL_ZONE_SIDE[1] + 1], scaleanchor="y", scaleratio=1),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A", range=[0, FULL_ZONE_HEIGHT[1] + 1.5]),
        margin=dict(t=40, b=40, l=40, r=40),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=480)


def _render_scatter_with_averages(title, x_label, y_label, data_by_type, x_key, y_key):
    fig = go.Figure()
    for i, (pitch_type, entries) in enumerate(data_by_type.items()):
        color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
        xs = [e[x_key] for e in entries if x_key in e and y_key in e]
        ys = [e[y_key] for e in entries if x_key in e and y_key in e]
        if not xs:
            continue
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers", name=pitch_type,
            marker=dict(color=color, size=8, opacity=0.35),
            showlegend=False,
            hovertemplate=f"{pitch_type}<br>{x_label}: %{{x}}<br>{y_label}: %{{y}}<extra></extra>",
        ))
        avg_x, avg_y = sum(xs) / len(xs), sum(ys) / len(ys)
        fig.add_trace(go.Scatter(
            x=[avg_x], y=[avg_y], mode="markers+text", name=pitch_type,
            marker=dict(color=color, size=18, line=dict(color="#FFFDE5", width=2)),
            text=[pitch_type], textposition="top center",
            textfont=dict(color="#FFFDE5", size=12),
            hovertemplate=f"{pitch_type} average<br>{x_label}: %{{x:.1f}}<br>{y_label}: %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(
        title=title,
        xaxis_title=x_label, yaxis_title=y_label,
        showlegend=False, height=420,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        yaxis=dict(gridcolor="#3A3A3A", zerolinecolor="#3A3A3A"),
        margin=dict(t=40, b=40, l=40, r=40),
    )
    return chart_helpers.fig_to_img(fig, width=700, height=420)


def _compute_zone_scores(swings):
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def _render_zone_heatmap(title, zone_scores, zone_counts, invert_colors=False, subtitle=None):
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_scores.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_scores[zid]:.1f}<br>({zone_counts[zid]})" if zid in zone_scores else "—" for zid in row] for row in zone_grid]

    colorscale = "RdYlGn_r" if invert_colors else "RdYlGn"
    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale=colorscale, zmin=0, zmax=3, showscale=True,
        colorbar=dict(title="Avg score", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    children = [chart_helpers.fig_to_img(fig, width=700, height=380)]
    if subtitle:
        children.append(ui.p(subtitle, class_="text-muted small"))
    return ui.div(*children)


def _render_execution_heatmap(title, zone_rates, zone_counts, subtitle=None):
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_rates.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_rates[zid]:.0f}%<br>({zone_counts[zid]})" if zid in zone_rates else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn", zmin=0, zmax=100, showscale=True,
        colorbar=dict(title="Hit rate %", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    children = [chart_helpers.fig_to_img(fig, width=700, height=380)]
    if subtitle:
        children.append(ui.p(subtitle, class_="text-muted small"))
    return ui.div(*children)


def _compute_execution_accuracy(swings):
    by_zone = {}
    for s in swings:
        if s.intended_zone is None or s.pitch_zone is None:
            continue
        by_zone.setdefault(s.intended_zone, []).append(1 if s.intended_zone == s.pitch_zone else 0)
    rates = {z: 100 * sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return rates, counts


def _compute_actual_zone(plate_side_ft, plate_height_ft):
    if plate_height_ft < BURY_HEIGHT_THRESHOLD:
        return 0
    if plate_side_ft < ZONE_SIDE_BOUNDS[0]:
        col = 0
    elif plate_side_ft > ZONE_SIDE_BOUNDS[1]:
        col = 2
    else:
        col = 1
    if plate_height_ft > ZONE_HEIGHT_BOUNDS[1]:
        row = 0
    elif plate_height_ft < ZONE_HEIGHT_BOUNDS[0]:
        row = 2
    else:
        row = 1
    return row * 3 + col + 1


def _summarize(b):
    s_linked = 0
    s_hits = 0
    s_hits_by_type = {}
    s_counts_by_type = {}
    s_velos_by_type = {}
    s_movement_by_type = {}
    for p in b.pitches:
        pt_name = p.pitch_type.type_name if p.pitch_type else "—"
        s_counts_by_type[pt_name] = s_counts_by_type.get(pt_name, 0) + 1
        if p.linked_assessment:
            s_linked += 1
            results = {r.test_type.test_name: float(r.value) for r in p.linked_assessment.results}
            plate_side = results.get("Plate Side")
            plate_height = results.get("Plate Height")
            if plate_side is not None and plate_height is not None:
                a_zone = _compute_actual_zone(plate_side, plate_height)
                if a_zone == p.target_zone:
                    s_hits += 1
                    s_hits_by_type[pt_name] = s_hits_by_type.get(pt_name, 0) + 1
            v = results.get("Velocity")
            if v is not None:
                s_velos_by_type.setdefault(pt_name, []).append(v)
            s_movement_by_type.setdefault(pt_name, []).append(results)
    return {
        "linked": s_linked, "hits": s_hits, "hits_by_type": s_hits_by_type,
        "counts_by_type": s_counts_by_type, "velos_by_type": s_velos_by_type,
        "movement_by_type": s_movement_by_type, "total_pitches": len(b.pitches),
    }


@module.ui
def player_bullpens_ui():
    return ui.div(
        ui_helpers.page_header("My Bullpens"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_bullpens_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _registered_video_outputs = set()
    _registered_chart_outputs = set()
    # bullpen_ids whose per-session charts have been explicitly requested
    # via that session's "Show charts" button -- see _register_chart_
    # section below. Every chart in every session's accordion panel used
    # to render unconditionally on every page load, even panels that were
    # never expanded (Shiny still builds all panel content up front
    # regardless of collapsed/expanded state); a player with several
    # data-heavy sessions could mean dozens of kaleido chart renders on
    # one page load. Same "gate behind an explicit click" fix already
    # applied to Bullpen Dashboard for the same reason.
    _charts_shown = reactive.Value(frozenset())

    def _my_player(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        return db.query(Player).filter(Player.player_id == me.player_id).first()

    def _get_bullpen_dashboard_target(input):
        """Resolves the "View" picker (defined by _bp_dashboard_body
        below) into a bullpen_dashboard_display target dict -- req()s on
        the view choice itself so both of bullpen_dashboard_display's
        registered outputs simply render nothing until a view is picked
        (same "not applicable yet" contract as its docstring)."""
        req("bp_view_choice" in input)
        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None:
                return None
            choice = input.bp_view_choice()
            if choice == "__all__":
                rapsodo_bullpen_ids = [
                    row[0] for row in
                    db.query(RapsodoPitch.bullpen_id).filter(RapsodoPitch.player_id == my_player.player_id).distinct().all()
                ]
                return {"kind": "combined", "player": my_player, "bullpen_ids": rapsodo_bullpen_ids}
            return {"kind": "session", "bullpen_id": int(choice)}
        finally:
            db.close()

    _bp_dashboard_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "bp", _get_bullpen_dashboard_target,
    )

    @render.ui
    def bp_dashboard_body():
        """View picker for the inline Bullpen Dashboard section -- a
        separate render.ui block from _get_bullpen_dashboard_target's
        consumers (bullpen_dashboard_display's own registered outputs),
        same ordering-hazard-safe split as everywhere else."""
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None or not my_player.is_pitcher:
                return None
            sessions = (
                db.query(BullpenSession)
                .options(joinedload(BullpenSession.bullpen_type))
                .filter(BullpenSession.player_id == my_player.player_id)
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            rapsodo_bullpen_ids = {
                row[0] for row in
                db.query(RapsodoPitch.bullpen_id).filter(RapsodoPitch.player_id == my_player.player_id).distinct().all()
            }
            if not rapsodo_bullpen_ids:
                return None
            rapsodo_sessions = [b for b in sessions if b.bullpen_id in rapsodo_bullpen_ids]

            choices = {"__all__": "All Sessions (Combined)"}
            for b in rapsodo_sessions:
                type_label = b.bullpen_type.type_name if b.bullpen_type else "—"
                choices[str(b.bullpen_id)] = f"{b.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}"

            return ui.div(
                ui.h5("Bullpen Dashboard", class_="gbo-section-title"),
                ui.p(
                    "Pick a specific session for its full pitch-type summary, filters, and charts -- "
                    "or view every session combined.",
                    class_="text-muted small",
                ),
                ui.input_select("bp_view_choice", "View", choices=choices),
                _bp_dashboard_fragment,
                ui.hr(),
            )
        finally:
            db.close()

    @render.ui
    def body():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() != "Player":
            return ui.p("This page is only available to Player accounts.", class_="text-danger")

        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None:
                return ui.p("Your player profile isn't linked yet. Check with an administrator.", class_="text-muted")
            if not my_player.is_pitcher:
                return ui.p("This page is only available to pitchers -- see My Hitting instead.", class_="text-danger")

            sessions = (
                db.query(BullpenSession)
                .options(
                    joinedload(BullpenSession.bullpen_type),
                    # Was just joinedload(BullpenSession.pitches) -- pitches
                    # loaded eagerly, but nothing about them did (pitch_type,
                    # linked_assessment, that assessment's results, each
                    # result's test_type). _summarize() below touches every
                    # one of those per pitch, so with those left as lazy
                    # relationships, a page with several sessions of several
                    # pitches each fired 100+ individual queries -- the same
                    # N+1 pattern bucket_system.py had (see that fix's
                    # commit). Chaining joinedload all the way down collapses
                    # this back to a small constant number of queries.
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.pitch_type),
                    joinedload(BullpenSession.pitches).joinedload(BullpenPitch.linked_assessment)
                    .joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                )
                .filter(BullpenSession.player_id == my_player.player_id)
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            if not sessions:
                return ui_helpers.empty_state("No bullpen sessions recorded yet.")

            # Precompute every session's summary once -- previously
            # _summarize(b) ran once for a session as "current" AND again
            # as "previous" whenever a later (older) same-bullpen_type
            # session needed it for its delta, doubling that work for any
            # session with a same-type predecessor.
            summaries_by_id = {b.bullpen_id: _summarize(b) for b in sessions}

            sections = [ui.output_ui("bp_dashboard_body")]

            panels = []
            for idx, b in enumerate(sessions):
                bp_type_name = b.bullpen_type.type_name if b.bullpen_type else "—"
                date_label = b.session_date.strftime("%Y-%m-%d (%a)")
                panel_children = []
                if b.overall_notes:
                    panel_children.append(ui.p(b.overall_notes, class_="text-muted small"))

                if not b.pitches:
                    panel_children.append(ui.p("No pitches recorded for this session.", class_="text-muted small"))
                else:
                    current = summaries_by_id[b.bullpen_id]
                    hits = current["hits"]
                    linked_count = current["linked"]
                    counts_by_type = current["counts_by_type"]
                    hits_by_type = current["hits_by_type"]
                    velos_by_type = current["velos_by_type"]
                    movement_by_type = current["movement_by_type"]

                    previous_session = next((sessions[j] for j in range(idx + 1, len(sessions)) if sessions[j].bullpen_type_id == b.bullpen_type_id), None)
                    prev_summary = summaries_by_id[previous_session.bullpen_id] if previous_session else None
                    prev_date_label = previous_session.session_date.strftime("%Y-%m-%d (%a)") if previous_session else None

                    panel_children.append(ui.p(ui.strong("Summary")))
                    if bp_type_name == "Velocity":
                        all_velos = [v for vs in velos_by_type.values() for v in vs]
                        if not all_velos:
                            panel_children.append(ui.p("No velocity data linked yet for this session.", class_="text-muted small"))
                        else:
                            avg_velo = sum(all_velos) / len(all_velos)
                            max_velo = max(all_velos)
                            avg_delta_str = max_delta_str = None
                            if prev_summary and prev_summary["velos_by_type"]:
                                prev_all = [v for vs in prev_summary["velos_by_type"].values() for v in vs]
                                if prev_all:
                                    avg_delta_str = f"{avg_velo - (sum(prev_all) / len(prev_all)):+.1f} vs {prev_date_label}"
                                    max_delta_str = f"{max_velo - max(prev_all):+.1f} vs {prev_date_label}"
                            panel_children.append(ui_helpers.render_kpi_cards([
                                {"label": "Max velocity", "value": f"{max_velo:.1f} mph", "delta": max_delta_str, "delta_positive": True},
                                {"label": "Average velocity", "value": f"{avg_velo:.1f} mph", "delta": avg_delta_str, "delta_positive": True},
                            ]))
                            by_type_lines = [f"{pt}: avg {sum(vs)/len(vs):.1f} mph, max {max(vs):.1f} mph" for pt, vs in velos_by_type.items()]
                            panel_children.append(ui.p(" · ".join(by_type_lines)))
                    elif bp_type_name == "Pitch Design":
                        if not movement_by_type:
                            panel_children.append(ui.p("No movement data linked yet for this session.", class_="text-muted small"))
                        else:
                            def _avg_of(entries, key):
                                vals = [e[key] for e in entries if key in e]
                                return round(sum(vals) / len(vals), 1) if vals else None

                            summary_rows = []
                            for pt, entries in movement_by_type.items():
                                row = {"Pitch Type": pt, "Count": len(entries)}
                                prev_entries = prev_summary["movement_by_type"].get(pt) if prev_summary else None
                                for label, key in [
                                    ("Avg Spin Rate (rpm)", "Spin Rate"),
                                    ("Avg Horizontal Break (in)", "Horizontal Break"),
                                    ("Avg Induced Vert. Break (in)", "Induced Vertical Break"),
                                ]:
                                    cur_avg = _avg_of(entries, key)
                                    row[label] = cur_avg if cur_avg is not None else "—"
                                    if cur_avg is not None and prev_entries:
                                        prev_avg = _avg_of(prev_entries, key)
                                        if prev_avg is not None:
                                            row[f"{label} vs last"] = f"{round(cur_avg - prev_avg, 1):+.1f}"
                                summary_rows.append(row)
                            panel_children.append(ui_helpers.render_dict_table(summary_rows))
                            if previous_session:
                                panel_children.append(ui.p(f'"vs last" compares to the previous {bp_type_name} session on {prev_date_label}.', class_="text-muted small"))
                    elif bp_type_name == "Command":
                        if linked_count == 0:
                            panel_children.append(ui.p("No pitches linked to Rapsodo data yet for this session.", class_="text-muted small"))
                        else:
                            pct = round(100 * hits / linked_count)
                            delta_str = None
                            if prev_summary and prev_summary["linked"] > 0:
                                prev_pct = round(100 * prev_summary["hits"] / prev_summary["linked"])
                                delta_str = f"{pct - prev_pct:+d} pts vs {prev_date_label}"
                            panel_children.append(ui_helpers.render_kpi_cards([
                                {"label": "Overall execution", "value": f"{hits}/{linked_count} ({pct}%)", "delta": delta_str, "delta_positive": (delta_str is not None and not delta_str.startswith("-"))},
                            ]))
                            by_type_lines = [f"{pt}: {hits_by_type.get(pt, 0)}/{count}" for pt, count in counts_by_type.items()]
                            panel_children.append(ui.p(" · ".join(by_type_lines)))
                    else:
                        delta = len(b.pitches) - prev_summary["total_pitches"] if prev_summary else None
                        panel_children.append(ui_helpers.render_kpi_cards([
                            {"label": "Total pitches", "value": str(len(b.pitches)), "delta": (f"{delta:+d} vs {prev_date_label}" if delta is not None else None), "delta_positive": (delta is not None and delta >= 0)},
                        ]))
                        by_type_lines = [f"{pt}: {count}" for pt, count in counts_by_type.items()]
                        panel_children.append(ui.p(" · ".join(by_type_lines)))

                    # --- Charts (gated behind "Show charts" -- see
                    # _register_chart_section below) ---
                    movement_data = current["movement_by_type"]
                    has_movement = any("Horizontal Break" in e and "Induced Vertical Break" in e for entries in movement_data.values() for e in entries)
                    has_release = any("Release Side" in e and "Release Height" in e for entries in movement_data.values() for e in entries)
                    has_location = any("Plate Side" in e and "Plate Height" in e for entries in movement_data.values() for e in entries)
                    has_velocity = any(vs for vs in current["velos_by_type"].values())

                    if has_movement or has_release or has_location or has_velocity:
                        panel_children.append(ui.p(ui.strong("Charts")))
                        panel_children.append(ui.output_ui(f"bp_charts_section_{b.bullpen_id}"))
                        _register_chart_section(
                            b.bullpen_id, movement_data, current["velos_by_type"],
                            has_movement, has_release, has_location, has_velocity,
                        )

                    # --- Pitch video ---
                    video_pitches = [p for p in b.pitches if p.video_url]
                    if video_pitches:
                        video_key = f"bp_video_choice_{b.bullpen_id}"
                        choices = {
                            str(p.bullpen_pitch_id): f"Pitch #{p.pitch_number}" + (f" ({p.pitch_type.type_name})" if p.pitch_type else "")
                            for p in video_pitches
                        }
                        panel_children.append(ui.p(ui.strong(f"Pitch video ({len(video_pitches)} of {len(b.pitches)} pitches)")))
                        panel_children.append(ui.input_select(video_key, "Watch", choices=choices))
                        panel_children.append(ui.output_ui(f"video_player_{b.bullpen_id}"))
                        _register_video_player(b.bullpen_id, video_key, video_pitches)

                panels.append(ui.accordion_panel(f"{date_label} — {bp_type_name} ({len(b.pitches)} pitches)", ui.div(*panel_children)))

            sections.append(ui.accordion(*panels, open=False, id=None))

            sections.append(ui.hr())
            sections.append(ui.h5("My zone heatmap", class_="gbo-section-title"))
            sections.append(ui.output_ui("my_zone_heatmap_section"))

            return ui.div(*sections)
        finally:
            db.close()

    def _register_chart_section(bullpen_id, movement_data, velos_by_type, has_movement, has_release, has_location, has_velocity):
        """Registers this session's "Show charts" gate exactly once (per
        bullpen_id, same dedup-guard idiom as _register_video_player
        below) -- chart data is captured in the closure at first
        registration, same accepted staleness tradeoff _register_video_player
        already has for pitches_by_id (this session's pitches don't change
        after import, so it's a non-issue in practice)."""
        gate_output_id = f"bp_charts_section_{bullpen_id}"
        if gate_output_id in _registered_chart_outputs:
            return
        _registered_chart_outputs.add(gate_output_id)
        show_charts_key = f"bp_show_charts_{bullpen_id}"
        location_output_id = f"bp_chart_location_{bullpen_id}"
        movement_output_id = f"bp_chart_movement_{bullpen_id}"
        release_output_id = f"bp_chart_release_{bullpen_id}"
        velocity_output_id = f"bp_chart_velocity_{bullpen_id}"

        @output(id=gate_output_id)
        @render.ui
        def _charts_gate():
            """Cheap orchestration only (no chart rendering here) --
            either the "Show charts" button, or a placeholder per
            applicable chart type, each its own output (registered
            below) so they stream in individually instead of this one
            output blocking until every chart in the session is done.
            Same fix as bullpen_dashboard_display.py's chart outputs,
            for the same "~30 seconds with nothing visible" complaint."""
            if bullpen_id not in _charts_shown():
                return ui.input_action_button(show_charts_key, "Show charts", class_="btn-outline-secondary mt-2")
            children = []
            if has_location:
                children.append(ui.output_ui(location_output_id))
            children.append(ui.p("Bold labeled markers are the average per pitch type; smaller dots are individual pitches.", class_="text-muted small"))
            if has_movement:
                children.append(ui.output_ui(movement_output_id))
            if has_release:
                children.append(ui.output_ui(release_output_id))
            if has_velocity:
                children.append(ui.output_ui(velocity_output_id))
            return ui.div(*children)

        @reactive.effect
        @reactive.event(input[show_charts_key])
        def _on_show_charts():
            _charts_shown.set(_charts_shown() | {bullpen_id})

        if has_location:
            @output(id=location_output_id)
            @render.ui
            def _chart_location():
                if bullpen_id not in _charts_shown():
                    return None
                return ui.div(
                    _render_strike_zone_plot("Actual Pitch Locations", movement_data),
                    ui.p("Where pitches actually crossed the plate -- from real Rapsodo Plate Side/Height, not the called intended zone.", class_="text-muted small"),
                )

        if has_movement:
            @output(id=movement_output_id)
            @render.ui
            def _chart_movement():
                if bullpen_id not in _charts_shown():
                    return None
                return _render_scatter_with_averages(
                    "Movement Plot", "Horizontal Break (in)", "Induced Vertical Break (in)",
                    movement_data, "Horizontal Break", "Induced Vertical Break",
                )

        if has_release:
            @output(id=release_output_id)
            @render.ui
            def _chart_release():
                if bullpen_id not in _charts_shown():
                    return None
                return _render_scatter_with_averages(
                    "Release Point (tunneling)", "Release Side (ft)", "Release Height (ft)",
                    movement_data, "Release Side", "Release Height",
                )

        if has_velocity:
            @output(id=velocity_output_id)
            @render.ui
            def _chart_velocity():
                if bullpen_id not in _charts_shown():
                    return None
                velo_fig = go.Figure()
                for i, (pt_name, vs) in enumerate(velos_by_type.items()):
                    if not vs:
                        continue
                    color = PITCH_TYPE_COLORS[i % len(PITCH_TYPE_COLORS)]
                    velo_fig.add_trace(go.Bar(x=[pt_name], y=[sum(vs) / len(vs)], marker_color=color, showlegend=False, name=pt_name))
                velo_fig.update_layout(
                    title="Average Velocity by Pitch Type", yaxis_title="mph",
                    plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E", font=dict(color="#FFFDE5"),
                    yaxis=dict(gridcolor="#3A3A3A"), height=380, margin=dict(t=40, b=40, l=40, r=40),
                )
                return chart_helpers.fig_to_img(velo_fig, width=700, height=380)

    def _register_video_player(bullpen_id, video_key, video_pitches):
        output_id = f"video_player_{bullpen_id}"
        if output_id in _registered_video_outputs:
            return
        _registered_video_outputs.add(output_id)
        pitches_by_id = {p.bullpen_pitch_id: p for p in video_pitches}

        @output(id=output_id)
        @render.ui
        def _player():
            req(video_key in input)
            p = pitches_by_id.get(int(input[video_key]()))
            if p is None:
                return None
            children = [ui.tags.video(ui.tags.source(src=p.video_url), controls=True, style="max-width:100%;")]
            if p.notes:
                children.append(ui.p(p.notes, class_="text-muted small"))
            return ui.div(*children)

    @render.ui
    def my_zone_heatmap_section():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None or not my_player.is_pitcher:
                return None

            my_pitcher_swings = (
                db.query(HitterSwing)
                .filter(HitterSwing.pitcher_player_id == my_player.player_id)
                .all()
            )
            if not my_pitcher_swings:
                return ui_helpers.empty_state("No swings logged against you yet on Hitter Tracking.")

            sections = []
            my_zone_scores, my_zone_counts = _compute_zone_scores(my_pitcher_swings)
            if not my_zone_scores:
                sections.append(ui_helpers.empty_state("No swings with both a zone and contact quality recorded against you yet."))
            else:
                sections.append(_render_zone_heatmap(
                    "Opponent contact quality by zone", my_zone_scores, my_zone_counts, invert_colors=True,
                    subtitle="Green = pitches hardest to hit here (good for you), red = hit hardest here. Number in parentheses is swing count.",
                ))

                sections.append(ui.hr())
                sections.append(ui.p("How well you execute to your intended locations with a hitter in the box (from Hitter Tracking).", class_="text-muted small"))
                my_exec_rates, my_exec_counts = _compute_execution_accuracy(my_pitcher_swings)
                if not my_exec_rates:
                    sections.append(ui_helpers.empty_state("No swings with both an intended and actual zone recorded for you yet."))
                else:
                    sections.append(_render_execution_heatmap(
                        "Live execution accuracy by intended zone", my_exec_rates, my_exec_counts,
                        subtitle="Green = you hit your spot most often when you aim here, red = you miss most often. Number in parentheses is attempt count.",
                    ))
            return ui.div(*sections)
        finally:
            db.close()