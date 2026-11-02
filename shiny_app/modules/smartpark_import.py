"""
GBO -- Import SmartPark game (WIN Reality / Yakkertech), Oct 2026.

Ryker's call: SmartPark replaces manual game charting. Upload one game's
SmartPark CSV -> pick the (empty) GBO game it belongs to -> match any names
GBO couldn't find on the roster -> import. The whole pitch-by-pitch record
is built by services/smartpark_import.py; this module is UI only.

Built before SmartPark was installed -- the column check at the top of the
page shows any columns the mapping (services/smartpark_columns.py) didn't
recognise, which is the first thing to look at with the first real file.

Same edit rights as Game Tracking (can_edit_sessions, or Data Analyst /
Video Coordinator); guests can't import.
"""

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, SmartParkImport, Game
from services import smartpark_import as sp

import ui_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")


def _game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs")
    opp = "Intrasquad" if g.is_intrasquad else (g.opponent_team.team_name if g.opponent_team else (g.opponent_name or "Opponent"))
    home = "" if g.is_intrasquad else (" (home)" if g.is_home else (" (away)" if g.is_home is False else " (home/away not set)"))
    return f"{g.game_date:%Y-%m-%d} {loc} {opp}{home}" if not g.is_intrasquad else f"{g.game_date:%Y-%m-%d} {opp}"


