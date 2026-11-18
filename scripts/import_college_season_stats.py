"""
Load researched college seasons (data/college_season_stats.csv) into
college_season_stats -- Nov 2026, College Career on Player Profile.

Matches each row to an active roster player by name (college_career.
match_player, with the few GBO-vs-school spelling differences aliased),
then inserts or updates on (player, side, year, school). A row already in
the table is only overwritten field-by-field where the CSV has a value,
so numbers staff typed in by hand are never blanked out.

Dry run by default. Run after migrations.migrate_college_season_stats:
    python3 -m scripts.import_college_season_stats            # dry run
    python3 -m scripts.import_college_season_stats --apply    # write
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import SessionLocal  # noqa: E402
from models import Player, CollegeSeasonStat  # noqa: E402
import college_career as cc  # noqa: E402

CSV_PATH = os.path.join(ROOT, "data", "college_season_stats.csv")


def run(db, apply=False, path=CSV_PATH):
    players = db.query(Player).all()
    added = updated = 0
    unmatched = []
    for rec in cc.read_csv(path):
        p = cc.match_player(rec["player"], [x for x in players if x.active] or players)
        if p is None:
            unmatched.append(rec["player"])
            continue
        side, year, school, level, vals, src = cc.parse_csv_row(rec)
        row = db.query(CollegeSeasonStat).filter_by(player_id=p.player_id, side=side, season_year=year, school=school).first()
        if row is None:
            db.add(CollegeSeasonStat(player_id=p.player_id, side=side, season_year=year, school=school,
                                     level=level, source_url=src, **vals))
            added += 1
            print(f"  + {p.first_name} {p.last_name}: {year} {school} {side}")
        else:
            changed = False
            for c, v in list(vals.items()) + [("level", level), ("source_url", src)]:
                if v is not None and getattr(row, c) != v:
                    setattr(row, c, v)
                    changed = True
            if changed:
                updated += 1
                print(f"  ~ {p.first_name} {p.last_name}: {year} {school} {side}")
    if apply:
        db.commit()
    else:
        db.rollback()
    print(f"{'Wrote' if apply else 'Would write'}: {added} new, {updated} updated.")
    if unmatched:
        print("No roster match (skipped): " + ", ".join(sorted(set(unmatched))))
    return added, updated, unmatched


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db, apply="--apply" in sys.argv)
    finally:
        db.close()
