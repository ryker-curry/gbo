"""
GBO -- Player Profile "College Career" tab (Nov 2026, Ryker). See
college_career.py for what's stored and how totals work.

Everyone who can see the profile sees the tables (players included);
staff also get "Add or fix a season" to type in a season or fill gaps
(blank = not published, never zero).
"""

from shiny import ui, render, reactive, req

from database import get_session
from models import CollegeSeasonStat
import college_career as cc
import ui_helpers

LEVELS = ["NCAA D1", "NCAA D2", "NCAA D3", "NAIA", "NJCAA D1", "NJCAA D2", "NJCAA D3", "CCCAA", "Other"]
NEW = "new"


def _table(columns, rows, total):
    def cells(row, link=True):
        out = []
        for c in columns:
            v = row.get(c, cc.DASH)
            if c == "School" and link and row.get("_source"):
                v = ui.a(v, href=row["_source"], target="_blank", rel="noopener", title="Where these numbers came from")
            if c == "School" and row.get("_partial"):
                v = ui.span(v, " ", ui.span("partial", class_="gbo-cc-partial", title="Only part of this season was published -- blanks aren't zeros, and it isn't in the total."))
            out.append(ui.tags.td(v, class_="gbo-statline-na") if v == cc.DASH else ui.tags.td(v))
        return out
    head = ui.tags.tr(*[ui.tags.th(c) for c in columns])
    body = [ui.tags.tr(*cells(r)) for r in rows]
    foot = ui.tags.tfoot(ui.tags.tr(*cells(total, link=False))) if total else None
    return ui.div(ui.div(ui.tags.table(ui.tags.thead(head), ui.tags.tbody(*body), foot, class_="table table-sm"),
                         class_="table-responsive"), class_="gbo-statline")


def _section(title, columns, rows, total, partial):
    if not rows:
        return None
    note = ("Total counts complete seasons only. " if partial else "") + \
        "School names link to the page the numbers came from. A dash means it wasn't published."
    return ui.div(ui.p(ui.strong(title)), _table(columns, rows, total), ui.p(note, class_="text-muted small"))


