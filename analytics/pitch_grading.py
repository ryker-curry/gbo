"""
GBO — Stuff+/Location+/Pitching+/Arsenal: team-relative pitch grading.

Adapted from the FanGraphs Stuff+/Location+/Pitching+ primer
(https://library.fangraphs.com/pitching/stuff-location-and-pitching-primer/),
per the Aug 2026 planning conversation with Ryker (see
STUFF-LOCATION-PITCHING-PLUS-PLAN.md section 4). FanGraphs trains a
decision-tree model against run values across the entire league --
hundreds of pitchers, millions of pitches. GBO has one program's worth of
data (roughly 15-20 pitchers, a few thousand pitches a season), nowhere
near enough distinct pitchers to train an equivalent model without it
just memorizing this specific roster instead of learning anything
general. So every score below keeps the FanGraphs *definitions* (what
inputs go into each score, what's deliberately left out) but swaps the
*scoring method* from a league-trained ML model to a team-relative
z-score composite -- same spirit as the Bucket System, and the same
"100 = average, 10 points = 1 SD" scale command_metrics.py's Command+
already uses.

Same separation as analytics/command_metrics.py: pure data logic, no
Streamlit/Shiny, no database queries of its own. Every function here
either (a) takes an already-loaded ORM row (RapsodoPitch or GamePitch)
plus a pre-built baseline and returns one pitch's score, or (b) takes a
list of already-loaded rows the caller queried/filtered/grouped, and
returns a baseline or a summary. The caller owns every DB query --
this module never queries the database itself.

Team-relative, not league-relative: there is no outside benchmark pool
to compare against (GBO doesn't have access to other programs' Rapsodo
data), so every score here answers "better or worse than THIS staff's
own average," never "better or worse than a real MLB Stuff+/Pitching+
number." The Lab page's footer badge should always make that framing
explicit, same as Command+ already does.

Aug 31 2026 methodology fix (Ryker's call): Stuff+ used to be a fixed
equal-weighted composite -- never trained on anything, so it silently
scored bullpen and game pitches identically with no connection to
run value at all. That's now corrected: Stuff+'s weights are fit by
regressing run_value on the physical features, same "team-relative
z-score, no league benchmark" spirit as everything else in this
module, just scaled down from a decision tree to a linear fit given
GBO's data volume (see fit_stuff_plus_model's docstring for the full
reasoning). Training a type's weights needs real-game pitches (a
run_value to learn from); SCORING a pitch with an already-fitted model
needs only its physical readings, so a bullpen pitch can still get a
Stuff+ number once its pitch type has enough real-game data to have
been fit -- until then, that type's Stuff+ is None (not a guess) for
every pitch of that type, bullpen or game alike.

Sept 2026 methodology fix (Ryker's call, after the Aug 31 regression-fit
version produced a concrete bad result on real data, not just a
theoretical worry): fitting 10 parameters per pitch type from a few
dozen to a couple hundred real-game pitches is exactly the small-sample
regime that overfits and memorizes noise instead of learning anything
general. Checking Ryker Curry's 2-Seam Fastball Stuff+ of 108 against
Luke Schimmel's ~88-93 -- despite Curry throwing 3-4 mph slower with
less horizontal break -- found the fitted model was scoring
release_side and gyro_degree z-score differences almost entirely, while
velocity's fitted weight was tiny and even backwards-signed: a
regression artifact of GBO's still-small per-type training pools, not a
real signal the model had learned. Stuff+'s weights are now FIXED:
hand-set once per canonical pitch type (STUFF_PLUS_FIXED_WEIGHTS below),
informed by outside Stuff+ research (aStuff+, Driveline, Rockland -- the
same sources Sept 2026's feature expansion drew on) and general
pitch-design principles for each type's own defining characteristics
(see STUFF_PLUS_FIXED_WEIGHTS's comment for the per-type reasoning),
rather than fit from GBO's own limited run-value sample. Weights differ
BY pitch type (a fastball's quality is driven by different physical
traits than a curveball's) but are still fixed WITHIN a type -- every
4-Seam Fastball, from any pitcher, scores against the same 4-Seam
Fastball weight set. Everything else about the pipeline is unchanged --
each pitch type still gets its own real, data-derived feature_baseline/
prediction_baseline (plain mean/stdev, not a fitted parameter, and far
more sample-efficient than a regression coefficient), so composites are
still standardized and rescaled against GBO's own team population, just
combined with a fixed rather than a fitted weight per feature. run_value
is no longer needed to compute a Stuff+ number at all -- run_value
remains part of fit_stuff_plus_model's input shape for backward
compatibility with its existing caller, but is now used only
defensively (to keep scoping to real, linkable game pitches), not to
fit anything. MIN_STUFF_TRAINING_PITCHES dropped from 80 to 20,
matching MIN_BASELINE_PITCHES, since descriptive statistics need far
less data than fitting a regression.

Sept 2026 methodology fix, Changeup velocity differential (Ryker's
follow-up call, same week): the per-type weights above initially
weighted a changeup's own standalone velocity near zero, with the
module docstring flagging as an open gap that a changeup's real value
driver -- velocity SEPARATION from the pitcher's own fastball -- wasn't
something this module could see. That gap is now closed for velocity
specifically: velocity_differential (see STUFF_PLUS_FEATURE_NAMES) is
each pitch's own velocity minus that SAME pitcher's own average
velocity on their primary fastball (whichever of 4-Seam/2-Seam Fastball
they throw more, from profile_queries.
team_pitcher_primary_fastball_velocity), sign-flipped so more separation
is a bigger positive number. Weighted only for Changeup for now (see
STUFF_PLUS_FIXED_WEIGHTS's comment), whose standalone velocity weight
dropped to a hard 0.0 now that the differential captures what actually
matters. This is still velocity-only, not movement differential (a
changeup's fade/tumble relative to the pitcher's own fastball shape is
a real thing too, per the plan doc, and remains unimplemented -- see
the V1 simplifications note below).

V1 simplifications, called out explicitly rather than silently guessed
at (see plan doc sections 4 and 8 for the open items these map to):
  - Stuff+ uses a fixed, hand-set weight per feature per pitch type (see
    the Sept 2026 methodology fixes above), not the fastball-
    differential-weighted design the plan doc sketched, and nowhere
    near the real FanGraphs decision-tree model -- GBO's pitcher count
    can't support fitting weights at all without overfitting to this
    specific roster, let alone something as complex as a decision tree.
    Velocity differential from a pitcher's own fastball is now captured
    for Changeup (see above), but MOVEMENT differential isn't -- every
    feature besides velocity_differential still compares a pitch only
    to its own pitch type's team population, never to that same
    pitcher's own fastball shape. Revisit the fixed weights themselves
    once there's a full season or more of real-game Rapsodo data to
    sanity-check them against, and revisit whether per-type fitting
    becomes viable once there's enough data to support it.
  - Location+ buckets by (attack zone tier x pitch type) only -- it
    skips the count-group split the plan doc flagged as a possible
    refinement, to avoid spreading GBO's early game-pitch volume across
    cells too sparse to trust. Revisit once there's more game data.
  - Pitching+ is a transparent weighted blend of Stuff+ and Location+,
    not a third independently-trained model -- the real Pitching+
    explicitly is NOT a weighted average of the other two, but a third
    model isn't viable yet for the same sample-size reasons as Stuff+.
    PITCHING_PLUS_STUFF_WEIGHT is a placeholder, not a validated number.
  - Arsenal's pitch-mix diagnostics ("is a plus pitch underused") are
    deliberately NOT implemented yet -- see arsenal_summary's docstring.
"""

