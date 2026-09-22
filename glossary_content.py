"""
GBO -- Glossary content (Sept 2026, Pitcher Profile's per-tab "Glossary"
links).

Ryker's reference is mlbpitchprofiler.com's own /glossary/statistics,
/glossary/zone, /glossary/results, and /glossary/modeling pages -- one
"Glossary" link per tab, opening the definitions relevant to what that
tab actually shows, so a coach or player can click and learn what a
stat means without leaving the page. Content here is GBO's own,
written for GBO's own metrics and formulas (not a copy of that site's
text) -- their pages were used as a reference for WHICH terms are worth
explaining and roughly how much detail belongs in one entry, not as
copy to reproduce.

Deliberately skips plain box-score counting stats that don't need a
definition (BB, K, Hits, At Bats, 1B/2B/3B/HR, Balls, Strikes, Total
Pitches, Swings, Whiffs as raw counts, etc.) -- only rate stats, grades,
and GBO-specific jargon get an entry.

Each section below is a list of (term, definition) tuples, in the order
they should display -- roughly matching the order those terms actually
appear on that tab. shiny_app/ui_helpers.glossary_modal() renders one of
these lists as a modal; shiny_app/modules/pitcher_profile.py wires one
"Glossary" link per view (pp_view) to the matching list here.
"""

OVERVIEW = [
    ("IP / WHIP / FIP", "Traditional pitching-line stats. WHIP = (Walks + Hits Allowed) / IP. FIP is an ERA-shaped estimate built only from K/BB/HBP/HR -- the outcomes a pitcher controls directly -- scaled with GBO's own constants, not real MLB FIP constants."),
    ("Strike %", "Strikes (called, swinging, foul, or in play) as a share of all pitches thrown."),
    ("Zone Execution %", "How often a pitch's actual location landed in the same called cell (the Level-Zone code the dugout signaled in) as the intended one -- a hit-your-spot rate, not just a ball/strike count."),
    ("OBA / wOBA*", "OBA is opponent batting average against this pitcher. wOBA* uses generic linear weights (not MLB's own run-value constants) -- a relative read within this team's own games, not an MLB-exact number."),
    ("Stuff+ / Location+ / Pitching+", "GBO's own pitch-quality grades, each on a 100-point scale where 100 = this TEAM's own average across every graded pitch this season and each 10 points = one standard deviation. Team-relative only -- GBO has no access to league-wide pitch data to compare against a real MLB Stuff+ number. Stuff+ grades a pitch's physical characteristics alone (velocity, movement, spin, release); Location+ grades where it was thrown; Pitching+ combines both into one grade for what the pitch actually did. The number shown here on Overview is blended across every pitch type in this window (each type counted once, not weighted by how often it's thrown) -- for the grade broken out by individual pitch type, see the Arsenal tab."),
    ("Command+", "Same 100-point team-relative scale, built from how far a pitcher's located pitches land from their own CALLED target, compared pitch-type by pitch-type against the team's own average miss distance -- not how far from the plate's center, how far from where the dugout asked for it."),
    ("Arsenal (score)", "Usage-weighted average of Pitching+ across a pitcher's own pitch mix -- a pitch type thrown more often counts for more toward this number."),
    ("Results (score)", "How this pitcher's FIP/WHIP/K-BB%/CSW%/Zone Execution% compare to the rest of the team, blended into one team-relative score."),
    ("Performance", "Equal-weighted blend of Stuff+, Location+, Command+, Arsenal, and Results -- one overall \"how did he pitch\" number, kept separate from the Bucket System's physical/athletic score. A V1 formula; it isn't adjusted for the overlap between Arsenal and Stuff+/Location+ (Arsenal is itself built from them)."),
    ("Team Percentile / Grade", "The two numbers next to each bar: \"Grade\" is the raw 100-point-scale number above; \"Team Percentile\" converts it to an approximate percentile using the normal curve. It's an approximation from the grade's own distribution, not a true rank against the live roster."),
    ("Pitch Usage", "Share of total pitches thrown, broken out by pitch type."),
    ("Pitching+ Trend", "Pitching+ per pitch, plotted by game date (oldest to newest) -- shows whether a pitcher's stuff-plus-location grade is trending up or down over the selected window."),
]

