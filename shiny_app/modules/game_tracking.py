"""
GBO -- Game Tracking module (the last of "the big 3" pages).

Direct port of pages/game_tracking.py -- the real, live, pitch-by-pitch
game tracking sheet, both sides of the ball (our batting AND our
pitching share one GamePitch table via is_our_team_batting, matching
Ryker's own tracking sheet). Season management, a season filter + game
picker, new-game creation, and (once a game is active) five sections --
Live Tracking, Lineup & Setup, Video Review, Pitch Log, Manage Game --
ported from the original's five st.tabs into a single ui.navset_tab with
each tab's body as its own nested ui.output_ui, same nesting technique
bullpen_tracking.py's pitch_video_section/pitch_video_body already
established (an output_ui can live inside another dynamically-rendered
render.ui, as long as the inner one is a real top-level registered
output).

Deliberate UX simplifications made porting this page (disclosed here,
same as every other such deviation elsewhere in this migration):

  1. **Numeric coordinate entry with a live static-preview image,
     instead of click-to-place.** The original captures intended pitch
     location, actual pitch location (Video Review), and batted-ball
     landing spot via st.plotly_chart(on_select="rerun") -- a real
     click on the figure. Shiny's equivalent would be shinywidgets'
     FigureWidget.on_click(), which is untested anywhere else in this
     migration and hard to verify without a live browser session. Since
     strike_zone.py/field_location.py already expose pure, Streamlit-
     free figure builders (build_zone_selector_figure/
     build_field_selector_figure) specifically so a UI layer can attach
     its own click handling, this page instead pairs a plain
     ui.input_numeric() pair (plate side/height, or field x/y) with a
     read-only preview image (chart_helpers.fig_to_img wrapping those
     same builders) that updates live as the numbers are typed. Less
     tactile than tapping the exact spot, but the same coordinate
     system, the same stored data, and no behavioral difference to
     anything downstream (execution %, spray charts, etc.).
  2. **Live cross-slot lineup exclusion IS implemented**, matching the
     original -- once a player is picked in one batting-order slot, he
     disappears from every OTHER slot's dropdown for that squad. This
     was initially simplified away (Shiny doesn't rerun the whole page
     on every keystroke the way Streamlit does) in favor of a save-time
     duplicate check alone; `_sync_lineup_exclusions` (inside
     `_register_squad_lineup`) restores the live behavior via a plain
     effect that watches every slot's current pick and pushes filtered
     choices to the others through `ui.update_select()`. The save-time
     duplicate check stays in place too, as a second line of defense.

Feature addition beyond the original page (requested after the initial
port): Squad B now gets a saved starting pitcher too, mirroring Squad
A's `games.starting_pitcher_id` via a new `games.squad_b_starting_pitcher_id`
column (see migrations/migrate_squad_b_starting_pitcher.py -- must be
run against the database before this field is usable). Unlike Squad A,
Squad B still has no formal pitching-change history (no parallel
PitchingChange-style table was added) -- `get_current_squad_b_pitcher_id()`
approximates it by falling back to the most recently recorded Squad B
pitcher in this game's own pitches, then to the saved starting pick.
This is used purely as a DEFAULT for the live per-plate-appearance
opposing-pitcher picker; the coach can still override it any at-bat.

Reactive design, worth calling out specifically:
  - `_active_game_id` replaces the original's st.query_params["game_id"]
    round-trip (see the migration plan's translation table) -- same
    local-reactive-value-as-query-param-replacement technique as every
    other page/session picker in this migration (_active_bullpen_id,
    _active_session_id, _target_bullpen_id), synced from game_select via
    a plain (non-evented) effect.
  - `_pa_tick` is a NARROW reactive.Value, bumped ONLY inside
    _record_pitch and _confirm_pitching_change -- deliberately NOT the
    broad `_refresh_tick` every other block on this page (and every
    other tab: Lineup & Setup, Video Review, Pitch Log, Manage Game)
    depends on. The Live Tracking cluster (game_state_display,
    who_is_up_*, pitch_type_and_outcome_picker, the location/result
    blocks, record_pitch_controls) depends on `_pa_tick` instead, so an
    unrelated refresh elsewhere on the page (saving a lineup, uploading
    video, changing game status) never remounts -- and so never
    silently resets -- an in-progress pitch entry. This replaces the
    original's st.session_state["gt_suggestion_applied_for_count"]
    guard, which existed for exactly the same reason under Streamlit's
    always-rerun-everything model.
  - Every place two widgets have a "read A to decide/default B"
    relationship (bullpen type -> script list, pitch outcome -> which
    extra fields show, AB outcome -> suggested outs/bases/runs, intended
    coordinates -> the preview image, etc.) is split into two blocks --
    one that defines the widget, a separate one that reads it -- per
    this migration's standing "never read a client input from the same
    render block that defines it" rule. Several of these (pitch-
    outcome-dependent fields, the AB-outcome-dependent result fields)
    also get re-validated at submit time from the CURRENT pitch_outcome
    value rather than trusting "was this id ever sent by the client" --
    Shiny keeps an input's last known value after its widget is removed
    from the DOM, so a naive `"x" in input` check could otherwise read
    a stale value left over from an outcome the coach has since changed
    away from (e.g. contact quality lingering after switching to
    "Ball"). _record_pitch and result_fields_body both recompute
    `ends_pa`/applicability fresh from pitch_outcome_select every time,
    rather than trusting field presence alone.
  - Squad A and Squad B's lineup setup/display/save is ONE set of
    functions, registered twice (via `_register_squad_lineup("A", ...)`
    / `_register_squad_lineup("B", ...)` at server-setup time) using
    `@output(id=...)` for the programmatic per-squad output ids -- same
    technique player_bullpens.py/player_hitting.py use for their own
    per-row dynamic outputs, just applied to a FIXED set of exactly two
    squads (not a lazily-registered, data-dependent set).
  - "Match clip to pitch" buttons (Video Review's bulk-upload section)
    are the one genuinely unbounded, data-dependent button set on this
    page -- lazily registered via _registered_clip_match_ids /
    _register_clip_match_handler, same pattern as bullpen_tracking.py's
    "Link" buttons for its own Rapsodo-linking section.

Restricted to Administrator/Head Coach/Coach/Sports Scientist/Data
Analyst (matches nav.py's Game Operations section) -- Data Analyst gets
real edit rights here specifically (can_edit_sessions is overridden the
same way the original did it, without touching the role's broader
can_edit_sessions flag used elsewhere), same as the original.

Milestone 1 -- "Reliability + speed during a live game" (see the plan
doc this shipped from), added on top of the original port, no schema
changes:
  - **Undo Last Pitch** -- a button next to Record Pitch in Live
    Tracking's record_pitch_controls. Deletes the single most-recent
    GamePitch row for the active game and, if it had ended a PA with
    runs scored, reverses that run adjustment on Game.our_score/
    opponent_score (the only piece of state this page persists outside
    GamePitch itself -- everything else, outs/bases/count/inning, is
    re-derived fresh from the remaining GamePitch rows by
    compute_current_state() on the next render, same as it always is).
    See _undo_last_pitch.
  - **Duplicate-submission guard** -- a session-scoped `_is_submitting`
    reactive.Value wraps _record_pitch (the real logic lives in
    _do_record_pitch now; _record_pitch is a thin guard wrapper) so a
    second Record Pitch click that arrives while the first is still
    being written is dropped rather than inserting a second pitch.
    Scoped to this page's record button only, per the Milestone 1 plan
    -- the same gap exists on hitter_tracking.py/bullpen_tracking.py's
    record buttons and is intentionally out of scope here.
  - **Live Pitch Sequence** -- a small table (live_pitch_sequence_display)
    showing only the pitches of the *current, still-open* plate
    appearance, computed by _current_pa_pitches() (everything after the
    last pitch that ended a PA). Depends on `_pa_tick`, not the broader
    `_refresh_tick`, same reasoning as the rest of the Live Tracking
    cluster.
  - **Live Game Dashboard** -- KPI cards (live_game_dashboard) at the
    top of Live Tracking: score/inning/outs/count, plus the current
    pitcher's and current batter's in-game line, reusing
    game_stats.py's get_pitching_pitches/compute_pitching_line and
    get_batting_pitches/compute_batting_line rather than computing new
    stats. Those functions only know about players in our own roster
    (see game_stats.py's docstring), so a true external opponent's
    pitcher/batter (non-intrasquad, not one of our players) shows a
    name-less "not tracked" note instead of a stat line --
    _resolve_current_pitcher_id_for_stats/_resolve_current_hitter_id_for_stats
    make that distinction explicit.
  - **Refresh recovery**: unchanged/no new code -- already-committed
    pitch and game state survive a browser refresh today, since
    compute_current_state() derives everything from committed GamePitch
    rows rather than session state. Only the active-game dropdown
    selection (_active_game_id) and any not-yet-submitted in-progress
    pitch entry are lost on refresh; picking the game again from
    game_picker immediately restores full context.
"""

import uuid
from datetime import date

from shiny import module, ui, render, reactive, req
from sqlalchemy.orm import joinedload

from database import get_session
from r2_client import upload_video_to_r2
import strike_zone
import field_location
from models import (
    Player, Position, PitchType, Game, GameLineupSlot, GamePitch, RunExpectancy,
    OpponentTeam, OpponentPlayer, Season, PitchingChange, PlayerPitchArsenal, OpponentLineupSlot,
    GameVideoClip,
)
from game_stats import get_pitching_pitches, get_batting_pitches, compute_pitching_line, compute_batting_line

import ui_helpers
import chart_helpers

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")

PITCH_OUTCOMES = ["Ball", "Called Strike", "Swing and Miss", "Foul", "In Play", "HBP"]
AB_OUTCOMES = [
    "K", "BB", "HBP", "1B", "2B", "3B", "HR", "E", "FC",
    "Sac Bunt", "Sac Fly", "Groundout", "Flyout", "Lineout", "Double Play",
]
CONTACT_QUALITY_OPTIONS = ["Barrel", "Solid", "Weak", "Miss"]

GAME_VIDEO_SUBFOLDER = "pitch-videos/"  # same folder Bullpen/Hitter Tracking's clips upload into, inside the one shared R2 bucket


# -----------------------------------------------------------------------
# Pure helpers -- ported verbatim from pages/game_tracking.py (none of
# these touched Streamlit in the original either).
# -----------------------------------------------------------------------

def build_re_lookup(db):
    rows = db.query(RunExpectancy).all()
    return {(r.outs, r.bases, r.count): float(r.re_value) for r in rows}


def compute_re_and_rv(re_lookup, outs_before, bases_before, balls_before, strikes_before,
                       ends_pa, outs_after, bases_after, runs_scored, new_balls=None, new_strikes=None):
    re_before = re_lookup.get((outs_before, bases_before, f"{balls_before}-{strikes_before}"))

    if ends_pa:
        if outs_after is not None and outs_after >= 3:
            re_after = 0.0
        else:
            re_after = re_lookup.get((outs_after, bases_after, "0-0"))
    else:
        re_after = re_lookup.get((outs_before, bases_before, f"{new_balls}-{new_strikes}"))

    run_value = None
    if re_before is not None and re_after is not None:
        run_value = round((re_after + runs_scored) - re_before, 3)

    return re_before, re_after, run_value


def get_current_pitcher_id(game):
    changes = sorted(game.pitching_changes, key=lambda c: c.pitch_sequence_at_entry)
    if changes:
        return changes[-1].player_id
    return game.starting_pitcher_id


