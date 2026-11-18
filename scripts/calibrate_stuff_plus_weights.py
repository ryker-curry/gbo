"""
Suggest data-tuned Stuff+ weights from GBO's real-game pitches.

Run from the project root:
    python3 -m scripts.calibrate_stuff_plus_weights

Prints a STUFF_PLUS_FIXED_WEIGHTS dict to paste into
analytics/pitch_grading.py, plus a review table of what moved and why.
Read-only: never writes to the database or to any file.

Method lives in analytics.pitch_grading.calibrate_stuff_plus_weights
(noise gate, shrinkage toward the hand-set priors, 50% cap per weight, no
sign flips). Outcome = called strike or swinging strike (CSW), which is a
much less noisy per-pitch outcome than run value at GBO's data size.
"""
from collections import defaultdict

from database import SessionLocal
from models import GamePitch, RapsodoPitch
from sqlalchemy.orm import joinedload

from analytics import pitch_grading as g
from analytics.profile_queries import team_pitcher_primary_fastball_velocity, team_pitcher_primary_fastball_shape


def main():
    db = SessionLocal()
    try:
        rows = (
            db.query(RapsodoPitch, GamePitch.pitch_outcome)
            .join(GamePitch, RapsodoPitch.game_pitch_id == GamePitch.game_pitch_id)
            .options(joinedload(RapsodoPitch.pitch_type))
            .filter(RapsodoPitch.pitch_type_id.isnot(None))
            .filter(GamePitch.run_value.isnot(None))
            .all()
        )
        velos = team_pitcher_primary_fastball_velocity(db)
        shapes = team_pitcher_primary_fastball_shape(db)
    finally:
        db.close()

    by_type = defaultdict(list)
    for rp, outcome in rows:
        label = rp.pitch_type.type_name if rp.pitch_type else None
        if label not in g.STUFF_PLUS_PRIOR_WEIGHTS:
            continue
        feats = g._stuff_plus_features(rp, velos.get(rp.player_id), shapes.get(rp.player_id))
        by_type[label].append((feats, 1 if outcome in g.STUFF_CALIBRATION_OUTCOMES else 0))

    tuned = g.calibrate_stuff_plus_weights(by_type)

    print("# Review")
    for label, weights in tuned.items():
        meta = weights.pop("__meta__")
        print(f"# {label}: n={meta['n']}, lambda={meta['lambda']}, moved={meta.get('moved') or 'none'}")
        for name, prior in g.STUFF_PLUS_PRIOR_WEIGHTS[label].items():
            if prior or weights[name]:
                print(f"#   {name:22} prior {prior:5} -> {weights[name]:5}   r={meta['r'].get(name)}")
    print()
    print("STUFF_PLUS_FIXED_WEIGHTS = {")
    for label, weights in tuned.items():
        print(f'    "{label}": {{')
        for name, w in weights.items():
            print(f'        "{name}": {float(w)},')
        print("    },")
    print("}")


if __name__ == "__main__":
    main()
