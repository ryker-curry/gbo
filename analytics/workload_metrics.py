"""
GBO -- Workload monitoring: Acute:Chronic Workload Ratio (ACWR) for
pitch volume, covering bullpens AND games/scrimmages. Ryker's call
(Aug 29 2026): intrasquad scrimmages get logged as Games in Game
Tracking, so the fall trial's "bullpen volume" really means bullpen +
game/scrimmage pitch counts combined, not bullpens alone.

Pure data logic -- no Streamlit/Shiny, no plotly, no database queries,
same rule as bullpen_metrics.py/command_metrics.py ("keep calculations
separate from visualization functions... keep database operations
separate from UI code," spec Section 20). Callers are responsible for
resolving ONE pitch total per calendar day, across every source, before
calling anything here -- nothing in this file touches the DB or knows
about ORM objects.

RESOLVING THE DAILY PITCH COUNT (read before wiring a caller):
A single BullpenSession can have pitches logged in up to THREE
independent tables -- BullpenPitch (live zone-tap), RapsodoPitch (CSV
import), CommandPitch (Command Tracker) -- with no automatic linking
between them yet (that's a reserved Phase-3 feature, not built). Per
Ryker's call, a session's pitch count is
    max(len(BullpenPitch rows), len(RapsodoPitch rows), len(CommandPitch rows))
for that bullpen_id, NOT the sum -- summing would double/triple-count a
bullpen that got tracked through more than one path. Game/scrimmage
volume adds GamePitch rows where our_player_id is the pitcher
(is_our_team_batting is False) -- one row per pitch already, no dedup
needed there, just union it in by date.

A day with a real, tracked-but-empty outing (he was around, threw
nothing) belongs in the input dict as 0 -- see compute_daily_acwr's
docstring for why that's different from a day that's simply absent.

METHOD: plain rolling-average ACWR (acute = trailing 7-day sum,
chronic = trailing 28-day sum / 4, ratio = acute/chronic) -- the
simplest version, deliberately chosen for the fall trial over EWMA
(see Ryker's project notes -- EWMA is a real candidate for the
in-season version once this is validated). The zone thresholds below
are the commonly-cited ones (Gabbett-style 0.8/1.3/1.5) but are NOT
validated for this population or specifically for baseball pitching --
treat every ratio as a flag worth a look, never as an automatic alert
or the sole input to a throwing-program decision. Recent methodology
critique (Impellizzeri et al. and others) has shown these thresholds
don't hold up well when treated as hard cutoffs rather than a rough
zone, and the ratio itself is mathematically unstable whenever the
chronic denominator is thin -- exactly the situation for every player
in roughly their first 4 weeks of being tracked. See has_full_history
below.
"""

from datetime import timedelta

ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28
CHRONIC_WEEKS = CHRONIC_WINDOW_DAYS / 7  # 4.0 -- divisor for the weekly-average chronic load

# Soft guidance zones only -- see module docstring's methodology caveat.
# Not validated thresholds; a prompt to look closer, not an alert.
ZONE_UNDER_TRAINING_MAX = 0.80
ZONE_SWEET_SPOT_MAX = 1.30
ZONE_ELEVATED_MAX = 1.50


def classify_zone(ratio):
    """Soft guidance label for a single ACWR value. None in, None out."""
    if ratio is None:
        return None
    if ratio < ZONE_UNDER_TRAINING_MAX:
        return "Under-training"
    if ratio <= ZONE_SWEET_SPOT_MAX:
        return "Sweet spot"
    if ratio <= ZONE_ELEVATED_MAX:
        return "Elevated"
    return "Danger zone"


