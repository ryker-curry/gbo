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

  1. **Numeric coordinate entry, now paired with real click-to-place
     (Milestone 2, revised Aug 2026 -- see below).** This page
     originally paired a plain ui.input_numeric() pair with a
     read-only static-preview image instead of a true click interface.
     A first attempt at real clicking (shinywidgets' FigureWidget.
     on_click()) looked right in code review but was never actually
     live-tested end to end; it turned out to be broken (plotly 6.x's
     anywidget-based FigureWidget rewrite -- see click_widgets.py's
     module docstring for the live-debugging trail and the upstream
     GitHub issues). It's since been replaced with a plain client-side
     click listener (click_widgets.click_target/CLICK_CAPTURE_JS) that
     writes the clicked coordinates straight into the same numeric
     inputs the click-less version used, dispatching the same
     input/change events a real keystroke would. Those numeric inputs
     are KEPT as the actual source of truth (still directly typeable
     for fine correction or if a click misses) -- nothing downstream
     (_do_record_pitch, _vr_save, execution %, spray charts, etc.)
     changed at all, since it never read the click event itself, only
     the numeric inputs the click now also fills in.
  2. **Live cross-slot lineup exclusion IS implemented**, matching the
     original -- once a player is picked in one batting-order slot, he
     disappears from every OTHER slot's dropdown for that squad. This
     was initially simplified away (Shiny doesn't rerun the whole page
     on every keystroke the way Streamlit does) in favor of a save-time
     duplicate check alone; `_sync_lineup_exclusions` (inside
     `_register_squad_lineup`) restores the live behavior via an effect
     that watches every slot's current pick and pushes filtered choices
     to the others through `ui.update_select()`. The save-time
     duplicate check stays in place too, as a second line of defense.
     **This effect is debounced** (`_lineup_last_change_time`/
     `_lineup_track_change`, 2026-08-26) -- a real bug Ryker hit (already-
     filled slots randomly going blank while filling in later ones)
     turned out to be a race between overlapping invocations of this
     effect whenever it's still mid-DB-query when the user edits another
     slot; two or more such invocations racing can drive the client/
     server into a self-sustaining oscillation, not just a one-off
     glitch. Debouncing so the effect's real body only runs once edits
     go quiet for `_LINEUP_DEBOUNCE_SECONDS` guarantees no two
     invocations ever overlap, which is what actually fixed it (confirmed
     against a sandboxed reproduction of the exact failure before this
     shipped -- see `_sync_lineup_exclusions`'s own docstring for the
     full root-cause writeup).

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

