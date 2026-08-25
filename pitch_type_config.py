"""
GBO — Centralized pitch-type mapping and pitch colors.

Single source of truth for two things that were previously scattered
across the app (spec Sections 22-23):
  1. Mapping a raw, free-text pitch-type label from any import (Rapsodo
     export, manual entry, a future different device) onto one of GBO's
     canonical PitchType rows.
  2. The color assigned to each canonical pitch type, so every chart in
     the Rapsodo Bullpen Analytics module (and beyond) draws a given
     pitch type in the same color. Replaces the positional
     PITCH_TYPE_COLORS list previously duplicated in
     pages/bullpen_tracking.py and pages/player_bullpens.py -- those
     assigned colors by iteration order, which drifts depending on which
     pitch types happen to appear first in a given session. This assigns
     by name instead, so the color is stable across sessions/players.

Canonical pitch types (PitchType.type_name rows):
    4-Seam Fastball, 2-Seam Fastball, Cutter, Slider, Changeup,
    Curveball, Splitter, Fastball

"Fastball" (generic/undifferentiated) is its own canonical type, distinct
from "4-Seam Fastball" -- NOT an alias for it. Rapsodo's real export
reviewed (Saben Seager's bullpen) classifies fastballs as plain
"Fastball" with no 2-seam/4-seam distinction. Forcing that into
"4-Seam Fastball" would assert a grip/pitch-design detail the device
never actually reported. If a export or manual entry DOES distinguish
4-seam from 2-seam, those map to their own existing types as before.
This is a judgment call, not a settled convention -- flag to Ryker if a
different mapping is preferred once more real exports are seen.
"""

import re


def _normalize(raw: str) -> str:
    """Lowercase, strip everything but letters/digits, for tolerant
    matching against minor punctuation/spacing/case differences between
    export naming conventions (e.g. "4-Seam Fastball" vs "Four Seam" vs
    "FourSeamFastball")."""
    return re.sub(r"[^a-z0-9]", "", str(raw).lower())


# Raw label (any casing/punctuation/spacing) -> canonical PitchType.type_name.
# Keys are pre-normalized (see _normalize) so lookups don't need to
# special-case punctuation at call sites.
_RAW_ALIASES = {
    # Fastballs
    "fastball": "Fastball",
    "fb": "Fastball",
    "4seamfastball": "4-Seam Fastball",
    "4seam": "4-Seam Fastball",
    "fourseam": "4-Seam Fastball",
    "fourseamfastball": "4-Seam Fastball",
    "ff": "4-Seam Fastball",
    "2seamfastball": "2-Seam Fastball",
    "2seam": "2-Seam Fastball",
    "twoseam": "2-Seam Fastball",
    "twoseamfastball": "2-Seam Fastball",
    "sinker": "2-Seam Fastball",
    "si": "2-Seam Fastball",
    "ft": "2-Seam Fastball",
    # Cutter
    "cutter": "Cutter",
    "fc": "Cutter",
    # Slider
    "slider": "Slider",
    "sl": "Slider",
    "sweeper": "Slider",  # closest existing catalog entry -- revisit if GBO wants Sweeper as its own type
    "sw": "Slider",
    # Changeup
    "changeup": "Changeup",
    "change": "Changeup",
    "changeoff": "Changeup",
    "ch": "Changeup",
    # Curveball
    "curveball": "Curveball",
    "curve": "Curveball",
    "cb": "Curveball",
    "cu": "Curveball",
    "kc": "Curveball",  # knuckle-curve -- closest existing catalog entry
    # Splitter
    "splitter": "Splitter",
    "splitfinger": "Splitter",
    "fs": "Splitter",
    "sf": "Splitter",
}

# Canonical type -> chart color (hex). Every chart module should import
# this dict rather than hardcoding or positionally cycling colors.
#
# Sept 2026: replaced the v2 design-system palette shipped in
# GBO-DESIGN-SYSTEM.md -- Ryker flagged Curveball/Splitter as reading
# as the same color on Bullpen Dashboard, and running that palette
# through the dataviz skill's validator (scripts/validate_palette.js)
# confirmed real, measurable problems, not just those two: Curveball
# vs Splitter scored a normal-vision Delta E of 7.3 (below the 15
# floor -- hard to tell apart even with full color vision), and
# 4-Seam Fastball vs 2-Seam Fastball scored a deutan (colorblind) Delta
# E of 1.1 (effectively identical for that kind of color blindness),
# neither of which anyone had actually flagged yet.
#
# These 7 colors are slots 1-7 of the skill's validated default
# categorical theme (references/palette.md), taken in its fixed
# published order (never cycled/reordered -- that order IS the
# colorblind-safety mechanism) and validated together as a set:
# adjacent-pair CVD Delta E >= 8.4, adjacent-pair normal-vision Delta E
# >= 19.3, all >= 3:1 contrast on the dark card surface. (7
# simultaneous series can't clear the strict ALL-PAIRS floor no matter
# the ordering -- the skill documents that as a hard limit past 3
# series -- but every chart these colors appear on already carries a
# legend and a hover tooltip naming the pitch type, which is exactly
# the secondary encoding the skill requires to make that acceptable.)
# Crimson and gold are still deliberately excluded: those are the
# app's action and rating colors, not chart series colors.
PITCH_TYPE_COLORS = {
    "4-Seam Fastball": "#3987E5",
    "Fastball": "#3987E5",
    "2-Seam Fastball": "#D95926",
    "Cutter": "#199E70",
    "Slider": "#C98500",
    "Changeup": "#D55181",
    "Curveball": "#008300",
    "Splitter": "#9085E9",
}

# Used for any pitch type that reaches a chart without a color assigned
# above (a newly added PitchType row nobody's updated this dict for yet)
# -- a chart should never fail to render for a missing color.
DEFAULT_PITCH_COLOR = "#7A8594"

# Canonical fastball-family types -- single source of truth for "is this
# pitch a fastball" (Aug 2026, Ryker: the player card's VELO stat should
# read as average FASTBALL velocity, not an average across every pitch
# type a pitcher threw that session -- a bullpen heavy on changeups/
# breaking stuff was dragging VELO down and misrepresenting what the
# pitcher's fastball actually sits at). Deliberately excludes Cutter --
# it's its own canonical type above, not folded into "fastball" here,
# same judgment call as everywhere else in this file.
FASTBALL_TYPES = {"Fastball", "4-Seam Fastball", "2-Seam Fastball"}


def normalize_pitch_type(raw_label):
    """Raw pitch-type text from any source -> canonical PitchType.type_name,
    or None if unrecognized (e.g. "-" for a Rapsodo-unclassified pitch, or
    a genuinely new pitch label nobody's added an alias for yet).

    Returning None rather than guessing is deliberate -- an unrecognized
    label should surface as "no pitch type" for review, not get silently
    misclassified into the nearest-sounding existing type.
    """
    if raw_label is None:
        return None
    normalized = _normalize(raw_label)
    if not normalized:
        return None
    return _RAW_ALIASES.get(normalized)


def get_pitch_color(canonical_type_name):
    """Canonical PitchType.type_name -> hex color, with a safe fallback
    for any type not yet in PITCH_TYPE_COLORS."""
    if canonical_type_name is None:
        return DEFAULT_PITCH_COLOR
    return PITCH_TYPE_COLORS.get(canonical_type_name, DEFAULT_PITCH_COLOR)
