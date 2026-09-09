"""
GBO — Migration: rename contact_quality value "Barrel" to
"Barreled/Squared Up" on existing rows.

Sept 2026, Ryker: contact quality went from Barrel/Solid/Weak/Miss to
Barreled/Squared Up/Solid/Jammed/Off the End/Clipped/Miss (see
game_tracking.py's/hitter_tracking.py's CONTACT_QUALITY_OPTIONS). Only
"Barrel" has a clean 1:1 rename to a new label ("Barreled/Squared
Up") -- old "Weak" rows are deliberately left alone rather than
guessed into one of the three new mishit categories (Jammed/Off the
End/Clipped), since there's no way to recover which one actually
applied from the stored data. A "Weak" row just won't match any
current dropdown option going forward; it still displays as-is
wherever a page shows the raw stored string, and it was never counted
by Barrel%/Hard Contact% (that's Barrel+Solid only), so leaving it
alone doesn't change any existing stat.

Without the "Barrel" rename below, every historical Barrel %/Hard
Contact % figure (game_stats.py's compute_batted_ball_profile, the 0-2
and 1-2 count "Barrel" splits in game_stats.py and analytics/
pitcher_game_report.py) would silently drop every pre-Sept-2026 barrel
to zero, since the app code now only checks for "Barreled/Squared Up".

Covers both tables that use this same category list: game_pitches
(live game tracking) and hitter_swings (Hitter Tracking BP/practice
sessions).

Run once, after pulling this update.

Run (from anywhere -- see the sys.path note below):
    python3 migrations/migrate_contact_quality_labels.py

Import path note: run as a bare script, Python puts THIS file's own
directory (migrations/) on sys.path, not the repo root one level up
where database.py actually lives -- fails with "ModuleNotFoundError:
No module named 'database'" (same root cause shiny_app/app.py's own
sys.path note already documents for the app itself). Fixed below the
same way: explicitly add the repo root to sys.path before importing
database, so this runs correctly no matter which directory it's
launched from.
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_THIS_DIR)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from sqlalchemy import text
from database import engine


def main():
    print("Renaming contact_quality 'Barrel' -> 'Barreled/Squared Up' on existing rows...")
    with engine.begin() as conn:
        gp_result = conn.execute(text(
            "UPDATE game_pitches SET contact_quality = 'Barreled/Squared Up' WHERE contact_quality = 'Barrel'"
        ))
        print(f"game_pitches: updated {gp_result.rowcount} row(s).")

        hs_result = conn.execute(text(
            "UPDATE hitter_swings SET contact_quality = 'Barreled/Squared Up' WHERE contact_quality = 'Barrel'"
        ))
        print(f"hitter_swings: updated {hs_result.rowcount} row(s).")

    print("\nMigration complete. Historical Barrel %/Hard Contact % stats are unaffected --")
    print("they're computed from this same relabeled value, same as before.")
    print("Existing 'Weak' rows were left as-is -- see this script's module docstring for why.")


if __name__ == "__main__":
    main()
