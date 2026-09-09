"""
GBO -- Game Tracking's "Video Review" section, extracted out of
game_tracking.py's single ~4700-line game_tracking_server (Tier 2 split,
2026-09 -- see game_tracking_manage_display.py's module docstring for the
overall rationale and the registration pattern this follows).

Fully self-contained: _vr_current_pitch_id and _registered_clip_match_ids
are used ONLY within this section (verified against the whole file before
this extraction), so unlike the Manage Game split, they're created here
rather than threaded in from game_tracking_server. _upload_game_video_clip
and GAME_VIDEO_SUBFOLDER moved along with their one and only call site
(game_video_upload_section's bulk-upload handler).
"""

from shiny import ui, render, reactive, req

from database import get_session
from models import GamePitch, GameVideoClip
from video_helpers import ShinyFileAdapter as _ShinyFileAdapter
from r2_client import upload_video_to_r2
import strike_zone
import click_widgets
import ui_helpers

GAME_VIDEO_SUBFOLDER = "pitch-videos/"  # same folder Bullpen/Hitter Tracking's clips upload into, inside the one shared R2 bucket


def _upload_game_video_clip(file_info: dict, identifier: str):
    try:
        return upload_video_to_r2(_ShinyFileAdapter(file_info), identifier, bucket_subfolder=GAME_VIDEO_SUBFOLDER)
    except Exception as e:
        ui.notification_show(
            f"Video upload failed: {e}. Make sure Cloudflare R2 is configured "
            f"(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- "
            f"see r2_client.py's docstring for setup steps).",
            type="error", duration=12,
        )
        return None


