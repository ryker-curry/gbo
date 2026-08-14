"""
GBO — Game Tracking (Phase 1: live tracking sheet).

The Baseball-Savant-style advanced stats page (Whiff%, CSW%, Chase%,
Putaway%, Run Expectancy/Run Value, splits by handedness, etc.) is a
deliberate follow-up phase, not built yet -- this page is the core:
get a real game trackable, pitch by pitch, both sides of the ball.

Design decisions (see models.py for the schema reasoning):
  - ONE pitch record covers both pitching and hitting context at once
    (is_our_team_batting flag), matching Ryker's own tracking sheet's
    one-row-per-pitch structure -- not two separate systems.
  - Inning/outs/bases/count are DERIVED from the last pitch stored in
    the database, not from session_state -- so nothing is lost on a
    page refresh mid-game, which matters a lot for something used live.
  - Who's up each new plate appearance is a fresh SELECTION, not an
    auto-cycled batting order -- more robust to real substitutions and
    simpler to get right than a fragile auto-advance system.
  - AB outcome suggests sensible outs/bases/runs defaults, always
    editable -- real plays have too many edge cases (errors, odd
    advances) to fully automate.

Layout (once a game is active): a persistent title + KPI scoreboard
(score/status) sit above everything else, then five tabs -- Live
Tracking, Lineup & Setup, Video Review, Pitch Log, Manage Game -- split
what used to be one long top-to-bottom scroll (season/game setup,
lineup, live entry, video review, pitch log, status controls all
stacked together) into focused screens. st.tabs (not a sidebar or wide
multi-column layout) so it works reasonably on both a tablet/phone in
the dugout and a laptop. Inside Live Tracking, the historically dense
linear widget sequence (who's up -> pitch type -> location -> outcome
-> AB result) is now grouped into bordered containers (Game State/
Who's Up/Pitch Details/Result) purely for visual chunking -- no
functional logic, session-state keys, or field behavior changed from
before this reorganization."""

import streamlit as st
import uuid
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
import strike_zone
import field_location
from models import (
    Player, Position, PitchType, Game, GameLineupSlot, GamePitch, RunExpectancy,
    OpponentTeam, OpponentPlayer, Season, PitchingChange, PlayerPitchArsenal, OpponentLineupSlot,
    GameVideoClip,
)
from ui_components import page_header, page_footer, empty_state, render_kpi_cards
from r2_client import upload_video_to_r2

page_header("Game Tracking")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False) or role_name == "Data Analyst"  # Data Analyst is "in charge of all game tracking data collection and analysis" -- real edit rights here specifically, without changing their broader can_edit_sessions flag (stays read-only on Bullpen/Hitter Tracking)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

PITCH_OUTCOMES = ["Ball", "Called Strike", "Swing and Miss", "Foul", "In Play", "HBP"]
AB_OUTCOMES = [
    "K", "BB", "HBP", "1B", "2B", "3B", "HR", "E", "FC",
    "Sac Bunt", "Sac Fly", "Groundout", "Flyout", "Lineout", "Double Play",
]
CONTACT_QUALITY_OPTIONS = ["Barrel", "Solid", "Weak", "Miss"]

GAME_VIDEO_SUBFOLDER = "pitch-videos/"  # same folder Video Review's pitcher/hitter clips upload into, inside the one shared R2 bucket


def upload_game_video_clip(uploaded_file, identifier: str):
    """Upload one clip to Cloudflare R2 and return its public URL, or
    None (with an st.error already shown) if the upload failed -- same
    helper pattern as pitch_video.py's upload_pitch_video, uploading
    into the same folder."""
    try:
        return upload_video_to_r2(uploaded_file, identifier, bucket_subfolder=GAME_VIDEO_SUBFOLDER)
    except Exception as e:
        st.error(
            f"Video upload failed: {e}. "
            f"Make sure Cloudflare R2 is configured (R2_ACCOUNT_ID/R2_ACCESS_KEY_ID/R2_SECRET_ACCESS_KEY/"
            f"R2_BUCKET_NAME/R2_PUBLIC_URL_BASE in .env -- see r2_client.py's docstring for setup steps)."
        )
        return None


def build_re_lookup(session):
    """Load Ryker's RunExpectancy table into a dict for fast lookup:
    (outs, bases, count) -> re_value. Returns an empty dict (RE/RV
    silently skipped, not an error) if the table hasn't been migrated
    yet or is empty."""
    rows = session.query(RunExpectancy).all()
    return {(r.outs, r.bases, r.count): float(r.re_value) for r in rows}


def compute_re_and_rv(re_lookup, outs_before, bases_before, balls_before, strikes_before,
                       ends_pa, outs_after, bases_after, runs_scored, new_balls=None, new_strikes=None):
    """RE Before/After and Run Value for one pitch, using Ryker's own
    table. Mirrors exactly how his own tracking sheet computes it
    (verified against his real example rows before building this):
      - re_before = lookup at the state before this pitch.
      - re_after: if this pitch ended the PA, look up the resulting
        state with count reset to 0-0 (next batter's starting count) --
        or 0 if the inning ended (3 outs). Otherwise, only the count
        changed (outs/bases stayed the same), so look up the same
        outs/bases with the ACTUAL new count (new_balls/new_strikes,
        passed in by the caller -- this function doesn't re-derive it,
        since a Ball, Called Strike, Swing and Miss, and Foul all
        change the count differently).
      - run_value = (re_after + runs_scored) - re_before.
    Returns (re_before, re_after, run_value) -- any of these can be
    None if the needed state isn't in the table."""
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
    """Whoever most recently entered the game as pitcher (the latest
    PitchingChange, ordered by when they entered), falling back to the
    starting pitcher if no formal change has happened yet. This is the
    single source of truth for "who's pitching" -- the coach only
    interacts with this via an explicit "Make a pitching change"
    action, never a per-PA dropdown."""
    changes = sorted(game.pitching_changes, key=lambda c: c.pitch_sequence_at_entry)
    if changes:
        return changes[-1].player_id
    return game.starting_pitcher_id


def get_arsenal_pitch_type_names(session, pitcher_id, all_pitch_types):
    """Pitch type names this pitcher is set up to throw. Falls back to
    every pitch type if no arsenal has been configured for them yet --
    doesn't block data entry before arsenals are set up."""
    arsenal = (
        session.query(PlayerPitchArsenal)
        .filter(PlayerPitchArsenal.player_id == pitcher_id, PlayerPitchArsenal.active.is_(True))
        .all()
    )
    if not arsenal:
        return [pt.type_name for pt in all_pitch_types]
    arsenal_type_ids = {a.pitch_type_id for a in arsenal}
    return [pt.type_name for pt in all_pitch_types if pt.pitch_type_id in arsenal_type_ids]


def suggest_next_our_batter(game, lineup_slots):
    """Who should bat next for us -- derived from whoever last completed
    a PA while we were batting (searching back across innings if
    needed, not just the last pitch overall), wrapping through the
    lineup. Returns None if there's no lineup to cycle through (coach
    picks manually in that case, same as before)."""
    if not lineup_slots:
        return None
    our_pa_endings = sorted(
        [p for p in game.pitches if p.is_our_team_batting and p.ends_plate_appearance],
        key=lambda p: p.pitch_sequence,
    )
    if not our_pa_endings:
        return lineup_slots[0].player_id  # leadoff hitter, first time up
    last_batter_id = our_pa_endings[-1].our_player_id
    last_slot = next((s for s in lineup_slots if s.player_id == last_batter_id), None)
    if last_slot is None:
        return lineup_slots[0].player_id
    slot_orders = sorted(s.batting_order for s in lineup_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    return next((s.player_id for s in lineup_slots if s.batting_order == next_order), lineup_slots[0].player_id)


def suggest_next_squad_b_batter(game, squad_b_slots):
    """Who should bat next for Squad B in an intrasquad game -- same
    logic as suggest_next_our_batter (Squad A), mirrored onto Squad B's
    own saved lineup. Squad B bats when is_our_team_batting is False
    (Squad A is pitching), and their batter is stored as
    opponent_our_player_id rather than our_player_id. Returns None if
    no Squad B lineup is set up for this game (coach picks manually in
    that case, same as before Squad B lineups existed)."""
    if not squad_b_slots:
        return None
    squad_b_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_our_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if not squad_b_pa_endings:
        return squad_b_slots[0].player_id  # leadoff hitter, first time up
    last_batter_id = squad_b_pa_endings[-1].opponent_our_player_id
    last_slot = next((s for s in squad_b_slots if s.player_id == last_batter_id), None)
    if last_slot is None:
        return squad_b_slots[0].player_id
    slot_orders = sorted(s.batting_order for s in squad_b_slots)
    current_idx = slot_orders.index(last_slot.batting_order)
    next_order = slot_orders[(current_idx + 1) % len(slot_orders)]
    return next((s.player_id for s in squad_b_slots if s.batting_order == next_order), squad_b_slots[0].player_id)


def suggest_next_opponent_order(game):
    """Next opponent batting-order NUMBER (1-9, wrapping) -- external
    games only, since there's no formal per-game opponent lineup yet
    (Phase 2). The coach still picks which named player occupies that
    slot; this just saves re-typing the number each time."""
    opp_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_batting_order],
        key=lambda p: p.pitch_sequence,
    )
    if not opp_pa_endings:
        return 1
    last_order = opp_pa_endings[-1].opponent_batting_order
    return (last_order % 9) + 1


