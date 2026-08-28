"""
GBO — Bullpen Analytics: pitch-type and session summary calculations.

Pure data logic -- no Streamlit, no database queries of its own. Every
function here takes a list of already-loaded RapsodoPitch ORM objects
(the caller/page is responsible for querying/filtering by bullpen_id,
joinedload-ing .pitch_type, etc.) and returns plain dicts/lists a page
can render however it wants. This is the separation the spec's
Section 20 calls for: "keep calculations separate from visualization
functions... keep database operations separate from UI code."

Column choices for pitch_type_summary() match the Rapsodo Bullpen
Analytics spec's Section 6 table (Pitch Type, #, Avg Velo, Max Velo,
Avg Spin, IVB, HB, Extension, Release Height, Release Side).

Aug 2026 addition: pitch_type_summary() and individual_pitch_rows()
both take an optional `player` (the Player ORM row -- for
Player.height_in/throws) and, when given one, add Estimated Arm Angle
/ Estimated VAA columns via analytics.pitch_trajectory. Per Ryker's
outlier-handling rule (spec Section 21), Estimated VAA is always
computed PITCH-BY-PITCH first and averaged second -- never from
already-averaged release height/angle/extension/plate height -- so a
single bad reading can't silently distort a whole pitch type's number,
and the displayed value always carries its own sample size, e.g.
"-7.8 degrees (n=14)". release_trajectory_summary() and
fastball_trajectory_diagnostic() (both new) follow the same rule for
the pitcher-level summary panel and the fastball diagnostic card.
`player` defaults to None everywhere so every existing caller of these
two functions keeps working unchanged -- the new columns simply don't
appear without a player.
"""

from statistics import mean

from analytics.pitch_trajectory import (
    calculate_estimated_arm_angle, calculate_estimated_vaa, calculate_estimated_haa,
    classify_fastball_trajectory,
)


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(float(mean(vals)), 2) if vals else None


def _max(values):
    vals = [v for v in values if v is not None]
    return round(float(max(vals)), 2) if vals else None


def _avg_extension(values):
    """Same as _avg(), but treats exactly 0 as a missing/bad reading rather
    than a real measurement. Rapsodo occasionally reports release_extension
    as a literal 0 when it fails to compute a real value -- a legitimate
    release extension is roughly 5-7 feet, so 0 is never a real reading.
    Including those in the average would silently drag it down, so they're
    excluded here the same way None already is. Only used for Extension --
    other fields (IVB, HB, etc.) can legitimately be near zero, so they
    keep using the plain _avg()."""
    vals = [v for v in values if v is not None and v != 0]
    return round(float(mean(vals)), 2) if vals else None


def _pitch_level_arm_angle(pitch, player):
    """Estimated Arm Angle for one pitch, using the player's existing
    Player.height_in (never a separate/new height field -- see
    pitch_trajectory.py's module docstring) plus THIS pitch's own
    release height/side. Returns the plain result dict from
    calculate_estimated_arm_angle (value_degrees/na_reason/debug)."""
    height_in = float(player.height_in) if player is not None and player.height_in is not None else None
    release_height = float(pitch.release_height) if pitch.release_height is not None else None
    release_side = float(pitch.release_side) if pitch.release_side is not None else None
    return calculate_estimated_arm_angle(height_in, release_height, release_side)


def _pitch_level_vaa(pitch):
    """Estimated VAA for one pitch -- release_height/release_angle/
    release_extension straight off the row, and plate_z_ft (already
    converted to real feet, 0=ground, at import time -- see
    rapsodo_conventions.strike_zone_inches_to_plate_feet) as the actual
    measured plate-crossing height. Returns the plain result dict from
    calculate_estimated_vaa."""
    release_height = float(pitch.release_height) if pitch.release_height is not None else None
    release_angle = float(pitch.release_angle) if pitch.release_angle is not None else None
    release_extension = float(pitch.release_extension) if pitch.release_extension is not None else None
    plate_height = float(pitch.plate_z_ft) if pitch.plate_z_ft is not None else None
    return calculate_estimated_vaa(release_height, release_angle, release_extension, plate_height)


