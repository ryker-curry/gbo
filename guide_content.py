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
        "shows": "Everything about a pitcher in one place, filtered by dates, pitch type and game type. Use the View "
                 "menu to switch between Overview, Arsenal, Results, Trends and more.",
        "use": [
            "Overview: your line (IP, K, BB, WHIP, FIP), plus stats vs D2, and your Stuff+/Location+/Pitching+ "
            "grades overall and by pitch.",
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
        "key": "hitter_profile", "title": "Hitter Profile", "who": "hitters", "pages": ["Hitter Profile", "My Hitter Profile"],
        "shows": "Everything about a hitter, filtered by dates and pitch type. Use the View menu for Overview, Hot "
                 "Zones, Swing Decisions, How Pitchers Attack Me, Results by Pitch Type, First Pitch & Two Strikes, "
                 "Team Percentile Ranks and Trends.",
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
        "key": "meeting_report", "title": "Meeting Reports (pitcher and hitter)", "who": "all",
        "pages": ["Pitcher Meeting Report", "Hitter Meeting Report", "My Meeting Report"],
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
            "Click a player to open their full meeting report sheet for the same games.",
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
        "pages": ["Pitching Staff Leaderboard", "Hitting Leaderboard"],
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
WHO_LABELS = {"all": "Everyone", "pitchers": "Pitchers", "hitters": "Hitters", "staff": "Coaches & staff"}