def suggest_next_opponent_lineup_player(game, opponent_lineup_slots):
    """Who should bat next for the OPPONENT -- same logic as
    suggest_next_our_batter, mirrored for a real per-game opponent
    lineup (Phase 2). Returns None if no opponent lineup is set up for
    this game (coach picks from the roster manually in that case, same
    as before this existed)."""
    if not opponent_lineup_slots:
        return None
    opp_pa_endings = sorted(
        [p for p in game.pitches if not p.is_our_team_batting and p.ends_plate_appearance and p.opponent_player_id],
        key=lambda p: p.pitch_sequence,
    )
    if not opp_pa_endings:
        return opponent_lineup_slots[0].opponent_player_id  # leadoff, first time up
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
    """Sensible defaults for outs_after/bases_after/runs_scored given an
    AB outcome -- a starting point, not a rules engine. Always shown
    editable before saving."""
    b = list(bases_before or "000")
    outs = outs_before
    runs = 0

    def force_advance():
        nonlocal b, runs
        if b[0] == "1":
            if b[1] == "1":
                if b[2] == "1":
                    runs += 1  # bases loaded, runner on 3rd forced home
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


def compute_current_state(game, lineup_slots):
    pitches = sorted(game.pitches, key=lambda p: p.pitch_sequence)
    default_batter = lineup_slots[0].player_id if lineup_slots else None
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
            # Derived from the DB, not session_state -- survives a hard
            # browser refresh mid-plate-appearance, unlike relying on
            # session_state alone (same lesson learned earlier building
            # Bullpen Tracking's session persistence).
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


