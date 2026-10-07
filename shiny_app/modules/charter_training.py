"""
GBO -- Charter Training page (Oct 2026, from Columbia SABRLions' "Building
a Trackman Team"; Ryker approved; staff only, under Game Operations).

Two tabs:
  Arsenal cards  one card per pitcher -- each pitch type's velo range,
                 ride, arm-side run, spin and spin direction, plus a small
                 movement plot. A cheat sheet to keep open while charting.
  Pitch ID quiz  a real Rapsodo reading's numbers; pick the pitch type.
                 "Pitcher named" (you know whose arsenal) or "pitcher
                 hidden" (league-wide shapes). Score / streak for this
                 visit only -- nothing is saved (Ryker's call).
Data helpers: analytics/charter_training.py.
"""

import random
from datetime import datetime, timedelta
from html import escape

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, RapsodoPitch
from analytics import charter_training as ct
from analytics.bullpen_metrics import pitch_type_label
from pitch_type_config import get_pitch_color
import ui_helpers

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
LOOKBACK_DAYS = 400

CSS = """
.gbo-ct-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
.gbo-ct-q { border: 1px solid var(--gbo-border); border-radius: 12px; padding: 16px 18px; background: var(--gbo-bg-card); }
.gbo-ct-q .nums { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 10px; margin: 10px 0; }
.gbo-ct-q .nums div { font-size: .72rem; text-transform: uppercase; letter-spacing: .06em; color: var(--gbo-text-muted); }
.gbo-ct-q .nums b { display: block; font-size: 1.4rem; color: var(--gbo-text); letter-spacing: 0; text-transform: none; }
.gbo-ct-right { color: var(--gbo-status-good); font-weight: 700; }
.gbo-ct-wrong { color: var(--gbo-status-flag); font-weight: 700; }
"""


def _movement_svg(rows):
    W, H, L, B = 220, 200, 26, 22
    x0, x1, y0, y1 = -22, 22, -20, 26

    def X(v):
        return L + (W - L - 6) * (v - x0) / (x1 - x0)

    def Y(v):
        return 6 + (H - B - 6) * (1 - (v - y0) / (y1 - y0))
    out = [f'<svg viewBox="0 0 {W} {H}" class="gbo-progress-svg" role="img" aria-label="Movement by pitch type" style="max-width:240px">']
    out.append(f'<line x1="{X(0):.1f}" x2="{X(0):.1f}" y1="6" y2="{H - B}" class="grid"/>')
    out.append(f'<line x1="{L}" x2="{W - 6}" y1="{Y(0):.1f}" y2="{Y(0):.1f}" class="grid"/>')
    out.append(f'<text x="{L}" y="{H - 6}" class="axis">glove</text><text x="{W - 6}" y="{H - 6}" text-anchor="end" class="axis">arm side</text>')
    out.append('<text x="2" y="12" class="axis">ride</text>')
    for r in rows:
        if r["ivb"] is None or r["run"] is None:
            continue
        c = get_pitch_color(r["label"])
        out.append(f'<g class="pt"><title>{escape(r["label"])}: {r["ivb"]:.1f}" ride, {r["run"]:+.1f}" run</title>'
                   f'<circle cx="{X(max(x0, min(x1, r["run"]))):.1f}" cy="{Y(max(y0, min(y1, r["ivb"]))):.1f}" r="7" '
                   f'style="fill:{c};stroke:var(--gbo-bg-card);stroke-width:2"/></g>')
    out.append("</svg>")
    return "".join(out)


@module.ui
def charter_training_ui():
    return ui.div(
        ui.tags.style(CSS),
        ui_helpers.page_header("Charter Training",
                               "Learn every arm before you chart it -- arsenal cheat sheets and a pitch-ID quiz from our own Rapsodo data."),
        ui.output_ui("gate"),
        ui.navset_tab(
            ui.nav_panel("Arsenal cards", ui.output_ui("cards_controls"), ui.output_ui("cards")),
            ui.nav_panel("Pitch ID quiz", ui.output_ui("quiz_controls"), ui.output_ui("quiz")),
            id="ct_tab",
        ),
    )