METRICS = [
    ("Velocity", "Ball speed off the hand, in mph, as read by Rapsodo."),
    ("Spin Rate", "Total spin on the ball, in rpm."),
    ("IVB (Induced Vertical Break)", "Vertical movement caused by spin alone, with gravity's own drop already factored out -- a positive number means the pitch drops less than a spinless pitch would, not that it actually rises (except for a true rise ball)."),
    ("HB (Horizontal Break)", "Side-to-side movement from the pitcher's own release line, in inches."),
    ("Release Height / Release Side", "Where the ball leaves the hand: Release Height is measured straight up from the ground, Release Side is measured left/right from the center of the rubber."),
    ("Spin Axis", "The tilt of the ball's spin on a clock face, as read directly off the ball by Rapsodo -- e.g. \"12:18\" means the axis is tilted just past straight-up-and-down. GBO shows this single measured value only; it doesn't currently compute a separate \"inferred from movement\" axis to compare it against."),
    ("Spin Efficiency", "The share of total spin that's actually contributing to the ball's movement, versus spin wasted on the bullet-like (gyroscopic) axis that doesn't move the ball at all."),
    ("Gyro Degree", "How much of a pitch's spin is pure bullet-spin (gyro) rather than transverse spin that creates movement -- higher gyro means less of that total spin translates into break."),
    ("Movement chart", "IVB vs. HB, one point per pitch, colored by pitch type -- shows the shape of each pitch's break relative to the others in the arsenal."),
    ("Release Point graphic", "Where each pitch type actually left the hand, viewed from behind or in front of the rubber -- consistency here (a tight cluster) is generally a good sign; different release points for different pitch types can tip a hitter off."),
    ("Spin Axis chart", "Each pitch type's spin axis plotted on a clock face -- \"Average by Pitch Type\" shows one arrow per type at its circular average (the right way to average clock-face angles); \"Individual Pitches\" shows every pitch's own arrow."),
]

RESULTS = [
    ("Weak / Jammed / Off the End / Clipped / Solid Contact / Barreled", "GBO's own six contact-quality grades, assigned live by the charting coach to every ball in play, ordered worst-for-the-pitcher to best-for-the-pitcher on the stacked bar (Weak/Jammed/Off the End/Clipped are all rough outs for the pitcher; Solid and Barreled are increasingly dangerous contact). Each pitch type's bar always sums to 100% of that type's own balls in play."),
    ("Hard Hit %", "Solid Contact + Barreled, as a share of balls in play -- GBO's stand-in for exit-velocity-based Hard Hit% (GBO doesn't track exit velocity)."),
    ("Whiff %", "Swings that missed, as a share of swings."),
    ("SwStr %", "Swings that missed, as a share of EVERY pitch thrown (not just swings) -- a different denominator from Whiff%, so the two numbers are never the same."),
    ("Chase %", "Swings at pitches located outside the strike zone, as a share of all out-of-zone pitches thrown -- an approach/results stat (how often a hitter bit), not a location stat. See the Zone tab's Chase Zone % for the pure \"where was it thrown\" version."),
    ("RV / RV/100", "Run Value: the total run impact of that pitch type's outcomes (negative = runs saved, good for the pitcher). RV/100 normalizes it to a per-100-pitches rate so pitch types and pitchers with different pitch counts can be compared fairly."),
]

ZONE = [
    ("Heart / Shadow / Chase / Waste", "GBO's four attack-zone tiers, nested boxes working outward from the true strike zone: Heart is the heart of the zone (what a hitter is sitting on), Shadow straddles the zone's edge, Chase is further out but still tempting, Waste is nowhere near the zone. Attack Zone Distribution shows what share of ALL located pitches in this window fell in each tier."),
    ("Zone %", "Share of a pitch type's LOCATED pitches that landed inside the actual strike zone."),
    ("Heart / Shadow / Chase / Waste Zone % (per pitch type)", "The same four tiers as above, broken out per pitch type instead of blended across every pitch in the outing -- e.g. \"the slider lives in the Chase zone, the fastball lives in the Heart\"."),
    ("Pitch Location Heatmaps", "Density of where each pitch type actually landed, real-game charted locations only -- darker/denser areas are where the pitcher throws that pitch most often. A pitch type with fewer than 5 located pitches shows plain dots instead of a density surface, since a handful of points can't support a real density read."),
    ("Command Target Zones", "Every located pitch plotted by its distance from its own CALLED target -- the level-zone code the dugout signaled in -- not from the center of the plate. The origin on this chart is always \"exactly where it was asked to go\", wherever that happened to be on the real strike zone."),
    ("Elite / Plus / Average / Fringe / Competitive / Major Miss", "The six miss-distance tiers a located pitch falls into, based on how far it landed from its own target: Elite <=4in, Plus <=8in, Average <=12in, Fringe <=16in, Competitive <=20in, Major Miss beyond that -- the same nested-ring idea as Heart-through-Waste above, but measuring distance from the pitcher's own target instead of from the plate."),
    ("Command+", "See the Overview glossary -- same grade, same team-relative 100-point scale, built from these miss distances."),
]

