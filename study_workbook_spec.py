"""
GBO -- Testing-workbook column map (Oct 2026, Ryker: rebuild the assessment
importer around the study workbook, STUDY_BBF26 DATA.xlsx -- one tab per
test, one row per pitcher).

Decisions agreed with Ryker (AskUserQuestion, Oct 2026):
  - Import EVERY column. Columns with an existing GBO test type map onto it;
    the rest get new test types (seed_lookups.py: "Dynamometry" and "Force
    Plate Detail" categories).
  - Convert to GBO units on the way in (kg -> lb, m / cm -> in or ft,
    m/s -> mph, N -> lb for shoulder dynamometer force).
  - Asymmetry %, ratios and "best of both legs" columns are NOT imported --
    GBO calculates them itself (analytics/research_analysis.py), the same
    way every time. The ER:IR ratio test types the app already uses are
    filled from the imported peak forces.
  - Same workbook every testing period: this file is built for this exact
    template. Columns it doesn't know are listed in the preview, never
    silently dropped.
  - "10+1" on Speed and MB = 10-yard sprint time.
  - FB VELO&SPIN is imported as the study's fastball outcomes
    (models.ResearchFBOutcome), not as an assessment.
  - Cells the sheet flags (IMTP notes column, Strength cells like
    "355 BELTSQUAT" / "KNEE") are skipped and the note is kept.

SIDES. The sheet says THROW / GLOVE and DRIVE / PLANT (and IMTP says R / L).
GBO's ROM tests are Right / Left and its force tests Drive / Plant, so a
column can name its test with placeholders resolved per player from
Player.throws (the drive leg is on the throwing-hand side):
    {T} / {G}  -> "Right" / "Left" for the throwing / glove side
    {D} / {P}  -> "Right" / "Left" for the drive / plant leg
    {R} / {L}  -> "Drive" / "Plant" for the right / left leg

Each Col:
    header   the sheet's header text (whitespace-normalized when matched)
    group    SH / HIP only: the group header above it ("ER", "IR", "HIP ABD",
             "HIP ADD") -- the same header text appears under both groups
    test     GBO test name (placeholders allowed), or None for non-test kinds
    unit     GBO unit after conversion
    conv     conversion key (CONV) or None
    kind     "value" | "derived" (skipped -- GBO calculates) | "throws" |
             "height_cm" | "note" | "fb:<field>"
    var      the research variable label (Research Project / CSV); defaults
             to "<tab> · <group> <header>"
"""

import re
from collections import namedtuple

Col = namedtuple("Col", ["header", "group", "test", "unit", "conv", "kind", "var"])

LB_PER_KG = 2.2046226218
IN_PER_M = 39.3700787
FT_PER_M = 3.2808399
MPH_PER_MPS = 2.2369363
LB_PER_N = 1 / 4.4482216

CONV = {
    "kg_lb": lambda v: v * LB_PER_KG,
    "m_in": lambda v: v * IN_PER_M,
    "cm_in": lambda v: v / 2.54,
    "m_ft": lambda v: v * FT_PER_M,
    "mps_mph": lambda v: v * MPH_PER_MPS,
    "n_lb": lambda v: v * LB_PER_N,
}


def C(header, test=None, unit=None, conv=None, kind="value", group=None, var=None):
    return Col(header, group, test, unit, conv, kind, var)


def norm(s):
    """Header / name matching: drop non-breaking spaces, collapse runs of
    whitespace, case-insensitive."""
    if s is None:
        return ""
    return re.sub(r"\s+", " ", str(s).replace("\xa0", " ")).strip().lower()


# ---------------------------------------------------------------------------
# Shoulder (SH) and hip (HIP) dynamometry: two header rows
# ---------------------------------------------------------------------------

