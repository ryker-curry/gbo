"""
GBO -- "How your grades are built" explainer (Oct 2026, Ryker: "deeper dive
into explaining stuff+, location+, arsenal+, all those metrics. showing the
weights of each variable that goes into the final number ... still needs to
be simple enough that somebody who is not big into numbers can understand
it"). Approved: opens from Pitcher Profile's Overview Glossary (big pop-up)
AND as a section of How to Read GBO; Stuff+ shows one pitch type at a time.

Every weight shown is read from the live model constants
(pitch_grading.STUFF_PLUS_FIXED_WEIGHTS, PITCHING_PLUS_STUFF_WEIGHT,
performance_score.PITCHER_RESULTS_METRICS ...) so this never drifts from
the real math. render_html() returns one self-contained HTML string.
"""

from html import escape

from analytics.pitch_grading import STUFF_PLUS_FIXED_WEIGHTS, PITCHING_PLUS_STUFF_WEIGHT
from analytics.performance_score import PITCHER_RESULTS_METRICS
from analytics.command_metrics import TOWARD_MIDDLE_PENALTY

# feature -> (plain label, what it means)
FEATURE_WORDS = {
    "velocity": ("Velocity", "how hard it's thrown"),
    "vb_trajectory": ("Vertical break", "how much it moves up or down (ride on a fastball, drop on a curveball)"),
    "hb_trajectory": ("Horizontal break", "how much it moves side to side"),
    "total_spin": ("Spin rate", "how fast the ball spins"),
    "spin_axis_offset": ("Spin tilt", "how far the spin is tilted off straight backspin"),
    "spin_efficiency": ("Spin efficiency", "how much of the spin actually turns into movement"),
    "gyro_degree": ("Gyro (bullet) spin", "spin that doesn't create movement"),
    "release_height": ("Release height", "how high you let go of the ball"),
    "release_side": ("Release side", "how far out to the side you let go"),
    "velocity_differential": ("Speed gap off your fastball", "how much slower it is than your own fastball"),
}

PITCH_ORDER = ["4-Seam Fastball", "2-Seam Fastball", "Cutter", "Slider", "Curveball", "Changeup", "Splitter"]

RESULTS_WORDS = {
    "FIP": ("FIP", "strikeouts, walks, HBP and home runs -- the things a pitcher controls (lower is better)"),
    "WHIP": ("WHIP", "walks + hits per inning (lower is better)"),
    "K/BB": ("K/BB", "strikeouts for every walk"),
    "CSW %": ("CSW %", "called strikes + swinging strikes per pitch"),
    "Zone Execution %": ("Hit-the-spot %", "pitches that landed in the called box or within 3 inches"),
}

CSS = """
.gbo-gx{font-size:.92rem;line-height:1.45}
.gbo-gx h4{font-size:1.02rem;margin:18px 0 4px;color:var(--gbo-text)}
.gbo-gx h4:first-child{margin-top:0}
.gbo-gx .intro{color:var(--gbo-text-2);margin:0 0 8px}
.gbo-gx .scale{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 4px}
.gbo-gx .scale span{border:1px solid var(--gbo-border);border-radius:6px;padding:3px 8px;font-size:.8rem;background:var(--gbo-bg-raised)}
.gbo-gx .card{border:1px solid var(--gbo-border);border-radius:10px;padding:12px 14px;margin:10px 0;background:var(--gbo-bg-raised)}
.gbo-gx .what{margin:0 0 6px}
.gbo-gx .recipe{font-size:.84rem;color:var(--gbo-text-2);margin:6px 0 0}
.gbo-gx .bar{display:grid;grid-template-columns:minmax(120px,190px) 1fr 44px;gap:8px;align-items:center;margin:5px 0}
.gbo-gx .bar .n{font-weight:600;font-size:.84rem}
.gbo-gx .bar .n small{display:block;font-weight:400;color:var(--gbo-text-muted);font-size:.72rem;line-height:1.2}
.gbo-gx .bar .t{height:12px;border-radius:6px;background:var(--gbo-bg-card);overflow:hidden;border:1px solid var(--gbo-border)}
.gbo-gx .bar .f{height:100%;border-radius:6px;background:#3E8EDE}
.gbo-gx .bar .f.neg{background:#D96C3D}
.gbo-gx .bar .v{font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
.gbo-gx .tag{display:inline-block;font-size:.68rem;font-weight:700;border-radius:4px;padding:1px 5px;margin-top:2px}
.gbo-gx .tag.less{background:rgba(217,108,61,.18);color:#E08A5F}
.gbo-gx details{border:1px solid var(--gbo-border);border-radius:8px;margin:6px 0;background:var(--gbo-bg-card)}
.gbo-gx summary{cursor:pointer;padding:7px 12px;font-weight:600}
.gbo-gx details[open] summary{border-bottom:1px solid var(--gbo-border)}
.gbo-gx details .in{padding:6px 12px 10px}
.gbo-gx .note{font-size:.78rem;color:var(--gbo-text-muted);margin-top:6px}
@media (max-width:700px){.gbo-gx .bar{grid-template-columns:110px 1fr 40px}}
"""


