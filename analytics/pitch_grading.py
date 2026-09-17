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

V1 simplifications, called out explicitly rather than silently guessed
at (see plan doc sections 4 and 8 for the open items these map to):
  - Stuff+'s regression is a simple per-type linear fit, not the
    fastball-differential-weighted design the plan doc sketched, and
    nowhere near the real FanGraphs decision-tree model -- GBO's pitcher
    count can't support anything more complex without overfitting to
    this specific roster. Revisit once there's a full season or more of
    real-game Rapsodo data to check how well this actually predicts.
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

from statistics import mean, stdev

import numpy as np

from strike_zone import classify_attack_zone

# Same floor as command_metrics.py's MIN_BASELINE_PITCHES, same caveat:
# a baseline built from a handful of pitches swings wildly with every new
# pitch logged and isn't trustworthy yet. 20 is a starting floor, not a
# statistically rigorous minimum -- easy to raise once GBO has more of a
# season's worth of data to see how noisy these scores actually are
# below that in practice. Used by Location+ and by arsenal_summary's
# per-pitcher "Reliable" flag -- NOT by Stuff+ anymore, which fits real
# parameters and needs a bigger floor (see MIN_STUFF_TRAINING_PITCHES).
MIN_BASELINE_PITCHES = 20

# Fitting Stuff+'s regression needs enough RUN-VALUE-BEARING (real-game)
# pitches to trust 10 fitted parameters (9 features + intercept -- see
# STUFF_PLUS_FEATURE_NAMES below, expanded Sept 2026 per Ryker's review
# of the aStuff+/Driveline/Rockland sources against what GBO's own
# Rapsodo import already captures but Stuff+ wasn't using) -- roughly
# 8-10 observations per parameter is a standard rule of thumb for a
# linear fit, rounded up to a clean number here (was 40 for the
# original 5 parameters/4 features -- raised in lockstep with the
# feature count, not left at the old floor, since an under-powered fit
# isn't a more "valid" model just because it still runs). This is a
# team-wide, PER PITCH TYPE floor (see fit_stuff_plus_model) -- distinct
# from MIN_BASELINE_PITCHES above, which just gates a plain mean/stdev.
# release_extension was DROPPED from the feature list (see
# STUFF_PLUS_FEATURE_NAMES comment) after a live-data check found it's
# not just missing sometimes, it's systematically wrong -- so this is
# 9 features, not the 10 briefly considered, and the floor is 80, not
# 90. Real consequence, checked against live data: 4-Seam Fastball
# (135 complete training pitches) clears it comfortably, but 2-Seam
# Fastball (47), Slider (43), Changeup (29), Curveball (14), Splitter
# (8), and Cutter (5) all fall short and will show no Stuff+ until
# more real-game Rapsodo data accumulates for those types. That's the
# honest tradeoff of fitting more parameters, not a bug.
MIN_STUFF_TRAINING_PITCHES = 80


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
    "release_height", "release_side",
)


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