def register(input, output, session, app_state, profile_pid):
    """Call from player_profile_server. profile_pid(db) -> shown player id."""
    _tick = reactive.Value(0)

    def _staff():
        return app_state.is_authenticated() and app_state.role_name() != "Player"

    @render.ui
    def college_career_tab():
        if not app_state.is_authenticated():
            return None
        req("profile_tabs" in input and input.profile_tabs() == "College Career")
        _tick()
        db = get_session()
        try:
            pid = profile_pid(db)
            if pid is None:
                return ui_helpers.card(ui_helpers.empty_state("No player selected."))
            rows = db.query(CollegeSeasonStat).filter(CollegeSeasonStat.player_id == pid).all()
            bat, bat_total, bat_partial = cc.career_rows(rows, "batting")
            pit, pit_total, pit_partial = cc.career_rows(rows, "pitching")
            sections = [
                _section("Pitching", cc.PITCHING_COLUMNS, pit, pit_total, pit_partial),
                _section("Batting", cc.BATTING_COLUMNS, bat, bat_total, bat_partial),
            ]
            # pitchers first for pitchers, hitters first for everyone else
            from models import Player
            p = db.query(Player).filter(Player.player_id == pid).first()
            if p is not None and not p.is_pitcher:
                sections.reverse()
            sections = [s for s in sections if s is not None]
            if not sections:
                sections = [ui_helpers.empty_state("No college seasons on file yet." + (" Add one below." if _staff() else ""))]
            intro = ui.p("Official season stats from Pitt State and the schools he played at before. "
                         "Fall ball is in Season Stats (charted in GBO).", class_="text-muted small")
            editor = None
            if _staff():
                choices = {NEW: "+ New season"}
                for r in sorted(rows, key=lambda r: (r.season_year, r.school, r.side)):
                    choices[str(r.college_season_stat_id)] = f"{r.season_year} {r.school} ({r.side})"
                editor = ui.tags.details(
                    ui.tags.summary("Add or fix a season"),
                    ui.div(
                        ui.input_select("cc_pick", "Season", choices=choices, selected=NEW),
                        ui.output_ui("cc_form"),
                        style="padding-top:8px;",
                    ),
                    class_="gbo-seq-details", style="margin-top:12px;",
                )
            return ui_helpers.card(intro, *sections, editor, title="College Career")
        finally:
            db.close()

    def _current_row(db):
        raw = input.cc_pick() if "cc_pick" in input else NEW
        if not raw or raw == NEW:
            return None
        return db.query(CollegeSeasonStat).filter(CollegeSeasonStat.college_season_stat_id == int(raw)).first()

    @render.ui
    def cc_form():
        if not _staff():
            return None
        req("cc_pick" in input)
        side_sel = input.cc_side() if "cc_side" in input else None
        db = get_session()
        try:
            row = _current_row(db)
            side = row.side if row is not None else (side_sel or "batting")
            fields = cc.BATTING_FIELDS if side == "batting" else cc.PITCHING_FIELDS

            def val(label):
                if row is None:
                    return ""
                if label == "IP":
                    return cc.outs_to_ip(row.ip_outs) or ""
                v = getattr(row, cc.CSV_TO_COL[label])
                return "" if v is None else str(v)
            stat_inputs = [ui.input_text(f"cc_f_{lab.replace('/', '_')}", lab, value=val(lab), width="80px") for lab in fields]
            top = [
                ui.input_radio_buttons("cc_side", "Side", {"batting": "Batting", "pitching": "Pitching"}, selected=side, inline=True)
                if row is None else ui.p(ui.strong(side.title())),
                ui.layout_columns(
                    ui.input_numeric("cc_year", "Year (spring)", value=row.season_year if row else None, min=1990, max=2100),
                    ui.input_text("cc_school", "School", value=row.school if row else ""),
                    ui.input_select("cc_level", "Level", {"": "--", **{x: x for x in LEVELS}}, selected=(row.level or "") if row else ""),
                ),
            ]
            return ui.div(
                *top,
                ui.div(*stat_inputs, style="display:flex; flex-wrap:wrap; gap:6px;"),
                ui.input_text("cc_source", "Source link (optional)", value=(row.source_url or "") if row else "", width="100%"),
                ui.p("Leave a box empty if the number wasn't published -- empty is not zero. IP like 45.1.", class_="text-muted small"),
                ui.div(
                    ui.input_action_button("cc_save", "Save season", class_="btn-primary btn-sm"),
                    ui.input_action_button("cc_delete", "Delete season", class_="btn-outline-danger btn-sm") if row is not None else None,
                    style="display:flex; gap:8px;",
                ),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.cc_save)
    def _save():
        if not _staff():
            return
        db = get_session()
        try:
            pid = profile_pid(db)
            row = _current_row(db)
            side = row.side if row is not None else (input.cc_side() or "batting")
            year, school = input.cc_year(), (input.cc_school() or "").strip()
            if not year or not school:
                ui.notification_show("Year and school are required -- not saved.", type="error", duration=8)
                return
            vals = {}
            for lab in (cc.BATTING_FIELDS if side == "batting" else cc.PITCHING_FIELDS):
                fid = f"cc_f_{lab.replace('/', '_')}"
                raw = (input[fid]() if fid in input else "").strip()
                try:
                    if lab == "IP":
                        vals["ip_outs"] = cc.ip_to_outs(raw)
                    else:
                        vals[cc.CSV_TO_COL[lab]] = int(raw) if raw else None
                        if vals[cc.CSV_TO_COL[lab]] is not None and vals[cc.CSV_TO_COL[lab]] < 0:
                            raise ValueError
                except ValueError:
                    ui.notification_show(f"{lab} must be a whole number{' like 45.1' if lab == 'IP' else ''} -- not saved.",
                                         type="error", duration=8)
                    return
            dup = db.query(CollegeSeasonStat).filter_by(player_id=pid, side=side, season_year=int(year), school=school).first()
            if dup is not None and (row is None or dup.college_season_stat_id != row.college_season_stat_id):
                ui.notification_show("That season is already on file -- pick it from the list to edit it.", type="error", duration=8)
                return
            if row is None:
                row = CollegeSeasonStat(player_id=pid, side=side, created_by_user_id=app_state.user_id())
                db.add(row)
            row.season_year, row.school = int(year), school
            row.level = input.cc_level() or None
            row.source_url = (input.cc_source() or "").strip() or None
            for c, v in vals.items():
                setattr(row, c, v)
            db.commit()
            ui.notification_show(f"Saved {year} {school}.", type="message", duration=5)
            _tick.set(_tick() + 1)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.cc_delete)
    def _delete():
        if not _staff():
            return
        db = get_session()
        try:
            row = _current_row(db)
            if row is None or row.player_id != profile_pid(db):
                return
            label = f"{row.season_year} {row.school}"
            db.delete(row)
            db.commit()
            ui.notification_show(f"Deleted {label}.", type="message", duration=5)
            _tick.set(_tick() + 1)
        finally:
            db.close()
