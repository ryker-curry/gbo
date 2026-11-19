"""
GBO -- Migration: game_pitches.location_source (Nov 2026).

Records WHERE a pitch's actual_plate_x/z came from: 'rapsodo',
'smartpark', 'video', or 'manual' (clicked in Game Tracking). Zone
Whiff % uses it to count only the season's tracking system -- Rapsodo
strike-zone location for Fall 2026, SmartPark from spring 2027 on
(strike_zone.ZONE_SOURCE_BY_SEASON, Ryker's call Nov 19 2026).

Backfill: located pitches with a matched Rapsodo reading at the same
spot -> 'rapsodo'; ones made by a SmartPark import -> 'smartpark' (only
if that table exists yet). Anything else located stays NULL (unknown,
not counted). As of Nov 19 2026 all 1,601 located fall pitches are
Rapsodo-linked.

Run once, after pulling this update:
    python3 -m migrations.migrate_location_source
"""

from sqlalchemy import text
from database import engine


def main():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE game_pitches ADD COLUMN IF NOT EXISTS location_source VARCHAR(20)"))
        r = conn.execute(text("""
            UPDATE game_pitches gp SET location_source = 'rapsodo'
            FROM rapsodo_pitches rp
            WHERE rp.game_pitch_id = gp.game_pitch_id
              AND gp.location_source IS NULL
              AND gp.actual_plate_x IS NOT NULL AND gp.actual_plate_z IS NOT NULL
              AND rp.plate_x_ft IS NOT NULL AND rp.plate_z_ft IS NOT NULL
              AND gp.actual_plate_x = rp.plate_x_ft AND gp.actual_plate_z = rp.plate_z_ft
        """))
        print(f"Tagged {r.rowcount} pitch location(s) as Rapsodo.")
        has_sp = conn.execute(text("SELECT to_regclass('public.smartpark_pitches') IS NOT NULL")).scalar()
        if has_sp:
            r = conn.execute(text("""
                UPDATE game_pitches gp SET location_source = 'smartpark'
                FROM smartpark_pitches sp
                WHERE sp.game_pitch_id = gp.game_pitch_id
                  AND gp.location_source IS NULL AND gp.actual_plate_x IS NOT NULL
            """))
            print(f"Tagged {r.rowcount} pitch location(s) as SmartPark.")
        left = conn.execute(text(
            "SELECT count(*) FROM game_pitches WHERE actual_plate_x IS NOT NULL AND location_source IS NULL"
        )).scalar()
        print(f"{left} located pitch(es) left untagged (not counted in Zone Whiff %).")
    print("Migration complete.")


if __name__ == "__main__":
    main()
