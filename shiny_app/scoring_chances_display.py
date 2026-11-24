"""
GBO -- Runs per Scoring Chance display pieces (Nov 2026). The math lives
in analytics/scoring_chances.py; this file is the shared UI used by the
Scoring Chances page and the Pitcher / Hitter Profiles, so the three
never show different numbers for the same filters.
"""

from html import escape

from shiny import ui

import ui_helpers
from analytics import scoring_chances as sc


def _f(v, d=2):
    return "—" if v is None else f"{v:.{d}f}"


def _p(v):
    return "—" if v is None else f"{v:.0f}%"


def _signed(v, d=2):
    return "—" if v is None else f"{v:+.{d}f}"


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
def team_section(team):
    off, st = team["offense"], team["staff"]
    rows = [
        {"": "Offense (higher is better)", "Half-innings": off["half_innings"], "Chances": off["chances"],
         "Chance %": _p(off["chance_pct"]), "Runs": off["runs"], "R/Chance": _f(off["r_per_chance"]),
         "Chances with 0 runs": _p(off["zero_pct"]), "Chances with 2+ runs": _p(off["multi_pct"])},
        {"": "Pitching staff (lower is better)", "Half-innings": st["half_innings"], "Chances": st["chances"],
         "Chance %": _p(st["chance_pct"]), "Runs": st["runs"], "R/Chance": _f(st["r_per_chance"]),
         "Chances with 0 runs": _p(st["zero_pct"]), "Chances with 2+ runs": _p(st["multi_pct"])},
    ]
    return [
        ui_helpers.render_kpi_cards([
            {"label": "Offense R/Chance", "value": _f(off["r_per_chance"]),
             "delta": f"{off['runs']} runs in {off['chances']} chances"},
            {"label": "Staff R/Chance allowed", "value": _f(st["r_per_chance"]),
             "delta": f"{st['runs']} runs in {st['chances']} chances"},
            {"label": "Offense chance %", "value": _p(off["chance_pct"]), "delta": "innings we got a man to 2nd/3rd"},
            {"label": "Staff chance % allowed", "value": _p(st["chance_pct"]), "delta": "innings they got a man to 2nd/3rd"},
        ]),
        ui_helpers.render_dict_table(rows),
        ui.p("A scoring chance is a half-inning where a runner reached 2nd or 3rd, or a run scored. In intrasquads "
             "everyone is ours, so both halves count for the offense and for the staff. Not adjusted for opponent.",
             class_="text-muted small"),
    ]


# ---------------------------------------------------------------------------
# PEAR-style scatter (inline SVG, same .gbo-progress-svg classes as the
# other small charts)
# ---------------------------------------------------------------------------
def scatter_svg(points, x_label, y_label, ref_x, ref_y, quadrants, x_better_low=False, y_better_low=False,
                x_fmt="{:.2f}", y_fmt="{:.2f}", x_bounds=None, y_bounds=None):
    """points: [{"label", "x", "y", "title"}]. Axes are flipped where lower
    is better so up/right always means better (PEAR's convention).
    quadrants: (top_left, top_right, bottom_left, bottom_right) labels."""
    if not points:
        return ""
    W, H, L, R, T, B = 720, 460, 58, 18, 26, 46
    xs = [p["x"] for p in points] + ([ref_x] if ref_x is not None else [])
    ys = [p["y"] for p in points] + ([ref_y] if ref_y is not None else [])

    def rng(vals, bounds):
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.12 or (abs(hi) * 0.2 or 1.0)
        lo, hi = lo - pad, hi + pad
        if bounds:   # e.g. a percentage axis never runs past 0-100
            lo = max(lo, bounds[0]) if bounds[0] is not None else lo
            hi = min(hi, bounds[1]) if bounds[1] is not None else hi
        return lo, hi

    x0, x1 = rng(xs, x_bounds)
    y0, y1 = rng(ys, y_bounds)

    def X(v):
        f = (v - x0) / (x1 - x0)
        return L + (W - L - R) * ((1 - f) if x_better_low else f)

    def Y(v):
        f = (v - y0) / (y1 - y0)
        return T + (H - T - B) * (f if y_better_low else (1 - f))

    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="{escape(y_label)} vs {escape(x_label)}">']
    for i in range(5):
        xv = x0 + (x1 - x0) * i / 4
        yv = y0 + (y1 - y0) * i / 4
        out.append(f'<line x1="{X(xv):.1f}" x2="{X(xv):.1f}" y1="{T}" y2="{H - B}" class="grid"/>'
                   f'<text x="{X(xv):.1f}" y="{H - B + 16}" text-anchor="middle" class="axis">{x_fmt.format(xv)}</text>')
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end" class="axis">{y_fmt.format(yv)}</text>')
    if ref_x is not None:
        out.append(f'<line x1="{X(ref_x):.1f}" x2="{X(ref_x):.1f}" y1="{T}" y2="{H - B}" class="avg"/>')
    if ref_y is not None:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(ref_y):.1f}" y2="{Y(ref_y):.1f}" class="avg"/>')
    tl, tr, bl, br = quadrants
    out.append(f'<text x="{L + 8}" y="{T + 14}" class="avg-lbl">{escape(tl)}</text>'
               f'<text x="{W - R - 8}" y="{T + 14}" text-anchor="end" class="avg-lbl">{escape(tr)}</text>'
               f'<text x="{L + 8}" y="{H - B - 8}" class="avg-lbl">{escape(bl)}</text>'
               f'<text x="{W - R - 8}" y="{H - B - 8}" text-anchor="end" class="avg-lbl">{escape(br)}</text>')
    for p in points:
        cx, cy = X(p["x"]), Y(p["y"])
        out.append(f'<g class="pt"><title>{escape(p["title"])}</title>'
                   f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="5" class="dot"/>'
                   f'<text x="{cx + 8:.1f}" y="{cy + 4:.1f}" class="axis">{escape(p["label"])}</text></g>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 8}" text-anchor="middle" class="axis">{escape(x_label)}</text>')
    out.append(f'<text transform="translate(14,{(T + H - B) / 2:.0f}) rotate(-90)" text-anchor="middle" class="axis">'
               f'{escape(y_label)}</text>')
    out.append("</svg>")
    return "".join(out)