session = get_session()
try:
    seasons = session.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
    seasons_by_id = {s.season_id: s for s in seasons}

    if can_edit_sessions:
        with st.expander("Manage seasons"):
            if seasons:
                st.dataframe(
                    [
                        {"Season": s.season_name, "Official": "Yes" if s.is_official else "No (practice/fall)", "Games": len(s.games)}
                        for s in seasons
                    ],
                    use_container_width=True, hide_index=True,
                )
            with st.form("new_season_form"):
                new_season_name = st.text_input("New season name", placeholder="e.g. Fall 2026, Spring 2027")
                new_season_official = st.checkbox("Official (counts toward real record -- uncheck for fall/practice)", value=True)
                new_season_submitted = st.form_submit_button("Create season", type="primary")
            if new_season_submitted:
                if not new_season_name.strip():
                    st.error("Season name is required.")
                elif session.query(Season).filter(Season.season_name == new_season_name.strip()).first():
                    st.error(f"A season named \"{new_season_name.strip()}\" already exists.")
                else:
                    session.add(Season(season_name=new_season_name.strip(), is_official=new_season_official, created_by_user_id=current_user_id))
                    session.commit()
                    st.success(f"Created season: {new_season_name.strip()}.")
                    st.rerun()

    season_filter_options = [None] + list(seasons_by_id.keys())
    season_filter_choice = st.selectbox(
        "Season",
        options=season_filter_options,
        format_func=lambda sid: "-- All seasons --" if sid is None else f"{seasons_by_id[sid].season_name}" + ("" if seasons_by_id[sid].is_official else " (practice/fall, not official)"),
        key="gt_season_filter",
    )

    games_query = session.query(Game).order_by(Game.game_date.desc())
    if season_filter_choice is not None:
        games_query = games_query.filter(Game.season_id == season_filter_choice)
    games = games_query.all()
    games_by_id = {g.game_id: g for g in games}

    query_game_id_raw = st.query_params.get("game_id")
    try:
        default_game_id = int(query_game_id_raw) if query_game_id_raw is not None else None
    except ValueError:
        default_game_id = None
    if default_game_id not in games_by_id:
        default_game_id = None

    def _set_active_game(game_id):
        if game_id is None:
            st.query_params.pop("game_id", None)
        else:
            st.query_params["game_id"] = str(game_id)

    def _opponent_display_name(g):
        if g.opponent_team:
            return g.opponent_team.team_name
        return g.opponent_name or "Unknown opponent"

    def _game_label(gid):
        if gid is None:
            return "-- Start a new game --"
        g = games_by_id[gid]
        loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
        season_label = f"[{g.season.season_name}] " if g.season else ""
        return f"{season_label}{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {_opponent_display_name(g)} ({g.status}) — {g.our_score}-{g.opponent_score}"

    game_options = [None] + list(games_by_id.keys())
    game_index = game_options.index(default_game_id) if default_game_id in game_options else 0
    active_game_id = st.selectbox("Game", options=game_options, index=game_index, format_func=_game_label, key="game_selectbox")
    if active_game_id != default_game_id:
        _set_active_game(active_game_id)

    active_game = games_by_id[active_game_id] if active_game_id is not None else None

    players = session.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
    players_by_id = {p.player_id: p for p in players}
    positions = session.query(Position).order_by(Position.display_order).all()
    pitch_types = session.query(PitchType).order_by(PitchType.pitch_type_id).all()
    opponent_teams = session.query(OpponentTeam).order_by(OpponentTeam.team_name).all()
    opponent_teams_by_id = {t.team_id: t for t in opponent_teams}

    if can_edit_sessions:
        st.caption("Pitch arsenals are managed on each pitcher's profile (Players page), not here.")

    if active_game_id is None and can_edit_sessions:
        st.subheader("Start a new game")
        if not seasons:
            st.warning("Create a season above first (e.g. \"Fall 2026\") before starting a game.")
        else:
            season_choice = st.selectbox(
                "Season",
                options=list(seasons_by_id.keys()),
                format_func=lambda sid: f"{seasons_by_id[sid].season_name}" + ("" if seasons_by_id[sid].is_official else " (practice/fall, not official)"),
            )
            is_intrasquad_choice = st.checkbox("Intrasquad scrimmage (Squad A vs Squad B, our own roster on both sides)")

            opponent_team_choice = None
            if not is_intrasquad_choice:
                opponent_team_choice = st.selectbox(
                    "Opponent",
                    options=[None] + list(opponent_teams_by_id.keys()),
                    format_func=lambda tid: "-- One-off opponent, just type a name --" if tid is None else opponent_teams_by_id[tid].team_name,
                )
                if opponent_team_choice is None:
                    st.caption("Not in your list yet? Add them as a reusable team on Opponent Teams for next time -- or just type a name below for a one-off.")

            with st.form("new_game_form"):
                opponent_name_input = None
                if not is_intrasquad_choice and opponent_team_choice is None:
                    opponent_name_input = st.text_input("Opponent name")
                game_date_input = st.date_input("Date", value=date.today())
                location_choice = st.selectbox("Location", ["Home", "Away", "Neutral site"], disabled=is_intrasquad_choice)
                new_game_submitted = st.form_submit_button("Create game", type="primary")

            if new_game_submitted:
                if not is_intrasquad_choice and opponent_team_choice is None and not (opponent_name_input or "").strip():
                    st.error("Opponent name is required.")
                else:
                    is_home = None if is_intrasquad_choice else {"Home": True, "Away": False, "Neutral site": None}[location_choice]
                    new_game = Game(
                        season_id=season_choice,
                        opponent_team_id=opponent_team_choice if not is_intrasquad_choice else None,
                        opponent_name=(opponent_name_input.strip() if opponent_name_input else None) if not is_intrasquad_choice else "Intrasquad Scrimmage",
                        is_intrasquad=is_intrasquad_choice,
                        game_date=game_date_input,
                        is_home=is_home,
                        status="Scheduled",
                        created_by_user_id=current_user_id,
                    )
                    session.add(new_game)
                    session.commit()
                    _set_active_game(new_game.game_id)
                    if is_intrasquad_choice:
                        display_name = "Intrasquad Scrimmage"
                    else:
                        display_name = opponent_teams_by_id[opponent_team_choice].team_name if opponent_team_choice else opponent_name_input.strip()
                    st.success(f"Created game vs {display_name} ({seasons_by_id[season_choice].season_name}).")
                    st.rerun()
    elif active_game_id is None:
        st.info("Your role has read-only access to game tracking.")

    if active_game:
        st.divider()
        loc = "vs" if active_game.is_home else ("@" if active_game.is_home is False else "vs (neutral)")
        st.markdown(f"### {loc} {_opponent_display_name(active_game)} — {active_game.game_date.strftime('%Y-%m-%d (%a)')}")
        render_kpi_cards([
            {"label": "Us", "value": str(active_game.our_score)},
            {"label": "Opponent", "value": str(active_game.opponent_score)},
            {"label": "Status", "value": active_game.status},
        ])

        lineup_slots = session.query(GameLineupSlot).options(joinedload(GameLineupSlot.player)).filter(GameLineupSlot.game_id == active_game.game_id).order_by(GameLineupSlot.batting_order).all()
        squad_a_slots = [s for s in lineup_slots if (s.squad or "A") == "A"]
        squad_b_slots = [s for s in lineup_slots if s.squad == "B"]

        tab_live, tab_setup, tab_video, tab_log, tab_manage = st.tabs(
            ["Live Tracking", "Lineup & Setup", "Video Review", "Pitch Log", "Manage Game"]
        )

        with tab_setup:

            def _render_squad_lineup_setup(squad, squad_slots, other_squad_slots, label):
                """Shared 'Set lineup' form for Squad A (every game) or
                Squad B (intrasquad only) -- same shape, just scoped to
                one squad's batting order via the squad column, and
                excluding whoever's already claimed by the OTHER squad
                (a player can't be on both sides of an intrasquad game
                at once)."""
                st.subheader(f"Set {label}" if label != "Lineup" else "Set lineup")

                other_squad_taken_ids = {s.player_id for s in other_squad_slots}
                include_pitchers_key = f"include_pitchers_in_lineup_{squad}"
                include_pitchers_in_lineup = st.checkbox("Include pitchers in the batting order (two-way players)", key=include_pitchers_key)
                batter_candidate_ids = [
                    pid for pid in (list(players_by_id.keys()) if include_pitchers_in_lineup else [pid for pid, p in players_by_id.items() if not p.is_pitcher])
                    if pid not in other_squad_taken_ids
                ]
                pitcher_candidate_ids = [pid for pid, p in players_by_id.items() if p.is_pitcher]

                # Adjustable spot count -- intrasquad scrimmages sometimes
                # run extra hitters through the order, so 9 can't be a hard
                # ceiling the way it effectively is for a real defense.
                num_lineup_spots = st.number_input(
                    "Number of batting order spots", min_value=9, max_value=20, value=9, step=1,
                    key=f"lineup_num_spots_{squad}",
                    help="9 covers a standard lineup. Raise this for intrasquad games running extra hitters through the order.",
                )
                st.caption(
                    f"{num_lineup_spots} batting order slots + starting pitcher. Each player can only fill "
                    "one slot -- once picked, he drops out of the other dropdowns. You can still track the "
                    "game without a full lineup -- this just makes the batter picker faster."
                )

                # Deliberately not an st.form(): each pick needs to trigger an
                # immediate rerun so the OTHER slots' dropdowns can drop that
                # player from their own options right away -- a form only
                # reruns once, on submit, which is too late to filter live as
                # the coach works down the list.
                slot_choices = {}
                for i in range(1, num_lineup_spots + 1):
                    already_taken = {
                        st.session_state.get(f"lineup_player_{squad}_{j}")
                        for j in range(1, num_lineup_spots + 1) if j != i
                    }
                    already_taken.discard(None)
                    options_for_slot = [None] + [pid for pid in batter_candidate_ids if pid not in already_taken]

                    cols = st.columns([1, 3, 2])
                    cols[0].markdown(f"**{i}.**")
                    player_choice = cols[1].selectbox(
                        f"Batter {i}", options=options_for_slot,
                        format_func=lambda pid: "-- Select --" if pid is None else f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                        key=f"lineup_player_{squad}_{i}", label_visibility="collapsed",
                    )
                    position_choice = cols[2].selectbox(
                        f"Position {i}", options=[None] + [p.position_id for p in positions],
                        format_func=lambda pid: "-- Position --" if pid is None else next(p.position_name for p in positions if p.position_id == pid),
                        key=f"lineup_pos_{squad}_{i}", label_visibility="collapsed",
                    )
                    slot_choices[i] = (player_choice, position_choice)

                starting_pitcher_choice = None
                if squad == "A":
                    # Squad A's starting pitcher/pitching changes are the
                    # game's formal pitching-staff tracking (starting_pitcher_id
                    # + PitchingChange). Squad B's pitcher intentionally stays
                    # a per-at-bat pick, same as before Squad B lineups existed
                    # -- not covered by this form.
                    starting_pitcher_choice = st.selectbox(
                        "Starting pitcher", options=[None] + pitcher_candidate_ids,
                        format_func=lambda pid: "-- Select --" if pid is None else f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                        key="lineup_starting_pitcher",
                    )

                if st.button("Save lineup", type="primary", key=f"lineup_save_button_{squad}"):
                    added = 0
                    for i, (player_choice, position_choice) in slot_choices.items():
                        if player_choice is not None:
                            session.add(GameLineupSlot(game_id=active_game.game_id, squad=squad, batting_order=i, player_id=player_choice, starting_position_id=position_choice))
                            added += 1
                    if squad == "A":
                        active_game.starting_pitcher_id = starting_pitcher_choice
                    session.commit()
                    st.success(f"Saved {label.lower()} ({added} batters).")
                    st.rerun()

            def _render_squad_lineup_display(squad_slots, label, show_pitcher):
                with st.expander(label, expanded=True):
                    st.dataframe(
                        [
                            {"#": s.batting_order, "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—", "Position": s.starting_position.position_name if s.starting_position else "—"}
                            for s in squad_slots
                        ],
                        use_container_width=True, hide_index=True,
                    )
                    if show_pitcher and active_game.starting_pitcher_id and active_game.starting_pitcher_id in players_by_id:
                        p = players_by_id[active_game.starting_pitcher_id]
                        st.caption(f"Starting pitcher: {p.first_name} {p.last_name}")

            # --- Lineup setup (Squad A -- "our" lineup for every game type) ---
            squad_a_label = "Squad A Lineup" if active_game.is_intrasquad else "Lineup"
            if not squad_a_slots and can_edit_sessions:
                _render_squad_lineup_setup("A", squad_a_slots, squad_b_slots, squad_a_label)
            elif squad_a_slots:
                _render_squad_lineup_display(squad_a_slots, squad_a_label, show_pitcher=True)

            # --- Squad B lineup setup (intrasquad games only) -- same shape
            # as Squad A's, so Squad B also gets a real batting order that
            # auto-suggests in Live Tracking instead of being picked ad hoc
            # every at-bat. Squad B's PITCHER stays a per-at-bat pick --
            # deliberately not covered here (see _render_squad_lineup_setup). ---
            if active_game.is_intrasquad:
                if not squad_b_slots and can_edit_sessions:
                    _render_squad_lineup_setup("B", squad_b_slots, squad_a_slots, "Squad B Lineup")
                elif squad_b_slots:
                    _render_squad_lineup_display(squad_b_slots, "Squad B Lineup", show_pitcher=False)

            # --- Opponent Lineup setup -- external games only (not
            # intrasquad, which uses Squad A/B above instead). Works
            # whether or not this opponent already has a built-out
            # OpponentTeam roster: pick an existing roster player, or just
            # type a new name -- typing a name adds them to a reusable
            # roster for this opponent (creating the OpponentTeam itself
            # first if this game started as a one-off typed name), so next
            # time you play them you can pick from a list instead of
            # retyping. Optional -- Game Tracking works fine without it,
            # same as before. ---
            opponent_lineup_slots = session.query(OpponentLineupSlot).options(joinedload(OpponentLineupSlot.opponent_player)).filter(OpponentLineupSlot.game_id == active_game.game_id).order_by(OpponentLineupSlot.batting_order).all()
            if not active_game.is_intrasquad and not opponent_lineup_slots and can_edit_sessions:
                opp_display_label = active_game.opponent_team.team_name if active_game.opponent_team else (active_game.opponent_name or "the opponent")
                opp_existing_roster = active_game.opponent_team.roster if active_game.opponent_team else []
                st.subheader(f"Set {opp_display_label}'s lineup (optional)")
                st.caption(
                    "9 batting order slots + starting pitcher. Pick a name from their roster if you've "
                    "got one built out, or just type a new name -- typing a name adds them to a reusable "
                    "roster for this opponent, so next time you play them you can pick from a list instead "
                    "of retyping. Skip this and Game Tracking still works -- you'll just pick the batter "
                    "manually each at-bat instead of it being suggested automatically."
                )
                opp_roster_candidate_ids = [p.opponent_player_id for p in opp_existing_roster]

                def _opp_roster_format(pid):
                    return "-- Existing roster --" if pid is None else next(p.player_name for p in opp_existing_roster if p.opponent_player_id == pid)

                with st.form("opponent_lineup_form"):
                    opp_slot_choices = {}
                    for i in range(1, 10):
                        cols = st.columns([1, 3, 3, 1])
                        cols[0].markdown(f"**{i}.**")
                        existing_pick = cols[1].selectbox(
                            f"Existing opponent batter {i}", options=[None] + opp_roster_candidate_ids,
                            format_func=_opp_roster_format,
                            key=f"opp_lineup_existing_{i}", label_visibility="collapsed",
                        )
                        new_name = cols[2].text_input(f"Or type a new name {i}", placeholder="...or type a new name", key=f"opp_lineup_new_{i}", label_visibility="collapsed")
                        new_jersey = cols[3].text_input(f"# {i}", placeholder="#", key=f"opp_lineup_jersey_{i}", label_visibility="collapsed")
                        opp_slot_choices[i] = (existing_pick, new_name, new_jersey)

                    st.markdown("**Their starting pitcher**")
                    pcols = st.columns([3, 3, 1])
                    opp_pitcher_existing = pcols[0].selectbox(
                        "Existing opponent pitcher", options=[None] + opp_roster_candidate_ids,
                        format_func=_opp_roster_format,
                        key="opp_pitcher_existing", label_visibility="collapsed",
                    )
                    opp_pitcher_new_name = pcols[1].text_input("Or type a new name (pitcher)", placeholder="...or type a new name", key="opp_pitcher_new_name", label_visibility="collapsed")
                    opp_pitcher_new_jersey = pcols[2].text_input("# (pitcher)", placeholder="#", key="opp_pitcher_new_jersey", label_visibility="collapsed")

                    opp_lineup_submitted = st.form_submit_button("Save opponent lineup", type="primary")

                if opp_lineup_submitted:
                    # Resolve (or create) a reusable OpponentTeam for this
                    # opponent, so typed names build up a real roster for
                    # next time -- same "create once, reuse later"
                    # principle as the rest of Opponent Teams, even when
                    # the game started as just a one-off typed name.
                    opp_team = active_game.opponent_team
                    if opp_team is None:
                        lookup_name = (active_game.opponent_name or "").strip()
                        if lookup_name:
                            opp_team = session.query(OpponentTeam).filter(OpponentTeam.team_name == lookup_name).first()
                        if opp_team is None:
                            opp_team = OpponentTeam(team_name=lookup_name or f"Opponent (Game #{active_game.game_id})", created_by_user_id=current_user_id)
                            session.add(opp_team)
                            session.flush()
                        active_game.opponent_team_id = opp_team.team_id

                    def _resolve_opponent_player(existing_pick, new_name, new_jersey):
                        if existing_pick is not None:
                            return existing_pick
                        name = (new_name or "").strip()
                        if not name:
                            return None
                        new_player = OpponentPlayer(team_id=opp_team.team_id, player_name=name, jersey_number=(new_jersey or "").strip() or None)
                        session.add(new_player)
                        session.flush()
                        return new_player.opponent_player_id

                    opp_added = 0
                    for i, (existing_pick, new_name, new_jersey) in opp_slot_choices.items():
                        resolved_id = _resolve_opponent_player(existing_pick, new_name, new_jersey)
                        if resolved_id is not None:
                            session.add(OpponentLineupSlot(game_id=active_game.game_id, batting_order=i, opponent_player_id=resolved_id))
                            opp_added += 1

                    active_game.opponent_starting_pitcher_id = _resolve_opponent_player(opp_pitcher_existing, opp_pitcher_new_name, opp_pitcher_new_jersey)
                    session.commit()
                    st.success(f"Saved {opp_team.team_name}'s lineup ({opp_added} batters).")
                    st.rerun()

            elif opponent_lineup_slots:
                with st.expander(f"{active_game.opponent_team.team_name}'s lineup"):
                    st.dataframe(
                        [{"#": s.batting_order, "Player": s.opponent_player.player_name if s.opponent_player else "—"} for s in opponent_lineup_slots],
                        use_container_width=True, hide_index=True,
                    )
                    if active_game.opponent_starting_pitcher:
                        st.caption(f"Their starting pitcher: {active_game.opponent_starting_pitcher.player_name}")

        with tab_live:
            # --- Live pitch entry ---
            if can_edit_sessions and active_game.status == "In Progress":
                state = compute_current_state(active_game, squad_a_slots)

                # Auto-suggest who's up next, applied exactly once per new PA
                # transition (detected via pitch count changing) so a manual
                # override by the coach isn't overwritten on later reruns
                # within the same PA (e.g. tapping a zone button).
                current_pitch_count = len(active_game.pitches)
                if state["new_pa"] and st.session_state.get("gt_suggestion_applied_for_count", -1) != current_pitch_count:
                    if state["is_our_batting"]:
                        suggested_batter = suggest_next_our_batter(active_game, squad_a_slots)
                        if suggested_batter is not None:
                            st.session_state["gt_our_batter"] = suggested_batter
                    elif active_game.is_intrasquad:
                        suggested_squad_b_batter = suggest_next_squad_b_batter(active_game, squad_b_slots)
                        if suggested_squad_b_batter is not None:
                            st.session_state["gt_opp_our_batter"] = suggested_squad_b_batter
                    else:
                        st.session_state["gt_opp_order"] = suggest_next_opponent_order(active_game)
                        suggested_opp_player = suggest_next_opponent_lineup_player(active_game, opponent_lineup_slots)
                        if suggested_opp_player is not None:
                            st.session_state["gt_opp_roster_player"] = suggested_opp_player
                    st.session_state["gt_suggestion_applied_for_count"] = current_pitch_count

                with st.container(border=True):
                    half_label = "We're batting" if state["is_our_batting"] else "We're pitching"
                    st.subheader(f"Inning {state['inning']} — {half_label}")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Outs", state["outs"])
                    c2.metric("Count", f"{state['balls']}-{state['strikes']}")
                    c3.metric("Runners", bases_display(state["bases"]))

                    if state["outs"] >= 3:
                        st.warning("3 outs reached but the inning hasn't advanced yet -- this shouldn't normally happen; check the last pitch logged.")

                with st.container(border=True):
                    st.markdown("**Who's Up**")
                    # Who's up this PA
                    our_player_choice = None
                    opp_hand_choice = None
                    opp_batting_order_choice = None
                    opp_player_choice = None
                    opp_our_player_choice = None
                    if state["new_pa"]:
                        st.caption("New plate appearance -- who's up? (auto-suggested from the lineup order, override if needed)")
                        if state["is_our_batting"]:
                            lineup_player_ids = [s.player_id for s in squad_a_slots] if squad_a_slots else [pid for pid, p in players_by_id.items() if not p.is_pitcher]
                            our_player_choice = st.selectbox("Our batter", options=lineup_player_ids, format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}", key="gt_our_batter")

                            if active_game.is_intrasquad:
                                # Pitchers only -- recomputed here rather than
                                # reused from the "Set lineup" section above,
                                # since that section only runs the first time
                                # (before a lineup exists) and its local
                                # pitcher_candidate_ids wouldn't be defined on
                                # this run once a lineup is already saved.
                                opp_pitcher_candidate_ids = [pid for pid, p in players_by_id.items() if p.is_pitcher]
                                if not opp_pitcher_candidate_ids:
                                    st.warning("No active players are marked as pitchers yet -- flag at least one on the Players page.")
                                else:
                                    opp_our_player_choice = st.selectbox(
                                        "Opposing pitcher (Squad B)",
                                        options=opp_pitcher_candidate_ids,
                                        format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                                        key="gt_opp_our_pitcher",
                                    )
                                    default_hand = players_by_id[opp_our_player_choice].throws or "R"
                                    opp_hand_choice = st.radio("Opposing pitcher's throwing hand", ["R", "L"], index=0 if default_hand == "R" else 1, horizontal=True, key="gt_opp_pitcher_hand")
                            else:
                                opp_hand_choice = st.radio("Opposing pitcher's hand", ["R", "L"], horizontal=True, key="gt_opp_pitcher_hand")
                        else:
                            our_player_choice = get_current_pitcher_id(active_game)
                            default_hand = "R"
                            if active_game.is_intrasquad:
                                # Restricted to Squad B's saved lineup (and
                                # auto-suggested from it) once one's been set
                                # up -- same pattern as "Our batter" above.
                                # Falls back to the full roster, unchanged
                                # from before Squad B lineups existed, if no
                                # Squad B lineup has been saved for this game.
                                squad_b_batter_ids = [s.player_id for s in squad_b_slots] if squad_b_slots else list(players_by_id.keys())
                                opp_our_player_choice = st.selectbox(
                                    "Opposing batter (Squad B)",
                                    options=squad_b_batter_ids,
                                    format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                                    key="gt_opp_our_batter",
                                )
                                default_hand = players_by_id[opp_our_player_choice].bats or "R"
                            else:
                                opp_roster = active_game.opponent_team.roster if active_game.opponent_team else []
                                if opp_roster:
                                    opp_roster_by_id = {p.opponent_player_id: p for p in opp_roster}
                                    opp_player_choice = st.selectbox(
                                        "Opposing batter (optional -- pick from roster)",
                                        options=[None] + list(opp_roster_by_id.keys()),
                                        format_func=lambda pid: "-- Not on roster / unknown --" if pid is None else f"{opp_roster_by_id[pid].player_name}" + (f" (#{opp_roster_by_id[pid].jersey_number})" if opp_roster_by_id[pid].jersey_number else ""),
                                        key="gt_opp_roster_player",
                                    )
                                    if opp_player_choice is not None and opp_roster_by_id[opp_player_choice].bats:
                                        default_hand = opp_roster_by_id[opp_player_choice].bats if opp_roster_by_id[opp_player_choice].bats in ("R", "L") else "R"

                            opp_hand_choice = st.radio("Opposing batter's hand", ["R", "L"], index=0 if default_hand == "R" else 1, horizontal=True, key="gt_opp_batter_hand")
                            if not active_game.is_intrasquad:
                                opp_batting_order_choice = st.number_input("Opponent's batting order #", min_value=1, max_value=12, value=1, step=1, key="gt_opp_order")
                    else:
                        # continuing the same PA -- derived from the last pitch
                        # stored in the DB (robust to a hard refresh), not
                        # session_state.
                        our_player_choice = state.get("current_our_player")
                        opp_hand_choice = state.get("current_opp_hand")
                        opp_batting_order_choice = state.get("current_opp_order")
                        opp_player_choice = state.get("current_opp_player")
                        opp_our_player_choice = state.get("current_opp_our_player")
                        if state["is_our_batting"] and our_player_choice and our_player_choice in players_by_id:
                            st.caption(f"At bat: {players_by_id[our_player_choice].first_name} {players_by_id[our_player_choice].last_name}")

                    if not state["is_our_batting"]:
                        if our_player_choice and our_player_choice in players_by_id:
                            st.markdown(f"**Currently pitching:** {players_by_id[our_player_choice].first_name} {players_by_id[our_player_choice].last_name}")
                        else:
                            st.warning("No pitcher set yet -- set a starting pitcher on the lineup above, or make a pitching change below.")

                        with st.expander("Make a pitching change"):
                            pitcher_candidates = [pid for pid, p in players_by_id.items() if p.is_pitcher]
                            new_pitcher_choice = st.selectbox(
                                "New pitcher",
                                options=pitcher_candidates,
                                format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}",
                                key="gt_pitching_change_choice",
                            )
                            if st.button("Confirm pitching change", key="gt_confirm_pitching_change"):
                                session.add(PitchingChange(
                                    game_id=active_game.game_id,
                                    player_id=new_pitcher_choice,
                                    inning=state["inning"],
                                    outs_at_entry=state["outs"],
                                    pitch_sequence_at_entry=len(active_game.pitches),
                                ))
                                session.commit()
                                st.success(f"{players_by_id[new_pitcher_choice].first_name} {players_by_id[new_pitcher_choice].last_name} is now pitching.")
                                st.rerun()

                with st.container(border=True):
                    st.markdown("**Pitch Details**")
                    arsenal_pitch_type_names = get_arsenal_pitch_type_names(session, our_player_choice, pitch_types) if not state["is_our_batting"] and our_player_choice else [pt.type_name for pt in pitch_types]
                    if st.session_state.get("gt_pitch_type") not in arsenal_pitch_type_names:
                        st.session_state.pop("gt_pitch_type", None)  # stale selection from before a pitching change/different pitcher's arsenal -- avoid crashing the widget
                    pitch_type_choice = st.selectbox("Pitch type", arsenal_pitch_type_names, key="gt_pitch_type")

                    pitch_count_for_key = len(active_game.pitches)  # part of the state/widget keys below, so each new pitch always starts fresh -- a stale click from the last pitch never silently carries over

                    intended_plate_x = intended_plate_z = None
                    if not state["is_our_batting"]:
                        st.caption("Intended location -- click where the pitch was supposed to go")
                        intended_state_key = f"gt_intended_plate_{pitch_count_for_key}"
                        if intended_state_key not in st.session_state:
                            st.session_state[intended_state_key] = (None, None)
                        cur_ix, cur_iz = st.session_state[intended_state_key]
                        new_ix, new_iz = strike_zone.render_zone_selector(
                            key=f"gt_intended_click_{pitch_count_for_key}", marker_x=cur_ix, marker_z=cur_iz,
                        )
                        if new_ix is not None and (new_ix, new_iz) != (cur_ix, cur_iz):
                            st.session_state[intended_state_key] = (new_ix, new_iz)
                            st.rerun()
                        intended_plate_x, intended_plate_z = st.session_state[intended_state_key]
                        st.caption(f"Intended: {intended_plate_x:+.2f} ft, {intended_plate_z:.2f} ft high" if intended_plate_x is not None else "Not yet set -- click the image above.")

                    # Actual location isn't captured live -- pitches are called
                    # from the dugout with no angle on where the ball actually
                    # crossed, so there's nothing real to click in the moment.
                    # It's filled in afterward from center-field game video via
                    # the Video Review section below (per Ryker's call), which
                    # is also where command/execution tracking (intended vs.
                    # actual) actually gets used.
                    actual_plate_x = actual_plate_z = None

                    pitch_outcome_choice = st.selectbox("Pitch outcome", PITCH_OUTCOMES, key="gt_pitch_outcome")
                    contact_quality_choice = None
                    is_sword_choice = False
                    if pitch_outcome_choice in ("In Play", "Foul", "Swing and Miss"):
                        contact_quality_choice = st.selectbox("Contact quality (optional)", ["-- N/A --"] + CONTACT_QUALITY_OPTIONS, key="gt_contact_quality")
                        is_sword_choice = st.checkbox("Sword (ugly, off-balance swing)", key="gt_is_sword")

                    batted_ball_type_choice = None
                    batted_ball_x = batted_ball_y = None
                    if pitch_outcome_choice == "In Play":
                        batted_ball_type_choice = st.selectbox(
                            "Batted ball type (optional)",
                            ["-- N/A --", "Ground Ball", "Line Drive", "Fly Ball", "Pop Up"],
                            key="gt_batted_ball_type",
                        )
                        st.caption("Where did it land? Click the field below.")
                        field_state_key = f"gt_batted_ball_field_{pitch_count_for_key}"
                        if field_state_key not in st.session_state:
                            st.session_state[field_state_key] = (None, None)
                        cur_bx, cur_by = st.session_state[field_state_key]
                        new_bx, new_by = field_location.render_field_selector(
                            key=f"gt_batted_ball_click_{pitch_count_for_key}", marker_x=cur_bx, marker_y=cur_by,
                        )
                        if new_bx is not None and (new_bx, new_by) != (cur_bx, cur_by):
                            st.session_state[field_state_key] = (new_bx, new_by)
                            st.rerun()
                        batted_ball_x, batted_ball_y = st.session_state[field_state_key]
                        if batted_ball_x is not None:
                            dist = field_location.distance_from_plate(batted_ball_x, batted_ball_y)
                            st.caption(f"Landed: {batted_ball_x:+.0f} ft, {batted_ball_y:.0f} ft deep ({dist:.0f} ft from home)")
                        else:
                            st.caption("Not yet set -- click the field above. Optional, but needed for spray charts later.")

                # Determine if this pitch ends the PA
                new_balls = state["balls"] + (1 if pitch_outcome_choice == "Ball" else 0)
                new_strikes = state["strikes"]
                if pitch_outcome_choice in ("Called Strike", "Swing and Miss"):
                    new_strikes += 1
                elif pitch_outcome_choice == "Foul" and new_strikes < 2:
                    new_strikes += 1
                ends_pa = pitch_outcome_choice == "In Play" or pitch_outcome_choice == "HBP" or new_balls >= 4 or (new_strikes >= 3 and pitch_outcome_choice != "Foul")

                ab_outcome_choice = None
                suggested_outs = suggested_bases = suggested_runs = None
                final_outs = final_bases = final_runs = None
                if ends_pa:
                    with st.container(border=True):
                        st.markdown("**Result**")
                        default_ab = "BB" if new_balls >= 4 else ("K" if new_strikes >= 3 else ("HBP" if pitch_outcome_choice == "HBP" else "1B"))
                        ab_outcome_choice = st.selectbox("AB outcome", AB_OUTCOMES, index=AB_OUTCOMES.index(default_ab) if default_ab in AB_OUTCOMES else 0, key="gt_ab_outcome")
                        suggested_outs, suggested_bases, suggested_runs = suggest_after_state(ab_outcome_choice, state["bases"], state["outs"])
                        st.caption("Confirm or adjust the result -- suggested from the AB outcome, but real plays vary.")
                        oc1, oc2, oc3 = st.columns(3)
                        final_outs = oc1.number_input("Outs after", min_value=0, max_value=3, value=min(suggested_outs, 3), step=1, key="gt_final_outs")
                        final_bases = oc2.text_input("Bases after (1st,2nd,3rd = 1/0)", value=suggested_bases, max_chars=3, key="gt_final_bases")
                        final_runs = oc3.number_input("Runs scored on play", min_value=0, max_value=4, value=suggested_runs, step=1, key="gt_final_runs")

                pitch_notes = st.text_input("Notes (optional)", key="gt_pitch_notes")

                if st.button("Record pitch", type="primary", key="gt_record_pitch"):
                    if state["is_our_batting"] and our_player_choice is None:
                        st.error("Select who's batting first.")
                    elif not state["is_our_batting"] and our_player_choice is None:
                        st.error("Select who's pitching first.")
                    else:
                        pitch_type_id = next(pt.pitch_type_id for pt in pitch_types if pt.type_name == pitch_type_choice)
                        cq = contact_quality_choice if contact_quality_choice and contact_quality_choice != "-- N/A --" else None
                        bbt = batted_ball_type_choice if batted_ball_type_choice and batted_ball_type_choice != "-- N/A --" else None
                        next_seq = (max((p.pitch_sequence for p in active_game.pitches), default=0)) + 1

                        re_lookup = build_re_lookup(session)
                        re_before, re_after, run_value = compute_re_and_rv(
                            re_lookup, state["outs"], state["bases"], state["balls"], state["strikes"],
                            ends_pa, final_outs if ends_pa else None, final_bases if ends_pa else None,
                            final_runs if ends_pa else 0, new_balls=new_balls, new_strikes=new_strikes,
                        )

                        session.add(GamePitch(
                            game_id=active_game.game_id,
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
                            intended_zone=strike_zone.derive_old_zone(intended_plate_x, intended_plate_z),
                            pitch_zone=strike_zone.derive_old_zone(actual_plate_x, actual_plate_z),
                            actual_plate_x=actual_plate_x,
                            actual_plate_z=actual_plate_z,
                            intended_plate_x=intended_plate_x,
                            intended_plate_z=intended_plate_z,
                            pitch_outcome=pitch_outcome_choice,
                            contact_quality=cq,
                            is_sword=is_sword_choice,
                            batted_ball_type=bbt,
                            batted_ball_x=batted_ball_x,
                            batted_ball_y=batted_ball_y,
                            ends_plate_appearance=ends_pa,
                            ab_outcome=ab_outcome_choice,
                            outs_after=final_outs if ends_pa else None,
                            bases_after=final_bases if ends_pa else None,
                            runs_scored_on_play=final_runs if ends_pa else 0,
                            re_before=re_before,
                            re_after=re_after,
                            run_value=run_value,
                            notes=pitch_notes.strip() or None,
                        ))
                        if ends_pa and final_runs:
                            if state["is_our_batting"]:
                                active_game.our_score += final_runs
                            else:
                                active_game.opponent_score += final_runs
                        session.commit()

                        # Clear this pitch's Pitch Details/Result/notes
                        # widgets so the next pitch starts blank instead of
                        # carrying over the last one's selections -- easy to
                        # misread as "still recording the same pitch" mid-AB
                        # otherwise. Deliberately NOT touching who's up/who's
                        # pitching (gt_our_batter, gt_opp_our_pitcher,
                        # gt_opp_pitcher_hand, gt_opp_batter_hand,
                        # gt_opp_roster_player, gt_opp_order,
                        # gt_opp_our_batter, gt_pitching_change_choice) --
                        # those should keep remembering the same batter/
                        # pitcher pitch to pitch, and (for our own pitcher)
                        # already do automatically since who's pitching is
                        # derived from PitchingChange/starting_pitcher_id,
                        # not a widget, so it only changes via an explicit
                        # pitching change.
                        for stale_key in (
                            "gt_pitch_type", "gt_pitch_outcome", "gt_contact_quality",
                            "gt_is_sword", "gt_batted_ball_type", "gt_pitch_notes",
                            "gt_ab_outcome", "gt_final_outs", "gt_final_bases", "gt_final_runs",
                        ):
                            st.session_state.pop(stale_key, None)

                        st.success("Pitch recorded.")
                        st.rerun()
            elif can_edit_sessions and active_game.status == "Scheduled":
                st.info("This game hasn't started yet -- click \"Start game\" on the Manage Game tab to begin live tracking.")
            elif can_edit_sessions and active_game.status == "Paused":
                st.info("This game is paused -- click \"Resume game\" on the Manage Game tab to continue tracking.")
            elif can_edit_sessions:
                st.caption(f"Live tracking isn't active for a {active_game.status.lower()} game.")
            else:
                st.caption("Live tracking status is only shown for edit-enabled roles today.")

        with tab_video:
            if can_edit_sessions:
                # --- Pitch Video: bulk-upload clips downloaded from a
                # camera (e.g. one clip per pitch) and match each one to
                # the actual pitch it belongs to. "Upload now, match
                # later" -- same pattern already proven on Video Review's
                # pitcher bulk-upload (Assessment/Video tables), here
                # against GameVideoClip/GamePitch instead. Matching just
                # copies the clip's video_url onto the chosen GamePitch
                # and records the match, so GamePitch.video_url stays the
                # one field every other page/report reads from. Covers
                # BOTH sides of the ball (our batting and our pitching) --
                # not scoped to pitches we threw, unlike the
                # location-marking section below. ---
                all_game_pitches_sorted = sorted(active_game.pitches, key=lambda p: p.pitch_sequence)
                if all_game_pitches_sorted:
                    st.subheader("Pitch Video")
                    st.caption(
                        "Upload clips downloaded from your camera -- if it already exports one clip per "
                        "pitch, upload them together and GBO will suggest a match to this game's pitches "
                        "in order below, which you can review and adjust before confirming."
                    )
                    with st.form(f"gt_video_upload_{active_game.game_id}"):
                        video_files = st.file_uploader(
                            "Video files", type=["mp4", "mov", "m4v"], accept_multiple_files=True,
                            key="gt_video_upload_files",
                        )
                        video_upload_submitted = st.form_submit_button("Upload", type="primary")

                    if video_upload_submitted:
                        if not video_files:
                            st.error("Choose at least one video file first.")
                        else:
                            progress = st.progress(0.0, text="Uploading...")
                            uploaded_count = 0
                            for i, f in enumerate(video_files):
                                identifier = f"game-{active_game.game_id}-{uuid.uuid4().hex[:8]}"
                                url = upload_game_video_clip(f, identifier)
                                if url:
                                    session.add(GameVideoClip(game_id=active_game.game_id, video_url=url, original_filename=f.name))
                                    uploaded_count += 1
                                progress.progress((i + 1) / len(video_files), text=f"Uploading... {i + 1}/{len(video_files)}")
                            session.commit()
                            progress.empty()
                            st.success(f"Uploaded {uploaded_count} clip(s). Match them to pitches below.")
                            st.rerun()

                    unmatched_clips = (
                        session.query(GameVideoClip)
                        .filter(GameVideoClip.game_id == active_game.game_id, GameVideoClip.matched_game_pitch_id.is_(None))
                        .order_by(GameVideoClip.uploaded_at, GameVideoClip.game_video_clip_id)
                        .all()
                    )
                    matched_clip_count = (
                        session.query(GameVideoClip)
                        .filter(GameVideoClip.game_id == active_game.game_id, GameVideoClip.matched_game_pitch_id.isnot(None))
                        .count()
                    )
                    if matched_clip_count or unmatched_clips:
                        st.caption(f"{matched_clip_count} clip(s) matched, {len(unmatched_clips)} still need matching.")

                    if unmatched_clips:
                        with st.expander(f"Match uploaded clips to pitches ({len(unmatched_clips)} pending)", expanded=True):
                            # Candidate pitches: this game's pitches that don't
                            # already have video, in pitch order -- since the
                            # camera already exports one clip per pitch,
                            # sequential order is the natural default match,
                            # always reviewed/adjustable per clip below rather
                            # than assumed blindly.
                            candidate_pitches = [p for p in all_game_pitches_sorted if p.video_url is None]
                            if not candidate_pitches:
                                st.caption("Every pitch in this game already has video -- nothing left to match these clips to.")
                            else:
                                candidates_by_id = {p.game_pitch_id: p for p in candidate_pitches}

                                def _pitch_match_label(gpid):
                                    p = candidates_by_id[gpid]
                                    side = "Us pitching" if not p.is_our_team_batting else "Us batting"
                                    pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                                    return f"#{p.pitch_sequence} — Inn {p.inning}, {side}, {p.balls_before}-{p.strikes_before}, {pt_name}, {p.pitch_outcome or '—'}"

                                for idx, clip in enumerate(unmatched_clips):
                                    suggested_gpid = candidate_pitches[idx].game_pitch_id if idx < len(candidate_pitches) else candidate_pitches[0].game_pitch_id
                                    match_options = list(candidates_by_id.keys())
                                    default_index = match_options.index(suggested_gpid) if suggested_gpid in match_options else 0
                                    mcol1, mcol2, mcol3 = st.columns([2, 4, 1])
                                    mcol1.markdown(clip.original_filename or "Clip")
                                    match_choice = mcol2.selectbox(
                                        f"Match clip {clip.game_video_clip_id}", options=match_options, index=default_index,
                                        format_func=_pitch_match_label,
                                        key=f"gt_match_clip_{clip.game_video_clip_id}", label_visibility="collapsed",
                                    )
                                    if mcol3.button("Link", key=f"gt_match_clip_btn_{clip.game_video_clip_id}"):
                                        matched_pitch = candidates_by_id[match_choice]
                                        clip.matched_game_pitch_id = match_choice
                                        matched_pitch.video_url = clip.video_url
                                        session.commit()
                                        st.success(f"Linked {clip.original_filename or 'clip'} to pitch #{matched_pitch.pitch_sequence}.")
                                        st.rerun()
                else:
                    empty_state("No pitches logged yet in this game to attach video to.")

                st.divider()

            # --- Video Review: fill in actual pitch locations from game
            # film -- the other half of command/execution tracking, now that
            # actual location is never captured live (see the note above the
            # removed live click block). Scoped to pitches WE threw
            # (is_our_team_batting is False) -- same scoping the live
            # intended-location capture already used, since there's no call
            # (and so no intended location) to grade for pitches we didn't
            # throw. Works at any game status, since this is done after the
            # fact from film, not during live entry. ---
            pitches_we_threw = sorted(
                (p for p in active_game.pitches if not p.is_our_team_batting),
                key=lambda p: p.pitch_sequence,
            )
            if can_edit_sessions and pitches_we_threw:
                st.subheader("Video Review — Actual Pitch Locations")
                st.caption(
                    "Step through the pitches we threw and mark where each one actually crossed, "
                    "watching the center-field angle (or the matched clip below, if there is one). "
                    "Paired with the call/intended location from the dugout, this is what drives "
                    "command/execution tracking."
                )

                review_pitch_ids = [p.game_pitch_id for p in pitches_we_threw]
                missing_ids = [p.game_pitch_id for p in pitches_we_threw if p.actual_plate_x is None]

                # Reset to the first un-reviewed pitch whenever a different
                # game becomes active (including the very first time this
                # section renders) -- avoids picking up a stale pitch id left
                # over from a previously-reviewed game.
                if st.session_state.get("vr_active_game_id") != active_game.game_id:
                    st.session_state["vr_active_game_id"] = active_game.game_id
                    st.session_state["vr_current_pitch_id"] = missing_ids[0] if missing_ids else review_pitch_ids[0]

                current_pitch_id = st.session_state.get("vr_current_pitch_id")
                if current_pitch_id not in review_pitch_ids:
                    current_pitch_id = review_pitch_ids[0]
                    st.session_state["vr_current_pitch_id"] = current_pitch_id
                current_idx = review_pitch_ids.index(current_pitch_id)
                current_pitch = pitches_we_threw[current_idx]

                def _vr_pitch_label(gpid):
                    p = next(pp for pp in pitches_we_threw if pp.game_pitch_id == gpid)
                    mark = "✓" if p.actual_plate_x is not None else "•"
                    pt_name = p.pitch_type.type_name if p.pitch_type else "?"
                    video_tag = " [video]" if p.video_url else ""
                    return f"{mark} #{p.pitch_sequence} — Inn {p.inning}, {p.balls_before}-{p.strikes_before}, {pt_name}{video_tag}"

                st.caption(f"{len(missing_ids)} of {len(pitches_we_threw)} pitch(es) we threw still need an actual location.")
                jump_choice = st.selectbox(
                    "Jump to pitch", options=review_pitch_ids, index=current_idx,
                    format_func=_vr_pitch_label, key="vr_jump_select",
                )
                if jump_choice != current_pitch_id:
                    st.session_state["vr_current_pitch_id"] = jump_choice
                    st.rerun()

                batter_label = (
                    (f"{current_pitch.opponent_our_player.first_name} {current_pitch.opponent_our_player.last_name}" if current_pitch.opponent_our_player else None)
                    or (current_pitch.opponent_player.player_name if current_pitch.opponent_player else None)
                    or (f"batting order #{current_pitch.opponent_batting_order}" if current_pitch.opponent_batting_order else "unknown batter")
                )
                hand_label = f" ({current_pitch.opponent_hand}HB)" if current_pitch.opponent_hand else ""
                st.markdown(
                    f"**Pitch #{current_pitch.pitch_sequence}** — Inning {current_pitch.inning}, "
                    f"{current_pitch.balls_before}-{current_pitch.strikes_before} count, "
                    f"vs. {batter_label}{hand_label}"
                )
                st.caption(
                    f"Called: {current_pitch.pitch_type.type_name if current_pitch.pitch_type else 'unknown pitch'}"
                    + (
                        f" — intended {float(current_pitch.intended_plate_x):+.2f} ft, {float(current_pitch.intended_plate_z):.2f} ft high"
                        if current_pitch.intended_plate_x is not None else " — no intended location was logged live"
                    )
                    + f". Outcome: {current_pitch.pitch_outcome or '—'}" + (f", {current_pitch.ab_outcome}" if current_pitch.ab_outcome else "")
                )

                if current_pitch.video_url:
                    st.video(current_pitch.video_url)

                vr_state_key = f"vr_actual_state_{current_pitch.game_pitch_id}"
                if vr_state_key not in st.session_state:
                    st.session_state[vr_state_key] = (
                        float(current_pitch.actual_plate_x) if current_pitch.actual_plate_x is not None else None,
                        float(current_pitch.actual_plate_z) if current_pitch.actual_plate_z is not None else None,
                    )
                cur_vx, cur_vz = st.session_state[vr_state_key]
                new_vx, new_vz = strike_zone.render_zone_selector(
                    key=f"vr_actual_click_{current_pitch.game_pitch_id}", marker_x=cur_vx, marker_z=cur_vz,
                )
                if new_vx is not None and (new_vx, new_vz) != (cur_vx, cur_vz):
                    st.session_state[vr_state_key] = (new_vx, new_vz)
                    st.rerun()
                review_x, review_z = st.session_state[vr_state_key]
                if review_x is not None:
                    located = strike_zone.is_in_zone(review_x, review_z)
                    st.caption(f"Marked: {review_x:+.2f} ft, {review_z:.2f} ft high — {'In zone' if located else 'Out of zone'}")
                else:
                    st.caption("Not yet marked -- click the image above.")

                nav_cols = st.columns(3)
                if nav_cols[0].button("◀ Previous", key="vr_prev_btn", disabled=current_idx == 0):
                    st.session_state["vr_current_pitch_id"] = review_pitch_ids[current_idx - 1]
                    st.rerun()
                if nav_cols[2].button("Next ▶", key="vr_next_btn", disabled=current_idx == len(review_pitch_ids) - 1):
                    st.session_state["vr_current_pitch_id"] = review_pitch_ids[current_idx + 1]
                    st.rerun()
                if nav_cols[1].button("Save actual location", type="primary", key="vr_save_btn", disabled=review_x is None):
                    current_pitch.actual_plate_x = review_x
                    current_pitch.actual_plate_z = review_z
                    current_pitch.pitch_zone = strike_zone.derive_old_zone(review_x, review_z)
                    session.commit()
                    st.session_state.pop(vr_state_key, None)
                    # Advance to the next still-missing pitch after this one
                    # in sequence (wrapping back to the first remaining one),
                    # or just the next pitch overall once nothing's missing.
                    still_missing = [p.game_pitch_id for p in pitches_we_threw if p.actual_plate_x is None]
                    later_missing = [gpid for gpid in still_missing if review_pitch_ids.index(gpid) > current_idx]
                    if later_missing:
                        st.session_state["vr_current_pitch_id"] = later_missing[0]
                    elif still_missing:
                        st.session_state["vr_current_pitch_id"] = still_missing[0]
                    else:
                        st.session_state["vr_current_pitch_id"] = review_pitch_ids[min(current_idx + 1, len(review_pitch_ids) - 1)]
                    st.success(f"Saved actual location for pitch #{current_pitch.pitch_sequence}.")
                    st.rerun()
            elif can_edit_sessions:
                empty_state("No pitches thrown yet in this game to review.")
            else:
                st.caption("Video Review is only available to edit-enabled roles.")

        with tab_log:
            # --- Pitch log ---
            st.subheader("Pitch log")
            all_pitches = sorted(active_game.pitches, key=lambda p: p.pitch_sequence, reverse=True)
            if not all_pitches:
                empty_state("No pitches logged yet for this game.")
            else:
                st.dataframe(
                    [
                        {
                            "#": p.pitch_sequence,
                            "Inn": p.inning,
                            "Side": "Us batting" if p.is_our_team_batting else "Us pitching",
                            "Player": f"{p.our_player.first_name} {p.our_player.last_name}" if p.our_player else "—",
                            "Opponent": (f"{p.opponent_our_player.first_name} {p.opponent_our_player.last_name}" if p.opponent_our_player else None) or (f"{p.opponent_player.player_name}" if p.opponent_player else None) or (f"#{p.opponent_batting_order} ({p.opponent_hand})" if p.opponent_batting_order else "—"),
                            "Pitch": p.pitch_type.type_name if p.pitch_type else "—",
                            "Location": f"{float(p.actual_plate_x):+.2f}, {float(p.actual_plate_z):.2f}" if p.actual_plate_x is not None else "—",
                            "Video": "✓" if p.video_url else "—",
                            "Outcome": (p.pitch_outcome or "—") + (" (Sword)" if p.is_sword else ""),
                            "Batted Ball": (p.batted_ball_type or "") + (f" ({float(p.batted_ball_x):+.0f}, {float(p.batted_ball_y):.0f})" if p.batted_ball_x is not None else "") if (p.batted_ball_type or p.batted_ball_x is not None) else "—",
                            "AB Result": p.ab_outcome or "",
                            "Runs": p.runs_scored_on_play,
                            "RE Before": f"{float(p.re_before):.2f}" if p.re_before is not None else "—",
                            "RE After": f"{float(p.re_after):.2f}" if p.re_after is not None else "—",
                            "RV": f"{float(p.run_value):+.3f}" if p.run_value is not None else "—",
                        }
                        for p in all_pitches[:50]
                    ],
                    use_container_width=True, hide_index=True,
                )

        with tab_manage:
            if can_edit_sessions and active_game.status not in ("Final", "Cancelled"):
                st.caption(f"Status: {active_game.status}")
                status_cols = st.columns(4)
                if active_game.status == "Scheduled":
                    if status_cols[0].button("Start game", type="primary"):
                        active_game.status = "In Progress"
                        session.commit()
                        st.success("Game started.")
                        st.rerun()
                if active_game.status == "In Progress":
                    if status_cols[0].button("Pause game"):
                        active_game.status = "Paused"
                        session.commit()
                        st.success("Game paused.")
                        st.rerun()
                    if status_cols[1].button("Mark game Final", type="primary"):
                        active_game.status = "Final"
                        session.commit()
                        st.success("Game marked Final.")
                        st.rerun()
                if active_game.status == "Paused":
                    if status_cols[0].button("Resume game", type="primary"):
                        active_game.status = "In Progress"
                        session.commit()
                        st.success("Game resumed.")
                        st.rerun()
                    if status_cols[1].button("Mark game Final"):
                        active_game.status = "Final"
                        session.commit()
                        st.success("Game marked Final.")
                        st.rerun()
                if status_cols[2].button("Cancel game"):
                    active_game.status = "Cancelled"
                    session.commit()
                    st.success("Game cancelled.")
                    st.rerun()
            elif can_edit_sessions:
                st.caption(f"Status: {active_game.status} (no further status changes available).")

            if can_edit_sessions:
                with st.expander("Delete this game"):
                    st.warning(f"This permanently deletes this game and all {len(active_game.pitches)} pitch(es) logged in it. This can't be undone.")
                    confirm_delete = st.checkbox("Yes, I want to permanently delete this game", key=f"confirm_delete_game_{active_game.game_id}")
                    if st.button("Delete game", key=f"delete_game_{active_game.game_id}", disabled=not confirm_delete, type="primary"):
                        deleted_id = active_game.game_id
                        session.delete(active_game)
                        session.commit()
                        _set_active_game(None)
                        st.success(f"Deleted game #{deleted_id}.")
                        st.rerun()
            else:
                st.caption("Game management is only available to edit-enabled roles.")

finally:
    session.close()

page_footer()