"""
GBO -- Pitch Calling Cards (Oct 2026, Ryker: no phone/tablet in the
dugout -- the pitching coach carries a pocket card made before the game).

Build tab: pick the game, the expected lineup (opponent roster, or our own
hitters for an intrasquad) and the pitchers who might throw -> one pocket
card per pitcher of Level-Pitch-Zone calls (e.g. 214) by hitter and count,
editable in place, saved (models.PitchCard) and printed one per pocket-size
page (5.5 x 4.25 in). Card vs Calls tab: after the game, every
charted call (pitch type + intended spot) against that pitcher's card.
Data: analytics/pitch_card.py; card HTML: visualizations/pitch_card_sheet.py.
"""

from datetime import date, timedelta

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from models import Game, GameLineupSlot, OpponentLineupSlot, OpponentPlayer, Player, PitcherAvailability
from analytics import pitch_card as pc
from visualizations.pitch_card_sheet import CARD_CSS, card_html
import ui_helpers

VIEW_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")
EDIT_ROLES = ("Administrator", "Head Coach", "Coach", "Data Analyst")

PRINT_JS = """
(function(){
  var cards = document.querySelectorAll('#gbo-pcards .gbo-pcard');
  if(!cards.length){ return; }
  var w = window.open('', '_blank');
  if(!w){ alert('Allow pop-ups for this site to print the cards.'); return; }
  var css = document.getElementById('gbo-pcard-css').innerHTML;
  var html = Array.prototype.map.call(cards, function(c){ return c.outerHTML; }).join('');
  w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>Pitch Calling Cards</title><style>'
    + css + '@page{size:5.5in 4.25in;margin:0} body{margin:0;background:#fff} .gbo-pcard{box-shadow:none;margin:0}'
    + ' [contenteditable]{background:none!important}</style></head><body>' + html + '</body></html>');
  w.document.close(); w.focus();
  setTimeout(function(){ w.print(); }, 300);
})();
"""

SAVE_JS = """
(function(ns){
  var out = [];
  document.querySelectorAll('#gbo-pcards .gbo-pcard').forEach(function(card){
    var cells = [];
    card.querySelectorAll('[data-hk]').forEach(function(el){
      cells.push({hk: el.getAttribute('data-hk'), g: el.getAttribute('data-g'), k: el.getAttribute('data-k'),
                  v: (el.innerText || '').trim()});
    });
    out.push({pid: parseInt(card.getAttribute('data-pid')), cells: cells});
  });
  Shiny.setInputValue(ns, JSON.stringify(out), {priority: 'event'});
})('%s');
"""


def _game_label(g):
    opp = (g.opponent_team.team_name if g.opponent_team else
           ("Intrasquad" if g.is_intrasquad else (g.opponent_name or "TBD")))
    return f"{g.game_date.strftime('%-m/%-d')} vs {opp}"


@module.ui
def pitch_cards_ui():
    return ui.div(
        ui.tags.style(CARD_CSS, id="gbo-pcard-css"),
        ui_helpers.page_header("Pitch Calling Cards",
                               "Pocket cards for the pitching coach: Level-Pitch-Zone calls (e.g. 214) by hitter and "
                               "count, built before the game -- and after it, how the calls lined up with the card."),
        ui.navset_tab(
            ui.nav_panel("Build cards", ui.output_ui("controls"), ui.output_ui("cards")),
            ui.nav_panel("Card vs Calls", ui.output_ui("cmp_controls"), ui.output_ui("cmp")),
            id="pc_tab",
        ),
    )