import math
from statistics import mean, stdev

from strike_zone import classify_attack_zone
from analytics.bullpen_metrics import pitch_type_label

# Same floor as command_metrics.py's MIN_BASELINE_PITCHES, same caveat:
# a baseline built from a handful of pitches swings wildly with every new
# pitch logged and isn't trustworthy yet. 20 is a starting floor, not a
# statistically rigorous minimum -- easy to raise once GBO has more of a
# season's worth of data to see how noisy these scores actually are
# below that in practice. Used by Location+ and by arsenal_summary's
# per-pitcher "Reliable" flag; Stuff+ uses the same floor via its own
# MIN_STUFF_TRAINING_PITCHES constant below (kept as a separate constant
# so the two can diverge again if that ever proves necessary).
MIN_BASELINE_PITCHES = 20

# Sept 2026 (see module docstring's "Sept 2026 methodology fix"): Stuff+'s
# weights are now fixed, not fitted, so this floor no longer needs to
# cover 10 regression parameters -- it's gating a set of plain
# per-pitch-type mean/stdev descriptive statistics (feature_baseline/
# prediction_baseline), the same kind of statistic MIN_BASELINE_PITCHES
# above already gates for Location+ and arsenal_summary. Lowered from 80
# (the old regression-era floor, sized for 10 fitted parameters at
# roughly 8-10 observations each) to 20 to match. Still a team-wide, PER
# PITCH TYPE floor (see fit_stuff_plus_model), kept as its own constant
# rather than merged into MIN_BASELINE_PITCHES in case Stuff+ and
# Location+/arsenal ever need to diverge again.
MIN_STUFF_TRAINING_PITCHES = 20

# Sept 2026 (Changeup velocity differential -- see module docstring):
# floor for trusting a PITCHER'S OWN average velocity on their primary
# fastball, used by profile_queries.team_pitcher_primary_fastball_velocity
# to build the reference velocity_differential is computed against. This
# is a per-pitcher sample, not one of this module's team-wide pools, so
# it's deliberately much smaller than MIN_BASELINE_PITCHES/
# MIN_STUFF_TRAINING_PITCHES above -- checked against live data, every
# one of GBO's real-game changeup-throwers has at least 1 real-game
# reading of their primary fastball, most have 6+, the thinnest has
# exactly 1. 3 is a starting floor, not a statistically rigorous
# minimum, chosen so a personal average isn't built from a single pitch
# -- easy to raise once there's more of a season's data to see how
# noisy this actually is below that in practice.
MIN_PITCHER_FASTBALL_VELO_PITCHES = 3


# ---------------------------------------------------------------------------
# Stuff+ -- physical characteristics only (no location, no count -- matches
# the real Stuff+ definition). See module docstring for the Aug 31 2026
# methodology fix: weights are fit from real run value, not assumed equal.
#
# Sept 2026 feature-set expansion (Ryker, after reviewing Salorio's
# aStuff+ writeup, Driveline's "What Is Stuff" primer, and Rockland Peak
# Performance's Stuff+ explainer against GBO's own model): all three
# sources single out release point/extension as real signal (Salorio's
# aStuff+ found adjusted horizontal release point to be its 2nd most
# important feature), and modern pitch-quality work generally treats
# spin efficiency/gyro degree as necessary to interpret total_spin at
# all (two pitches with identical total_spin can move very differently
# depending on how much of that spin is "useful" transverse spin vs.
# "wasted" gyro/bullet spin) -- none of which the original 4-feature
# version used, even though GBO's own Rapsodo import already captures
# release_height/release_side/spin_axis_degrees/spin_efficiency/
# gyro_degree on RapsodoPitch.
#
# release_extension was tried too and pulled back out: checking it
# against live data (not just for nulls -- it has none) found 56% of
# 4-Seam Fastball's real-game training rows sitting at a literal 0.000,
# clustered across nearly every "_Live" (in-game) Rapsodo export from
# many different pitchers/dates, while genuine readings run a plausible
# 4.9-7.0 ft -- i.e. Rapsodo's own Live-tracking mode can't always
# resolve release point and appears to export 0 rather than leave the
# column blank when it can't, and every OTHER pitch type shows the same
# pattern (14% zero on Curveball up to 100% on Splitter's n=8). Since
# real-game run_value linkage only ever comes from Live-mode capture,
# this isn't a fixable import bug or a case for imputing -- it's a
# hardware/capture limitation that makes release_extension specifically
# unusable as a training feature here, so it's left out even though
# release_height/release_side (also release-point metrics, from the
# same RapsodoPitch rows) show no such problem and are kept. Also
# switched vb_spin/hb_spin (pure spin-induced break) to vb_trajectory/
# hb_trajectory (the actual measured break, including seam-shifted-wake
# effects) -- every source describes the headline feature as "vertical/horizontal
# break," not spin-only break, and SSW-heavy pitch types (sinkers,
# splitters) can move meaningfully more than their spin alone predicts.
# ---------------------------------------------------------------------------

STUFF_PLUS_FEATURE_NAMES = (
    "velocity", "vb_trajectory", "hb_trajectory", "total_spin",
    "spin_axis_offset", "spin_efficiency", "gyro_degree",
    "release_height", "release_side", "velocity_differential",
)

