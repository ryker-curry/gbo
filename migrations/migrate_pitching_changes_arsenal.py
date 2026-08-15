"""
GBO — Migration: add pitching_changes and player_pitch_arsenal tables.

Phase 1 of the Game Operations expansion (per Ryker's architecture
doc): formal Pitching Change tracking (so the coach doesn't re-select
the pitcher every plate appearance) and PlayerPitchArsenal (filters
the pitch-type dropdown to what a pitcher actually throws).

Run once, after pulling this update.

Run:
    python migrate_pitching_changes_arsenal.py
"""

from database import engine, Base
import models  # noqa: F401 -- registers all model classes with Base


def main():
    Base.metadata.create_all(bind=engine)
    print("Created pitching_changes and player_pitch_arsenal tables.")


if __name__ == "__main__":
    main()