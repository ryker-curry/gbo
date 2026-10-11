"""
GBO -- Game Tracking > Live Tracking, step-by-step mode for phones and
tablets (Oct 2026, Ryker: "if i click in play then the next thing i see
is contact quality, then batted ball type, then where it went, then ab
outcome, then autosuggest bases/runs scoring and confirm").

One screen at a time, big buttons, Back on every step:

  pitch   call (Level-Zone grid), pitch type, outcome. A pitch that
          doesn't end the at-bat saves on the outcome tap.
  cq      contact quality          (In Play only; Skip)
  bbt     batted ball type          (In Play only; Skip)
  spray   tap where it went         (In Play only; Skip)
  ab      AB outcome                (In Play only)
  result  runners / outs / runs, suggested from the AB outcome and
          editable, then Save. A strikeout, walk or HBP comes straight
          here with the result already picked.

Skipped details show up in the half-inning review and can be filled in
from the Pitch Log later, same as the full form.

The pitch screen and the result screen run in the browser (no round trip
per tap); only the finished choice is sent. Everything goes through one
input, `wiz`, as {a: action, ...}. Saving uses game_tracking's own
_do_record_pitch(step=...), so the count, replay, score and run-value
math are exactly the full form's.

Registered from game_tracking_server (same pattern as
game_tracking_manage_display), so ids live in that module's namespace.
"""

import json

from shiny import ui, render, reactive

from database import get_session
from models import Player, PitchType
from game_stats import get_pitching_pitches

STEP_ORDER_IN_PLAY = ["pitch", "cq", "bbt", "spray", "ab", "result"]

OUTCOME_BUTTONS = [
    ("Ball", "Ball", "ball"),
    ("Called Strike", "Called strike", "strike"),
    ("Swing and Miss", "Swing & miss", "strike"),
    ("Foul", "Foul", "foul"),
    ("In Play", "In play", "inplay"),
    ("HBP", "HBP", "ball"),
]
IN_PLAY_CQ = ["Barreled/Squared Up", "Solid", "Weak", "Jammed", "Off the End", "Clipped", "Bunt"]
BBT = ["Ground Ball", "Line Drive", "Fly Ball", "Pop Up"]
IN_PLAY_AB = ["Groundout", "Flyout", "Lineout", "1B", "2B", "3B", "HR", "E", "FC",
              "Double Play", "Sac Fly", "Sac Bunt", "No Result"]
NON_IN_PLAY_AB = ["K", "K (Looking)", "BB", "HBP", "No Result"]
ZONE_LABELS = {1: "chalk", 2: "in", 3: "mid", 4: "away", 5: "chalk"}


def _fresh():
    return {"step": "pitch", "hist": []}