def _pitch_level_haa(pitch):
    """Same as _pitch_level_vaa, horizontal plane. See
    calculate_estimated_haa's docstring for its lower-confidence caveat
    (Horizontal Angle's exact definition isn't independently confirmed
    the way the vertical plate-height conversion is)."""
    release_side = float(pitch.release_side) if pitch.release_side is not None else None
    horizontal_angle = float(pitch.horizontal_angle) if pitch.horizontal_angle is not None else None
    release_extension = float(pitch.release_extension) if pitch.release_extension is not None else None
    plate_side = float(pitch.plate_x_ft) if pitch.plate_x_ft is not None else None
    return calculate_estimated_haa(release_side, horizontal_angle, release_extension, plate_side)


def _avg_pitch_level(values):
    """Average a list of already-computed pitch-level values (arm
    angle/VAA/HAA degrees), dropping Nones -- i.e. average SECOND, per
    Ryker's outlier-handling rule (spec Section 21), never averaging
    the raw inputs first and computing one estimate from the average.
    Returns (avg_or_None, n) -- n is always reported alongside the
    value wherever this is displayed, never hidden."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None, 0
    return round(sum(vals) / len(vals), 1), len(vals)


def pitch_type_label(pitch):
    """Display name for a pitch's type -- the normalized canonical name
    if one was matched at import time, otherwise the raw Rapsodo label
    (so an unclassified "-" pitch still shows something meaningful
    rather than just disappearing from summaries), otherwise a plain
    fallback. Public -- pages group individual pitches by this same
    label to match the summary table's rows."""
    if pitch.pitch_type is not None:
        return pitch.pitch_type.type_name
    if pitch.raw_pitch_type:
        return f"{pitch.raw_pitch_type} (unrecognized)"
    return "Unclassified"


def filter_pitches(pitches, pitch_type_name=None, pitch_number_range=None):
    """Filters an already-loaded list of RapsodoPitch objects. Section 5's
    filters: All Pitches / Pitch Type / Pitch Number Range.

    pitch_type_name: exact display label as returned by pitch_type_label,
    or None for no filtering by type.
    pitch_number_range: (low, high) inclusive, or None for no range filter.
    """
    result = pitches
    if pitch_type_name is not None:
        result = [p for p in result if pitch_type_label(p) == pitch_type_name]
    if pitch_number_range is not None:
        low, high = pitch_number_range
        result = [p for p in result if low <= p.pitch_number <= high]
    return result


def session_summary(pitches):
    """Session Header metrics (spec Section 5): total pitches, distinct
    pitch types present, average/maximum velocity, average spin rate."""
    if not pitches:
        return {
            "total_pitches": 0,
            "pitch_type_names": [],
            "avg_velocity": None,
            "max_velocity": None,
            "avg_spin_rate": None,
        }

    type_names = []
    for p in pitches:
        label = pitch_type_label(p)
        if label not in type_names:
            type_names.append(label)

    return {
        "total_pitches": len(pitches),
        "pitch_type_names": type_names,
        "avg_velocity": _avg([p.velocity for p in pitches]),
        "max_velocity": _max([p.velocity for p in pitches]),
        "avg_spin_rate": _avg([p.total_spin for p in pitches]),
    }