def register_game_tracking_video(input, output, session, _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_refresh):
    _vr_current_pitch_id = reactive.Value(None)
    _registered_clip_match_ids = set()

    @render.ui
    def video_review_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        if not _can_edit():
            return ui.p("Video Review is only available to edit-enabled roles.", class_="text-muted")
        return ui.div(
            ui.output_ui("game_video_upload_section"),
            ui.output_ui("clip_match_section"),
            ui.hr(),
            ui.output_ui("video_review_jump_picker"),
            ui.output_ui("video_review_detail"),
            click_widgets.click_target(output_widget("video_review_widget"), "vr_actual_x_input", "vr_actual_z_input"),
            ui.output_ui("video_review_caption"),
            ui.output_ui("video_review_nav"),
        )

    @render.ui
    def game_video_upload_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            pitch_count = db.query(GamePitch).filter(GamePitch.game_id == game_id).count()
            if not pitch_count:
                return ui_helpers.empty_state("No pitches logged yet in this game to attach video to.")
            return ui.div(
                ui.h5("Pitch Video", class_="gbo-section-title"),
                ui.p(
                    "Upload clips downloaded from your camera -- if it already exports one clip per pitch, "
                    "upload them together and match each to this game's pitches below.",
                    class_="text-muted small",
                ),
                ui.input_file("game_video_files", "Video files", accept=[".mp4", ".mov", ".m4v"], multiple=True),
                ui.input_action_button("game_video_upload_btn", "Upload", class_="btn-primary"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.game_video_upload_btn)
    def _upload_game_videos():
        game_id = _active_game_id()
        if game_id is None:
            return
        files = input.game_video_files() if "game_video_files" in input else None
        if not files:
            ui.notification_show("Choose at least one video file first.", type="error", duration=8)
            return
        db = get_session()
        try:
            uploaded = 0
            for f in files:
                identifier = f"game-{game_id}-{uuid.uuid4().hex[:8]}"
                url = _upload_game_video_clip(f, identifier)
                if url:
                    db.add(GameVideoClip(game_id=game_id, video_url=url, original_filename=f["name"]))
                    uploaded += 1
            db.commit()
            ui.notification_show(f"Uploaded {uploaded} clip(s). Match them to pitches below.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def clip_match_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            matched_count = db.query(GameVideoClip).filter(GameVideoClip.game_id == game_id, GameVideoClip.matched_game_pitch_id.isnot(None)).count()
            unmatched = (
                db.query(GameVideoClip)
                .filter(GameVideoClip.game_id == game_id, GameVideoClip.matched_game_pitch_id.is_(None))
                .order_by(GameVideoClip.uploaded_at, GameVideoClip.game_video_clip_id).all()
            )
            if not matched_count and not unmatched:
                return None
            children = [ui.p(f"{matched_count} clip(s) matched, {len(unmatched)} still need matching.", class_="text-muted small")]
            if unmatched:
                candidate_pitches = (
                    db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
                    .filter(GamePitch.game_id == game_id, GamePitch.video_url.is_(None))
                    .order_by(GamePitch.pitch_sequence).all()
                )
                if not candidate_pitches:
                    children.append(ui.p("Every pitch in this game already has video -- nothing left to match these clips to.", class_="text-muted small"))
                else:
                    match_choices = {"": "-- Select a pitch --"}
                    for p in candidate_pitches:
                        side = "Us pitching" if not p.is_our_team_batting else "Us batting"
                        pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                        match_choices[str(p.game_pitch_id)] = f"#{p.pitch_sequence} — Inn {p.inning}, {side}, {p.balls_before}-{p.strikes_before}, {pt_name}, {p.pitch_outcome or '—'}"

                    panel_rows = []
                    for idx, clip in enumerate(unmatched):
                        suggested = candidate_pitches[idx].game_pitch_id if idx < len(candidate_pitches) else candidate_pitches[0].game_pitch_id
                        select_id = f"clip_match_select_{clip.game_video_clip_id}"
                        btn_id = f"clip_match_btn_{clip.game_video_clip_id}"
                        panel_rows.append(ui.layout_columns(
                            ui.p(clip.original_filename or "Clip", class_="mb-0"),
                            ui.input_select(select_id, None, choices=match_choices, selected=str(suggested)),
                            ui.input_action_button(btn_id, "Link", class_="btn-sm btn-outline-primary"),
                            col_widths=[3, 6, 3],
                        ))
                        if btn_id not in _registered_clip_match_ids:
                            _registered_clip_match_ids.add(btn_id)
                            _register_clip_match_handler(btn_id, select_id, clip.game_video_clip_id)

                    children.append(ui.accordion(ui.accordion_panel(f"Match uploaded clips to pitches ({len(unmatched)} pending)", *panel_rows), open=True, id=None))
            return ui.div(*children)
        finally:
            db.close()

    def _register_clip_match_handler(btn_id, select_id, clip_id):
        @reactive.effect
        @reactive.event(input[btn_id])
        def _handler():
            chosen_raw = input[select_id]()
            if not chosen_raw:
                return
            db = get_session()
            try:
                clip = db.query(GameVideoClip).filter(GameVideoClip.game_video_clip_id == clip_id).first()
                pitch = db.query(GamePitch).filter(GamePitch.game_pitch_id == int(chosen_raw)).first()
                if clip is None or pitch is None:
                    return
                clip.matched_game_pitch_id = pitch.game_pitch_id
                pitch.video_url = clip.video_url
                db.commit()
                ui.notification_show(f"Linked {clip.original_filename or 'clip'} to pitch #{pitch.pitch_sequence}.", type="message", duration=8)
                _bump_refresh()
            finally:
                db.close()

    @reactive.effect
    def _reset_vr_on_game_change():
        game_id = _active_game_id()
        if game_id is None:
            _vr_current_pitch_id.set(None)
            return
        db = get_session()
        try:
            # Every pitch in the game needs an actual location eventually
            # (see the module-level note on Video Review's scope) -- no
            # is_our_team_batting filter here any more.
            pitches_to_review = (
                db.query(GamePitch).filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence).all()
            )
            if not pitches_to_review:
                _vr_current_pitch_id.set(None)
                return
            missing = [p.game_pitch_id for p in pitches_to_review if p.actual_plate_x is None]
            _vr_current_pitch_id.set(missing[0] if missing else pitches_to_review[0].game_pitch_id)
        finally:
            db.close()

    @render.ui
    def video_review_jump_picker():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            pitches_to_review = (
                db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
                .filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence).all()
            )
            if not pitches_to_review:
                return ui.div(
                    ui.h5("Video Review — Actual Pitch Locations", class_="gbo-section-title"),
                    ui_helpers.empty_state("No pitches logged yet in this game to review."),
                )
            missing_count = sum(1 for p in pitches_to_review if p.actual_plate_x is None)
            choices = {}
            for p in pitches_to_review:
                mark = "unmarked" if p.actual_plate_x is None else "done"
                pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                video_tag = " [video]" if p.video_url else ""
                side_tag = "Us pitching" if not p.is_our_team_batting else "Us batting"
                choices[str(p.game_pitch_id)] = f"[{mark}] #{p.pitch_sequence} — Inn {p.inning}, {p.balls_before}-{p.strikes_before}, {side_tag}, {pt_name}{video_tag}"
            current = _vr_current_pitch_id()
            selected = str(current) if current is not None and str(current) in choices else None
            return ui.div(
                ui.h5("Video Review — Actual Pitch Locations", class_="gbo-section-title"),
                ui.p(
                    "Step through every pitch of the game and mark where it actually crossed, watching the "
                    "center-field angle (or the matched clip below, if there is one).",
                    class_="text-muted small",
                ),
                ui.p(f"{missing_count} of {len(pitches_to_review)} pitch(es) still need an actual location.", class_="text-muted small"),
                ui.input_select("vr_jump_select", "Jump to pitch", choices=choices, selected=selected),
            )
        finally:
            db.close()

    @reactive.effect
    def _sync_vr_current_pitch():
        req("vr_jump_select" in input)
        raw = input.vr_jump_select()
        if raw:
            _vr_current_pitch_id.set(int(raw))

    @render.ui
    def video_review_detail():
        if not _access_ok() or not _can_edit():
            return None
        pitch_id = _vr_current_pitch_id()
        if pitch_id is None:
            return None
        db = get_session()
        try:
            p = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.opponent_our_player), joinedload(GamePitch.opponent_player), joinedload(GamePitch.our_player))
                .filter(GamePitch.game_pitch_id == pitch_id).first()
            )
            if p is None:
                return None
            # Video Review now covers every pitch, not just ones we threw --
            # who's the "batter" vs. the "pitcher" flips depending on
            # is_our_team_batting (see GamePitch's own docstring), and
            # opponent_hand's meaning flips right along with it (it's
            # always "the OTHER side's hand").
            opponent_label = (
                (f"{p.opponent_our_player.first_name} {p.opponent_our_player.last_name}" if p.opponent_our_player else None)
                or (p.opponent_player.player_name if p.opponent_player else None)
                or (f"batting order #{p.opponent_batting_order}" if p.opponent_batting_order else None)
            )
            our_label = f"{p.our_player.first_name} {p.our_player.last_name}" if p.our_player else None
            if p.is_our_team_batting:
                pitcher_label = (opponent_label or "opponent pitcher") + (f" ({p.opponent_hand}HP)" if p.opponent_hand else "")
                batter_label = our_label or "unknown batter"
                intended_label = (
                    f"intended {float(p.intended_plate_x):+.2f} ft, {float(p.intended_plate_z):.2f} ft high"
                    if p.intended_plate_x is not None
                    else ("no intended location was logged live" if p.game.is_intrasquad else "intended location isn't tracked for opponent pitchers")
                )
            else:
                pitcher_label = our_label or "unknown pitcher"
                batter_label = (opponent_label or "unknown batter") + (f" ({p.opponent_hand}HB)" if p.opponent_hand else "")
                intended_label = (
                    f"intended {float(p.intended_plate_x):+.2f} ft, {float(p.intended_plate_z):.2f} ft high"
                    if p.intended_plate_x is not None else "no intended location was logged live"
                )
            children = [
                ui.p(f"Pitch #{p.pitch_sequence} — Inning {p.inning}, {p.balls_before}-{p.strikes_before} count — {pitcher_label} to {batter_label}", class_="fw-bold mb-1"),
                ui.p(
                    f"Called: {p.pitch_type.type_name if p.pitch_type else 'unknown pitch'} — {intended_label}. "
                    f"Outcome: {p.pitch_outcome or '—'}" + (f", {p.ab_outcome}" if p.ab_outcome else ""),
                    class_="text-muted small",
                ),
            ]
            if p.video_url:
                children.append(ui.tags.video(ui.tags.source(src=p.video_url), controls=True, style="max-width:100%;"))
            x_default = float(p.actual_plate_x) if p.actual_plate_x is not None else 0.0
            z_default = float(p.actual_plate_z) if p.actual_plate_z is not None else 2.5
            children.append(ui.layout_columns(
                ui.input_numeric("vr_actual_x_input", "Actual plate side (ft, 0 = center, negative = 3B side)", value=x_default, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                ui.input_numeric("vr_actual_z_input", "Actual plate height (ft off the ground)", value=z_default, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
            ))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def video_review_widget():
        """Real click-to-place actual pitch location -- see
        intended_location_widget above for the pattern; clicks write
        into vr_actual_x_input/vr_actual_z_input."""
        if not _access_ok() or not _can_edit():
            return None
        if _vr_current_pitch_id() is None:
            return None
        req("vr_actual_x_input" in input)
        x, z = input.vr_actual_x_input(), input.vr_actual_z_input()
        return _build_clickable_widget(strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z))

    @render.ui
    def video_review_caption():
        if not _access_ok() or not _can_edit():
            return None
        if _vr_current_pitch_id() is None:
            return None
        req("vr_actual_x_input" in input)
        x, z = input.vr_actual_x_input(), input.vr_actual_z_input()
        located = strike_zone.is_in_zone(x, z)
        return ui.p(
            f"Marked: {x:+.2f} ft, {z:.2f} ft high — {'In zone' if located else 'Out of zone'} — click the zone above, or type coordinates directly.",
            class_="text-muted small text-center",
        )

    @render.ui
    def video_review_nav():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        pitch_id = _vr_current_pitch_id()
        if game_id is None or pitch_id is None:
            return None
        db = get_session()
        try:
            ids = [
                p.game_pitch_id for p in
                db.query(GamePitch).filter(GamePitch.game_id == game_id).order_by(GamePitch.pitch_sequence).all()
            ]
            if pitch_id not in ids:
                return None
            idx = ids.index(pitch_id)
            return ui.layout_columns(
                ui.input_action_button("vr_prev_btn", "◀ Previous", disabled=(idx == 0), class_="w-100"),
                ui.input_action_button("vr_save_btn", "Save actual location", class_="btn-primary w-100"),
                ui.input_action_button("vr_next_btn", "Next ▶", disabled=(idx == len(ids) - 1), class_="w-100"),
            )
        finally:
            db.close()

    def _vr_step(direction):
        game_id = _active_game_id()
        pitch_id = _vr_current_pitch_id()
        if game_id is None or pitch_id is None:
            return
        db = get_session()
        try:
            ids = [
                p.game_pitch_id for p in
                db.query(GamePitch).filter(GamePitch.game_id == game_id).order_by(GamePitch.pitch_sequence).all()
            ]
            if pitch_id not in ids:
                return
            idx = ids.index(pitch_id)
            new_idx = min(max(idx + direction, 0), len(ids) - 1)
            _vr_current_pitch_id.set(ids[new_idx])
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.vr_prev_btn)
    def _vr_prev():
        _vr_step(-1)

    @reactive.effect
    @reactive.event(input.vr_next_btn)
    def _vr_next():
        _vr_step(1)

    @reactive.effect
    @reactive.event(input.vr_save_btn)
    def _vr_save():
        pitch_id = _vr_current_pitch_id()
        if pitch_id is None:
            return
        req("vr_actual_x_input" in input)
        x, z = input.vr_actual_x_input(), input.vr_actual_z_input()
        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                return
            p.actual_plate_x = x
            p.actual_plate_z = z
            p.pitch_zone = strike_zone.derive_old_zone(x, z)
            db.commit()
            game_id = p.game_id
            pitches_to_review = (
                db.query(GamePitch).filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence).all()
            )
            ids = [pp.game_pitch_id for pp in pitches_to_review]
            still_missing = [pp.game_pitch_id for pp in pitches_to_review if pp.actual_plate_x is None]
            idx = ids.index(pitch_id)
            later_missing = [gpid for gpid in still_missing if ids.index(gpid) > idx]
            if later_missing:
                _vr_current_pitch_id.set(later_missing[0])
            elif still_missing:
                _vr_current_pitch_id.set(still_missing[0])
            else:
                _vr_current_pitch_id.set(ids[min(idx + 1, len(ids) - 1)])
            ui.notification_show(f"Saved actual location for pitch #{p.pitch_sequence}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

