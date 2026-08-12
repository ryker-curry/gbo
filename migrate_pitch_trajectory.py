"""
GBO — Migration: backfill trajectory_json for existing RapsodoPitch rows.

Phase 4 of the Rapsodo Bullpen Analytics build. trajectory_json is
already a column on rapsodo_pitches (added when that table was first
created in migrate_rapsodo_bullpen.py) -- this migration doesn't need
an ALTER TABLE, it just needs to populate it for every pitch imported
BEFORE Phase 4 shipped. Pitches imported AFTER Phase 4 get
trajectory_json computed automatically at import time (see
services/rapsodo_import.py); this script only needs to run once to
catch up the backlog.

Pitches missing a required physics input (release_extension, hb_spin,
etc. -- see pitch_trajectory.py's docstring for the full list) are
left with trajectory_json=NULL, same as at import time -- this script
never guesses a value pitch_trajectory.py itself would refuse to
compute.

Deliberately filters "already has a trajectory?" in PYTHON, not via a
`.filter(RapsodoPitch.trajectory_json.is_(None))` SQL clause -- caught
during testing that SQLAlchemy's plain JSON column type (models.py
uses JSON, not a none_as_null=True variant) stores Python None as the
JSON literal 'null', NOT a real SQL NULL, so an IS NULL filter at the
SQL level silently matches zero rows even when every row's Python
.trajectory_json value is actually None. Loading every row and
checking in Python sidesteps that gotcha entirely; fine for a one-off
backfill script at GBO's pitch-count scale.

Run:
    python migrate_pitch_trajectory.py
"""

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
                print(f"  pitch_id={pitch.rapsodo_pitch_id}: trajectory computation raised {type(e).__name__}: {e} -- left NULL")
                continue
            if trajectory is None:
                skipped += 1
                continue
            pitch.trajectory_json = trajectory
            computed += 1

        session.commit()
        print(f"Done. Computed and saved {computed} trajectory/trajectories.")
        print(f"Skipped {skipped} pitch(es) missing a required physics input (release_extension, hb_spin, vb_spin, etc.) -- left NULL, same as import-time behavior.")
        if errored:
            print(f"{errored} pitch(es) raised an unexpected error during computation -- left NULL, see lines above.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
