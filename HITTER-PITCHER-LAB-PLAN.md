# Hitter Lab / Pitcher Lab / Catching Value Board — Reference & Build Plan

Source material: a scouting-portal tool (screenshots shared by Ryker, Aug 2026 — "Bushnell Scouting Portal," shown by Nate Rasmussen on X) with a Hitter Lab, Pitcher Lab, Catching value board, and per-outing pitching/hitting detail pages. This doc extracts what it measures, checks it against GBO's actual current code (not memory/notes — verified by reading the real files in this repo on 2026-08-29), and lays out what to build.

---

## 1. Metric glossary — what the reference tool shows

### Hitter Lab (season/date-range, per player)
| Metric | Definition (as shown) |
|---|---|
| Avg Exit Velo / Max Exit Velo | Mean and max batted-ball exit velocity (mph), shown as a percentile bar vs. the team's qualified-batter population |
| Hard-Hit% | % of batted balls ≥ 95 mph |
| Sweet-Spot% | % of batted balls with launch angle in the "sweet spot" band (8–32°) |
| Whiff% | Swings-and-misses / swings |
| Zone Contact% | Contact rate on pitches in the zone |
| BB% | Walk rate |
| Chase% | Swing rate on pitches outside the zone |
| K% | Strikeout rate |
| xAVG / xSLG / xwOBA | "Expected" stats modeled from a Statcast-style exit-velo + launch-angle surface; strikeouts count as outs, walks/HBP feed xwOBA, batted balls use the EV/LA model instead of actual result. Shown against actual AVG/SLG/wOBA with an "over/under-performing" label. |
| Splits by hand and by pitch type | Seen, Swing%, Whiff%, Chase%, BBE, EV, Hard-Hit%, xwOBAcon, RV — one row per pitch type (min. 10 seen), shaded relative to the other rows shown |
| Swing/Take Runs by Attack Zone | Every called pitch priced with a count-based run value, split by swing vs. take, summed by zone tier (Heart/Shadow/Chase/Waste) |
| Session Trend | xwOBAcon / Avg EV / Hard-Hit% plotted over time (session by session) |
| Count leverage tiles | First-Pitch Swing%, 2K Contact%, Chase% Behind, EV When Ahead |
| Development maps | Six 2D heatmaps over the strike zone by cell: Swings%, Whiffs%, Damage (avg EV allowed), Hard Contact% (≥90 mph), Called Strikes on Takes — i.e. approach, damage, and passivity all read off the same zone grid |

### Pitcher Lab (season/date-range, per player, filterable: All live / Games only / Scrimmages / Intrasquads / Everything, vs LHH/RHH, All measures)
| Metric | Definition |
|---|---|
| Velo (avg/max), Spin rate, Fastball Ride (IVB), Extension | Percentile bars vs. team's qualified-arm population |
| Whiff%, CSW%, BB%, Hard-Hit Against | Same idea, outcome side |
| Per-pitch-type table | Loc+, N, Usage%, Velo (avg/max), IVB, HB, Spin, Extension, VAA, GB%, Zone%, ShdwZone%, Whiff%, Chase%, CSW% |
| Locations by pitch (K-zone box) | Per-pitch-type location heatmap |
| Pitch mix / zone / edge presence by count | For every ball-strike count, pitch usage breakdown + Zone% + "Shadow%" (edge-of-zone presence) |
| Development maps | Whiffs%, Strikes Earned% (called+swinging/cell), Damage (avg EV allowed), Where he starts ABs (0-0 pitch location%), Where he goes behind-in-count, Where he finishes (two-strike location%) |
| Count leverage | First-Pitch Strike%, Putaway% at 2K, CSW% ahead/behind, Zone% at 3 balls |
| Arm & release profile | Slot (qualitative), Est. arm angle (range), Release height/side, Consistency (qualitative), Extension, Approach angle |
| Tunneling off the fastball | Per secondary pitch: Tunnel distance (separation at the decision point), Plate (separation at the plate), Late break, Ratio (plate/tunnel), a 0–100 Grade; "best pair" called out |

