"""
GBO -- Team overview block for the staff Dashboard (v2 design system).

Rendered at the top of every staff role's dashboard (modules/dashboard.py),
above the role-specific section Ryker already built. Answers "what needs
my attention today" before any raw counts:

  - KPI row: Priority flags · Needs attention · Assessments (7d) ·
    Bullpens (7d) · Open IDP goals
  - Players needing attention (flag + one-line reason, click -> profile)
  - Today (team events + AT appointments) and Recent activity
  - Team status by bucket (priority / attention / good counts as a
    stacked bar) and Assessment coverage (players tested per bucket
    in the last 60 days)

All flags come from bucket_system.compute_bucket_system -- the same rule
the Roster uses (roster._flag_for) so the two never disagree.
"""

from datetime import date, timedelta

from shiny import ui
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from models import (Assessment, AssessmentCategory, BullpenSession, IDPGoal, IDPStatus,
                    TeamScheduleEvent, ATAppointment, PlayerAssignment)
from bucket_system import compute_bucket_system
from modules.roster import _flag_for
import ui_helpers


_BUCKETS = [("Body comp", "body_comp_score"), ("Power", "power_score"), ("Strength", "strength_score"), ("Speed", "speed_score"), ("Arm capacity", "capacity_score")]
_COVERAGE_CATS = ["Body Composition", "Mobility & ROM", "Arm Health", "Lower Body Strength", "Explosive Power", "Speed"]
_COVERAGE_SHORT = {"Body Composition": "Body", "Mobility & ROM": "ROM", "Arm Health": "Arm", "Lower Body Strength": "Str", "Explosive Power": "Power", "Speed": "Speed"}


