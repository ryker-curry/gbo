"""
GBO — Guest Overview.

A curated, illustrative, and detailed walkthrough of the platform's
vision -- NOT a real login, and NOT connected to the actual database.
Guests see example numbers and module descriptions only, never real
player data. This is intentional: privacy first, even for a low-stakes
"show the vision" mode.

Written to stand alone for someone who has never seen GBO before --
every assessment category is explained in terms of what it measures and
why it matters for baseball performance, not just named.
"""

import streamlit as st

from ui_components import page_header, page_footer, render_kpi_cards

page_header("Gorilla Baseball Operations")

st.write(
    "A comprehensive player development platform for Pittsburg State Gorilla Baseball -- "
    "combining physical testing, individual development plans, training logs, scheduling, "
    "and role-based dashboards in one place. Below is a detailed look at everything the "
    "platform does."
)

st.caption("You're viewing example data as a guest -- this is not connected to real player records.")

st.divider()
st.subheader("Example: what a coach sees at a glance")
render_kpi_cards([
    {"label": "Players", "value": "24"},
    {"label": "Open IDP Goals", "value": "12", "delta": "3 vs last week", "delta_positive": False},
    {"label": "Assessments (7 days)", "value": "18", "delta": "5 vs last week", "delta_positive": True},
    {"label": "Training Sessions (7 days)", "value": "31", "delta": "8 vs last week", "delta_positive": True},
])

st.divider()
st.header("Player Management")
st.write(
    "The full team roster: name, photo, jersey number, position, class, graduation year, "
    "throws/bats, height, weight, hometown, high school, and status (Active, Injured, Redshirt, "
    "Medical Hold, Inactive). Searchable, filterable, sortable, and exportable to CSV. This is the "
    "single source of truth every other module builds on -- assessments, goals, and sessions are "
    "all tied back to a specific player record here."
)

st.divider()
st.header("Assessments — 11 categories of physical testing")
st.write(
    "Every category below supports full history (not just a snapshot) -- a player can be tested "
    "the same way repeatedly over months or years, and the platform tracks trends (Count, Average, "
    "Max, Min) automatically. Here's what each one measures and why it matters:"
)

assessment_categories = [
    ("Anthropometrics", "18 body measurements",
     "Standing height, wingspan, limb lengths, and more. These are fixed physical traits (not "
     "trainable), but they matter because a player's proportions influence their natural mechanics -- "
     "long levers can help generate velocity or bat speed but may require more mobility work to "
     "control safely, while shorter levers often mean quicker, more repeatable motions."),
    ("Body Composition", "19 metrics via InBody770",
     "Skeletal muscle mass, body fat percentage, and lean/fat mass broken out by limb (including "
     "throwing arm vs. non-throwing arm). This tracks a player's power-to-weight ratio and conditioning "
     "level over an offseason or season, and asymmetries between limbs can flag developing imbalances "
     "before they become injuries."),
    ("Mobility & ROM", "33 range-of-motion measurements",
     "How far each joint moves -- shoulder, elbow, hip, spine, ankle, and more, tested at multiple "
     "sub-regions (Cervical Spine, T-Spine, Lumbar Spine, Hip, Ankle). Restricted mobility anywhere in "
     "the chain limits how efficiently force transfers through the body, and it's one of the most "
     "common root causes of both reduced performance and overuse injury."),
    ("Arm Health", "26 metrics — ROM, strength, pain, and workload",
     "A dedicated deep-dive on the throwing arm: shoulder rotation range, shoulder and grip strength, "
     "elbow mobility, and daily self-reported pain/readiness scores, plus throwing workload counts "
     "(bullpen and game pitch counts). This is the platform's core injury-prevention tool for pitchers "
     "and any position player who throws often -- catching a strength or ROM deficit early can prevent "
     "a shoulder or elbow injury before it happens."),
    ("Upper Body Strength", "6 metrics — push, pull, grip",
     "Bench press load and reps, chin-up load and reps, grip strength. Upper body strength underlies "
     "bat speed and throwing velocity -- a stronger, more stable upper body can produce and control "
     "more force through the swing or throw."),
    ("Lower Body Strength", "15 metrics — bilateral, unilateral, hip, knee",
     "Squat and deadlift loads, isometric mid-thigh pull force, single-leg strength, and hip/knee "
     "force output on each side. Baseball power starts from the ground up -- sprint speed, jump "
     "height, and rotational power at the plate or on the mound all trace back to lower body strength "
     "and how symmetric it is left to right."),
    ("Explosive Power", "13 metrics — jump and reactive power",
     "Countermovement jump height, squat jump, single-leg jumps, broad jump, lateral jumps, and a "
     "plyometric push-up test. This measures how quickly a player can produce force (not just how "
     "much), which is what actually translates strength into bat speed, throwing velocity, and first-step "
     "quickness -- strength alone doesn't win at the plate or on the bases without speed of application."),
    ("Rotational Power", "4 metrics — medicine ball throws",
     "Distance and velocity of a rotational medicine ball throw, both directions. Baseball's core "
     "movements -- the swing and the throw -- are both rotational, so this is one of the most direct "
     "physical proxies for hitting and throwing power the platform tracks."),
    ("Speed", "4 metrics — acceleration and top speed",
     "10-yard and 20-yard sprint times, a flying 10-yard split, and estimated max velocity. Directly "
     "relevant to baserunning and defensive range, and a useful cross-check against lower body "
     "strength and power numbers -- strength gains that don't show up in speed testing may not be "
     "transferring to the field yet."),
    ("Pitcher-Specific (Pitch Characteristics)", "13 metrics via Rapsodo, per pitch",
     "Velocity, spin rate, spin efficiency, spin axis, horizontal/vertical break, release point, "
     "extension, approach angle, and plate location -- captured pitch by pitch. This is what "
     "separates raw arm strength from actual pitch effectiveness: two pitchers can throw the same "
     "velocity, but movement, spin, and location are what determine how hittable each pitch actually is."),
    ("Baseball Performance", "reserved for future use",
     "A placeholder category for future performance metrics not yet defined -- kept open rather than "
     "removed so it's ready whenever the program decides what belongs here."),
]

