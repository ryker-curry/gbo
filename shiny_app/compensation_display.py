"""
GBO -- Compensation tab on Player Profile (Oct 2026, staff only, pitchers).
Data: analytics/compensation.py.
"""

from html import escape

from shiny import ui

import ui_helpers
from analytics import compensation as comp


def _domain_svg(doms):
    """Diverging bars: one row per domain, -2.5 to +2.5 SD vs the staff."""
    names = comp.DOMAIN_NAMES
    W, row, L, R, T = 640, 30, 170, 70, 22
    H = T + row * len(names) + 26
    span = 2.5
    mid = L + (W - L - R) / 2
    half = (W - L - R) / 2

    def X(z):
        return mid + half * max(-span, min(span, z)) / span
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Strengths and limiters by domain">']
    for k in (-2, -1, 0, 1, 2):
        out.append(f'<line x1="{X(k):.1f}" x2="{X(k):.1f}" y1="{T - 6}" y2="{H - 22}" class="grid"/>'
                   f'<text x="{X(k):.1f}" y="{H - 6}" text-anchor="middle" class="axis">{k:+d}</text>'.replace(">+0<", ">0<"))
    out.append(f'<text x="{X(-2.4):.1f}" y="{T - 9}" class="axis">limiter</text>'
               f'<text x="{X(2.4):.1f}" y="{T - 9}" text-anchor="end" class="axis">strength</text>')
    for i, name in enumerate(names):
        y = T + i * row
        d = doms.get(name)
        out.append(f'<text x="{L - 10}" y="{y + 19}" text-anchor="end" class="axis">{escape(name)}</text>')
        if d is None:
            out.append(f'<text x="{mid + 6:.1f}" y="{y + 19}" class="axis" style="opacity:.6">not tested</text>')
            continue
        z = d["z"]
        color = ("var(--gbo-status-good)" if z >= comp.STRONG else
                 "var(--gbo-status-flag)" if z <= comp.WEAK else "var(--gbo-text-muted)")
        x0, x1 = sorted((mid, X(z)))
        tests = "; ".join(f"{n}: {zz:+.1f}" for n, _v, zz in d["tests"])
        out.append(f'<g><title>{escape(name)} {z:+.2f} SD ({escape(tests)})</title>'
                   f'<rect x="{x0:.1f}" y="{y + 6}" width="{max(2.0, x1 - x0):.1f}" height="18" rx="3" style="fill:{color}"/></g>'
                   f'<text x="{(X(z) + 6) if z >= 0 else (X(z) - 6):.1f}" y="{y + 19}" '
                   f'text-anchor="{"start" if z >= 0 else "end"}" class="axis">{z:+.1f}</text>')
    out.append("</svg>")
    return "".join(out)


def _join(xs):
    xs = [x.lower() for x in xs]
    return xs[0] if len(xs) == 1 else " and ".join(xs)


def strengths_card(doms):
    if not doms:
        return ui_helpers.card(ui_helpers.empty_state("No tests on file this season to compare against the staff."),
                               title="Strengths vs limiters")
    strong, weak = comp.read(doms)
    if strong and weak:
        line = f"Leans on {_join(strong)}; limited by {_join(weak)}."
    elif strong:
        line = f"Leans on {_join(strong)}; no clear limiter among what's tested."
    elif weak:
        line = f"Limited by {_join(weak)}; no standout strength among what's tested."
    else:
        line = "Close to the staff average across what's tested -- no clear strength or limiter."
    missing = [d for d in comp.DOMAIN_NAMES if d not in doms]
    cover = (ui.p(f"Tested in {len(doms)} of {len(comp.DOMAIN_NAMES)} domains -- not in yet: {', '.join(missing)}. "
                  "The read, the flags that need those domains, and the staff comparisons fill in as testing is "
                  "logged.", class_="small", style="color:var(--gbo-status-watch);") if missing else None)
    rows = [{"Domain": d, "Test": n, "Value": f"{v:.3g}", "vs staff (SD)": f"{z:+.2f}"}
            for d in comp.DOMAIN_NAMES if d in doms for n, v, z in doms[d]["tests"]]
    return ui_helpers.card(
        ui.p(ui.strong(line)),
        cover,
        ui.HTML(_domain_svg(doms)),
        ui.p("Each bar is his average across that domain's tests vs the active pitching staff this season (0 = staff "
             "average, ±1 = one standard deviation). Strength and force tests are per lb of body weight, so size only "
             f"counts once. Green = strength (+{comp.STRONG}), red = limiter ({comp.WEAK}). Hover a bar for the tests.",
             class_="text-muted small"),
        ui.accordion(ui.accordion_panel("Every test", ui_helpers.render_dict_table(rows)), open=False),
        title="Strengths vs limiters",
    )


