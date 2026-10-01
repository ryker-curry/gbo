"""
GBO — Migration: backfill trajectory_json for existing RapsodoPitch rows.

Sept 2026, restoring pitch_trajectory.py as backend-only data for
pitch-tunneling analytics (see that module's docstring, and
analytics/pitch_grading.py, for the full history/reasoning). Pitches
imported before this restore never had trajectory_json computed (a
small number from the original Aug 2026 Phase 4 chart build may
already hold a value from that brief earlier window -- see models.py's
trajectory_json comment) -- this migration computes and saves
trajectory_json for every row that doesn't already have one. Pitches
imported AFTER this restore get it computed automatically at import
time (see services/rapsodo_import.py); this script only needs to run
once to catch up the backlog.

Pitches missing a required physics input (release_extension, hb_spin,
etc. -- see pitch_trajectory.py's docstring for the full list) are
left with trajectory_json=NULL, same as at import time -- this script
never guesses a value pitch_trajectory.py itself would refuse to
compute.

Deliberately filters "already has a trajectory?" in PYTHON, not via a
`.filter(RapsodoPitch.trajectory_json.is_(None))` SQL clause -- this
repeats a gotcha caught during the original Phase 4 build: SQLAlchemy's
plain JSON column type (models.py uses JSON, not a none_as_null=True
variant) can store Python None as the JSON literal 'null' rather than
a real SQL NULL depending on how a row was written, so an IS NULL
filter at the SQL level can silently miss rows whose Python
.trajectory_json value is actually None. Loading every row and
checking in Python sidesteps that gotcha entirely; fine for a one-off
backfill script at GBO's pitch-count scale (well under 1,000 rows as
of Sept 2026).

Run (see migrate_fastball_to_4seam.py's docstring for why the
sys.path fix below is needed -- same root cause, same fix):
    python3 migrations/backfill_trajectory_json.py
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from database import get_session
from models import RapsodoPitch
from pitch_trajectory import compute_trajectory


def main():
    session = get_session()
    try:
        pitches = [p for p in session.query(RapsodoPitch).all() if p.trajectory_json is None]
        print(f"Found {len(pitches)} RapsodoPitch row(s) without a cached trajectory.")

        computed = 0
        skipped = 0
        errored = 0
        for pitch in pitches:
            try:
                trajectory = compute_trajectory(pitch)
            except Exception as e:
                errored += 1
                print(f"  rapsodo_pitch_id={pitch.rapsodo_pitch_id}: trajectory computation raised {type(e).__name__}: {e} -- left NULL")
                continue
            if trajectory is None:
                skipped += 1
                continue
            pitch.trajectory_json = trajectory
            computed += 1

        session.commit()
        print(f"Done. Computed and saved {computed} trajectory/trajectories.")
        print(f"Skipped {skipped} pitch(es) missing a required physics input (release_extension, hb_spin, "
              f"vb_spin, plate_x_ft, plate_z_ft, etc.) -- left NULL, same as import-time behavior.")
        if errored:
            print(f"{errored} pitch(es) raised an unexpected error during computation -- left NULL, see lines above.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