def _dyn_block(group, side_a, side_b, label, peak_tests, cat_unit_force, conv_force):
    """One ER / IR / ABD / ADD block: max force (existing tests), avg force,
    impulse, time to peak (new tests), asymmetry columns derived."""
    A, B = side_a.upper(), side_b.upper()
    a_word, b_word = peak_tests["words"]
    cols = [
        C(f"{A}_Max Force (N)", peak_tests[A], cat_unit_force, conv_force, group=group),
        C(f"{B}_Max Force (N)", peak_tests[B], cat_unit_force, conv_force, group=group),
        C("Max Force_ASYM", kind="derived", group=group),
        C(f"{A}_ Avg Force (N)", f"{label} Avg Force ({a_word})", cat_unit_force, conv_force, group=group),
        C(f"{B}_ Avg Force (N)", f"{label} Avg Force ({b_word})", cat_unit_force, conv_force, group=group),
        C("AVG FORCE_ASYM", kind="derived", group=group),
        C(f"Max_Impulse_{side_a} (Ns)", f"{label} Impulse ({a_word})", "N s", group=group),
        C(f"Max_Impulse_{side_b} (Ns)", f"{label} Impulse ({b_word})", "N s", group=group),
        C(f"{A}_Time To Peak Force (s)", f"{label} Time to Peak Force ({a_word})", "s", group=group),
        C(f"{B}_Time To Peak Force (s)", f"{label} Time to Peak Force ({b_word})", "s", group=group),
    ]
    return cols


SH = (
    _dyn_block("ER", "THROW", "Glove", "Shoulder ER", {
        "THROW": "Shoulder Strength: Throwing Arm ER Peak Force", "GLOVE": "Shoulder Strength: Non-Throwing Arm ER Peak Force",
        "words": ("Throwing Arm", "Non-Throwing Arm")}, "lbs", "n_lb")
    + _dyn_block("IR", "THROW", "Glove", "Shoulder IR", {
        "THROW": "Shoulder Strength: Throwing Arm IR Peak Force", "GLOVE": "Shoulder Strength: Non-Throwing Arm IR Peak Force",
        "words": ("Throwing Arm", "Non-Throwing Arm")}, "lbs", "n_lb")
    + [C("HAND", kind="throws")]
    + [C(h, kind="derived", group="Ratios") for h in
       ("MAX_Sh ER/IR_THROW", "AVG_ Sh ER/IR_THROW", "MAX_SH ER/IR_GLOVE", "AVG_SH ER/IR_GLOVE")]
)

HIP = (
    _dyn_block("HIP ABD", "DRIVE", "Plant", "Hip Abduction", {
        "DRIVE": "Hip Abduction Force (Drive Leg)", "PLANT": "Hip Abduction Force (Plant Leg)",
        "words": ("Drive Leg", "Plant Leg")}, "N", None)
    + _dyn_block("HIP ADD", "DRIVE", "Plant", "Hip Adduction", {
        "DRIVE": "Hip Adduction Force (Drive Leg)", "PLANT": "Hip Adduction Force (Plant Leg)",
        "words": ("Drive Leg", "Plant Leg")}, "N", None)
    + [C("HAND", kind="throws")]
    + [C(h, kind="derived", group="Ratios") for h in
       ("HIP AD/AB Max Ratio _DRIVE", "HIP AD/AB Max Ratio _PLANT", "HIP AD/AB AVG Ratio_DRIVE", "HIP AD/AB AVG Ratio_PLANT")]
)
# The sheet spells the impulse sides "Max_Impulse_Glove" / "Max_Impulse_Drive" /
# "Max_Impulse_Plant" -- _dyn_block builds those exact strings.

# ---------------------------------------------------------------------------
# Single-header tabs
# ---------------------------------------------------------------------------

SPEED_MB = [
    C("20/10 Fly", "Top Speed: Flying 10 Sprint Time", "s"),
    C("30Y", "30-Yard Sprint Time", "s"),
    C("10+1", "Acceleration: 10-Yard Sprint Time", "s"),
    C("MB DIST_m", "Medicine Ball Shot Put Distance", "ft", "m_ft"),
    C("MB VELO_m/s", "Medicine Ball Shot Put Velocity", "mph", "mps_mph"),
]

_ROM = [("SH ER", "Shoulder", "External Rotation"), ("SH_IR", "Shoulder", "Internal Rotation"),
        ("SH_FLEX", "Shoulder", "Flexion"), ("SH_EXT", "Shoulder", "Extension"),
        ("ELB_FLEX", "Elbow", "Flexion"), ("ELB_EXT", "Elbow", "Extension")]
_HIP_ROM = [("EXT", "Extension"), ("FLEX", "Flexion"), ("AB", "Abduction"), ("AD", "Adduction"),
            ("IR", "Internal Rotation"), ("ER", "External Rotation")]