def velo_card(pid, model, velo):
    if velo is None:
        body = [ui.p("Not enough Rapsodo fastballs this season (5+ needed).", class_="text-muted small")]
    elif model is None or pid not in model["pred"]:
        need = ", ".join((model or {}).get("predictors") or comp.MODEL_DOMAINS)
        body = [ui.p(f"Season FB velo {velo:.1f} mph. The team model needs {comp.MIN_MODEL}+ pitchers with {need} and FB "
                     "velo, and this pitcher needs each of those tested.", class_="text-muted small")]
    else:
        exp, act, res = model["pred"][pid]
        rm = model["rmse"]
        if res >= rm:
            word = "Throws well above what his body predicts -- velo the tests don't explain (mechanics, arm speed, " \
                   "elasticity). That's the compensation to look at."
        elif res <= -rm:
            word = "Throws well below what his body predicts -- the physical tools are there; something is leaking " \
                   "(mechanics, sequencing, intent)."
        else:
            word = "About what his body predicts."
        body = [
            ui_helpers.render_kpi_cards([
                {"label": "Actual FB velo", "value": f"{act:.1f}"},
                {"label": "Expected from body", "value": f"{exp:.1f}"},
                {"label": "Difference", "value": f"{res:+.1f} mph"},
                {"label": "Typical model error", "value": f"±{rm:.1f}"},
            ]),
            ui.p(ui.strong(word)),
            ui.p(f"Expected = a straight-line model of season average FB velo on {', '.join(model['predictors'])} across "
                 f"{model['n']} pitchers, fit without him so he can't predict himself. "
                 + (f"Those domains were picked because they track with velo across the staff (|r| ≥ {comp.PICK_R:.2f}: "
                    + ", ".join(f"{d} {model['screen'][d][0]:+.2f}" for d in model["predictors"] if d in model["screen"])
                    + "); they're re-picked as data comes in. " if model.get("picked") else
                    "No domain tracks with velo strongly enough yet, so it uses the default three. ")
                 + "'Well above/below' = more than the typical error. Small staff, rough model -- a starting point for "
                 "a conversation.", class_="text-muted small"),
        ]
    return ui_helpers.card(*body, title="Velo vs his body")


def flags_card(fl):
    if not fl:
        body = [ui.p("None of the watch patterns show up with what's tested.", class_="small")]
    else:
        body = [ui.div(
            ui_helpers.status_chip("flag" if f["level"] == "high" else "watch", "High" if f["level"] == "high" else "Watch"),
            " ",
            ui.strong(f["name"]), ": ", f["why"], style="margin-bottom:8px;") for f in fl]
    body.append(ui.p("Research-based patterns linked to arm stress -- watch items to check with the AT and on video, "
                     "not diagnoses. GBO has no injury log, so none of these are validated on this team yet.",
                     class_="text-muted small"))
    return ui_helpers.card(*body, title="Risk-pattern flags")


def _fmt(v, f):
    return "—" if v is None else f.format(v)


