"""
GBO — Bullpen Scripts.

A reusable, pre-planned pitch sequence -- build a script once (e.g.
"25-pitch Execution Ladder": pitch type + intended zone for each pitch,
in order), then load it on Bullpen Tracking to pre-create the whole
planned sequence at once when starting a real session. Matches Ryker's
chosen workflow: script the whole bullpen upfront, link each pitch to
its Rapsodo data after it's actually thrown, rather than picking each
pitch live one at a time.
"""

import streamlit as st
import pandas as pd

from database import get_session
from models import BullpenType, BullpenScript, BullpenScriptPitch, PitchType
from ui_components import page_header, page_footer, empty_state

page_header("Bullpen Scripts")

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

if role_name == "Coach" and st.session_state.get("gbo_coach_specialty") == "Hitting":
    st.error("You don't have access to this page.")
    page_footer()
    st.stop()

ZONE_CHOICES = ["0 - Bury"] + [str(z) for z in range(1, 10)]


def _zone_choice_to_int(choice):
    return int(choice.split(" ")[0])


session = get_session()
try:
    bullpen_types = session.query(BullpenType).order_by(BullpenType.display_order).all()
    pitch_types = session.query(PitchType).order_by(PitchType.pitch_type_id).all()

    st.subheader("Script library")
    scripts = session.query(BullpenScript).order_by(BullpenScript.script_name).all()

    if not scripts:
        empty_state("No bullpen scripts saved yet.")
    else:
        for s in scripts:
            bp_type_name = s.bullpen_type.type_name if s.bullpen_type else "—"
            with st.expander(f"**{s.script_name}** ({bp_type_name}) — {len(s.pitches)} pitch(es)"):
                if not s.pitches:
                    st.caption("No pitches added to this script yet.")
                else:
                    st.dataframe(
                        [
                            {
                                "#": p.pitch_number,
                                "Pitch Type": p.pitch_type.type_name if p.pitch_type else "—",
                                "Intended Zone": "Bury" if p.target_zone == 0 else p.target_zone,
                                "Notes": p.notes or "",
                            }
                            for p in s.pitches
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )

    if not can_edit_sessions:
        st.info("Your role has read-only access to bullpen scripts.")
        page_footer()
        st.stop()

    st.divider()
    st.subheader("Create a new script")

    with st.form("new_script_form"):
        script_name = st.text_input("Script name", placeholder="e.g. 25-pitch Execution Ladder")
        type_choice = st.selectbox("Bullpen type", [t.type_name for t in bullpen_types])
        create_submitted = st.form_submit_button("Create script", type="primary")

    if create_submitted:
        if not script_name.strip():
            st.error("Script name is required.")
        else:
            type_id = next(t.bullpen_type_id for t in bullpen_types if t.type_name == type_choice)
            session.add(BullpenScript(
                script_name=script_name.strip(),
                bullpen_type_id=type_id,
                created_by_user_id=current_user_id,
            ))
            session.commit()
            st.success(f"Created script: {script_name.strip()}")
            st.rerun()

    st.divider()
    st.subheader("Add planned pitches to a script")

    if not scripts:
        st.caption("Create a script above first.")
    else:
        scripts_by_id = {s.script_id: s for s in scripts}
        selected_script_id = st.selectbox(
            "Script",
            options=list(scripts_by_id.keys()),
            format_func=lambda sid: scripts_by_id[sid].script_name,
        )
        selected_script = scripts_by_id[selected_script_id]

        st.caption(f"Type the planned sequence for {selected_script.script_name} below -- add as many rows as you need, then save.")
        pitch_table = st.data_editor(
            pd.DataFrame(columns=["Pitch Type", "Intended Zone", "Notes"]),
            num_rows="dynamic",
            use_container_width=True,
            key=f"script_pitch_table_{selected_script_id}",
            column_config={
                "Pitch Type": st.column_config.SelectboxColumn(options=[pt.type_name for pt in pitch_types], required=True),
                "Intended Zone": st.column_config.SelectboxColumn(options=ZONE_CHOICES, required=True),
                "Notes": st.column_config.TextColumn(),
            },
        )

        if st.button("Save planned pitches", type="primary"):
            valid_rows = pitch_table[pitch_table["Pitch Type"].notna() & pitch_table["Intended Zone"].notna()]
            if valid_rows.empty:
                st.error("Add at least one planned pitch (pitch type + intended zone) before saving.")
            else:
                pitch_types_by_name = {pt.type_name: pt.pitch_type_id for pt in pitch_types}
                next_number = len(selected_script.pitches) + 1
                added = 0
                for _, row in valid_rows.iterrows():
                    session.add(BullpenScriptPitch(
                        script_id=selected_script_id,
                        pitch_number=next_number,
                        pitch_type_id=pitch_types_by_name.get(row["Pitch Type"]),
                        target_zone=_zone_choice_to_int(row["Intended Zone"]),
                        notes=str(row["Notes"]).strip() if pd.notna(row.get("Notes")) else None,
                    ))
                    next_number += 1
                    added += 1
                session.commit()
                st.success(f"Added {added} planned pitch(es) to {selected_script.script_name}.")
                st.rerun()

finally:
    session.close()

page_footer()