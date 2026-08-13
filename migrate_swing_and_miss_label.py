"""
GBO — Migration: rename pitch_outcome value "Swinging Strike" to
"Swing and Miss".

Pure relabeling, per Ryker's preference -- no change to what the value
means. Updates every existing GamePitch row that says "Swinging
Strike" so historical games stay consistent with the app's new
comparison sets (WHIFF_OUTCOMES, SWING_OUTCOMES, CSW_OUTCOMES,
DOMINANT_OUTCOMES, STRIKE_OUTCOMES, etc.) -- without this, old whiffs
would silently stop counting toward Whiff%/CSW%/Dominant% once the app
code only checks for the new label.

Run once, after pulling this update.

Run:
    python migrate_swing_and_miss_label.py
"""

from sqlalchemy import text
from database import engine


def main():
    print("Renaming pitch_outcome 'Swinging Strike' -> 'Swing and Miss' on existing pitches...")
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE game_pitches SET pitch_outcome = 'Swing and Miss' WHERE pitch_outcome = 'Swinging Strike'"
        ))
        print(f"Updated {result.rowcount} row(s).")

    print("\nMigration complete. Historical Whiff%/CSW%/Dominant Pitch stats are unaffected --")
    print("they're computed from this same relabeled value, same as before.")


if __name__ == "__main__":
    main()
