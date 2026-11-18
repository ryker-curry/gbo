"""
GBO -- daily error summary email (Oct 2026, error_log.py). Run every
morning on Posit Connect (error_summary_job.ipynb): emails yesterday's app
errors, grouped by bug, to GBO_ALERT_EMAIL (Ryker). No email on a clean day.

Needs: python3 -m migrations.migrate_app_errors, plus the weekly reports'
SMTP_* env vars.

    python3 scripts/send_error_summary.py              # yesterday (UTC)
    python3 scripts/send_error_summary.py --dry-run    # print, send nothing
    python3 scripts/send_error_summary.py --date 2026-10-03
"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session  # noqa: E402
from models import AppError  # noqa: E402
import error_log  # noqa: E402


def errors_on(db, day):
    start = datetime.combine(day, datetime.min.time())
    return (db.query(AppError).filter(AppError.created_at >= start, AppError.created_at < start + timedelta(days=1))
            .order_by(AppError.created_at).all())


def run(day=None, dry_run=False):
    day = day or (datetime.utcnow().date() - timedelta(days=1))
    db = get_session()
    try:
        rows = errors_on(db, day)
        if not rows:
            print(f"No errors on {day} -- nothing sent.")
            return 0
        msg = error_log.summary_email(rows, day)
        if dry_run:
            print(msg)
        else:
            error_log._send(msg)
            print(f"Sent {len(rows)} errors for {day} to {error_log.alert_email()}.")
        return len(rows)
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.date, a.dry_run)