ARSENAL = [
    ("Usage % / Reliable", "Usage % is that pitch type's share of total pitches thrown. \"Reliable\" means this window has at least the minimum pitch count needed for that pitch type's Stuff+/Location+/Pitching+ grade to hold up -- below it, the grade still shows but can swing wildly with every new pitch."),
    ("Strike % / Called Strike % / FPS %", "Strike% is any strike (swing or take) as a share of all pitches of that type. Called Strike% narrows that to takes the umpire rang up. FPS% (First Pitch Strike%) looks only at the very first pitch of each plate appearance."),
    ("Swing % / Zone Swings", "Swing% is how often that pitch type gets swung at, out of every pitch thrown. Zone Swings counts how many of those swings came against a pitch that was actually located in the strike zone."),
    ("Whiff % / SwStr % / Zone Whiff %", "Whiff% and SwStr% are defined the same as on the Results tab (misses per swing, and misses per pitch, respectively). Zone Whiff% narrows Whiff% further to swings at pitches that were actually in the strike zone -- missing a pitch down the middle is a different skill than missing one out of the zone."),
    ("CSW %", "Called Strikes + Whiffs, as a share of all pitches of that type -- one number for \"how often did this pitch either freeze the hitter or fool him into missing.\""),
    ("Chase %", "Same definition as the Results tab: swing rate on pitches of this type located outside the zone. See the Zone tab's Chase Zone % for the pure location version (where it was thrown, regardless of whether the batter swung)."),
    ("Putaway %", "With two strikes already on the batter, how often this pitch type actually finished the strikeout."),
    ("Dominance %", "Pitches that produced a whiff, a called strike, or a foul ball -- anything except a ball or a ball in play -- as a share of all pitches of that type."),
    ("E+A % (Early + Ahead %)", "Plate appearances this pitch type ended or helped push to a pitcher-friendly count, as a share of batters faced. \"Early\" credits contact within the first 3 pitches at a count that hasn't gone the hitter's way (0-0/1-0/0-1/1-1); \"Ahead\" credits reaching an 0-2 or 1-2 count at any point in the plate appearance. Each plate appearance counts as at most one of the two, never both."),
    ("A3P %", "\"Ahead after 3 pitches\": of the plate appearances that reached a 3rd pitch, how many had the pitcher ahead in the count at that point."),
    ("Sword %", "Swings a coach flagged live as an ugly, off-balance checked swing (\"sword\"), as a share of swings at that pitch type -- a judgment call entered at charting time, not something derived from the pitch outcome."),
    ("Zone Execution %", "Same definition as the Overview glossary, broken out per pitch type here: how often this pitch type's actual location matched its own called cell."),
    ("GB / FB / LD / PopUp %", "Batted-ball-type mix (Ground Ball / Fly Ball / Line Drive / Pop Up) on balls put in play off this pitch type."),
    ("RV / RV/100", "Same definition as the Results glossary, per pitch type."),
    ("Weak / Jammed / ... / Barreled %, Hard Hit %", "Same contact-quality definitions as the Results glossary, per pitch type."),
    ("Zone %, Heart / Shadow / Chase / Waste Zone %", "Same location-mix definitions as the Zone glossary, per pitch type."),
]