def pitcher_scatter(pitchers, names, staff):
    pts = []
    for pid, r in pitchers.items():
        if r["small_sample"] or r["r_per_chance"] is None:
            continue
        full = names.get(pid, f"#{pid}")
        pts.append({"label": full.split()[-1], "x": r["chance_pct"], "y": r["r_per_chance"],
                    "title": f"{full}: {r['runs']} runs in {r['chances']} chances ({_f(r['r_per_chance'])}/chance), "
                             f"in trouble {_p(r['chance_pct'])} of {r['innings']} innings"})
    return scatter_svg(
        pts, "Chance % allowed (flipped: right = in trouble less often)",
        "R/Chance allowed (flipped: up = fewer runs)", staff["chance_pct"], staff["r_per_chance"],
        ("In trouble often, gets out of it", "Rarely in trouble, gets out of it",
         "Behind on both", "Rarely in trouble, gets hurt"),
        x_better_low=True, y_better_low=True, x_fmt="{:.0f}%", x_bounds=(0, 100), y_bounds=(0, None))


def hitter_scatter(hitters, names):
    pts, tot_pa, tot_runs, tot_re = [], 0, 0, 0.0
    for bid, r in hitters.items():
        if not r["risp_pa"]:
            continue
        tot_pa += r["risp_pa"]
        tot_runs += r["risp_runs"]
        tot_re += r["risp_re24"] or 0
        if r["small_sample"]:
            continue
        full = names.get(bid, f"#{bid}")
        pts.append({"label": full.split()[-1], "x": r["r_per_risp_pa"], "y": r["re24_per_risp_pa"],
                    "title": f"{full}: {r['risp_runs']} runs in {r['risp_pa']} RISP PA, RISP RE24 {_signed(r['risp_re24'])}"})
    return scatter_svg(
        pts, "Runs per RISP PA", "RISP RE24 per PA (run value added)",
        (tot_runs / tot_pa) if tot_pa else None, (tot_re / tot_pa) if tot_pa else None,
        ("Keeps innings alive, fewer runs in", "Cashes in and adds value",
         "Leaves them on", "Drives them in, but costs outs"),
        x_fmt="{:.2f}", y_fmt="{:+.2f}")


