"""
GBO — Migration: add Hitter Tracking (hitter_tracking_sessions, hitter_swings).

Run once, after pulling this update.

Run:
    python migrate_hitter_tracking.py
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    Base.metadata.create_all(bind=engine)
    print("Created hitter_tracking_sessions and hitter_swings tables.")


if __name__ == "__main__":
    main()