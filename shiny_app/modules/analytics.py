"""
GBO -- Analytics module (coach/staff-facing "Player Stats").

Direct port of pages/analytics.py -- pick a player, see their batting
and pitching lines computed from Game Tracking data, filterable by
season (so fall/practice stats stay separate from real spring
regular-season stats). Shares its computation logic with My Stats (the
player-facing equivalent, not yet migrated) via game_stats.py, so the
two never drift apart.

Two-block ordering-hazard-safe chain: player_picker() (player + season
selects) -> report_body() (req on both, since the season select's
choices don't depend on the player one, both live in the same first
block safely -- unlike the game/pitcher-select chains elsewhere, there's
no data dependency between the two pickers here).

Zone Performance heatmap uses plate_discipline.py's documented Shiny
migration seam: build_zone_performance_heatmap_figure() (pure, no
Streamlit import) instead of the Streamlit-only render_zone_performance_
heatmap() wrapper, rendered via chart_helpers.fig_to_img() same as every
other decorative (non-click) chart in this migration.

Pitching KPIs section reuses bucket_display.build_percentage_rings()
unchanged (confirmed signature-compatible with the original's
bucket_system_display.render_percentage_rings(metrics_list,
key_prefix=...) call: list of (label, value) tuples in, UI out).
"""

from shiny import module, ui, render, reactive, req

from database import get_session
from models import Player, Season
from game_stats import (
    get_batting_pitches, get_pitching_pitches, compute_batting_line, compute_pitching_line,
    compute_pitch_type_breakdown, compute_batted_ball_profile,
)
from plate_discipline import (
    compute_hitter_discipline, compute_pitcher_command, compute_zone_performance,
    build_zone_performance_heatmap_figure, compute_zone_tier_discipline,
)
from pitch_location_stats import compute_command_precision, compute_attack_zones
from bucket_display import build_percentage_rings

import ui_helpers
import chart_helpers


def _fmt_pct(value):
    return f"{value:.0f}%" if value is not None else "—"