# Sept 2026 methodology fix (see module docstring): fixed, hand-set
# per-feature weights, one set PER CANONICAL PITCH TYPE, replacing the
# per-pitch-type regression fit that used to produce quality_weights.
# Same "higher = better" sign convention the old fitted weights used (a
# positive weight means more of that standardized feature predicts a
# BETTER pitch), and the same composite math in stuff_plus() below
# consumes whichever type's dict was selected exactly as it consumed the
# old fitted coefficients -- only where the numbers come from changed,
# not how they're used.
#
# Why per-type rather than one shared set (Ryker's call, after seeing
# the first shared-weight version): a fastball's quality genuinely comes
# from different physical traits than a breaking ball's or a
# changeup's, so forcing every type through the same scorecard was
# always a simplification, not a deliberate finding. Every dict below
# uses the SAME feature list and SAME sign convention (positive =
# better) and keeps release_height/release_side at zero across the
# board -- that zeroing isn't type-specific, it's the direct fix for
# the small-sample regression artifact the Sept 2026 methodology fix
# above documents, and nothing about moving to per-type weights changes
# that reasoning.
#
# Reasoning per type, drawing on the same outside Stuff+ research as the
# original shared weights (Salorio's aStuff+, Driveline's "What Is
# Stuff" primer, Rockland Peak Performance's Stuff+ explainer) plus
# general, widely-documented pitch-design characteristics of each type
# -- the latter is standard pitching-instruction knowledge (what a good
# example of each pitch type looks like physically), not a claim those
# three sources specifically validated per pitch type, and is the least
# confident part of this scorecard -- flag anything that looks off once
# real pitchers are scored against it:
#   - 4-Seam Fastball: velocity and spin_efficiency both weighted high
#     -- efficient (mostly-backspin) spin at high velocity is what
#     produces "ride"/carry, a 4-seam's main swing-and-miss driver.
#     vb_trajectory weighted above hb_trajectory (carry matters more
#     than arm-side run for a 4-seamer); gyro_degree penalized hardest
#     of any type, since gyro spin directly undercuts the backspin a
#     4-seamer's value depends on.
#   - 2-Seam Fastball: velocity weighted the same as 4-seam, but
#     hb_trajectory/vb_trajectory swapped in emphasis -- horizontal
#     run/sink is the defining 2-seam characteristic, not vertical
#     carry. spin_efficiency and the gyro_degree penalty both eased
#     versus 4-seam, since 2-seamers can add real seam-shifted-wake
#     movement even off less purely-efficient spin.
#   - Cutter: velocity weighted close to the fastballs (cutters sit
#     near fastball velocity and lose value if they slow down too much
#     toward slider territory); hb_trajectory (the signature late cut)
#     weighted above vb_trajectory, unlike either fastball.
#   - Slider: velocity weighted well below the fastballs -- a slider's
#     value is centered on movement/bite, not raw speed. hb_trajectory
#     (sweep) weighted highest of any feature for this type.
#     spin_efficiency and the gyro_degree penalty both eased well below
#     the fastballs' -- unlike a fastball, a slider with meaningful gyro
#     ("bullet") spin isn't necessarily a worse slider, so this type
#     doesn't punish it the way 4-Seam Fastball does.
#   - Curveball: velocity weighted lowest of any type -- depth/shape,
#     not speed, is what makes a curveball good. vb_trajectory (vertical
#     drop) weighted highest of any feature for any type; total_spin
#     also weighted above every other type, since spin rate is a
#     particularly well-established driver of curveball depth
#     specifically (unlike for the other types, where it's mostly
#     redundant with movement/efficiency).
#   - Changeup: standalone velocity weighted to ZERO, not just low --
#     superseded by velocity_differential (see that feature's own note
#     below), which is what actually captures a changeup's real value
#     driver now. hb_trajectory (arm-side fade) weighted above
#     vb_trajectory. gyro_degree left at a flat 0.0 -- no clear-cut
#     directional case either way for a changeup, so left neutral rather
#     than guessed.
#   - Splitter: vb_trajectory (the signature sudden vertical drop)
#     weighted highest of any feature for this type. total_spin given a
#     small NEGATIVE weight, the only type where it is -- splitters are
#     commonly described as intentionally low-spin pitches, where LESS
#     spin is part of what produces the tumbling action, not more. This
#     is the single most speculative weight in this whole scorecard
#     (least literature specifically on splitters of the three sources
#     reviewed, and GBO's own Splitter sample is currently far below
#     MIN_STUFF_TRAINING_PITCHES, so it won't be exercised until there's
#     more data anyway) -- flag to revisit first if anything here looks
#     wrong once Splitter has enough pitches to actually score.
#
# velocity_differential (Sept 2026, Ryker's follow-up call): this
# pitch's own velocity minus the SAME pitcher's own average velocity on
# their primary fastball (see profile_queries.
# team_pitcher_primary_fastball_velocity), sign-flipped so a bigger
# gap -- more separation -- is a bigger POSITIVE number, matching this
# module's "higher = better" convention. Currently weighted only for
# Changeup, where velocity separation from the fastball is widely
# treated as the pitch's central value driver, well ahead of the
# changeup's own standalone velocity (which is why Changeup's own
# "velocity" entry is zeroed out above, not just lowered). Left at 0.0
# for every other type for now -- Splitter is a plausible future
# candidate for the same reasoning (a splitter also plays off the
# fastball), deliberately not added yet since Splitter doesn't have
# enough real-game data to fit a model at all right now (see
# MIN_STUFF_TRAINING_PITCHES), so there's nothing to validate it
# against; revisit once it does. A pitcher whose own fastball reference
# can't be computed (see MIN_PITCHER_FASTBALL_VELO_PITCHES) simply has
# this feature come back None for their pitches -- same graceful
# degradation as any other missing feature, not an error.
#
# A pitch type with no entry below (the unused legacy "Fastball" catalog
# row -- see pitch_type_config.py's docstring for why it's unused going
# forward -- or any future/unrecognized label) falls back to 4-Seam
# Fastball's weights via _stuff_plus_weights_for, matching the app's
# existing convention elsewhere that an unclassified straight fastball
# reading is assumed to be 4-seam (see migrations/
# migrate_fastball_to_4seam.py).
#
# Not a validated set of numbers -- a starting point Ryker can adjust
# per type once he's seen how each one scores real pitchers, same
# caveat as PITCHING_PLUS_STUFF_WEIGHT below.
STUFF_PLUS_FIXED_WEIGHTS = {
    "4-Seam Fastball": {
        "velocity": 3.0,
        "vb_trajectory": 1.75,
        "hb_trajectory": 0.75,
        "total_spin": 0.5,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 2.0,
        "gyro_degree": -1.0,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
    "2-Seam Fastball": {
        "velocity": 3.0,
        "vb_trajectory": 0.75,
        "hb_trajectory": 1.75,
        "total_spin": 0.5,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 1.25,
        "gyro_degree": -0.5,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
    "Cutter": {
        "velocity": 2.25,
        "vb_trajectory": 1.0,
        "hb_trajectory": 1.5,
        "total_spin": 0.5,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 1.0,
        "gyro_degree": -0.5,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
    "Slider": {
        "velocity": 1.5,
        "vb_trajectory": 1.0,
        "hb_trajectory": 2.0,
        "total_spin": 0.75,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 0.5,
        "gyro_degree": -0.25,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
    "Curveball": {
        "velocity": 0.75,
        "vb_trajectory": 2.25,
        "hb_trajectory": 0.75,
        "total_spin": 1.0,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 1.25,
        "gyro_degree": -0.5,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
    "Changeup": {
        "velocity": 0.0,
        "vb_trajectory": 1.25,
        "hb_trajectory": 1.5,
        "total_spin": 0.25,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 0.75,
        "gyro_degree": 0.0,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 2.5,
    },
    "Splitter": {
        "velocity": 0.5,
        "vb_trajectory": 2.0,
        "hb_trajectory": 0.75,
        "total_spin": -0.5,
        "spin_axis_offset": 0.25,
        "spin_efficiency": 0.25,
        "gyro_degree": -0.25,
        "release_height": 0.0,
        "release_side": 0.0,
        "velocity_differential": 0.0,
    },
}


def _stuff_plus_weights_for(pitch_type_label):
    """STUFF_PLUS_FIXED_WEIGHTS[pitch_type_label], or 4-Seam Fastball's
    weights as a fallback for any label with no entry (see
    STUFF_PLUS_FIXED_WEIGHTS's comment for why 4-Seam Fastball
    specifically is the fallback). Always returns a fresh dict copy, not
    a reference to the shared module-level one, so a caller can't
    accidentally mutate it through a returned model."""
    return dict(STUFF_PLUS_FIXED_WEIGHTS.get(pitch_type_label, STUFF_PLUS_FIXED_WEIGHTS["4-Seam Fastball"]))


def _spin_axis_offset(spin_axis_degrees):
    """spin_axis_degrees (rapsodo_conventions.spin_clock_to_degrees's
    0-360 clock-face convention, 0 = 12:00 = pure backspin) can't be fed
    into a linear regression as-is -- it's circular, so 359 and 1 are
    nearly the same spin orientation but numerically nearly maximally
    far apart, which would badly confuse an OLS fit. Folds it onto a
    single 0-180 "how far this pitch's spin axis sits from pure
    backspin" value instead -- well-behaved and monotonic, at the cost
    of not distinguishing which SIDE it's off-axis toward.
    Deliberately does NOT attempt a pitcher-handedness mirror correction
    the way release_side/horizontal break already get (see
    rapsodo_conventions.py) -- whether spin axis needs one is still an
    open question per that module's own documented caveat about
    confirming Rapsodo's clock-direction convention; revisit once
    that's settled rather than guessing a correction now."""
    if spin_axis_degrees is None:
        return None
    degrees = float(spin_axis_degrees) % 360.0
    return min(degrees, 360.0 - degrees)


def _stuff_plus_features(rapsodo_pitch, pitcher_fastball_velo=None):
    """Extract Stuff+'s physical inputs from one RapsodoPitch, in the form
    used consistently for BOTH fitting and scoring. vb_trajectory/
    hb_trajectory (actual measured vertical/horizontal break) are taken
    as magnitude (abs) -- raw sign encodes break DIRECTION (arm-side vs.
    glove-side, rise vs. drop), which varies by pitch type and isn't
    itself a quality signal on its own (a slider breaking hard glove-side
    and a sinker breaking hard arm-side are both "good break," just in
    opposite raw directions). More break in a pitch's own characteristic
    direction is what's actually valued; using magnitude here is a
    documented V1 simplification versus a direction-aware weighting (see
    module docstring). spin_axis_offset is derived, see that function.
    Every other feature (velocity, total_spin, spin_efficiency,
    gyro_degree, release_height/side) is used as reported -- none of
    them have the same sign-ambiguity problem break does.
    release_extension was deliberately left out here -- see
    STUFF_PLUS_FEATURE_NAMES's comment for the live-data finding that
    ruled it out (a widespread literal-0.000 sentinel in real-game
    Rapsodo Live captures, not a real reading).

    pitcher_fastball_velo (Sept 2026, Ryker's follow-up call): this SAME
    pitcher's own average velocity on their primary fastball, from
    profile_queries.team_pitcher_primary_fastball_velocity -- feeds
    velocity_differential, currently the only feature this function
    can't compute purely from rapsodo_pitch's own columns. None (the
    default) when the caller has no per-pitcher reference to give
    (nothing fit yet, or this pitcher's own fastball sample is too thin
    -- see MIN_PITCHER_FASTBALL_VELO_PITCHES), in which case
    velocity_differential comes back None too, same graceful
    degradation as a missing physical reading."""
    velocity = float(rapsodo_pitch.velocity) if rapsodo_pitch.velocity is not None else None
    return {
        "velocity": velocity,
        "vb_trajectory": abs(float(rapsodo_pitch.vb_trajectory)) if rapsodo_pitch.vb_trajectory is not None else None,
        "hb_trajectory": abs(float(rapsodo_pitch.hb_trajectory)) if rapsodo_pitch.hb_trajectory is not None else None,
        "total_spin": float(rapsodo_pitch.total_spin) if rapsodo_pitch.total_spin is not None else None,
        "spin_axis_offset": _spin_axis_offset(rapsodo_pitch.spin_axis_degrees),
        "spin_efficiency": float(rapsodo_pitch.spin_efficiency) if rapsodo_pitch.spin_efficiency is not None else None,
        "gyro_degree": float(rapsodo_pitch.gyro_degree) if rapsodo_pitch.gyro_degree is not None else None,
        "release_height": float(rapsodo_pitch.release_height) if rapsodo_pitch.release_height is not None else None,
        "release_side": float(rapsodo_pitch.release_side) if rapsodo_pitch.release_side is not None else None,
        # Sign-flipped (reference minus this pitch, not this pitch minus
        # reference) so MORE separation from the pitcher's own fastball
        # is a bigger POSITIVE number -- matching this module's
        # "higher = better" convention. A changeup that's slower than
        # its own pitcher's fastball (the normal case) gets a positive
        # value here; a changeup thrown nearly as hard as the fastball
        # (little deception) gets a value near zero or negative.
        "velocity_differential": (
            pitcher_fastball_velo - velocity
            if pitcher_fastball_velo is not None and velocity is not None
            else None
        ),
    }


def fit_stuff_plus_model(training_pairs, pitch_type_label, pitcher_fastball_velocities=None):
    """training_pairs: list of (RapsodoPitch, run_value) for ONE
    canonical pitch type -- caller groups by pitch_type_id/normalized
    name first (same convention every baseline in this module uses) and
    supplies ONLY pitches that have a real run_value, i.e. a RapsodoPitch
    linked to a GamePitch whose run_value is set (see
    profile_queries.team_stuff_plus_training_pitches). pitch_type_label
    is that SAME canonical pitch type's name (PitchType.type_name) --
    it's what selects which of STUFF_PLUS_FIXED_WEIGHTS's per-type
    dicts this model uses (see _stuff_plus_weights_for); passing the
    wrong label silently scores this type against another type's
    weights, so callers must pass the same label they grouped
    training_pairs by. Kept training_pairs' shape for backward
    compatibility with the existing caller, but as of the Sept 2026
    methodology fix (see module docstring) run_value is no longer fit
    against anything -- Stuff+'s weights are now fixed per type, not a
    per-pitch-type regression. run_value is still required here
    defensively, to keep this scoped to real, run-value-linkable game
    pitches rather than bullpen-only readings, matching every other
    baseline builder in this module's team-scoping convention -- not
    because anything is learned from its value.

    pitcher_fastball_velocities: optional {player_id: float}, each
    pitcher's own average primary-fastball velocity (see
    profile_queries.team_pitcher_primary_fastball_velocity) -- feeds
    velocity_differential (see _stuff_plus_features), currently only
    given a nonzero weight for Changeup. Omitted (None), every row's
    velocity_differential simply comes back None, same as any other
    missing feature. The dict this model is fit with is stored on the
    returned model itself (see below) so stuff_plus() can look a
    pitcher's own reference back up at SCORING time too, without every
    caller needing to pass it through separately.

    Computes feature_baseline (this type's training-population mean/
    stdev per feature) and prediction_baseline (the mean/stdev of the
    fixed-weight composite across the training population) the same way
    the old fitted version did -- both are plain descriptive statistics,
    not fitted parameters, so they stay real and GBO-data-derived even
    though the weights themselves no longer are. This is what lets a
    raw composite be standardized against this pitch type's own team
    population and re-centered so 100 = this type's own team average and
    10 points = 1 SD, same scale as every other score in this module.

    A training row is required to have every feature THIS TYPE actually
    weights nonzero (dropped listwise if any of those are missing --
    imputing a value into an already-small sample would just be
    inventing data), but NOT features this type weights at 0.0. That
    matters as of the Sept 2026 velocity_differential addition: most
    types weight it 0.0, and requiring it anyway would silently shrink
    their training populations over a feature their own composite never
    uses (the same latent issue release_height/release_side would have
    caused too, now fixed for all of them at once).

    Returns None if fewer than MIN_STUFF_TRAINING_PITCHES complete rows
    are available -- descriptive statistics need far less data than a
    regression fit did, but a baseline built from a handful of pitches
    still swings wildly with every new pitch logged (same caveat
    MIN_BASELINE_PITCHES documents for Location+). Otherwise a model
    dict:
        {"feature_baseline": {feature: (mean, stdev)},
         "quality_weights": {feature: float},
         "prediction_baseline": (mean, stdev),
         "pitcher_fastball_velocities": {player_id: float},
         "n": int}
    quality_weights is pitch_type_label's own entry in
    STUFF_PLUS_FIXED_WEIGHTS (or 4-Seam Fastball's, as a fallback --
    see _stuff_plus_weights_for), copied per call so a caller can't
    accidentally mutate the shared module-level dict through a returned
    model. feature_baseline only has entries for features this type
    actually weights nonzero -- stuff_plus() already skips any weight
    whose feature_baseline entry is missing, so this needs no special
    handling there."""
    weights_for_type = _stuff_plus_weights_for(pitch_type_label)
    required_features = tuple(name for name in STUFF_PLUS_FEATURE_NAMES if weights_for_type.get(name, 0.0))
    pitcher_fastball_velocities = dict(pitcher_fastball_velocities or {})

    rows = []
    for rapsodo_pitch, run_value in training_pairs:
        if run_value is None:
            continue
        pitcher_velo = pitcher_fastball_velocities.get(rapsodo_pitch.player_id)
        features = _stuff_plus_features(rapsodo_pitch, pitcher_velo)
        if any(features[name] is None for name in required_features):
            continue
        rows.append(features)

    n = len(rows)
    if n < MIN_STUFF_TRAINING_PITCHES:
        return None

    feature_baseline = {}
    for name in required_features:
        vals = [f[name] for f in rows]
        # `or 1e-9` guards a (practically impossible, for continuous
        # physical readings) exactly-zero-variance feature from a
        # division-by-zero -- when every value is identical, (value -
        # mean) is also 0 for every row, so the guard changes nothing.
        feature_baseline[name] = (mean(vals), stdev(vals) or 1e-9)

    quality_weights = weights_for_type

    composites = [
        sum(quality_weights[name] * (f[name] - feature_baseline[name][0]) / feature_baseline[name][1]
            for name in required_features)
        for f in rows
    ]
    prediction_baseline = (mean(composites), stdev(composites))

    return {
        "feature_baseline": feature_baseline,
        "quality_weights": quality_weights,
        "prediction_baseline": prediction_baseline,
        "pitcher_fastball_velocities": pitcher_fastball_velocities,
        "n": n,
    }


def stuff_plus(rapsodo_pitch, model):
    """One RapsodoPitch -- bullpen OR game-linked, scoring never needs an
    outcome, only the fitted model does -- against a fitted `model` (see
    fit_stuff_plus_model) for the SAME canonical pitch type; that scoping
    is the caller's responsibility, same as every other grade in this
    module. Returns None if no model exists yet for this pitch type (not
    enough real-game data to fit it -- see MIN_STUFF_TRAINING_PITCHES) or
    this pitch has none of the features the model needs.

    No separate pitcher_fastball_velocities parameter here (unlike
    fit_stuff_plus_model) -- this pitch's own pitcher's fastball
    reference is looked up from model["pitcher_fastball_velocities"]
    (see fit_stuff_plus_model), keyed by rapsodo_pitch.player_id, so
    every existing caller of this function keeps working unchanged and
    automatically gets velocity_differential once the model it's
    scoring against was fit with it.

    Composite is the raw weighted sum of standardized features (a
    feature this pitch is missing simply drops out of the sum, same as
    assuming that feature sits at its own team average -- there's no
    dividing-by-partial-weight renormalization here, unlike the old
    equal-weights version, since these weights no longer sum to 1 and
    dividing by whatever subset is present would shift the scale
    inconsistently pitch to pitch)."""
    if model is None:
        return None
    pitcher_velo = model.get("pitcher_fastball_velocities", {}).get(rapsodo_pitch.player_id)
    features = _stuff_plus_features(rapsodo_pitch, pitcher_velo)
    composite = 0.0
    used_any = False
    for name, weight in model["quality_weights"].items():
        value = features.get(name)
        b_mean, b_sd = model["feature_baseline"].get(name, (None, None))
        if value is None or b_mean is None or not b_sd:
            continue
        composite += weight * (value - b_mean) / b_sd
        used_any = True
    if not used_any:
        return None
    p_mean, p_sd = model["prediction_baseline"]
    if not p_sd:
        return None
    return round(100 + 10 * (composite - p_mean) / p_sd, 1)


# ---------------------------------------------------------------------------
# Location+ -- actual location + count-adjacent context (pitch type here,
# see module docstring for why count itself is deferred) only. No
# physical characteristics, no intent -- matches the real Location+
# definition (stringer-judged intent doesn't add predictive value per the
# FanGraphs primer, which is also why GBO's own intended-zone tracking is
# a separate Command/execution metric, not an input here).
# ---------------------------------------------------------------------------

def team_location_plus_baseline(game_pitches):
    """Mean+stdev of GamePitch.run_value, grouped by (attack zone tier,
    canonical pitch type) -- the cell a pitch's location is graded
    against (plan doc: "bucket pitches into zone-region x pitch-type
    cells, compute the average run_value for each cell across the team's
    own history"). V1 simplification: no count-group split -- see module
    docstring.

    Caller supplies every already-loaded, already-located GamePitch in
    whatever pool counts as "the team" (same team-scoping convention as
    command_metrics.py's Command+: every located pitch from our own
    pitchers across every game, intrasquad and real opponents alike, not
    just bullpens -- bullpens have no run value to grade against).

    Returns {(attack_zone, pitch_type_label): (mean, stdev, n)}."""
    values_by_cell = {}
    for pitch in game_pitches:
        if pitch.run_value is None or pitch.actual_plate_x is None or pitch.actual_plate_z is None:
            continue
        zone = classify_attack_zone(pitch.actual_plate_x, pitch.actual_plate_z)
        label = pitch.pitch_type.type_name if pitch.pitch_type is not None else "Unspecified"
        values_by_cell.setdefault((zone, label), []).append(float(pitch.run_value))

    baseline = {}
    for cell, values in values_by_cell.items():
        n = len(values)
        baseline[cell] = (round(mean(values), 4), round(stdev(values), 4), n) if n >= 2 else (None, None, n)
    return baseline


def location_plus(game_pitch, baseline):
    """One GamePitch -> Location+ against `baseline` (see
    team_location_plus_baseline). LOWER run_value is BETTER for the
    pitcher (a pitch that helped the batter scores a bigger run_value),
    so the sign is flipped from the usual pattern -- same convention as
    command_metrics.command_plus:

        location_plus = 100 + 10 * (baseline_mean - run_value) / baseline_stdev

    None if the pitch has no actual location or run_value yet, or its
    (zone, pitch type) cell doesn't have a usable (n>=2) baseline."""
    if game_pitch.run_value is None or game_pitch.actual_plate_x is None or game_pitch.actual_plate_z is None:
        return None
    zone = classify_attack_zone(game_pitch.actual_plate_x, game_pitch.actual_plate_z)
    label = game_pitch.pitch_type.type_name if game_pitch.pitch_type is not None else "Unspecified"
    b_mean, b_sd, _b_n = baseline.get((zone, label), (None, None, 0))
    if b_mean is None or not b_sd:
        return None
    return round(100 + 10 * (b_mean - float(game_pitch.run_value)) / b_sd, 1)


# ---------------------------------------------------------------------------
# Pitching+ -- see module docstring for why this is a blend, not a third
# model, at this sample size.
# ---------------------------------------------------------------------------

# Placeholder, not a validated number -- leans toward Stuff+ per the
# FanGraphs primer's finding that Stuff+ drives most of the year-to-year
# stability of real Pitching+. Revisit once there's enough of GBO's own
# outcome data to check whether this weighting actually predicts
# performance (plan doc section 7, Phase 2).
PITCHING_PLUS_STUFF_WEIGHT = 0.6


def pitching_plus(stuff_plus_value, location_plus_value):
    """Transparent weighted blend of a pitch's Stuff+ and Location+
    scores. Returns None if EITHER input is missing -- Pitching+ needs
    both a Rapsodo-linked physical read and a graded location, not a
    partial score from just one side."""
    if stuff_plus_value is None or location_plus_value is None:
        return None
    return round(
        PITCHING_PLUS_STUFF_WEIGHT * stuff_plus_value + (1 - PITCHING_PLUS_STUFF_WEIGHT) * location_plus_value,
        1,
    )


# ---------------------------------------------------------------------------
# Arsenal -- GBO's own extension, not part of the FanGraphs primer.
# ---------------------------------------------------------------------------

def _avg(values):
    vals = [v for v in values if v is not None]
    return round(mean(vals), 1) if vals else None


def arsenal_summary(pitch_type_grades):
    """Usage-weighted roll-up across one pitcher's full pitch mix.

    pitch_type_grades: {pitch_type_label: {"n": int,
    "stuff_plus": [values], "location_plus": [values],
    "pitching_plus": [values]}} -- caller pre-groups already-graded
    per-pitch values (from stuff_plus/location_plus/pitching_plus above)
    by canonical pitch type.

    Returns a list of rows, one per pitch type, sorted by usage
    descending: {"Pitch Type", "Usage %", "Pitches", "Stuff+",
    "Location+", "Pitching+", "Reliable"} -- "Reliable" is True only when
    the type has at least MIN_BASELINE_PITCHES pitches, same floor used
    everywhere else in this module.

    Deliberately does NOT flag "is a plus pitch underused" or similar
    pitch-mix diagnostics yet, even though the plan doc names that as an
    Arsenal goal -- that needs a decision on what usage should even be
    compared against (the pitcher's own history, the rest of the staff at
    that pitch type, handedness-specific norms), which hasn't been made.
    Flag to Ryker once real Stuff+/Location+ numbers exist to look at --
    inventing a threshold now would just be a guess nobody's validated."""
    total_pitches = sum(g["n"] for g in pitch_type_grades.values())
    rows = []
    for label, g in pitch_type_grades.items():
        n = g["n"]
        rows.append({
            "Pitch Type": label,
            "Usage %": round(n / total_pitches * 100, 1) if total_pitches else None,
            "Pitches": n,
            "Stuff+": _avg(g.get("stuff_plus", [])),
            "Location+": _avg(g.get("location_plus", [])),
            "Pitching+": _avg(g.get("pitching_plus", [])),
            "Reliable": n >= MIN_BASELINE_PITCHES,
        })
    rows.sort(key=lambda r: r["Usage %"] or 0, reverse=True)
    return rows


# ---------------------------------------------------------------------------
# Tunneling+ -- Sept 2026 addition (Ryker: "add height adjusted vertical
# approach angle [HAVAA] to pitcher profile", then "keep working on the
# trajectory model for the tunneling+ model" -- see
# HITTER-PITCHER-LAB-PLAN.md sections 3/5 for the original scope: per
# secondary pitch, Tunnel distance (separation at the decision point),
# Plate (separation at the plate), Late break, Ratio, and a Grade).
# Definitions follow Baseball Prospectus's published "Introducing Pitch
# Tunnels" methodology (Pavlidis & Long, 2017,
# https://www.baseballprospectus.com/news/article/31030/prospectus-feature-introducing-pitch-tunnels/)
# -- same house rule as pitch_trajectory.py: borrow a published,
# externally-validated methodology rather than invent tunnel/plate/ratio
# definitions from scratch. Scored on GBO's own "+" scale (100 = this
# team's average, 10 points = 1 SD, per Ryker's call) instead of BP's
# own scale, for consistency with every other grade in this module.
#
# Reads RapsodoPitch.trajectory_json -- already computed at import time
# and backfilled for existing rows (see pitch_trajectory.py and
# migrations/backfill_trajectory_json.py) -- rather than recomputing a
# trajectory here, so this section keeps the same "this module never
# does its own DB queries or physics, only scores already-loaded rows"
# boundary as the rest of pitch_grading.py.
# ---------------------------------------------------------------------------

# BP's published "tunnel point": roughly 167ms before a pitch reaches the
# plate for a typical fastball -- the point their research ties to when a
# hitter must commit to swing. BP expresses it as a fixed DISTANCE from
# the plate (~23.8 ft) rather than a per-pitch time, so two pitches in a
# pair are always compared at the same physical point in space regardless
# of either one's own speed. Used as published, not re-derived.
TUNNEL_POINT_DISTANCE_FROM_PLATE_FT = 23.8

# Floor for the Tunnel measurement (the Ratio denominator) -- two pitches
# whose paths happen to cross almost exactly AT the tunnel point would
# otherwise produce a divide-by-near-zero Ratio in the hundreds, which
# isn't a real deception signal, just noise from where their specific
# paths happened to intersect. Same spirit as command_metrics.py's
# `not stdev` guard: clip the denominator instead of discarding the pair
# entirely.
MIN_TUNNEL_FLOOR_IN = 0.5

# Real consecutive-pitch pairs pooled per (pitcher, secondary pitch type)
# before trusting an averaged Tunnel/Plate/Ratio number enough to grade
# it -- an average built from 2-3 sequences is noise, not a real read on
# how that pitcher tunnels that pitch off his fastball. Same "starting
# floor, not a statistically rigorous minimum" caveat as
# MIN_PITCHER_FASTBALL_VELO_PITCHES above; set lower than
# MIN_BASELINE_PITCHES because real back-to-back SEQUENCES (not raw
# pitch counts) are the scarcer resource here.
MIN_TUNNELING_PAIRS = 8


def _trajectory_xy_at_distance_from_plate(trajectory_json, distance_from_plate_ft):
    """(x, y) in feet from a cached RapsodoPitch.trajectory_json payload
    (see pitch_trajectory.compute_trajectory's docstring for the sample
    shape), at the point `distance_from_plate_ft` feet before the plate
    -- linearly interpolated between the cached samples (already spaced
    pitch_trajectory.SAMPLE_DT = 0.01s apart, so interpolation error is a
    small fraction of an inch). Returns None if trajectory_json is
    missing/malformed, or doesn't reach back that far -- would mean an
    implausibly long release_extension; treated as unavailable, never
    extrapolated past real computed data."""
    if not trajectory_json:
        return None
    samples = trajectory_json.get("samples")
    flight_distance = trajectory_json.get("flight_distance_ft")
    if not samples or flight_distance is None:
        return None
    target_z = flight_distance - distance_from_plate_ft
    if target_z < samples[0]["z"]:
        return None
    prev = samples[0]
    for s in samples[1:]:
        if s["z"] >= target_z:
            if s["z"] == prev["z"]:
                return (prev["x"], prev["y"])
            frac = (target_z - prev["z"]) / (s["z"] - prev["z"])
            return (
                prev["x"] + frac * (s["x"] - prev["x"]),
                prev["y"] + frac * (s["y"] - prev["y"]),
            )
        prev = s
    return None


def tunnel_pair_metrics(pitch_a, pitch_b):
    """Raw tunneling numbers for ONE pair of pitches -- caller decides
    which two pitches count as a real "pair" (see
    consecutive_pitch_pairs below); this function only does the geometry
    once given two already-chosen RapsodoPitch rows.

    Returns {"tunnel_in", "plate_in", "late_break_in", "ratio"} --
    tunnel_in/plate_in/late_break_in in inches (matching HB/VB's own
    units elsewhere in the app); ratio is unitless (Plate/Tunnel, BP's
    "Break:Tunnel Ratio" -- higher means the two pitches stayed closer
    together through the decision point and diverged MORE after it,
    i.e. more deceptive). Returns None if either pitch is missing a
    cached trajectory or a real plate-crossing location.

    late_break_in = plate_in - tunnel_in (BP's "Post-Tunnel Break") --
    how much separation was added AFTER the decision point, as a plain
    inches number alongside the ratio."""
    if pitch_a.trajectory_json is None or pitch_b.trajectory_json is None:
        return None
    if pitch_a.plate_x_ft is None or pitch_a.plate_z_ft is None:
        return None
    if pitch_b.plate_x_ft is None or pitch_b.plate_z_ft is None:
        return None

    xy_a = _trajectory_xy_at_distance_from_plate(pitch_a.trajectory_json, TUNNEL_POINT_DISTANCE_FROM_PLATE_FT)
    xy_b = _trajectory_xy_at_distance_from_plate(pitch_b.trajectory_json, TUNNEL_POINT_DISTANCE_FROM_PLATE_FT)
    if xy_a is None or xy_b is None:
        return None

    tunnel_in = math.hypot(xy_a[0] - xy_b[0], xy_a[1] - xy_b[1]) * 12.0
    plate_in = math.hypot(
        float(pitch_a.plate_x_ft) - float(pitch_b.plate_x_ft),
        float(pitch_a.plate_z_ft) - float(pitch_b.plate_z_ft),
    ) * 12.0
    return {
        "tunnel_in": round(tunnel_in, 2),
        "plate_in": round(plate_in, 2),
        "late_break_in": round(plate_in - tunnel_in, 2),
        "ratio": round(plate_in / max(tunnel_in, MIN_TUNNEL_FLOOR_IN), 2),
    }


def consecutive_pitch_pairs(pitches):
    """Given ONE outing's pitches (a single bullpen session, or one
    pitcher's real-game pitches within a single plate appearance)
    already ordered the way they were actually thrown, returns adjacent
    (pitch_i, pitch_{i+1}) tuples -- real back-to-back sequences only,
    since tunneling is fundamentally about what the hitter just saw
    right before the NEXT pitch arrives, not a comparison between two
    pitches thrown innings (or bullpens) apart. Caller owns grouping
    pitches into outings/plate-appearances and ordering them (same
    "caller owns every DB query" boundary as the rest of this module)
    -- see pitcher_profile.py's _tunneling_pairs_for_player for the real
    grouping logic (bullpen: same bullpen_id, ordered by pitch_number;
    game: same plate appearance, ordered by pa_pitch_number)."""
    return list(zip(pitches, pitches[1:]))


def tunnel_type_pair_summary(all_pairs, type_a, type_b):
    """Averages tunnel_pair_metrics across every pair in `all_pairs`
    (RapsodoPitch tuples, e.g. from consecutive_pitch_pairs) whose two
    pitch-type labels are exactly {type_a, type_b}, in EITHER order --
    tunneling is symmetric (how close two pitches' paths stayed through
    the decision point is the same fact regardless of which one was
    thrown first), so a fastball-then-slider sequence and a
    slider-then-fastball sequence both count toward the same
    (fastball, slider) summary.

    Returns None if fewer than MIN_TUNNELING_PAIRS qualifying pairs are
    found (see that constant) -- an average from a handful of sequences
    isn't a real read on how this pitcher tunnels that pitch pair yet."""
    wanted = {type_a, type_b}
    tunnel_vals, plate_vals, late_vals, ratio_vals = [], [], [], []
    for p1, p2 in all_pairs:
        if {pitch_type_label(p1), pitch_type_label(p2)} != wanted:
            continue
        m = tunnel_pair_metrics(p1, p2)
        if m is None:
            continue
        tunnel_vals.append(m["tunnel_in"])
        plate_vals.append(m["plate_in"])
        late_vals.append(m["late_break_in"])
        ratio_vals.append(m["ratio"])

    n = len(ratio_vals)
    if n < MIN_TUNNELING_PAIRS:
        return None
    return {
        "n": n,
        "tunnel_in": round(mean(tunnel_vals), 2),
        "plate_in": round(mean(plate_vals), 2),
        "late_break_in": round(mean(late_vals), 2),
        "ratio": round(mean(ratio_vals), 2),
    }


def team_tunneling_baseline(pitcher_type_pair_summaries):
    """Team-wide mean+stdev of Ratio, grouped by secondary pitch type --
    the population a pitcher's OWN (fastball, secondary) Ratio gets
    graded against for Tunneling+, same shape as every other X_plus
    baseline in this module.

    pitcher_type_pair_summaries: [(secondary_pitch_type_label, summary),
    ...] -- one entry per pitcher per secondary type they throw enough
    of to have a real tunnel_type_pair_summary (see above); caller
    builds this list across every pitcher on the team.

    Returns {secondary_pitch_type_label: (mean_ratio, stdev_ratio, n)},
    n counted in PITCHERS (one Ratio per pitcher per type), not raw
    pitch pairs -- matches command_metrics.team_command_plus_baseline's
    own "one number per pitcher feeds the baseline" pooling."""
    by_type = {}
    for secondary_type, summary in pitcher_type_pair_summaries:
        if summary is None:
            continue
        by_type.setdefault(secondary_type, []).append(summary["ratio"])

    baseline = {}
    for secondary_type, ratios in by_type.items():
        n = len(ratios)
        baseline[secondary_type] = (round(mean(ratios), 4), round(stdev(ratios), 4), n) if n >= 2 else (None, None, n)
    return baseline


def tunneling_plus(summary, secondary_pitch_type, baseline):
    """One pitcher's Tunneling+ for one secondary pitch type -- how this
    pitcher's own (fastball, that type) Ratio (see
    tunnel_type_pair_summary) compares to the rest of the team's Ratio
    for that same type:

        tunneling_plus = 100 + 10 * (ratio - baseline_mean) / baseline_stdev

    HIGHER ratio is better for the pitcher (more separation added after
    the decision point relative to how close together the pitches
    started), so unlike Command+/Location+ this is NOT sign-flipped --
    same orientation as Stuff+.

    None if `summary` is None (not enough real sequences yet -- see
    MIN_TUNNELING_PAIRS) or the team baseline for this pitch type isn't
    usable yet (fewer than 2 pitchers have a real summary for it)."""
    if summary is None:
        return None
    b_mean, b_sd, _b_n = baseline.get(secondary_pitch_type, (None, None, 0))
    if b_mean is None or not b_sd:
        return None
    return round(100 + 10 * (summary["ratio"] - b_mean) / b_sd, 1)
