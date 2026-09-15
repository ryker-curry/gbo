"""
One-time backfill: lowercase every users.email value in the live DB.

Root cause (Sept 2026, Ryker: reports of login landing on "account not
set up" for some users): Supabase Auth normalizes emails to lowercase
internally, but user_management.py / create_admin_user.py /
create_staff_user.py only .strip()'d the email typed at account
creation -- never .lower()'d it. auth.py's _load_gbo_role looks up
users.email against the (lowercase) email Supabase hands back after a
successful login, so any account created with a capital letter in its
email can never match, even though the Supabase credentials are
correct. That code path is now fixed (auth.py normalizes on read,
user_management.py/create_*_user.py normalize on write) -- this script
is the one-time catch-up for rows that already exist with mixed case.

Also checks for collisions: two existing rows whose emails are
identical once lowercased (e.g. "Bob@x.com" and "bob@x.com" both on
file -- possible pre-fix, since the old duplicate-email check was also
case-sensitive) would violate users.email's UNIQUE constraint once
both are lowercased. Any such pair is reported and left untouched --
resolve those by hand (they're almost certainly the same person
double-entered) before re-running.

Safety: dry run by default -- prints every change it WOULD make
without writing anything. Re-run with --apply once the printed report
looks right.

Usage:
    python3 scripts/backfill_lowercase_user_emails.py            # dry run
    python3 scripts/backfill_lowercase_user_emails.py --apply    # writes changes
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Repo root is this script's parent directory -- add it to sys.path so
# `python3 scripts/backfill_lowercase_user_emails.py` finds database.py/
# models.py at the repo root regardless of the caller's own working
# directory or PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_session
from models import User


def main(apply: bool):
    db = get_session()
    try:
        users = db.query(User).order_by(User.user_id).all()

        # Detect collisions first: two DIFFERENT users whose emails would
        # become identical once lowercased. Skip both members of any such
        # pair -- writing either would hit the UNIQUE constraint (or
        # silently shadow one account behind the other if the constraint
        # somehow didn't catch it), and this needs a human decision, not
        # an automatic one.
        by_lower = defaultdict(list)
        for u in users:
            by_lower[(u.email or "").lower()].append(u)

        collisions = {lower: rows for lower, rows in by_lower.items() if len(rows) > 1}
        if collisions:
            print("COLLISIONS -- these will be SKIPPED, resolve by hand first:")
            for lower, rows in collisions.items():
                print(f"  {lower!r} <- " + ", ".join(f"user_id={u.user_id} email={u.email!r}" for u in rows))
            print()

        changes = []
        for u in users:
            current = u.email or ""
            lowered = current.lower()
            if lowered == current:
                continue  # already lowercase, nothing to do
            if lowered in collisions:
                continue  # would collide, skip (reported above)
            changes.append((u, current, lowered))

        if not changes:
            print("No changes needed -- every non-colliding email is already lowercase.")
            return

        print(f"{'Would update' if not apply else 'Updating'} {len(changes)} row(s):")
        for u, current, lowered in changes:
            print(f"  user_id={u.user_id}  {current!r} -> {lowered!r}")

        if not apply:
            print("\nDry run only -- re-run with --apply to write these changes.")
            return

        for u, _current, lowered in changes:
            u.email = lowered
        db.commit()
        print(f"\nDone -- {len(changes)} row(s) updated.")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run only).")
    args = parser.parse_args()
    main(apply=args.apply)