@module.server
def charter_training_server(input, output, session, app_state):
    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in STAFF_ROLES

    @render.ui
    def gate():
        if app_state.is_authenticated() and not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        return None

    @reactive.calc
    def _data():
        req(_ok())
        db = get_session()
        try:
            since = datetime.now() - timedelta(days=LOOKBACK_DAYS)
            raps = (db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type))
                    .filter(RapsodoPitch.pitch_date >= since).all())
            pids = {p.player_id for p in raps}
            players = {pl.player_id: pl for pl in db.query(Player).filter(Player.player_id.in_(pids)).all()} if pids else {}
            for pl in players.values():   # detach-safe copies of what we read
                _ = (pl.first_name, pl.last_name, pl.throws, pl.jersey_number)
            return raps, players
        finally:
            db.close()

    def _name(pl):
        num = f" #{pl.jersey_number}" if getattr(pl, "jersey_number", None) else ""
        return f"{pl.last_name}, {pl.first_name}{num}"

    # ---- Arsenal cards ----------------------------------------------------
    @render.ui
    def cards_controls():
        if not _ok():
            return None
        raps, players = _data()
        choices = {"__all__": "All pitchers"} | {str(pid): _name(pl) for pid, pl in sorted(players.items(), key=lambda kv: _name(kv[1]))}
        return ui.div(
            ui.input_select("ct_card_pitcher", "Pitcher", choices=choices),
            ui.p(f"From each pitcher's Rapsodo readings over the last {LOOKBACK_DAYS // 30} months (bullpens + games). "
                 "Run is arm-side + for either hand. Pitch types need 5+ readings to show.", class_="text-muted small"),
            style="margin-top:10px;",
        )

    @render.ui
    def cards():
        if not _ok():
            return None
        req("ct_card_pitcher" in input)
        raps, players = _data()
        sel = input.ct_card_pitcher()
        pids = sorted(players, key=lambda pid: _name(players[pid])) if sel == "__all__" else [int(sel)]
        blocks = []
        for pid in pids:
            pl = players.get(pid)
            if pl is None:
                continue
            rows = ct.arsenal_card([p for p in raps if p.player_id == pid], pl.throws, pitch_type_label)
            if not rows:
                continue

            def f(v, d=1, suf=""):
                return f"{v:.{d}f}{suf}" if v is not None else "—"
            table = [{
                "Pitch": r["label"], "Use": f"{r['usage']:.0f}%",
                "Velo": f"{r['velo_lo']:.0f}–{r['velo_hi']:.0f}" if r["velo_lo"] is not None else "—",
                "Ride": f(r["ivb"], 1, '"'), "Run": f(r["run"], 1, '"'), "Spin": f(r["spin"], 0),
                "Tilt": r["clock"] or "—",
            } for r in rows]
            blocks.append(ui_helpers.card(
                ui.div(ui.HTML(_movement_svg(rows)),
                       ui.div(*[ui.div(ui.span(style=f"display:inline-block;width:10px;height:10px;border-radius:5px;background:{get_pitch_color(r['label'])};margin-right:6px;"),
                                       r["label"], class_="small") for r in rows],
                              style="display:flex;flex-direction:column;gap:4px;justify-content:center;"),
                       style="display:flex;justify-content:center;gap:14px;align-items:center;"),
                ui_helpers.render_dict_table(table),
                title=f"{_name(pl)} ({'LHP' if pl.throws == 'L' else 'RHP'})",
            ))
        if not blocks:
            return ui_helpers.empty_state("No pitcher has 5+ readings of a pitch type yet.")
        return ui.div(*blocks, class_="gbo-ct-cards", style="margin-top:8px;")

    # ---- Pitch ID quiz ------------------------------------------------------
    _score = reactive.value(dict(ct.NEW_SCORE))
    _current = reactive.value(None)       # rapsodo_pitch_id of the question
    _answered = reactive.value(None)      # (picked, correct) once checked
    _rng = random.Random()

    def _pool():
        raps, _players = _data()
        return ct.quiz_pool(raps, pitch_type_label)

    @render.ui
    def quiz_controls():
        if not _ok():
            return None
        raps, players = _data()
        pool_pids = {p.player_id for p in ct.quiz_pool(raps, pitch_type_label)}
        choices = {"__any__": "Any pitcher"} | {str(pid): _name(players[pid]) for pid in sorted(pool_pids, key=lambda i: _name(players[i])) if pid in players}
        return ui.div(
            ui.input_radio_buttons("ct_mode", "Mode", {"named": "Pitcher named", "hidden": "Pitcher hidden"},
                                   selected="named", inline=True),
            ui.input_select("ct_quiz_pitcher", "Pitcher", choices=choices),
            ui.input_action_button("ct_next", "New pitch", class_="btn-primary", width="auto"),
            ui.input_action_button("ct_reset", "Reset score", class_="btn-sm btn-outline-light", width="auto"),
            style="display:flex;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-top:10px;",
        )

    def _new_question():
        pool = _pool()
        sel = input.ct_quiz_pitcher() if "ct_quiz_pitcher" in input else "__any__"
        q = ct.pick(pool, _rng, None if sel == "__any__" else int(sel), exclude=_current())
        _current.set(q.rapsodo_pitch_id if q else None)
        _answered.set(None)

    @reactive.effect
    @reactive.event(input.ct_next)
    def _on_next():
        _new_question()

    @reactive.effect
    @reactive.event(input.ct_reset)
    def _on_reset():
        _score.set(dict(ct.NEW_SCORE))

    @reactive.effect
    @reactive.event(input.ct_check)
    def _on_check():
        if _current() is None or _answered() is not None or "ct_answer" not in input or not input.ct_answer():
            return
        raps, _players = _data()
        q = next((p for p in raps if p.rapsodo_pitch_id == _current()), None)
        if q is None:
            return
        correct = input.ct_answer() == pitch_type_label(q)
        _answered.set((input.ct_answer(), correct))
        _score.set(ct.update_score(_score(), correct))

    @render.ui
    def quiz():
        if not _ok():
            return None
        s = _score()
        pct = f" ({100 * s['right'] / s['total']:.0f}%)" if s["total"] else ""
        score_line = ui.p(ui.strong(f"{s['right']} / {s['total']}"), f" correct{pct} · streak {s['streak']} · best {s['best']}",
                          class_="small", style="margin:10px 0 6px;")
        if _current() is None:
            return ui.div(score_line, ui.p("Press New pitch to start.", class_="text-muted"))
        raps, players = _data()
        q = next((p for p in raps if p.rapsodo_pitch_id == _current()), None)
        if q is None:
            return ui.div(score_line, ui.p("Press New pitch.", class_="text-muted"))
        pl = players.get(q.player_id)
        named = ("ct_mode" not in input) or input.ct_mode() == "named"
        who = (f"{_name(pl)} ({'LHP' if pl.throws == 'L' else 'RHP'})" if named and pl
               else f"Hidden pitcher ({'LHP' if pl and pl.throws == 'L' else 'RHP'})")
        run = ct.arm_run(q, pl.throws if pl else "R")
        nums = ui.div(
            ui.div("Velo", ui.tags.b(f"{float(q.velocity):.1f}")),
            ui.div("Ride (IVB)", ui.tags.b(f"{float(q.vb_spin):+.1f}\"")),
            ui.div("Run (arm side +)", ui.tags.b(f"{run:+.1f}\"" if run is not None else "—")),
            ui.div("Spin", ui.tags.b(f"{float(q.total_spin):.0f}" if q.total_spin is not None else "—")),
            ui.div("Tilt", ui.tags.b(q.spin_direction_clock or "—")),
            ui.div("Spin eff.", ui.tags.b(f"{float(q.spin_efficiency):.0f}%" if q.spin_efficiency is not None else "—")),
            class_="nums",
        )
        opts = ct.choices_for(_pool(), pitch_type_label, q.player_id if named else None)
        ans = _answered()
        if ans is None:
            body = [ui.input_radio_buttons("ct_answer", "What was it?", {o: o for o in opts}, selected=None, inline=True),
                    ui.input_action_button("ct_check", "Check", class_="btn-sm btn-primary")]
        else:
            picked, correct = ans
            truth = pitch_type_label(q)
            body = [ui.p(ui.span("Right" if correct else "Not quite", class_="gbo-ct-right" if correct else "gbo-ct-wrong"),
                         f" -- it was a {truth}" + ("" if correct else f" (you said {picked})") +
                         ("" if named or not pl else f", thrown by {_name(pl)}") +
                         (f" on {q.pitch_date.strftime('%b %-d')}" if q.pitch_date else "") + ".")]
            if pl:
                card = ct.arsenal_card([p for p in raps if p.player_id == q.player_id], pl.throws, pitch_type_label)
                body.append(ui.p("His arsenal: " + " · ".join(
                    f"{r['label']} {r['velo']:.0f} mph, {r['ivb']:+.0f}\" ride, {r['run']:+.0f}\" run"
                    for r in card if r["velo"] is not None and r["ivb"] is not None and r["run"] is not None),
                    class_="text-muted small"))
            body.append(ui.p("Press New pitch for the next one.", class_="text-muted small"))
        return ui.div(
            score_line,
            ui.div(ui.strong(who), nums, *body, class_="gbo-ct-q"),
            ui.p("Answers are the pitch type on file in GBO (the pitcher's own label, checked by the Fastball Shape / "
                 "Pitch Type checks). Score is for this visit only.", class_="text-muted small", style="margin-top:8px;"),
        )
