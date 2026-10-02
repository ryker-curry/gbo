"""
GBO -- send Monday's weekly progress report emails (Oct 2026).

Builds last week's report (Mon-Sun) for every active pitcher who threw
(any Rapsodo reading or game pitch) and emails a short summary + link to
the full report in GBO. Each send is logged in weekly_report_sends, so
running it twice never double-sends (use --resend to force).

Usage (from the repo root):
    python3 scripts/send_weekly_reports.py --dry-run     # build + save previews, send nothing
    python3 scripts/send_weekly_reports.py               # send last week's
    python3 scripts/send_weekly_reports.py --week 2026-09-28 --only "Holman"

Email settings come from environment variables (set them as Vars on the
Posit Connect content that schedules this -- see weekly_reports_job.ipynb):
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD,
    SMTP_FROM (e.g. "Pitt State Baseball <baseball@...>"), GBO_APP_URL (link in the email)

Recipient = Player.email, else the email on the player's GBO login.
"""

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session  # noqa: E402
from models import Player, User, WeeklyReportNote, WeeklyReportSend  # noqa: E402
from analytics import weekly_report  # noqa: E402
from visualizations.weekly_report_sheet import render_email, email_subject  # noqa: E402


def _recipient(db, player):
    if player.email:
        return player.email.strip()
    u = db.query(User).filter(User.player_id == player.player_id, User.active.is_(True)).first()
    return u.email.strip() if u and u.email else None


def _smtp():
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP_HOST isn't set -- see this script's docstring.")
    port = int(os.environ.get("SMTP_PORT", "587"))
    s = smtplib.SMTP(host, port, timeout=30)
    s.starttls(context=ssl.create_default_context())
    if os.environ.get("SMTP_USER"):
        s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
    return s


def run(week=None, dry_run=False, resend=False, only=None, preview_dir="weekly_report_previews"):
    db = get_session()
    week = week or weekly_report.last_completed_week()
    app_url = os.environ.get("GBO_APP_URL")
    sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")
    smtp = None
    counts = {"sent": 0, "skipped": 0, "no_activity": 0, "no_email": 0, "failed": 0}
    try:
        try:
            from analytics import profile_queries
            stuff = profile_queries.team_stuff_plus_baselines(db)
        except Exception:
            stuff = {}
        pitchers = (db.query(Player).filter(Player.is_pitcher.is_(True), Player.active.is_(True))
                    .order_by(Player.last_name).all())
        for p in pitchers:
            name = f"{p.first_name} {p.last_name}"
            if only and only.lower() not in name.lower():
                continue
            already = db.query(WeeklyReportSend).filter(WeeklyReportSend.player_id == p.player_id,
                                                        WeeklyReportSend.week_start == week).first()
            if already and already.status == "sent" and not resend and not dry_run:
                counts["skipped"] += 1
                continue
            rep = weekly_report.build(db, p.player_id, week, stuff_models=stuff)
            if rep is None or not rep["active"]:
                counts["no_activity"] += 1
                continue
            n = db.query(WeeklyReportNote).filter(WeeklyReportNote.player_id == p.player_id,
                                                  WeeklyReportNote.week_start == week).first()
            html = render_email(rep, n.note if n else None, app_url)
            to = _recipient(db, p)
            if dry_run:
                Path(preview_dir).mkdir(exist_ok=True)
                f = Path(preview_dir) / f"{week.isoformat()}_{p.last_name}_{p.first_name}.html"
                f.write_text(html)
                print(f"[dry run] {name} -> {to or 'NO EMAIL'} : {f}")
                continue
            row = already or WeeklyReportSend(player_id=p.player_id, week_start=week)
            if already is None:
                db.add(row)
            row.email, row.sent_at = to, datetime.utcnow()
            if not to:
                row.status, row.detail = "no_email", "No email on the player or his login."
                counts["no_email"] += 1
                db.commit()
                continue
            try:
                smtp = smtp or _smtp()
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = email_subject(rep), sender, to
                msg.set_content("Your weekly report is ready in GBO: My Development -> My Weekly Report."
                                + (f"\n{app_url}" if app_url else ""))
                msg.add_alternative(html, subtype="html")
                smtp.send_message(msg)
                row.status, row.detail = "sent", None
                counts["sent"] += 1
                print(f"sent: {name} -> {to}")
            except Exception as e:
                row.status, row.detail = "failed", str(e)[:500]
                counts["failed"] += 1
                print(f"FAILED: {name} -> {to}: {e}")
            db.commit()
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                pass
        db.close()
    print(f"Week of {week}: {counts}")
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", help="Monday of the week to send (YYYY-MM-DD). Default: last completed week.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resend", action="store_true")
    ap.add_argument("--only", help="Only pitchers whose name contains this text.")
    a = ap.parse_args()
    wk = datetime.fromisoformat(a.week).date() if a.week else None
    if wk and wk.weekday() != 0:
        wk = weekly_report.week_start_for(wk)
    run(week=wk, dry_run=a.dry_run, resend=a.resend, only=a.only)
