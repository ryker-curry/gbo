"""
GBO — Integrated Insights (spec Section 27): IDPGoal <-> RapsodoPitch metric mapping.

The Pitcher-Specific AssessmentTestType rows seeded in seed_lookups.py
(PITCHER_SPECIFIC_TESTS) were originally written against Rapsodo's own
column vocabulary -- Velocity, Spin Rate, Horizontal Break, and so on --
because they were built for the old Assessment-based Rapsodo import path.
Now that pitch data lands in RapsodoPitch instead (Phases 1-3), an
IDPGoal targeting one of these test types should compute its live
baseline/current value from RapsodoPitch, not from AssessmentResult,
since nothing writes new AssessmentResult rows under Pitcher-Specific
any more.

This module is the single place that mapping lives, so pages/idp.py
doesn't have to know RapsodoPitch's column names, and so the mapping
isn't duplicated if anything else ever needs it.

One test type is deliberately left unmapped: "Spin Axis". Spin axis is
clock/angular data that wraps at 0/360 -- averaging it correctly requires
circular (vector) averaging, exactly like visualizations/spin_axis_chart.py
already does for the dashboard's average-by-pitch-type chart. Reusing
that correctly for a goal's baseline/current/target semantics (which
assume a plain increase-or-decrease-toward-a-target number) hasn't been
thought through yet, so rather than quietly average clock angles the
wrong way, Spin Axis goals keep using the legacy AssessmentResult path
for now. Flag to Ryker if a real Spin Axis goal is needed.
"""

# AssessmentTestType.test_name (Pitcher-Specific category) -> RapsodoPitch
# column name. Every non-circular Pitcher-Specific test from
# seed_lookups.PITCHER_SPECIFIC_TESTS maps 1:1 to a RapsodoPitch column
# already used elsewhere in the Rapsodo Bullpen Analytics module (see
# visualizations/bullpen_charts.py and visualizations/spin_axis_chart.py
# for where each of these is used on the dashboard).
RAPSODO_FIELD_BY_TEST_NAME = {
    "Velocity": "velocity",
    "Spin Rate": "total_spin",
    "Spin Efficiency": "spin_efficiency",
    "Horizontal Break": "hb_spin",
    "Induced Vertical Break": "vb_spin",
    "Release Height": "release_height",
    "Release Side": "release_side",
    "Extension": "release_extension",
    "Vertical Approach Angle": "vertical_approach_angle",
    "Horizontal Approach Angle": "horizontal_approach_angle",
    "Plate Height": "plate_z_ft",
    "Plate Side": "plate_x_ft",
    # "Spin Axis" intentionally omitted -- see module docstring.
}


def rapsodo_field_for_test_name(test_name):
    """AssessmentTestType.test_name -> RapsodoPitch attribute name, or
    None if this test has no Rapsodo equivalent (e.g. Spin Axis, or any
    custom Pitcher-Specific test Ryker adds later that isn't one of
    Rapsodo's own columns)."""
    return RAPSODO_FIELD_BY_TEST_NAME.get(test_name)


def average_rapsodo_metric(pitches, field_name):
    """Plain arithmetic mean of a RapsodoPitch numeric field across the
    given pitches, skipping any that are null. Returns None if there's
    no usable data. Not for spin_axis_degrees / spin_direction_clock --
    those need circular averaging (see module docstring), not this."""
    values = [float(getattr(p, field_name)) for p in pitches if getattr(p, field_name) is not None]
    if not values:
        return None
    return sum(values) / len(values)
