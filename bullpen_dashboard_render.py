"""
GBO — Shared Rapsodo Bullpen Dashboard rendering: a single session's
full drill-down (session header/KPI cards, filters, pitch-type
summary, and the five core charts), plus a combined "every session
this pitcher has" view. Pulled out of pages/bullpen_dashboard.py into
its own module so the exact same rendering can be called from two
different places, per Ryker's request:

  - pages/bullpen_dashboard.py -- the standalone page (coaches' picker
    flow, and every existing direct ?bullpen_id= link from Bullpen
    Tracking / Import Rapsodo Data), unchanged in behavior.
  - pages/player_bullpens.py -- inline, right on My Bullpens, behind a
    "which session (or all combined)?" picker, so a player can see the
    full dashboard without leaving My Bullpens or navigating to a
    separate tab.

Because render_bullpen_session can now run more than once on the same
page in principle, every interactive widget's key is suffixed with the
bullpen_id it belongs to -- the original single-page version used
fixed keys ("dash_min_shading_pitches" etc.), which only worked
because exactly one instance ever existed on a page at once. Same
pattern for render_overall_pitch_tracking, suffixed by player_id.

Also, unlike the original inlined version, render_bullpen_session's
"no pitches match the selected filters" case now does a plain `return`
instead of `page_footer(); st.stop()` -- stopping the whole script
would be wrong for a caller with other content above/below it.
"""

import streamlit as st
from sqlalchemy.orm import joinedload

from models import BullpenSession, RapsodoPitch
from ui_components import empty_state, render_kpi_cards
from bullpen_dashboard_style import section_label, pitch_type_legend
from analytics.bullpen_metrics import (
    session_summary, pitch_type_summary, individual_pitch_rows, filter_pitches, pitch_type_label,
)
from visualizations.bullpen_charts import (
    movement_chart, release_point_chart, velocity_spin_trend_chart, location_chart, color_for_pitch_label,
)
from visualizations.spin_axis_chart import individual_spin_axis_chart, average_spin_axis_chart


