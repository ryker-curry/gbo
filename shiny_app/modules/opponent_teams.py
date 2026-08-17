"""
GBO -- Opponent Teams module.

Direct port of pages/opponent_teams.py -- reusable opponent teams +
rosters for Game Tracking. Reference-data CRUD (create team / delete
team) uses the same form patterns as every other module; the roster
list is a bulk "type several new players, save them all" grid, which
is the first of this migration's three st.data_editor pages (Task #11)
and establishes the pattern the other two (bullpen_scripts.py,
training_routines.py) reuse.

st.data_editor -> render.data_frame, the Task #11 spike's conclusion:
Shiny's editable data_frame (shiny 1.7) supports in-place CELL editing
(editable=True) and ROW SELECTION (selection_mode="rows"), but has no
native "+" button to insert a blank row the way Streamlit's
num_rows="dynamic" does, and no per-column constrained-choice cell
editor (Streamlit's SelectboxColumn) -- cell edits are always plain
text. The pattern this settles on:
  - The working rows live in a plain Python list of dicts, held in a
    module-local reactive.Value (_roster_rows) -- NOT derived fresh
    from the grid each render, since the grid itself has no persistent
    state of its own beyond what render.data_frame's own function
    returns each time.
  - The grid's render.data_frame function rebuilds a pandas DataFrame
    from that list every time it re-renders (string dtype throughout,
    "" for blank -- avoids the original's pd.notna()/NaN handling
    entirely, since every cell is always a real string here).
  - "+Add rows" reads <grid>.data_view() (the CURRENT data with any
    in-progress cell edits already patched in) so nothing the user
    already typed is lost, appends N blank rows, and writes the result
    back to _roster_rows -- this rebuilds the grid with a fresh
    baseline, which also naturally clears .cell_patches() since
    they're now baked into the new baseline.
  - "Remove selected" reads <grid>.data_view(selected=True) (the
    selected rows' actual content) and calls
    ui_helpers.remove_selected_grid_rows() against the same
    .data_view() snapshot, same reasoning as above.
  - "Save" reads <grid>.data_view() one more time, validates the
    constrained fields (Bats/Throws) against known-valid values since
    there's no dropdown to prevent a typo at entry time, inserts one
    OpponentPlayer per non-blank-name row, and resets _roster_rows back
    to a fresh set of blanks.
  - Switching which team's roster is being edited resets _roster_rows
    to fresh blanks (mirrors the original's per-team `key=` on
    st.data_editor, which gave each team its own blank slate).
"""

import pandas as pd

from shiny import module, ui, render, reactive, req

from database import get_session
from models import OpponentTeam, OpponentPlayer, Game, GamePitch

import ui_helpers

ROSTER_COLUMNS = ["Name", "Jersey #", "Bats", "Throws", "Position", "Notes"]
BATS_CHOICES = ("R", "L", "S")
THROWS_CHOICES = ("R", "L")
BLANK_ROSTER_ROW_COUNT = 5


def _blank_roster_rows(n):
    return [{c: "" for c in ROSTER_COLUMNS} for _ in range(n)]


@module.ui
def opponent_teams_ui():
    return ui.div(
        ui_helpers.page_header("Opponent Teams"),
        ui.output_ui("teams_list"),
        ui.output_ui("create_team_section"),
        ui.output_ui("roster_team_picker"),
        ui.output_ui("roster_grid_controls"),
        ui.output_data_frame("roster_grid"),
        ui.output_ui("delete_team_section"),
        ui_helpers.page_footer(),
    )


