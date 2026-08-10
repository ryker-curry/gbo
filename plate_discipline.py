"""
GBO — Plate discipline & pitch command/usage analytics.

Derived from raw GamePitch coordinate data (actual_plate_x/z, captured
in Phase 2) and pitch_outcome, per Ryker's architecture doc Section 14
("Hitting Analytics") and the pitcher-side equivalent. Doesn't
duplicate game_stats.py's Execution % (intended vs actual zone match)
-- that already exists there and uses the same underlying coordinates.

Swing/contact/whiff are all DERIVED from pitch_outcome, never entered
as separate fields (see strike_zone.py's docstring for why):
  - Swing = pitch_outcome in (Swinging Strike, Foul, In Play)
  - Whiff (swing and miss) = pitch_outcome == Swinging Strike
  - Contact (on a swing) = pitch_outcome in (Foul, In Play)

Zone-based metrics (Zone%, Chase%, etc.) only count pitches that
actually have a recorded location (actual_plate_x/z not null) --
pitches logged without a location click are excluded from those
specific metrics, shown separately as "located_pitches" vs the full
pitch count, rather than silently treated as in-zone or out.
"""

import streamlit as st
import plotly.graph_objects as go

from strike_zone import is_in_zone, derive_old_zone

SWING_OUTCOMES = {"Swinging Strike", "Foul", "In Play"}
WHIFF_OUTCOMES = {"Swinging Strike"}
CONTACT_OUTCOMES = {"Foul", "In Play"}


def _pct(numerator, denominator):
    return round(100 * numerator / denominator, 1) if denominator else None


def compute_hitter_discipline(pitches):
    """Plate discipline metrics for a hitter, from their own
    get_batting_pitches() list (game_stats.py)."""
    total = len(pitches)
    located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
    swings = [p for p in pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in pitches if p.pitch_outcome in WHIFF_OUTCOMES]

    in_zone_located = [p for p in located if is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    out_zone_located = [p for p in located if not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    zone_swings = [p for p in in_zone_located if p.pitch_outcome in SWING_OUTCOMES]
    chase_swings = [p for p in out_zone_located if p.pitch_outcome in SWING_OUTCOMES]
    zone_contacts = [p for p in zone_swings if p.pitch_outcome in CONTACT_OUTCOMES]
    chase_contacts = [p for p in chase_swings if p.pitch_outcome in CONTACT_OUTCOMES]

    first_pitches = [p for p in pitches if p.pa_pitch_number == 1]
    first_pitch_swings = [p for p in first_pitches if p.pitch_outcome in SWING_OUTCOMES]

    return {
        "Pitches Seen": total,
        "Located Pitches": len(located),
        "Swing %": _pct(len(swings), total),
        "Whiff %": _pct(len(whiffs), len(swings)),
        "Zone %": _pct(len(in_zone_located), len(located)),
        "Zone Swing %": _pct(len(zone_swings), len(in_zone_located)),
        "Chase %": _pct(len(chase_swings), len(out_zone_located)),
        "Zone Contact %": _pct(len(zone_contacts), len(zone_swings)),
        "Chase Contact %": _pct(len(chase_contacts), len(chase_swings)),
        "First-Pitch Swing %": _pct(len(first_pitch_swings), len(first_pitches)),
    }


def compute_pitcher_command(pitches):
    """Command/usage metrics for a pitcher, from their own
    get_pitching_pitches() list (game_stats.py). Doesn't duplicate
    Execution % -- that's already in game_stats.py's
    compute_pitching_line, using the same intended/actual data."""
    total = len(pitches)
    located = [p for p in pitches if p.actual_plate_x is not None and p.actual_plate_z is not None]
    swings = [p for p in pitches if p.pitch_outcome in SWING_OUTCOMES]
    whiffs = [p for p in pitches if p.pitch_outcome in WHIFF_OUTCOMES]

    in_zone_located = [p for p in located if is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    out_zone_located = [p for p in located if not is_in_zone(float(p.actual_plate_x), float(p.actual_plate_z))]
    chase_swings_induced = [p for p in out_zone_located if p.pitch_outcome in SWING_OUTCOMES]

    usage_counts = {}
    for p in pitches:
        if p.pitch_type:
            name = p.pitch_type.type_name
            usage_counts[name] = usage_counts.get(name, 0) + 1
    usage_pct = {name: _pct(count, total) for name, count in usage_counts.items()}

    return {
        "Pitches Thrown": total,
        "Located Pitches": len(located),
        "Zone %": _pct(len(in_zone_located), len(located)),
        "Whiff % Induced": _pct(len(whiffs), len(swings)),
        "Chase % Induced": _pct(len(chase_swings_induced), len(out_zone_located)),
        "Usage %": usage_pct,
    }


def compute_zone_performance(pitches):
    """Average Run Value and pitch count per zone, from this pitcher's
    OWN Game Tracking pitches (not swing-outcome data from Hitter
    Tracking, unlike the heatmap this replaces) -- how well his
    pitches actually perform when located in each part of the zone.
    Run Value is from the BATTING team's perspective, so lower/more
    negative = better for the pitcher. Only counts pitches with both a
    recorded location and a computed Run Value."""
    by_zone = {}
    for p in pitches:
        if p.actual_plate_x is None or p.actual_plate_z is None or p.run_value is None:
            continue
        zone = derive_old_zone(float(p.actual_plate_x), float(p.actual_plate_z))
        by_zone.setdefault(zone, []).append(float(p.run_value))
    avg_rv = {z: sum(vals) / len(vals) for z, vals in by_zone.items()}
    counts = {z: len(vals) for z, vals in by_zone.items()}
    return avg_rv, counts


def render_zone_performance_heatmap(avg_rv, counts, title="Performance by zone"):
    """3x3 heatmap of average Run Value per zone. Green = good for the
    pitcher (low/negative RV), red = poor (high/positive RV) -- an
    inverted colorscale, since low RV is the good outcome here."""
    zone_grid = [[7, 8, 9], [4, 5, 6], [1, 2, 3]]
    z = [[avg_rv.get(zid) for zid in row] for row in zone_grid]
    text = [[f"{avg_rv[zid]:+.2f}<br>({counts[zid]})" if zid in avg_rv else "—" for zid in row] for row in zone_grid]

    fig = go.Figure(data=go.Heatmap(
        z=z, text=text, texttemplate="%{text}", textfont=dict(color="#111111", size=14),
        colorscale="RdYlGn_r", zmin=-0.3, zmax=0.3, showscale=True,
        colorbar=dict(title="Avg RV", tickfont=dict(color="#FFFDE5"), title_font=dict(color="#FFFDE5")),
        xgap=3, ygap=3,
    ))
    fig.update_layout(
        title=title,
        height=380,
        plot_bgcolor="#1E1E1E", paper_bgcolor="#1E1E1E",
        font=dict(color="#FFFDE5"),
        xaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(showticklabels=False, showgrid=False, zeroline=False),
        margin=dict(t=40, b=20, l=20, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Green = good for him (low/negative Run Value), red = poor (high/positive). Number in parentheses is pitch count. Zone 0/Bury not shown on this grid.")