### Catching Value Board
| Metric | Definition |
|---|---|
| Value | Framing runs + arm runs, total |
| Framing / SAE | Strikes-above-expected on takes |
| Edge takes / Edge K% | Volume and strike% on edge-of-zone takes only |
| High/Low/Left/Right | Framing runs by which edge of the zone |
| Arm | Arm runs (throwing value) |
| SB-CS, CSX%, Est. CSX% | Stolen base/caught-stealing record, actual caught-stealing%, and an estimated CS% derived from pop time, for comparison |
| Pop, Best, Exch, Arm Velo, Throws | Pop time (avg), best pop time, exchange time, arm velocity, throw count |
| Framing map | Per-catcher strikes-above-expected shown separately on each of the 4 zone edges |
| Blocking workload | Pitches caught, dirt balls, dirt balls per 100 pitches, offspeed% (context for blocking difficulty), passed balls — explicitly volume/workload, not a runs-saved number, since dirt-ball tracking alone doesn't capture whether it was blocked |

---

## 2. What GBO already has — verified against the real code (not the old memory summary, which undersold this)

GBO's `gbo-shiny-migration` repo already covers a surprising amount of this, in pieces that just haven't been unified into one "Lab" page yet:

- **Plate discipline (`plate_discipline.py`)** — `compute_hitter_discipline()` and `compute_pitcher_command()` already produce Swing%, Whiff%, Zone%, Zone Contact%, Chase%, Chase Contact%, First-Pitch Swing% (hitter) and Zone%, Whiff% Induced, Chase% Induced, Usage% (pitcher), all derived from real per-pitch `actual_plate_x/z` coordinates, not estimates. `compute_zone_tier_discipline()` already buckets by **Heart/Shadow/Chase/Waste** — the exact same 4-tier zone framework the reference tool's "Swing/Take Runs by Attack Zone" table uses.
- **Run value** — `RunExpectancy` is a real 289-row outs/bases/count table; `GamePitch.re_before/re_after/run_value` are computed automatically at save time for every game pitch. `compute_zone_performance()` + `build_zone_performance_heatmap_figure()` already render a 3x3 avg-Run-Value-by-zone heatmap for a pitcher's own results — functionally the same idea as the reference tool's zone-performance maps, just not yet gridded as finely (3x3 vs. the reference's ~5x5+ cell grid) and not yet built for the swing/take-run-by-zone-tier version on the hitter side.
- **Command+ (`analytics/command_metrics.py`)** — this is the closest thing GBO has to the reference tool's whole "percentile vs. your data" concept, just scoped to pitch command specifically: `danger_adjusted_miss()`, `team_command_plus_baseline()` (team mean/stdev), and `command_plus()` normalize a pitcher's miss distance against the team population — a real z-score-style relative metric, the same statistical shape as a percentile bar.
- **Arm & release profile (`analytics/bullpen_metrics.py`, `analytics/pitch_trajectory.py`)** — `calculate_estimated_arm_angle()` (geometric, from release point + `Player.height_in`), estimated VAA/HAA, `release_trajectory_summary()` (release point consistency), fastball trajectory classification. This maps almost metric-for-metric onto the reference tool's "Arm & Release Profile" box (Slot / Est. Arm Angle / Release / Consistency / Extension / Approach Angle).
- **Tunneling groundwork (`visualizations/bullpen_charts.py`)** — `release_point_chart()` already overlays release points by pitch type specifically to make cross-type tunneling visible; `movement_chart()` and `location_chart()` exist too. The *visual* is there; the *numeric* tunnel/plate/late-break/ratio/grade table is not.
- **Rapsodo bullpen data (`RapsodoPitch` model)** — already captures velocity, total/true spin, spin efficiency, spin axis, VB/HB movement, release height/side, extension, and VAA/HAA at the plate, per pitch. This is exactly the raw material a real Pitcher Lab's percentile bars and per-pitch-type table would run on — no new data collection needed for that part.
- **Real wOBA** — `analytics/pitcher_game_report.py` computes actual wOBA from game outcomes (`_compute_woba`). Not *expected* wOBA (that needs batted-ball EV/LA — see gaps below), but the actual-outcome side already exists.
- **A working percentile engine (`bucket_system.py`)** — the Physical Testing "Bucket System" already does `percentile = round(value/team_max*100)` (or `team_min/value*100` for lower-is-better), against a live team population, rendered as rings/bars (`bucket_system_display.py`). This is a proven, reusable pattern — it's scoped to physical-testing data today, but the math and the display component both generalize directly to on-field performance percentiles.
- **A cautionary precedent worth remembering**: a full physics-based pitch flight-path chart was built once (`pitch_trajectory.py`'s trajectory model, a `visualizations/trajectory_chart.py`), shipped, then *removed entirely* after Ryker reviewed it live and it "didn't read as useful." Worth keeping in mind before over-building a flashy visual in this project that doesn't actually change a coaching decision.

## 3. What's genuinely missing

- **No batted-ball exit velocity or launch angle anywhere in the schema.** `HitterSwing.contact_quality` and `GamePitch.contact_quality` are categorical (`Barrel`/`Solid`/`Weak`/`Miss`), not numeric mph/degrees; `batted_ball_type` is categorical (`Ground Ball`/`Line Drive`/`Fly Ball`/`Pop Up`), not a launch-angle number. This single gap blocks the entire "Percentile vs. your data" EV/Hard-Hit%/Sweet-Spot% section AND the whole Expected Stats panel (xAVG/xSLG/xwOBA), since Statcast-style expected stats are *built from* an EV+LA surface. Closing this needs either a batted-ball tracking device feed (Rapsodo Hitting, HitTrax, Trackman, Blast Motion) or manual EV/LA entry per swing — a data-collection decision, not just a coding one.
- **No catcher framing/arm/blocking tracking at all.** No pop time, no strikes-above-expected, no SB-CS/CSX/estimated-CSX, no framing-by-zone-edge, no dirt-ball/blocking log. GBO currently has zero catching-specific defensive data beyond a player's position — this is the single biggest net-new build of the set, and needs its own capture workflow (someone has to log catcher-specific events per pitch or per steal attempt), not just a new report on existing data.
- **No season/date-range aggregate "Lab" view with team-relative percentile bars.** Everything performance-related in GBO today is either a single-game report (`pitcher_game_report.py`, `hitter_game_report.py`) or a live-session bullpen dashboard — nothing currently aggregates across a date range with the "Games + Scrimmages / BP only / All arms / vs LHP/RHP" style filters the reference tool uses. Command+ is the only place with a real team-baseline percentile-style pattern today.
- **No numeric tunneling table.** Only the visual release-point overlay exists; tunnel distance, plate separation, late break, ratio, and a 0–100 grade would all be new computation on top of already-captured release/movement data.
- **No pitch grading model.** Confirmed nothing resembling Stuff+/a per-pitch ML grade anywhere in the codebase — this is the "pitch models" piece Ryker wants to try later (see §5).

## 4. Recommendation

Build it — most of the hard plumbing already exists in fragments; the work is mostly *unifying and extending*, not starting from zero. Suggested order, cheapest/highest-value first:

1. **Ship the "Lab" page itself first, with zero new data collection.** Wrap `plate_discipline.py` + `command_metrics.py` + `bullpen_metrics.py` outputs in one date-range/session-type-filterable page per player, with team-relative percentile bars reusing `bucket_system_display.py`'s existing ring/bar pattern. This alone gets most of the Pitcher Lab and a meaningful chunk of the Hitter Lab (everything except EV/power) built from data GBO already has.
2. **Numeric tunneling table.** `release_trajectory_summary()` already computes most of the raw release/movement inputs needed — this is mostly new math (tunnel/plate/late-break/ratio/grade) on existing data, no new capture.
3. **Decide on batted-ball EV/LA capture.** This is the real fork in the road — it gates the entire Expected Stats panel and the power side of the Hitter Lab. Worth a direct conversation with the coaching staff about whether a device (Rapsodo Hitting bay, HitTrax) is realistically available before designing around it; manual entry is a fallback but adds real workflow cost.
4. **Catching Value Board — treat as its own project**, scoped after 1–3 land. New model(s), new capture workflow, no existing GBO code to build on.

## 5. Pitch models — flagged for later (per Ryker's request, not started)

Confirmed nothing in the codebase today resembles a pitch-grading model. The prerequisite data is already being collected, though — `RapsodoPitch` has velocity, spin (total/true/efficiency/axis), movement (VB/HB), release point, extension, and approach angle per pitch, which is enough to eventually train something like a whiff-probability or run-value-by-pitch-characteristics model once there's enough volume logged. Explicitly deferred, not scoped further here — just on record for when Ryker wants to pick it up.

---

## Files reviewed for §2/§3 (this repo, `gbo-shiny-migration`, 2026-08-29)
`plate_discipline.py`, `game_stats.py`, `models.py` (`GamePitch`, `HitterSwing`, `RapsodoPitch`), `bucket_system.py` + `bucket_system_display.py`, `force_plate_standards.py`, `analytics/bullpen_metrics.py`, `analytics/command_metrics.py`, `analytics/pitch_trajectory.py`, `analytics/pitcher_game_report.py`, `visualizations/bullpen_charts.py`, `shiny_app/modules/hitter_game_report.py`, `shiny_app/modules/player_hitting.py`.
