"""
GBO -- Player Profile (v2 design system, new page).

The hub for one athlete (Ryker's brief: "when a coach selects a player,
the profile serves as the central hub"). Layout, top to bottom:

  1. Page header: name, jersey/position/class/B-T/height/weight/
     hometown, and the page's actions.
  2. Hero row: the MLB-The-Show-style player card (ui_helpers.show_card)
     on the left; on the right, at-a-glance tiles (overall flag, last
     assessed, movement flag) and the development priorities -- the
     worst metrics in plain words, so the "Objective -> Analytics ->
     Insight" chain is visible before any table.
  3. Tabs: Overview (bucket summary cards + composite rings) ·
     Assessments (the scored breakdown from bucket_display, PLUS --
     Sept 2026 -- a "Full History" accordion, one panel per assessment
     category with data, raw dated entries via assessment_history.py)
     · Mobility (ROM report + movement flag) · Pitching (latest
     Rapsodo session summary) · Development (IDP goals) · Video.

Everything analytic is REUSED from bucket_system / bucket_display /
bullpen_metrics -- this page adds no new calculations.

Sept 2026 (Ryker's call): the Assessments page (shiny_app/modules/
assessments.py) was pared down to pure data entry -- viewing moved
here. Full History is this page's one genuinely new piece: two of the
11 assessment categories (Anthropometrics, Pitcher-Specific) never
feed bucket_system at all, so before this they had NO display anywhere
except the Assessments page's own history view. Full History covers
every category uniformly (not just those two) so nothing needs special-
casing here.

Who lands here: coaches via the Roster (app_state.deep_link_player_id
+ update_navs) or the in-page picker; a Player-role user always sees
their own linked player and gets no picker.
"""

from datetime import date

from shiny import module, ui, render, reactive
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from database import get_session
from models import (Player, StaffPlayerAssignment, Assessment, AssessmentCategory, BullpenSession,
                    RapsodoPitch, IDPGoal, Video)
from bucket_system import compute_bucket_system, list_seasons, current_season_label
from analytics.bullpen_metrics import session_summary, pitch_type_summary
from assessment_history import assessment_history_query, assessment_history_rows
from pitch_type_config import FASTBALL_TYPES
import bucket_display
import ui_helpers


def _fmt_height(inches):
    try:
        inches = float(inches)
    except (TypeError, ValueError):
        return None
    if not inches:
        return None
    return f"{int(inches // 12)}'{int(inches % 12)}\""


def _priorities(bd, limit=3):
    """Worst metrics across the bucket system + red/yellow ROM rows,
    as (status, title, detail). Drives the 'Development priorities'
    card and the card's flag."""
    items = []
    for row in bd.get("mobility_rom_report") or []:
        st = row.get("status")
        if st in ("red", "yellow"):
            name = row.get("test_name") or row.get("name") or row.get("label") or "Mobility"
            raw = row.get("raw"); unit = row.get("unit") or ""; thr = row.get("threshold")
            detail = row.get("explanation") or row.get("recommendation") or ""
            if not detail and raw is not None:
                detail = f"{raw:g}{unit}" + (f" · threshold {thr:g}{unit}" if thr is not None else "")
            items.append((0 if st == "red" else 1, ui_helpers.status_from_color_word(st), name.replace(": ", " — "), detail.strip()))
    groups = [("body_comp_metrics", None), ("speed_metrics", None), ("power_subgroup_metrics", "sub"), ("strength_subgroup_metrics", "sub"), ("capacity_subgroup_metrics", "sub")]
    for key, kind in groups:
        data = bd.get(key) or {}
        metrics = {}
        if kind == "sub":
            for sub, m in data.items():
                metrics.update(m)
        else:
            metrics = data
        if key == "body_comp_metrics":
            # Body Fat Mass / Percent Body Fat are reference-only, same
            # BODY_COMP_BAR_NAMES split bucket_display.py already uses
            # for the Assessments tab (Aug 2026, Ryker: they shouldn't
            # show up as a percentile OR as a Development priority --
            # a lean-team player's fat % looking "low percentile" isn't
            # a deficiency the way a weak lift is).
            metrics = {n: d for n, d in metrics.items() if n in bucket_display.BODY_COMP_BAR_NAMES}
        for name, d in metrics.items():
            pct = d.get("percentile")
            if pct is None:
                continue
            st = ui_helpers.status_from_percentile(pct)
            if st in (ui_helpers.STATUS_FLAG, ui_helpers.STATUS_WATCH):
                items.append((pct, st, name, f"{d.get('raw')}{(' ' + d['unit']) if d.get('unit') else ''} · {bucket_display.ordinal(pct)} percentile on team"))
    items.sort(key=lambda x: x[0])
    return [(st, t, dt) for _, st, t, dt in items[:limit]]


