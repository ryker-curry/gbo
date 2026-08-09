"""
GBO — Rapsodo CSV Import (Pitcher-Specific assessments).

Bulk-imports pitch-by-pitch Rapsodo 2.0 exports instead of manual entry.
Each row in the CSV becomes one Assessment record (category =
Pitcher-Specific) with its mapped AssessmentResult values -- so a
3,000-pitch export becomes 3,000 assessment records, one per pitch,
which the existing history table already handles fine.

Players are matched by exact "First Last" name against the roster.
Unmatched names are reported, not imported -- add the player first,
then re-import (already-imported rows are not re-duplicated by
Unique_ID tracking... actually not tracked in MVP -- re-importing the
same file twice will create duplicates. Flagged as a known limitation).

Column mapping has pre-filled best guesses for the columns I'm
confident about (Velocity, Total_Spin -> Spin Rate, Spin_Efficiency,
Spin_Direction -> Spin Axis via clock-to-degrees conversion,
Release_Extension/Height/Side, VB_(spin)/HB_(spin) -> Induced Vertical
Break/Horizontal Break). Ambiguous ones (trajectory-based break,
release-point angles vs. plate-crossing approach angles, strike zone
side/height vs. plate side/height) are left unmapped by default --
verify and pick manually if you want them included.

"Who is this for?" (player, optional bullpen session) is asked BEFORE
the file upload -- none of that depends on the CSV's contents, and
Ryker specifically wanted to pick the session before uploading rather
than after.
"""

import streamlit as st
from ui_components import page_header, page_footer
import pandas as pd
from datetime import datetime

from database import get_session
from models import Player, AssessmentCategory, AssessmentTestType, Assessment, AssessmentResult, PitchType, BullpenSession, BullpenPitch

page_header("Import Rapsodo Data")

role_name = st.session_state.get("gbo_role_name")
current_user_id = st.session_state.get("gbo_user_id")
can_edit_assessments = st.session_state.get("gbo_can_edit_assessments", False)

if not can_edit_assessments:
    st.error("Your role doesn't have edit access to assessments.")
    page_footer()
    st.stop()

if role_name == "Coach" and st.session_state.get("gbo_coach_specialty") == "Hitting":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

# Best-guess default column mappings: test_name -> likely Rapsodo column name.
# "-- Skip --" default for anything ambiguous -- verify these before relying on them.
DEFAULT_GUESSES = {
    "Velocity": "Velocity",
    "Spin Rate": "Total_Spin",
    "Spin Efficiency": "Spin_Efficiency",
    "Spin Axis": "Spin_Direction",  # clock format -> converted to degrees
    "Extension": "Release_Extension",
    "Release Height": "Release_Height",
    "Release Side": "Release_Side",
    "Induced Vertical Break": "VB_(spin)",
    "Horizontal Break": "HB_(spin)",
    "Vertical Approach Angle": None,
    "Horizontal Approach Angle": None,
    "Plate Height": None,
    "Plate Side": None,
}

# Rapsodo pitch type label -> our PitchType lookup name
PITCH_TYPE_MAP = {
    "fastball": "4-Seam Fastball",
    "twoseamfastball": "2-Seam Fastball",
    "changeup": "Changeup",
    "curveball": "Curveball",
    "slider": "Slider",
    "cutter": "Cutter",
    "splitter": "Splitter",
}


def clock_to_degrees(clock_str: str):
    """'10:26' -> degrees (0-360), treating 12:00 as 0 degrees."""
    try:
        hours, minutes = clock_str.strip().split(":")
        hours, minutes = int(hours) % 12, int(minutes)
        return round(((hours + minutes / 60) / 12) * 360, 1)
    except Exception:
        return None


def parse_float(val):
    try:
        if val is None or str(val).strip() in ("", "-"):
            return None
        return float(val)
    except (ValueError, TypeError):
        return None