def tracking_card(doms, timeline, effects_by_domain, months):
    strong, weak = comp.read(doms) if doms else ([], [])
    parts = []
    if len(timeline) < 2:
        parts.append(ui.p("Only one test date so far -- retest to see whether improving a limiter changes his velo "
                          "and availability.", class_="text-muted small"))
    focus = weak or [d for d in comp.DOMAIN_NAMES if effects_by_domain.get(d)][:2]
    for dom in focus:
        pts = [(d, z[dom]) for d, z in timeline if dom in z]
        if not pts:
            continue
        years = {d.year for d, _z in pts[-6:]}
        fmt = "%b %-d" if len(years) == 1 else "%b %-d, %Y"
        trail = " → ".join(f"{d.strftime(fmt)}: {z:+.1f}" for d, z in pts[-6:])
        lines = [ui.p(ui.strong(dom + (" (limiter)" if dom in weak else "")), ui.br(),
                      ui.span(trail, class_="small"))]
        for e in effects_by_domain.get(dom, []):
            word = "improved" if e["z1"] > e["z0"] else "dropped"
            v = (f"FB {e['velo_before']:.1f} → {e['velo_after']:.1f} mph ({e['dvelo']:+.1f})" if e["dvelo"] is not None
                 else "not enough FB readings on both sides")
            h = f"Hold/Limited days {e['hold_before']} → {e['hold_after']}"
            tail = "" if e["after_complete"] else " (after-window still open)"
            lines.append(ui.p(f"{word} {e['z0']:+.1f} → {e['z1']:+.1f} SD on {e['to'].strftime('%b %-d, %Y')}: "
                              f"{comp.WINDOW_DAYS} days before vs after -- {v}; {h}.{tail}", class_="small mb-1"))
        parts.append(ui.div(*lines, style="margin-bottom:12px;"))
    rows = [{"Month": m["month"].strftime("%b %Y"), "FB velo": _fmt(m["velo"], "{:.1f}"), "FB readings": m["n"],
             "Velo fade / 25 pitches": _fmt(m["fade"], "{:+.1f}"), "Game miss (in)": _fmt(m["miss"], "{:.1f}"),
             "Hold/Limited days": m["hold"]} for m in months[-12:]]
    parts.append(ui.p(ui.strong("Month by month"), class_="mt-2 mb-1"))
    parts.append(ui_helpers.render_dict_table(rows, empty_message="No Rapsodo, game or availability data yet."))
    parts.append(ui.p(f"Domain scores at each test date are against TODAY's staff so the scale holds still. Before/after "
                      f"= Rapsodo fastballs and Arm Care Hold/Limited days in the {comp.WINDOW_DAYS} days on each side of "
                      "the retest. Game miss = average distance from the called spot on charted game pitches. One "
                      "pitcher over a few months can't separate cause from season timing -- read it next to the team "
                      "view below.", class_="text-muted small"))
    return ui_helpers.card(*parts, title="Fix-the-limiter tracking")


def team_card(team):
    rows = []
    for dom in comp.DOMAIN_NAMES:
        t = team.get(dom) or {}
        rows.append({"Domain": dom, "Retests with velo both sides": t.get("n", 0),
                     "r (domain change vs velo change)": _fmt(t.get("r"), "{:+.2f}"),
                     "Avg FB change after an improvement": (f"{t['improved_dvelo']:+.1f} mph (n={t['n_improved']})"
                                                            if t.get("improved_dvelo") is not None else "—")})
    return ui_helpers.card(
        ui_helpers.render_dict_table(rows),
        ui.p(f"Every active pitcher's retests pooled: when a domain moved {0.25:.2f}+ SD between tests, how did his FB "
             f"velo change in the {comp.WINDOW_DAYS} days after vs before? r needs 8+ retests. This is where 'does fixing "
             "the limiter help' gets answered -- early on it will mostly read '—'.", class_="text-muted small"),
        title="Across the staff",
    )


