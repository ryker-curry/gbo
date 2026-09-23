"""
GBO -- Guest-mode demo data (Sept 2026).

Entirely synthetic. This module builds a small, made-up pitching staff
(six fictional players, none of them real Pittsburg State Gorillas)
plus fake Rapsodo bullpen readings and fake located/charted game
pitches for them, ONLY so the "Continue as Guest" page can show real
GBO analytics end to end -- Physical Profile, Stuff+/Location+/
Pitching+, Command+, Estimated Arm Angle/VAA -- without ever touching
the real database or a real player's data.

The point isn't to invent a parallel data model: every number a guest
sees comes out of the SAME functions the live app uses on real data
(analytics/bullpen_metrics.pitch_type_summary, analytics/pitch_grading.
stuff_plus/location_plus/pitching_plus, analytics/command_metrics'
Command+ pipeline). This module's only job is to manufacture plausible
inputs for those functions -- a fake team-wide population to baseline
against, and one featured fake pitcher to show off -- and then get out
of the way. If a real methodology change lands in those analytics
modules, this file doesn't need a matching change; it'll just show the
new math on fake numbers automatically.

Deterministic (fixed random seed): the numbers a guest sees are the
same on every reload. That matters here more than it would for an
ordinary demo -- this page doubles as Ryker's own portfolio piece when
he shows GBO to MLB organizations, and the numbers shouldn't reshuffle
mid-conversation.

Two small, deliberate simplifications versus the real pipeline, both
called out again where they're used below:
  1. Stuff+ models are normally fit from real-game run-value pitches
     (see analytics.pitch_grading.fit_stuff_plus_model). This roster has
     no real games, so the model here is built the same way -- same
     fixed per-type weights, same "standardize against the team's own
     mean/stdev" math, reusing pitch_grading's own private feature
     extractor so the math is identical -- just skipping the MIN_STUFF_
     TRAINING_PITCHES/run-value gating that only matters for deciding
     whether a REAL model is trustworthy yet.
  2. Location+/Pitching+ need a run_value per pitch. Real run_value
     comes from GBO's run-expectancy tables (see models.RunExpectancy);
     this module just assigns a plausible, directionally-correct run
     value per pitch outcome (a walk costs the pitcher, a strikeout
     helps him, etc.) rather than building a fake RE24 matrix. Good
     enough to illustrate what the grade means -- not a claim that
     these exact numbers are calibrated.
"""

import random
from collections import defaultdict
from statistics import mean, stdev
from types import SimpleNamespace

from analytics.bullpen_metrics import pitch_type_summary
from analytics.command_metrics import (
    game_pitches_command_view,
    miss_bias,
    session_command_scorecard,
)
from analytics.pitch_grading import (
    _stuff_plus_features,  # reused so demo Stuff+ uses the exact same feature math as production -- see module docstring
    _stuff_plus_weights_for,
    location_plus,
    pitching_plus,
    stuff_plus as score_stuff_plus,
    team_location_plus_baseline,
)

_SEED = 20260923

FEATURED_PLAYER_NAME = "Deacon Whitfield"

# Six made-up pitchers. Names, numbers, and results below are entirely
# fictional -- not modeled on any real Pittsburg State player, current
# or former.
_ROSTER = [
    dict(name="Deacon Whitfield", throws="R", height_in=74, pitches=["4-Seam Fastball", "Slider"]),
    dict(name="Cole Bannister", throws="R", height_in=72, pitches=["4-Seam Fastball", "Changeup"]),
    dict(name="Trey Osgood", throws="L", height_in=73, pitches=["4-Seam Fastball", "Curveball"]),
    dict(name="Marcus Delgado", throws="R", height_in=75, pitches=["4-Seam Fastball", "Slider"]),
    dict(name="Jonah Pruitt", throws="R", height_in=71, pitches=["4-Seam Fastball", "Changeup"]),
    dict(name="Silas Vance", throws="L", height_in=76, pitches=["4-Seam Fastball", "Curveball"]),
]

