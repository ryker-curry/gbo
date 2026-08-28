"""
GBO -- Estimated Arm Angle / Estimated VAA / Estimated HAA / fastball
trajectory classification (Aug 2026).

Pure data logic -- no Streamlit/Shiny, no plotly, no database queries,
matching bullpen_metrics.py's own rule ("keep calculations separate
from visualization functions... keep database operations separate from
UI code," spec Section 20). Callers pass plain floats already pulled
off a RapsodoPitch/Player row; nothing here queries the DB or knows
about ORM objects.

IMPORTANT PRECEDENT -- read before touching this file: a Phase 4
flight-path trajectory chart (gravity+drag physics, calibrated per
pitch) was already built once (pitch_trajectory.py, a *different* file
under the project root, plus visualizations/trajectory_chart.py and an
import-time backfill), shipped, and then removed entirely per Ryker's
call after reviewing it live -- "didn't read as useful." See
RapsodoPitch.trajectory_json's and bullpen_dashboard_render.py's
docstrings in the Shiny app root. That attempt rendered a full flight
-path chart; this module is deliberately narrower -- it produces a
single scalar estimate (a number and a short ray/label), not a
simulated trajectory panel, specifically because the earlier attempt's
lesson was that a rendered physics chart didn't earn its place. If
Estimated VAA/HAA also turns out not to read as useful in practice,
that's a real possible outcome here too -- these are geometric/
kinematic ESTIMATES from limited inputs, not measurements, and are
labeled that way everywhere they're displayed (never "Rapsodo VAA" or
"Rapsodo Arm Angle").

Everything below folds in the Aug 2026 correction: pitcher height for
Estimated Arm Angle comes from the EXISTING Player.height_in field
(the one source of truth already used across GBO -- Players page,
Body Comp displays, etc.) -- this module never accepts or stores a
separate height value, and callers are expected to look it up from the
Player row already in hand rather than asking the user for it again.
"""

import math

# ---------------------------------------------------------------------------
# 1. ESTIMATED ARM ANGLE
# ---------------------------------------------------------------------------
# MLB/Statcast convention (baseballsavant.com): 0 degrees = pure sidearm
# (release directly out to the side, no vertical offset from the
# shoulder), 90 degrees = pure overhand (release directly above the
# shoulder, no horizontal offset). This is the same atan2(vertical,
# horizontal) shape either way -- there's no separate "old" vs "new"
# formula, just this one convention, which is what's implemented.

SHOULDER_HEIGHT_FRACTION = 0.70  # estimated shoulder height as a fraction of standing height -- documented assumption, not measured per-player


def calculate_estimated_arm_angle(player_height_in, release_height_ft, release_side_ft):
    """Geometric estimate of arm slot from release point + estimated
    shoulder height. NOT a biomechanical measurement -- see module and
    UI-facing tooltip copy.

    player_height_in: the player's height in inches -- MUST come from
    the existing Player.height_in field (GBO's one source of truth for
    player height). This function does not know or care where the
    caller got it, but the calling convention across this app is
    "look it up from the Player row you already have," never a new
    input field and never a hard-coded average.

    Returns a dict:
      value_degrees   -- rounded to the nearest whole degree, or None
      na_reason        -- short human-readable reason value_degrees is
                          None, or None when a value was produced
      debug             -- dict of the intermediate numbers (shoulder
                          height, vertical difference, horizontal
                          distance) for a debug/dev view; always
                          present even when value_degrees is None, with
                          whichever pieces could be computed
    """
    debug = {"shoulder_height_ft": None, "vertical_difference_ft": None, "horizontal_distance_ft": None}

    if player_height_in is None:
        return {"value_degrees": None, "na_reason": "Pitcher height required (set it on the Players page)", "debug": debug}
    if release_height_ft is None:
        return {"value_degrees": None, "na_reason": "Release height required", "debug": debug}
    if release_side_ft is None:
        return {"value_degrees": None, "na_reason": "Release side required", "debug": debug}

    height_in = float(player_height_in)
    shoulder_height_ft = (height_in / 12.0) * SHOULDER_HEIGHT_FRACTION
    vertical_difference = float(release_height_ft) - shoulder_height_ft
    # abs() is deliberate -- the sign of release side must never change
    # the magnitude of the angle (a pitcher releasing 2 ft to either
    # side of center has the same arm slot either way). Throwing hand
    # is retained separately by callers for left/right VISUAL
    # orientation only -- it never enters this calculation.
    horizontal_distance = abs(float(release_side_ft))

    debug["shoulder_height_ft"] = round(shoulder_height_ft, 3)
    debug["vertical_difference_ft"] = round(vertical_difference, 3)
    debug["horizontal_distance_ft"] = round(horizontal_distance, 3)

    # atan2 handles horizontal_distance == 0 correctly (release directly
    # over the shoulder, no horizontal offset -- a real, if rare, case)
    # without a divide-by-zero: it returns +/-90 degrees as appropriate
    # instead of raising.
    angle_degrees = math.atan2(vertical_difference, horizontal_distance) * 180.0 / math.pi
    return {"value_degrees": round(angle_degrees), "na_reason": None, "debug": debug}


