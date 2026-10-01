"""
GBO -- Roster (v2 design system, new page).

The team at a glance: one row per player with position, class, status,
a Flag chip (Good / Attention / Priority, derived from the bucket
system + movement flag), the five composite scores, and the date of the
most recent assessment. Clicking a name opens that player's profile
(modules/player_profile.py) via app_state.deep_link_player_id + the
same ui.update_navs("main_nav") pattern the bullpen pages use.

This page is VIEW-ONLY. Adding/editing a player still happens on the
existing "Player setup" page (modules/players.py) -- the "Add player"
button here just jumps there.

Permissions: same rule as Assessments -- everyone with
can_view_all_players sees the whole roster; other staff see only their
StaffPlayerAssignment players.
"""

from datetime import date

from shiny import module, ui, render, reactive
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import get_session
from models import Player, StaffPlayerAssignment, Assessment
from bucket_system import compute_bucket_system, list_seasons, current_season_label, season_date_range, build_roster_batch_cache
import ui_helpers


def _flag_for(bucket_data):
    """Player-level Flag (design doc section 7): movement flag red /
    current injury -> Priority; any bucket < 35 -> Priority; any bucket
    35-59 or movement flag yellow/orange -> Attention; else Good.
    Returns (status, short_reason)."""
    if not bucket_data:
        return ui_helpers.STATUS_NEUTRAL, "No assessments yet"
    mf = bucket_data.get("movement_flag") or {}
    reasons = []
    worst = ui_helpers.STATUS_GOOD
    if mf.get("color") == "red":
        worst = ui_helpers.STATUS_FLAG; reasons.append(mf.get("reason") or "Movement flag")
    elif mf.get("color") in ("orange", "yellow"):
        worst = ui_helpers.STATUS_WATCH; reasons.append(mf.get("reason") or "Movement flag")
    for key, label in (("body_comp_score", "Body comp"), ("power_score", "Power"), ("strength_score", "Strength"), ("speed_score", "Speed"), ("capacity_score", "Arm capacity")):
        v = bucket_data.get(key)
        if v is None:
            continue
        st = ui_helpers.status_from_percentile(v)
        if st == ui_helpers.STATUS_FLAG:
            worst = ui_helpers.STATUS_FLAG; reasons.append(f"{label} {v:.0f}")
        elif st == ui_helpers.STATUS_WATCH and worst != ui_helpers.STATUS_FLAG:
            worst = ui_helpers.STATUS_WATCH; reasons.append(f"{label} {v:.0f}")
    return worst, " · ".join(reasons[:2]) if reasons else "All buckets in range"


def _score_cell(v):
    if v is None:
        return ui.tags.td("—", class_="text-end", style="color:var(--gbo-text-muted)")
    st = ui_helpers.status_from_percentile(v)
    color = {"flag": "var(--gbo-status-flag)", "watch": "var(--gbo-status-watch)"}.get(st, "inherit")
    return ui.tags.td(f"{v:.0f}", class_="text-end gbo-num", style=f"color:{color}; font-family:var(--gbo-mono);")


def _season_choices():
    """{label: display_text} for every season, "(current)" appended to
    whichever one is current right now -- shared by the static select
    below and by roster_server's _on_season effect. Built ONCE at UI-
    definition time (not a @render.ui) since list_seasons()/current_
    season_label() are pure functions of the hardcoded SEASONS list +
    today's date, not per-session state -- see the module docstring
    below for why re-rendering this as a reactive select caused the
    picker to visibly flip back and forth."""
    cur = current_season_label()
    return {label: (f"{label} (current)" if label == cur else label) for label, _, _ in list_seasons()}


