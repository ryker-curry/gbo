"""
GBO -- Data Health page (Oct 2026, Ryker approved; staff only, under Game
Operations). Read-only: lists what's missing or inconsistent in each
game's charting so every report stays accurate, with a "Fix in Game
Tracking" button that opens that game. Checks: analytics/data_health.py.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req

from database import get_session
from analytics import data_health, box_score, rapsodo_check
from analytics import metric_check as mcheck
from analytics.team_report import game_label

import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
GRADE_COLORS = {"green": "#2E9C62", "yellow": "#B58A22", "red": "#D94F3D"}


@module.ui
def data_health_ui():
    return ui.div(
        ui_helpers.page_header("Data Health",
                               "What's missing in the charting -- fix these and every report stays accurate.", actions=ui_helpers.how_to_link("data_health")),
        ui.output_ui("controls"),
        ui.navset_tab(
            ui.nav_panel("Game charting",
                         ui.output_ui("summary"),
                         ui.output_ui("box_card"),
                         ui.output_ui("games")),
            ui.nav_panel("Rapsodo readings", ui.output_ui("rapsodo")),
            ui.nav_panel("Metric check", ui.output_ui("metric_check")),
            id="dh_tab",
        ),
    )


@module.server
def data_health_server(input, output, session, app_state):

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        today = date.today()
        return ui.div(
            ui.input_date_range("range", "From / to", start=today - timedelta(days=14), end=today),
            ui.input_checkbox("only_problems", "Only show games with something to fix", value=True),
            style="display:flex;gap:24px;align-items:flex-end;flex-wrap:wrap;",
        )

    _saved = reactive.value(0)

    @reactive.calc
    def _results():
        _saved()
        req(_ok() and "range" in input and input.range())
        d0, d1 = input.range()
        req(d0 and d1)
        db = get_session()
        try:
            return data_health.check_range(db, d0, d1)
        finally:
            db.close()

    @render.ui
    def summary():
        if not _ok():
            return None
        res = _results()
        if not res:
            return ui_helpers.empty_state("No tracked games in this range.")
        avg = sum(r["score"] for r in res) / len(res)
        totals = {}
        for r in res:
            for c in r["checks"]:
                t = totals.setdefault(c["key"], [0, 0])
                t[0] += c["missing"]
                t[1] += c["total"]
        worst = sorted(((k, v) for k, v in totals.items() if v[0]), key=lambda kv: -kv[1][0] * data_health.CHECK_META[kv[0]][2])
        cards = [
            {"label": "Charting complete", "value": f"{avg:.0f}%", "delta": f"{len(res)} games", "delta_positive": avg >= data_health.GREEN},
            {"label": "Games to fix", "value": str(sum(1 for r in res if r["grade"] != "green")),
             "delta": f"{sum(1 for r in res if r['grade'] == 'red')} red"},
        ]
        trend = data_health.weekly_trend(res)
        trend_rows = [{"Week of": w.strftime("%b %d"), "Games": n, "Complete": f"{s:.0f}%"} for w, s, n in trend]
        top = [ui.tags.li(ui.strong(data_health.CHECK_META[k][0]), f": {v[0]} of {v[1]} -- ", data_health.CHECK_META[k][1])
               for k, v in worst[:4]]
        return ui.div(
            ui_helpers.render_kpi_cards(cards),
            ui.layout_columns(
                ui_helpers.card(ui.tags.ul(*top) if top else ui.p("Nothing missing in this range.", class_="text-muted"),
                                title="Biggest gaps (all games in range)"),
                ui_helpers.card(ui_helpers.render_dict_table(trend_rows), title="By week"),
                col_widths=[7, 5],
            ),
        )

    @render.ui
    def games():
        if not _ok():
            return None
        res = _results()
        if not res:
            return None
        only = input.only_problems() if "only_problems" in input else True
        blocks = []
        for r in res:
            g = r["game"]
            issues = [c for c in r["checks"] if c["missing"]]
            if only and not issues:
                continue
            color = GRADE_COLORS[r["grade"]]
            head = ui.div(
                ui.span(f"{r['score']:.0f}%", style=f"background:{color};color:#fff;font-weight:700;border-radius:10px;padding:2px 10px;margin-right:10px;"),
                ui.strong(game_label(g)),
                ui.span(f"  ·  {r['pitches']} pitches  ·  {g.status}", class_="text-muted small"),
                ui.input_action_button(f"fix_{g.game_id}", "Fix in Game Tracking", class_="btn-sm btn-outline-light",
                                       style="margin-left:auto;"),
                style="display:flex;align-items:center;gap:6px;",
            )
            rows = [{"Problem": c["label"], "Missing": f"{c['missing']} of {c['total']}" if c["key"] != "final" else "—",
                     "Why it matters": c["why"]} for c in issues]
            body = ui_helpers.render_dict_table(rows) if rows else ui.p("All checks pass.", class_="text-muted small")
            blocks.append(ui_helpers.card(head, ui.div(body, style="margin-top:8px;"), _box_line(r)))
        if not blocks:
            return ui.p("Every game in this range passes all checks.", class_="text-muted", style="margin-top:12px;")
        return ui.div(*blocks, style="margin-top:12px;display:flex;flex-direction:column;gap:12px;")

    # ---- Box score check ------------------------------------------------
    def _box_line(r):
        if r["game"].is_intrasquad:
            return None
        if not r["has_box"]:
            return ui.p("No official box score entered yet -- add it in Box score check above.",
                        class_="text-muted small", style="margin:6px 0 0;")
        bad = [x for x in r["box_rows"] if not x["ok"]]
        if not bad:
            return ui.p("✓ Charting matches the official box score.", class_="small",
                        style="margin:6px 0 0;color:#2E9C62;")
        txt = ", ".join(f"{'Pitt State' if x['side'] == 'our' else 'Opponent'} {x['label']} "
                        f"charted {x['charted']} vs official {x['official']}" for x in bad)
        return ui.p("Box score off: " + txt, class_="small", style="margin:6px 0 0;color:#D94F3D;")

    def _box_games():
        return [r for r in _results() if not r["game"].is_intrasquad]

    @render.ui
    def box_card():
        if not _ok():
            return None
        res = _box_games()
        if not res:
            return None
        choices = {str(r["game"].game_id): ("✓ " if r["has_box"] else "") + game_label(r["game"]) for r in res}
        sel = input.box_game() if "box_game" in input and input.box_game() in choices else next(iter(choices))
        head = ui.tags.tr(ui.tags.th(""), *[ui.tags.th(box_score.LABELS[k], style="text-align:center;") for k in box_score.STATS])
        # Re-renders whenever the game changes (reads input.box_game above),
        # so the boxes always show that game's saved line.
        cur = next(r for r in res if str(r["game"].game_id) == sel)
        saved = {(x["side"], x["stat"]): x["official"] for x in cur["box_rows"]}

        def row(side, name):
            return ui.tags.tr(ui.tags.td(ui.strong(name)), *[
                ui.tags.td(ui.input_numeric(f"box_{side}_{k}", None, value=saved.get((side, k)), min=0, step=1,
                                            width="70px"))
                for k in box_score.STATS])
        form = ui.tags.table(head, row("our", "Pitt State"), row("opp", "Opponent"), class_="gbo-box-form")
        return ui_helpers.card(
            ui.p("Type the official line (R / H / E / BB / K) from the final box score. E = errors that team made "
                 "in the field. GBO checks it against what the charting adds up to.", class_="text-muted small"),
            ui.layout_columns(
                ui.div(ui.input_select("box_game", "Game", choices=choices, selected=sel), form,
                       ui.input_action_button("box_save", "Save box score", class_="btn-sm btn-primary",
                                              style="margin-top:6px;")),
                ui.output_ui("box_compare"),
                col_widths=[6, 6],
            ),
            ui.tags.style(".gbo-box-form td{padding:2px 6px;vertical-align:middle}.gbo-box-form .form-group{margin:0}"),
            title="Box score check",
        )

    @reactive.effect
    @reactive.event(input.box_save)
    def _save_box():
        if not _ok() or "box_game" not in input:
            return
        vals = {}
        for side in box_score.SIDES:
            for k in box_score.STATS:
                v = input[f"box_{side}_{k}"]()
                vals[f"{side}_{k}"] = int(v) if v not in (None, "") else None
        if all(v is None for v in vals.values()):
            ui.notification_show("Type at least one number first.", type="warning")
            return
        db = get_session()
        try:
            box_score.save(db, int(input.box_game()), vals, app_state.user_id())
        except Exception as e:
            db.rollback()
            ui.notification_show(f"Couldn't save the box score: {e}", type="error")
            return
        finally:
            db.close()
        ui.notification_show("Box score saved.", type="message")
        _saved.set(_saved() + 1)

    @render.ui
    def box_compare():
        if not _ok() or "box_game" not in input or not input.box_game():
            return None
        gid = int(input.box_game())
        r = next((x for x in _box_games() if x["game"].game_id == gid), None)
        if r is None:
            return None
        db = get_session()
        try:
            charted = box_score.charted_line(db, gid)
        finally:
            db.close()
        if not r["has_box"]:
            rows = [{"": "Pitt State" if s == "our" else "Opponent",
                     **{box_score.LABELS[k]: charted[s][k] for k in box_score.STATS}} for s in box_score.SIDES]
            return ui.div(ui.strong("What the charting adds up to"), ui_helpers.render_dict_table(rows),
                          ui.p("Save the official line to compare.", class_="text-muted small"))
        cells = {(x["side"], x["stat"]): x for x in r["box_rows"]}

        def td(side, k):
            x = cells.get((side, k))
            if x is None:
                return ui.tags.td(str(charted[side][k]), style="text-align:center;color:#888;")
            if x["ok"]:
                return ui.tags.td(f"{x['charted']} ✓", style="text-align:center;color:#2E9C62;")
            return ui.tags.td(f"{x['charted']} (box {x['official']})",
                              style="text-align:center;color:#D94F3D;font-weight:700;")
        head = ui.tags.tr(ui.tags.th("Charted"), *[ui.tags.th(box_score.LABELS[k], style="text-align:center;")
                                                   for k in box_score.STATS])
        body = [ui.tags.tr(ui.tags.td(ui.strong("Pitt State" if s == "our" else "Opponent")),
                           *[td(s, k) for k in box_score.STATS]) for s in box_score.SIDES]
        bad = sum(1 for x in r["box_rows"] if not x["ok"])
        msg = (ui.p("Everything matches.", style="color:#2E9C62;margin-top:6px;") if not bad else
               ui.p(f"{bad} number{'s' if bad != 1 else ''} off -- open the game in Game Tracking and look for a "
                    "missing PA, a wrong result, or a run that didn't get credited.", class_="small",
                    style="color:#D94F3D;margin-top:6px;"))
        return ui.div(ui.tags.table(head, *body, class_="table table-sm"), msg)

    # One observer for every "Fix" button (ids are per game).
    _seen = {}

    @reactive.effect
    def _fix_clicks():
        if not _ok():
            return
        res = _results()
        for r in res:
            gid = r["game"].game_id
            key = f"fix_{gid}"
            if key not in input:
                continue
            v = input[key]()
            if not v:
                _seen[key] = 0      # button re-rendered -> reset
                continue
            if v != _seen.get(key, 0):
                _seen[key] = v
                app_state.deep_link_game_id.set(gid)
                ui.update_navs("main_nav", selected="Game Tracking", session=session.root_scope())


    # ---- Rapsodo readings (Oct 2026, analytics/rapsodo_check.py) --------
    @reactive.calc
    def _raps_check():
        req(_ok() and "range" in input and input.range())
        d0, d1 = input.range()
        req(d0 and d1)
        from datetime import datetime, time
        from sqlalchemy.orm import joinedload
        from models import RapsodoPitch, Player
        db = get_session()
        try:
            lo, hi = datetime.combine(d0, time.min), datetime.combine(d1, time.max)
            in_range = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
                        .filter(RapsodoPitch.pitch_date >= lo, RapsodoPitch.pitch_date <= hi).all())
            pids = {p.player_id for p in in_range}
            allp = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
                    .filter(RapsodoPitch.player_id.in_(pids)).all()) if pids else []
            names = {pl.player_id: f"{pl.first_name} {pl.last_name}" for pl in db.query(Player).filter(Player.player_id.in_(pids)).all()} if pids else {}
            return rapsodo_check.check(in_range, allp), len(in_range), names
        finally:
            db.close()

    @render.ui
    def rapsodo():
        if not _ok():
            return None
        rows, n, names = _raps_check()
        intro = ui.p(
            "Readings that look off, by outing. \"Shifted\" = a pitch type that day sat more than "
            f"{rapsodo_check.Z_FLAG} SD from that pitcher's own normal (needs {rapsodo_check.MIN_NORM}+ readings of it "
            "on file) -- usually a misread or a mislabeled pitch, sometimes a real change. Bad readings skew Stuff+, "
            "IVB over expected and the classifiers, so fix the label (Fastball Shape Check / Pitch Type Check) or "
            "check the setup.", class_="text-muted small", style="margin-top:10px;")
        if not n:
            return ui.div(intro, ui_helpers.empty_state("No Rapsodo readings in this range."))
        if not rows:
            return ui.div(intro, ui.p(f"All {n} readings in this range look normal.", class_="text-muted"))
        table = [{
            "Date": r["date"].strftime("%b %-d") if r["date"] else "—", "Pitcher": names.get(r["player_id"], "—"),
            "Outing": r["kind"], "Readings": r["n"], "What looks off": "; ".join(r["issues"]),
        } for r in rows]
        bp = {str(r["bullpen_id"]): f"{r['date'].strftime('%b %-d') if r['date'] else '—'} -- {names.get(r['player_id'], '—')}"
              for r in rows if r["bullpen_id"] is not None}
        opener = ui.div(
            ui.input_select("dh_bp_pick", "Open a flagged bullpen", choices=bp),
            ui.input_action_button("dh_bp_open", "Open in Bullpen Dashboard", class_="btn-sm btn-outline-light"),
            style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap;margin-top:8px;",
        ) if bp else None
        return ui.div(
            intro,
            ui_helpers.render_kpi_cards([
                {"label": "Readings checked", "value": str(n)},
                {"label": "Outings flagged", "value": str(len(rows))},
                {"label": "Shifted pitch types", "value": str(sum(1 for r in rows for i in r["issues"] if " SD)" in i))},
            ]),
            ui_helpers.render_dict_table(table),
            opener,
        )

    @reactive.effect
    @reactive.event(input.dh_bp_open)
    def _open_bp():
        if not _ok() or "dh_bp_pick" not in input:
            return
        app_state.deep_link_bullpen_id.set(int(input.dh_bp_pick()))
        ui.update_navs("main_nav", selected="Bullpen Dashboard", session=session.root_scope())


    # ---- Metric check (Oct 2026, analytics/metric_check.py) ------------
    def _scatter_svg(points, ylab):
        """Tiny scatter: bullpen Stuff+ (x) vs game stat (y)."""
        if not points:
            return ""
        W, H, L, R, T, B = 420, 220, 44, 12, 12, 34
        xs = [p[1] for p in points]
        ys = [p[2] for p in points]
        x0, x1 = min(xs) - 2, max(xs) + 2
        y0, y1 = max(0, min(ys) - 5), max(ys) + 5

        def X(v):
            return L + (W - L - R) * (v - x0) / ((x1 - x0) or 1)

        def Y(v):
            return T + (H - T - B) * (1 - (v - y0) / ((y1 - y0) or 1))
        out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Bullpen Stuff+ vs {ylab}">']
        for v in (y0, (y0 + y1) / 2, y1):
            out.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" class="grid"/>'
                       f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" text-anchor="end" class="axis">{v:.0f}%</text>')
        for v in (x0, (x0 + x1) / 2, x1):
            out.append(f'<text x="{X(v):.1f}" y="{H - 16}" text-anchor="middle" class="axis">{v:.0f}</text>')
        out.append(f'<text x="{(L + W - R) / 2:.0f}" y="{H - 2}" text-anchor="middle" class="axis">bullpen Stuff+</text>')
        for _pid, x, y in points:
            out.append(f'<g class="pt"><title>Stuff+ {x:.0f}, {ylab} {y:.0f}%</title>'
                       f'<circle cx="{X(x):.1f}" cy="{Y(y):.1f}" r="5" class="dot"/></g>')
        out.append("</svg>")
        return "".join(out)

    @render.ui
    def metric_check():
        if not _ok():
            return None
        req("range" in input and input.range())
        d0, d1 = input.range()
        req(d0 and d1)
        from datetime import datetime, time
        from sqlalchemy.orm import joinedload
        from models import RapsodoPitch, Player, GamePitch
        from analytics import trends, profile_queries, command_metrics, sequencing
        from analytics.pitch_grading import stuff_plus
        db = get_session()
        try:
            team = trends.team_pitches_in_range(db, d0, d1, pitching=True)
            lo, hi = datetime.combine(d0, time.min), datetime.combine(d1, time.max)
            raps = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
                    .filter(RapsodoPitch.pitch_date >= lo, RapsodoPitch.pitch_date <= hi).all())
            models = profile_queries.team_stuff_plus_baselines(db)
            throws = {pl.player_id: pl.throws for pl in db.query(Player).all()}
            all_cmd = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
            cmd_base = command_metrics.team_command_plus_baselines(command_metrics.game_pitches_command_view(all_cmd, None))
        finally:
            db.close()

        game = {}
        for p in sorted(team, key=lambda p: (p.game_id, p.pitch_sequence)):
            pid = sequencing.pitcher_of(p)
            if pid is not None:
                game.setdefault(pid, []).append(p)
        rows = []
        for name, fn in mcheck.GAME_STATS:
            r = mcheck.split_half(game, fn)
            rows.append((name, "charted game pitches", r))

        stuff_by = {}
        bp_stuff = {}
        for p in sorted(raps, key=lambda p: (p.pitch_date or datetime.min, p.pitch_number or 0)):
            lab = p.pitch_type.type_name if p.pitch_type else None
            v = stuff_plus(p, models.get(lab)) if lab else None
            if v is None:
                continue
            stuff_by.setdefault(p.player_id, []).append(v)
            if p.bullpen_id is not None:
                bp_stuff.setdefault(p.player_id, []).append(v)
        rows.insert(0, ("Stuff+", "Rapsodo readings", mcheck.split_half(
            stuff_by, lambda vs: sum(vs) / len(vs) if vs else None)))
        cmd = {pid: command_metrics.game_pitches_command_view(ps, throws.get(pid)) for pid, ps in game.items()}
        rows.insert(1, ("Command+", "game pitches with a called spot", mcheck.split_half(
            cmd, lambda ps: command_metrics.session_command_plus(ps, cmd_base))))

        def f2(v):
            return f"{v:.2f}" if v is not None else "—"
        table = [{"Stat": n, "From": src, "Pitchers": r["n_pitchers"], "Half vs half r": f2(r["r"]),
                  "Full-sample reliability": f2(r["full"]), "Read": r["read"]} for n, src, r in rows]

        bg = mcheck.bullpen_to_game({pid: (sum(v) / len(v), len(v)) for pid, v in bp_stuff.items()}, game)
        bg_cards = []
        for name, d in bg.items():
            if d["r"] is None:
                txt = (f"Needs {mcheck.MIN_PITCHERS}+ pitchers with {mcheck.MIN_BP}+ bullpen Stuff+ readings "
                       f"and {mcheck.MIN_GAME}+ game pitches -- {d['n']} so far.")
            else:
                strength = "strong" if abs(d["r"]) >= 0.5 else ("some" if abs(d["r"]) >= 0.3 else "little")
                txt = (f"r = {d['r']:.2f} across {d['n']} pitchers -- {strength} relationship "
                       f"{'(higher bullpen Stuff+, higher game ' + name + ')' if d['r'] > 0 else '(goes the wrong way)'}.")
            bg_cards.append(ui_helpers.card(ui.p(txt, class_="small"), ui.HTML(_scatter_svg(d["points"], name)),
                                            title=f"Bullpen Stuff+ → game {name}"))
        return ui.div(
            ui.p("Is each stat telling us about the pitcher, or mostly luck at our sample size? Each pitcher's pitches "
                 "are split into odd and even (in order thrown), the stat is figured on both halves, and the halves "
                 "are compared across the staff -- then stepped up to the full sample (Spearman-Brown). "
                 f"{mcheck.STABLE}+ = stable, {mcheck.GETTING}+ = getting there, lower = mostly noise so far. "
                 f"Pitchers need {mcheck.MIN_HALF}+ pitches per half. Uses the date range above -- a wider range "
                 "gives a truer answer.", class_="text-muted small", style="margin-top:10px;"),
            ui_helpers.render_dict_table(table),
            ui.p(ui.strong("Does bullpen stuff show up in games?"), style="margin:14px 0 4px;"),
            ui.p("Each dot is a pitcher: his average bullpen Stuff+ against his game rate. If Stuff+ is measuring "
                 "something real, the dots should rise left to right.", class_="text-muted small"),
            ui.layout_columns(*bg_cards, col_widths=[6, 6]),
        )
