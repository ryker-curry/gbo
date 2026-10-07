"""
GBO -- "How to Read GBO" guide content (Oct 2026, Ryker approved Part 2).

Plain-English, one section per page/view: what it shows, how to use it,
what good looks like. Rendered by shiny_app/modules/how_to_read.py (the
full guide page) and by the "How to read this" links on key pages
(ui_helpers.how_to_link(key) -> a modal with just that section).

Each section:
  key      -- id used by how_to_link()
  title    -- heading
  who      -- "all", "pitchers", "hitters" or "staff" (who it's mainly for)
  pages    -- nav titles that open it (first one this role can open is used)
  shows    -- one or two sentences
  use      -- how to use it (bullets)
  good     -- what good looks like (bullets)
"""

GUIDE = [
    {
        "key": "basics", "title": "The basics: grades, plus stats and colors", "who": "all", "pages": [],
        "shows": "A few ideas show up on almost every page. Learn these once and the rest of GBO reads easily.",
        "use": [
            "Plus stats (OPS+, ERA+, K%+ ...): 100 = the 2026 NCAA Division II average. 120 means 20% better than "
            "a D2-average player, 80 means 20% worse. Higher is ALWAYS better -- stats where lower is better "
            "(ERA, WHIP, walks for pitchers, strikeouts for hitters) are flipped for you.",
            "Stuff+, Location+, Command+, Pitching+: 100 = OUR team's average for that same pitch type. Every 10 "
            "points is about one standard deviation, so 110 is clearly above our average and 90 clearly below.",
            "Team percentile: where you rank on our own roster (90th = better than 90% of the team).",
            "Green = good, yellow = about average / keep an eye on it, red = needs work. Gray means not enough "
            "data yet -- don't read anything into it.",
            "Small samples lie. A few at-bats or one outing can swing any number. Look for the same story "
            "across several games before changing anything.",
        ],
        "good": ["Above 100 on plus stats and grades.", "The same strength showing up week after week."],
    },
    {
        "key": "today", "title": "Today (top of your dashboard)", "who": "all", "pages": ["Dashboard"],
        "shows": "Your day at a glance. Players: whether your arm is ready, your last game, your goals and your newest "
                 "weekly report. Coaches: who can throw, the last game, charting that still needs fixing and goals "
                 "that are slipping.",
        "use": [
            "Click any link at the bottom of a box to jump straight to that page.",
            "Pitchers: \"Rested on ...\" is the first day the rest chart says you're ready again.",
            "Coaches: \"Charting\" counts games in the last two weeks that are missing pieces or don't match the "
            "official box score -- fix those first so every report stays right.",
        ],
        "good": ["Players: green arm status and goals marked On track or Met.",
                 "Coaches: charting at 95%+ and no box-score mismatches."],
    },
    {
        "key": "pitcher_profile", "title": "Pitcher Profile", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Everything about a pitcher in one place, filtered by dates, pitch type and game type. The View "
                 "menu is grouped: Summary (Overview, Trends), Stuff & Shape (Metrics, Arsenal, Tunneling+, Arsenal "
                 "Plan), Command (Command & Execution, Zone) and Usage & Results (Results, Count Leverage, Sequencing).",
        "use": [
            "Overview: your line (IP, K, BB, WHIP, TBIP, FIP), plus stats vs D2, and your Stuff+/Location+/Pitching+ "
            "grades overall and by pitch.",
            "TBIP = bases you give up per inning (walks, HBP and hits, with a double counting 2, a homer 4). In college "
            "each base turns into about half a run, so every free pass costs you -- lower is better.",
            "Arsenal: each pitch's shape (velo, movement, spin) and its Stuff+ breakdown -- the bars show exactly "
            "which traits add or take away from the grade, compared only to the same pitch type on our staff "
            "(your slider vs our sliders).",
            "Results: what hitters did against each pitch, vs RHH and LHH.",
            "Trends: one point per game (or per week) so you can see if a stat is moving the right way. The "
            "thick line smooths out one-game noise; the dashed lines are the team and D2 averages.",
        ],
        "good": [
            "Strike % around 65%+, first-pitch strikes 60%+, early & ahead often.",
            "Stuff+ or Location+ above 100 on the pitches you throw most.",
            "Trend lines moving toward your goal over several games, not just one.",
        ],
    },
    {
        "key": "grades", "title": "How the pitching grades are built (Stuff+, Location+, Command+ ...)",
        "who": "pitchers", "pages": ["Pitcher Profile", "My Pitcher Profile"], "html": "grade_explainer",
        "shows": "What goes into each grade and how much each ingredient counts, in plain words.",
        "use": [
            "Stuff+ has a different recipe for each pitch -- tap a pitch to see what matters most for it.",
            "Use the biggest bars to decide what to train: they move your grade the most.",
            "To see which ingredients helped or hurt YOUR pitch, open Pitcher Profile > Arsenal > Stuff+ Breakdown.",
        ],
        "good": ["100 is our team average. 110+ is clearly above it."],
    },
    {
        "key": "stuff_breakdown", "title": "Why your stuff grades what it does (Stuff+ breakdown)", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Stuff+ starts at a baseline and each trait (velo, vertical break, horizontal break, spin, "
                 "release, velo gap off your fastball for changeups) adds or subtracts points. The pieces add up "
                 "exactly to your grade.",
        "use": [
            "Green bars = traits helping the pitch, red bars = traits costing it.",
            "Each trait is compared to the same pitch type on our staff only.",
            "The strip charts show where you sit among our pitchers for that trait.",
            "The outcomes chart shows runs saved per 100 pitches by result (swings and misses, weak contact ...) "
            "compared to the team.",
        ],
        "good": ["Your biggest green bar is the thing to keep; your biggest red bar is the thing to train."],
    },
    {
        "key": "zone_execution", "title": "Zone Execution % (hitting your spot)", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "How often you put the pitch where the catcher called it. Find it on Pitcher Profile > Command & "
                 "Execution (also called Hit-the-spot % on the reports).",
        "use": [
            "A pitch hits its spot if it lands in the called box or within 6 inches (half a foot) of it.",
            "Calls off the plate count anywhere off the plate on that side -- a chase pitch way outside still did its job.",
            "By pitch: which pitch you command best and worst. By count: do you lose the spot when you're behind or "
            "with two strikes?",
            "When you miss: up, down, arm side or glove side -- and how often a miss ends up over the middle "
            "(the misses that get hit).",
            "Command Execution % is its partial-credit partner: 4 points within 4 in of the box, 3 within 8, 2 within "
            "12, 1 within 16, 0 beyond, averaged out of 4. Zone Execution % = how often you hit it; Command "
            "Execution % = how close you usually get.",
        ],
        "good": ["Our staff hit about 1 in 3 spots this fall (33%) -- anything above that is better than our average.",
                 "Fewer misses ending up over the middle."],
    },
    {
        "key": "hitter_profile", "title": "Hitter Profile", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Everything about a hitter, filtered by dates and pitch type. The View menu is grouped: Summary "
                 "(Overview, Team Percentile Ranks, Trends), Approach (Discipline & Decisions, Counts & Situations), "
                 "Matchups (How Pitchers Attack Me, Results by Pitch Type, Results by Pitch Shape) and Contact "
                 "(Batted Ball, Hot Zones, Contact Quality by Zone, Spray Chart).",
        "use": [
            "Overview: your slash line (AVG/OBP/SLG/OPS), QAB %, plus stats vs D2.",
            "Results by Pitch Type: how you do vs fastballs, breaking balls and offspeed -- where the damage and "
            "the misses come from.",
            "First Pitch & Two Strikes: are you ready to hit early, and do you battle with two strikes?",
            "Team Percentile Ranks: where you rank on our roster in each key stat.",
        ],
        "good": ["OPS+ and wOBA+ over 100.", "QAB % at or above 54% (our goal).",
                 "Chase % going down and swing decision % going up over time."],
    },
    {
        "key": "hot_zones", "title": "Hot Zones", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Where you do damage when you put the ball in play: AVG or SLG on balls in play for each part of "
                 "the zone, for all pitchers, vs RHP and vs LHP.",
        "use": [
            "It's drawn from the catcher's view: left side of the chart = third-base side.",
            "Red = hot, blue = cold. Gray boxes have fewer than 3 balls in play -- not enough to judge.",
            "The 4 outside corner boxes are pitches off the plate you still put in play.",
            "Use it to plan your approach: hunt the red zones early in the count, lay off the blue ones until two "
            "strikes.",
        ],
        "good": ["A clear hot zone you can sit on, and few hits coming on pitches off the plate."],
    },
    {
        "key": "swing_decisions", "title": "Swing Decisions", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Every located pitch graded on the decision, not the result.",
        "use": [
            "Heart of the plate: swing = Good swing, take = Taken strike (a hittable pitch you let go).",
            "Way off the plate: take = Good take, swing = Chase.",
            "The edges (shadow) are your call -- Borderline, not graded -- except with two strikes, when you "
            "protect and a swing is the good decision.",
            "Swing decision % = good swings + good takes out of everything graded.",
        ],
        "good": ["Swing decision % in the 60s or higher.", "Chase % under about 25%.",
                 "Few taken strikes in the heart early in the count."],
    },
    {
        "key": "attack", "title": "How Pitchers Attack Me", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "What pitchers throw you in every count (0-0, 1-0, 0-1 ... 3-2) and where they put it, so you can "
                 "walk up with a plan.",
        "use": [
            "The count table: how often you're in each count, and the pitch mix there.",
            "Pitch mix by count: the colored bars show fastball / breaking / offspeed in each count.",
            "Where they throw it: pick a count and a pitch to see the location habit (in / middle / away from YOUR "
            "side of the plate, up / middle / down).",
            "The notes list clear habits, like \"0-2: breaking balls down and away\".",
        ],
        "good": ["Use it to sit on a pitch: if they go fastball 70% in 1-0, be ready to hit it."],
    },
    {
        "key": "qab", "title": "Quality At-Bats (QAB %)", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Share of your plate appearances that were quality at-bats, using Brian Cain's definition.",
        "use": [
            "An at-bat counts as quality if ANY of these happen: hard-hit ball (barreled or solid, even if it's "
            "caught), walk or HBP, an RBI, moving a runner from 2nd to 3rd with no outs, a sac bunt, a bunt hit, "
            "an 8+ pitch at-bat, or seeing 4+ pitches after falling behind 0-2.",
            "It rewards good at-bats that don't show up in batting average.",
        ],
        "good": ["54% or better is our team goal."],
    },
    {
        "key": "trends", "title": "Trends", "who": "all", "pages": ["Pitcher Profile", "Hitter Profile", "My Pitcher Profile", "My Hitter Profile"],
        "shows": "Your key stats game by game (or week by week) so you can see whether you're getting better.",
        "use": [
            "Dots are single games; the thick line is a rolling average that smooths out one-game noise.",
            "Reference lines: dotted = your own average, gray dashed = team average, gold dashed = D2 average, "
            "green = a goal line (like the 54% QAB goal).",
            "Switch to \"by week\" if you play a lot of short outings.",
        ],
        "good": ["The thick line moving toward the good side over several games."],
    },
    {
        "key": "meeting_report", "title": "Pitcher & Hitter Reports", "who": "all",
        "pages": ["Pitcher Report", "Hitter Report"],
        "shows": "One printable page to go through with a coach, for one game or the whole season.",
        "use": [
            "Key numbers: this game vs your season, the team average and the D2 / MIAA average. ▲ = better, "
            "▼ = worse, ● = about the same.",
            "What went well / What to work on are written for you from the numbers.",
            "Coach's focus is space for notes -- coaches can type notes that print on the sheet.",
            "Use Print / save as PDF to bring it to the meeting.",
        ],
        "good": ["Leave every meeting with one thing to keep doing and one thing to work on."],
    },
    {
        "key": "weekly_report", "title": "Weekly Report", "who": "all", "pages": ["Weekly Reports", "My Weekly Report"],
        "shows": "Your week on one page: what you did (games, bullpens), how your numbers moved vs the week before, "
                 "and your goals. It's also emailed every Monday.",
        "use": [
            "Green arrows = better than last week, red = worse. Small changes aren't shown as moves.",
            "Pitchers also see velo and pitch shape by pitch type for the week.",
        ],
        "good": ["More green than red, and goals that keep moving toward the target."],
    },
    {
        "key": "goals", "title": "Development goals on game stats", "who": "all", "pages": ["My Development", "IDP"],
        "shows": "Goals tied to a real game stat (chase %, strike %, QAB % ...) that update themselves after every "
                 "game.",
        "use": [
            "Pick the stat, how it's measured (last 5 games, last 10 or season to date) and a target. GBO suggests "
            "a stretch target from where you are now.",
            "Status: Met, On track (at least halfway from your start to the target), Making progress, or Off track "
            "(moving the wrong way).",
            "For stats where lower is better (chase %, walks), the goal reads \"under X\".",
        ],
        "good": ["One or two goals at a time, each On track or Met."],
    },
    {
        "key": "arm_care", "title": "Arm Care & Availability", "who": "staff", "pages": ["Arm Care & Availability"],
        "shows": "Who can throw today, from pitch counts and the rest chart, plus coach holds and planned outings.",
        "use": [
            "Rest chart: 1-30 pitches = no rest day needed, 31-45 = 1 day, 46-60 = 2, 61-75 = 3, 76+ = 4.",
            "Limited means 25 pitches max. A coach hold or limit always wins over the automatic status.",
            "Plan outings ahead -- the board warns you if a pitcher won't be rested by that date.",
            "Workload ratio compares the last week of throwing to the last month. Over 1.5 is a spike, and the "
            "pitcher is set to Limited even if he's rested.",
        ],
        "good": ["Everyone you plan to use is green on game day; no workload spikes."],
    },
    {
        "key": "team_report", "title": "Team Game Report", "who": "staff", "pages": ["Team Game Report"],
        "shows": "How we did as a team -- pitching and hitting -- for one game, a series, the season or any dates, "
                 "with every player's own report one click away. Coaches also get it by email after each game.",
        "use": [
            "Cards at the top compare the team to the D2 average (OPS+, ERA+, QAB %).",
            "Standouts list the best and worst individual performances.",
            "Click a player to open their full Pitcher or Hitter Report for the same games.",
        ],
        "good": ["ERA+ and OPS+ over 100 and team QAB % at or above 54%."],
    },
    {
        "key": "data_health", "title": "Data Health & the box score check", "who": "staff", "pages": ["Data Health"],
        "shows": "What's missing or wrong in each game's charting, so every report stays accurate.",
        "use": [
            "Each game gets a % complete score: green 95%+, yellow 80%+, red below.",
            "Box score check: type the official R / H / E / BB / K for both teams. GBO compares it to what the "
            "charting adds up to and shows any number that's off.",
            "\"Fix in Game Tracking\" opens that game so you can correct it.",
        ],
        "good": ["Every game green and every box score matching."],
    },
    {
        "key": "leaderboard", "title": "Pitching & Hitting Leaderboards", "who": "all",
        "pages": ["Pitching Leaderboard", "Hitting Leaderboard"],
        "shows": "The whole staff or lineup side by side, sortable by any stat, with plus stats vs D2. Pick any "
                 "dates (season to date by default).",
        "use": ["Tick the columns you care about, then click a stat under the table to sort best to worst.",
                "Hitting: hitters under the Min PA box drop to the bottom, grayed out -- a hot 2-for-2 doesn't top "
                "the list.",
                "Compare like with like -- starters and relievers pile up innings very differently."],
        "good": ["Look at rate stats (K-BB %, strike %, Stuff+, OPS+, QAB %, chase %) as much as totals."],
    },
]

BY_KEY = {s["key"]: s for s in GUIDE}


# Oct 2026: article-batch features (pitching, hitting, data tools) --
# added with the reorganization so "How to read this" covers them.
GUIDE += [
    {
        "key": "ivb_expected", "title": "IVB over expected (ride vs. arm slot)", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Pitcher Profile > Metrics. How much more (or less) ride a pitch has than pitchers with the same arm "
                 "slot get on our staff. Ride mostly follows slot, so the leftover is what surprises hitters.",
        "use": ["Fastballs: + means it carries more than hitters expect from that arm -- it plays up in the zone. "
                "- means it sinks or runs more -- live lower in the zone.",
                "Breaking balls: + = more carry than expected, - = more depth.",
                "Within +/-1.5\" reads as typical. Compared to our staff, not a league."],
        "good": ["A fastball 2\"+ over expected (carry) thrown up, or 2\"+ under (sink) thrown down."],
    },
    {
        "key": "slider_fit", "title": "Slider type & fit", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Pitcher Profile > Arsenal Plan. What his breaking ball actually is (gyro, traditional, sweeper, "
                 "carry sweeper, curveball, slurve) and which slider his fastball suggests he'll spin best.",
        "use": ["Fastball spin efficiency 93%+ leans pronator -- usually a hard gyro slider. 85% or less leans "
                "supinator -- usually a sweeper. In between, either can work.",
                "When that hint and the arm-slot rule disagree, try both grips in a bullpen and let the Rapsodo shape decide.",
                "Past about 12\" of sweep, more sweep adds little -- velo matters more."],
        "good": ["A clear type (not 'traditional') that matches his fit hint."],
    },
    {
        "key": "velo_fade", "title": "Velo fade", "who": "pitchers",
        "pages": ["Bullpen Dashboard", "Pitcher Game Breakdown", "Pitcher Profile"],
        "shows": "Fastball velo by pitch number through a bullpen or a Rapsodo game, with a trend line. Pitcher Profile > "
                 "Trends shows one bar per outing.",
        "use": ["The headline is mph lost per 25 pitches. Under 0.5 = held, 0.5-1.5 = mild fade, more = notable.",
                "Needs 15+ fastballs with a Rapsodo velo. Game velo only exists when Rapsodo was running.",
                "A fade that grows outing to outing is a workload flag -- check Arm Care."],
        "good": ["Held velo (under 0.5 mph per 25) through his normal pitch count."],
    },
    {
        "key": "sequencing", "title": "Sequencing (what follows what)", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Pitcher Profile > Sequencing. Back-to-back pitches to the same hitter (FB -> SL, SL -> SL ...), graded "
                 "on the second pitch: strike %, CSW %, whiff %, chase %, balls in play.",
        "use": ["Filter by hitter hand and the count before the second pitch.",
                "Compare his CSW % on a pair to the team's on the same pair.",
                "Gray rows have fewer than 8 -- don't read into them yet."],
        "good": ["His most-used pairs at or above the team's CSW %."],
    },
    {
        "key": "tunnel_check", "title": "Tunnel check", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Pitcher Profile > Tunneling+. Pairs more than about 20\" apart in movement or 10 mph apart in velo "
                 "can't look like his fastball out of the hand.",
        "use": ["Those pitches still work -- as a change of speed or shape. Judge them on whiffs and results, not "
                "tunnel numbers."],
        "good": ["Secondaries that tunnel, plus one that's a big change of speed or shape."],
    },
    {
        "key": "outperform", "title": "Release & results vs. stuff", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile", "Pitching Leaderboard"],
        "shows": "Pitcher Profile > Overview card, plus Beats Stuff / Release Outlier on the leaderboard. How unusual his "
                 "release is on our staff, and whether his results beat what his Stuff+ predicts.",
        "use": ["Release: his release height, side and extension as a percentile of our staff; tagged when he's in "
                "roughly the top or bottom 10%.",
                "Beats Stuff: runs per 100 pitches better (+) or worse (-) than pitchers with his Stuff+ usually get. "
                "Needs 60+ game pitches."],
        "good": ["A + Beats Stuff -- command, deception or mix carrying average stuff."],
    },
    {
        "key": "arsenal_extras", "title": "Outcome profile & Arsenal Breadth+", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile"],
        "shows": "Pitcher Profile > Arsenal. Outcome profile: what the 60 most similar pitches thrown by other staff "
                 "pitchers got (whiff %, CSW %, ground-ball %). Arsenal Breadth+: how much speed and movement range "
                 "his arsenal covers (100 = staff average).",
        "use": ["If his actual rates beat 'like it', he's getting more from location or sequencing than the shape alone.",
                "Breadth+ is descriptive -- a narrow arsenal that tunnels well can be just as good."],
        "good": ["His actual whiff / CSW at or above what pitches like it get."],
    },
    {
        "key": "data_tools", "title": "Data Health: Rapsodo readings, Pitch labels, Metric check", "who": "staff",
        "pages": ["Data Health"],
        "shows": "Three more tabs on Data Health. Rapsodo readings: sessions where a pitch type sat far off a "
                 "pitcher's normal (misread or mislabeled). Pitch labels: pitchers with readings that don't move like "
                 "their label. Metric check: which stats are stable enough to trust yet.",
        "use": ["Fix labels from Pitch labels -- 'Open' jumps to that pitcher's Fastball Shape or Pitch Type Check.",
                "Metric check splits each pitcher's pitches odd/even: 0.7+ = stable, 0.4+ = getting there, lower = "
                "mostly noise so far. Wider date ranges give truer answers.",
                "Bullpen -> game: if Stuff+ is real, pitchers with better bullpen Stuff+ should get more game whiffs."],
        "good": ["No flagged sessions or labels; game stats moving toward 'stable' as the season fills in."],
    },
    {
        "key": "charter_training", "title": "Charter Training", "who": "staff", "pages": ["Charter Training"],
        "shows": "Arsenal cards (each pitcher's pitch types: velo range, ride, run, spin, tilt, movement plot) and a "
                 "pitch-ID quiz from real Rapsodo readings.",
        "use": ["Keep a pitcher's card open while charting him.",
                "Quiz: 'Pitcher named' to learn arms, 'Pitcher hidden' to learn shapes. Score is for that visit only."],
        "good": ["New charters at 85%+ in 'Pitcher named' before charting a game alone."],
    },
    {
        "key": "decision_runs", "title": "Decision runs & Decision Score", "who": "hitters",
        "pages": ["Hitter Profile", "My Hitter Profile", "Hitting Leaderboard"],
        "shows": "Hitter Profile > Discipline & Decisions. Every swing and take valued in runs for that zone and count; "
                 "Decision Score rolls the discipline stats into one number (100 = team average).",
        "use": ["+ = good decisions. Taking a strike down the middle at 3-1 costs more than at 0-2.",
                "The zone x count table shows exactly where runs are gained and lost; the coaching lines say it in words.",
                "Swing Decision % (rule based) stays next to it."],
        "good": ["Decision runs above 0 and a Decision Score over 100."],
    },
    {
        "key": "counts_situations", "title": "Counts & Situations", "who": "hitters",
        "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Hitter Profile > Counts & Situations. RISP / two-strike / leadoff, count leverage, first pitch & two "
                 "strikes, run value in every count, how long at-bats go, and high-leverage spots.",
        "use": ["Starred counts (2-0, 3-1, 2-1, 1-1) are where hitters who got called up separated themselves.",
                "Early win % = you got to a hitter's count, or put pitch 1 or 2 in play hard. Long at-bats rarely help.",
                "High leverage uses GBO's run leverage (1.0 = average spot) or late & close (7th on, within 2). "
                "Context only -- clutch doesn't carry over."],
        "good": ["+ run value in the starred counts and Early win % at or above the team."],
    },
    {
        "key": "pitch_shape", "title": "Results by Pitch Shape", "who": "hitters",
        "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Hitter Profile > Results by Pitch Shape. How you do against riding vs dead-zone vs sinking fastballs, "
                 "gyro vs sweeping sliders, curveballs, arm slots and velo bands -- from our own pitchers in intrasquads.",
        "use": ["Find the shapes that beat you and ask for those in BP or live at-bats.",
                "Compare to the team row -- some shapes are tough for everyone."],
        "good": ["No shape far below the team in RV/100."],
    },
    {
        "key": "zone_whiff", "title": "In-zone whiff check", "who": "hitters",
        "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Hitter Profile > Trends. Your miss rate on strikes you swing at, over your last 30, against your normal.",
        "use": ["A jump of 10+ points flags on Overview -- often timing or bat path before it shows in results.",
                "Needs 30+ swings at strikes."],
        "good": ["The line at or under your normal."],
    },
    {
        "key": "approach_panel", "title": "Advance Scouting: approach panel", "who": "staff",
        "pages": ["Advance Scouting", "Scouting Reports"],
        "shows": "On each of their pitchers' pages: where each pitch family gets swings and misses, where we do damage "
                 "against that hand, and his mix the 1st, 2nd and 3rd time through our order.",
        "use": ["Red where he wins + pale green where we don't = lay off it. The auto-drafted points say it in words.",
                "Mix changing the 2nd / 3rd time through tells hitters what's coming late."],
        "good": ["A plan built on his best pitch being in zones we can lay off."],
    },
    {
        "key": "bauer_units", "title": "Bauer units", "who": "pitchers",
        "pages": ["Pitcher Profile", "My Pitcher Profile", "Bullpen Dashboard"],
        "shows": "Spin divided by velo (rpm per mph). Spin climbs when you throw harder, so this separates natural "
                 "spin ability from arm speed. In the Metrics table (with a vs-team column) and on Trends.",
        "use": ["Most telling on breaking balls: high Bauer units = a natural spinner.",
                "On Trends: spin up with Bauer units flat = you're throwing harder; Bauer units up = you're actually "
                "spinning it better.",
                "On fastballs it doesn't say how much of the spin moves the ball -- use spin efficiency and IVB over "
                "expected for that."],
        "good": ["Breaking balls above the team's Bauer units for that pitch."],
    },
]
BY_KEY = {s["key"]: s for s in GUIDE}
WHO_LABELS = {"all": "Everyone", "pitchers": "Pitchers", "hitters": "Hitters", "staff": "Coaches & staff"}
