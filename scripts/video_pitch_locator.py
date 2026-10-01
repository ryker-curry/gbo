"""
GBO -- Video pitch locator (Sept 30 2026).

Ryker's ask: "send you a video of a pitch and you give me pitch location
from it." Workflow agreed via AskUserQuestion: clips come from the
CENTER-FIELD camera (same setup as the Sept 12 intrasquad clips),
attached in chat; output is plate_x/plate_z in feet (GBO convention,
see strike_zone.py), the 1-9/Bury zone, attack-zone tier, a confidence
band, and an annotated frame + zone picture.

The vision step (finding the plate and the ball in the frame) is done
by a person or by Claude looking at the gridded frames this script
produces -- this script does NOT try to auto-detect the ball. That's a
deliberate call: from ~400 ft away the ball is 10-20 px, often motion-
blurred and half-hidden by the pitcher's follow-through, and an
auto-detector that silently latches onto a white shoe or a batting
glove would produce confident wrong numbers. What this script owns is
everything around that step, so the math has exactly one
implementation:

  scan    -- probe the clip, find the burst of motion around the
             plate, write a timestamped contact sheet of the clip.
  frames  -- dump full-res frames for a time window, cropped to the
             plate area, with a pixel grid labeled in FULL-FRAME
             coordinates so points can be read straight off them.
  locate  -- pixel points (plate corners + ball) -> plate_x/plate_z,
             zone, tier, uncertainty, and two PNGs (annotated frame,
             pitcher's-view zone chart).

COORDINATES / SIGN CONVENTION -- matches strike_zone.py and
rapsodo_conventions.py exactly: plate_x in feet, 0 = plate center,
NEGATIVE = third-base side (arm side for a RHP), positive = first-base
side; plate_z in feet, 0 = ground. A center-field camera looks IN at
home, so the 3B side is on the RIGHT of the image -- plate_x is the
mirror of image-x there (--camera cf, the default). A camera behind
home plate looks OUT, 3B on the left, so no mirror (--camera home).

CALIBRATION -- the plate's 17-in front edge (its two front corners) sets
both the scale (ft per pixel) and the origin: midpoint = plate_x 0,
its image row = plate_z 0 (ground). A long-lens CF camera is close to
orthographic over the few feet around the plate, so one scale for x
and z is a good approximation; if the plate is hidden, --ref accepts
any two points a known distance apart AT PLATE DEPTH (e.g. the outer
chalk lines of the two batter's boxes: 17 + 2*6 + 2*48 = 125 in) plus
--origin for the plate-center/ground pixel.

CATCH-POINT CORRECTION -- the ball is usually located where it meets
the mitt, which is behind the plate, and the pitch keeps dropping
after it crosses the front of the plate. --catch-depth (ft behind the
front of the plate, default 1.5) and --vaa (vertical approach angle,
deg, default by pitch type) add back that extra drop:
    plate_z = z_at_catch + catch_depth * tan(|VAA|)
Typical college VAAs (fastball ~ -5 deg, breaking ~ -8 to -10 deg) make
this a 1.5-3.5 in correction. A catcher who reaches/frames before the
ball arrives moves the mitt, not the ball, so pick the ball in the
first frame it touches the mitt, not the settled mitt.

Runs anywhere with ffmpeg + numpy + Pillow + matplotlib; imports
strike_zone.py for zone math when run from the repo root and falls
back to a mirrored copy of the same constants otherwise (Claude runs
it from a scratch workspace where the repo isn't importable).

Usage (from repo root):
    python3 scripts/video_pitch_locator.py scan   clip.mp4 --out out/
    python3 scripts/video_pitch_locator.py frames clip.mp4 --start 3.4 --end 3.9 --crop 1300,850,700,500 --out out/
    python3 scripts/video_pitch_locator.py locate --frame out/f_3.650.png \\
        --plate-left 1520,1255 --plate-right 1628,1255 --ball 1590,1105 \\
        --pitch-type FB --out out/
"""

import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    from strike_zone import (  # noqa: E402
        ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP,
        derive_old_zone, is_in_zone, classify_attack_zone,
    )
    _ZONE_SOURCE = "strike_zone.py"
