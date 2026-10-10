"""
GBO -- Staff Compensation (Oct 2026, Ryker). Redesigned after "right now
it is not useful, information doesn't make sense. don't know what
everything means": one card per pitcher, the ones that need attention
first, written in plain English --

  * a one-paragraph read: what he gets his results from, what he lacks,
    and whether his velo is more or less than his body predicts
  * strengths / limiters as "Top 20% of our staff", not SD numbers
  * each flag with why it matters and what to do about it
  * what hasn't been tested yet (so a thin read is obviously thin)

The number grid (SD vs the staff) is still there behind "Show the
numbers", with spelled-out headers. Click a name for the full Player
Profile -> Compensation tab. Staff only. Data: analytics/compensation.py.
"""

from shiny import module, ui, render, reactive

from database import get_session
from analytics import compensation as comp
import ui_helpers

CSS = """
.gbo-sc .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr)); gap: 14px; }
.gbo-sc .pc { background: var(--gbo-bg-card); border: 1px solid var(--gbo-border); border-radius: 10px; padding: 14px 16px; }
.gbo-sc .pc.high { border-left: 4px solid var(--gbo-status-flag); }
.gbo-sc .pc.watch { border-left: 4px solid var(--gbo-status-watch); }
.gbo-sc .pc.clear { border-left: 4px solid var(--gbo-status-good); }
.gbo-sc .pc h6 { margin: 0; display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.gbo-sc .pc a.nm { cursor: pointer; font-weight: 800; font-size: 1rem; }
.gbo-sc .pc .read { margin: 8px 0; line-height: 1.5; }
.gbo-sc .pc .lbl { font-size: .68rem; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--gbo-text-muted); margin: 8px 0 3px; }
.gbo-sc .pc ul { margin: 0; padding-left: 18px; }
.gbo-sc .pc li { margin-bottom: 3px; }
.gbo-sc .pc .good { color: var(--gbo-status-good); font-weight: 700; }
.gbo-sc .pc .bad { color: var(--gbo-status-flag); font-weight: 700; }
.gbo-sc .pc .fl { margin: 6px 0; }
.gbo-sc .pc .fl .do { color: var(--gbo-text-muted); font-size: .85rem; }
.gbo-sc .pc .gap { font-size: .8rem; color: var(--gbo-text-muted); margin-top: 8px; }
.gbo-sc td.z { text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; }
.gbo-sc td.z.s { background: var(--gbo-status-good-soft); color: var(--gbo-status-good); }
.gbo-sc td.z.w { background: var(--gbo-status-flag-soft); color: var(--gbo-status-flag); }
.gbo-sc td.z.na { color: var(--gbo-text-muted); font-weight: 400; }
.gbo-sc th.z { text-align: center; font-size: .7rem; }
"""

# Flag -> (why it matters, what to do). Delivery flags match by prefix.
FLAG_HELP = {
    "Arm-driven velo": ("His velo is ahead of what his lower half produces, so more of the work may be landing on the arm.",
                        "Build lower-body strength / power; keep an eye on his throwing load."),
    "Range without strength": ("Lots of shoulder layback without the strength to control it.",
                               "Shoulder external-rotation strength and decel work."),
    "ER:IR strength ratio": ("The muscles that slow the arm down are weak next to the ones that speed it up.",
                             "Back-of-shoulder (external rotation) and decel strengthening."),
    "Shoulder motion loss with velo": ("He's lost shoulder rotation on his throwing side and throws hard -- a known "
                                       "shoulder/elbow stress combo.",
                                       "Have the AT check it; shoulder mobility work and monitor."),
    "Lead-hip internal rotation": ("A stiff front hip pushes rotation up the chain to the trunk and arm.",
                                   "Lead-hip mobility; check his landing on video."),
    "Velo outrunning arm capacity": ("He throws harder than his shoulder / forearm strength would suggest.",
                                     "Arm-capacity work (shoulder, forearm, grip) before adding intensity."),
    "Command fades late": ("His misses get bigger deeper into outings.",
                           "Look at late-outing video; conditioning and pitch-count plan."),
    "Release angle wanders": ("His release isn't repeating, so location suffers.",
                              "Delivery repeatability work."),
}
LATE_HELP = ("Something in his delivery changes more than the staff's as he tires.",
             "Compare early vs late video; conditioning and pitch-count plan.")
