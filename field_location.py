"""
GBO — Batted-ball field location (Game Tracking).

Captures WHERE a ball in play landed, as raw coordinates -- not a
Pull/Straight/Oppo classification. That classification depends on
batter handedness, which varies by scenario (our batter, an intrasquad
opponent, an external roster player, or hand-only) and is better
computed later at analysis time than resolved live during entry --
same "store what happened, compute the derived stat later" principle
as everywhere else in this data model. Math verified with round-trip
and visual checks before this was wired into any page.

Coordinate convention: feet from home plate. x = feet right of the
center-field line (negative = left field side, positive = right field
side); y = feet from home plate toward the outfield (0 = the plate).
Top-down view: home plate at the BOTTOM of the image, outfield at TOP.
"""

import math
from PIL import Image, ImageDraw

IMG_WIDTH, IMG_HEIGHT = 400, 420
X_MIN, X_MAX = -350, 350
Y_MIN, Y_MAX = -20, 420

GBO_CRIMSON = "#BF1E2D"
GBO_CREAM = "#FFFDE5"
BG_DARK = "#1E1E1E"

_PX_PER_FT_X = IMG_WIDTH / (X_MAX - X_MIN)
_PX_PER_FT_Y = IMG_HEIGHT / (Y_MAX - Y_MIN)


def field_to_pixel(x, y):
    """Feet (x, y) -> pixel (px, py) on the generated image."""
    px = (x - X_MIN) * _PX_PER_FT_X
    py = IMG_HEIGHT - (y - Y_MIN) * _PX_PER_FT_Y
    return px, py


def pixel_to_field(px, py):
    """Pixel (px, py) from a click -> feet (x, y) from home plate."""
    x = X_MIN + (px / IMG_WIDTH) * (X_MAX - X_MIN)
    y = Y_MIN + ((IMG_HEIGHT - py) / IMG_HEIGHT) * (Y_MAX - Y_MIN)
    return round(x, 1), round(y, 1)


def distance_from_plate(x, y):
    """Straight-line feet from home plate -- useful later for a rough
    infield/outfield split without needing a batter-specific
    classification."""
    if x is None or y is None:
        return None
    return round(math.hypot(x, y), 1)


def generate_field_image(marker_x=None, marker_y=None, marker_color=GBO_CRIMSON):
    """The clickable field graphic -- foul lines, an outfield arc, and
    a small infield diamond for reference. If marker_x/marker_y are
    given (a previously-recorded click), draws a small circle there."""
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), color=BG_DARK)
    draw = ImageDraw.Draw(img)

    plate_px, plate_py = field_to_pixel(0, 0)

    line_dist = 400
    for sign in (-1, 1):
        end_x, end_y = field_to_pixel(sign * line_dist * math.sin(math.radians(45)), line_dist * math.cos(math.radians(45)))
        draw.line([(plate_px, plate_py), (end_x, end_y)], fill=GBO_CREAM, width=2)

    radius_ft = 350
    r_px_x = radius_ft * _PX_PER_FT_X
    r_px_y = radius_ft * _PX_PER_FT_Y
    draw.arc(
        [plate_px - r_px_x, plate_py - r_px_y, plate_px + r_px_x, plate_py + r_px_y],
        start=225, end=315, fill=GBO_CREAM, width=2,
    )

    base_dist = 90  # feet, real basepath distance -- small reference markers only
    for angle in (45, 135, 225, 315):
        bx, by = field_to_pixel(base_dist * math.sin(math.radians(angle)), base_dist * math.cos(math.radians(angle)))
        draw.ellipse([bx - 3, by - 3, bx + 3, by + 3], fill=GBO_CREAM)

    if marker_x is not None and marker_y is not None:
        mx, my = field_to_pixel(marker_x, marker_y)
        r = 8
        draw.ellipse([mx - r, my - r, mx + r, my + r], fill=marker_color, outline=GBO_CREAM, width=2)

    return img