FIELD = (
    [C("GRIP_THROW_kg", "Grip Strength (Seated, Throwing Hand)", "lbs", "kg_lb"),
     C("GRIP_GLOVE_kg", "Grip Strength (Seated, Glove Hand)", "lbs", "kg_lb"),
     C("Broad Jump_m", "Broad Jump Distance", "in", "m_in"),
     C("SL_Lateral_Jump_Drive_m", "Lateral Jump Distance (Drive Leg)", "in", "m_in"),
     C("SL_Lateral Jump_Plant_m", "Lateral Jump Distance (Plant Leg)", "in", "m_in"),
     C("Vertical Jump_cm", "Vertical Jump (Jump Mat)", "in", "cm_in")]
    # "SH ER_THROW" / "SH_ER_GLOVE": the sheet's own spelling differs by side
    + [C("SH ER_THROW", "Shoulder: {T} External Rotation", "°"), C("SH_ER_GLOVE", "Shoulder: {G} External Rotation", "°")]
    + [C(f"{pre}_{s}", f"{joint}: {{{'T' if s == 'THROW' else 'G'}}} {motion}", "°")
       for pre, joint, motion in _ROM[1:] for s in ("THROW", "GLOVE")]
    + [C(f"HIP_{k}_{s}", f"Hip: {{{'D' if s == 'DRIVE' else 'P'}}} {motion}", "°")
       for k, motion in _HIP_ROM for s in ("DRIVE", "PLANT")]
)

BC = [
    C("Handedness", kind="throws"),
    C("AGE_yrs", "Age", "yrs"),
    C("HT_CM", kind="height_cm", var="BC · Height (in)"),
    C("BM_kg", "Body Weight", "lb", "kg_lb"),
    C("SMM_kg", "Skeletal Muscle Mass", "lb", "kg_lb"),
    C("SMM%", "Skeletal Muscle Mass %", "%"),
    C("BF%", "Percent Body Fat", "%"),
    C("FFM_kg", "Fat-Free Mass", "lb", "kg_lb"),
    C("FM_kg", "Body Fat Mass", "lb", "kg_lb"),
    C("BMI", "Body Mass Index (BMI)", "kg/m2"),
    C("FFMI", "Fat-Free Mass Index (FFMI)", "kg/m2"),
    C("FMI", "Fat Mass Index (FMI)", "kg/m2"),
    C("SMI", "Skeletal Muscle Index (SMI)", "kg/m2"),
    C("FFM_THROW_ARM_kg", "Fat-Free Mass (Throwing Arm)", "lb", "kg_lb"),
    C("FFM_GLOVE_ARM_kg", "Fat-Free Mass (Glove/Non-Throwing Arm)", "lb", "kg_lb"),
    C("FFM TRUNK_kg", "Trunk Lean Mass", "lb", "kg_lb"),
    C("FFM_DRIVE_kg", "Lean Mass (Drive Leg)", "lb", "kg_lb"),
    C("FFM_PLANT_kg", "Lean Mass (Plant Leg)", "lb", "kg_lb"),
    C("TBW_kg", "Total Body Water", "lb", "kg_lb"),
    C("TBW_%", "Total Body Water %", "%"),
    C("ICW_kg", "Intracellular Water", "lb", "kg_lb"),
    C("ECW_kg", "Extracellular Water", "lb", "kg_lb"),
    C("ECW/TBW", "ECW/TBW Ratio", "ratio"),
    C("BMR", "Basal Metabolic Rate (BMR)", "kcal"),
    C("REC CAL", "Recommended Caloric Intake", "kcal"),
]

CMJ = [
    C("BW [KG]", "CMJ Bodyweight", "kg"),
    C("Concentric Duration [ms]", "Countermovement Jump Concentric Duration", "ms"),
    C("Concentric Impulse [N s]", "CMJ Concentric Impulse", "N s"),
    C("Peak Power [W]", "CMJ Peak Power", "W"),
    C("Concentric Peak Force [N]", "CMJ Concentric Peak Force", "N"),
    C("Concentric Peak Velocity [m/s]", "CMJ Concentric Peak Velocity", "m/s"),
    C("Eccentric Duration [ms]", "CMJ Eccentric Duration", "ms"),
    C("Eccentric Peak Force [N]", "CMJ Eccentric Peak Force", "N"),
    C("Eccentric Peak Power [W]", "CMJ Eccentric Peak Power", "W"),
    C("Eccentric Peak Velocity [m/s]", "CMJ Eccentric Peak Velocity", "m/s"),
    C("Jump Height (Imp-Mom) [cm]", "Countermovement Jump Height", "in", "cm_in"),
    C("RSI-modified (Imp-Mom) [m/s]", "Countermovement Jump RSI-Modified", "ratio"),
]