# Pitching Staff Leaderboard (Sept 2026, Ryker: "have a glossary
# explaining each stat. pull definitions for stats from trustworthy
# sources, fangraphs, mlb.com, pitchprofiler."). Traditional-stat
# entries below are written from real definitions pulled from MLB.com's
# own glossary (mlb.com/glossary -- ERA, WHIP, FIP, K/BB) and
# FanGraphs' Sabermetrics Library (library.fangraphs.com/pitching/
# rate-stats -- K%, BB%, K-BB%, K/9, BB/9), not copied verbatim (GBO's
# own words, same house style as every other entry in this file), each
# noting which direction is better since that's what the leaderboard's
# own sort uses. The team-relative grade entries (Stuff+ through
# Performance) are GBO's own invented stats -- no external source
# defines them -- so those five are reused word-for-word from the
# Overview glossary above rather than re-written, same numbers/scale, so
# a coach or player doesn't hit two different explanations of "Command+"
# depending on which tab they read it from.
LEADERBOARD = [
    ("IP", "Innings Pitched, standard fractional notation -- X.1 means one out into the next inning, X.2 means two outs in (thirds of an inning, not tenths)."),
    ("ERA", "Earned Run Average: earned runs allowed per 9 innings pitched -- runs that scored without the help of a fielding error or passed ball. MLB.com calls it \"the most commonly accepted statistical tool for evaluating pitchers,\" though team defense and park factors can move it independent of how a pitcher actually threw. Lower is better."),
    ("WHIP", "Walks and Hits per Inning Pitched -- how well a pitcher keeps runners off the bases (MLB.com). Doesn't distinguish how a runner reached (a walk and a home run count the same), and HBP/errors/fielder's-choice reaches aren't counted at all. Lower is better."),
    ("FIP", "Fielding Independent Pitching: an ERA-shaped estimate built only from strikeouts, walks, hit-by-pitches, and home runs -- \"the events a pitcher has the most control over,\" per MLB.com, entirely removing what happens to a ball once it's put in play. GBO's own FIP_CONSTANT is calibrated against real earned-run figures rather than MLB's league-wide one -- see game_stats.py. Lower is better."),
    ("K/9, BB/9, HR/9", "Strikeouts, walks, and home runs allowed, scaled to a 9-inning rate (FanGraphs' own formula: count x 9 / IP) so pitchers with different workloads compare on equal footing. K/9: higher is better. BB/9 and HR/9: lower is better."),
    ("K %, BB %", "Strikeouts (or walks) as a share of batters faced, not innings. FanGraphs prefers this over K/9 or BB/9 for comparing pitchers head to head, since \"worse pitchers will often face more batters per inning than better pitchers\" -- a stat scaled to innings can flatter a pitcher who's just working through more traffic. K%: higher is better. BB%: lower is better."),
    ("K-BB %", "K% minus BB% -- FanGraphs' single-number read on overall command, the gap between how often a pitcher misses bats and how often he loses the zone entirely. Higher is better."),
    ("K/BB", "Strikeout-to-walk ratio: strikeouts divided by walks -- \"how many strikeouts a pitcher records for each walk he allows\" (MLB.com). Higher is better."),
    ("OBA (opponent AVG)", "Opponent batting average against this pitcher -- hits allowed divided by at-bats, the pitching side's version of a hitter's own AVG. Lower is better."),
    ("Strike %", "Same definition as the Overview glossary: strikes (called, swinging, foul, or in play) as a share of all pitches thrown. Higher is better."),
    ("FPS % (First Pitch Strike %)", "Of all completed plate appearances, how many opened with pitch #1 going for a strike (called, swinging, foul, or in play -- a ball or hit-by-pitch on pitch 1 doesn't count). Higher is better."),
    ("CSW %", "Called Strikes + Whiffs, as a share of every pitch thrown -- one number for how often a pitcher either froze the hitter or fooled him into missing entirely. Higher is better."),
    ("Zone Execution %", "Same definition as the Overview glossary: how often a pitch's actual location landed in the same called cell (the Level-Zone code the dugout signaled in) as the intended one -- a hit-your-spot rate, not just a ball/strike count. Higher is better."),
    ("BF, K, BB", "Batters Faced, Strikeouts, and Walks -- the raw counting stats the rate stats above are built from, useful here mainly as a workload/sample-size check next to them."),
    ("Stuff+ / Location+ / Pitching+", "GBO's own pitch-quality grades, each on a 100-point scale where 100 = this TEAM's own average across every graded pitch this season and each 10 points = one standard deviation. Team-relative only -- GBO has no access to league-wide pitch data to compare against a real MLB Stuff+ number. Stuff+ grades a pitch's physical characteristics alone (velocity, movement, spin, release); Location+ grades where it was thrown; Pitching+ combines both into one grade for what the pitch actually did. Higher is better."),
    ("Command+", "Same 100-point team-relative scale, built from how far a pitcher's located pitches land from their own CALLED target, compared pitch-type by pitch-type against the team's own average miss distance -- not how far from the plate's center, how far from where the dugout asked for it. Higher is better."),
    ("Arsenal", "Usage-weighted average of Pitching+ across a pitcher's own pitch mix -- a pitch type thrown more often counts for more toward this number. Higher is better."),
    ("Results", "How this pitcher's FIP/WHIP/K-BB%/CSW%/Zone Execution% compare to the rest of the team, blended into one team-relative score. Higher is better."),
    ("Performance", "Equal-weighted blend of Stuff+, Location+, Command+, Arsenal, and Results -- one overall \"how did he pitch\" number, kept separate from the Bucket System's physical/athletic score. A V1 formula; it isn't adjusted for the overlap between Arsenal and Stuff+/Location+ (Arsenal is itself built from them). Higher is better."),
]


