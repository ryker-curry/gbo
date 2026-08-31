"""
GBO -- Release Point pitcher graphic (v6, pro silhouette).

A broadcast-style RELEASE-POINT graphic: a clean, monochrome silhouette
of a pitcher at release (front view -- the catcher's perspective, same
view the release side/height data is measured from), with the pitch
markers plotted at their true data positions.

Instead of a procedurally-bent cartoon body, the figure is one of
three hand-tuned release poses -- OVERHEAD, THREE-QUARTER, SIDEARM --
traced from real release-frame photography conventions (slot angle
measured off vertical at the shoulder: overhead 0-45, three-quarter
45-65, sidearm 65+). The pitcher's own data picks the pose:

  - slot angle comes from the primary release point vs the shoulder,
  - the whole silhouette scales with the pitcher's height,
  - only the throwing arm is fit to the data (two-segment IK), so the
    hand lands exactly on the primary release point,
  - lefties mirror.

The silhouette is a single filled shape (subtle top-light gradient +
soft ground shadow), so all color on the page belongs to the pitch
markers -- like a professional analytics graphic, not a mascot.

Contract (matches the design brief):
  - 320 x 380 viewBox, portrait, mound at bottom.
  - Feet-based mapping: release side -4..+4 ft (center = 0),
    release height 0..8 ft above the ground line.
  - Grouped, id'd layers: mound, shadow, figure, rays, throwing-arm,
    markers, legend.
  - 1..6+ pitch types, each marker in that type's app-wide color;
    the most-thrown type gets the arm + the baseball.
  - Crowd handling: dots never move off their true positions -- the
    primary gets a halo ring, near-overlapping dots get a short fan
    tick, and the legend names every type with usage %.
  - Internal ids are namespaced per figure, so several figures can sit
    on one page without gradient/clip collisions.

Usage:
    from visualizations.pitcher_graphic import pitcher_release_svg
    ui.HTML(pitcher_release_svg(releases, throws="R", height_in=73))

    releases = [{"label": "Slider", "color": "#B08618",
                 "side_ft": 2.1, "height_ft": 5.7, "count": 34}, ...]
"""

import math

# --- palette ---------------------------------------------------------------
SIL_TOP = "#9AA1AE"       # silhouette, lit top
SIL_BOT = "#454A55"       # silhouette, shaded bottom
DIRT = "#54402F"
DIRT_LIGHT = "#6E523C"
DIRT_DARK = "#33261B"
GRASS = "#1A2B1A"
GRASS_LIGHT = "#243D24"
RUBBER = "#D8D4C6"
OUTLINE = "#17100B"
INK_MUTED = "#B8B2A4"
CRIMSON = "#CE1126"

W, H = 320, 380
GROUND_Y = 330.0
X_CENTER = 160.0
PX_PER_FT_X = 30.0
PX_PER_FT_Y = 36.0


def _x(side_ft):
    return X_CENTER + side_ft * PX_PER_FT_X


def _y(height_ft):
    return GROUND_Y - height_ft * PX_PER_FT_Y


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _ik_joint(sx, sy, ex, ey, l1, l2, prefer="low"):
    """Elbow position for a two-segment arm from (sx,sy) to (ex,ey);
    `prefer` picks the natural bend; out-of-reach stretches straight."""
    dx, dy = ex - sx, ey - sy
    D = math.hypot(dx, dy) or 1.0
    if D >= (l1 + l2) * 0.999:
        t = l1 / (l1 + l2)
        return sx + dx * t, sy + dy * t
    a = (l1 * l1 - l2 * l2 + D * D) / (2 * D)
    h = math.sqrt(max(0.0, l1 * l1 - a * a))
    mx, my = sx + dx * a / D, sy + dy * a / D
    nx, ny = -dy / D, dx / D
    c1 = (mx + nx * h, my + ny * h)
    c2 = (mx - nx * h, my - ny * h)
    if prefer == "low":
        return c1 if c1[1] >= c2[1] else c2
    if prefer == "high":
        return c1 if c1[1] < c2[1] else c2
    if prefer == "left":
        return c1 if c1[0] <= c2[0] else c2
    return c1 if c1[0] > c2[0] else c2