def _stuff_plus_features(rapsodo_pitch):
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
    Rapsodo Live captures, not a real reading)."""
    return {
        "velocity": float(rapsodo_pitch.velocity) if rapsodo_pitch.velocity is not None else None,
        "vb_trajectory": abs(float(rapsodo_pitch.vb_trajectory)) if rapsodo_pitch.vb_trajectory is not None else None,
        "hb_trajectory": abs(float(rapsodo_pitch.hb_trajectory)) if rapsodo_pitch.hb_trajectory is not None else None,
        "total_spin": float(rapsodo_pitch.total_spin) if rapsodo_pitch.total_spin is not None else None,
        "spin_axis_offset": _spin_axis_offset(rapsodo_pitch.spin_axis_degrees),
        "spin_efficiency": float(rapsodo_pitch.spin_efficiency) if rapsodo_pitch.spin_efficiency is not None else None,
        "gyro_degree": float(rapsodo_pitch.gyro_degree) if rapsodo_pitch.gyro_degree is not None else None,
        "release_height": float(rapsodo_pitch.release_height) if rapsodo_pitch.release_height is not None else None,
        "release_side": float(rapsodo_pitch.release_side) if rapsodo_pitch.release_side is not None else None,
    }


def fit_stuff_plus_model(training_pairs):
    """training_pairs: list of (RapsodoPitch, run_value) for ONE
    canonical pitch type -- caller groups by pitch_type_id/normalized
    name first (same convention every baseline in this module uses) and
    supplies ONLY pitches that have a real run_value, i.e. a RapsodoPitch
    linked to a GamePitch whose run_value is set (see
    profile_queries.team_stuff_plus_training_pitches). A bullpen-only
    reading has no run_value to learn from and must never appear here --
    that's what makes this "trained to RV" rather than the old fixed
    equal-weighted guess.

    Fits a linear regression of run_value on this type's 9 standardized
    physical features via ordinary least squares (numpy.linalg.lstsq).
    A full decision-tree model (what real FanGraphs Stuff+ uses) needs
    far more distinct pitchers than GBO has without just memorizing this
    roster; a simple per-type linear fit is the most that's honestly
    supportable at this sample size (see module docstring). Training
    rows missing ANY of the 4 features are dropped (listwise) --
    imputing a value into an already-small sample would just be
    inventing data.

    Lower run_value is better for the pitcher (same sign convention as
    location_plus), so every fitted coefficient is NEGATED before being
    stored as that feature's "quality weight" -- a positive quality
    weight means more of that feature predicts BETTER outcomes, matching
    the "higher composite = better" convention every other score in this
    module uses.

    Returns None if fewer than MIN_STUFF_TRAINING_PITCHES complete rows
    are available -- not enough to trust 10 fitted parameters yet.
    Otherwise a model dict:
        {"feature_baseline": {feature: (mean, stdev)},
         "quality_weights": {feature: float},
         "prediction_baseline": (mean, stdev),
         "n": int}
    feature_baseline is this type's training-population mean/stdev per
    feature (needed to standardize any future pitch, bullpen or game,
    the same way the training data was standardized). prediction_baseline
    is the mean/stdev of the fitted composite ACROSS the training
    population -- it's what lets a raw composite be re-centered so 100 =
    this type's own team average and 10 points = 1 SD, same scale as
    every other score in this module."""
    rows = []
    for rapsodo_pitch, run_value in training_pairs:
        if run_value is None:
            continue
        features = _stuff_plus_features(rapsodo_pitch)
        if any(features[name] is None for name in STUFF_PLUS_FEATURE_NAMES):
            continue
        rows.append((features, float(run_value)))

    n = len(rows)
    if n < MIN_STUFF_TRAINING_PITCHES:
        return None

    feature_baseline = {}
    for name in STUFF_PLUS_FEATURE_NAMES:
        vals = [f[name] for f, _rv in rows]
        # `or 1e-9` guards a (practically impossible, for continuous
        # physical readings) exactly-zero-variance feature from a
        # division-by-zero -- when every value is identical, (value -
        # mean) is also 0 for every row, so the guard changes nothing.
        feature_baseline[name] = (mean(vals), stdev(vals) or 1e-9)

    x = np.ones((n, len(STUFF_PLUS_FEATURE_NAMES) + 1))
    for j, name in enumerate(STUFF_PLUS_FEATURE_NAMES):
        b_mean, b_sd = feature_baseline[name]
        x[:, j + 1] = [(f[name] - b_mean) / b_sd for f, _rv in rows]
    y = np.array([rv for _f, rv in rows])

    coeffs, *_rest = np.linalg.lstsq(x, y, rcond=None)
    quality_weights = {name: -float(coeffs[j + 1]) for j, name in enumerate(STUFF_PLUS_FEATURE_NAMES)}

    composites = [
        sum(quality_weights[name] * (f[name] - feature_baseline[name][0]) / feature_baseline[name][1]
            for name in STUFF_PLUS_FEATURE_NAMES)
        for f, _rv in rows
    ]
    prediction_baseline = (mean(composites), stdev(composites))

    return {
        "feature_baseline": feature_baseline,
        "quality_weights": quality_weights,
        "prediction_baseline": prediction_baseline,
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

    Composite is the raw weighted sum of standardized features (a
    feature this pitch is missing simply drops out of the sum, same as
    assuming that feature sits at its own team average -- there's no
    dividing-by-partial-weight renormalization here, unlike the old
    equal-weights version, since these weights no longer sum to 1 and
    dividing by whatever subset is present would shift the scale
    inconsistently pitch to pitch)."""
    if model is None:
        return None
    features = _stuff_plus_features(rapsodo_pitch)
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