except Exception:  # repo not importable -- mirrored constants, keep in sync
    ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP = 0.708, 1.5, 3.5
    _ZONE_SOURCE = "fallback constants (mirror of strike_zone.py)"

    def derive_old_zone(x, z):
        if x is None or z is None:
            return None
        if z < ZONE_BOTTOM - 0.15:
            return 0
        c = int(max(0.0, min(0.999, (x + ZONE_HALF_WIDTH) / (2 * ZONE_HALF_WIDTH))) * 3)
        r = int(max(0.0, min(0.999, (ZONE_TOP - z) / (ZONE_TOP - ZONE_BOTTOM))) * 3)
        return [[1, 2, 3], [4, 5, 6], [7, 8, 9]][r][c]

    def is_in_zone(x, z):
        return (-ZONE_HALF_WIDTH <= x <= ZONE_HALF_WIDTH) and (ZONE_BOTTOM <= z <= ZONE_TOP)

    def classify_attack_zone(x, z):
        px, pz = 3.3 / 12, 4.0 / 12
        cz, hh = (ZONE_BOTTOM + ZONE_TOP) / 2, (ZONE_TOP - ZONE_BOTTOM) / 2
        ax, dz = abs(x), abs(z - cz)
        if ax <= ZONE_HALF_WIDTH - px and dz <= hh - pz:
            return "Heart"
        if ax <= ZONE_HALF_WIDTH + px and dz <= hh + pz:
            return "Shadow"
        if ax <= ZONE_HALF_WIDTH * 2 and dz <= hh * 2:
            return "Chase"
        return "Waste"

PLATE_WIDTH_IN = 17.0
CRIMSON, CREAM, BG_DARK, GRID = "#BF1E2D", "#FFFDE5", "#1E1E1E", "#3A3A3A"

# Default VAA (deg, magnitude) by pitch-type shorthand when --vaa isn't
# given. College-level ballparks, only used for the small catch-point
# correction above -- not a claim about any specific pitcher.
DEFAULT_VAA = {"FB": 5.5, "4S": 5.5, "2S": 6.0, "SI": 6.0, "CT": 6.5,
               "SL": 7.5, "SW": 7.5, "CH": 7.5, "SP": 8.0, "CB": 9.5, "KC": 9.5}
FALLBACK_VAA = 6.5


# ------------------------------------------------------------------ core math

def pixel_to_plate(ball_px, plate_left_px, plate_right_px, camera="cf",
                   catch_depth_ft=1.5, vaa_deg=FALLBACK_VAA,
                   ref_px=None, ref_in=None, origin_px=None):
    """Pure conversion, no I/O -- the one implementation of the math.

    plate_left_px / plate_right_px are the plate's two FRONT corners as
    they appear left/right in the IMAGE (not 1B/3B -- the camera arg
    handles which side is which). Returns a dict with plate_x/plate_z
    (ft, GBO convention) and the intermediate numbers."""
    bx, by = ball_px
    if ref_px is not None:
        (x1, y1), (x2, y2) = ref_px
        ft_per_px = (ref_in / 12.0) / math.hypot(x2 - x1, y2 - y1)
        cx, gy = origin_px
    else:
        (lx, ly), (rx, ry) = plate_left_px, plate_right_px
        ft_per_px = (PLATE_WIDTH_IN / 12.0) / math.hypot(rx - lx, ry - ly)
        cx, gy = (lx + rx) / 2.0, (ly + ry) / 2.0

    dx_ft = (bx - cx) * ft_per_px
    plate_x = -dx_ft if camera == "cf" else dx_ft
    z_catch = (gy - by) * ft_per_px  # image y grows downward
    drop = catch_depth_ft * math.tan(math.radians(abs(vaa_deg)))
    plate_z = z_catch + drop
    return {
        "plate_x": round(plate_x, 3),
        "plate_z": round(plate_z, 3),
        "z_at_catch": round(z_catch, 3),
        "catch_drop_correction_ft": round(drop, 3),
        "ft_per_px": ft_per_px,
        "origin_px": [round(cx, 1), round(gy, 1)],
    }


def uncertainty_in(ft_per_px, pick_px=6.0, catch_depth_ft=1.5):
    """Rough +/- band in inches: pixel-pick error on the ball and plate
    (pick_px, ~ half a ball-width at typical CF zoom) plus the model
    error of treating the mitt point as the plate crossing (~1 in per
    foot of catch depth for VAA uncertainty of a couple degrees)."""
    pick = pick_px * ft_per_px * 12 * math.sqrt(2)
    model = 0.6 * catch_depth_ft + 0.75  # VAA +/-2deg, orthographic approx
    return round(math.hypot(pick, model), 1)


