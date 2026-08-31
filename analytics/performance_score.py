"""
GBO -- Performance score: game-production composite, kept deliberately
SEPARATE from the Bucket System's physical/athletic composite (Aug 31
2026 design call with Ryker). Bucket System answers "how good an
athlete is this player" (weight-room testing); Performance answers
"how well is he actually producing" (game outcomes, plus -- for
pitchers -- the existing pitch-grading family). Blending the two into
one number would hide exactly the divergence between them that's
useful to a coach: a toolsy player who hasn't translated it to results
yet (a development priority) vs. a grinder whose tools test modest but
who performs (someone whose game plays up).

Same "100 = team average, 10 points = 1 SD" scale as
analytics/command_metrics.py and analytics/pitch_grading.py, so
Performance sits numerically and visually consistent with Stuff+/
Location+/Pitching+/Command+ (pitcher_profile.py blends this module's
output directly against those) rather than switching to Bucket
System's separate 0-100-percentile-of-max convention -- unlike Bucket
System's four scores (which only ever combine with each other),
Performance combines with grades that are already on this scale, so
matching it is what keeps the blend meaningful.

Same "caller owns every DB query" separation as pitch_grading.py --
every function here takes already-computed line dicts (from
game_stats.compute_pitching_line/compute_batting_line and
plate_discipline.compute_hitter_discipline) or lists of them, never
queries the database itself. analytics/profile_queries.py's
team_pitching_lines()/team_hitting_lines() are the query-layer
counterparts that build those lists.

--- Pitcher Performance ---
Ryker's exact call (Aug 31 2026): equal-weighted average (20% each) of
Stuff+, Location+, Command+, Arsenal (usage-weighted Pitching+ across
his mix), and Results (this module's new composite) --
combine_pitcher_performance() below does that final average; it
doesn't recompute any of the four existing grades itself. Deliberately
NOT adjusted for the overlap this creates -- Arsenal's own grade is
built from Stuff+/Location+ per pitch, so pitch-quality carries
roughly 3/5 of the total weight under a plain equal split. Flagged
here and wherever this is shown, not silently corrected -- same "V1
formula, revisit once real scores exist to look at" treatment as every
other composite in this codebase (Stuff+'s equal-weighted features,
Pitching+'s own 60/40 blend).

Results composite inputs (Ryker's pick, Aug 31 2026): FIP, WHIP, K/BB,
CSW %, Execution % -- FIP and WHIP are lower-is-better (sign flipped,
same convention as command_metrics.command_plus's miss-distance
grading); K/BB, CSW %, Execution % are higher-is-better. CSW % isn't a
field game_stats.compute_pitching_line() returns on its own (only
compute_pitch_type_breakdown's per-type/Total rows have it) --
csw_pct() below computes it directly off the same raw pitches instead
of pulling the whole breakdown table just for one number.

--- Hitter Performance ---
Hitters don't have a Stuff+/Location+/Command+/Arsenal equivalent --
those are pitch-quality/pitch-execution concepts, pitcher-specific by
definition (see hitter_profile.py's own module docstring). So Hitter
Performance IS the Results composite, not a blend of several pieces.

Results composite inputs (Ryker's pick, Aug 31 2026): wOBA, AVG,
Chase % (lower better), Whiff % (lower better), Zone Swing % (higher
better) -- AVG here, not "OBA": OBA (opponent AVG) is specifically the
pitching-against-side stat name in compute_pitching_line(); a hitter's
own line from compute_batting_line() calls the same concept "AVG".

--- Reliability ---
MIN_BASELINE_PLAYERS below gates the TEAM baseline -- is there a big
enough pool of pitchers/hitters this window to trust a mean/stdev at
all -- a different axis from pitch_grading.py's MIN_BASELINE_PITCHES,
which gates an individual PITCH sample, not a player-count sample.
Whether one player's own line (built from too few innings/PAs) is
itself noisy is a real, separate concern this V1 doesn't gate on yet --
flagged for Ryker, same as Arsenal's "is a plus pitch underused"
diagnostic in pitch_grading.py was left open rather than guessed at.
"""

from statistics import mean, stdev

from plate_discipline import WHIFF_OUTCOMES

MIN_BASELINE_PLAYERS = 5

# {metric_name: higher_is_better}
PITCHER_RESULTS_METRICS = {
    "FIP": False, "WHIP": False, "K/BB": True, "CSW %": True, "Execution %": True,
}
HITTER_RESULTS_METRICS = {
    "wOBA": True, "AVG": True, "Chase %": False, "Whiff %": False, "Zone Swing %": True,
}


