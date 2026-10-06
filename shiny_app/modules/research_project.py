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

from shiny import module, ui, render

import database
import ui_helpers
from analytics import research_progress

CSS = """
.gbo-rp p, .gbo-rp li { line-height: 1.55; }
.gbo-rp .lbl { font-size: .72rem; font-weight: 700; text-transform: uppercase; letter-spacing: .07em; color: var(--gbo-text-muted); margin: 18px 0 6px; }
.gbo-rp .q { font-size: 1.05rem; font-weight: 600; border-left: 3px solid var(--gbo-crimson); padding: 4px 0 4px 12px; margin: 6px 0 14px; }
.gbo-rp table td.n, .gbo-rp table th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.gbo-rp .bar { height: 6px; border-radius: 3px; background: var(--gbo-bg-raised); overflow: hidden; min-width: 80px; }
.gbo-rp .bar > div { height: 100%; background: var(--gbo-series-1); }
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


@module.server
def research_project_server(input, output, session, app_state):
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
        return ui.div(
            ui_helpers.card(*intro, title="The study"),
            ui_helpers.card(*progress_ui, title="Data collection progress"),
            ui_helpers.card(*tour, title="About this demo"),
        )