LATE_WHAT = {"Velo": "He loses more velo through an outing than most of our staff.",
             "Release height": "His arm slot drops more than the staff's as he tires.",
             "Release side (width)": "His release drifts away from his body late in outings.",
             "Extension": "He loses extension late -- often the lower half giving out.",
             "Spin": "His spin drops off more than the staff's as he tires."}

NUMBERS_HEAD = {"Size": "Size", "Lower-body strength": "Lower-body strength", "Lower-body power": "Lower-body power",
                "Rotational power": "Rotational power", "Speed": "Speed", "Upper-body strength": "Upper-body strength",
                "Shoulder strength": "Shoulder strength", "Forearm & grip": "Forearm & grip",
                "Shoulder mobility": "Shoulder mobility", "Hip mobility": "Hip mobility"}


def _help(name):
    if name in FLAG_HELP:
        return FLAG_HELP[name]
    if name.endswith("late in outings"):
        what = LATE_WHAT.get(name[:-len(" late in outings")])
        return (what or LATE_HELP[0], LATE_HELP[1])
    return ("", "")


def _ranks(doms_by_pid):
    """{(pid, domain): share of staff he's better than, 0-100}."""
    out = {}
    for d in comp.DOMAIN_NAMES:
        vals = sorted((v[d]["z"], pid) for pid, v in doms_by_pid.items() if d in v)
        n = len(vals)
        for i, (_z, pid) in enumerate(vals):
            out[(pid, d)] = 100.0 * i / (n - 1) if n > 1 else 50.0
    return out


def _rank_words(pct):
    if pct >= 80:
        return "top 20% of our staff"
    if pct >= 65:
        return "top third of our staff"
    if pct <= 20:
        return "bottom 20% of our staff"
    if pct <= 35:
        return "bottom third of our staff"
    return "about staff average"


def _join(xs):
    xs = [x.lower() for x in xs]
    if not xs:
        return ""
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def _velo_sentence(pr, rmse):
    if not pr:
        return None
    exp, act, res = pr
    if res >= rmse:
        return (f"He throws {res:.1f} mph harder than his body predicts ({act:.1f} vs {exp:.1f}) -- he's getting velo "
                f"from somewhere the tests don't measure (delivery, arm speed).")
    if res <= -rmse:
        return (f"He throws {-res:.1f} mph below what his body predicts ({act:.1f} vs {exp:.1f}) -- the physical tools "
                f"are there but aren't showing up in his velo yet.")
    return f"His velo ({act:.1f}) is about what his body predicts."


