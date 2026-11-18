"""
GBO -- External reference standards for force-plate metrics.

Source: AdaptPTPD's "HD Informed Training" sheet (Hawkins Dynamics-based
CMJ/multi-rebound norms), supplied Aug 2026. This is a SECOND, independent
lens on top of the Bucket System's team-relative percentiles in
bucket_system.py -- it does not touch, replace, or feed into
compute_bucket_system's percentile math anywhere. The two coexist: a
player's Power/Strength percentile scores stay exactly what
bucket_system.py already computes; this module only adds an external
tier label next to specific raw metrics, and a suggested IDP target
value.

Pure computation, no Shiny/plotly dependency -- same rule as
bucket_system.py, so this can be imported by both bucket_display.py
(badge rendering) and modules/idp.py (goal target suggestion) without
either pulling in the other's UI layer.

SCOPE (Ryker's explicit call, Aug 2026): only 2 of AdaptPTPD's metrics
are wired up here --

  - "Countermovement Jump RSI-Modified" (mRSI) -- true MLB norms, split
    Pitcher vs Position Player, 5 tiers each.
  - "Hop Test RSI (10/5)" (AdaptPTPD's "Avg RSI -- Multi-Rebound") --
    generic reactive-strength-ability bands, not MLB-sourced, not
    position-split.

The other 6 metrics on the sheet (Peak Relative Power, Relative/Net
Peak Force IMTP, both Squat Jump propulsive-power metrics, the two
Impulse Ratios, DSI, EUR) are deliberately NOT included: GBO's bucket
spreadsheet has no raw field for CMJ Peak Force/Power, IMTP body-
weight-at-test, or Squat Jump at all (Ryker: "we did not perform a
squat jump" -- SJ-dependent metrics, including EUR, are excluded on
principle, not just for now). Add them here the same way once/if those
raw fields exist and there's real data behind them -- don't wire up a
tier or a target suggestion for a metric nobody has a number for.

Tier format: (label, floor, status). Ordered highest tier first.
`floor` is the metric value at/above which a player qualifies for that
tier; the bottom tier's floor is None (catch-all). `status` is one of
"good"/"watch"/"flag", matching bucket_display's existing status-color
vocabulary (see .gbo-tier-badge in theme.py) so this reads as part of
the same visual language as everything else on Physical Testing pages,
not a bolted-on second system.
"""

FORCE_PLATE_STANDARDS = {
    "Countermovement Jump RSI-Modified": {
        "short_label": "mRSI",
        "badge_source": "MLB",
        "position_split": True,
        # Pitchers: Elite >=.63 | Good .55-.62 | Avg .54 | Below .49-.52 | Poor <=.47
        "tiers_pitcher": [
            ("Elite", 0.63, "good"),
            ("Good", 0.55, "good"),
            ("Avg", 0.54, "watch"),
            ("Below Avg", 0.49, "watch"),
            ("Poor", None, "flag"),
        ],
        # Position players: Elite >=.61 | Good .54-.60 | Avg .53 | Below .46-.52 | Poor <=.44
        "tiers_position_player": [
            ("Elite", 0.61, "good"),
            ("Good", 0.54, "good"),
            ("Avg", 0.53, "watch"),
            ("Below Avg", 0.46, "watch"),
            ("Poor", None, "flag"),
        ],
    },
    "Hop Test RSI (10/5)": {
        "short_label": "Avg RSI",
        "badge_source": "Reference",
        "position_split": False,
        # AdaptPTPD's generic reactive-strength-ability bands (not MLB,
        # not position-split): World class >3.0 | High 2.5-3.0 |
        # Well established 2.0-2.5 | Moderate 1.5-2.0 | Low <1.5
        "tiers": [
            ("World Class", 3.0, "good"),
            ("High Level", 2.5, "good"),
            ("Well Established", 2.0, "watch"),
            ("Moderate", 1.5, "watch"),
            ("Low", None, "flag"),
        ],
    },
}

REFERENCE_TEST_NAMES = set(FORCE_PLATE_STANDARDS.keys())


def _tiers_for(test_name, is_pitcher):
    config = FORCE_PLATE_STANDARDS.get(test_name)
    if config is None:
        return None, None
    if config["position_split"]:
        tiers = config["tiers_pitcher"] if is_pitcher else config["tiers_position_player"]
    else:
        tiers = config["tiers"]
    return config, tiers


def classify(test_name, raw_value, is_pitcher):
    """Return the tier a raw value falls into for one of the covered
    metrics, or None if this metric isn't covered or raw_value is
    unknown.

    Result dict:
      tier_label       -- e.g. "Good", "Moderate"
      status           -- "good"/"watch"/"flag", for badge coloring
      badge_source      -- "MLB" or "Reference" (see module docstring)
      next_tier_label   -- the tier above this one, or None if already top tier
      next_tier_target  -- that tier's floor value, or None if already top tier
    """
    if raw_value is None:
        return None
    config, tiers = _tiers_for(test_name, is_pitcher)
    if tiers is None:
        return None
    for i, (label, floor, status) in enumerate(tiers):
        if floor is None or raw_value >= floor:
            next_label, next_target = None, None
            if i > 0:
                next_label, next_floor, _ = tiers[i - 1]
                next_label, next_target = next_label, next_floor
            return {
                "tier_label": label,
                "status": status,
                "badge_source": config["badge_source"],
                "next_tier_label": next_label,
                "next_tier_target": next_target,
            }
    return None  # unreachable -- bottom tier's floor is always None


def suggest_idp_target(test_name, current_value, is_pitcher):
    """Suggested IDP goal target: the floor of the tier above the
    player's current result. Returns None when the metric isn't
    covered, current_value is unknown (no baseline yet -- can't tell
    which tier they're in), or the player's already in the top tier
    (nothing higher on this table to suggest -- caller keeps its own
    default rather than getting a None target)."""
    result = classify(test_name, current_value, is_pitcher)
    if result is None:
        return None
    return result["next_tier_target"]
