"""
GBO -- My Hitting module (Player role only).

Direct port of pages/player_hitting.py -- read-only view of the
player's own Hitter Tracking sessions plus a contact-quality-by-zone
heatmap. The heatmap (a Plotly Heatmap, decorative/hoverinfo-capable
but no click handling in the original) renders as a static PNG via
chart_helpers.fig_to_img -- same technique as bucket_display.py and
bullpen_dashboard_display.py, for the same reason (no interactivity
lost, and a data-dependent chart doesn't need a pre-declared shinywidgets
output id).

Per-session video pickers use dynamic per-session input IDs
("hit_video_choice_{session_id}"), same idiom as player_stats.py/
players.py elsewhere in this migration -- keyed once, read via
input[key]() bracket access.
"""

from shiny import module, ui, render, reactive, req
import plotly.graph_objects as go

from database import get_session
from models import Player, User, HitterTrackingSession, HitterSwing

import ui_helpers
import chart_helpers

CONTACT_QUALITY_SCORE = {"Barrel": 3, "Solid": 2, "Weak": 1, "Miss": 0}


def _compute_zone_scores(swings):
    by_zone = {}
    for s in swings:
        if s.pitch_zone is None or s.contact_quality not in CONTACT_QUALITY_SCORE:
            continue
        by_zone.setdefault(s.pitch_zone, []).append(CONTACT_QUALITY_SCORE[s.contact_quality])
    scores = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return scores, counts


