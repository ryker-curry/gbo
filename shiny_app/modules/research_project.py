"""
GBO -- Research Project page (Oct 2026, Ryker: midterm progress report --
"this is for the project looking at the relationship between different
strength and conditioning tests and their correlation (relationship) to
velocity/spin rate ... we are still collecting data and will run
correlations once all data collected").

The first page a guest sees. Explains the study and shows REAL data-
collection progress -- counts only, no names or values -- read straight
from the live database even while the rest of the guest demo runs on the
fictional team (database.SessionLocal, not get_session()).
"""

import datetime as dt

from shiny import module, ui, render, reactive, req

import database
import ui_helpers
from analytics import research_progress, research_analysis as ra, inflection as inf

CSS = """
.gbo-rp p, .gbo-rp li { line-height: 1.55; }
.gbo-rp .lbl { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--gbo-text-muted); margin: 18px 0 6px; }
.gbo-rp .q { font-size: 1.05rem; font-weight: 600; border-left: 3px solid var(--gbo-crimson); padding: 4px 0 4px 12px; margin: 6px 0 14px; }
.gbo-rp table td.n, .gbo-rp table th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.gbo-rp .bar { height: 6px; border-radius: 3px; background: var(--gbo-bg-raised); overflow: hidden; min-width: 80px; }
.gbo-rp .bar > div { height: 100%; background: var(--gbo-series-1); }
.gbo-rp .chk td.c { text-align: center; white-space: nowrap; font-variant-numeric: tabular-nums; }
.gbo-rp .chk .ok { color: var(--gbo-status-good); font-weight: 700; }
.gbo-rp .chk .part { color: var(--gbo-status-watch); font-weight: 700; }
.gbo-rp .chk .no { color: var(--gbo-status-flag); font-weight: 700; }
.gbo-rp .banner { border-left: 4px solid var(--gbo-status-watch); background: var(--gbo-status-watch-soft); padding: 8px 12px; border-radius: 6px; margin: 10px 0; }
.gbo-rp tr.sig td { font-weight: 700; }
.gbo-rp .status { display: inline-block; font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em;
  padding: 3px 10px; border-radius: 999px; color: var(--gbo-status-watch); background: var(--gbo-status-watch-soft); }
"""


