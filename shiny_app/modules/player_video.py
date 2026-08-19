"""
GBO -- My Video module (Player role only).

Direct port of pages/player_video.py -- unified video hub merging clips
from Bullpen Tracking, Hitter Tracking, and general Video Review
uploads into one chronological "Session" picker, auto-scoped by the
player's own is_pitcher flag (no manual mode selection, same as the
original).

Two-level picker (Session, then a per-kind sub-picker: Pitch/Swing/Clip)
-- same ordering-hazard-safe split used throughout this migration:
the Session select lives in one render.ui block, the sub-picker (and
everything downstream of it) lives in a second block that reads it via
req("video_session_choice" in input).
"""

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, User, AssessmentCategory, Assessment, AssessmentResult, Video,
    BullpenSession, BullpenPitch, HitterTrackingSession, HitterSwing,
)

import ui_helpers
from video_helpers import render_video_clip


def _build_sessions_list(db, my_player):
    """Same unified-session-list construction as the original --
    see pages/player_video.py's module docstring for the full source
    breakdown (Bullpen Tracking / Hitter Tracking / general Video
    Review), plus one fix: general Video Import clips (assessment_id
    IS NULL -- every clip added from the Video Import page, see that
    module's docstring) are now included for pitchers too, not just
    hitters -- see the "general_clip" block below, which used to be
    hitter-only (the "else" branch's general_clips query) even though
    nothing about it is actually hitter-specific. A pitcher whose coach
    used Video Import (rather than linking a clip to a specific
    Rapsodo-imported pitch) previously had that clip visible on the
    coach's Video Import page but invisible on the player's own My
    Video page -- this was a real gap, not intentional scoping."""
    sessions_list = []

    if my_player.is_pitcher:
        bullpen_sessions = (
            db.query(BullpenSession)
            .options(joinedload(BullpenSession.bullpen_type), joinedload(BullpenSession.pitches))
            .filter(BullpenSession.player_id == my_player.player_id)
            .all()
        )
        for b in bullpen_sessions:
            video_pitches = [p for p in b.pitches if p.video_url]
            if video_pitches:
                type_name = b.bullpen_type.type_name if b.bullpen_type else "—"
                sessions_list.append({
                    "key": f"bullpen_{b.bullpen_id}",
                    "sort_date": b.session_date,
                    "display": f"{b.session_date.strftime('%Y-%m-%d (%a)')} — Bullpen: {type_name}",
                    "kind": "bullpen",
                    "pitches": video_pitches,
                })

        category = db.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
        general_pitches = []
        if category:
            general_pitches = (
                db.query(Assessment)
                .options(
                    joinedload(Assessment.results).joinedload(AssessmentResult.test_type),
                    joinedload(Assessment.pitch_type),
                    joinedload(Assessment.videos),
                )
                .filter(Assessment.player_id == my_player.player_id, Assessment.category_id == category.category_id)
                .all()
            )
            general_pitches = [p for p in general_pitches if p.videos]
        general_dates = sorted({p.assessment_date for p in general_pitches}, reverse=True)
        for d in general_dates:
            sessions_list.append({
                "key": f"assessment_{d.isoformat()}",
                "sort_date": d,
                "display": f"{d.strftime('%Y-%m-%d (%a)')} — Pitch-linked clips",
                "kind": "general_pitcher",
                "pitches": [p for p in general_pitches if p.assessment_date == d],
            })

    else:
        hitter_sessions = (
            db.query(HitterTrackingSession)
            .options(joinedload(HitterTrackingSession.session_type), joinedload(HitterTrackingSession.swings))
            .filter(HitterTrackingSession.player_id == my_player.player_id)
            .all()
        )
        for hs in hitter_sessions:
            video_swings = [sw for sw in hs.swings if sw.video_url]
            if video_swings:
                type_name = hs.session_type.type_name if hs.session_type else "—"
                label = f"{hs.session_date.strftime('%Y-%m-%d (%a)')} — {type_name}"
                if hs.label:
                    label += f": {hs.label}"
                sessions_list.append({
                    "key": f"hitter_{hs.session_id}",
                    "sort_date": hs.session_date,
                    "display": label,
                    "kind": "hitter",
                    "swings": video_swings,
                })

    # General Video Import clips (assessment_id IS NULL) -- every clip
    # a coach adds from the Video Import page lands here, regardless of
    # whether the player is a pitcher or hitter. See this function's
    # docstring for why this now runs for both instead of hitters only.
    general_clips = (
        db.query(Video)
        .filter(Video.player_id == my_player.player_id, Video.assessment_id.is_(None))
        .all()
    )
    general_clip_dates = sorted({v.recorded_date for v in general_clips if v.recorded_date}, reverse=True)
    for d in general_clip_dates:
        sessions_list.append({
            "key": f"general_{d.isoformat()}",
            "sort_date": d,
            "display": f"{d.strftime('%Y-%m-%d (%a)')} — General clips",
            "kind": "general_clip",
            "clips": [v for v in general_clips if v.recorded_date == d],
        })

    sessions_list.sort(key=lambda s: s["sort_date"], reverse=True)
    return sessions_list


@module.ui
def player_video_ui():
    return ui.div(
        ui_helpers.page_header("My Video"),
        ui.output_ui("session_picker"),
        ui.output_ui("clip_section"),
        ui_helpers.page_footer(),
    )


