"""
GBO -- Player Types (Oct 2026, Ryker: the Georgia Southern Muscular /
Hybrid / Elastic athlete types "to help with development, deciding on best
training for each player", plus "anything similar ... for pitcher type,
how each pitcher attacks or should based on arsenal").

Two team boards, staff only:
  * Athlete types  -- every player's archetype from jump / force tests
                      (analytics/athlete_archetype.py) and its training focus,
                      grouped so lifting groups can be built by type.
  * Pitcher types  -- every pitcher's type and whether his games follow his
                      attack plan (analytics/pitcher_type.py), season to date.
Click a name for the full card (Player Profile / Pitcher Deep Dive).
"""

import html

from shiny import module, ui, render, req

from database import get_session
import ui_helpers

STAFF_ONLY = ("Player",)


def _e(s):
    return html.escape(str(s))


CSS = """
<style>
.gbo-pt-board { width:100%; border-collapse:separate; border-spacing:0 4px; }
.gbo-pt-board th { font-size:.66rem; text-transform:uppercase; letter-spacing:.05em; color:var(--gbo-text-muted);
  text-align:left; padding:2px 8px; }
.gbo-pt-board td { background:var(--gbo-bg-raised,#1D1D20); padding:8px; font-size:.85rem; vertical-align:top; }
.gbo-pt-board td:first-child { border-radius:8px 0 0 8px; font-weight:700; }
.gbo-pt-board td:last-child { border-radius:0 8px 8px 0; }
.gbo-pt-badge { padding:1px 8px; border-radius:6px; font-weight:800; font-size:.72rem; color:#111; white-space:nowrap; }
.gbo-pt-sum { display:flex; gap:10px; flex-wrap:wrap; margin:6px 0 12px; }
.gbo-pt-sum div { border:1px solid var(--gbo-border); border-radius:10px; padding:8px 12px; min-width:150px; }
.gbo-pt-sum b { font-size:1.3rem; display:block; }
</style>
"""


@module.ui
def player_types_ui():
    return ui.div(
        ui_helpers.page_header("Player Types", "What kind of athlete and what kind of pitcher each player is -- and "
                               "what that means for how he trains and attacks hitters."),
        ui.navset_tab(
            ui.nav_panel("Athlete types", ui.div(ui.output_ui("athletes"), style="padding-top:12px;")),
            ui.nav_panel("Pitcher types", ui.div(ui.output_ui("pitchers"), style="padding-top:12px;")),
            id="pt_tab",
        ),
    )