def pitcher_card(p, doms, ranks, fl, pr, rmse, angle_x, open_js):
    strong, weak = comp.read(doms)
    high = sum(f["level"] == "high" for f in fl)
    status = "high" if high else ("watch" if fl else ("clear" if doms else "none"))
    chip = {"high": ui_helpers.status_chip("flag", f"{high} high flag{'s' if high != 1 else ''}"),
            "watch": ui_helpers.status_chip("watch", f"{len(fl)} to watch"),
            "clear": ui_helpers.status_chip("good", "No flags"),
            "none": ui_helpers.status_chip("neutral", "Not enough tests")}[status]

    bits = []
    if strong:
        bits.append(f"His strengths are {_join(strong)}")
    if weak:
        bits.append(("he's limited by " if strong else "He's limited by ") + _join(weak))
    read = ("; ".join(bits) + ".") if bits else ("Close to staff average on everything tested." if doms else
                                                 "Not enough of his tests are in this season to say yet.")
    vs = _velo_sentence(pr, rmse)

    lists = []
    if strong:
        lists.append(ui.div(ui.div("Leans on", class_="lbl"), ui.tags.ul(*[
            ui.tags.li(ui.span(d, class_="good"), f" -- {_rank_words(ranks[(p.player_id, d)])}") for d in strong])))
    if weak:
        lists.append(ui.div(ui.div("Lacks", class_="lbl"), ui.tags.ul(*[
            ui.tags.li(ui.span(d, class_="bad"), f" -- {_rank_words(ranks[(p.player_id, d)])}") for d in weak])))

    flags_ui = []
    if fl:
        rows = []
        for f in sorted(fl, key=lambda f: f["level"] != "high"):
            why, do = _help(f["name"])
            rows.append(ui.div(
                ui_helpers.status_chip("flag" if f["level"] == "high" else "watch", f["name"]), " ",
                ui.span(why or f["why"]),
                ui.div(ui.strong("What to do: "), do, class_="do") if do else None,
                class_="fl", title=f["why"]))
        flags_ui = [ui.div("Watch items (research-based, not diagnoses)", class_="lbl"), *rows]

    angles = angle_x.get(p.player_id) or []
    angle_ui = ([ui.div("Pitch angles that stand out on our staff", class_="lbl"),
                 ui.tags.ul(*[ui.tags.li(e["text"]) for e in angles])] if angles else [])

    missing = [d for d in comp.DOMAIN_NAMES if d not in doms]
    gap = (ui.div(f"Not tested yet: {', '.join(missing)}.", class_="gap") if missing and doms else None)

    return status, ui.div(
        ui.tags.h6(ui.tags.a(f"{p.first_name} {p.last_name}", class_="nm", title="Open his full profile",
                             onclick=f"Shiny.setInputValue('{open_js}', {p.player_id}, {{priority: 'event'}})"),
                   chip),
        ui.p(read + ((" " + vs) if vs else ""), class_="read"),
        *lists, *flags_ui, *angle_ui, gap,
        class_=f"pc {status}",
    )


@module.ui
def staff_compensation_ui():
    return ui.div(
        ui.tags.style(CSS),
        ui_helpers.page_header("Staff Compensation",
                               "Every pitcher makes up for something. This shows what each one leans on, what he "
                               "lacks, and whether that pattern is a known arm-stress risk -- the ones that need a "
                               "look first."),
        ui.output_ui("controls"),
        ui.output_ui("cards"),
        ui.output_ui("numbers"),
        class_="gbo-sc",
    )


