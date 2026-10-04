"""
GBO -- email the Team Game Report to every coach after each game (Oct 2026).

Ryker: head coach + pitching and hitting coaches get a game report for the
whole team after each game. Run HOURLY on Posit Connect
(team_reports_job.ipynb): finds games marked Final in the last few days
that haven't been sent yet and emails each active Head Coach / Coach.
Logged in team_report_sends (python3 -m migrations.migrate_team_report_sends)
so nothing is sent twice.

Same SMTP env vars as the weekly reports: SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM, GBO_APP_URL.

    python3 scripts/send_team_game_reports.py --dry-run     # write previews, send nothing
    python3 scripts/send_team_game_reports.py --game 42     # one game (even if already sent, with --resend)
"""

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import joinedload  # noqa: E402

from database import get_session  # noqa: E402
from models import Game, GamePitch, User, Role, TeamReportSend  # noqa: E402
from analytics import team_report  # noqa: E402
from visualizations.team_report_email import render_email, subject  # noqa: E402
from scripts.send_weekly_reports import _smtp  # noqa: E402

COACH_ROLES = ("Head Coach", "Coach")
LOOKBACK_DAYS = 3


def coaches(db):
    return (db.query(User).join(Role, User.role_id == Role.role_id)
            .filter(Role.role_name.in_(COACH_ROLES), User.active.is_(True)).all())


def run(game_id=None, dry_run=False, resend=False, preview_dir="team_report_previews"):
    db = get_session()
    app_url = os.environ.get("GBO_APP_URL")
    sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")
    smtp = None
    counts = {"sent": 0, "skipped": 0, "failed": 0, "games": 0}
    try:
        q = db.query(Game).options(joinedload(Game.opponent_team))
        if game_id is not None:
            q = q.filter(Game.game_id == game_id)
        else:
            q = q.filter(Game.status == "Final", Game.game_date >= date.today() - timedelta(days=LOOKBACK_DAYS))
        games = [g for g in q.all() if db.query(GamePitch.game_pitch_id).filter(GamePitch.game_id == g.game_id).first()]
        staff = coaches(db)
        for g in games:
            sent = {s.user_id: s for s in db.query(TeamReportSend).filter(TeamReportSend.game_id == g.game_id)}
            todo = [u for u in staff if resend or dry_run or (u.user_id not in sent or sent[u.user_id].status != "sent")]
            if not todo:
                counts["skipped"] += 1
                continue
            counts["games"] += 1
            rep = team_report.build(db, [g])
            html = render_email(rep, g, app_url)
            subj = subject(g)
            if dry_run:
                Path(preview_dir).mkdir(exist_ok=True)
                f = Path(preview_dir) / f"game_{g.game_id}.html"
                f.write_text(html)
                print(f"[dry run] {subj} -> {', '.join(u.email for u in todo)} : {f}")
                continue
            for u in todo:
                row = sent.get(u.user_id) or TeamReportSend(game_id=g.game_id, user_id=u.user_id)
                if u.user_id not in sent:
                    db.add(row)
                row.email, row.sent_at = u.email, datetime.utcnow()
                try:
                    smtp = smtp or _smtp()
                    msg = EmailMessage()
                    msg["Subject"], msg["From"], msg["To"] = subj, sender, u.email
                    msg.set_content("The team game report is ready in GBO: Analytics -> Team Game Report."
                                    + (f"\n{app_url}" if app_url else ""))
                    msg.add_alternative(html, subtype="html")
                    smtp.send_message(msg)
                    row.status, row.detail = "sent", None
                    counts["sent"] += 1
                    print(f"sent: {subj} -> {u.email}")
                except Exception as e:
                    row.status, row.detail = "failed", str(e)[:500]
                    counts["failed"] += 1
                    print(f"FAILED: {u.email}: {e}")
                db.commit()
    finally:
        if smtp:
            try:
                smtp.quit()
            except Exception:
                pass
        db.close()
    print(counts)
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--resend", action="store_true")
    a = ap.parse_args()
    run(game_id=a.game, dry_run=a.dry_run, resend=a.resend)