@module.server
def pitch_cards_server(input, output, session, app_state):
    built = reactive.Value(None)      # {"game_id", "label", "cards": [card]}
    tick = reactive.Value(0)

    def _ok():
        return app_state.is_authenticated() and app_state.role_name() in VIEW_ROLES

    def _can_edit():
        return app_state.is_authenticated() and app_state.role_name() in EDIT_ROLES

    def _table_ready(db):
        from sqlalchemy import inspect as sa_inspect
        try:
            return sa_inspect(db.get_bind()).has_table("pitch_cards")
        except Exception:
            return False

    @render.ui
    def controls():
        if not app_state.is_authenticated():
            return None
        if not _ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        db = get_session()
        try:
            today = date.today()
            games = (db.query(Game).options(joinedload(Game.opponent_team))
                     .filter(Game.game_date >= today - timedelta(days=60)).order_by(Game.game_date).all())
            if not games:
                return ui_helpers.empty_state("No games in the last 60 days or upcoming -- create one in Game Tracking.")
            upcoming = [g for g in games if g.game_date >= today]
            default = (upcoming[0] if upcoming else games[-1]).game_id
            choices = {str(g.game_id): _game_label(g) + (" (upcoming)" if g.game_date >= today else "")
                       for g in reversed(games)}
            return ui.div(
                ui.input_select("game", "Game", choices=choices, selected=str(default)),
                ui.output_ui("pickers"),
            )
        finally:
            db.close()

    @render.ui
    def pickers():
        req(_ok() and "game" in input and input.game())
        db = get_session()
        try:
            g = db.query(Game).filter(Game.game_id == int(input.game())).first()
            if g is None:
                return None
            hitters, default_h = _hitter_choices(db, g)
            pitchers = (db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True))
                        .order_by(Player.last_name, Player.first_name).all())
            pchoices = {str(p.player_id): f"{p.last_name}, {p.first_name} ({p.throws or '?'})" for p in pitchers}
            default_p = _default_pitchers(db, g, pitchers)
            return ui.div(
                ui.layout_columns(
                    ui.input_selectize("hitters", "Expected lineup (in batting order)", choices=hitters,
                                       selected=default_h, multiple=True, options={"plugins": ["remove_button"]}),
                    ui.input_selectize("pitchers", "Pitchers who might throw", choices=pchoices, selected=default_p,
                                       multiple=True, options={"plugins": ["remove_button"]}),
                    col_widths=[6, 6]),
                ui.div(ui.input_action_button("build", "Build cards", class_="btn-primary btn-sm"),
                       ui.span(" Rebuilding replaces saved edits for these pitchers.", class_="text-muted small"),
                       style="margin:4px 0 12px;"),
            )
        finally:
            db.close()

    def _hitter_choices(db, g):
        if g.opponent_team_id:
            roster = (db.query(OpponentPlayer).filter(OpponentPlayer.team_id == g.opponent_team_id)
                      .order_by(OpponentPlayer.player_name).all())
            choices = {f"opp:{o.opponent_player_id}": f"{o.player_name} ({o.bats or '?'})" for o in roster}
            last = (db.query(OpponentLineupSlot).join(Game, Game.game_id == OpponentLineupSlot.game_id)
                    .filter(Game.opponent_team_id == g.opponent_team_id)
                    .order_by(Game.game_date.desc(), OpponentLineupSlot.batting_order).all())
            default, seen_game = [], None
            for s in last:
                if seen_game is None:
                    seen_game = s.game_id
                if s.game_id != seen_game:
                    break
                default.append(f"opp:{s.opponent_player_id}")
            if not default:      # no lineup charted vs them yet: first 9 non-pitchers on their roster
                default = [f"opp:{o.opponent_player_id}" for o in roster
                           if (o.position or "").upper() not in ("P", "RHP", "LHP", "PITCHER")][:9]
            return choices, default
        hitters = (db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all())
        choices = {f"our:{p.player_id}": f"{p.last_name}, {p.first_name} ({p.bats or '?'})" for p in hitters
                   if not p.is_pitcher}
        slots = (db.query(GameLineupSlot).filter(GameLineupSlot.game_id == g.game_id)
                 .order_by(GameLineupSlot.squad, GameLineupSlot.batting_order).all())
        default = [f"our:{s.player_id}" for s in slots if f"our:{s.player_id}" in choices][:9]
        return choices, default

    def _default_pitchers(db, g, pitchers):
        out = []
        if g.starting_pitcher_id:
            out.append(str(g.starting_pitcher_id))
        held = {a.player_id for a in db.query(PitcherAvailability).filter(
            PitcherAvailability.kind == "status", PitcherAvailability.status == "Hold").all()
                if (a.start_date is None or a.start_date <= g.game_date)
                and (a.end_date is None or a.end_date >= g.game_date)}
        return out or [str(p.player_id) for p in pitchers if p.player_id not in held][:6]

    def _hitter_rows(db, keys):
        rows = []
        for k in keys:
            kind, sid = k.split(":")
            if kind == "opp":
                o = db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id == int(sid)).first()
                if o:
                    rows.append({"key": ("opp", o.opponent_player_id), "name": o.player_name, "bats": o.bats})
            else:
                p = db.query(Player).filter(Player.player_id == int(sid)).first()
                if p:
                    rows.append({"key": ("our", p.player_id), "name": f"{p.first_name[0]}. {p.last_name}", "bats": p.bats})
        return rows

    def _model(db):
        from models import RapsodoPitch, PitchType
        pitches = pc.load_pitches(db)
        raps = {}
        for pid, lab in (db.query(RapsodoPitch.player_id, PitchType.type_name)
                         .join(PitchType, PitchType.pitch_type_id == RapsodoPitch.pitch_type_id).all()):
            raps.setdefault(pid, []).append(lab)
        return pc.Model(pitches), pc.usage(pitches, raps), pitches

    @reactive.effect
    @reactive.event(input.build)
    def _build():
        if not _ok():
            return
        db = get_session()
        try:
            g = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == int(input.game())).first()
            hitters = _hitter_rows(db, list(input.hitters() or []))
            pids = [int(x) for x in (input.pitchers() or [])]
            if g is None or not pids:
                ui.notification_show("Pick a game and at least one pitcher.", type="warning")
                return
            model, use, _p = _model(db)
            # Oct 2026 (Paradigm, "The Angle Advantage"): each pitch's VAAA /
            # HAAAA nudges where it's called -- analytics/pitch_card.angle_bonus.
            try:
                from analytics import approach_angles as aa
                profiles = aa.staff_profiles(db)["profiles"]
            except Exception:
                profiles = {}
            cards = []
            for pid in pids:
                p = db.query(Player).filter(Player.player_id == pid).first()
                if p is not None:
                    angles = {d: (v, (h if p.throws == "R" else -h) if h is not None else None)
                              for d, (v, h) in aa.digit_angles(profiles.get(pid), pc.PITCH_DIGIT).items()} \
                        if profiles.get(pid) else None
                    cards.append(pc.build_card(model, p, hitters, use, angles))
            built.set({"game_id": g.game_id, "label": _game_label(g), "cards": cards})
            if _can_edit() and _table_ready(db):
                _save_cards(db, g.game_id, cards)
        finally:
            db.close()

    def _save_cards(db, game_id, cards):
        from models import PitchCard
        for c in cards:
            row = db.query(PitchCard).filter(PitchCard.game_id == game_id, PitchCard.pitcher_id == c["pitcher_id"]).first()
            if row is None:
                row = PitchCard(game_id=game_id, pitcher_id=c["pitcher_id"], data=c)
                db.add(row)
            row.data = c
            row.updated_by_user_id = app_state.user_id()
        db.commit()

    @reactive.effect
    def _load_saved():
        """Switching games shows that game's saved cards, if any."""
        req(_ok() and "game" in input and input.game())
        tick()
        db = get_session()
        try:
            if not _table_ready(db):
                return
            from models import PitchCard
            g = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == int(input.game())).first()
            rows = db.query(PitchCard).filter(PitchCard.game_id == int(input.game())).all()
            with reactive.isolate():
                cur = built.get()
            if rows and g is not None and (cur is None or cur["game_id"] != g.game_id):
                built.set({"game_id": g.game_id, "label": _game_label(g), "cards": [r.data for r in rows]})
            elif not rows and cur is not None and g is not None and cur["game_id"] != g.game_id:
                built.set(None)
        finally:
            db.close()

    @render.ui
    def cards():
        if not _ok():
            return None
        b = built.get()
        if not b or not b["cards"]:
            return ui.p("Pick the lineup and pitchers, then Build cards.", class_="text-muted small")
        db = get_session()
        try:
            ready = _table_ready(db)
        finally:
            db.close()
        edit = _can_edit()
        save_btn = (ui.tags.button("Save edits", type="button", class_="btn btn-sm btn-outline-light",
                                   onclick=SAVE_JS % session.ns("save_edits"))
                    if edit and ready else None)
        note = (None if ready else ui.p("Run migrations/migrate_pitch_cards.py once to save cards and edits -- you can "
                                        "still edit and print.", class_="text-muted small"))
        return ui.div(
            ui.div(ui.tags.button("Print cards", type="button", class_="btn btn-sm btn-primary", onclick=PRINT_JS),
                   save_btn, style="display:flex;gap:8px;margin-bottom:8px;"),
            note,
            ui.p("Click any code to change it (3 digits: Level-Pitch-Zone). Each card prints on its own 5.5 x 4.25 in "
                 "page -- a quarter of a letter sheet; set the printer to that paper size or print 'fit to page' and "
                 "trim. Big code = the call, small = backup. 'Any RHH / LHH' rows cover a hitter who isn't on the card.",
                 class_="text-muted small"),
            ui.div(*[ui.HTML(card_html(c, b["label"], editable=edit)) for c in b["cards"]], id="gbo-pcards",
                   style="display:flex;flex-wrap:wrap;gap:14px;"),
            ui.p(f"Calls come from {b['cards'][0].get('n', 0):,} charted pitches: what's worked for that pitch type in "
                 "that spot and count across the staff, nudged by this pitcher's own results with it and by the "
                 "hitter's history vs it (when he has 15+ pitches seen). Early-season cards lean on the staff numbers.",
                 class_="text-muted small"),
        )

    @reactive.effect
    @reactive.event(input.save_edits)
    def _save_edits():
        import json
        if not _can_edit():
            return
        b = built.get()
        if not b:
            return
        try:
            edits = json.loads(input.save_edits())
        except ValueError:
            return
        bad = []
        cards = {c["pitcher_id"]: c for c in b["cards"]}
        for e in edits:
            c = cards.get(e["pid"])
            if c is None:
                continue
            for cell in e["cells"]:
                v = cell["v"]
                if v and pc.parse(v) is None:
                    bad.append(v)
                    continue
                if cell["hk"].startswith("gen:"):
                    tgt = c["generic"].setdefault(cell["hk"][4:], {}).setdefault(cell["g"], {})
                else:
                    kind, sid = cell["hk"].split(":")
                    row = next((r for r in c["rows"] if r["key"][0] == kind and str(r["key"][1]) == sid), None)
                    if row is None:
                        continue
                    tgt = row["cells"].setdefault(cell["g"], {})
                tgt[cell["k"]] = v
        db = get_session()
        try:
            _save_cards(db, b["game_id"], list(cards.values()))
        finally:
            db.close()
        built.set({**b, "cards": list(cards.values())})
        msg = "Cards saved." + (f" Skipped {len(bad)} code(s) that aren't 3 digits: {', '.join(bad[:5])}." if bad else "")
        ui.notification_show(msg, type="warning" if bad else "message", duration=6)

    # ---- Card vs Calls --------------------------------------------------------
    @render.ui
    def cmp_controls():
        if not _ok():
            return None
        db = get_session()
        try:
            games = (db.query(Game).options(joinedload(Game.opponent_team))
                     .filter(Game.game_date <= date.today()).order_by(Game.game_date.desc()).limit(40).all())
            if not games:
                return ui_helpers.empty_state("No games yet.")
            return ui.input_select("cmp_game", "Game", choices={"all": "Every game with saved cards", **{
                str(g.game_id): _game_label(g) for g in games}})
        finally:
            db.close()

    @render.ui
    def cmp():
        req(_ok() and "cmp_game" in input and input.cmp_game())
        if input.cmp_game() == "all":
            return _season_cmp()
        gid = int(input.cmp_game())
        db = get_session()
        try:
            from models import PitchCard
            saved = {}
            if _table_ready(db):
                saved = {r.pitcher_id: r.data for r in db.query(PitchCard).filter(PitchCard.game_id == gid).all()}
            model, use, pitches = _model(db)
            game_p = [p for p in pitches if p["game_id"] == gid]
            source = "saved cards"
            if not saved:
                source = "cards rebuilt now (no saved cards for this game)"
                pids = {p["pid"] for p in game_p}
                for pid in pids:
                    pl = db.query(Player).filter(Player.player_id == pid).first()
                    if pl is not None:
                        saved[pid] = pc.build_card(model, pl, [], use)
            res = pc.compare(saved, game_p)
            names = {p.player_id: f"{p.first_name} {p.last_name}" for p in db.query(Player).all()}
        finally:
            db.close()
        if not res["rows"]:
            return ui.p("No charted calls (pitch type + intended spot) by a pitcher with a card in this game.",
                        class_="text-muted small")
        lab = {"match": "Called the card", "pitch": "Same pitch, other spot", "off": "Off the card"}
        summ = []
        for st in ("match", "pitch", "off"):
            s = res["summary"].get(st)
            if not s:
                continue
            f = lambda v, fmt="{:.0f}%": "—" if v is None else fmt.format(v)
            summ.append({"Call": lab[st], "Pitches": s["n"], "Share": f"{100 * s['n'] / len(res['rows']):.0f}%",
                         "Whiff % (of swings)": f(s["whiff_per_swing"]), "Chase %": f(s["chase"]),
                         "Hard contact %": f(s["hard"]), "RV/100 (ours)": f(s["rv100"], "{:+.2f}")})
        per = {}
        for r in res["rows"]:
            d = per.setdefault(r["pid"], {"match": 0, "pitch": 0, "off": 0})
            d[r["status"]] += 1
        prow = [{"Pitcher": names.get(pid, pid), "Card": d["match"], "Same pitch": d["pitch"], "Off": d["off"],
                 "Card %": f"{100 * d['match'] / sum(d.values()):.0f}%"} for pid, d in per.items()]
        detail = [{"Pitcher": names.get(r["pid"], r["pid"]), "Count group": r["group"], "Called": r["called"],
                   "Card": r["card"], "Result": r["outcome"] or "—",
                   "Match": {"match": "✓", "pitch": "pitch", "off": "—"}[r["status"]]} for r in res["rows"]]
        return ui.div(
            ui.p(f"Compared against {source}. A call = the charted pitch type plus its intended spot, turned into the "
                 "same Level-Pitch-Zone code. RV/100 is on our side (+ = good for us). One game is a handful of "
                 "pitches -- the season trend is what tells you whether to trust the card.", class_="text-muted small"),
            ui_helpers.card(ui_helpers.render_dict_table(summ), title="Results by how the call lined up"),
            ui_helpers.card(ui_helpers.render_dict_table(prow), title="By pitcher"),
            ui.accordion(ui.accordion_panel("Every call", ui_helpers.render_dict_table(detail)), open=False),
        )

    def _season_cmp():
        db = get_session()
        try:
            if not _table_ready(db):
                return ui.p("Season view needs saved cards -- run migrations/migrate_pitch_cards.py.", class_="text-muted small")
            from models import PitchCard
            saved = db.query(PitchCard).all()
            pitches = pc.load_pitches(db)
        finally:
            db.close()
        by_game = {}
        for r in saved:
            by_game.setdefault(r.game_id, {})[r.pitcher_id] = r.data
        rows = []
        for gid, cards in by_game.items():
            rows += pc.compare(cards, [p for p in pitches if p["game_id"] == gid])["rows"]
        if not rows:
            return ui.p("No charted calls in games with saved cards yet.", class_="text-muted small")
        summ = pc.summarize(rows)
        lab = {"match": "Called the card", "pitch": "Same pitch, other spot", "off": "Off the card"}
        f = lambda v, fmt="{:.0f}%": "—" if v is None else fmt.format(v)
        table = [{"Call": lab[st], "Pitches": s["n"], "Share": f"{100 * s['n'] / len(rows):.0f}%",
                  "Whiff % (of swings)": f(s["whiff_per_swing"]), "Chase %": f(s["chase"]),
                  "Hard contact %": f(s["hard"]), "RV/100 (ours)": f(s["rv100"], "{:+.2f}")}
                 for st, s in ((k, summ.get(k)) for k in ("match", "pitch", "off")) if s]
        return ui.div(
            ui.p(f"{len(by_game)} game{'s' if len(by_game) != 1 else ''} with saved cards, {len(rows)} charted calls. "
                 "If 'Called the card' keeps beating 'Off the card' on RV/100 and whiffs, the card is earning its spot "
                 "in the pocket.", class_="text-muted small"),
            ui_helpers.card(ui_helpers.render_dict_table(table), title="Season: results by how the call lined up"),
        )