def _e(s):
    return escape(str(s))


def _bar(name, sub, pct, neg=False, tag=None):
    t = f'<span class="tag less">{_e(tag)}</span>' if tag else ""
    return (f'<div class="bar"><div class="n">{_e(name)}<small>{_e(sub)}</small>{t}</div>'
            f'<div class="t"><div class="f{" neg" if neg else ""}" style="width:{max(pct, 2):.0f}%"></div></div>'
            f'<div class="v">{pct:.0f}%</div></div>')


def stuff_shares(pitch_type):
    """[(feature, share %, negative?)] for one pitch type, biggest first --
    share = |weight| / total |weight|. Zero-weight features are left out."""
    w = STUFF_PLUS_FIXED_WEIGHTS[pitch_type]
    total = sum(abs(v) for v in w.values())
    rows = [(f, 100 * abs(v) / total, v < 0) for f, v in w.items() if v]
    return sorted(rows, key=lambda r: -r[1])


def _stuff_block(open_type=None):
    types = [t for t in PITCH_ORDER if t in STUFF_PLUS_FIXED_WEIGHTS] + \
            [t for t in STUFF_PLUS_FIXED_WEIGHTS if t not in PITCH_ORDER]
    open_type = open_type if open_type in types else types[0]
    out = []
    for t in types:
        bars = "".join(_bar(FEATURE_WORDS[f][0], FEATURE_WORDS[f][1], pct, neg,
                            "less is better" if neg else None) for f, pct, neg in stuff_shares(t))
        unused = [FEATURE_WORDS[f][0] for f, v in STUFF_PLUS_FIXED_WEIGHTS[t].items() if not v]
        note = f'<div class="note">Not counted for this pitch: {_e(", ".join(unused))}.</div>' if unused else ""
        out.append(f'<details name="gbo-gx-stuff"{" open" if t == open_type else ""}><summary>{_e(t)}</summary>'
                   f'<div class="in">{bars}{note}</div></details>')
    return "".join(out)