def render_bullpen_session(session, target_bullpen_id, section_start=1):
    """Renders one bullpen session's full Rapsodo dashboard: session
    header/KPI cards, an optional video expander, then three numbered
    sections -- Filters, Pitch Summary, Charts -- starting at
    section_start (so a caller with sections already above this, like
    Bullpen Dashboard's Overall Pitch Tracking = section 1, can pass
    section_start=2 to keep numbering continuous; a caller embedding
    this with nothing above it, like a My Bullpens expander, can leave
    the default of 1).

    Caller is responsible for the SQLAlchemy session (already open) and
    for confirming target_bullpen_id is one the current user is allowed
    to see -- no permission checks happen in here, same as the rest of
    GBO's page/analytics-layer split."""
    active_bullpen = (
        session.query(BullpenSession)
        .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.player))
        .filter(BullpenSession.bullpen_id == target_bullpen_id)
        .first()
    )
    if active_bullpen is None:
        st.warning("That session either doesn't exist, has no Rapsodo data yet, or you don't have access to it.")
        return

    all_pitches = (
        session.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.bullpen_id == target_bullpen_id)
        .order_by(RapsodoPitch.pitch_number)
        .all()
    )

    # --- Session header ---
    player_name = f"{active_bullpen.player.first_name} {active_bullpen.player.last_name}" if active_bullpen.player else "—"
    type_label = active_bullpen.bullpen_type.type_name if active_bullpen.bullpen_type else "—"
    st.subheader(f"{player_name} — {active_bullpen.session_date.strftime('%Y-%m-%d (%a)')} — {type_label}")
    if active_bullpen.overall_notes:
        st.caption(active_bullpen.overall_notes)

    summary = session_summary(all_pitches)
    render_kpi_cards([
        {"label": "Total Pitches", "value": str(summary["total_pitches"])},
        {"label": "Pitch Types", "value": str(len(summary["pitch_type_names"]))},
        {"label": "Avg Velocity", "value": f"{summary['avg_velocity']:.1f} mph" if summary["avg_velocity"] is not None else "—"},
        {"label": "Max Velocity", "value": f"{summary['max_velocity']:.1f} mph" if summary["max_velocity"] is not None else "—"},
        {"label": "Avg Spin Rate", "value": f"{summary['avg_spin_rate']:.0f} rpm" if summary["avg_spin_rate"] is not None else "—"},
    ])

    if active_bullpen.video_url:
        with st.expander("Session video"):
            st.video(active_bullpen.video_url)

    st.write("")

    # --- Filters (spec Section 5): All Pitches / Pitch Type / Pitch Number Range ---
    with st.container(border=True):
        section_label(section_start, "Filters")
        col1, col2 = st.columns([1, 2])
        with col1:
            type_options = ["All Pitches"] + summary["pitch_type_names"]
            selected_type = st.selectbox("Pitch Type", options=type_options, key=f"dash_pitch_type_{target_bullpen_id}")
        with col2:
            max_pitch_number = max((p.pitch_number for p in all_pitches), default=1)
            pitch_range = st.slider(
                "Pitch Number Range", min_value=1, max_value=max_pitch_number,
                value=(1, max_pitch_number), disabled=(max_pitch_number <= 1),
                key=f"dash_pitch_range_{target_bullpen_id}",
            )

    filtered_pitches = filter_pitches(
        all_pitches,
        pitch_type_name=None if selected_type == "All Pitches" else selected_type,
        pitch_number_range=pitch_range,
    )

    if not filtered_pitches:
        empty_state("No pitches match the selected filters.")
        return

    st.write("")

    # --- Pitch-type summary table (spec Section 6) ---
    with st.container(border=True):
        section_label(section_start + 1, "Pitch Summary")
        summary_rows = pitch_type_summary(filtered_pitches)
        st.dataframe(summary_rows, use_container_width=True, hide_index=True)

        st.caption("Expand a pitch type below to see every individual pitch.")
        pitches_by_type = {}
        for p in filtered_pitches:
            pitches_by_type.setdefault(pitch_type_label(p), []).append(p)

        for row in summary_rows:
            label = row["Pitch Type"]
            with st.expander(f"{label} ({row['#']} pitches)"):
                st.dataframe(individual_pitch_rows(pitches_by_type[label]), use_container_width=True, hide_index=True)

    st.write("")

    # --- Charts (spec Sections 7-11, Phase 3) -- respect the same
    # filters as the summary table above (pitch type, pitch number
    # range), per spec Section 5's "charts should respond to the
    # filters whenever appropriate." ---
    with st.container(border=True):
        section_label(section_start + 2, "Charts")

        # Each chart gets its own full-width row -- no side-by-side
        # columns -- per Ryker's request.
        min_shading_pitches = st.slider(
            "Minimum pitches to shade a pitch type's cluster", min_value=1, max_value=10, value=2,
            key=f"dash_min_shading_pitches_{target_bullpen_id}",
            help="A pitch type with fewer pitches than this still shows its dots, just no shaded cluster region.",
        )
        st.plotly_chart(movement_chart(filtered_pitches, min_pitches_for_shading=min_shading_pitches), use_container_width=True)
        pitch_type_legend(summary_rows, len(filtered_pitches), color_for_pitch_label)
        st.caption("Centered on release point; color-coded by pitch type. Hover a pitch for details.")

        st.plotly_chart(release_point_chart(filtered_pitches), use_container_width=True)
        st.caption("Tighter clustering across pitch types suggests better tunneling out of the hand.")

        st.plotly_chart(velocity_spin_trend_chart(filtered_pitches), use_container_width=True)
        if selected_type == "All Pitches":
            st.caption(
                "Showing every pitch in throwing order -- a fastball/offspeed mix will naturally zigzag here. "
                "Filter to a single pitch type above for that type's own trend."
            )

        location_mode = st.radio(
            "Location view", ["Heat Map", "Individual Pitches"], horizontal=True,
            key=f"dash_location_mode_{target_bullpen_id}",
        )
        st.plotly_chart(
            location_chart(filtered_pitches, mode="heatmap" if location_mode == "Heat Map" else "individual"),
            use_container_width=True,
        )

        spin_axis_mode = st.radio(
            "Spin axis view", ["Average by Pitch Type", "Individual Pitches"], horizontal=True,
            key=f"dash_spin_axis_mode_{target_bullpen_id}",
        )
        if spin_axis_mode == "Average by Pitch Type":
            st.plotly_chart(average_spin_axis_chart(filtered_pitches), use_container_width=True)
        else:
            individual_type_filter = None if selected_type == "All Pitches" else selected_type
            if selected_type == "All Pitches":
                st.caption("Showing every pitch type at once gets busy -- filter to one type above for a cleaner view.")
            st.plotly_chart(individual_spin_axis_chart(filtered_pitches, pitch_type_filter=individual_type_filter), use_container_width=True)


