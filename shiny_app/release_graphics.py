"""
release_graphics.py -- GBO release-point card + PSU teammate similarity comps.

Lives in shiny_app/ (Nov 2026, Ryker: Past The Eye Test-style release
card + PSU-vs-PSU comps; shown NEXT TO the existing behind-the-pitcher
graphic, not replacing it). Data plumbing: analytics/release_comps.py.
Render with ui.HTML(...):

    from release_graphics import (
        ReleaseProfile, release_card_svg, comparison_html, find_comps,
    )
    ui.HTML(release_card_svg(profile))
    ui.HTML(comparison_html(profile_a, profile_b, pool_df))

Everything is pure Python string building (no new dependencies). The SVGs use
width=100% so they scale inside Shiny's display:contents wrappers (theme.py's
rescue selectors already cover `> svg`).

View: CATCHER'S VIEW (pitcher facing you). An RHP's arm is on the 3B side,
which is the LEFT of the drawing. The card carries an explicit "pitcher facing
you" cue (brim + face toward the viewer, glove-side shoulder, home-plate glyph)
so nobody reads it as the pitcher's POV.

Inputs come from Rapsodo averages (fastball-only recommended):
    release height (ft), release side (ft, absolute, toward arm side),
    extension (ft), player height (in). Rapsodo has no arm angle, so it's
    estimated (labelled "est." on the card) unless you pass a measured one.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from html import escape
from typing import Optional

import pandas as pd

# ---------------------------------------------------------------- theme
CRIMSON = "#BF1E2D"
CREAM = "#FFFDE5"
INK = "#1C1D22"        # card background
PANEL = "#26282F"      # table stripes / plot frame
MUTED = "#9A9CA6"      # axis + secondary text
BODY = "#8E97A8"       # figure fill
BODY_DARK = "#6B7384"  # far-side limbs
DIRT = "#4A3527"
B_COLOR = "#E9C46A"    # comparison player B (warm gold, reads next to crimson)
FONT = "Inter, 'Helvetica Neue', Arial, sans-serif"

# Shoulder height as a fraction of standing height, used only when arm angle
# has to be estimated. Re-fit with calibrate_shoulder_ratio() once you have
# a few PSU pitchers with a known (video-measured) arm angle.
SHOULDER_RATIO = 0.70


@dataclass
class ReleaseProfile:
    name: str
    throws: str                      # "R" or "L"
    release_height_ft: float
    release_side_ft: float           # absolute distance toward arm side
    extension_ft: float
    height_in: Optional[float] = None
    arm_angle_deg: Optional[float] = None   # measured; else estimated
    subtitle: str = ""               # e.g. "Fall 2026 · games only"
    extra: dict = field(default_factory=dict)  # FB VAA / HAA etc. for tables

    @property
    def arm_angle(self) -> float:
        if self.arm_angle_deg is not None:
            return float(self.arm_angle_deg)
        return estimate_arm_angle(self.release_height_ft, self.release_side_ft,
                                  self.height_in or 74)

    @property
    def arm_angle_is_estimate(self) -> bool:
        return self.arm_angle_deg is None or bool(self.extra.get("arm_angle_estimated"))


# ---------------------------------------------------------------- arm angle
def estimate_arm_angle(release_height_ft: float, release_side_ft: float,
                       height_in: float, shoulder_ratio: float = SHOULDER_RATIO) -> float:
    """Angle (deg) of the shoulder->ball line above horizontal, catcher's view.

    Shoulder is assumed at shoulder_ratio x height, centred over the rubber.
    It's an estimate (+/- ~8 deg vs. Savant's measured angle on MLB arms); the
    card labels it "est." so coaches don't over-read single degrees.
    """
    shoulder_z = shoulder_ratio * height_in / 12.0
    return math.degrees(math.atan2(release_height_ft - shoulder_z,
                                   abs(release_side_ft)))


def calibrate_shoulder_ratio(rows: pd.DataFrame) -> float:
    """Fit SHOULDER_RATIO from rows with a known arm angle.

    rows needs: release_height_ft, release_side_ft, height_in, arm_angle_deg.
    Grid search, no scipy needed.
    """
    best, best_err = SHOULDER_RATIO, float("inf")
    for r in [x / 1000 for x in range(600, 800)]:
        est = rows.apply(lambda s: estimate_arm_angle(
            s.release_height_ft, s.release_side_ft, s.height_in, r), axis=1)
        err = ((est - rows.arm_angle_deg) ** 2).mean()
        if err < best_err:
            best, best_err = r, err
    return best


# ---------------------------------------------------------------- figure
def _label(x, y, text, color, size=12, anchor="middle") -> str:
    """Outlined label as ONE <text> element: paint-order draws the dark
    halo first, then the fill on top. If a renderer ignores paint-order
    the text still shows (it just loses the halo) -- the old two-copy
    trick could leave only the dark copy visible in some renderers."""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="700" '
            f'text-anchor="{anchor}" fill="{color}" stroke="{INK}" stroke-width="4" '
            f'stroke-linejoin="round" paint-order="stroke fill" '
            f'style="paint-order:stroke fill">{text}</text>')


def _figure_points(p: ReleaseProfile) -> dict:
    """Body landmarks in 'arm coordinates': a = ft toward arm side, z = ft up.

    Built outward from the release point: ball -> throwing shoulder (fixed arm
    length along the arm angle) -> trunk (tilted with the slot) -> hips -> an
    athletic, spread-out stride (front leg braced, back knee kicked out).
    """
    H = (p.height_in or 74) / 12.0
    ang = math.radians(p.arm_angle)
    R = (abs(p.release_side_ft), p.release_height_ft)

    arm_len = 0.38 * H
    S = (R[0] - arm_len * math.cos(ang), R[1] - arm_len * math.sin(ang))

    # Trunk tilt: over-the-top leans the top of the trunk toward the glove
    # side; sidearm/submarine bend toward the arm side.
    lean = math.radians(max(-50.0, min(32.0, 0.6 * (p.arm_angle - 15))))
    r = (math.cos(lean), math.sin(lean))        # across shoulders, toward arm side
    u = (-math.sin(lean), math.cos(lean))       # up the spine
    half_w = 0.10 * H                            # half shoulder width
    mid = (S[0] - r[0] * half_w, S[1] - r[1] * half_w)
    G = (mid[0] - r[0] * half_w, mid[1] - r[1] * half_w)

    torso = 0.29 * H
    hip = (mid[0] - u[0] * torso, mid[1] - u[1] * torso)
    hip = (max(-1.2, min(1.2, hip[0])), max(0.30 * H, min(0.50 * H, hip[1])))
    hip_half = 0.075 * H
    hip_arm = (hip[0] + r[0] * hip_half, hip[1] + r[1] * hip_half)
    hip_glv = (hip[0] - r[0] * hip_half, hip[1] - r[1] * hip_half)

    head_r = 0.06 * H
    head = (mid[0] + u[0] * (0.035 * H + head_r), mid[1] + u[1] * (0.035 * H + head_r))

    # Feet well apart: stride foot planted toward the glove side and slightly
    # in front of the mound line (closer to the catcher); drive foot back on
    # the rubber toward the arm side with the knee flexed out.
    back_foot = (0.50, 0.10)                       # arm-side end of the rubber
    back_knee = (max(hip_arm[0], back_foot[0]) + 0.40, hip_arm[1] * 0.48)
    front_foot = (min(hip_glv[0] - 0.20, back_foot[0] - 1.35), -0.12)
    front_knee = ((hip_glv[0] + front_foot[0]) / 2 - 0.10, hip_glv[1] * 0.5)

    glove = (mid[0] - u[0] * 0.55 - r[0] * 0.15, mid[1] - u[1] * 0.55 - r[1] * 0.15)
    glove_elbow = (G[0] - r[0] * 0.25 - u[0] * 0.75, G[1] - r[1] * 0.25 - u[1] * 0.75)

    return dict(H=H, R=R, S=S, G=G, mid=mid, hip=hip, hip_arm=hip_arm,
                hip_glv=hip_glv, head=head, head_r=head_r, u=u, r=r,
                front_foot=front_foot, front_knee=front_knee,
                back_foot=back_foot, back_knee=back_knee,
                glove=glove, glove_elbow=glove_elbow)


def release_card_svg(p: ReleaseProfile, color: str = CRIMSON,
                     show_header: bool = True, title_suffix: str = "Release point") -> str:
    W, Hpx = 400, 530 if show_header else 470
    top = 60 if show_header else 0
    scale = 36.0                    # px per ft
    ground = top + 335
    cx = W / 2
    arm_dir = -1 if p.throws.upper() == "R" else 1   # RHP arm on screen-left

    def X(a: float) -> float:
        return cx + arm_dir * a * scale

    def Y(z: float) -> float:
        return ground - z * scale

    f = _figure_points(p)
    R, S, G, hip, head, hr = f["R"], f["S"], f["G"], f["hip"], f["head"], f["head_r"]

    out: list[str] = []
    a = out.append
    a(f'<svg viewBox="0 0 {W} {Hpx}" width="100%" xmlns="http://www.w3.org/2000/svg" '
      f'role="img" aria-label="{escape(p.name)} release point, catcher\'s view" '
      f'style="font-family:{FONT};display:block;max-width:520px">')
    a(f'<rect width="{W}" height="{Hpx}" rx="14" fill="{INK}"/>')

    if show_header:
        a(f'<rect width="{W}" height="54" rx="14" fill="{color}"/>'
          f'<rect y="40" width="{W}" height="14" fill="{color}"/>')
        a(f'<text x="18" y="25" fill="{CREAM}" font-size="17" font-weight="700">{escape(p.name)}</text>')
        sub = p.subtitle or title_suffix
        a(f'<text x="18" y="43" fill="{CREAM}" fill-opacity=".8" font-size="11">{escape(sub)}</text>')
        a(f'<text x="{W-18}" y="25" fill="{CREAM}" font-size="13" font-weight="700" '
          f'text-anchor="end">{"RHP" if arm_dir == -1 else "LHP"}</text>')

    # POV cue: home-plate glyph + plain sentence
    py = top + 22
    a(f'<g transform="translate(18,{py - 9})"><path d="M0 0h12v6l-6 6-6-6z" fill="{CREAM}"/></g>')
    a(f'<text x="36" y="{py}" fill="{CREAM}" font-size="11.5" font-weight="600">'
      f'Catcher\'s view: pitcher is facing you</text>')
    left_lbl, right_lbl = "3B side", "1B side"
    a(f'<text x="18" y="{py + 16}" fill="{MUTED}" font-size="10">&#8592; {left_lbl}</text>')
    a(f'<text x="{W-18}" y="{py + 16}" fill="{MUTED}" font-size="10" text-anchor="end">{right_lbl} &#8594;</text>')

    # height axis
    for ft in (2, 4, 6):
        a(f'<line x1="44" x2="{W-14}" y1="{Y(ft)}" y2="{Y(ft)}" stroke="{PANEL}" stroke-width="1"/>')
        a(f'<text x="38" y="{Y(ft)+3.5}" fill="{MUTED}" font-size="10" text-anchor="end">{ft} ft</text>')

    # mound + rubber
    a(f'<path d="M14 {ground+4} Q{cx} {ground-10} {W-14} {ground+4} L{W-14} {ground+34} L14 {ground+34}Z" fill="{DIRT}"/>')
    a(f'<rect x="{cx-30}" y="{ground-4}" width="60" height="5" rx="1" fill="{CREAM}"/>')
    a(f'<text x="{cx}" y="{ground+20}" fill="{CREAM}" fill-opacity=".55" font-size="9.5" text-anchor="middle">rubber</text>')

    def pts(*ps):
        return " ".join(f"{X(x):.1f},{Y(z):.1f}" for x, z in ps)

    LEG_BACK, LEG_FRONT, PANTS, JERSEY = "#5E6676", "#A7AFBD", "#B9C0CC", "#8E97A8"

    # back (drive) leg: behind the body, knee flexed out toward the arm side
    a(f'<polyline points="{pts(f["hip_arm"], f["back_knee"], f["back_foot"])}" fill="none" '
      f'stroke="{LEG_BACK}" stroke-width="15" stroke-linecap="round" stroke-linejoin="round"/>')
    bf = f["back_foot"]
    a(f'<ellipse cx="{X(bf[0]):.1f}" cy="{Y(bf[1]) + 3:.1f}" rx="12" ry="5" fill="{LEG_BACK}"/>')

    # front (stride) leg: braced, planted toward the glove side
    a(f'<polyline points="{pts(f["hip_glv"], f["front_knee"], f["front_foot"])}" fill="none" '
      f'stroke="{LEG_FRONT}" stroke-width="17" stroke-linecap="round" stroke-linejoin="round"/>')
    ff = f["front_foot"]
    a(f'<ellipse cx="{X(ff[0]):.1f}" cy="{Y(ff[1]) + 4:.1f}" rx="15" ry="6" fill="{LEG_FRONT}"/>')
    a(f'<ellipse cx="{X(ff[0]):.1f}" cy="{Y(ff[1]) + 10:.1f}" rx="18" ry="4" fill="#000" fill-opacity=".25"/>')

    # pants block over the hips
    rx_, ux_ = f["r"], f["u"]
    hw = 0.085 * f["H"]
    hp = f["hip"]
    pants = [(hp[0] + rx_[0] * hw + ux_[0] * 0.35, hp[1] + rx_[1] * hw + ux_[1] * 0.35),
             (hp[0] - rx_[0] * hw + ux_[0] * 0.35, hp[1] - rx_[1] * hw + ux_[1] * 0.35),
             (hp[0] - rx_[0] * hw - ux_[0] * 0.15, hp[1] - rx_[1] * hw - ux_[1] * 0.15),
             (hp[0] + rx_[0] * hw - ux_[0] * 0.15, hp[1] + rx_[1] * hw - ux_[1] * 0.15)]
    a(f'<polygon points="{pts(*pants)}" fill="{PANTS}" stroke="{PANTS}" stroke-width="8" stroke-linejoin="round"/>')

    # jersey: tilted trunk with rounded corners, placket + piping mark the front
    top_w = 0.115 * f["H"]
    jersey = [(f["mid"][0] + rx_[0] * top_w, f["mid"][1] + rx_[1] * top_w),
              (f["mid"][0] - rx_[0] * top_w, f["mid"][1] - rx_[1] * top_w),
              (hp[0] - rx_[0] * hw + ux_[0] * 0.25, hp[1] - rx_[1] * hw + ux_[1] * 0.25),
              (hp[0] + rx_[0] * hw + ux_[0] * 0.25, hp[1] + rx_[1] * hw + ux_[1] * 0.25)]
    a(f'<polygon points="{pts(*jersey)}" fill="{JERSEY}" stroke="{JERSEY}" stroke-width="10" stroke-linejoin="round"/>')
    a(f'<polygon points="{pts(*jersey)}" fill="none" stroke="{color}" stroke-opacity=".55" stroke-width="1.5" '
      f'stroke-linejoin="round" transform="translate(0,0)"/>')
    plk_top = (f["mid"][0] - rx_[0] * 0.05, f["mid"][1] - rx_[1] * 0.05)
    plk_bot = (hp[0] + ux_[0] * 0.3 - rx_[0] * 0.05, hp[1] + ux_[1] * 0.3 - rx_[1] * 0.05)
    a(f'<line x1="{X(plk_top[0]):.1f}" y1="{Y(plk_top[1]):.1f}" x2="{X(plk_bot[0]):.1f}" y2="{Y(plk_bot[1]):.1f}" '
      f'stroke="{color}" stroke-width="2.5"/>')
    a(f'<line x1="{X(pants[0][0]):.1f}" y1="{Y(pants[0][1]):.1f}" x2="{X(pants[1][0]):.1f}" y2="{Y(pants[1][1]):.1f}" '
      f'stroke="{INK}" stroke-width="4" stroke-linecap="round"/>')  # belt

    # glove arm: elbow out, glove tucked at the chest
    a(f'<polyline points="{pts(G, f["glove_elbow"], f["glove"])}" fill="none" stroke="{JERSEY}" '
      f'stroke-width="11" stroke-linecap="round" stroke-linejoin="round"/>')
    a(f'<circle cx="{X(f["glove"][0]):.1f}" cy="{Y(f["glove"][1]):.1f}" r="11" fill="#7A4A26" '
      f'stroke="{INK}" stroke-width="1.5"/>')

    # head facing the viewer: cap with the brim toward us
    hx, hy, rpx = X(head[0]), Y(head[1]), hr * scale
    nb = (f["mid"][0], f["mid"][1])
    a(f'<line x1="{X(nb[0]):.1f}" y1="{Y(nb[1]):.1f}" x2="{hx:.1f}" y2="{hy:.1f}" stroke="#C9CED8" stroke-width="9"/>')
    a(f'<circle cx="{hx:.1f}" cy="{hy:.1f}" r="{rpx:.1f}" fill="#C9CED8"/>')
    a(f'<path d="M{hx-rpx:.1f} {hy-2:.1f} A{rpx:.1f} {rpx:.1f} 0 0 1 {hx+rpx:.1f} {hy-2:.1f}Z" fill="{color}"/>')
    a(f'<ellipse cx="{hx:.1f}" cy="{hy:.1f}" rx="{rpx*1.15:.1f}" ry="{rpx*0.28:.1f}" fill="{color}" '
      f'stroke="{INK}" stroke-opacity=".6" stroke-width="1"/>')
    a(f'<rect x="{hx-1.2:.1f}" y="{hy-rpx-2:.1f}" width="2.4" height="3" fill="{CREAM}"/>')

    # throwing arm + release point
    a(f'<line x1="{X(S[0])}" y1="{Y(S[1])}" x2="{X(R[0])}" y2="{Y(R[1])}" '
      f'stroke="{color}" stroke-width="10" stroke-linecap="round"/>')
    a(f'<circle cx="{X(S[0])}" cy="{Y(S[1])}" r="7" fill="{color}"/>')
    a(f'<circle cx="{X(R[0])}" cy="{Y(R[1])}" r="8" fill="{color}" stroke="{CREAM}" stroke-width="2"/>')

    # guides: height (horizontal), drop to ground, side measure
    a(f'<line x1="44" x2="{X(R[0])}" y1="{Y(R[1])}" y2="{Y(R[1])}" stroke="{color}" '
      f'stroke-dasharray="4 4" stroke-width="1.3"/>')
    a(f'<line x1="{X(R[0])}" x2="{X(R[0])}" y1="{Y(R[1])}" y2="{ground}" stroke="{color}" '
      f'stroke-dasharray="4 4" stroke-width="1.3"/>')
    side_y = ground - 14
    a(f'<line x1="{X(0)}" x2="{X(R[0])}" y1="{side_y}" y2="{side_y}" stroke="{color}" stroke-width="1.6"/>')
    for xx in (X(0), X(R[0])):
        a(f'<line x1="{xx}" x2="{xx}" y1="{side_y-5}" y2="{side_y+5}" stroke="{color}" stroke-width="1.6"/>')
    a(_label((X(0) + X(R[0])) / 2, side_y - 7, f"{abs(p.release_side_ft):.1f} ft side", color))
    lbl_y = max(top + 52, Y(R[1]) - 12)
    a(_label(X(R[0]), lbl_y, f"{p.release_height_ft:.1f} ft high", color, 13))

    # arm-angle arc at shoulder (from horizontal toward arm side to the arm)
    ang = math.radians(p.arm_angle)
    r_ft = 0.55
    sx, sy = X(S[0]), Y(S[1])
    x0, y0 = X(S[0] + r_ft), sy
    x1, y1 = X(S[0] + r_ft * math.cos(ang)), Y(S[1] + r_ft * math.sin(ang))
    v0, v1 = (x0 - sx, y0 - sy), (x1 - sx, y1 - sy)
    sweep = 1 if v0[0] * v1[1] - v0[1] * v1[0] > 0 else 0
    a(f'<line x1="{sx}" x2="{X(S[0] + r_ft + 0.25)}" y1="{sy}" y2="{sy}" stroke="{CREAM}" '
      f'stroke-opacity=".6" stroke-dasharray="2 3"/>')
    a(f'<path d="M{x0} {y0} A{r_ft*scale} {r_ft*scale} 0 0 {sweep} {x1} {y1}" fill="none" '
      f'stroke="{CREAM}" stroke-width="1.5"/>')
    est = " est." if p.arm_angle_is_estimate else ""
    # Label sits just below the shoulder, growing AWAY from the body
    # (toward the arm side) so it never lands on the jersey.
    lx = X(S[0] + 0.45)
    ly = sy + 24 if p.arm_angle >= 0 else sy - 10
    anchor = "end" if arm_dir == -1 else "start"
    a(_label(lx, ly, f"{p.arm_angle:.0f}&#176; arm{est}", CREAM, 12, anchor))

    # extension bar (side view, rubber -> release)
    ey = ground + 84
    x_l, x_r = 30, W - 30
    ext_px = lambda ft: x_l + (x_r - x_l) * ft / 10.0
    a(f'<text x="{W/2}" y="{ground+48}" fill="{MUTED}" font-size="10.5" text-anchor="middle">'
      f'Extension: rubber to release, side view</text>')
    a(f'<line x1="{x_l}" x2="{x_r}" y1="{ey}" y2="{ey}" stroke="{PANEL}" stroke-width="4" stroke-linecap="round"/>')
    a(f'<line x1="{x_l}" x2="{ext_px(p.extension_ft)}" y1="{ey}" y2="{ey}" stroke="{color}" '
      f'stroke-width="4" stroke-linecap="round"/>')
    a(f'<rect x="{x_l-3}" y="{ey-9}" width="6" height="12" fill="{CREAM}"/>')
    for ft in (2, 4, 6, 8):
        a(f'<text x="{ext_px(ft)}" y="{ey+18}" fill="{MUTED}" font-size="9.5" text-anchor="middle">{ft} ft</text>')
    ext_x = ext_px(max(0.0, min(10.0, p.extension_ft)))
    a(f'<circle cx="{ext_x:.1f}" cy="{ey}" r="7" fill="{color}" stroke="{CREAM}" stroke-width="2"/>')
    # Value goes beside the dot on the bar's own line (never up into the
    # caption); flips to the left near the bar's end.
    if ext_x > x_r - 50:
        a(_label(ext_x - 13, ey + 4.5, f"{p.extension_ft:.1f} ft", color, 12, "end"))
    else:
        a(_label(ext_x + 13, ey + 4.5, f"{p.extension_ft:.1f} ft", color, 12, "start"))

    a('</svg>')
    return "".join(out)


def both_views_html(behind_svg: str, profile: Optional[ReleaseProfile],
                    empty_note: str = "Needs 5+ fastball readings with a release point.",
                    caption_color: Optional[str] = None) -> str:
    """The existing behind-the-pitcher graphic (every pitch type) and the
    catcher's-view card (fastball) side by side; stacks on a phone.
    Nov 2026, Ryker: 'i want to have both views'."""
    cap = (f'style="text-align:center;font-weight:700;font-size:13px;margin:0 0 6px;'
           f'font-family:{FONT}' + (f';color:{caption_color}' if caption_color else '') + '"')
    right = (release_card_svg(profile) if profile is not None else
             f'<p class="text-muted small" style="text-align:center;margin-top:40px">{escape(empty_note)}</p>')
    return ('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));'
            'gap:16px;align-items:start;width:100%">'
            f'<div><p {cap}>Behind the pitcher &#8212; every pitch type</p>{behind_svg}</div>'
            f'<div><p {cap}>Catcher\'s view &#8212; fastball</p>'
            f'<div style="max-width:420px;margin:0 auto">{right}</div></div></div>')


# ---------------------------------------------------------------- similarity
# Feature columns expected in the pool DataFrame (one row per pitcher-season,
# e.g. "Fall 2026"). Missing columns/NaNs are skipped, so you can start with
# Release only and add the rest as GBO's game data fills in.
# Matched to what GBO actually stores (Nov 2026): release + arsenal come
# from game-linked Rapsodo pitches; Whiff/Command/Contact come from
# profile_queries.pitching_staff_leaderboard_rows (the same numbers the
# Pitching Leaderboard shows).
CATEGORY_FEATURES: dict[str, list[str]] = {
    "Release": ["arm_angle", "release_side_ft", "release_height_ft", "extension_ft"],
    "Arsenal": ["usage_fb", "usage_si", "usage_fc", "usage_sl", "usage_cu", "usage_ch",
                "fb_velo", "fb_ivb", "fb_hb"],
    "Whiff": ["stuff_plus", "k_pct", "csw_pct"],
    "Command": ["location_plus", "command_plus", "bb_pct", "first_pitch_strike_pct"],
    "Contact": ["oba", "rv_per_100"],
}
FEATURE_LABELS = {
    "arm_angle": "Arm angle", "release_side_ft": "Release side",
    "release_height_ft": "Release height", "extension_ft": "Extension",
    "usage_fb": "Four-seam %", "usage_si": "Two-seam/sinker %", "usage_fc": "Cutter %",
    "usage_sl": "Slider/sweeper %", "usage_cu": "Curveball %", "usage_ch": "Changeup/splitter %",
    "fb_velo": "FB velo", "fb_ivb": "FB IVB", "fb_hb": "FB HB (arm side)",
    "stuff_plus": "Stuff+", "k_pct": "K %", "csw_pct": "CSW %",
    "location_plus": "Location+", "command_plus": "Command+", "bb_pct": "BB %",
    "first_pitch_strike_pct": "First-pitch strike %",
    "oba": "Opp. AVG", "rv_per_100": "Run value / 100",
}

# GBO pitch-type name -> arsenal family (pitch_type_config.py catalog).
PITCH_FAMILY = {
    "Fastball": "fb", "4-Seam Fastball": "fb", "2-Seam Fastball": "si", "Cutter": "fc",
    "Slider": "sl", "Curveball": "cu", "Changeup": "ch", "Splitter": "ch",
}
FASTBALL_LABELS = ("4-Seam Fastball", "Fastball", "2-Seam Fastball")
MIN_CARD_READINGS = 5     # fewest fastball readings before a card is drawn


def _type_name(p) -> Optional[str]:
    try:
        pt = getattr(p, "pitch_type", None)
    except Exception:          # detached ORM row with an unloaded relationship
        return None
    return pt.type_name if pt is not None else None


def card_pitches(raps: list) -> tuple[list, str]:
    """The pitches a release card is drawn from: his most-thrown fastball
    type, or (no fastball) his most-thrown pitch. Returns (pitches, label)."""
    groups: dict[str, list] = {}
    for p in raps:
        if p.release_height is None or p.release_side is None:
            continue
        groups.setdefault(_type_name(p) or "Unclassified", []).append(p)
    if not groups:
        return [], ""
    fbs = [k for k in groups if k in FASTBALL_LABELS]
    pool = fbs or list(groups)
    label = max(pool, key=lambda k: len(groups[k]))
    return groups[label], label


def _avg(vals):
    vals = [float(v) for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def profile_from_rapsodo(player, raps: list, subtitle: str = "",
                         min_readings: int = MIN_CARD_READINGS) -> Optional[ReleaseProfile]:
    """ReleaseProfile from a pitcher's Rapsodo pitches (caller filters:
    game-linked, date range). None if too few readings to draw.

    Arm angle uses GBO's own estimate (analytics.bullpen_metrics.
    average_estimated_arm_angle -- the same number Physical Profile's
    table shows), so the card and the table never disagree."""
    pitches, label = card_pitches(raps)
    if len(pitches) < min_readings:
        return None
    height_in = float(player.height_in) if getattr(player, "height_in", None) is not None else None
    exts = [p.release_extension for p in pitches
            if p.release_extension is not None and float(p.release_extension) > 0]
    angle = None
    if height_in is not None:
        try:
            from analytics.bullpen_metrics import average_estimated_arm_angle
            angle, _n = average_estimated_arm_angle(pitches, player)
        except Exception:
            angle = None
    side = _avg(abs(float(p.release_side)) for p in pitches)
    prof = ReleaseProfile(
        name=f"{player.first_name} {player.last_name}",
        throws=(player.throws or "R"),
        release_height_ft=_avg(p.release_height for p in pitches),
        release_side_ft=side,
        extension_ft=_avg(exts) or 0.0,
        height_in=height_in,
        subtitle=subtitle or f"{label} avg -- {len(pitches)} game pitches",
    )
    if angle is not None:
        prof.arm_angle_deg = float(angle)
        prof.extra["arm_angle_estimated"] = True
    return prof


def zscore_pool(pool: pd.DataFrame, group_col: Optional[str] = "season") -> pd.DataFrame:
    """Scale every feature within its own season (so Fall vs Spring compare fairly)."""
    feats = [c for cols in CATEGORY_FEATURES.values() for c in cols if c in pool.columns]
    z = pool.copy()
    z[feats] = z[feats].astype(float)
    groups = z.groupby(group_col) if group_col and group_col in z.columns else [(None, z)]
    for _, g in groups:
        for c in feats:
            # Missing stays missing (skipped by similarity()), never 0 =
            # "staff average" -- otherwise two pitchers with no data
            # would look identical on that stat.
            sd = g[c].std(ddof=0)
            if not sd or pd.isna(sd):
                z.loc[g.index, c] = g[c].where(g[c].isna(), 0.0)
            else:
                z.loc[g.index, c] = (g[c] - g[c].mean()) / sd
    return z


def similarity(za: pd.Series, zb: pd.Series,
               categories: Optional[list[str]] = None) -> dict:
    """Per-category and overall similarity (0-100, 100 = identical).

    sim = 100 * exp(-0.5 * mean(dz^2)): one SD apart on every feature ~ 61%.
    """
    cats = categories or list(CATEGORY_FEATURES)
    out = {"categories": {}, "dz": {}}
    for cat in cats:
        dzs = []
        for c in CATEGORY_FEATURES[cat]:
            if c in za and c in zb and pd.notna(za[c]) and pd.notna(zb[c]):
                d = float(za[c] - zb[c])
                out["dz"][c] = d
                dzs.append(d * d)
        if dzs:
            out["categories"][cat] = 100 * math.exp(-0.5 * sum(dzs) / len(dzs))
    vals = list(out["categories"].values())
    out["overall"] = sum(vals) / len(vals) if vals else None
    return out


def find_comps(target_id, pool: pd.DataFrame, id_col: str = "player_id",
               categories: Optional[list[str]] = None, n: int = 5,
               group_col: Optional[str] = "season") -> pd.DataFrame:
    """Closest PSU teammates (other pitchers, any season in the pool)."""
    z = zscore_pool(pool, group_col)
    target = z[z[id_col] == target_id]
    if target.empty:
        return pd.DataFrame()
    t = target.iloc[-1]
    rows = []
    for idx, r in z[z[id_col] != target_id].iterrows():
        s = similarity(t, r, categories)
        if s["overall"] is not None:
            rows.append({"pool_index": idx, id_col: r[id_col], "similarity": s["overall"],
                         **{f"sim_{k.lower()}": v for k, v in s["categories"].items()}})
    return pd.DataFrame(rows).sort_values("similarity", ascending=False).head(n)


# ---------------------------------------------------------------- comparison
def _fmt(c: str, v) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "&#8212;"
    if c == "arm_angle":
        return f"{v:.0f}&#176;"
    if c.endswith("_ft"):
        return f"{v:.2f} ft"
    if c in ("stuff_plus", "location_plus", "command_plus"):
        return f"{v:.0f}"
    if c == "oba":
        return f"{v:.3f}".lstrip("0") if v < 1 else f"{v:.3f}"
    if c == "rv_per_100":
        return f"{v:+.2f}"
    return f"{v:.1f}"


def comparison_html(a: ReleaseProfile, b: ReleaseProfile, row_a: pd.Series,
                    row_b: pd.Series, sim: dict) -> str:
    """Side-by-side cards + similarity badge + stat table with dz per row.

    row_a/row_b: raw pool rows; sim: output of similarity() on their z rows.
    """
    def bar(cat, val):
        return (f'<div style="flex:1;min-width:92px"><div style="display:flex;justify-content:space-between;'
                f'font-size:11px;color:{MUTED}"><span>{cat}</span><b style="color:{CREAM}">{val:.0f}%</b></div>'
                f'<div style="height:5px;background:{PANEL};border-radius:3px;margin-top:4px">'
                f'<div style="height:5px;width:{val:.0f}%;background:{CRIMSON};border-radius:3px"></div></div></div>')

    overall = sim.get("overall") or 0
    h = [f'<div style="background:{INK};color:{CREAM};font-family:{FONT};border-radius:14px;'
         f'padding:16px;max-width:1080px">']
    h.append(f'<div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">'
             f'<div><div style="font-weight:700;font-size:17px">{escape(a.name)}</div>'
             f'<div style="color:{MUTED};font-size:12px">{escape(a.subtitle)}</div></div>'
             f'<div style="text-align:center"><div style="font-size:11px;color:{MUTED}">Similarity</div>'
             f'<div style="background:{CRIMSON};border-radius:10px;padding:4px 14px;font-size:24px;'
             f'font-weight:800">{overall:.0f}%</div></div>'
             f'<div style="text-align:right"><div style="font-weight:700;font-size:17px;color:{B_COLOR}">'
             f'{escape(b.name)}</div><div style="color:{MUTED};font-size:12px">{escape(b.subtitle)}</div></div></div>')
    h.append('<div style="display:flex;gap:14px;flex-wrap:wrap;margin:14px 0">' +
             "".join(bar(c, v) for c, v in sim["categories"].items()) + '</div>')
    def card(prof, col):
        if prof.extra.get("no_card"):
            return (f'<div style="border:1px dashed {PANEL};border-radius:14px;padding:40px 16px;'
                    f'text-align:center;color:{MUTED};font-size:13px">No release card yet: needs 5+ '
                    f'Rapsodo fastball readings from games in this range.</div>')
        return release_card_svg(prof, col, show_header=False)
    h.append('<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">'
             f'<div>{card(a, CRIMSON)}</div>'
             f'<div>{card(b, B_COLOR)}</div></div>')

    h.append('<table style="width:100%;border-collapse:collapse;margin-top:14px;font-size:13px">')
    for cat, cols in CATEGORY_FEATURES.items():
        shown = [c for c in cols if c in sim["dz"]]
        if not shown:
            continue
        h.append(f'<tr><td colspan="3" style="padding:12px 0 4px;text-align:center;color:{MUTED};'
                 f'font-size:12px;font-weight:600">{cat}</td></tr>')
        for i, c in enumerate(shown):
            dz = sim["dz"][c]
            hot = abs(dz) >= 1.0
            bg = PANEL if i % 2 else "transparent"
            h.append(f'<tr style="background:{bg}"><td style="text-align:right;padding:5px 10px;'
                     f'font-weight:700;color:{CRIMSON}">{_fmt(c, row_a.get(c))}</td>'
                     f'<td style="text-align:center;padding:5px 6px;color:{MUTED}">{FEATURE_LABELS.get(c, c)}'
                     f'<div style="font-size:10.5px;color:{CRIMSON if hot else MUTED};font-weight:{700 if hot else 400}">'
                     f'&#916;z {dz:+.1f}</div></td>'
                     f'<td style="padding:5px 10px;font-weight:700;color:{B_COLOR}">{_fmt(c, row_b.get(c))}</td></tr>')
    h.append('</table>')
    h.append(f'<div style="color:{MUTED};font-size:11px;margin-top:10px">PSU pitchers only, game pitches. '
             f'Each stat is scaled across our staff in this date range; 100% = identical. '
             f'&#916;z of 1.0 or more is highlighted.</div></div>')
    return "".join(h)
