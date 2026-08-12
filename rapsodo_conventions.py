"""
GBO — Rapsodo unit-conversion conventions.

Small, isolated helpers for the two raw-Rapsodo-format -> GBO-convention
conversions the import service and later chart code both need. Kept in
one place per the architecture review's centralization principle --
nothing else should re-implement clock-to-degrees or inches-to-feet math
independently.

Both conventions are documented here with the reasoning that justified
them, since the spec is explicit that baseball-physics/unit assumptions
must be documented, not silently assumed.
"""


def spin_clock_to_degrees(clock_str):
    """Rapsodo's "Spin Direction" column, clock format (e.g. "12:18"),
    converted to degrees on a 0-360 scale.

    Convention: 12:00 = 0 degrees, increasing clockwise as the minute
    hand would move (so 3:00 = 90 degrees, 6:00 = 180, 9:00 = 270).
    This matches the conversion already implemented and in production
    use in pages/import_rapsodo.py's clock_to_degrees() -- ported here
    unchanged so both the old and new import paths agree, and so the
    Phase 3 spin-axis clock-face chart has one source of truth.

    Rapsodo itself describes spin direction as viewed looking at the
    pitcher's release point from the catcher's/plate's perspective --
    confirm this against Rapsodo's own documentation before treating the
    resulting degree value as authoritative for anything beyond display
    (this note carries forward the same caveat the original
    implementation's docstring raised).

    Returns None if the value can't be parsed (e.g. "-" for an
    unclassified pitch, or a malformed string) -- never raises.
    """
    try:
        hours, minutes = str(clock_str).strip().split(":")
        hours, minutes = int(hours) % 12, int(minutes)
        return round(((hours + minutes / 60) / 12) * 360, 1)
    except (ValueError, TypeError, AttributeError):
        return None


# Rapsodo mound-to-plate reference distance used by both the strike-zone
# conversion below and (in Phase 4) the perceived-velocity formula.
MOUND_TO_PLATE_FT = 60.5


def strike_zone_inches_to_plate_feet(strike_zone_side_in, strike_zone_height_in):
    """Convert Rapsodo's "Strike Zone Side"/"Strike Zone Height" (inches,
    zone-relative) to GBO's plate_x_ft/plate_z_ft convention (feet,
    0 = plate center / 0 = ground -- the same convention strike_zone.py
    already uses for Game Tracking, ZONE_HALF_WIDTH = 0.708 ft = 8.5 in).

    Reasoning checked against the real export before adopting this as a
    straight unit conversion (Ryker confirmed: convert & use, rather than
    wait for a feet-based Plate Side/Height export):
      - Strike Zone Side values in the sample file (e.g. -1.85, 8.94)
        are small numbers consistent with inches-from-plate-center, and
        8.5 in (half the 17 in plate) is exactly strike_zone.py's own
        ZONE_HALF_WIDTH * 12 -- so dividing by 12 lines up with GBO's
        existing zone boundaries with no re-centering needed.
      - Strike Zone Height values (e.g. 30.97, 43.78, 23.92 in) divided
        by 12 land at roughly 2.6 ft, 3.6 ft, 2.0 ft -- consistent with
        real pitch locations relative to the ground (zone bottom ~1.5 ft,
        top ~3.5 ft per strike_zone.py), not some other reference point.

    What's NOT yet confirmed and should be spot-checked against real
    video/known locations before this is treated as ground truth: the
    LEFT/RIGHT sign convention (which side of plate_x is negative for a
    given pitcher's arm side). The magnitude/vertical mapping checks out
    arithmetically; the horizontal sign does not have an independent
    confirmation yet.

    Returns (plate_x_ft, plate_z_ft), either of which may be None if the
    corresponding input is None.
    """
    plate_x_ft = round(float(strike_zone_side_in) / 12, 3) if strike_zone_side_in is not None else None
    plate_z_ft = round(float(strike_zone_height_in) / 12, 3) if strike_zone_height_in is not None else None
    return plate_x_ft, plate_z_ft