def register_step_mode(input, output, session, d):
    """d: SimpleNamespace of game_tracking internals -- active_game_id,
    pa_tick, can_edit, access_ok, load_ctx(db, gid), record(step) -> bool,
    resolve_pitcher(game, state), stats_pitcher(game, state),
    arsenal(db, pid, pitch_types), inning_display(inning, game, state),
    ends_pa(state, outcome), suggest(ab, bases, outs)."""
    _wiz = reactive.value(_fresh())
    wiz_id = session.ns("wiz")

    @reactive.effect
    def _reset_on_game_change():
        d.active_game_id()
        with reactive.isolate():
            _wiz.set(_fresh())

    def _go(step, **vals):
        w = dict(_wiz())
        w["hist"] = w["hist"] + [w["step"]]
        w.update(vals)
        w["step"] = step
        _wiz.set(w)

    def _ctx(db):
        gid = d.active_game_id()
        if gid is None:
            return None
        ctx = d.load_ctx(db, gid)
        if ctx is None or ctx[0].status != "In Progress":
            return None
        return ctx

    # ------------------------------------------------------------------
    # Status strip: inning, outs, count, runners, score, pitch count
    # ------------------------------------------------------------------
    @render.ui
    def step_status():
        d.pa_tick()
        if not d.access_ok() or not d.can_edit():
            return None
        db = get_session()
        try:
            ctx = _ctx(db)
            if ctx is None:
                return None
            game, pitches, _a, _b, _o, state, _c = ctx
            if game.uses_three_squad_intrasquad:
                score = f"{game.our_score}-{game.opponent_score}-{game.squad_c_score}"
            else:
                score = f"{game.our_score}-{game.opponent_score}"
            bases = state["bases"] or "000"
            dia = ui.HTML(
                '<svg class="gbo-ss-dia" viewBox="0 0 40 30" aria-label="runners">'
                + "".join(
                    f'<rect x="{x}" y="{y}" width="10" height="10" transform="rotate(45 {x + 5} {y + 5})" '
                    f'class="{"on" if bases[i] == "1" else ""}"/>'
                    for i, (x, y) in enumerate(((27, 13), (15, 2), (3, 13)))
                )
                + "</svg>"
            )
            pc = ""
            pid = d.stats_pitcher(game, state)
            if pid is not None:
                p = db.query(Player).filter(Player.player_id == pid).first()
                if p is not None:
                    n = sum(1 for gp in get_pitching_pitches(db, pid, game_id=game.game_id) if gp.is_pitch is not False)
                    pc = f"{p.last_name} {n}P"
            outs = "".join(f'<i class="{"on" if k < state["outs"] else ""}"></i>' for k in range(3))
            return ui.div(
                ui.div(d.inning_display(state["inning"], game, state), class_="gbo-ss-inn"),
                ui.div(ui.span(f"{state['balls']}-{state['strikes']}", class_="gbo-ss-count"),
                       ui.HTML(f'<span class="gbo-ss-outs" aria-label="{state["outs"]} outs">{outs}</span>'),
                       class_="gbo-ss-mid"),
                dia,
                ui.div(ui.div(score, class_="gbo-ss-score"), ui.div(pc, class_="gbo-ss-pc"), class_="gbo-ss-right"),
                class_="gbo-ss",
            )
        finally:
            db.close()

    # ------------------------------------------------------------------
    # The step screens
    # ------------------------------------------------------------------
    def _btn(label, payload, cls="", selected=False):
        return ui.tags.button(
            label, type="button", class_=f"gbo-sb {cls}" + (" sel" if selected else ""),
            onclick=f"gboWiz('{wiz_id}', {json.dumps(payload)})",
        )

    def _nav(back=True, skip=None):
        kids = []
        if back:
            kids.append(_btn("‹ Back", {"a": "back"}, "gbo-sb-ghost"))
        kids.append(_btn("Cancel", {"a": "cancel"}, "gbo-sb-ghost"))
        if skip:
            kids.append(_btn("Skip ›", {"a": "skip", "to": skip}, "gbo-sb-ghost gbo-sb-skip"))
        return ui.div(*kids, class_="gbo-step-nav")

    def _so_far(w):
        bits = [w.get("code") and f"Call {w['code']}", w.get("ptype"), w.get("outcome"),
                w.get("cq"), w.get("bbt"), (w.get("x") is not None) and "landed ✓", w.get("ab")]
        bits = [b for b in bits if b]
        return ui.div(" · ".join(bits), class_="gbo-step-sofar") if bits else None

    @render.ui
    def step_flow():
        d.pa_tick()
        if not d.access_ok() or not d.can_edit():
            return None
        w = _wiz()
        db = get_session()
        try:
            ctx = _ctx(db)
            if ctx is None:
                return None
            game, pitches, _a, _b, _o, state, _c = ctx
            step = w["step"]
            return ui.TagList(_screen(db, w, step, game, pitches, state),
                              ui.tags.script("gboStepIntoView();"))
        finally:
            db.close()

    def _screen(db, w, step, game, pitches, state):
        if step == "pitch":
            return _pitch_screen(db, game, pitches, state)
        if step == "cq":
            return ui.div(
                _so_far(w), ui.h6("Contact quality", class_="gbo-step-q"),
                ui.div(*[_btn(c, {"a": "cq", "v": c}) for c in IN_PLAY_CQ], class_="gbo-step-grid g2"),
                _nav(skip="bbt"), class_="gbo-step",
            )
        if step == "bbt":
            return ui.div(
                _so_far(w), ui.h6("Batted ball type", class_="gbo-step-q"),
                ui.div(*[_btn(c, {"a": "bbt", "v": c}) for c in BBT], class_="gbo-step-grid g2 big"),
                _nav(skip="spray"), class_="gbo-step",
            )
        if step == "spray":
            return _spray_screen(w)
        if step == "ab":
            return ui.div(
                _so_far(w), ui.h6("AB outcome", class_="gbo-step-q"),
                ui.div(*[_btn(c, {"a": "ab", "v": c}) for c in IN_PLAY_AB], class_="gbo-step-grid g3"),
                _nav(), class_="gbo-step",
            )
        if step == "result":
            return _result_screen(w, state)
        return None

    def _pitch_screen(db, game, pitches, state):
        show_call = (not state["is_our_batting"]) or game.is_intrasquad
        pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
        pid = d.resolve_pitcher(game, state)
        arsenal = d.arsenal(db, pid, pitch_types) if pid else [pt.type_name for pt in pitch_types]
        others = [pt.type_name for pt in pitch_types if pt.type_name not in arsenal]
        n_in_pa = (state.get("pa_pitch_number") or 1)
        key = f"{game.game_id}-{len(pitches)}"
        kids = [ui.div(f"Pitch {n_in_pa} of the at-bat", class_="gbo-step-sofar")]
        if show_call:
            rows = []
            for level in (4, 3, 2, 1):
                rows.extend(ui.tags.button(f"{level}{zone}", type="button", class_="gbo-call",
                                           **{"data-code": f"{level}{zone}"}) for zone in range(1, 6))
            kids += [
                ui.h6(ui.span("Call"), ui.span("level ↕  ·  zone ↔ (1 = in to a righty)", class_="gbo-step-hint"),
                      class_="gbo-step-q"),
                ui.div(*rows, class_="gbo-call-grid"),
            ]
        kids += [
            ui.h6("Pitch type", class_="gbo-step-q"),
            ui.div(*[ui.tags.button(t, type="button", class_="gbo-sb gbo-pt", **{"data-pt": t}) for t in arsenal],
                   class_="gbo-step-grid g3"),
        ]
        if others:
            kids.append(ui.tags.details(
                ui.tags.summary("Other pitch types"),
                ui.div(*[ui.tags.button(t, type="button", class_="gbo-sb gbo-pt", **{"data-pt": t}) for t in others],
                       class_="gbo-step-grid g3"),
                class_="gbo-step-more-pt",
            ))
        kids += [
            ui.h6("Outcome", class_="gbo-step-q"),
            ui.div(*[ui.tags.button(label, type="button", class_=f"gbo-sb gbo-out gbo-out-{kind}", **{"data-out": val})
                     for val, label, kind in OUTCOME_BUTTONS], class_="gbo-step-grid g2 big"),
            ui.tags.script(f"gboPitchScreen('{wiz_id}', '{session.ns('step_pitch')}', '{key}');"),
        ]
        return ui.div(*kids, class_="gbo-step gbo-step-pitch", id=session.ns("step_pitch"))

    def _spray_screen(w):
        x, y = w.get("x"), w.get("y")
        return ui.div(
            _so_far(w), ui.h6(ui.span("Where did it go?"), ui.span("tap the field", class_="gbo-step-hint"),
                              class_="gbo-step-q"),
            ui.HTML(_FIELD_SVG),
            ui.div(_btn("Next ›", {"a": "spray"}, "gbo-sb-primary gbo-spray-next"), class_="gbo-step-grid g1"),
            _nav(skip="ab"),
            ui.tags.script(f"gboSprayScreen('{wiz_id}', '{session.ns('step_spray')}', {json.dumps(x)}, {json.dumps(y)});"),
            class_="gbo-step", id=session.ns("step_spray"),
        )

    def _result_screen(w, state):
        ab = w.get("ab")
        in_play = w.get("outcome") == "In Play"
        choices = IN_PLAY_AB if in_play else NON_IN_PLAY_AB
        sugg = {}
        for c in choices:
            if c == "No Result":
                sugg[c] = [state["outs"], state["bases"] or "000", 0]
            else:
                o, b, r = d.suggest(c, state["bases"] or "000", state["outs"])
                sugg[c] = [min(o, 3), b, r]
        kids = [_so_far(w)]
        if not in_play:
            kids += [ui.h6("Result", class_="gbo-step-q"),
                     ui.div(*[ui.tags.button(c, type="button", class_="gbo-sb gbo-ab", **{"data-ab": c}) for c in choices],
                            class_="gbo-step-grid g3")]
        kids += [
            ui.h6(ui.span("After the play"), ui.span("suggested -- tap to change", class_="gbo-step-hint"), class_="gbo-step-q"),
            ui.div(
                ui.div(ui.div("Runners", class_="gbo-rs-lbl"),
                       ui.div(*[ui.tags.button(lbl, type="button", class_="gbo-sb gbo-base", **{"data-base": str(i)})
                                for i, lbl in ((3, "3rd"), (2, "2nd"), (1, "1st"))], class_="gbo-rs-bases"),
                       class_="gbo-rs-row"),
                ui.div(ui.div("Outs", class_="gbo-rs-lbl"),
                       ui.div(*[ui.tags.button(str(k), type="button", class_="gbo-sb gbo-outs", **{"data-outs": str(k)})
                                for k in range(4)], class_="gbo-rs-outs"),
                       class_="gbo-rs-row"),
                _stepper("Runs scored", "runs"),
                _stepper("Of those, unearned", "unearned"),
                class_="gbo-rs",
            ),
            ui.tags.input(type="text", class_="form-control gbo-rs-notes", placeholder="Notes (optional)"),
            ui.div(ui.tags.button("Save", type="button", class_="gbo-sb gbo-sb-primary gbo-rs-save"), class_="gbo-step-grid g1"),
            _nav(),
            ui.tags.script(f"gboResultScreen('{wiz_id}', '{session.ns('step_result')}', {json.dumps(ab)}, {json.dumps(sugg)});"),
        ]
        return ui.div(*kids, class_="gbo-step gbo-step-result", id=session.ns("step_result"))

    def _stepper(label, key):
        return ui.div(
            ui.div(label, class_="gbo-rs-lbl"),
            ui.div(
                ui.tags.button("−", type="button", class_="gbo-sb gbo-num-btn", **{"data-k": key, "data-d": "-1"}),
                ui.span("0", class_="gbo-num", **{"data-num": key}),
                ui.tags.button("+", type="button", class_="gbo-sb gbo-num-btn", **{"data-k": key, "data-d": "1"}),
                class_="gbo-rs-step",
            ),
            class_="gbo-rs-row",
        )

    # ------------------------------------------------------------------
    # Every tap lands here
    # ------------------------------------------------------------------
    @reactive.effect
    @reactive.event(input.wiz)
    def _on_wiz():
        ev = input.wiz() or {}
        a = ev.get("a")
        w = dict(_wiz())
        if a == "cancel":
            _wiz.set(_fresh())
            return
        if a == "back":
            if not w["hist"]:
                return
            prev = w["hist"][-1]
            w["hist"] = w["hist"][:-1]
            w["step"] = prev
            _wiz.set(w)
            return
        if a == "skip":
            _go(ev.get("to"))
            return
        if a == "pitch":
            outcome = ev.get("outcome")
            if outcome not in [o[0] for o in OUTCOME_BUTTONS]:
                return
            db = get_session()
            try:
                ctx = _ctx(db)
                if ctx is None:
                    return
                state = ctx[5]
            finally:
                db.close()
            vals = {"code": ev.get("code") or None, "ptype": ev.get("ptype") or None, "outcome": outcome}
            ends, nb, ns = d.ends_pa(state, outcome)
            if not ends:
                if d.record({**vals}):
                    _wiz.set(_fresh())
                return
            if outcome == "In Play":
                _go("cq", **vals)
                return
            ab = "BB" if nb >= 4 else ("HBP" if outcome == "HBP" else ("K (Looking)" if outcome == "Called Strike" else "K"))
            _go("result", ab=ab, **vals)
            return
        if a == "cq":
            _go("bbt", cq=ev.get("v"))
        elif a == "bbt":
            _go("spray", bbt=ev.get("v"))
        elif a == "spray":
            if ev.get("x") is None or ev.get("y") is None:
                ui.notification_show("Tap the field first, or Skip.", type="warning", duration=4)
                return
            _go("ab", x=float(ev["x"]), y=float(ev["y"]))
        elif a == "ab":
            _go("result", ab=ev.get("v"))
        elif a == "save":
            step = {k: w.get(k) for k in ("code", "ptype", "outcome", "cq", "bbt", "x", "y")}
            step.update(ab=ev.get("ab") or w.get("ab"), outs=ev.get("outs"), bases=ev.get("bases"),
                        runs=ev.get("runs"), unearned=ev.get("unearned"), notes=ev.get("notes"))
            if step["ab"] != "No Result" and (step["outs"] is None or step["runs"] is None or not step["bases"]):
                ui.notification_show("Set outs, runners and runs first.", type="warning", duration=5)
                return
            if d.record(step):
                _wiz.set(_fresh())