# (mean, stdev) per field, per pitch type -- loosely calibrated to
# realistic college-level Rapsodo readings, not measured from anyone.
_PROFILES = {
    "4-Seam Fastball": dict(
        velocity=(91.5, 1.8), total_spin=(2250, 90), vb=(16.0, 1.3), hb=(6.0, 1.6),
        spin_eff=(80, 5), gyro=(35, 5), rel_h=(5.7, 0.30), rel_side=(1.70, 0.25),
        rel_ext=(6.2, 0.35), rel_angle=(-2.0, 0.8),
    ),
    "Slider": dict(
        velocity=(80.5, 1.6), total_spin=(2350, 110), vb=(-1.0, 1.4), hb=(-8.5, 1.6),
        spin_eff=(35, 6), gyro=(68, 6), rel_h=(5.6, 0.30), rel_side=(1.80, 0.25),
        rel_ext=(6.0, 0.35), rel_angle=(0.8, 0.8),
    ),
    "Changeup": dict(
        velocity=(82.0, 1.5), total_spin=(1750, 90), vb=(4.5, 1.4), hb=(12.0, 1.6),
        spin_eff=(55, 6), gyro=(52, 6), rel_h=(5.6, 0.30), rel_side=(1.70, 0.25),
        rel_ext=(6.0, 0.35), rel_angle=(-1.0, 0.8),
    ),
    "Curveball": dict(
        velocity=(76.0, 1.6), total_spin=(2500, 120), vb=(-10.0, 1.6), hb=(-6.0, 1.6),
        spin_eff=(60, 6), gyro=(50, 6), rel_h=(5.8, 0.30), rel_side=(1.70, 0.25),
        rel_ext=(5.9, 0.35), rel_angle=(2.0, 0.8),
    ),
}

N_BULLPEN_PITCHES_PER_TYPE = 15
N_GAME_PITCHES_PER_PLAYER = 24

# (pitch_outcome, ab_outcome, ends_pa, weight) -- a plain, illustrative
# outcome mix. Skewed toward outs/weak-to-medium outcomes on purpose:
# this roster is meant to look like a competent college staff, the way
# a recruiter watching the demo would expect.
_OUTCOME_TABLE = [
    ("Ball", None, False, 0.34),
    ("Called Strike", None, False, 0.14),
    ("Swing and Miss", None, False, 0.10),
    ("Foul", None, False, 0.12),
    ("Swing and Miss", "K", True, 0.03),
    ("In Play", "Groundout", True, 0.10),
    ("In Play", "Flyout", True, 0.08),
    ("In Play", "1B", True, 0.06),
    ("In Play", "2B", True, 0.02),
    ("In Play", "E", True, 0.01),
]

# Simplified, directionally-correct run values per outcome (negative =
# good for the pitcher) -- see module docstring, simplification #2.
_RUN_VALUE = {
    "Ball": 0.03, "Called Strike": -0.06, "Swing and Miss": -0.11, "Foul": -0.02,
    "K": -0.25, "Groundout": -0.20, "Flyout": -0.19, "1B": 0.42, "2B": 0.72, "E": 0.35,
}

_CONTACT_QUALITY_WEIGHTS = [
    ("Weak", 0.25), ("Jammed", 0.20), ("Off the End", 0.15),
    ("Clipped", 0.15), ("Solid", 0.15), ("Barreled/Squared Up", 0.10),
]


def _weighted_choice(rng, table):
    total = sum(row[-1] for row in table)
    r = rng.uniform(0, total)
    upto = 0
    for row in table:
        upto += row[-1]
        if r <= upto:
            return row
    return table[-1]


def _gauss(rng, spec):
    m, sd = spec
    return rng.gauss(m, sd)


def _build_rapsodo_pitch(rng, player_id, pitch_type_label, profile):
    vb = round(_gauss(rng, profile["vb"]), 1)
    hb = round(_gauss(rng, profile["hb"]), 1)
    return SimpleNamespace(
        player_id=player_id,
        pitch_type=SimpleNamespace(type_name=pitch_type_label),
        raw_pitch_type=pitch_type_label,
        velocity=round(_gauss(rng, profile["velocity"]), 1),
        total_spin=round(_gauss(rng, profile["total_spin"])),
        vb_spin=vb,
        hb_spin=hb,
        vb_trajectory=round(vb + rng.gauss(0, 0.6), 1),
        hb_trajectory=round(hb + rng.gauss(0, 0.6), 1),
        spin_efficiency=round(max(5, min(99, _gauss(rng, profile["spin_eff"]))), 1),
        gyro_degree=round(max(0, min(90, _gauss(rng, profile["gyro"]))), 1),
        spin_axis_degrees=round(rng.uniform(0, 30), 1),
        release_height=round(_gauss(rng, profile["rel_h"]), 2),
        release_side=round(_gauss(rng, profile["rel_side"]), 2),
        release_extension=round(_gauss(rng, profile["rel_ext"]), 2),
        release_angle=round(_gauss(rng, profile["rel_angle"]), 2),
        plate_z_ft=round(rng.uniform(1.4, 3.2), 2),
        plate_x_ft=round(rng.uniform(-1.2, 1.2), 2),
    )