def _fmt_pct1(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_num(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


@module.ui
def analytics_ui():
    return ui.div(
        ui_helpers.page_header("Player Stats"),
        ui.output_ui("player_picker"),
        ui.output_ui("report_body"),
        ui_helpers.page_footer(),
    )


@module.server
def analytics_server(input, output, session, app_state):
    ALLOWED_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst")

    @render.ui
    def player_picker():
        if not app_state.is_authenticated():
            return None
        if app_state.role_name() not in ALLOWED_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")

        db = get_session()
        try:
            players = db.query(Player).filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()
            if not players:
                return ui_helpers.empty_state("No players to show yet.")
            player_choices = {str(p.player_id): f"{p.first_name} {p.last_name}" for p in players}

            seasons = db.query(Season).order_by(Season.start_date.desc().nullslast(), Season.season_name.desc()).all()
            season_choices = {"": "-- All seasons --"}
            for s in seasons:
                label = s.season_name + ("" if s.is_official else " (practice/fall, not official)")
                season_choices[str(s.season_id)] = label

            return ui.div(
                ui.input_select("player_select", "Player", choices=player_choices),
                ui.input_select("season_select", "Season", choices=season_choices),
            )
        finally:
            db.close()

    @render.ui
    def report_body():
        if not app_state.is_authenticated() or app_state.role_name() not in ALLOWED_ROLES:
            return None
        req("player_select" in input)
        req("season_select" in input)
        selected_player_id = int(input.player_select())
        season_raw = input.season_select()
        season_choice = int(season_raw) if season_raw else None

        db = get_session()
        try:
            player = db.query(Player).filter(Player.player_id == selected_player_id).first()
            if player is None:
                return None
            season = db.query(Season).filter(Season.season_id == season_choice).first() if season_choice is not None else None
            season_suffix = f" — {season.season_name}" if season is not None else " — All seasons"

            sections = [ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title")]

            batting_pitches = get_batting_pitches(db, selected_player_id, season_choice)
            pitching_pitches = get_pitching_pitches(db, selected_player_id, season_choice)

            if not player.is_pitcher:
                sections.append(ui.h6("Hitting", class_="gbo-section-title"))
                if not batting_pitches:
                    sections.append(ui_helpers.empty_state("No hitting data recorded yet for this player in Game Tracking."))
                else:
                    batting_line = compute_batting_line(batting_pitches)
                    sections.append(ui.p(ui.strong("Line" + season_suffix)))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "PA", "value": str(batting_line["PA"])},
                        {"label": "AB", "value": str(batting_line["AB"])},
                        {"label": "H", "value": str(batting_line["H"])},
                        {"label": "BB", "value": str(batting_line["BB"])},
                        {"label": "K", "value": str(batting_line["K"])},
                        {"label": "AVG", "value": _fmt_num(batting_line["AVG"], 3)},
                    ]))
                    sections.append(ui.p(
                        f"1B: {batting_line['1B']} · 2B: {batting_line['2B']} · 3B: {batting_line['3B']} · HR: {batting_line['HR']} · "
                        f"HBP: {batting_line['HBP']} · Total RV: {batting_line['Total RV']} · Avg RV/PA: {batting_line['Avg RV/PA']}",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Slash Line")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "OBP", "value": _fmt_num(batting_line["OBP"], 3)},
                        {"label": "SLG", "value": _fmt_num(batting_line["SLG"], 3)},
                        {"label": "OPS", "value": _fmt_num(batting_line["OPS"], 3)},
                        {"label": "ISO", "value": _fmt_num(batting_line["ISO"], 3)},
                        {"label": "wOBA*", "value": _fmt_num(batting_line["wOBA"], 3)},
                    ]))
                    sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.", class_="text-muted small"))

                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "BB %", "value": _fmt_pct1(batting_line["BB %"])},
                        {"label": "K %", "value": _fmt_pct1(batting_line["K %"])},
                        {"label": "BB/K", "value": _fmt_num(batting_line["BB/K"], 2)},
                    ]))

                    sections.append(ui.p(ui.strong("Situational")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "RISP AVG", "value": _fmt_num(batting_line["RISP AVG"], 3)},
                        {"label": "2-Strike AVG", "value": _fmt_num(batting_line["2-Strike AVG"], 3)},
                        {"label": "Leadoff AVG", "value": _fmt_num(batting_line["Leadoff AVG"], 3)},
                    ]))
                    sections.append(ui.p(
                        f"RISP: {batting_line['RISP PA']} PA ({batting_line['RISP AB']} AB) · 2-Strike: {batting_line['2-Strike PA']} PA "
                        f"({_fmt_pct1(batting_line['2-Strike K %'])} ended in a K) · Leadoff: {batting_line['Leadoff PA']} PA",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Plate Discipline")))
                    discipline = compute_hitter_discipline(batting_pitches)
                    if discipline["Pitches Seen"] == 0:
                        sections.append(ui.p("No pitches seen yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Zone %", "value": _fmt_pct(discipline["Zone %"])},
                            {"label": "Swing %", "value": _fmt_pct(discipline["Swing %"])},
                            {"label": "Chase %", "value": _fmt_pct(discipline["Chase %"])},
                            {"label": "Whiff %", "value": _fmt_pct(discipline["Whiff %"])},
                            {"label": "1st-Pitch Swing %", "value": _fmt_pct(discipline["First-Pitch Swing %"])},
                        ]))
                        sections.append(ui.p(
                            f"Zone Swing %: {_fmt_pct(discipline['Zone Swing %'])} · Zone Contact %: {_fmt_pct(discipline['Zone Contact %'])} · "
                            f"Chase Contact %: {_fmt_pct(discipline['Chase Contact %'])} · Pitches Seen: {discipline['Pitches Seen']} "
                            f"({discipline['Located Pitches']} with a recorded location)",
                            class_="text-muted small",
                        ))

                    sections.append(ui.p(ui.strong("Zone-Tier Discipline")))
                    sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                    sections.append(ui_helpers.render_dict_table(compute_zone_tier_discipline(batting_pitches)))

                    sections.append(ui.p(ui.strong("Batted-Ball Profile")))
                    profile = compute_batted_ball_profile(batting_pitches, bats=player.bats)
                    if profile["Balls in Play"] == 0:
                        sections.append(ui.p("No balls in play yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Ground Ball %", "value": _fmt_pct1(profile["Ground Ball %"])},
                            {"label": "Fly Ball %", "value": _fmt_pct1(profile["Fly Ball %"])},
                            {"label": "Line Drive %", "value": _fmt_pct1(profile["Line Drive %"])},
                            {"label": "Pop Up %", "value": _fmt_pct1(profile["Pop Up %"])},
                        ]))
                        if profile["Spray Mode"] == "Pull/Center/Oppo":
                            sections.append(ui_helpers.render_kpi_cards([
                                {"label": "Pull %", "value": _fmt_pct1(profile["Pull %"])},
                                {"label": "Center %", "value": _fmt_pct1(profile["Center %"])},
                                {"label": "Oppo %", "value": _fmt_pct1(profile["Oppo %"])},
                            ]))
                        else:
                            sections.append(ui_helpers.render_kpi_cards([
                                {"label": "Left Field %", "value": _fmt_pct1(profile["Left Field %"])},
                                {"label": "Center %", "value": _fmt_pct1(profile["Center %"])},
                                {"label": "Right Field %", "value": _fmt_pct1(profile["Right Field %"])},
                            ]))
                            sections.append(ui.p("Batter's hand isn't on file (or switch-hitter), so this shows raw field side instead of Pull/Oppo.", class_="text-muted small"))

                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Barrel %", "value": _fmt_pct1(profile["Barrel %"])},
                            {"label": "Hard Contact %", "value": _fmt_pct1(profile["Hard Contact %"])},
                        ]))
                        sections.append(ui.p(f"Balls in Play: {profile['Balls in Play']} ({profile['Located']} with a recorded field location).", class_="text-muted small"))
                sections.append(ui.hr())

            if player.is_pitcher:
                sections.append(ui.h6("Pitching", class_="gbo-section-title"))
                if not pitching_pitches:
                    sections.append(ui_helpers.empty_state("No pitching data recorded yet for this player in Game Tracking."))
                else:
                    pitching_line = compute_pitching_line(pitching_pitches)
                    command = compute_pitcher_command(pitching_pitches)

                    sections.append(ui.p(ui.strong("Pitching KPIs")))
                    rings = build_percentage_rings(
                        [
                            ("Zone %", command["Zone %"]),
                            ("Whiff % Induced", command["Whiff % Induced"]),
                            ("Chase % Induced", command["Chase % Induced"]),
                            ("Execution %", pitching_line["Execution %"]),
                        ],
                        key_prefix=f"pitch_kpi_{selected_player_id}",
                    )
                    if rings is not None:
                        sections.append(rings)

                    sections.append(ui.p(ui.strong("Line" + season_suffix)))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "IP", "value": str(pitching_line["IP"])},
                        {"label": "Pitches", "value": str(pitching_line["Pitches"])},
                        {"label": "K", "value": str(pitching_line["K"])},
                        {"label": "BB", "value": str(pitching_line["BB"])},
                        {"label": "H", "value": str(pitching_line["H Allowed"])},
                        {"label": "R", "value": str(pitching_line["Runs Allowed"])},
                    ]))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "WHIP", "value": _fmt_num(pitching_line["WHIP"])},
                        {"label": "K/BB", "value": _fmt_num(pitching_line["K/BB"])},
                        {"label": "K %", "value": _fmt_pct1(pitching_line["K %"])},
                        {"label": "ERA*", "value": _fmt_num(pitching_line["ERA (runs-allowed avg -- ER not tracked)"])},
                        {"label": "FIP", "value": _fmt_num(pitching_line["FIP"])},
                        {"label": "Execution %", "value": _fmt_pct1(pitching_line["Execution %"])},
                    ]))
                    sections.append(ui.p(
                        f"*ERA here is runs-allowed average, not true ERA -- GBO doesn't distinguish earned from unearned runs yet. "
                        f"Total RV Allowed: {pitching_line['Total RV Allowed']} · Avg RV Allowed/Pitch: {pitching_line['Avg RV Allowed/Pitch']}",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Count Control")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Strike %", "value": _fmt_pct1(pitching_line["Strike %"])},
                        {"label": "Early", "value": str(pitching_line["Early"])},
                        {"label": "Ahead", "value": str(pitching_line["Ahead (PA)"])},
                        {"label": "E+A %", "value": _fmt_pct1(pitching_line["E+A %"])},
                    ]))
                    sections.append(ui.p(
                        f"Pitches/Inning: {_fmt_num(pitching_line['Pitches/Inning'], 1)} · "
                        f"Balls: {pitching_line['Balls']} ({_fmt_pct1(pitching_line['Ball %'])})",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Situational")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "Leadoff Out %", "value": _fmt_pct1(pitching_line["Leadoff Out %"])},
                        {"label": "Leadoff BB", "value": str(pitching_line["Leadoff BB"])},
                        {"label": "2 Out BB", "value": str(pitching_line["2 Out BB"])},
                        {"label": "XBH Allowed", "value": str(pitching_line["XBH"])},
                    ]))
                    sections.append(ui.p(
                        f"0-2 Hits: {pitching_line['0-2 Hits']} · 0-2 Barrel: {pitching_line['0-2 Barrel']} · "
                        f"1-2 Barrel: {pitching_line['1-2 Barrel']} · "
                        "\"Score\" versions (did that specific walked runner score) aren't computable yet -- "
                        "GBO tracks base occupancy, not individual runner identity.",
                        class_="text-muted small",
                    ))

                    sections.append(ui.p(ui.strong("Against")))
                    sections.append(ui_helpers.render_kpi_cards([
                        {"label": "OBA", "value": _fmt_num(pitching_line["OBA (opponent AVG)"], 3)},
                        {"label": "wOBA*", "value": _fmt_num(pitching_line["wOBA"], 3)},
                        {"label": "AB", "value": str(pitching_line["AB"])},
                    ]))
                    sections.append(ui.p("*wOBA uses generic linear weights, not a season/league-specific set -- a relative read within your own games, not MLB-exact.", class_="text-muted small"))

                    sections.append(ui.p(ui.strong("Pitch Command / Usage")))
                    if command["Pitches Thrown"] == 0:
                        sections.append(ui.p("No pitches thrown yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Zone %", "value": _fmt_pct(command["Zone %"])},
                            {"label": "Whiff % Induced", "value": _fmt_pct(command["Whiff % Induced"])},
                            {"label": "Chase % Induced", "value": _fmt_pct(command["Chase % Induced"])},
                        ]))
                        sections.append(ui.p(f"Pitches Thrown: {command['Pitches Thrown']} ({command['Located Pitches']} with a recorded location)", class_="text-muted small"))
                        if command["Usage %"]:
                            usage_str = " · ".join(f"{name}: {_fmt_pct(pct)}" for name, pct in sorted(command["Usage %"].items(), key=lambda kv: -(kv[1] or 0)))
                            sections.append(ui.p(f"Usage — {usage_str}", class_="text-muted small"))

                    sections.append(ui.p(ui.strong("Pitch Type Breakdown")))
                    sections.append(ui.p(
                        "Rate stats per pitch type -- the same breakdown a game-tracking spreadsheet computes with "
                        "formulas, generated here from the same pitches already logged in Game Tracking.",
                        class_="text-muted small",
                    ))
                    vs_rhh = [p for p in pitching_pitches if p.opponent_hand == "R"]
                    vs_lhh = [p for p in pitching_pitches if p.opponent_hand == "L"]
                    sections.append(ui.navset_tab(
                        ui.nav_panel("All Batters", ui_helpers.render_dict_table(compute_pitch_type_breakdown(pitching_pitches))),
                        ui.nav_panel("vs RHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_rhh)) if vs_rhh else ui.p("No pitches recorded against a right-handed batter yet.", class_="text-muted small")),
                        ui.nav_panel("vs LHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_lhh)) if vs_lhh else ui.p("No pitches recorded against a left-handed batter yet.", class_="text-muted small")),
                    ))

                    sections.append(ui.p(ui.strong("Command Precision")))
                    sections.append(ui.p(
                        "Real distance between where he aimed and where it actually crossed the plate -- only counts "
                        "pitches reviewed in Video Review (both an intended and an actual location on file).",
                        class_="text-muted small",
                    ))
                    cp_overall, cp_by_type = compute_command_precision(pitching_pitches, throws=player.throws)
                    if cp_overall["Reviewed"] == 0:
                        sections.append(ui.p("No reviewed pitches yet (needs Video Review).", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Avg Miss", "value": f"{cp_overall['Avg Miss (in)']}\""},
                            {"label": "Reviewed", "value": str(cp_overall["Reviewed"])},
                            {"label": "Horizontal Bias", "value": f"{cp_overall['Horizontal Bias (in)']}\" {cp_overall['Horizontal Label']}"},
                            {"label": "Vertical Bias", "value": f"{cp_overall['Vertical Bias (in)']}\" {cp_overall['Vertical Label']}"},
                        ]))
                        if player.throws not in ("R", "L"):
                            sections.append(ui.p("Pitcher's throwing hand isn't on file, so horizontal bias shows raw 3B-side/1B-side instead of Arm-side/Glove-side.", class_="text-muted small"))
                        sections.append(ui_helpers.render_dict_table(cp_by_type))

                    sections.append(ui.p(ui.strong("Attack Zones")))
                    sections.append(ui.p("Heart = down the middle, Shadow = straddles the zone edge, Chase = tempting but outside, Waste = nowhere near. GBO approximation of Statcast's own tiers -- see pitch_location_stats.py for exact boundaries.", class_="text-muted small"))
                    az_overall, az_by_type = compute_attack_zones(pitching_pitches)
                    if az_overall["Located"] == 0:
                        sections.append(ui.p("No located pitches yet.", class_="text-muted small"))
                    else:
                        sections.append(ui_helpers.render_kpi_cards([
                            {"label": "Heart %", "value": _fmt_pct(az_overall["Heart %"])},
                            {"label": "Shadow %", "value": _fmt_pct(az_overall["Shadow %"])},
                            {"label": "Chase Zone %", "value": _fmt_pct(az_overall["Chase Zone %"])},
                            {"label": "Waste %", "value": _fmt_pct(az_overall["Waste %"])},
                        ]))
                        sections.append(ui_helpers.render_dict_table(az_by_type))

                    sections.append(ui.p(ui.strong("Zone Performance")))
                    sections.append(ui.p("How well his pitches perform in each part of the zone, from his own Game Tracking pitches (Run Value by location).", class_="text-muted small"))
                    avg_rv, zone_counts = compute_zone_performance(pitching_pitches)
                    if not avg_rv:
                        sections.append(ui_helpers.empty_state("No pitches yet with both a recorded location and a computed Run Value."))
                    else:
                        fig = build_zone_performance_heatmap_figure(avg_rv, zone_counts)
                        sections.append(chart_helpers.fig_to_img(fig))
                        sections.append(ui.p("Green = good for him (low/negative Run Value), red = poor (high/positive). Number in parentheses is pitch count. Zone 0/Bury not shown on this grid.", class_="text-muted small"))

            return ui.div(*sections)
        finally:
            db.close()
