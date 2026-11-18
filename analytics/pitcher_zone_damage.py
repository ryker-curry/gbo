"""
GBO -- Opposing-hitter "damage by zone" heat map data (Sept 2026,
Ryker: "an opposing hitters heat map for each of my pitchers ... so we
can see where the most damage gets done for each pitch our pitchers
throw from intrasquad and real games ... select a pitch type from a
drop down then see a strikezone that has red zones for hot zones where
the most damage gets done and blue for cold zones").

Metric choice (Ryker asked directly: wOBA or contact quality --
neither. Run value): every GamePitch already carries its own
run_value, computed at save time from Ryker's own real run-expectancy
table (models.GamePitch's docstring; RunExpectancy is Ryker's own
table, not a generic published one) -- and it's already the
established "damage" number in this exact Results tab (the "RV/100"
column game_stats.compute_pitch_type_breakdown already produces per
pitch type). This heat map is the SAME stat, just re-sliced spatially
by zone for one pitch type instead of by pitch type across the whole
outing/season -- not a second, parallel value system. wOBA would be a
step down in accuracy (generic linear weights vs. a real table this
staff already built and trusts) for no benefit. Contact quality
(Weak/Jammed/Off the End/Clipped/Solid/Barreled) is real signal but
incomplete on its own -- it says nothing about called balls/strikes,
walks, HBP, or strikeouts, which are just as much "what happened at
this location" as a batted ball is. So contact quality rides along as
SUPPORTING context per cell (see "contact_quality_counts" below)
rather than driving the color.

Every pitch counts here, not just plate-appearance-ending ones -- same
scope as the existing RV/100 column (game_stats.py's rv_values list
comprehension has no ends_plate_appearance filter either). A 2-strike
pitch that misses off the plate and draws a chase whiff is exactly as
real a "cold" (good-for-the-pitcher) result at that location as a
first-pitch fastball down the middle that gets drilled is a "hot" one
at that other location -- and including every pitch, not just batted
balls, gives each cell far more pitches to work with, which matters a
lot at GBO's real sample sizes.

Zones are the SAME 1-9 grid (+0 = Bury) every pitch already gets
stamped with at save time (strike_zone.derive_old_zone, from
actual_plate_x/actual_plate_z -- see GamePitch.pitch_zone's own
comment in models.py) -- not a new scheme invented just for this
chart, so "zone 6" means the same thing here as everywhere else in
GBO a pitch gets graded. Zone 0 (Bury) has no fixed box the same way
1-9 do (derive_old_zone's own docstring), so it's reported as its own
summary rather than forced into a 10th irregular grid cell.

Needs Video Review, same as every other zone-dependent stat in this
app (pitch_zone is derived from actual_plate_x/actual_plate_z, which
per Ryker's call is no longer captured live -- see
analytics/pitcher_game_report.py's own module docstring for the full
reasoning). Pitches with no pitch_zone yet are simply excluded, not
treated as zero/cold.
"""

ZONE_LAYOUT = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]  # matches strike_zone.derive_old_zone exactly

# GBO's own contact_quality vocabulary (models.GamePitch's own comment
# lists these verbatim, "Bunt" included as Game-Tracking-only) -- same
# values visualizations/pitch_results_chart.py's stacked bar uses.
CONTACT_QUALITY_VALUES = ("Weak", "Jammed", "Off the End", "Clipped", "Solid", "Barreled/Squared Up", "Bunt")

HIT_AB_OUTCOMES = ("1B", "2B", "3B", "HR")


def _cell_stats(zone_pitches):
    rv_values = [float(p.run_value) for p in zone_pitches if p.run_value is not None]
    balls_in_play = [p for p in zone_pitches if p.pitch_outcome == "In Play"]
    contact_quality_counts = {
        cq: sum(1 for p in balls_in_play if p.contact_quality == cq) for cq in CONTACT_QUALITY_VALUES
    }
    return {
        "n": len(zone_pitches),
        "avg_rv": (sum(rv_values) / len(rv_values)) if rv_values else None,
        "total_rv": sum(rv_values) if rv_values else None,
        "balls_in_play": len(balls_in_play),
        "contact_quality_counts": contact_quality_counts,
        "hits_allowed": sum(1 for p in zone_pitches if p.ends_plate_appearance and p.ab_outcome in HIT_AB_OUTCOMES),
        "hr_allowed": sum(1 for p in zone_pitches if p.ends_plate_appearance and p.ab_outcome == "HR"),
    }


def compute_zone_damage(pitches):
    """pitches: any list of GamePitch ORM objects for ONE pitcher,
    already filtered to whatever pitch-type selection the caller wants
    (a single type, or "all pitch types" by just not filtering) --
    this function does no pitch-type filtering itself, so it stays
    reusable for either case.

    Returns {"cells": {1: {...}, ..., 9: {...}}, "bury": {...} | None,
    "n_located": int, "n_total": int}. Each cell dict has "n" (pitch
    count), "avg_rv"/"total_rv" (None if nothing here has a run_value
    yet), "balls_in_play", "contact_quality_counts" (dict, balls in
    play only), "hits_allowed", "hr_allowed"."""
    located = [p for p in pitches if p.pitch_zone is not None]
    cells = {
        zone: _cell_stats([p for p in located if p.pitch_zone == zone])
        for zone in range(1, 10)
    }

    bury_pitches = [p for p in pitches if p.pitch_zone == 0]
    bury = _cell_stats(bury_pitches) if bury_pitches else None

    return {
        "cells": cells,
        "bury": bury,
        "n_located": len(located),
        "n_total": len(pitches),
    }
