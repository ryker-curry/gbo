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

V1 simplifications, called out explicitly rather than silently guessed
at (see plan doc sections 4 and 8 for the open items these map to):
  - Stuff+ uses an equal-weighted-by-default composite of velocity,
    |induced vertical break|, |horizontal break|, and total spin,
    per canonical pitch type -- not the fastball-differential-weighted
    design the plan doc sketched. STUFF_PLUS_WEIGHTS below is the one
    place to tune this once real scores exist to sanity-check against
    what Ryker's eyes tell him about the staff.
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

from strike_zone import classify_attack_zone

# Same floor as command_metrics.py's MIN_BASELINE_PITCHES, same caveat:
# a baseline built from a handful of pitches swings wildly with every new
# pitch logged and isn't trustworthy yet. 20 is a starting floor, not a
# statistically rigorous minimum -- easy to raise once GBO has more of a
# season's worth of data to see how noisy these scores actually are
# below that in practice.
MIN_BASELINE_PITCHES = 20


# ---------------------------------------------------------------------------
# Stuff+ -- physical characteristics only (no location, no outcome, no
# count -- matches the real Stuff+ definition).
# ---------------------------------------------------------------------------

# Equal-weighted V1 default (see module docstring). Kept as a plain dict
# rather than a hardcoded formula so it's the one obvious place to change
# once real Stuff+ scores exist to tune against.
STUFF_PLUS_WEIGHTS = {
    "velocity": 0.25,
    "vb_spin": 0.25,
    "hb_spin": 0.25,
    "total_spin": 0.25,
}


def _stuff_plus_features(rapsodo_pitch):
    """Extract Stuff+'s physical inputs from one RapsodoPitch, in the form
    used consistently for BOTH baselining and scoring. vb_spin/hb_spin
    (induced vertical/horizontal break) are taken as magnitude (abs) --
    raw sign encodes break DIRECTION (arm-side vs. glove-side, rise vs.
    drop), which varies by pitch type and pitcher handedness and isn't
    itself a quality signal on its own. More break in a pitch's own
    characteristic direction is what's actually valued; using magnitude
    here is a documented V1 simplification versus a direction-aware
    weighting (see module docstring)."""
    return {
        "velocity": float(rapsodo_pitch.velocity) if rapsodo_pitch.velocity is not None else None,
        "vb_spin": abs(float(rapsodo_pitch.vb_spin)) if rapsodo_pitch.vb_spin is not None else None,
        "hb_spin": abs(float(rapsodo_pitch.hb_spin)) if rapsodo_pitch.hb_spin is not None else None,
        "total_spin": float(rapsodo_pitch.total_spin) if rapsodo_pitch.total_spin is not None else None,
    }


def team_stuff_plus_baseline(rapsodo_pitches_for_type):
    """Mean+stdev of each Stuff+ input feature, across every already-loaded
    RapsodoPitch of ONE canonical pitch type -- caller groups by
    pitch_type_id/normalized name before calling (a slider is judged
    against other sliders, not fastballs -- see plan doc's Stuff+
    section). Same caller-owns-the-query convention as
    command_metrics.py's team_command_plus_baseline.

    Returns {feature_name: (mean, stdev, n)}. A feature with fewer than 2
    pitches carrying a value gets (None, None, n) -- can't take a stdev
    of fewer than 2 points."""
    values_by_feature = {}
    for pitch in rapsodo_pitches_for_type:
        for name, value in _stuff_plus_features(pitch).items():
            values_by_feature.setdefault(name, []).append(value)

    baseline = {}
    for name, raw_values in values_by_feature.items():
        vals = [v for v in raw_values if v is not None]
        n = len(vals)
        baseline[name] = (round(mean(vals), 3), round(stdev(vals), 3), n) if n >= 2 else (None, None, n)
    return baseline


def stuff_plus(rapsodo_pitch, baseline):
    """One RapsodoPitch -> Stuff+ against `baseline` (see
    team_stuff_plus_baseline) -- baseline MUST be for the same canonical
    pitch type as this pitch; that scoping is the caller's responsibility,
    same as command_plus's baseline-scoping convention.

    Weighted composite of per-feature z-scores (STUFF_PLUS_WEIGHTS),
    renormalized over only the features that have both a value on this
    pitch AND a usable (n>=2) baseline entry -- a missing Rapsodo field
    (e.g. spin data dropped for one pitch) reduces the composite's inputs
    rather than zeroing out the whole score. Returns None if no feature
    qualifies at all."""
    features = _stuff_plus_features(rapsodo_pitch)
    weighted_sum, weight_total = 0.0, 0.0
    for name, weight in STUFF_PLUS_WEIGHTS.items():
        value = features.get(name)
        b_mean, b_sd, _b_n = baseline.get(name, (None, None, 0))
        if value is None or b_mean is None or not b_sd:
            continue
        z = (value - b_mean) / b_sd
        weighted_sum += z * weight
        weight_total += weight
    if weight_total == 0:
        return None
    return round(100 + 10 * (weighted_sum / weight_total), 1)


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
