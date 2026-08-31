"""
GBO -- Pitcher Profile (Aug 2026, Phase 0 of STUFF-LOCATION-PITCHING-
PLUS-PLAN.md). A filterable, per-pitcher deep dive: counting stats,
pitch-type breakdown, Stuff+/Location+/Pitching+ grades, pitch usage,
attack-zone distribution, a grade trend over time, the reused Bullpen
Dashboard physical charts, Command Target Zones, and a full Individual
Pitches table. Sits alongside the existing Analytics page as a coach-
facing (and player-facing, self-scoped) advanced view -- not a
replacement for it.

Self-scoping, same pattern as player_profile.py: a staff role sees a
player picker (scoped to assigned players unless can_view_all_players);
a "Player" role always sees their own linked player, no picker, and
gets nothing at all if that player isn't a pitcher (see hitter_profile.py
for that mirror case). Both cases render the exact same page body
otherwise -- no simplified/stripped-down player version, per the design
brief.

Reuses, doesn't reinvent: game_stats.py (line/pitch-type breakdown),
plate_discipline.py, analytics/command_metrics.py + visualizations/
command_charts.py (Command Target Zones, same code pitcher_game_report.py
already uses, just scoped by this page's own filters instead of one
game_id), bullpen_dashboard_display.register_bullpen_dashboard
(Physical Profile -- the exact same Bullpen Dashboard charts, pointed at
this pitcher's bullpen sessions in the selected date range instead of a
single session/all-time), and analytics/pitch_grading.py (Stuff+/
Location+/Pitching+/Arsenal). analytics/profile_queries.py is the one
new piece: the date-range/pitch-type/game-scope filtered queries this
page needs that game_stats.py's season/single-game queries don't cover.
"""

from datetime import date, timedelta

from shiny import module, ui, render, req
from shinywidgets import output_widget, render_plotly
from database import get_session
from models import Player, User, PitchType, PlayerPitchArsenal, StaffPlayerAssignment
from game_stats import compute_pitching_line, compute_pitch_type_breakdown
from strike_zone import classify_attack_zone
from analytics import command_metrics, profile_queries
from analytics.pitch_grading import (
    stuff_plus, location_plus, pitching_plus, arsenal_summary, MIN_BASELINE_PITCHES,
)
from visualizations import command_charts, profile_charts
from pitch_type_config import get_pitch_color

import ui_helpers
import bullpen_dashboard_display

STAFF_ROLES = ("Administrator", "Head Coach", "Coach", "Sports Scientist", "Data Analyst", "Video Coordinator")

# V1 fixed palette for the Attack Zone bar (Heart -> Waste), innermost
# to outermost -- no existing app-wide convention to reuse (Heart/
# Shadow/Chase/Waste only ever appear as text/percentages elsewhere,
# see plate_discipline.py/pitch_location_stats.py), so this picks a
# brand-consistent crimson-to-gray fade rather than inventing an
# unrelated scheme. Flag for Ryker/the designer to revise if a
# different treatment is wanted.
ATTACK_ZONE_COLORS = {"Heart": "#BF1E2D", "Shadow": "#F2B529", "Chase": "#7A8594", "Waste": "#3A3F47"}


def _fmt(value, decimals=2):
    return f"{value:.{decimals}f}" if value is not None else "—"


def _fmt_pct(value):
    return f"{value:.1f}%" if value is not None else "—"


def _fmt_grade(value):
    return f"{value:.1f}" if value is not None else "—"


def _my_player(db, app_state):
    me = db.query(User).filter(User.user_id == app_state.user_id()).first()
    if me is None or me.player_id is None:
        return None
    return db.query(Player).filter(Player.player_id == me.player_id).first()


def _grade_ring_status(label, value):
    """V1 color cut points for the mean-100/10-per-SD grade scale
    (Stuff+/Location+/Pitching+) -- NOT bucket_display.py's 0-100
    percentile cut points. >=110 (roughly 1+ SD above the team) reads
    good, <90 (1+ SD below) flags, in between stays the neutral default
    look. Unvalidated V1 guess, same as every other new cut point in
    this build -- revisit once real scores exist to check against
    Ryker's own read of the staff."""
    if value is None:
        return None
    if value >= 110:
        return "good"
    if value < 90:
        return "flag"
    return None