for name, count_label, explanation in assessment_categories:
    with st.expander(f"{name} — {count_label}"):
        st.write(explanation)

st.divider()
st.header("Individual Development Plans (IDP)")
st.write(
    "A development goal isn't just a note -- it's tied to a specific assessment category, and can "
    "link directly to the exact assessment record that motivated it (e.g. a shoulder mobility deficit "
    "found on a specific date). Each goal can carry action steps (specific tasks with due dates and "
    "status) and progress notes (dated commentary from staff). Training Sessions can be tagged as "
    "'prescribed toward' a specific goal, so a coach can open any goal and see the actual work that's "
    "been logged against it -- not just a plan, but a running record of follow-through."
)

st.divider()
st.header("Training Sessions")
st.write(
    "A day-to-day log of what actually happened: arm care, lifting, conditioning, hitting drills, or "
    "throwing/plyometric work, each with notes, optional player feedback, and next steps. This is "
    "distinct from a formal Assessment (which is periodic testing) -- it's the daily diary that shows "
    "consistency and follow-through over time, and each entry can optionally be linked back to a "
    "specific IDP goal."
)

st.divider()
st.header("Team Schedule, Player Assignments & AT Appointments")
st.write(
    "**Team Schedule** is a shared calendar for team-wide events -- lift days, practices, games. "
    "**Player Assignments** are forward-looking, prescribed tasks for a specific player (e.g. \"today: "
    "throwing program\"), assigned ahead of time by a coach or Athletic Trainer -- separate from the "
    "Training Sessions log of completed work. **Athletic Trainer Appointments** are real, timed "
    "appointments between a specific player and a specific Athletic Trainer. Together, these give "
    "every player a clear picture of what's coming up -- team commitments, individual prescribed work, "
    "and medical appointments -- all in one place on their own dashboard."
)

st.divider()
st.header("Rapsodo & Video Integration")
st.write(
    "Bulk-import an entire Rapsodo pitching session in one upload instead of typing in every pitch "
    "by hand -- the platform maps columns automatically (with sensible pre-filled guesses), converts "
    "units where needed (like spin axis from clock format to degrees), and creates one record per "
    "pitch. Any individual pitch can then have video uploaded and linked directly to it, so a coach "
    "can pull up the exact numbers for a pitch side-by-side with the actual footage -- comparing what "
    "the data says against what the eye sees."
)

st.divider()
st.header("Role-Based Dashboards")
st.write(
    "Every role sees a dashboard built around what actually matters for their job, all pulling from "
    "the same underlying data:"
)
dashboards = [
    ("Head Coach / Coach / Administrator", "A general overview: roster size, open IDP goals, "
     "recent assessments and training sessions, and week-over-week trend deltas."),
    ("Strength Coach", "S&C-specific: recent Upper/Lower Body Strength, Explosive Power, and "
     "Rotational Power assessments, lifting session workload, and upcoming scheduled lifts."),
    ("Athletic Trainer", "Injury and return-to-play focus: a live count of injured/medical-hold "
     "players, recent Arm Health pain and readiness scores, and recent Arm Care sessions."),
    ("Player", "Their own upcoming week: team schedule, their prescribed assignments, and their "
     "Athletic Trainer appointments."),
]
for role, desc in dashboards:
    st.markdown(f"**{role}**")
    st.write(desc)
    st.write("")

st.divider()
st.info("Ready to see the real thing? Log in with a GBO account using the button below.")
if st.button("Go to login", type="primary"):
    st.session_state.gbo_is_guest = False
    st.rerun()

page_footer()