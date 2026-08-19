"""
GBO -- Video Import module.

Second redesign of this page (see git history / prior delivery notes
for the first, which still uploaded files to Cloudflare R2). Per
explicit request, this version drops R2 entirely: instead of uploading
a file, a coach uploads the clip to Google Drive themselves and pastes
the resulting shareable link into GBO. This sidesteps R2 configuration
altogether (the credential setup was a recurring source of trouble) and
removes any file-size ceiling, at the cost of an extra manual step
(uploading to Drive first) that isn't automatable from here.

Still the simplest possible structure: pick a player, browse their
clip library, add new clips (single or bulk-paste) -- no attempt to
associate a clip with any specific pitch's data. Every video this page
creates has assessment_id=None. Reuses the Video table exactly as
before (player_id, video_url, description, recorded_date) -- video_url
now holds whatever Drive share link the user pasted, verbatim, rather
than an R2 object URL. Existing clips uploaded under either of the
earlier versions of this page still show up here unchanged.

Playback: Drive share links (the "Copy link" URL you get from Drive's
share dialog, e.g. https://drive.google.com/file/d/FILE_ID/view?usp=...)
don't work as a plain <video src>. video_helpers.render_video_clip()
(previously private to this module as _clip_player, extracted out --
see that module's docstring for why: bullpen_tracking.py, hitter_
tracking.py, and player_video.py all render a video_url too and were
found to still be using a plain, non-working <video> tag) builds
Drive's dedicated embeddable preview URL (.../file/d/FILE_ID/preview)
for an <iframe> player -- this plays inline just like the old
R2-backed <video> tag did, but requires the file be shared as "Anyone
with the link can view" in Drive (GBO has no way to check that from
here; if a clip won't play, that's the first thing to check). If a
pasted link doesn't match a recognizable Drive file-share shape (e.g.
a folder link, or some other host entirely), it renders a native
<video> tag instead (works for a direct file URL, e.g. R2 -- see
video_helpers' module docstring) plus an always-visible "Open in a new
tab" link, so even a URL that can't actually play inline still has a
way to view it.
"""

from datetime import date

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, StaffPlayerAssignment, Video

import ui_helpers
from video_helpers import drive_file_id, render_video_clip


@module.ui
def video_import_ui():
    return ui.div(
        ui_helpers.page_header("Video Import"),
        ui.output_ui("player_picker"),
        ui.output_ui("clip_library"),
        ui.output_ui("add_clip_section"),
        ui_helpers.page_footer(),
    )


@module.server
def video_import_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

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
            return ui.div(
                ui.input_select("player_select", "Player", choices=choices),
                ui.hr(),
            )
        finally:
            db.close()

    @render.ui
    def clip_library():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        selected_player_id = int(input.player_select())

        db = get_session()
        try:
            selected_player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            if selected_player is None:
                return None
            clips = (
                db.query(Video)
                .filter(Video.player_id == selected_player_id)
                .order_by(Video.recorded_date.desc(), Video.created_at.desc())
                .all()
            )

            sections = [ui.h5(f"{selected_player.first_name} {selected_player.last_name}'s clips", class_="gbo-section-title")]
            if not clips:
                sections.append(ui_helpers.empty_state("No video clips added yet for this player."))
            else:
                panels = []
                for v in clips:
                    date_label = v.recorded_date.strftime("%Y-%m-%d (%a)") if v.recorded_date else "No date"
                    title = date_label + (f" — {v.description}" if v.description else "")
                    panels.append(ui.accordion_panel(title, render_video_clip(v.video_url)))
                sections.append(ui.accordion(*panels, open=False, id=None))

            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def add_clip_section():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        req("player_select" in input)
        if not app_state.can_edit_assessments():
            return None

        return ui.div(
            ui.hr(),
            ui.h5("Add a clip", class_="gbo-section-title"),
            ui.p(
                "Upload the video to Google Drive first, then paste its shareable link here. "
                "Make sure sharing is set to \"Anyone with the link can view\" so it plays inline.",
                class_="text-muted small",
            ),
            ui.input_text("video_link", "Google Drive link", placeholder="https://drive.google.com/file/d/.../view?usp=sharing"),
            ui.input_date("video_date", "Date", value=date.today()),
            ui.input_text("video_desc", "Description (optional)", placeholder="e.g. bullpen, BP, live at-bat, side view"),
            ui.input_action_button("add_link_btn", "Add clip", class_="btn-primary mt-2"),
            ui.hr(),
            ui.accordion(
                ui.accordion_panel(
                    "Bulk-add clips",
                    ui.p(
                        "For adding many clips at once for the selected player -- e.g. a full bullpen or BP round "
                        "already uploaded to Drive. One link per line.",
                        class_="text-muted small",
                    ),
                    ui.input_text_area("bulk_links", "Google Drive links (one per line)", rows=6, placeholder="https://drive.google.com/file/d/.../view?usp=sharing\nhttps://drive.google.com/file/d/.../view?usp=sharing"),
                    ui.input_date("bulk_date", "Date these were recorded", value=date.today()),
                    ui.input_text("bulk_desc", "Shared description for bulk-add (optional)", placeholder="e.g. BP round 1"),
                    ui.input_action_button("bulk_add_btn", "Add all", class_="btn-primary mt-2"),
                ),
                open=False, id=None,
            ),
        )

    @reactive.effect
    @reactive.event(input.add_link_btn)
    def _add_clip_single():
        selected_player_id = int(input.player_select())
        link = (input.video_link() or "").strip()
        if not link:
            ui.notification_show("Paste a Google Drive link first.", type="error", duration=8)
            return
        if drive_file_id(link) is None:
            ui.notification_show(
                "That doesn't look like a standard Google Drive file link -- it'll still be saved, but it may not "
                "play inline (an \"Open in a new tab\" link will show alongside it either way).",
                type="warning", duration=10,
            )
        db = get_session()
        try:
            db.add(Video(
                player_id=selected_player_id, assessment_id=None, video_url=link,
                description=(input.video_desc() or "").strip() or None,
                recorded_date=input.video_date(),
            ))
            db.commit()
            ui.notification_show("Clip added.", type="message", duration=6)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.bulk_add_btn)
    def _add_clips_bulk():
        selected_player_id = int(input.player_select())
        raw = input.bulk_links() or ""
        links = [line.strip() for line in raw.splitlines() if line.strip()]
        if not links:
            ui.notification_show("Paste at least one Google Drive link first.", type="error", duration=8)
            return
        bulk_date = input.bulk_date()
        bulk_desc = (input.bulk_desc() or "").strip() if "bulk_desc" in input else ""

        unrecognized = sum(1 for link in links if drive_file_id(link) is None)

        db = get_session()
        try:
            for i, link in enumerate(links, start=1):
                description = f"{bulk_desc} — Clip {i}" if bulk_desc else f"Clip {i}"
                db.add(Video(player_id=selected_player_id, assessment_id=None, video_url=link, description=description, recorded_date=bulk_date))
            db.commit()
            msg = f"Added {len(links)} clip(s)."
            if unrecognized:
                msg += (
                    f" {unrecognized} didn't look like standard Drive file links -- they'll still be saved, but may "
                    "not play inline (an \"Open in a new tab\" link will show alongside each one either way)."
                )
            ui.notification_show(msg, type="message", duration=10)
            _bump_refresh()
        finally:
            db.close()