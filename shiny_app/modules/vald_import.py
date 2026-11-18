"""
GBO -- Import VALD (Nov 2026, Ryker).

Upload a VALD Hub CSV export (ForceDecks or ForceFrame -- detected from the
columns), check the names, import. Tests land in vald_tests and show on
Player Profile's VALD Testing tab. Display only: nothing here touches
Assessments, percentiles or the Bucket System.

Names: VALD spellings are often wrong (e.g. "Brooks Knapplemann", "CJ
Freeland"). Exact roster matches go straight through; every other name gets
a dropdown, pre-filled with a remembered link or GBO's closest guess, and
the confirmed pick is remembered for future files. "Skip" leaves that
athlete's tests out (e.g. someone not on the roster).

Access mirrors Import Assessments: every staff role that sees Assessments
can open it and preview; importing needs assessment edit rights (and never
in the guest demo). Parsing/writing: services/vald_import.py.
"""

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, ValdImport
from services import vald_import as vi
import ui_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Strength Coach", "Athletic Trainer", "Sports Scientist", "Data Analyst")
SKIP = "skip"


@module.ui
def vald_import_ui():
    return ui.div(
        ui_helpers.page_header(
            "Import VALD",
            "Upload a ForceDecks or ForceFrame export from VALD Hub. Tests show on each player's profile "
            "(VALD Testing tab) -- for reference, not scored.",
        ),
        ui.output_ui("body"),
        ui_helpers.page_footer(),
    )