@module.ui
def research_project_ui():
    return ui.div(
        ui.tags.style(CSS),
        ui_helpers.page_header("Research Project", "Strength & conditioning tests and their relationship to pitch velocity and spin rate"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
        class_="gbo-rp",
    )


def _bar(n, total):
    pct = 0 if not total else round(100 * n / total)
    return ui.div(ui.div(style=f"width:{pct}%;"), class_="bar")


# Same roles nav.py gives the Research Project page to.
STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")


@module.server
def research_project_server(input, output, session, app_state):
    def _staff():
        return (app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES
                and not database.in_guest_demo())

    @render.ui
    def body():
        intro = [
            ui.div(ui.span("Data collection in progress", class_="status")),
            ui.div("Research question", class_="lbl"),
            ui.p("Which strength and conditioning tests are related to fastball velocity and spin rate in "
                 "collegiate baseball pitchers?", class_="q"),
            ui.div("What is being measured", class_="lbl"),
            ui.tags.ul(
                ui.tags.li(ui.strong("Strength & conditioning tests (the predictors): "),
                           "body composition (InBody 770), explosive power (jumps), rotational power (med ball shot "
                           "put), lower- and upper-body strength, and sprint speed. Every result is entered into GBO "
                           "on the Assessments page and kept with its test date."),
                ui.tags.li(ui.strong("Pitch characteristics (the outcomes): "),
                           "fastball velocity and spin rate from Rapsodo, captured pitch by pitch in bullpens and "
                           "games and linked to each pitcher automatically when the file is imported."),
            ),
            ui.div("Plan", class_="lbl"),
            ui.tags.ol(
                ui.tags.li("Collect the full testing battery and Rapsodo fastball data for every pitcher on the staff."),
                ui.tags.li("For each pitcher, pair his test results with his average fastball velocity and spin rate "
                           "from the same period."),
                ui.tags.li("Once data collection is complete, run correlations between each test and velocity / spin "
                           "rate to see which physical qualities are most closely related to them."),
            ),
            ui.p("GBO is the system that holds all of this in one place: the testing, the pitch data and the "
                 "player records, so the dataset can be pulled for analysis without hand-merging spreadsheets.",
                 class_="text-muted small"),
        ]

        try:
            db = database.SessionLocal()      # REAL database, counts only
            try:
                d = research_progress.progress(db)
            finally:
                db.close()
        except Exception:
            d = None

        if d is None:
            progress_ui = [ui.p("Live progress numbers are unavailable right now.", class_="text-muted")]
        else:
            n = d["n_pitchers"]
            since = d["window"].strftime("%b %-d, %Y") if isinstance(d["window"], dt.date) else "the start of the season"
            kpis = ui_helpers.render_kpi_cards([
                {"label": "Pitchers on the staff", "value": str(n)},
                {"label": "With any S&C testing", "value": f"{d['tested_any']} / {n}"},
                {"label": "With fastball velocity", "value": f"{d['velo']} / {n}"},
                {"label": "With fastball spin rate", "value": f"{d['spin']} / {n}"},
            ])
            head = ui.tags.tr(ui.tags.th("Category"), ui.tags.th("Test"), ui.tags.th("Pitchers tested", class_="n"), ui.tags.th(""))
            rows = []
            last_cat = None
            for cat, test, k in d["rows"]:
                rows.append(ui.tags.tr(
                    ui.tags.td(ui.strong(cat) if cat != last_cat else ""), ui.tags.td(test),
                    ui.tags.td(f"{k} / {n}", class_="n"), ui.tags.td(_bar(k, n), style="width:22%;"),
                ))
                last_cat = cat
            table = ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*rows), class_="table table-sm"),
                           class_="table-responsive")
            progress_ui = [
                ui.p(f"Live counts from GBO's real database for the current season (since {since}). Counts only -- "
                     "no names or individual results are shown here.", class_="text-muted small"),
                kpis,
                ui.p(f"{d['both_any']} pitchers already have both testing and fastball data on file.", style="margin-top:10px;"),
                table,
            ]

        tour = [
            ui.div("Exploring GBO", class_="lbl"),
            ui.p("Everything else in this guest view is the real GBO app running on a made-up team -- every name and "
                 "number outside this page is fictional. Use the sidebar to click around as a head coach, or switch to "
                 "a player's view with the buttons at the top. Good places to start:"),
            ui.tags.ul(
                ui.tags.li(ui.strong("Player Profile / My Assessments: "), "the physical testing breakdown, change since "
                           "the last test, and progress over time -- the same data this study uses."),
                ui.tags.li(ui.strong("Pitcher Profile: "), "Rapsodo velocity, spin and movement for each pitch, plus "
                           "Stuff+, Location+ and Command+ grades."),
                ui.tags.li(ui.strong("Game Tracking and the Pitcher / Hitter Reports: "), "how game data is charted pitch "
                           "by pitch and turned into reports for player meetings."),
            ),
            ui.p("Changes you make in the demo only affect your own copy and disappear when you leave.", class_="text-muted small"),
        ]
        if _staff():
            # Oct 2026: staff (real login, never the guest demo) get the data
            # checklist and analysis tabs -- names only ever shown here.
            return ui.div(
                ui.div(ui.input_action_button("rp_reload", "Reload data", class_="btn-sm btn-outline-light"),
                       ui.span(" Pulls the latest assessments and Rapsodo readings.", class_="text-muted small"),
                       style="display:flex;justify-content:flex-end;align-items:center;gap:8px;margin-bottom:4px;"),
                ui.navset_tab(
                ui.nav_panel("Overview", ui_helpers.card(*intro, title="The study"),
                             ui_helpers.card(*progress_ui, title="Data collection progress")),
                ui.nav_panel("Data checklist", ui.output_ui("rp_checklist")),
                ui.nav_panel("Analysis", ui.output_ui("rp_controls"), ui.output_ui("rp_analysis")),
                ui.nav_panel("Inflection points", ui.output_ui("rp_inf_controls"), ui.output_ui("rp_inf")),
                id="rp_tab",
            ))
        return ui.div(
            ui_helpers.card(*intro, title="The study"),
            ui_helpers.card(*progress_ui, title="Data collection progress"),
            ui_helpers.card(*tour, title="About this demo"),
        )


    # ---- Staff: data checklist + analysis (Oct 2026, analytics/research_analysis.py) ----
    @reactive.calc
    def _ds():
        req(_staff())
        # Re-query on "Reload data", so new assessments / Rapsodo imports show
        # up without logging out.
        if "rp_reload" in input:
            input.rp_reload()
        # Scout login: same data through the Scout engine (names hidden).
        import scout_mode
        db = scout_mode.maker()() if scout_mode.is_scout() else database.SessionLocal()
        try:
            return ra.dataset(db)
        finally:
            db.close()

    def _cell(c):
        if c["done"] == c["total"]:
            return ui.tags.td(ui.span("✓", class_="ok"), " ", c["last"].strftime("%-m/%-d") if c["last"] else "",
                              class_="c", title="All tests on file")
        if c["done"] == 0:
            return ui.tags.td(ui.span("✗", class_="no"), class_="c", title="Nothing on file this season")
        return ui.tags.td(ui.span(f"{c['done']} of {c['total']}", class_="part"), class_="c",
                          title="Missing: " + ", ".join(c["missing"]))

    @render.ui
    def rp_checklist():
        if not _staff():
            return None
        rows = ra.checklist(_ds())
        comp = ra.category_completion(rows)
        only = input.rp_missing_only() if "rp_missing_only" in input else False
        shown = [r for r in rows if not (only and r["complete"])]
        cats = [c for c, _t in ra.BATTERY if c != ra.CALC_GROUP]
        head = ui.tags.tr(ui.tags.th("Pitcher"), ui.tags.th("T", title="Throws"),
                          *[ui.tags.th(c, class_="n") for c in cats], ui.tags.th("FB velo", class_="n"),
                          ui.tags.th("FB spin", class_="n"), ui.tags.th("Notes"))
        body = []
        for r in shown:
            p = r["player"]
            fb = r["fb"]
            body.append(ui.tags.tr(
                ui.tags.td(ui.strong(f"{p.last_name}, {p.first_name}")), ui.tags.td(p.throws or "—"),
                *[_cell(r["cats"][c]) for c in cats],
                ui.tags.td(ui.span(str(fb["n_velo"]), class_="ok" if fb["avg_velo"] is not None else "no"), class_="c",
                           title=f"{ra.MIN_FB}+ fastball readings needed"),
                ui.tags.td(ui.span(str(fb["n_spin"]), class_="ok" if fb["avg_spin"] is not None else "no"), class_="c"),
                ui.tags.td(ui.span(f"{len(r['notes'])} note{'s' if len(r['notes']) != 1 else ''}", class_="part",
                                   title="\n".join(r["notes"])) if r["notes"] else "",
                           class_="small"),
            ))
        bars = ui.tags.table(
            ui.tags.tbody(*[ui.tags.tr(ui.tags.td(k), ui.tags.td(f"{v:.0f}%", class_="n"),
                                       ui.tags.td(_bar(v, 100), style="width:40%;")) for k, v in comp.items()]),
            class_="table table-sm")
        n_done = sum(1 for r in rows if r["complete"])
        return ui.div(
            ui.p(f"{n_done} of {len(rows)} active pitchers have every test plus fastball velo and spin this season. "
                 "✓ = all tests in that category (date of the latest), \"3 of 15\" = partial (hover to see what's "
                 f"missing), ✗ = nothing yet. Fastball columns = pitches behind the study's FB numbers (imported FB VELO&SPIN "
                 f"tab), or Rapsodo readings this season when none were imported ({ra.MIN_FB}+ needed). Notes = values "
                 "the import skipped and why (hover).",
                 class_="text-muted small", style="margin-top:10px;"),
            ui.layout_columns(ui_helpers.card(bars, title="Complete by category"),
                              ui.div(ui.input_checkbox("rp_missing_only", "Only pitchers still missing something", value=only),
                                     ui.download_button("rp_csv", "Download dataset (CSV)", class_="btn-sm btn-outline-light"),
                                     ui.p("One row per pitcher: every test result (latest this season), body weight, "
                                          "and fastball n / average velo / peak velo / average spin / Bauer units -- "
                                          "ready for SPSS, R or Excel.", class_="text-muted small", style="margin-top:6px;")),
                              col_widths=[6, 6]),
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table table-sm chk"),
                   class_="table-responsive"),
        )

    @render.download(filename=lambda: f"gbo_research_dataset_{dt.date.today().isoformat()}.csv")
    def rp_csv():
        req(_staff())
        yield ra.to_csv(_ds())

    @render.ui
    def rp_controls():
        if not _staff():
            return None
        return ui.div(
            ui.input_select("rp_outcome", "Outcome", {k: v[0] for k, v in ra.OUTCOMES.items()}),
            ui.input_radio_buttons("rp_hand", "Pitchers", {"all": "All", "R": "RHP", "L": "LHP"}, inline=True),
            ui.input_checkbox("rp_relative", "Strength & force per lb of body weight", value=False),
            style="display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;margin-top:10px;",
        )

    @render.ui
    def rp_analysis():
        if not _staff():
            return None
        req("rp_outcome" in input)
        ds = _ds()
        outcome = input.rp_outcome()
        hand = input.rp_hand() if "rp_hand" in input else "all"
        rel = input.rp_relative() if "rp_relative" in input else False
        rows, m = ra.correlations(ds, outcome, hand, rel)
        chk = ra.checklist(ds)
        n_done = sum(1 for r in chk if r["complete"])
        banner = (ui.div(ui.strong("Preliminary -- data collection in progress. "),
                         f"{n_done} of {len(chk)} pitchers have complete data. Treat every number here as early; the real "
                         "analysis runs once collection is done.", class_="banner small")
                  if n_done < len(chk) else
                  ui.div(ui.strong("Data collection complete for every active pitcher."), class_="banner small"))

        def f2(v):
            return f"{v:+.2f}" if v is not None else "—"

        def fp(v):
            return "—" if v is None else ("<.001" if v < 0.001 else f"{v:.3f}".replace("0.", ".", 1))
        # Oct 2026 (Ryker): every variable, grouped by the workbook tab it came
        # from; strongest relationships first within each group.
        def _key(r):
            return (r["r"] is None, -(abs(r["r"]) if r["r"] is not None else 0))
        order = []
        for g, _labs in ra.BATTERY:
            order += sorted([r for r in rows if r["category"] == g], key=_key)
        head = ui.tags.tr(*[ui.tags.th(h, class_="n" if i > 1 else None) for i, h in enumerate(
            ["Variable", "Group", "n", "r", "95% CI", "p", "Spearman ρ", "Read"])])
        trs = []
        last_group = None
        for r in order:
            if r["category"] != last_group:
                last_group = r["category"]
                trs.append(ui.tags.tr(ui.tags.td(ui.strong(last_group), colspan="8",
                                                 style="padding-top:10px;color:var(--gbo-crimson);")))
            mark = " **" if r["bonf"] else (" *" if r["bh"] else "")
            trs.append(ui.tags.tr(
                ui.tags.td(r["test"] + (" (per lb)" if r["relative"] else "") + mark), ui.tags.td(r["category"]),
                ui.tags.td(str(r["n"]), class_="n"), ui.tags.td(f2(r["r"]), class_="n"),
                ui.tags.td(f"{f2(r['lo'])} to {f2(r['hi'])}" if r["lo"] is not None else "—", class_="n"),
                ui.tags.td(fp(r["p"]), class_="n"), ui.tags.td(f2(r["rho"]), class_="n"),
                ui.tags.td(ra.meaning(r, outcome)),
                class_="sig" if (r["bh"] or r["bonf"]) else None))
        choices = {r["test"]: f"{r['test']} (n={r['n']}, r={f2(r['r'])})" for r in order if r["n"] >= ra.MIN_N}
        with reactive.isolate():    # keep the pick, but don't redraw the whole table when it changes
            prev = input.rp_test() if "rp_test" in input else None
        sel = prev if prev in choices else next(iter(choices), None)
        return ui.div(
            banner,
            ui.p(f"Each pitcher's latest result on each test this season vs. his {ra.OUTCOMES[outcome][0]} this "
                 f"season. r = Pearson correlation (-1 to +1); 95% CI = the range r likely falls in; p = chance of an r "
                 f"this big if there were no relationship; Spearman ρ = the same on ranks (less thrown off by one outlier). "
                 f"Strength: under .1 negligible, .1-.3 small, .3-.5 moderate, .5+ large. Tests need {ra.MIN_N}+ pitchers. "
                 f"With {m} tests, a few will look 'significant' by chance: * = holds up after a false-discovery-rate "
                 f"correction (Benjamini-Hochberg, 5%), ** = after Bonferroni (p under {0.05 / m if m else 0:.4f}). "
                 "Sprint times: lower is better, so a negative r means faster runners throw harder -- the Read column "
                 "already accounts for that. Correlation isn't cause. "
                 "Throw / Glove and Drive / Plant follow each pitcher's throwing hand. 'Calculated by GBO': ER:IR and "
                 "AD:AB ratios, asymmetries the way the testing sheet does them (shoulder ÷ throwing arm, hip ÷ drive leg, "
                 "single-leg jump and IMTP ÷ the higher side), and Dynamic "
                 "Strength Index = CMJ concentric peak force ÷ IMTP peak force.", class_="text-muted small"),
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*trs), class_="table table-sm"),
                   class_="table-responsive"),
            ui.hr(),
            ui.input_select("rp_test", "Scatter plot", choices=choices, selected=sel) if choices else
            ui.p("No test has enough pitchers yet for a scatter plot.", class_="text-muted small"),
            ui.output_ui("rp_scatter"),
        )

    @render.ui
    def rp_scatter():
        if not _staff():
            return None
        req("rp_test" in input and input.rp_test() and "rp_outcome" in input)
        ds = _ds()
        outcome = input.rp_outcome()
        hand = input.rp_hand() if "rp_hand" in input else "all"
        rel = input.rp_relative() if "rp_relative" in input else False
        pr = ra.pairs(ds, input.rp_test(), outcome, hand, rel)
        if len(pr) < ra.MIN_N:
            return None
        names = {pid: f"{rec['player'].first_name} {rec['player'].last_name}" for pid, rec in ds.items()}
        unit = next((rec["tests"][input.rp_test()][2] for rec in ds.values() if input.rp_test() in rec["tests"]), "")
        xlab = input.rp_test() + (" per lb" if rel and ra.relative_ok(input.rp_test()) else (f" ({unit})" if unit else ""))
        ylab = ra.OUTCOMES[outcome][0] + (f" ({ra.OUTCOMES[outcome][1]})" if ra.OUTCOMES[outcome][1] else "")
        return ui.HTML(_scatter(pr, names, xlab, ylab))

    # ---- Inflection points (Oct 2026, Ryker: "a certain point ... the weight
    # guys need to get to to throw hard") -- analytics/inflection.py ----
    @render.ui
    def rp_inf_controls():
        if not _staff():
            return None
        return ui.div(
            ui.input_select("rp_inf_outcome", "Outcome", {k: v[0] for k, v in ra.OUTCOMES.items()}),
            ui.input_radio_buttons("rp_inf_hand", "Pitchers", {"all": "All", "R": "RHP", "L": "LHP"}, inline=True),
            ui.output_ui("rp_inf_line_ui"),
            style="display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;margin-top:10px;",
        )

    @render.ui
    def rp_inf_line_ui():
        req("rp_inf_outcome" in input)
        o = input.rp_inf_outcome()
        unit = ra.OUTCOMES[o][1]
        step = 50 if o in ("avg_spin", "peak_spin") else 0.5
        return ui.input_numeric("rp_inf_line", f"Line ({unit})" if unit else "Line", value=inf.DEFAULT_LINE[o], step=step)

    @reactive.calc
    def _inf_fits():
        """Breakpoint fits (the slow part: shuffles + bootstrap) -- depend only
        on outcome and hand, not on the velo line."""
        req("rp_inf_outcome" in input)
        o = input.rp_inf_outcome()
        hand = input.rp_inf_hand() if "rp_inf_hand" in input else "all"
        return inf.run(_ds(), o, hand, split=False)

    @reactive.calc
    def _inf_rows():
        rows = _inf_fits()
        o = input.rp_inf_outcome()
        hand = input.rp_inf_hand() if "rp_inf_hand" in input else "all"
        line = input.rp_inf_line() if "rp_inf_line" in input and input.rp_inf_line() is not None else None
        return inf.add_splits(rows, _ds(), o, hand, line)

    @render.ui
    def rp_inf():
        if not _staff():
            return None
        req("rp_inf_outcome" in input)
        o = input.rp_inf_outcome()
        rows = _inf_rows()
        oname, ounit = ra.OUTCOMES[o]
        ou = f" {ounit}" if ounit else ""
        chk = ra.checklist(_ds())
        n_done = sum(1 for r in chk if r["complete"])
        banner = (ui.div(ui.strong("Preliminary -- data collection in progress. "),
                         f"{n_done} of {len(chk)} pitchers have complete data.", class_="banner small")
                  if n_done < len(chk) else None)
        p_ch = [r["fit"]["p_chance"] if r["fit"] else None for r in rows]
        bh = ra.bh_flags(p_ch)

        def fp(v):
            return "—" if v is None else ("<.001" if v < 0.001 else f"{v:.3f}".replace("0.", ".", 1))

        def num(v, unit):
            return f"{v:.1f}" if unit in ("lb", "%", "% of body weight") else f"{v:.2f}"
        head = ui.tags.tr(*[ui.tags.th(h, class_="n" if i in (1, 2, 3, 4, 5) else None) for i, h in enumerate(
            ["Measure", "n", "Cutoff (95% range)", "Slope below → above", "Beats a line (p)", "Beats chance (p)",
             "Read", "Velo-line split"])])
        trs = []
        for i, r in enumerate(rows):
            f, u = r["fit"], r["unit"]
            per = f"per {r['step']:g} {u}" if u in ("lb", "lb/in") else f"per {r['step']:g} pt"
            if f:
                rng_ = (f" ({num(f['lo'], u)}–{num(f['hi'], u)})" if f["lo"] is not None else "")
                cut = ui.TagList(f"{num(f['k'], u)}{rng_}", ui.br(),
                                 ui.span(f"{f['n_below']} below · {f['n_above']} above", class_="text-muted small"))
                slopes = f"{f['b1'] * r['step']:+.1f} → {f['b2'] * r['step']:+.1f}{ou} {per}"
            else:
                cut, slopes = "—", "—"
            sp = r["split"]
            if sp is None:
                split = "—"
            elif sp["degenerate"]:
                split = f"{sp['n_fast']} of {sp['n']} at {sp['line']:g}+ -- move the line"
            else:
                word = "at or above" if sp["higher"] else "below"
                split = (f"{word} {num(sp['cutoff'], u)}: {sp['in_fast']} of {sp['in_n']} reach {sp['line']:g}{ou}; "
                         f"others: {sp['out_fast']} of {sp['out_n']} (p {fp(sp['p'])})")
            trs.append(ui.tags.tr(
                ui.tags.td(r["metric"] + (" *" if i in bh else ""),
                           ui.span(" height check", class_="text-muted small") if r["height"] else None),
                ui.tags.td(str(r["n"]), class_="n"), ui.tags.td(cut, class_="n"), ui.tags.td(slopes, class_="n"),
                ui.tags.td(fp(f["p_line"]) if f else "—", class_="n"), ui.tags.td(fp(f["p_chance"]) if f else "—", class_="n"),
                ui.tags.td(r["read"]), ui.tags.td(split, class_="small"),
                class_="sig" if r["code"] in ("plateau", "takeoff", "bend") else None))
        choices = {r["metric"]: f"{r['metric']} (n={r['n']})" for r in rows if r["n"] >= inf.MIN_N}
        with reactive.isolate():    # keep the pick, but don't redraw the whole table when it changes
            prev = input.rp_inf_metric() if "rp_inf_metric" in input else None
        sel = prev if prev in choices else next(iter(choices), None)
        return ui.div(
            banner,
            ui.p(f"Does {oname.lower()} climb up to a certain body comp number and then level off (or only take off "
                 "after it)? Each measure gets a line that's allowed to bend once -- the bend is the cutoff. "
                 "Beats a line: could straight-line data with the same scatter show a bend this big? Beats chance: "
                 "could random pairings of pitchers and results fit this well? Both need p under .05 before the cutoff "
                 "means anything; * = still holds after correcting for testing all seven measures (Benjamini-Hochberg). "
                 "The 95% range is where the cutoff lands when the pitchers are resampled -- wide = the data can't pin "
                 f"it down yet; only a few pitchers on one side of it means a handful of guys set the bend. Needs "
                 f"{inf.MIN_N}+ pitchers. The height-check rows divide by height, so a cutoff that "
                 "survives there isn't just taller guys being heavier. Velo-line split: the cutoff that best separates "
                 "pitchers who reach the line from those who don't. Bold = a real bend. Pitchers above a cutoff "
                 "throwing harder doesn't prove gaining to it adds velo.", class_="text-muted small"),
            ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*trs), class_="table table-sm"),
                   class_="table-responsive"),
            ui.hr(),
            ui.input_select("rp_inf_metric", "Chart", choices=choices, selected=sel) if choices else
            ui.p(f"No measure has {inf.MIN_N}+ pitchers yet.", class_="text-muted small"),
            ui.output_ui("rp_inf_chart"),
        )

    @render.ui
    def rp_inf_chart():
        if not _staff():
            return None
        req("rp_inf_metric" in input and input.rp_inf_metric() and "rp_inf_outcome" in input)
        o = input.rp_inf_outcome()
        hand = input.rp_inf_hand() if "rp_inf_hand" in input else "all"
        row = next((r for r in _inf_rows() if r["metric"] == input.rp_inf_metric()), None)
        if row is None:
            return None
        ds = _ds()
        pr = inf.pairs(ds, row["metric"], o, hand)
        if len(pr) < inf.MIN_N:
            return None
        names = {pid: f"{rec['player'].first_name} {rec['player'].last_name}" for pid, rec in ds.items()}
        ylab = ra.OUTCOMES[o][0] + (f" ({ra.OUTCOMES[o][1]})" if ra.OUTCOMES[o][1] else "")
        line = row["split"]["line"] if row["split"] else None
        return ui.div(ui.HTML(_inf_svg(pr, names, f"{row['metric']} ({row['unit']})", ylab, row["fit"], line,
                                       row["code"])),
                      ui.p("Solid line = the bent fit (dashed if the bend isn't real -- see the table). Shaded band = "
                           "the cutoff's 95% range. Dotted line = the velo line. Hover a dot for the pitcher.",
                           class_="text-muted small"))