def _build_game_pitch(rng, pitch_type_label, game_id, game_pitch_id, pitch_sequence):
    intended_x = round(rng.uniform(-0.6, 0.6), 3)
    intended_z = round(rng.uniform(1.3, 3.0), 3)
    actual_x = round(intended_x + rng.gauss(0, 0.35), 3)
    actual_z = round(intended_z + rng.gauss(0, 0.35), 3)
    pitch_outcome, ab_outcome, ends_pa, _w = _weighted_choice(rng, _OUTCOME_TABLE)
    contact_quality = None
    batted_ball_type = None
    if pitch_outcome == "In Play":
        contact_quality, _w2 = _weighted_choice(rng, _CONTACT_QUALITY_WEIGHTS)
        batted_ball_type = rng.choice(["Ground Ball", "Fly Ball", "Line Drive"])
    run_value = _RUN_VALUE[ab_outcome if ab_outcome else pitch_outcome]
    return SimpleNamespace(
        pitch_type=SimpleNamespace(type_name=pitch_type_label),
        game_id=game_id, game_pitch_id=game_pitch_id, pitch_sequence=pitch_sequence,
        intended_plate_x=intended_x, intended_plate_z=intended_z,
        actual_plate_x=actual_x, actual_plate_z=actual_z,
        pitch_outcome=pitch_outcome, ab_outcome=ab_outcome, ends_plate_appearance=ends_pa,
        contact_quality=contact_quality, batted_ball_type=batted_ball_type,
        run_value=run_value,
    )


def _build_stuff_plus_model(pitch_type_label, pitches_of_type, fastball_velo_by_player):
    """Same math fit_stuff_plus_model uses (fixed per-type weights,
    standardize against this population's own mean/stdev) -- see module
    docstring for why this doesn't call that function directly."""
    weights = _stuff_plus_weights_for(pitch_type_label)
    required = [name for name, w in weights.items() if w]
    rows = []
    for p in pitches_of_type:
        pitcher_velo = fastball_velo_by_player.get(p.player_id)
        feats = _stuff_plus_features(p, pitcher_velo)
        if any(feats[name] is None for name in required):
            continue
        rows.append(feats)
    if len(rows) < 2:
        return None
    feature_baseline = {}
    for name in required:
        vals = [r[name] for r in rows]
        sd = stdev(vals) if len(vals) > 1 else 0.0
        feature_baseline[name] = (mean(vals), sd or 1e-9)
    composites = [
        sum(weights[name] * (r[name] - feature_baseline[name][0]) / feature_baseline[name][1] for name in required)
        for r in rows
    ]
    p_sd = stdev(composites) if len(composites) > 1 else 0.0
    return {
        "feature_baseline": feature_baseline,
        "quality_weights": weights,
        "prediction_baseline": (mean(composites), p_sd or 1e-9),
        "pitcher_fastball_velocities": fastball_velo_by_player,
        "n": len(rows),
    }


_STATE = None  # built once, lazily -- see _state()


