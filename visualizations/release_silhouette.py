"""
GBO -- Release-point pitcher silhouette (Aug 2026 addition; revised
three times since -- first per Ryker: show every pitch's release point
+ arm, not just one averaged point, and fix the shoulder/arm-line not
lining up with the illustrated body; then per Ryker again: one marker
per PITCH TYPE (that type's average release point), not one per
individual pitch -- matching the existing release_point_chart's
"average by pitch type" panel it sits next to, and reusing that same
panel's per-pitch-type color convention (spec Section 23: pitch colors
never invented here, always looked up) instead of a flat gold dot; and
now (third revision) a full body-illustration redesign, from a thin
stick figure to a solid-shaded athletic silhouette with a proper
tapered throwing arm, per Ryker's follow-up that the stick figure
"does not look right."

Ryker's reference for this third revision was a screenshot of a
third-party commercial product's own release-point panel (solid
silhouette, tube-like arm, overlapping release markers at the hand).
This module deliberately does NOT reproduce that product's specific
artwork, palette, or branding -- every shape below is still hand-built
from basic SVG primitives (path/circle/rect/line), just with fuller,
filled body shapes and a proper tapered arm instead of thin stroked
"stick" limbs, styled in GBO's own dark/gold theme. Original
illustration only, same as every earlier revision -- see the module's
standing "not a copy or reproduction of any third-party product's
artwork" rule, unchanged.

An ORIGINAL, minimalist SVG illustration of a pitcher at release,
viewed from behind (looking from center field toward home plate, i.e.
the pitcher's back) standing on a stylized mound -- NOT a copy or
reproduction of any third-party product's artwork.

Returns a plain SVG string -- no Shiny/plotly import here, matching
visualizations/bullpen_charts.py's own "pure viz function, caller
wraps it" pattern (there: Plotly Figure -> chart_helpers.fig_to_img();
here: SVG string -> ui.HTML() at the call site). Deliberately NOT a
Plotly figure -- a plotly version would mean another kaleido PNG
render per pitcher switch, and this dashboard's own code already flags
kaleido cost as a real, previously-hit performance problem (see
shiny_app/bullpen_dashboard_display.py's docstring: charts "streaming
in one at a time" and websocket timeouts were both kaleido-render-time
problems). Inline SVG costs nothing extra to render.

COORDINATE CONVENTION -- deliberately matches visualizations.
bullpen_charts.release_point_chart's existing axes exactly, so this
panel and that existing scatter chart agree with each other sitting
side by side: Release Side in ft, range [-4, 4] (same X_MIN/X_MAX);
Release Height in ft, range [0, 8] (same Y_MIN/Y_MAX). Release Side is
plotted at its raw, unflipped signed value -- same as release_point_
chart already does -- rather than this module inventing its own
sign-flip. See this module's KNOWN LIMITATION note below for what that
convention does and doesn't guarantee.

PER-PITCH-TYPE AVERAGE MARKERS -- the caller passes one
(release_height_ft, release_side_ft, color, label, n) tuple per pitch
type actually thrown, each already averaged over that type's pitches
and colored via visualizations.bullpen_charts.color_for_pitch_label --
the exact same lookup release_point_chart's own "average" mode uses,
so a fastball marker here and a fastball dot on that adjacent chart
are always the same color, never a separately-invented one. This
module does not compute the average or pick the color itself -- both
arrive from the caller -- keeping this file a pure "given these
points, draw them" renderer per the established calculations-vs-
visualization split.

SOLID ARM + PER-TYPE RAYS (third revision) -- rather than one uniform
gold line to every marker, the pitch type with the MOST pitches (the
pitcher's primary/most-thrown type) gets a solid, filled, tapered
"tube" arm illustrated from the shoulder anchor to that type's release
point, ending in a rounded hand -- this is the pitcher's illustrated
throwing arm, not just a data line. Every OTHER pitch type still gets
a thin line from the same shoulder anchor to its own release point,
now colored to match THAT type's own color (matching the same
per-pitch-type-colored-ray convention just added to the Movement
Profile chart's arm-angle rays -- visualizations.bullpen_charts.
_add_arm_angle_rays -- so the two panels read the same way) instead of
a flat gold line. All release points, including the primary type's,
still get their own colored marker circle drawn on top, so every
type's exact release point stays visible even where the solid arm
overlaps it.

SHOULDER ANCHOR -- the "arm" line (spec: "a subtle line from the
approximate shoulder location to the release point... should
correspond visually to the calculated arm angle") is the straight line
between two points plotted in the SAME ft-based coordinate system as
everything else: each pitch type's average release point, and one
assumed shoulder point at (horizontal center, estimated shoulder
height). Estimated shoulder height reuses analytics.pitch_trajectory.
SHOULDER_HEIGHT_FRACTION (0.70 * player height) -- the exact same
assumption calculate_estimated_arm_angle uses -- so each line's
rendered angle is geometrically guaranteed to match that pitch type's
numeric Estimated Arm Angle, by construction, not by a second parallel
calculation that could quietly drift out of sync with the first.

The illustrated body (torso/head/solid arm) is built FROM this same
computed shoulder pixel point (falling back to a stylized fixed
position only when there's no player height to place it with), so the
body and every arm line always agree -- this was a real bug in an
earlier revision (separately-positioned stylized shoulder vs.
data-driven line origin landing on different pixels) that is fixed by
construction, not just by coincidence, and stays fixed across this
revision too since nothing about the shoulder-anchor math changed.

KNOWN LIMITATION -- handedness mirroring: the STICK-FIGURE BODY (legs/
torso stance) mirrors left-right based on `throws` (a real, confirmed
Player field). The RELEASE MARKERS and arm lines use each pitch type's
raw average release_side value UNFLIPPED, matching release_point_
chart's own convention -- but Rapsodo's real left/right sign
convention for release side is NOT independently confirmed anywhere in
this codebase yet (see rapsodo_conventions.strike_zone_inches_to_
plate_feet's docstring, which flags the same open question for the
adjacent strike-zone-side field). In practice this means: markers are
trustworthy relative to each other (a bigger number is further to one
consistent side, type to type), but whether that visually lines up
with the "correct" side for a given throwing hand has not been checked
against real video. Flag to Ryker to spot-check once this is live.
"""

