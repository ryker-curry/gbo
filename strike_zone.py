"""
GBO — Strike zone coordinate system (Game Tracking).

Replaces manual 1-9 zone-button entry with click-the-exact-spot
location, per Ryker's architecture doc. All math here was verified
with round-trip and zone-center tests before this was wired into any
page -- see the conversation this was built in for the test output.

Coordinate convention (matches Statcast/Trackman): plate_x in feet,
0 = center of the plate; plate_z in feet, 0 = the ground. Positive
plate_x is drawn on the right side of the generated image.

The image is intentionally simple (zone rectangle + 3x3 reference grid
+ ground line) rather than a photorealistic batter/plate graphic --
easy to read at a glance during a live game, which matters more than
visual flourish here.
"""

from PIL import Image, ImageDraw

IMG_WIDTH, IMG_HEIGHT = 400, 500

# View window in feet -- wide/tall enough to click a real ball (chase
# pitch, pitchout) without the zone itself being tiny.
X_MIN, X_MAX = -2.5, 2.5
Z_MIN, Z_MAX = 0.0, 5.0

# Generic average strike zone (17in plate width; knee-to-letters
# height). Not batter-specific -- GBO doesn't track individual batter
# heights/stances, so this is the same reasonable default everywhere,
# same as the old 1-9 grid was.
ZONE_HALF_WIDTH = 0.708  # ft, half of 17 inches
ZONE_BOTTOM, ZONE_TOP = 1.5, 3.5

GBO_CRIMSON = "#BF1E2D"
GBO_CREAM = "#FFFDE5"
BG_DARK = "#1E1E1E"
GRID_GRAY = "#3A3A3A"


def plate_to_pixel(x, z):
    """Feet (plate_x, plate_z) -> pixel (px, py) on the generated image."""
    px = (x - X_MIN) / (X_MAX - X_MIN) * IMG_WIDTH
    py = IMG_HEIGHT - (z - Z_MIN) / (Z_MAX - Z_MIN) * IMG_HEIGHT
    return px, py


def pixel_to_plate(px, py):
    """Pixel (px, py) from a click on the generated image -> feet
    (plate_x, plate_z)."""
    x = X_MIN + (px / IMG_WIDTH) * (X_MAX - X_MIN)
    z = Z_MIN + ((IMG_HEIGHT - py) / IMG_HEIGHT) * (Z_MAX - Z_MIN)
    return round(x, 3), round(z, 3)


def derive_old_zone(plate_x, plate_z):
    """Precise coordinates -> the old 1-9 grid + 0=Bury convention, so
    existing execution-accuracy calculations elsewhere in the app
    (game_stats.py, Bullpen/Hitter Tracking comparisons) keep working
    unchanged. Verified against all 9 zone centers + Bury + an
    outside-the-zone clamping case before use. Layout:
        1 2 3   (top third)
        4 5 6   (middle third)
        7 8 9   (bottom third)
    Meaningfully below the zone (more than ~2 inches under the bottom)
    -> 0 (Bury). Coordinates outside the zone horizontally or above it
    vertically are clamped to the nearest column/row rather than left
    unclassified -- there's no exact old-system equivalent for "how far
    outside," so nearest-zone is the most useful fallback."""
    if plate_x is None or plate_z is None:
        return None
    if plate_z < ZONE_BOTTOM - 0.15:
        return 0
    col_frac = (plate_x - (-ZONE_HALF_WIDTH)) / (2 * ZONE_HALF_WIDTH)
    col_frac = max(0.0, min(0.999, col_frac))
    col = int(col_frac * 3)
    row_frac = (ZONE_TOP - plate_z) / (ZONE_TOP - ZONE_BOTTOM)
    row_frac = max(0.0, min(0.999, row_frac))
    row = int(row_frac * 3)
    zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    return zone_layout[row][col]


def is_in_zone(plate_x, plate_z):
    """Simple in/out-of-zone check from precise coordinates -- used for
    a quick located/not-located indicator without needing the full
    heat-map classification work (Edge/Heart/Chase), which is a later
    phase."""
    if plate_x is None or plate_z is None:
        return None
    return (-ZONE_HALF_WIDTH <= plate_x <= ZONE_HALF_WIDTH) and (ZONE_BOTTOM <= plate_z <= ZONE_TOP)


def generate_zone_image(marker_x=None, marker_z=None, marker_color=GBO_CRIMSON):
    """The clickable strike-zone graphic. If marker_x/marker_z are
    given (a previously-recorded click), draws a small circle there so
    the coach can see what was captured, not just a blank zone."""
    img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), color=BG_DARK)
    draw = ImageDraw.Draw(img)

    ground_y = plate_to_pixel(0, 0)[1]
    draw.line([(0, ground_y), (IMG_WIDTH, ground_y)], fill=GRID_GRAY, width=2)

    x1, y1 = plate_to_pixel(-ZONE_HALF_WIDTH, ZONE_TOP)
    x2, y2 = plate_to_pixel(ZONE_HALF_WIDTH, ZONE_BOTTOM)
    draw.rectangle([x1, y1, x2, y2], outline=GBO_CREAM, width=3)

    for i in range(1, 3):
        gx = x1 + (x2 - x1) * i / 3
        draw.line([(gx, y1), (gx, y2)], fill=GBO_CREAM, width=1)
        gy = y1 + (y2 - y1) * i / 3
        draw.line([(x1, gy), (x2, gy)], fill=GBO_CREAM, width=1)

    if marker_x is not None and marker_z is not None:
        mx, my = plate_to_pixel(marker_x, marker_z)
        r = 8
        draw.ellipse([mx - r, my - r, mx + r, my + r], fill=marker_color, outline=GBO_CREAM, width=2)

    return img