def _window_load(counts_by_day, day, window_days, tracking_start_date):
    """Sum of counts_by_day over the trailing `window_days` ending on
    `day` (inclusive), clipped so it never reaches earlier than
    tracking_start_date. Returns (load, days_available) -- days_available
    is how many of the requested window_days actually fall on/after
    tracking_start_date, i.e. how much real history backs this number.
    A day in range but missing from counts_by_day is treated as a real
    0 (see module docstring) -- only days before tracking_start_date are
    excluded outright, since those are genuinely unknown, not zero."""
    window_start = day - timedelta(days=window_days - 1)
    effective_start = max(window_start, tracking_start_date)
    if effective_start > day:
        return 0, 0
    days_available = (day - effective_start).days + 1
    load = sum(
        counts_by_day.get(effective_start + timedelta(days=i), 0)
        for i in range(days_available)
    )
    return load, days_available


def compute_daily_acwr(daily_pitch_counts, tracking_start_date=None, start_date=None, end_date=None):
    """Day-by-day acute/chronic/ACWR for ONE player.

    daily_pitch_counts: dict[date -> int]. One entry per calendar day
    with ANY tracked pitch volume for this player (bullpen sessions,
    resolved per the module docstring's max-across-tables rule, unioned
    with GamePitch-derived game/scrimmage counts). A day the player was
    tracked but genuinely threw nothing MUST be present with 0 -- days
    simply absent from this dict are treated as "not yet being tracked,"
    not as rest days, and are excluded from the load windows below via
    tracking_start_date rather than silently zero-filled.

    tracking_start_date: the first date real tracking exists for this
    player. Defaults to min(daily_pitch_counts.keys()) if not given --
    reasonable since the caller is expected to include every tracked day
    (0s included), so the earliest key IS the tracking start.

    start_date/end_date: the calendar range to return rows for. Defaults
    to the min/max dates present in daily_pitch_counts.

    Returns a list of dicts, one per calendar day in [start_date,
    end_date], oldest first:
      date, pitches_today,
      acute_load (trailing 7-day sum), acute_days_available,
      chronic_load (trailing 28-day sum / 4, i.e. avg pitches/week),
        chronic_days_available (of the 28, how many fall on/after
        tracking_start_date -- the real history depth backing this
        number),
      acwr (acute_load / chronic_load, or None if chronic_load is 0),
      zone (classify_zone(acwr)),
      has_full_history (chronic_days_available >= CHRONIC_WINDOW_DAYS).

    IMPORTANT: for roughly the first 28 days after tracking starts for a
    given player, has_full_history is False and the chronic (therefore
    acwr) number is calculated from whatever partial history exists --
    it reads artificially LOW early on (thin denominator), which can
    make the ratio look artificially HIGH. This isn't a bug to fix --
    every ACWR implementation has this "burn-in" period. Callers should
    visibly flag has_full_history == False (e.g. gray out or caption the
    ratio) rather than show it with the same confidence as a fully-
    seasoned number. It's also the concrete reason this needs a real
    fall trial before it ever drives an in-season decision -- there
    has to be enough tracked history for the chronic side to mean
    anything at all.
    """
    if not daily_pitch_counts:
        return []

    all_dates = sorted(daily_pitch_counts.keys())
    if tracking_start_date is None:
        tracking_start_date = all_dates[0]
    range_start = start_date or all_dates[0]
    range_end = end_date or all_dates[-1]

    rows = []
    d = range_start
    while d <= range_end:
        acute_load, acute_days = _window_load(daily_pitch_counts, d, ACUTE_WINDOW_DAYS, tracking_start_date)
        chronic_sum, chronic_days = _window_load(daily_pitch_counts, d, CHRONIC_WINDOW_DAYS, tracking_start_date)
        chronic_load = round(chronic_sum / CHRONIC_WEEKS, 1) if chronic_days > 0 else None
        acwr = round(acute_load / chronic_load, 2) if chronic_load else None

        rows.append({
            "date": d,
            "pitches_today": daily_pitch_counts.get(d, 0),
            "acute_load": acute_load,
            "acute_days_available": acute_days,
            "chronic_load": chronic_load,
            "chronic_days_available": chronic_days,
            "acwr": acwr,
            "zone": classify_zone(acwr),
            "has_full_history": chronic_days >= CHRONIC_WINDOW_DAYS,
        })
        d += timedelta(days=1)

    return rows