Milestone 2 -- real click-to-place pitch/batted-ball location, replacing
the numeric-entry-only workaround (see the "Deliberate UX
simplifications" note above for what this superseded). No schema
changes -- clicks still populate the exact same ui.input_numeric()
fields _do_record_pitch/_vr_save already read, so nothing downstream of
those inputs changed:
  - **_build_clickable_widget** -- wraps a plain plotly Figure (from
    strike_zone.build_zone_selector_figure/
    field_location.build_field_selector_figure -- both pure,
    Streamlit-free figure builders that already included an invisible,
    dense click-grid scatter trace at data index 0 specifically for
    this, left over from those modules' original Streamlit design) into
    a go.FigureWidget with the toolbar hidden.
  - **click_widgets.click_target()** -- wraps each output_widget(...)
    call site so a plain client-side 'plotly_click' listener (installed
    once, app-wide, by shiny_app/app.py's CLICK_CAPTURE_JS) knows which
    two numeric inputs to write a click's coordinates into. Replaced
    the original _register_click_to_numeric()/FigureWidget.on_click()
    Python-side round-trip in Aug 2026 after live debugging showed that
    round-trip never actually reached the browser (see
    click_widgets.py's module docstring) -- no server-side click
    handling code is involved at all any more.
  - **Three call sites**, all following the identical
    render_plotly-widget + caption-text pair shape (a render_plotly
    can't also return caption text, so each is split into a
    `..._widget` output_widget() and a separate `..._caption`
    ui.output_ui()): intended_location_widget (Live Tracking, intended
    pitch location while pitching), batted_ball_location_widget (Live
    Tracking, "In Play" batted-ball landing spot),
    video_review_widget (Video Review, actual pitch location).
  - **Verification caveat, disclosed for the same reason
    strike_zone.py/field_location.py's own docstrings already flag it**:
    this sandbox has no live Supabase/Postgres credentials and no
    browser, so an actual in-browser click was never click-tested here
    -- only the API contracts (shinywidgets' render_widget_base.widget
    property, plotly's Points/on_click signature, the existing
    click-grid trace ordering) were verified directly against the
    installed shinywidgets==0.8.1/shiny==1.7.0/plotly packages in this
    environment. If a click doesn't register live, the numeric inputs
    still work exactly as before (nothing about them changed), so nothing
    is lost even in that case -- but please click-test this for real and
    flag it if something's off.

Milestone 3 -- opponent scouting / pitch-calling ("what should we throw
this hitter?"), from GamePitch.opponent_player_id data. No schema
changes -- new query function only:
  - **game_stats.get_pitches_thrown_to_opponent_batter** (new function,
    living in game_stats.py alongside get_batting_pitches/
    get_pitching_pitches which it mirrors) -- every pitch WE threw to a
    given OpponentPlayer, keyed the same way get_pitching_pitches/
    get_batting_pitches are keyed on our own player_id, just on the
    opponent side instead. Its result plugs directly into the EXISTING
    compute_pitching_line()/compute_pitch_type_breakdown() unchanged --
    both are already generic over any list of pitches WE threw,
    regardless of whose stat line they're aggregating, so no new stats
    logic was needed, only the new query.
  - **opponent_scouting_card** -- shown live in Live Tracking whenever
    we're pitching to a known opposing batter (resolved by
    _resolve_current_opponent_batter_id): his career-vs-us line (PA,
    OBA, K, BB, whiffs) plus a per-pitch-type breakdown table
    (usage/strike%/whiff%/CSW%/chase%), sorted by CSW% so the most
    effective pitch against him surfaces first. This is the DATA, not
    an automated pitch-calling recommendation -- the coach still makes
    the call; an automated recommendation engine is explicitly a later,
    out-of-scope phase (the original spec's Phase 5 "Advanced
    Intelligence").
  - **Coverage caveat**: only pitches where the coach picked the batter
    from the opponent's roster (opp_roster_player_select, rather than
    "-- Not on roster / unknown --") are attributable this way -- an
    opponent with no roster on file, or at-bats logged without naming
    the batter, simply won't have a card (or will show "no pitch
    history yet") even if we've technically faced them before. This is
    an existing data-capture gap, not something this milestone changed;
    Opponent Teams' roster-building flow already exists (see
    opponent_lineup_setup_picker/who_is_up_identity_picker) and is the
    lever to improve coverage, not this card.

Milestone 4 -- batting lineup substitutions. The gap: once a squad's
starting lineup was saved, `who_is_up_identity_picker`'s batter choices
were hard-restricted to whoever was in that saved GameLineupSlot set --
for either squad, in intrasquad scrimmages OR real external games, with
no substitute/pinch-hitter/extra-hitter path anywhere on the page (only
whole-game delete). This blocked Ryker's stated goal of tracking data
for every player in an intrasquad scrimmage, and ordinary pinch-hitting
in real games. Pitching substitutions never had this problem (any active
pitcher, any time, via PitchingChange); the opponent's own batting order
was also already open (opp_roster_player_select offers their whole
roster every PA). So this milestone is scoped entirely to GameLineupSlot
(our own squads' batting slots). New schema, mirrors PitchingChange's
proven "a start + an ordered list of changes, most-recent-wins" shape,
scoped to an individual slot rather than the whole team (batting has N
*simultaneous* current occupants, one per slot, unlike pitching's single
role):
  - **LineupSubstitution** (new table, models.py) -- a formal record of
    a player entering an EXISTING slot, replacing whoever's there now.
    `GameLineupSlot.player_id`/`starting_position_id` keep their
    original meaning (that slot's ORIGINAL starter, immutable once
    saved) -- who's CURRENTLY in a slot is derived, via
    `get_current_slot_occupant_id`/`get_current_slot_position_id`
    below, the batting-side equivalent of `get_current_pitcher_id`.
  - **GamePitch.batting_slot_id** (new nullable column) -- which slot
    the batter occupied at the moment a pitch was recorded, stamped by
    `_do_record_pitch` via `_resolve_current_batting_slot` for both the
    Squad A batting case and the intrasquad Squad B batting case (NULL
    for external-opponent batting, and for any pitch recorded before
    this migration ran). Lets "who's up next" look up the next slot
    directly instead of re-matching by player identity, which breaks
    once a player can be subbed out and later re-enter the same slot.
  - **Adding a brand-new slot** that wasn't part of the original saved
    lineup (an "extra hitter" cycling into a scrimmage for reps) is a
    DIFFERENT, simpler operation -- just another GameLineupSlot row,
    via `_insert_lineup_slot_at`. Per Ryker's explicit choice, new slots
    are insertable at ANY position in the batting order, not just
    appended -- every existing slot at or after the insertion point
    shifts `batting_order` +1 (processed highest-order-first, with a
    `db.flush()` after each shift, so no two slots are ever briefly
    equal). This is safe because every FK that references a slot
    (`LineupSubstitution.lineup_slot_id`, `GamePitch.batting_slot_id`)
    points at the slot's stable `lineup_slot_id` primary key, never at
    the mutable `batting_order` value -- renumbering never invalidates
    a past pitch's or substitution's slot reference.
  - **Migration**: migrations/migrate_lineup_substitutions.py (not yet
    run against the live database as of this commit -- run it once
    before this milestone's UI is used against real data). Existing
    games are unaffected: no LineupSubstitution rows yet, and every
    existing GamePitch row defaults batting_slot_id=NULL, so
    suggest_next_our_batter/suggest_next_squad_b_batter fall back to
    identity-matching (against each slot's CURRENT occupant) for those
    older pitches.
  - **who_is_up_identity_picker**: both squads' batter-choice lists now
    use `get_current_slot_occupant_id(s)` instead of `s.player_id`, so a
    substituted-in player becomes immediately pickable the moment a
    LineupSubstitution row exists for his slot.
  - **suggest_next_our_batter/suggest_next_squad_b_batter**: now
    slot-aware -- prefer the last recorded batting pitch's
    `batting_slot_id` (advance to the next slot by batting_order, return
    ITS current occupant), falling back to identity-matching against
    current occupants for older, pre-migration pitches where the column
    is NULL.
  - **_register_squad_lineup's _display()**: shows each slot's current
    occupant + current position (via the two new helpers), tagging a
    changed occupant "(sub)", instead of only ever showing the original
    starter -- so Lineup & Setup always reflects live reality.
    _picker()/_slots() (first-time lineup creation) are unchanged.
  - **_register_lineup_moves(squad, prefix)** -- new factory, called for
    both squads at server setup (Squad B's panel only renders when
    game.is_intrasquad, same guard opponent_scouting_card-adjacent
    blocks use elsewhere). Lives entirely in Live Tracking, not
    duplicated into Lineup & Setup, since these are live in-game events
    tied to the current inning/outs -- same reasoning
    _confirm_pitching_change already follows, and it reads
    _load_tracking_context's own state for inning/outs_at_entry rather
    than re-deriving it. Two accordion panels, mirroring the existing
    pitching-change accordion's shape: "Substitute into a slot" (slot
    select, labelled with the current occupant + optional
    position-change select, eligible incoming players excluding anyone
    via `_currently_occupied_player_ids`) and "Add a batting slot"
    (eligible incoming player + a batting-order-position select
    covering every position 1..N+1, defaulting to the end). Both
    confirm handlers bump BOTH `_pa_tick` (so the live Who's Up picker
    updates immediately) and `_refresh_tick` (so Lineup & Setup's
    display updates too) -- the one place on this page a single action
    needs both. Eligible-player dropdowns are computed fresh on each
    render from `_currently_occupied_player_ids`, not synced live via
    ui.update_select() the way `_sync_lineup_exclusions` does for
    initial lineup entry -- acceptable here since these panels remount
    on every `_pa_tick`, unlike the one-time lineup-entry form.
  - **No changes needed**: Undo Last Pitch (Milestone 1) only ever
    deletes the highest-pitch_sequence GamePitch row and never
    renumbers remaining sequences, so it has zero interaction with
    LineupSubstitution.pitch_sequence_at_entry ordering. The
    opponent-scouting card (Milestone 3) is entirely OpponentPlayer-keyed
    and orthogonal.
"""

import re
import time
from datetime import date

from shiny import module, ui, render, reactive, req
from shinywidgets import output_widget, render_plotly
from sqlalchemy.orm import joinedload

from database import get_session
from format_helpers import opponent_display_name as _opponent_display_name
import strike_zone
import field_location
from models import (
    Player, Position, PitchType, Game, GameLineupSlot, GamePitch, RunExpectancy,
    OpponentTeam, OpponentPlayer, Season, PitchingChange, PlayerPitchArsenal, OpponentLineupSlot,
    LineupSubstitution, GameRunnerEvent, GameForcedHalfInningEnd,
)
from game_stats import (
    get_pitching_pitches, get_batting_pitches, compute_pitching_line, compute_batting_line,
    get_pitches_thrown_to_opponent_batter, compute_pitch_type_breakdown,
)

import ui_helpers
import game_tracking_manage_display
import game_tracking_video_display
import game_tracking_pitch_log_display
import game_tracking_runner_events_display

ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

PITCH_OUTCOMES = ["Ball", "Called Strike", "Swing and Miss", "Foul", "In Play", "HBP"]
AB_OUTCOMES = [
    "K", "K (Looking)", "BB", "HBP", "1B", "2B", "3B", "HR", "E", "FC",
    "Sac Bunt", "Sac Fly", "Groundout", "Flyout", "Lineout", "Double Play",
]
# Both count as a strikeout/out everywhere stats are computed from
# ab_outcome (game_stats.py, analytics/pitcher_game_report.py) -- "K
# (Looking)" exists only so a strikeout looking shows as its own
# result here, per Ryker's request (Sept 2026).
K_OUTCOMES = ("K", "K (Looking)")
# Sept 2026, Ryker: renamed/expanded from Barrel/Solid/Weak/Miss so
# "weak contact" splits into how it was actually mishit. "Miss" stays
# a separate 6th value (swung and made literally no contact -- not a
# contact-quality tier at all) -- same categories shared with Hitter
# Tracking (see hitter_tracking.py's own copy of this list).
CONTACT_QUALITY_OPTIONS = ["Barreled/Squared Up", "Solid", "Jammed", "Off the End", "Clipped", "Miss"]

# Mid-plate-appearance base-running events -- see GameRunnerEvent's
# docstring in models.py for the full "why" (bases_before/outs_before
# previously had no way to change except on a pitch that ends the PA).
# RUNNER_EVENT_OUT_TYPES are the two that end in an out with no
# advance; every other type always advances (never an out) -- so the
# UI only ever needs to show a to-base picker OR an "out" note, never
# both, per event type.
RUNNER_EVENT_TYPES = ["Stolen Base", "Caught Stealing", "Picked Off", "Wild Pitch", "Passed Ball", "Balk", "Defensive Indifference"]
RUNNER_EVENT_OUT_TYPES = ("Caught Stealing", "Picked Off")

# Display-only label for each squad letter (Sep 2026, Ryker: show "Team
# 1/2/3" instead of "Squad A/B/C"). Purely cosmetic -- the underlying
# squad column values ('A'/'B'/'C', on GameLineupSlot/GamePitch.
# batting_squad/GameRunnerEvent.batting_squad) and every variable/
# function name built around them are UNCHANGED, so this is the only
# place that ever needs to change if the wording changes again.
TEAM_LABEL = {"A": "Team 1", "B": "Team 2", "C": "Team 3"}


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


def get_current_slot_occupant_id(slot):
    """Milestone 4 -- batting-side equivalent of get_current_pitcher_id
    above. A slot's current occupant is whoever the most recent
    LineupSubstitution for that slot says entered, falling back to the
    slot's original starter (GameLineupSlot.player_id) if no
    substitution has happened yet."""
    subs = sorted(slot.substitutions, key=lambda s: s.pitch_sequence_at_entry)
    if subs:
        return subs[-1].player_id
    return slot.player_id


def get_current_slot_position_id(slot):
    """Milestone 4 -- same "most recent, fall back to the original"
    idea as get_current_slot_occupant_id, but for the slot's current
    defensive position. A LineupSubstitution's new_position_id is only
    set when the incoming player takes over a DIFFERENT position (NULL
    means "unchanged from before"), so this walks the slot's
    substitution history newest-first for the first non-NULL
    new_position_id, falling all the way back to the slot's original
    starting_position_id if none was ever set."""
    subs = sorted(slot.substitutions, key=lambda s: s.pitch_sequence_at_entry, reverse=True)
    for s in subs:
        if s.new_position_id is not None:
            return s.new_position_id
    return slot.starting_position_id


def _currently_occupied_player_ids(game, squad):
    """Milestone 4 -- every player currently occupying a GameLineupSlot
    for this squad right now (original starters who haven't been subbed
    out, plus anyone substituted in since) -- used to exclude
    already-in-the-lineup players from the incoming-player choices on
    both "Substitute into a slot" and "Add a batting slot," so nobody
    can be picked into two slots at once."""
    slots = [s for s in game.lineup_slots if s.squad == squad]
    return {get_current_slot_occupant_id(s) for s in slots}


def _players_taken_by_other_squads(game, squad):
    """Which players are already committed to a DIFFERENT squad in this
    intrasquad game -- either in another squad's saved batting lineup
    (any slot, subbed-in occupant included) or as another squad's
    starting pitcher. Ryker's ask (Sep 2026): once a guy is picked for
    one team, he shouldn't show up as a pickable option for the other
    team(s) too -- a player can only be on one squad. Used to trim the
    batter/pitcher choices when SETTING UP a squad's lineup, and as the
    final save-time guard against a cross-squad duplicate slipping
    through (see _save below)."""
    other_squads = [s for s in ("A", "B", "C") if s != squad]
    taken = {get_current_slot_occupant_id(s) for s in game.lineup_slots if s.squad in other_squads}
    starting_pitcher_by_squad = {
        "A": game.starting_pitcher_id,
        "B": game.squad_b_starting_pitcher_id,
        "C": game.squad_c_starting_pitcher_id,
    }
    taken |= {starting_pitcher_by_squad[s] for s in other_squads}
    taken.discard(None)
    return taken


def _resolve_current_batting_slot(slots, batter_player_id):
    """Milestone 4 -- which GameLineupSlot the given batter currently
    occupies, used to stamp GamePitch.batting_slot_id at record time.
    Matches on each slot's CURRENT occupant (get_current_slot_occupant_id),
    not its original starter, so a substituted-in player is correctly
    attributed to the slot he entered. Returns None if batter_player_id
    doesn't currently occupy any slot in the list (an external opponent
    batter, or a squad with no saved lineup yet)."""
    if batter_player_id is None:
        return None
    for slot in slots:
        if get_current_slot_occupant_id(slot) == batter_player_id:
            return slot.lineup_slot_id
    return None


def _insert_lineup_slot_at(db, game_id, squad, batting_order_position, player_id, position_id):
    """Milestone 4 -- insert a brand-new GameLineupSlot at an arbitrary
    position in the batting order (an "extra hitter" who wasn't part of
    the original saved lineup, cycling into a scrimmage for reps).
    Every existing slot at or after the insertion point shifts
    batting_order +1, processed highest-order-first with a db.flush()
    after each shift so no two slots are ever briefly equal. Safe
    because every FK that references a slot (LineupSubstitution.
    lineup_slot_id, GamePitch.batting_slot_id) points at the slot's
    stable lineup_slot_id, never at the mutable batting_order value --
    see GameLineupSlot's docstring in models.py. Caller is responsible
    for committing."""
    shifting = (
        db.query(GameLineupSlot)
        .filter(
            GameLineupSlot.game_id == game_id,
            GameLineupSlot.squad == squad,
            GameLineupSlot.batting_order >= batting_order_position,
        )
        .order_by(GameLineupSlot.batting_order.desc())
        .all()
    )
    for slot in shifting:
        slot.batting_order += 1
        db.flush()
    new_slot = GameLineupSlot(
        game_id=game_id, squad=squad, batting_order=batting_order_position,
        player_id=player_id, starting_position_id=position_id,
    )
    db.add(new_slot)
    db.flush()
    return new_slot


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
    """Milestone 4 -- now slot-aware: prefers the last recorded batting
    pitch's batting_slot_id (a direct slot lookup, correct even after a
    substitution), falling back to identity-matching against each
    slot's CURRENT occupant for older, pre-migration pitches where that
    column is NULL. Always returns the resolved slot's CURRENT occupant
    (get_current_slot_occupant_id), not necessarily who started there."""
    if not lineup_slots:
        return None
    our_pa_endings = sorted(
        [p for p in game.pitches if p.is_our_team_batting and p.ends_plate_appearance],
        key=lambda p: p.pitch_sequence,
    )
    if not our_pa_endings:
        return get_current_slot_occupant_id(lineup_slots[0])
    last_pitch = our_pa_endings[-1]
    if last_pitch.batting_slot_id is not None:
        last_slot = next((s for s in lineup_slots if s.lineup_slot_id == last_pitch.batting_slot_id), None)
    else:
        last_batter_id = last_pitch.our_player_id
        last_slot = next((s for s in lineup_slots if get_current_slot_occupant_id(s) == last_batter_id), None)
    if last_slot is None:
        return get_current_slot_occupant_id(lineup_slots[0])
    slot_orders = sorted(s.batting_order for s in lineup_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    next_slot = next((s for s in lineup_slots if s.batting_order == next_order), lineup_slots[0])
    return get_current_slot_occupant_id(next_slot)


def suggest_next_squad_b_batter(game, squad_b_slots):
    """Milestone 4 -- see suggest_next_our_batter above; identical
    slot-aware logic, mirrored for Squad B's opponent_our_player_id/
    opponent-side pitch fields."""
    if not squad_b_slots:
        return None
    squad_b_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_our_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if not squad_b_pa_endings:
        return get_current_slot_occupant_id(squad_b_slots[0])
    last_pitch = squad_b_pa_endings[-1]
    if last_pitch.batting_slot_id is not None:
        last_slot = next((s for s in squad_b_slots if s.lineup_slot_id == last_pitch.batting_slot_id), None)
    else:
        last_batter_id = last_pitch.opponent_our_player_id
        last_slot = next((s for s in squad_b_slots if get_current_slot_occupant_id(s) == last_batter_id), None)
    if last_slot is None:
        return get_current_slot_occupant_id(squad_b_slots[0])
    slot_orders = sorted(s.batting_order for s in squad_b_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    next_slot = next((s for s in squad_b_slots if s.batting_order == next_order), squad_b_slots[0])
    return get_current_slot_occupant_id(next_slot)


# ---------------------------------------------------------------------
# Three-squad intrasquad mode (Sep 2026) -- helpers below are ONLY ever
# exercised for a game with uses_three_squad_intrasquad=True. See
# Game.uses_three_squad_intrasquad's docstring in models.py for the
# overall design: deliberately ADDITIVE, existing two-squad games are
# completely untouched by any of this.
#
# One structural note that explains several of the functions below:
# is_our_team_batting keeps alternating exactly as compute_current_state
# (UNCHANGED -- not touched by this feature at all) already makes it --
# outs/bases/inning tracking and run-expectancy stay exactly as
# reliable as they've always been. What CHANGES for a three-squad pitch
# is which id column that alternating flag points the BATTER at:
# our_player_id holds the batter when is_our_team_batting is True,
# opponent_our_player_id holds the batter when it's False (and the
# free-picked PITCHER sits in whichever of the two columns isn't the
# batter) -- the same "our_player_id flips role" convention Squad A/
# Squad B already use, just generalized so "our" isn't pinned to Squad
# A specifically. batting_squad ('A'/'B'/'C', stamped on the row
# separately) is what actually records which of the three squads was
# up, independent of that alternating column-role bookkeeping -- see
# _do_record_pitch.
# ---------------------------------------------------------------------

_THREE_SQUAD_ROTATION = {"A": "B", "B": "C", "C": "A"}


def suggest_current_batting_squad(pitches, state):
    """Which squad ('A'/'B'/'C') is up right now, in a three-squad game
    -- auto-suggested default for the live "team up to bat" picker
    (always overridable, same as every other suggestion on this page),
    and also used to resolve batting_squad for a mid-PA pitch/runner
    event so it stays the same squad the PA already started with.
    Deliberately reuses `state` (compute_current_state's UNCHANGED
    output) rather than re-deriving outs/rollover itself: a rollover
    to the next squad happened if and only if the game's inning
    advanced past the last three-squad pitch's own inning -- true
    whether that rollover came from the pitch's own outs_after or from
    a runner event supplying the 3rd out (compute_current_state
    already folds both into `state["inning"]` identically). Falls back
    to 'A' when no three-squad pitch has been recorded yet this game
    (including every ordinary, non-three-squad game, whose pitches
    never set batting_squad at all)."""
    relevant = [p for p in pitches if p.batting_squad]
    if not relevant:
        return "A"
    last = relevant[-1]
    if state["inning"] > last.inning:
        return _THREE_SQUAD_ROTATION.get(last.batting_squad, "A")
    return last.batting_squad


def _three_squad_batter_id(pitch):
    """Which id column holds the BATTER on a given three-squad pitch --
    see the module-level note above this section."""
    return pitch.our_player_id if pitch.is_our_team_batting else pitch.opponent_our_player_id


def _three_squad_pitcher_id(pitch):
    """Which id column holds the PITCHER on a given three-squad pitch
    -- the complement of _three_squad_batter_id, see the note above."""
    return pitch.opponent_our_player_id if pitch.is_our_team_batting else pitch.our_player_id


def suggest_next_squad_batter(game, squad, slots):
    """Three-squad intrasquad games only -- mirrors suggest_next_our_batter/
    suggest_next_squad_b_batter's slot-aware "last PA's slot + 1" logic,
    keyed on GamePitch.batting_squad instead of is_our_team_batting/
    opponent_our_player_id directly (see _three_squad_batter_id for why
    the batter's id isn't in a fixed column here). Returns None when
    this squad has no saved lineup yet -- same free-pick fallback every
    other squad already has."""
    if not slots:
        return None
    squad_pa_endings = sorted(
        [p for p in game.pitches if p.batting_squad == squad and p.ends_plate_appearance],
        key=lambda p: p.pitch_sequence,
    )
    if not squad_pa_endings:
        return get_current_slot_occupant_id(slots[0])
    last_pitch = squad_pa_endings[-1]
    if last_pitch.batting_slot_id is not None:
        last_slot = next((s for s in slots if s.lineup_slot_id == last_pitch.batting_slot_id), None)
    else:
        last_batter_id = _three_squad_batter_id(last_pitch)
        last_slot = next((s for s in slots if get_current_slot_occupant_id(s) == last_batter_id), None)
    if last_slot is None:
        return get_current_slot_occupant_id(slots[0])
    slot_orders = sorted(s.batting_order for s in slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    next_slot = next((s for s in slots if s.batting_order == next_order), slots[0])
    return get_current_slot_occupant_id(next_slot)


def get_current_three_squad_pitcher_id(game):
    """Three-squad intrasquad games only -- mirrors
    get_current_squad_b_pitcher_id's "most recently used, no formal
    pitching-change history" idea, as a DEFAULT for the live free-pick
    pitcher picker (always overridable per plate appearance). Checks
    whichever of the two id columns actually holds the pitcher on the
    most recent three-squad pitch -- see _three_squad_pitcher_id."""
    candidates = sorted([p for p in game.pitches if p.batting_squad], key=lambda p: p.pitch_sequence)
    if not candidates:
        return None
    return _three_squad_pitcher_id(candidates[-1])


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

    if ab_outcome in K_OUTCOMES + ("Groundout", "Flyout", "Lineout"):
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

    # 3rd out ends the half-inning -- any runners still shown on base
    # don't carry over (Ryker, Sept 2026: base state should auto-clear
    # once 3 outs are recorded, not require a manual fix on the "Bases
    # after" field). compute_current_state already treats outs>=3 as
    # 000 for computing the NEXT pitch's starting state either way --
    # this makes the stored bases_after for THIS pitch, and what the
    # picker defaults to, agree with that instead of showing whoever
    # was left on base when the out was made.
    if outs >= 3:
        b = ["0", "0", "0"]

    return outs, "".join(b), runs


def apply_runner_events(bases, outs, events):
    """Folds a chronological list of GameRunnerEvent rows onto a
    (bases, outs) pair -- from_base's bit always clears (the runner
    leaves that base, whether by advancing, scoring, or being put out);
    to_base's bit sets only when there IS one (an out, or a run scored
    via to_base == 4, leaves no base occupied). Each is_out event adds
    one out. Does NOT itself roll to the next half-inning -- callers
    (compute_current_state) apply that uniformly, the same way whether
    the 3rd out came from a PA-ending pitch or a runner event."""
    b = list(bases or "000")
    for ev in events:
        idx = ev.from_base - 1
        if 0 <= idx < 3:
            b[idx] = "0"
        if not ev.is_out and ev.to_base in (2, 3):
            b[ev.to_base - 1] = "1"
        if ev.is_out:
            outs += 1
    return "".join(b), outs


def compute_current_state(pitches, runner_events=None, forced_ends=None):
    """runner_events: every GameRunnerEvent for this game (any order --
    this function sorts and filters). Folded in AFTER the pitch-derived
    state below, using the SAME rollover rule (outs >= 3 -> next half-
    inning) whether the pitch-derived state or a runner event supplied
    the 3rd out -- see GameRunnerEvent's docstring in models.py for why
    this exists at all (mid-PA base-running events previously had no
    way to change bases/outs).

    forced_ends: every GameForcedHalfInningEnd for this game (any
    order). Folded in last, at the same anchor -- but UNCONDITIONALLY
    rolls to the next half-inning (a coach ended it here on purpose),
    regardless of whatever bases/outs the pitch- and runner-event-
    derived state above just computed. See models.GameForcedHalfInningEnd's
    docstring."""
    runner_events = runner_events or []
    forced_ends = forced_ends or []
    if not pitches:
        state = {
            "inning": 1, "is_our_batting": True, "outs": 0, "bases": "000",
            "balls": 0, "strikes": 0, "pa_pitch_number": 1, "new_pa": True,
        }
        anchor = 0
    else:
        last = pitches[-1]
        anchor = last.pitch_sequence
        if not last.ends_plate_appearance:
            balls = (last.balls_before or 0) + (1 if last.pitch_outcome == "Ball" else 0)
            strikes = (last.strikes_before or 0)
            if last.pitch_outcome in ("Called Strike", "Swing and Miss"):
                strikes += 1
            elif last.pitch_outcome == "Foul" and strikes < 2:
                strikes += 1
            state = {
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
            state = {
                "inning": inning, "is_our_batting": is_our_batting,
                "outs": outs, "bases": bases,
                "balls": 0, "strikes": 0, "pa_pitch_number": 1, "new_pa": True,
            }

    pending = sorted(
        [e for e in runner_events if e.pitch_sequence_after == anchor],
        key=lambda e: e.created_at,
    )
    if pending:
        bases, outs = apply_runner_events(state["bases"], state["outs"], pending)
        if outs >= 3:
            # A runner event (caught stealing / picked off) supplied the
            # 3rd out mid-PA -- the batter's partial plate appearance
            # (whatever count he'd worked to) just ends with no
            # ends_plate_appearance row of its own, same as any other
            # incomplete trailing PA this schema already tolerates.
            state["inning"] += 1
            state["is_our_batting"] = not state["is_our_batting"]
            outs, bases = 0, "000"
            state["balls"], state["strikes"], state["pa_pitch_number"], state["new_pa"] = 0, 0, 1, True
            for k in ("current_our_player", "current_opp_hand", "current_opp_order", "current_opp_player", "current_opp_our_player"):
                state.pop(k, None)
        state["outs"], state["bases"] = outs, bases

    # Loop (not `any(...)`) so two forced ends anchored at the identical
    # pitch (a real, supported case -- see the game #14 forced-end rows
    # from Sept 2026) each apply their own rollover instead of only one
    # of them counting, matching replay_game's own per-fe loop below.
    for fe in (e for e in forced_ends if e.pitch_sequence_after == anchor):
        state["inning"] += 1
        if not fe.same_side_continues:
            state["is_our_batting"] = not state["is_our_batting"]
        state["outs"], state["bases"] = 0, "000"
        state["balls"], state["strikes"], state["pa_pitch_number"], state["new_pa"] = 0, 0, 1, True
        for k in ("current_our_player", "current_opp_hand", "current_opp_order", "current_opp_player", "current_opp_our_player"):
            state.pop(k, None)

    return state


def replay_game(pitches, runner_events, re_lookup, forced_ends=None):
    """Recompute every pitch's forward-derived chain (balls_before,
    strikes_before, outs_before, bases_before, inning, is_our_team_batting,
    pa_pitch_number, re_before, re_after, run_value) plus the game's
    score totals, by walking the ENTIRE game from the start -- unlike
    compute_current_state (above), which only ever looks at the single
    last-recorded pitch to figure out what the NEXT pitch's state should
    be. This is that same one-step transition, just applied at every
    step of a full replay instead of once at the end.

    Built for the Pitch Log "edit any past pitch" feature (Ryker, Sept
    2026: "can we adjust game tracking to be able and go back and edit
    anything that has happened but not having to undo pitches"). Editing
    an EARLIER pitch's pitch_outcome/ab_outcome/outs_after/bases_after/
    runs_scored_on_play silently desyncs every later pitch's stored
    chain fields, since those were only ever computed once, at insert
    time, from whatever came before them at THAT moment -- nothing
    re-derives them when an earlier row changes. This function is the
    fix: give it the game's full pitch list (with a pending, not-yet-
    committed edit already applied in memory by the caller -- see
    game_tracking_pitch_log_display._save_pitch_log_edit) and every
    GameRunnerEvent, and it returns what SHOULD be stored everywhere,
    so the caller can diff against what IS stored and write only what
    changed.

    Deliberately INPUT, never recomputed/returned, because these are
    facts about what actually happened (or the coach's own judgment
    calls), not something derivable from count math: ab_outcome,
    outs_after, bases_after, runs_scored_on_play, unearned_runs_on_play,
    ends_plate_appearance, pitch_outcome, pitch_type_id, every location/
    contact/batted-ball field, notes, our_player_id, opponent_hand,
    opponent_player_id, opponent_our_player_id, opponent_batting_order,
    batting_slot_id, batting_squad, pitch_sequence. Each historical
    row's own ends_plate_appearance/outs_after/bases_after/
    runs_scored_on_play is trusted as given -- this only recomputes the
    count/RE/RV/inning/side chain that flows FROM those facts, exactly
    the same way compute_current_state does for one pitch at a time.

    inning and is_our_team_batting ARE recomputed/returned (an earlier
    edit that changes how many outs a half-inning took can shift where
    every later half-inning boundary falls) -- but a pitch whose
    recomputed inning/is_our_team_batting differs from what's currently
    stored is also listed separately in side_changed_pitch_ids, because
    that pitch's already-recorded our_player_id/opponent_* identity
    fields describe who was ACTUALLY batting/pitching live and this
    function has no way to know who that should be instead -- reassigning
    those is a human judgment call (see the module docstring's Milestone
    on Pitch Log editing), not something this replay attempts.

    Score reconstruction sums every PA-ending pitch's runs_scored_on_play
    and every runner event's to_base == 4, crediting our_score/
    opponent_score/squad_c_score with the exact same 5-way branch used
    at every other score-mutating site in this file (batting_squad
    'A'/'B'/'C' first, falling back to is_our_team_batting for ordinary
    two-side games) -- except that for a pitch, the is_our_team_batting
    used in that fallback is the just-RECOMPUTED value for that pitch
    (the value this function is about to have the caller write onto the
    row), not the stale stored one -- so the score total this function
    returns always agrees with the inning/side chain it also returns.
    batting_squad itself is never recomputed (same reasoning as player
    identity above: which of three squads was actually up isn't
    derivable from count math), so a three-squad game with a side change
    still needs the same manual review flagged by side_changed_pitch_ids.
    Runner events are simpler: neither their is_our_team_batting nor
    their batting_squad is ever recomputed (events aren't reordered or
    re-attributed by this function), so their score credit always uses
    their own stored values, unchanged.

    Args:
        pitches: every GamePitch for one game (any order -- sorted here
            by pitch_sequence). May already have one pending, not-yet-
            committed edit applied in memory; that's the caller's job.
        runner_events: every GameRunnerEvent for the same game (any
            order -- sorted here, same as compute_current_state).
        forced_ends: every GameForcedHalfInningEnd for the same game
            (any order), folded in at its own pitch_sequence_after the
            same way a runner event supplying the 3rd out is, except it
            ALWAYS forces the rollover (outs to 3, bases to "000",
            inning +1, is_our_team_batting flips) regardless of the
            actual bases/outs at that point, and its own runs_scored is
            credited via the same batting_squad/is_our_team_batting
            5-way branch every other score site here uses -- see
            models.GameForcedHalfInningEnd's docstring. Defaults to
            None/[] so every existing caller (no forced ends yet) is
            unaffected.
        re_lookup: build_re_lookup(db)'s {(outs, bases, count): re_value}
            dict.

    Returns a dict:
        "by_pitch": {game_pitch_id: {"balls_before", "strikes_before",
            "outs_before", "bases_before", "inning", "is_our_team_batting",
            "pa_pitch_number", "re_before", "re_after", "run_value"}}
            for every pitch passed in.
        "side_changed_pitch_ids": game_pitch_ids where the recomputed
            inning or is_our_team_batting differs from what's currently
            stored on that row.
        "our_score", "opponent_score", "squad_c_score": reconstructed
            from scratch (not incremental deltas).
    """
    ordered_pitches = sorted(pitches, key=lambda p: p.pitch_sequence)
    events = list(runner_events or [])
    forced = list(forced_ends or [])

    state = {
        "inning": 1, "is_our_batting": True, "outs": 0, "bases": "000",
        "balls": 0, "strikes": 0, "pa_pitch_number": 1,
    }
    our_score = opponent_score = squad_c_score = 0

    def _credit(batting_squad, is_our_team_batting, runs):
        nonlocal our_score, opponent_score, squad_c_score
        if not runs:
            return
        if batting_squad == "A":
            our_score += runs
        elif batting_squad == "B":
            opponent_score += runs
        elif batting_squad == "C":
            squad_c_score += runs
        elif is_our_team_batting:
            our_score += runs
        else:
            opponent_score += runs

    def _fold_pending(anchor_seq):
        pending = sorted(
            (e for e in events if e.pitch_sequence_after == anchor_seq),
            key=lambda e: e.created_at,
        )
        for ev in pending:
            if ev.is_out is False and ev.to_base == 4:
                _credit(ev.batting_squad, ev.is_our_team_batting, 1)
        if pending:
            bases, outs = apply_runner_events(state["bases"], state["outs"], pending)
            if outs >= 3:
                state["inning"] += 1
                state["is_our_batting"] = not state["is_our_batting"]
                outs, bases = 0, "000"
                state["balls"], state["strikes"], state["pa_pitch_number"] = 0, 0, 1
            state["outs"], state["bases"] = outs, bases

        # Forced half-inning ends (models.GameForcedHalfInningEnd) --
        # same anchor convention, but ALWAYS roll over (a coach ended
        # it here on purpose, regardless of the real out count) and
        # credit its own runs_scored, all-earned, to whichever score
        # column its batting_squad/is_our_team_batting resolves to.
        for fe in (e for e in forced if e.pitch_sequence_after == anchor_seq):
            _credit(fe.batting_squad, fe.is_our_team_batting, fe.runs_scored)
            state["inning"] += 1
            if not fe.same_side_continues:
                state["is_our_batting"] = not state["is_our_batting"]
            state["outs"], state["bases"] = 0, "000"
            state["balls"], state["strikes"], state["pa_pitch_number"] = 0, 0, 1

    by_pitch = {}
    side_changed_pitch_ids = []

    # Events recorded before this game's very first pitch (anchor 0),
    # same convention compute_current_state uses for an empty pitch list.
    _fold_pending(0)

    for p in ordered_pitches:
        by_pitch[p.game_pitch_id] = {
            "balls_before": state["balls"],
            "strikes_before": state["strikes"],
            "outs_before": state["outs"],
            "bases_before": state["bases"],
            "inning": state["inning"],
            "is_our_team_batting": state["is_our_batting"],
            "pa_pitch_number": state["pa_pitch_number"],
        }
        if state["inning"] != p.inning or state["is_our_batting"] != p.is_our_team_batting:
            side_changed_pitch_ids.append(p.game_pitch_id)

        ends_pa = bool(p.ends_plate_appearance)
        if ends_pa:
            new_balls = new_strikes = None
        else:
            new_balls = state["balls"] + (1 if p.pitch_outcome == "Ball" else 0)
            new_strikes = state["strikes"]
            if p.pitch_outcome in ("Called Strike", "Swing and Miss"):
                new_strikes += 1
            elif p.pitch_outcome == "Foul" and new_strikes < 2:
                new_strikes += 1

        re_before, re_after, run_value = compute_re_and_rv(
            re_lookup, state["outs"], state["bases"], state["balls"], state["strikes"],
            ends_pa, p.outs_after if ends_pa else None, p.bases_after if ends_pa else None,
            (p.runs_scored_on_play or 0) if ends_pa else 0,
            new_balls=new_balls, new_strikes=new_strikes,
        )
        by_pitch[p.game_pitch_id]["re_before"] = re_before
        by_pitch[p.game_pitch_id]["re_after"] = re_after
        by_pitch[p.game_pitch_id]["run_value"] = run_value

        if ends_pa and p.runs_scored_on_play:
            # Use the just-recomputed is_our_team_batting (state["is_our_batting"],
            # already stashed above as this pitch's "is_our_team_batting" result)
            # rather than the pitch's own stale stored value, so the score this
            # function returns always agrees with the side/inning chain it also
            # returns -- see docstring.
            _credit(p.batting_squad, state["is_our_batting"], p.runs_scored_on_play)

        if not ends_pa:
            state["balls"], state["strikes"] = new_balls, new_strikes
            state["pa_pitch_number"] = (state["pa_pitch_number"] or 1) + 1
            # inning/is_our_batting/outs/bases are unchanged by a pitch
            # that doesn't end the PA.
        else:
            outs = p.outs_after if p.outs_after is not None else state["outs"]
            bases = p.bases_after if p.bases_after is not None else "000"
            inning = state["inning"]
            is_our_batting = state["is_our_batting"]
            if outs >= 3:
                inning += 1
                is_our_batting = not is_our_batting
                outs, bases = 0, "000"
            state["inning"], state["is_our_batting"] = inning, is_our_batting
            state["outs"], state["bases"] = outs, bases
            state["balls"], state["strikes"], state["pa_pitch_number"] = 0, 0, 1

        _fold_pending(p.pitch_sequence)

    return {
        "by_pitch": by_pitch,
        "side_changed_pitch_ids": side_changed_pitch_ids,
        "our_score": our_score,
        "opponent_score": opponent_score,
        "squad_c_score": squad_c_score,
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
    docstring), so there's no stat line to show for them.

    Three-squad intrasquad games are handled first and separately --
    see suggest_current_batting_squad's module-level note for the
    "pitcher sits in whichever of our_player_id/opponent_our_player_id
    isn't the batter" convention this mirrors."""
    if game.uses_three_squad_intrasquad:
        if not state["new_pa"]:
            cur_our, cur_opp = state.get("current_our_player"), state.get("current_opp_our_player")
            return cur_opp if state["is_our_batting"] else cur_our
        return get_current_three_squad_pitcher_id(game)
    if state["is_our_batting"]:
        if game.is_intrasquad:
            return get_current_squad_b_pitcher_id(game)
        return None
    return get_current_pitcher_id(game)


