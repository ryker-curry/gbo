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
"""

from statistics import mean


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(float(mean(vals)), 2) if vals else None


def _max(values):
    vals = [v for v in values if v is not None]
    return round(float(max(vals)), 2) if vals else None


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


def pitch_type_summary(pitches):
    """One row per pitch type, per spec Section 6's table: Pitch Type, #,
    Avg Velo, Max Velo, Avg Spin, IVB, HB, Extension, Release Height,
    Release Side. Returns a list of dicts in first-seen order (which,
    since pitches are expected to already be pitch_number-sorted, is
    also throwing order -- e.g. a pitcher's primary fastball usually
    appears first)."""
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
        rows.append({
            "Pitch Type": label,
            "#": len(group),
            "Avg Velo": _avg([p.velocity for p in group]),
            "Max Velo": _max([p.velocity for p in group]),
            "Avg Spin": _avg([p.total_spin for p in group]),
            "IVB": _avg([p.vb_spin for p in group]),
            "HB": _avg([p.hb_spin for p in group]),
            "Extension": _avg([p.release_extension for p in group]),
            "Release Height": _avg([p.release_height for p in group]),
            "Release Side": _avg([p.release_side for p in group]),
        })
    return rows


def individual_pitch_rows(pitches):
    """Flat per-pitch table for the "expand a pitch type to see every
    individual pitch" requirement (spec Section 6)."""
    rows = []
    for p in pitches:
        rows.append({
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
        })
    return rows