# ---------------------------------------------------------------------------
# 2. TRAJECTORY MODEL (Estimated VAA / Estimated HAA)
# ---------------------------------------------------------------------------
# Do NOT calculate VAA as atan(release angle) -- that's the direction
# the ball LEAVES the hand, not the direction of the velocity vector as
# it CROSSES the plate (Rapsodo's own definition of VAA). This module
# instead fits an "effective parabola" through the 3 things actually
# known about the pitch's vertical (or horizontal) path:
#   1. y(0)              = release height (or release side)     -- known
#   2. y'(0)              = tan(release angle) (or horizontal angle) -- known, sets the INITIAL slope
#   3. y(flight_distance) = strike zone height in real feet, i.e.
#                           RapsodoPitch.plate_z_ft (or plate_x_ft)     -- known, the ACTUAL measured plate crossing
# A parabola y = a*x^2 + b*x + c has exactly 3 free parameters, so
# these 3 real, measured quantities pin it down uniquely -- no drag
# coefficient, air density, or spin-decay constant has to be assumed or
# invented. This is deliberately a *fit through known endpoints*, not a
# first-principles gravity+drag simulation (that was the earlier,
# removed Phase 4 attempt) -- over the ~53-55 ft of flight after
# release, the ball's real path (gravity + drag + Magrus force
# combined) is close enough to parabolic that anchoring a parabola to
# the real release and real plate-crossing point gives a defensible
# estimate of the exit slope without needing to model the forces
# individually. The trade-off, stated plainly: this estimates the AVERAGE
# curvature between release and the plate, not the true instantaneous
# curvature at the plate -- see calculate_estimated_vaa's docstring for
# what that means in practice.
#
# flight_distance = plate_distance_ft - release_extension_ft (release
# extension is how far in front of the rubber the ball leaves the hand,
# so the ball only has to cover the REMAINING distance to the plate).

TRAJECTORY_MODEL_CONFIG = {
    # Rubber-to-plate distance. Not "60.6" -- 60.5 ft is the actual
    # rubber-to-plate-tip distance; this matches rapsodo_conventions.py's
    # own MOUND_TO_PLATE_FT constant, kept as a separate literal here
    # (rather than importing it) so this config can be handed to a
    # caller/debug view as one self-contained object, per the user's
    # own trajectoryModelConfig spec.
    "plate_distance_ft": 60.5,
    # Calibration offset added to the raw estimate, degrees. MUST default
    # to 0 -- never tuned to make numbers look "right" without a real
    # known-VAA comparison. See calibrate_vaa_offset() below for the
    # documented way to change this once real TrackMan/Statcast/Rapsodo
    # PRO 3.0 values are available to compare against.
    "calibration_offset_vaa_degrees": 0.0,
}


def _effective_parabola_exit_slope(release_pos_ft, release_slope, plate_pos_ft, flight_distance_ft):
    """Shared math core for both VAA (vertical plane) and HAA (horizontal
    plane): fit y = a*x^2 + b*x + c through (0, release_pos), slope
    release_slope at x=0, and (flight_distance, plate_pos); return the
    slope (dy/dx) at x = flight_distance. Returns None if flight_distance
    isn't usable (<= 0 -- e.g. a bad/zero release_extension reading)."""
    if flight_distance_ft is None or flight_distance_ft <= 0:
        return None
    b = release_slope
    c = release_pos_ft
    a = (plate_pos_ft - c - b * flight_distance_ft) / (flight_distance_ft ** 2)
    return 2 * a * flight_distance_ft + b