@module.ui
def roster_ui():
    return ui.div(
        ui.output_ui("head"),
        ui.div(
            # Static input_select, NOT a @render.ui rebuilt from
            # _selected_season() -- Aug 2026, Ryker: picking "Before
            # 2026-2027" made the page go dim and the Season dropdown
            # itself flip back and forth between the two options.
            # Root cause: the picker used to be a @render.ui that
            # rebuilt this same <select> every time _selected_season()
            # changed (mirroring Player Profile's picker) -- but
            # replacing an input's own DOM element in response to that
            # same input's value changing causes Shiny's client-side
            # binding to rebind the fresh element and re-announce its
            # value, which can race with (and stomp) the value the
            # user actually just picked, especially once the
            # server-side recompute is slow enough (a whole season's
            # roster) for that race window to matter. A plain static
            # select has no such loop -- season_label is tracked
            # separately in _selected_season via the _on_season effect
            # below, same as before.
            ui.div(ui.input_select("season", "Season", _season_choices(), selected=current_season_label()), class_="gbo-filter"),
            ui.div(ui.input_select("pos", "Position", {"all": "All positions", "P": "Pitchers", "C": "Catchers", "IF": "Infield", "OF": "Outfield"}), class_="gbo-filter"),
            ui.div(ui.input_select("status", "Status", {"active": "Active", "all": "All", "injured": "Injured / medical hold", "inactive": "Inactive"}), class_="gbo-filter"),
            ui.div(ui.input_select("flag", "Flag", {"any": "Any", "flag": "Priority only", "watch": "Attention + priority"}), class_="gbo-filter"),
            ui.div(ui.input_select("sort", "Sort", {"flag": "Flagged first", "name": "Name", "total": "Overall score", "recent": "Most recent test"}), class_="gbo-filter"),
            style="display:flex; gap:12px; flex-wrap:wrap; align-items:end; margin-bottom:16px;",
        ),
        ui.output_ui("table"),
        ui_helpers.page_footer(),
    )


