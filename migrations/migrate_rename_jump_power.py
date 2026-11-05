"""
GBO -- Migration: rename the "Explosive Power" assessment category to
"Jump Power" (Nov 2026, Ryker: no "explosive" anywhere in the app).

Run once, RIGHT AFTER the Posit Connect redeploy that ships this update
(the new code looks the category up as "Jump Power"; the old code looked
for the old name, so code and database should switch together):
    python3 -m migrations.migrate_rename_jump_power

Safe to re-run: renames only if the old row exists and the new one doesn't.
Only the category's name changes -- its id, tests and every result stay.
"""

from sqlalchemy import text
from database import engine

OLD, NEW = "Explosive Power", "Jump Power"


def main():
    with engine.begin() as conn:
        has_new = conn.execute(text("SELECT 1 FROM assessment_categories WHERE category_name = :n"), {"n": NEW}).first()
        if has_new:
            print(f'"{NEW}" already exists -- nothing to do.')
            return
        res = conn.execute(text("UPDATE assessment_categories SET category_name = :new WHERE category_name = :old"),
                           {"new": NEW, "old": OLD})
    print(f'Renamed "{OLD}" to "{NEW}".' if res.rowcount else f'No "{OLD}" category found -- nothing to do.')


if __name__ == "__main__":
    main()