def _resolve_current_hitter_id_for_stats(game, state, squad_a_slots, squad_b_slots, squad_c_slots=None):
    """Mirrors _resolve_current_pitcher_id_for_stats for the current
    batter. Mid-PA (state['new_pa'] is False), the committed identity
    is already on `state`. At the start of a new PA, nothing's been
    committed yet, so this falls back to the same suggestion the
    who's-up picker itself shows (suggest_next_our_batter /
    suggest_next_squad_b_batter / suggest_next_squad_batter) -- a
    reasonable "who's up" answer for a dashboard even before the coach
    has explicitly confirmed it. Returns None for a genuine external
    opponent's batter (an OpponentPlayer, not one of our own Players --
    no game_stats.py line available for them, same reasoning as the
    pitcher side)."""
    if game.uses_three_squad_intrasquad:
        if not state["new_pa"]:
            cur_our, cur_opp = state.get("current_our_player"), state.get("current_opp_our_player")
            return cur_our if state["is_our_batting"] else cur_opp
        squad = suggest_current_batting_squad(game.pitches, state)
        slots = {"A": squad_a_slots, "B": squad_b_slots, "C": squad_c_slots or []}.get(squad, [])
        return suggest_next_squad_batter(game, squad, slots) if slots else None
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


def _ends_plate_appearance(state, outcome, force=False):
    """force=True (from the "This pitch ends the at-bat" override
    checkbox, see pitch_outcome_dependent_fields) makes the AB Result
    picker show up regardless of the ball/strike math below -- a
    manual escape hatch for anything the automatic count doesn't
    already cover (Ryker, Sept 2026: needed a guaranteed way to record
    a hit-by-pitch, or confirm a walk, no matter what count it
    happened on)."""
    new_balls = state["balls"] + (1 if outcome == "Ball" else 0)
    new_strikes = state["strikes"]
    if outcome in ("Called Strike", "Swing and Miss"):
        new_strikes += 1
    elif outcome == "Foul" and new_strikes < 2:
        new_strikes += 1
    ends_pa = force or outcome == "In Play" or outcome == "HBP" or new_balls >= 4 or (new_strikes >= 3 and outcome != "Foul")
    return ends_pa, new_balls, new_strikes


def _game_label(g):
    loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
    season_label = f"[{g.season.season_name}] " if g.season else ""
    return f"{season_label}{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status}) — {g.our_score}-{g.opponent_score}"


