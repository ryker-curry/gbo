"""
GBO — Migration: add Game Tracking (games, game_lineup_slots,
game_pitches).

Phase 1 of Game Tracking: the core live tracking sheet. Advanced
sabermetric stats (Run Expectancy/Run Value, Whiff%/CSW%/Chase%/
Putaway%, splits, etc. -- the Baseball-Savant-style stats page) are a
deliberate follow-up phase, not built yet.

Run once, after pulling this update.

Run:
    python migrate_game_tracking.py
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    Base.metadata.create_all(bind=engine)
    print("Created games, game_lineup_slots, and game_pitches tables.")


if __name__ == "__main__":
    main()