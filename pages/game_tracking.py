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
"""

import streamlit as st
from datetime import date
from sqlalchemy.orm import joinedload

from database import get_session
from models import (
    Player, Position, PitchType, Game, GameLineupSlot, GamePitch, RunExpectancy,
)
from ui_components import page_header, page_footer, empty_state

page_header("Game Tracking")

current_user_id = st.session_state.get("gbo_user_id")
role_name = st.session_state.get("gbo_role_name")
can_edit_sessions = st.session_state.get("gbo_can_edit_sessions", False)

if current_user_id is None:
    st.error("Session expired. Please log in again from the main page.")
    page_footer()
    st.stop()

if role_name not in ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst"):
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

PITCH_OUTCOMES = ["Ball", "Called Strike", "Swinging Strike", "Foul", "In Play", "HBP"]
AB_OUTCOMES = [
    "K", "BB", "HBP", "1B", "2B", "3B", "HR", "E", "FC",
    "Sac Bunt", "Sac Fly", "Groundout", "Flyout", "Lineout", "Double Play",
]
ZONE_LABELS = {
    0: "Bury (in the dirt)",
    1: "Up-Left", 2: "Up-Middle", 3: "Up-Right",
    4: "Middle-Left", 5: "Middle-Middle", 6: "Middle-Right",
    7: "Down-Left", 8: "Down-Middle", 9: "Down-Right",
}
CONTACT_QUALITY_OPTIONS = ["Barrel", "Solid", "Weak", "Miss"]


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
        since a Ball, Called Strike, Swinging Strike, and Foul all
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
        if last.pitch_outcome in ("Called Strike", "Swinging Strike"):
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
    games = (
        session.query(Game)
        .order_by(Game.game_date.desc())
        .all()
    )
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

    def _game_label(gid):
        if gid is None:
            return "-- Start a new game --"
        g = games_by_id[gid]
        loc = "vs" if g.is_home else ("@" if g.is_home is False else "vs (neutral)")
        return f"{g.game_date.strftime('%Y-%m-%d (%a)')} — {loc} {g.opponent_name} ({g.status}) — {g.our_score}-{g.opponent_score}"

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

    if active_game_id is None and can_edit_sessions:
        st.subheader("Start a new game")
        with st.form("new_game_form"):
            opponent_name = st.text_input("Opponent")
            game_date_input = st.date_input("Date", value=date.today())
            location_choice = st.selectbox("Location", ["Home", "Away", "Neutral site"])
            new_game_submitted = st.form_submit_button("Create game", type="primary")

        if new_game_submitted:
            if not opponent_name.strip():
                st.error("Opponent name is required.")
            else:
                is_home = {"Home": True, "Away": False, "Neutral site": None}[location_choice]
                new_game = Game(
                    opponent_name=opponent_name.strip(),
                    game_date=game_date_input,
                    is_home=is_home,
                    created_by_user_id=current_user_id,
                )
                session.add(new_game)
                session.commit()
                _set_active_game(new_game.game_id)
                st.success(f"Created game vs {opponent_name.strip()}.")
                st.rerun()
    elif active_game_id is None:
        st.info("Your role has read-only access to game tracking.")

    if active_game:
        st.divider()
        loc = "vs" if active_game.is_home else ("@" if active_game.is_home is False else "vs (neutral)")
        st.markdown(f"### {loc} {active_game.opponent_name} — {active_game.game_date.strftime('%Y-%m-%d (%a)')}")
        st.markdown(f"**Score: {active_game.our_score} - {active_game.opponent_score}** ({active_game.status})")

        lineup_slots = session.query(GameLineupSlot).options(joinedload(GameLineupSlot.player)).filter(GameLineupSlot.game_id == active_game.game_id).order_by(GameLineupSlot.batting_order).all()

        # --- Lineup setup ---
        if not lineup_slots and can_edit_sessions:
            st.subheader("Set lineup")
            st.caption("9 batting order slots + starting pitcher. You can still track the game without a full lineup -- this just makes the batter picker faster.")
            with st.form("lineup_form"):
                slot_choices = {}
                for i in range(1, 10):
                    cols = st.columns([1, 3, 2])
                    cols[0].markdown(f"**{i}.**")
                    player_choice = cols[1].selectbox(f"Batter {i}", options=[None] + list(players_by_id.keys()), format_func=lambda pid: "-- Select --" if pid is None else f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}", key=f"lineup_player_{i}", label_visibility="collapsed")
                    position_choice = cols[2].selectbox(f"Position {i}", options=[None] + [p.position_id for p in positions], format_func=lambda pid: "-- Position --" if pid is None else next(p.position_name for p in positions if p.position_id == pid), key=f"lineup_pos_{i}", label_visibility="collapsed")
                    slot_choices[i] = (player_choice, position_choice)
                starting_pitcher_choice = st.selectbox("Starting pitcher", options=[None] + list(players_by_id.keys()), format_func=lambda pid: "-- Select --" if pid is None else f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}")
                lineup_submitted = st.form_submit_button("Save lineup", type="primary")

            if lineup_submitted:
                added = 0
                for i, (player_choice, position_choice) in slot_choices.items():
                    if player_choice is not None:
                        session.add(GameLineupSlot(game_id=active_game.game_id, batting_order=i, player_id=player_choice, starting_position_id=position_choice))
                        added += 1
                active_game.starting_pitcher_id = starting_pitcher_choice
                session.commit()
                st.success(f"Saved lineup ({added} batters).")
                st.rerun()

        elif lineup_slots:
            with st.expander("Lineup"):
                st.dataframe(
                    [
                        {"#": s.batting_order, "Player": f"{s.player.first_name} {s.player.last_name}" if s.player else "—", "Position": s.starting_position.position_name if s.starting_position else "—"}
                        for s in lineup_slots
                    ],
                    use_container_width=True, hide_index=True,
                )
                if active_game.starting_pitcher_id and active_game.starting_pitcher_id in players_by_id:
                    p = players_by_id[active_game.starting_pitcher_id]
                    st.caption(f"Starting pitcher: {p.first_name} {p.last_name}")

        # --- Live pitch entry ---
        if can_edit_sessions:
            state = compute_current_state(active_game, lineup_slots)

            st.divider()
            half_label = "We're batting" if state["is_our_batting"] else "We're pitching"
            st.subheader(f"Inning {state['inning']} — {half_label}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Outs", state["outs"])
            c2.metric("Count", f"{state['balls']}-{state['strikes']}")
            c3.metric("Runners", bases_display(state["bases"]))

            if state["outs"] >= 3:
                st.warning("3 outs reached but the inning hasn't advanced yet -- this shouldn't normally happen; check the last pitch logged.")

            # Who's up this PA
            our_player_choice = None
            opp_hand_choice = None
            opp_batting_order_choice = None
            if state["new_pa"]:
                st.caption("New plate appearance -- who's up?")
                if state["is_our_batting"]:
                    lineup_player_ids = [s.player_id for s in lineup_slots] if lineup_slots else list(players_by_id.keys())
                    our_player_choice = st.selectbox("Our batter", options=lineup_player_ids, format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}", key="gt_our_batter")
                    opp_hand_choice = st.radio("Opposing pitcher's hand", ["R", "L"], horizontal=True, key="gt_opp_pitcher_hand")
                else:
                    pitcher_options = list(players_by_id.keys())
                    default_pitcher_idx = pitcher_options.index(active_game.starting_pitcher_id) if active_game.starting_pitcher_id in pitcher_options else 0
                    our_player_choice = st.selectbox("Our pitcher", options=pitcher_options, index=default_pitcher_idx, format_func=lambda pid: f"{players_by_id[pid].first_name} {players_by_id[pid].last_name}", key="gt_our_pitcher")
                    opp_hand_choice = st.radio("Opposing batter's hand", ["R", "L"], horizontal=True, key="gt_opp_batter_hand")
                    opp_batting_order_choice = st.number_input("Opponent's batting order #", min_value=1, max_value=12, value=1, step=1, key="gt_opp_order")
            else:
                # continuing the same PA -- derived from the last pitch
                # stored in the DB (robust to a hard refresh), not
                # session_state.
                our_player_choice = state.get("current_our_player")
                opp_hand_choice = state.get("current_opp_hand")
                opp_batting_order_choice = state.get("current_opp_order")
                if our_player_choice and our_player_choice in players_by_id:
                    st.caption(f"At bat: {players_by_id[our_player_choice].first_name} {players_by_id[our_player_choice].last_name}")

            st.divider()
            pitch_type_choice = st.selectbox("Pitch type", [pt.type_name for pt in pitch_types], key="gt_pitch_type")

            zone_choice = None
            if not state["is_our_batting"]:
                st.caption("Intended zone")
                if "gt_intended_zone" not in st.session_state:
                    st.session_state.gt_intended_zone = 5
                zone_layout = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
                for row in zone_layout:
                    cols = st.columns(3)
                    for i, zone in enumerate(row):
                        is_selected = st.session_state.gt_intended_zone == zone
                        label = f"● {zone}" if is_selected else str(zone)
                        if cols[i].button(label, key=f"gt_zone_btn_{zone}", use_container_width=True):
                            st.session_state.gt_intended_zone = zone
                            st.rerun()
                if st.button("Bury (in the dirt)", key="gt_zone_btn_bury", use_container_width=True):
                    st.session_state.gt_intended_zone = 0
                    st.rerun()
                st.caption(f"Selected: {st.session_state.gt_intended_zone} ({ZONE_LABELS[st.session_state.gt_intended_zone]})")
                zone_choice = st.session_state.gt_intended_zone

            pitch_outcome_choice = st.selectbox("Pitch outcome", PITCH_OUTCOMES, key="gt_pitch_outcome")
            contact_quality_choice = None
            if pitch_outcome_choice in ("In Play", "Foul", "Swinging Strike"):
                contact_quality_choice = st.selectbox("Contact quality (optional)", ["-- N/A --"] + CONTACT_QUALITY_OPTIONS, key="gt_contact_quality")

            # Determine if this pitch ends the PA
            new_balls = state["balls"] + (1 if pitch_outcome_choice == "Ball" else 0)
            new_strikes = state["strikes"]
            if pitch_outcome_choice in ("Called Strike", "Swinging Strike"):
                new_strikes += 1
            elif pitch_outcome_choice == "Foul" and new_strikes < 2:
                new_strikes += 1
            ends_pa = pitch_outcome_choice == "In Play" or pitch_outcome_choice == "HBP" or new_balls >= 4 or (new_strikes >= 3 and pitch_outcome_choice != "Foul")

            ab_outcome_choice = None
            suggested_outs = suggested_bases = suggested_runs = None
            final_outs = final_bases = final_runs = None
            if ends_pa:
                st.divider()
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
                        pa_pitch_number=state["pa_pitch_number"],
                        balls_before=state["balls"],
                        strikes_before=state["strikes"],
                        outs_before=state["outs"],
                        bases_before=state["bases"],
                        pitch_type_id=pitch_type_id,
                        intended_zone=zone_choice,
                        pitch_outcome=pitch_outcome_choice,
                        contact_quality=cq,
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
                    st.success("Pitch recorded.")
                    st.rerun()

        # --- Pitch log ---
        st.divider()
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
                        "Pitch": p.pitch_type.type_name if p.pitch_type else "—",
                        "Outcome": p.pitch_outcome or "—",
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

        if can_edit_sessions and active_game.status == "In Progress":
            if st.button("Mark game Final", type="primary"):
                active_game.status = "Final"
                session.commit()
                st.success("Game marked Final.")
                st.rerun()

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

finally:
    session.close()

page_footer()