def csw_pct(pitches):
    """Called-Strike-plus-Whiff %, off raw pitches -- same definition
    already used per pitch type in game_stats._pitch_type_row, just
    not otherwise available as a single number off
    compute_pitching_line(). None if pitches is empty."""
    n = len(pitches)
    if not n:
        return None
    called_strikes = sum(1 for p in pitches if p.pitch_outcome == "Called Strike")
    whiffs = sum(1 for p in pitches if p.pitch_outcome in WHIFF_OUTCOMES)
    return round(100 * (called_strikes + whiffs) / n, 1)


def usage_weighted_average(arsenal_rows, key):
    """arsenal_rows: pitch_grading.arsenal_summary()'s output. Usage-%-
    weighted mean of `key` (e.g. "Pitching+") across rows that have
    both a usage share and a non-None value for it -- a row with no
    graded pitches of that type is excluded from both the numerator
    and the weight total, not treated as a zero. Returns None if no
    row qualifies."""
    weighted_sum, weight_total = 0.0, 0.0
    for row in arsenal_rows:
        value = row.get(key)
        usage = row.get("Usage %")
        if value is None or usage is None:
            continue
        weighted_sum += value * usage
        weight_total += usage
    return round(weighted_sum / weight_total, 1) if weight_total else None


def _team_baseline(lines, metrics):
    """lines: list of already-computed per-player dicts (one per
    pitcher/hitter, same window). metrics: {metric_name:
    higher_is_better}. Returns {metric_name: (mean, stdev, n,
    higher_is_better)} -- (None, None, n, higher_is_better) for a
    metric with fewer than 2 non-null values across the population,
    same shape convention as pitch_grading.team_stuff_plus_baseline."""
    baseline = {}
    for name, higher_is_better in metrics.items():
        vals = [line.get(name) for line in lines]
        vals = [float(v) for v in vals if v is not None]
        n = len(vals)
        baseline[name] = (round(mean(vals), 4), round(stdev(vals), 4), n, higher_is_better) if n >= 2 else (None, None, n, higher_is_better)
    return baseline


def _results_score(line, baseline):
    weighted_sum, weight_total = 0.0, 0.0
    for name, (b_mean, b_sd, _n, higher_is_better) in baseline.items():
        value = line.get(name)
        if value is None or b_mean is None or not b_sd:
            continue
        z = (float(value) - b_mean) / b_sd
        if not higher_is_better:
            z = -z
        weighted_sum += z
        weight_total += 1
    if weight_total == 0:
        return None
    return round(100 + 10 * (weighted_sum / weight_total), 1)


def team_pitcher_results_baseline(pitcher_lines):
    """pitcher_lines: list of dicts, each a
    game_stats.compute_pitching_line() dict merged with a "CSW %" key
    (see csw_pct() above). Population unit is PITCHERS, not pitches --
    MIN_BASELINE_PLAYERS (not pitch_grading.MIN_BASELINE_PITCHES) is
    the relevant reliability floor for whether this baseline itself is
    trustworthy; callers should check len(pitcher_lines) against it
    before trusting a score built from this baseline."""
    return _team_baseline(pitcher_lines, PITCHER_RESULTS_METRICS)


def pitcher_results_score(pitcher_line, baseline):
    """One pitcher's compute_pitching_line() dict (merged with "CSW %")
    -> Results z-score composite against `baseline`. None if the
    pitcher has no value for any of PITCHER_RESULTS_METRICS, or the
    baseline itself has no usable population for any of them."""
    return _results_score(pitcher_line, baseline)


def team_hitter_results_baseline(hitter_lines):
    """hitter_lines: list of dicts, each a
    game_stats.compute_batting_line() dict merged with
    plate_discipline.compute_hitter_discipline()'s "Chase %"/"Whiff %"/
    "Zone Swing %" for the same pitches. Same MIN_BASELINE_PLAYERS
    reliability note as team_pitcher_results_baseline."""
    return _team_baseline(hitter_lines, HITTER_RESULTS_METRICS)


def hitter_results_score(hitter_line, baseline):
    """One hitter's merged line -> Results z-score composite. This IS
    Hitter Performance in full -- see module docstring for why hitters
    don't get a blended score the way pitchers do."""
    return _results_score(hitter_line, baseline)


def combine_pitcher_performance(stuff_plus, location_plus, command_plus, arsenal_pitching_plus, results_score):
    """Ryker's exact V1 call (Aug 31 2026): plain equal-weighted
    average of all five -- see module docstring for the Stuff+/
    Location+/Arsenal overlap this doesn't correct for. A None input is
    dropped, not zeroed (a missing grade shrinks the average's inputs,
    same convention as pitch_grading.stuff_plus's per-feature
    renormalization) -- returns None only if every input is None."""
    values = [v for v in (stuff_plus, location_plus, command_plus, arsenal_pitching_plus, results_score) if v is not None]
    return round(sum(values) / len(values), 1) if values else None