def _inf_svg(pr, names, xlab, ylab, fit, line, code):
    from html import escape
    W, H, L, R, T, B = 640, 360, 64, 20, 16, 48
    xs = [x for _p, x, _y in pr]
    ys = [y for _p, _x, y in pr] + ([line] if line is not None else [])
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    px, py = (x1 - x0) * 0.08 or 1, (y1 - y0) * 0.1 or 1
    x0, x1, y0, y1 = x0 - px, x1 + px, y0 - py, y1 + py

    def X(v):
        return L + (W - L - R) * (v - x0) / (x1 - x0)

    def Y(v):
        return T + (H - T - B) * (1 - (v - y0) / (y1 - y0))
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="{escape(xlab)} vs {escape(ylab)}">']
    for k in range(5):
        yv, xv = y0 + (y1 - y0) * k / 4, x0 + (x1 - x0) * k / 4
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end" class="axis">{yv:.4g}</text>'
                   f'<text x="{X(xv):.1f}" y="{H - 28}" text-anchor="middle" class="axis">{xv:.4g}</text>')
    if fit and fit["lo"] is not None:
        out.append(f'<rect x="{X(fit["lo"]):.1f}" y="{T}" width="{max(1.0, X(fit["hi"]) - X(fit["lo"])):.1f}" '
                   f'height="{H - T - B}" style="fill:var(--gbo-series-1);opacity:.12"/>')
    if line is not None:
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(line):.1f}" y2="{Y(line):.1f}" '
                   'style="stroke:var(--gbo-status-watch);stroke-width:1.5;stroke-dasharray:2 4"/>'
                   f'<text x="{W - R - 4}" y="{Y(line) - 5:.1f}" text-anchor="end" class="axis">line {line:g}</text>')
    if fit:
        k, a, b1, b2 = fit["k"], fit["a"], fit["b1"], fit["b2"]
        xa, xb = min(xs), max(xs)
        real = code in ("plateau", "takeoff", "bend")
        dash = "" if real else ";stroke-dasharray:6 5;opacity:.6"
        pts = [(xa, a + b1 * xa), (k, a + b1 * k), (xb, a + b1 * k + b2 * (xb - k))]
        out.append('<polyline points="' + " ".join(f"{X(u):.1f},{Y(v):.1f}" for u, v in pts) + '" '
                   f'style="fill:none;stroke:var(--gbo-text);stroke-width:2{dash}"/>')
        out.append(f'<line x1="{X(k):.1f}" x2="{X(k):.1f}" y1="{T}" y2="{H - B}" '
                   f'style="stroke:var(--gbo-crimson);stroke-width:1.5;stroke-dasharray:5 4{"" if real else ";opacity:.5"}"/>'
                   f'<text x="{X(k) + 5:.1f}" y="{T + 12}" class="last">cutoff {k:.4g}</text>')
    for pid, x, y in pr:
        out.append(f'<g class="pt"><title>{escape(names.get(pid, "?"))}: {x:.4g}, {y:.4g}</title>'
                   f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="11" class="hit"/>'
                   f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="5" class="dot"/></g>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 8}" text-anchor="middle" class="axis">{escape(xlab)}</text>')
    out.append(f'<text x="14" y="{(T + H - B) / 2:.0f}" text-anchor="middle" class="axis" '
               f'transform="rotate(-90 14 {(T + H - B) / 2:.0f})">{escape(ylab)}</text>')
    out.append("</svg>")
    return "".join(out)