IMTP = [
    C("Knee (45)", "IMTP Knee Angle", "°"),
    C("Hip (35)", "IMTP Hip Angle", "°"),
    C("BW [KG]", "IMTP Bodyweight", "kg"),
    C("Peak Vertical Force [N]", "Isometric Mid-Thigh Pull Peak Vertical Force", "N"),
    C("Peak Vertical Force (Net of BW) [N]", "IMTP Peak Vertical Force (Net of BW)", "N"),
    C("Net Peak Vertical Force [N]", "IMTP Net Peak Vertical Force", "N"),
    C("Peak Vertical Force / BM [N/kg]", "IMTP Peak Vertical Force / BM", "N/kg"),
    C("Net Peak Vertical Force % (Asym) (%)", kind="derived"),
    C("Net Peak Vertical Force [N] (R)", "IMTP Net Peak Vertical Force ({R} Leg)", "N"),
    C("Net Peak Vertical Force [N] (L)", "IMTP Net Peak Vertical Force ({L} Leg)", "N"),
    C("Peak Vertical Force [N] (R)", "Isometric Mid-Thigh Pull Peak Vertical Force ({R} Leg)", "N"),
    C("Peak Vertical Force [N] (L)", "Isometric Mid-Thigh Pull Peak Vertical Force ({L} Leg)", "N"),
] + [C(f"RFD - {ms}ms [N/s]", f"IMTP RFD 0-{ms} ms", "N/s") for ms in (100, 150, 200, 250)] \
  + [C(f"Net Force at {ms}ms [N]", f"IMTP Net Force at {ms} ms", "N") for ms in (100, 150, 200)] \
  + [C(f"Impulse (Net of BW) - {ms}ms [N s]", f"IMTP Impulse (Net of BW) 0-{ms} ms", "N s") for ms in (100, 150, 200)]

HOP = [
    C("BW [KG]", "Hop Test Bodyweight", "kg"),
    C("Average Force [N]", "Hop Test Average Force", "N"),
    C("Average Power [W]", "Hop Test Average Power", "W"),
    C("Flight Time [ms]", "Hop Test Flight Time", "ms"),
    C("Contact Time [ms]", "Hop Test Mean Contact Time", "ms"),
    C("Impulse [N s]", "Hop Test Impulse", "N s"),
    C("Jump Height (Flight Time) [cm]", "Hop Test Jump Height", "in", "cm_in"),
    C("Peak Force [N]", "Hop Test Peak Force", "N"),
    C("Peak Power [W]", "Hop Test Peak Power", "W"),
    C("RSI (Jump Height/Contact Time) [m/s]", "Hop Test RSI (10/5)", "ratio"),
    C("Time to Peak Force [ms]", "Hop Test Time to Peak Force", "ms"),
    C("Landing RFD [N/s]", "Hop Test Landing RFD", "N/s"),
]

# SL Jump: every metric has a best-of-both-legs column (derived: the higher
# leg), DRIVE, PLANT and an asymmetry column (derived).
_SL = [("Concentric Duration [ms]", "Concentric Duration", "ms", None),
       ("Concentric Impulse [N s]", "Concentric Impulse", "Ns", None),
       ("Peak Power [W]", "Peak Power", "W", None),
       ("Concentric Peak Force [N]", "Concentric Peak Force", "N", None),
       ("Concentric Peak Velocity [m/s]", "Concentric Peak Velocity", "m/s", None),
       ("Eccentric Duration [ms]", "Eccentric Duration", "ms", None),
       ("Eccentric Peak Force [N]", "Eccentric Peak Force", "N", None),
       ("Eccentric Peak Power [W]", "Eccentric Peak Power", "W", None),
       ("Eccentric Peak Velocity [m/s]", "Eccentric Peak Velocity", "m/s", None),
       ("Jump Height (Imp-Mom) [cm]", "Height", "in", "cm_in"),
       ("RSI-modified (Imp-Mom) [m/s]", "RSI-Modified", "ratio", None)]
SL_JUMP = [C("BW [KG]", "Single-Leg Jump Bodyweight", "kg")]
for _h, _name, _unit, _conv in _SL:
    _asym = {"Concentric Duration [ms]": "Concentric Duration ASYM (%)"}.get(_h, f"{_h} (Asym)(%)")
    SL_JUMP += [
        C(_h, kind="derived"),
        C(f"{_h}_DRIVE", f"Single-Leg Jump {_name} (Drive Leg)", _unit, _conv),
        C(f"{_h}_PLANT", f"Single-Leg Jump {_name} (Plant Leg)", _unit, _conv),
        C(_asym, kind="derived"),
    ]