def render_html(open_type=None):
    s_w = round(100 * PITCHING_PLUS_STUFF_WEIGHT)
    n_res = len(PITCHER_RESULTS_METRICS)
    res_bars = "".join(_bar(RESULTS_WORDS.get(k, (k, ""))[0], RESULTS_WORDS.get(k, (k, ""))[1], 100 / n_res)
                       for k in PITCHER_RESULTS_METRICS)
    perf = [("Stuff+", "how nasty your pitches are"), ("Location+", "where you put them"),
            ("Command+", "how close you hit your target"), ("Arsenal", "your whole pitch mix"),
            ("Results", "what actually happened in games")]
    perf_bars = "".join(_bar(n, d, 100 / len(perf)) for n, d in perf)
    return f"""
<div class="gbo-gx"><style>{CSS}</style>
<h4>First: how to read any "+" grade</h4>
<p class="intro">Every grade on this page uses the same scale. <b>100 = our team's average</b> for that same pitch.
Every 10 points is a big step.</p>
<div class="scale"><span>80 · well below our average</span><span>90 · below</span><span><b>100 · team average</b></span>
<span>110 · clearly above</span><span>120+ · one of our best</span></div>
<p class="note">Compared to our own staff, not to D2 or MLB. A slider is only ever compared to our other sliders.</p>

<div class="card">
<h4>Stuff+ -- how nasty is the pitch?</h4>
<p class="what">Grades the pitch itself from Rapsodo: speed, movement and spin. It doesn't care where the pitch
went or what the hitter did. Each pitch type has its own recipe, because a great curveball and a great fastball
get there in different ways. The bars show how much each ingredient counts toward the grade. Tap a pitch to see
its recipe.</p>
{_stuff_block(open_type)}
<p class="recipe"><b>How it adds up:</b> each ingredient is compared to our team's average for that pitch. Being
above average on a big ingredient (like velocity on a fastball) moves your grade a lot; a small one barely moves
it. Orange bars are "less is better". Want to see exactly which ingredients helped or hurt <i>your</i> pitch?
Open the <b>Arsenal</b> view and look at the Stuff+ Breakdown.</p>
</div>

<div class="card">
<h4>Location+ -- did you put it in a good spot?</h4>
<p class="what">Grades the <b>spot</b> each pitch went to. GBO splits the plate into four areas: <b>Heart</b>
(middle), <b>Shadow</b> (the edges), <b>Chase</b> (just off the plate) and <b>Waste</b> (way off). Every pitch gets
how well our team usually does with <i>that pitch type</i> in <i>that area</i> -- not what happened on that one pitch,
so a perfect slider on the edge still grades well even if the hitter got lucky.</p>
{_bar("How good that spot is for that pitch", "our team's average result there", 100)}
<p class="recipe">Sliders and changeups at the edges or just off the plate usually grade well; fastballs over the
heart or pitches way off the plate (easy balls) usually don't. Your grade is your average spot compared to the rest
of our staff -- 10 points is one step between pitchers, and with only a few pitches you stay close to 100.</p>
</div>

<div class="card">
<h4>Command+ -- did you hit the target?</h4>
<p class="what">Grades how close each pitch landed to where the catcher set up, compared to our team for the same
pitch type. Then your average is compared to the rest of our staff.</p>
{_bar("Distance from the target", "how far it missed the called spot", round(100 / (1 + TOWARD_MIDDLE_PENALTY)))}
{_bar("Extra if it missed toward the middle", "a miss over the heart gets hit", round(100 * TOWARD_MIDDLE_PENALTY / (1 + TOWARD_MIDDLE_PENALTY)))}
<p class="recipe"><b>How it works:</b> every inch you miss the spot counts. If the miss drifted toward the middle of
the plate, that part counts half again, because a miss over the heart gets hit. Missing off the plate is still a
miss -- it doesn't get you a better grade. With only a few pitches charted, your grade stays close to 100 until
there's enough to trust it.</p>
</div>

<div class="card">
<h4>Pitching+ -- stuff and location together</h4>
<p class="what">One grade per pitch that blends how good it was with where you put it.</p>
{_bar("Stuff+", "the pitch itself", s_w)}{_bar("Location+", "where it went", 100 - s_w)}
</div>

<div class="card">
<h4>Arsenal -- your whole mix</h4>
<p class="what">Your Pitching+ for each pitch, counted by how often you throw it. If you throw your fastball 60% of
the time, the fastball is 60% of your Arsenal grade.</p>
{_bar("Fastball (example: thrown 60%)", "counts 60%", 60)}{_bar("Slider (example: thrown 25%)", "counts 25%", 25)}
{_bar("Changeup (example: thrown 15%)", "counts 15%", 15)}
<p class="recipe">So getting better at the pitch you throw most moves your Arsenal grade the most.</p>
</div>

<div class="card">
<h4>Results -- what actually happened in games</h4>
<p class="what">Your game numbers, each compared to the rest of our staff, counted equally.</p>
{res_bars}
</div>

<div class="card">
<h4>Performance -- the overall number</h4>
<p class="what">The five grades above, counted equally. One number for "how well is he pitching".</p>
{perf_bars}
<p class="recipe">Arsenal is built from Stuff+ and Location+, so how good your pitches are counts for a little more
than it looks here.</p>
</div>

<p class="note">Small samples bounce around. Trust a grade more once it's built from a few outings, not one.</p>
</div>
"""