# Field in feet: x = right of the CF line, y = toward the outfield (SVG y is
# flipped). Foul lines to 330, fence arc at 380, 90 ft bases.
_FIELD_SVG = """
<svg class="gbo-field" viewBox="-300 -410 600 430" role="img" aria-label="Tap where the ball went">
  <path class="grass" d="M0 0 L-268.7 -268.7 A380 380 0 0 1 268.7 -268.7 Z"/>
  <path class="dirt" d="M0 0 L-106 -106 A150 150 0 0 1 106 -106 Z"/>
  <path class="infield" d="M0 0 L63.6 -63.6 L0 -127.3 L-63.6 -63.6 Z"/>
  <line class="foul" x1="0" y1="0" x2="-268.7" y2="-268.7"/><line class="foul" x1="0" y1="0" x2="268.7" y2="-268.7"/>
  <path class="fence" d="M-268.7 -268.7 A380 380 0 0 1 268.7 -268.7"/>
  <g class="bases"><rect x="57.6" y="-69.6" width="12" height="12"/><rect x="-6" y="-133.3" width="12" height="12"/>
  <rect x="-69.6" y="-69.6" width="12" height="12"/><path d="M-7 -4 L7 -4 L7 3 L0 9 L-7 3 Z"/></g>
  <text x="-215" y="-150">LF</text><text x="-12" y="-300">CF</text><text x="195" y="-150">RF</text>
  <circle class="mark" r="11" cx="0" cy="0" style="display:none"/>
</svg>
"""