session = get_session()
try:
    category = session.query(AssessmentCategory).filter(AssessmentCategory.category_name == "Pitcher-Specific").first()
    if category is None:
        st.error("Pitcher-Specific category not found -- run migrate_pitcher_specific.py first.")
        page_footer()
        st.stop()

    test_types = session.query(AssessmentTestType).filter(AssessmentTestType.category_id == category.category_id).all()
    test_types_by_name = {t.test_name: t for t in test_types}

    # Pitchers only -- this page is specifically Pitcher-Specific data.
    # Includes inactive pitchers too (not just active), matching the
    # same philosophy as Assessments' own entry form -- a coach may
    # still need to import historical Rapsodo data for a prior-year
    # pitcher who's since been marked inactive.
    roster = session.query(Player).filter(Player.is_pitcher.is_(True)).order_by(Player.active.desc(), Player.last_name, Player.first_name).all()
    roster_by_name = {f"{p.first_name} {p.last_name}".strip().lower(): p for p in roster}

    # --- Who is this for? (asked before upload -- doesn't need the CSV) ---
    st.subheader("Who is this data for?")
    single_player_mode = st.checkbox(
        "This file is for one player only (assign every row to them, skip name matching)",
        value=True,
    )

    single_player_id = None
    single_player_bullpen_id = None
    if single_player_mode:
        if not roster:
            st.warning("No pitchers on the roster yet -- add one first from the Players page (make sure \"Pitcher\" is checked).")
            page_footer()
            st.stop()
        roster_by_id = {p.player_id: p for p in roster}
        single_player_id = st.selectbox(
            "Player",
            options=list(roster_by_id.keys()),
            format_func=lambda pid: f"{roster_by_id[pid].first_name} {roster_by_id[pid].last_name}" + ("" if roster_by_id[pid].active else " (Inactive / prior roster)"),
        )

        # Only offer this to roles that can actually reach Bullpen
        # Tracking to do the linking -- no point sending someone to a
        # page they don't have access to.
        if role_name in ("Administrator", "Head Coach", "Coach"):
            unlinked_bullpens = (
                session.query(BullpenSession)
                .join(BullpenSession.pitches)
                .filter(BullpenSession.player_id == single_player_id, BullpenPitch.linked_assessment_id.is_(None))
                .distinct()
                .order_by(BullpenSession.session_date.desc())
                .all()
            )
            if unlinked_bullpens:
                bullpens_by_id = {b.bullpen_id: b for b in unlinked_bullpens}
                single_player_bullpen_id = st.selectbox(
                    "Is this for a specific bullpen session? (optional)",
                    options=[None] + list(bullpens_by_id.keys()),
                    format_func=lambda bid: "-- Not tied to a bullpen session --" if bid is None else (
                        f"{bullpens_by_id[bid].session_date.strftime('%Y-%m-%d (%a)')} — {bullpens_by_id[bid].bullpen_type.type_name if bullpens_by_id[bid].bullpen_type else '—'}"
                    ),
                )
                if single_player_bullpen_id is not None:
                    st.caption("After importing, you'll get a shortcut straight to linking these pitches on Bullpen Tracking.")

    st.divider()
    uploaded_file = st.file_uploader("Upload Rapsodo CSV export", type=["csv"])

    if uploaded_file is None:
        st.info("Upload a Rapsodo 2.0 CSV export to continue.")
        page_footer()
        st.stop()

    df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    csv_columns = list(df.columns)

    st.success(f"Loaded {len(df)} pitches from the file.")

    if not single_player_mode:
        # --- Match players by name (for multi-player files) -- needs the CSV, so this stays here ---
        csv_names = df["Player_Name"].dropna().unique() if "Player_Name" in df.columns else []
        matched_names = [n for n in csv_names if n.strip().lower() in roster_by_name]
        unmatched_names = [n for n in csv_names if n.strip().lower() not in roster_by_name]

        st.write(f"**{len(matched_names)} of {len(csv_names)} player names matched your roster.**")
        if unmatched_names:
            st.warning(
                "These names in the file don't match anyone on your roster -- their pitches will be "
                "skipped unless you add them first, or fix the name in the CSV to match exactly:\n\n"
                + ", ".join(sorted(unmatched_names))
            )

    st.divider()
    st.subheader("Column mapping")
    st.caption("Verify these before importing -- pre-filled guesses aren't all certain (see notes in the code/README).")

    column_options = ["-- Skip --"] + csv_columns
    mapping = {}
    for test_name in test_types_by_name:
        default = DEFAULT_GUESSES.get(test_name)
        default_idx = column_options.index(default) if default and default in column_options else 0
        mapping[test_name] = st.selectbox(f"{test_name}", column_options, index=default_idx, key=f"map_{test_name}")

    date_col_guess = "Date" if "Date" in csv_columns else column_options[0]
    date_col = st.selectbox("Date column", column_options, index=column_options.index(date_col_guess) if date_col_guess in column_options else 0)
    pitch_type_col_guess = "Pitch_Type" if "Pitch_Type" in csv_columns else column_options[0]
    pitch_type_col = st.selectbox("Pitch Type column", column_options, index=column_options.index(pitch_type_col_guess) if pitch_type_col_guess in column_options else 0)

    player_name_col = "-- Skip --"
    if not single_player_mode:
        player_name_col_guess = "Player_Name" if "Player_Name" in csv_columns else column_options[0]
        player_name_col = st.selectbox("Player Name column", column_options, index=column_options.index(player_name_col_guess) if player_name_col_guess in column_options else 0)

    st.divider()

    mapped_count = sum(1 for v in mapping.values() if v != "-- Skip --")
    st.write(f"{mapped_count} of {len(test_types_by_name)} test values will be imported per pitch.")

    if st.button("Import", type="primary"):
        if date_col == "-- Skip --":
            st.error("A Date column is required.")
            page_footer()
            st.stop()
        if not single_player_mode and player_name_col == "-- Skip --":
            st.error("Player Name column is required when importing multiple players.")
            page_footer()
            st.stop()

        pitch_types_cache = {pt.type_name.lower(): pt for pt in session.query(PitchType).all()}
        roster_by_id_for_import = {p.player_id: p for p in roster}

        imported = 0
        skipped_no_player = 0
        skipped_no_values = 0

        progress = st.progress(0.0, text="Importing...")
        total_rows = len(df)

        for i, row in df.iterrows():
            if single_player_mode:
                player = roster_by_id_for_import.get(single_player_id)
            else:
                name = str(row.get(player_name_col, "")).strip().lower()
                player = roster_by_name.get(name)
            if player is None:
                skipped_no_player += 1
                continue

            try:
                assessment_date = datetime.strptime(str(row[date_col]).strip(), "%a %b %d %Y %I:%M:%S %p").date()
            except Exception:
                skipped_no_player += 1  # unparseable date -- treat as skipped
                continue

            pitch_type_id = None
            if pitch_type_col != "-- Skip --":
                raw_type = str(row.get(pitch_type_col, "")).strip()
                normalized = PITCH_TYPE_MAP.get(raw_type.lower().replace(" ", ""))
                if normalized:
                    pt = pitch_types_cache.get(normalized.lower())
                    if pt is None:
                        pt = PitchType(type_name=normalized, display_order=99)
                        session.add(pt)
                        session.flush()
                        pitch_types_cache[normalized.lower()] = pt
                    pitch_type_id = pt.pitch_type_id

            new_assessment = Assessment(
                player_id=player.player_id,
                category_id=category.category_id,
                assessment_date=assessment_date,
                entered_by_user_id=current_user_id,
                pitch_type_id=pitch_type_id,
                notes="Imported from Rapsodo CSV",
            )
            session.add(new_assessment)
            session.flush()

            values_added = 0
            for test_name, csv_col in mapping.items():
                if csv_col == "-- Skip --":
                    continue
                raw_val = row.get(csv_col)
                if test_name == "Spin Axis":
                    value = clock_to_degrees(str(raw_val)) if pd.notna(raw_val) else None
                else:
                    value = parse_float(raw_val)
                if value is not None:
                    session.add(AssessmentResult(
                        assessment_id=new_assessment.assessment_id,
                        test_type_id=test_types_by_name[test_name].test_type_id,
                        value=value,
                    ))
                    values_added += 1

            if values_added == 0:
                session.rollback()
                skipped_no_values += 1
                continue

            imported += 1
            if imported % 100 == 0:
                session.commit()
            progress.progress((i + 1) / total_rows, text=f"Importing... {i + 1}/{total_rows}")

        session.commit()
        progress.empty()

        st.success(
            f"Imported {imported} pitch assessments. "
            f"Skipped {skipped_no_player} (no matching player or unparseable date), "
            f"{skipped_no_values} (no mapped values present)."
        )

        if single_player_mode and single_player_bullpen_id is not None:
            target_bullpen = session.query(BullpenSession).filter(BullpenSession.bullpen_id == single_player_bullpen_id).first()
            if target_bullpen:
                label = f"{target_bullpen.session_date.strftime('%Y-%m-%d (%a)')} — {target_bullpen.bullpen_type.type_name if target_bullpen.bullpen_type else '—'}"
                if st.button(f"Go link these pitches to {label}", type="primary"):
                    st.session_state.bp_selected_pitcher_id = single_player_id
                    st.query_params["bullpen_id"] = str(single_player_bullpen_id)
                    st.session_state.active_bullpen_id = single_player_bullpen_id
                    st.switch_page("pages/bullpen_tracking.py")

finally:
    session.close()

page_footer()