# Hitter Game Report / Hitter Profile (Sept 2026, Ryker: "add glossary
# that explains all hitting stats"). Traditional-stat entries below are
# written from real definitions pulled from MLB.com's own glossary
# (mlb.com/glossary -- AVG, OBP, SLG, OPS, ISO) and FanGraphs'
# Sabermetrics Library (library.fangraphs.com/offense/woba,
# library.fangraphs.com/offense/obp, etc. -- wOBA, OPS+), not copied
# verbatim (GBO's own words, same house style as the pitching-side
# glossaries above), each noting which direction is better. The
# GBO-specific entries (QAB, Ahead/Even/Behind, Contact Quality by
# Zone/Pitch Type, RV) have no external source -- they're GBO's own
# metrics, defined from how this app actually computes them
# (game_stats.py/plate_discipline.py). One shared "Stats Glossary" link
# per page (matching pitching_staff_leaderboard's single-link pattern,
# not pitcher_profile.py's per-tab pattern -- neither hitter page has
# tabs), covering everything shown on either page so a coach or player
# hits the same explanation whichever hitting page they're reading.
HITTING = [
    ('AVG (Batting Average)', 'Hits divided by At Bats -- "the most commonly used statistic for evaluating hitters" (MLB.com), though it treats every hit the same regardless of type and ignores walks/HBP entirely. Higher is better.'),
    ('OBP (On-Base Percentage)', "How often a batter reaches base by any means -- hits, walks, or hit-by-pitch -- divided by plate appearances that could have ended in an out (AB + BB + HBP + SF). MLB.com calls it a broader read on a hitter's value than AVG since it credits walks. Higher is better."),
    ('SLG (Slugging Percentage)', 'Total bases (1B=1, 2B=2, 3B=3, HR=4) divided by At Bats -- measures power, not just contact rate, since extra-base hits count for more. Higher is better.'),
    ('OPS (On-Base Plus Slugging)', "OBP + SLG added together -- a quick single-number blend of getting on base and hitting for power. MLB.com notes it's not perfectly weighted (a point of OBP and a point of SLG aren't actually equal in run value), but it's a fast, widely-used shorthand. Higher is better."),
    ('OPS+', 'OPS scaled against a baseline via the standard Baseball-Reference formula: 100 x (OBP / baseline OBP + SLG / baseline SLG - 1). GBO\'s baseline is this TEAM\'s own average over the same season(s) as the hitter\'s own filtered pitches -- GBO has no access to real league-wide data to compare against an actual MLB OPS+. 100 = exactly team average; each point above or below 100 is that hitter\'s OPS running that percent better or worse than the team. Unlike GBO\'s pitcher-side "+" grades (Stuff+/Location+/etc., which are standard-deviation-scaled), OPS+ is the literal unscaled ratio formula. Higher is better.'),
    ('ISO (Isolated Power)', "SLG minus AVG -- FanGraphs' own read on raw power that strips out batting average entirely, so a hitter who mostly singles and a hitter who mostly walks-or-homers can be told apart even at the same AVG. Higher is better."),
    ('wOBA*', 'Weighted On-Base Average (FanGraphs): every way of reaching base is weighted by its own actual run value, instead of OBP\'s all-or-nothing or SLG\'s arbitrary 1/2/3/4 weighting -- "combines all the different aspects of hitting into one metric, weighting each of them in proportion to their actual run value," per FanGraphs. GBO\'s version (marked wOBA*) uses generic linear weights, not a real MLB/season-specific weight set recalculated from actual run environment -- a relative read within this team\'s own games, not MLB-exact. Higher is better.'),
    ('QAB / QAB %', 'Quality At-Bat: an at-bat that made a positive team contribution, credited automatically when any of several things happened -- a walk, HBP, sacrifice bunt or bunt hit, any RBI (with 2 or fewer outs), moving a runner station-to-station with a productive out, a hard-hit ball in play (GBO\'s own Solid/Barreled contact-quality calls), an at-bat of 8+ pitches, or battling back to see 4+ more pitches after falling behind 0-2. Definition follows Brian Cain\'s published Quality At-Bat criteria. QAB % is QAB divided by PA -- the "quality at-bats per plate appearance" rate those goal figures (54% per game, .500 by season\'s end) are expressed in. Two of Cain\'s original criteria (a hit-and-run play specifically, and reaching on catcher\'s interference) aren\'t separately trackable in GBO\'s data yet, so those two never trigger a credit on their own -- everything else does. Higher is better.'),
    ('Ahead / Even / Behind (count leverage)', "AVG/OBP/SLG/wOBA split by the ball-strike count at the moment the at-bat ended: Ahead = the hitter had more balls than strikes (the count favored them), Behind = more strikes than balls (the count favored the pitcher), Even = equal. A walk always ends Even-or-Ahead by definition (ball four never has more strikes than balls); a strikeout always ends Even-or-Behind for the same reason in reverse. Shows how a hitter's production shifts depending on whether they were controlling the at-bat or fighting from behind in it."),
    ('BB % / K %', 'Walks (or strikeouts) as a share of plate appearances -- how often a hitter draws a walk or strikes out regardless of how many other things happen in between. BB %: higher is better. K %: lower is better.'),
    ('BB/K', 'Walk-to-strikeout ratio -- walks divided by strikeouts, a single-number read on plate discipline (drawing walks relative to chasing/missing into a K). Higher is better.'),
    ('RISP AVG', 'Batting average specifically in at-bats with a Runner In Scoring Position (a runner on 2nd and/or 3rd) -- a "in the moments that matter most" read, separate from overall AVG.'),
    ('2-Strike AVG / 2-Strike K %', "Batting average, and strikeout rate, specifically in plate appearances that reached two strikes -- shows how a hitter performs once they're in the pitcher's most dangerous count, not just their overall numbers."),
    ('Leadoff AVG', 'Batting average specifically when leading off an inning (the first batter to hit that inning) -- table-setting production, separate from overall AVG.'),
    ('Total RV / Avg RV per PA', 'Run Value: each pitch\'s real, data-driven change in expected runs scored the rest of that half-inning (an RE24-style calculation, same run-expectancy framework used across GBO\'s pitching side too), summed for every pitch in the at-bat. Total RV is the sum across every tracked plate appearance; Avg RV/PA divides that by PA count -- GBO\'s most granular "how much offense did this hitter actually create" number, since it accounts for the specific base/out situation each pitch happened in rather than treating every hit the same regardless of context. Higher (more positive) is better.'),
    ('Zone %, Swing %, Chase %, Whiff %, SwStr %', 'Same plate-discipline definitions as the pitching side, read from the hitter\'s own perspective: Zone % = pitches seen inside the strike zone; Swing % = swung at (in or out of zone); Chase % = swung at pitches OUTSIDE the zone; Whiff % = swings that missed, as a share of all swings; SwStr % = swinging strikes as a share of all pitches seen. Zone %/Swing % are read situationally (neither direction is simply "better"); Chase % and Whiff %/SwStr %: lower is generally better for a hitter (fewer bad chases, fewer misses).'),
    ('Zone Contact %, Chase Contact %', "Of pitches swung at inside the zone (or outside it, for Chase Contact %), how often the swing made contact rather than missing entirely -- a hitter's bat-to-ball rate split by whether the pitch was a strike or a chase. Higher is better for both."),
    ('1st-Pitch Swing %', 'How often a hitter swung at the very first pitch of the at-bat. Read situationally -- an approach/aggression number, not inherently good or bad.'),
    ('Zone-Tier Discipline (Heart / Shadow / Chase / Waste)', "Every pitch seen bucketed into four zone tiers by how tempting/hittable its location was: Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside the zone, Waste = nowhere near the zone. Shows a hitter's swing decisions broken out by how good (or bad) the pitch actually was, not just in-zone-vs-out."),
    ('Ground Ball %, Fly Ball %, Line Drive %, Pop Up %', 'Batted-ball type, as a share of all balls put in play -- the shape of contact a hitter makes, independent of the outcome (a hard-hit line drive and a bloop single are both "hits," but very different batted-ball types).'),
    ('Pull %, Center %, Oppo %', "Spray direction on balls in play, split into thirds by the standard 30/30/30-degree spray-angle convention -- Pull = pulled to the batter's power side, Oppo = hit the opposite way, Center = up the middle. Shown as Left/Center/Right Field % instead for switch-hitters or batters with no recorded bats, since Pull/Oppo needs a known handedness to assign a side."),
    ('Barrel %, Hard Contact %', "GBO's own contact-quality read, built from the coach's live contact-quality call on each batted ball (Barreled/Squared Up, Solid, Weak, Jammed, Off the End, Clipped) rather than a measured exit velocity -- GBO has no exit-velo radar, so this is a scouted read, not a real Statcast Barrel. Barrel % is the Barreled/Squared Up share specifically; Hard Contact % folds in Solid contact too. Higher is better for both."),
    ('Contact Quality by Zone / Pitch Type', 'A heat map of the same 0-3 Barrel/Solid/Weak/Miss contact-quality scale, broken out by where in the strike zone (or which pitch type) the contact happened -- shows WHERE and on WHAT a hitter does the most damage, from real game at-bats only (not simulated Hitter Tracking sessions). Same scoring scale Hitter Tracking uses elsewhere in the app.'),
    ('Pitch Locations (by at-bat)', "Every pitch of one plate appearance, numbered in the order it was thrown and plotted at its real location on the strike zone, connected by a thin dotted line so the AT-BAT'S own path (ball away, ball in, strike down the middle...) reads at a glance. Colored by pitch type, same convention as every other pitch-location chart in the app."),
    ('Performance', "GBO's own results-based composite for hitters -- a blend of wOBA, AVG, Chase % (lower better), Whiff % (lower better), and Zone Swing % (higher better), all compared against this team's own average. Kept separate from the Bucket System's physical/athletic score. Hitters don't get a pitch-quality grade the way pitchers do (no equivalent of Stuff+/Location+), so this Results blend IS the whole Hitter Performance score, not one piece of a larger one."),
]


