"""
GBO -- Team Game Report page (Oct 2026, Ryker: "for both hitters and
pitchers i want the hitting and pitching coach as well as head coach to get
game reports for the entire team. be able to see a whole team page that
shows how we performed collectively as well as individual pages for each
player that the coaches can see").

Decisions (AskUserQuestion): every coach sees both sides; in GBO + an
email after each game (scripts/send_team_game_reports.py); scope picker =
one game / a series / a season / any date range.

Staff only. Pitching and Hitting tabs each show the team's collective
numbers, then a row per player; pick a player at the bottom of a tab to
open his own report for the same games (the Pitcher / Hitter Meeting
Report sheet -- game sheet for one game, season-style sheet otherwise).
Math: analytics/team_report.py.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Game, Season
from analytics import team_report, player_report, hitter_report, league_baselines as lb
from visualizations.meeting_report_sheet import render_sheet as render_pitcher_sheet
from visualizations.hitter_report_sheet import render_sheet as render_hitter_sheet

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
ALL = "all"


def _p(v):
    return "—" if v is None else f"{v:.0f}%"


def _a(v):
    if v is None:
        return "—"
    s = f"{v:.3f}"
    return s[1:] if s.startswith("0") else s


@module.ui
def team_game_report_ui():
    return ui.div(
        ui_helpers.page_header("Team Game Report",
                               "How we played as a team -- pitching and hitting -- for a game, a series, a season, or any dates."),
        ui.div(
            ui.input_radio_buttons("scope", "Show", choices={"game": "Game", "series": "Series", "season": "Season",
                                                             "dates": "Dates"}, selected="game", inline=True),
            ui.output_ui("scope_picker"),
            style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end;",
        ),
        ui.output_ui("summary"),
        ui.navset_tab(
            ui.nav_panel("Pitching", ui.output_ui("pitching")),
            ui.nav_panel("Hitting", ui.output_ui("hitting")),
            id="side",
        ),
    )


@module.server
def team_game_report_server(input, output, session, app_state):

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    @render.ui
    def scope_picker():
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger") if app_state.is_authenticated() else None
        db = get_session()
        try:
            games = team_report.tracked_games(db)
            if not games:
                return ui_helpers.empty_state("No tracked games yet.")
            kind = input.scope()
            if kind == "game":
                return ui.input_select("game", "Game", {str(g.game_id): team_report.game_label(g) for g in games}, width="340px")
            if kind == "series":
                ser = team_report.list_series(games)
                return ui.input_select("series", "Series", {s["key"]: s["label"] for s in ser}, width="380px")
            if kind == "season":
                sids = list(dict.fromkeys(g.season_id for g in games if g.season_id is not None))
                seasons = {s.season_id: s for s in db.query(Season).filter(Season.season_id.in_(sids)).all()} if sids else {}
                choices = {str(sid): seasons[sid].season_name for sid in sids if sid in seasons}
                choices[ALL] = "All games"
                return ui.input_select("season", "Season", choices, width="240px")
            last = games[0].game_date
            return ui.div(
                ui.input_date_range("dates", "From / to", start=last - timedelta(days=13), end=last),
            )
        finally:
            db.close()

    @reactive.calc
    def _scope():
        """(games, label, single_game_or_None)"""
        req(_ok())
        kind = input.scope()
        db = get_session()
        try:
            games = team_report.tracked_games(db)
            if kind == "game":
                req("game" in input and input.game())
                g = next((g for g in games if g.game_id == int(input.game())), None)
                req(g)
                return [g], team_report.game_label(g), g
            if kind == "series":
                req("series" in input and input.series())
                s = next((s for s in team_report.list_series(games) if s["key"] == input.series()), None)
                req(s)
                return [g for g in games if g.game_id in s["game_ids"]], s["label"], None
            if kind == "season":
                req("season" in input and input.season())
                v = input.season()
                if v == ALL:
                    return games, "All games", None
                sid = int(v)
                season = db.query(Season).filter(Season.season_id == sid).first()
                return [g for g in games if g.season_id == sid], season.season_name if season else "Season", None
            req("dates" in input and input.dates())
            d0, d1 = input.dates()
            req(d0 and d1)
            sel = [g for g in games if d0 <= g.game_date <= d1]
            return sel, f"{d0.strftime('%b %d')} – {d1.strftime('%b %d, %Y')}", None
        finally:
            db.close()

    @reactive.calc
    def _rep():
        games, label, single = _scope()
        if not games:
            return None
        db = get_session()
        try:
            gs = db.query(Game).options(joinedload(Game.opponent_team)).filter(
                Game.game_id.in_([g.game_id for g in games])).all()
            rep = team_report.build(db, gs)
            rep["label"], rep["single"] = label, single
            return rep
        finally:
            db.close()

    @render.ui
    def summary():
        if not _ok():
            return None
        rep = _rep()
        if rep is None:
            return ui_helpers.empty_state("No games in this range.")
        rec, tp, th = rep["record"], rep["pitching"]["team"], rep["hitting"]["team"]
        cards = []
        if rep["single"] is not None and rec["final"]:
            g = rep["single"]
            res = "W" if g.our_score > g.opponent_score else ("L" if g.our_score < g.opponent_score else "T")
            cards.append({"label": "Final", "value": f"{res} {g.our_score}-{g.opponent_score}",
                          "delta": team_report.opponent_label(g), "delta_positive": res == "W"})
        elif rec["final"]:
            cards.append({"label": "Record", "value": f"{rec['w']}-{rec['l']}" + (f"-{rec['t']}" if rec["t"] else ""),
                          "delta": f"{rec['rf']} runs scored · {rec['ra']} allowed", "delta_positive": rec["rf"] >= rec["ra"]})
        cards.append({"label": "Games", "value": str(rec["games"]),
                      "delta": f"{rec['intrasquads']} intrasquad" if rec["intrasquads"] else None})
        if tp:
            cards.append({"label": "Pitching", "value": f"{tp['ip_display']} IP",
                          "delta": f"{tp['runs']} R · {tp['bb']} BB · {tp['ks']} K"})
        if th:
            cards.append({"label": "Hitting", "value": f"{_a(th['AVG'])} / {_a(th['OBP'])} / {_a(th['SLG'])}",
                          "delta": f"{th['H']} H · {th['BB']} BB · {th['K']} K"})
        so = rep["standouts"]
        lines = []
        if so["pitching"]:
            lines.append(ui.div(ui.strong("On the mound: "), "; ".join(so["pitching"])))
        if so["hitting"]:
            lines.append(ui.div(ui.strong("At the plate: "), "; ".join(so["hitting"])))
        return ui.div(ui.h5(rep["label"], style="margin:10px 0 6px;"), ui_helpers.render_kpi_cards(cards),
                      ui.div(*lines, style="margin:8px 0 14px;font-size:.92rem;") if lines else None)

    # ---------------- Pitching ----------------
    @render.ui
    def pitching():
        if not _ok():
            return None
        rep = _rep()
        if rep is None or not rep["pitching"]["n"]:
            return ui.p("No pitches from our staff in this range.", class_="text-muted small", style="margin-top:10px;")
        t = rep["pitching"]["team"]
        cards = ui_helpers.render_kpi_cards([
            {"label": "Strike %", "value": _p(t["strike_pct"]), "delta": f"{t['pitches']} pitches"},
            {"label": "First-pitch strike %", "value": _p(t["fps_pct"])},
            {"label": "Whiff %", "value": _p(t["whiff_pct"])},
            {"label": "K % / BB %", "value": f"{_p(t['k_pct'])} / {_p(t['bb_pct'])}",
             "delta": f"D2 {lb.pitching('k_pct'):.0f}% / {lb.pitching('bb_pct'):.0f}% · {t['bf']} batters",
             "delta_positive": (t["k_pct"] or 0) - (t["bb_pct"] or 0) >= lb.pitching("k_pct") - lb.pitching("bb_pct")},
            {"label": "ERA* / WHIP", "value": ("—" if t["era"] is None else f"{t['era']:.2f}") + " / "
                                              + ("—" if t["whip"] is None else f"{t['whip']:.2f}"),
             "delta": f"D2 {lb.pitching('era'):.2f} / {lb.pitching('whip'):.2f} · MIAA {lb.pitching('era', 'MIAA'):.2f} / {lb.pitching('whip', 'MIAA'):.2f}",
             "delta_positive": None if t["era"] is None else t["era"] <= lb.pitching("era")},
            {"label": "Hit-the-spot %", "value": _p(t["execution_pct"]), "delta": "needs video review"},
            {"label": "Pitches / inning", "value": "—" if t["pitches_per_inning"] is None else f"{t['pitches_per_inning']:.1f}"},
        ])
        rows = [{"Pitcher": r["name"], "G": r["games"], "IP": r["ip"], "Pitches": r["pitches"], "BF": r["bf"],
                 "H": r["h"], "R": r["r"], "BB": r["bb"], "K": r["k"], "Strike %": _p(r["strike_pct"]),
                 "1st-pitch K %": _p(r["fps_pct"]), "Whiff %": _p(r["whiff_pct"]), "Hit spot %": _p(r["execution_pct"])}
                for r in rep["pitching"]["rows"]]
        types = [{"Pitch": r["Pitch"], "Thrown": r["Thrown"], "Usage": _p(r["Usage %"]), "Strike %": _p(r["Strike %"]),
                  "Whiff %": _p(r["Whiff %"]), "In play": r["In play"], "Hits": r["Hits"],
                  "Hard contact %": _p(r["Hard contact %"])} for r in rep["pitching"]["types"]]
        choices = {str(r["player_id"]): r["name"] for r in rep["pitching"]["rows"]}
        return ui.div(
            ui.div(cards, style="margin-top:12px;"),
            ui.p(ui.strong("Every pitcher"), style="margin:14px 0 4px;"),
            ui_helpers.render_dict_table(rows),
            ui.p(ui.strong("By pitch type (whole staff)"), style="margin:14px 0 4px;"),
            ui_helpers.render_dict_table(types),
            ui.hr(),
            ui.input_select("pitcher_pick", "Open a pitcher's report", choices, width="320px"),
            ui.output_ui("pitcher_sheet"),
        )

    @render.ui
    def pitcher_sheet():
        req(_ok() and "pitcher_pick" in input and input.pitcher_pick())
        games, label, single = _scope()
        pid = int(input.pitcher_pick())
        db = get_session()
        try:
            if single is not None:
                rep = player_report.game_report(db, pid, single.game_id)
            elif input.scope() == "season" and input.season() != ALL:
                rep = player_report.season_report(db, pid, int(input.season()))
            else:
                rep = player_report.range_report(db, pid, [g.game_id for g in games], label)
            if rep is None:
                return ui.p("No pitches for him in this range.", class_="text-muted small")
            return ui.div(ui.HTML(render_pitcher_sheet(rep, None)), style="padding:8px 0 24px;overflow-x:auto;")
        finally:
            db.close()

    # ---------------- Hitting ----------------
    @render.ui
    def hitting():
        if not _ok():
            return None
        rep = _rep()
        h = rep["hitting"] if rep else None
        if not h or not h["n"]:
            return ui.p("No at-bats from our hitters in this range.", class_="text-muted small", style="margin-top:10px;")
        t, sd, fp = h["team"], h["sd"], h["fp"]
        cards = ui_helpers.render_kpi_cards([
            {"label": "AVG / OBP / SLG", "value": f"{_a(t['AVG'])} / {_a(t['OBP'])} / {_a(t['SLG'])}",
             "delta": f"D2 {_a(lb.hitting('AVG'))} / {_a(lb.hitting('OBP'))} / {_a(lb.hitting('SLG'))} · "
                      f"MIAA {_a(lb.hitting('AVG', 'MIAA'))} / {_a(lb.hitting('OBP', 'MIAA'))} / {_a(lb.hitting('SLG', 'MIAA'))}",
             "delta_positive": None if t["OBP"] is None else (t["OBP"] + t["SLG"]) >= lb.hitting("OBP") + lb.hitting("SLG")},
            {"label": "K % / BB %", "value": f"{_p(t['K%'])} / {_p(t['BB%'])}",
             "delta": f"D2 {lb.hitting('K%'):.0f}% / {lb.hitting('BB%'):.0f}% · {t['PA']} PA"},
            {"label": "Swing decisions", "value": _p(t["Swing Decision %"]),
             "delta": f"{sd['counts']['Chase']} chases · {sd['counts']['Taken strike']} hittable strikes taken"},
            {"label": "Chase %", "value": _p(t["Chase %"])},
            {"label": "Hard contact %", "value": _p(t["Hard contact %"])},
            {"label": "2-strike K %", "value": _p(fp["two"]["K %"]), "delta": f"{fp['two']['PAs']} two-strike PAs"},
        ])
        rows = [{"Hitter": r["name"], "PA": r["pa"], "AB": r["ab"], "H": r["h"], "2B": r["2b"], "HR": r["hr"],
                 "BB": r["bb"], "K": r["k"], "AVG": _a(r["avg"]), "OBP": _a(r["obp"]), "SLG": _a(r["slg"]),
                 "Swing dec.": _p(r["sd"]), "Chase %": _p(r["chase"]), "Whiff %": _p(r["whiff"]),
                 "Hard contact %": _p(r["hard"])}
                for r in h["rows"]]
        pt_tabs = []
        for split in ("All", "vs RHP", "vs LHP"):
            prow = [{"Pitch": r["Pitch"], "Seen": r["Seen"], "Swing %": _p(r["Swing %"]), "Whiff %": _p(r["Whiff %"]),
                     "Chase %": _p(r["Chase %"]), "AB": r["AB"], "AVG": _a(r["AVG"]), "SLG": _a(r["SLG"]),
                     "Hard contact %": _p(r["Hard contact %"])} for r in h["pt"][split]]
            pt_tabs.append(ui.nav_panel(split, ui_helpers.render_dict_table(prow)))
        choices = {str(r["player_id"]): r["name"] for r in h["rows"]}
        return ui.div(
            ui.div(cards, style="margin-top:12px;"),
            ui.p(ui.strong("Every hitter"), style="margin:14px 0 4px;"),
            ui_helpers.render_dict_table(rows),
            ui.p(ui.strong("By pitch type (whole lineup)"), style="margin:14px 0 4px;"),
            ui.navset_tab(*pt_tabs),
            ui.hr(),
            ui.input_select("hitter_pick", "Open a hitter's report", choices, width="320px"),
            ui.output_ui("hitter_sheet"),
        )

    @render.ui
    def hitter_sheet():
        req(_ok() and "hitter_pick" in input and input.hitter_pick())
        games, label, single = _scope()
        pid = int(input.hitter_pick())
        db = get_session()
        try:
            if single is not None:
                rep = hitter_report.game_report(db, pid, single.game_id)
            elif input.scope() == "season" and input.season() != ALL:
                rep = hitter_report.season_report(db, pid, int(input.season()))
            else:
                rep = hitter_report.range_report(db, pid, [g.game_id for g in games], label)
            if rep is None:
                return ui.p("No at-bats for him in this range.", class_="text-muted small")
            return ui.div(ui.HTML(render_hitter_sheet(rep, None)), style="padding:8px 0 24px;overflow-x:auto;")
        finally:
            db.close()