@module.server
def vald_import_server(input, output, session, app_state):
    _tick = reactive.Value(0)
    _upload_key = reactive.Value(0)
    _last_result = reactive.Value(None)
    _error = reactive.Value(None)

    def _upload_id():
        return f"vald_file_{_upload_key()}"

    def _access_ok():
        return app_state.is_authenticated() and app_state.role_name() in ALLOWED_ROLES

    def _can_edit():
        if app_state.is_guest():
            return False
        return app_state.can_edit_assessments()

    def _file():
        uid = _upload_id()
        if uid not in input:
            return None, None
        files = input[uid]()
        if not files:
            return None, None
        with open(files[0]["datapath"], "rb") as f:
            return f.read(), files[0]["name"]

    def _pick_id(i):
        return f"vald_pick_{_upload_key()}_{i}"

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
            ui.input_file(_upload_id(), "VALD export (.csv)", accept=[".csv"]),
            ui.p("In VALD Hub: open the results for the day you tested, then Export to CSV. Upload ForceDecks and "
                 "ForceFrame files one at a time. Re-uploading the same file updates those tests instead of "
                 "adding them twice.", class_="text-muted small"),
            ui.output_ui("file_section"),
            ui.output_ui("result_section"),
            ui.output_ui("history_section"),
        ]
        return ui.div(*parts)

    def _plan():
        data, name = _file()
        if data is None:
            return None, None, None
        db = get_session()
        try:
            plan = vi.preview(db, data)
            roster = db.query(Player).order_by(Player.active.desc(), Player.last_name, Player.first_name).all()
            roster = [(p.player_id, p.name_last_first + ("" if p.active else " (inactive)")) for p in roster]
        finally:
            db.close()
        return plan, roster, name

    @render.ui
    def file_section():
        _tick()
        try:
            plan, roster, _ = _plan()
        except vi.ValdImportError as e:
            return ui.p(str(e), class_="text-danger")
        if plan is None:
            return None
        names = plan["names"]
        matches = plan["matches"]
        player_names = dict(roster)
        exact = [n for n in names if matches[n]["how"] == "exact"]
        review = [n for n in names if matches[n]["how"] != "exact"]
        dates = ", ".join(f"{d:%b %d, %Y}" for d in plan["dates"])

        parts = [ui_helpers.render_kpi_cards([
            {"label": "System", "value": plan["system"]},
            {"label": "Tests", "value": str(len(plan["tests"]))},
            {"label": "Athletes", "value": str(len(names))},
            {"label": "Test date", "value": dates if len(plan["dates"]) <= 2 else f"{len(plan['dates'])} days"},
        ])]
        parts.append(ui.p("Tests in this file: " + ", ".join(plan["test_types"]), class_="text-muted small"))

        if review:
            choices = {"": "-- pick a player --", SKIP: "Skip (don't import)"}
            choices.update({str(pid): label for pid, label in roster})
            rows = []
            for i, n in enumerate(review):
                mm = matches[n]
                pre = mm["player_id"] or mm["suggested_id"]
                with reactive.isolate():   # keep a pick across re-renders without re-rendering on every pick
                    current = input[_pick_id(i)]() if _pick_id(i) in input else None
                selected = current if current is not None and current in choices else (str(pre) if pre else "")
                hint = {"saved": "remembered from an earlier import",
                        "suggested": "closest roster name -- check it",
                        "none": "no close match on the roster"}[mm["how"]]
                rows.append(ui.div(
                    ui.input_select(_pick_id(i), ui.span(ui.strong(n), " ", ui.span(hint, class_="text-muted small")),
                                    choices=choices, selected=selected, width="100%"),
                ))
            parts.append(ui_helpers.card(
                ui.p("These VALD names aren't spelled the same as on the roster. Confirm or pick who each one is "
                     "-- GBO remembers it, so you won't have to fix that spelling again.", class_="small"),
                *rows,
                title=f"Check {len(review)} name{'s' if len(review) != 1 else ''}",
            ))
        if exact:
            parts.append(ui.tags.details(
                ui.tags.summary(f"{len(exact)} name{'s' if len(exact) != 1 else ''} matched the roster exactly", class_="small"),
                ui.p(", ".join(player_names.get(matches[n]["player_id"], n) for n in exact), class_="small text-muted"),
            ))
        if _error():
            parts.append(ui.p(_error(), class_="text-danger"))
        if _can_edit():
            parts.append(ui.input_action_button("vald_import_btn", f"Import {len(plan['tests'])} tests", class_="btn-primary mt-2"))
        return ui.div(*parts)

    @reactive.effect
    @reactive.event(input.vald_import_btn)
    def _do_import():
        if not _can_edit():
            return
        _error.set(None)
        data, fname = _file()
        if data is None:
            return
        db = get_session()
        try:
            plan = vi.preview(db, data)
            review = [n for n in plan["names"] if plan["matches"][n]["how"] != "exact"]
            picks, missing = {}, []
            for n in plan["names"]:
                mm = plan["matches"][n]
                if mm["how"] == "exact":
                    picks[n] = mm["player_id"]
            for i, n in enumerate(review):
                v = input[_pick_id(i)]() if _pick_id(i) in input else ""
                if v == SKIP:
                    picks[n] = None
                elif v:
                    picks[n] = int(v)
                else:
                    missing.append(n)
            if missing:
                _error.set("Pick a player (or Skip) for: " + ", ".join(missing))
                return
            result = vi.commit(db, data, fname, picks, user_id=app_state.user_id())
        except vi.ValdImportError as e:
            db.rollback()
            _error.set(str(e))
            return
        except Exception as e:
            db.rollback()
            _error.set(f"Import failed, nothing was saved. Underlying error: {e}")
            return
        finally:
            db.close()
        _last_result.set((plan["system"], fname, result))
        _upload_key.set(_upload_key() + 1)
        _tick.set(_tick() + 1)

    @render.ui
    def result_section():
        _tick()
        r = _last_result()
        if not r:
            return None
        system, fname, res = r
        msg = f"Imported {system}: {res['created']} new test{'s' if res['created'] != 1 else ''}"
        if res["updated"]:
            msg += f", {res['updated']} updated"
        msg += "."
        extra = f" Skipped: {', '.join(res['skipped_names'])}." if res["skipped_names"] else ""
        return ui_helpers.card(ui.p(msg + extra, class_="text-success mb-1"),
                               ui.p("See them on Player Profile > VALD Testing.", class_="text-muted small mb-0"),
                               title="Done")

    @render.ui
    def history_section():
        _tick()
        if not _access_ok():
            return None
        db = get_session()
        try:
            imps = db.query(ValdImport).order_by(ValdImport.created_at.desc()).limit(10).all()
            rows = [(i.created_at, i.system, i.file_name, i.first_test_date, i.last_test_date, i.test_count) for i in imps]
        finally:
            db.close()
        if not rows:
            return None
        items = []
        for created, system, fname, d1, d2, n in rows:
            when = f"{d1:%b %d, %Y}" if d1 and d1 == d2 else (f"{d1:%b %d} - {d2:%b %d, %Y}" if d1 and d2 else "—")
            items.append(ui.div(ui.div(when, class_="gbo-li-dt"),
                                ui.div(f"{system} · {n} tests" + (f" · {fname}" if fname else "")), class_="gbo-li"))
        return ui_helpers.card(*items, title="Recent VALD imports")
