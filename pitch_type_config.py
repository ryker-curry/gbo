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
PITCH_TYPE_COLORS = {
    "4-Seam Fastball": "#BF1E2D",  # GBO crimson
    "2-Seam Fastball": "#F76707",
    "Cutter": "#D4AF37",  # GBO gold
    "Slider": "#4C6EF5",
    "Changeup": "#37B24D",
    "Curveball": "#AE3EC9",
    "Splitter": "#0CA678",
    "Fastball": "#E64980",
}

# Used for any pitch type that reaches a chart without a color assigned
# above (a newly added PitchType row nobody's updated this dict for yet)
# -- a chart should never fail to render for a missing color.
DEFAULT_PITCH_COLOR = "#6B6B6B"


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