# ---------------------------------------------------------------------------
# Leaderboard tables
# ---------------------------------------------------------------------------
def pitcher_table(pitchers, names):
    rows = sorted(pitchers.items(), key=lambda kv: (kv[1]["small_sample"],
                                                     kv[1]["r_per_chance"] if kv[1]["r_per_chance"] is not None else 99,
                                                     -kv[1]["chances"]))
    out = []
    for pid, r in rows:
        if not r["chances"]:
            continue
        out.append({"Pitcher": names.get(pid, f"#{pid}") + (" *" if r["small_sample"] else ""),
                    "Innings": r["innings"], "Chances": r["chances"], "Chance %": _p(r["chance_pct"]),
                    "Runs charged": r["runs"], "R/Chance": _f(r["r_per_chance"]),
                    "Got out clean": f"{r['escaped']} ({_p(r['escape_pct'])})", "2+ run chances": r["multi"]})
    return out


def hitter_table(hitters, names):
    rows = sorted(hitters.items(), key=lambda kv: (kv[1]["small_sample"],
                                                    -(kv[1]["risp_re24"] if kv[1]["risp_re24"] is not None else -99)))
    out = []
    for bid, r in rows:
        if not r["risp_pa"]:
            continue
        out.append({"Hitter": names.get(bid, f"#{bid}") + (" *" if r["small_sample"] else ""),
                    "PA": r["pa"], "RISP PA": r["risp_pa"], "Runs": r["risp_runs"],
                    "R/RISP PA": _f(r["r_per_risp_pa"]), "PAs that scored a run": f"{r['risp_pa_scored']} ({_p(r['cash_pct'])})",
                    "RISP RE24": _signed(r["risp_re24"])})
    return out


# ---------------------------------------------------------------------------
# Profile sections
# ---------------------------------------------------------------------------
def pitcher_section(db, player_id, date_from, date_to, game_scope, note=None):
    mine, staff = sc.pitcher_line(db, player_id, date_from, date_to, game_scope)
    head = ui.div(ui.strong("Runs per Scoring Chance"), "  ", ui_helpers.how_to_link("scoring_chances"),
                  style="margin:14px 0 4px;")
    if not mine or not mine["chances"]:
        return [head, ui.p("No scoring chances in this range yet (no runner on 2nd or 3rd while he pitched).",
                           class_="text-muted small")]
    cards = [
        {"label": "R/Chance", "value": _f(mine["r_per_chance"]), "delta": f"staff {_f(staff['r_per_chance'])} (lower is better)"},
        {"label": "Chances", "value": str(mine["chances"]), "delta": f"in {mine['innings']} innings ({_p(mine['chance_pct'])})"},
        {"label": "Got out clean", "value": _p(mine["escape_pct"]), "delta": f"{mine['escaped']} of {mine['chances']} with 0 runs"},
        {"label": "Runs charged", "value": str(mine["runs"]), "delta": "incl. his runners a reliever let in"},
    ]
    tail = ("Small sample -- fewer than %d chances, so this will move a lot." % sc.MIN_PITCHER_CHANCES
            if mine["small_sample"] else
            "A chance = an inning where he pitched with a runner on 2nd or 3rd, or a run charged to him scored. "
            "Runs go to the pitcher who put that runner on.")
    return [head, ui_helpers.render_kpi_cards(cards), ui.p(tail + (" " + note if note else ""), class_="text-muted small")]


def hitter_section(db, player_id, date_from, date_to, game_scope, note=None):
    mine, _team = sc.hitter_line(db, player_id, date_from, date_to, game_scope)
    head = ui.div(ui.strong("Runs per Scoring Chance (RISP)"), "  ", ui_helpers.how_to_link("scoring_chances"),
                  style="margin:14px 0 4px;")
    if not mine or not mine["risp_pa"]:
        return [head, ui.p("No plate appearances with a runner on 2nd or 3rd in this range yet.", class_="text-muted small")]
    cards = [
        {"label": "R/RISP PA", "value": _f(mine["r_per_risp_pa"]), "delta": f"{mine['risp_runs']} runs in {mine['risp_pa']} PA"},
        {"label": "RISP PA that scored", "value": _p(mine["cash_pct"]), "delta": f"{mine['risp_pa_scored']} of {mine['risp_pa']}"},
        {"label": "RISP RE24", "value": _signed(mine["risp_re24"]), "delta": "runs added in those spots"},
    ]
    tail = ("Small sample -- fewer than %d RISP plate appearances." % sc.MIN_HITTER_RISP_PA if mine["small_sample"] else
            "Runs that scored on the play that ended his at-bat with a runner on 2nd or 3rd. RE24 is the better read: "
            "it gives a 3-run double more credit than a sac fly and takes value away for outs.")
    return [head, ui_helpers.render_kpi_cards(cards), ui.p(tail + (" " + note if note else ""), class_="text-muted small")]