def build(db, players, player_ids, ns):
    """ns: the dashboard module's session.ns, used for the click-to-profile
    input id. Returns a ui.div."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    two_weeks = today - timedelta(days=14)

    rows = []
    for p in players:
        try:
            bd = compute_bucket_system(db, p.player_id)
        except Exception:
            bd = None
        flag, why = _flag_for(bd)
        rows.append((p, bd or {}, flag, why))
    n_flag = sum(1 for _, _, f, _ in rows if f == "flag")
    n_watch = sum(1 for _, _, f, _ in rows if f == "watch")

    def _count(model, datecol, lo, hi=None):
        q = db.query(model).filter(model.player_id.in_(player_ids), datecol >= lo)
        if hi is not None:
            q = q.filter(datecol < hi)
        return q.count()
    a_now, a_prev = _count(Assessment, Assessment.assessment_date, week_ago), _count(Assessment, Assessment.assessment_date, two_weeks, week_ago)
    b_now, b_prev = _count(BullpenSession, BullpenSession.session_date, week_ago), _count(BullpenSession, BullpenSession.session_date, two_weeks, week_ago)
    completed = db.query(IDPStatus).filter(IDPStatus.status_name == "Completed").first()
    goals_q = db.query(IDPGoal).filter(IDPGoal.player_id.in_(player_ids))
    if completed:
        goals_q = goals_q.filter(IDPGoal.status_id != completed.status_id)
    open_goals = goals_q.options(joinedload(IDPGoal.player), joinedload(IDPGoal.status)).order_by(IDPGoal.target_date.asc().nullslast()).all()

    kpis = ui.div(
        ui_helpers.kpi_tile("Priority flags", n_flag, status="flag" if n_flag else None, delta="players with a red flag"),
        ui_helpers.kpi_tile("Needs attention", n_watch, status="watch" if n_watch else None, delta="players with an amber flag"),
        ui_helpers.kpi_tile("Assessments · 7 days", a_now, delta=f"{abs(a_now - a_prev)} vs last week", delta_positive=(a_now > a_prev) if a_now != a_prev else None),
        ui_helpers.kpi_tile("Bullpens · 7 days", b_now, delta=f"{abs(b_now - b_prev)} vs last week", delta_positive=(b_now > b_prev) if b_now != b_prev else None),
        ui_helpers.kpi_tile("Open IDP goals", len(open_goals), delta=f"{sum(1 for g in open_goals if g.target_date and g.target_date < today)} past target date"),
        class_="gbo-kpi-row",
    )

    # --- players needing attention ---
    flagged = [r for r in rows if r[2] in ("flag", "watch")]
    flagged.sort(key=lambda r: (0 if r[2] == "flag" else 1, -(r[1].get("total_score") or 0) * -1))
    last_by_player = dict(db.query(Assessment.player_id, func.max(Assessment.assessment_date)).filter(Assessment.player_id.in_(player_ids)).group_by(Assessment.player_id).all())
    if flagged:
        trs = []
        for p, bd, f, why in flagged[:8]:
            pos = p.player_position.position_name if getattr(p, "player_position", None) else "—"
            last = last_by_player.get(p.player_id)
            trs.append(ui.tags.tr(
                ui.tags.td(ui.tags.a(f"{p.first_name} {p.last_name}", href="#", class_="gbo-player-link", **{"data-player-id": str(p.player_id)})),
                ui.tags.td(pos), ui.tags.td(ui_helpers.status_chip(f)), ui.tags.td(why, style="white-space:normal; min-width:200px; max-width:320px;"),
                ui.tags.td(last.strftime("%b %d") if last else "—", class_="text-end", style="font-family:var(--gbo-mono);"),
                ui.tags.td(f"{bd.get('total_score'):.0f}" if bd.get("total_score") is not None else "—", class_="text-end", style="font-family:var(--gbo-mono); color:var(--gbo-text);"),
            ))
        attention_table = ui.div(ui.tags.table(ui.tags.thead(ui.tags.tr(ui.tags.th("Player"), ui.tags.th("Pos"), ui.tags.th("Flag"), ui.tags.th("Why"), ui.tags.th("Last test", class_="text-end"), ui.tags.th("Overall", class_="text-end"))), ui.tags.tbody(*trs), class_="table"), class_="table-responsive")
        if len(flagged) > 8:
            attention_table = ui.div(attention_table, ui.div(f"Showing 8 of {len(flagged)} · open the roster for the full list", class_="gbo-page-sub", style="margin-top:10px; font-size:.78rem;"))
    else:
        attention_table = ui_helpers.empty_state("Nobody is flagged right now. Players appear here when a bucket falls below the team range or the movement flag turns amber or red.")
    attention_card = ui_helpers.card(attention_table, title="Players needing attention", right=ui.tags.a("Full roster", href="#", class_="gbo-goto", **{"data-nav": "Roster"}, style="color:var(--gbo-crimson); font-weight:600;"))

    # --- today + recent activity ---
    events = db.query(TeamScheduleEvent).options(joinedload(TeamScheduleEvent.event_type)).filter(TeamScheduleEvent.scheduled_date == today).order_by(TeamScheduleEvent.title).all()
    appts = db.query(ATAppointment).options(joinedload(ATAppointment.player)).filter(ATAppointment.appointment_date == today, ATAppointment.player_id.in_(player_ids)).order_by(ATAppointment.appointment_time).all()
    assigns = db.query(PlayerAssignment).options(joinedload(PlayerAssignment.player), joinedload(PlayerAssignment.session_type)).filter(PlayerAssignment.scheduled_date == today, PlayerAssignment.player_id.in_(player_ids)).all()
    today_items = []
    for e in events:
        today_items.append(ui.div(ui.div(e.event_type.type_name if e.event_type else "Team", class_="gbo-li-dt"), ui.div(ui.tags.b(e.title), f" — {e.notes}" if e.notes else ""), class_="gbo-li", style="justify-content:flex-start;"))
    for a in appts:
        today_items.append(ui.div(ui.div(a.appointment_time or "AT", class_="gbo-li-dt"), ui.div(ui.tags.b("AT appt"), f" — {a.player.first_name} {a.player.last_name}" if a.player else "", f" · {a.reason}" if a.reason else ""), class_="gbo-li", style="justify-content:flex-start;"))
    if assigns:
        by_type = {}
        for a in assigns:
            by_type.setdefault(a.session_type.type_name if a.session_type else "Assignment", []).append(a.player.last_name if a.player else "?")
        for t, names in by_type.items():
            today_items.append(ui.div(ui.div("Assigned", class_="gbo-li-dt"), ui.div(ui.tags.b(t), " — " + ", ".join(sorted(names)[:6]) + (f" +{len(names)-6}" if len(names) > 6 else "")), class_="gbo-li", style="justify-content:flex-start;"))
    today_card_body = today_items or [ui_helpers.empty_state("Nothing scheduled today. Team events come from Team schedule; player work from Assignments.")]

    recent = db.query(Assessment).options(joinedload(Assessment.player), joinedload(Assessment.category)).filter(Assessment.player_id.in_(player_ids)).order_by(Assessment.assessment_date.desc(), Assessment.created_at.desc()).limit(40).all()
    grouped = {}
    for a in recent:
        key = (a.assessment_date, a.category.category_name if a.category else "Assessment")
        grouped.setdefault(key, set()).add(a.player.last_name if a.player else "?")
    activity = []
    for (d, cat), names in list(grouped.items())[:5]:
        names = sorted(names)
        activity.append(ui.div(ui.div(d.strftime("%b %d"), class_="gbo-li-dt"), ui.div(ui.tags.b(cat), " — " + ", ".join(names[:4]) + (f" +{len(names)-4}" if len(names) > 4 else "")), class_="gbo-li", style="justify-content:flex-start;"))
    pens = db.query(BullpenSession).options(joinedload(BullpenSession.player), joinedload(BullpenSession.rapsodo_pitches)).filter(BullpenSession.player_id.in_(player_ids)).order_by(BullpenSession.session_date.desc()).limit(3).all()
    for b in pens:
        activity.append(ui.div(ui.div(b.session_date.strftime("%b %d"), class_="gbo-li-dt"), ui.div(ui.tags.b(f"{b.player.first_name} {b.player.last_name}" if b.player else "Bullpen"), f" bullpen — {len(b.rapsodo_pitches or [])} pitches"), class_="gbo-li", style="justify-content:flex-start;"))
    side_card = ui_helpers.card(
        ui.div(*today_card_body),
        ui.div("Recent activity", class_="gbo-section-title", style="margin:18px 0 6px;"),
        ui.div(*(activity or [ui_helpers.empty_state("No activity yet.")])),
        title="Today", right=today.strftime("%a, %b %d"),
    )

    # --- team status by bucket ---
    bucket_rows = []
    for label, key in _BUCKETS:
        vals = [bd.get(key) for _, bd, _, _ in rows if bd.get(key) is not None]
        if not vals:
            continue
        nf = sum(1 for v in vals if v < 35); nw = sum(1 for v in vals if 35 <= v < 60); ng = len(vals) - nf - nw
        tot = len(vals)
        seg = lambda n, var: ui.div(style=f"width:{100*n/tot:.1f}%; background:var(--{var});") if n else None
        bucket_rows.append(ui.div(
            ui.div(ui.span(label, class_="gbo-metric-bar-name"), ui.span(f"{nf} ", ui.span("priority", class_="unit"), class_="gbo-metric-bar-raw", style="color:var(--gbo-status-flag);" if nf else ""), class_="gbo-metric-bar-header"),
            ui.div(seg(nf, "gbo-status-flag"), seg(nw, "gbo-status-watch"), seg(ng, "gbo-status-good"), class_="gbo-stack-bar"),
            ui.div(f"{nf} · {nw} · {ng} of {tot} tested", class_="gbo-metric-bar-percentile"),
            class_="gbo-metric-bar-row",
        ))
    bucket_card = ui_helpers.card(ui.div(*(bucket_rows or [ui_helpers.empty_state("No scored assessments yet.")]), class_="gbo-metric-bar-group"), title="Team status by bucket", right="priority · attention · good")

    # --- coverage chart (last 60 days) ---
    since = today - timedelta(days=60)
    cov = dict(db.query(AssessmentCategory.category_name, func.count(func.distinct(Assessment.player_id))).join(Assessment, Assessment.category_id == AssessmentCategory.category_id).filter(Assessment.player_id.in_(player_ids), Assessment.assessment_date >= since).group_by(AssessmentCategory.category_name).all())
    n_players = max(1, len(players))
    bars = []
    worst = None
    for cat in _COVERAGE_CATS:
        n = cov.get(cat, 0); pct = 100 * n / n_players
        st = "good" if pct >= 75 else "watch" if pct >= 40 else "flag"
        if worst is None or n < worst[1]:
            worst = (cat, n)
        bars.append(ui.div(ui.div(str(n), class_="gbo-col-val"), ui.div(ui.div(class_=st, style=f"height:{max(3, pct):.0f}%;"), class_="gbo-col-track"), ui.div(_COVERAGE_SHORT[cat], class_="gbo-col-lab"), class_="gbo-col"))
    cov_caption = f"Players tested per bucket. {_COVERAGE_SHORT.get(worst[0], worst[0])} is {n_players - worst[1]} players behind." if worst else ""
    coverage_card = ui_helpers.card(ui.div(*bars, class_="gbo-cols"), ui.div(cov_caption, class_="gbo-page-sub", style="font-size:.78rem; margin-top:8px;"), title="Assessment coverage", right="last 60 days")

    # --- open goals ---
    goal_items = []
    for g in open_goals[:5]:
        st = "flag" if (g.target_date and g.target_date < today) else "neutral"
        goal_items.append(ui.div(ui.div(ui.tags.b(f"{g.player.last_name}" if g.player else "—"), f" — {g.description[:60]}", ui.span(f" · due {g.target_date.strftime('%b %d')}" if g.target_date else "", style="color:var(--gbo-text-muted);")), ui_helpers.status_chip(st, "Overdue" if st == "flag" else (g.status.status_name if g.status else "Open")), class_="gbo-li"))
    goals_card = ui_helpers.card(*(goal_items or [ui_helpers.empty_state("No open development goals. Create them from the IDP page.")]), title="Open development goals", right=f"{len(open_goals)} open")

    js = ui.tags.script(f"""
    (function(){{
      var root = document.getElementById('{ns("body")}'); if (!root || root.__gboOv) return; root.__gboOv = true;
      root.addEventListener('click', function(e){{
        var a = e.target.closest ? e.target.closest('.gbo-player-link') : null;
        if (a) {{ e.preventDefault(); Shiny.setInputValue('{ns("open_player")}', parseInt(a.getAttribute('data-player-id')), {{priority:'event'}}); return; }}
        var n = e.target.closest ? e.target.closest('.gbo-goto') : null;
        if (n) {{ e.preventDefault(); Shiny.setInputValue('sidebar_go', n.getAttribute('data-nav'), {{priority:'event'}}); }}
      }});
    }})();""")

    return ui.div(
        kpis,
        ui.div(attention_card, side_card, class_="gbo-grid gbo-grid-21", style="margin-bottom:20px;"),
        ui.div(bucket_card, coverage_card, goals_card, class_="gbo-grid gbo-grid-3", style="margin-bottom:24px;"),
        js,
    )