HITTING_OVERVIEW = [
    ('AVG (Batting Average)', 'Hits divided by At Bats -- "the most commonly used statistic for evaluating hitters" (MLB.com), though it treats every hit the same regardless of type and ignores walks/HBP entirely. Higher is better.'),
    ('OBP (On-Base Percentage)', "How often a batter reaches base by any means -- hits, walks, or hit-by-pitch -- divided by plate appearances that could have ended in an out (AB + BB + HBP + SF). MLB.com calls it a broader read on a hitter's value than AVG since it credits walks. Higher is better."),
    ('SLG (Slugging Percentage)', 'Total bases (1B=1, 2B=2, 3B=3, HR=4) divided by At Bats -- measures power, not just contact rate, since extra-base hits count for more. Higher is better.'),
    ('OPS (On-Base Plus Slugging)', "OBP + SLG added together -- a quick single-number blend of getting on base and hitting for power. MLB.com notes it's not perfectly weighted (a point of OBP and a point of SLG aren't actually equal in run value), but it's a fast, widely-used shorthand. Higher is better."),
    ('OPS+', "OPS scaled against a baseline via the standard Baseball-Reference formula: 100 x (OBP / baseline OBP + SLG / baseline SLG - 1). GBO's baseline is this TEAM's own average over the same season(s) as the hitter's own filtered pitches -- GBO has no access to real league-wide data to compare against an actual MLB OPS+. 100 = exactly team average; each point above or below 100 is that hitter's OPS running that percent better or worse than the team. Higher is better."),
    ('ISO (Isolated Power)', "SLG minus AVG -- FanGraphs' own read on raw power that strips out batting average entirely, so a hitter who mostly singles and a hitter who mostly walks-or-homers can be told apart even at the same AVG. Higher is better."),
    ('wOBA*', "Weighted On-Base Average (FanGraphs): every way of reaching base is weighted by its own actual run value, instead of OBP's all-or-nothing or SLG's arbitrary 1/2/3/4 weighting. GBO's version (marked wOBA*) uses generic linear weights, not a real MLB/season-specific weight set -- a relative read within this team's own games, not MLB-exact. Higher is better."),
    ('Total RV / Avg RV per PA', "Run Value: each pitch's real, data-driven change in expected runs scored the rest of that half-inning (an RE24-style calculation), summed for every pitch in the at-bat. Total RV is the sum across every tracked plate appearance; Avg RV/PA divides that by PA count. Higher (more positive) is better."),
    ('Performance', "GBO's own results-based composite for hitters -- a blend of wOBA, AVG, Chase % (lower better), Whiff % (lower better), and Zone Swing % (higher better), all compared against this team's own average over this same window. Kept separate from the Bucket System's physical/athletic score. Hitters don't get a pitch-quality grade the way pitchers do (no equivalent of Stuff+/Location+), so this Results blend IS the whole Hitter Performance score, not one piece of a larger one."),
    ('Team Percentile / Grade', 'The two numbers next to each bar: "Grade" is the raw 100-point-scale number (100 = this team\'s own average over the selected window, each 10 points = one standard deviation); "Team Percentile" converts it to an approximate percentile using the normal curve -- an approximation from the grade\'s own distribution, not a true rank against the live roster.'),
]