@module.server
def player_types_server(input, output, session, app_state):

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() not in STAFF_ONLY

    @render.ui
    def athletes():
        if not _ok():
            return ui.p("Staff only.", class_="text-muted")
        from analytics import athlete_archetype as aa
        from archetype_display import KIND_C
        db = get_session()
        try:
            rows = aa.team(db)
        finally:
            db.close()
        if not rows:
            return ui_helpers.empty_state("No players have both a force test and a jump / spring test yet.")
        counts = {k: sum(1 for _p, pr in rows if pr["kind"] == k) for k in ("Elastic", "Hybrid", "Muscular")}
        summ = "".join(
            f'<div><b style="color:{KIND_C[k]}">{n}</b><span class="small">{k} -- '
            f'{_e(aa.TRAINING[k]["focus"].lower())}</span></div>' for k, n in counts.items())
        trs = []
        for p, pr in rows:
            pos = "P" if p.is_pitcher else "H"
            pos_pct = max(0, min(100, 50 + pr["index"] * 50))
            bar = (f'<div style="position:relative;height:6px;border-radius:3px;min-width:110px;'
                   f'background:linear-gradient(90deg,{KIND_C["Muscular"]},{KIND_C["Hybrid"]},{KIND_C["Elastic"]})">'
                   f'<div style="position:absolute;left:calc({pos_pct:.0f}% - 5px);top:-3px;width:10px;height:10px;'
                   f'border-radius:50%;background:#fff"></div></div>')
            trs.append(
                f'<tr><td>{_e(p.first_name)} {_e(p.last_name)} <span class="text-muted small">{pos}</span></td>'
                f'<td><span class="gbo-pt-badge" style="background:{KIND_C[pr["kind"]]}">{pr["kind"].upper()}</span></td>'
                f'<td>{bar}<div class="small text-muted">force ← {pr["index"]:+.2f} → spring</div></td>'
                f'<td>{pr["output"]}</td>'
                f'<td>{_e(pr["best"]["label"])} <span class="text-muted small">({pr["best"]["pct"]})</span></td>'
                f'<td>{_e(pr["worst"]["label"])} <span class="text-muted small">({pr["worst"]["pct"]})</span></td>'
                f'<td>{_e(aa.TRAINING[pr["kind"]]["focus"])}</td></tr>')
        table = ('<div class="gbo-sg-wrap"><table class="gbo-pt-board"><thead><tr><th>Player</th><th>Type</th>'
                 '<th>Force vs spring</th><th>Overall output (team pct)</th><th>Superpower</th><th>Biggest opportunity</th>'
                 f'<th>Training focus</th></tr></thead><tbody>{"".join(trs)}</tbody></table></div>')
        how = ("From each player's latest jump and force tests, ranked against the team (Georgia Southern's archetype "
               "idea). Elastic = wins with speed and spring, Muscular = wins with force, Hybrid = no strong lean. Use "
               "it to group lifting: Elastic guys need strength under the spring, Muscular guys need speed and "
               "reactive work. Open a player's Player Profile → Assessments for his full card and a one-click IDP goal. "
               "A snapshot of the latest test -- regular jump testing turns it into a trend.")
        return ui.div(ui.HTML(CSS), ui.p(how, class_="text-muted small"), ui.HTML(f'<div class="gbo-pt-sum">{summ}</div>'),
                      ui.HTML(table))

    @render.ui
    def pitchers():
        if not _ok():
            return ui.p("Staff only.", class_="text-muted")
        req("pt_tab" in input and input.pt_tab() == "Pitcher types")
        import bucket_system as bs
        from analytics import pitcher_type
        from pitch_insights_display import _PT_COLOR
        d0, d1 = bs.season_date_range(bs.current_season_label())
        db = get_session()
        try:
            rows = pitcher_type.team(db, d0, d1)
        finally:
            db.close()
        if not rows:
            return ui_helpers.empty_state("No charted game pitches this season yet.")
        trs = []
        for p, t in rows:
            n = sum(1 for r in t["rows"] if r["status"])
            ok = sum(1 for r in t["rows"] if r["status"] == "match")
            gap_rows = [r for r in t["rows"] if r["status"] == "gap"]
            gap = "; ".join(f'{r["stage_lbl"].split(" (")[0]} vs {"same" if r["side"] == "same" else "opposite"}-handed: '
                            f'plan says {r["plan"]}, he throws {r["actual"].split(" of ")[0]}' for r in gap_rows[:2])
            mix = " · ".join(f"{k} {v:.0f}%" for k, v in sorted(t["use"].items(), key=lambda kv: -kv[1]) if v >= 5)
            trs.append(
                f'<tr><td>{_e(p.first_name)} {_e(p.last_name)} <span class="text-muted small">{_e(p.throws or "")}HP</span></td>'
                f'<td><span class="gbo-pt-badge" style="background:{_PT_COLOR.get(t["type"], "#999")};color:#fff">'
                f'{_e(t["type"].upper())}</span>{" <span class=small>· power</span>" if t["power"] else ""}</td>'
                f'<td class="small">{_e(mix)}</td>'
                f'<td>{"—" if t.get("fb_velo") is None else format(t["fb_velo"], ".1f")}</td>'
                f'<td>{ok} of {n}</td><td class="small">{_e(gap) or "—"}</td></tr>')
        table = ('<div class="gbo-sg-wrap"><table class="gbo-pt-board"><thead><tr><th>Pitcher</th><th>Type</th>'
                 '<th>Mix</th><th>FB velo</th><th>Plan followed</th><th>Biggest gaps</th></tr></thead>'
                 f'<tbody>{"".join(trs)}</tbody></table></div>')
        how = ("Season to date. Type comes from his fastball shape and arm slot (Arsenal Plan), how many pitches he "
               "really uses, and velo / strike rate vs our staff. 'Plan followed' = count / hitter-hand situations "
               "where his game usage matches how his type should attack. Open Pitcher Deep Dive → Coach Summary for "
               "his full attack plan.")
        return ui.div(ui.HTML(CSS), ui.p(how, class_="text-muted small"), ui.HTML(table))