@module.server
def roster_server(input, output, session, app_state):
    _rows = reactive.Value(None)
    # Which season the roster is scoped to -- None means "current
    # season" (the default every coach lands on). Aug 2026, Ryker:
    # "i want to be able to view guys scores from last year" -- same
    # season-picker pattern already built for Player Profile (see
    # bucket_system.list_seasons/current_season_label/season_date_range
    # and player_profile.py's own _selected_season/season_picker).
    _selected_season = reactive.Value(None)

    @reactive.effect
    @reactive.event(input.season)
    def _on_season():
        _selected_season.set(input.season())

    @reactive.calc
    def _players():
        if not app_state.is_authenticated():
            return []
        season_label = _selected_season() or None
        resolved_label = season_label or current_season_label()
        # "Last test" should reflect that season's own window too --
        # otherwise viewing a past season would still show today's
        # date next to historical scores (Aug 2026, Ryker's follow-up
        # to the season-picker request).
        season_start, season_end = season_date_range(resolved_label)
        db = get_session()
        try:
            q = db.query(Player).options(joinedload(Player.player_position), joinedload(Player.player_class), joinedload(Player.status))
            if not app_state.can_view_all_players():
                ids = [a.player_id for a in db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()]
                q = q.filter(Player.player_id.in_(ids))
            players = q.order_by(Player.last_name, Player.first_name).all()
            last_q = db.query(Assessment.player_id, func.max(Assessment.assessment_date)).group_by(Assessment.player_id)
            if season_start is not None:
                last_q = last_q.filter(Assessment.assessment_date >= season_start)
            if season_end is not None:
                last_q = last_q.filter(Assessment.assessment_date < season_end)
            last = dict(last_q.all())

            # One shared batch fetch for the WHOLE team instead of
            # once per player -- see build_roster_batch_cache's
            # docstring. Without this, viewing a past season (which
            # drops the active-roster-only filter and has no lower
            # date bound for "Before 2026-2027") meant ~57 players x
            # the same expensive whole-roster query repeated, slow
            # enough to look like the page had hung (Aug 2026, Ryker).
            pool_cache, pool_units, throws_map, active_only = build_roster_batch_cache(db, season_label=season_label)

            # Viewing a past season should only show players who were
            # actually around for it -- otherwise, e.g., a freshman who
            # joined for 2026-2027 shows up in "Before 2026-2027" too,
            # just with blank scores. Aug 2026, Ryker: "if they weren't
            # on the roster before that point then they don't show up
            # ... from here on out each year will have a roster."
            # There's no separately-tracked roster-membership history
            # (Player.active is only ever "right now," not "as of a
            # past date"), so this uses the same signal already on
            # screen as the proxy: had at least one assessment result
            # recorded during that season's own window (`last`, above)
            # -- confirmed with Ryker as the simplest option over
            # building a real per-season roster list, since the team
            # already gets tested regularly each season. The one
            # tradeoff: a player who was genuinely on the roster but
            # never got assessed that season (hurt all year, etc.)
            # won't show up for it either. Doesn't apply to the CURRENT
            # season -- everyone on today's roster still belongs there
            # regardless of whether they've been tested yet.
            is_past_season = not active_only
            rows = []
            for p in players:
                if is_past_season and last.get(p.player_id) is None:
                    continue
                bd = None
                try:
                    if active_only and not p.active:
                        # Only case the shared cache above doesn't
                        # already cover: an inactive player scored
                        # against the CURRENT season, who needs his
                        # own include_player_id carve-out (Aug 2026,
                        # Ryker: "inactive players should have a
                        # score") -- falls back to its own fetch since
                        # no _cache is passed here.
                        bd = compute_bucket_system(db, p.player_id, season_label=season_label)
                    else:
                        bd = compute_bucket_system(db, p.player_id, season_label=season_label, _cache=pool_cache, _units=pool_units, _throws_map=throws_map)
                except Exception:
                    bd = None
                flag, why = _flag_for(bd)
                rows.append(dict(player=p, bd=bd or {}, flag=flag, why=why, last=last.get(p.player_id)))
            return rows
        finally:
            db.close()

    @render.ui
    def head():
        rows = _players()
        n_active = sum(1 for r in rows if r["player"].active and (r["player"].status is None or r["player"].status.status_name == "Active"))
        n_inj = sum(1 for r in rows if r["player"].status is not None and r["player"].status.status_name in ("Injured", "Medical Hold"))
        n_flag = sum(1 for r in rows if r["flag"] == ui_helpers.STATUS_FLAG)
        actions = [ui.input_action_button("go_setup", "Add or edit player", class_="btn-primary")] if app_state.can_edit_assessments() or app_state.role_name() in ("Administrator", "Head Coach", "Coach") else []
        season_label = _selected_season() or None
        season_note = f" · Viewing {season_label} (historical)" if season_label and season_label != current_season_label() else ""
        return ui_helpers.page_header("Players", f"{n_active} active · {n_inj} injured or on hold · {n_flag} priority flags{season_note}", actions=actions)

    @reactive.effect
    @reactive.event(input.go_setup)
    def _go_setup():
        ui.update_navs("main_nav", selected="Player setup", session=session.root_scope())

    @render.ui
    def table():
        rows = _players()
        if not rows:
            return ui_helpers.card(ui_helpers.empty_state("No players on the roster yet. Add one from Player setup."))
        pos_f, st_f, fl_f, sort = input.pos(), input.status(), input.flag(), input.sort()

        def pos_group(p):
            name = p.player_position.position_name if p.player_position else ""
            if name in ("RHP", "LHP") or p.is_pitcher: return "P"
            if name == "C": return "C"
            # "INF"/"OF" are the grouped position rows added Aug 2026 (Players
            # page redesign) -- new position assignments use these instead of
            # the granular 1B/2B/3B/SS/LF/CF/RF names, which still exist on
            # older records, so both forms are matched here.
            if name in ("1B", "2B", "3B", "SS", "INF"): return "IF"
            if name in ("LF", "CF", "RF", "OF"): return "OF"
            return "UTL"
        out = []
        for r in rows:
            p = r["player"]; sname = p.status.status_name if p.status else "Active"
            if pos_f != "all" and pos_group(p) != pos_f: continue
            if st_f == "active" and (not p.active or sname != "Active"): continue
            if st_f == "injured" and sname not in ("Injured", "Medical Hold"): continue
            if st_f == "inactive" and p.active: continue
            if fl_f == "flag" and r["flag"] != ui_helpers.STATUS_FLAG: continue
            if fl_f == "watch" and r["flag"] not in (ui_helpers.STATUS_FLAG, ui_helpers.STATUS_WATCH): continue
            out.append(r)
        rank = {"flag": 0, "watch": 1, "good": 2, "neutral": 3}
        if sort == "flag": out.sort(key=lambda r: (rank[r["flag"]], r["player"].last_name))
        elif sort == "total": out.sort(key=lambda r: -(r["bd"].get("total_score") or -1))
        elif sort == "recent": out.sort(key=lambda r: (r["last"] or date.min), reverse=True)
        else: out.sort(key=lambda r: (r["player"].last_name, r["player"].first_name))

        head = ui.tags.tr(*[ui.tags.th(h, class_="text-end" if i >= 7 else "") for i, h in enumerate(["#", "Player", "Pos", "B/T", "Class", "Status", "Flag", "Overall", "Body", "Power", "Str", "Speed", "Arm", "Last test"])], ui.tags.th(""))
        body = []
        for r in out:
            p, bd = r["player"], r["bd"]
            sname = p.status.status_name if p.status else "Active"
            st_chip = ui_helpers.status_chip("neutral", sname) if sname == "Active" else ui_helpers.status_chip("watch" if sname in ("Injured", "Medical Hold") else "neutral", sname)
            cls = (p.player_class.class_name if p.player_class else "").replace("Redshirt ", "RS ").replace("Freshman", "FR").replace("Sophomore", "SO").replace("Junior", "JR").replace("Senior", "SR").replace("Graduate", "GR")
            last_cell = ui.tags.td(r["last"].strftime("%b %d") if r["last"] else "—", class_="text-end gbo-num", style="font-family:var(--gbo-mono);" + ("" if r["last"] and (date.today() - r["last"]).days <= 45 else "color:var(--gbo-status-watch);"))
            body.append(ui.tags.tr(
                ui.tags.td(str(p.jersey_number or "—"), class_="gbo-num", style="font-family:var(--gbo-mono); color:var(--gbo-text-muted);"),
                ui.tags.td(ui.tags.a(f"{p.first_name} {p.last_name}", href="#", class_="gbo-player-link", **{"data-player-id": str(p.player_id)}), title=r["why"]),
                ui.tags.td(p.player_position.position_name if p.player_position else "—"),
                ui.tags.td(f"{p.bats or '-'}/{p.throws or '-'}"),
                ui.tags.td(cls or "—"),
                ui.tags.td(st_chip),
                ui.tags.td(ui_helpers.status_chip(r["flag"])),
                ui.tags.td(ui.tags.b(f"{bd.get('total_score'):.0f}") if bd.get("total_score") is not None else "—", class_="text-end gbo-num", style="font-family:var(--gbo-mono); color:var(--gbo-text);"),
                _score_cell(bd.get("body_comp_score")), _score_cell(bd.get("power_score")), _score_cell(bd.get("strength_score")), _score_cell(bd.get("speed_score")), _score_cell(bd.get("capacity_score")),
                last_cell,
                ui.tags.td(ui.tags.a("Profile", href="#", class_="gbo-player-link", style="color:var(--gbo-crimson); font-weight:600;", **{"data-player-id": str(p.player_id)})),
            ))
        table = ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), class_="table")
        js = ui.tags.script(f"""
        (function(){{
          var root = document.getElementById('{session.ns("table")}');
          if (!root || root.__gboBound) return; root.__gboBound = true;
          root.addEventListener('click', function(e){{
            var a = e.target.closest ? e.target.closest('.gbo-player-link') : null;
            if (!a) return; e.preventDefault();
            Shiny.setInputValue('{session.ns("open_player")}', parseInt(a.getAttribute('data-player-id')), {{priority:'event'}});
          }});
        }})();""")
        return ui.div(
            ui_helpers.card(ui.div(table, class_="table-responsive"), ui.div(f"{len(out)} of {len(rows)} players · scores are latest bucket percentiles, colored when Attention or Priority · hover a name for the flag reason", class_="gbo-page-sub", style="margin-top:12px; font-size:.78rem;")),
            js,
        )

    @reactive.effect
    @reactive.event(input.open_player)
    def _open_player():
        app_state.deep_link_player_id.set(int(input.open_player()))
        ui.update_navs("main_nav", selected="Player Profile", session=session.root_scope())