HITTING_DISCIPLINE = [
    ('BB % / K %', 'Walks (or strikeouts) as a share of plate appearances. BB %: higher is better. K %: lower is better.'),
    ('BB/K', 'Walk-to-strikeout ratio -- a single-number read on plate discipline. Higher is better.'),
    ('Zone %, Swing %, Chase %, Whiff %, SwStr %', 'Zone % = pitches seen inside the strike zone; Swing % = swung at (in or out of zone); Chase % = swung at pitches OUTSIDE the zone; Whiff % = swings that missed, as a share of all swings; SwStr % = swinging strikes as a share of all pitches seen. Chase % and Whiff %/SwStr %: lower is generally better for a hitter.'),
    ('Zone Contact %, Chase Contact %', 'Of pitches swung at inside the zone (or outside it, for Chase Contact %), how often the swing made contact rather than missing entirely. Higher is better for both.'),
    ('1st-Pitch Swing %', 'How often a hitter swung at the very first pitch of the at-bat. Read situationally -- an approach/aggression number, not inherently good or bad.'),
    ('wOBA*', "Weighted On-Base Average (FanGraphs), GBO's generic-linear-weights version -- see the Overview glossary for the full definition. Shown here as its own team-percentile bar, one metric at a time rather than blended into Performance."),
    ('Zone-Tier Discipline (Heart / Shadow / Chase / Waste)', 'Every pitch seen bucketed into four zone tiers by how tempting/hittable its location was: Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside the zone, Waste = nowhere near the zone.'),
    ('Team Percentile / Grade', 'The two numbers next to each bar: "Grade" is the raw 100-point-scale number (100 = this team\'s own average over the selected window, each 10 points = one standard deviation); "Team Percentile" converts it to an approximate percentile using the normal curve -- an approximation from the grade\'s own distribution, not a true rank against the live roster. Sept 2026, Ryker\'s own reference for these bars was Baseball Savant\'s percentile-rank rows -- GBO has no real league-wide Statcast data, so this is the same team-relative "+" grade system Performance uses, shown one metric (wOBA/Chase %/Whiff %/Zone Swing %) at a time instead of blended together.'),
]

