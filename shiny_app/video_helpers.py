"""
GBO -- Shared "render a stored video_url as a playable clip" helper.

Extracted from video_import.py's original private `_drive_file_id`/
`_clip_player`. This app has TWO different kinds of video_url in play
at once, not one:
  - Video.video_url and HitterSwing.video_url are pasted Google Drive
    share links (e.g. https://drive.google.com/file/d/FILE_ID/view?...)
    -- video_import.py and hitter_tracking.py both dropped direct file
    upload in favor of "paste a Drive link" (see each module's
    docstring). A Drive "view" URL is an HTML page, not a raw video
    stream, so a plain <video src> tag CANNOT play it -- it needs
    Drive's dedicated embeddable preview URL (.../file/d/FILE_ID/preview)
    in an <iframe> instead.
  - BullpenPitch.video_url is still a genuine uploaded file, hosted on
    Cloudflare R2 (see bullpen_tracking.py's ui.input_file + r2_client.
    upload_video_to_r2 -- that page was NOT redesigned to Drive links).
    An R2 URL IS a direct, playable video file, so a plain <video src>
    tag works fine for it -- wrapping it in Drive-only logic would
    break it (no Drive file ID to extract -> falls through to a bare
    "can't play" message instead of actually playing).

render_video_clip() below handles both without the caller needing to
know which kind a given URL is: Drive share links get the iframe
embed; anything else gets a native <video> tag (correct for R2 and any
other direct file URL) PLUS an always-visible "Open in a new tab"
link underneath, so a URL the browser's <video> tag genuinely can't
play (e.g. a Drive FOLDER link pasted by mistake) still has a working
way to view it instead of silently failing.

Public (unlike video_import._clip_player, which stayed private/
internal to that module, and the module's original single-branch
"Drive-only" version of this function, which briefly existed here too)
because bullpen_tracking.py, hitter_tracking.py, and player_video.py
all independently render a video_url too. Before this fix, every one
of those used a plain `ui.tags.video(ui.tags.source(src=url), ...)`
call -- which happened to work for bullpen_tracking.py (R2 URLs) but
never worked for a Drive share link (hitter_tracking.py's swings,
video_import.py's general clips) -- invisible on the coach's Video
Import page (which had its own correct embed logic) but broken
everywhere else a clip could be watched, including the exact page a
player uses to view their own video.

Found and fixed after a report that a general (Video Import) clip
showed up in the player's My Video list but wouldn't play. Note:
sharing still has to be set to "Anyone with the link can view" in
Drive for the embed to load for someone without access to the file
otherwise -- that part hasn't changed and still has to be right on the
uploader's end; this fix only addresses the app-side rendering bug,
not a link that's actually still permission-restricted.
"""

import re

from shiny import ui

_DRIVE_FILE_ID_PATTERNS = [
    re.compile(r"/file/d/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
]


def drive_file_id(url: str):
    """Extracts a Google Drive file ID from the common share-link
    shapes (.../file/d/FILE_ID/view?... and .../open?id=FILE_ID).
    Returns None if the link doesn't match either -- callers should
    treat a None result as "probably a direct file URL" (see
    render_video_clip), not assume it's unplayable."""
    url = (url or "").strip()
    if not url:
        return None
    for pattern in _DRIVE_FILE_ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def render_video_clip(url: str, height: str = "480"):
    """Renders one clip, correctly, regardless of whether `url` is a
    Google Drive share link or a direct file URL (e.g. R2) -- see this
    module's docstring for why both exist in this app. This is the
    correct way to render EVERY video_url in this app -- never use a
    plain ui.tags.video/ui.tags.source pair directly on one, since that
    silently fails to play for a Drive link."""
    file_id = drive_file_id(url)
    if file_id:
        preview_url = f"https://drive.google.com/file/d/{file_id}/preview"
        return ui.tags.iframe(
            src=preview_url, width="100%", height=height,
            allow="autoplay", style="border:0; max-width:100%;",
        )
    return ui.div(
        ui.tags.video(ui.tags.source(src=url), controls=True, style="max-width:100%;"),
        ui.p(
            ui.tags.a("Open video in a new tab", href=url, target="_blank", rel="noopener noreferrer"),
            class_="text-muted small mt-1",
        ),
    )