"""
GBO — Migration: reclassify existing rapsodo_pitches rows tagged generic
"Fastball" onto "4-Seam Fastball".

Sept 2026, Ryker: "treat fastball as 4sfb". Rapsodo's export never
distinguishes 2-seam from 4-seam -- every straight fastball reading
comes back labeled plain "Fastball", which pitch_type_config.py used to
map onto its own separate "Fastball" PitchType row rather than assuming
it was 4-seam (see that module's docstring for the original reasoning).
In practice that split was starving "4-Seam Fastball" of real-game
training data: 298 rapsodo_pitches rows team-wide were tagged generic
"Fastball" (imports only -- no manual entry anywhere in the app, in
game_pitches/hitter_swings/bullpen_pitches/command_pitches/
player_pitch_arsenal, had ever actually picked "Fastball" over "4-Seam
Fastball"), vs. 0 tagged "4-Seam Fastball" -- so
pitch_grading.fit_stuff_plus_model could never reach
MIN_STUFF_TRAINING_PITCHES for 4-Seam Fastball specifically, even
though the team's actual 4-seam sample (hiding under the generic label)
was the largest of any pitch type.

pitch_type_config.py's _RAW_ALIASES now maps "fastball"/"fb" straight to
"4-Seam Fastball" going forward -- this script is the one-time backfill
for rows imported BEFORE that change. Only rapsodo_pitches needed this
(confirmed via a direct count against every other pitch_type_id-bearing
table -- all zero for pitch_type_id 8, "Fastball"); nothing else in the
schema had ever used the generic "Fastball" type.

The "Fastball" PitchType row itself is left in the catalog, just
unused going forward -- not deleted, so this is easy to revert if a
different mapping is ever preferred again.

Run once, after pulling this update.

Run (from anywhere -- see the sys.path note below):
    python3 migrations/migrate_fastball_to_4seam.py

Import path note: run as a bare script, Python puts THIS file's own
directory (migrations/) on sys.path, not the repo root one level up
where database.py actually lives -- fails with "ModuleNotFoundError:
No module named 'database'" (same root cause every other migration
script in this directory already documents). Fixed below the same way:
explicitly add the repo root to sys.path before importing database, so
this runs correctly no matter which directory it's launched from.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text
from database import engine


def main():
    print("Reclassifying rapsodo_pitches rows: 'Fastball' -> '4-Seam Fastball'...")
    with engine.begin() as conn:
        fastball_id = conn.execute(text(
            "SELECT pitch_type_id FROM pitch_types WHERE type_name = 'Fastball'"
        )).scalar()
        four_seam_id = conn.execute(text(
            "SELECT pitch_type_id FROM pitch_types WHERE type_name = '4-Seam Fastball'"
        )).scalar()
        if fastball_id is None or four_seam_id is None:
            print("Couldn't find both 'Fastball' and '4-Seam Fastball' in pitch_types -- nothing changed.")
            return

        result = conn.execute(text(
            "UPDATE rapsodo_pitches SET pitch_type_id = :four_seam_id WHERE pitch_type_id = :fastball_id"
        ), {"four_seam_id": four_seam_id, "fastball_id": fastball_id})
        print(f"rapsodo_pitches: reclassified {result.rowcount} row(s) from 'Fastball' to '4-Seam Fastball'.")

    print("\nMigration complete. The 'Fastball' PitchType row is left in the catalog, just")
    print("unused going forward -- see this script's module docstring if this ever needs reverting.")
    print("Stuff+ for 4-Seam Fastball can now train once enough of these are also run-value-linked")
    print("(pitch_grading.MIN_STUFF_TRAINING_PITCHES) -- re-check via analytics/profile_queries.py's")
    print("team_stuff_plus_training_pitches.")


if __name__ == "__main__":
    main()