STEP_JS = r"""
(function(){
  if (window.gboWiz) return;
  window.gboWiz = function(id, payload){
    payload = Object.assign({}, payload, {t: Date.now()});
    if (window.Shiny) Shiny.setInputValue(id, payload, {priority: 'event'});
  };
  var sel = {};   // pitch-screen picks survive a redraw of the same pitch
  window.gboPitchScreen = function(id, rootId, key){
    var root = document.getElementById(rootId);
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    if (sel.key !== key) sel = {key: key, code: null, pt: null};
    function paint(){
      root.querySelectorAll('.gbo-call').forEach(function(b){ b.classList.toggle('sel', b.dataset.code === sel.code); });
      root.querySelectorAll('.gbo-pt').forEach(function(b){ b.classList.toggle('sel', b.dataset.pt === sel.pt); });
    }
    root.addEventListener('click', function(e){
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.code) { sel.code = sel.code === b.dataset.code ? null : b.dataset.code; paint(); }
      else if (b.dataset.pt) { sel.pt = sel.pt === b.dataset.pt ? null : b.dataset.pt; paint(); }
      else if (b.dataset.out) {
        if (root.dataset.busy) return;
        root.dataset.busy = '1'; setTimeout(function(){ delete root.dataset.busy; }, 1200);
        gboWiz(id, {a: 'pitch', code: sel.code, ptype: sel.pt, outcome: b.dataset.out});
      }
    });
    paint();
  };
  window.gboSprayScreen = function(id, rootId, x0, y0){
    var root = document.getElementById(rootId);
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var svg = root.querySelector('svg.gbo-field'), mark = svg.querySelector('.mark');
    var next = root.querySelector('.gbo-spray-next');
    var pos = (x0 === null || y0 === null) ? null : {x: x0, y: y0};
    function paint(){
      if (pos) { mark.style.display = ''; mark.setAttribute('cx', pos.x); mark.setAttribute('cy', -pos.y); }
      next.disabled = !pos;
    }
    svg.addEventListener('click', function(e){
      var p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
      var q = p.matrixTransform(svg.getScreenCTM().inverse());
      pos = {x: Math.round(Math.max(-350, Math.min(350, q.x))), y: Math.round(Math.max(-20, Math.min(420, -q.y)))};
      paint();
    });
    next.onclick = function(ev){ ev.stopPropagation(); if (pos) gboWiz(id, {a: 'spray', x: pos.x, y: pos.y}); };
    paint();
  };
  window.gboResultScreen = function(id, rootId, ab, sugg){
    var root = document.getElementById(rootId);
    if (!root || root.dataset.bound) return;
    root.dataset.bound = '1';
    var st = {ab: ab, bases: '000', outs: 0, runs: 0, unearned: 0};
    function apply(){
      var s = sugg[st.ab]; if (!s) return;
      st.outs = s[0]; st.bases = s[1]; st.runs = s[2]; st.unearned = 0;
    }
    function paint(){
      root.querySelectorAll('.gbo-ab').forEach(function(b){ b.classList.toggle('sel', b.dataset.ab === st.ab); });
      root.querySelectorAll('.gbo-base').forEach(function(b){ b.classList.toggle('sel', st.bases[+b.dataset.base - 1] === '1'); });
      root.querySelectorAll('.gbo-outs').forEach(function(b){ b.classList.toggle('sel', +b.dataset.outs === st.outs); });
      root.querySelectorAll('[data-num]').forEach(function(s){ s.textContent = st[s.dataset.num]; });
      var nr = st.ab === 'No Result';
      root.querySelector('.gbo-rs').classList.toggle('off', nr);
    }
    root.addEventListener('click', function(e){
      var b = e.target.closest('button'); if (!b) return;
      if (b.dataset.ab) { st.ab = b.dataset.ab; apply(); }
      else if (b.dataset.base) { var i = +b.dataset.base - 1, a = st.bases.split(''); a[i] = a[i] === '1' ? '0' : '1'; st.bases = a.join(''); }
      else if (b.dataset.outs) { st.outs = +b.dataset.outs; }
      else if (b.dataset.k) { st[b.dataset.k] = Math.max(0, Math.min(4, st[b.dataset.k] + (+b.dataset.d))); }
      else if (b.classList.contains('gbo-rs-save')) {
        if (!st.ab) return;
        if (root.dataset.busy) return;
        root.dataset.busy = '1'; setTimeout(function(){ delete root.dataset.busy; }, 1200);
        var notes = root.querySelector('.gbo-rs-notes');
        gboWiz(id, {a: 'save', ab: st.ab, outs: st.outs, bases: st.bases, runs: st.runs,
                    unearned: st.unearned, notes: notes ? notes.value : ''});
        return;
      } else { return; }
      paint();
    });
    if (st.ab) apply();
    paint();
  };
  // Keep the current step on screen (below the sticky bars) after each tap.
  window.gboStepIntoView = function(){
    setTimeout(function(){
      var el = document.querySelector('.gbo-step'); if (!el) return;
      var r = el.getBoundingClientRect();
      if (r.top < 120 || r.top > window.innerHeight * 0.6) {
        window.scrollTo({top: window.scrollY + r.top - 130, behavior: 'smooth'});
      }
    }, 30);
  };
  // Phone/tablet: step mode by default; the switch on Live Tracking remembers a choice.
  window.gboStepModeInit = function(id){
    var pref = null;
    try { pref = localStorage.getItem('gboStepMode'); } catch (e) {}
    var touch = (window.matchMedia && window.matchMedia('(pointer: coarse)').matches) || window.innerWidth < 900;
    var on = pref === null ? touch : pref === '1';
    function send(){ if (window.Shiny && Shiny.setInputValue) Shiny.setInputValue(id, on); else setTimeout(send, 100); }
    send();
  };
  window.gboSetStepMode = function(id, on){
    try { localStorage.setItem('gboStepMode', on ? '1' : '0'); } catch (e) {}
    if (window.Shiny) Shiny.setInputValue(id, on);
  };
})();
"""
