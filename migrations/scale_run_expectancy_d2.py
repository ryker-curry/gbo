"""
GBO -- Migration: put the run-expectancy table on the D2 run environment
(Oct 2026 stat audit, Ryker approved).

The run_expectancy table was MLB-scale: 0 outs, bases empty, 0-0 = 0.51
runs, while 2026 D2 teams score about 0.80 runs per inning (ERA 6.73 plus
unearned runs). The ORDER of situations was right, so grades barely move,
but every run value / Total RV read about a third too small.

This multiplies every run_expectancy value by TARGET_START_RE / current
start-of-inning value, then rescales the re_before / re_after already
stored on game_pitches and recomputes their run_value
(= re_after + runs scored - re_before). Safe to run twice: it does nothing
if the start-of-inning value is already at the target.

    python3 -m migrations.scale_run_expectancy_d2            # apply
    python3 -m migrations.scale_run_expectancy_d2 --dry-run  # just print the factor
"""

import sys

from sqlalchemy import text
from database import engine

TARGET_START_RE = 0.80   # 2026 D2 runs per inning (start of inning, 0 outs, empty, 0-0)


def main(dry_run=False):
    with engine.begin() as conn:
        cur = conn.execute(text(
            "SELECT re_value FROM run_expectancy WHERE outs = 0 AND bases = '000' AND count = '0-0'")).scalar()
        if cur is None:
            print("No start-of-inning row in run_expectancy -- nothing to do.")
            return
        cur = float(cur)
        if abs(cur - TARGET_START_RE) < 0.02:
            print(f"Already on the D2 scale (start-of-inning RE = {cur:.3f}). Nothing to do.")
            return
        factor = TARGET_START_RE / cur
        print(f"Start-of-inning RE {cur:.3f} -> {TARGET_START_RE:.3f}  (x{factor:.3f})")
        if dry_run:
            return
        conn.execute(text("UPDATE run_expectancy SET re_value = ROUND(CAST(re_value * :f AS numeric), 3)"), {"f": factor})
        conn.execute(text("""
            UPDATE game_pitches
               SET re_before = ROUND(CAST(re_before * :f AS numeric), 3),
                   re_after  = ROUND(CAST(re_after  * :f AS numeric), 3)
             WHERE re_before IS NOT NULL OR re_after IS NOT NULL
        """), {"f": factor})
        conn.execute(text("""
            UPDATE game_pitches
               SET run_value = ROUND(CAST(re_after + COALESCE(runs_scored_on_play, 0) - re_before AS numeric), 3)
             WHERE re_before IS NOT NULL AND re_after IS NOT NULL
        """))
    print("Done. Run values are now in D2 runs.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