def calculate_estimated_vaa(release_height_ft, release_angle_deg, release_extension_ft, plate_height_ft,
                             config=None):
    """Estimated Vertical Approach Angle -- the vertical angle of the
    ball's velocity vector as it crosses the plate, fit through release
    height, release angle (initial slope), and the pitch's actual
    measured plate height (RapsodoPitch.plate_z_ft -- NOT the blank
    Rapsodo "Vertical Approach Angle" export column).

    All four inputs are required -- this deliberately does not fall
    back to a 2-point/no-plate-height version, because the whole reason
    this exists instead of atan(release_angle) is to account for where
    the pitch actually ends up, per Ryker's explicit requirement.
    Missing any one of them returns N/A with the specific missing field
    named, never a silently-degraded estimate.

    Returns a dict: value_degrees (rounded to 1 decimal, or None),
    na_reason, debug (flight_distance_ft, raw parabola a/b/c, raw vs.
    calibrated value -- useful for a dev/debug view and for later
    comparing against a known VAA).

    Limitation (state this wherever this number is shown): this is the
    AVERAGE exit slope of a parabola anchored to release and plate
    conditions, not a direct measurement of the ball's true
    instantaneous vertical angle at the plate the way a full multi-
    camera tracking system (TrackMan/Statcast/Hawk-Eye) reports it. It
    will track real VAA differences between pitches reasonably well
    (steeper drop -> more negative estimate) but its absolute value
    should be validated against a trusted source before being used for
    pitch-design decisions -- see calibrate_vaa_offset().
    """
    cfg = config or TRAJECTORY_MODEL_CONFIG
    debug = {"flight_distance_ft": None, "a": None, "b": None, "c": None, "raw_value_degrees": None}

    missing = []
    if release_height_ft is None:
        missing.append("Release Height")
    if release_angle_deg is None:
        missing.append("Release Angle")
    if release_extension_ft is None:
        missing.append("Release Extension")
    if plate_height_ft is None:
        missing.append("Strike Zone Height")
    if missing:
        return {"value_degrees": None, "na_reason": f"Estimated VAA unavailable: {', '.join(missing)} missing", "debug": debug}

    flight_distance_ft = cfg["plate_distance_ft"] - float(release_extension_ft)
    if flight_distance_ft <= 0:
        return {"value_degrees": None, "na_reason": "Estimated VAA unavailable: Release Extension is implausibly large for the configured plate distance", "debug": debug}

    b = math.tan(math.radians(float(release_angle_deg)))
    c = float(release_height_ft)
    a = (float(plate_height_ft) - c - b * flight_distance_ft) / (flight_distance_ft ** 2)
    slope_at_plate = 2 * a * flight_distance_ft + b
    raw_degrees = math.degrees(math.atan(slope_at_plate))

    debug.update({"flight_distance_ft": round(flight_distance_ft, 3), "a": a, "b": round(b, 5), "c": c, "raw_value_degrees": round(raw_degrees, 2)})

    calibrated = raw_degrees + cfg.get("calibration_offset_vaa_degrees", 0.0)
    return {"value_degrees": round(calibrated, 1), "na_reason": None, "debug": debug}


def calculate_estimated_haa(release_side_ft, horizontal_angle_deg, release_extension_ft, plate_side_ft,
                             config=None):
    """Estimated Horizontal Approach Angle -- same effective-parabola
    model as calculate_estimated_vaa, applied in the horizontal plane
    (release side -> plate side, using Horizontal Angle as the initial
    slope). Lower confidence than Estimated VAA: GBO's own import-layer
    notes (models.py, RapsodoPitch.horizontal_angle) flag that Rapsodo's
    "Horizontal Angle" column's exact definition is "pending
    confirmation" -- this function uses it at face value (the initial
    horizontal slope at release), same role Release Angle plays for
    VAA, but that mapping hasn't been independently verified the way
    the vertical plate-height conversion has (see rapsodo_conventions.
    strike_zone_inches_to_plate_feet's docstring, which explicitly notes
    the horizontal SIGN convention isn't confirmed either).

    Returns the same shape as calculate_estimated_vaa. Per the
    priority in the request this module was built against: VAA
    accuracy is never traded off to make HAA available -- this is a
    fully separate calculation that only fires when all 4 of its own
    inputs are present, and returns N/A otherwise rather than guessing.
    """
    cfg = config or TRAJECTORY_MODEL_CONFIG
    debug = {"flight_distance_ft": None, "a": None, "b": None, "c": None, "raw_value_degrees": None}

    missing = []
    if release_side_ft is None:
        missing.append("Release Side")
    if horizontal_angle_deg is None:
        missing.append("Horizontal Angle")
    if release_extension_ft is None:
        missing.append("Release Extension")
    if plate_side_ft is None:
        missing.append("Strike Zone Side")
    if missing:
        return {"value_degrees": None, "na_reason": f"Estimated HAA unavailable: {', '.join(missing)} missing", "debug": debug}

    flight_distance_ft = cfg["plate_distance_ft"] - float(release_extension_ft)
    if flight_distance_ft <= 0:
        return {"value_degrees": None, "na_reason": "Estimated HAA unavailable: Release Extension is implausibly large for the configured plate distance", "debug": debug}

    b = math.tan(math.radians(float(horizontal_angle_deg)))
    c = float(release_side_ft)
    a = (float(plate_side_ft) - c - b * flight_distance_ft) / (flight_distance_ft ** 2)
    slope_at_plate = 2 * a * flight_distance_ft + b
    raw_degrees = math.degrees(math.atan(slope_at_plate))

    debug.update({"flight_distance_ft": round(flight_distance_ft, 3), "a": a, "b": round(b, 5), "c": c, "raw_value_degrees": round(raw_degrees, 2)})
    return {"value_degrees": round(raw_degrees, 1), "na_reason": None, "debug": debug}