def _scatter(pr, names, xlab, ylab):
    from html import escape
    W, H, L, R, T, B = 640, 340, 64, 20, 16, 48
    xs = [x for _p, x, _y in pr]
    ys = [y for _p, _x, y in pr]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    px, py = (x1 - x0) * 0.08 or 1, (y1 - y0) * 0.1 or 1
    x0, x1, y0, y1 = x0 - px, x1 + px, y0 - py, y1 + py

    def X(v):
        return L + (W - L - R) * (v - x0) / (x1 - x0)

    def Y(v):
        return T + (H - T - B) * (1 - (v - y0) / (y1 - y0))
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="{escape(xlab)} vs {escape(ylab)}">']
    for k in range(5):
        yv = y0 + (y1 - y0) * k / 4
        xv = x0 + (x1 - x0) * k / 4
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{Y(yv) + 4:.1f}" text-anchor="end" class="axis">{yv:.4g}</text>'
                   f'<text x="{X(xv):.1f}" y="{H - 28}" text-anchor="middle" class="axis">{xv:.4g}</text>')
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx:
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        a = my - b * mx
        xa, xb = min(xs), max(xs)
        out.append(f'<line x1="{X(xa):.1f}" y1="{Y(a + b * xa):.1f}" x2="{X(xb):.1f}" y2="{Y(a + b * xb):.1f}" '
                   'style="stroke:var(--gbo-text);stroke-width:2"/>')
    r = ra.pearson(xs, ys)
    for pid, x, y in pr:
        out.append(f'<g class="pt"><title>{escape(names.get(pid, "?"))}: {x:.4g}, {y:.4g}</title>'
                   f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="11" class="hit"/>'
                   f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="5" class="dot"/></g>')
    out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 8}" text-anchor="middle" class="axis">{escape(xlab)}</text>')
    out.append(f'<text x="14" y="{(T + H - B) / 2:.0f}" text-anchor="middle" class="axis" '
               f'transform="rotate(-90 14 {(T + H - B) / 2:.0f})">{escape(ylab)}</text>')
    if r is not None:
        out.append(f'<text x="{W - R}" y="{T + 12}" text-anchor="end" class="last">r = {r:+.2f}, n = {len(pr)}</text>')
    out.append("</svg>")
    return "".join(out)
