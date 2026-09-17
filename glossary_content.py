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