def calibrate_vaa_offset(known_vaa_degrees, estimated_vaa_degrees_list):
    """Given a known-good VAA (from TrackMan/Statcast/Rapsodo PRO 3.0/etc.
    for a comparable pitch) and one or more of this module's raw
    estimates for the same/similar pitches, returns the mean error
    (known - estimated) -- the value that could be set as
    TRAJECTORY_MODEL_CONFIG["calibration_offset_vaa_degrees"] to correct
    future estimates. Pure arithmetic, does not mutate the module-level
    config itself -- a human decides if/when to apply it, per Ryker's
    explicit "do not arbitrarily tune the calibration offset" rule.
    Returns None if estimated_vaa_degrees_list is empty."""
    vals = [v for v in estimated_vaa_degrees_list if v is not None]
    if not vals:
        return None
    return round(known_vaa_degrees - (sum(vals) / len(vals)), 2)


def vaa_error(estimated_vaa_degrees, known_vaa_degrees):
    """Estimated - Known, for a debug/dev view showing Estimated VAA /
    Known VAA / VAA Error side by side. Returns None if either input is
    None."""
    if estimated_vaa_degrees is None or known_vaa_degrees is None:
        return None
    return round(estimated_vaa_degrees - known_vaa_degrees, 2)


# ---------------------------------------------------------------------------
# 3. FASTBALL TRAJECTORY CLASSIFICATION ("flat" / "average" / "steep")
# ---------------------------------------------------------------------------
# Deliberately per-pitch-type, deliberately just a plain, hand-editable
# dict -- not an auto-tuned model. Ryker's own explicit rule: don't
# hard-code one universal VAA threshold, and don't tune it to produce
# attractive-looking numbers. These starting thresholds are round,
# clearly-labeled placeholders (roughly consistent with published
# amateur/college fastball VAA ranges at a ~5.5-6.5 ft release height),
# NOT validated against Pittsburg State's own pitchers -- Ryker should
# retune flat_at_or_above / steep_at_or_below for each pitch type once
# he has enough real Estimated VAA data from his own roster to know
# what "flat" and "steep" actually look like for his population. Every
# threshold here is a starting point, not a finding.
TRAJECTORY_CLASSIFICATION_CONFIG = {
    "4-Seam Fastball": {"flat_at_or_above": -4.0, "steep_at_or_below": -6.0},
    "Fastball": {"flat_at_or_above": -4.0, "steep_at_or_below": -6.0},
    # Sinkers/2-seamers are EXPECTED to play flatter/more horizontal by
    # design -- do not reuse the 4-seam thresholds. Placeholder, same
    # "retune with real data" caveat as above.
    "2-Seam Fastball": {"flat_at_or_above": -5.0, "steep_at_or_below": -7.5},
}


def classify_fastball_trajectory(canonical_pitch_type, estimated_vaa_degrees, config=None):
    """"Flat" / "Average" / "Steep" for a fastball-family pitch type, or
    None if canonical_pitch_type isn't in the classification config (a
    breaking/offspeed pitch, or a fastball variant nobody's configured
    yet) or estimated_vaa_degrees is None. Uses "Flat trajectory" /
    "Steep trajectory" language, never "good pitch"/"bad pitch" -- this
    is a description of shape, not a coaching verdict, unless a coach
    chooses to read it that way for their own purposes."""
    cfg = config or TRAJECTORY_CLASSIFICATION_CONFIG
    thresholds = cfg.get(canonical_pitch_type)
    if thresholds is None or estimated_vaa_degrees is None:
        return None
    if estimated_vaa_degrees >= thresholds["flat_at_or_above"]:
        return "Flat"
    if estimated_vaa_degrees <= thresholds["steep_at_or_below"]:
        return "Steep"
    return "Average"