HITTING_BATTED_BALL = [
    ('Ground Ball %, Fly Ball %, Line Drive %, Pop Up %', 'Batted-ball type, as a share of all balls put in play -- the shape of contact a hitter makes, independent of the outcome.'),
    ('Pull %, Center %, Oppo %', "Spray direction on balls in play, split into thirds by the standard 30/30/30-degree spray-angle convention -- Pull = pulled to the batter's power side, Oppo = hit the opposite way, Center = up the middle. Shown as Left/Center/Right Field % instead for switch-hitters or batters with no recorded bats, since Pull/Oppo needs a known handedness to assign a side."),
    ('Barrel %, Hard Contact %', "GBO's own contact-quality read, built from the coach's live contact-quality call on each batted ball (Barreled/Squared Up, Solid, Weak, Jammed, Off the End, Clipped) rather than a measured exit velocity -- GBO has no exit-velo radar, so this is a scouted read, not a real Statcast Barrel. Barrel % is the Barreled/Squared Up share specifically; Hard Contact % folds in Solid contact too. Higher is better for both."),
]

HITTING_SITUATIONAL = [
    ('QAB / QAB %', "Quality At-Bat: an at-bat that made a positive team contribution, credited automatically when any of several things happened -- a walk, HBP, sacrifice bunt or bunt hit, any RBI (with 2 or fewer outs), moving a runner station-to-station with a productive out, a hard-hit ball in play, an at-bat of 8+ pitches, or battling back to see 4+ more pitches after falling behind 0-2. Definition follows Brian Cain's published Quality At-Bat criteria. QAB % is QAB divided by PA. Higher is better."),
    ('Ahead / Even / Behind (count leverage)', 'AVG/OBP/SLG/wOBA split by the ball-strike count at the moment the at-bat ended: Ahead = the hitter had more balls than strikes (the count favored them), Behind = more strikes than balls (the count favored the pitcher), Even = equal.'),
    ('RISP AVG', 'Batting average specifically in at-bats with a Runner In Scoring Position (a runner on 2nd and/or 3rd).'),
    ('2-Strike AVG / 2-Strike K %', 'Batting average, and strikeout rate, specifically in plate appearances that reached two strikes.'),
    ('Leadoff AVG', 'Batting average specifically when leading off an inning (the first batter to hit that inning).'),
]

HITTING_CONTACT_ZONE = [
    ('Contact Quality by Zone / Pitch Type', 'A heat map of the 0-3 Barrel/Solid/Weak/Miss contact-quality scale, broken out by where in the strike zone (or which pitch type) the contact happened -- shows WHERE and on WHAT a hitter does the most damage, from real game at-bats only (not simulated Hitter Tracking sessions). Same scoring scale Hitter Tracking uses elsewhere in the app.'),
]


HITTING_SPRAY = [
    ('Spray Chart', 'Every base hit (1B/2B/3B/HR) plotted at its recorded field location (batted-ball x/y from Game Tracking), colored by hit type -- matches Baseball Savant\'s own default "BASE HITS" spray chart. Outs are not plotted, same as Savant\'s default view.'),
    ('Infield Slice Chart', "The share of all batted balls with a projected distance of 200 ft or less from home plate that land in each of five equal 18-degree field wedges, left field line to right field line -- Baseball Savant's own definition and threshold for this chart. A higher share in a wedge means more weak/short contact hit that direction; wedges are raw field side (left/center/right), not adjusted for batter handedness, same as Savant's own non-mirrored treatment."),
    ('Why hits-only on the Spray Chart', 'Ryker\'s own call (Sept 2026), matching Savant\'s default BASE HITS view rather than plotting every ball in play -- outs would clutter the picture and this chart is meant to answer "where does this hitter get his hits," not "where does he hit the ball."'),
]