@module.server
def opponent_teams_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _roster_rows = reactive.Value(_blank_roster_rows(BLANK_ROSTER_ROW_COUNT))
    _roster_rows_team_id = reactive.Value(None)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")

    def _access_ok():
        return app_state.is_authenticated() and app_state.role_name() in ALLOWED_ROLES

    @render.ui
    def teams_list():
        _refresh_tick()
        if not app_state.is_authenticated():
            return None
        if not _access_ok():
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            teams = db.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
            sections = [ui.p(ui.strong("Teams"))]
            if not teams:
                sections.append(ui_helpers.empty_state("No opponent teams created yet."))
            else:
                sections.append(ui.accordion(*[
                    ui.accordion_panel(
                        f"{t.team_name} ({len(t.roster)} roster player(s))",
                        ui_helpers.render_dict_table([
                            {
                                "Name": p.player_name,
                                "#": p.jersey_number or "",
                                "Bats": p.bats or "—",
                                "Throws": p.throws or "—",
                                "Position": p.position or "—",
                                "Notes": p.notes or "",
                            }
                            for p in t.roster
                        ], empty_message="No roster players added yet."),
                    )
                    for t in teams
                ], open=False, id=None))
            return ui.div(*sections)
        finally:
            db.close()

    @render.ui
    def create_team_section():
        _refresh_tick()
        if not _access_ok():
            return None
        if not app_state.can_edit_sessions():
            return ui.p("Your role has read-only access to opponent teams.", class_="text-muted small")
        return ui.div(
            ui.hr(),
            ui.p(ui.strong("Create a new team")),
            ui.input_text("new_team_name", "Team name"),
            ui.input_action_button("create_team_btn", "Create team", class_="btn-primary mt-2"),
        )

    @reactive.effect
    @reactive.event(input.create_team_btn)
    def _create_team():
        name = (input.new_team_name() or "").strip()
        if not name:
            ui.notification_show("Team name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            if db.query(OpponentTeam).filter(OpponentTeam.team_name == name).first():
                ui.notification_show(f'A team named "{name}" already exists.', type="error", duration=8)
                return
            db.add(OpponentTeam(team_name=name, created_by_user_id=app_state.user_id()))
            db.commit()
            ui.notification_show(f"Created {name}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Roster grid (bulk add)
    # -------------------------------------------------------------------

    @render.ui
    def roster_team_picker():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        db = get_session()
        try:
            teams = db.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
            if not teams:
                return ui.div(ui.hr(), ui.p(ui.strong("Add roster players")), ui.p("Create a team above first.", class_="text-muted small"))
            choices = {str(t.team_id): t.team_name for t in teams}
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Add roster players")),
                ui.input_select("roster_team_select", "Team", choices=choices),
            )
        finally:
            db.close()

    @reactive.effect
    def _reset_roster_rows_on_team_change():
        req("roster_team_select" in input)
        tid = int(input.roster_team_select())
        if tid != _roster_rows_team_id():
            _roster_rows_team_id.set(tid)
            _roster_rows.set(_blank_roster_rows(BLANK_ROSTER_ROW_COUNT))

    @render.data_frame
    def roster_grid():
        req("roster_team_select" in input)
        df = pd.DataFrame(_roster_rows(), columns=ROSTER_COLUMNS, dtype="string").fillna("")
        return render.DataGrid(df, editable=True, selection_mode="rows", width="100%")

    @render.ui
    def roster_grid_controls():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        req("roster_team_select" in input)
        return ui.div(
            ui.p(
                f"Type roster players below -- add as many rows as you need, then save. "
                f"Bats/Throws should be typed as {', '.join(BATS_CHOICES)} / {', '.join(THROWS_CHOICES)}.",
                class_="text-muted small",
            ),
            ui.input_action_button("add_roster_rows_btn", f"+ Add {BLANK_ROSTER_ROW_COUNT} rows", class_="btn-outline-secondary btn-sm"),
            ui.input_action_button("remove_roster_rows_btn", "Remove selected", class_="btn-outline-secondary btn-sm ms-1"),
            ui.input_action_button("save_roster_btn", "Save roster players", class_="btn-primary btn-sm ms-1"),
        )

    @reactive.effect
    @reactive.event(input.add_roster_rows_btn)
    def _add_roster_rows():
        current = roster_grid.data_view().to_dict("records")
        _roster_rows.set(current + _blank_roster_rows(BLANK_ROSTER_ROW_COUNT))

    @reactive.effect
    @reactive.event(input.remove_roster_rows_btn)
    def _remove_roster_rows():
        current = roster_grid.data_view().to_dict("records")
        selected = roster_grid.data_view(selected=True).to_dict("records")
        _roster_rows.set(ui_helpers.remove_selected_grid_rows(current, selected))

    @reactive.effect
    @reactive.event(input.save_roster_btn)
    def _save_roster():
        req("roster_team_select" in input)
        selected_team_id = int(input.roster_team_select())
        rows = roster_grid.data_view().to_dict("records")
        valid_rows = [r for r in rows if (r.get("Name") or "").strip()]
        if not valid_rows:
            ui.notification_show("Add at least one player with a name before saving.", type="error", duration=8)
            return

        errors = []
        for i, r in enumerate(valid_rows, start=1):
            bats = (r.get("Bats") or "").strip().upper()
            throws = (r.get("Throws") or "").strip().upper()
            if bats and bats not in BATS_CHOICES:
                errors.append(f"Row {i}: Bats \"{r.get('Bats')}\" isn't one of {', '.join(BATS_CHOICES)}.")
            if throws and throws not in THROWS_CHOICES:
                errors.append(f"Row {i}: Throws \"{r.get('Throws')}\" isn't one of {', '.join(THROWS_CHOICES)}.")
        if errors:
            for e in errors:
                ui.notification_show(e, type="error", duration=12)
            return

        db = get_session()
        try:
            added = 0
            for r in valid_rows:
                bats = (r.get("Bats") or "").strip().upper() or None
                throws = (r.get("Throws") or "").strip().upper() or None
                db.add(OpponentPlayer(
                    team_id=selected_team_id,
                    player_name=(r.get("Name") or "").strip(),
                    jersey_number=(r.get("Jersey #") or "").strip() or None,
                    bats=bats,
                    throws=throws,
                    position=(r.get("Position") or "").strip() or None,
                    notes=(r.get("Notes") or "").strip() or None,
                ))
                added += 1
            db.commit()
            ui.notification_show(f"Added {added} player(s).", type="message", duration=8)
            _roster_rows.set(_blank_roster_rows(BLANK_ROSTER_ROW_COUNT))
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Delete a team
    # -------------------------------------------------------------------

    @render.ui
    def delete_team_section():
        _refresh_tick()
        if not _access_ok() or not app_state.can_edit_sessions():
            return None
        db = get_session()
        try:
            teams = db.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
            if not teams:
                return ui.div(ui.hr(), ui.accordion(ui.accordion_panel("Delete a team", ui.p("No teams to delete.", class_="text-muted small")), open=False, id=None))
            choices = {str(t.team_id): t.team_name for t in teams}
            return ui.div(
                ui.hr(),
                ui.accordion(ui.accordion_panel(
                    "Delete a team",
                    ui.input_select("delete_team_select", "Which team?", choices=choices),
                    ui.p(
                        "This permanently deletes the team and its entire roster. Games already logged against "
                        "them keep their data (the team link just becomes empty) -- this can't be undone.",
                        class_="text-warning",
                    ),
                    ui.input_checkbox("confirm_delete_team", "Yes, I want to permanently delete this team", value=False),
                    ui.input_action_button("delete_team_btn", "Delete team", class_="btn-danger"),
                ), open=False, id=None),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_team_btn)
    def _delete_team():
        if not input.confirm_delete_team():
            ui.notification_show("Check the confirmation box before deleting.", type="error", duration=8)
            return
        req("delete_team_select" in input)
        delete_team_id = int(input.delete_team_select())

        db = get_session()
        try:
            team_to_delete = db.query(OpponentTeam).filter(OpponentTeam.team_id == delete_team_id).first()
            if team_to_delete is None:
                return
            team_name = team_to_delete.team_name

            # Unlink (don't cascade-destroy) anything that points at this
            # team or its roster -- games and logged pitches keep their
            # actual data, they just lose the team/player link.
            linked_games = db.query(Game).filter(Game.opponent_team_id == delete_team_id).all()
            for g in linked_games:
                g.opponent_team_id = None

            roster_ids = [p.opponent_player_id for p in team_to_delete.roster]
            if roster_ids:
                linked_pitches = db.query(GamePitch).filter(GamePitch.opponent_player_id.in_(roster_ids)).all()
                for gp in linked_pitches:
                    gp.opponent_player_id = None

            db.delete(team_to_delete)
            db.commit()
            msg = f"Deleted {team_name}."
            if linked_games:
                msg += f" Unlinked {len(linked_games)} game(s) that referenced it (their data is kept)."
            ui.notification_show(msg, type="message", duration=10)
            _bump_refresh()
        finally:
            db.close()
