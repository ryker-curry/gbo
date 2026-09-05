"""
GBO -- Generic hitter silhouette + home plate context shapes for
pitch-location charts (Sept 2026, Ryker: wants a batter graphic on
each side of the strike zone plus the plate on the ground, similar in
spirit to Baseball Savant's illustrator pitch-location graphics).

Sept 2026, rebuild history (for whoever reads this next): two
hand-drawn attempts (overlapping capsule shapes -- seamed/faceted;
then one single outline path -- no seams, but a guessed pose) didn't
hold up, and a third hand-drawn "back view" attempt (Ryker briefly
wanted to see the back elbow, as if the chart were viewed from the
catcher's side) also came out looking bad with no way to preview it
well. Settled convention: this chart's hitters are drawn from the
PITCHER's point of view, not the catcher's -- so the correct image is
a front/side stance (face, arms, bat visible), not a back view. Ryker
supplies the actual reference photo directly; each one gets cleaned up
here (checkerboard/background thresholded out to real alpha
transparency, recolored to the app's own MUTED_GRAY so it reads as
chart context rather than a mismatched gray, cropped tight, downsized)
into assets/hitter_silhouette.png, mirrored once into
assets/hitter_silhouette_flipped.png (see the repo's assets/ dir --
app.py already serves it at the /assets static route via
theme.ASSETS_DIR, same mechanism the GBO logo uses) -- current pair is
Ryker's loaded/leg-kick stance photo. The mirrored copy doubles as
both "the other side of the chart" (pure decoration, flanking the
zone) and, since mirroring a batting stance reads as the opposite-
handed stance, "a left-handed version" of the same pose -- one image
pair serves both asks. Both are placed as Plotly layout images rather
than drawn shapes.

hitter_images(...) returns plain dicts for fig.add_layout_image(**d) --
NOT fig.add_shape like this module's earlier shape-based versions, and
NOT the fig.images property list Plotly also exposes; add_layout_image
is the one Figure method that actually applies the dict's `layer` key
correctly for images (setting it on fig.layout.images entries directly
skips validation of some fields), so callers must use that method, not
add_shape. Sized/positioned in the SAME real-world feet coordinate
system as the calling chart (feet, plate-center at x=0, ground at
y=0), same convention as this module's shape-based functions before
it and as strike_zone.py / chart_theme.py elsewhere in visualizations/.

Usage:
    from visualizations.hitter_graphic import hitter_images, home_plate_shape
    for img in hitter_images(center_x=-1.7, facing="left"):
        fig.add_layout_image(**img)
    for img in hitter_images(center_x=1.7, facing="right"):
        fig.add_layout_image(**img)
    fig.add_shape(**home_plate_shape())
"""

PLATE_COLOR = "#AEB6C2"
PLATE_OUTLINE = "#1E1E1E"

# The source image (see module docstring) is 260x818px, bat swinging up
# toward the image's own right -- i.e. it's already the "facing=right"
# pose. hitter_silhouette_flipped.png is a plain horizontal mirror of
# it (the "facing=left" / left-handed pose), NOT a negative-sizex trick
# on the same file -- simpler and avoids relying on how a given Plotly
# version handles a negative image size. Update this if the source
# photo is ever swapped again -- it must match the new file's actual
# pixel dimensions or "contain" sizing will letterbox instead of fill.
_IMAGE_ASPECT = 260 / 818  # width / height
_SOURCE_BY_FACING = {
    "right": "/assets/hitter_silhouette.png",
    "left": "/assets/hitter_silhouette_flipped.png",
}
IMAGE_OPACITY = 0.55


def hitter_images(center_x, facing="right", height_ft=4.2, ground_y=0.0):
    """One generic hitter image, anchored by its feet. facing="right"
    plants the hitter with the bat swinging up toward +x (the RIGHT-
    side hitter); facing="left" uses the pre-mirrored image (the LEFT-
    side hitter) so the bat swings up toward -x instead -- both bats
    point OUTWARD, away from the plate/zone in the middle. Returns a
    single-item list of a dict for fig.add_layout_image(**d)."""
    width_ft = height_ft * _IMAGE_ASPECT
    return [dict(
        source=_SOURCE_BY_FACING[facing],
        xref="x", yref="y",
        x=center_x, y=ground_y,
        xanchor="center", yanchor="bottom",
        sizex=width_ft, sizey=height_ft,
        sizing="contain",
        opacity=IMAGE_OPACITY,
        layer="below",
    )]


def home_plate_shape(half_width_ft=0.708, depth_ft=0.22, ground_y=0.0, center_x=0.0):
    """Home plate, drawn at the ground line -- same half-width as the
    strike zone (strike_zone.ZONE_HALF_WIDTH, passed in by the caller
    so the two stay in sync) so it reads as directly under the zone.
    Purely decorative context like the hitters above, not a real
    top-down plate outline -- this chart has no "depth" axis to draw
    one on, just enough of a pentagon silhouette sitting on the ground
    line to read as a plate.

    Orientation: on a real plate the flat 17in edge faces the pitcher
    and the back point faces the catcher. This chart's viewpoint is
    the PITCHER's (see hitter_graphic module docstring), so the point
    -- the edge nearest the catcher/backstop, i.e. farthest from the
    pitcher -- reads as farthest from the viewer too, which in this
    ground-level side elevation means closest to the zone above; the
    flat pitcher-facing edge is nearest the viewer, at the bottom. An
    earlier version had this reversed (flat edge up touching the zone,
    point hanging down) -- correct for a catcher's/ump's-eye chart like
    Statcast's, backwards for this pitcher's-eye one, per Ryker's
    "the plate is backwards" -- fixed by flipping which end is which.
    Still a plain fig.add_shape shape (not an image) -- a five-point
    polygon is simpler to draw directly than to round-trip through an
    image asset."""
    hw = half_width_ft
    y_point = ground_y
    y_mid = ground_y - depth_ft
    y_flat = ground_y - depth_ft * 1.7
    path = (
        f"M {center_x:.3f} {y_point:.3f} "
        f"L {center_x + hw:.3f} {y_mid:.3f} "
        f"L {center_x + hw:.3f} {y_flat:.3f} "
        f"L {center_x - hw:.3f} {y_flat:.3f} "
        f"L {center_x - hw:.3f} {y_mid:.3f} Z"
    )
    return dict(
        type="path", xref="x", yref="y", path=path,
        fillcolor=PLATE_COLOR, opacity=0.85,
        line=dict(color=PLATE_OUTLINE, width=1), layer="below",
    )