def pitch_type_summary(pitches, player=None):
    """One row per pitch type, per spec Section 6's table: Pitch Type, #,
    Avg Velo, Max Velo, Avg Spin, IVB, HB, Extension, Release Height,
    Release Side. Returns a list of dicts in first-seen order (which,
    since pitches are expected to already be pitch_number-sorted, is
    also throwing order -- e.g. a pitcher's primary fastball usually
    appears first).

    player=None (default): unchanged from before this feature existed.
    Pass the pitcher's Player row to also get "Release Angle", "Est.
    Arm Angle", "Est. VAA" (each pitch-level-then-averaged, with (n=...)
    on VAA), and "Trajectory" (Flat/Average/Steep, fastball-family
    types only, blank otherwise)."""
    groups = {}
    order = []
    for p in pitches:
        label = pitch_type_label(p)
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(p)

    rows = []
    for label in order:
        group = groups[label]
        row = {
            "Pitch Type": label,
            "#": len(group),
            "Avg Velo": _avg([p.velocity for p in group]),
            "Max Velo": _max([p.velocity for p in group]),
            "Avg Spin": _avg([p.total_spin for p in group]),
            "IVB": _avg([p.vb_spin for p in group]),
            "HB": _avg([p.hb_spin for p in group]),
            "Extension": _avg_extension([p.release_extension for p in group]),
            "Release Height": _avg([p.release_height for p in group]),
            "Release Side": _avg([p.release_side for p in group]),
        }
        if player is not None:
            row["Release Angle"] = _avg([p.release_angle for p in group])

            arm_angles = [_pitch_level_arm_angle(p, player)["value_degrees"] for p in group]
            arm_avg, arm_n = _avg_pitch_level(arm_angles)
            row["Est. Arm Angle"] = f"{arm_avg:g}°" if arm_avg is not None else "N/A"

            vaas = [_pitch_level_vaa(p)["value_degrees"] for p in group]
            vaa_avg, vaa_n = _avg_pitch_level(vaas)
            row["Est. VAA"] = f"{vaa_avg:g}° (n={vaa_n})" if vaa_avg is not None else "N/A"

            row["Trajectory"] = classify_fastball_trajectory(label, vaa_avg) or "—"
        rows.append(row)
    return rows


def individual_pitch_rows(pitches, player=None):
    """Flat per-pitch table for the "expand a pitch type to see every
    individual pitch" requirement (spec Section 6).

    player=None (default): unchanged. Pass the pitcher's Player row to
    also get "Release Angle" and "Est. VAA" side by side -- spec intent
    (Aug 2026 addition): seeing the vertical angle the ball LEFT the
    hand at next to the estimated angle it CROSSES the plate at, on the
    same row, makes the release-to-plate change legible pitch by pitch,
    not just as a type-level average. "Est. Arm Angle" is also included
    per pitch (arm slot can vary a little pitch to pitch even within
    one type) -- unlike VAA it has no natural "n=" (it's already a
    single-pitch value, not itself an average)."""
    rows = []
    for p in pitches:
        row = {
            "#": p.pitch_number,
            "Time": p.pitch_date.strftime("%I:%M:%S %p") if p.pitch_date else "—",
            "Pitch Type": pitch_type_label(p),
            "Velocity": float(p.velocity) if p.velocity is not None else None,
            "Total Spin": float(p.total_spin) if p.total_spin is not None else None,
            "IVB": float(p.vb_spin) if p.vb_spin is not None else None,
            "HB": float(p.hb_spin) if p.hb_spin is not None else None,
            "Extension": float(p.release_extension) if p.release_extension is not None else None,
            "Release Height": float(p.release_height) if p.release_height is not None else None,
            "Release Side": float(p.release_side) if p.release_side is not None else None,
            "Strike": "Y" if p.is_strike else ("N" if p.is_strike is False else "—"),
        }
        if player is not None:
            row["Release Angle"] = float(p.release_angle) if p.release_angle is not None else None
            vaa = _pitch_level_vaa(p)
            row["Est. VAA"] = f"{vaa['value_degrees']:g}°" if vaa["value_degrees"] is not None else "N/A"
            arm = _pitch_level_arm_angle(p, player)
            row["Est. Arm Angle"] = f"{arm['value_degrees']}°" if arm["value_degrees"] is not None else "N/A"
        rows.append(row)
    return rows


def average_estimated_arm_angle(pitches, player):
    """Public helper (unlike the underscored per-pitch internals above)
    for callers that need the raw numeric average -- e.g. the movement
    chart's arm-angle ray, which needs a float degrees value, not the
    formatted "24° (n=15)" string release_trajectory_summary() returns.
    Returns (avg_degrees_or_None, n) -- pitch-level-then-averaged, same
    outlier-handling rule as everywhere else in this module."""
    if player is None:
        return None, 0
    angles = [_pitch_level_arm_angle(p, player)["value_degrees"] for p in pitches]
    return _avg_pitch_level(angles)