@module.server
def staff_compensation_server(input, output, session, app_state):
    def _ok():
        return app_state.is_authenticated() and app_state.role_name() != "Player"

    @reactive.calc
    def _data():
        db = get_session()
        try:
            data = comp.load(db)
            dl = comp.load_delivery(db, data)
            try:   # Paradigm, "The Angle Advantage": staff angle standouts
                from analytics import approach_angles as aa
                angle_x = aa.staff_extremes(aa.staff_profiles(db))
            except Exception:
                angle_x = {}
        finally:
            db.close()
        rows = []
        for pid, p in data["players"].items():
            doms = data["doms"].get(pid, {})
            _s, weak = comp.read(doms)
            fl = comp.flags(pid, doms, data["derived"][pid], data["model"], data["velo"])
            fl += comp.delivery_flags(dl["drifts"].get(pid, {}), dl["el"].get(pid, (None, None)), dl["staff"], weak)
            rows.append((pid, p, doms, fl))
        return data, rows, angle_x, _ranks(data["doms"])

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        return ui.div(
            ui.input_radio_buttons("sc_show", None, {"attention": "Needs attention", "all": "All pitchers"},
                                   selected="attention", inline=True),
            ui.input_switch("sc_numbers", "Show the numbers", value=False),
            class_="gbo-filter", style="display:flex;gap:28px;align-items:center;flex-wrap:wrap;margin-bottom:8px;",
        )

    @render.ui
    def cards():
        if not _ok() or "sc_show" not in input:
            return None
        data, rows, angle_x, ranks = _data()
        if not rows:
            return ui_helpers.card(ui_helpers.empty_state("No active pitchers."))
        model = data["model"] or {}
        rmse = model.get("rmse", 0.0)
        open_js = session.ns("open")
        built = []
        for pid, p, doms, fl in rows:
            status, card = pitcher_card(p, doms, ranks, fl, model.get("pred", {}).get(pid), rmse, angle_x, open_js)
            order = {"high": 0, "watch": 1, "clear": 2, "none": 3}[status]
            built.append((order, -sum(f["level"] == "high" for f in fl), -len(fl), p.last_name, p.first_name, status, card))
        built.sort(key=lambda t: t[:5])
        n_high = sum(1 for b in built if b[5] == "high")
        n_watch = sum(1 for b in built if b[5] == "watch")
        n_none = sum(1 for b in built if b[5] == "none")
        shown = [b for b in built if input.sc_show() == "all" or b[5] in ("high", "watch")]
        summary = (f"{n_high} pitcher{'s' if n_high != 1 else ''} with a high flag, {n_watch} with something to watch, "
                   f"{len(built) - n_high - n_watch - n_none} clear"
                   + (f", {n_none} without enough tests yet" if n_none else "") + ".")
        how = ("How to read it: strengths and limiters compare him to the rest of our pitchers on that kind of test "
               "(strength and force tests are per pound of body weight). \"Velo vs his body\" compares his fastball to "
               "what pitchers with his tests usually throw on our staff. Watch items come from published research on "
               "arm stress; we don't have an injury log, so they're things to check, not diagnoses.")
        return ui.div(
            ui.p(ui.strong(summary)),
            ui.p(how, class_="text-muted small"),
            ui.div(*[b[6] for b in shown], class_="cards") if shown else
            ui.p("Nobody has a flag right now. Switch to All pitchers to see everyone.", class_="text-muted"),
        )

    @render.ui
    def numbers():
        if not _ok() or "sc_numbers" not in input or not input.sc_numbers():
            return None
        data, rows, _angle_x, _ranks_ = _data()
        model = data["model"] or {}
        head = ui.tags.tr(ui.tags.th("Pitcher"), ui.tags.th("Velo vs his body (mph)", class_="z"),
                          *[ui.tags.th(NUMBERS_HEAD[d], class_="z", title=d) for d in comp.DOMAIN_NAMES])
        body = []
        for pid, p, doms, _fl in sorted(rows, key=lambda r: (r[1].last_name, r[1].first_name)):
            pr = model.get("pred", {}).get(pid)
            rm = model.get("rmse", 0.0)
            vcls = "z" + ((" s" if pr[2] >= rm else " w" if pr[2] <= -rm else "") if pr else " na")
            cells = []
            for d in comp.DOMAIN_NAMES:
                v = doms.get(d)
                if v is None:
                    cells.append(ui.tags.td("·", class_="z na", title=f"{d}: not tested"))
                    continue
                z = v["z"]
                cls = "z s" if z >= comp.STRONG else ("z w" if z <= comp.WEAK else "z")
                cells.append(ui.tags.td(f"{z:+.1f}", class_=cls, title=f"{d}: {z:+.2f} SD from the staff average"))
            body.append(ui.tags.tr(ui.tags.td(f"{p.last_name}, {p.first_name}", style="white-space:nowrap;"),
                                   ui.tags.td(f"{pr[2]:+.1f}" if pr else "—", class_=vcls), *cells))
        return ui_helpers.card(
            ui.p("Each number is how far he is from the staff average on that group of tests, in standard deviations: "
                 "0 = average, +1 = clearly better than most of the staff, -1 = clearly worse. Green = strength "
                 f"(+{comp.STRONG} or more), red = limiter ({comp.WEAK} or less), · = not tested. Velo vs his body = "
                 "his fastball minus what the team model predicts from his tests.", class_="text-muted small"),
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm"),
                   class_="table-responsive"),
            title="The numbers")

    @reactive.effect
    @reactive.event(input.open)
    def _open():
        if not _ok():
            return
        app_state.deep_link_player_id.set((int(input.open()), "Compensation"))
        ui.update_navs("main_nav", selected="Player Profile", session=session.root_scope())