def _cr(pts):
    """Catmull-Rom cubics smoothly through an open point list."""
    if len(pts) < 2:
        return ""
    if len(pts) == 2:
        return f"L {pts[1][0]:.1f} {pts[1][1]:.1f} "
    d = ""
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d += (f"C {c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} "
              f"{p2[0]:.1f} {p2[1]:.1f} ")
    return d


def _blob(pts):
    """Closed smooth path through a cyclic point list."""
    n = len(pts)
    d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f} "
    for i in range(n):
        p0, p1 = pts[(i - 1) % n], pts[i]
        p2, p3 = pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
        d += (f"C {c1[0]:.1f} {c1[1]:.1f} {c2[0]:.1f} {c2[1]:.1f} "
              f"{p2[0]:.1f} {p2[1]:.1f} ")
    return d + "Z"


def _limb_path(points, widths):
    """Tapered limb outline (round caps) as a path `d` (one subpath)."""
    left, right = [], []
    n = len(points)
    for i, (x, y) in enumerate(points):
        if i == 0:
            dx, dy = points[1][0] - x, points[1][1] - y
        elif i == n - 1:
            dx, dy = x - points[i - 1][0], y - points[i - 1][1]
        else:
            dx = points[i + 1][0] - points[i - 1][0]
            dy = points[i + 1][1] - points[i - 1][1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        w = widths[i] / 2.0
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    d = f"M {left[0][0]:.1f} {left[0][1]:.1f} " + _cr(left)
    d += (f"A {widths[-1]/2:.1f} {widths[-1]/2:.1f} 0 1 1 "
          f"{right[-1][0]:.1f} {right[-1][1]:.1f} ")
    d += _cr(right[::-1])
    d += (f"A {widths[0]/2:.1f} {widths[0]/2:.1f} 0 1 1 "
          f"{left[0][0]:.1f} {left[0][1]:.1f} Z")
    return d


def _circle_path(cx, cy, r):
    return (f"M {cx - r:.1f} {cy:.1f} "
            f"a {r:.1f} {r:.1f} 0 1 1 {2*r:.1f} 0 "
            f"a {r:.1f} {r:.1f} 0 1 1 {-2*r:.1f} 0 Z")


# ---------------------------------------------------------------------------
# Hand-tuned release poses (front view, throwing arm toward +x).
# Coordinates are fractions of the pitcher's height: x from body center
# toward the arm side, y up from the ground.
# ---------------------------------------------------------------------------
POSES = {
    "overhead": {
        "sh_c": (-0.045, 0.76), "sh_tilt": 0.34, "hip_c": (0.0, 0.468),
        "head_dx": -0.045,
        "plant": [(-0.05, 0.47), (-0.165, 0.27), (-0.27, 0.05)],
        "plant_toe": (-0.345, 0.012),
        "drive": [(0.05, 0.475), (0.145, 0.295), (0.095, 0.07)],
        "drive_toe": (0.062, 0.006),
        "gl_elbow": (-0.21, 0.60), "glove": (-0.165, 0.545),
        "glove_r": 0.05,
        "l1": 0.205, "l2": 0.23,
    },
    "three_quarter": {
        "sh_c": (-0.022, 0.75), "sh_tilt": 0.20, "hip_c": (0.0, 0.465),
        "head_dx": -0.025,
        "plant": [(-0.05, 0.465), (-0.16, 0.265), (-0.26, 0.045)],
        "plant_toe": (-0.335, 0.01),
        "drive": [(0.05, 0.47), (0.145, 0.28), (0.095, 0.065)],
        "drive_toe": (0.06, 0.005),
        "gl_elbow": (-0.19, 0.615), "glove": (-0.155, 0.555),
        "glove_r": 0.05,
        "l1": 0.205, "l2": 0.228,
    },
    "sidearm": {
        "sh_c": (0.0, 0.715), "sh_tilt": 0.04, "hip_c": (0.0, 0.44),
        "head_dx": 0.0,
        "plant": [(-0.055, 0.44), (-0.175, 0.245), (-0.295, 0.04)],
        "plant_toe": (-0.37, 0.008),
        "drive": [(0.055, 0.445), (0.15, 0.255), (0.10, 0.06)],
        "drive_toe": (0.065, 0.004),
        "gl_elbow": (-0.185, 0.60), "glove": (-0.15, 0.545),
        "glove_r": 0.048,
        "l1": 0.21, "l2": 0.23, "elbow": "high",
    },
}



# ---------------------------------------------------------------------------
# TRACED POSE -- extracted from a real release-frame photograph (GrabCut
# segmentation -> contour -> simplified outline). Units: origin at the
# front-foot ground contact, +x toward the arm side, y up, 1.0 = pose
# height. HAND is the ball/hand tip; BACK_TOE trails near the rubber.
# Used for overhead + three-quarter slots; sidearm still uses the
# constructed pose until a sidearm frame is traced.
# ---------------------------------------------------------------------------
TRACE_HAND = (0.1688, 1.2693)
TRACE_BACK_TOE = (0.2145, 0.2642)
TRACE_PTS = [(0.1688, 1.2693), (0.1495, 1.2669), (0.1397, 1.2563), (0.1424, 1.1929), (0.1251, 1.1598), (0.1247, 1.1323), (0.1125, 1.0634), (0.0771, 0.9697), (0.0503, 0.9504), (0.0282, 0.9264), (0.0062, 0.9138), (-0.0214, 0.9055), (-0.0572, 0.8823), (-0.0847, 0.8799), (-0.0926, 0.8898), (-0.0946, 0.9177), (-0.1265, 0.9287), (-0.1332, 0.9642), (-0.1462, 0.9854), (-0.1647, 0.9972), (-0.1895, 1.0), (-0.2328, 0.9878), (-0.2454, 0.9697), (-0.2497, 0.9425), (-0.2706, 0.9201), (-0.2662, 0.913), (-0.2501, 0.9106), (-0.2403, 0.9035), (-0.2344, 0.8732), (-0.2005, 0.8098), (-0.206, 0.7906), (-0.2466, 0.7299), (-0.2686, 0.661), (-0.2686, 0.6472), (-0.2509, 0.5894), (-0.2497, 0.5453), (-0.2442, 0.5382), (-0.2194, 0.5276), (-0.195, 0.537), (-0.1536, 0.5276), (-0.119, 0.4894), (-0.0997, 0.4543), (-0.0977, 0.4213), (-0.0792, 0.3634), (-0.0875, 0.3), (-0.0761, 0.2118), (-0.0627, 0.187), (-0.0662, 0.1402), (-0.0615, 0.1181), (-0.0481, 0.0988), (-0.0387, 0.0575), (-0.0422, 0.0189), (-0.0324, 0.0067), (-0.0186, 0.0), (0.0172, 0.0004), (0.0338, 0.011), (0.0338, 0.0602), (0.0412, 0.0961), (0.0314, 0.1236), (0.0349, 0.139), (0.0558, 0.1528), (0.0739, 0.1563), (0.0889, 0.174), (0.1318, 0.1783), (0.1452, 0.1996), (0.1684, 0.2059), (0.1975, 0.2339), (0.2145, 0.2642), (0.2145, 0.289), (0.1991, 0.3606), (0.196, 0.413), (0.1767, 0.526), (0.1586, 0.5811), (0.1515, 0.6417), (0.1338, 0.6665), (0.1113, 0.7327), (0.0834, 0.7961), (0.0834, 0.8402), (0.0905, 0.8898), (0.105, 0.9189), (0.1251, 0.9394), (0.1334, 0.9724), (0.1527, 1.0), (0.1605, 1.0386), (0.1656, 1.113), (0.1849, 1.1461), (0.1881, 1.1709), (0.1771, 1.2094), (0.1877, 1.248), (0.1818, 1.2614)]


def pitcher_release_svg(releases, throws="R", height_in=73,
                        show_legend=True, jersey_number=None):
    if not releases:
        return (f'<svg viewBox="0 0 {W} {H}" '
                f'style="width:100%;height:auto;display:block;max-width:340px;margin:0 auto;" '
                f'xmlns="http://www.w3.org/2000/svg"></svg>')
    releases = sorted(releases, key=lambda r: -(r.get("count") or 0))
    primary = releases[0]
    # BACK VIEW (viewed from behind the pitcher, looking toward home
    # plate -- Ryker's call, Aug 31 2026): a RIGHT-handed pitcher's
    # throwing arm appears on the viewer's RIGHT (+x); a lefty's on the
    # LEFT (-x). The traced photo is a LHP, so lefties render natively
    # and righties mirror. side_ft is back-view too (+ = pitcher's own
    # right/throwing side), which matches Rapsodo's native raw
    # release_side convention directly -- no negation needed when
    # building `releases` (see rapsodo_conventions.py).
    sign = 1 if (throws or "R").upper() == "R" else -1

    uid = "pg%05d" % (abs(hash((throws, int(height_in or 73),
                                int(primary["side_ft"] * 10),
                                int(primary["height_ft"] * 10),
                                len(releases)))) % 100000)

    hf = max(5.5, min(6.9, (height_in or 73) / 12.0))   # height, ft
    hp = hf * PX_PER_FT_Y                                # height, px
    cx = X_CENTER
    ex, ey = _x(primary["side_ft"]), _y(primary["height_ft"])

    # --- pick the pose from the arm-slot angle (degrees off vertical) -------
    sh_guess_y = GROUND_Y - 0.77 * hp
    slot_deg = math.degrees(math.atan2(abs(ex - cx),
                                       max(6.0, sh_guess_y - ey)))
    if ey > sh_guess_y:          # release below the shoulder line
        slot_deg = 90.0 + math.degrees(
            math.atan2(ey - sh_guess_y, abs(ex - cx)))
    if slot_deg < 45:
        pose_name = "overhead"
    elif slot_deg < 65:
        pose_name = "three_quarter"
    else:
        pose_name = "sidearm"
    P = POSES[pose_name]

    def pt(p):
        return (cx + sign * p[0] * hp, GROUND_Y - p[1] * hp)

    # --- skeleton anchors ---------------------------------------------------
    sh_c = pt(P["sh_c"])
    hip_c = pt(P["hip_c"])
    tilt = P["sh_tilt"]
    sh_hw = hp * 0.132                      # shoulder half-width
    hip_hw = hp * 0.082
    sh_a = (sh_c[0] + sign * sh_hw * math.cos(tilt),
            sh_c[1] - sh_hw * math.sin(tilt))
    sh_g = (sh_c[0] - sign * sh_hw * math.cos(tilt) * 0.97,
            sh_c[1] + sh_hw * math.sin(tilt) * 0.8)
    head_r = hp * 0.062
    head = (sh_c[0] + sign * P["head_dx"] * hp,
            sh_c[1] - hp * 0.055 - head_r * 0.95)
    arm_sh = (sh_a[0] - sign * 2, sh_a[1] + 2)
    l1, l2 = P["l1"] * hp, P["l2"] * hp

    # --- silhouette parts (separate paths, one shared gradient) -------------
    # every limb is capsule + joint disc + capsule, so no path can
    # self-intersect and no seams or holes can appear
    sil = []

    def disc(c, r):
        sil.append(_circle_path(c[0], c[1], r))

    def cap2(a, b, w1, w2):
        sil.append(_limb_path([a, b], [w1, w2]))
        disc(a, w1 / 2)          # explicit end caps: the arc caps can
        disc(b, w2 / 2)          # flip concave on some orientations

    # shoulder bar with deltoid caps
    cap2(sh_g, sh_a, hp*0.095, hp*0.095)
    # trunk: shoulders taper to waist, then the pelvis
    waist_y = (sh_c[1] + hip_c[1]) / 2 + hp * 0.02
    sil.append(_blob([
        (sh_g[0] - sign * hp*0.008, sh_g[1] + hp*0.008),
        (sh_a[0] + sign * hp*0.008, sh_a[1] + hp*0.008),
        (hip_c[0] + sign * hp*0.098, waist_y),
        (hip_c[0] + sign * hip_hw, hip_c[1] + hp*0.02),
        (hip_c[0] - sign * hip_hw, hip_c[1] + hp*0.02),
        (hip_c[0] - sign * hp*0.096, waist_y),
    ]))
    cap2((hip_c[0] - hip_hw, hip_c[1]), (hip_c[0] + hip_hw, hip_c[1]),
         hp*0.095, hp*0.095)
    # legs: thigh capsule + knee disc + shin capsule + foot
    for leg_key, toe_key, wmul in (("plant", "plant_toe", 1.0),
                                   ("drive", "drive_toe", 0.95)):
        hip, knee, ank = [pt(p) for p in P[leg_key]]
        toe = pt(P[toe_key])
        cap2(hip, knee, hp*0.112*wmul, hp*0.072*wmul)
        disc(knee, hp*0.037*wmul)
        cap2(knee, ank, hp*0.070*wmul, hp*0.040*wmul)
        cap2(ank, toe, hp*0.046*wmul, hp*0.036*wmul)
    # neck + head + cap
    cap2((sh_c[0], sh_c[1] - hp*0.01), (head[0], head[1] + head_r*0.55),
         hp*0.05, hp*0.042)
    disc(head, head_r)
    sil.append(_blob([(head[0] - head_r*0.92, head[1] - head_r*0.18),
                      (head[0], head[1] - head_r*1.16),
                      (head[0] + head_r*0.92, head[1] - head_r*0.18),
                      (head[0], head[1] - head_r*0.6)]))
    brim_dir = -sign
    sil.append(_blob([(head[0] + brim_dir*head_r*0.78,
                       head[1] - head_r*0.5),
                      (head[0] + brim_dir*head_r*1.72,
                       head[1] - head_r*0.14),
                      (head[0] + brim_dir*head_r*1.62,
                       head[1] + head_r*0.08),
                      (head[0] + brim_dir*head_r*0.72,
                       head[1] - head_r*0.1)]))
    # glove arm: upper + elbow + forearm + glove
    ge, gv = pt(P["gl_elbow"]), pt(P["glove"])
    gsh = (sh_g[0] + sign*2, sh_g[1] + 2)
    cap2(gsh, ge, hp*0.072, hp*0.048)
    disc(ge, hp*0.026)
    cap2(ge, gv, hp*0.046, hp*0.034)
    disc(gv, P["glove_r"] * hp)
    # throwing arm: two-segment IK so the hand lands ON the release point
    dxr, dyr = ex - arm_sh[0], ey - arm_sh[1]
    Dr = math.hypot(dxr, dyr) or 1.0
    wrist = (ex - dxr / Dr * hp * 0.028, ey - dyr / Dr * hp * 0.028)
    # elbow bend: below the chord for high slots; for sidearm with the
    # release at/below the shoulder, the whip look (elbow above) is right
    prefer = ("high" if pose_name == "sidearm" and ey >= arm_sh[1]
              else "low")
    eb = _ik_joint(arm_sh[0], arm_sh[1], wrist[0], wrist[1], l1, l2,
                   prefer=prefer)
    cap2(arm_sh, eb, hp*0.086, hp*0.058)
    disc(eb, hp*0.030)
    cap2(eb, wrist, hp*0.056, hp*0.028)
    disc(wrist, hp*0.026)
    grad_top = head[1] - head_r * 1.3
    connector = None

    # --- traced real-photo figure (all slots) -------------------------------
    # One real pitcher for every arm slot: for slots lower than the
    # photo's (~17 deg off vertical), the throwing arm is cut at the
    # shoulder and rotated down to the pitcher's actual slot; a deltoid
    # disc seals the joint. The whole figure is then fitted (bounded
    # scale + rotation + shift) so the hand lands on the release point.
    if True:
        ARM_RUN = list(range(78, 90)) + list(range(0, 10))
        PIVOT = (0.055, 0.90)
        NATIVE_SLOT = 17.2
        delta = _clamp(slot_deg - NATIVE_SLOT, 0.0, 125.0)
        if delta < 10.0:
            delta = 0.0
        pts_mod = list(TRACE_PTS)
        hand_m = TRACE_HAND
        if delta:
            dr = math.radians(delta)
            cd, sd = math.cos(dr), math.sin(dr)

            def lower(p):
                lx, ly = p[0] - PIVOT[0], p[1] - PIVOT[1]
                return (PIVOT[0] + lx * cd + ly * sd,
                        PIVOT[1] - lx * sd + ly * cd)

            for i in ARM_RUN:
                pts_mod[i] = lower(pts_mod[i])
            hand_m = lower(TRACE_HAND)
        s0 = 0.82 * hp
        htx, hty = hand_m
        btx, bty = TRACE_BACK_TOE
        target = (ex, ey - 6.0)
        best = None
        for th10 in range(-24, 25, 3):
            th_ = th10 / 100.0
            c_, s_r = math.cos(th_), math.sin(th_)
            for sm in (0.90, 0.95, 1.0, 1.05, 1.10):
                sc = s0 * sm

                def rot(px, py):
                    dx0, dy0 = sign * px * sc, -py * sc
                    return (dx0 * c_ - dy0 * s_r, dx0 * s_r + dy0 * c_)

                hdx, hdy = rot(htx, hty)
                ax = target[0] - hdx
                ax0 = X_CENTER - rot(btx, bty)[0]
                axc = _clamp(ax, ax0 - 0.30 * hp, ax0 + 0.30 * hp)
                res = math.hypot(axc + hdx - target[0],
                                 GROUND_Y + hdy - target[1])
                pen = res + abs(axc - ax0) * 0.12 + abs(th_) * 14 + \
                    abs(1 - sm) * 26
                if best is None or pen < best[0]:
                    best = (pen, th_, sc, axc, res)
        _, th_, sc, axc, res = best
        c_, s_r = math.cos(th_), math.sin(th_)

        def T(px, py):
            dx0, dy0 = sign * px * sc, -py * sc
            return (axc + dx0 * c_ - dy0 * s_r,
                    GROUND_Y + dx0 * s_r + dy0 * c_)

        spts = [T(px, py) for px, py in pts_mod]
        sil = [_blob(spts)]
        if delta:
            pv = T(*PIVOT)
            sil.append(_circle_path(pv[0], pv[1], 0.058 * sc))
        grad_top = min(p[1] for p in spts)
        arm_sh = T(*PIVOT)                    # rays start at the shoulder
        hand_pt = T(htx, hty)
        if res > 12:
            connector = hand_pt
    d = []
    d.append(f'<svg viewBox="0 0 {W} {H}" '
             f'style="width:100%;height:auto;display:block;max-width:340px;margin:0 auto;" '
             f'xmlns="http://www.w3.org/2000/svg" role="img" '
             f'aria-label="Release point illustration">')
    d.append(
        '<defs>'
        f'<filter id="{uid}ds" x="-30%" y="-30%" width="160%" height="160%">'
        f'<feDropShadow dx="{sign*3}" dy="4" stdDeviation="3" '
        f'flood-color="#000" flood-opacity=".4"/></filter>'
        f'<linearGradient id="{uid}Sil" gradientUnits="userSpaceOnUse" '
        f'x1="0" y1="{grad_top:.0f}" x2="0" y2="{GROUND_Y:.0f}">'
        f'<stop offset="0" stop-color="{SIL_TOP}"/>'
        f'<stop offset="1" stop-color="{SIL_BOT}"/></linearGradient>'
        f'<radialGradient id="{uid}Mound" cx=".5" cy=".15" r="1.1">'
        f'<stop offset="0" stop-color="{DIRT_LIGHT}"/>'
        f'<stop offset=".6" stop-color="{DIRT}"/>'
        f'<stop offset="1" stop-color="{DIRT_DARK}"/></radialGradient>'
        f'<radialGradient id="{uid}Sh" cx=".5" cy=".5" r=".5">'
        f'<stop offset="0" stop-color="#000" stop-opacity=".55"/>'
        f'<stop offset="1" stop-color="#000" stop-opacity="0"/>'
        f'</radialGradient>'
        f'<radialGradient id="{uid}Glow" cx=".5" cy=".5" r=".5">'
        f'<stop offset="0" stop-color="#8B93A4" stop-opacity=".14"/>'
        f'<stop offset="1" stop-color="#8B93A4" stop-opacity="0"/>'
        f'</radialGradient>'
        f'<radialGradient id="{uid}Ball" cx=".35" cy=".3" r="1">'
        f'<stop offset="0" stop-color="#FFFDF6"/>'
        f'<stop offset=".75" stop-color="#EDEAE0"/>'
        f'<stop offset="1" stop-color="#C9C4B4"/></radialGradient>'
        '</defs>')

    # --- mound --------------------------------------------------------------
    d.append('<g id="mound">')
    d.append(f'<ellipse cx="{X_CENTER}" cy="{GROUND_Y+22}" rx="152" ry="35" '
             f'fill="{GRASS}"/>')
    d.append(f'<ellipse cx="{X_CENTER}" cy="{GROUND_Y+22}" rx="152" ry="35" '
             f'fill="none" stroke="{GRASS_LIGHT}" stroke-width="1.2" '
             f'opacity=".5"/>')
    d.append(f'<path d="M {X_CENTER-140:.0f} {GROUND_Y+31:.0f} '
             f'Q {X_CENTER-92:.0f} {GROUND_Y-5:.0f} {X_CENTER:.0f} {GROUND_Y-7:.0f} '
             f'Q {X_CENTER+92:.0f} {GROUND_Y-5:.0f} {X_CENTER+140:.0f} {GROUND_Y+31:.0f} '
             f'Q {X_CENTER:.0f} {GROUND_Y+48:.0f} {X_CENTER-140:.0f} {GROUND_Y+31:.0f} Z" '
             f'fill="url(#{uid}Mound)"/>')
    d.append(f'<rect x="{X_CENTER-22}" y="{GROUND_Y-1}" width="44" height="5.5" '
             f'rx="1.4" fill="{RUBBER}" opacity=".92"/>')
    d.append('</g>')

    # --- glow + contact shadow ----------------------------------------------
    d.append(f'<ellipse cx="{cx:.0f}" cy="{GROUND_Y - hp*0.42:.0f}" '
             f'rx="{hp*0.52:.0f}" ry="{hp*0.5:.0f}" fill="url(#{uid}Glow)"/>')
    d.append(f'<ellipse id="shadow" cx="{cx - sign*hp*0.04:.0f}" '
             f'cy="{GROUND_Y+8:.0f}" rx="{hp*0.34:.0f}" ry="9" '
             f'fill="url(#{uid}Sh)"/>')

    # --- the silhouette (separate parts, one shared gradient) ---------------
    fig_sw = 3.0 if (pose_name != "sidearm") else 0.8
    d.append(f'<g id="figure" filter="url(#{uid}ds)">')
    for part in sil:
        d.append(f'<path d="{part}" fill="url(#{uid}Sil)" '
                 f'stroke="url(#{uid}Sil)" stroke-width="{fig_sw}" '
                 f'stroke-linejoin="round"/>')
    d.append('</g>')

    # --- rays to secondary release points -----------------------------------
    d.append('<g id="rays">')
    if connector:
        d.append(f'<path d="M {connector[0]:.1f} {connector[1]:.1f} '
                 f'L {ex:.1f} {ey:.1f}" stroke="{INK_MUTED}" '
                 f'stroke-width="1.4" stroke-dasharray="2 4" opacity=".6"/>')
    for r in releases[1:]:
        rx, ry = _x(r["side_ft"]), _y(r["height_ft"])
        d.append(f'<path d="M {arm_sh[0]:.1f} {arm_sh[1]:.1f} '
                 f'Q {(arm_sh[0] + rx)/2:.1f} {(arm_sh[1] + ry)/2 - 6:.1f} '
                 f'{rx:.1f} {ry:.1f}" stroke="{r["color"]}" '
                 f'stroke-width="2" fill="none" opacity=".45" '
                 f'stroke-linecap="round" stroke-dasharray="1 5"/>')
    d.append('</g>')

    # --- markers ------------------------------------------------------------
    d.append('<g id="markers">')
    pts = [(r, _x(r["side_ft"]), _y(r["height_ft"])) for r in releases]
    for r, rx, ry in pts[1:][::-1]:
        crowded = any(math.hypot(rx - qx, ry - qy) < 9
                      for q, qx, qy in pts if q is not r)
        if crowded:
            ang = math.atan2(ry - arm_sh[1], rx - arm_sh[0])
            d.append(f'<path d="M {rx:.1f} {ry:.1f} '
                     f'l {math.cos(ang)*10:.1f} {math.sin(ang)*10:.1f}" '
                     f'stroke="{r["color"]}" stroke-width="1.6" '
                     f'opacity=".85"/>')
        d.append(f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="5.6" '
                 f'fill="{r["color"]}" stroke="{OUTLINE}" '
                 f'stroke-width="1.6"/>')
    d.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="13" '
             f'fill="{primary["color"]}" opacity=".22"/>')
    d.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="9.4" fill="none" '
             f'stroke="{primary["color"]}" stroke-width="2.2"/>')
    d.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="7" '
             f'fill="url(#{uid}Ball)" stroke="{OUTLINE}" '
             f'stroke-width="1.3"/>')
    d.append(f'<path d="M {ex-3.6:.1f} {ey-4.6:.1f} q 3 4.6 0 9.2 '
             f'M {ex+3.6:.1f} {ey-4.6:.1f} q -3 4.6 0 9.2" '
             f'stroke="{CRIMSON}" stroke-width="1.1" fill="none" '
             f'opacity=".9"/>')
    d.append('</g>')

    # --- legend --------------------------------------------------------------
    if show_legend:
        d.append('<g id="legend" font-family="IBM Plex Sans, system-ui, '
                 'sans-serif" font-size="10">')
        total = sum((r.get("count") or 0) for r in releases) or None
        x0, y0 = 14, H - 8
        for r in releases[:6]:
            pct = (f' {round(100*(r.get("count") or 0)/total)}%'
                   if total else "")
            label = f'{r["label"]}{pct}'
            d.append(f'<circle cx="{x0:.0f}" cy="{y0 - 3:.0f}" r="4" '
                     f'fill="{r["color"]}"/>')
            d.append(f'<text x="{x0 + 8:.0f}" y="{y0:.0f}" '
                     f'fill="{INK_MUTED}">{label}</text>')
            x0 += 14 + len(label) * 5.4 + 10
            if x0 > W - 60:
                break
        d.append('</g>')

    d.append('</svg>')
    return "".join(d)