def _grade_rings(specs):
    """Stuff+/Location+/Pitching+ as the same full-circle CSS ring
    bucket_display.build_percentage_rings uses app-wide (identical
    .gbo-ring* classes from theme.py -- same visual language as the
    Bucket System/Command+ rings, per the design brief's explicit call
    to reuse that style rather than invent a new one). NOT that
    function directly, though -- these scores sit on a mean-100/
    +-10-per-SD scale (pitch_grading.py), not a true 0-100 percentile,
    so the ring's FILL needs its own mapping while the NUMBER shown
    stays the real, untransformed grade. specs: list of (label, value)
    tuples, value may be None ('not enough baseline yet').

    Fill mapping (V1, unvalidated): 100 (dead average) -> 50% filled;
    +/-30 points (3 SD) -> fully empty/full."""
    if not any(v is not None for _, v in specs):
        return None
    cols = []
    for label, value in specs:
        if value is None:
            cols.append(ui.div(ui.p(ui.strong(label)), ui.p("Not enough data yet", class_="text-muted small"), class_="gbo-ring-col"))
            continue
        pct = max(0.0, min(100.0, 50 + (float(value) - 100) * (50 / 30)))
        status = _grade_ring_status(label, value)
        ring = ui.div(
            ui.div(
                ui.span(f"{value:.0f}", class_="gbo-ring-value"),
                ui.span(label, class_="gbo-ring-sublabel"),
                class_="gbo-ring-inner",
            ),
            class_=f"gbo-ring {status}" if status else "gbo-ring",
            style=f"--gbo-ring-pct: {pct};",
        )
        cols.append(ui.div(ring, class_="gbo-ring-col"))
    col_width = max(1, 12 // len(specs))
    return ui.layout_columns(*cols, col_widths=[col_width] * len(cols))


def _stacked_bar(segments):
    """segments: list of (label, pct, color), pct 0-100 (need not sum
    to exactly 100 after rounding). Plain CSS flex bar -- same
    zero-image-render approach as bucket_display.py's rings/metric bars,
    no Plotly/kaleido needed for a simple stacked-percentage bar."""
    segments = [(label, pct, color) for label, pct, color in segments if pct]
    if not segments:
        return None
    bar = ui.div(
        *[ui.div(style=f"width:{pct}%; background:{color};", title=f"{label}: {pct:.0f}%") for label, pct, color in segments],
        style="display:flex; height:22px; border-radius:6px; overflow:hidden; width:100%;",
    )
    legend = ui.div(
        *[
            ui.div(
                ui.span(style=f"display:inline-block; width:10px; height:10px; border-radius:5px; background:{color}; margin-right:5px;"),
                f"{label} {pct:.0f}%",
                style="display:inline-flex; align-items:center; font-size:0.8rem; margin:2px 10px 2px 0;",
            )
            for label, pct, color in segments
        ],
        style="display:flex; flex-wrap:wrap; margin-top:6px;",
    )
    return ui.div(bar, legend)


@module.ui
def pitcher_profile_ui():
    return ui.div(
        ui_helpers.page_header("Pitcher Profile"),
        ui.output_ui("pp_player_picker"),
        ui.output_ui("pp_filters"),
        ui.output_ui("pp_body"),
        ui.output_ui("pp_command_section"),
        ui_helpers.page_footer(),
    )


@module.server
def pitcher_profile_server(input, output, session, app_state):

    def _visible_pitchers(db):
        q = db.query(Player).filter(Player.is_pitcher.is_(True))
        if not app_state.can_view_all_players():
            ids = [a.player_id for a in db.query(StaffPlayerAssignment).filter(StaffPlayerAssignment.staff_user_id == app_state.user_id()).all()]
            q = q.filter(Player.player_id.in_(ids))
        return q.filter(Player.active.is_(True)).order_by(Player.last_name, Player.first_name).all()

    def _current_player_id(db):
        if app_state.role_name() == "Player":
            me = _my_player(db, app_state)
            return me.player_id if (me is not None and me.is_pitcher) else None
        if "pp_player_select" not in input or not input.pp_player_select():
            return None
        return int(input.pp_player_select())

    @render.ui
    def pp_player_picker():
        if not app_state.is_authenticated() or app_state.role_name() == "Player":
            return None
        if app_state.role_name() not in STAFF_ROLES:
            return ui.p("You don't have access to this page.", class_="text-danger")
        db = get_session()
        try:
            pitchers = _visible_pitchers(db)
        finally:
            db.close()
        if not pitchers:
            return ui_helpers.empty_state("No pitchers to show yet.")
        choices = {str(p.player_id): f"{p.last_name}, {p.first_name}" + (f"  #{p.jersey_number}" if p.jersey_number else "") for p in pitchers}
        return ui.div(ui.input_select("pp_player_select", "Pitcher", choices=choices, width="320px"), style="margin-bottom:8px;")

    @render.ui
    def pp_filters():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        if role in STAFF_ROLES:
            req("pp_player_select" in input)

        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            arsenal = (
                db.query(PitchType)
                .join(PlayerPitchArsenal, PlayerPitchArsenal.pitch_type_id == PitchType.pitch_type_id)
                .filter(PlayerPitchArsenal.player_id == pid, PlayerPitchArsenal.active.is_(True))
                .order_by(PitchType.display_order)
                .all()
            )
            type_choices = {"__all__": "All Pitches"}
            for t in arsenal:
                type_choices[t.type_name] = t.type_name
        finally:
            db.close()

        return ui.layout_columns(
            ui.input_date("pp_date_from", "From", value=date.today() - timedelta(days=365)),
            ui.input_date("pp_date_to", "To", value=date.today()),
            ui.input_select("pp_pitch_type", "Pitch Type", choices=type_choices),
            ui.input_select("pp_game_scope", "Games", choices={"all": "All Games", "intrasquad": "Intrasquad Only", "external": "External Only"}),
            col_widths=[3, 3, 3, 3],
        )

    def _current_filters():
        req("pp_date_from" in input)
        req("pp_date_to" in input)
        req("pp_pitch_type" in input)
        req("pp_game_scope" in input)
        pitch_type = input.pp_pitch_type()
        return {
            "date_from": input.pp_date_from(),
            "date_to": input.pp_date_to(),
            "pitch_type": None if pitch_type == "__all__" else pitch_type,
            "game_scope": input.pp_game_scope(),
        }

    # -------------------------------------------------------------------
    # Physical Profile -- reused Bullpen Dashboard (register once here,
    # per bullpen_dashboard_display's own "mount once" convention; its
    # returned fragment is embedded inside pp_body below).
    # -------------------------------------------------------------------

    def _get_physical_target(input):
        req("pp_date_from" in input)
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None
            f = _current_filters()
            bullpen_ids = profile_queries.bullpen_ids_for_player(db, pid, f["date_from"], f["date_to"])
            if not bullpen_ids:
                return None
            return {"kind": "combined", "player": player, "bullpen_ids": bullpen_ids}
        finally:
            db.close()

    _physical_fragment = bullpen_dashboard_display.register_bullpen_dashboard(
        input, output, session, "pp_phys", _get_physical_target,
    )

    @render.ui
    def pp_body():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        f = _current_filters()

        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            player = db.query(Player).filter(Player.player_id == pid).first()
            if player is None:
                return None

            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            rapsodo_pitches = profile_queries.get_pitcher_rapsodo_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"], pitch_type=f["pitch_type"],
            )
            if not game_pitches and not rapsodo_pitches:
                return ui_helpers.card(ui_helpers.empty_state(
                    "No pitches in this date range yet. Widen the filters, or check back once games/bullpens are tracked."
                ))

            sections = [ui.h5(f"{player.first_name} {player.last_name}", class_="gbo-section-title")]

            # --- Line (condensed -- full box-score detail already lives
            # on Pitcher Game Report, per-outing; this is the aggregate
            # read across the filtered window) ---
            if game_pitches:
                line = compute_pitching_line(game_pitches)
                sections.append(ui.p(ui.strong("Line")))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "IP", "value": str(line["IP"])},
                    {"label": "Pitches", "value": str(line["Pitches"])},
                    {"label": "K", "value": str(line["K"])},
                    {"label": "BB", "value": str(line["BB"])},
                    {"label": "WHIP", "value": _fmt(line["WHIP"])},
                    {"label": "FIP", "value": _fmt(line["FIP"])},
                ]))
                sections.append(ui_helpers.render_kpi_cards([
                    {"label": "Strike %", "value": _fmt_pct(line["Strike %"])},
                    {"label": "Execution %", "value": _fmt_pct(line["Execution %"])},
                    {"label": "OBA", "value": _fmt(line["OBA (opponent AVG)"], 3)},
                    {"label": "wOBA*", "value": _fmt(line["wOBA"], 3)},
                ]))
                sections.append(ui.p("*wOBA uses generic linear weights, a relative read within your own games, not MLB-exact.", class_="text-muted small"))

            # --- Grading: Stuff+/Location+/Pitching+/Arsenal ---
            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Overview")))
            sections.append(ui.p(
                "Stuff+/Location+/Pitching+: 100 = your own team's average across every graded pitch, 10 points = 1 "
                "standard deviation. Team-relative only -- GBO has no access to league-wide pitch data to compare "
                "against a real MLB Stuff+ number.",
                class_="text-muted small",
            ))

            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            location_baseline = profile_queries.team_location_plus_baseline(db)

            game_pitch_ids = [p.game_pitch_id for p in game_pitches]
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, game_pitch_ids)

            def _type_label(pitch_type_obj):
                return pitch_type_obj.type_name if pitch_type_obj is not None else "Unspecified"

            pitch_type_grades = {}
            individual_rows = []
            trend_points = []
            zone_counts = {"Heart": 0, "Shadow": 0, "Chase": 0, "Waste": 0}
            usage_counts = {}

            for p in game_pitches:
                label = _type_label(p.pitch_type)
                usage_counts[label] = usage_counts.get(label, 0) + 1

                rap = rap_by_gp.get(p.game_pitch_id)
                s_val = stuff_plus(rap, stuff_baselines.get(label, {})) if rap is not None else None
                l_val = location_plus(p, location_baseline)
                pi_val = pitching_plus(s_val, l_val)

                grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
                grp["n"] += 1
                if s_val is not None:
                    grp["stuff_plus"].append(s_val)
                if l_val is not None:
                    grp["location_plus"].append(l_val)
                if pi_val is not None:
                    grp["pitching_plus"].append(pi_val)

                if p.actual_plate_x is not None and p.actual_plate_z is not None:
                    zone = classify_attack_zone(float(p.actual_plate_x), float(p.actual_plate_z))
                    if zone:
                        zone_counts[zone] += 1

                if pi_val is not None and p.game is not None:
                    trend_points.append((p.game.game_date, pi_val))

                individual_rows.append({
                    "Date": p.game.game_date.strftime("%Y-%m-%d") if p.game else "—",
                    "#": p.pitch_sequence,
                    "Pitch Type": label,
                    "Velo": f"{float(rap.velocity):.1f}" if rap is not None and rap.velocity is not None else "—",
                    "Result": p.pitch_outcome or "—",
                    "Stuff+": _fmt_grade(s_val),
                    "Location+": _fmt_grade(l_val),
                    "Pitching+": _fmt_grade(pi_val),
                })

            # Any Rapsodo pitches with no game link at all (pure bullpen
            # reps) still count toward Arsenal's Stuff+ rollup -- they
            # just can't get a Location+/Pitching+ (no game outcome to
            # grade) or a spot in the game-pitch-driven Individual
            # Pitches table above (that table's backbone is GamePitch,
            # since "Result" only exists there -- see module docstring).
            linked_rapsodo_ids = {r.rapsodo_pitch_id for r in rap_by_gp.values()}
            for r in rapsodo_pitches:
                if r.rapsodo_pitch_id in linked_rapsodo_ids:
                    continue
                label = _type_label(r.pitch_type)
                s_val = stuff_plus(r, stuff_baselines.get(label, {}))
                if s_val is None:
                    continue
                grp = pitch_type_grades.setdefault(label, {"n": 0, "stuff_plus": [], "location_plus": [], "pitching_plus": []})
                grp["n"] += 1
                grp["stuff_plus"].append(s_val)

            arsenal_rows = arsenal_summary(pitch_type_grades) if pitch_type_grades else []
            overview_stuff = [v for row in arsenal_rows for v in [row["Stuff+"]] if v is not None]
            overview_loc = [v for row in arsenal_rows for v in [row["Location+"]] if v is not None]
            overview_pitching = [v for row in arsenal_rows for v in [row["Pitching+"]] if v is not None]
            grade_rings = _grade_rings([
                ("Stuff+", round(sum(overview_stuff) / len(overview_stuff), 1) if overview_stuff else None),
                ("Location+", round(sum(overview_loc) / len(overview_loc), 1) if overview_loc else None),
                ("Pitching+", round(sum(overview_pitching) / len(overview_pitching), 1) if overview_pitching else None),
            ])
            if grade_rings is not None:
                sections.append(grade_rings)
            else:
                sections.append(ui.p("No graded pitches yet in this range -- needs Rapsodo-linked pitches (Stuff+) or located game pitches (Location+).", class_="text-muted small"))

            # --- Pitch Usage / Attack Zone bars ---
            total_pitches = sum(usage_counts.values())
            if total_pitches:
                sections.append(ui.p(ui.strong("Pitch Usage"), class_="mt-3"))
                sections.append(_stacked_bar([
                    (label, round(100 * n / total_pitches, 1), get_pitch_color(label))
                    for label, n in sorted(usage_counts.items(), key=lambda kv: -kv[1])
                ]))
            total_located = sum(zone_counts.values())
            if total_located:
                sections.append(ui.p(ui.strong("Attack Zone Distribution"), class_="mt-3"))
                sections.append(ui.p("Heart = down the middle, Shadow = zone edge, Chase = tempting but outside, Waste = nowhere near.", class_="text-muted small"))
                sections.append(_stacked_bar([
                    (zone, round(100 * zone_counts[zone] / total_located, 1), ATTACK_ZONE_COLORS[zone])
                    for zone in ("Heart", "Shadow", "Chase", "Waste")
                ]))

            # --- Trend over time (Pitching+) ---
            if len(trend_points) >= 2:
                trend_points.sort(key=lambda t: t[0])
                fig = profile_charts.trend_chart(trend_points, y_label="Pitching+")
                if fig is not None:
                    sections.append(ui.p(ui.strong("Pitching+ Trend"), class_="mt-3"))
                    sections.append(output_widget("pp_trend_chart"))

            # --- Arsenal ---
            if arsenal_rows:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Arsenal")))
                sections.append(ui.p(
                    f"'Reliable' needs at least {MIN_BASELINE_PITCHES} pitches of that type in this window -- "
                    "fewer than that and the grade swings wildly with every new pitch.",
                    class_="text-muted small",
                ))
                sections.append(ui_helpers.render_dict_table([
                    {
                        "Pitch Type": row["Pitch Type"], "Usage %": _fmt_pct(row["Usage %"]), "Pitches": row["Pitches"],
                        "Stuff+": _fmt_grade(row["Stuff+"]), "Location+": _fmt_grade(row["Location+"]),
                        "Pitching+": _fmt_grade(row["Pitching+"]), "Reliable": "Yes" if row["Reliable"] else "No",
                    }
                    for row in arsenal_rows
                ]))

            # --- Pitch Type Breakdown (existing game_stats.py logic,
            # same vs RHH/vs LHH tab convention as Pitcher Game Report) ---
            if game_pitches:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Pitch Type Breakdown")))
                vs_rhh = [p for p in game_pitches if p.opponent_hand == "R"]
                vs_lhh = [p for p in game_pitches if p.opponent_hand == "L"]
                sections.append(ui.navset_tab(
                    ui.nav_panel("All Batters", ui_helpers.render_dict_table(compute_pitch_type_breakdown(game_pitches))),
                    ui.nav_panel("vs RHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_rhh)) if vs_rhh else ui.p("No pitches vs a right-handed batter in this range.", class_="text-muted small")),
                    ui.nav_panel("vs LHH", ui_helpers.render_dict_table(compute_pitch_type_breakdown(vs_lhh)) if vs_lhh else ui.p("No pitches vs a left-handed batter in this range.", class_="text-muted small")),
                ))

            # --- Individual Pitches ---
            if individual_rows:
                sections.append(ui.hr())
                sections.append(ui.p(ui.strong("Individual Pitches")))
                sections.append(ui_helpers.render_dict_table(list(reversed(individual_rows))))

            # --- Physical Profile (reused Bullpen Dashboard) ---
            sections.append(ui.hr())
            sections.append(ui.p(ui.strong("Physical Profile")))
            sections.append(ui.p("Same Bullpen Dashboard charts used elsewhere in GBO, scoped to this pitcher's bullpen sessions in the selected date range.", class_="text-muted small"))
            sections.append(_physical_fragment)

            return ui.div(*sections)
        finally:
            db.close()

    @render_plotly
    def pp_trend_chart():
        if not app_state.is_authenticated():
            return None
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None
        f = _current_filters()
        db = get_session()
        try:
            pid = _current_player_id(db)
            if pid is None:
                return None
            game_pitches = profile_queries.get_pitcher_profile_pitches(
                db, pid, date_from=f["date_from"], date_to=f["date_to"],
                pitch_type=f["pitch_type"], game_scope=f["game_scope"],
            )
            game_pitch_ids = [p.game_pitch_id for p in game_pitches]
            rap_by_gp = profile_queries.rapsodo_by_game_pitch_id(db, game_pitch_ids)
            stuff_baselines = profile_queries.team_stuff_plus_baselines(db)
            location_baseline = profile_queries.team_location_plus_baseline(db)
            points = []
            for p in game_pitches:
                label = p.pitch_type.type_name if p.pitch_type else "Unspecified"
                rap = rap_by_gp.get(p.game_pitch_id)
                s_val = stuff_plus(rap, stuff_baselines.get(label, {})) if rap is not None else None
                l_val = location_plus(p, location_baseline)
                pi_val = pitching_plus(s_val, l_val)
                if pi_val is not None and p.game is not None:
                    points.append((p.game.game_date, pi_val))
            points.sort(key=lambda t: t[0])
            return profile_charts.trend_chart(points, y_label="Pitching+")
        finally:
            db.close()

    # -------------------------------------------------------------------
    # Command Target Zones -- same code pitcher_game_report.py uses
    # (Command Tracker's own scorecard/table/chart via
    # command_metrics.game_pitches_command_view), scoped by this page's
    # filters instead of a single game_id. Own render.ui/render_plotly
    # split, same reason as pitcher_game_report.py: a render_plotly
    # output needs its own registered function.
    # -------------------------------------------------------------------

    def _view_pitches(db):
        role = app_state.role_name()
        if role != "Player" and role not in STAFF_ROLES:
            return None, None
        pid = _current_player_id(db)
        if pid is None:
            return None, None
        player = db.query(Player).filter(Player.player_id == pid).first()
        if player is None:
            return None, None
        f = _current_filters()
        game_pitches = profile_queries.get_pitcher_profile_pitches(
            db, pid, date_from=f["date_from"], date_to=f["date_to"],
            pitch_type=f["pitch_type"], game_scope=f["game_scope"],
        )
        if not game_pitches:
            return None, None
        return command_metrics.game_pitches_command_view(game_pitches, player.throws), player.throws

    def _team_command_plus_baseline(db):
        """Same all-time, all-games team population Pitcher Game Report's
        Command+ uses (see that module's docstring) -- not scoped to
        this page's own filters, a stable roster-wide reference."""
        from models import GamePitch
        all_pitches = db.query(GamePitch).filter(GamePitch.intended_plate_x.isnot(None)).all()
        view_pitches = command_metrics.game_pitches_command_view(all_pitches, None)
        return command_metrics.team_command_plus_baseline(view_pitches)

    def _cmd_bias_label(bias):
        parts = []
        if bias["horizontal_bias_in"] is not None:
            parts.append(f'{bias["horizontal_bias_in"]:.1f}" {bias["horizontal_bias_label"]}')
        if bias["vertical_bias_in"] is not None:
            parts.append(f'{bias["vertical_bias_in"]:.1f}" {bias["vertical_bias_label"]}')
        return " / ".join(parts) if parts else "—"

    @render.ui
    def pp_command_section():
        if not app_state.is_authenticated():
            return None
        _current_filters()
        db = get_session()
        try:
            view_pitches, _throws = _view_pitches(db)
            if not view_pitches:
                return None
            return ui.div(
                ui.hr(),
                ui.p(ui.strong("Command Target Zones")),
                ui.p(
                    "Same Precision/Command/Competitive target-radius bands and concentric-ring chart Command "
                    "Tracker uses -- built from this window's intended-vs-actual pitch locations. Only pitches with "
                    "a logged intended location count (a real opponent's pitcher never has one on file).",
                    class_="text-muted small",
                ),
                ui.output_ui("pp_command_table"),
                output_widget("pp_command_chart"),
            )
        finally:
            db.close()

    @render.ui
    def pp_command_table():
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            view_pitches, throws = _view_pitches(db)
            if not view_pitches:
                return None
            scorecard = command_metrics.session_command_scorecard(view_pitches)
            if scorecard["located_pitches"] == 0:
                return ui.p("No pitches have an actual location recorded yet -- needs Video Review or a Rapsodo link.", class_="text-muted small")

            baseline_mean, baseline_stdev, baseline_n = _team_command_plus_baseline(db)
            command_plus_value = None
            if baseline_n >= command_metrics.MIN_BASELINE_PITCHES:
                command_plus_value = command_metrics.command_plus(scorecard["avg_danger_adjusted_miss"], baseline_mean, baseline_stdev)

            children = [ui_helpers.render_kpi_cards([
                {"label": "Located / Total", "value": f'{scorecard["located_pitches"]}/{scorecard["total_pitches"]}'},
                {"label": "Command+", "value": _fmt_grade(command_plus_value)},
                {"label": "Avg Miss", "value": f'{scorecard["avg_miss_distance"]}"' if scorecard["avg_miss_distance"] is not None else "—"},
                {"label": "Precision %", "value": _fmt_pct(scorecard["precision_pct"])},
                {"label": "Command Target %", "value": _fmt_pct(scorecard["command_target_pct"])},
                {"label": "Competitive %", "value": _fmt_pct(scorecard["competitive_pct"])},
            ])]
            bias = command_metrics.miss_bias(view_pitches, throws)
            children.append(ui.p(f"Average miss bias: {_cmd_bias_label(bias)}", class_="text-muted small mt-2"))
            return ui.div(*children)
        finally:
            db.close()

    @render_plotly
    def pp_command_chart():
        if not app_state.is_authenticated():
            return None
        db = get_session()
        try:
            view_pitches, _throws = _view_pitches(db)
            if not view_pitches:
                return None
            located = [p for p in view_pitches if p.horizontal_miss is not None]
            if not located:
                return None
            return command_charts.command_chart(view_pitches)
        finally:
            db.close()