from analytics.pitch_trajectory import SHOULDER_HEIGHT_FRACTION

# Matches release_point_chart's fixed axis range exactly -- see module docstring.
X_MIN_FT, X_MAX_FT = -4.0, 4.0
Y_MIN_FT, Y_MAX_FT = 0.0, 8.0

VIEW_W, VIEW_H = 320, 380
_GROUND_Y = 338.0          # px -- Y_MIN_FT (0 ft) maps here
_TOP_Y = 34.0               # px -- Y_MAX_FT (8 ft) maps here
_CENTER_X = 160.0           # px -- release_side 0 ft maps here
_LEFT_X, _RIGHT_X = 46.0, 274.0   # px -- X_MIN_FT / X_MAX_FT map here

_SCALE_Y = (_GROUND_Y - _TOP_Y) / (Y_MAX_FT - Y_MIN_FT)
_SCALE_X = (_RIGHT_X - _LEFT_X) / (X_MAX_FT - X_MIN_FT)

# Stylized fallback shoulder position (px) used only when there's no
# player height to place the shoulder from real data -- keeps the body
# illustration rendering instead of going blank.
_FALLBACK_SHOULDER_X = _CENTER_X
_FALLBACK_SHOULDER_Y = _GROUND_Y - 120.0

# Fixed, stylized torso/neck lengths (px) -- not biomechanically exact,
# same "illustration, not a measurement" spirit as the rest of the body.
_TORSO_LEN_PX = 46.0
_NECK_LEN_PX = 18.0


def _ft_to_px(side_ft, height_ft):
    """Map (release_side_ft, release_height_ft) -> (x_px, y_px), clamped
    to stay on the visible mound/backdrop even for an outlier reading
    (per spec's "unusually low/high release height" edge case) --
    clamping is purely a rendering safeguard, it never changes the
    displayed numeric values elsewhere on the page."""
    x = _CENTER_X + side_ft * _SCALE_X
    y = _GROUND_Y - height_ft * _SCALE_Y
    x = max(10.0, min(VIEW_W - 10.0, x))
    y = max(10.0, min(_GROUND_Y, y))
    return x, y