def get_current_squad_b_pitcher_id(game):
    """Squad B has no formal pitching-change history (unlike Squad A's
    PitchingChange-backed get_current_pitcher_id above) -- mirrors the
    same "most recent, falling back to the saved starting pick" idea
    using GamePitch history itself instead: the most recently recorded
    Squad B pitcher from a plate appearance we (Squad A) batted, or the
    saved games.squad_b_starting_pitcher_id if none has been recorded
    yet this game. Used only as a DEFAULT for the live opposing-pitcher
    picker -- always overridable per plate appearance, same as before."""
    our_batting_pitches = sorted(
        [p for p in game.pitches if p.is_our_team_batting and p.opponent_our_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if our_batting_pitches:
        return our_batting_pitches[-1].opponent_our_player_id
    return game.squad_b_starting_pitcher_id


def get_arsenal_pitch_type_names(db, pitcher_id, all_pitch_types):
    arsenal = (
        db.query(PlayerPitchArsenal)
        .filter(PlayerPitchArsenal.player_id == pitcher_id, PlayerPitchArsenal.active.is_(True))
        .all()
    )
    if not arsenal:
        return [pt.type_name for pt in all_pitch_types]
    arsenal_type_ids = {a.pitch_type_id for a in arsenal}
    return [pt.type_name for pt in all_pitch_types if pt.pitch_type_id in arsenal_type_ids]


def suggest_next_our_batter(game, lineup_slots):
    if not lineup_slots:
        return None
    our_pa_endings = sorted(
        [p for p in game.pitches if p.is_our_team_batting and p.ends_plate_appearance],
        key=lambda p: p.pitch_sequence,
    )
    if not our_pa_endings:
        return lineup_slots[0].player_id
    last_batter_id = our_pa_endings[-1].our_player_id
    last_slot = next((s for s in lineup_slots if s.player_id == last_batter_id), None)
    if last_slot is None:
        return lineup_slots[0].player_id
    slot_orders = sorted(s.batting_order for s in lineup_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    return next((s.player_id for s in lineup_slots if s.batting_order == next_order), lineup_slots[0].player_id)


def suggest_next_squad_b_batter(game, squad_b_slots):
    if not squad_b_slots:
        return None
    squad_b_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_our_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if not squad_b_pa_endings:
        return squad_b_slots[0].player_id
    last_batter_id = squad_b_pa_endings[-1].opponent_our_player_id
    last_slot = next((s for s in squad_b_slots if s.player_id == last_batter_id), None)
    if last_slot is None:
        return squad_b_slots[0].player_id
    slot_orders = sorted(s.batting_order for s in squad_b_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    return next((s.player_id for s in squad_b_slots if s.batting_order == next_order), squad_b_slots[0].player_id)


def suggest_next_opponent_order(game):
    opp_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_batting_order],
        key=lambda p: p.pitch_sequence,
    )
    if not opp_pa_endings:
        return 1
    last_order = opp_pa_endings[-1].opponent_batting_order
    return (last_order % 9) + 1


def suggest_next_opponent_lineup_player(game, opponent_lineup_slots):
    if not opponent_lineup_slots:
        return None
    opp_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if not opp_pa_endings:
        return opponent_lineup_slots[0].opponent_player_id
    last_batter_id = opp_pa_endings[-1].opponent_player_id
    last_slot = next((s for s in opponent_lineup_slots if s.opponent_player_id == last_batter_id), None)
    if last_slot is None:
        return opponent_lineup_slots[0].opponent_player_id
    slot_orders = sorted(s.batting_order for s in opponent_lineup_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    return next((s.opponent_player_id for s in opponent_lineup_slots if s.batting_order == next_order), opponent_lineup_slots[0].opponent_player_id)


def bases_display(bases_str):
    if not bases_str:
        return "Empty"
    labels = []
    if bases_str[0] == "1":
        labels.append("1st")
    if bases_str[1] == "1":
        labels.append("2nd")
    if bases_str[2] == "1":
        labels.append("3rd")
    return ", ".join(labels) if labels else "Empty"


def suggest_after_state(ab_outcome, bases_before, outs_before):
    b = list(bases_before or "000")
    outs = outs_before
    runs = 0

    def force_advance():
        nonlocal b, runs
        if b[0] == "1":
            if b[1] == "1":
                if b[2] == "1":
                    runs += 1
                b[2] = "1"
            b[1] = "1"
        b[0] = "1"

    if ab_outcome in ("K", "Groundout", "Flyout", "Lineout"):
        outs += 1
    elif ab_outcome == "Double Play":
        outs += 2
        if b[0] == "1":
            b[0] = "0"
    elif ab_outcome in ("BB", "HBP"):
        force_advance()
    elif ab_outcome == "1B":
        if b[2] == "1":
            runs += 1
            b[2] = "0"
        if b[1] == "1":
            b[2] = "1"
            b[1] = "0"
        if b[0] == "1":
            b[1] = "1"
        b[0] = "1"
    elif ab_outcome == "2B":
        if b[2] == "1":
            runs += 1
            b[2] = "0"
        if b[1] == "1":
            runs += 1
            b[1] = "0"
        if b[0] == "1":
            b[2] = "1"
            b[0] = "0"
        b[1] = "1"
    elif ab_outcome == "3B":
        runs += b.count("1")
        b = ["0", "0", "1"]
    elif ab_outcome == "HR":
        runs += b.count("1") + 1
        b = ["0", "0", "0"]
    elif ab_outcome == "Sac Fly":
        outs += 1
        if b[2] == "1":
            runs += 1
            b[2] = "0"
    elif ab_outcome == "Sac Bunt":
        outs += 1
        if b[0] == "1" and b[1] != "1":
            b[1] = "1"
            b[0] = "0"
    elif ab_outcome == "FC":
        if b[0] == "1":
            b[0] = "0"
        outs += 1
        force_advance()
    elif ab_outcome == "E":
        force_advance()

    return outs, "".join(b), runs


def compute_current_state(pitches):
    if not pitches:
        return {
            "inning": 1, "is_our_batting": True, "outs": 0, "bases": "000",
            "balls": 0, "strikes": 0, "pa_pitch_number": 1, "new_pa": True,
        }
    last = pitches[-1]
    if not last.ends_plate_appearance:
        balls = (last.balls_before or 0) + (1 if last.pitch_outcome == "Ball" else 0)
        strikes = (last.strikes_before or 0)
        if last.pitch_outcome in ("Called Strike", "Swing and Miss"):
            strikes += 1
        elif last.pitch_outcome == "Foul" and strikes < 2:
            strikes += 1
        return {
            "inning": last.inning, "is_our_batting": last.is_our_team_batting,
            "outs": last.outs_before, "bases": last.bases_before,
            "balls": balls, "strikes": strikes,
            "pa_pitch_number": (last.pa_pitch_number or 1) + 1, "new_pa": False,
            "current_our_player": last.our_player_id,
            "current_opp_hand": last.opponent_hand,
            "current_opp_order": last.opponent_batting_order,
            "current_opp_player": last.opponent_player_id,
            "current_opp_our_player": last.opponent_our_player_id,
        }
    else:
        outs = last.outs_after if last.outs_after is not None else last.outs_before
        bases = last.bases_after if last.bases_after is not None else "000"
        inning = last.inning
        is_our_batting = last.is_our_team_batting
        if outs >= 3:
            inning += 1
            is_our_batting = not is_our_batting
            outs = 0
            bases = "000"
        return {
            "inning": inning, "is_our_batting": is_our_batting,
            "outs": outs, "bases": bases,
            "balls": 0, "strikes": 0, "pa_pitch_number": 1, "new_pa": True,
        }


def _current_pa_pitches(pitches):
    """Trailing pitches of the still-open plate appearance -- everything
    after the last pitch that ended a PA (sorted ascending, same order
    as the `pitches` argument). Naturally empty right when a PA just
    ended (compute_current_state's `new_pa` is True then, since the
    very last pitch itself has ends_plate_appearance=True and the walk
    below stops immediately), non-empty mid-PA. Used by
    live_pitch_sequence_display."""
    current = []
    for p in reversed(pitches):
        if p.ends_plate_appearance:
            break
        current.append(p)
    return list(reversed(current))


def _resolve_current_pitcher_id_for_stats(game, state):
    """The player_id (from OUR roster) currently on the mound, for
    live_game_dashboard's stat line -- always resolvable when we're the
    ones pitching (get_current_pitcher_id), and resolvable when a Squad
    B intrasquad pitcher is up (get_current_squad_b_pitcher_id, also
    always one of our own players). Returns None only when we're
    batting against a genuine external opponent, whose pitcher is an
    OpponentPlayer, not a Player -- game_stats.py's
    get_pitching_pitches() has no way to look that player up (see its
    docstring), so there's no stat line to show for them."""
    if state["is_our_batting"]:
        if game.is_intrasquad:
            return get_current_squad_b_pitcher_id(game)
        return None
    return get_current_pitcher_id(game)


def _resolve_current_hitter_id_for_stats(game, state, squad_a_slots, squad_b_slots):
    """Mirrors _resolve_current_pitcher_id_for_stats for the current
    batter. Mid-PA (state['new_pa'] is False), the committed identity
    is already on `state`. At the start of a new PA, nothing's been
    committed yet, so this falls back to the same suggestion the
    who's-up picker itself shows (suggest_next_our_batter /
    suggest_next_squad_b_batter) -- a reasonable "who's up" answer for
    a dashboard even before the coach has explicitly confirmed it.
    Returns None for a genuine external opponent's batter (an
    OpponentPlayer, not one of our own Players -- no game_stats.py line
    available for them, same reasoning as the pitcher side)."""
    if not state["new_pa"]:
        if state["is_our_batting"]:
            return state.get("current_our_player")
        if game.is_intrasquad:
            return state.get("current_opp_our_player")
        return None
    if state["is_our_batting"]:
        return suggest_next_our_batter(game, squad_a_slots) if squad_a_slots else None
    if game.is_intrasquad:
        return suggest_next_squad_b_batter(game, squad_b_slots) if squad_b_slots else None
    return None


def _ends_plate_appearance(state, outcome):
    new_balls = state["balls"] + (1 if outcome == "Ball" else 0)
    new_strikes = state["strikes"]
    if outcome in ("Called Strike", "Swing and Miss"):
        new_strikes += 1
    elif outcome == "Foul" and new_strikes < 2:
        new_strikes += 1
    ends_pa = outcome == "In Play" or outcome == "HBP" or new_balls >= 4 or (new_strikes >= 3 and outcome != "Foul")
    return ends_pa, new_balls, new_strikes


def _opponent_display_name(g):
    if g.opponent_team:
        return g.opponent_team.team_name
    return g.opponent_name or "Unknown opponent"


def _game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
    season_label = f"[{g.season.season_name}] " if g.season else ""
    return f"{season_label}{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status}) — {g.our_score}-{g.opponent_score}"


class _ShinyFileAdapter:
    """Adapts one ui.input_file() entry to the .name/.getvalue()/.type
    shape upload_video_to_r2() expects -- same adapter duplicated in
    every video-handling module in this migration (hitter_tracking.py,
    training_routines.py, bullpen_tracking.py), per that convention."""
    def __init__(self, file_info: dict):
        self.name = file_info["name"]
        self.type = file_info.get("type")
        self._datapath = file_info["datapath"]

    def getvalue(self) -> bytes:
        with open(self._datapath, "rb") as f:
            return f.read()


def _upload_game_video_clip(file_info: dict, identifier: str):
    try:
        return upload_video_to_r2(_ShinyFileAdapter(file_info), identifier, bucket_subfolder=GAME_VIDEO_SUBFOLDER)
    except Exception as e:
        ui.notification_show(
            f"Video upload failed: {e}. Make sure Cloudflare R2 is configured "
            f"(R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- "
            f"see r2_client.py's docstring for setup steps).",
            type="error", duration=12,
        )
        return None


@module.ui
def game_tracking_ui():
    return ui.div(
        ui_helpers.page_header("Game Tracking"),
        ui.output_ui("season_manage_section"),
        ui.output_ui("season_filter_picker"),
        ui.output_ui("game_picker"),
        ui.output_ui("new_game_season_picker"),
        ui.output_ui("new_game_opponent_picker"),
        ui.output_ui("new_game_form_body"),
        ui.output_ui("no_game_notice"),
        ui.output_ui("game_header"),
        ui.output_ui("game_tabs"),
        ui_helpers.page_footer(),
    )


@module.server
def game_tracking_server(input, output, session, app_state):
    _refresh_tick = reactive.Value(0)
    _pa_tick = reactive.Value(0)
    _active_game_id = reactive.Value(None)
    _vr_current_pitch_id = reactive.Value(None)
    _registered_clip_match_ids = set()
    _is_submitting = reactive.Value(False)  # duplicate-submission guard for _record_pitch, see module docstring

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _bump_pa():
        _pa_tick.set(_pa_tick() + 1)

    def _access_ok():
        if not app_state.is_authenticated():
            return False
        return app_state.role_name() in ALLOWED_ROLES

    def _can_edit():
        return app_state.can_edit_sessions() or app_state.role_name() == "Data Analyst"

    def _load_tracking_context(db, game_id):
        game = (
            db.query(Game)
            .options(joinedload(Game.pitching_changes))
            .filter(Game.game_id == game_id)
            .first()
        )
        if game is None:
            return None
        pitches = sorted(game.pitches, key=lambda p: p.pitch_sequence)
        squad_a_slots = (
            db.query(GameLineupSlot).options(joinedload(GameLineupSlot.player))
            .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == "A")
            .order_by(GameLineupSlot.batting_order).all()
        )
        squad_b_slots = (
            db.query(GameLineupSlot).options(joinedload(GameLineupSlot.player))
            .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == "B")
            .order_by(GameLineupSlot.batting_order).all()
        )
        opponent_lineup_slots = (
            db.query(OpponentLineupSlot).options(joinedload(OpponentLineupSlot.opponent_player))
            .filter(OpponentLineupSlot.game_id == game_id)
            .order_by(OpponentLineupSlot.batting_order).all()
        )
        state = compute_current_state(pitches)
        return game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state

    # -------------------------------------------------------------------
    # Seasons + game picker
    # -------------------------------------------------------------------

    @render.ui
    def season_manage_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        db = get_session()
        try:
            seasons = db.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
            children = []
            if seasons:
                rows = [{"Season": s.season_name, "Official": "Yes" if s.is_official else "No (practice/fall)", "Games": len(s.games)} for s in seasons]
                children.append(ui_helpers.render_dict_table(rows))
            children.append(ui.input_text("new_season_name", "New season name", placeholder="e.g. Fall 2026, Spring 2027"))
            children.append(ui.input_checkbox("new_season_official", "Official (counts toward real record -- uncheck for fall/practice)", value=True))
            children.append(ui.input_action_button("create_season_btn", "Create season", class_="btn-primary mt-2"))
            return ui.accordion(ui.accordion_panel("Manage seasons", *children), open=False, id=None)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.create_season_btn)
    def _create_season():
        name = (input.new_season_name() or "").strip()
        if not name:
            ui.notification_show("Season name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            if db.query(Season).filter(Season.season_name == name).first():
                ui.notification_show(f'A season named "{name}" already exists.', type="error", duration=8)
                return
            db.add(Season(season_name=name, is_official=input.new_season_official(), created_by_user_id=app_state.user_id()))
            db.commit()
            ui.notification_show(f"Created season: {name}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def season_filter_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        db = get_session()
        try:
            seasons = db.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
            choices = {"": "-- All seasons --"}
            choices.update({str(s.season_id): s.season_name + ("" if s.is_official else " (practice/fall, not official)") for s in seasons})
            return ui.div(ui.hr(), ui.input_select("season_filter_select", "Season", choices=choices))
        finally:
            db.close()

    @render.ui
    def game_picker():
        _refresh_tick()
        if not _access_ok():
            return None
        req("season_filter_select" in input)
        season_filter_raw = input.season_filter_select()
        db = get_session()
        try:
            games_query = db.query(Game).options(joinedload(Game.season), joinedload(Game.opponent_team)).order_by(Game.game_date.desc())
            if season_filter_raw:
                games_query = games_query.filter(Game.season_id == int(season_filter_raw))
            games = games_query.all()
            choices = {"": "-- Start a new game --"}
            for g in games:
                choices[str(g.game_id)] = _game_label(g)
            active_id = _active_game_id()
            selected = str(active_id) if active_id is not None and str(active_id) in choices else ""
            return ui.input_select("game_select", "Game", choices=choices, selected=selected)
        finally:
            db.close()

    @reactive.effect
    def _sync_active_game_id():
        req("game_select" in input)
        raw = input.game_select()
        _active_game_id.set(int(raw) if raw else None)

    # -------------------------------------------------------------------
    # New game
    # -------------------------------------------------------------------

    @render.ui
    def new_game_season_picker():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is not None:
            return None
        db = get_session()
        try:
            seasons = db.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
            if not seasons:
                return ui.div(
                    ui.h5("Start a new game", class_="gbo-section-title"),
                    ui.p('Create a season above first (e.g. "Fall 2026") before starting a game.', class_="text-warning small"),
                )
            choices = {str(s.season_id): s.season_name + ("" if s.is_official else " (practice/fall, not official)") for s in seasons}
            return ui.div(
                ui.h5("Start a new game", class_="gbo-section-title"),
                ui.input_select("new_game_season_choice", "Season", choices=choices),
                ui.input_checkbox("new_game_intrasquad", "Intrasquad scrimmage (Squad A vs Squad B, our own roster on both sides)"),
            )
        finally:
            db.close()

    @render.ui
    def new_game_opponent_picker():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is not None:
            return None
        req("new_game_intrasquad" in input)
        if input.new_game_intrasquad():
            return None
        db = get_session()
        try:
            opponent_teams = db.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
            choices = {"": "-- One-off opponent, just type a name --"}
            choices.update({str(t.team_id): t.team_name for t in opponent_teams})
            return ui.div(
                ui.input_select("new_game_opponent_team_choice", "Opponent", choices=choices),
                ui.p("Not in your list yet? Add them as a reusable team on Opponent Teams for next time -- or just type a name below for a one-off.", class_="text-muted small"),
            )
        finally:
            db.close()

    @render.ui
    def new_game_form_body():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is not None:
            return None
        req("new_game_season_choice" in input)
        req("new_game_intrasquad" in input)
        is_intrasquad = input.new_game_intrasquad()
        opponent_team_raw = (input.new_game_opponent_team_choice() if "new_game_opponent_team_choice" in input else "") if not is_intrasquad else ""

        children = []
        if not is_intrasquad and not opponent_team_raw:
            children.append(ui.input_text("new_game_opponent_name", "Opponent name"))
        children.append(ui.input_date("new_game_date", "Date", value=date.today()))
        children.append(ui.input_select("new_game_location", "Location", choices=["Home", "Away", "Neutral site"], selected="Home"))
        children.append(ui.input_action_button("create_game_btn", "Create game", class_="btn-primary mt-2"))
        return ui.div(*children)

    @reactive.effect
    @reactive.event(input.create_game_btn)
    def _create_game():
        is_intrasquad = input.new_game_intrasquad()
        opponent_team_raw = (input.new_game_opponent_team_choice() if "new_game_opponent_team_choice" in input else "") if not is_intrasquad else ""
        opponent_name_raw = (input.new_game_opponent_name() if "new_game_opponent_name" in input else "") or ""
        if not is_intrasquad and not opponent_team_raw and not opponent_name_raw.strip():
            ui.notification_show("Opponent name is required.", type="error", duration=8)
            return
        db = get_session()
        try:
            season_id = int(input.new_game_season_choice())
            opponent_team_id = int(opponent_team_raw) if opponent_team_raw else None
            location_choice = input.new_game_location()
            is_home = None if is_intrasquad else {"Home": True, "Away": False, "Neutral site": None}[location_choice]
            new_game = Game(
                season_id=season_id,
                opponent_team_id=opponent_team_id if not is_intrasquad else None,
                opponent_name=(opponent_name_raw.strip() if opponent_name_raw else None) if not is_intrasquad else "Intrasquad Scrimmage",
                is_intrasquad=is_intrasquad,
                game_date=input.new_game_date(),
                is_home=is_home,
                status="Scheduled",
                created_by_user_id=app_state.user_id(),
            )
            db.add(new_game)
            db.commit()
            _active_game_id.set(new_game.game_id)
            if is_intrasquad:
                display_name = "Intrasquad Scrimmage"
            elif opponent_team_id:
                opp = db.query(OpponentTeam).filter(OpponentTeam.team_id == opponent_team_id).first()
                display_name = opp.team_name if opp else "opponent"
            else:
                display_name = opponent_name_raw.strip()
            season = db.query(Season).filter(Season.season_id == season_id).first()
            ui.notification_show(f"Created game vs {display_name} ({season.season_name if season else ''}).", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def no_game_notice():
        _refresh_tick()
        if not _access_ok():
            return None
        if _active_game_id() is not None or _can_edit():
            return None
        return ui.p("Your role has read-only access to game tracking.", class_="text-muted")

    # -------------------------------------------------------------------
    # Game header + tabs shell
    # -------------------------------------------------------------------

    @render.ui
    def game_header():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            g = db.query(Game).options(joinedload(Game.season), joinedload(Game.opponent_team)).filter(Game.game_id == game_id).first()
            if g is None:
                return None
            loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
            title = f"{loc} {_opponent_display_name(g)} — {g.game_date.strftime('%Y-%m-%d (%a)')}"
            return ui.div(
                ui.hr(),
                ui.h4(title, class_="gbo-section-title"),
                ui_helpers.render_kpi_cards([
                    {"label": "Us", "value": str(g.our_score)},
                    {"label": "Opponent", "value": str(g.opponent_score)},
                    {"label": "Status", "value": g.status},
                ]),
            )
        finally:
            db.close()

    @render.ui
    def game_tabs():
        _refresh_tick()
        if not _access_ok():
            return None
        if _active_game_id() is None:
            return None
        return ui.navset_tab(
            ui.nav_panel("Live Tracking", ui.output_ui("live_tracking_body")),
            ui.nav_panel("Lineup & Setup", ui.output_ui("lineup_setup_body")),
            ui.nav_panel("Video Review", ui.output_ui("video_review_body")),
            ui.nav_panel("Pitch Log", ui.output_ui("pitch_log_body")),
            ui.nav_panel("Manage Game", ui.output_ui("manage_game_body")),
        )

    # -------------------------------------------------------------------
    # Lineup & Setup
    # -------------------------------------------------------------------

    @render.ui
    def lineup_setup_body():
        _refresh_tick()
        if not _access_ok():
            return None
        if _active_game_id() is None:
            return None
        return ui.div(
            ui.output_ui("squad_a_lineup_setup_picker"),
            ui.output_ui("squad_a_lineup_slots_body"),
            ui.output_ui("squad_a_lineup_display"),
            ui.hr(),
            ui.output_ui("squad_b_lineup_setup_picker"),
            ui.output_ui("squad_b_lineup_slots_body"),
            ui.output_ui("squad_b_lineup_display"),
            ui.hr(),
            ui.output_ui("opponent_lineup_setup_picker"),
            ui.output_ui("opponent_lineup_display"),
        )

    def _register_squad_lineup(squad, prefix):
        squad_label = ("Squad A Lineup" if squad == "A" else "Squad B Lineup")

        @output(id=f"{prefix}_setup_picker")
        @render.ui
        def _picker():
            _refresh_tick()
            if not _access_ok() or not _can_edit():
                return None
            game_id = _active_game_id()
            if game_id is None:
                return None
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None or (squad == "B" and not game.is_intrasquad):
                    return None
                existing = db.query(GameLineupSlot).filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad).count()
                if existing:
                    return None
                label = squad_label if squad == "B" else ("Squad A Lineup" if game.is_intrasquad else "Lineup")
                return ui.div(
                    ui.h5(f"Set {label}", class_="gbo-section-title"),
                    ui.input_checkbox(f"{prefix}_include_pitchers", "Include pitchers in the batting order (two-way players)"),
                    ui.input_numeric(f"{prefix}_num_spots", "Number of batting order spots", value=9, min=9, max=20, step=1),
                    ui.p(
                        "Set the count above, then fill in each slot below. A player can be picked in more than "
                        "one slot here -- unlike the original, this page doesn't live-filter the dropdowns as you "
                        "pick (see the module note); duplicates are flagged when you save instead.",
                        class_="text-muted small",
                    ),
                )
            finally:
                db.close()

        @output(id=f"{prefix}_slots_body")
        @render.ui
        def _slots():
            _refresh_tick()
            if not _access_ok() or not _can_edit():
                return None
            game_id = _active_game_id()
            if game_id is None:
                return None
            req(f"{prefix}_num_spots" in input)
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None or (squad == "B" and not game.is_intrasquad):
                    return None
                existing = db.query(GameLineupSlot).filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad).count()
                if existing:
                    return None
                num_spots = int(input[f"{prefix}_num_spots"]())
                include_pitchers = input[f"{prefix}_include_pitchers"]()
                players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                positions = db.query(Position).order_by(Position.display_order).all()
                batter_candidates = players if include_pitchers else [p for p in players if not p.is_pitcher]
                pitcher_candidates = [p for p in players if p.is_pitcher]

                player_choices = {"": "-- Select --"}
                player_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in batter_candidates})
                position_choices = {"": "-- Position --"}
                position_choices.update({str(pos.position_id): pos.position_name for pos in positions})

                rows = []
                for i in range(1, num_spots + 1):
                    rows.append(ui.layout_columns(
                        ui.p(f"{i}.", class_="mb-0 fw-bold"),
                        ui.input_select(f"{prefix}_slot_player_{i}", None, choices=player_choices),
                        ui.input_select(f"{prefix}_slot_position_{i}", None, choices=position_choices),
                        col_widths=[1, 6, 5],
                    ))
                children = [ui.div(*rows)]
                pitcher_choices = {"": "-- Select --"}
                pitcher_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitcher_candidates})
                pitcher_label = "Starting pitcher" if squad == "A" else "Starting pitcher (Squad B)"
                children.append(ui.input_select(f"{prefix}_starting_pitcher", pitcher_label, choices=pitcher_choices))
                if squad == "B":
                    children.append(ui.p(
                        "Saved as a default for the live \"who's pitching\" picker during Squad A's at-bats -- "
                        "Squad B doesn't get formal pitching-change history the way Squad A does, so this is a "
                        "starting point you can still override any at-bat, not a lock-in.",
                        class_="text-muted small",
                    ))
                children.append(ui.input_action_button(f"{prefix}_save_btn", "Save lineup", class_="btn-primary mt-2"))
                return ui.div(*children)
            finally:
                db.close()

        @output(id=f"{prefix}_display")
        @render.ui
        def _display():
            _refresh_tick()
            if not _access_ok():
                return None
            game_id = _active_game_id()
            if game_id is None:
                return None
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None or (squad == "B" and not game.is_intrasquad):
                    return None
                slots = (
                    db.query(GameLineupSlot)
                    .options(joinedload(GameLineupSlot.player), joinedload(GameLineupSlot.starting_position))
                    .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad)
                    .order_by(GameLineupSlot.batting_order).all()
                )
                if not slots:
                    return None
                label = squad_label if squad == "B" else ("Squad A Lineup" if game.is_intrasquad else "Lineup")
                rows = [
                    {"#": s.batting_order, "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—", "Position": s.starting_position.position_name if s.starting_position else "—"}
                    for s in slots
                ]
                children = [ui.h5(label, class_="gbo-section-title"), ui_helpers.render_dict_table(rows)]
                starting_pitcher_id = game.starting_pitcher_id if squad == "A" else game.squad_b_starting_pitcher_id
                pitcher_prefix = "Starting pitcher" if squad == "A" else "Starting pitcher (default -- overridable live)"
                if starting_pitcher_id:
                    p = db.query(Player).filter(Player.player_id == starting_pitcher_id).first()
                    if p:
                        children.append(ui.p(f"{pitcher_prefix}: {p.first_name} {p.last_name}", class_="text-muted small"))
                return ui.div(*children)
            finally:
                db.close()

        @reactive.effect
        def _sync_lineup_exclusions():
            """Live cross-slot exclusion: once a player is picked in one
            slot, every OTHER slot's dropdown stops offering him. Not a
            @render.ui block (that would hit the "read a client input
            from the block that defines it" hazard, since it would be
            reading every slot_player_i to decide what to show for
            slot_player_i itself) -- instead a plain effect that reads
            every slot's CURRENT value (registering all of them as
            dependencies, so this reruns whenever ANY one changes) and
            pushes fresh, mutually-exclusive choices to every slot via
            ui.update_select(). This restores the original Streamlit
            page's live-filtering behavior (each pick immediately
            removed that player from every other slot) that the initial
            port had simplified away in favor of a save-time duplicate
            check -- both protections are kept: this prevents the
            duplicate from being pickable in the first place, and _save
            below still double-checks in case a slot's stale choice list
            briefly allowed one through mid-interaction."""
            game_id = _active_game_id()
            if game_id is None:
                return
            req(f"{prefix}_num_spots" in input)
            num_spots = int(input[f"{prefix}_num_spots"]())
            include_pitchers = input[f"{prefix}_include_pitchers"]() if f"{prefix}_include_pitchers" in input else False

            current_picks = {}
            for i in range(1, num_spots + 1):
                key = f"{prefix}_slot_player_{i}"
                if key not in input:
                    continue
                raw = input[key]()
                if raw:
                    current_picks[i] = int(raw)
            if not current_picks:
                return

            db = get_session()
            try:
                players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                candidates = players if include_pitchers else [p for p in players if not p.is_pitcher]
                names_by_id = {p.player_id: f"{p.first_name} {p.last_name}" for p in candidates}
            finally:
                db.close()

            for i in range(1, num_spots + 1):
                key = f"{prefix}_slot_player_{i}"
                if key not in input:
                    continue
                taken_elsewhere = {pid for slot, pid in current_picks.items() if slot != i}
                choices = {"": "-- Select --"}
                choices.update({str(pid): name for pid, name in names_by_id.items() if pid not in taken_elsewhere})
                current_val = current_picks.get(i)
                ui.update_select(key, choices=choices, selected=str(current_val) if current_val else "")

        @reactive.effect
        @reactive.event(input[f"{prefix}_save_btn"])
        def _save():
            game_id = _active_game_id()
            if game_id is None:
                return
            num_spots = int(input[f"{prefix}_num_spots"]())
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None:
                    return
                picks = []
                chosen_ids = []
                for i in range(1, num_spots + 1):
                    player_raw = input[f"{prefix}_slot_player_{i}"]()
                    position_raw = input[f"{prefix}_slot_position_{i}"]()
                    if player_raw:
                        picks.append((i, int(player_raw), int(position_raw) if position_raw else None))
                        chosen_ids.append(int(player_raw))
                if len(chosen_ids) != len(set(chosen_ids)):
                    ui.notification_show("The same player is picked in more than one slot -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return
                for i, player_id, position_id in picks:
                    db.add(GameLineupSlot(game_id=game_id, squad=squad, batting_order=i, player_id=player_id, starting_position_id=position_id))
                pitcher_raw = input[f"{prefix}_starting_pitcher"]() if f"{prefix}_starting_pitcher" in input else ""
                if squad == "A":
                    game.starting_pitcher_id = int(pitcher_raw) if pitcher_raw else None
                else:
                    game.squad_b_starting_pitcher_id = int(pitcher_raw) if pitcher_raw else None
                db.commit()
                label = "lineup" if squad == "A" else "Squad B lineup"
                ui.notification_show(f"Saved {label} ({len(picks)} batters).", type="message", duration=8)
                _bump_refresh()
            finally:
                db.close()

    _register_squad_lineup("A", "squad_a_lineup")
    _register_squad_lineup("B", "squad_b_lineup")

    @render.ui
    def opponent_lineup_setup_picker():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == game_id).first()
            if game is None or game.is_intrasquad:
                return None
            existing_count = db.query(OpponentLineupSlot).filter(OpponentLineupSlot.game_id == game_id).count()
            if existing_count:
                return None
            opp_label = game.opponent_team.team_name if game.opponent_team else (game.opponent_name or "the opponent")
            roster = game.opponent_team.roster if game.opponent_team else []
            roster_choices = {"": "-- Existing roster --"}
            roster_choices.update({str(p.opponent_player_id): p.player_name + (f" (#{p.jersey_number})" if p.jersey_number else "") for p in roster})

            rows = [
                ui.h5(f"Set {opp_label}'s lineup (optional)", class_="gbo-section-title"),
                ui.p(
                    "9 batting order slots + starting pitcher. Pick a name from their roster if you've got one "
                    "built out, or just type a new name -- typing a name adds them to a reusable roster for this "
                    "opponent, so next time you play them you can pick from a list instead of retyping. Skip this "
                    "and Game Tracking still works -- you'll just pick the batter manually each at-bat instead of "
                    "it being suggested automatically.",
                    class_="text-muted small",
                ),
            ]
            for i in range(1, 10):
                rows.append(ui.layout_columns(
                    ui.p(f"{i}.", class_="mb-0 fw-bold"),
                    ui.input_select(f"opp_lineup_existing_{i}", None, choices=roster_choices),
                    ui.input_text(f"opp_lineup_new_{i}", None, placeholder="...or type a new name"),
                    ui.input_text(f"opp_lineup_jersey_{i}", None, placeholder="#"),
                    col_widths=[1, 4, 5, 2],
                ))
            rows.append(ui.p("Their starting pitcher", class_="fw-bold mt-2 mb-1"))
            rows.append(ui.layout_columns(
                ui.input_select("opp_pitcher_existing", None, choices=roster_choices),
                ui.input_text("opp_pitcher_new_name", None, placeholder="...or type a new name"),
                ui.input_text("opp_pitcher_new_jersey", None, placeholder="#"),
                col_widths=[4, 6, 2],
            ))
            rows.append(ui.input_action_button("opp_lineup_save_btn", "Save opponent lineup", class_="btn-primary mt-2"))
            return ui.div(*rows)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.opp_lineup_save_btn)
    def _save_opponent_lineup():
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team)).filter(Game.game_id == game_id).first()
            if game is None:
                return
            opp_team = game.opponent_team
            if opp_team is None:
                lookup_name = (game.opponent_name or "").strip()
                if lookup_name:
                    opp_team = db.query(OpponentTeam).filter(OpponentTeam.team_name == lookup_name).first()
                if opp_team is None:
                    opp_team = OpponentTeam(team_name=lookup_name or f"Opponent (Game #{game.game_id})", created_by_user_id=app_state.user_id())
                    db.add(opp_team)
                    db.flush()
                game.opponent_team_id = opp_team.team_id

            def _resolve(existing_raw, new_name_raw, new_jersey_raw):
                if existing_raw:
                    return int(existing_raw)
                name = (new_name_raw or "").strip()
                if not name:
                    return None
                new_player = OpponentPlayer(team_id=opp_team.team_id, player_name=name, jersey_number=(new_jersey_raw or "").strip() or None)
                db.add(new_player)
                db.flush()
                return new_player.opponent_player_id

            added = 0
            for i in range(1, 10):
                existing_raw = input[f"opp_lineup_existing_{i}"]() if f"opp_lineup_existing_{i}" in input else ""
                new_name_raw = input[f"opp_lineup_new_{i}"]() if f"opp_lineup_new_{i}" in input else ""
                new_jersey_raw = input[f"opp_lineup_jersey_{i}"]() if f"opp_lineup_jersey_{i}" in input else ""
                resolved = _resolve(existing_raw, new_name_raw, new_jersey_raw)
                if resolved is not None:
                    db.add(OpponentLineupSlot(game_id=game_id, batting_order=i, opponent_player_id=resolved))
                    added += 1

            pitcher_existing = input.opp_pitcher_existing() if "opp_pitcher_existing" in input else ""
            pitcher_new_name = input.opp_pitcher_new_name() if "opp_pitcher_new_name" in input else ""
            pitcher_new_jersey = input.opp_pitcher_new_jersey() if "opp_pitcher_new_jersey" in input else ""
            game.opponent_starting_pitcher_id = _resolve(pitcher_existing, pitcher_new_name, pitcher_new_jersey)

            db.commit()
            ui.notification_show(f"Saved {opp_team.team_name}'s lineup ({added} batters).", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def opponent_lineup_display():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).options(joinedload(Game.opponent_team), joinedload(Game.opponent_starting_pitcher)).filter(Game.game_id == game_id).first()
            if game is None or game.is_intrasquad:
                return None
            slots = (
                db.query(OpponentLineupSlot).options(joinedload(OpponentLineupSlot.opponent_player))
                .filter(OpponentLineupSlot.game_id == game_id).order_by(OpponentLineupSlot.batting_order).all()
            )
            if not slots:
                return None
            rows = [{"#": s.batting_order, "Player": s.opponent_player.player_name if s.opponent_player else "—"} for s in slots]
            children = [ui.h5(f"{game.opponent_team.team_name if game.opponent_team else 'Opponent'}'s lineup", class_="gbo-section-title"), ui_helpers.render_dict_table(rows)]
            if game.opponent_starting_pitcher:
                children.append(ui.p(f"Their starting pitcher: {game.opponent_starting_pitcher.player_name}", class_="text-muted small"))
            return ui.div(*children)
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Live Tracking
    # -------------------------------------------------------------------

    @render.ui
    def live_tracking_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            status = game.status
        finally:
            db.close()

        if _can_edit() and status == "In Progress":
            # Static headers/dividers live here (not inside the individual
            # reactive blocks below) purely for visual grouping -- matches
            # the original's four bordered st.container()s (Game State/
            # Who's Up/Pitch Details/Result), and keeps every block's own
            # logic untouched by the grouping. class_="gbo-section-title"
            # is the same section-header treatment used throughout the
            # rest of the app (bullpen_tracking.py, idp.py, etc.), so this
            # page reads as consistent with everything else instead of a
            # denser, un-sectioned wall of widgets.
            return ui.div(
                ui.output_ui("live_game_dashboard"),
                ui.hr(),
                ui.output_ui("game_state_display"),
                ui.hr(),
                ui.h5("Who's Up", class_="gbo-section-title"),
                ui.output_ui("who_is_up_identity_picker"),
                ui.output_ui("who_is_up_hand_and_order"),
                ui.hr(),
                ui.output_ui("live_pitch_sequence_display"),
                ui.hr(),
                ui.output_ui("pitch_type_and_outcome_picker"),
                ui.output_ui("intended_location_preview"),
                ui.output_ui("pitch_outcome_dependent_fields"),
                ui.output_ui("batted_ball_location_preview"),
                ui.output_ui("result_ab_outcome_picker"),
                ui.output_ui("result_fields_body"),
                ui.hr(),
                ui.output_ui("record_pitch_controls"),
            )
        elif _can_edit() and status == "Scheduled":
            return ui.p('This game hasn\'t started yet -- click "Start game" on the Manage Game tab to begin live tracking.', class_="text-muted")
        elif _can_edit() and status == "Paused":
            return ui.p('This game is paused -- click "Resume game" on the Manage Game tab to continue tracking.', class_="text-muted")
        elif _can_edit():
            return ui.p(f"Live tracking isn't active for a {status.lower()} game.", class_="text-muted")
        else:
            return ui.p("Live tracking status is only shown for edit-enabled roles today.", class_="text-muted")

    @render.ui
    def live_game_dashboard():
        """Milestone 1 -- see module docstring. A console-style summary
        at the top of Live Tracking: score/inning/outs/count plus the
        current pitcher's and current batter's in-game line, reusing
        game_stats.py's existing aggregation functions rather than
        computing new stats. Depends on _pa_tick (not _refresh_tick),
        same reasoning as the rest of this cluster."""
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None

            half_label = "Batting" if state["is_our_batting"] else "Pitching"
            children = [
                ui.h5("Live Game Dashboard", class_="gbo-section-title"),
                ui_helpers.render_kpi_cards([
                    {"label": "Score", "value": f"{game.our_score}-{game.opponent_score}"},
                    {"label": "Inning", "value": f"{state['inning']} — {half_label}"},
                    {"label": "Outs", "value": str(state["outs"])},
                    {"label": "Count", "value": f"{state['balls']}-{state['strikes']}"},
                ]),
            ]

            pitcher_id = _resolve_current_pitcher_id_for_stats(game, state)
            if pitcher_id is not None:
                p = db.query(Player).filter(Player.player_id == pitcher_id).first()
                if p is not None:
                    line = compute_pitching_line(get_pitching_pitches(db, pitcher_id, game_id=game_id))
                    strike_pct = line["Strike %"]
                    children.append(ui_helpers.render_kpi_cards([
                        {"label": f"P — {p.first_name} {p.last_name}", "value": f"{line['Pitches']} pitches"},
                        {"label": "Strike %", "value": f"{strike_pct}%" if strike_pct is not None else "—"},
                        {"label": "K", "value": str(line["K"])},
                        {"label": "BB", "value": str(line["BB"])},
                    ]))
            elif not state["is_our_batting"]:
                # Shouldn't happen -- we always have a resolvable pitcher_id when we're the ones pitching.
                pass
            else:
                children.append(ui.p("Opposing pitcher isn't one of our tracked players, so pitch stats aren't available for them.", class_="text-muted small"))

            hitter_id = _resolve_current_hitter_id_for_stats(game, state, squad_a_slots, squad_b_slots)
            if hitter_id is not None:
                h = db.query(Player).filter(Player.player_id == hitter_id).first()
                if h is not None:
                    line = compute_batting_line(get_batting_pitches(db, hitter_id, game_id=game_id))
                    children.append(ui_helpers.render_kpi_cards([
                        {"label": f"AB — {h.first_name} {h.last_name}", "value": f"{line['PA']} PA"},
                        {"label": "H", "value": str(line["H"])},
                        {"label": "BB", "value": str(line["BB"])},
                        {"label": "K", "value": str(line["K"])},
                    ]))
            else:
                children.append(ui.p("Opposing batter isn't one of our tracked players, so batting stats aren't available for them.", class_="text-muted small"))

            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def game_state_display():
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None
            half_label = "We're batting" if state["is_our_batting"] else "We're pitching"
            children = [
                ui.h5(f"Inning {state['inning']} — {half_label}", class_="gbo-section-title"),
                ui_helpers.render_kpi_cards([
                    {"label": "Outs", "value": str(state["outs"])},
                    {"label": "Count", "value": f"{state['balls']}-{state['strikes']}"},
                    {"label": "Runners", "value": bases_display(state["bases"])},
                ]),
            ]
            if state["outs"] >= 3:
                children.append(ui.p("3 outs reached but the inning hasn't advanced yet -- this shouldn't normally happen; check the last pitch logged.", class_="text-warning small"))
            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def who_is_up_identity_picker():
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None

            if not state["new_pa"]:
                if state["is_our_batting"]:
                    cur_id = state.get("current_our_player")
                    p = db.query(Player).filter(Player.player_id == cur_id).first() if cur_id else None
                    if p:
                        return ui.p(f"At bat: {p.first_name} {p.last_name}", class_="text-muted small")
                return None

            children = [ui.p("New plate appearance -- who's up? (auto-suggested from the lineup order, override if needed)", class_="text-muted small")]

            if state["is_our_batting"]:
                if squad_a_slots:
                    lineup_ids = [s.player_id for s in squad_a_slots]
                else:
                    lineup_ids = [p.player_id for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(False)).order_by(Player.last_name, Player.first_name).all()]
                players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(lineup_ids)).all()}
                choices = {str(pid): f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in lineup_ids if pid in players_by_id}
                suggested = suggest_next_our_batter(game, squad_a_slots) if squad_a_slots else None
                selected = str(suggested) if suggested is not None and str(suggested) in choices else None
                children.append(ui.input_select("our_batter_select", "Our batter", choices=choices, selected=selected))

                if game.is_intrasquad:
                    pitcher_candidates = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).order_by(Player.last_name, Player.first_name).all()
                    if not pitcher_candidates:
                        children.append(ui.p("No active players are marked as pitchers yet -- flag at least one on the Players page.", class_="text-warning small"))
                    else:
                        pitcher_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitcher_candidates}
                        suggested_pitcher = get_current_squad_b_pitcher_id(game)
                        pitcher_selected = str(suggested_pitcher) if suggested_pitcher is not None and str(suggested_pitcher) in pitcher_choices else None
                        children.append(ui.input_select("opp_pitcher_select", "Opposing pitcher (Squad B)", choices=pitcher_choices, selected=pitcher_selected))
            else:
                if game.is_intrasquad:
                    if squad_b_slots:
                        squad_b_ids = [s.player_id for s in squad_b_slots]
                    else:
                        squad_b_ids = [p.player_id for p in db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()]
                    players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(squad_b_ids)).all()}
                    choices = {str(pid): f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in squad_b_ids if pid in players_by_id}
                    suggested = suggest_next_squad_b_batter(game, squad_b_slots) if squad_b_slots else None
                    selected = str(suggested) if suggested is not None and str(suggested) in choices else None
                    children.append(ui.input_select("opp_our_batter_select", "Opposing batter (Squad B)", choices=choices, selected=selected))
                else:
                    opp_roster = game.opponent_team.roster if game.opponent_team else []
                    if opp_roster:
                        choices = {"": "-- Not on roster / unknown --"}
                        choices.update({str(p.opponent_player_id): p.player_name + (f" (#{p.jersey_number})" if p.jersey_number else "") for p in opp_roster})
                        suggested = suggest_next_opponent_lineup_player(game, opponent_lineup_slots) if opponent_lineup_slots else None
                        selected = str(suggested) if suggested is not None and str(suggested) in choices else ""
                        children.append(ui.input_select("opp_roster_player_select", "Opposing batter (optional -- pick from roster)", choices=choices, selected=selected))

            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def who_is_up_hand_and_order():
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None

            children = []
            if state["new_pa"]:
                if state["is_our_batting"]:
                    default_hand = "R"
                    if game.is_intrasquad and "opp_pitcher_select" in input and input.opp_pitcher_select():
                        pitcher = db.query(Player).filter(Player.player_id == int(input.opp_pitcher_select())).first()
                        if pitcher and pitcher.throws:
                            default_hand = pitcher.throws
                    label = "Opposing pitcher's throwing hand" if game.is_intrasquad else "Opposing pitcher's hand"
                    children.append(ui.input_radio_buttons("opp_pitcher_hand_radio", label, choices=["R", "L"], selected=default_hand, inline=True))
                else:
                    default_hand = "R"
                    if game.is_intrasquad and "opp_our_batter_select" in input and input.opp_our_batter_select():
                        batter = db.query(Player).filter(Player.player_id == int(input.opp_our_batter_select())).first()
                        if batter and batter.bats:
                            default_hand = batter.bats
                    elif not game.is_intrasquad and "opp_roster_player_select" in input and input.opp_roster_player_select():
                        rp = db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id == int(input.opp_roster_player_select())).first()
                        if rp and rp.bats in ("R", "L"):
                            default_hand = rp.bats
                    children.append(ui.input_radio_buttons("opp_batter_hand_radio", "Opposing batter's hand", choices=["R", "L"], selected=default_hand, inline=True))
                    if not game.is_intrasquad:
                        children.append(ui.input_numeric("opp_batting_order_input", "Opponent's batting order #", value=suggest_next_opponent_order(game), min=1, max=12, step=1))

            if not state["is_our_batting"]:
                current_pitcher_id = get_current_pitcher_id(game)
                p = db.query(Player).filter(Player.player_id == current_pitcher_id).first() if current_pitcher_id else None
                if p:
                    children.append(ui.p(f"Currently pitching: {p.first_name} {p.last_name}", class_="fw-bold"))
                else:
                    children.append(ui.p("No pitcher set yet -- set a starting pitcher on the Lineup & Setup tab, or make a pitching change below.", class_="text-warning small"))

                pitcher_candidates = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).order_by(Player.last_name, Player.first_name).all()
                pitcher_choices = {str(pp.player_id): f"{pp.first_name} {pp.last_name}" for pp in pitcher_candidates}
                children.append(ui.accordion(
                    ui.accordion_panel(
                        "Make a pitching change",
                        ui.input_select("new_pitcher_select", "New pitcher", choices=pitcher_choices),
                        ui.input_action_button("confirm_pitching_change_btn", "Confirm pitching change", class_="btn-sm btn-primary"),
                    ),
                    open=False, id=None,
                ))

            return ui.div(*children) if children else None
        finally:
            db.close()

    @render.ui
    def live_pitch_sequence_display():
        """Milestone 1 -- see module docstring. Shows only the pitches
        of the current, still-open plate appearance (via
        _current_pa_pitches), so the coach can see this at-bat's
        sequence without scrolling to the full Pitch Log. Depends on
        _pa_tick, not _refresh_tick, same as the rest of this cluster."""
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None
            current_pa_pitches = _current_pa_pitches(pitches)
            if not current_pa_pitches:
                return ui.div(ui.h6("This At-Bat", class_="gbo-section-title"), ui.p("New plate appearance -- no pitches yet.", class_="text-muted small"))
            pitch_type_names = {pt.pitch_type_id: pt.type_name for pt in db.query(PitchType).all()}
            rows = [
                {
                    "#": p.pa_pitch_number,
                    "Pitch": pitch_type_names.get(p.pitch_type_id, "—"),
                    "Count": f"{p.balls_before}-{p.strikes_before}",
                    "Outcome": p.pitch_outcome or "—",
                }
                for p in current_pa_pitches
            ]
            return ui.div(ui.h6("This At-Bat", class_="gbo-section-title"), ui_helpers.render_dict_table(rows))
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.confirm_pitching_change_btn)
    def _confirm_pitching_change():
        game_id = _active_game_id()
        if game_id is None:
            return
        req("new_pitcher_select" in input)
        if not input.new_pitcher_select():
            return
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            new_pitcher_id = int(input.new_pitcher_select())
            db.add(PitchingChange(game_id=game_id, player_id=new_pitcher_id, inning=state["inning"], outs_at_entry=state["outs"], pitch_sequence_at_entry=len(pitches)))
            db.commit()
            pitcher = db.query(Player).filter(Player.player_id == new_pitcher_id).first()
            ui.notification_show(f"{pitcher.first_name} {pitcher.last_name} is now pitching.", type="message", duration=8)
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def pitch_type_and_outcome_picker():
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None

            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            if not state["is_our_batting"]:
                current_pitcher_id = get_current_pitcher_id(game)
                arsenal_names = get_arsenal_pitch_type_names(db, current_pitcher_id, pitch_types) if current_pitcher_id else [pt.type_name for pt in pitch_types]
            else:
                arsenal_names = [pt.type_name for pt in pitch_types]
            pitch_type_choices = {name: name for name in arsenal_names}

            children = [
                ui.h5("Pitch Details", class_="gbo-section-title"),
                ui.input_select("pitch_type_select", "Pitch type", choices=pitch_type_choices),
            ]

            if not state["is_our_batting"]:
                children.append(ui.p(
                    "Intended location -- enter where the pitch was supposed to go (numeric entry with a live "
                    "preview below replaces the original's click-to-place; see the module note).",
                    class_="text-muted small",
                ))
                children.append(ui.layout_columns(
                    ui.input_numeric("intended_x_input", "Intended plate side (ft, 0 = center, negative = 3B side)", value=0.0, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                    ui.input_numeric("intended_z_input", "Intended plate height (ft off the ground)", value=2.5, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
                ))

            children.append(ui.input_select("pitch_outcome_select", "Pitch outcome", choices=PITCH_OUTCOMES))
            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def intended_location_preview():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None or ctx[0].status != "In Progress" or ctx[5]["is_our_batting"]:
                return None
        finally:
            db.close()
        req("intended_x_input" in input)
        x, z = input.intended_x_input(), input.intended_z_input()
        fig = strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z)
        return ui.div(
            chart_helpers.fig_to_img(fig, width=300, height=300),
            ui.p(f"Intended: {x:+.2f} ft, {z:.2f} ft high", class_="text-muted small text-center"),
        )

    @render.ui
    def pitch_outcome_dependent_fields():
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is None:
            return None
        req("pitch_outcome_select" in input)
        outcome = input.pitch_outcome_select()
        children = []
        if outcome in ("In Play", "Foul", "Swing and Miss"):
            children.append(ui.input_select("contact_quality_select", "Contact quality (optional)", choices=["-- N/A --"] + CONTACT_QUALITY_OPTIONS))
            children.append(ui.input_checkbox("is_sword_checkbox", "Sword (ugly, off-balance swing)"))
        if outcome == "In Play":
            children.append(ui.input_select("batted_ball_type_select", "Batted ball type (optional)", choices=["-- N/A --", "Ground Ball", "Line Drive", "Fly Ball", "Pop Up"]))
            children.append(ui.p(
                "Where did it land? Enter coordinates below (numeric entry with a live preview replaces the "
                "original's click-to-place).",
                class_="text-muted small",
            ))
            children.append(ui.layout_columns(
                ui.input_numeric("batted_ball_x_input", "Feet right of the CF line (negative = left field side)", value=0.0, min=field_location.X_MIN, max=field_location.X_MAX, step=5.0),
                ui.input_numeric("batted_ball_y_input", "Feet from home plate toward the outfield", value=150.0, min=field_location.Y_MIN, max=field_location.Y_MAX, step=5.0),
            ))
        if not children:
            return None
        return ui.div(*children)

    @render.ui
    def batted_ball_location_preview():
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is None:
            return None
        req("pitch_outcome_select" in input)
        if input.pitch_outcome_select() != "In Play":
            return None
        req("batted_ball_x_input" in input)
        x, y = input.batted_ball_x_input(), input.batted_ball_y_input()
        fig = field_location.build_field_selector_figure(marker_x=x, marker_y=y)
        dist = field_location.distance_from_plate(x, y)
        return ui.div(
            chart_helpers.fig_to_img(fig, width=320, height=340),
            ui.p(f"Landed: {x:+.0f} ft, {y:.0f} ft deep ({dist:.0f} ft from home)", class_="text-muted small text-center"),
        )

    @render.ui
    def result_ab_outcome_picker():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        req("pitch_outcome_select" in input)
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None
            outcome = input.pitch_outcome_select()
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome)
            if not ends_pa:
                return None
            default_ab = "BB" if new_balls >= 4 else ("K" if new_strikes >= 3 else ("HBP" if outcome == "HBP" else "1B"))
            choices = {name: name for name in AB_OUTCOMES}
            return ui.div(
                ui.h5("Result", class_="gbo-section-title"),
                ui.input_select("ab_outcome_select", "AB outcome", choices=choices, selected=default_ab if default_ab in AB_OUTCOMES else None),
                ui.p("Confirm or adjust the result -- suggested from the AB outcome, but real plays vary.", class_="text-muted small"),
            )
        finally:
            db.close()

    @render.ui
    def result_fields_body():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        req("pitch_outcome_select" in input)
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return None
            outcome = input.pitch_outcome_select()
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome)
            if not ends_pa:
                return None
            req("ab_outcome_select" in input)
            ab_outcome = input.ab_outcome_select()
            suggested_outs, suggested_bases, suggested_runs = suggest_after_state(ab_outcome, state["bases"], state["outs"])
            return ui.layout_columns(
                ui.input_numeric("final_outs_input", "Outs after", value=min(suggested_outs, 3), min=0, max=3, step=1),
                ui.input_text("final_bases_input", "Bases after (1st,2nd,3rd = 1/0)", value=suggested_bases),
                ui.input_numeric("final_runs_input", "Runs scored on play", value=suggested_runs, min=0, max=4, step=1),
            )
        finally:
            db.close()

    @render.ui
    def record_pitch_controls():
        # Depends on _pa_tick (not just _active_game_id) so the Undo
        # button's enabled/disabled state and the "Last recorded" note
        # stay current as pitches are recorded/undone.
        _pa_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None or game.status != "In Progress":
                return None
            last_pitch = (
                db.query(GamePitch)
                .filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence.desc())
                .first()
            )
        finally:
            db.close()
        children = [
            ui.input_text("pitch_notes_input", "Notes (optional)"),
            ui.layout_columns(
                ui.input_action_button("record_pitch_btn", "Record pitch", class_="btn-primary mt-2 w-100"),
                ui.input_action_button(
                    "undo_last_pitch_btn", "Undo Last Pitch",
                    class_="btn-outline-danger mt-2 w-100", disabled=(last_pitch is None),
                ),
                col_widths=[8, 4],
            ),
        ]
        if last_pitch is not None:
            outcome_label = last_pitch.ab_outcome or last_pitch.pitch_outcome or "—"
            children.append(ui.p(f"Last recorded: pitch #{last_pitch.pitch_sequence} ({outcome_label}).", class_="text-muted small"))
        return ui.div(*children)

    @reactive.effect
    @reactive.event(input.undo_last_pitch_btn)
    def _undo_last_pitch():
        """Milestone 1 -- see module docstring. Deletes the single
        most-recent GamePitch row for the active game. Only
        game.our_score/opponent_score need a manual reversal here (they're
        the one piece of state this page persists outside GamePitch
        itself) -- everything else (outs/bases/count/inning) is
        re-derived fresh from the remaining GamePitch rows by
        compute_current_state() the next time anything on this page
        renders, since _bump_pa()/_bump_refresh() below trigger exactly
        that."""
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return
            last_pitch = (
                db.query(GamePitch)
                .filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence.desc())
                .first()
            )
            if last_pitch is None:
                ui.notification_show("No pitches recorded yet in this game.", type="warning", duration=6)
                return
            if last_pitch.ends_plate_appearance and last_pitch.runs_scored_on_play:
                if last_pitch.is_our_team_batting:
                    game.our_score = max(0, game.our_score - last_pitch.runs_scored_on_play)
                else:
                    game.opponent_score = max(0, game.opponent_score - last_pitch.runs_scored_on_play)
            undone_seq = last_pitch.pitch_sequence
            undone_outcome = last_pitch.ab_outcome or last_pitch.pitch_outcome or "—"
            db.delete(last_pitch)
            db.commit()
            ui.notification_show(f"Undid pitch #{undone_seq} ({undone_outcome}).", type="message", duration=8)
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    def _do_record_pitch():
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state = ctx
            if game.status != "In Progress":
                return

            our_player_choice = opp_hand_choice = opp_batting_order_choice = opp_player_choice = opp_our_player_choice = None
            if state["new_pa"]:
                if state["is_our_batting"]:
                    if "our_batter_select" not in input or not input.our_batter_select():
                        ui.notification_show("Select who's batting first.", type="error", duration=8)
                        return
                    our_player_choice = int(input.our_batter_select())
                    if game.is_intrasquad and "opp_pitcher_select" in input and input.opp_pitcher_select():
                        opp_our_player_choice = int(input.opp_pitcher_select())
                    opp_hand_choice = input.opp_pitcher_hand_radio() if "opp_pitcher_hand_radio" in input else "R"
                else:
                    our_player_choice = get_current_pitcher_id(game)
                    if our_player_choice is None:
                        ui.notification_show("Select who's pitching first.", type="error", duration=8)
                        return
                    if game.is_intrasquad:
                        if "opp_our_batter_select" not in input or not input.opp_our_batter_select():
                            ui.notification_show("Select the opposing batter first.", type="error", duration=8)
                            return
                        opp_our_player_choice = int(input.opp_our_batter_select())
                    else:
                        if "opp_roster_player_select" in input and input.opp_roster_player_select():
                            opp_player_choice = int(input.opp_roster_player_select())
                        opp_batting_order_choice = int(input.opp_batting_order_input()) if "opp_batting_order_input" in input else None
                    opp_hand_choice = input.opp_batter_hand_radio() if "opp_batter_hand_radio" in input else "R"
            else:
                our_player_choice = state.get("current_our_player")
                opp_hand_choice = state.get("current_opp_hand")
                opp_batting_order_choice = state.get("current_opp_order")
                opp_player_choice = state.get("current_opp_player")
                opp_our_player_choice = state.get("current_opp_our_player")
                if our_player_choice is None:
                    ui.notification_show("Couldn't determine who's up -- try refreshing the page.", type="error", duration=8)
                    return

            req("pitch_type_select" in input)
            pitch_type_name = input.pitch_type_select()
            pitch_types = db.query(PitchType).all()
            pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_name), None)

            intended_x = intended_z = None
            if not state["is_our_batting"] and "intended_x_input" in input:
                intended_x, intended_z = input.intended_x_input(), input.intended_z_input()

            # Actual location isn't captured live here either -- same as
            # the original, filled in afterward from game video via
            # Video Review.
            actual_x = actual_z = None

            req("pitch_outcome_select" in input)
            outcome = input.pitch_outcome_select()
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome)

            cq = None
            is_sword = False
            if outcome in ("In Play", "Foul", "Swing and Miss") and "contact_quality_select" in input:
                raw_cq = input.contact_quality_select()
                cq = raw_cq if raw_cq and raw_cq != "-- N/A --" else None
                is_sword = input.is_sword_checkbox() if "is_sword_checkbox" in input else False

            bbt = None
            batted_x = batted_y = None
            if outcome == "In Play" and "batted_ball_type_select" in input:
                raw_bbt = input.batted_ball_type_select()
                bbt = raw_bbt if raw_bbt and raw_bbt != "-- N/A --" else None
                if "batted_ball_x_input" in input:
                    batted_x, batted_y = input.batted_ball_x_input(), input.batted_ball_y_input()

            ab_outcome = final_outs = final_bases = final_runs = None
            if ends_pa:
                if "ab_outcome_select" not in input:
                    ui.notification_show("Confirm the AB result before recording this pitch.", type="error", duration=8)
                    return
                ab_outcome = input.ab_outcome_select()
                final_outs = int(input.final_outs_input())
                final_bases = input.final_bases_input()
                final_runs = int(input.final_runs_input())

            notes = ((input.pitch_notes_input() or "").strip() if "pitch_notes_input" in input else "")

            next_seq = (max((p.pitch_sequence for p in pitches), default=0)) + 1
            re_lookup = build_re_lookup(db)
            re_before, re_after, run_value = compute_re_and_rv(
                re_lookup, state["outs"], state["bases"], state["balls"], state["strikes"],
                ends_pa, final_outs if ends_pa else None, final_bases if ends_pa else None,
                final_runs if ends_pa else 0, new_balls=new_balls, new_strikes=new_strikes,
            )

            db.add(GamePitch(
                game_id=game_id,
                pitch_sequence=next_seq,
                inning=state["inning"],
                is_our_team_batting=state["is_our_batting"],
                our_player_id=our_player_choice,
                opponent_hand=opp_hand_choice,
                opponent_batting_order=opp_batting_order_choice if not state["is_our_batting"] else None,
                opponent_player_id=opp_player_choice if not state["is_our_batting"] else None,
                opponent_our_player_id=opp_our_player_choice,
                pa_pitch_number=state["pa_pitch_number"],
                balls_before=state["balls"],
                strikes_before=state["strikes"],
                outs_before=state["outs"],
                bases_before=state["bases"],
                pitch_type_id=pitch_type_id,
                intended_zone=strike_zone.derive_old_zone(intended_x, intended_z),
                pitch_zone=strike_zone.derive_old_zone(actual_x, actual_z),
                actual_plate_x=actual_x,
                actual_plate_z=actual_z,
                intended_plate_x=intended_x,
                intended_plate_z=intended_z,
                pitch_outcome=outcome,
                contact_quality=cq,
                is_sword=is_sword,
                batted_ball_type=bbt,
                batted_ball_x=batted_x,
                batted_ball_y=batted_y,
                ends_plate_appearance=ends_pa,
                ab_outcome=ab_outcome,
                outs_after=final_outs if ends_pa else None,
                bases_after=final_bases if ends_pa else None,
                runs_scored_on_play=final_runs if ends_pa else 0,
                re_before=re_before,
                re_after=re_after,
                run_value=run_value,
                notes=notes or None,
            ))
            if ends_pa and final_runs:
                if state["is_our_batting"]:
                    game.our_score += final_runs
                else:
                    game.opponent_score += final_runs
            db.commit()

            ui.notification_show("Pitch recorded.", type="message", duration=6)
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.record_pitch_btn)
    def _record_pitch():
        """Duplicate-submission guard -- see module docstring. Wraps
        _do_record_pitch (the real logic, unchanged from the original
        port) with a session-scoped busy flag so a second click that
        arrives while the first is still being written is dropped
        rather than inserting a second pitch, instead of running
        _do_record_pitch directly off the button event."""
        if _is_submitting():
            return
        _is_submitting.set(True)
        try:
            _do_record_pitch()
        finally:
            _is_submitting.set(False)

    # -------------------------------------------------------------------
    # Video Review
    # -------------------------------------------------------------------

    @render.ui
    def video_review_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        if not _can_edit():
            return ui.p("Video Review is only available to edit-enabled roles.", class_="text-muted")
        return ui.div(
            ui.output_ui("game_video_upload_section"),
            ui.output_ui("clip_match_section"),
            ui.hr(),
            ui.output_ui("video_review_jump_picker"),
            ui.output_ui("video_review_detail"),
            ui.output_ui("video_review_preview"),
            ui.output_ui("video_review_nav"),
        )

    @render.ui
    def game_video_upload_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            pitch_count = db.query(GamePitch).filter(GamePitch.game_id == game_id).count()
            if not pitch_count:
                return ui_helpers.empty_state("No pitches logged yet in this game to attach video to.")
            return ui.div(
                ui.h5("Pitch Video", class_="gbo-section-title"),
                ui.p(
                    "Upload clips downloaded from your camera -- if it already exports one clip per pitch, "
                    "upload them together and match each to this game's pitches below.",
                    class_="text-muted small",
                ),
                ui.input_file("game_video_files", "Video files", accept=[".mp4", ".mov", ".m4v"], multiple=True),
                ui.input_action_button("game_video_upload_btn", "Upload", class_="btn-primary"),
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.game_video_upload_btn)
    def _upload_game_videos():
        game_id = _active_game_id()
        if game_id is None:
            return
        files = input.game_video_files() if "game_video_files" in input else None
        if not files:
            ui.notification_show("Choose at least one video file first.", type="error", duration=8)
            return
        db = get_session()
        try:
            uploaded = 0
            for f in files:
                identifier = f"game-{game_id}-{uuid.uuid4().hex[:8]}"
                url = _upload_game_video_clip(f, identifier)
                if url:
                    db.add(GameVideoClip(game_id=game_id, video_url=url, original_filename=f["name"]))
                    uploaded += 1
            db.commit()
            ui.notification_show(f"Uploaded {uploaded} clip(s). Match them to pitches below.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @render.ui
    def clip_match_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            matched_count = db.query(GameVideoClip).filter(GameVideoClip.game_id == game_id, GameVideoClip.matched_game_pitch_id.isnot(None)).count()
            unmatched = (
                db.query(GameVideoClip)
                .filter(GameVideoClip.game_id == game_id, GameVideoClip.matched_game_pitch_id.is_(None))
                .order_by(GameVideoClip.uploaded_at, GameVideoClip.game_video_clip_id).all()
            )
            if not matched_count and not unmatched:
                return None
            children = [ui.p(f"{matched_count} clip(s) matched, {len(unmatched)} still need matching.", class_="text-muted small")]
            if unmatched:
                candidate_pitches = (
                    db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
                    .filter(GamePitch.game_id == game_id, GamePitch.video_url.is_(None))
                    .order_by(GamePitch.pitch_sequence).all()
                )
                if not candidate_pitches:
                    children.append(ui.p("Every pitch in this game already has video -- nothing left to match these clips to.", class_="text-muted small"))
                else:
                    match_choices = {"": "-- Select a pitch --"}
                    for p in candidate_pitches:
                        side = "Us pitching" if not p.is_our_team_batting else "Us batting"
                        pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                        match_choices[str(p.game_pitch_id)] = f"#{p.pitch_sequence} — Inn {p.inning}, {side}, {p.balls_before}-{p.strikes_before}, {pt_name}, {p.pitch_outcome or '—'}"

                    panel_rows = []
                    for idx, clip in enumerate(unmatched):
                        suggested = candidate_pitches[idx].game_pitch_id if idx < len(candidate_pitches) else candidate_pitches[0].game_pitch_id
                        select_id = f"clip_match_select_{clip.game_video_clip_id}"
                        btn_id = f"clip_match_btn_{clip.game_video_clip_id}"
                        panel_rows.append(ui.layout_columns(
                            ui.p(clip.original_filename or "Clip", class_="mb-0"),
                            ui.input_select(select_id, None, choices=match_choices, selected=str(suggested)),
                            ui.input_action_button(btn_id, "Link", class_="btn-sm btn-outline-primary"),
                            col_widths=[3, 6, 3],
                        ))
                        if btn_id not in _registered_clip_match_ids:
                            _registered_clip_match_ids.add(btn_id)
                            _register_clip_match_handler(btn_id, select_id, clip.game_video_clip_id)

                    children.append(ui.accordion(ui.accordion_panel(f"Match uploaded clips to pitches ({len(unmatched)} pending)", *panel_rows), open=True, id=None))
            return ui.div(*children)
        finally:
            db.close()

    def _register_clip_match_handler(btn_id, select_id, clip_id):
        @reactive.effect
        @reactive.event(input[btn_id])
        def _handler():
            chosen_raw = input[select_id]()
            if not chosen_raw:
                return
            db = get_session()
            try:
                clip = db.query(GameVideoClip).filter(GameVideoClip.game_video_clip_id == clip_id).first()
                pitch = db.query(GamePitch).filter(GamePitch.game_pitch_id == int(chosen_raw)).first()
                if clip is None or pitch is None:
                    return
                clip.matched_game_pitch_id = pitch.game_pitch_id
                pitch.video_url = clip.video_url
                db.commit()
                ui.notification_show(f"Linked {clip.original_filename or 'clip'} to pitch #{pitch.pitch_sequence}.", type="message", duration=8)
                _bump_refresh()
            finally:
                db.close()

    @reactive.effect
    def _reset_vr_on_game_change():
        game_id = _active_game_id()
        if game_id is None:
            _vr_current_pitch_id.set(None)
            return
        db = get_session()
        try:
            pitches_we_threw = (
                db.query(GamePitch).filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False))
                .order_by(GamePitch.pitch_sequence).all()
            )
            if not pitches_we_threw:
                _vr_current_pitch_id.set(None)
                return
            missing = [p.game_pitch_id for p in pitches_we_threw if p.actual_plate_x is None]
            _vr_current_pitch_id.set(missing[0] if missing else pitches_we_threw[0].game_pitch_id)
        finally:
            db.close()

    @render.ui
    def video_review_jump_picker():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            pitches_we_threw = (
                db.query(GamePitch).options(joinedload(GamePitch.pitch_type))
                .filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False))
                .order_by(GamePitch.pitch_sequence).all()
            )
            if not pitches_we_threw:
                return ui.div(
                    ui.h5("Video Review — Actual Pitch Locations", class_="gbo-section-title"),
                    ui_helpers.empty_state("No pitches thrown yet in this game to review."),
                )
            missing_count = sum(1 for p in pitches_we_threw if p.actual_plate_x is None)
            choices = {}
            for p in pitches_we_threw:
                mark = "unmarked" if p.actual_plate_x is None else "done"
                pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                video_tag = " [video]" if p.video_url else ""
                choices[str(p.game_pitch_id)] = f"[{mark}] #{p.pitch_sequence} — Inn {p.inning}, {p.balls_before}-{p.strikes_before}, {pt_name}{video_tag}"
            current = _vr_current_pitch_id()
            selected = str(current) if current is not None and str(current) in choices else None
            return ui.div(
                ui.h5("Video Review — Actual Pitch Locations", class_="gbo-section-title"),
                ui.p(
                    "Step through the pitches we threw and mark where each one actually crossed, watching the "
                    "center-field angle (or the matched clip below, if there is one).",
                    class_="text-muted small",
                ),
                ui.p(f"{missing_count} of {len(pitches_we_threw)} pitch(es) we threw still need an actual location.", class_="text-muted small"),
                ui.input_select("vr_jump_select", "Jump to pitch", choices=choices, selected=selected),
            )
        finally:
            db.close()

    @reactive.effect
    def _sync_vr_current_pitch():
        req("vr_jump_select" in input)
        raw = input.vr_jump_select()
        if raw:
            _vr_current_pitch_id.set(int(raw))

    @render.ui
    def video_review_detail():
        if not _access_ok() or not _can_edit():
            return None
        pitch_id = _vr_current_pitch_id()
        if pitch_id is None:
            return None
        db = get_session()
        try:
            p = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.opponent_our_player), joinedload(GamePitch.opponent_player))
                .filter(GamePitch.game_pitch_id == pitch_id).first()
            )
            if p is None:
                return None
            batter_label = (
                (f"{p.opponent_our_player.first_name} {p.opponent_our_player.last_name}" if p.opponent_our_player else None)
                or (p.opponent_player.player_name if p.opponent_player else None)
                or (f"batting order #{p.opponent_batting_order}" if p.opponent_batting_order else "unknown batter")
            )
            hand_label = f" ({p.opponent_hand}HB)" if p.opponent_hand else ""
            intended_label = (
                f"intended {float(p.intended_plate_x):+.2f} ft, {float(p.intended_plate_z):.2f} ft high"
                if p.intended_plate_x is not None else "no intended location was logged live"
            )
            children = [
                ui.p(f"Pitch #{p.pitch_sequence} — Inning {p.inning}, {p.balls_before}-{p.strikes_before} count, vs. {batter_label}{hand_label}", class_="fw-bold mb-1"),
                ui.p(
                    f"Called: {p.pitch_type.type_name if p.pitch_type else 'unknown pitch'} — {intended_label}. "
                    f"Outcome: {p.pitch_outcome or '—'}" + (f", {p.ab_outcome}" if p.ab_outcome else ""),
                    class_="text-muted small",
                ),
            ]
            if p.video_url:
                children.append(ui.tags.video(ui.tags.source(src=p.video_url), controls=True, style="max-width:100%;"))
            x_default = float(p.actual_plate_x) if p.actual_plate_x is not None else 0.0
            z_default = float(p.actual_plate_z) if p.actual_plate_z is not None else 2.5
            children.append(ui.layout_columns(
                ui.input_numeric("vr_actual_x_input", "Actual plate side (ft, 0 = center, negative = 3B side)", value=x_default, min=strike_zone.X_MIN, max=strike_zone.X_MAX, step=0.1),
                ui.input_numeric("vr_actual_z_input", "Actual plate height (ft off the ground)", value=z_default, min=strike_zone.Z_MIN, max=strike_zone.Z_MAX, step=0.1),
            ))
            return ui.div(*children)
        finally:
            db.close()

    @render.ui
    def video_review_preview():
        if not _access_ok() or not _can_edit():
            return None
        if _vr_current_pitch_id() is None:
            return None
        req("vr_actual_x_input" in input)
        x, z = input.vr_actual_x_input(), input.vr_actual_z_input()
        fig = strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z)
        located = strike_zone.is_in_zone(x, z)
        return ui.div(
            chart_helpers.fig_to_img(fig, width=320, height=320),
            ui.p(f"Marked: {x:+.2f} ft, {z:.2f} ft high — {'In zone' if located else 'Out of zone'}", class_="text-muted small text-center"),
        )

    @render.ui
    def video_review_nav():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        pitch_id = _vr_current_pitch_id()
        if game_id is None or pitch_id is None:
            return None
        db = get_session()
        try:
            ids = [
                p.game_pitch_id for p in
                db.query(GamePitch).filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False)).order_by(GamePitch.pitch_sequence).all()
            ]
            if pitch_id not in ids:
                return None
            idx = ids.index(pitch_id)
            return ui.layout_columns(
                ui.input_action_button("vr_prev_btn", "◀ Previous", disabled=(idx == 0), class_="w-100"),
                ui.input_action_button("vr_save_btn", "Save actual location", class_="btn-primary w-100"),
                ui.input_action_button("vr_next_btn", "Next ▶", disabled=(idx == len(ids) - 1), class_="w-100"),
            )
        finally:
            db.close()

    def _vr_step(direction):
        game_id = _active_game_id()
        pitch_id = _vr_current_pitch_id()
        if game_id is None or pitch_id is None:
            return
        db = get_session()
        try:
            ids = [
                p.game_pitch_id for p in
                db.query(GamePitch).filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False)).order_by(GamePitch.pitch_sequence).all()
            ]
            if pitch_id not in ids:
                return
            idx = ids.index(pitch_id)
            new_idx = min(max(idx + direction, 0), len(ids) - 1)
            _vr_current_pitch_id.set(ids[new_idx])
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.vr_prev_btn)
    def _vr_prev():
        _vr_step(-1)

    @reactive.effect
    @reactive.event(input.vr_next_btn)
    def _vr_next():
        _vr_step(1)

    @reactive.effect
    @reactive.event(input.vr_save_btn)
    def _vr_save():
        pitch_id = _vr_current_pitch_id()
        if pitch_id is None:
            return
        req("vr_actual_x_input" in input)
        x, z = input.vr_actual_x_input(), input.vr_actual_z_input()
        db = get_session()
        try:
            p = db.query(GamePitch).filter(GamePitch.game_pitch_id == pitch_id).first()
            if p is None:
                return
            p.actual_plate_x = x
            p.actual_plate_z = z
            p.pitch_zone = strike_zone.derive_old_zone(x, z)
            db.commit()
            game_id = p.game_id
            pitches_we_threw = (
                db.query(GamePitch).filter(GamePitch.game_id == game_id, GamePitch.is_our_team_batting.is_(False))
                .order_by(GamePitch.pitch_sequence).all()
            )
            ids = [pp.game_pitch_id for pp in pitches_we_threw]
            still_missing = [pp.game_pitch_id for pp in pitches_we_threw if pp.actual_plate_x is None]
            idx = ids.index(pitch_id)
            later_missing = [gpid for gpid in still_missing if ids.index(gpid) > idx]
            if later_missing:
                _vr_current_pitch_id.set(later_missing[0])
            elif still_missing:
                _vr_current_pitch_id.set(still_missing[0])
            else:
                _vr_current_pitch_id.set(ids[min(idx + 1, len(ids) - 1)])
            ui.notification_show(f"Saved actual location for pitch #{p.pitch_sequence}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Pitch Log
    # -------------------------------------------------------------------

    @render.ui
    def pitch_log_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            pitches = (
                db.query(GamePitch)
                .options(joinedload(GamePitch.pitch_type), joinedload(GamePitch.our_player), joinedload(GamePitch.opponent_our_player), joinedload(GamePitch.opponent_player))
                .filter(GamePitch.game_id == game_id)
                .order_by(GamePitch.pitch_sequence.desc())
                .limit(50).all()
            )
            if not pitches:
                return ui.div(ui.h5("Pitch log", class_="gbo-section-title"), ui_helpers.empty_state("No pitches logged yet for this game."))
            rows = []
            for p in pitches:
                rows.append({
                    "#": p.pitch_sequence,
                    "Inn": p.inning,
                    "Side": "Us batting" if p.is_our_team_batting else "Us pitching",
                    "Player": f"{p.our_player.first_name} {p.our_player.last_name}" if p.our_player else "—",
                    "Opponent": (f"{p.opponent_our_player.first_name} {p.opponent_our_player.last_name}" if p.opponent_our_player else None) or (p.opponent_player.player_name if p.opponent_player else None) or (f"#{p.opponent_batting_order} ({p.opponent_hand})" if p.opponent_batting_order else "—"),
                    "Pitch": p.pitch_type.type_name if p.pitch_type else "—",
                    "Location": f"{float(p.actual_plate_x):+.2f}, {float(p.actual_plate_z):.2f}" if p.actual_plate_x is not None else "—",
                    "Video": "✓" if p.video_url else "—",
                    "Outcome": (p.pitch_outcome or "—") + (" (Sword)" if p.is_sword else ""),
                    "Batted Ball": ((p.batted_ball_type or "") + (f" ({float(p.batted_ball_x):+.0f}, {float(p.batted_ball_y):.0f})" if p.batted_ball_x is not None else "")) if (p.batted_ball_type or p.batted_ball_x is not None) else "—",
                    "AB Result": p.ab_outcome or "",
                    "Runs": p.runs_scored_on_play,
                    "RE Before": f"{float(p.re_before):.2f}" if p.re_before is not None else "—",
                    "RE After": f"{float(p.re_after):.2f}" if p.re_after is not None else "—",
                    "RV": f"{float(p.run_value):+.3f}" if p.run_value is not None else "—",
                })
            return ui.div(ui.h5("Pitch log", class_="gbo-section-title"), ui_helpers.render_dict_table(rows))
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Manage Game
    # -------------------------------------------------------------------

    @render.ui
    def manage_game_body():
        _refresh_tick()
        if not _access_ok():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        if not _can_edit():
            return ui.p("Game management is only available to edit-enabled roles.", class_="text-muted")
        return ui.div(
            ui.output_ui("game_status_controls"),
            ui.output_ui("game_delete_section"),
        )

    @render.ui
    def game_status_controls():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            if game.status in ("Final", "Cancelled"):
                return ui.p(f"Status: {game.status} (no further status changes available).", class_="text-muted small")
            row = []
            if game.status == "Scheduled":
                row.append(ui.input_action_button("start_game_btn", "Start game", class_="btn-primary"))
            if game.status == "In Progress":
                row.append(ui.input_action_button("pause_game_btn", "Pause game", class_="btn-outline-secondary"))
                row.append(ui.input_action_button("mark_final_btn", "Mark game Final", class_="btn-primary"))
            if game.status == "Paused":
                row.append(ui.input_action_button("resume_game_btn", "Resume game", class_="btn-primary"))
                row.append(ui.input_action_button("mark_final_btn", "Mark game Final", class_="btn-outline-secondary"))
            row.append(ui.input_action_button("cancel_game_btn", "Cancel game", class_="btn-outline-danger"))
            return ui.div(ui.p(f"Status: {game.status}", class_="text-muted small"), ui.layout_columns(*row))
        finally:
            db.close()

    def _set_game_status(new_status, message):
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return
            game.status = new_status
            db.commit()
            ui.notification_show(message, type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.start_game_btn)
    def _start_game():
        _set_game_status("In Progress", "Game started.")

    @reactive.effect
    @reactive.event(input.pause_game_btn)
    def _pause_game():
        _set_game_status("Paused", "Game paused.")

    @reactive.effect
    @reactive.event(input.resume_game_btn)
    def _resume_game():
        _set_game_status("In Progress", "Game resumed.")

    @reactive.effect
    @reactive.event(input.mark_final_btn)
    def _mark_final():
        _set_game_status("Final", "Game marked Final.")

    @reactive.effect
    @reactive.event(input.cancel_game_btn)
    def _cancel_game():
        _set_game_status("Cancelled", "Game cancelled.")

    @render.ui
    def game_delete_section():
        _refresh_tick()
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return None
            pitch_count = len(game.pitches)
            return ui.accordion(
                ui.accordion_panel(
                    "Delete this game",
                    ui.p(f"This permanently deletes this game and all {pitch_count} pitch(es) logged in it. This can't be undone.", class_="text-warning small"),
                    ui.input_checkbox("confirm_delete_game", "Yes, I want to permanently delete this game", value=False),
                    ui.input_action_button("delete_game_btn", "Delete game", class_="btn-danger btn-sm"),
                ),
                open=False, id=None,
            )
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.delete_game_btn)
    def _delete_game():
        if not (input.confirm_delete_game() if "confirm_delete_game" in input else False):
            return
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            game = db.query(Game).filter(Game.game_id == game_id).first()
            if game is None:
                return
            deleted_id = game.game_id
            db.delete(game)
            db.commit()
            _active_game_id.set(None)
            ui.notification_show(f"Deleted game #{deleted_id}.", type="message", duration=8)
            _bump_refresh()
        finally:
            db.close()