@module.server
def player_video_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _my_player(db):
        me = db.query(User).filter(User.user_id == app_state.user_id()).first()
        if me is None or me.player_id is None:
            return None
        return db.query(Player).filter(Player.player_id == me.player_id).first()

    @render.ui
    def session_picker():
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

            sessions_list = _build_sessions_list(db, my_player)
            if not sessions_list:
                return ui_helpers.empty_state("No video available yet.")

            choices = {s["key"]: s["display"] for s in sessions_list}
            return ui.input_select("video_session_choice", "Session", choices=choices)
        finally:
            db.close()

    @render.ui
    def clip_section():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        req("video_session_choice" in input)

        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None:
                return None
            sessions_list = _build_sessions_list(db, my_player)
            sessions_by_key = {s["key"]: s for s in sessions_list}
            selected = sessions_by_key.get(input.video_session_choice())
            if selected is None:
                return None

            if selected["kind"] == "bullpen":
                pitches_by_id = {p.bullpen_pitch_id: p for p in selected["pitches"]}
                choices = {
                    str(pid): f"Pitch #{p.pitch_number}" + (f" ({p.pitch_type.type_name})" if p.pitch_type else "")
                    for pid, p in pitches_by_id.items()
                }
                return ui.div(
                    ui.hr(),
                    ui.input_select("video_pitch_choice", "Pitch", choices=choices),
                    ui.output_ui("clip_player"),
                )

            if selected["kind"] == "general_pitcher":
                pitches_by_id = {p.assessment_id: p for p in selected["pitches"]}

                def _label(p):
                    pt = p.pitch_type.type_name if p.pitch_type else "Unknown type"
                    velo = next((r.value for r in p.results if r.test_type.test_name == "Velocity"), None)
                    return f"{pt}" + (f" — {float(velo):.1f} mph" if velo is not None else "")

                choices = {str(aid): _label(p) for aid, p in pitches_by_id.items()}
                return ui.div(
                    ui.hr(),
                    ui.input_select("video_general_pitch_choice", "Pitch", choices=choices),
                    ui.output_ui("clip_player"),
                )

            if selected["kind"] == "hitter":
                swings_by_id = {sw.swing_id: sw for sw in selected["swings"]}
                choices = {
                    str(sid): f"Swing #{sw.swing_number}" + (f" ({sw.pitch_type.type_name})" if sw.pitch_type else "")
                    + (f" — {sw.contact_quality}" if sw.contact_quality else "")
                    for sid, sw in swings_by_id.items()
                }
                return ui.div(
                    ui.hr(),
                    ui.input_select("video_swing_choice", "Swing", choices=choices),
                    ui.output_ui("clip_player"),
                )

            # general_clip -- the only remaining kind at this point for
            # either a pitcher or hitter session (see _build_sessions_
            # list's docstring)
            clips_by_id = {v.video_id: v for v in selected["clips"]}
            choices = {str(vid): (v.description or f"Clip #{vid}") for vid, v in clips_by_id.items()}
            return ui.div(
                ui.hr(),
                ui.input_select("video_clip_choice", "Clip", choices=choices),
                ui.output_ui("clip_player"),
            )
        finally:
            db.close()

    @render.ui
    def clip_player():
        _refresh_tick()
        if not app_state.is_authenticated() or app_state.role_name() != "Player":
            return None
        req("video_session_choice" in input)

        db = get_session()
        try:
            my_player = _my_player(db)
            if my_player is None:
                return None
            sessions_list = _build_sessions_list(db, my_player)
            sessions_by_key = {s["key"]: s for s in sessions_list}
            selected = sessions_by_key.get(input.video_session_choice())
            if selected is None:
                return None

            if selected["kind"] == "bullpen":
                req("video_pitch_choice" in input)
                pitches_by_id = {p.bullpen_pitch_id: p for p in selected["pitches"]}
                p = pitches_by_id.get(int(input.video_pitch_choice()))
                if p is None:
                    return None
                children = [render_video_clip(p.video_url)]
                if p.notes:
                    children.append(ui.p(p.notes, class_="text-muted small"))
                return ui.div(*children)

            if selected["kind"] == "general_pitcher":
                req("video_general_pitch_choice" in input)
                pitches_by_id = {p.assessment_id: p for p in selected["pitches"]}
                selected_pitch = pitches_by_id.get(int(input.video_general_pitch_choice()))
                if selected_pitch is None:
                    return None
                rapsodo_col = [ui.h6("Rapsodo data")]
                if not selected_pitch.results:
                    rapsodo_col.append(ui.p("No numeric values recorded for this pitch.", class_="text-muted small"))
                else:
                    rapsodo_col.append(ui_helpers.render_dict_table([
                        {"Test": r.test_type.test_name, "Value": f"{float(r.value):.2f}" + (f" {r.test_type.unit}" if r.test_type.unit else "")}
                        for r in selected_pitch.results
                    ]))
                video_col = [ui.h6("Video")]
                for v in selected_pitch.videos:
                    video_col.append(render_video_clip(v.video_url))
                    if v.description:
                        video_col.append(ui.p(v.description, class_="text-muted small"))
                return ui.layout_columns(ui.div(*rapsodo_col), ui.div(*video_col))

            if selected["kind"] == "hitter":
                req("video_swing_choice" in input)
                swings_by_id = {sw.swing_id: sw for sw in selected["swings"]}
                sw = swings_by_id.get(int(input.video_swing_choice()))
                if sw is None:
                    return None
                children = [render_video_clip(sw.video_url)]
                if sw.notes:
                    children.append(ui.p(sw.notes, class_="text-muted small"))
                return ui.div(*children)

            # general_clip -- the only remaining kind at this point for
            # either a pitcher or hitter session (see _build_sessions_
            # list's docstring)
            req("video_clip_choice" in input)
            clips_by_id = {v.video_id: v for v in selected["clips"]}
            v = clips_by_id.get(int(input.video_clip_choice()))
            if v is None:
                return None
            return render_video_clip(v.video_url)
        finally:
            db.close()