def confidence_label(unc_in, ball_visible):
    if ball_visible == "no":
        return "Low (ball not visible -- read from mitt only)"
    if unc_in <= 2.5 and ball_visible == "yes":
        return "High"
    if unc_in <= 4.5:
        return "Medium"
    return "Low"


# ------------------------------------------------------------------ ffmpeg I/O

def probe(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,nb_frames:format=duration", "-of", "json", video],
        capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    s = d["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"width": int(s["width"]), "height": int(s["height"]),
            "fps": float(num) / float(den), "duration": float(d["format"]["duration"])}


def read_gray_frames(video, width=320, fps=None):
    """Downscaled grayscale frames as a numpy array (n, h, w)."""
    info = probe(video)
    h = int(round(info["height"] * width / info["width"] / 2) * 2)
    vf = f"scale={width}:{h},format=gray" + (f",fps={fps}" if fps else "")
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vf", vf,
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    arr = np.frombuffer(raw, np.uint8)
    return arr.reshape(-1, h, width), (fps or info["fps"])


def _font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ------------------------------------------------------------------ commands

def cmd_scan(a):
    os.makedirs(a.out, exist_ok=True)
    info = probe(a.video)
    frames, fps = read_gray_frames(a.video, width=320)
    diff = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
    # Smooth over ~0.1 s and report the top motion bursts -- the delivery
    # + catch is normally the biggest one in a single-pitch clip.
    k = max(1, int(fps * 0.1))
    sm = np.convolve(diff, np.ones(k) / k, mode="same")
    order = np.argsort(sm)[::-1]
    peaks = []
    for i in order:
        t = (i + 1) / fps
        if all(abs(t - p) > 0.5 for p in peaks):
            peaks.append(round(t, 2))
        if len(peaks) == 3:
            break
    # Contact sheet: 4 fps, labeled with timestamps.
    step = max(1, int(round(fps / 4)))
    n = min(24, len(frames) // step + 1)
    cols = 6
    rows = math.ceil(n / cols)
    tw = 480
    th = int(info["height"] * tw / info["width"])
    sheet = Image.new("RGB", (cols * tw, rows * th), BG_DARK)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.video, "-vf",
                          f"fps=4,scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    imgs = np.frombuffer(raw, np.uint8).reshape(-1, th, tw, 3)
    f = _font(20)
    for j, im in enumerate(imgs[:cols * rows]):
        tile = Image.fromarray(im)
        d = ImageDraw.Draw(tile)
        d.rectangle([0, 0, 90, 26], fill=BG_DARK)
        d.text((6, 3), f"{j / 4:.2f}s", fill=CREAM, font=f)
        sheet.paste(tile, ((j % cols) * tw, (j // cols) * th))
    path = os.path.join(a.out, "scan_sheet.jpg")
    sheet.save(path, quality=88)
    res = {**info, "motion_peaks_s": peaks, "contact_sheet": path}
    print(json.dumps(res, indent=2))


def cmd_frames(a):
    os.makedirs(a.out, exist_ok=True)
    info = probe(a.video)
    cx, cy, cw, ch = ([int(v) for v in a.crop.split(",")] if a.crop
                      else [0, 0, info["width"], info["height"]])
    fps = a.fps or info["fps"]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(a.start), "-i", a.video, "-t", str(a.end - a.start),
         "-vf", f"fps={fps},crop={cw}:{ch}:{cx}:{cy}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True).stdout
    imgs = np.frombuffer(raw, np.uint8).reshape(-1, ch, cw, 3)
    scale = a.zoom
    f = _font(max(12, int(11 * scale)))
    paths = []
    for j, im in enumerate(imgs):
        t = a.start + j / fps
        img = Image.fromarray(im).resize((int(cw * scale), int(ch * scale)), Image.LANCZOS)
        d = ImageDraw.Draw(img, "RGBA")
        g = a.grid
        # Grid lines labeled in FULL-FRAME pixel coordinates.
        for gx in range((cx // g + 1) * g, cx + cw, g):
            X = (gx - cx) * scale
            d.line([(X, 0), (X, img.height)], fill=(255, 253, 229, 70))
            d.text((X + 2, 2), str(gx), fill=CREAM, font=f)
        for gy in range((cy // g + 1) * g, cy + ch, g):
            Y = (gy - cy) * scale
            d.line([(0, Y), (img.width, Y)], fill=(255, 253, 229, 70))
            d.text((2, Y + 2), str(gy), fill=CREAM, font=f)
        d.rectangle([img.width - 110, img.height - 30, img.width, img.height], fill=(30, 30, 30, 220))
        d.text((img.width - 104, img.height - 26), f"{t:.3f}s", fill=CREAM, font=f)
        p = os.path.join(a.out, f"f_{t:07.3f}.png")
        img.save(p)
        paths.append(p)
    print(json.dumps({"frames": paths, "crop": [cx, cy, cw, ch], "fps": fps}, indent=2))


def _pt(s):
    return tuple(float(v) for v in s.split(",")) if s else None


def draw_zone_chart(res, path, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle, Polygon

    fig, ax = plt.subplots(figsize=(4.2, 5.2), dpi=150)
    fig.patch.set_facecolor(BG_DARK)
    ax.set_facecolor(BG_DARK)
    w, b, t = ZONE_HALF_WIDTH, ZONE_BOTTOM, ZONE_TOP
    ax.add_patch(Rectangle((-w, b), 2 * w, t - b, fill=False, ec=CREAM, lw=2))
    for i in (1, 2):
        ax.plot([-w + i * 2 * w / 3] * 2, [b, t], color=GRID, lw=1)
        ax.plot([-w, w], [b + i * (t - b) / 3] * 2, color=GRID, lw=1)
    ax.add_patch(Polygon([(-w, 0.0), (w, 0.0), (w, 0.08), (0, 0.16), (-w, 0.08)],
                         closed=True, fc=CREAM, ec=CREAM))
    unc = res["uncertainty_in"] / 12.0
    x, z = res["plate_x"], res["plate_z"]
    ax.add_patch(Circle((x, z), unc, fc=CRIMSON, alpha=0.18, ec=CRIMSON, lw=1, ls="--"))
    ax.add_patch(Circle((x, z), 0.121, fc=CRIMSON, ec=CREAM, lw=1.5))  # 2.9 in ball
    ax.set_xlim(2.0, -2.0)  # PITCHER'S view: 3B side (negative x) on the right
    ax.set_ylim(-0.1, 5.0)
    ax.set_aspect("equal")
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=CREAM, labelsize=7)
    ax.set_xlabel("plate_x (ft)   1B side  <-   ->  3B side", color=CREAM, fontsize=7)
    ax.set_ylabel("plate_z (ft)", color=CREAM, fontsize=7)
    ax.set_title(title, color=CREAM, fontsize=9)
    ax.text(0, 4.7, f"x {x:+.2f}  z {z:.2f}   Zone {res['zone']}  {res['attack_zone']}",
            color=CREAM, ha="center", fontsize=8)
    ax.text(0, 4.45, "Pitcher's view", color="#9A9A9A", ha="center", fontsize=7)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG_DARK)
    plt.close(fig)


def cmd_locate(a):
    os.makedirs(a.out, exist_ok=True)
    vaa = a.vaa if a.vaa is not None else DEFAULT_VAA.get((a.pitch_type or "").upper(), FALLBACK_VAA)
    ref = None
    if a.ref:
        p = [float(v) for v in a.ref.split(",")]
        ref = ((p[0], p[1]), (p[2], p[3]))
    r = pixel_to_plate(_pt(a.ball), _pt(a.plate_left), _pt(a.plate_right), camera=a.camera,
                       catch_depth_ft=a.catch_depth, vaa_deg=vaa,
                       ref_px=ref, ref_in=a.ref_in, origin_px=_pt(a.origin))
    unc = uncertainty_in(r["ft_per_px"], a.pick_px, a.catch_depth)
    res = {
        "plate_x": r["plate_x"], "plate_z": r["plate_z"],
        "zone": derive_old_zone(r["plate_x"], r["plate_z"]),
        "in_zone": bool(is_in_zone(r["plate_x"], r["plate_z"])),
        "attack_zone": classify_attack_zone(r["plate_x"], r["plate_z"]),
        "uncertainty_in": unc,
        "confidence": confidence_label(unc, a.ball_visible),
        "px_per_inch": round(1 / (r["ft_per_px"] * 12), 2),
        "z_at_catch": r["z_at_catch"],
        "catch_drop_correction_in": round(r["catch_drop_correction_ft"] * 12, 1),
        "vaa_deg_used": vaa, "camera": a.camera, "zone_math": _ZONE_SOURCE,
        "source": "video",
    }
    stem = a.name or os.path.splitext(os.path.basename(a.frame))[0]
    if a.frame:
        img = Image.open(a.frame).convert("RGB")
        # Frames from `frames` are cropped/zoomed; map full-frame px back.
        ox, oy, zm = [float(v) for v in a.frame_offset.split(",")]

        def P(pt):
            return ((pt[0] - ox) * zm, (pt[1] - oy) * zm)
        d = ImageDraw.Draw(img, "RGBA")
        k = zm / (r["ft_per_px"] * 12)  # display px per inch
        cxp, gyp = P(r["origin_px"])
        sgn = -1 if a.camera == "cf" else 1
        # Draw the generic zone (plate_x -> image x mirrors for CF).
        zl = cxp - ZONE_HALF_WIDTH * 12 * k
        zr = cxp + ZONE_HALF_WIDTH * 12 * k
        zt = gyp - ZONE_TOP * 12 * k
        zb = gyp - ZONE_BOTTOM * 12 * k
        d.rectangle([zl, zt, zr, zb], outline=(255, 253, 229, 200), width=2)
        for pt in (a.plate_left, a.plate_right):
            if pt:
                X, Y = P(_pt(pt))
                d.ellipse([X - 5, Y - 5, X + 5, Y + 5], outline=CREAM, width=2)
        bx, by = P(_pt(a.ball))
        d.ellipse([bx - 9, by - 9, bx + 9, by + 9], outline=CRIMSON, width=3)
        # Corrected plate-crossing point (drop added back).
        X = cxp + sgn * r["plate_x"] * 12 * k
        Y = gyp - r["plate_z"] * 12 * k
        d.line([(X - 8, Y), (X + 8, Y)], fill=CRIMSON, width=2)
        d.line([(X, Y - 8), (X, Y + 8)], fill=CRIMSON, width=2)
        ap = os.path.join(a.out, f"{stem}_annotated.png")
        img.save(ap)
        res["annotated_frame"] = ap
    zp = os.path.join(a.out, f"{stem}_zone.png")
    draw_zone_chart(res, zp, a.title or "Pitch location (video)")
    res["zone_chart"] = zp
    print(json.dumps(res, indent=2))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan")
    s.add_argument("video")
    s.add_argument("--out", default="video_locator_out")
    s.set_defaults(fn=cmd_scan)

    f = sub.add_parser("frames")
    f.add_argument("video")
    f.add_argument("--start", type=float, required=True)
    f.add_argument("--end", type=float, required=True)
    f.add_argument("--crop", help="x,y,w,h in full-frame pixels")
    f.add_argument("--fps", type=float, help="default: native fps")
    f.add_argument("--zoom", type=float, default=1.0)
    f.add_argument("--grid", type=int, default=50, help="grid spacing, full-frame px")
    f.add_argument("--out", default="video_locator_out")
    f.set_defaults(fn=cmd_frames)

    l = sub.add_parser("locate")
    l.add_argument("--frame", help="frame image to annotate (optional)")
    l.add_argument("--frame-offset", default="0,0,1", help="crop_x,crop_y,zoom of --frame")
    l.add_argument("--plate-left", help="x,y of the plate front corner on the IMAGE left")
    l.add_argument("--plate-right", help="x,y of the plate front corner on the IMAGE right")
    l.add_argument("--ref", help="x1,y1,x2,y2 of a known length at plate depth (instead of plate corners)")
    l.add_argument("--ref-in", type=float, help="real length of --ref in inches")
    l.add_argument("--origin", help="x,y of plate center on the ground (with --ref)")
    l.add_argument("--ball", required=True, help="x,y of ball center (full-frame px)")
    l.add_argument("--ball-visible", choices=["yes", "partial", "no"], default="yes")
    l.add_argument("--camera", choices=["cf", "home"], default="cf")
    l.add_argument("--pitch-type", help="FB/2S/SI/CT/SL/SW/CH/SP/CB/KC -- sets default VAA")
    l.add_argument("--vaa", type=float, help="vertical approach angle magnitude, deg")
    l.add_argument("--catch-depth", type=float, default=1.5, help="ft behind the plate's front edge")
    l.add_argument("--pick-px", type=float, default=6.0, help="pixel-pick uncertainty")
    l.add_argument("--name")
    l.add_argument("--title")
    l.add_argument("--out", default="video_locator_out")
    l.set_defaults(fn=cmd_locate)

    a = ap.parse_args()
    if a.cmd == "locate" and not a.ref and not (a.plate_left and a.plate_right):
        ap.error("locate needs --plate-left/--plate-right, or --ref/--ref-in/--origin")
    a.fn(a)


if __name__ == "__main__":
    main()