def release_trajectory_summary(pitches, player):
    """Pitcher-level "RELEASE / TRAJECTORY SUMMARY" panel data (spec
    Section 22): average Release Height/Side/Extension/Release Angle/
    Est. Arm Angle/Est. VAA across whatever `pitches` the caller has
    already filtered (by pitch type/session/date/pitcher -- filtering
    itself is filter_pitches' job, same as everywhere else in this
    module; this function just aggregates whatever list it's given).

    `player` is required (not optional) here, unlike pitch_type_summary/
    individual_pitch_rows -- there's no meaningful version of this
    panel without knowing whose height the arm-angle numbers are
    against.

    Returns a dict of {label: display_string}, already formatted
    ("N/A", "(n=...)" etc.) so the caller can drop it straight into a
    KPI-card-style panel with no further logic."""
    release_heights = [float(p.release_height) for p in pitches if p.release_height is not None]
    release_sides = [float(p.release_side) for p in pitches if p.release_side is not None]
    extensions = [float(p.release_extension) for p in pitches if p.release_extension not in (None, 0)]
    release_angles = [float(p.release_angle) for p in pitches if p.release_angle is not None]
    arm_angles = [_pitch_level_arm_angle(p, player)["value_degrees"] for p in pitches]
    vaas = [_pitch_level_vaa(p)["value_degrees"] for p in pitches]

    arm_avg, arm_n = _avg_pitch_level(arm_angles)
    vaa_avg, vaa_n = _avg_pitch_level(vaas)

    def _fmt(vals, suffix, decimals=2):
        if not vals:
            return "N/A"
        return f"{round(sum(vals) / len(vals), decimals):g}{suffix} (n={len(vals)})"

    return {
        "Average Release Height": _fmt(release_heights, " ft"),
        "Average Release Side": _fmt(release_sides, " ft"),
        "Average Extension": _fmt(extensions, " ft"),
        "Average Release Angle": _fmt(release_angles, "°", decimals=1),
        "Average Estimated Arm Angle": f"{arm_avg:g}° (n={arm_n})" if arm_avg is not None else "N/A",
        "Average Estimated VAA": f"{vaa_avg:g}° (n={vaa_n})" if vaa_avg is not None else "N/A",
    }


def fastball_trajectory_diagnostic(pitches, player, canonical_pitch_type="4-Seam Fastball"):
    """Compact "FASTBALL TRAJECTORY" diagnostic card data (spec Section
    18): Velocity/VB/VAA/Release Height/Extension/Arm Angle plus a
    Flat/Average/Steep classification, scoped to ONE canonical pitch
    type at a time (never mixing 4-seam and 2-seam/sinker thresholds --
    call this once per fastball-family type actually present, per
    classify_fastball_trajectory's own per-type config).

    Returns None if no pitch in `pitches` matches canonical_pitch_type
    (nothing to show a card for) -- caller should skip rendering the
    card entirely in that case, not show an all-N/A card."""
    group = [p for p in pitches if pitch_type_label(p) == canonical_pitch_type]
    if not group:
        return None

    vaas = [_pitch_level_vaa(p)["value_degrees"] for p in group]
    vaa_avg, vaa_n = _avg_pitch_level(vaas)
    arm_angles = [_pitch_level_arm_angle(p, player)["value_degrees"] for p in group]
    arm_avg, arm_n = _avg_pitch_level(arm_angles)

    return {
        "pitch_type": canonical_pitch_type,
        "n": len(group),
        "Velocity": _avg([p.velocity for p in group]),
        "VB": _avg([p.vb_spin for p in group]),
        "VAA": f"{vaa_avg:g}° (n={vaa_n})" if vaa_avg is not None else "N/A",
        "Release Height": _avg([p.release_height for p in group]),
        "Extension": _avg_extension([p.release_extension for p in group]),
        "Arm Angle": f"{arm_avg:g}°" if arm_avg is not None else "N/A",
        "Trajectory": classify_fastball_trajectory(canonical_pitch_type, vaa_avg) or "N/A",
    }