@module.ui
def player_profile_ui():
    return ui.div(
        ui.div(ui.output_ui("picker"), ui.output_ui("season_picker"), style="display:flex; gap:12px; flex-wrap:wrap; align-items:flex-end;"),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def player_profile_server(input, output, session, app_state):
    _selected = reactive.Value(None)
    # None = current season (compute_bucket_system's own default) --
    # only set to something else once the coach actually picks a past
    # season from season_picker() below. Aug 2026, Ryker: "coaches
    # should be able to go back and look at a player's overall scores
    # for previous seasons" -- see SEASONS/list_seasons in
    # bucket_system.py for how a season's date window is defined.
    _selected_season = reactive.Value(None)

    def _visible_players(db):
        q = db.query(Player).options(joinedload(Player.player_position), joinedload(Player.player_class), joinedload(Player.status))
        if app_state.role_name() == "Player":
            return q.filter(Player.player_id == app_state.player_id()).all() if hasattr(app_state, "player_id") else []
        if not app_state.can_view_all_players():
            ids = [a.player_id for a in db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()]
            q = q.filter(Player.player_id.in_(ids))
        return q.filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()

    @reactive.effect
    def _consume_deep_link():
        pid = app_state.deep_link_player_id()
        if pid is not None:
            _selected.set(int(pid))
            app_state.deep_link_player_id.set(None)
            ui.update_select("pick", selected=str(pid))

    @render.ui
    def picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() == "Player":
            return None
        db = get_session()
        try:
            players = _visible_players(db)
        finally:
            db.close()
        choices = {str(p.player_id): f"{p.last_name}, {p.first_name}" + (f"  #{p.jersey_number}" if p.jersey_number else "") for p in players}
        sel = str(_selected()) if _selected() and str(_selected()) in choices else (next(iter(choices)) if choices else None)
        return ui.div(ui.input_select("pick", "Player", choices, selected=sel, width="320px"), style="margin-bottom:8px;")

    @reactive.effect
    @reactive.event(input.pick)
    def _on_pick():
        try:
            _selected.set(int(input.pick()))
        except (TypeError, ValueError):
            pass

    @render.ui
    def season_picker():
        # Unlike picker() above, NOT gated behind role -- a Player-role
        # user should still be able to look back at their own past
        # seasons, they just never see the player dropdown next to it.
        if not app_state.is_authenticated():
            return None
        cur = current_season_label()
        choices = {label: (f"{label} (current)" if label == cur else label) for label, _, _ in list_seasons()}
        sel = _selected_season() if _selected_season() in choices else cur
        return ui.div(ui.input_select("season", "Season", choices, selected=sel, width="220px"), style="margin-bottom:8px;")

    @reactive.effect
    @reactive.event(input.season)
    def _on_season():
        _selected_season.set(input.season())

    @reactive.effect
    @reactive.event(input.go_assess)
    def _go_assess():
        ui.update_navs("main_nav", selected="Assessments", session=session.root_scope())

    @reactive.effect
    @reactive.event(input.go_idp)
    def _go_idp():
        ui.update_navs("main_nav", selected="IDP", session=session.root_scope())

    @reactive.effect
    @reactive.event(input.go_bullpen, input.go_bullpen2)
    def _go_bullpen():
        ui.update_navs("main_nav", selected="Bullpen Dashboard", session=session.root_scope())

    @render.ui
    def body():
        if not app_state.is_authenticated():
            return None
        pid = _selected()
        db = get_session()
        try:
            if app_state.role_name() == "Player":
                me = db.query(Player).join(Player.users).filter(Player.users.any(user_id=app_state.user_id())).first() if hasattr(Player, "users") else None
                if me is None:
                    from models import User
                    u = db.query(User).filter(User.user_id == app_state.user_id()).first()
                    me = db.query(Player).filter(Player.player_id == u.player_id).first() if u and u.player_id else None
                if me is None:
                    return ui_helpers.card(ui_helpers.empty_state("Your account isn't linked to a player record yet. Ask a coach to link it in User Management."))
                pid = me.player_id
            if pid is None:
                players = _visible_players(db)
                if not players:
                    return ui_helpers.card(ui_helpers.empty_state("No players to show. Add players from Player setup."))
                pid = players[0].player_id
            p = db.query(Player).options(joinedload(Player.player_position), joinedload(Player.player_class), joinedload(Player.status)).filter(Player.player_id == pid).first()
            if p is None:
                return ui_helpers.card(ui_helpers.empty_state("That player doesn't exist or you don't have access."))
            # season_label=None resolves to the current season inside
            # compute_bucket_system -- _selected_season only holds a
            # real value once the coach (or player) has actually picked
            # a season from season_picker() above.
            bd = compute_bucket_system(db, pid, season_label=_selected_season() or None) or {}
            last_by_cat = db.query(AssessmentCategory.category_name, func.max(Assessment.assessment_date)).join(Assessment, Assessment.category_id == AssessmentCategory.category_id).filter(Assessment.player_id == pid).group_by(AssessmentCategory.category_name).all()
            last_date = max((d for _, d in last_by_cat), default=None)
            last_cat = next((c for c, d in last_by_cat if d == last_date), None)
            bullpen = db.query(BullpenSession).options(joinedload(BullpenSession.bullpen_type)).filter(BullpenSession.player_id == pid).order_by(BullpenSession.session_date.desc()).first()
            pitches = db.query(RapsodoPitch).options(joinedload(RapsodoPitch.pitch_type)).filter(RapsodoPitch.bullpen_id == bullpen.bullpen_id).order_by(RapsodoPitch.pitch_number).all() if bullpen else []
            n_bullpens = db.query(BullpenSession).filter(BullpenSession.player_id == pid).count()
            goals = db.query(IDPGoal).options(joinedload(IDPGoal.category), joinedload(IDPGoal.status)).filter(IDPGoal.player_id == pid).order_by(IDPGoal.created_at.desc()).all()
            videos = db.query(Video).filter(Video.player_id == pid).order_by(Video.recorded_date.desc().nullslast()).limit(10).all()
            mode = app_state.dark_mode() or "dark"
            # Full History (Sept 2026): every assessment category with
            # data for this player, not just the 6 that feed the bucket
            # score -- see the module docstring. One query per category
            # (11 total, cheap -- same as bucket_system's own per-
            # category queries elsewhere) rather than a lazily-loaded
            # picker, since this whole page is already one render pass.
            history_categories = db.query(AssessmentCategory).order_by(AssessmentCategory.display_order).all()
            history_panels = []
            for cat in history_categories:
                rows = assessment_history_rows(assessment_history_query(db, pid, cat.category_id).all())
                if rows:
                    history_panels.append(ui.accordion_panel(f"{cat.category_name} ({len(rows)})", ui_helpers.render_dict_table(rows)))
            return _render(p, bd, last_date, last_cat, bullpen, pitches, n_bullpens, goals, videos, mode, app_state, history_panels)
        finally:
            db.close()

    def _render(p, bd, last_date, last_cat, bullpen, pitches, n_bullpens, goals, videos, mode, app_state, history_panels):
        pos = p.player_position.position_name if p.player_position else None
        cls = p.player_class.class_name if p.player_class else None
        meta = " · ".join(x for x in [f"#{p.jersey_number}" if p.jersey_number else None, pos, cls, f"{p.bats or '-'}/{p.throws or '-'}",
                                      " ".join(x for x in [_fmt_height(p.height_in), f"{float(p.weight_lb):.0f} lb" if p.weight_lb else None] if x) or None, p.hometown] if x)
        can_edit = app_state.role_name() != "Player"
        actions = [ui.input_action_button("go_idp", "Add goal", class_="btn-outline-light"), ui.input_action_button("go_assess", "Log assessment", class_="btn-primary")] if can_edit else []
        # Called out in the subtitle whenever the season picker isn't on
        # "current" -- everything below (card, bucket scores, Mobility &
        # ROM, Assessments tab) is scoped to that past season's data,
        # not this player's live/current standing, and that's easy to
        # miss without an explicit flag here.
        season_label = bd.get("season_label")
        season_note = f" · Viewing {season_label} (historical)" if season_label and season_label != current_season_label() else ""
        header = ui_helpers.page_header(f"{p.first_name} {p.last_name}", meta + season_note, actions=actions)

        pris = _priorities(bd)
        flag = ui_helpers.STATUS_NEUTRAL if not bd.get("total_score") and not pris else (ui_helpers.STATUS_FLAG if any(s == "flag" for s, _, _ in pris) else ui_helpers.STATUS_WATCH if pris else ui_helpers.STATUS_GOOD)
        mf = bd.get("movement_flag") or {}
        summ = session_summary(pitches) if pitches else None
        # Fastball-only slice of the same latest-session pitch list, for
        # the card's VELO stat (Aug 2026, Ryker: VELO should read as
        # average fastball velocity, not an average across every pitch
        # type thrown that session -- see FASTBALL_TYPES in
        # pitch_type_config.py). pitch_type is already joinedloaded on
        # `pitches` above, so this doesn't cost another query. None (not
        # an all-zero summary) when the pitcher threw no fastballs that
        # session, so the card shows "—" rather than a misleading 0.
        fastball_pitches = [pt for pt in pitches if pt.pitch_type and pt.pitch_type.type_name in FASTBALL_TYPES]
        fastball_summ = session_summary(fastball_pitches) if fastball_pitches else None

        card = ui_helpers.show_card(p, bd, summ, flag, fastball_summary=fastball_summ)
        tiles = ui.div(
            ui_helpers.kpi_tile("Status", ui_helpers.status_chip(flag), delta=f"{sum(1 for s,_,_ in pris if s=='flag')} priority · {sum(1 for s,_,_ in pris if s=='watch')} attention" if pris else "No flags"),
            ui_helpers.kpi_tile("Last assessed", last_date.strftime("%b %d") if last_date else "—", delta=f"{last_cat} · {(date.today()-last_date).days} days ago" if last_date else "No assessments yet"),
            ui_helpers.kpi_tile("Movement flag", (mf.get("color") or "—").title(), delta=mf.get("reason") or ("Score " + str(mf.get("score")) if mf.get("score") is not None else "Not assessed"), status="flag" if mf.get("color") == "red" else "watch" if mf.get("color") in ("yellow", "orange") else None),
            class_="gbo-kpi-row", style="margin-bottom:16px;",
        )
        # Left blank for now (Aug 2026, Ryker's call) -- was populated
        # from _priorities(bd) (worst bucket-system/ROM metrics). pris
        # is still computed above and still drives the Status tile and
        # the hero card's flag color, just no longer rendered here.
        priorities = ui_helpers.card(title="Development priorities")
        hero = ui.div(card, ui.div(tiles, priorities), class_="gbo-profile-hero")

        # --- tabs ---
        overview = _overview_tab(bd, summ, pitches, bullpen, goals, mode)
        breakdown_block = bucket_display.build_full_breakdown(bd, key_prefix="profile", mode=mode) if bd.get("total_score") is not None else ui_helpers.card(ui_helpers.empty_state("No scored assessments yet. Log Body Composition, Power, or Strength tests to populate the breakdown."))
        # Full History -- collapsed by default, same treatment the raw
        # history table always got on the (now data-entry-only)
        # Assessments page. Only categories with real data get a panel,
        # so an unused category (e.g. Baseball Performance, still an
        # empty placeholder) doesn't show up as a dead accordion row.
        history_block = (
            ui.div(
                ui.h5("Full History", class_="gbo-section-title", style="margin-top:20px;"),
                ui.accordion(*history_panels, open=False, id=None),
            )
            if history_panels else None
        )
        assessments_tab = ui.div(breakdown_block, history_block)
        rom = bd.get("mobility_rom_report") or []
        mobility_tab = ui.div(
            ui.div(bucket_display.build_movement_flag_ring(mf, rom, key_prefix="profile", mode=mode) if mf else None, style="margin-bottom:16px;"),
            ui_helpers.card(bucket_display.build_mobility_rom_report(rom) if rom else ui_helpers.empty_state("No Mobility & ROM assessment yet."), title="Mobility & ROM", right="threshold-based, not percentile"),
        )
        pitching_tab = _pitching_tab(p, bullpen, pitches, summ, n_bullpens)
        dev_tab = _dev_tab(goals)
        video_tab = ui_helpers.card(*( [ui.div(ui.div(v.recorded_date.strftime("%b %d, %Y") if v.recorded_date else "—", class_="gbo-li-dt"), ui.div(ui.a(v.description or "Video", href=v.video_url, target="_blank") if v.video_url else (v.description or "Video")), class_="gbo-li") for v in videos] or [ui_helpers.empty_state("No video linked to this player yet. Pitch and swing clips upload from Bullpen Tracking, Hitter Tracking, and Video Import.")]), title="Video")

        tabs = ui.navset_tab(
            ui.nav_panel("Overview", ui.div(overview, class_="gbo-tab-body")),
            ui.nav_panel("Assessments", ui.div(assessments_tab, class_="gbo-tab-body")),
            ui.nav_panel("Mobility", ui.div(mobility_tab, class_="gbo-tab-body")),
            ui.nav_panel("Pitching", ui.div(pitching_tab, class_="gbo-tab-body")),
            ui.nav_panel("Development", ui.div(dev_tab, class_="gbo-tab-body")),
            ui.nav_panel("Video", ui.div(video_tab, class_="gbo-tab-body")),
            id="profile_tabs",
        )
        return ui.div(header, hero, ui.div(tabs, style="margin-top:24px;"))

    def _overview_tab(bd, summ, pitches, bullpen, goals, mode):
        def flat(sub):
            m = {}
            for s, mm in (sub or {}).items(): m.update(mm)
            return m
        # Body Fat Mass / Percent Body Fat are reference-only (same
        # BODY_COMP_BAR_NAMES split bucket_display.py's Assessments-tab
        # breakdown already uses) -- excluded here too so they can't
        # show up as a percentile bar or drag the Body composition
        # panel's flagged/watch count (Aug 2026, Ryker's call).
        body_comp_bar_metrics = {n: d for n, d in (bd.get("body_comp_metrics") or {}).items() if n in bucket_display.BODY_COMP_BAR_NAMES}
        buckets = [
            ("Body composition", bd.get("body_comp_score"), body_comp_bar_metrics),
            ("Explosive & rotational power", bd.get("power_score"), flat(bd.get("power_subgroup_metrics"))),
            ("Strength", bd.get("strength_score"), flat(bd.get("strength_subgroup_metrics"))),
            ("Speed", bd.get("speed_score"), bd.get("speed_metrics") or {}),
            ("Arm capacity", bd.get("capacity_score"), flat(bd.get("capacity_subgroup_metrics"))),
        ]
        bucket_cards = []
        for title, score, metrics in buckets:
            if score is None and not metrics:
                continue
            # Sept 1 2026 fix: this accordion used to grade both the
            # panel's own composite score AND each individual metric bar
            # with the app-wide 35/60 default (ui_helpers.status_from_
            # percentile) -- on this roster that read as "everyone
            # green," the same complaint that already drove build_score_
            # rings/build_metric_bars to stricter cut points elsewhere.
            # Now reuses those same two scales instead of a third copy:
            # composite_score_status for the panel/score badge (matches
            # the Composite scores ring for the identical value), individual_
            # metric_status for each metric row and the flagged/watch
            # counts that drive this panel's chip.
            st = bucket_display.composite_score_status(score) or ui_helpers.STATUS_NEUTRAL
            flagged = sum(1 for d in metrics.values() if bucket_display.individual_metric_status(d.get("percentile")) == "flag")
            watch = sum(1 for d in metrics.values() if bucket_display.individual_metric_status(d.get("percentile")) == "watch")
            if flagged: st = ui_helpers.STATUS_FLAG
            elif watch and st == ui_helpers.STATUS_GOOD: st = ui_helpers.STATUS_WATCH
            rows = [ui_helpers.metric_bar(n, f"{d.get('raw')}", d.get("percentile"), status=bucket_display.individual_metric_status(d.get("percentile")), unit=d.get("unit"), percentile_text=f"{bucket_display.ordinal(d['percentile'])} percentile" if d.get("percentile") is not None else "No team comparison yet") for n, d in metrics.items()]
            bucket_cards.append(ui.accordion_panel(
                ui.div(ui.span(f"{score:.0f}" if score is not None else "—", class_=f"gbo-bucket-score {('gold' if (score or 0) >= 90 else (bucket_display.composite_score_status(score) or 'neutral'))}"),
                       ui.div(title, class_="gbo-bucket-title"),
                       ui_helpers.status_chip(st, f"{flagged} priority · {watch} attention" if (flagged or watch) else None), class_="gbo-bucket-head"),
                ui.div(*rows, class_="gbo-metric-bar-group") if rows else ui_helpers.empty_state("No metrics recorded."),
                value=title,
            ))
        left = ui.accordion(*bucket_cards, open=False, class_="gbo-bucket-accordion") if bucket_cards else ui_helpers.card(ui_helpers.empty_state("No scored assessments yet."))
        rings = ui_helpers.card(ui.div(bucket_display.build_score_rings(bd, key_prefix="profile_ov", mode=mode), class_="gbo-rings-row"), title="Composite scores", right="Total = Body comp + Power + Strength") if bd.get("total_score") is not None else None
        latest_pen = None
        if summ:
            latest_pen = ui_helpers.card(
                ui.div(ui_helpers.kpi_tile("Pitches", summ["total_pitches"]), ui_helpers.kpi_tile("Avg velo", f"{summ['avg_velocity']:.1f}" if summ["avg_velocity"] else "—", unit="mph"), ui_helpers.kpi_tile("Avg spin", f"{summ['avg_spin_rate']:,.0f}" if summ["avg_spin_rate"] else "—", unit="rpm"), class_="gbo-kpi-row", style="margin-bottom:8px;"),
                ui.input_action_button("go_bullpen", "Open bullpen dashboard", class_="btn-outline-light btn-sm"),
                title="Latest bullpen", right=bullpen.session_date.strftime("%b %d") + (f" · {bullpen.bullpen_type.type_name}" if bullpen.bullpen_type else ""),
            )
        open_goals = [g for g in goals if not (g.status and g.status.status_name == "Completed")][:4]
        goals_card = ui_helpers.card(*([ui.div(ui.div(ui.tags.b(g.description[:80]), ui.span(f" — {g.category.category_name}" if g.category else "", style="color:var(--gbo-text-muted)"), ui.span(f" · due {g.target_date.strftime('%b %d')}" if g.target_date else "", style="color:var(--gbo-text-muted)")), ui_helpers.status_chip("neutral", g.status.status_name if g.status else "Open"), class_="gbo-li") for g in open_goals] or [ui_helpers.empty_state("No development goals yet. Coaches add them from the IDP page.")]), title="Active goals", right=f"{len(open_goals)} open")
        right = ui.div(rings, latest_pen, goals_card, class_="gbo-stack")
        return ui.div(left, right, class_="gbo-grid gbo-grid-2", style="align-items:start;")

    def _pitching_tab(p, bullpen, pitches, summ, n_bullpens):
        if not p.is_pitcher and not pitches:
            return ui_helpers.card(ui_helpers.empty_state("Not flagged as a pitcher. Mark the player as a pitcher in Player setup to track bullpens here."))
        if not pitches:
            return ui_helpers.card(ui_helpers.empty_state("No Rapsodo bullpen imported yet. Import a session from Import Rapsodo and it will show here."))
        rows = pitch_type_summary(pitches)
        cols = list(rows[0].keys()) if rows else []
        table = ui.tags.table(ui.tags.thead(ui.tags.tr(*[ui.tags.th(c, class_="text-end" if i else "") for i, c in enumerate(cols)])),
                              ui.tags.tbody(*[ui.tags.tr(*[ui.tags.td(_fmt(r.get(c)), class_=("text-end gbo-num" if i else ""), style=("font-family:var(--gbo-mono);" if i else "")) for i, c in enumerate(cols)]) for r in rows]), class_="table")
        return ui.div(
            ui.div(ui_helpers.kpi_tile("Sessions", n_bullpens), ui_helpers.kpi_tile("Pitches (latest)", summ["total_pitches"]), ui_helpers.kpi_tile("Avg velo", f"{summ['avg_velocity']:.1f}" if summ["avg_velocity"] else "—", unit="mph"), ui_helpers.kpi_tile("Max velo", f"{summ['max_velocity']:.1f}" if summ["max_velocity"] else "—", unit="mph"), ui_helpers.kpi_tile("Avg spin", f"{summ['avg_spin_rate']:,.0f}" if summ["avg_spin_rate"] else "—", unit="rpm"), class_="gbo-kpi-row"),
            ui_helpers.card(ui.div(table, class_="table-responsive"), ui.div(ui.input_action_button("go_bullpen2", "Open bullpen dashboard for charts", class_="btn-outline-light btn-sm"), style="margin-top:12px;"), title="Latest session by pitch type", right=bullpen.session_date.strftime("%b %d, %Y")),
        )

    def _dev_tab(goals):
        if not goals:
            return ui_helpers.card(ui_helpers.empty_state("No development goals yet. Coaches add them from the IDP page, tied to the assessment that motivated them."), title="Development plan")
        rows = []
        for g in goals:
            rows.append(ui.div(
                ui.div(ui.tags.b(g.description), ui.div(" · ".join(x for x in [g.category.category_name if g.category else None, f"target {g.target_value}" if g.target_value is not None else None, f"by {g.target_date.strftime('%b %d, %Y')}" if g.target_date else None] if x), style="color:var(--gbo-text-muted); font-size:.8rem;")),
                ui_helpers.status_chip("neutral", g.status.status_name if g.status else "Open"), class_="gbo-li"))
        return ui_helpers.card(*rows, title="Development plan", right=f"{len(goals)} goals")


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}" if abs(v) < 1000 else f"{v:,.0f}"
    return str(v)