# _build_clickable_widget used to be defined here directly -- moved to
# the repo-root click_widgets.py (see that module's docstring, including
# the Aug 2026 pivot away from register_click_to_numeric's broken
# FigureWidget.on_click() round-trip to click_widgets.click_target()'s
# plain client-side listener) so Command Tracker's location widgets can
# reuse the exact same click-capture code instead of a second
# copy-pasted implementation. build_clickable_widget aliased back to its
# original name on import so every call site below is unchanged;
# click_target() is used via the click_widgets module directly at each
# output_widget(...) call site (see live_tracking_body/video review UI).
import click_widgets  # noqa: E402
from click_widgets import build_clickable_widget as _build_clickable_widget  # noqa: E402


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
    _is_submitting = reactive.Value(False)  # duplicate-submission guard for _record_pitch, see module docstring

    # Pitch Log edit/delete -- same lazy per-row button registration shape
    # as Video Review's _registered_clip_match_ids (and as Command Tracker's own
    # pitch log, shiny_app/modules/command_tracker.py's
    # _registered_pitch_row_ids), applied to GamePitch rows instead of
    # video clips. Only one row can be mid-edit or mid-delete-confirm at
    # once, so those two states are fixed-id reactive.Values rather than
    # needing per-row storage themselves -- the per-row buttons only need
    # to know their OWN pitch id, which they get via closure at
    # registration time (see _register_pitch_row_handlers).
    _registered_pitch_row_ids = set()
    _gt_editing_pitch_id = reactive.Value(None)
    _gt_pending_delete_pitch_id = reactive.Value(None)
    _pitch_log_limit = reactive.Value(50)  # "Load more" bumps this by 50 at a time -- see pitch_log_body
    # Set only while a state-affecting Pitch Log edit (pitch_outcome/
    # ab_outcome/ends_plate_appearance/outs_after/bases_after/
    # runs_scored_on_play/unearned_runs_on_play) is awaiting the
    # coach's explicit "Confirm & Save" -- holds the pending edit's
    # values plus the replay_game()-computed preview to render. See
    # game_tracking_pitch_log_display.py's module docstring for the
    # full preview-then-confirm design (Sept 2026, Ryker: "can we
    # adjust game tracking to be able and go back and edit anything
    # that has happened but not having to undo pitches").
    _gt_pl_pending_preview = reactive.Value(None)
    # Pending "End half-inning after this pitch" confirmation (Pitch Log
    # retroactive fix -- see forced_half_inning_end_panel above for the
    # live version, and game_tracking_pitch_log_display.py for how this
    # is built/rendered/confirmed). A separate Value from
    # _gt_pl_pending_preview above rather than reusing it -- inserting a
    # brand-new GameForcedHalfInningEnd is a different shape of pending
    # action from "here's the edited pitch's replay preview", and
    # keeping them separate avoids teaching that dict two shapes.
    _gt_pl_pending_forced_end = reactive.Value(None)
    # Retroactive "Log runner event after this pitch" (Pitch Log --
    # the counterpart to the live "+ Log a runner event" form in
    # runner_events_panel below, which can only ever anchor to
    # whatever pitch was just thrown; this one can anchor to ANY
    # past pitch in an already-tracked game, live or completed --
    # Ryker, Sept 2026: "if i need to add a runner event to
    # something that i logged before how do i do that"). Two
    # separate Values, same reasoning as the forced-end pair above:
    # _gt_pl_adding_runner_event_pitch_id is which pitch's row has
    # the add-form open (None otherwise); _gt_pl_pending_runner_add
    # is the built-but-not-yet-saved preview once that form is
    # submitted (see game_tracking_pitch_log_display.py).
    _gt_pl_adding_runner_event_pitch_id = reactive.Value(None)
    _gt_pl_pending_runner_add = reactive.Value(None)
    _runner_event_form_open = reactive.Value(False)  # collapsed by default -- see runner_events_panel (Ryker, 2026-08-26)
    _forced_end_form_open = reactive.Value(False)  # collapsed by default -- see forced_half_inning_end_panel (Ryker, Sept 2026)

    # Runner Events Log tab (Sept 2026, Ryker: "also need to be able to
    # edit runner events such as wild pitch, stolen base etc.") -- same
    # editing/delete/preview-then-confirm shape as Pitch Log, since a
    # GameRunnerEvent feeds replay_game exactly like a GamePitch does.
    # See game_tracking_runner_events_display.py's module docstring.
    _registered_runner_event_row_ids = set()
    _gt_re_editing_event_id = reactive.Value(None)
    # Holds either an edit-preview (kind="edit", built after "Save" on a
    # state-affecting field change) or a delete-preview (kind="delete",
    # built immediately on "Delete" -- deleting an event always needs a
    # replay pass too, since it might have supplied an out or a base
    # advance later state depends on, unlike Pitch Log's delete which
    # is safe without one; see game_tracking_runner_events_display.py).
    # No separate pending-delete Value needed -- delete has no form of
    # its own to show before its preview, unlike edit.
    _gt_re_pending_preview = reactive.Value(None)

    def _bump_refresh():
        _refresh_tick.set(_refresh_tick() + 1)

    def _bump_pa():
        _pa_tick.set(_pa_tick() + 1)

    def _access_ok():
        if not app_state.is_authenticated():
            return False
        return app_state.role_name() in ALLOWED_ROLES

    def _can_edit():
        return app_state.can_edit_sessions() or app_state.role_name() in ("Data Analyst", "Video Coordinator")

    def _resolve_current_opponent_batter_id(game, state):
        """Milestone 3 -- see module docstring. Which OpponentPlayer is
        up right now, for opponent_scouting_card below -- only
        meaningful when we're pitching (state['is_our_batting'] is
        False) against a genuine external opponent (never intrasquad,
        which has no OpponentPlayer rows at all -- Squad B batters are
        just our own Players, already covered by
        _resolve_current_hitter_id_for_stats). Mid-PA, the committed
        identity already lives on state (compute_current_state's
        'current_opp_player'). At the start of a new PA, nothing's
        committed yet, so this reads whatever's currently selected in
        opp_roster_player_select -- the same picker
        who_is_up_identity_picker shows, defined in a separate render
        block, so reading it here is fine (see this file's read/define
        rule)."""
        if game.is_intrasquad or state["is_our_batting"]:
            return None
        if not state["new_pa"]:
            return state.get("current_opp_player")
        if "opp_roster_player_select" in input and input.opp_roster_player_select():
            return int(input.opp_roster_player_select())
        return None

    def _load_tracking_context(db, game_id):
        game = (
            db.query(Game)
            .options(
                joinedload(Game.pitching_changes), joinedload(Game.runner_events),
                joinedload(Game.forced_half_inning_ends),
            )
            .filter(Game.game_id == game_id)
            .first()
        )
        if game is None:
            return None
        pitches = sorted(game.pitches, key=lambda p: p.pitch_sequence)
        runner_events = sorted(game.runner_events, key=lambda e: (e.pitch_sequence_after, e.created_at))
        forced_ends = sorted(game.forced_half_inning_ends, key=lambda e: e.pitch_sequence_after)
        squad_a_slots = (
            db.query(GameLineupSlot).options(joinedload(GameLineupSlot.player), joinedload(GameLineupSlot.substitutions))
            .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == "A")
            .order_by(GameLineupSlot.batting_order).all()
        )
        squad_b_slots = (
            db.query(GameLineupSlot).options(joinedload(GameLineupSlot.player), joinedload(GameLineupSlot.substitutions))
            .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == "B")
            .order_by(GameLineupSlot.batting_order).all()
        )
        # Only ever populated for uses_three_squad_intrasquad games (Squad
        # C lineup slots only ever get created for those, via
        # _register_squad_lineup("C", ...) above) -- an empty list for
        # every other game, same as squad_a_slots/squad_b_slots are empty
        # lists (not None) when no lineup has been saved yet.
        squad_c_slots = (
            db.query(GameLineupSlot).options(joinedload(GameLineupSlot.player), joinedload(GameLineupSlot.substitutions))
            .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == "C")
            .order_by(GameLineupSlot.batting_order).all()
        )
        opponent_lineup_slots = (
            db.query(OpponentLineupSlot).options(joinedload(OpponentLineupSlot.opponent_player))
            .filter(OpponentLineupSlot.game_id == game_id)
            .order_by(OpponentLineupSlot.batting_order).all()
        )
        state = compute_current_state(pitches, runner_events, forced_ends)
        # squad_c_slots is appended at the END of this tuple (not
        # interleaved alongside squad_a_slots/squad_b_slots) so every
        # existing index-based access (ctx[0], ctx[5], etc.) elsewhere in
        # this file keeps pointing at exactly what it always has.
        return game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots

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
        # Per-game Pitch Log UI state shouldn't survive a switch to a
        # different game -- same reasoning as Command Tracker's
        # _sync_active_bullpen_id resetting its own editing/delete state
        # on a real session switch (this session's earlier fix for a
        # stale-state bug of the same shape).
        _gt_editing_pitch_id.set(None)
        _gt_pending_delete_pitch_id.set(None)
        _pitch_log_limit.set(50)
        _gt_pl_pending_preview.set(None)
        _gt_pl_pending_forced_end.set(None)
        _gt_pl_adding_runner_event_pitch_id.set(None)
        _gt_pl_pending_runner_add.set(None)
        _gt_re_editing_event_id.set(None)
        _gt_re_pending_preview.set(None)

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
                ui.input_checkbox("new_game_intrasquad", "Intrasquad scrimmage (Team 1 vs Team 2, our own roster on both sides)"),
                ui.input_checkbox("new_game_three_squad", "Three-team intrasquad (Team 1/2/3 rotating through, one team bats while the other two field -- only used when Intrasquad scrimmage above is also checked)"),
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
        uses_three_squad = bool(is_intrasquad and "new_game_three_squad" in input and input.new_game_three_squad())
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
                uses_three_squad_intrasquad=uses_three_squad,
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
            score_cards = (
                [
                    {"label": "Team 1", "value": str(g.our_score)},
                    {"label": "Team 2", "value": str(g.opponent_score)},
                    {"label": "Team 3", "value": str(g.squad_c_score)},
                ]
                if g.uses_three_squad_intrasquad else
                [
                    {"label": "Us", "value": str(g.our_score)},
                    {"label": "Opponent", "value": str(g.opponent_score)},
                ]
            )
            return ui.div(
                ui.hr(),
                ui.h4(title, class_="gbo-section-title"),
                ui_helpers.render_kpi_cards(score_cards + [{"label": "Status", "value": g.status}]),
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
            ui.nav_panel("Runner Events", ui.output_ui("runner_events_log_body")),
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
            ui.output_ui("squad_a_lineup_edit_body"),
            ui.hr(),
            ui.output_ui("squad_b_lineup_setup_picker"),
            ui.output_ui("squad_b_lineup_slots_body"),
            ui.output_ui("squad_b_lineup_display"),
            ui.output_ui("squad_b_lineup_edit_body"),
            ui.hr(),
            # Squad C's lineup setup/slots/display -- rendered like Squad
            # A/B above, but each of these three outputs returns None on
            # its own whenever the active game isn't flagged
            # uses_three_squad_intrasquad, so this is always safe to
            # include even for every ordinary (non-three-squad) game.
            ui.output_ui("squad_c_lineup_setup_picker"),
            ui.output_ui("squad_c_lineup_slots_body"),
            ui.output_ui("squad_c_lineup_display"),
            ui.output_ui("squad_c_lineup_edit_body"),
            ui.hr(),
            ui.output_ui("opponent_lineup_setup_picker"),
            ui.output_ui("opponent_lineup_display"),
        )

    def _register_squad_lineup(squad, prefix):
        # squad: 'A' / 'B' / 'C'. 'C' is only ever registered for games
        # with uses_three_squad_intrasquad=True (see the three
        # _register_squad_lineup(...) calls below) -- every _picker/
        # _slots/_display function below still independently re-checks
        # game.uses_three_squad_intrasquad before showing anything for
        # squad "C", the same way they already re-check game.is_intrasquad
        # for squad "B", so this stays safe even if that ever changes.
        squad_label = {"A": "Team 1 Lineup", "B": "Team 2 Lineup", "C": "Team 3 Lineup"}[squad]
        _edit_open = reactive.Value(False)  # toggles the "Edit lineup" form below _display -- Ryker's ask (Sep 2026): edit a saved lineup directly in Lineup & Setup

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
                if game is None or (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return None
                existing = db.query(GameLineupSlot).filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad).count()
                if existing:
                    return None
                label = squad_label if squad in ("B", "C") else ("Team 1 Lineup" if game.is_intrasquad else "Lineup")
                return ui.div(
                    ui.h5(f"Set {label}", class_="gbo-section-title"),
                    ui.input_checkbox(f"{prefix}_include_pitchers", "Include pitchers in the batting order (two-way players)"),
                    ui.input_numeric(f"{prefix}_num_spots", "Number of batting order spots", value=9, min=9, max=20, step=1),
                    ui.p(
                        "Set the count above, then fill in each slot below. Once a player is picked in one slot, "
                        "or a position is assigned in one slot, neither shows up as an option in any other slot -- "
                        "the dropdowns below live-filter as you go, and save still double-checks for duplicates "
                        "just in case.",
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
                if game is None or (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return None
                existing = db.query(GameLineupSlot).filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad).count()
                if existing:
                    return None
                num_spots = int(input[f"{prefix}_num_spots"]())
                include_pitchers = input[f"{prefix}_include_pitchers"]()
                players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                # Lineup slots need the real, specific fielding position (so
                # e.g. a 2B and a SS can both be in the lineup at once without
                # tripping the "no duplicate position" exclusion below) --
                # exclude the grouped INF/OF entries added for the Players
                # page's Primary/Secondary Position picker, which are for a
                # player's profile only and were never meant to be a
                # selectable defensive assignment for an actual game.
                positions = db.query(Position).filter(Position.position_name.notin_(["INF", "OF"])).order_by(Position.display_order).all()
                # "Include pitchers" only surfaces pitchers who actually have
                # a secondary position on file (Player.secondary_position_id)
                # -- a real two-way player, not every pitcher on the roster.
                # Ryker's ask (Sep 2026): a pitcher with no secondary
                # position isn't someone who'd ever hit/field for us, so
                # they shouldn't clutter this dropdown even with the box
                # checked.
                # Once a player's picked for a DIFFERENT squad in this game
                # (saved lineup slot or saved starting pitcher), he drops
                # out of every OTHER squad's choices entirely -- a guy can
                # only be on one team. See _players_taken_by_other_squads.
                taken_elsewhere = _players_taken_by_other_squads(game, squad)
                batter_candidates = [p for p in players if p.player_id not in taken_elsewhere and (not p.is_pitcher or (include_pitchers and p.secondary_position_id))]
                pitcher_candidates = [p for p in players if p.is_pitcher and p.player_id not in taken_elsewhere]

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
                # Three-squad intrasquad games skip the "starting pitcher"
                # pick entirely, for every squad (A included) -- per
                # Ryker's explicit ask (Sep 2026): in this mode there's no
                # upfront designation at all, just a live free-pick pitcher
                # each plate appearance (see
                # who_is_up_three_squad_batter_and_pitcher /
                # get_current_three_squad_pitcher_id), so a "starting
                # pitcher" field here would just be unused clutter. Two-
                # squad games (including ordinary intrasquad) are
                # unaffected -- Squad A still gets its formal starting
                # pitcher + pitching-change history, Squad B still gets
                # its own saved default.
                if not game.uses_three_squad_intrasquad:
                    pitcher_choices = {"": "-- Select --"}
                    pitcher_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitcher_candidates})
                    pitcher_label = {"A": "Starting pitcher", "B": "Starting pitcher (Team 2)", "C": "Starting pitcher (Team 3)"}[squad]
                    children.append(ui.input_select(f"{prefix}_starting_pitcher", pitcher_label, choices=pitcher_choices))
                    if squad in ("B", "C"):
                        children.append(ui.p(
                            "Saved as a default for the live \"who's pitching\" picker during other teams' at-bats -- "
                            f"{TEAM_LABEL[squad]} doesn't get formal pitching-change history the way Team 1 does, so this is a "
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
                if game is None or (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return None
                slots = (
                    db.query(GameLineupSlot)
                    .options(
                        joinedload(GameLineupSlot.player),
                        joinedload(GameLineupSlot.starting_position),
                        joinedload(GameLineupSlot.substitutions),
                    )
                    .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad)
                    .order_by(GameLineupSlot.batting_order).all()
                )
                if not slots:
                    return None
                label = squad_label if squad in ("B", "C") else ("Team 1 Lineup" if game.is_intrasquad else "Lineup")
                # Milestone 4 -- shows each slot's CURRENT occupant/position
                # (post-substitution), not the original starter; see
                # get_current_slot_occupant_id/get_current_slot_position_id.
                occupant_ids = {s.lineup_slot_id: get_current_slot_occupant_id(s) for s in slots}
                position_ids = {s.lineup_slot_id: get_current_slot_position_id(s) for s in slots}
                players_by_id = {
                    p.player_id: p for p in db.query(Player).filter(
                        Player.player_id.in_([pid for pid in occupant_ids.values() if pid])
                    ).all()
                }
                positions_by_id = {
                    p.position_id: p for p in db.query(Position).filter(
                        Position.position_id.in_([pid for pid in position_ids.values() if pid])
                    ).all()
                }
                rows = []
                for s in slots:
                    occupant = players_by_id.get(occupant_ids[s.lineup_slot_id])
                    position = positions_by_id.get(position_ids[s.lineup_slot_id])
                    player_label = f"{occupant.first_name} {occupant.last_name}" if occupant else "—"
                    if occupant_ids[s.lineup_slot_id] != s.player_id:
                        player_label += " (sub)"
                    rows.append({
                        "#": s.batting_order,
                        "Player": player_label,
                        "Position": position.position_name if position else "—",
                    })
                children = [ui.h5(label, class_="gbo-section-title"), ui_helpers.render_dict_table(rows)]
                # No starting-pitcher concept at all in three-squad mode
                # (see the setup form's own comment) -- always None here,
                # skip the line entirely rather than show a stale/blank one.
                starting_pitcher_id = None if game.uses_three_squad_intrasquad else {"A": game.starting_pitcher_id, "B": game.squad_b_starting_pitcher_id, "C": game.squad_c_starting_pitcher_id}[squad]
                pitcher_prefix = "Starting pitcher" if squad == "A" else "Starting pitcher (default -- overridable live)"
                if starting_pitcher_id:
                    p = db.query(Player).filter(Player.player_id == starting_pitcher_id).first()
                    if p:
                        children.append(ui.p(f"{pitcher_prefix}: {p.first_name} {p.last_name}", class_="text-muted small"))
                if _can_edit() and not _edit_open():
                    children.append(ui.input_action_button(f"{prefix}_edit_toggle_btn", "Edit lineup", class_="btn-outline-secondary btn-sm mt-2"))
                return ui.div(*children)
            finally:
                db.close()

        @output(id=f"{prefix}_edit_body")
        @render.ui
        def _edit_body():
            _refresh_tick()
            if not _access_ok() or not _can_edit() or not _edit_open():
                return None
            game_id = _active_game_id()
            if game_id is None:
                return None
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None or (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return None
                slots = (
                    db.query(GameLineupSlot)
                    .options(joinedload(GameLineupSlot.player), joinedload(GameLineupSlot.substitutions))
                    .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad)
                    .order_by(GameLineupSlot.batting_order).all()
                )
                if not slots:
                    _edit_open.set(False)
                    return None
                # A slot counts as "used" (its original player pick is locked)
                # once any pitch has been recorded against it, or it already
                # has substitution history -- changing player_id on either
                # would corrupt already-recorded stat attribution (see
                # GameLineupSlot's docstring: player_id is "this slot's
                # ORIGINAL occupant -- kept immutable once saved"). Position
                # and batting order are always safe to change regardless --
                # GBO doesn't track fielding stats at all, and every FK that
                # cares about a slot points at lineup_slot_id, never at
                # batting_order (see the same docstring).
                slot_ids = [s.lineup_slot_id for s in slots]
                used_slot_ids = {
                    row[0] for row in db.query(GamePitch.batting_slot_id)
                    .filter(GamePitch.game_id == game_id, GamePitch.batting_slot_id.in_(slot_ids))
                    .distinct().all()
                }
                players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                positions = db.query(Position).filter(Position.position_name.notin_(["INF", "OF"])).order_by(Position.display_order).all()
                # Unlike the original setup form, this doesn't filter players
                # by is_pitcher at all -- a two-way player needs to stay
                # pickable here regardless of which squad's slot this is,
                # same as the setup form's own "Include pitchers" checkbox
                # already allows when checked.
                player_choices = {"": "-- Select --"}
                player_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in players})
                position_choices = {"": "-- Position --"}
                position_choices.update({str(pos.position_id): pos.position_name for pos in positions})

                rows = [ui.layout_columns(
                    ui.p("Order", class_="mb-0 small text-muted"),
                    ui.p("Player", class_="mb-0 small text-muted"),
                    ui.p("Position", class_="mb-0 small text-muted"),
                    col_widths=[2, 6, 4],
                )]
                for s in slots:
                    locked = s.lineup_slot_id in used_slot_ids or bool(s.substitutions)
                    order_input = ui.input_numeric(f"{prefix}_edit_order_{s.lineup_slot_id}", None, value=s.batting_order, min=1, max=99, step=1)
                    position_input = ui.input_select(f"{prefix}_edit_position_{s.lineup_slot_id}", None, choices=position_choices, selected=str(s.starting_position_id) if s.starting_position_id else "")
                    if locked:
                        player_cell = ui.p(
                            (f"{s.player.first_name} {s.player.last_name}" if s.player else "—") + " 🔒",
                            class_="mb-0",
                            title="Already used in this game -- the player can't be changed without corrupting recorded stats. Position/order can still be changed.",
                        )
                    else:
                        player_cell = ui.input_select(f"{prefix}_edit_player_{s.lineup_slot_id}", None, choices=player_choices, selected=str(s.player_id))
                    rows.append(ui.layout_columns(order_input, player_cell, position_input, col_widths=[2, 6, 4]))

                pitcher_children = []
                if not game.uses_three_squad_intrasquad:
                    current_pitcher_id = {"A": game.starting_pitcher_id, "B": game.squad_b_starting_pitcher_id, "C": game.squad_c_starting_pitcher_id}[squad]
                    pitcher_candidates = [p for p in players if p.is_pitcher]
                    pitcher_choices = {"": "-- Select --"}
                    pitcher_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitcher_candidates})
                    pitcher_label = {"A": "Starting pitcher", "B": "Starting pitcher (Team 2)", "C": "Starting pitcher (Team 3)"}[squad]
                    pitcher_children.append(ui.input_select(f"{prefix}_edit_starting_pitcher", pitcher_label, choices=pitcher_choices, selected=str(current_pitcher_id) if current_pitcher_id else ""))

                edit_label = squad_label if squad in ("B", "C") else ("Team 1 Lineup" if game.is_intrasquad else "Lineup")
                return ui.div(
                    ui.h5(f"Edit {edit_label}", class_="gbo-section-title"),
                    ui.p(
                        "Players already used in this game (🔒) are locked in so past pitches stay attributed correctly -- "
                        "batting order and position can still be changed for every slot. To swap in a different player for "
                        "an unused slot, just pick someone new below.",
                        class_="text-muted small",
                    ),
                    ui.div(*rows),
                    *pitcher_children,
                    ui.input_action_button(f"{prefix}_edit_save_btn", "Save changes", class_="btn-primary mt-2"),
                    ui.input_action_button(f"{prefix}_edit_cancel_btn", "Cancel", class_="btn-outline-secondary mt-2 ms-2"),
                )
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[f"{prefix}_edit_toggle_btn"])
        def _open_edit():
            _edit_open.set(True)

        @reactive.effect
        @reactive.event(input[f"{prefix}_edit_cancel_btn"])
        def _cancel_edit():
            _edit_open.set(False)

        @reactive.effect
        @reactive.event(input[f"{prefix}_edit_save_btn"])
        def _save_edit():
            game_id = _active_game_id()
            if game_id is None:
                return
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None:
                    return
                if (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return
                slots = (
                    db.query(GameLineupSlot)
                    .options(joinedload(GameLineupSlot.substitutions))
                    .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad)
                    .all()
                )
                if not slots:
                    return
                slot_ids = [s.lineup_slot_id for s in slots]
                used_slot_ids = {
                    row[0] for row in db.query(GamePitch.batting_slot_id)
                    .filter(GamePitch.game_id == game_id, GamePitch.batting_slot_id.in_(slot_ids))
                    .distinct().all()
                }

                new_player_ids = {}
                new_position_ids = {}
                new_orders = {}
                for s in slots:
                    order_key = f"{prefix}_edit_order_{s.lineup_slot_id}"
                    position_key = f"{prefix}_edit_position_{s.lineup_slot_id}"
                    player_key = f"{prefix}_edit_player_{s.lineup_slot_id}"
                    if order_key not in input:
                        continue  # stale slot list (lineup changed since the form rendered) -- skip rather than guess
                    order_raw = input[order_key]()
                    new_orders[s.lineup_slot_id] = int(order_raw) if order_raw else s.batting_order
                    position_raw = input[position_key]() if position_key in input else None
                    new_position_ids[s.lineup_slot_id] = int(position_raw) if position_raw else None
                    locked = s.lineup_slot_id in used_slot_ids or bool(s.substitutions)
                    if not locked and player_key in input:
                        player_raw = input[player_key]()
                        new_player_ids[s.lineup_slot_id] = int(player_raw) if player_raw else None

                # Duplicate checks -- same protection _save (the original
                # setup form) already has, applied across the post-edit
                # state of every slot together.
                final_player_ids = [new_player_ids.get(s.lineup_slot_id, s.player_id) for s in slots]
                final_player_ids = [pid for pid in final_player_ids if pid]
                if len(final_player_ids) != len(set(final_player_ids)):
                    ui.notification_show("The same player would end up in more than one slot -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return
                final_position_ids = [new_position_ids.get(s.lineup_slot_id, s.starting_position_id) for s in slots]
                final_position_ids = [pid for pid in final_position_ids if pid]
                if len(final_position_ids) != len(set(final_position_ids)):
                    ui.notification_show("The same position would be assigned to more than one slot -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return
                final_orders = [new_orders.get(s.lineup_slot_id, s.batting_order) for s in slots]
                if len(final_orders) != len(set(final_orders)):
                    ui.notification_show("Two slots would end up with the same batting order number -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return

                skipped_locked_players = 0
                for s in slots:
                    if s.lineup_slot_id in new_player_ids:
                        if s.lineup_slot_id in used_slot_ids or bool(s.substitutions):
                            skipped_locked_players += 1  # defensive -- shouldn't happen, the form doesn't offer a player select for locked slots
                        else:
                            new_pid = new_player_ids[s.lineup_slot_id]
                            if new_pid:
                                s.player_id = new_pid
                    if s.lineup_slot_id in new_position_ids:
                        s.starting_position_id = new_position_ids[s.lineup_slot_id]
                    if s.lineup_slot_id in new_orders:
                        s.batting_order = new_orders[s.lineup_slot_id]

                if not game.uses_three_squad_intrasquad and f"{prefix}_edit_starting_pitcher" in input:
                    pitcher_raw = input[f"{prefix}_edit_starting_pitcher"]()
                    new_pitcher_id = int(pitcher_raw) if pitcher_raw else None
                    if squad == "A":
                        game.starting_pitcher_id = new_pitcher_id
                    elif squad == "B":
                        game.squad_b_starting_pitcher_id = new_pitcher_id
                    else:
                        game.squad_c_starting_pitcher_id = new_pitcher_id

                db.commit()
                msg = "Lineup updated."
                if skipped_locked_players:
                    msg += " (A locked player pick was skipped -- that slot's already been used in this game.)"
                ui.notification_show(msg, type="message", duration=8)
                _edit_open.set(False)
                _bump_refresh()
            finally:
                db.close()

        # ---------------------------------------------------------------
        # _sync_lineup_exclusions used to be a single plain @reactive.effect
        # that read every slot on every keystroke and immediately pushed
        # fresh choices to all of them. That caused a real, reproducible
        # bug Ryker hit (2026-08-26): already-filled slots would randomly
        # revert to blank while filling in later ones. Root-caused via a
        # sandboxed reproduction of this exact pattern (see chat) -- it's
        # NOT a duplicate-player edge case (that's the separate carve-out
        # below), it's this: the effect's own DB query takes real wall-
        # clock time, and if the user edits ANOTHER slot while a previous
        # invocation is still mid-query, the two invocations' ui.update_
        # select() calls interleave and race. Confirmed in the sandbox
        # that touching 2+ selects from one effect, back to back, with
        # ANY latency in between, can drive the client and server into a
        # self-sustaining oscillation (each invocation's stale push gets
        # echoed back as a fresh "change", re-triggering the effect again
        # with a NOW-stale snapshot, indefinitely) -- not just a one-time
        # glitch. A per-slot "does the live value still match what I
        # think it is" recheck does NOT fix this, because Shiny only
        # applies queued client messages at flush boundaries, so a still-
        # running invocation can't see a newer edit no matter how it
        # rechecks mid-run.
        #
        # The fix that actually held up under the sandboxed adversarial
        # test (rapid edits + an artificial slow DB call, both human-
        # paced and rapid-fire): debounce this effect so its real body
        # only ever runs once edits have been quiet for DEBOUNCE_SECONDS.
        # That guarantees no two invocations ever overlap, so there's
        # nothing left to race -- by construction, not by getting lucky
        # on timing. _lineup_last_change_time/_lineup_track_change below
        # implement the debounce (shiny.reactive has no built-in
        # debounce/throttle as of the version this project pins);
        # _lineup_last_synced skips redoing the DB query + push when nothing
        # actually changed since the last successful sync, so this doesn't
        # needlessly re-hit Supabase forever once things settle.
        # ---------------------------------------------------------------
        _lineup_last_change_time = reactive.Value(0.0)
        _lineup_last_synced = {"v": None}
        _LINEUP_DEBOUNCE_SECONDS = 0.6

        @reactive.calc
        def _lineup_raw_picks():
            req(f"{prefix}_num_spots" in input)
            num_spots = int(input[f"{prefix}_num_spots"]())
            include_pitchers = input[f"{prefix}_include_pitchers"]() if f"{prefix}_include_pitchers" in input else False
            current_player_picks = {}
            current_position_picks = {}
            for i in range(1, num_spots + 1):
                player_key = f"{prefix}_slot_player_{i}"
                if player_key in input:
                    raw = input[player_key]()
                    if raw:
                        current_player_picks[i] = int(raw)
                position_key = f"{prefix}_slot_position_{i}"
                if position_key in input:
                    raw = input[position_key]()
                    if raw:
                        current_position_picks[i] = int(raw)
            return (num_spots, include_pitchers, current_player_picks, current_position_picks)

        @reactive.effect
        def _lineup_track_change():
            _lineup_raw_picks()  # depend on every slot -- this is the "did anything change" tripwire
            _lineup_last_change_time.set(time.monotonic())

        @reactive.effect
        def _sync_lineup_exclusions():
            """See the block comment above _lineup_raw_picks for why this
            is debounced. Live cross-slot exclusion: once a player -- or
            a defensive position -- is picked in one slot, every OTHER
            slot's dropdown stops offering it. This restores the
            original Streamlit page's live-filtering behavior (each pick
            immediately removed that player from every other slot) that
            the initial port had simplified away in favor of a save-time
            duplicate check -- both protections are kept: this prevents
            the duplicate from being pickable in the first place, and
            _save below still double-checks in case a slot's stale
            choice list briefly allowed one through mid-interaction.

            Position exclusion is the same idea, added per Ryker's
            explicit ask (2026-08-23): once one slot is set to Catcher,
            no other slot can also be set to Catcher, matching real
            baseball -- exactly one player occupies each position at a
            time. Applies to every row in the Positions table (RHP,
            LHP, C, 1B, 2B, 3B, SS, LF, CF, RF, DH, UTL), not just the
            obvious fielding spots -- no exception was asked for and
            none seemed clearly warranted; easy to carve one out later
            if a position turns out to need to repeat."""
            game_id = _active_game_id()
            if game_id is None:
                return
            elapsed = time.monotonic() - _lineup_last_change_time()
            if elapsed < _LINEUP_DEBOUNCE_SECONDS:
                reactive.invalidate_later(_LINEUP_DEBOUNCE_SECONDS - elapsed)
                return  # still mid-edit -- check again once things go quiet
            with reactive.isolate():
                num_spots, include_pitchers, current_player_picks, current_position_picks = _lineup_raw_picks()
            snapshot = (num_spots, include_pitchers, current_player_picks, current_position_picks)
            if snapshot == _lineup_last_synced["v"]:
                return  # already synced this exact state, nothing to do
            if not current_player_picks and not current_position_picks:
                _lineup_last_synced["v"] = snapshot
                return

            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None:
                    return
                players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                # Same "two-way = has a secondary position" rule as the
                # initial batter_candidates filter above -- see that comment.
                # Also drops anyone already saved to a DIFFERENT squad's
                # lineup, same as the initial form -- see
                # _players_taken_by_other_squads.
                taken_elsewhere = _players_taken_by_other_squads(game, squad)
                candidates = [p for p in players if p.player_id not in taken_elsewhere and (not p.is_pitcher or (include_pitchers and p.secondary_position_id))]
                names_by_id = {p.player_id: f"{p.first_name} {p.last_name}" for p in candidates}
                # Lineup slots need the real, specific fielding position (so
                # e.g. a 2B and a SS can both be in the lineup at once without
                # tripping the "no duplicate position" exclusion below) --
                # exclude the grouped INF/OF entries added for the Players
                # page's Primary/Secondary Position picker, which are for a
                # player's profile only and were never meant to be a
                # selectable defensive assignment for an actual game.
                positions = db.query(Position).filter(Position.position_name.notin_(["INF", "OF"])).order_by(Position.display_order).all()
                position_names_by_id = {pos.position_id: pos.position_name for pos in positions}
            finally:
                db.close()

            for i in range(1, num_spots + 1):
                player_key = f"{prefix}_slot_player_{i}"
                if player_key in input:
                    current_val = current_player_picks.get(i)
                    taken_elsewhere = {pid for slot, pid in current_player_picks.items() if slot != i}
                    choices = {"": "-- Select --"}
                    # A slot's own current pick must ALWAYS survive into its
                    # own choices dict, even if that same player_id also
                    # happens to be sitting in another slot right now. That
                    # can genuinely happen for a moment -- e.g. slot 2's
                    # dropdown still listed a player as available because
                    # this effect hadn't caught up yet, and the user picked
                    # them there right after already picking them in slot 1.
                    # Without this `or pid == current_val` carve-out, BOTH
                    # slots would exclude that player from their own
                    # choices (each sees the other's pick as "taken
                    # elsewhere"), so the selected= value below would point
                    # at an option that no longer exists in the list --
                    # Shiny's <select> can't select a missing option and
                    # silently falls back to blank. That's the exact bug
                    # Ryker reported (2026-08-26): already-filled slots
                    # reverting to blank as later slots are edited. The
                    # save-time duplicate check further down still catches
                    # and rejects a real duplicate before it's persisted --
                    # this carve-out only stops the LIVE dropdown from
                    # erasing a valid pick out from under the user while
                    # they're mid-interaction.
                    choices.update({
                        str(pid): name for pid, name in names_by_id.items()
                        if pid not in taken_elsewhere or pid == current_val
                    })
                    ui.update_select(player_key, choices=choices, selected=str(current_val) if current_val else "")

                position_key = f"{prefix}_slot_position_{i}"
                if position_key in input:
                    current_val = current_position_picks.get(i)
                    taken_elsewhere = {pid for slot, pid in current_position_picks.items() if slot != i}
                    choices = {"": "-- Position --"}
                    # Same carve-out as the player select above, for the
                    # same reason -- see the comment there.
                    choices.update({
                        str(pid): name for pid, name in position_names_by_id.items()
                        if pid not in taken_elsewhere or pid == current_val
                    })
                    ui.update_select(position_key, choices=choices, selected=str(current_val) if current_val else "")

            _lineup_last_synced["v"] = snapshot

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
                if (squad == "B" and not game.is_intrasquad) or (squad == "C" and not game.uses_three_squad_intrasquad):
                    return
                picks = []
                chosen_ids = []
                chosen_position_ids = []
                for i in range(1, num_spots + 1):
                    player_raw = input[f"{prefix}_slot_player_{i}"]()
                    position_raw = input[f"{prefix}_slot_position_{i}"]()
                    if player_raw:
                        picks.append((i, int(player_raw), int(position_raw) if position_raw else None))
                        chosen_ids.append(int(player_raw))
                        if position_raw:
                            chosen_position_ids.append(int(position_raw))
                if len(chosen_ids) != len(set(chosen_ids)):
                    ui.notification_show("The same player is picked in more than one slot -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return
                if len(chosen_position_ids) != len(set(chosen_position_ids)):
                    ui.notification_show("The same position is assigned to more than one slot -- fix the duplicate(s) before saving.", type="error", duration=10)
                    return
                pitcher_raw = input[f"{prefix}_starting_pitcher"]() if f"{prefix}_starting_pitcher" in input else ""
                pitcher_id = int(pitcher_raw) if pitcher_raw else None
                # Final guard against a cross-squad duplicate -- the live
                # dropdowns already filter these out, but this is the
                # authoritative check at the moment of saving (e.g. another
                # squad's lineup could've been saved in a different tab
                # since this form was opened). See
                # _players_taken_by_other_squads.
                taken_elsewhere = _players_taken_by_other_squads(game, squad)
                collision_ids = (set(chosen_ids) | ({pitcher_id} if pitcher_id else set())) & taken_elsewhere
                if collision_ids:
                    collision_names = [f"{p.first_name} {p.last_name}" for p in db.query(Player).filter(Player.player_id.in_(collision_ids)).all()]
                    ui.notification_show(
                        f"{', '.join(collision_names) or 'A picked player'} is already on another team in this game -- fix before saving.",
                        type="error", duration=10,
                    )
                    return
                for i, player_id, position_id in picks:
                    db.add(GameLineupSlot(game_id=game_id, squad=squad, batting_order=i, player_id=player_id, starting_position_id=position_id))
                if squad == "A":
                    game.starting_pitcher_id = pitcher_id
                elif squad == "B":
                    game.squad_b_starting_pitcher_id = pitcher_id
                else:
                    game.squad_c_starting_pitcher_id = pitcher_id
                db.commit()
                label = "lineup" if squad == "A" else f"{TEAM_LABEL[squad]} lineup"
                ui.notification_show(f"Saved {label} ({len(picks)} batters).", type="message", duration=8)
                _bump_refresh()
            finally:
                db.close()

    _register_squad_lineup("A", "squad_a_lineup")
    _register_squad_lineup("B", "squad_b_lineup")
    _register_squad_lineup("C", "squad_c_lineup")

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
                ui.output_ui("runner_events_panel"),
                ui.output_ui("forced_half_inning_end_panel"),
                ui.hr(),
                ui.h5("Who's Up", class_="gbo-section-title"),
                ui.output_ui("who_is_up_identity_picker"),
                ui.output_ui("who_is_up_three_squad_batter_and_pitcher"),
                ui.output_ui("who_is_up_hand_and_order"),
                ui.output_ui("opponent_scouting_card"),
                ui.output_ui("squad_a_lineup_moves"),
                ui.output_ui("squad_b_lineup_moves"),
                ui.hr(),
                ui.output_ui("live_pitch_sequence_display"),
                ui.hr(),
                ui.output_ui("pitch_type_and_outcome_picker"),
                click_widgets.click_target(output_widget("intended_location_widget"), "intended_x_input", "intended_z_input"),
                ui.output_ui("intended_location_caption"),
                ui.output_ui("pitch_outcome_dependent_fields"),
                click_widgets.click_target(output_widget("batted_ball_location_widget"), "batted_ball_x_input", "batted_ball_y_input", round_ndigits=1),
                ui.output_ui("batted_ball_location_caption"),
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None

            if game.uses_three_squad_intrasquad:
                half_label = f"{TEAM_LABEL[suggest_current_batting_squad(pitches, state)]} batting"
                score_value = f"{game.our_score}-{game.opponent_score}-{game.squad_c_score} (A-B-C)"
            else:
                half_label = "Batting" if state["is_our_batting"] else "Pitching"
                score_value = f"{game.our_score}-{game.opponent_score}"
            children = [
                ui.h5("Live Game Dashboard", class_="gbo-section-title"),
                ui_helpers.render_kpi_cards([
                    {"label": "Score", "value": score_value},
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

            hitter_id = _resolve_current_hitter_id_for_stats(game, state, squad_a_slots, squad_b_slots, squad_c_slots)
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None
            half_label = f"{TEAM_LABEL[suggest_current_batting_squad(pitches, state)]} batting" if game.uses_three_squad_intrasquad else ("We're batting" if state["is_our_batting"] else "We're pitching")
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

    # -------------------------------------------------------------------
    # Runner events (steal / caught stealing / pickoff / wild pitch /
    # passed ball / balk) -- see GameRunnerEvent's docstring in
    # models.py. Two-stage render chain (runner_events_panel defines
    # runner_event_type_select/runner_event_from_base_select ->
    # runner_event_fields reads them to build the to-base picker and
    # optional runner picker) -- same "never read an input from the
    # block that defines it" rule this whole file already follows for
    # pitch_type_and_outcome_picker -> pitch_outcome_dependent_fields,
    # etc. runner_event_fields is nested inside runner_events_panel's
    # own output via ui.output_ui(), the same nesting technique this
    # module's docstring documents (bullpen_tracking.py precedent).
    # -------------------------------------------------------------------

    @render.ui
    def runner_events_panel():
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None

            anchor = pitches[-1].pitch_sequence if pitches else 0
            # joinedload our_player/opponent_player -- these used to be
            # looked up with one extra db.query(Player)/db.query(
            # OpponentPlayer) PER pending event (re-run on every reactive
            # tick this panel re-renders, i.e. every pitch); a runner's
            # name is a fixed 1:1 relationship already declared on the
            # model, so it's cheaper to fetch in the same query.
            pending = (
                db.query(GameRunnerEvent)
                .options(joinedload(GameRunnerEvent.our_player), joinedload(GameRunnerEvent.opponent_player))
                .filter(GameRunnerEvent.game_id == game_id, GameRunnerEvent.pitch_sequence_after == anchor)
                .order_by(GameRunnerEvent.created_at)
                .all()
            )

            base_label = {1: "1st", 2: "2nd", 3: "3rd"}
            children = [ui.h5("Runner events since last pitch", class_="gbo-section-title")]
            if pending:
                for ev in pending:
                    who = None
                    if ev.our_player_id:
                        p = ev.our_player
                        who = f"{p.first_name} {p.last_name} — " if p else None
                    elif ev.opponent_player_id:
                        op = ev.opponent_player
                        who = f"{op.player_name} — " if op else None
                    outcome = "out" if ev.is_out else {2: "2nd", 3: "3rd", 4: "home"}.get(ev.to_base, "?")
                    children.append(ui.p(f"{ev.event_type}: {who or ''}{base_label.get(ev.from_base, '?')} → {outcome}", class_="text-muted small"))
            else:
                children.append(ui.p(
                    "None yet -- log a steal, caught stealing, pickoff, wild pitch, passed ball, or balk here before recording the next pitch.",
                    class_="text-muted small",
                ))

            # state["bases"] already reflects any pending events (folded
            # in by compute_current_state), so this list shrinks/grows
            # live as events are recorded/undone -- a double steal's
            # SECOND event correctly offers the runner's new base, not
            # the pre-event one.
            occupied_bases = [i + 1 for i, c in enumerate(state["bases"]) if c == "1"]
            if not occupied_bases:
                children.append(ui.p("No runners on base right now.", class_="text-muted small"))
            elif not _runner_event_form_open():
                # Collapsed by default -- the full Event/Runner-on/Advances-to
                # form only takes up space on the page once someone actually
                # asks for it. Reopened by _open_runner_event_form below, and
                # closed again by _record_runner_event/_undo_last_runner_event/
                # _close_runner_event_form so it doesn't linger after use.
                # (Ryker, 2026-08-26: "make it a dropdown to where they can
                # click a runner event and then select it" instead of the
                # form always being visible.)
                children.append(ui.input_action_button("open_runner_event_form_btn", "+ Log a runner event", class_="btn-outline-light btn-sm mt-1"))
            else:
                from_choices = {str(b): base_label[b] for b in occupied_bases}
                children.append(ui.layout_columns(
                    ui.input_select("runner_event_type_select", "Event", choices=RUNNER_EVENT_TYPES),
                    ui.input_select("runner_event_from_base_select", "Runner on", choices=from_choices),
                    col_widths=[7, 5],
                ))
                children.append(ui.output_ui("runner_event_fields"))
                children.append(ui.input_action_link("close_runner_event_form_btn", "Cancel", class_="text-muted small d-block mt-1"))

            if pending:
                children.append(ui.input_action_button("undo_last_runner_event_btn", "Undo last runner event", class_="btn-outline-danger btn-sm mt-1"))

            return ui.div(*children)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.open_runner_event_form_btn)
    def _open_runner_event_form():
        _runner_event_form_open.set(True)

    @reactive.effect
    @reactive.event(input.close_runner_event_form_btn)
    def _close_runner_event_form():
        _runner_event_form_open.set(False)

    @render.ui
    def runner_event_fields():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        req("runner_event_from_base_select" in input)
        req("runner_event_type_select" in input)
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return None
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None

            event_type = input.runner_event_type_select()
            from_base_val = int(input.runner_event_from_base_select())
            is_out_type = event_type in RUNNER_EVENT_OUT_TYPES
            base_label = {1: "1st", 2: "2nd", 3: "3rd"}

            fields = []
            if is_out_type:
                fields.append(ui.p(f"Recorded as an out at {base_label.get(from_base_val, '?')}.", class_="text-muted small"))
            else:
                to_choices = {str(b): ("Home" if b == 4 else base_label[b]) for b in (2, 3, 4) if b > from_base_val}
                fields.append(ui.input_select("runner_event_to_base_select", "Advances to", choices=to_choices))

            # Optional runner identity -- same "always overridable, don't
            # force a pick you don't have" pattern as who_is_up_identity_picker.
            if game.uses_three_squad_intrasquad:
                slots = {"A": squad_a_slots, "B": squad_b_slots, "C": squad_c_slots}.get(suggest_current_batting_squad(pitches, state))
            else:
                slots = squad_a_slots if state["is_our_batting"] else (squad_b_slots if game.is_intrasquad else None)
            if slots:
                ids = [get_current_slot_occupant_id(s) for s in slots]
                players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(ids)).all()}
                choices = {"": "-- Unspecified --"}
                choices.update({str(pid): f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in ids if pid in players_by_id})
                fields.append(ui.input_select("runner_event_our_player_select", "Runner (optional)", choices=choices))
            elif not state["is_our_batting"] and not game.is_intrasquad:
                opp_roster = game.opponent_team.roster if game.opponent_team else []
                if opp_roster:
                    choices = {"": "-- Unspecified --"}
                    choices.update({str(p.opponent_player_id): p.player_name for p in opp_roster})
                    fields.append(ui.input_select("runner_event_opponent_player_select", "Runner (optional)", choices=choices))

            fields.append(ui.input_action_button("record_runner_event_btn", "Log runner event", class_="btn-outline-light btn-sm mt-1"))
            return ui.div(*fields)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.record_runner_event_btn)
    def _record_runner_event():
        game_id = _active_game_id()
        if game_id is None:
            return
        req("runner_event_from_base_select" in input)
        req("runner_event_type_select" in input)
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx

            event_type = input.runner_event_type_select()
            from_base = int(input.runner_event_from_base_select())
            is_out = event_type in RUNNER_EVENT_OUT_TYPES
            to_base = None
            if not is_out:
                if "runner_event_to_base_select" not in input or not input.runner_event_to_base_select():
                    ui.notification_show("Pick where the runner advances to.", type="error", duration=8)
                    return
                to_base = int(input.runner_event_to_base_select())

            our_player_id = None
            opponent_player_id = None
            if "runner_event_our_player_select" in input and input.runner_event_our_player_select():
                our_player_id = int(input.runner_event_our_player_select())
            elif "runner_event_opponent_player_select" in input and input.runner_event_opponent_player_select():
                opponent_player_id = int(input.runner_event_opponent_player_select())

            anchor = pitches[-1].pitch_sequence if pitches else 0
            batting_squad = suggest_current_batting_squad(pitches, state) if game.uses_three_squad_intrasquad else None
            db.add(GameRunnerEvent(
                game_id=game_id, pitch_sequence_after=anchor,
                is_our_team_batting=state["is_our_batting"],
                batting_squad=batting_squad,
                event_type=event_type, from_base=from_base, to_base=to_base, is_out=is_out,
                our_player_id=our_player_id, opponent_player_id=opponent_player_id,
                created_by_user_id=app_state.user_id(),
            ))
            if to_base == 4:
                if batting_squad == "A":
                    game.our_score += 1
                elif batting_squad == "B":
                    game.opponent_score += 1
                elif batting_squad == "C":
                    game.squad_c_score += 1
                elif state["is_our_batting"]:
                    game.our_score += 1
                else:
                    game.opponent_score += 1
            db.commit()
            ui.notification_show(f"{event_type} recorded.", type="message", duration=6)
            _runner_event_form_open.set(False)  # collapse back down -- see runner_events_panel
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.undo_last_runner_event_btn)
    def _undo_last_runner_event():
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            last_event = (
                db.query(GameRunnerEvent)
                .filter(GameRunnerEvent.game_id == game_id)
                .order_by(GameRunnerEvent.created_at.desc())
                .first()
            )
            if last_event is None:
                return
            if last_event.to_base == 4:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is not None:
                    if last_event.batting_squad == "A":
                        game.our_score = max(0, game.our_score - 1)
                    elif last_event.batting_squad == "B":
                        game.opponent_score = max(0, game.opponent_score - 1)
                    elif last_event.batting_squad == "C":
                        game.squad_c_score = max(0, game.squad_c_score - 1)
                    elif last_event.is_our_team_batting:
                        game.our_score = max(0, game.our_score - 1)
                    else:
                        game.opponent_score = max(0, game.opponent_score - 1)
            db.delete(last_event)
            db.commit()
            ui.notification_show("Last runner event undone.", type="message", duration=6)
            _runner_event_form_open.set(False)  # collapse back down -- see runner_events_panel
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    # Intrasquad-only manual override: a pitcher's outing (and the
    # current half-inning) sometimes has to end on a pitch count before
    # 3 real outs are recorded (Ryker, Sept 2026: "some innings may be
    # ended due to pitch counts... i need to be able to click something
    # that ends that inning where it was and moves on to the next" --
    # the Kurt Kassner example: his outing ended on a pitch count with
    # runners on, and the team just moved to the next pitcher/lineup).
    # See models.GameForcedHalfInningEnd, and compute_current_state()/
    # replay_game() above for how this is folded into state either way.
    @render.ui
    def forced_half_inning_end_panel():
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress" or not game.is_intrasquad:
                return None

            runs_pending = state["bases"].count("1")
            last_pitch = pitches[-1] if pitches else None
            pitcher = None
            if last_pitch is not None:
                pitcher_id = (
                    last_pitch.our_player_id if not last_pitch.is_our_team_batting
                    else last_pitch.opponent_our_player_id
                )
                if pitcher_id is not None:
                    pitcher = db.query(Player).filter(Player.player_id == pitcher_id).first()

            children = [ui.h5("Pitch count / early end", class_="gbo-section-title")]

            if not _forced_end_form_open():
                children.append(ui.input_action_button(
                    "open_forced_end_form_btn", "End half-inning now (pitch count)",
                    class_="btn-outline-warning btn-sm mt-1",
                ))
            else:
                who = f"{pitcher.first_name} {pitcher.last_name}" if pitcher else None
                if runs_pending:
                    charge = f"charged to {who}'s ERA" if who else "not charged to anyone's ERA (no pitcher on file for this half)"
                    run_note = f"{runs_pending} runner(s) on base will score and {charge}."
                else:
                    run_note = "No runners on base -- the half-inning just ends here, no runs charged."
                children.append(ui.p(run_note, class_="text-muted small"))
                if game.uses_three_squad_intrasquad:
                    children.append(ui.input_action_button("confirm_forced_end_btn", "Confirm -- new team is up", class_="btn-warning btn-sm mt-1"))
                    children.append(ui.p(
                        "Use \"new team is up\" for a genuine half-inning end. Use \"same team "
                        f"continues\" instead when {who or 'this pitcher'} is being pulled on a pitch "
                        "count and the SAME squad keeps pitching to a fresh lineup -- that keeps "
                        "who's-pitching/who's-batting straight for every pitch after this one.",
                        class_="text-muted small mt-1",
                    ))
                    children.append(ui.input_action_button("confirm_forced_end_same_side_btn", "Confirm -- same team continues (pitch count)", class_="btn-warning btn-sm mt-1"))
                else:
                    children.append(ui.input_action_button("confirm_forced_end_btn", "Confirm -- end half-inning", class_="btn-warning btn-sm mt-1"))
                children.append(ui.input_action_link("cancel_forced_end_btn", "Cancel", class_="text-muted small d-block mt-1"))

            return ui.div(*children)
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.open_forced_end_form_btn)
    def _open_forced_end_form():
        _forced_end_form_open.set(True)

    @reactive.effect
    @reactive.event(input.cancel_forced_end_btn)
    def _cancel_forced_end_form():
        _forced_end_form_open.set(False)

    def _do_confirm_forced_end(same_side_continues):
        game_id = _active_game_id()
        if game_id is None:
            return
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None:
                return
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress" or not game.is_intrasquad:
                return

            runs_scored = state["bases"].count("1")
            last_pitch = pitches[-1] if pitches else None
            credited_player_id = None
            if last_pitch is not None:
                credited_player_id = (
                    last_pitch.our_player_id if not last_pitch.is_our_team_batting
                    else last_pitch.opponent_our_player_id
                )
            anchor = last_pitch.pitch_sequence if last_pitch else 0
            batting_squad = suggest_current_batting_squad(pitches, state) if game.uses_three_squad_intrasquad else None

            db.add(GameForcedHalfInningEnd(
                game_id=game_id, pitch_sequence_after=anchor,
                inning=state["inning"], is_our_team_batting=state["is_our_batting"],
                batting_squad=batting_squad, runs_scored=runs_scored,
                credited_player_id=credited_player_id,
                same_side_continues=same_side_continues,
                created_by_user_id=app_state.user_id(),
            ))
            if runs_scored:
                if batting_squad == "A":
                    game.our_score += runs_scored
                elif batting_squad == "B":
                    game.opponent_score += runs_scored
                elif batting_squad == "C":
                    game.squad_c_score += runs_scored
                elif state["is_our_batting"]:
                    game.our_score += runs_scored
                else:
                    game.opponent_score += runs_scored
            db.commit()
            if same_side_continues:
                ui.notification_show("Half-inning ended -- same team continues pitching to a fresh lineup.", type="message", duration=6)
            else:
                ui.notification_show("Half-inning ended -- moving on to the next pitcher/lineup.", type="message", duration=6)
            _forced_end_form_open.set(False)
            _runner_event_form_open.set(False)  # a stale open runner-event form no longer applies to the new half
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    @reactive.effect
    @reactive.event(input.confirm_forced_end_btn)
    def _confirm_forced_end():
        _do_confirm_forced_end(False)

    @reactive.effect
    @reactive.event(input.confirm_forced_end_same_side_btn)
    def _confirm_forced_end_same_side():
        _do_confirm_forced_end(True)

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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None

            if not state["new_pa"]:
                if game.uses_three_squad_intrasquad:
                    cur_id = state.get("current_our_player") if state["is_our_batting"] else state.get("current_opp_our_player")
                    p = db.query(Player).filter(Player.player_id == cur_id).first() if cur_id else None
                    if p:
                        squad = suggest_current_batting_squad(pitches, state)
                        return ui.p(f"At bat: {p.first_name} {p.last_name} ({TEAM_LABEL[squad]})", class_="text-muted small")
                    return None
                if state["is_our_batting"]:
                    cur_id = state.get("current_our_player")
                    p = db.query(Player).filter(Player.player_id == cur_id).first() if cur_id else None
                    if p:
                        return ui.p(f"At bat: {p.first_name} {p.last_name}", class_="text-muted small")
                return None

            # Three-squad intrasquad games get their own, separate "who's
            # up" flow -- a live "team up to bat" picker instead of the
            # automatic two-way is_our_batting split below (which still
            # drives outs/bases/inning under the hood, unchanged, but no
            # longer maps onto "which of our three squads is up"). The
            # batter/pitcher selects themselves are rendered by a SEPARATE
            # output (who_is_up_three_squad_batter_and_pitcher) that reads
            # this select's live value -- this file's own "never read a
            # client input from the same render block that defines it"
            # rule (see module docstring).
            if game.uses_three_squad_intrasquad:
                suggested_squad = suggest_current_batting_squad(pitches, state)
                squad_choices = dict(TEAM_LABEL)
                return ui.div(
                    ui.p("New plate appearance -- which team is up? (auto-suggested from the rotation, override if needed)", class_="text-muted small"),
                    ui.input_select("batting_squad_select", "Team up to bat", choices=squad_choices, selected=suggested_squad),
                )

            children = [ui.p("New plate appearance -- who's up? (auto-suggested from the lineup order, override if needed)", class_="text-muted small")]

            if state["is_our_batting"]:
                if squad_a_slots:
                    lineup_ids = [get_current_slot_occupant_id(s) for s in squad_a_slots]
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
                        children.append(ui.input_select("opp_pitcher_select", "Opposing pitcher (Team 2)", choices=pitcher_choices, selected=pitcher_selected))
            else:
                if game.is_intrasquad:
                    if squad_b_slots:
                        squad_b_ids = [get_current_slot_occupant_id(s) for s in squad_b_slots]
                    else:
                        squad_b_ids = [p.player_id for p in db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()]
                    players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(squad_b_ids)).all()}
                    choices = {str(pid): f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in squad_b_ids if pid in players_by_id}
                    suggested = suggest_next_squad_b_batter(game, squad_b_slots) if squad_b_slots else None
                    selected = str(suggested) if suggested is not None and str(suggested) in choices else None
                    children.append(ui.input_select("opp_our_batter_select", "Opposing batter (Team 2)", choices=choices, selected=selected))
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
    def who_is_up_three_squad_batter_and_pitcher():
        """Three-squad intrasquad games only -- the dependent half of
        who_is_up_identity_picker's split above: reads batting_squad_select
        (defined there) to render the batter dropdown scoped to that
        squad's saved roster (with a suggested next batter, still
        overridable, same as every other squad's picker) plus a free-pick
        pitcher dropdown (from anyone active marked as a pitcher -- no
        formal pitching-change history for any of the three squads in
        this mode, same "always picked live" pattern Squad B already
        uses) and that pitcher's throwing hand, defaulted from his
        profile. This is the one place three-squad games capture both
        halves of a plate appearance's identity."""
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress" or not game.uses_three_squad_intrasquad or not state["new_pa"]:
                return None
            req("batting_squad_select" in input)
            squad = input.batting_squad_select()
            slots_by_squad = {"A": squad_a_slots, "B": squad_b_slots, "C": squad_c_slots}
            slots = slots_by_squad.get(squad, [])
            if slots:
                lineup_ids = [get_current_slot_occupant_id(s) for s in slots]
            else:
                lineup_ids = [p.player_id for p in db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(False)).order_by(Player.last_name, Player.first_name).all()]
            players_by_id = {p.player_id: p for p in db.query(Player).filter(Player.player_id.in_(lineup_ids)).all()}
            choices = {str(pid): f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}" for pid in lineup_ids if pid in players_by_id}
            suggested = suggest_next_squad_batter(game, squad, slots) if slots else None
            selected = str(suggested) if suggested is not None and str(suggested) in choices else None
            children = [ui.input_select("three_squad_batter_select", f"{TEAM_LABEL[squad]} batter", choices=choices, selected=selected)]

            pitcher_candidates = db.query(Player).filter(Player.active.is_(True), Player.is_pitcher.is_(True)).order_by(Player.last_name, Player.first_name).all()
            if not pitcher_candidates:
                children.append(ui.p("No active players are marked as pitchers yet -- flag at least one on the Players page.", class_="text-warning small"))
            else:
                pitcher_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in pitcher_candidates}
                suggested_pitcher_id = get_current_three_squad_pitcher_id(game)
                pitcher_selected = str(suggested_pitcher_id) if suggested_pitcher_id is not None and str(suggested_pitcher_id) in pitcher_choices else None
                children.append(ui.input_select("three_squad_pitcher_select", "Pitcher (free pick -- from either fielding squad)", choices=pitcher_choices, selected=pitcher_selected))
                default_hand = "R"
                suggested_pitcher = players_by_id_all = None
                if suggested_pitcher_id is not None:
                    suggested_pitcher = db.query(Player).filter(Player.player_id == suggested_pitcher_id).first()
                if suggested_pitcher and suggested_pitcher.throws:
                    default_hand = suggested_pitcher.throws
                children.append(ui.input_radio_buttons("three_squad_pitcher_hand_radio", "Pitcher's throwing hand", choices=["R", "L"], selected=default_hand, inline=True))
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None
            if game.uses_three_squad_intrasquad:
                # Fully covered by who_is_up_three_squad_batter_and_pitcher
                # instead (batter + free-pick pitcher + pitcher's hand, all
                # in one place) -- this function's is_our_batting-keyed
                # split doesn't map onto three rotating squads, and no
                # squad has formal pitching-change history in this mode
                # anyway (same as Squad B today), so the "Currently
                # pitching" + pitching-change UI further down doesn't apply.
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
    def opponent_scouting_card():
        """Milestone 3 -- opponent scouting / pitch-calling (see module
        docstring). Shown in Live Tracking whenever we're pitching to a
        known opposing batter (identified via
        _resolve_current_opponent_batter_id): that hitter's line
        against us and a per-pitch-type usage/effectiveness breakdown,
        so the coach can see what's worked against him without leaving
        the tracking screen. This surfaces the DATA -- reusing
        game_stats.py's existing compute_pitching_line/
        compute_pitch_type_breakdown unchanged, no new stats logic --
        rather than an automated "throw this pitch" recommendation,
        which is an explicitly later, out-of-scope phase (see the
        original spec's Phase 5 "Advanced Intelligence", deferred)."""
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None
            opponent_batter_id = _resolve_current_opponent_batter_id(game, state)
            if opponent_batter_id is None:
                return None
            opp_player = db.query(OpponentPlayer).filter(OpponentPlayer.opponent_player_id == opponent_batter_id).first()
            if opp_player is None:
                return None

            history = get_pitches_thrown_to_opponent_batter(db, opponent_batter_id)
            if not history:
                return ui.div(
                    ui.h6(f"Scouting — {opp_player.player_name}", class_="gbo-section-title"),
                    ui.p("No pitch history against this hitter yet -- this card fills in once we've faced him before.", class_="text-muted small"),
                )

            line = compute_pitching_line(history)
            oba = line["OBA (opponent AVG)"]
            children = [
                ui.h6(f"Scouting — {opp_player.player_name}", class_="gbo-section-title"),
                ui_helpers.render_kpi_cards([
                    {"label": "PA vs. us", "value": str(line["Batters Faced"])},
                    {"label": "OBA", "value": f"{oba:.3f}" if oba is not None else "—"},
                    {"label": "K", "value": str(line["K"])},
                    {"label": "BB", "value": str(line["BB"])},
                    {"label": "Whiffs", "value": str(sum(1 for p in history if p.pitch_outcome == "Swing and Miss"))},
                ]),
            ]

            breakdown = compute_pitch_type_breakdown(history)
            per_type_rows = [row for row in breakdown if row["Pitch Type"] != "Total"]
            if per_type_rows:
                table_rows = [
                    {
                        "Pitch Type": row["Pitch Type"],
                        "Thrown": row["Total Pitches"],
                        "Usage %": row["Pitch Usage %"],
                        "Strike %": row["Strike %"],
                        "Whiff %": row["Whiff %"],
                        "CSW %": row["CSW %"],
                        "Chase %": row["Chase %"],
                    }
                    for row in sorted(per_type_rows, key=lambda r: (r["CSW %"] if r["CSW %"] is not None else -1), reverse=True)
                ]
                children.append(ui_helpers.render_dict_table(table_rows))
                children.append(ui.p(
                    "Sorted by CSW% (called strikes + whiffs), highest first -- what's generated the most strikes "
                    "against this hitter so far. Small sample sizes (low \"Thrown\" counts) are noisy; check the "
                    "count before trusting a single pitch type's row.",
                    class_="text-muted small",
                ))
            return ui.div(*children)
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            new_pitcher_id = int(input.new_pitcher_select())
            db.add(PitchingChange(game_id=game_id, player_id=new_pitcher_id, inning=state["inning"], outs_at_entry=state["outs"], pitch_sequence_at_entry=len(pitches)))
            db.commit()
            pitcher = db.query(Player).filter(Player.player_id == new_pitcher_id).first()
            ui.notification_show(f"{pitcher.first_name} {pitcher.last_name} is now pitching.", type="message", duration=8)
            _bump_pa()
            _bump_refresh()
        finally:
            db.close()

    def _register_lineup_moves(squad, prefix):
        """Milestone 4 -- see module docstring. Live, in-game batting
        substitutions and mid-order slot additions, registered per squad
        (called for both squads below, same one-set-of-functions-
        registered-twice pattern _register_squad_lineup already uses).
        Lives entirely in Live Tracking, not duplicated into Lineup &
        Setup, since these are live events tied to the current
        inning/outs -- same reasoning _confirm_pitching_change follows,
        reading _load_tracking_context's own state rather than
        re-deriving it."""

        @output(id=f"{prefix}_moves")
        @render.ui
        def _moves_ui():
            _pa_tick()
            if not _access_ok() or not _can_edit():
                return None
            game_id = _active_game_id()
            if game_id is None:
                return None
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None or game.status != "In Progress" or (squad == "B" and not game.is_intrasquad):
                    return None
                slots = (
                    db.query(GameLineupSlot)
                    .options(joinedload(GameLineupSlot.substitutions))
                    .filter(GameLineupSlot.game_id == game_id, GameLineupSlot.squad == squad)
                    .order_by(GameLineupSlot.batting_order).all()
                )
                if not slots:
                    return None  # no saved lineup for this squad yet -- nothing to substitute into

                occupant_ids = {s.lineup_slot_id: get_current_slot_occupant_id(s) for s in slots}
                players_by_id = {
                    p.player_id: p for p in db.query(Player).filter(
                        Player.player_id.in_([pid for pid in occupant_ids.values() if pid])
                    ).all()
                }
                slot_choices = {}
                for s in slots:
                    occ = players_by_id.get(occupant_ids[s.lineup_slot_id])
                    label = f"#{s.batting_order} — {occ.first_name} {occ.last_name}" if occ else f"#{s.batting_order} — —"
                    slot_choices[str(s.lineup_slot_id)] = label

                occupied_ids = _currently_occupied_player_ids(game, squad)
                eligible = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
                eligible_choices = {"": "-- Select --"}
                eligible_choices.update({str(p.player_id): f"{p.first_name} {p.last_name}" for p in eligible if p.player_id not in occupied_ids})

                # Lineup slots need the real, specific fielding position (so
                # e.g. a 2B and a SS can both be in the lineup at once without
                # tripping the "no duplicate position" exclusion below) --
                # exclude the grouped INF/OF entries added for the Players
                # page's Primary/Secondary Position picker, which are for a
                # player's profile only and were never meant to be a
                # selectable defensive assignment for an actual game.
                positions = db.query(Position).filter(Position.position_name.notin_(["INF", "OF"])).order_by(Position.display_order).all()
                sub_position_choices = {"": "No change"}
                sub_position_choices.update({str(pos.position_id): pos.position_name for pos in positions})
                add_position_choices = {"": "-- Position --"}
                add_position_choices.update({str(pos.position_id): pos.position_name for pos in positions})

                max_order = max((s.batting_order for s in slots), default=0)
                order_choices = {str(i): str(i) for i in range(1, max_order + 2)}

                title_suffix = " (Team 2)" if squad == "B" else ""

                return ui.accordion(
                    ui.accordion_panel(
                        f"Substitute into a slot{title_suffix}",
                        ui.input_select(f"{prefix}_sub_slot_select", "Slot", choices=slot_choices),
                        ui.input_select(f"{prefix}_sub_player_select", "Incoming player", choices=eligible_choices),
                        ui.input_select(f"{prefix}_sub_position_select", "New position (optional)", choices=sub_position_choices),
                        ui.input_action_button(f"{prefix}_confirm_sub_btn", "Confirm substitution", class_="btn-sm btn-primary"),
                    ),
                    ui.accordion_panel(
                        f"Add a batting slot{title_suffix}",
                        ui.input_select(f"{prefix}_add_player_select", "Incoming player", choices=eligible_choices),
                        ui.input_select(f"{prefix}_add_order_select", "Batting order position", choices=order_choices, selected=str(max_order + 1)),
                        ui.input_select(f"{prefix}_add_position_select", "Position (optional)", choices=add_position_choices),
                        ui.input_action_button(f"{prefix}_confirm_add_btn", "Add to lineup", class_="btn-sm btn-primary"),
                    ),
                    open=False, id=None,
                )
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[f"{prefix}_confirm_sub_btn"])
        def _confirm_sub():
            game_id = _active_game_id()
            if game_id is None:
                return
            req(f"{prefix}_sub_slot_select" in input)
            slot_raw = input[f"{prefix}_sub_slot_select"]()
            player_raw = input[f"{prefix}_sub_player_select"]()
            if not slot_raw or not player_raw:
                ui.notification_show("Pick both a slot and an incoming player.", type="error", duration=8)
                return
            db = get_session()
            try:
                ctx = _load_tracking_context(db, game_id)
                if ctx is None:
                    return
                game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
                slot = db.query(GameLineupSlot).filter(GameLineupSlot.lineup_slot_id == int(slot_raw), GameLineupSlot.game_id == game_id).first()
                if slot is None:
                    return
                position_raw = input[f"{prefix}_sub_position_select"]() if f"{prefix}_sub_position_select" in input else ""
                db.add(LineupSubstitution(
                    game_id=game_id, lineup_slot_id=slot.lineup_slot_id, player_id=int(player_raw),
                    inning=state["inning"], outs_at_entry=state["outs"], pitch_sequence_at_entry=len(pitches),
                    new_position_id=int(position_raw) if position_raw else None,
                ))
                db.commit()
                player = db.query(Player).filter(Player.player_id == int(player_raw)).first()
                ui.notification_show(f"{player.first_name} {player.last_name} is now in the #{slot.batting_order} spot.", type="message", duration=8)
                _bump_pa()
                _bump_refresh()
            finally:
                db.close()

        @reactive.effect
        @reactive.event(input[f"{prefix}_confirm_add_btn"])
        def _confirm_add():
            game_id = _active_game_id()
            if game_id is None:
                return
            req(f"{prefix}_add_player_select" in input)
            player_raw = input[f"{prefix}_add_player_select"]()
            order_raw = input[f"{prefix}_add_order_select"]() if f"{prefix}_add_order_select" in input else ""
            if not player_raw or not order_raw:
                ui.notification_show("Pick both an incoming player and a batting-order position.", type="error", duration=8)
                return
            db = get_session()
            try:
                game = db.query(Game).filter(Game.game_id == game_id).first()
                if game is None:
                    return
                position_raw = input[f"{prefix}_add_position_select"]() if f"{prefix}_add_position_select" in input else ""
                _insert_lineup_slot_at(
                    db, game_id, squad, int(order_raw), int(player_raw),
                    int(position_raw) if position_raw else None,
                )
                db.commit()
                player = db.query(Player).filter(Player.player_id == int(player_raw)).first()
                ui.notification_show(f"{player.first_name} {player.last_name} added to the lineup at #{order_raw}.", type="message", duration=8)
                _bump_pa()
                _bump_refresh()
            finally:
                db.close()

    _register_lineup_moves("A", "squad_a_lineup")
    _register_lineup_moves("B", "squad_b_lineup")

    def _resolve_actual_pitcher_id(game, state):
        """Whoever is ACTUALLY pitching this plate appearance, across
        every mode this page supports -- Squad A's own formal pitching
        staff (get_current_pitcher_id), Squad B's free pick, or a
        three-squad game's free pick. Used to scope the pitch-type
        dropdown to that real pitcher's real arsenal (the pitch-code
        decoder, _apply_pitch_code below, no longer needs this -- it
        only ever resolves location now, never pitch type).
        Previously only Squad A's own pitcher got this treatment here;
        an intrasquad opposing pitcher (Squad B, or three-squad free
        pick) saw every pitch type unfiltered -- this folds that in too."""
        if game.uses_three_squad_intrasquad:
            if not state["new_pa"]:
                cur_our, cur_opp = state.get("current_our_player"), state.get("current_opp_our_player")
                return cur_opp if state["is_our_batting"] else cur_our
            if "three_squad_pitcher_select" in input and input.three_squad_pitcher_select():
                return int(input.three_squad_pitcher_select())
            return None
        if not state["is_our_batting"]:
            return get_current_pitcher_id(game)
        if game.is_intrasquad:
            if not state["new_pa"]:
                return state.get("current_opp_our_player")
            if "opp_pitcher_select" in input and input.opp_pitcher_select():
                return int(input.opp_pitcher_select())
            return get_current_squad_b_pitcher_id(game)
        return None

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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None

            pitch_types = db.query(PitchType).order_by(PitchType.pitch_type_id).all()
            current_pitcher_id = _resolve_actual_pitcher_id(game, state)
            arsenal_names = get_arsenal_pitch_type_names(db, current_pitcher_id, pitch_types) if current_pitcher_id else [pt.type_name for pt in pitch_types]
            pitch_type_choices = {name: name for name in arsenal_names}

            children = [
                ui.h5("Pitch Details", class_="gbo-section-title"),
                ui.input_select("pitch_type_select", "Pitch type", choices=pitch_type_choices),
            ]

            # Intended location is only meaningful when the pitcher throwing
            # THIS pitch is someone we coach and can know the intent of --
            # that's true when we're pitching (always), and ALSO true when
            # we're batting in an intrasquad game (the "opposing" pitcher is
            # still one of our own roster players, is_intrasquad's whole
            # point -- see Game/GamePitch docstrings). A real external
            # opponent's pitcher's intent is never known, so it's never
            # captured -- only their pitch type (above) and, via Video
            # Review, their actual location (see that section below) are.
            show_intended = (not state["is_our_batting"]) or game.is_intrasquad
            if show_intended:
                # Ryker's shorthand pitch code (Sep 2026, revised Sep 2026) --
                # type Level-Zone (e.g. "14") and hit Apply instead of
                # clicking the zone graphic. _apply_pitch_code below
                # decodes it into the same intended_x_input/
                # intended_z_input the click widget and manual entry
                # already write into, so nothing downstream (record_pitch,
                # execution scoring, etc.) needs to know this path even
                # exists -- the click graphic still works too, and updates
                # to show where the code landed. Location only -- pitch
                # type is never touched by the code, always picked from
                # the dropdown above (see the module-level note in
                # strike_zone.py's Pitch code shorthand section for why
                # an earlier version that also guessed pitch type from
                # the code was dropped).
                children.append(ui.p(
                    'Pitch code (Level-Zone, e.g. "14") -- or click the zone / type coordinates below.',
                    class_="text-muted small",
                ))
                children.append(ui.layout_columns(
                    ui.input_text("pitch_code_input", None, placeholder="e.g. 14"),
                    ui.input_action_button("apply_pitch_code_btn", "Apply code", class_="btn-outline-light btn-sm"),
                    col_widths=[8, 4],
                ))
                children.append(ui.p(
                    "Level: 1=dirt/below zone, 2=knees/bottom, 3=middle, 4=top & above. "
                    "Zone: 1=chalk/off the plate (in to a righty, off to a lefty), 2=inner, 3=middle, "
                    "4=inner (away to a righty, in to a lefty), 5=chalk/off the plate (away to a righty, in to a lefty). "
                    "Sets location only -- pick the pitch type above yourself.",
                    class_="text-muted small",
                ))
                children.append(ui.p(
                    "Intended location -- click the zone below to place where the pitch was supposed to go, "
                    "or type coordinates directly.",
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

    @reactive.effect
    @reactive.event(input.apply_pitch_code_btn)
    def _apply_pitch_code():
        """Decodes pitch_code_input (Ryker's Level-Zone shorthand, see
        strike_zone.py's own module-level note) and pushes the result
        into intended_x_input/intended_z_input via ui.update_*, the same
        two widgets the click graphic and manual entry already drive --
        so this is purely an alternate, faster way to fill in the exact
        same fields, not a separate data path. Location only -- never
        touches pitch_type_select, which the coach always picks
        themselves (see the module-level note in strike_zone.py for why
        an earlier version that also guessed pitch type from a third
        digit was dropped: that digit resolved against the pitcher's
        arsenal-list position rather than a fixed pitch type, so e.g.
        "2" didn't reliably mean the same pitch for every pitcher)."""
        game_id = _active_game_id()
        if game_id is None:
            return
        raw = (input.pitch_code_input() or "").strip() if "pitch_code_input" in input else ""
        try:
            level, zone = strike_zone.parse_pitch_code(raw)
            x, z = strike_zone.decode_pitch_code(level, zone)
        except ValueError as e:
            ui.notification_show(str(e), type="error", duration=8)
            return
        ui.update_numeric("intended_x_input", value=round(x, 3))
        ui.update_numeric("intended_z_input", value=round(z, 3))
        ui.notification_show(f'Applied "{raw}": location set. Pick the pitch type above.', type="message", duration=5)

    @render_plotly
    def intended_location_widget():
        """Real click-to-place intended pitch location, replacing the
        numeric-entry + static-preview-image workaround (see module
        docstring's Milestone 2 note). Clicking anywhere in the zone
        writes the clicked point into intended_x_input/intended_z_input
        via the click_widgets.click_target() wrapper at this widget's
        output_widget(...) call site (see live_tracking_body) -- those
        two numeric inputs stay the actual source of truth (still
        directly typeable for fine correction), so _do_record_pitch and
        everything else downstream is completely unchanged."""
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None or ctx[0].status != "In Progress":
                return None
            # See pitch_type_and_outcome_picker's show_intended for why this
            # isn't simply "not is_our_batting" -- intrasquad batting also
            # shows intended location, since the opposing pitcher is ours too.
            if not ((not ctx[5]["is_our_batting"]) or ctx[0].is_intrasquad):
                return None
        finally:
            db.close()
        req("intended_x_input" in input)
        x, z = input.intended_x_input(), input.intended_z_input()
        return _build_clickable_widget(strike_zone.build_zone_selector_figure(marker_x=x, marker_z=z))

    @render.ui
    def intended_location_caption():
        if not _access_ok() or not _can_edit():
            return None
        game_id = _active_game_id()
        if game_id is None:
            return None
        db = get_session()
        try:
            ctx = _load_tracking_context(db, game_id)
            if ctx is None or ctx[0].status != "In Progress":
                return None
            if not ((not ctx[5]["is_our_batting"]) or ctx[0].is_intrasquad):
                return None
        finally:
            db.close()
        req("intended_x_input" in input)
        x, z = input.intended_x_input(), input.intended_z_input()
        return ui.p(
            f"Intended: {x:+.2f} ft, {z:.2f} ft high — click the zone above, or type coordinates directly.",
            class_="text-muted small text-center",
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
        # Manual escape hatch: force the Result/AB-outcome section to
        # show up below even when this outcome alone wouldn't naturally
        # end the at-bat by the ball/strike count -- e.g. confirming a
        # walk, or flagging a "Ball" that was actually a hit-by-pitch.
        # Hidden for In Play/HBP since those already always end the PA
        # on their own; showing it there would do nothing.
        if outcome not in ("In Play", "HBP"):
            children.append(ui.input_checkbox("force_end_pa_checkbox", "This pitch ends the at-bat (e.g. walk, hit-by-pitch)"))
        if outcome in ("In Play", "Foul", "Swing and Miss"):
            children.append(ui.input_select("contact_quality_select", "Contact quality (optional)", choices=["-- N/A --"] + CONTACT_QUALITY_OPTIONS))
            children.append(ui.input_checkbox("is_sword_checkbox", "Sword (ugly, off-balance swing)"))
        if outcome == "In Play":
            children.append(ui.input_select("batted_ball_type_select", "Batted ball type (optional)", choices=["-- N/A --", "Ground Ball", "Line Drive", "Fly Ball", "Pop Up"]))
            children.append(ui.p(
                "Where did it land? Click the field below, or type coordinates directly.",
                class_="text-muted small",
            ))
            children.append(ui.layout_columns(
                ui.input_numeric("batted_ball_x_input", "Feet right of the CF line (negative = left field side)", value=0.0, min=field_location.X_MIN, max=field_location.X_MAX, step=5.0),
                ui.input_numeric("batted_ball_y_input", "Feet from home plate toward the outfield", value=150.0, min=field_location.Y_MIN, max=field_location.Y_MAX, step=5.0),
            ))
        if not children:
            return None
        return ui.div(*children)

    @render_plotly
    def batted_ball_location_widget():
        """Real click-to-place batted-ball landing spot -- see
        intended_location_widget above for the pattern (this is the
        same approach applied to field_location's field selector);
        clicks write into batted_ball_x_input/batted_ball_y_input."""
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is None:
            return None
        req("pitch_outcome_select" in input)
        if input.pitch_outcome_select() != "In Play":
            return None
        req("batted_ball_x_input" in input)
        x, y = input.batted_ball_x_input(), input.batted_ball_y_input()
        return _build_clickable_widget(field_location.build_field_selector_figure(marker_x=x, marker_y=y))

    @render.ui
    def batted_ball_location_caption():
        if not _access_ok() or not _can_edit():
            return None
        if _active_game_id() is None:
            return None
        req("pitch_outcome_select" in input)
        if input.pitch_outcome_select() != "In Play":
            return None
        req("batted_ball_x_input" in input)
        x, y = input.batted_ball_x_input(), input.batted_ball_y_input()
        dist = field_location.distance_from_plate(x, y)
        return ui.p(
            f"Landed: {x:+.0f} ft, {y:.0f} ft deep ({dist:.0f} ft from home) — click the field above, or type coordinates directly.",
            class_="text-muted small text-center",
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None
            outcome = input.pitch_outcome_select()
            force_end_pa = input.force_end_pa_checkbox() if "force_end_pa_checkbox" in input else False
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome, force=force_end_pa)
            if not ends_pa:
                return None
            # Called Strike is a strikeout LOOKING, Swing and Miss is
            # swinging -- default to the right one instead of always
            # "K", same "suggested, not forced" pattern as everything
            # else in this picker (coach can still override).
            strikeout_default = "K (Looking)" if outcome == "Called Strike" else "K"
            if new_balls >= 4:
                default_ab = "BB"
            elif new_strikes >= 3:
                default_ab = strikeout_default
            elif outcome == "HBP":
                default_ab = "HBP"
            elif outcome == "In Play":
                default_ab = "1B"
            else:
                # Only reachable via the force-end-the-at-bat override --
                # the count alone doesn't suggest anything, so leave it
                # unselected rather than default to a guess (e.g. a
                # forced "Ball" is often actually a hit-by-pitch the
                # coach is flagging manually -- don't assume "1B").
                default_ab = None
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return None
            outcome = input.pitch_outcome_select()
            force_end_pa = input.force_end_pa_checkbox() if "force_end_pa_checkbox" in input else False
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome, force=force_end_pa)
            if not ends_pa:
                return None
            req("ab_outcome_select" in input)
            ab_outcome = input.ab_outcome_select()
            suggested_outs, suggested_bases, suggested_runs = suggest_after_state(ab_outcome, state["bases"], state["outs"])
            return ui.div(
                ui.layout_columns(
                    ui.input_numeric("final_outs_input", "Outs after", value=min(suggested_outs, 3), min=0, max=3, step=1),
                    ui.input_text("final_bases_input", "Bases after (1st,2nd,3rd = 1/0)", value=suggested_bases),
                    ui.input_numeric("final_runs_input", "Runs scored on play", value=suggested_runs, min=0, max=4, step=1),
                ),
                # Manual earned/unearned tagging (Ryker, Aug 31 2026) --
                # defaults to 0 (all earned, the common case); bump this
                # up only when an error caused a run that wouldn't have
                # scored on clean defense. See
                # models.GamePitch.unearned_runs_on_play for the full
                # reasoning on why this is manual, not auto-derived.
                ui.input_numeric("unearned_runs_input", "Of those, unearned (error-caused)", value=0, min=0, max=4, step=1),
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
                if last_pitch.batting_squad == "A":
                    game.our_score = max(0, game.our_score - last_pitch.runs_scored_on_play)
                elif last_pitch.batting_squad == "B":
                    game.opponent_score = max(0, game.opponent_score - last_pitch.runs_scored_on_play)
                elif last_pitch.batting_squad == "C":
                    game.squad_c_score = max(0, game.squad_c_score - last_pitch.runs_scored_on_play)
                elif last_pitch.is_our_team_batting:
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
            game, pitches, squad_a_slots, squad_b_slots, opponent_lineup_slots, state, squad_c_slots = ctx
            if game.status != "In Progress":
                return

            our_player_choice = opp_hand_choice = opp_batting_order_choice = opp_player_choice = opp_our_player_choice = None
            batting_squad = None
            if game.uses_three_squad_intrasquad:
                # Three-squad intrasquad games -- see the module-level
                # note above suggest_current_batting_squad for the
                # "our_player_id/opponent_our_player_id role flips with
                # is_our_team_batting's parity" convention this reuses.
                # batting_squad ('A'/'B'/'C') is recorded separately and
                # is what actually identifies which real squad was up.
                batting_squad = suggest_current_batting_squad(pitches, state)
                if state["new_pa"]:
                    req("batting_squad_select" in input)
                    batting_squad = input.batting_squad_select()  # coach's live pick -- may override the rotation-suggested default just computed above
                    if "three_squad_batter_select" not in input or not input.three_squad_batter_select():
                        ui.notification_show("Select who's batting first.", type="error", duration=8)
                        return
                    batter_id = int(input.three_squad_batter_select())
                    if "three_squad_pitcher_select" not in input or not input.three_squad_pitcher_select():
                        ui.notification_show("Select the pitcher first.", type="error", duration=8)
                        return
                    pitcher_id = int(input.three_squad_pitcher_select())
                    opp_hand_choice = input.three_squad_pitcher_hand_radio() if "three_squad_pitcher_hand_radio" in input else "R"
                    if state["is_our_batting"]:
                        our_player_choice, opp_our_player_choice = batter_id, pitcher_id
                    else:
                        our_player_choice, opp_our_player_choice = pitcher_id, batter_id
                else:
                    our_player_choice = state.get("current_our_player")
                    opp_hand_choice = state.get("current_opp_hand")
                    opp_our_player_choice = state.get("current_opp_our_player")
                    if our_player_choice is None:
                        ui.notification_show("Couldn't determine who's up -- try refreshing the page.", type="error", duration=8)
                        return
            elif state["new_pa"]:
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

            # Milestone 4 -- which GameLineupSlot the batter currently
            # occupies, so "who's up next" can look this up directly
            # instead of re-matching by identity. Only meaningful when
            # the batter is one of our own roster players in a saved
            # lineup (Squad A batting, intrasquad Squad B batting, or any
            # squad batting in three-squad mode) -- None for a true
            # external-opponent batter, where there's no GameLineupSlot
            # to reference.
            batting_slot_id = None
            if game.uses_three_squad_intrasquad:
                slots_by_squad = {"A": squad_a_slots, "B": squad_b_slots, "C": squad_c_slots}
                batter_id_for_slot = our_player_choice if state["is_our_batting"] else opp_our_player_choice
                batting_slot_id = _resolve_current_batting_slot(slots_by_squad.get(batting_squad, []), batter_id_for_slot)
            elif state["is_our_batting"]:
                batting_slot_id = _resolve_current_batting_slot(squad_a_slots, our_player_choice)
            elif game.is_intrasquad:
                batting_slot_id = _resolve_current_batting_slot(squad_b_slots, opp_our_player_choice)

            req("pitch_type_select" in input)
            pitch_type_name = input.pitch_type_select()
            pitch_types = db.query(PitchType).all()
            pitch_type_id = next((pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_name), None)

            intended_x = intended_z = None
            if ((not state["is_our_batting"]) or game.is_intrasquad) and "intended_x_input" in input:
                intended_x, intended_z = input.intended_x_input(), input.intended_z_input()

            # Actual location isn't captured live here either -- same as
            # the original, filled in afterward from game video via
            # Video Review. As of this change, EVERY pitch eventually gets
            # an actual location this way, not just ones we threw -- see
            # the Video Review section below.
            actual_x = actual_z = None

            req("pitch_outcome_select" in input)
            outcome = input.pitch_outcome_select()
            force_end_pa = input.force_end_pa_checkbox() if "force_end_pa_checkbox" in input else False
            ends_pa, new_balls, new_strikes = _ends_plate_appearance(state, outcome, force=force_end_pa)

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
                final_bases = (input.final_bases_input() or "").strip()
                if not re.fullmatch(r"[01]{3}", final_bases):
                    ui.notification_show(
                        'Bases after must be exactly 3 characters of 0/1 (e.g. "010" = runner on 2nd only) -- pitch not recorded.',
                        type="error", duration=10,
                    )
                    return
                final_runs = int(input.final_runs_input())
                unearned_runs = int(input.unearned_runs_input()) if "unearned_runs_input" in input else 0
                if unearned_runs > final_runs:
                    ui.notification_show(
                        "Unearned runs can't exceed runs scored on the play -- pitch not recorded.",
                        type="error", duration=8,
                    )
                    return

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
                batting_slot_id=batting_slot_id,
                batting_squad=batting_squad,
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
                unearned_runs_on_play=unearned_runs if ends_pa else 0,
                re_before=re_before,
                re_after=re_after,
                run_value=run_value,
                notes=notes or None,
            ))
            if ends_pa and final_runs:
                if batting_squad == "A":
                    game.our_score += final_runs
                elif batting_squad == "B":
                    game.opponent_score += final_runs
                elif batting_squad == "C":
                    game.squad_c_score += final_runs
                elif state["is_our_batting"]:
                    game.our_score += final_runs
                else:
                    game.opponent_score += final_runs
            db.commit()

            ui.notification_show("Pitch recorded.", type="message", duration=6)
            _runner_event_form_open.set(False)  # fresh pitch -- collapse the runner-event form back down, see runner_events_panel
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
    # Extracted to game_tracking_video_display.py (Tier 2 split, 2026-09
    # -- see that file's module docstring). _vr_current_pitch_id and
    # _registered_clip_match_ids moved with it (used nowhere else in this
    # server function). Registered here, once, synchronously, same
    # pattern as register_game_tracking_manage above.
    game_tracking_video_display.register_game_tracking_video(
        input, output, session, _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_refresh,
    )

    # -------------------------------------------------------------------
    # Pitch Log
    # -------------------------------------------------------------------
    # Extracted to game_tracking_pitch_log_display.py (Tier 2 split,
    # 2026-09 -- see that file's module docstring for why
    # _registered_pitch_row_ids/_gt_editing_pitch_id/
    # _gt_pending_delete_pitch_id/_pitch_log_limit/_gt_pl_pending_preview
    # stay defined here (below) rather than moving with the functions --
    # _sync_active_game_id above still resets them on game change).
    # AB_OUTCOMES/build_re_lookup/replay_game are threaded in the same
    # way PITCH_OUTCOMES/CONTACT_QUALITY_OPTIONS already were, for the
    # same circular-import reason. Registered here, once, synchronously,
    # same pattern as the other extracted sections.
    game_tracking_pitch_log_display.register_game_tracking_pitch_log(
        input, output, session, app_state,
        _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_pa, _bump_refresh,
        _registered_pitch_row_ids, _gt_editing_pitch_id, _gt_pending_delete_pitch_id, _pitch_log_limit,
        _gt_pl_pending_preview, _gt_pl_pending_forced_end,
        _gt_pl_adding_runner_event_pitch_id, _gt_pl_pending_runner_add,
        PITCH_OUTCOMES, CONTACT_QUALITY_OPTIONS, AB_OUTCOMES,
        RUNNER_EVENT_TYPES, RUNNER_EVENT_OUT_TYPES,
        build_re_lookup, replay_game,
    )

    # -------------------------------------------------------------------
    # Runner Events Log
    # -------------------------------------------------------------------
    # Extracted to game_tracking_runner_events_display.py, mirroring the
    # Pitch Log split above (same reasons: _registered_runner_event_row_ids/
    # _gt_re_editing_event_id/_gt_re_pending_preview stay defined here so
    # _sync_active_game_id can keep resetting them on game change).
    game_tracking_runner_events_display.register_game_tracking_runner_events(
        input, output, session,
        _refresh_tick, _active_game_id, _access_ok, _can_edit, _bump_pa, _bump_refresh,
        _registered_runner_event_row_ids, _gt_re_editing_event_id, _gt_re_pending_preview,
        build_re_lookup, replay_game,
        RUNNER_EVENT_TYPES, RUNNER_EVENT_OUT_TYPES,
    )

    # -------------------------------------------------------------------
    # Manage Game
    # -------------------------------------------------------------------
    # Extracted to game_tracking_manage_display.py (Tier 2 split, 2026-09
    # -- see that file's module docstring). Registered here, once,
    # synchronously, exactly like bullpen_dashboard_display.register_
    # bullpen_dashboard is registered from bullpen_dashboard_server --
    # this still runs inside game_tracking_server's own namespaced
    # session context, so manage_game_body/game_status_controls/
    # game_delete_section auto-register to the same output ids
    # game_tracking_ui already expects (ui.output_ui("game_tabs") ->
    # manage_game_body -> those two), unchanged.
    game_tracking_manage_display.register_game_tracking_manage(
        input, output, session, _refresh_tick, _active_game_id, _bump_refresh, _access_ok, _can_edit,
    )