def render_overall_pitch_tracking(session, player, player_session_ids, section_start=1):
    """Renders the combined "every one of this pitcher's Rapsodo
    sessions" view: KPI cards, the pitch-type summary table, and all
    five charts, fed every pitch across every session in
    player_session_ids instead of just one. Shared by:

      - pages/bullpen_dashboard.py -- as the Overall Pitch Tracking
        section ahead of a single session's drill-down (coaches).
      - pages/player_bullpens.py -- as the "All Sessions (Combined)"
        option in its session picker (players), per Ryker's request
        for that same combined view there too.

    Caller is responsible for the SQLAlchemy session (already open),
    for player being a Player ORM object, and for player_session_ids
    being bullpen_ids this user is allowed to see -- same permission
    split as render_bullpen_session."""
    overall_pitches = (
        session.query(RapsodoPitch)
        .options(joinedload(RapsodoPitch.pitch_type))
        .filter(RapsodoPitch.bullpen_id.in_(player_session_ids))
        .order_by(RapsodoPitch.pitch_date)
        .all()
    )
    with st.container(border=True):
        section_label(section_start, f"Overall Pitch Tracking — {player.first_name} {player.last_name}")
        overall_summary = session_summary(overall_pitches)
        render_kpi_cards([
            {"label": "Sessions", "value": str(len(player_session_ids))},
            {"label": "Total Pitches", "value": str(overall_summary["total_pitches"])},
            {"label": "Pitch Types", "value": str(len(overall_summary["pitch_type_names"]))},
            {"label": "Avg Velocity", "value": f"{overall_summary['avg_velocity']:.1f} mph" if overall_summary["avg_velocity"] is not None else "—"},
            {"label": "Avg Spin Rate", "value": f"{overall_summary['avg_spin_rate']:.0f} rpm" if overall_summary["avg_spin_rate"] is not None else "—"},
        ])
        overall_rows = pitch_type_summary(overall_pitches)
        st.dataframe(overall_rows, use_container_width=True, hide_index=True)

        if overall_pitches:
            st.write("")
            st.markdown("**Charts — every imported pitch for this pitcher, all sessions combined**")

            overall_min_shading = st.slider(
                "Minimum pitches to shade a pitch type's cluster", min_value=1, max_value=10, value=2,
                key=f"overall_min_shading_pitches_{player.player_id}",
                help="A pitch type with fewer pitches than this still shows its dots, just no shaded cluster region.",
            )
            st.plotly_chart(
                movement_chart(overall_pitches, min_pitches_for_shading=overall_min_shading), use_container_width=True
            )
            pitch_type_legend(overall_rows, overall_summary["total_pitches"], color_for_pitch_label)
            st.caption("Centered on release point; color-coded by pitch type. Hover a pitch for details.")

            st.plotly_chart(release_point_chart(overall_pitches), use_container_width=True)
            st.caption("Tighter clustering across pitch types suggests better tunneling out of the hand.")

            st.plotly_chart(velocity_spin_trend_chart(overall_pitches), use_container_width=True)
            st.caption(
                "Showing every pitch across every session in throwing order -- a jump between sessions "
                "will show up as a break in the trend here, not a single continuous outing."
            )

            overall_location_mode = st.radio(
                "Location view", ["Heat Map", "Individual Pitches"], horizontal=True,
                key=f"overall_location_mode_{player.player_id}",
            )
            st.plotly_chart(
                location_chart(overall_pitches, mode="heatmap" if overall_location_mode == "Heat Map" else "individual"),
                use_container_width=True,
            )

            overall_spin_axis_mode = st.radio(
                "Spin axis view", ["Average by Pitch Type", "Individual Pitches"], horizontal=True,
                key=f"overall_spin_axis_mode_{player.player_id}",
            )
            if overall_spin_axis_mode == "Average by Pitch Type":
                st.plotly_chart(average_spin_axis_chart(overall_pitches), use_container_width=True)
            else:
                st.caption("Showing every pitch type at once gets busy across a full multi-session history.")
                st.plotly_chart(
                    individual_spin_axis_chart(overall_pitches, pitch_type_filter=None), use_container_width=True
                )