@module.ui
def smartpark_import_ui():
    return ui.div(
        ui_helpers.page_header(
            "Import SmartPark Game",
            "Upload a game's SmartPark file and GBO builds the whole pitch-by-pitch chart -- count, results, "
            "location, pitch type, batted balls and every tracking reading.",
        ),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def smartpark_import_server(input, output, session, app_state):
    _tick = reactive.Value(0)
    _upload_key = reactive.Value(0)
    _last = reactive.Value(None)  # (game label, SmartParkImport id, warnings text)

    def _bump():
        _tick.set(_tick() + 1)

    def _upload_id():
        return f"sp_file_{_upload_key()}"

    def _access_ok():
        return app_state.is_authenticated() and app_state.role_name() in ALLOWED_ROLES

    def _can_edit():
        if app_state.is_guest():
            return False
        return app_state.can_edit_sessions() or app_state.role_name() in ("Data Analyst", "Video Coordinator")

    def _file_bytes():
        uid = _upload_id()
        if uid not in input:
            return None, None
        files = input[uid]()
        if not files:
            return None, None
        with open(files[0]["datapath"], "rb") as f:
            return f.read(), files[0]["name"]

    @render.ui
    def body():
        _tick()
        if not app_state.is_authenticated():
            return None
        if not _access_ok():
            return ui.p("You don't have access to this page.", class_="text-danger")
        parts = []
        if not _can_edit():
            parts.append(ui.p("Your role can preview a file but not import it.", class_="text-muted small"))
        parts += [
            ui.input_file(_upload_id(), "SmartPark game file (.csv)", accept=[".csv"]),
            ui.output_ui("file_section"),
            ui.output_ui("result_section"),
            ui.output_ui("history_section"),
        ]
        return ui.div(*parts)

    @render.ui
    def file_section():
        _tick()
        data, name = _file_bytes()
        if data is None:
            return ui.p("Export one game from SmartPark as a CSV and upload it here.", class_="text-muted small")
        try:
            info = sp.check_file(data)
        except sp.SmartParkError as e:
            return ui.p(str(e), class_="text-danger")

        db = get_session()
        try:
            games = sp.empty_games(db)
            for g in games:
                _ = g.opponent_team  # load before close
            choices = {str(g.game_id): _game_label(g) for g in games}
            default = next((str(g.game_id) for g in games if g.game_date in info["dates"]), None)
        finally:
            db.close()

        dates = ", ".join(f"{d:%b %d, %Y}" for d in info["dates"]) or "no date in file"
        check = [ui.p(f"{info['row_count']} pitches read · {dates}" + (f" · SmartPark game {info['game_uid']}" if info["game_uid"] else ""),
                      class_="text-success")]
        if info["unmapped"]:
            check.append(ui.p(ui.strong("Columns GBO doesn't use yet (kept with each pitch): "),
                              ", ".join(map(str, info["unmapped"])), class_="text-muted small"))
        parts = [ui_helpers.card(*check, title="Column check")]

        if not games:
            parts.append(ui.p("There's no empty game to import into. Create the game in Game Tracking first "
                              "(opponent, date, home/away), then come back.", class_="text-warning"))
            return ui.div(*parts)
        current = input.sp_game() if "sp_game" in input else None
        selected = current if current in choices else (default or next(iter(choices)))
        parts.append(ui.input_select("sp_game", "Which GBO game is this?", choices=choices, selected=selected, width="100%"))
        parts.append(ui.p("Only games with nothing charted are listed. Home/Away must be right -- it decides which "
                          "half-innings are Pitt State's.", class_="text-muted small"))
        parts.append(ui.output_ui("preview_section"))
        return ui.div(*parts)

    @render.ui
    def preview_section():
        _tick()
        req("sp_game" in input and input.sp_game())
        data, _ = _file_bytes()
        req(data is not None)
        db = get_session()
        try:
            try:
                info, game, plan = sp.preview(db, data, int(input.sp_game()))
            except sp.SmartParkError as e:
                return ui.p(str(e), class_="text-danger")
            opp_team_name = game.opponent_team.team_name if game.opponent_team else "the opponent"
            roster = db.query(Player).order_by(Player.active.desc(), Player.last_name, Player.first_name).all()
            roster_choices = {"": "-- pick a player --"}
            roster_choices.update({str(p.player_id): f"{p.last_name}, {p.first_name}" + ("" if p.active else " (inactive)") for p in roster})
        finally:
            db.close()

        parts = []
        if plan["unmatched"]:
            rows = []
            for i, (key, u) in enumerate(sorted(plan["unmatched"].items(), key=lambda kv: kv[1]["name"])):
                rows.append(ui.input_select(f"sp_link_{i}", f"{u['name']} ({u['role']})", choices=roster_choices, width="100%"))
            parts.append(ui_helpers.card(
                ui.p("These Pitt State names aren't on the roster under the same name. Pick who each one is -- "
                     "GBO remembers it for every future file.", class_="small"),
                *rows,
                ui.input_action_button("sp_save_links", "Save matches", class_="btn-primary mt-2") if _can_edit() else None,
                title=f"Match {len(plan['unmatched'])} player(s)"))

        n_pa = sum(1 for p in plan["pitches"] if p["ends_plate_appearance"])
        parts.append(ui_helpers.render_kpi_cards([
            {"label": "Pitches", "value": str(len(plan["pitches"]))},
            {"label": "Plate appearances", "value": str(n_pa)},
            {"label": "Pitt State" if not game.is_intrasquad else "Squad A", "value": str(plan["our_score"])},
            {"label": "Opponent" if not game.is_intrasquad else "Squad B", "value": str(plan["opponent_score"])},
        ]))
        if plan["new_opponents"] and game.opponent_team_id:
            parts.append(ui.p(f"{len(plan['new_opponents'])} opposing player(s) will be added to "
                              f"{opp_team_name}'s roster.",
                              class_="text-muted small"))
        if plan["warnings"]:
            parts.append(ui_helpers.card(*[ui.p(w, class_="small mb-1") for w in plan["warnings"]], title="Check these"))
        if plan["notes"]:
            parts.append(ui.tags.details(ui.tags.summary("Notes on this import", class_="small"),
                                         *[ui.p(n, class_="small text-muted mb-1") for n in plan["notes"]]))
        if _can_edit() and not plan["unmatched"]:
            parts.append(ui.input_action_button("sp_import", f"Import {len(plan['pitches'])} pitches", class_="btn-primary mt-2"))
        parts.append(ui.p("After importing, add intended locations, unearned runs and contact quality in Game "
                          "Tracking's Pitch Log -- SmartPark can't know those.", class_="text-muted small mt-2"))
        return ui.div(*parts)

    @reactive.effect
    @reactive.event(input.sp_save_links)
    def _save_links():
        if not _can_edit():
            return
        data, _ = _file_bytes()
        if data is None or "sp_game" not in input:
            return
        db = get_session()
        try:
            _, _, plan = sp.preview(db, data, int(input.sp_game()))
            links = {}
            for i, (key, u) in enumerate(sorted(plan["unmatched"].items(), key=lambda kv: kv[1]["name"])):
                iid = f"sp_link_{i}"
                pid = input[iid]() if iid in input else ""
                if pid:
                    for k in u["keys"]:
                        links[k] = (u["name"], int(pid))
            if not links:
                ui.notification_show("Pick a player for at least one name first.", type="warning")
                return
            sp.save_links(db, links)
            db.commit()
        except sp.SmartParkError as e:
            db.rollback()
            ui.notification_show(str(e), type="error", duration=10)
            return
        finally:
            db.close()
        ui.notification_show("Matches saved.", type="message")
        _bump()

    @reactive.effect
    @reactive.event(input.sp_import)
    def _do_import():
        if not _can_edit():
            return
        data, name = _file_bytes()
        if data is None or "sp_game" not in input:
            return
        db = get_session()
        try:
            imp = sp.import_game(db, data, name, int(input.sp_game()), app_state.user_id())
            db.commit()
            game = db.query(Game).filter(Game.game_id == imp.game_id).first()
            _ = game.opponent_team
            _last.set((_game_label(game), imp.pitch_count, imp.warnings))
        except sp.SmartParkError as e:
            db.rollback()
            ui.notification_show(str(e), type="error", duration=12)
            return
        except Exception as e:  # noqa: BLE001 -- never leave a half-written game
            db.rollback()
            ui.notification_show(f"Import failed, nothing was saved: {e}", type="error", duration=15)
            return
        finally:
            db.close()
        _upload_key.set(_upload_key() + 1)
        ui.notification_show("Game imported.", type="message")
        _bump()

    @render.ui
    def result_section():
        _tick()
        last = _last()
        if not last:
            return None
        label, n, warn = last
        return ui_helpers.card(
            ui.p(f"Imported {n} pitches into {label}. It's marked Final -- open it in Game Tracking or any game report."),
            *[ui.p(w, class_="small text-muted mb-1") for w in (warn or "").splitlines()],
            title="Last import")

    @render.ui
    def history_section():
        _tick()
        db = get_session()
        try:
            imps = db.query(SmartParkImport).order_by(SmartParkImport.uploaded_at.desc()).limit(25).all()
            rows, choices = [], {}
            for imp in imps:
                g = imp.game
                label = _game_label(g) if g else f"game {imp.game_id}"
                rows.append({"Game": label, "File": imp.original_filename, "Pitches": imp.pitch_count,
                             "Uploaded": f"{imp.uploaded_at:%Y-%m-%d %H:%M}", "Status": imp.status})
                choices[str(imp.import_id)] = f"{label} -- {imp.original_filename}"
        finally:
            db.close()
        if not rows:
            return None
        parts = [ui.h5("Past SmartPark imports", class_="gbo-section-title mt-4"), ui_helpers.render_dict_table(rows)]
        if _can_edit():
            parts.append(ui.div(
                ui.input_select("sp_delete_pick", "Undo an import", choices=choices, width="100%"),
                ui.p("Clears that game's whole pitch-by-pitch (including any edits made after the import) so the file "
                     "can be imported again.", class_="text-muted small"),
                ui.input_action_button("sp_delete", "Undo import", class_="btn-outline-danger"),
            ))
        return ui.div(*parts)

    @reactive.effect
    @reactive.event(input.sp_delete)
    def _confirm_delete():
        if not _can_edit() or "sp_delete_pick" not in input:
            return
        ui.modal_show(ui.modal(
            "This deletes every pitch in that game and sets it back to Scheduled. Continue?",
            title="Undo SmartPark import",
            footer=ui.div(ui.modal_button("Cancel"),
                          ui.input_action_button("sp_delete_confirm", "Delete pitches", class_="btn-danger")),
        ))

    @reactive.effect
    @reactive.event(input.sp_delete_confirm)
    def _do_delete():
        ui.modal_remove()
        if not _can_edit() or "sp_delete_pick" not in input:
            return
        db = get_session()
        try:
            sp.delete_import(db, int(input.sp_delete_pick()))
            db.commit()
        except sp.SmartParkError as e:
            db.rollback()
            ui.notification_show(str(e), type="error")
            return
        finally:
            db.close()
        _last.set(None)
        ui.notification_show("Import undone -- the game is empty again.", type="message")
        _bump()