STRENGTH = [
    C("FS", "Front Squat Max", "lbs"),
    C("Bench Press", "Neutral Grip/DB Bench Press Max Load", "lbs"),
    C("HBDL", "Hex Bar Deadlift Max", "lbs"),
    C("", kind="note"),               # unnamed 6th column: injury / limitation notes
]

FB = [
    C("AVG VELO", kind="fb:avg_velo"), C("PEAK VELO", kind="fb:peak_velo"),
    C("AVG SPIN RATE", kind="fb:avg_spin"), C("PEAK SPIN RATE", kind="fb:peak_spin"),
    C("# of Pitches", kind="fb:n_pitches"), C("", kind="note"),
]

# tab -> (header row count, first-name column index, the tab's column list,
#         label used for research variable groups)
TABS = {
    "SH": dict(header_rows=2, name_col=0, cols=SH, group="Shoulder dynamometry"),
    "HIP": dict(header_rows=2, name_col=0, cols=HIP, group="Hip dynamometry"),
    "Speed and MB": dict(header_rows=1, name_col=0, cols=SPEED_MB, group="Speed & med ball"),
    "Field Testing": dict(header_rows=1, name_col=0, cols=FIELD, group="Field testing & ROM"),
    "BC": dict(header_rows=1, name_col=0, cols=BC, group="Body composition"),
    "CMJ": dict(header_rows=1, name_col=0, cols=CMJ, group="CMJ"),
    "IMTP": dict(header_rows=1, name_col=1, cols=IMTP, group="IMTP", flag_col=0),
    "Hop": dict(header_rows=1, name_col=0, cols=HOP, group="Hop test"),
    "SL Jump": dict(header_rows=1, name_col=0, cols=SL_JUMP, group="Single-leg jump"),
    "Strength": dict(header_rows=1, name_col=0, cols=STRENGTH, group="Strength"),
    "FB VELO&SPIN": dict(header_rows=1, name_col=0, cols=FB, group="Fastball outcomes", fb=True),
}


def var_label(tab, col):
    """Research variable label for one imported column."""
    if col.var:
        return col.var
    g = f"{col.group} " if col.group and col.group != "Ratios" else ""
    short = TABS[tab]["group"]
    return f"{short} · {g}{norm(col.header).upper() if tab in ('SH', 'HIP') else col.header.strip()}"


def resolve_test(template, throws):
    """Fill {T}/{G}/{D}/{P}/{R}/{L} for a player's throwing hand ('R' / 'L').
    Returns None when the name needs a side and the hand is unknown."""
    if template is None or "{" not in template:
        return template
    if throws not in ("R", "L"):
        return None
    right_is_throw = throws == "R"
    t, g = ("Right", "Left") if right_is_throw else ("Left", "Right")
    r, l = ("Drive", "Plant") if right_is_throw else ("Plant", "Drive")
    return template.format(T=t, G=g, D=t, P=g, R=r, L=l)


NEW_TEST_CATEGORY = {"SH": "Dynamometry", "HIP": "Dynamometry"}   # every other tab -> "Force Plate Detail"


def new_test_types():
    """[(category, test_name, unit)] for every test this workbook needs that
    isn't in seed_lookups' original lists -- seed_lookups seeds exactly
    these (single source of truth, so the two can't drift)."""
    import seed_lookups as sl
    existing = {n for lst in (sl.ANTHROPOMETRICS_TESTS, sl.BODY_COMPOSITION_TESTS, sl.MOBILITY_ROM_TESTS,
                              sl.ARM_HEALTH_TESTS, sl.UPPER_BODY_STRENGTH_TESTS, sl.LOWER_BODY_STRENGTH_TESTS,
                              sl.EXPLOSIVE_POWER_TESTS, sl.ROTATIONAL_POWER_TESTS, sl.SPEED_TESTS,
                              sl.PITCHER_SPECIFIC_TESTS) for n, _u in lst}
    out, seen = [], set()
    for tab, t in TABS.items():
        for col in t["cols"]:
            if col.kind != "value":
                continue
            for hand in ("R", "L"):
                name = resolve_test(col.test, hand)
                if name and name not in existing and name not in seen:
                    seen.add(name)
                    out.append((NEW_TEST_CATEGORY.get(tab, "Force Plate Detail"), name, col.unit))
    return out