def _generate():
    rng = random.Random(_SEED)
    players = {}
    pitches_by_player = defaultdict(list)
    all_pitches_by_type = defaultdict(list)
    game_pitches_by_player = defaultdict(list)
    fastball_velo_by_player = {}

    for idx, spec in enumerate(_ROSTER, start=1):
        player_id = idx
        first_name, last_name = spec["name"].split(" ", 1)
        players[spec["name"]] = SimpleNamespace(
            player_id=player_id, first_name=first_name, last_name=last_name,
            throws=spec["throws"], height_in=spec["height_in"],
        )
        for label in spec["pitches"]:
            profile = _PROFILES[label]
            for _ in range(N_BULLPEN_PITCHES_PER_TYPE):
                pitch = _build_rapsodo_pitch(rng, player_id, label, profile)
                pitches_by_player[spec["name"]].append(pitch)
                all_pitches_by_type[label].append(pitch)
        fb_pitches = [p for p in pitches_by_player[spec["name"]] if p.pitch_type.type_name == "4-Seam Fastball"]
        if fb_pitches:
            fastball_velo_by_player[player_id] = mean(p.velocity for p in fb_pitches)

        # Each fake pitcher gets their own single fake outing (game_id
        # == player_id is fine here -- nothing cross-references a real
        # Game row, this only needs to satisfy game_pitches_command_
        # view's own per-game pitch-numbering logic).
        for seq in range(1, N_GAME_PITCHES_PER_PLAYER + 1):
            label = rng.choice(spec["pitches"])
            game_pitch_id = player_id * 1000 + seq
            game_pitches_by_player[spec["name"]].append(
                _build_game_pitch(rng, label, game_id=player_id, game_pitch_id=game_pitch_id, pitch_sequence=seq)
            )

    stuff_plus_models = {
        label: _build_stuff_plus_model(label, pitches, fastball_velo_by_player)
        for label, pitches in all_pitches_by_type.items()
    }

    all_game_pitches = [gp for gps in game_pitches_by_player.values() for gp in gps]
    location_plus_baseline = team_location_plus_baseline(all_game_pitches)

    return SimpleNamespace(
        players=players,
        pitches_by_player=pitches_by_player,
        game_pitches_by_player=game_pitches_by_player,
        stuff_plus_models=stuff_plus_models,
        location_plus_baseline=location_plus_baseline,
    )


def _state():
    global _STATE
    if _STATE is None:
        _STATE = _generate()
    return _STATE


def teammate_names():
    """Every fake name on the roster, featured pitcher first."""
    names = [spec["name"] for spec in _ROSTER]
    names.remove(FEATURED_PLAYER_NAME)
    return [FEATURED_PLAYER_NAME] + names


def demo_pitcher_report(name=FEATURED_PLAYER_NAME):
    """Everything the guest-mode Pitcher Profile deep dive needs for one
    fake pitcher, computed with the SAME analytics functions the real
    Pitcher Profile page calls (see module docstring)."""
    state = _state()
    player = state.players[name]
    pitches = state.pitches_by_player[name]
    game_pitches = state.game_pitches_by_player[name]

    physical_rows = []
    for row in pitch_type_summary(pitches, player=player):
        physical_rows.append({
            "Pitch Type": row["Pitch Type"], "#": row["#"],
            "Velo": row["Avg Velo"], "Max Velo": row["Max Velo"],
            "Spin Rate": row["Avg Spin"],
            "IVB": row["IVB"], "HB": row["HB"],
            "Release Ht": row["Release Height"], "Release Side": row["Release Side"],
            "Arm Angle": row.get("Est. Arm Angle", "N/A"),
            "Est. VAA": row.get("Est. VAA", "N/A"),
        })

    grades = {}
    for label in {p.pitch_type.type_name for p in pitches}:
        model = state.stuff_plus_models.get(label)
        type_pitches = [p for p in pitches if p.pitch_type.type_name == label]
        stuff_vals = [v for v in (score_stuff_plus(p, model) for p in type_pitches) if v is not None] if model else []
        type_game_pitches = [gp for gp in game_pitches if gp.pitch_type.type_name == label]
        loc_vals = [v for v in (location_plus(gp, state.location_plus_baseline) for gp in type_game_pitches) if v is not None]
        stuff_avg = round(mean(stuff_vals), 1) if stuff_vals else None
        loc_avg = round(mean(loc_vals), 1) if loc_vals else None
        grades[label] = {
            "n_bullpen": len(type_pitches),
            "n_located": len(type_game_pitches),
            "stuff_plus": stuff_avg,
            "location_plus": loc_avg,
            "pitching_plus": pitching_plus(stuff_avg, loc_avg),
        }

    command_view = game_pitches_command_view(game_pitches, player.throws)
    scorecard = session_command_scorecard(command_view)
    bias = miss_bias(command_view, player.throws)

    return {
        "player": player,
        "physical_rows": physical_rows,
        "grades": grades,
        "command": scorecard,
        "miss_bias": bias,
    }