# Bullpen Dashboard's own established dark-card palette (shiny_app/
# bullpen_dashboard_display.py's _card()/GOLD/TEXT_CREAM) -- this panel
# lives inside that same card, so it uses the SAME literal colors
# rather than the app-wide --gbo-* light/dark tokens bucket_display.py
# uses elsewhere; the Bullpen Dashboard section is its own fixed dark
# theme by original design, unrelated to the global light/dark toggle.
_GOLD = "#D4AF37"
_BODY_FILL = "#8A8578"        # neutral warm gray -- the silhouette's base fill
_BODY_SHADE = "#5F5B4E"       # darker tone -- trailing leg/cleats, for depth
_BODY_HIGHLIGHT = "#A6A192"   # lighter tone -- subtle top-edge highlight on the torso
_MOUND_COLOR = "#241C18"
_MOUND_EDGE = "rgba(212,175,55,0.35)"
_RUBBER_COLOR = "#EDEAE0"


def render_release_silhouette_svg(release_points, player_height_in, throws):
    """Build the full silhouette SVG for this pitcher: a solid-shaded
    body illustration with one tapered throwing arm to the pitcher's
    primary (most-thrown) pitch type's average release point, plus one
    thin colored ray + marker per OTHER pitch type thrown, each at that
    type's own average release point. Returns an SVG string ready for
    ui.HTML().

    release_points: list of (release_height_ft, release_side_ft, color,
    label, n) tuples, one per pitch type -- already averaged and
    colored by the caller (see module docstring). An entry with either
    coordinate None is skipped individually rather than dropping the
    whole panel. The entry with the largest n becomes the "primary"
    type the solid illustrated arm points to; ties keep the caller's
    original list order (first one wins), same tie-break spirit as the
    rest of this codebase's first-seen-order grouping.

    player_height_in: without it there's no way to place the shoulder,
    so the arm (solid or thin-ray) is skipped entirely (markers still
    show, in their pitch-type colors) and a caption explains why.

    throws: 'R' or 'L' (Player.throws) -- mirrors the stick-figure
    stance only; see module docstring for what does and doesn't mirror.
    """
    mirror = throws == "L"
    stance_x = -1 if mirror else 1  # +1 = legs/lead-arm stance drawn toward +X (RHP default)

    valid_points = [
        (h, s, color, label, n) for (h, s, color, label, n) in release_points
        if h is not None and s is not None
    ]
    has_release = len(valid_points) > 0
    has_height = player_height_in is not None

    # Primary = most-thrown type among the ones with a plottable release
    # point -- gets the solid illustrated arm; ties keep first-seen order.
    primary = None
    if valid_points:
        primary = max(valid_points, key=lambda pt: pt[4])
    secondary_points = [pt for pt in valid_points if pt is not primary] if primary else []

    svg_parts = [
        f'<svg viewBox="0 0 {VIEW_W} {VIEW_H}" xmlns="http://www.w3.org/2000/svg" '
        f'style="width:100%; height:auto; display:block; max-width:340px; margin:0 auto;" role="img" '
        f'aria-label="Pitcher release point">'
    ]

    # --- Mound (soft trapezoid) + rubber ---
    svg_parts.append(
        f'<path d="M 10,{_GROUND_Y+2:.0f} Q {VIEW_W/2:.0f},{_GROUND_Y-34:.0f} {VIEW_W-10},{_GROUND_Y+2:.0f} '
        f'L {VIEW_W-10},{VIEW_H-6} L 10,{VIEW_H-6} Z" fill="{_MOUND_COLOR}" stroke="{_MOUND_EDGE}" stroke-width="1.5"/>'
    )
    svg_parts.append(
        f'<rect x="{_CENTER_X-20:.0f}" y="{_GROUND_Y-40:.0f}" width="40" height="8" rx="2" fill="{_RUBBER_COLOR}" opacity="0.92"/>'
    )
    svg_parts.append(
        f'<text x="{_CENTER_X:.0f}" y="{VIEW_H-14}" text-anchor="middle" fill="{_BODY_FILL}" font-size="11" '
        f'font-family="inherit" letter-spacing="0.08em">PITCHING MOUND</text>'
    )

    # --- Shoulder anchor: the SAME pixel point drives both the
    # illustrated body AND every data-driven arm/ray, so the two can
    # never visually disconnect (see module docstring). Falls back to a
    # stylized fixed position only when there's no height to place it
    # from real data.
    if has_height:
        shoulder_height_ft = (float(player_height_in) / 12.0) * SHOULDER_HEIGHT_FRACTION
        shoulder_x, shoulder_y = _ft_to_px(0.0, shoulder_height_ft)
    else:
        shoulder_x, shoulder_y = _FALLBACK_SHOULDER_X, _FALLBACK_SHOULDER_Y

    hip_x, hip_y = _CENTER_X, shoulder_y + _TORSO_LEN_PX
    head_cx, head_cy = shoulder_x, shoulder_y - _NECK_LEN_PX

    # --- Solid-shaded body, standing at the mound's peak, stylized (not
    # a biomechanically exact stride). Filled shapes throughout instead
    # of thin stroked "stick" limbs, per Ryker's "does not look right"
    # feedback on the earlier stick-figure revision. ---

    # Legs -- solid tapered pillars (thick round-capped strokes read as
    # filled tubes at this width), back leg trailing and shaded darker
    # (depth cue -- it's the leg further from the "camera" in this
    # from-behind view), front (lead) leg planted toward the stance
    # direction in the base body color, each with a small cleat mark at
    # the ground.
    back_knee_x, back_knee_y = hip_x - 7 * stance_x, hip_y + 34
    back_foot_x, back_foot_y = hip_x - 11 * stance_x, _GROUND_Y - 4
    svg_parts.append(
        f'<path d="M {hip_x:.0f},{hip_y:.0f} L {back_knee_x:.0f},{back_knee_y:.0f} L {back_foot_x:.0f},{back_foot_y:.0f}" '
        f'stroke="{_BODY_SHADE}" stroke-width="15" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    )
    svg_parts.append(f'<ellipse cx="{back_foot_x:.0f}" cy="{_GROUND_Y-2:.0f}" rx="11" ry="4" fill="{_MOUND_COLOR}" opacity="0.6"/>')

    front_knee_x, front_knee_y = hip_x + 24 * stance_x, hip_y + 40
    front_foot_x, front_foot_y = hip_x + 36 * stance_x, _GROUND_Y - 4
    svg_parts.append(
        f'<path d="M {hip_x:.0f},{hip_y:.0f} L {front_knee_x:.0f},{front_knee_y:.0f} L {front_foot_x:.0f},{front_foot_y:.0f}" '
        f'stroke="{_BODY_FILL}" stroke-width="16" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    )
    svg_parts.append(f'<ellipse cx="{front_foot_x:.0f}" cy="{_GROUND_Y-2:.0f}" rx="12" ry="4" fill="{_MOUND_COLOR}" opacity="0.6"/>')

    # Torso -- a real filled silhouette shape (broad shoulders tapering
    # to the waist), not a stroked line, so the figure reads as a solid
    # athlete rather than a wireframe.
    svg_parts.append(
        f'<path d="M {shoulder_x-27:.0f},{shoulder_y-3:.0f} '
        f'C {shoulder_x-32:.0f},{shoulder_y+16:.0f} {hip_x-21:.0f},{hip_y-18:.0f} {hip_x-16:.0f},{hip_y:.0f} '
        f'L {hip_x+16:.0f},{hip_y:.0f} '
        f'C {hip_x+21:.0f},{hip_y-18:.0f} {shoulder_x+32:.0f},{shoulder_y+16:.0f} {shoulder_x+27:.0f},{shoulder_y-3:.0f} '
        f'Q {shoulder_x:.0f},{shoulder_y-15:.0f} {shoulder_x-27:.0f},{shoulder_y-3:.0f} Z" '
        f'fill="{_BODY_FILL}"/>'
    )
    # Subtle highlight along the upper back edge -- a thin lighter arc,
    # purely a shading cue, not a second shape competing with the torso fill.
    svg_parts.append(
        f'<path d="M {shoulder_x-22:.0f},{shoulder_y-2:.0f} Q {shoulder_x:.0f},{shoulder_y-11:.0f} {shoulder_x+22:.0f},{shoulder_y-2:.0f}" '
        f'stroke="{_BODY_HIGHLIGHT}" stroke-width="2.5" fill="none" opacity="0.55" stroke-linecap="round"/>'
    )

    # Glove (non-throwing) arm -- short, bent across the front of the
    # torso for balance, filled tapered tube matching the new limb style.
    svg_parts.append(
        f'<path d="M {shoulder_x-4*stance_x:.0f},{shoulder_y+6:.0f} '
        f'L {shoulder_x-18*stance_x:.0f},{shoulder_y+27:.0f} '
        f'L {shoulder_x-8*stance_x:.0f},{shoulder_y+46:.0f}" '
        f'stroke="{_BODY_FILL}" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    )

    # Head + a small two-tone cap (an original GBO-styling touch, gold
    # accent -- not a reproduction of any reference image's headwear).
    svg_parts.append(f'<circle cx="{head_cx:.0f}" cy="{head_cy:.0f}" r="15" fill="{_BODY_FILL}"/>')
    svg_parts.append(
        f'<path d="M {head_cx-14:.0f},{head_cy-4:.0f} '
        f'Q {head_cx:.0f},{head_cy-22:.0f} {head_cx+14:.0f},{head_cy-4:.0f} '
        f'Q {head_cx:.0f},{head_cy-10:.0f} {head_cx-14:.0f},{head_cy-4:.0f} Z" fill="{_GOLD}" opacity="0.9"/>'
    )
    svg_parts.append(
        f'<ellipse cx="{head_cx+9*stance_x:.0f}" cy="{head_cy-3:.0f}" rx="9" ry="3.5" fill="{_GOLD}" opacity="0.9"/>'
    )

    # --- Data-driven: the primary (most-thrown) pitch type gets a
    # solid, tapered illustrated throwing arm from the shoulder anchor
    # to its release point, with a rounded "hand" at the end. Every
    # other type gets a thin ray in ITS OWN pitch-type color (matching
    # visualizations.bullpen_charts._add_arm_angle_rays's convention on
    # the Movement Profile chart) instead of a flat gold line. All
    # valid types -- primary included -- get their own colored marker
    # circle drawn last so it always sits on top. ---
    if has_release and has_height:
        p_h, p_s, p_color, p_label, p_n = primary
        hand_x, hand_y = _ft_to_px(p_s, p_h)
        # Slight bend at the "elbow" (roughly midway, offset toward the
        # release side) so the tube reads as an arm rather than a dead-
        # straight rod -- stylized, not a biomechanical elbow position.
        elbow_x = shoulder_x + (hand_x - shoulder_x) * 0.55
        elbow_y = shoulder_y + (hand_y - shoulder_y) * 0.35 + 10
        svg_parts.append(
            f'<path d="M {shoulder_x:.0f},{shoulder_y:.0f} Q {elbow_x:.0f},{elbow_y:.0f} {hand_x:.0f},{hand_y:.0f}" '
            f'stroke="{_BODY_FILL}" stroke-width="12" stroke-linecap="round" fill="none"/>'
        )
    elif has_release and not has_height:
        pass  # no shoulder to draw an arm from -- markers alone still render below

    if has_release:
        for h, s, color, label, n in secondary_points:
            rx, ry = _ft_to_px(s, h)
            if has_height:
                svg_parts.append(
                    f'<line x1="{shoulder_x:.0f}" y1="{shoulder_y:.0f}" x2="{rx:.0f}" y2="{ry:.0f}" '
                    f'stroke="{color}" stroke-width="2.5" stroke-linecap="round" opacity="0.8"/>'
                )
            svg_parts.append(
                f'<circle cx="{rx:.0f}" cy="{ry:.0f}" r="8" fill="{color}" '
                f'stroke="{_MOUND_COLOR}" stroke-width="1.5" opacity="0.95"/>'
            )
        if primary is not None:
            p_h, p_s, p_color, p_label, p_n = primary
            prx, pry = _ft_to_px(p_s, p_h)
            svg_parts.append(
                f'<circle cx="{prx:.0f}" cy="{pry:.0f}" r="9" fill="{p_color}" '
                f'stroke="{_MOUND_COLOR}" stroke-width="1.5" opacity="0.95"/>'
            )
    else:
        pass  # caption below explains the empty panel

    svg_parts.append('</svg>')
    svg = "".join(svg_parts)

    if not has_release:
        return svg, "Release point unavailable — Release Height/Side required"
    if not has_height:
        return svg, "Estimated Arm Angle lines require this pitcher's height (Players page)"
    return svg, None