def _render_zone_heatmap(title, zone_scores, zone_counts, subtitle=None):
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[zone_scores.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{zone_scores[zid]:.1f}<br>({zone_counts[zid]})" if zid in zone_scores else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn", zmin=0, zmax=3, showscale=True,
        colorbar=dict(title="Avg score", tickfont=dict(color="#AEB6C2"), title_font=dict(color="#AEB6C2")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#AEB6C2"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    children = [chart_helpers.fig_to_img(fig, width=700, height=380)]
    if subtitle:
        children.append(ui.p(subtitle, class_="text-muted small"))
    return ui.div(*children)


@module.ui
def player_hitting_ui():
    return ui.div(
        ui_helpers.page_header("My Hitting"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_hitting_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _my_player(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        return db.query(Player).filter(Player.player_id == me.player_id).first()

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
            if my_player.is_pitcher:
                return ui.p("This page is only available to position players -- see My Bullpens instead.", class_="text-danger")

            sessions = (
                db.query(HitterTrackingSession)
                .filter(HitterTrackingSession.player_id == my_player.player_id)
                .order_by(HitterTrackingSession.session_date.desc())
                .all()
            )

            sections = [ui.h5("My sessions", class_="gbo-section-title")]
            if not sessions:
                sections.append(ui_helpers.empty_state("No hitting sessions recorded yet."))
            else:
                panels = []
                for s in sessions:
                    type_name = s.session_type.type_name if s.session_type else "—"
                    title = f"{s.session_date.strftime('%Y-%m-%d (%a)')} — {type_name}"
                    if s.label:
                        title += f": {s.label}"
                    title += f" ({len(s.swings)} swings)"

                    panel_children = []
                    if s.overall_notes:
                        panel_children.append(ui.p(s.overall_notes, class_="text-muted small"))
                    if not s.swings:
                        panel_children.append(ui.p("No swings recorded for this session.", class_="text-muted small"))
                    else:
                        counts_by_quality = {}
                        counts_by_type = {}
                        for sw in s.swings:
                            if sw.contact_quality:
                                counts_by_quality[sw.contact_quality] = counts_by_quality.get(sw.contact_quality, 0) + 1
                            pt_name = sw.pitch_type.type_name if sw.pitch_type else "—"
                            counts_by_type[pt_name] = counts_by_type.get(pt_name, 0) + 1

                        panel_children.append(ui.p(ui.strong("Contact quality")))
                        quality_line = " · ".join(f"{q}: {c}" for q, c in counts_by_quality.items())
                        panel_children.append(ui.p(quality_line or "—"))

                        panel_children.append(ui.p(ui.strong("By pitch type")))
                        type_line = " · ".join(f"{t}: {c}" for t, c in counts_by_type.items())
                        panel_children.append(ui.p(type_line or "—"))

                        video_swings = [sw for sw in s.swings if sw.video_url]
                        if video_swings:
                            video_key = f"hit_video_choice_{s.session_id}"
                            video_choices = {
                                str(sw.swing_id): f"Swing #{sw.swing_number}"
                                + (f" ({sw.pitch_type.type_name})" if sw.pitch_type else "")
                                + (f" — {sw.contact_quality}" if sw.contact_quality else "")
                                for sw in video_swings
                            }
                            panel_children.append(ui.p(ui.strong(f"Swing video ({len(video_swings)} of {len(s.swings)} swings)")))
                            panel_children.append(ui.input_select(video_key, "Watch", choices=video_choices))
                            panel_children.append(ui.output_ui(f"video_player_{s.session_id}"))
                            _register_video_player(s.session_id, video_key, video_swings)

                    panels.append(ui.accordion_panel(title, ui.div(*panel_children)))
                sections.append(ui.accordion(*panels, open=False, id=None))

            sections.append(ui.hr())
            sections.append(ui.h5("My zone heatmap", class_="gbo-section-title"))
            all_swings = (
                db.query(HitterSwing)
                .join(HitterTrackingSession)
                .filter(HitterTrackingSession.player_id == my_player.player_id)
                .all()
            )
            sections.append(ui.input_radio_buttons("hit_hand_filter", "Filter by pitcher hand", ["All", "vs RHP", "vs LHP"], inline=True))
            sections.append(ui.output_ui("zone_heatmap_section"))

            return ui.div(*sections)
        finally:
            db.close()

    _registered_video_outputs = set()

    def _register_video_player(session_id, video_key, video_swings):
        """Lazy-registration for a per-session video player output --
        same pattern used elsewhere in this migration for a dynamic,
        data-dependent number of outputs (see training_routines.py's
        _register_video_save_handler docstring for the fuller rationale;
        here it's an @render.ui output instead of a button effect, but
        the "register once, guard against re-registering" shape is the
        same)."""
        output_id = f"video_player_{session_id}"
        if output_id in _registered_video_outputs:
            return
        _registered_video_outputs.add(output_id)
        swings_by_id = {sw.swing_id: sw for sw in video_swings}

        @output(id=output_id)
        @render.ui
        def _player():
            req(video_key in input)
            chosen_id = int(input[video_key]())
            sw = swings_by_id.get(chosen_id)
            if sw is None:
                return None
            children = [ui.tags.video(ui.tags.source(src=sw.video_url), controls=True, style="max-width:100%;")]
            if sw.notes:
                children.append(ui.p(sw.notes, class_="text-muted small"))
            return ui.div(*children)

    @render.ui
    def zone_heatmap_section():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        req("hit_hand_filter" in input)

        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None or my_player.is_pitcher:
                return None

            all_swings = (
                db.query(HitterSwing)
                .join(HitterTrackingSession)
                .filter(HitterTrackingSession.player_id == my_player.player_id)
                .all()
            )
            hand_filter = input.hit_hand_filter()
            filtered_swings = all_swings
            if hand_filter == "vs RHP":
                filtered_swings = [sw for sw in all_swings if sw.pitcher_hand == "R"]
            elif hand_filter == "vs LHP":
                filtered_swings = [sw for sw in all_swings if sw.pitcher_hand == "L"]

            if not filtered_swings:
                return ui_helpers.empty_state("No swings logged yet to build a heatmap from.")

            zone_scores, zone_counts = _compute_zone_scores(filtered_swings)
            if not zone_scores:
                return ui_helpers.empty_state("No swings with both a zone and contact quality recorded yet.")

            return _render_zone_heatmap(
                f"Contact quality by zone ({hand_filter})", zone_scores, zone_counts,
                subtitle="Green = best contact (Barrel/Solid), red = weakest (Weak/Miss). Number in parentheses is swing count.",
            )
        finally:
            db.close()