def own_card(rows, n_dates):
    """What works for HIM -- his own history, not the staff."""
    if not rows:
        return ui_helpers.card(
            ui.p(f"Needs a test measured on {comp.NOF1_MIN}+ dates with Rapsodo fastballs within {comp.NOF1_WINDOW} days "
                 f"of each -- {n_dates} test date{'s' if n_dates != 1 else ''} on file so far.", class_="text-muted small"),
            title="What works for him")
    top = [r for r in rows if abs(r["r"]) >= 0.5][:3]
    flat = [r for r in rows if abs(r["r"]) < 0.2][:2]
    bits = []
    if top:
        bits.append("His velo has moved with " + ", ".join(
            f"{r['test'].lower()} ({r['r']:+.2f}, {r['n']} tests)" for r in top))
    if flat:
        bits.append("not with " + ", ".join(f"{r['test'].lower()} ({r['r']:+.2f})" for r in flat))
    line = ("; ".join(bits) + ".") if bits else "Nothing tracks clearly with his velo yet."
    solid = max(r["n"] for r in rows) >= comp.NOF1_SOLID
    table = [{"Test": r["test"], "Domain": r["domain"] or "—", "Tests with velo": r["n"],
              "r (better test = more velo)": f"{r['r']:+.2f}",
              "Velo: better half vs worse half": f"{r['diff']:+.1f} mph"} for r in rows]
    return ui_helpers.card(
        ui.p(ui.strong(line[0].upper() + line[1:])),
        None if solid else ui.p(f"Early and anecdotal -- fewer than {comp.NOF1_SOLID} test dates. Read as a hunch to "
                                "test, not a finding.", class_="small", style="color:var(--gbo-status-watch);"),
        ui_helpers.render_dict_table(table),
        ui.p(f"His own history only, not the staff: each test result paired with his Rapsodo FB velo within "
             f"{comp.NOF1_WINDOW} days of that test. r is flipped for lower-is-better tests so + always means 'a better "
             "result went with more velo'. This is the 'works for one guy, not another' view -- compare it with the "
             "staff-level research results. Season timing (velo usually climbs into the spring) can masquerade as a "
             "relationship.", class_="text-muted small"),
        title="What works for him",
    )


def delivery_card(drift, el, staff, release_grade, fl):
    rows = []
    for key, label, unit, _s in comp.DRIFT_METRICS:
        if key not in drift:
            continue
        v, n = drift[key]
        st = staff.get(key)
        rows.append({"First vs last 10 FB": label, "His change": f"{v:+.1f} {unit}",
                     "Staff average": f"{st[0]:+.1f} {unit}" if st else "—", "Outings": n})
    e, l = el
    parts = []
    if fl:
        parts += [ui.div(ui_helpers.status_chip("flag" if f["level"] == "high" else "watch",
                                                "High" if f["level"] == "high" else "Watch"), " ",
                         ui.strong(f["name"]), ": ", f["why"], style="margin-bottom:8px;") for f in fl]
    elif rows or (e is not None and l is not None):
        parts.append(ui.p("Nothing in his delivery changes more than the staff's as he tires.", class_="small"))
    parts.append(ui_helpers.render_dict_table(rows, empty_message=f"No outing with {comp.MIN_OUTING_FB}+ Rapsodo fastballs yet."))
    kpis = []
    if e is not None and l is not None:
        kpis += [{"label": "Game miss, pitches 1-25", "value": f'{e:.1f}"'}, {"label": "Game miss, 50+", "value": f'{l:.1f}"'}]
    if release_grade is not None:
        kpis.append({"label": "Release consistency", "value": f"{release_grade:.0f}"})
    if kpis:
        parts.append(ui_helpers.render_kpi_cards(kpis))
    parts.append(ui.p(f"As he tires: the last {comp.EDGE_FB} fastballs minus the first {comp.EDGE_FB} in each Rapsodo "
                      f"outing ({comp.MIN_OUTING_FB}+ fastballs), averaged. Width = distance of the release from his "
                      "body's center line, so + = wider late. Game miss = distance from the called spot (needs 10+ "
                      "located pitches in each range). Release consistency: 100 = staff average, higher = tighter. "
                      "Flags only fire when he's more than 1 SD worse than the staff, and link to a limiter when "
                      "one fits -- those links are coaching hypotheses to check on video.", class_="text-muted small"))
    return ui_helpers.card(*parts, title="Delivery compensations")


def idp_buttons(weak, specs, ns_id):
    """One 'Make IDP goal' button per limiter with a usable test."""
    out = []
    for i, dom in enumerate(weak):
        sp = specs.get(dom)
        if not sp:
            continue
        out.append(ui.div(
            ui.input_action_button(f"{ns_id}_{i}", f"Make IDP goal: {dom}", class_="btn-sm btn-outline-light"),
            ui.span(f" {sp['test']}: {sp['baseline']:.1f} → staff average {sp['target']:.1f}"
                    + (" (per-lb average x his weight)" if sp["per_lb"] else "") + f", due in {comp.IDP_WEEKS} weeks",
                    class_="text-muted small"),
            style="margin:4px 0;"))
    return ui.div(*out) if out else None
